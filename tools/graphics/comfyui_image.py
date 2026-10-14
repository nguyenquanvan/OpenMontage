"""ComfyUI image generation via a local or remote ComfyUI server.

Bundled workflows, chosen by what the server actually has:
- FLUX 2 Dev (NVFP4) with the Mistral text encoder, when its three files are installed;
- otherwise FLUX.1 schnell GGUF (ComfyUI-GGUF custom node), which fits 8 GB cards.
Supports custom workflows via the ``workflow_json`` input.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from tools.base_tool import (
    BaseTool,
    Determinism,
    ExecutionMode,
    ResourceProfile,
    RetryPolicy,
    ToolResult,
    ToolRuntime,
    ToolStability,
    ToolStatus,
    ToolTier,
)
from tools._comfyui.client import ComfyUIClient, ComfyUIError
from tools._comfyui.metadata import (
    BUNDLED_MODEL_STACKS,
    COMFYUI_SETUP_OFFER,
    missing_models_payload,
    model_stack,
    workflow_hash,
)

_WORKFLOWS = Path(__file__).resolve().parent.parent / "_comfyui" / "workflows"

# Models required by the bundled flux2-txt2img workflow
_REQUIRED_MODELS = [
    "flux2-dev-nvfp4.safetensors",
    "mistral_3_small_flux2_fp4_mixed.safetensors",
    "flux2-vae.safetensors",
]
_FLUX2 = "flux2-txt2img"
_SCHNELL = "flux1-schnell-gguf-txt2img"
# schnell is distilled for 1-4 steps; more only costs time.
_SCHNELL_DEFAULT_STEPS = 4
_SCHNELL_MAX_STEPS = 8
_LICENSES = {
    _FLUX2: {
        "name": "FLUX.2 [dev] Non-Commercial License",
        "commercial_use": False,
        "url": "https://huggingface.co/black-forest-labs/FLUX.2-dev",
    },
    _SCHNELL: {
        "name": "Apache-2.0 (FLUX.1 [schnell])",
        "commercial_use": True,
        "url": "https://huggingface.co/black-forest-labs/FLUX.1-schnell",
    },
}


def _first(names: list[str], *needles: str, suffix: str = "") -> str | None:
    for name in names:
        lowered = name.lower()
        if all(needle in lowered for needle in needles) and lowered.endswith(suffix):
            return name
    return None


def _schnell_models(models: dict[str, list[str]]) -> dict[str, str] | None:
    """Pick the FLUX.1 schnell GGUF stack from a ComfyUI model listing, or None if incomplete."""
    clips = models.get("clip_gguf", [])
    vaes = models.get("vae", [])
    picked = {
        "unet_name": _first(models.get("unet_gguf", []), "schnell", suffix=".gguf"),
        "clip_name1": _first(clips, "t5", suffix=".gguf") or _first(clips, "t5"),
        "clip_name2": _first(clips, "clip_l"),
        # FLUX.1 uses ae.safetensors; flux2-vae is a different latent space.
        "vae_name": "ae.safetensors" if "ae.safetensors" in vaes else _first(vaes, "flux1", "ae"),
    }
    return picked if all(picked.values()) else None


class ComfyUIImage(BaseTool):
    name = "comfyui_image"
    version = "0.1.0"
    tier = ToolTier.GENERATE
    capability = "image_generation"
    provider = "comfyui"
    stability = ToolStability.EXPERIMENTAL
    execution_mode = ExecutionMode.SYNC
    determinism = Determinism.SEEDED
    runtime = ToolRuntime.LOCAL_GPU

    dependencies = []  # checked at runtime via server health
    setup_offer = COMFYUI_SETUP_OFFER
    install_instructions = (
        "Start a ComfyUI server and set COMFYUI_SERVER_URL "
        "(default http://127.0.0.1:8188).\n"
        "See https://github.com/comfyanonymous/ComfyUI for setup.\n"
        "Running a separate ComfyUI instance for images? Set COMFYUI_IMAGE_SERVER_URL "
        "instead -- it takes priority over COMFYUI_SERVER_URL for this tool only."
    )
    agent_skills = ["comfyui", "flux-best-practices"]

    capabilities = ["text_to_image"]
    supports = {
        "seed": True,
        "custom_size": True,
        "custom_workflow": True,
        "custom_output_node": True,
        "offline": True,
    }
    best_for = [
        "local GPU generation without API costs",
        "8 GB cards through FLUX.1 schnell GGUF (about 10-16 s an image on an RTX 3070)",
        "Blackwell / DGX Spark hardware where diffusers is unsupported",
        "full control over sampling via custom ComfyUI workflows",
    ]
    not_good_for = [
        "setups without a running ComfyUI server",
        "CPU-only machines",
    ]
    fallback = "flux_image"
    fallback_tools = ["flux_image", "local_diffusion", "openai_image"]

    input_schema = {
        "type": "object",
        "anyOf": [{"required": ["prompt"]}, {"required": ["batch"]}],
        "properties": {
            "prompt": {"type": "string", "description": "Text prompt for image generation"},
            "batch": {
                "type": "array",
                "description": (
                    "Many images in one call, e.g. every scene of a chapter. Each item needs prompt "
                    "and output_path and may set seed, width, height; top-level width, height and "
                    "steps apply to items that omit them. Keep a call to about 25 images so it ends "
                    "within agent command timeouts."
                ),
                "items": {
                    "type": "object",
                    "required": ["prompt", "output_path"],
                    "properties": {
                        "prompt": {"type": "string"},
                        "output_path": {"type": "string"},
                        "seed": {"type": "integer"},
                        "width": {"type": "integer"},
                        "height": {"type": "integer"},
                    },
                },
            },
            "width": {"type": "integer", "default": 1024},
            "height": {"type": "integer", "default": 1024},
            "steps": {"type": "integer", "default": 20},
            "guidance": {"type": "number", "default": 3.5},
            "seed": {"type": "integer", "description": "Random if omitted"},
            "output_path": {"type": "string", "description": "Where to save the image"},
            "workflow_json": {
                "type": "string",
                "description": "Optional full ComfyUI workflow JSON. Requires output_node.",
            },
            "workflow_path": {
                "type": "string",
                "description": "Optional path to a ComfyUI workflow JSON file. Requires output_node.",
            },
            "output_node": {
                "type": "string",
                "description": "ComfyUI output node ID for custom workflow_json/workflow_path.",
            },
            "workflow_name": {
                "type": "string",
                "description": "Optional human-readable provenance label for a custom workflow.",
            },
            "workflow_model": {
                "type": "string",
                "description": "Optional model/provenance label for a custom workflow.",
            },
            "workflow_model_stack": {
                "type": "array",
                "description": (
                    "Optional provenance metadata for custom workflow dependencies. "
                    "Items should include name, role, quantization, and LoRA strengths when known."
                ),
                "items": {"type": "object"},
            },
        },
    }

    resource_profile = ResourceProfile(
        cpu_cores=2, ram_mb=8000, vram_mb=8000, disk_mb=500, network_required=False,
    )
    retry_policy = RetryPolicy(max_retries=1, retryable_errors=["timeout"])
    idempotency_key_fields = ["prompt", "width", "height", "steps", "seed"]
    side_effects = ["writes image file to output_path"]
    user_visible_verification = ["Inspect generated image for quality and prompt adherence"]

    def __init__(self) -> None:
        self._client = ComfyUIClient(capability="image")

    def _select_stack(self) -> tuple[str | None, dict[str, str] | None, list[str]]:
        """Return (workflow key, schnell model names, FLUX.2 files missing) for this server.

        While the server is down, the files of the install the app can start stand in for its listing.
        """
        if self._client.is_available():
            models = self._client.list_models()
        else:
            root = self._client.startable_root()
            if root is None:
                return None, None, list(_REQUIRED_MODELS)
            from backlot import comfyui_runtime

            models = comfyui_runtime.offline_models(root)
        available = {name for names in models.values() for name in names}
        missing = [name for name in _REQUIRED_MODELS if name not in available]
        if not missing:
            return _FLUX2, None, []
        schnell = _schnell_models(models)
        if schnell:
            return _SCHNELL, schnell, []
        return None, None, missing

    def get_status(self) -> ToolStatus:
        if not self._client.is_available() and self._client.startable_root() is None:
            return ToolStatus.UNAVAILABLE
        stack, _, _ = self._select_stack()
        return ToolStatus.AVAILABLE if stack else ToolStatus.DEGRADED

    def estimate_cost(self, inputs: dict[str, Any]) -> float:
        return 0.0

    def estimate_runtime(self, inputs: dict[str, Any]) -> float:
        return float(inputs.get("steps", 20)) * 1.5

    def get_info(self) -> dict[str, Any]:
        info = super().get_info()
        info["setup_offer"] = self.setup_offer
        info["bundled_model_stack"] = BUNDLED_MODEL_STACKS[_FLUX2]
        info["bundled_model_stacks"] = {key: BUNDLED_MODEL_STACKS[key] for key in (_FLUX2, _SCHNELL)}
        info["workflow_licenses"] = _LICENSES
        if info["status"] == ToolStatus.AVAILABLE.value:
            stack, schnell, _ = self._select_stack()
            info["active_workflow"] = stack
            info["active_models"] = schnell
            info["license"] = _LICENSES.get(stack)
        return info

    def execute(self, inputs: dict[str, Any]) -> ToolResult:
        if inputs.get("batch"):
            return self._execute_batch(inputs)
        custom_workflow = bool(inputs.get("workflow_json") or inputs.get("workflow_path"))
        if custom_workflow and not inputs.get("output_node"):
            return ToolResult(
                success=False,
                error=(
                    "Custom ComfyUI workflows require output_node so OpenMontage "
                    "knows which ComfyUI node to download artifacts from."
                ),
            )

        if not self._client.ensure_available():
            return ToolResult(
                success=False,
                error=self._unavailable_reason(),
            )

        stack, schnell = None, None
        if not custom_workflow:
            stack, schnell, missing = self._select_stack()
            if stack is None:
                payload = missing_models_payload(
                    missing,
                    workflow_key=_FLUX2,
                    workflow_name=f"{_FLUX2}.json",
                )
                payload["alternative_stack"] = BUNDLED_MODEL_STACKS[_SCHNELL]
                return ToolResult(
                    success=False,
                    data=payload,
                    error=(
                        f"ComfyUI server is running but missing required models: "
                        f"{', '.join(missing)}.\n"
                        f"Alternatively install the FLUX.1 schnell GGUF stack (data.alternative_stack), "
                        f"which fits 8 GB cards.\n"
                        f"See data.missing_models for destination hints and download URLs."
                    ),
                )

        start = time.time()
        seed = inputs.get("seed") or ComfyUIClient.random_seed()
        width = inputs.get("width", 1024)
        height = inputs.get("height", 1024)
        steps = inputs.get("steps", 20)
        guidance = inputs.get("guidance", 3.5)
        output_path = Path(inputs.get("output_path", f"comfyui_image_{seed}.png"))

        try:
            if custom_workflow:
                workflow = self._load_custom_workflow(inputs)
                output_node = str(inputs["output_node"])
            elif stack == _SCHNELL:
                steps = min(int(inputs.get("steps") or _SCHNELL_DEFAULT_STEPS), _SCHNELL_MAX_STEPS)
                guidance = None
                workflow = ComfyUIClient.load_workflow(_WORKFLOWS / f"{_SCHNELL}.json")
                workflow = ComfyUIClient.patch_workflow(workflow, {
                    "1": {"unet_name": schnell["unet_name"]},
                    "2": {"clip_name1": schnell["clip_name1"], "clip_name2": schnell["clip_name2"]},
                    "3": {"vae_name": schnell["vae_name"]},
                    "4": {"text": inputs["prompt"]},
                    "6": {"width": width, "height": height, "batch_size": 1},
                    "7": {"seed": seed, "steps": steps},
                    "9": {"filename_prefix": output_path.stem},
                })
                output_node = "9"
            else:
                workflow = ComfyUIClient.load_workflow(_WORKFLOWS / f"{_FLUX2}.json")
                workflow = ComfyUIClient.patch_workflow(workflow, {
                    "4": {"text": inputs["prompt"]},
                    "5": {"guidance": guidance},
                    "6": {"width": width, "height": height, "batch_size": 1},
                    "7": {"noise_seed": seed},
                    "10": {"steps": steps, "width": width, "height": height},
                    "13": {"filename_prefix": output_path.stem},
                })
                output_node = "13"

            provenance = self._workflow_provenance(
                inputs, custom_workflow, output_node, workflow, stack, schnell
            )
            # A schnell image takes ~16 s, so the default 5 s REST poll (used when
            # websocket-client is absent, as in the packaged app) added ~4 s each.
            paths = self._client.generate(
                workflow, output_node=output_node, dest=output_path, timeout=600, interval=1,
            )

        except ComfyUIError as exc:
            return ToolResult(success=False, error=str(exc))
        except Exception as exc:
            return ToolResult(success=False, error=f"ComfyUI image generation failed: {exc}")

        model_name = self._model_name(inputs, custom_workflow, schnell)
        return ToolResult(
            success=True,
            data={
                "provider": "comfyui",
                "model": model_name,
                "prompt": inputs["prompt"],
                "width": width,
                "height": height,
                "steps": steps,
                "guidance": guidance,
                "output": str(paths[0]),
                "format": "png",
                "workflow_provenance": provenance,
                "license": _LICENSES.get(stack),
            },
            artifacts=[str(p) for p in paths],
            cost_usd=0.0,
            duration_seconds=round(time.time() - start, 2),
            seed=seed,
            model=model_name,
        )

    def _execute_batch(self, inputs: dict[str, Any]) -> ToolResult:
        """Generate every item in one process: one agent call instead of one per image."""
        shared = {key: value for key, value in inputs.items() if key not in {"batch", "prompt", "output_path", "seed"}}
        start = time.time()
        results: list[dict[str, Any]] = []
        artifacts: list[str] = []
        for item in inputs["batch"]:
            result = self.execute({**shared, **item})
            entry: dict[str, Any] = {"output_path": item.get("output_path"), "success": result.success, "seed": result.seed}
            if result.success:
                artifacts.extend(result.artifacts)
                entry["data"] = result.data
            else:
                entry["error"] = result.error
            results.append(entry)
        failed = sum(1 for entry in results if not entry["success"])
        return ToolResult(
            success=failed == 0,
            data={"provider": "comfyui", "count": len(results), "failed": failed, "results": results},
            artifacts=artifacts,
            error=f"{failed}/{len(results)} images failed; see data.results" if failed else None,
            cost_usd=0.0,
            duration_seconds=round(time.time() - start, 2),
        )

    def _unavailable_reason(self) -> str:
        from backlot import comfyui_runtime

        started = comfyui_runtime.last_error()
        return f"{self._client.unavailable_reason()}\n{started}" if started else self._client.unavailable_reason()

    @staticmethod
    def _load_custom_workflow(inputs: dict[str, Any]) -> dict:
        if inputs.get("workflow_json"):
            return json.loads(inputs["workflow_json"])
        return ComfyUIClient.load_workflow(Path(inputs["workflow_path"]))

    @staticmethod
    def _model_name(inputs: dict[str, Any], custom_workflow: bool, schnell: dict[str, str] | None = None) -> str:
        if not custom_workflow:
            return schnell["unet_name"] if schnell else "flux2-dev-nvfp4"
        return (
            inputs.get("workflow_model")
            or inputs.get("model")
            or inputs.get("workflow_name")
            or "custom-comfyui-workflow"
        )

    @staticmethod
    def _workflow_provenance(
        inputs: dict[str, Any],
        custom_workflow: bool,
        output_node: str,
        workflow: dict[str, Any],
        stack: str | None = _FLUX2,
        schnell: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        if not custom_workflow:
            stack = stack or _FLUX2
            models = model_stack(stack, inputs)
            if schnell:
                # Record the files the server really has (quantisation can differ from the default).
                by_role = {"diffusion_model": "unet_name", "text_encoder": "clip_name1", "clip": "clip_name2", "vae": "vae_name"}
                for item in models:
                    if item.get("role") in by_role:
                        item["name"] = schnell[by_role[item["role"]]]
            return {
                "source": "bundled",
                "workflow": f"{stack}.json",
                "workflow_hash_sha256": workflow_hash(workflow),
                "model_stack": models,
                "output_node": output_node,
            }
        return {
            "source": "user_supplied",
            "workflow_name": inputs.get("workflow_name"),
            "workflow_path": inputs.get("workflow_path"),
            "model": inputs.get("workflow_model") or inputs.get("model"),
            "workflow_hash_sha256": workflow_hash(workflow),
            "model_stack": model_stack(None, inputs),
            "model_stack_source": (
                "caller_supplied"
                if inputs.get("workflow_model_stack")
                else "unknown_custom_workflow"
            ),
            "output_node": output_node,
        }
