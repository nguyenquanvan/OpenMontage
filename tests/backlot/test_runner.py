"""Tests for the optional in-app agent runner bridge."""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta, timezone

import pytest

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
    popen_kwargs = {}

    def fake_popen(*args, **kwargs):
        popen_kwargs.update(kwargs)
        return _FinishedProcess()

    monkeypatch.setattr(runner_mod.subprocess, "Popen", fake_popen)
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
    assert popen_kwargs["env"]["PYTHONUTF8"] == "1"
    assert popen_kwargs["env"]["PYTHONIOENCODING"] == "utf-8"


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


def test_run_note_from_the_start_form_reaches_the_agent_prompt(tmp_path, monkeypatch):
    projects = tmp_path / "projects"
    projects.mkdir()
    monkeypatch.setattr(state_mod, "PROJECTS_DIR", projects)
    monkeypatch.setattr(server_mod, "PROJECTS_DIR", projects)
    monkeypatch.setattr(server_mod, "_summary_cache", {})
    monkeypatch.setattr(server_mod, "_PROJECTS_ROOT_STR", os.path.normcase(str(projects.resolve())))
    monkeypatch.setattr(runner_mod.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(runner_mod.subprocess, "Popen", lambda *args, **kwargs: _FinishedProcess())
    monkeypatch.setattr(runner_mod, "_watch_process", lambda *args: None)

    async def no_watch():
        return None

    monkeypatch.setattr(server_mod, "_watch_projects", no_watch)
    note = "Dùng ComfyUI đang chạy ở máy này, đổi sang FLUX.1 schnell."
    with TestClient(server_mod.create_app()) as client:
        assert client.post(
            "/api/projects",
            json={"project_id": "note-test", "title": "Note", "pipeline_type": "cinematic"},
        ).status_code == 201
        too_long = client.post(
            "/api/project/note-test/run",
            json={"brief": "Phim ngắn", "run_note": "x" * 4001, "agent": "codex", "allow_automation": True},
        )
        assert too_long.status_code == 400
        started = client.post(
            "/api/project/note-test/run",
            json={"brief": "Phim ngắn về sói", "run_note": f"  {note}  ", "agent": "codex", "allow_automation": True},
        )
        assert started.status_code == 202

    project = projects / "note-test"
    prompt = (project / "agent_prompt.md").read_text(encoding="utf-8")
    assert "## Ghi chú của người dùng cho lần chạy này" in prompt
    assert note in prompt
    assert prompt.index("## Brief người dùng") < prompt.index(note) < prompt.index("## Giao thức bắt buộc")
    assert json.loads((project / "agent_run.json").read_text(encoding="utf-8"))["run_note"] == note
    assert json.loads((project / "project.json").read_text(encoding="utf-8"))["brief"] == "Phim ngắn về sói"
    checkpoint = json.loads((project / "checkpoint_research.json").read_text(encoding="utf-8"))
    assert checkpoint["metadata"]["run_note"] == note


def _gate_prompt(tmp_path, monkeypatch, **kwargs):
    projects = tmp_path / "projects"
    project = projects / "gate-test"
    project.mkdir(parents=True)
    (project / "project.json").write_text(
        json.dumps({"project_id": "gate-test", "title": "Gate Test", "pipeline_type": "health-infographic"}),
        encoding="utf-8",
    )
    monkeypatch.setattr(state_mod, "PROJECTS_DIR", projects)
    monkeypatch.setattr(runner_mod.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(runner_mod, "get_next_stage", lambda *args: "proposal")
    monkeypatch.setattr(runner_mod.subprocess, "Popen", lambda *args, **kwargs: _FinishedProcess())
    monkeypatch.setattr(runner_mod, "_watch_process", lambda *args: None)
    runner_mod.start_run("gate-test", brief="Video bảng phấn 20 phút", agent="codex", allow_automation=True, **kwargs)
    return project, (project / "agent_prompt.md").read_text(encoding="utf-8")


def test_runs_stop_at_every_gate_by_default(tmp_path, monkeypatch):
    project, prompt = _gate_prompt(tmp_path, monkeypatch)

    assert "trình bày nội dung cần duyệt, rồi mới dừng" in prompt
    assert "approval_policy" not in prompt
    assert "auto_approve" not in json.loads((project / "agent_run.json").read_text(encoding="utf-8"))


def test_auto_approve_pre_authorizes_every_gate_of_the_run(tmp_path, monkeypatch):
    project, prompt = _gate_prompt(tmp_path, monkeypatch, auto_approve=True)

    assert "## Người dùng duyệt trước toàn bộ lượt chạy" in prompt
    assert '`category: "approval_policy"`' in prompt
    assert "`human_approved=True`" in prompt
    assert "rồi mới dừng" not in prompt
    assert "vượt ngân sách" in prompt
    assert json.loads((project / "agent_run.json").read_text(encoding="utf-8"))["auto_approve"] is True
    checkpoint = json.loads((project / "checkpoint_proposal.json").read_text(encoding="utf-8"))
    assert checkpoint["metadata"]["auto_approve"] is True


def test_auto_approve_must_be_a_boolean(tmp_path, monkeypatch):
    with pytest.raises(ValueError, match="auto_approve"):
        _gate_prompt(tmp_path, monkeypatch, auto_approve="yes")


def test_run_api_passes_auto_approve_to_the_runner(tmp_path, monkeypatch):
    projects = tmp_path / "projects"
    (projects / "api-gate").mkdir(parents=True)
    monkeypatch.setattr(server_mod, "PROJECTS_DIR", projects)
    monkeypatch.setattr(server_mod, "_PROJECTS_ROOT_STR", os.path.normcase(str(projects.resolve())))
    seen = {}

    def fake_start_run(project_id, **kwargs):
        seen.update(kwargs)
        return {"project_id": project_id, "status": "starting"}

    async def no_watch():
        return None

    monkeypatch.setattr(server_mod, "start_run", fake_start_run)
    monkeypatch.setattr(server_mod, "_watch_projects", no_watch)
    with TestClient(server_mod.create_app()) as client:
        response = client.post(
            "/api/project/api-gate/run",
            json={"brief": "Video", "agent": "codex", "allow_automation": True, "auto_approve": True},
        )
    assert response.status_code == 202
    assert seen["auto_approve"] is True


def test_approval_policy_decisions_validate() -> None:
    from schemas.artifacts import validate_artifact

    validate_artifact("decision_log", {
        "version": "1.0",
        "project_id": "gate-test",
        "decisions": [{
            "decision_id": "d-approval",
            "stage": "research",
            "category": "approval_policy",
            "subject": "Chạy thẳng",
            "options_considered": [{"option_id": "auto", "label": "Duyệt trước toàn bộ", "score": 1.0,
                                    "reason": "Người dùng chọn từ form chạy."}],
            "selected": "auto",
            "reason": "Người dùng bật Chạy thẳng đến video cuối.",
            "confidence": 1.0,
        }],
    })


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


def test_windows_claude_uses_native_binary_instead_of_npm_cmd(tmp_path, monkeypatch):
    npm_bin = tmp_path / "npm"
    native = npm_bin / "node_modules" / "@anthropic-ai" / "claude-code" / "bin" / "claude.exe"
    native.parent.mkdir(parents=True)
    native.touch()
    monkeypatch.setattr(runner_mod.shutil, "which", lambda name: str(npm_bin / "claude.cmd"))
    monkeypatch.setattr(runner_mod.sys, "platform", "win32")

    assert runner_mod._agent_executable("claude") == str(native)


def test_starting_run_is_not_failed_before_pid_is_recorded(tmp_path, monkeypatch):
    monkeypatch.setattr(runner_mod, "_pid_alive", lambda pid: False)
    run = {"project_id": "startup-race", "status": "starting", "started_at": runner_mod._now()}

    result = runner_mod._refresh_run("startup-race", tmp_path, run)

    assert result["status"] == "starting"
    assert not (tmp_path / runner_mod.RUN_FILENAME).exists()


def test_stale_starting_run_is_failed(tmp_path, monkeypatch):
    monkeypatch.setattr(runner_mod, "_pid_alive", lambda pid: False)
    started = (datetime.now(timezone.utc) - timedelta(minutes=2)).isoformat()
    run = {"project_id": "stale-startup", "status": "starting", "started_at": started}

    result = runner_mod._refresh_run("stale-startup", tmp_path, run)

    assert result["status"] == "failed"


@pytest.mark.skipif(sys.platform != "win32", reason="Windows process detection")
def test_windows_pid_alive_detects_running_and_missing_process():
    assert runner_mod._pid_alive(os.getpid()) is True
    assert runner_mod._pid_alive(2_147_483_647) is False


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


def test_agent_blocker_reason_is_reported_and_the_desktop_is_told(tmp_path, monkeypatch):
    project = tmp_path / "projects" / "blocked"
    project.mkdir(parents=True)
    (project / "project.json").write_text(
        json.dumps({"project_id": "blocked", "pipeline_type": "character-animation"}), encoding="utf-8"
    )
    (project / "agent_run.json").write_text(
        json.dumps({"project_id": "blocked", "status": "running", "agent": "codex"}), encoding="utf-8"
    )
    blocker = "Required tool skills missing: character-rigging. No rig generated."
    runner_mod.write_checkpoint(
        project.parent, "blocked", "rig_plan", "failed", {},
        pipeline_type="character-animation", error=blocker,
    )
    monkeypatch.setattr(runner_mod, "get_next_stage", lambda *args: "rig_plan")
    heard = []
    monkeypatch.setattr(runner_mod.notifications, "_listeners", [lambda *args: heard.append(args)])

    runner_mod._watch_process("blocked", project, _FinishedProcess())

    run = json.loads((project / "agent_run.json").read_text(encoding="utf-8"))
    assert run["status"] == "failed"
    assert run["error"] == f"Agent dừng ở stage 'rig_plan': {blocker}"
    assert heard == [("blocked", "failed", run["error"])]


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


def _write_stream_json_log(project, events):
    project.mkdir(parents=True)
    (project / "agent_run.log").write_text(
        "".join(json.dumps(event, ensure_ascii=False) + "\n" for event in events),
        encoding="utf-8",
    )


_CLAUDE_INIT_EVENT = {
    "type": "system",
    "subtype": "init",
    "session_id": "9b2e4c1a-401f-4d3b-8c2a-5e6f70401a2b",
    "tools": ["Bash", "Read", "Write"],
    "skills": ["anthropic-skills:deep-research", "anthropic-skills:doc-coauthoring"],
    "uuid": "c3d401e2-0a1b-4c5d-9e8f-401401401401",
}


def test_stream_json_noise_is_not_reported_as_auth_or_usage_failure(tmp_path):
    project = tmp_path / "projects" / "noisy-success-run"
    _write_stream_json_log(project, [
        _CLAUDE_INIT_EVENT,
        {
            "type": "user",
            "message": {"content": [{
                "type": "tool_result",
                "tool_use_id": "toolu_01",
                "content": "GET /v1/clips 401 Unauthorized (oauth scope)\nPexels usage limit 80%\nLỖI: thử nguồn khác",
            }]},
            "uuid": "e401b2c3-1d2e-4f5a-8b9c-0d1e2f3a4b5c",
        },
        {
            "type": "result",
            "subtype": "success",
            "is_error": False,
            "stop_reason": "end_turn",
            "result": "Phim đã render xong, đang chờ bạn duyệt.",
            "session_id": "9b2e4c1a-401f-4d3b-8c2a-5e6f70401a2b",
        },
    ])

    message = runner_mod._run_failure_detail(project, "generic failure")

    assert message == "generic failure"


def test_claude_stream_json_auth_failure_result_is_reported_actionably(tmp_path):
    project = tmp_path / "projects" / "claude-stream-auth-run"
    api_error = (
        'Failed to authenticate. API Error: 401 {"type":"error","error":{"type":"authentication_error",'
        '"message":"OAuth access token is invalid"},"request_id":"req_011CU9"}'
    )
    _write_stream_json_log(project, [
        _CLAUDE_INIT_EVENT,
        {
            "type": "assistant",
            "message": {"content": [{"type": "text", "text": api_error}]},
            "error": "authentication_failed",
        },
        {
            "type": "result",
            "subtype": "success",
            "is_error": True,
            "api_error_status": 401,
            "result": api_error,
        },
    ])

    message = runner_mod._run_failure_detail(project, "generic failure")

    assert "Claude Code chưa xác thực" in message
    assert "claude auth login" in message


def test_codex_turn_failed_usage_limit_is_reported_actionably(tmp_path):
    project = tmp_path / "projects" / "codex-quota-run"
    _write_stream_json_log(project, [
        {"type": "thread.started", "thread_id": "0199a401-7c2e-7d10-9a3b-5e6f7a8b9c0d"},
        {
            "type": "turn.failed",
            "error": {"message": "You've hit your usage limit. Try again in 3 days."},
        },
    ])

    message = runner_mod._run_failure_detail(project, "generic failure")

    assert "hết hạn mức sử dụng" in message


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


def test_review_gate_normalizes_documentary_timeline_edit_decisions(tmp_path, monkeypatch):
    from lib import checkpoint as checkpoint_mod
    from schemas.artifacts import validate_artifact

    projects = tmp_path / "projects"
    project = projects / "legacy-edit-review"
    artifact_dir = project / "artifacts"
    artifact_dir.mkdir(parents=True)
    (project / "project.json").write_text(
        json.dumps({
            "project_id": "legacy-edit-review",
            "title": "Legacy Edit Review",
            "pipeline_type": "documentary-montage",
            "brief": "Tạo phóng sự ngắn.",
        }),
        encoding="utf-8",
    )
    legacy_edit = {
        "version": "1.0",
        "project_id": "legacy-edit-review",
        "pipeline_type": "documentary-montage",
        "renderer_family": "documentary-montage",
        "render_runtime": "remotion",
        "total_duration_seconds": 6,
        "canvas": "1920x1080",
        "frame_rate": 24,
        "cuts": [{
            "cut_id": "c01",
            "scene_id": "s01",
            "asset_id": "asset_s01",
            "asset_path": "assets/video/s01.mp4",
            "timeline_in": 0,
            "timeline_out": 6,
            "source_in": 1,
            "source_out": 7,
            "duration_seconds": 6,
            "movement": "slow_push_in",
            "transition_in": "fade_from_black",
            "transition_out": "fade_to_black",
            "reason": "Hero opening",
        }],
        "music": {
            "asset_id": "asset_music_bed",
            "asset_path": "assets/music/bed.mp3",
            "volume_db": -12,
            "fade_in_seconds": 1,
            "fade_out_seconds": 2,
        },
        "end_tag": {"offset_seconds": 5, "text": "THE END"},
        "metadata": {"tone": "reverent"},
    }
    edit_path = artifact_dir / "edit_decisions.json"
    edit_path.write_text(json.dumps(legacy_edit), encoding="utf-8")
    (project / "checkpoint_edit.json").write_text(
        json.dumps({
            "version": "1.0",
            "project_id": "legacy-edit-review",
            "pipeline_type": "documentary-montage",
            "stage": "edit",
            "status": "awaiting_human",
            "timestamp": "2026-09-23T00:00:00+00:00",
            "checkpoint_policy": "guided",
            "human_approval_required": True,
            "human_approved": False,
            "artifacts": {"edit_decisions": "artifacts/edit_decisions.json"},
        }),
        encoding="utf-8",
    )
    (project / "agent_run.json").write_text(
        json.dumps({
            "project_id": "legacy-edit-review",
            "status": "awaiting_human",
            "agent": "claude",
            "brief": "Tạo phóng sự ngắn.",
        }),
        encoding="utf-8",
    )
    monkeypatch.setattr(state_mod, "PROJECTS_DIR", projects)
    # This test isolates legacy artifact normalization. Stage prerequisite
    # enforcement is covered independently by checkpoint contract tests.
    monkeypatch.setattr(checkpoint_mod, "_enforce_stage_prerequisites", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        runner_mod,
        "start_run",
        lambda project_id, **kwargs: {"project_id": project_id, "status": "running"},
    )

    result = runner_mod.review_gate("legacy-edit-review", stage="edit", action="approve")

    checkpoint = json.loads((project / "checkpoint_edit.json").read_text(encoding="utf-8"))
    persisted = json.loads(edit_path.read_text(encoding="utf-8"))
    normalized = checkpoint["artifacts"]["edit_decisions"]
    validate_artifact("edit_decisions", normalized)
    assert result["resumed"] is True
    assert checkpoint["status"] == "completed"
    assert normalized["cuts"][0]["id"] == "c01"
    assert normalized["cuts"][0]["source"] == "asset_s01"
    assert normalized["audio"]["music"]["volume"] < 0.3
    assert normalized["metadata"]["end_tag"]["text"] == "THE END"
    assert persisted == normalized


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


def test_review_gate_cannot_approve_a_blocker_checkpoint_without_artifacts(tmp_path, monkeypatch):
    """An agent that pauses on a blocker leaves awaiting_human with no artifact; approve explains why it cannot proceed."""
    projects = tmp_path / "projects"
    project = projects / "blocked"
    project.mkdir(parents=True)
    (project / "project.json").write_text(
        json.dumps({"project_id": "blocked", "title": "Blocked", "pipeline_type": "documentary-montage"}),
        encoding="utf-8",
    )
    # Hand-written like the agent's own blocker checkpoints: write_checkpoint()
    # would refuse an awaiting_human stage without its canonical artifact.
    (project / "checkpoint_idea.json").write_text(
        json.dumps({
            "version": "1.0",
            "project_id": "blocked",
            "pipeline_type": "documentary-montage",
            "stage": "idea",
            "status": "awaiting_human",
            "timestamp": "2026-10-14T01:27:06+00:00",
            "checkpoint_policy": "guided",
            "human_approval_required": True,
            "human_approved": False,
            "artifacts": {},
            "metadata": {"runner": "codex", "blocker_review_ref": "artifacts/idea_blocker_review.json"},
            "error": "Reference analysis blocked: missing yt_dlp",
        }, ensure_ascii=False),
        encoding="utf-8",
    )
    monkeypatch.setattr(state_mod, "PROJECTS_DIR", projects)
    monkeypatch.setattr(runner_mod, "start_run", lambda *args, **kwargs: pytest.fail("must not resume"))

    with pytest.raises(ValueError, match="không có tài liệu để duyệt.*missing yt_dlp.*Chạy lại với ghi chú"):
        runner_mod.review_gate("blocked", stage="idea", action="approve", note="")

    checkpoint = json.loads((project / "checkpoint_idea.json").read_text(encoding="utf-8"))
    assert checkpoint["status"] == "awaiting_human"
    assert checkpoint["human_approved"] is False


def _blocker_project(tmp_path, monkeypatch, *, auto_approve=True):
    projects = tmp_path / "projects"
    project = projects / "blocked"
    project.mkdir(parents=True)
    (project / "project.json").write_text(
        json.dumps({"project_id": "blocked", "title": "Blocked", "pipeline_type": "documentary-montage", "brief": "Phóng sự"}),
        encoding="utf-8",
    )
    (project / "checkpoint_idea.json").write_bytes(b"\xef\xbb\xbf" + json.dumps({
        "version": "1.0",
        "project_id": "blocked",
        "pipeline_type": "documentary-montage",
        "stage": "idea",
        "status": "awaiting_human",
        "timestamp": "2026-10-14T01:27:06+00:00",
        "checkpoint_policy": "guided",
        "human_approval_required": True,
        "human_approved": False,
        "artifacts": {},
        "metadata": {"runner": "codex"},
        "error": "Reference analysis blocked: missing yt_dlp",
    }, ensure_ascii=False).encode("utf-8"))
    (project / "agent_run.json").write_text(
        json.dumps({"project_id": "blocked", "status": "failed", "agent": "codex", "auto_approve": auto_approve}),
        encoding="utf-8",
    )
    monkeypatch.setattr(state_mod, "PROJECTS_DIR", projects)
    monkeypatch.setattr(runner_mod.shutil, "which", lambda name: f"/usr/bin/{name}")
    return project


def test_blocker_pause_is_read_with_a_bom_and_detected(tmp_path, monkeypatch):
    project = _blocker_project(tmp_path, monkeypatch)
    checkpoint = runner_mod._read_json(project / "checkpoint_idea.json")
    assert checkpoint["status"] == "awaiting_human"
    assert runner_mod._is_blocker_pause(checkpoint) is True
    assert runner_mod._is_blocker_pause({**checkpoint, "error": ""}) is False
    assert runner_mod._is_blocker_pause({**checkpoint, "artifacts": {"brief": {}}}) is False


def test_rerun_with_a_note_on_a_blocker_keeps_the_run_preapproved(tmp_path, monkeypatch):
    _blocker_project(tmp_path, monkeypatch)
    captured = {}

    def fake_start_run(project_id, **kwargs):
        captured.update(kwargs)
        return {"project_id": project_id, "status": "running", "agent": "codex"}

    monkeypatch.setattr(runner_mod, "start_run", fake_start_run)

    result = runner_mod.review_gate("blocked", stage="idea", action="revise", note="Bỏ qua video tham khảo.")

    assert result["resumed"] is True
    assert captured["run_note"] == "Bỏ qua video tham khảo."
    assert captured["review_feedback"] is None
    assert captured["auto_approve"] is True


def test_start_workflow_accepts_a_blocker_pause(tmp_path, monkeypatch):
    project = _blocker_project(tmp_path, monkeypatch)
    monkeypatch.setattr(runner_mod.subprocess, "Popen", lambda *args, **kwargs: _FinishedProcess())
    monkeypatch.setattr(runner_mod, "_watch_process", lambda *args: None)

    runner_mod.start_run("blocked", brief="Phóng sự", agent="codex", allow_automation=True, auto_approve=True)

    checkpoint = json.loads((project / "checkpoint_idea.json").read_text(encoding="utf-8"))
    assert checkpoint["status"] == "in_progress"
    assert list((project / "history").glob("checkpoint_idea_*.json"))
