"""Optional local bridge from Backlot to an installed coding agent.

Backlot remains a file-backed board. This module only starts the user's chosen
agent with a generated production brief; the agent is still responsible for
reading the pipeline manifest, calling tools, and writing checkpoints.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backlot import state as state_mod
from lib.paths import REPO_ROOT
from lib.checkpoint import get_pipeline_stages, write_checkpoint
from lib.events import emit_event

RUN_FILENAME = "agent_run.json"
PROMPT_FILENAME = "agent_prompt.md"
LOG_FILENAME = "agent_run.log"
MAX_BRIEF_LENGTH = 12_000

_PROCESS_LOCK = threading.Lock()
_PROCESSES: dict[str, subprocess.Popen] = {}
_LOG_HANDLES: dict[str, Any] = {}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _run_path(project_dir: Path) -> Path:
    return project_dir / RUN_FILENAME


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _write_json(path: Path, value: dict[str, Any]) -> None:
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(temp, path)


def _pid_alive(pid: Any) -> bool:
    if not isinstance(pid, int) or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except (OSError, ProcessLookupError):
        return False
    return True


def _refresh_run(project_id: str, project_dir: Path, run: dict[str, Any] | None) -> dict[str, Any]:
    if not run:
        return {"project_id": project_id, "status": "idle"}
    if run.get("status") in {"starting", "running"}:
        process = _PROCESSES.get(project_id)
        if process is not None and process.poll() is None:
            return run
        if _pid_alive(run.get("pid")):
            return run
        run = {
            **run,
            "status": "failed",
            "finished_at": run.get("finished_at") or _now(),
            "error": "Agent đã dừng trước khi ghi nhận hoàn tất.",
        }
        _write_json(_run_path(project_dir), run)
    return run


def get_run(project_id: str) -> dict[str, Any]:
    project_dir = state_mod.PROJECTS_DIR / project_id
    return _refresh_run(project_id, project_dir, _read_json(_run_path(project_dir)))


def available_agents() -> list[dict[str, Any]]:
    agents = []
    for name, label in (("codex", "Codex"), ("claude", "Claude Code")):
        executable = shutil.which(name)
        agents.append({"name": name, "label": label, "available": bool(executable)})
    return agents


def _resolve_agent(requested: str | None) -> tuple[str, str]:
    choice = (requested or "auto").strip().lower()
    if choice not in {"auto", "codex", "claude"}:
        raise ValueError("Agent không hợp lệ")
    candidates = ("codex", "claude") if choice == "auto" else (choice,)
    for name in candidates:
        executable = shutil.which(name)
        if executable:
            return name, executable
    raise ValueError("Chưa tìm thấy Codex hoặc Claude Code trên máy này")


def _load_marker(project_dir: Path) -> dict[str, Any]:
    marker = _read_json(project_dir / "project.json")
    if not marker:
        raise ValueError("Không đọc được project.json")
    return marker


def _build_prompt(project_id: str, project_dir: Path, marker: dict[str, Any], brief: str) -> str:
    pipeline_type = marker.get("pipeline_type") or "unknown"
    return f"""# MOSA TOOL ALL — bắt đầu production

Bạn là agent điều phối workflow cho MOSA TOOL ALL. Hãy thực hiện production thật,
không chỉ mô phỏng trạng thái.

## Dự án
- project_id: `{project_id}`
- tên: {marker.get("title") or project_id}
- pipeline: `{pipeline_type}`
- workspace: `{project_dir}`
- repository/runtime root: `{REPO_ROOT}`

## Brief người dùng
{brief}

## Giao thức bắt buộc
1. Đọc manifest tại `pipeline_defs/{pipeline_type}.yaml` và executive-producer skill tương ứng.
2. Dùng workspace `{project_dir}` cho mọi checkpoint, artifact, asset và render của dự án.
3. Tuân thủ checkpoint protocol, schema artifact, review và cổng duyệt; không đánh dấu stage gated
   là completed nếu chưa có phê duyệt rõ ràng của người dùng.
4. Ưu tiên provider/local runtime đã cấu hình trong MOSA TOOL ALL; không tự phát sinh chi phí ngoài
   budget hoặc gọi provider chưa được cấu hình.
5. Cập nhật checkpoint và events thường xuyên để bảng Backlot hiển thị tiến độ. Nếu thiếu input/API,
   ghi stage `awaiting_human` hoặc `failed` với lý do cụ thể, không tạo dữ liệu giả.
6. Khi kết thúc, để lại artifact và checkpoint hợp lệ trong workspace. Không sửa file ứng dụng,
   không xoá dữ liệu ngoài workspace.

