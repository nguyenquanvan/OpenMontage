"""Optional local bridge from Backlot to an installed coding agent.

Backlot remains a file-backed board. This module only starts the user's chosen
agent with a generated production brief; the agent is still responsible for
reading the pipeline manifest, calling tools, and writing checkpoints.
"""

from __future__ import annotations

import json
import math
import os
import shutil
import subprocess
import sys
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from backlot import state as state_mod
from lib.paths import REPO_ROOT
from lib.checkpoint import get_next_stage, get_pipeline_stages, write_checkpoint
from lib.events import emit_event

RUN_FILENAME = "agent_run.json"
PROMPT_FILENAME = "agent_prompt.md"
LOG_FILENAME = "agent_run.log"
MAX_BRIEF_LENGTH = 12_000
MAX_REVIEW_NOTE_LENGTH = 4_000

_PROCESS_LOCK = threading.Lock()
_PROCESSES: dict[str, subprocess.Popen] = {}
_LOG_HANDLES: dict[str, Any] = {}


def _ollama_stage_blocker(pipeline_type: str | None, stage: str | None) -> str | None:
    if pipeline_type == "health-infographic" and stage == "research":
        return (
            "Bước nghiên cứu y khoa cần truy cập nguồn web và trích dẫn kiểm chứng. "
            "Ollama Local đang chạy offline nên không thể hoàn thành an toàn. "
            "Hãy chọn Tự chọn, Codex hoặc Claude; Ollama/Granite vẫn dùng được cho các bước local sau."
        )
    if pipeline_type == "documentary-montage":
        return (
            "Quy trình phóng sự cần tìm kiếm và tải footage thật từ các nguồn web như "
            "Pexels, Archive.org, NASA và Wikimedia. Ollama Local chỉ được cấp tool offline "
            "nên không thể hoàn thành pipeline này. Hãy chọn Tự chọn, Codex hoặc Claude."
        )
    return None


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


def _run_failure_detail(project_dir: Path, fallback: str) -> str:
    try:
        lines = (project_dir / LOG_FILENAME).read_text(
            encoding="utf-8", errors="replace"
        ).splitlines()
    except OSError:
        return fallback
    recent = "\n".join(lines[-160:])
    lowered = recent.lower()
    if (
        "oauth access token is invalid" in lowered
        or "failed to authenticate" in lowered
        or "authentication failed" in lowered
        or "401" in lowered and "oauth" in lowered
    ):
        return (
            "Claude Code chưa xác thực được (OAuth token không hợp lệ). "
            "Hãy chạy `claude auth login` trong Terminal, đăng nhập lại tài khoản Claude, "
            "sau đó bấm 'Bắt đầu workflow' để thử lại; dữ liệu dự án vẫn được giữ nguyên."
        )
    if "hit your usage limit" in lowered or "usage limit" in lowered:
        return (
            "Agent Codex đã hết hạn mức sử dụng. Hãy chọn Claude Code hoặc thử lại sau khi "
            "hạn mức được đặt lại; dữ liệu dự án vẫn được giữ nguyên."
        )
    for line in reversed(lines[-80:]):
        text = line.strip()
        if "LỖI:" in text:
            return text.split("LỖI:", 1)[1].strip()[:500] or fallback
    return fallback


def _fail_active_checkpoint(project_dir: Path, error: str, run: dict[str, Any]) -> None:
    marker = _read_json(project_dir / "project.json") or {}
    pipeline_type = marker.get("pipeline_type")
    project_id = str(marker.get("project_id") or project_dir.name)
    try:
        stages = get_pipeline_stages(pipeline_type)
    except Exception:
        return
    for stage in stages:
        checkpoint = _read_json(project_dir / f"checkpoint_{stage}.json")
        if not checkpoint or checkpoint.get("status") != "in_progress":
            continue
        try:
            write_checkpoint(
                project_dir.parent,
                project_id,
                stage,
                "failed",
                checkpoint.get("artifacts") or {},
                pipeline_type=pipeline_type,
                error=error,
                metadata={
                    **(checkpoint.get("metadata") or {}),
                    "runner": run.get("agent"),
                    "model": run.get("model"),
                },
            )
        except Exception:
            pass
        return


