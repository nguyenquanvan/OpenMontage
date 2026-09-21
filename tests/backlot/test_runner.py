"""Tests for the optional in-app agent runner bridge."""

from __future__ import annotations

import json

from backlot import runner as runner_mod
from backlot import server as server_mod
from backlot import state as state_mod
from fastapi.testclient import TestClient


class _FinishedProcess:
    pid = 43210

    def poll(self):
        return 0

    def wait(self):
        return 0


def test_start_run_creates_prompt_and_initial_checkpoint(tmp_path, monkeypatch):
    projects = tmp_path / "projects"
    projects.mkdir()
    monkeypatch.setattr(state_mod, "PROJECTS_DIR", projects)
    monkeypatch.setattr(server_mod, "PROJECTS_DIR", projects)
    monkeypatch.setattr(server_mod, "_summary_cache", {})
    monkeypatch.setattr(
        server_mod,
        "_PROJECTS_ROOT_STR",
        __import__("os").path.normcase(str(projects.resolve())),
    )
    monkeypatch.setattr(runner_mod.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(runner_mod.subprocess, "Popen", lambda *args, **kwargs: _FinishedProcess())

    async def no_watch():
        return None

    monkeypatch.setattr(server_mod, "_watch_projects", no_watch)
    with TestClient(server_mod.create_app()) as client:
        created = client.post(
            "/api/projects",
            json={
                "project_id": "runner-test",
                "title": "Runner Test",
                "pipeline_type": "cinematic",
            },
        )
        assert created.status_code == 201

        started = client.post(
            "/api/project/runner-test/run",
            json={
                "brief": "Tạo một video giới thiệu ngắn về sản phẩm mới.",
                "agent": "codex",
                "allow_automation": True,
            },
        )
        assert started.status_code == 202

    project = projects / "runner-test"
    assert (project / "agent_prompt.md").is_file()
    assert (project / "agent_run.log").is_file()
    checkpoint = json.loads((project / "checkpoint_research.json").read_text(encoding="utf-8"))
    assert checkpoint["status"] == "in_progress"
    run = json.loads((project / "agent_run.json").read_text(encoding="utf-8"))
    assert run["agent"] == "codex"
    assert run["status"] in {"running", "completed"}


def test_start_run_requires_explicit_automation_confirmation(tmp_path, monkeypatch):
    projects = tmp_path / "projects"
    projects.mkdir()
    monkeypatch.setattr(state_mod, "PROJECTS_DIR", projects)
    monkeypatch.setattr(server_mod, "PROJECTS_DIR", projects)
    monkeypatch.setattr(server_mod, "_summary_cache", {})
    monkeypatch.setattr(
        server_mod,
        "_PROJECTS_ROOT_STR",
        __import__("os").path.normcase(str(projects.resolve())),
    )

    async def no_watch():
        return None

    monkeypatch.setattr(server_mod, "_watch_projects", no_watch)
    with TestClient(server_mod.create_app()) as client:
        assert client.post(
            "/api/projects",
            json={"project_id": "confirm-test", "title": "Confirm", "pipeline_type": "cinematic"},
        ).status_code == 201
        response = client.post(
            "/api/project/confirm-test/run",
            json={"brief": "Một video ngắn", "agent": "auto", "allow_automation": False},
        )
        assert response.status_code == 400
        assert "Cho phép agent" in response.json()["detail"]
