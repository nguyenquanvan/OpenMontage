"""comfyui_image picks the bundled workflow that the connected ComfyUI can actually run."""

from pathlib import Path

from tools._comfyui.client import ComfyUIError
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
    server_url = "http://127.0.0.1:8188"

    def __init__(self, models, available=True, root=None, starts=True):
        self.models, self.available, self.submitted = models, available, []
        self.root, self.starts, self.start_calls = root, starts, 0
        self.cancelled, self.cancel_outcome = [], "interrupted"

    def cancel(self, prompt_id):
        self.cancelled.append(prompt_id)
        return self.cancel_outcome

    def is_available(self):
        return self.available

    def startable_root(self):
        return self.root

    def ensure_available(self):
        if self.available:
            return True
        self.start_calls += 1
        if self.root is not None and self.starts:
            self.available = True       # the managed ComfyUI came up
        return self.available

    def list_models(self):
        return self.models

    def unavailable_reason(self):
        return "ComfyUI server not reachable"

    def generate(self, workflow, *, output_node, dest, timeout, interval=5, resume_prompt_id=None):
        self.submitted.append((workflow, output_node))
        self.interval = interval
        Path(dest).write_bytes(b"png")
        return [Path(dest)]


def tool_with(models, available=True, root=None, starts=True):
    tool = ComfyUIImage()
    tool._client = FakeClient(models, available, root, starts)
    return tool


def test_server_down_but_startable_install_with_schnell_files_counts_as_available(tmp_path, monkeypatch):
    from backlot import comfyui_runtime

    monkeypatch.setattr(comfyui_runtime, "offline_models", lambda root: SCHNELL_ONLY)
    # Before the start the listing comes from disk; once ComfyUI is up the server reports the same files.
    tool = tool_with(SCHNELL_ONLY, available=False, root=tmp_path)

    assert tool.get_status() == ToolStatus.AVAILABLE
    info = tool.get_info()
    assert info["active_workflow"] == "flux1-schnell-gguf-txt2img"

    result = tool.execute({"prompt": "a village", "output_path": str(tmp_path / "a.png")})

    assert result.success, result.error
    assert tool._client.start_calls == 1          # the tool started ComfyUI itself
    assert tool._client.submitted[0][1] == "9"


def test_server_down_and_nothing_to_start_is_unavailable_with_the_reason(tmp_path, monkeypatch):
    from backlot import comfyui_runtime

    monkeypatch.setattr(comfyui_runtime, "last_error", lambda: "Chưa có ComfyUI nào để bật")
    tool = tool_with({}, available=False, root=None)

    assert tool.get_status() == ToolStatus.UNAVAILABLE
    result = tool.execute({"prompt": "p", "output_path": str(tmp_path / "a.png")})
    assert not result.success
    assert "Chưa có ComfyUI nào để bật" in result.error


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
    # A ~16 s image must not wait out a 5 s poll tick.
    assert tool._client.interval == 1
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


def test_batch_draws_every_item_in_one_call(tmp_path):
    tool = tool_with(SCHNELL_ONLY)

    result = tool.execute({
        "width": 1344,
        "height": 768,
        "batch": [
            {"prompt": "chalk bowl of yogurt", "output_path": str(tmp_path / "s1.png"), "seed": 11},
            {"prompt": "chalk salmon fillet", "output_path": str(tmp_path / "s2.png"), "seed": 12, "width": 1024},
        ],
    })

    assert result.success, result.error
    assert result.data["count"] == 2 and result.data["failed"] == 0
    assert result.artifacts == [str(tmp_path / "s1.png"), str(tmp_path / "s2.png")]
    first, second = (workflow for workflow, _ in tool._client.submitted)
    assert first["4"]["inputs"]["text"] == "chalk bowl of yogurt"
    assert first["6"]["inputs"]["width"] == 1344
    assert second["6"]["inputs"]["width"] == 1024
    assert [entry["seed"] for entry in result.data["results"]] == [11, 12]


