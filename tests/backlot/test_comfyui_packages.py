"""Model Center packages for ComfyUI: the portable runtime and the FLUX.1 schnell stack."""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from backlot import comfyui_runtime as rt
from backlot import model_installer as installer


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    data = tmp_path / "data"
    monkeypatch.setattr(rt, "DATA_DIR", data)
    monkeypatch.setattr(installer, "MODEL_ROOT", data / "models")
    monkeypatch.setattr(installer, "STATE_ROOT", data / "models" / ".install-state")
    monkeypatch.setattr(installer, "MODEL_RUNTIME_ROOT", data / "model-runtime")
    monkeypatch.setattr(installer, "update_provider_settings", lambda updates, clear: None)
    monkeypatch.delenv("MOSA_COMFYUI_DIR", raising=False)
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    installer._JOBS.clear()
    installer._nvidia_driver_version.cache_clear()
    return data


def test_catalog_has_the_schnell_pack_and_its_sizes_are_exact():
    spec = installer.INSTALL_SPECS["comfyui-flux1-schnell"]
    files = {item.relative_path: item.size_bytes for item in spec["files"]}
    assert files == {
        "unet/flux1-schnell-Q4_K_S.gguf": 6_783_943_712,
        "clip/t5-v1_1-xxl-encoder-Q4_K_M.gguf": 2_896_123_072,
        "clip/clip_l.safetensors": 246_144_152,
        "vae/ae.safetensors": 335_304_388,
    }
    assert spec["license"] == "Apache-2.0"
    assert spec["requires"] == ("comfyui-runtime",)
    assert not spec.get("commercial_restricted")
    # Every ComfyUI-hosted package depends on the runtime now; the old entries stay in the catalogue.
    for model_id in ("comfyui-image", "comfyui-video", "comfyui-music"):
        assert installer.INSTALL_SPECS[model_id]["requires"] == ("comfyui-runtime",)
    for model_id in ("face-restore", "wav2lip-research", "musicgen-research", "qwen-vl-research", "comfyui-image"):
        assert model_id in installer.INSTALL_SPECS


def test_portable_archive_follows_the_driver(monkeypatch):
    monkeypatch.setattr(installer, "_platform_key", lambda: "win32-x64")
    installer._nvidia_driver_version.cache_clear()
    monkeypatch.setattr(installer, "_nvidia_driver_version", lambda: 591.86)
    files = installer._comfyui_portable_files()
    assert files[0].relative_path == "ComfyUI_windows_portable_nvidia.7z"
    assert files[0].size_bytes == 2_009_901_495 and files[0].record_root == rt.PORTABLE_DIRNAME
    assert files[1].record_root.endswith("custom_nodes/ComfyUI-GGUF")

    monkeypatch.setattr(installer, "_nvidia_driver_version", lambda: 552.0)
    assert installer._comfyui_portable_files()[0].relative_path == "ComfyUI_windows_portable_nvidia_cu126.7z"

    monkeypatch.setattr(installer, "_platform_key", lambda: "darwin-arm64")
    assert installer._comfyui_portable_files() == []


def test_runtime_pack_is_blocked_without_an_nvidia_driver_or_7zr(sandbox, monkeypatch):
    monkeypatch.setattr(installer, "_platform_key", lambda: "win32-x64")
    monkeypatch.setattr(installer, "_nvidia_driver_version", lambda: 0.0)
    monkeypatch.setattr(installer, "_seven_zip_executable", lambda: "7zr.exe")
    ok, why = installer._compatibility(installer.INSTALL_SPECS["comfyui-runtime"])
    assert ok is False and "NVIDIA" in why

    monkeypatch.setattr(installer, "_nvidia_driver_version", lambda: 591.0)
    monkeypatch.setattr(installer, "_seven_zip_executable", lambda: None)
    ok, why = installer._compatibility(installer.INSTALL_SPECS["comfyui-runtime"])
    assert ok is False and "7zr" in why