Bắt đầu từ stage kế tiếp còn thiếu của pipeline và tiếp tục cho đến checkpoint hợp lệ đầu tiên hoặc
điểm duyệt cần người dùng xác nhận.
"""


def _command(
    agent: str,
    executable: str,
    project_dir: Path,
    model: str | None,
    allow_automation: bool,
    prompt: str,
) -> list[str]:
    if not allow_automation:
        raise ValueError("Hãy bật 'Cho phép agent chạy lệnh tự động' trước khi bắt đầu")

    if agent == "codex":
        command = [
            executable,
            "exec",
            "--json",
            "--skip-git-repo-check",
            "--sandbox",
            "workspace-write",
            "--dangerously-bypass-approvals-and-sandbox",
            "-C",
            str(project_dir),
            "--add-dir",
            str(REPO_ROOT),
        ]
        if model:
            command.extend(["--model", model])
        command.append(prompt)
        return command

    command = [
        executable,
        "--print",
        "--output-format",
        "stream-json",
        "--permission-mode",
        "auto",
        "--add-dir",
        str(REPO_ROOT),
    ]
    if model:
        command.extend(["--model", model])
    command.append(prompt)
    return command


def _watch_process(project_id: str, project_dir: Path, process: subprocess.Popen) -> None:
    return_code = process.wait()
    with _PROCESS_LOCK:
        _PROCESSES.pop(project_id, None)
        handle = _LOG_HANDLES.pop(project_id, None)
    if handle is not None:
        handle.close()

    run = _read_json(_run_path(project_dir)) or {"project_id": project_id}
    run.update({
        "status": "completed" if return_code == 0 else "failed",
        "finished_at": _now(),
        "exit_code": return_code,
    })
    if return_code != 0:
        run["error"] = f"Agent kết thúc với mã lỗi {return_code}. Xem agent_run.log để biết chi tiết."
    _write_json(_run_path(project_dir), run)
    emit_event(project_dir, {
        "tool": f"agent:{run.get('agent', 'unknown')}",
        "event": "finish" if return_code == 0 else "error",
        "status": run["status"],
        "exit_code": return_code,
    })


def start_run(
    project_id: str,
    *,
    brief: str,
    agent: str | None = None,
    model: str | None = None,
    allow_automation: bool = False,
) -> dict[str, Any]:
    project_dir = state_mod.PROJECTS_DIR / project_id
    if not project_dir.is_dir():
        raise ValueError("Không tìm thấy workspace của dự án")
    if not isinstance(brief, str):
        raise ValueError("Brief phải là văn bản")
    if model is not None and not isinstance(model, str):
        raise ValueError("Model phải là văn bản")
    if not isinstance(allow_automation, bool):
        raise ValueError("allow_automation phải là boolean")
    brief = brief.strip()
    model = model.strip() if isinstance(model, str) else None
    if not brief:
        raise ValueError("Hãy mô tả video cần sản xuất trước khi bắt đầu")
    if len(brief) > MAX_BRIEF_LENGTH:
        raise ValueError(f"Brief quá dài, tối đa {MAX_BRIEF_LENGTH} ký tự")

    current = get_run(project_id)
    if current.get("status") in {"starting", "running"}:
        raise ValueError("Workflow của dự án này đang chạy")

    marker = _load_marker(project_dir)
    resolved_agent, executable = _resolve_agent(agent)
    prompt = _build_prompt(project_id, project_dir, marker, brief)
    command = _command(resolved_agent, executable, project_dir, model, allow_automation, prompt)
    (project_dir / PROMPT_FILENAME).write_text(prompt, encoding="utf-8")
    marker["brief"] = brief
    _write_json(project_dir / "project.json", marker)

    run: dict[str, Any] = {
        "project_id": project_id,
        "status": "starting",
        "agent": resolved_agent,
        "model": model or None,
        "brief": brief,
        "prompt_file": PROMPT_FILENAME,
        "log_file": LOG_FILENAME,
        "started_at": _now(),
    }
    _write_json(_run_path(project_dir), run)
    emit_event(project_dir, {"tool": f"agent:{resolved_agent}", "event": "start", "status": "starting"})

    first_stage = get_pipeline_stages(marker.get("pipeline_type"))[0]
    try:
        write_checkpoint(
            state_mod.PROJECTS_DIR,
            project_id,
            first_stage,
            "in_progress",
            {},
            pipeline_type=marker.get("pipeline_type"),
            metadata={"runner": resolved_agent, "run_started_at": run["started_at"]},
        )
    except Exception as exc:
        run["status"] = "failed"
        run["error"] = f"Không khởi tạo được checkpoint đầu tiên: {exc}"
        run["finished_at"] = _now()
        _write_json(_run_path(project_dir), run)
        raise ValueError(run["error"]) from exc

    env = os.environ.copy()
    env["OPENMONTAGE_PROJECTS_DIR"] = str(state_mod.PROJECTS_DIR)
    env["PYTHONPATH"] = os.pathsep.join(
        part for part in (str(REPO_ROOT), env.get("PYTHONPATH", "")) if part
    )
    try:
        log_handle = open(project_dir / LOG_FILENAME, "a", encoding="utf-8")
        kwargs: dict[str, Any] = {
            "cwd": str(project_dir),
            "env": env,
            "stdin": subprocess.DEVNULL,
            "stdout": log_handle,
            "stderr": subprocess.STDOUT,
        }
        if os.name == "nt":
            kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        else:
            kwargs["start_new_session"] = True
        process = subprocess.Popen(command, **kwargs)
    except (OSError, ValueError) as exc:
        if "log_handle" in locals():
            log_handle.close()
        run["status"] = "failed"
        run["error"] = f"Không khởi chạy được {resolved_agent}: {exc}"
        run["finished_at"] = _now()
        _write_json(_run_path(project_dir), run)
        try:
            write_checkpoint(
                state_mod.PROJECTS_DIR,
                project_id,
                first_stage,
                "failed",
                {},
                pipeline_type=marker.get("pipeline_type"),
                error=run["error"],
            )
        except Exception:
            pass
        raise ValueError(run["error"]) from exc

    run.update({"status": "running", "pid": process.pid, "command": [executable, resolved_agent]})
    _write_json(_run_path(project_dir), run)
    with _PROCESS_LOCK:
        _PROCESSES[project_id] = process
        _LOG_HANDLES[project_id] = log_handle
    threading.Thread(
        target=_watch_process,
        args=(project_id, project_dir, process),
        name=f"mosa-agent-{project_id}",
        daemon=True,
    ).start()
    return run