def test_batch_reports_failed_items_without_hiding_the_rest(tmp_path):
    tool = tool_with(SCHNELL_ONLY)
    real_generate = tool._client.generate

    def flaky(workflow, **kwargs):
        if workflow["4"]["inputs"]["text"] == "bad":
            raise RuntimeError("GPU out of memory")
        return real_generate(workflow, **kwargs)

    tool._client.generate = flaky
    result = tool.execute({"batch": [
        {"prompt": "good", "output_path": str(tmp_path / "ok.png")},
        {"prompt": "bad", "output_path": str(tmp_path / "bad.png")},
    ]})

    assert not result.success
    assert result.data["failed"] == 1
    assert result.artifacts == [str(tmp_path / "ok.png")]
    assert "GPU out of memory" in result.data["results"][1]["error"]


def stalls_on(tool, *prompts):
    """Make generate() miss its deadline for the given prompts, like a GPU starved by another program."""
    real_generate = tool._client.generate

    def generate(workflow, **kwargs):
        if kwargs.get("resume_prompt_id"):
            raise ComfyUIError("still running", prompt_id=kwargs["resume_prompt_id"], timed_out=True)
        if workflow["4"]["inputs"]["text"] in prompts:
            tool._client.submitted.append((workflow, kwargs["output_node"]))
            raise ComfyUIError("did not complete within 600s", prompt_id=f"id-{workflow['4']['inputs']['text']}",
                               timed_out=True)
        return real_generate(workflow, **kwargs)

    tool._client.generate = generate


def test_a_timed_out_image_is_cancelled_on_the_server(tmp_path):
    tool = tool_with(SCHNELL_ONLY)
    stalls_on(tool, "slow")

    result = tool.execute({"prompt": "slow", "output_path": str(tmp_path / "s01.png")})

    assert not result.success
    assert tool._client.cancelled == ["id-slow"]
    assert result.data == {"timed_out": True, "prompt_id": "id-slow", "cancelled": "interrupted",
                           "output_path": str(tmp_path / "s01.png")}
    assert "interrupted on the ComfyUI server" in result.error
    assert "8188/queue" in result.error


def test_an_image_that_finished_at_the_deadline_is_kept(tmp_path):
    tool = tool_with(SCHNELL_ONLY)
    tool._client.cancel_outcome = "not_queued"
    calls = []

    def generate(workflow, **kwargs):
        calls.append(kwargs.get("resume_prompt_id"))
        if not kwargs.get("resume_prompt_id"):
            raise ComfyUIError("did not complete within 600s", prompt_id="id-1", timed_out=True)
        Path(kwargs["dest"]).write_bytes(b"png")
        return [Path(kwargs["dest"])]

    tool._client.generate = generate
    result = tool.execute({"prompt": "p", "output_path": str(tmp_path / "s01.png")})

    assert result.success, result.error
    assert calls == [None, "id-1"]
    assert result.artifacts == [str(tmp_path / "s01.png")]


def test_execution_errors_are_reported_without_cancelling(tmp_path):
    tool = tool_with(SCHNELL_ONLY)

    def broken(workflow, **kwargs):
        raise ComfyUIError("Execution error: out of memory", prompt_id="id-1")

    tool._client.generate = broken
    result = tool.execute({"prompt": "p", "output_path": str(tmp_path / "s01.png")})

    assert not result.success and "out of memory" in result.error
    assert tool._client.cancelled == []


def test_a_batch_stops_at_the_first_timeout_and_skips_the_rest(tmp_path):
    tool = tool_with(SCHNELL_ONLY)
    stalls_on(tool, "s2")

    result = tool.execute({"batch": [
        {"prompt": f"s{n}", "output_path": str(tmp_path / f"s{n}.png")} for n in range(1, 5)
    ]})

    assert not result.success
    assert [workflow["4"]["inputs"]["text"] for workflow, _ in tool._client.submitted] == ["s1", "s2"]
    assert tool._client.cancelled == ["id-s2"]
    assert result.artifacts == [str(tmp_path / "s1.png")]
    assert result.data["stopped_after_timeout"] is True
    assert result.data["failed"] == 3
    assert result.data["results"][1]["data"]["prompt_id"] == "id-s2"
    assert [entry.get("skipped", False) for entry in result.data["results"]] == [False, False, True, True]
    assert "stopped after a timeout" in result.error
