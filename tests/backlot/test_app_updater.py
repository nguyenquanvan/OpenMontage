from __future__ import annotations

import hashlib

from backlot import app_updater


def test_semantic_version_comparison():
    assert app_updater.is_newer_version("1.6.0", "1.5.15") is True
    assert app_updater.is_newer_version("v1.6", "1.6.0") is False
    assert app_updater.is_newer_version("1.5.9", "1.5.10") is False


def test_checksum_manifest_requires_matching_asset():
    text = "a" * 64 + "  MOSA-TOOL-ALL-Setup-1.6.0-win-x64.exe\n"
    assert app_updater._expected_checksum(text, "MOSA-TOOL-ALL-Setup-1.6.0-win-x64.exe") == "a" * 64


def test_update_status_selects_windows_installer(monkeypatch):
    release = {
        "tag_name": "v9.0.0",
        "assets": [
            {"name": "MOSA-TOOL-ALL-Setup-9.0.0-build-win-x64.exe", "size": 123},
            {"name": "SHA256SUMS.txt", "size": 90},
        ],
    }
    monkeypatch.setattr(app_updater, "_release_payload", lambda force=False: release)
    monkeypatch.setattr(app_updater, "_platform_name", lambda: "windows")
    payload = app_updater.update_status(force=True)
    assert payload["update_available"] is True
    assert payload["install_supported"] is True
    assert payload["asset_name"].endswith("-win-x64.exe")


def test_windows_installer_waits_for_active_workflow(monkeypatch, tmp_path):
    events = []
    active = iter((True, True, False))
    monkeypatch.setattr(app_updater, "_platform_name", lambda: "windows")
    monkeypatch.setattr(app_updater, "_workflow_running", lambda: next(active))
    monkeypatch.setattr(app_updater.time, "sleep", lambda seconds: events.append("wait"))
    monkeypatch.setattr(app_updater, "_launch_installer", lambda path: events.append("launch"))

    app_updater._finish_install(tmp_path / "setup.exe")

    assert events == ["wait", "wait", "launch"]
    assert app_updater._job["status"] == "launched"


def test_bad_checksum_never_launches_installer(monkeypatch, tmp_path):
    asset_name = "MOSA-TOOL-ALL-Setup-9.0.0-win-x64.exe"
    launched = []
    monkeypatch.setattr(app_updater, "_platform_name", lambda: "windows")
    monkeypatch.setattr(app_updater, "_updates_dir", lambda: tmp_path)
    monkeypatch.setattr(app_updater, "_launch_installer", lambda path: launched.append(path))

    def fake_download(url, destination, **kwargs):
        if destination.name == app_updater.CHECKSUM_ASSET_NAME:
            destination.write_text(f"{'0' * 64}  {asset_name}\n", encoding="utf-8")
        else:
            destination.write_bytes(b"tampered installer")

    monkeypatch.setattr(app_updater, "_download", fake_download)
    release = {"tag_name": "v9.0.0"}
    asset = {"name": asset_name, "browser_download_url": "https://example.test/setup"}
    checksum = {"browser_download_url": "https://example.test/SHA256SUMS.txt"}

    app_updater._install_worker(release, asset, checksum, automatic=True)

    assert launched == []
    assert app_updater._job["status"] == "error"
    assert not (tmp_path / "9.0.0" / asset_name).exists()


def test_macos_automatic_download_requires_manual_dmg_install(monkeypatch, tmp_path):
    asset_name = "MOSA-TOOL-ALL-macOS.dmg"
    content = b"verified dmg"
    digest = hashlib.sha256(content).hexdigest()
    launched = []
    monkeypatch.setattr(app_updater, "_platform_name", lambda: "macos")
    monkeypatch.setattr(app_updater, "_updates_dir", lambda: tmp_path)
    monkeypatch.setattr(app_updater, "_launch_installer", lambda path: launched.append(path))

    def fake_download(url, destination, **kwargs):
        if destination.name == app_updater.CHECKSUM_ASSET_NAME:
            destination.write_text(f"{digest}  {asset_name}\n", encoding="utf-8")
        else:
            destination.write_bytes(content)

    monkeypatch.setattr(app_updater, "_download", fake_download)
    app_updater._install_worker(
        {"tag_name": "v9.0.0"},
        {"name": asset_name, "browser_download_url": "https://example.test/dmg"},
        {"browser_download_url": "https://example.test/SHA256SUMS.txt"},
        automatic=True,
    )

    assert launched == []
    assert app_updater._job["status"] == "ready"
    assert (tmp_path / "9.0.0" / asset_name).read_bytes() == content
