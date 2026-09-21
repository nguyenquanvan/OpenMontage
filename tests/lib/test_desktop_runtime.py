from __future__ import annotations

import io
import tarfile

from scripts import fetch_desktop_runtime as runtime


def test_copy_ffprobe_uses_windows_executable_name(tmp_path, monkeypatch):
    archive = tmp_path / "ffprobe-win.tgz"
    payload = b"windows-ffprobe"
    with tarfile.open(archive, "w:gz") as bundle:
        member = tarfile.TarInfo("package/ffprobe.exe")
        member.size = len(payload)
        bundle.addfile(member, io.BytesIO(payload))

    monkeypatch.setattr(runtime, "RUNTIME_ROOT", tmp_path / "runtime")
    monkeypatch.setattr(runtime, "DOWNLOAD_ROOT", tmp_path / "downloads")
    monkeypatch.setattr(runtime, "target_platform", lambda: ("win", "x64"))
    monkeypatch.setattr(runtime, "download", lambda url, destination: archive)

    result = runtime.copy_ffprobe(force=True)

    assert result["bundled"] is True
    assert (tmp_path / "runtime" / "ffmpeg" / "ffprobe.exe").read_bytes() == payload
