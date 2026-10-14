"""MuseTalk runs from its source tree, where its relative ./musetalk and ./models paths both resolve."""

from __future__ import annotations

from pathlib import Path

from backlot.model_installer import INSTALL_SPECS
from tools import local_model_integrations as integrations


class Completed:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode, self.stdout, self.stderr = returncode, stdout, stderr


def installed_musetalk(tmp_path: Path) -> Path:
    root = tmp_path / "musetalk-1.5"
    (root / "models" / "musetalkV15").mkdir(parents=True)
    (root / "models" / "musetalkV15" / "unet.pth").write_bytes(b"weights")
    (root / "MuseTalk-main" / "scripts").mkdir(parents=True)
    (root / "MuseTalk-main" / "scripts" / "inference.py").write_text("", encoding="utf-8")
    return root


def test_inference_runs_in_the_source_tree_with_the_weights_linked(tmp_path, monkeypatch):
    root = installed_musetalk(tmp_path)
    monkeypatch.setattr(integrations, "model_runtime_info",
                        lambda model_id: {"installed": True, "python": "python", "target": str(root / "models")})
    calls = []

    def run(command, **kwargs):
        calls.append((command, kwargs))
        result_dir = Path(command[command.index("--result_dir") + 1])
        (result_dir / "v15").mkdir(parents=True, exist_ok=True)
        (result_dir / "v15" / "face_voice.mp4").write_bytes(b"mp4")
        return Completed()

    monkeypatch.setattr(integrations.subprocess, "run", run)

    result = integrations.MuseTalkLipSync().execute({"inference_config": str(tmp_path / "task.yaml"),
                                                     "output_dir": str(tmp_path / "out")})

    assert result.success, result.error
    command, kwargs = calls[0]
    assert Path(kwargs["cwd"]) == root / "MuseTalk-main"
    assert kwargs["encoding"] == "utf-8" and kwargs["env"]["PYTHONIOENCODING"] == "utf-8"
    assert (root / "MuseTalk-main" / "models" / "musetalkV15" / "unet.pth").read_bytes() == b"weights"
    assert "--use_float16" in command
    assert command[command.index("--whisper_dir") + 1] == str(root / "models" / "whisper")
    assert result.artifacts == [str(tmp_path / "out" / "v15" / "face_voice.mp4")]

    # A second run reuses the existing link.
    assert integrations.MuseTalkLipSync().execute({"inference_config": str(tmp_path / "task.yaml"),
                                                   "output_dir": str(tmp_path / "out")}).success


def test_missing_source_tree_asks_for_a_reinstall(tmp_path, monkeypatch):
    root = tmp_path / "musetalk-1.5"
    (root / "models").mkdir(parents=True)
    monkeypatch.setattr(integrations, "model_runtime_info",
                        lambda model_id: {"installed": True, "python": "python", "target": str(root / "models")})

    result = integrations.MuseTalkLipSync().execute({"inference_config": "task.yaml", "output_dir": str(tmp_path / "out")})

    assert not result.success
    assert "cài lại MuseTalk" in result.error


def test_musetalk_runtime_is_built_with_the_openmmlab_stack():
    spec = INSTALL_SPECS["musetalk-lipsync"]
    steps = [" ".join(step) for step in spec["runtime_install_steps"]]

    assert spec["torch_backend"] == "cu118" and spec["requires_nvidia"]
    assert steps[0] == "torch==2.0.1 torchvision==0.15.2 torchaudio==2.0.2"
    assert any("mmcv==2.0.1" in step and "--only-binary" in step for step in steps)
    assert steps[-1] == "mmpose==1.1.0 --no-build-isolation-package chumpy"
