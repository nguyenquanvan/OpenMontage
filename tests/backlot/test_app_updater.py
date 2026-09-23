from __future__ import annotations

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