def test_schnell_pack_reports_the_runtime_blocker_and_counts_its_size(sandbox, monkeypatch):
    monkeypatch.setattr(installer, "_platform_key", lambda: "win32-x64")
    monkeypatch.setattr(installer, "_nvidia_driver_version", lambda: 0.0)
    ok, why = installer._compatibility(installer.INSTALL_SPECS["comfyui-flux1-schnell"])
    assert ok is False and "Cần cài ComfyUI portable" in why

    monkeypatch.setattr(installer, "_nvidia_driver_version", lambda: 591.0)
    monkeypatch.setattr(installer, "_seven_zip_executable", lambda: "7zr.exe")
    monkeypatch.setattr(installer.shutil, "disk_usage", lambda path: type("U", (), {"free": 15 * 1024**3})())
    ok, why = installer._compatibility(installer.INSTALL_SPECS["comfyui-flux1-schnell"])
    assert ok is False and "trống" in why          # 10 GB models + 7.5 GB runtime + reserve do not fit in 15 GB


def test_existing_comfyui_checkout_satisfies_the_runtime_requirement(sandbox, monkeypatch, tmp_path):
    own = tmp_path / "own-comfy"
    (own / "models").mkdir(parents=True)
    (own / "main.py").write_text("", encoding="utf-8")
    (own / ".venv" / "Scripts").mkdir(parents=True)
    (own / ".venv" / "Scripts" / "python.exe").write_bytes(b"")
    monkeypatch.setenv("MOSA_COMFYUI_DIR", str(own))

    assert installer._requirement_ready("comfyui-runtime") is True
    assert installer._target_root(installer.INSTALL_SPECS["comfyui-flux1-schnell"]) == own / "models"


def test_install_chain_runs_the_runtime_first_then_places_models_in_it(sandbox, monkeypatch, tmp_path):
    """A fake 7z (extracted by a stub 7zr) stands in for the portable; model files come from file:// URLs."""
    portable_payload = tmp_path / "payload.zip"
    with zipfile.ZipFile(portable_payload, "w") as bundle:
        bundle.writestr(f"{rt.PORTABLE_DIRNAME}/python_embeded/python.exe", "")
        bundle.writestr(f"{rt.PORTABLE_DIRNAME}/ComfyUI/main.py", "")
        bundle.writestr(f"{rt.PORTABLE_DIRNAME}/ComfyUI/models/.keep", "")
    gguf_zip = tmp_path / "gguf.zip"
    with zipfile.ZipFile(gguf_zip, "w") as bundle:
        bundle.writestr("ComfyUI-GGUF-main/nodes.py", "")
        bundle.writestr("ComfyUI-GGUF-main/requirements.txt", "gguf>=0.13.0\n")
    archive_7z = tmp_path / "portable.7z"
    archive_7z.write_bytes(portable_payload.read_bytes())

    def fake_7zr(command, **kwargs):
        destination = next(part[2:] for part in command if part.startswith("-o"))
        with zipfile.ZipFile(command[-1]) as bundle:
            bundle.extractall(destination)
        return type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    pip_calls = []

    def fake_run(command, **kwargs):
        if "7zr" in str(command[0]):
            return fake_7zr(command)
        pip_calls.append(command)
        return type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    monkeypatch.setattr(installer.subprocess, "run", fake_run)
    monkeypatch.setattr(installer, "_seven_zip_executable", lambda: "C:/runtime/7zr.exe")
    monkeypatch.setattr(installer, "_comfyui_portable_files", lambda: [
        installer.DownloadFile(archive_7z.as_uri(), "portable.7z", archive_7z.stat().st_size,
                               extract_to=".", record_root=rt.PORTABLE_DIRNAME),
        installer.DownloadFile(gguf_zip.as_uri(), "ComfyUI-GGUF-main.zip", 0,
                               extract_to=f"{rt.PORTABLE_DIRNAME}/ComfyUI/custom_nodes",
                               record_root=f"{rt.PORTABLE_DIRNAME}/ComfyUI/custom_nodes/ComfyUI-GGUF"),
    ])
    weights = {}
    for relative in ("unet/flux1-schnell-Q4_K_S.gguf", "clip/t5-v1_1-xxl-encoder-Q4_K_M.gguf",
                     "clip/clip_l.safetensors", "vae/ae.safetensors"):
        source = tmp_path / Path(relative).name
        source.write_bytes(relative.encode())
        weights[relative] = source
    schnell = dict(installer.INSTALL_SPECS["comfyui-flux1-schnell"])
    schnell["files"] = tuple(installer.DownloadFile(src.as_uri(), rel, src.stat().st_size) for rel, src in weights.items())
    monkeypatch.setitem(installer.INSTALL_SPECS, "comfyui-flux1-schnell", schnell)

    installer._run_install("comfyui-flux1-schnell", schnell)

    root = sandbox / "ComfyUI" / rt.PORTABLE_DIRNAME / "ComfyUI"
    runtime_state = installer._read_state("comfyui-runtime")
    assert runtime_state["status"] == "installed", runtime_state.get("detail")
    assert runtime_state["files"] == [
        rt.PORTABLE_DIRNAME, f"{rt.PORTABLE_DIRNAME}/ComfyUI/custom_nodes/ComfyUI-GGUF"]
    assert (root / "custom_nodes" / "ComfyUI-GGUF" / "nodes.py").is_file()
    assert not (sandbox / "ComfyUI" / "portable.7z").exists()
    state = installer._read_state("comfyui-flux1-schnell")
    assert state["status"] == "installed"
    assert (root / "models" / "unet" / "flux1-schnell-Q4_K_S.gguf").read_bytes() == b"unet/flux1-schnell-Q4_K_S.gguf"
    assert (root / "models" / "vae" / "ae.safetensors").is_file()
    assert pip_calls and pip_calls[0][-2:] == ["-r", str(root / "custom_nodes" / "ComfyUI-GGUF" / "requirements.txt")]
    assert pip_calls[0][0].endswith("python.exe") and "python_embeded" in pip_calls[0][0]
    assert installer._requirement_ready("comfyui-runtime") is True
    catalog = {item["id"]: item for item in installer.install_catalog()}
    assert catalog["comfyui-flux1-schnell"]["installed"] is True
    assert catalog["comfyui-runtime"]["installed"] is True


