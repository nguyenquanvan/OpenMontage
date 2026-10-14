"""Model runtimes get a CUDA PyTorch on NVIDIA machines, and a repair swaps in a fresh runtime safely."""

from __future__ import annotations

from pathlib import Path

import pytest

from backlot import model_installer as installer


class Completed:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode, self.stdout, self.stderr = returncode, stdout, stderr


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    monkeypatch.setattr(installer, "MODEL_ROOT", tmp_path / "models")
    monkeypatch.setattr(installer, "STATE_ROOT", tmp_path / "models" / ".install-state")
    monkeypatch.setattr(installer, "MODEL_RUNTIME_ROOT", tmp_path / "runtime")
    monkeypatch.setattr(installer, "_uv_executable", lambda: "uv")
    installer._JOBS.clear()
    return tmp_path


def fake_uv(calls, fail_on=None):
    """Record uv commands; `uv venv` creates the interpreter file so later steps see a runtime."""

    def run(command, **kwargs):
        calls.append(command)
        if command[1] == "venv":
            root = Path(command[-1])
            python = root / ("Scripts/python.exe" if installer.os.name == "nt" else "bin/python")
            python.parent.mkdir(parents=True, exist_ok=True)
            python.write_text("", encoding="utf-8")
        if fail_on and fail_on in command:
            return Completed(1, stderr="resolution failed")
        return Completed()

    return run


def test_every_runtime_install_asks_uv_for_the_matching_torch_build(sandbox, monkeypatch):
    calls = []
    monkeypatch.setattr(installer.subprocess, "run", fake_uv(calls))

    installer._install_runtime("sam2-segmentation", installer.INSTALL_SPECS["sam2-segmentation"])

    venv, pip = calls
    assert "--relocatable" in venv
    assert pip[pip.index("--torch-backend") + 1] == "auto"
    assert "torch>=2.5.1" in pip


def test_kokoro_stays_on_cpu_and_keeps_its_spacy_model(sandbox, monkeypatch):
    calls = []
    monkeypatch.setattr(installer.subprocess, "run", fake_uv(calls))

    installer._install_runtime("kokoro-tts", installer.INSTALL_SPECS["kokoro-tts"])

    pip = calls[-1]
    assert pip[pip.index("--torch-backend") + 1] == "cpu"
    assert any(item.startswith("en_core_web_sm @ ") for item in pip)


def test_multi_step_runtime_installs_run_in_order(sandbox, monkeypatch):
    calls = []
    monkeypatch.setattr(installer.subprocess, "run", fake_uv(calls))
    spec = {"runtime_packages": ("a",), "runtime_install_steps": (("torch==2.0.1",), ("mmcv==2.0.1", "--find-links", "x")),
            "torch_backend": "cu118", "python_version": "3.10"}

    installer._install_runtime("custom", spec)

    steps = [call for call in calls if call[1] == "pip"]
    assert [step[-1] for step in steps] == ["torch==2.0.1", "x"]
    assert all(step[step.index("--torch-backend") + 1] == "cu118" for step in steps)
    assert calls[0][calls[0].index("--python") + 1] == "3.10"


def test_repair_swaps_in_the_fresh_runtime_and_removes_the_old_one(sandbox, monkeypatch):
    live = installer._runtime_root("sam2-segmentation")
    (live / "old-marker").parent.mkdir(parents=True)
    (live / "old-marker").write_text("cpu", encoding="utf-8")
    calls = []
    monkeypatch.setattr(installer.subprocess, "run", fake_uv(calls))

    python = installer._rebuild_runtime("sam2-segmentation", installer.INSTALL_SPECS["sam2-segmentation"])

    assert Path(python).is_file()
    assert not (live / "old-marker").exists()
    assert not live.with_name(live.name + ".rebuild").exists()
    assert not live.with_name(live.name + ".old").exists()
    assert calls[0][-1].endswith("sam2-segmentation.rebuild")


def test_failed_repair_keeps_the_working_runtime(sandbox, monkeypatch):
    live = installer._runtime_root("sam2-segmentation")
    (live / "old-marker").parent.mkdir(parents=True)
    (live / "old-marker").write_text("cpu", encoding="utf-8")
    monkeypatch.setattr(installer.subprocess, "run", fake_uv([], fail_on="pip"))

    with pytest.raises(RuntimeError):
        installer._rebuild_runtime("sam2-segmentation", installer.INSTALL_SPECS["sam2-segmentation"])

    assert (live / "old-marker").read_text(encoding="utf-8") == "cpu"
    assert not live.with_name(live.name + ".rebuild").exists()


def make_torch_dist(root: Path, version: str) -> None:
    site = root / ("Lib/site-packages" if installer.os.name == "nt" else "lib/python3.11/site-packages")
    (site / f"torch-{version}.dist-info").mkdir(parents=True)


def test_cpu_torch_on_an_nvidia_machine_offers_a_gpu_upgrade(sandbox, monkeypatch):
    monkeypatch.setattr(installer, "_nvidia_driver_version", lambda: 591.86)
    make_torch_dist(installer._runtime_root("sam2-segmentation"), "2.14.0+cpu")
    make_torch_dist(installer._runtime_root("realesrgan"), "2.14.0")
    make_torch_dist(installer._runtime_root("kokoro-tts"), "2.14.0+cpu")
    make_torch_dist(installer._runtime_root("florence-vision"), "2.14.0+cu130")

    assert installer.runtime_torch_build("sam2-segmentation") == "cpu"
    assert installer._gpu_upgrade_available("sam2-segmentation", installer.INSTALL_SPECS["sam2-segmentation"]) is True
    assert installer._gpu_upgrade_available("kokoro-tts", installer.INSTALL_SPECS["kokoro-tts"]) is False
    assert installer._gpu_upgrade_available("florence-vision", installer.INSTALL_SPECS["florence-vision"]) is False
    assert installer.runtime_torch_build("piper-tts") is None
    # PyPI's untagged torch is CPU-only on Windows but already CUDA-enabled on Linux.
    assert installer.runtime_torch_build("realesrgan") == "pypi"
    assert installer._gpu_upgrade_available("realesrgan", installer.INSTALL_SPECS["realesrgan"]) is (installer.os.name == "nt")

    monkeypatch.setattr(installer, "_nvidia_driver_version", lambda: 0.0)
    assert installer._gpu_upgrade_available("sam2-segmentation", installer.INSTALL_SPECS["sam2-segmentation"]) is False