def _pid_alive(pid: Any) -> bool:
    if not isinstance(pid, int) or pid <= 0:
        return False
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
        kernel32.WaitForSingleObject.restype = wintypes.DWORD
        kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
        kernel32.CloseHandle.restype = wintypes.BOOL
        handle = kernel32.OpenProcess(0x00100000, False, pid)  # SYNCHRONIZE
        if not handle:
            return False
        try:
            return kernel32.WaitForSingleObject(handle, 0) == 0x00000102  # WAIT_TIMEOUT
        finally:
            kernel32.CloseHandle(handle)
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
        if run.get("status") == "starting" and not run.get("pid"):
            try:
                started = datetime.fromisoformat(run["started_at"])
                if started.tzinfo is None:
                    started = started.replace(tzinfo=timezone.utc)
                age = datetime.now(timezone.utc) - started
                if timedelta(seconds=-5) <= age < timedelta(seconds=60):
                    return run
            except (KeyError, TypeError, ValueError):
                pass
        if _pid_alive(run.get("pid")):
            return run
        run = {
            **run,
            "status": "failed",
            "finished_at": run.get("finished_at") or _now(),
            "error": "Agent đã dừng trước khi ghi nhận hoàn tất.",
        }
        _write_json(_run_path(project_dir), run)
        _fail_active_checkpoint(project_dir, run["error"], run)
    return run


def get_run(project_id: str) -> dict[str, Any]:
    project_dir = state_mod.PROJECTS_DIR / project_id
    return _refresh_run(project_id, project_dir, _read_json(_run_path(project_dir)))


def _agent_executable(name: str) -> str | None:
    executable = shutil.which(name)
    if not executable:
        return None
    if name == "claude" and sys.platform == "win32" and Path(executable).suffix.lower() in {".cmd", ".bat"}:
        native = Path(executable).parent / "node_modules" / "@anthropic-ai" / "claude-code" / "bin" / "claude.exe"
        if native.is_file():
            return str(native)
    return executable


def available_agents() -> list[dict[str, Any]]:
    agents = []
    for name, label in (("codex", "Codex"), ("claude", "Claude Code")):
        executable = _agent_executable(name)
        agents.append({"name": name, "label": label, "available": bool(executable)})
    from backlot.ollama_agent import DEFAULT_MODEL, model_pull_status, ollama_status

    ollama = ollama_status()
    agents.append({
        "name": "ollama",
        "label": "Ollama — miễn phí trên máy",
        "available": bool(ollama["online"] and ollama["models"]),
        "online": ollama["online"],
        "models": ollama["models"],
        "recommended_model": DEFAULT_MODEL,
        "installer": model_pull_status(DEFAULT_MODEL),
        "detail": (
            f"Sẵn sàng với {len(ollama['models'])} model local."
            if ollama["models"]
            else "Ollama đang chạy nhưng chưa có model."
            if ollama["online"]
            else ollama["error"]
        ),
        "setup_url": "https://ollama.com/download",
    })
    return agents


def _resolve_agent(requested: str | None) -> tuple[str, str]:
    choice = (requested or "auto").strip().lower()
    if choice not in {"auto", "codex", "claude", "ollama"}:
        raise ValueError("Agent không hợp lệ")
    if choice == "ollama":
        from backlot.ollama_agent import ollama_status

        status = ollama_status(timeout=2.0)
        if not status["online"]:
            raise ValueError(status["error"])
        if not status["models"]:
            raise ValueError("Ollama chưa có model. Hãy tải Llama 3.1 8B trong cửa sổ workflow.")
        return "ollama", sys.executable
    candidates = ("codex", "claude") if choice == "auto" else (choice,)
    for name in candidates:
        executable = _agent_executable(name)
        if executable:
            return name, executable
    raise ValueError("Chưa tìm thấy Codex hoặc Claude Code trên máy này")


def _load_marker(project_dir: Path) -> dict[str, Any]:
    marker = _read_json(project_dir / "project.json")
    if not marker:
        raise ValueError("Không đọc được project.json")
    return marker


