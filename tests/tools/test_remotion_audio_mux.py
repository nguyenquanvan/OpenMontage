import shutil
import subprocess
from pathlib import Path

import pytest

from tools.video.video_compose import VideoCompose


pytestmark = pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="ffmpeg and ffprobe are required",
)


def _run(command: list[str]) -> None:
    subprocess.run(command, capture_output=True, check=True, timeout=30)


def test_external_audio_mux_adds_audible_stream_without_changing_video_length(tmp_path) -> None:
    video = tmp_path / "video.mp4"
    audio = tmp_path / "audio.wav"
    _run([
        "ffmpeg", "-y", "-f", "lavfi", "-i",
        "color=c=red:s=320x180:d=2:r=30",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", str(video),
    ])
    _run([
        "ffmpeg", "-y", "-f", "lavfi", "-i",
        "sine=frequency=440:duration=1", str(audio),
    ])

    result = VideoCompose()._mux_external_audio(video, audio)

    assert result.success, result.error
    streams = subprocess.run(
        [
            "ffprobe", "-v", "error", "-show_entries",
            "stream=codec_type", "-of", "csv=p=0", str(video),
        ],
        capture_output=True,
        check=True,
        text=True,
        timeout=30,
    ).stdout.splitlines()
    duration = float(subprocess.run(
        [
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "csv=p=0", str(video),
        ],
        capture_output=True,
        check=True,
        text=True,
        timeout=30,
    ).stdout.strip())

    assert "video" in streams
    assert "audio" in streams
    assert duration == pytest.approx(2.0, abs=0.15)


def test_mux_bounds_the_audio_to_the_video_instead_of_relying_on_shortest(tmp_path, monkeypatch) -> None:
    """FFmpeg 7.1 (bundled in the app) never ends "apad" + "-shortest" with a copied video."""
    video = tmp_path / "video.mp4"
    audio = tmp_path / "audio.wav"
    video.write_bytes(b"v")
    audio.write_bytes(b"a")
    seen = {}

    def fake_run(self, cmd, *, timeout=None, cwd=None):
        seen["cmd"], seen["timeout"] = cmd, timeout
        Path(cmd[-1]).write_bytes(b"muxed")

    monkeypatch.setattr(VideoCompose, "_media_duration", staticmethod(lambda path: 13.056))
    monkeypatch.setattr(VideoCompose, "run_command", fake_run)

    result = VideoCompose()._mux_external_audio(video, audio)

    assert result.success, result.error
    cmd = seen["cmd"]
    assert "-shortest" not in cmd
    assert cmd[cmd.index("-af") + 1] == "apad=whole_dur=13.056"
    assert cmd[cmd.index("-t") + 1] == "13.056"
    assert seen["timeout"] >= 120
    assert video.read_bytes() == b"muxed"


def test_mux_without_a_known_duration_falls_back_to_shortest_without_padding(tmp_path, monkeypatch) -> None:
    video = tmp_path / "video.mp4"
    audio = tmp_path / "audio.wav"
    video.write_bytes(b"v")
    audio.write_bytes(b"a")
    seen = {}

    def fake_run(self, cmd, *, timeout=None, cwd=None):
        seen["cmd"] = cmd
        Path(cmd[-1]).write_bytes(b"muxed")

    monkeypatch.setattr(VideoCompose, "_media_duration", staticmethod(lambda path: None))
    monkeypatch.setattr(VideoCompose, "run_command", fake_run)

    assert VideoCompose()._mux_external_audio(video, audio).success
    assert "-shortest" in seen["cmd"]
    assert not any(str(part).startswith("apad") for part in seen["cmd"])

