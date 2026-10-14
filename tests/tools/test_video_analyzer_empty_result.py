"""An empty reference analysis is a failure, not a success with no data."""

from __future__ import annotations

from tools.analysis import transcript_fetcher, video_downloader
from tools.analysis.video_analyzer import VideoAnalyzer
from tools.base_tool import ToolResult


def test_analysis_without_media_transcript_or_frames_fails(tmp_path, monkeypatch):
    monkeypatch.setattr(
        video_downloader.VideoDownloader,
        "execute",
        lambda self, inputs: ToolResult(success=False, error="No module named 'yt_dlp'"),
    )
    monkeypatch.setattr(
        transcript_fetcher.TranscriptFetcher,
        "execute",
        lambda self, inputs: ToolResult(success=False, error="No module named 'youtube_transcript_api'"),
    )

    result = VideoAnalyzer().execute({
        "source": "https://www.youtube.com/watch?v=SIwPOjEL0TU",
        "analysis_depth": "standard",
        "output_dir": str(tmp_path / "analysis"),
    })

    assert result.success is False
    assert "yt_dlp" in (result.error or "")
    # The partial brief is still returned so the agent can see what failed.
    assert result.data["_analysis_meta"]["has_transcript"] is False
    assert result.data["_analysis_meta"]["keyframe_count"] == 0