def _materialize_checkpoint_artifacts(
    project_dir: Path,
    artifacts: dict[str, Any],
) -> dict[str, Any]:
    materialized: dict[str, Any] = {}
    for name, value in artifacts.items():
        if isinstance(value, dict):
            materialized[name] = _normalize_legacy_artifact(project_dir, name, value)
            continue
        if isinstance(value, str):
            resolved = state_mod._resolve_artifact(project_dir, value)
            if isinstance(resolved, dict):
                materialized[name] = _normalize_legacy_artifact(project_dir, name, resolved)
                continue
        raise ValueError(
            f"Không đọc được artifact '{name}'. Hãy tạo lại tài liệu của stage này trước khi duyệt."
        )
    return materialized


def _number(value: Any, fallback: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return fallback


def _thematic_question(project_dir: Path) -> str | None:
    brief = state_mod._resolve_artifact(project_dir, "artifacts/brief.json") or {}
    metadata = brief.get("metadata") or {}
    documentary = metadata.get("documentary_montage") or {}
    value = documentary.get("thematic_question") or metadata.get("thematic_question")
    return value if isinstance(value, str) and value.strip() else None


def _normalize_legacy_scene_plan(project_dir: Path, artifact: dict[str, Any]) -> dict[str, Any]:
    acts = artifact.get("acts")
    if not isinstance(acts, list) or not acts:
        return artifact

    source_scenes: list[tuple[int, dict[str, Any]]] = []
    for act_index, act in enumerate(acts):
        if not isinstance(act, dict):
            continue
        for scene in act.get("scenes") or []:
            if isinstance(scene, dict):
                source_scenes.append((act_index, scene))

    scenes = []
    slots = []
    for index, (act_index, scene) in enumerate(source_scenes):
        start = _number(scene.get("time_in"), 0.0)
        duration = max(0.1, _number(scene.get("duration"), 0.0))
        end = _number(scene.get("time_out"), start + duration)
        if end <= start:
            end = start + duration
        description = str(scene.get("description") or f"Cảnh {index + 1}").strip()
        candidates = [item for item in scene.get("source_candidates") or [] if isinstance(item, dict)]
        sources = []
        queries = []
        for value in [scene.get("search_query"), *(item.get("query") for item in candidates)]:
            if isinstance(value, str) and value.strip() and value.strip() not in queries:
                queries.append(value.strip())
        for item in candidates:
            source = item.get("source")
            if isinstance(source, str) and source and source not in sources:
                sources.append(source)
        hero = index == 0 or (index > 0 and act_index != source_scenes[index - 1][0])
        scene_id = str(scene.get("id") or f"slot_{index + 1:02d}")
        texture_keywords = [
            part.strip()
            for value in (scene.get("visual_mood"), scene.get("color_grade"))
            if isinstance(value, str)
            for part in value.replace("_", " ").split(",")
            if part.strip()
        ]
        scenes.append({
            "id": scene_id,
            "type": "broll",
            "description": description,
            "start_seconds": start,
            "end_seconds": end,
            "movement": str(scene.get("motion") or "static"),
            "transition_out": str(scene.get("cut_to_next") or "cut"),
            "overlay_notes": " · ".join(
                str(value) for value in (scene.get("visual_mood"), scene.get("color_grade")) if value
            ),
            "narrative_role": (
                "establish_context" if index == 0
                else "resolution" if index == len(source_scenes) - 1
                else "emotional_beat"
            ),
            "information_role": description,
            "hero_moment": hero,
            "texture_keywords": texture_keywords,
            "required_assets": [{
                "type": "video",
                "description": description,
                "source": "source",
            }],
        })
        slots.append({
            "id": scene_id,
            "description": description,
            "hero": hero,
            "preferred_sources": sources,
            "queries": queries[:3],
            "min_duration": min(duration, max(1.0, duration * 0.75)),
            "target_hold_seconds": end - start,
            "era_hint": "any",
        })

    metadata = {
        "pipeline": "documentary-montage",
        "shape": artifact.get("shape") or "three-act",
        "tone": artifact.get("tone"),
        "thematic_question": _thematic_question(project_dir),
        "total_duration_seconds": _number(artifact.get("total_duration_seconds"), 0.0),
        "slots": slots,
        "end_tag": artifact.get("end_tag"),
        "music_plan": artifact.get("music_plan"),
        "asset_acquisition_plan": artifact.get("asset_acquisition_plan"),
        "timeline_summary": artifact.get("timeline_summary"),
        "legacy_format": "documentary_acts_v1",
    }
    return {
        "version": "1.0",
        "scenes": scenes,
        "metadata": {key: value for key, value in metadata.items() if value is not None},
    }


def _normalize_legacy_edit_decisions(artifact: dict[str, Any]) -> dict[str, Any]:
    """Convert agent-authored documentary timeline aliases to the canonical schema."""

    allowed_top_level = {
        "version", "cuts", "overlays", "audio", "subtitles", "music", "transitions",
        "renderer_family", "render_runtime", "motionIntensity", "composition_mode",
        "bespoke", "slideshow_risk_score", "metadata",
    }
    cuts = artifact.get("cuts")
    if not isinstance(cuts, list):
        return artifact
    has_alias_cuts = any(
        isinstance(cut, dict)
        and not {"id", "source", "in_seconds", "out_seconds"}.issubset(cut)
        and any(key in cut for key in ("cut_id", "asset_id", "source_in", "source_out"))
        for cut in cuts
    )
    has_extra_top_level = bool(set(artifact) - allowed_top_level)
    legacy_music = artifact.get("music")
    has_legacy_music = isinstance(legacy_music, dict) and bool(
        set(legacy_music) - {"asset_id", "volume", "ducking", "fade_in_seconds", "fade_out_seconds"}
    )
    if not has_alias_cuts and not has_extra_top_level and not has_legacy_music:
        return artifact

    normalized_cuts: list[dict[str, Any]] = []
    cut_details: list[dict[str, Any]] = []
    canonical_cut_keys = {
        "id", "source", "in_seconds", "out_seconds", "speed", "layer", "type", "text",
        "title", "subtitle", "stat", "sourceLabel", "myth", "reality", "takeaway",
        "badge", "ingredientImage", "facts", "mechanismNodes", "evidenceLevels",
        "timelineSteps", "transform", "transition_in", "transition_out",
        "transition_duration", "motion_intensity", "backgroundColor", "accentColor",
        "secondaryColor", "reason",
    }
    for index, cut in enumerate(cuts):
        if not isinstance(cut, dict):
            continue
        if {"id", "source", "in_seconds", "out_seconds"}.issubset(cut):
            normalized_cuts.append({key: value for key, value in cut.items() if key in canonical_cut_keys})
            continue
        source_in = _number(cut.get("source_in", cut.get("in_seconds")), 0.0)
        source_out = _number(cut.get("source_out", cut.get("out_seconds")), source_in)
        if source_out <= source_in:
            source_out = source_in + max(0.1, _number(cut.get("duration_seconds"), 0.1))
        normalized_cut: dict[str, Any] = {
            "id": str(cut.get("cut_id") or cut.get("id") or f"cut_{index + 1:02d}"),
            "source": str(cut.get("asset_id") or cut.get("source") or cut.get("asset_path") or ""),
            "in_seconds": source_in,
            "out_seconds": source_out,
            "speed": max(0.1, _number(cut.get("speed"), 1.0)),
            "layer": str(cut.get("layer") or "primary"),
        }
        for key in ("transition_in", "transition_out", "transition_duration", "reason"):
            if cut.get(key) is not None:
                normalized_cut[key] = cut[key]
        movement = cut.get("movement")
        if isinstance(movement, str) and movement:
            normalized_cut["transform"] = {"position": "center", "animation": movement}
        normalized_cuts.append(normalized_cut)
        details = {key: value for key, value in cut.items() if key not in canonical_cut_keys}
        if details:
            cut_details.append({"id": normalized_cut["id"], **details})

    metadata = dict(artifact.get("metadata") or {})
    metadata["normalized_from"] = "documentary_timeline_v1"
    metadata["target_duration_seconds"] = _number(
        artifact.get("total_duration_seconds"),
        sum(max(0.0, _number(cut.get("out_seconds")) - _number(cut.get("in_seconds"))) for cut in normalized_cuts),
    )
    for key in (
        "project_id", "pipeline_type", "body_duration_seconds", "end_tag_mode",
        "target_platform", "canvas", "frame_rate", "end_tag", "color_grade_lut_map",
        "transition_vocabulary",
    ):
        if artifact.get(key) is not None:
            metadata[key] = artifact[key]
    if cut_details:
        metadata["source_cut_details"] = cut_details
    if has_legacy_music:
        metadata["source_music_config"] = legacy_music

    normalized = {
        key: value
        for key, value in artifact.items()
        if key in allowed_top_level and key not in {"cuts", "metadata", "music"}
    }
    normalized.update({
        "version": "1.0",
        "cuts": normalized_cuts,
        "metadata": metadata,
    })
    if isinstance(legacy_music, dict):
        volume = legacy_music.get("volume")
        if volume is None and legacy_music.get("volume_db") is not None:
            volume = math.pow(10.0, _number(legacy_music.get("volume_db")) / 20.0)
        music = {
            "asset_id": str(legacy_music.get("asset_id") or ""),
            "volume": min(1.0, max(0.0, _number(volume, 0.7))),
            "ducking": bool(legacy_music.get("ducking", False)),
            "fade_in_seconds": max(0.0, _number(legacy_music.get("fade_in_seconds"), 0.0)),
            "fade_out_seconds": max(0.0, _number(legacy_music.get("fade_out_seconds"), 0.0)),
        }
        audio = dict(normalized.get("audio") or {})
        audio["music"] = music
        normalized["audio"] = audio
    elif "music" in artifact:
        normalized["music"] = artifact["music"]
    return normalized


def _normalize_legacy_artifact(
    project_dir: Path,
    name: str,
    artifact: dict[str, Any],
) -> dict[str, Any]:
    if name == "scene_plan" and not isinstance(artifact.get("scenes"), list):
        return _normalize_legacy_scene_plan(project_dir, artifact)
    if name == "edit_decisions":
        return _normalize_legacy_edit_decisions(artifact)
    return artifact


def _persist_materialized_artifacts(
    project_dir: Path,
    references: dict[str, Any],
    artifacts: dict[str, Any],
) -> None:
    root = project_dir.resolve()
    for name, reference in references.items():
        if not isinstance(reference, str) or name not in artifacts:
            continue
        target = (
            (project_dir / reference).resolve()
            if not Path(reference).is_absolute()
            else Path(reference).resolve()
        )
        try:
            target.relative_to(root)
        except (ValueError, OSError):
            continue
        _write_json(target, artifacts[name])


def _build_prompt(
    project_id: str,
    project_dir: Path,
    marker: dict[str, Any],
    brief: str,
    review_feedback: str | None = None,
) -> str:
    pipeline_type = marker.get("pipeline_type") or "unknown"
    feedback_section = ""
    if review_feedback:
        feedback_section = f"""
## Phản hồi duyệt trong app
{review_feedback}

Hãy sửa artifact của stage hiện tại theo phản hồi trên, tự kiểm tra lại, rồi ghi một
checkpoint `awaiting_human` mới để người dùng duyệt lại. Không bỏ qua cổng duyệt.
"""
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
{feedback_section}

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
7. Tiếp tục tự động qua mọi stage không yêu cầu duyệt. Một stage không gated vừa `completed`
   KHÔNG phải là điểm kết thúc workflow.
8. Với stage có `human_approval_default: true`, hãy tạo và kiểm tra đầy đủ artifact của stage đó,
   ghi checkpoint `awaiting_human`, trình bày nội dung cần duyệt, rồi mới dừng.

Bắt đầu từ stage kế tiếp còn thiếu của pipeline. Chỉ được dừng khi đã tới checkpoint
`awaiting_human`, hoàn tất toàn bộ pipeline, hoặc gặp lỗi/blocker thật đã được ghi rõ vào checkpoint.
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

    if agent == "ollama":
        prompt_file = project_dir / PROMPT_FILENAME
        if getattr(sys, "frozen", False):
            command = [
                executable,
                "--ollama-worker",
                "--project-dir",
                str(project_dir),
                "--prompt-file",
                str(prompt_file),
            ]
        else:
            command = [
                executable,
                "-m",
                "backlot.ollama_agent",
                "--project-dir",
                str(project_dir),
                "--prompt-file",
                str(prompt_file),
            ]
        if model:
            command.extend(["--model", model])
        return command

    command = [
        executable,
        "--print",
        "--output-format",
        "stream-json",
        "--verbose",
        "--permission-mode",
        "auto",
        prompt,
        "--add-dir",
        str(REPO_ROOT),
    ]
    if model:
        command.extend(["--model", model])
    return command


def _watch_process(project_id: str, project_dir: Path, process: subprocess.Popen) -> None:
    return_code = process.wait()
    with _PROCESS_LOCK:
        _PROCESSES.pop(project_id, None)
        handle = _LOG_HANDLES.pop(project_id, None)
    if handle is not None:
        handle.close()

    run = _read_json(_run_path(project_dir)) or {"project_id": project_id}
    pending_review = run.pop("pending_review_resume", None)
    if isinstance(pending_review, dict):
        run.update({
            "finished_at": _now(),
            "exit_code": return_code,
            "status": "idle",
        })
        _write_json(_run_path(project_dir), run)
        _resume_after_review(project_id, pending_review, prior_run=run)
        return

    run.update({"finished_at": _now(), "exit_code": return_code})
    if return_code != 0:
        run["status"] = "failed"
        fallback = f"Agent kết thúc với mã lỗi {return_code}. Xem agent_run.log để biết chi tiết."
        run["error"] = _run_failure_detail(project_dir, fallback)
        _fail_active_checkpoint(project_dir, run["error"], run)
    else:
        marker = _read_json(project_dir / "project.json") or {}
        pipeline_type = marker.get("pipeline_type")
        next_stage = get_next_stage(project_dir.parent, project_id, pipeline_type)
        next_checkpoint = (
            _read_json(project_dir / f"checkpoint_{next_stage}.json")
            if next_stage
            else None
        )
        if next_stage is None:
            run["status"] = "completed"
            run.pop("error", None)
        elif next_checkpoint and next_checkpoint.get("status") == "awaiting_human":
            run["status"] = "awaiting_human"
            run["awaiting_stage"] = next_stage
            run.pop("error", None)
        else:
            run["status"] = "failed"
            fallback = (
                f"Agent đã dừng trước khi hoàn tất stage '{next_stage}' hoặc tạo cổng duyệt. "
                "Hãy chạy lại workflow để tiếp tục."
            )
            run["error"] = _run_failure_detail(project_dir, fallback)
            _fail_active_checkpoint(project_dir, run["error"], run)
    _write_json(_run_path(project_dir), run)
    emit_event(project_dir, {
        "tool": f"agent:{run.get('agent', 'unknown')}",
        "event": "finish" if run["status"] in {"completed", "awaiting_human"} else "error",
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
    review_feedback: str | None = None,
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
    if review_feedback is not None and not isinstance(review_feedback, str):
        raise ValueError("Phản hồi duyệt phải là văn bản")
    brief = brief.strip()
    model = model.strip() if isinstance(model, str) else None
    review_feedback = review_feedback.strip() if isinstance(review_feedback, str) else None
    if not brief:
        raise ValueError("Hãy mô tả video cần sản xuất trước khi bắt đầu")
    if len(brief) > MAX_BRIEF_LENGTH:
        raise ValueError(f"Brief quá dài, tối đa {MAX_BRIEF_LENGTH} ký tự")

    current = get_run(project_id)
    if current.get("status") in {"starting", "running"}:
        raise ValueError("Workflow của dự án này đang chạy")
    if not allow_automation:
        raise ValueError("Hãy bật 'Cho phép agent chạy lệnh tự động' trước khi bắt đầu")

    marker = _load_marker(project_dir)
    resolved_agent, executable = _resolve_agent(agent)
    next_stage = get_next_stage(
        state_mod.PROJECTS_DIR,
        project_id,
        marker.get("pipeline_type"),
    )
    if next_stage is None:
        raise ValueError("Workflow đã hoàn tất toàn bộ pipeline")
    current_checkpoint = _read_json(project_dir / f"checkpoint_{next_stage}.json")
    if current_checkpoint and current_checkpoint.get("status") == "awaiting_human":
        raise ValueError(f"Stage '{next_stage}' đang chờ bạn duyệt trên board")
    if resolved_agent == "ollama":
        blocker = _ollama_stage_blocker(marker.get("pipeline_type"), next_stage)
        if blocker:
            raise ValueError(blocker)
    prompt = _build_prompt(project_id, project_dir, marker, brief, review_feedback)
    (project_dir / PROMPT_FILENAME).write_text(prompt, encoding="utf-8")
    command = _command(resolved_agent, executable, project_dir, model, allow_automation, prompt)
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
    if review_feedback:
        run["review_feedback"] = review_feedback
    _write_json(_run_path(project_dir), run)
    emit_event(project_dir, {"tool": f"agent:{resolved_agent}", "event": "start", "status": "starting"})

    try:
        write_checkpoint(
            state_mod.PROJECTS_DIR,
            project_id,
            next_stage,
            "in_progress",
            {},
            pipeline_type=marker.get("pipeline_type"),
            metadata={
                "runner": resolved_agent,
                "run_started_at": run["started_at"],
                **({"review_feedback": review_feedback} if review_feedback else {}),
            },
        )
    except Exception as exc:
        run["status"] = "failed"
        run["error"] = f"Không khởi tạo được checkpoint đầu tiên: {exc}"
        run["finished_at"] = _now()
        _write_json(_run_path(project_dir), run)
        raise ValueError(run["error"]) from exc

    env = os.environ.copy()
    env["OPENMONTAGE_PROJECTS_DIR"] = str(state_mod.PROJECTS_DIR)
    # A frozen Windows GUI process inherits the active ANSI code page unless
    # explicitly overridden.  The Ollama worker prints Vietnamese status and
    # error messages, so force UTF-8 for its redirected log stream.
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONPATH"] = os.pathsep.join(
        part for part in (str(REPO_ROOT), env.get("PYTHONPATH", "")) if part
    )
    try:
        log_handle = open(project_dir / LOG_FILENAME, "w", encoding="utf-8")
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
                next_stage,
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


def _resume_after_review(
    project_id: str,
    request: dict[str, Any],
    *,
    prior_run: dict[str, Any] | None = None,
) -> dict[str, Any]:
    project_dir = state_mod.PROJECTS_DIR / project_id
    marker = _load_marker(project_dir)
    next_stage = get_next_stage(
        state_mod.PROJECTS_DIR,
        project_id,
        marker.get("pipeline_type"),
    )
    if next_stage is None:
        completed = {
            **(prior_run or {}),
            "project_id": project_id,
            "status": "completed",
            "finished_at": _now(),
        }
        completed.pop("error", None)
        completed.pop("pending_review_resume", None)
        _write_json(_run_path(project_dir), completed)
        return {"resumed": False, "completed": True, "run": completed}

    try:
        resumed = start_run(
            project_id,
            brief=str(request.get("brief") or marker.get("brief") or "").strip(),
            agent=request.get("agent"),
            model=request.get("model"),
            allow_automation=True,
            review_feedback=request.get("review_feedback"),
        )
    except ValueError as exc:
        failed = {
            **(prior_run or {}),
            "project_id": project_id,
            "status": "failed",
            "finished_at": _now(),
            "error": f"Đã lưu quyết định duyệt nhưng chưa thể tiếp tục tự động: {exc}",
        }
        failed.pop("pending_review_resume", None)
        _write_json(_run_path(project_dir), failed)
        emit_event(project_dir, {
            "tool": "human:review",
            "event": "resume_error",
            "status": "failed",
            "error": failed["error"],
        })
        return {"resumed": False, "completed": False, "run": failed, "error": failed["error"]}
    return {"resumed": True, "completed": False, "run": resumed}


def review_gate(
    project_id: str,
    *,
    stage: str,
    action: str,
    note: str = "",
) -> dict[str, Any]:
    project_dir = state_mod.PROJECTS_DIR / project_id
    if not project_dir.is_dir():
        raise ValueError("Không tìm thấy workspace của dự án")
    if action not in {"approve", "revise"}:
        raise ValueError("Hành động duyệt không hợp lệ")
    if not isinstance(stage, str) or not stage.strip():
        raise ValueError("Thiếu stage cần duyệt")
    if not isinstance(note, str):
        raise ValueError("Ghi chú duyệt phải là văn bản")
    stage = stage.strip()
    note = note.strip()
    if len(note) > MAX_REVIEW_NOTE_LENGTH:
        raise ValueError(f"Ghi chú quá dài, tối đa {MAX_REVIEW_NOTE_LENGTH} ký tự")
    if action == "revise" and not note:
        raise ValueError("Hãy nhập nội dung cần chỉnh sửa")

    marker = _load_marker(project_dir)
    checkpoint = _read_json(project_dir / f"checkpoint_{stage}.json")
    if not checkpoint or checkpoint.get("status") != "awaiting_human":
        raise ValueError(f"Stage '{stage}' hiện không chờ duyệt")

    reviewed_at = _now()
    metadata = {
        **(checkpoint.get("metadata") or {}),
        "reviewed_via": "backlot_app",
        "reviewed_at": reviewed_at,
        "review_action": action,
    }
    if note:
        metadata["review_note"] = note

    approved = action == "approve"
    artifact_references = checkpoint.get("artifacts") or {}
    artifacts = _materialize_checkpoint_artifacts(
        project_dir,
        artifact_references,
    )
    if approved and stage == "assets":
        from backlot.asset_materializer import asset_file_report

        report = asset_file_report(project_dir, artifacts.get("asset_manifest"))
        if not report["complete"]:
            missing = ", ".join(entry["id"] or entry["path"] for entry in report["missing_entries"][:5])
            suffix = "…" if report["missing"] > 5 else ""
            raise ValueError(
                f"Chưa thể duyệt tài nguyên: còn thiếu {report['missing']}/{report['total']} file "
                f"({missing}{suffix}). Hãy bấm 'Tải tài nguyên 0 USD' và chờ kiểm tra hoàn tất."
            )
    write_checkpoint(
        state_mod.PROJECTS_DIR,
        project_id,
        stage,
        "completed" if approved else "failed",
        artifacts,
        pipeline_type=marker.get("pipeline_type"),
        style_playbook=checkpoint.get("style_playbook") or marker.get("style_playbook"),
        checkpoint_policy=checkpoint.get("checkpoint_policy") or "guided",
        human_approval_required=True,
        human_approved=approved,
        review=checkpoint.get("review"),
        cost_snapshot=checkpoint.get("cost_snapshot"),
        error=None if approved else f"Người dùng yêu cầu chỉnh sửa: {note}",
        metadata=metadata,
    )
    _persist_materialized_artifacts(project_dir, artifact_references, artifacts)
    emit_event(project_dir, {
        "tool": "human:review",
        "event": action,
        "status": "approved" if approved else "revision_requested",
        "stage": stage,
    })

    current_run = get_run(project_id)
    resume_request = {
        "brief": current_run.get("brief") or marker.get("brief") or "",
        "agent": current_run.get("agent") or "auto",
        "model": current_run.get("model"),
        "review_feedback": (
            f"Stage `{stage}` chưa được duyệt. Yêu cầu chỉnh sửa của người dùng: {note}"
            if not approved
            else None
        ),
    }
    if current_run.get("status") in {"starting", "running"}:
        queued_run = {**current_run, "pending_review_resume": resume_request}
        _write_json(_run_path(project_dir), queued_run)
        return {
            "ok": True,
            "action": action,
            "stage": stage,
            "queued": True,
            "resumed": False,
        }

    result = _resume_after_review(project_id, resume_request, prior_run=current_run)
    return {
        "ok": True,
        "action": action,
        "stage": stage,
        "queued": False,
        **result,
    }
