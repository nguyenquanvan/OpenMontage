from __future__ import annotations

from pathlib import Path

from backlot import model_installer as installer


def test_file_pack_install_writes_marker_and_configures_path(tmp_path, monkeypatch):
    source = tmp_path / "source.onnx"
    source.write_bytes(b"model-data")
    model_root = tmp_path / "models"
    state_root = tmp_path / "state"
    configured = {}

    monkeypatch.setattr(installer, "MODEL_ROOT", model_root)
    monkeypatch.setattr(installer, "STATE_ROOT", state_root)
    monkeypatch.setattr(
        installer,
        "update_provider_settings",
        lambda updates, clear: configured.update(updates),
    )
    installer._JOBS.clear()
    spec = {
        "label": "Test",
        "kind": "files",
        "target": "test-pack",
        "estimated_bytes": len(b"model-data"),
        "files": (installer.DownloadFile(source.as_uri(), "voice.onnx", len(b"model-data")),),
        "settings": {"PIPER_MODEL": "{target}/voice.onnx"},
    }

    installer._run_install("test-pack", spec)

    assert (model_root / "test-pack" / "voice.onnx").read_bytes() == b"model-data"
    assert installer._read_state("test-pack")["status"] == "installed"
    assert configured["PIPER_MODEL"].endswith("test-pack/voice.onnx")


def test_unsupported_pack_is_rejected(monkeypatch):
    monkeypatch.setitem(
        installer.INSTALL_SPECS,
        "blocked-test",
        {"label": "Blocked", "kind": "unsupported", "blocked_reason": "Không phù hợp"},
    )

    try:
        installer.start_install("blocked-test")
    except ValueError as exc:
        assert str(exc) == "Không phù hợp"
    else:
        raise AssertionError("unsupported pack must be rejected")


def test_archive_pack_extracts_and_can_be_uninstalled(tmp_path, monkeypatch):
    import zipfile

    archive = tmp_path / "pack.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("bin/runtime.txt", "ready")
    model_root = tmp_path / "models"
    state_root = tmp_path / "state"
    monkeypatch.setattr(installer, "MODEL_ROOT", model_root)
    monkeypatch.setattr(installer, "STATE_ROOT", state_root)
    monkeypatch.setattr(installer, "MODEL_RUNTIME_ROOT", tmp_path / "runtime")
    installer._JOBS.clear()
    spec = {
        "label": "Archive",
        "kind": "files",
        "target": "archive-pack",
        "estimated_bytes": archive.stat().st_size,
        "files": (installer.DownloadFile(archive.as_uri(), "pack.zip", archive.stat().st_size, extract_to="."),),
    }
    monkeypatch.setitem(installer.INSTALL_SPECS, "archive-pack", spec)

    installer._run_install("archive-pack", spec)

    assert (model_root / "archive-pack" / "bin" / "runtime.txt").read_text() == "ready"
    assert installer.model_runtime_info("archive-pack")["installed"] is True
    installer.uninstall_model("archive-pack")
    assert not (model_root / "archive-pack" / "bin" / "runtime.txt").exists()


def test_catalog_marks_downloaded_weights_that_need_runtime(tmp_path, monkeypatch):
    model_root = tmp_path / "models"
    state_root = tmp_path / "state"
    runtime_root = tmp_path / "runtime"
    target = model_root / "runtime-pack"
    target.mkdir(parents=True)
    (target / "weights.bin").write_bytes(b"weights")
    monkeypatch.setattr(installer, "MODEL_ROOT", model_root)
    monkeypatch.setattr(installer, "STATE_ROOT", state_root)
    monkeypatch.setattr(installer, "MODEL_RUNTIME_ROOT", runtime_root)
    monkeypatch.setitem(installer.INSTALL_SPECS, "runtime-pack", {
        "label": "Runtime Pack",
        "kind": "files",
        "target": "runtime-pack",
        "estimated_bytes": 7,
        "runtime_packages": ("example",),
        "files": (),
    })
    installer._write_state("runtime-pack", {"status": "installed", "files": ["weights.bin"]})

    item = next(item for item in installer.install_catalog() if item["id"] == "runtime-pack")

    assert item["weights_installed"] is True
    assert item["runtime_installed"] is False
    assert item["status"] == "needs_runtime"
    assert item["installed"] is False


def test_platform_specific_pack_is_rejected_when_missing(monkeypatch):
    monkeypatch.setattr(installer, "_platform_key", lambda: "linux-arm64")
    spec = {
        "label": "Platform Pack",
        "kind": "files",
        "platform_files": {"darwin-arm64": ()},
    }

    compatible, reason = installer._compatibility(spec)

    assert compatible is False
    assert "linux-arm64" in reason
