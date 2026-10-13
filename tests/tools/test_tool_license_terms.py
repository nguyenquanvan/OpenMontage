"""Usage-license metadata travels from tool info and tool results to the agent."""

from tools import local_model_integrations as integrations
from tools.base_tool import ToolResult
from tools.local_model_integrations import KokoroTTS, MusicGenLocal


def test_research_music_model_is_reported_as_not_for_commercial_use():
    info = MusicGenLocal().get_info()

    assert info["license"]["commercial_use"] is False
    assert "CC-BY-NC" in info["license"]["name"]


def test_tools_without_declared_terms_report_none():
    assert KokoroTTS().get_info()["license"] is None


def test_successful_music_result_carries_the_license(monkeypatch):
    monkeypatch.setattr(
        integrations,
        "run_model_worker",
        lambda *args, **kwargs: ToolResult(success=True, data={"output": "theme.wav"}),
    )

    result = MusicGenLocal().execute({"prompt": "piano", "output_path": "theme.wav"})

    assert result.data["output"] == "theme.wav"
    assert result.data["license"]["commercial_use"] is False


def test_failed_result_is_left_alone(monkeypatch):
    monkeypatch.setattr(
        integrations,
        "run_model_worker",
        lambda *args, **kwargs: ToolResult(success=False, error="model missing"),
    )

    result = MusicGenLocal().execute({"prompt": "piano", "output_path": "theme.wav"})

    assert result.error == "model missing"
    assert "license" not in (result.data or {})
