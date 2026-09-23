"""Desktop launcher environment tests."""

from pathlib import Path

from desktop import app as desktop_app


def test_configure_agent_path_adds_existing_user_bin(tmp_path, monkeypatch):
    home = tmp_path / "home"
    user_bin = home / ".local" / "bin"
    user_bin.mkdir(parents=True)
    monkeypatch.setattr(Path, "home", lambda: home)
    monkeypatch.setenv("PATH", "/usr/bin")
    monkeypatch.setattr(desktop_app.sys, "platform", "linux")

    desktop_app.configure_agent_path()

    assert desktop_app.os.environ["PATH"].split(desktop_app.os.pathsep)[0] == str(user_bin)
