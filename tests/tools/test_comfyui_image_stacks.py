"""comfyui_image picks the bundled workflow that the connected ComfyUI can actually run."""

from pathlib import Path

from tools.base_tool import ToolStatus
from tools.graphics import comfyui_image as module
from tools.graphics.comfyui_image import ComfyUIImage, _schnell_models

# What /object_info reports on a FLUX.1-only machine (D:\ComfyUI on the owner's RTX 3070, 13/10/2026).
SCHNELL_ONLY = {
    "checkpoints": ["DreamShaperXL_Turbo_V2-SFW.safetensors"],
    "diffusion_models": [],
    "vae": ["ae.safetensors", "wan2.2_vae.safetensors"],
    "clip": ["clip_l.safetensors"],
    "loras": [],
    "unet_gguf": ["Chroma1-HD-Q4_K_S.gguf", "flux1-dev-Q4_K_S.gguf", "flux1-schnell-Q4_K_S.gguf"],
    "clip_gguf": ["clip_l.safetensors", "t5-v1_1-xxl-encoder-Q4_K_M.gguf", "umt5-xxl-encoder-Q4_K_M.gguf"],
}
FLUX2 = {
    "diffusion_models": ["flux2-dev-nvfp4.safetensors"],
    "clip": ["mistral_3_small_flux2_fp4_mixed.safetensors"],
    "vae": ["flux2-vae.safetensors"],
}


class FakeClient:
    def __init__(self, models, available=True):
        self.models, self.available, self.submitted = models, available, []

    def is_available(self):
        return self.available

    def list_models(self):
        return self.models

    def unavailable_reason(self):
        return "ComfyUI server not reachable"

    def generate(self, workflow, *, output_node, dest, timeout):
        self.submitted.append((workflow, output_node))
        Path(dest).write_bytes(b"png")
        return [Path(dest)]


def tool_with(models, available=True):
    tool = ComfyUIImage()
    tool._client = FakeClient(models, available)
    return tool


def test_schnell_stack_is_picked_from_the_gguf_listing():
    assert _schnell_models(SCHNELL_ONLY) == {
        "unet_name": "flux1-schnell-Q4_K_S.gguf",
        "clip_name1": "t5-v1_1-xxl-encoder-Q4_K_M.gguf",
        "clip_name2": "clip_l.safetensors",
        "vae_name": "ae.safetensors",
    }


def test_incomplete_schnell_stack_is_not_used():
    without_t5 = {**SCHNELL_ONLY, "clip_gguf": ["clip_l.safetensors"]}
    flux2_vae_only = {**SCHNELL_ONLY, "vae": ["flux2-vae.safetensors"]}
    assert _schnell_models(without_t5) is None
    assert _schnell_models(flux2_vae_only) is None


def test_status_is_available_on_a_schnell_only_server():
    assert tool_with(SCHNELL_ONLY).get_status() == ToolStatus.AVAILABLE
    assert tool_with({"vae": [], "unet_gguf": []}).get_status() == ToolStatus.DEGRADED
    assert tool_with(SCHNELL_ONLY, available=False).get_status() == ToolStatus.UNAVAILABLE


def test_schnell_render_uses_the_servers_files_and_few_steps(tmp_path):
    tool = tool_with(SCHNELL_ONLY)

    result = tool.execute({"prompt": "a snowy village", "seed": 7, "width": 1344, "height": 768,
                           "output_path": str(tmp_path / "sc01.png")})

    assert result.success, result.error
    workflow, output_node = tool._client.submitted[0]
    assert output_node == "9"
    assert workflow["1"]["inputs"]["unet_name"] == "flux1-schnell-Q4_K_S.gguf"
    assert workflow["4"]["inputs"]["text"] == "a snowy village"
    assert workflow["7"]["inputs"]["seed"] == 7
    assert workflow["7"]["inputs"]["steps"] == 4
    assert result.data["license"]["commercial_use"] is True
    assert result.data["model"] == "flux1-schnell-Q4_K_S.gguf"
    assert result.data["workflow_provenance"]["workflow"] == "flux1-schnell-gguf-txt2img.json"


def test_flux2_step_counts_are_capped_for_schnell(tmp_path):
    tool = tool_with(SCHNELL_ONLY)
    tool.execute({"prompt": "p", "steps": 20, "output_path": str(tmp_path / "a.png")})
    assert tool._client.submitted[0][0]["7"]["inputs"]["steps"] == module._SCHNELL_MAX_STEPS


def test_flux2_is_preferred_when_installed(tmp_path):
    tool = tool_with({**SCHNELL_ONLY, **FLUX2})

    result = tool.execute({"prompt": "p", "output_path": str(tmp_path / "a.png")})

    assert result.success, result.error
    assert tool._client.submitted[0][1] == "13"
    assert result.data["license"]["commercial_use"] is False


def test_missing_everything_points_to_the_schnell_alternative(tmp_path):
    tool = tool_with({"vae": [], "unet_gguf": [], "clip_gguf": []})

    result = tool.execute({"prompt": "p", "output_path": str(tmp_path / "a.png")})

    assert not result.success
    assert "FLUX.1 schnell GGUF" in result.error
    assert result.data["alternative_stack"][0]["name"] == "flux1-schnell-Q4_K_S.gguf"


def test_info_reports_the_active_workflow_and_its_license():
    info = tool_with(SCHNELL_ONLY).get_info()

    assert info["active_workflow"] == "flux1-schnell-gguf-txt2img"
    assert info["license"]["commercial_use"] is True
    assert set(info["workflow_licenses"]) == {"flux2-txt2img", "flux1-schnell-gguf-txt2img"}
