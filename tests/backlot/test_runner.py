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


class _FailedProcess:
    def wait(self):
        return 1


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
    monkeypatch.setattr(runner_mod, "_watch_process", lambda *args: None)

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
    assert run["status"] == "running"


def test_start_run_resumes_at_next_incomplete_stage(tmp_path, monkeypatch):
    projects = tmp_path / "projects"
    project = projects / "resume-test"
    project.mkdir(parents=True)
    (project / "project.json").write_text(
        json.dumps({
            "project_id": "resume-test",
            "title": "Resume Test",
            "pipeline_type": "cinematic",
        }),
        encoding="utf-8",
    )
    monkeypatch.setattr(state_mod, "PROJECTS_DIR", projects)
    monkeypatch.setattr(runner_mod.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(runner_mod, "get_next_stage", lambda *args: "proposal")
    monkeypatch.setattr(runner_mod.subprocess, "Popen", lambda *args, **kwargs: _FinishedProcess())
    monkeypatch.setattr(runner_mod, "_watch_process", lambda *args: None)

    runner_mod.start_run(
        "resume-test",
        brief="Tiếp tục dự án đến cổng duyệt kế tiếp.",
        agent="codex",
        allow_automation=True,
    )

    checkpoint = json.loads((project / "checkpoint_proposal.json").read_text(encoding="utf-8"))
    prompt = (project / "agent_prompt.md").read_text(encoding="utf-8")
    assert checkpoint["status"] == "in_progress"
    assert not (project / "checkpoint_research.json").exists()
    assert "KHÔNG phải là điểm kết thúc workflow" in prompt
    assert "awaiting_human" in prompt


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


def test_claude_command_places_prompt_before_variadic_add_dir():
    prompt = "Tạo checkpoint ý tưởng hợp lệ."
    command = runner_mod._command(
        "claude",
        "/usr/local/bin/claude",
        __import__("pathlib").Path("/tmp/project"),
        None,
        True,
        prompt,
    )

    assert command.index(prompt) < command.index("--add-dir")
    assert "--verbose" in command


def test_resolve_ollama_requires_downloaded_model(monkeypatch):
    from backlot import ollama_agent as ollama_mod

    monkeypatch.setattr(
        ollama_mod,
        "ollama_status",
        lambda **kwargs: {"online": True, "models": [], "error": None},
    )

    try:
        runner_mod._resolve_agent("ollama")
    except ValueError as exc:
        assert "chưa có model" in str(exc)
    else:
        raise AssertionError("Ollama without a model must not start")


def test_failed_worker_marks_active_checkpoint_failed(tmp_path):
    project = tmp_path / "projects" / "failed-run"
    project.mkdir(parents=True)
    (project / "project.json").write_text(
        json.dumps({
            "project_id": "failed-run",
            "pipeline_type": "cinematic",
        }),
        encoding="utf-8",
    )
    (project / "agent_run.json").write_text(
        json.dumps({"project_id": "failed-run", "status": "running", "agent": "ollama"}),
        encoding="utf-8",
    )
    (project / "agent_run.log").write_text(
        "[ollama] LỖI: Model dừng mà chưa ghi checkpoint hợp lệ\n",
        encoding="utf-8",
    )
    runner_mod.write_checkpoint(
        project.parent,
        "failed-run",
        "research",
        "in_progress",
        {},
        pipeline_type="cinematic",
    )

    runner_mod._watch_process("failed-run", project, _FailedProcess())

    run = json.loads((project / "agent_run.json").read_text(encoding="utf-8"))
    checkpoint = json.loads((project / "checkpoint_research.json").read_text(encoding="utf-8"))
    assert run["status"] == "failed"
    assert run["error"] == "Model dừng mà chưa ghi checkpoint hợp lệ"
    assert checkpoint["status"] == "failed"
    assert checkpoint["error"] == run["error"]


def test_successful_worker_is_failed_when_pipeline_stops_before_gate(tmp_path, monkeypatch):
    project = tmp_path / "projects" / "early-stop"
    project.mkdir(parents=True)
    (project / "project.json").write_text(
        json.dumps({"project_id": "early-stop", "pipeline_type": "cinematic"}),
        encoding="utf-8",
    )
    (project / "agent_run.json").write_text(
        json.dumps({"project_id": "early-stop", "status": "running", "agent": "codex"}),
        encoding="utf-8",
    )
    runner_mod.write_checkpoint(
        project.parent,
        "early-stop",
        "proposal",
        "in_progress",
        {},
        pipeline_type="cinematic",
    )
    monkeypatch.setattr(runner_mod, "get_next_stage", lambda *args: "proposal")

    runner_mod._watch_process("early-stop", project, _FinishedProcess())

    run = json.loads((project / "agent_run.json").read_text(encoding="utf-8"))
    checkpoint = json.loads((project / "checkpoint_proposal.json").read_text(encoding="utf-8"))
    assert run["status"] == "failed"
    assert "proposal" in run["error"]
    assert checkpoint["status"] == "failed"


def test_successful_worker_pauses_at_human_gate(tmp_path, monkeypatch):
    project = tmp_path / "projects" / "approval-stop"
    project.mkdir(parents=True)
    (project / "project.json").write_text(
        json.dumps({"project_id": "approval-stop", "pipeline_type": "cinematic"}),
        encoding="utf-8",
    )
    (project / "agent_run.json").write_text(
        json.dumps({"project_id": "approval-stop", "status": "running", "agent": "codex"}),
        encoding="utf-8",
    )
    (project / "checkpoint_proposal.json").write_text(
        json.dumps({"stage": "proposal", "status": "awaiting_human"}),
        encoding="utf-8",
    )
    monkeypatch.setattr(runner_mod, "get_next_stage", lambda *args: "proposal")

    runner_mod._watch_process("approval-stop", project, _FinishedProcess())

    run = json.loads((project / "agent_run.json").read_text(encoding="utf-8"))
    assert run["status"] == "awaiting_human"
    assert run["awaiting_stage"] == "proposal"


def test_usage_limit_failure_is_reported_actionably(tmp_path):
    project = tmp_path / "projects" / "quota-run"
    project.mkdir(parents=True)
    (project / "agent_run.log").write_text(
        "You've hit your usage limit. Upgrade or try again later.\n",
        encoding="utf-8",
    )

    message = runner_mod._run_failure_detail(project, "generic failure")

    assert "hết hạn mức sử dụng" in message
    assert "Claude Code" in message


def test_claude_auth_failure_is_reported_actionably(tmp_path):
    project = tmp_path / "projects" / "claude-auth-run"
    project.mkdir(parents=True)
    (project / "agent_run.log").write_text(
        "Failed to authenticate. API Error: 401 OAuth access token is invalid.\n",
        encoding="utf-8",
    )

    message = runner_mod._run_failure_detail(project, "generic failure")

    assert "Claude Code chưa xác thực" in message
    assert "claude auth login" in message


def test_health_research_blocks_offline_ollama(tmp_path, monkeypatch):
    projects = tmp_path / "projects"
    project = projects / "health-test"
    project.mkdir(parents=True)
    (project / "project.json").write_text(
        json.dumps({
            "project_id": "health-test",
            "title": "Health Test",
            "pipeline_type": "health-infographic",
        }),
        encoding="utf-8",
    )
    monkeypatch.setattr(state_mod, "PROJECTS_DIR", projects)
    monkeypatch.setattr(
        __import__("backlot.ollama_agent", fromlist=["ollama_status"]),
        "ollama_status",
        lambda **kwargs: {
            "online": True,
            "models": ["granite3.3:8b"],
            "error": None,
            "host": "http://127.0.0.1:11434",
        },
    )

    try:
        runner_mod.start_run(
            "health-test",
            brief="Nghiên cứu chủ đề sức khỏe có nguồn.",
            agent="ollama",
            allow_automation=True,
        )
    except ValueError as exc:
        assert "nguồn web" in str(exc)
        assert "Codex" in str(exc)
    else:
        raise AssertionError("Offline Ollama must not run the health research stage")

    assert not (project / "agent_run.json").exists()


def test_documentary_montage_blocks_offline_ollama(tmp_path, monkeypatch):
    projects = tmp_path / "projects"
    project = projects / "documentary-test"
    project.mkdir(parents=True)
    (project / "project.json").write_text(
        json.dumps({
            "project_id": "documentary-test",
            "title": "Documentary Test",
            "pipeline_type": "documentary-montage",
        }),
        encoding="utf-8",
    )
    monkeypatch.setattr(state_mod, "PROJECTS_DIR", projects)
    monkeypatch.setattr(
        __import__("backlot.ollama_agent", fromlist=["ollama_status"]),
        "ollama_status",
        lambda **kwargs: {
            "online": True,
            "models": ["granite3.3:8b"],
            "error": None,
            "host": "http://127.0.0.1:11434",
        },
    )

    try:
        runner_mod.start_run(
            "documentary-test",
            brief="Tạo phóng sự dùng footage thật từ nhiều nguồn.",
            agent="ollama",
            allow_automation=True,
        )
    except ValueError as exc:
        assert "footage thật" in str(exc)
        assert "Codex hoặc Claude" in str(exc)
    else:
        raise AssertionError("Offline Ollama must not run documentary montage")

    assert not (project / "agent_run.json").exists()


def _make_review_gate_project(tmp_path, project_id: str):
    from tests.contracts.test_phase0_contracts import sample_artifact

    projects = tmp_path / "projects"
    project = projects / project_id
    project.mkdir(parents=True)
    (project / "project.json").write_text(
        json.dumps({
            "project_id": project_id,
            "title": "Review Gate",
            "pipeline_type": "documentary-montage",
            "brief": "Tạo một video phóng sự ngắn.",
        }),
        encoding="utf-8",
    )
    runner_mod.write_checkpoint(
        projects,
        project_id,
        "idea",
        "awaiting_human",
        {"brief": sample_artifact("brief")},
        pipeline_type="documentary-montage",
        review={"summary": "Sẵn sàng duyệt"},
        metadata={"runner": "claude"},
    )
    (project / "agent_run.json").write_text(
        json.dumps({
            "project_id": project_id,
            "status": "awaiting_human",
            "agent": "claude",
            "model": "claude-sonnet",
            "brief": "Tạo một video phóng sự ngắn.",
        }),
        encoding="utf-8",
    )
    return projects, project


def test_review_gate_approves_and_resumes_with_same_agent(tmp_path, monkeypatch):
    projects, project = _make_review_gate_project(tmp_path, "approve-in-app")
    monkeypatch.setattr(state_mod, "PROJECTS_DIR", projects)
    captured = {}

    def fake_start_run(project_id, **kwargs):
        captured.update({"project_id": project_id, **kwargs})
        return {"project_id": project_id, "status": "running", "agent": kwargs["agent"]}

    monkeypatch.setattr(runner_mod, "start_run", fake_start_run)

    result = runner_mod.review_gate(
        "approve-in-app",
        stage="idea",
        action="approve",
        note="Duyệt phương án này.",
    )

    checkpoint = json.loads((project / "checkpoint_idea.json").read_text(encoding="utf-8"))
    assert result["resumed"] is True
    assert checkpoint["status"] == "completed"
    assert checkpoint["human_approved"] is True
    assert checkpoint["metadata"]["reviewed_via"] == "backlot_app"
    assert checkpoint["metadata"]["review_note"] == "Duyệt phương án này."
    assert captured["agent"] == "claude"
    assert captured["model"] == "claude-sonnet"
    assert captured["review_feedback"] is None
    assert list((project / "history").glob("checkpoint_idea_*.json"))


def test_review_gate_revision_passes_feedback_to_agent(tmp_path, monkeypatch):
    projects, project = _make_review_gate_project(tmp_path, "revise-in-app")
    monkeypatch.setattr(state_mod, "PROJECTS_DIR", projects)
    captured = {}

    def fake_start_run(project_id, **kwargs):
        captured.update({"project_id": project_id, **kwargs})
        return {"project_id": project_id, "status": "running", "agent": kwargs["agent"]}

    monkeypatch.setattr(runner_mod, "start_run", fake_start_run)

    result = runner_mod.review_gate(
        "revise-in-app",
        stage="idea",
        action="revise",
        note="Đổi tiêu đề sang tiếng Việt và giữ chi phí 0 USD.",
    )

    checkpoint = json.loads((project / "checkpoint_idea.json").read_text(encoding="utf-8"))
    assert result["resumed"] is True
    assert checkpoint["status"] == "failed"
    assert checkpoint["human_approved"] is False
    assert "0 USD" in checkpoint["error"]
    assert "0 USD" in captured["review_feedback"]
    assert captured["agent"] == "claude"


def test_review_gate_revision_requires_note(tmp_path, monkeypatch):
    projects, _ = _make_review_gate_project(tmp_path, "revise-note-required")
    monkeypatch.setattr(state_mod, "PROJECTS_DIR", projects)

    try:
        runner_mod.review_gate(
            "revise-note-required",
            stage="idea",
            action="revise",
            note=" ",
        )
    except ValueError as exc:
        assert "nhập nội dung" in str(exc)
    else:
        raise AssertionError("Revision without feedback must be rejected")


def test_review_gate_queues_resume_until_active_agent_exits(tmp_path, monkeypatch):
    projects, project = _make_review_gate_project(tmp_path, "queued-review")
    monkeypatch.setattr(state_mod, "PROJECTS_DIR", projects)
    captured = {}

    class ActiveProcess:
        pid = 55667

        def poll(self):
            return None

        def wait(self):
            return 0

    process = ActiveProcess()
    (project / "agent_run.json").write_text(
        json.dumps({
            "project_id": "queued-review",
            "status": "running",
            "agent": "claude",
            "brief": "Tạo một video phóng sự ngắn.",
            "pid": process.pid,
        }),
        encoding="utf-8",
    )
    monkeypatch.setitem(runner_mod._PROCESSES, "queued-review", process)

    def fake_start_run(project_id, **kwargs):
        captured.update({"project_id": project_id, **kwargs})
        return {"project_id": project_id, "status": "running", "agent": kwargs["agent"]}

    monkeypatch.setattr(runner_mod, "start_run", fake_start_run)

    result = runner_mod.review_gate(
        "queued-review",
        stage="idea",
        action="approve",
    )
    queued = json.loads((project / "agent_run.json").read_text(encoding="utf-8"))

    assert result["queued"] is True
    assert "pending_review_resume" in queued
    assert captured == {}

    runner_mod._watch_process("queued-review", project, process)

    assert captured["project_id"] == "queued-review"
    assert captured["agent"] == "claude"


def test_review_gate_materializes_artifact_path_before_approval(tmp_path, monkeypatch):
    projects, project = _make_review_gate_project(tmp_path, "path-artifact-review")
    monkeypatch.setattr(state_mod, "PROJECTS_DIR", projects)
    checkpoint_path = project / "checkpoint_idea.json"
    checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    brief = checkpoint["artifacts"]["brief"]
    brief["cta"] = None
    artifact_path = project / "artifacts" / "brief.json"
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    artifact_path.write_text(json.dumps(brief), encoding="utf-8")
    checkpoint["artifacts"]["brief"] = "artifacts/brief.json"
    checkpoint_path.write_text(json.dumps(checkpoint), encoding="utf-8")

    monkeypatch.setattr(
        runner_mod,
        "start_run",
        lambda project_id, **kwargs: {
            "project_id": project_id,
            "status": "running",
            "agent": kwargs["agent"],
        },
    )

    result = runner_mod.review_gate(
        "path-artifact-review",
        stage="idea",
        action="approve",
    )

    approved = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    assert result["resumed"] is True
    assert approved["status"] == "completed"
    assert approved["artifacts"]["brief"] == brief


def test_review_gate_normalizes_documentary_acts_scene_plan(tmp_path, monkeypatch):
    from tests.contracts.test_phase0_contracts import sample_artifact

    projects = tmp_path / "projects"
    project = projects / "legacy-scene-review"
    artifact_dir = project / "artifacts"
    artifact_dir.mkdir(parents=True)
    (project / "project.json").write_text(
        json.dumps({
            "project_id": "legacy-scene-review",
            "title": "Legacy Scene Review",
            "pipeline_type": "documentary-montage",
            "brief": "Tạo phóng sự ngắn.",
        }),
        encoding="utf-8",
    )
    brief = sample_artifact("brief")
    brief["metadata"] = {
        "documentary_montage": {"thematic_question": "Điều gì tạo nên một đất nước?"}
    }
    (artifact_dir / "brief.json").write_text(json.dumps(brief), encoding="utf-8")
    runner_mod.write_checkpoint(
        projects,
        "legacy-scene-review",
        "idea",
        "completed",
        {"brief": brief},
        pipeline_type="documentary-montage",
        human_approved=True,
    )
    legacy_scene_plan = {
        "version": "1.0",
        "tone": "reverent",
        "shape": "three-act",
        "total_duration_seconds": 12,
        "acts": [{
            "id": "act_1",
            "scenes": [
                {
                    "id": "s01",
                    "time_in": 0,
                    "time_out": 6,
                    "duration": 6,
                    "description": "Cánh đồng rộng lúc bình minh.",
                    "motion": "slow_push_in",
                    "cut_to_next": "dissolve",
                    "search_query": "field sunrise aerial",
                    "source_candidates": [
                        {"source": "pexels", "query": "wide field sunrise"},
                        {"source": "archive_org", "query": "historic farm field"},
                    ],
                },
                {
                    "id": "s02",
                    "time_in": 6,
                    "time_out": 12,
                    "duration": 6,
                    "description": "Đôi tay người thợ trên cầu thép.",
                    "search_query": "worker hands steel",
                    "source_candidates": [
                        {"source": "pexels", "query": "steel worker hands"},
                    ],
                },
            ],
        }],
    }
    scene_path = artifact_dir / "scene_plan.json"
    scene_path.write_text(json.dumps(legacy_scene_plan), encoding="utf-8")
    (project / "checkpoint_scene_plan.json").write_text(
        json.dumps({
            "version": "1.0",
            "project_id": "legacy-scene-review",
            "pipeline_type": "documentary-montage",
            "stage": "scene_plan",
            "status": "awaiting_human",
            "timestamp": "2026-09-23T00:00:00+00:00",
            "checkpoint_policy": "guided",
            "human_approval_required": True,
            "human_approved": False,
            "artifacts": {"scene_plan": "artifacts/scene_plan.json"},
        }),
        encoding="utf-8",
    )
    (project / "agent_run.json").write_text(
        json.dumps({
            "project_id": "legacy-scene-review",
            "status": "awaiting_human",
            "agent": "claude",
            "brief": "Tạo phóng sự ngắn.",
        }),
        encoding="utf-8",
    )
    monkeypatch.setattr(state_mod, "PROJECTS_DIR", projects)
    monkeypatch.setattr(
        runner_mod,
        "start_run",
        lambda project_id, **kwargs: {"project_id": project_id, "status": "running"},
    )

    result = runner_mod.review_gate(
        "legacy-scene-review",
        stage="scene_plan",
        action="approve",
    )

    checkpoint = json.loads((project / "checkpoint_scene_plan.json").read_text(encoding="utf-8"))
    persisted = json.loads(scene_path.read_text(encoding="utf-8"))
    assert result["resumed"] is True
    assert checkpoint["status"] == "completed"
    assert len(checkpoint["artifacts"]["scene_plan"]["scenes"]) == 2
    assert checkpoint["artifacts"]["scene_plan"]["metadata"]["slots"][0]["queries"]
    assert persisted == checkpoint["artifacts"]["scene_plan"]


def test_review_gate_rejects_asset_manifest_with_missing_files(tmp_path, monkeypatch):
    projects = tmp_path / "projects"
    project = projects / "missing-assets-review"
    (project / "artifacts").mkdir(parents=True)
    (project / "project.json").write_text(
        json.dumps({
            "project_id": "missing-assets-review",
            "title": "Missing Assets",
            "pipeline_type": "documentary-montage",
            "brief": "Tạo phóng sự ngắn.",
        }),
        encoding="utf-8",
    )
    manifest = {
        "version": "1.0",
        "assets": [{
            "id": "asset_s01",
            "type": "video",
            "path": "assets/video/s01.mp4",
            "source_tool": "direct_clip_search",
            "scene_id": "s01",
            "provider": "pexels",
            "license": "Pexels License",
            "original_url": "https://www.pexels.com/video/example-123456/",
        }],
    }
    (project / "artifacts" / "asset_manifest.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )
    (project / "checkpoint_assets.json").write_text(
        json.dumps({
            "version": "1.0",
            "project_id": "missing-assets-review",
            "pipeline_type": "documentary-montage",
            "stage": "assets",
            "status": "awaiting_human",
            "timestamp": "2026-09-23T00:00:00+00:00",
            "checkpoint_policy": "guided",
            "human_approval_required": True,
            "human_approved": False,
            "artifacts": {"asset_manifest": "artifacts/asset_manifest.json"},
        }),
        encoding="utf-8",
    )
    monkeypatch.setattr(state_mod, "PROJECTS_DIR", projects)

    try:
        runner_mod.review_gate(
            "missing-assets-review",
            stage="assets",
            action="approve",
        )
    except ValueError as exc:
        assert "Tải tài nguyên 0 USD" in str(exc)
        assert "1/1" in str(exc)
    else:
        raise AssertionError("Asset approval must require real files")

    checkpoint = json.loads((project / "checkpoint_assets.json").read_text(encoding="utf-8"))
    assert checkpoint["status"] == "awaiting_human"
