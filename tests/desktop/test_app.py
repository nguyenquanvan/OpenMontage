"""Desktop launcher environment tests."""

import sys
from pathlib import Path

from desktop import app as desktop_app


def test_standard_streams_are_reconfigured_for_utf8(monkeypatch):
    calls = []

    class Stream:
        def reconfigure(self, **kwargs):
            calls.append(kwargs)

    monkeypatch.setattr(sys, "stdout", Stream())
    monkeypatch.setattr(sys, "stderr", Stream())
    monkeypatch.delenv("PYTHONUTF8", raising=False)
    monkeypatch.delenv("PYTHONIOENCODING", raising=False)

    desktop_app.ensure_standard_streams()

    assert calls == [
        {"encoding": "utf-8", "errors": "backslashreplace"},
        {"encoding": "utf-8", "errors": "backslashreplace"},
    ]
    assert desktop_app.os.environ["PYTHONUTF8"] == "1"
    assert desktop_app.os.environ["PYTHONIOENCODING"] == "utf-8"


def test_configure_agent_path_adds_existing_user_bin(tmp_path, monkeypatch):
    home = tmp_path / "home"
    user_bin = home / ".local" / "bin"
    user_bin.mkdir(parents=True)
    monkeypatch.setattr(Path, "home", lambda: home)
    monkeypatch.setenv("PATH", "/usr/bin")
    monkeypatch.setattr(desktop_app.sys, "platform", "linux")

    desktop_app.configure_agent_path()

    assert desktop_app.os.environ["PATH"].split(desktop_app.os.pathsep)[0] == str(user_bin)


def test_configure_agent_path_finds_windows_agent_installations(tmp_path, monkeypatch):
    home = tmp_path / "home"
    appdata = tmp_path / "Roaming"
    local = tmp_path / "Local"
    npm_bin = appdata / "npm"
    winget_links = local / "Microsoft" / "WinGet" / "Links"
    codex_bin = local / "OpenAI" / "Codex" / "bin" / "versioned"
    for directory in (npm_bin, winget_links, codex_bin):
        directory.mkdir(parents=True)
    (codex_bin / "codex.exe").touch()
    monkeypatch.setattr(Path, "home", lambda: home)
    monkeypatch.setattr(desktop_app.sys, "platform", "win32")
    monkeypatch.setenv("APPDATA", str(appdata))
    monkeypatch.setenv("LOCALAPPDATA", str(local))
    monkeypatch.setenv("PATH", "C:\\Windows")

    desktop_app.configure_agent_path()

    paths = desktop_app.os.environ["PATH"].split(desktop_app.os.pathsep)
    assert str(npm_bin) in paths
    assert str(winget_links) in paths
    assert str(codex_bin) in paths
