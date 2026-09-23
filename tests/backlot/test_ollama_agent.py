"""Tests for the zero-cost Ollama workflow runner."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from backlot import ollama_agent as ollama_mod
from backlot import runner as runner_mod


def test_ollama_status_reports_models(monkeypatch):
    monkeypatch.setattr(
        ollama_mod,
        "_request_json",
        lambda *args, **kwargs: {
            "models": [
                {"name": "llama3.1:8b"},
                {"name": "mistral:latest"},
                {"invalid": True},
            ]
        },
    )

    status = ollama_mod.ollama_status()

    assert status["online"] is True
    assert status["models"] == ["llama3.1:8b", "mistral:latest"]


def test_default_model_prefers_granite_tool_calling_model():
    assert ollama_mod.DEFAULT_MODEL == "granite3.3:8b"


def test_ollama_status_is_clear_when_server_is_offline(monkeypatch):
    def offline(*args, **kwargs):
        raise RuntimeError("Không kết nối được Ollama")

    monkeypatch.setattr(ollama_mod, "_request_json", offline)

    status = ollama_mod.ollama_status()

    assert status["online"] is False
    assert status["models"] == []
    assert "Không kết nối" in status["error"]


def test_local_agent_cannot_write_outside_project(tmp_path):
    project = tmp_path / "projects" / "demo"
    project.mkdir(parents=True)
    tools = ollama_mod.LocalWorkflowTools("demo", project, "cinematic", "llama3.1:8b")

    with pytest.raises(ValueError, match="ngoài phạm vi"):
        tools.write_project_file("../../outside.txt", "blocked")
    with pytest.raises(ValueError, match="chuyên dụng"):
        tools.write_project_file("checkpoint_research.json", "{}")
    with pytest.raises(ValueError, match="chuyên dụng"):
        tools.write_project_file("checkpoint.json", "{}")

    result = tools.write_project_file("artifacts/note.md", "nội dung")
    assert result["path"] == "artifacts/note.md"
    assert (project / "artifacts" / "note.md").read_text(encoding="utf-8") == "nội dung"


def test_local_agent_cannot_read_environment_files(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    project = tmp_path / "projects" / "demo"
    repo.mkdir()
    project.mkdir(parents=True)
    (repo / ".env").write_text("SECRET=value", encoding="utf-8")
    (repo / "guide.md").write_text("safe", encoding="utf-8")
    monkeypatch.setattr(ollama_mod, "REPO_ROOT", repo)
    tools = ollama_mod.LocalWorkflowTools("demo", project, "cinematic", "llama3.1:8b")

    with pytest.raises(ValueError, match="credential"):
        tools.read_file("repo", ".env")
    listed = tools.list_files("repo")
    assert ".env" not in listed["files"]
    assert "guide.md" in listed["files"]


def test_ollama_command_uses_python_module_in_source_mode(tmp_path, monkeypatch):
    monkeypatch.delattr(runner_mod.sys, "frozen", raising=False)

    command = runner_mod._command(
        "ollama",
        sys.executable,
        tmp_path,
        "llama3.1:8b",
        True,
        "prompt is stored in a file",
    )

    assert command[:3] == [sys.executable, "-m", "backlot.ollama_agent"]
    assert command[-2:] == ["--model", "llama3.1:8b"]
    assert str(tmp_path / runner_mod.PROMPT_FILENAME) in command


def test_available_agents_includes_ollama_models(monkeypatch):
    monkeypatch.setattr(runner_mod.shutil, "which", lambda name: None)
    monkeypatch.setattr(
        ollama_mod,
        "ollama_status",
        lambda **kwargs: {
            "online": True,
            "models": ["llama3.1:8b"],
            "error": None,
            "host": "http://127.0.0.1:11434",
        },
    )
    monkeypatch.setattr(
        ollama_mod,
        "model_pull_status",
        lambda model=ollama_mod.DEFAULT_MODEL: {"model": model, "status": "idle"},
    )

    agents = runner_mod.available_agents()
    ollama = next(item for item in agents if item["name"] == "ollama")

    assert ollama["available"] is True
    assert ollama["models"] == ["llama3.1:8b"]
    assert ollama["recommended_model"] == ollama_mod.DEFAULT_MODEL


def test_save_checkpoint_uses_validated_writer(tmp_path):
    project = tmp_path / "projects" / "demo"
    project.mkdir(parents=True)
    (project / "project.json").write_text(
        json.dumps({"project_id": "demo", "pipeline_type": "cinematic"}),
        encoding="utf-8",
    )
    tools = ollama_mod.LocalWorkflowTools("demo", project, "cinematic", "llama3.1:8b")

    result = tools.save_checkpoint("research", "failed", {}, error="Thiếu nguồn kiểm chứng")
    checkpoint = json.loads(Path(result["path"]).read_text(encoding="utf-8"))

    assert checkpoint["status"] == "failed"
    assert checkpoint["metadata"]["runner"] == "ollama"
    assert checkpoint["metadata"]["model"] == "llama3.1:8b"


def test_save_checkpoint_accepts_json_object_strings_from_local_models(tmp_path):
    project = tmp_path / "projects" / "demo"
    project.mkdir(parents=True)
    (project / "project.json").write_text(
        json.dumps({"project_id": "demo", "pipeline_type": "cinematic"}),
        encoding="utf-8",
    )
    tools = ollama_mod.LocalWorkflowTools("demo", project, "cinematic", "llama3.1:8b")

    tools.save_checkpoint(
        "research",
        "failed",
        "{}",
        error="Cần nguồn web",
        metadata='{"reason": "offline"}',
    )

    checkpoint = json.loads((project / "checkpoint_research.json").read_text(encoding="utf-8"))
    assert checkpoint["status"] == "failed"
    assert checkpoint["metadata"]["reason"] == "offline"


def test_content_tool_calls_recovers_and_deduplicates_json_calls():
    content = """
    Tôi sẽ gọi tool:
    {"name":"list_local_tools","parameters":{}}
    Lặp lại để minh họa:
    {"name":"list_local_tools","parameters":{}}
    Sau đó lưu:
    {"function":{"name":"save_checkpoint","arguments":{"stage":"research","status":"awaiting_human","artifacts":{},"error":"Cần nguồn web"}}}
    """

    calls = ollama_mod._content_tool_calls(content)

    assert calls == [
        {"function": {"name": "list_local_tools", "arguments": {}}},
        {
            "function": {
                "name": "save_checkpoint",
                "arguments": {
                    "stage": "research",
                    "status": "awaiting_human",
                    "artifacts": {},
                    "error": "Cần nguồn web",
                },
            }
        },
    ]


def test_content_tool_calls_ignores_prose_and_malformed_json():
    assert ollama_mod._content_tool_calls("Chỉ giải thích, không gọi tool") == []
    assert ollama_mod._content_tool_calls('{"name":"read_file","parameters":') == []


def test_normalize_tool_calls_parses_arguments_and_removes_duplicates():
    calls = ollama_mod._normalize_tool_calls([
        {"function": {"name": "list_files", "arguments": '{"base":"project"}'}},
        {"function": {"name": "list_files", "arguments": {"base": "project"}}},
        {"function": {"name": "read_file", "arguments": "not-json"}},
    ])

    assert calls == [
        {"function": {"name": "list_files", "arguments": {"base": "project"}}},
    ]
