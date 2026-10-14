"""The app finds, starts and stops its own ComfyUI; it never touches one the owner started."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from backlot import comfyui_runtime as rt


def make_portable(data_dir: Path) -> Path:
    portable = data_dir / "ComfyUI" / rt.PORTABLE_DIRNAME
    (portable / "python_embeded").mkdir(parents=True)
    (portable / "python_embeded" / "python.exe").write_bytes(b"")
    root = portable / "ComfyUI"
    (root / "models" / "unet").mkdir(parents=True)
    (root / "main.py").write_text("", encoding="utf-8")
    return root


def make_checkout(path: Path) -> Path:
    (path / "models").mkdir(parents=True)
    (path / "main.py").write_text("", encoding="utf-8")
    (path / ".venv" / "Scripts").mkdir(parents=True)
    (path / ".venv" / "Scripts" / "python.exe").write_bytes(b"")
    return path


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(rt, "DATA_DIR", tmp_path / "data")
    monkeypatch.delenv("MOSA_COMFYUI_DIR", raising=False)
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    return tmp_path / "data"


def test_configured_dir_wins_over_the_managed_portable(data_dir, monkeypatch, tmp_path):
    make_portable(data_dir)
    own = make_checkout(tmp_path / "own-comfy")
    assert rt.detect_root() == data_dir / "ComfyUI" / rt.PORTABLE_DIRNAME / "ComfyUI"
    monkeypatch.setenv("MOSA_COMFYUI_DIR", str(own))
    assert rt.detect_root() == own


def test_bare_models_folder_is_not_a_root(data_dir):
    (data_dir / "ComfyUI" / "models").mkdir(parents=True)
    assert rt.detect_root() is None


def test_launcher_uses_the_portable_python_or_the_checkout_venv(data_dir, tmp_path):
    portable_root = make_portable(data_dir)
    command, cwd = rt.launcher(portable_root, 8188)
    assert command[0].endswith("python.exe") and "python_embeded" in command[0]
    assert command[1:4] == ["-s", str(Path("ComfyUI") / "main.py"), "--windows-standalone-build"]
    assert "--port" in command and command[command.index("--port") + 1] == "8188"
    assert "--disable-auto-launch" in command and "--listen" in command
    assert cwd == portable_root.parent

    own = make_checkout(tmp_path / "own")
    command, cwd = rt.launcher(own, 8190)
    assert command[0].endswith(str(Path(".venv") / "Scripts" / "python.exe"))
    assert command[1] == "main.py" and cwd == own

    (tmp_path / "nopython" / "models").mkdir(parents=True)
    (tmp_path / "nopython" / "main.py").write_text("", encoding="utf-8")
    assert rt.launcher(tmp_path / "nopython", 8188) is None


def test_offline_models_mirror_the_server_listing_shape(data_dir):
    root = make_portable(data_dir)
    (root / "models" / "unet" / "flux1-schnell-Q4_K_S.gguf").write_bytes(b"")
    (root / "models" / "unet" / "flux1-dev-Q4_K_S.gguf").write_bytes(b"")
    (root / "models" / "clip").mkdir()
    (root / "models" / "clip" / "t5-v1_1-xxl-encoder-Q4_K_M.gguf").write_bytes(b"")
    (root / "models" / "clip" / "clip_l.safetensors").write_bytes(b"")
    (root / "models" / "vae").mkdir()
    (root / "models" / "vae" / "ae.safetensors").write_bytes(b"")

    models = rt.offline_models(root)

    assert models["unet_gguf"] == ["flux1-dev-Q4_K_S.gguf", "flux1-schnell-Q4_K_S.gguf"]
    assert set(models["clip_gguf"]) == {"t5-v1_1-xxl-encoder-Q4_K_M.gguf", "clip_l.safetensors"}
    assert models["vae"] == ["ae.safetensors"]
    assert models["diffusion_models"] == []


class FakeProcess:
    def __init__(self, pid=4321):
        self.pid = pid


def test_ensure_running_starts_the_managed_install_and_waits(data_dir, monkeypatch):
    root = make_portable(data_dir)
    answers = iter([False, False, False, True])
    monkeypatch.setattr(rt, "reachable", lambda url, timeout=3.0: next(answers, True))
    monkeypatch.setattr(rt, "_pid_alive", lambda pid: pid == 4321)
    monkeypatch.setattr(rt.time, "sleep", lambda seconds: None)
    launched = {}

    def popen(command, **kwargs):
        launched["command"], launched["kwargs"] = command, kwargs
        return FakeProcess()

    assert rt.ensure_running("http://127.0.0.1:8188", timeout=30, popen=popen) is True
    assert launched["command"][1:3] == ["-s", str(Path("ComfyUI") / "main.py")]
    assert launched["kwargs"]["cwd"] == str(root.parent)
    assert launched["kwargs"]["env"]["PYTHONUTF8"] == "1"
    state = json.loads((data_dir / ".backlot" / "comfyui-managed.json").read_text(encoding="utf-8"))
    assert state["pid"] == 4321 and state["port"] == 8188
    assert (data_dir / "logs" / "comfyui.log").is_file()


def test_ensure_running_does_not_start_anything_when_the_server_already_answers(data_dir, monkeypatch):
    make_portable(data_dir)
    monkeypatch.setattr(rt, "reachable", lambda url, timeout=3.0: True)
    popen_calls = []
    assert rt.ensure_running("http://127.0.0.1:8188", popen=lambda *a, **k: popen_calls.append(a)) is True
    assert popen_calls == []
    assert not (data_dir / ".backlot" / "comfyui-managed.json").exists()


def test_ensure_running_explains_when_there_is_nothing_to_start(data_dir, monkeypatch):
    monkeypatch.setattr(rt, "reachable", lambda url, timeout=3.0: False)
    assert rt.ensure_running("http://127.0.0.1:8188", popen=lambda *a, **k: FakeProcess()) is False
    assert "Model Center" in rt.last_error()
    assert rt.ensure_running("http://gpu-box.local:8188", popen=lambda *a, **k: FakeProcess()) is False
    assert "không phải máy này" in rt.last_error()


def test_ensure_running_reports_a_server_that_died_on_startup(data_dir, monkeypatch):
    make_portable(data_dir)
    monkeypatch.setattr(rt, "reachable", lambda url, timeout=3.0: False)
    monkeypatch.setattr(rt, "_pid_alive", lambda pid: False)
    monkeypatch.setattr(rt.time, "sleep", lambda seconds: None)
    assert rt.ensure_running("http://127.0.0.1:8188", timeout=5, popen=lambda *a, **k: FakeProcess()) is False
    assert "comfyui.log" in rt.last_error()
    assert not (data_dir / ".backlot" / "comfyui-managed.json").exists()


def test_stop_managed_only_touches_the_process_the_app_started(data_dir, monkeypatch):
    killed = []
    monkeypatch.setattr(rt.subprocess, "run", lambda command, **kwargs: killed.append(command))
    monkeypatch.setattr(rt, "_pid_alive", lambda pid: pid == 777)
    monkeypatch.setattr(rt.os, "name", "nt")

    assert rt.stop_managed() is False          # nothing recorded: the owner's own ComfyUI is left alone
    rt._write_state({"pid": 777, "port": 8188})
    assert rt.stop_managed() is True
    assert killed and killed[0][:3] == ["taskkill", "/PID", "777"]
    assert not (data_dir / ".backlot" / "comfyui-managed.json").exists()