def test_failed_runtime_install_fails_the_schnell_pack(sandbox, monkeypatch):
    monkeypatch.setattr(installer, "_requirement_ready", lambda model_id: False)

    def failing_runtime(model_id, spec):
        installer._write_state(model_id, {"status": "error", "detail": "mất mạng"})

    original = installer._run_install
    monkeypatch.setattr(installer, "_run_install", lambda model_id, spec: failing_runtime(model_id, spec)
                        if model_id == "comfyui-runtime" else original(model_id, spec))

    installer._run_install("comfyui-flux1-schnell", installer.INSTALL_SPECS["comfyui-flux1-schnell"])

    state = installer._read_state("comfyui-flux1-schnell")
    assert state["status"] == "error"
    assert "mất mạng" in state["detail"]


def test_7z_archives_go_through_7zr(tmp_path, monkeypatch):
    calls = []

    def fake_run(command, **kwargs):
        calls.append(command)
        (tmp_path / "out" / "ComfyUI_windows_portable").mkdir(parents=True)
        return type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    monkeypatch.setattr(installer.subprocess, "run", fake_run)
    monkeypatch.setattr(installer, "_seven_zip_executable", lambda: "7zr.exe")
    archive = tmp_path / "x.7z"
    archive.write_bytes(b"7z")

    extracted = installer._extract_archive(archive, tmp_path / "out")

    assert extracted == ["ComfyUI_windows_portable"]
    assert calls[0][:3] == ["7zr.exe", "x", "-y"] and calls[0][-1] == str(archive)

    monkeypatch.setattr(installer, "_seven_zip_executable", lambda: None)
    with pytest.raises(RuntimeError):
        installer._extract_archive(archive, tmp_path / "out2")
