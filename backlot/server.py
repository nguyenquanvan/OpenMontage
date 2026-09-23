"""Backlot server — FastAPI app: board state API, SSE change feed, media.

The watcher observes ``projects/`` with watchfiles; on any change it bumps a
per-project version and wakes SSE subscribers, who tell the browser to
refetch state. The server never writes to project directories.
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from lib.checkpoint import init_project
from lib.pipeline_loader import load_pipeline_readonly
from backlot.state import PROJECTS_DIR, REPO_ROOT, list_projects, load_board_state, summarize_project
from backlot.settings import (
    settings_status,
    update_cost_settings,
    update_provider_settings,
    validate_cost_settings,
)
from backlot.free_models import free_model_catalog
from backlot.runner import available_agents, get_run, review_gate, start_run
from backlot.ollama_agent import DEFAULT_MODEL, model_pull_status, start_model_pull
from backlot.model_installer import install_catalog, start_install, start_runtime_repair, uninstall_model
from backlot.asset_materializer import materialization_status, start_materialization
from backlot.app_updater import start_update, update_status
from lib.app_version import version_payload
from lib.runtime import runtime_status

UI_DIR = Path(__file__).resolve().parent / "ui"
THUMB_CACHE_DIR = REPO_ROOT / ".backlot" / "thumbs"
THUMB_WIDTHS = (320, 640, 960)

# Paths inside a project whose changes are pure noise for the board.
_IGNORE_PARTS = {"node_modules", ".git", "__pycache__", ".cache"}

SSE_HEARTBEAT_SECONDS = 15
PROJECT_ID_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
MAX_PROJECT_ID_LENGTH = 80
MAX_PROJECT_TITLE_LENGTH = 200
MAX_INTAKE_VALUE_LENGTH = 4_000


def _ui_html(name: str, assets: tuple[str, ...]) -> HTMLResponse:
    html = (UI_DIR / name).read_text(encoding="utf-8")
    for asset in assets:
        path = UI_DIR / asset
        if path.is_file():
            version = str(int(path.stat().st_mtime))
            html = html.replace(f"/ui/{asset}", f"/ui/{asset}?v={version}")
    return HTMLResponse(html)


class ChangeHub:
    """Fan-out of project-change notifications to SSE subscribers.

    Subscriptions are filtered: a board subscribed to one project only ever
    receives that project's ids, so unrelated-project bursts can't flood its
    queue and starve out the one notification it actually needs.
    """

    def __init__(self) -> None:
        self._subscribers: dict[asyncio.Queue, Optional[str]] = {}

    def subscribe(self, project_id: Optional[str] = None) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=64)
        self._subscribers[q] = project_id
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self._subscribers.pop(q, None)

    def publish(self, project_id: str) -> None:
        for q, only in list(self._subscribers.items()):
            if only is not None and only != project_id:
                continue
            try:
                q.put_nowait(project_id)
            except asyncio.QueueFull:
                # Queue holds only THIS subscriber's relevant ids, so a full
                # queue already guarantees a pending wake-up → safe to drop.
                pass


hub = ChangeHub()

# Library summaries are expensive to derive (full state parse per project);
# cache per project and invalidate from the watcher.
_summary_cache: dict[str, dict] = {}


def _invalidate_summary(project_id: str) -> None:
    _summary_cache.pop(project_id, None)


def _cached_summaries() -> list[dict]:
    if not PROJECTS_DIR.is_dir():
        return []
    summaries = []
    for entry in sorted(PROJECTS_DIR.iterdir()):
        if not entry.is_dir() or entry.name.startswith(("_", ".")):
            continue
        cached = _summary_cache.get(entry.name)
        if cached is None:
            try:
                cached = summarize_project(entry)
            except Exception:
                cached = {
                    "project_id": entry.name, "title": entry.name,
                    "pipeline_type": "unknown", "has_pipeline_state": False,
                    "poster": None, "live": False, "last_activity": 0,
                    "active_stage": None, "awaiting_human": False,
                    "stage_states": [], "completed_count": 0,
                    "render_count": 0, "scene_count": 0, "error": "unreadable",
                }
            _summary_cache[entry.name] = cached
        summaries.append(cached)
    summaries.sort(key=lambda s: (not s["live"], -(s["last_activity"] or 0)))
    return summaries


def _workflow_catalog() -> list[dict]:
    """Return the user-facing catalog derived from pipeline manifests."""
    from lib.pipeline_loader import PIPELINE_DEFS_DIR, load_pipeline

    workflows = []
    for path in sorted(PIPELINE_DEFS_DIR.glob("*.yaml")):
        if path.stem == "framework-smoke":
            continue
        try:
            manifest = load_pipeline(path.stem)
        except Exception:
            continue
        orchestration = manifest.get("orchestration") or {}
        reference_input = manifest.get("reference_input") or {}
        stages = [
            {
                "name": stage.get("name"),
                "gated": bool(stage.get("human_approval_default", False)),
            }
            for stage in manifest.get("stages", [])
            if isinstance(stage, dict) and stage.get("name")
        ]
        workflows.append({
            "name": manifest.get("name", path.stem),
            "version": manifest.get("version"),
            "description": " ".join(str(manifest.get("description", "")).split()),
            "category": manifest.get("category", "custom"),
            "stability": manifest.get("stability", "beta"),
            "default_checkpoint_policy": manifest.get("default_checkpoint_policy", "guided"),
            "budget_default_usd": orchestration.get("budget_default_usd"),
            "max_wall_time_minutes": orchestration.get("max_wall_time_minutes"),
            "reference_input": bool(reference_input.get("supported", False)),
            "project_intake": manifest.get("project_intake"),
            "stages": stages,
        })
    return workflows


def _validate_project_intake(manifest: dict, payload: object) -> tuple[dict[str, str], str | None]:
    config = manifest.get("project_intake")
    if not config:
        return {}, None
    if payload is None:
        payload = {}
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Thông tin dự án không hợp lệ")

    fields = config.get("fields") or []
    known = {field["name"] for field in fields}
    unknown = set(payload) - known
    if unknown:
        raise HTTPException(status_code=400, detail="Thông tin dự án chứa trường không hợp lệ")

    values: dict[str, str] = {}
    for field in fields:
        name = field["name"]
        raw = payload.get(name, field.get("default", ""))
        value = str(raw).strip() if raw is not None else ""
        if field.get("required") and not value:
            raise HTTPException(status_code=400, detail=f"Hãy điền {field['label']}")
        if len(value) > MAX_INTAKE_VALUE_LENGTH:
            raise HTTPException(status_code=400, detail=f"{field['label']} quá dài")
        if field.get("type") == "select":
            allowed = {str(option["value"]) for option in field.get("options", [])}
            if value and value not in allowed:
                raise HTTPException(status_code=400, detail=f"{field['label']} không hợp lệ")
        if field.get("type") == "url" and value and not re.fullmatch(r"https?://[^\s]+", value):
            raise HTTPException(status_code=400, detail=f"{field['label']} phải là URL http(s)")
        if field.get("type") == "number" and value:
            try:
                number = float(value)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=f"{field['label']} phải là số") from exc
            if field.get("min") is not None and number < field["min"]:
                raise HTTPException(status_code=400, detail=f"{field['label']} quá nhỏ")
            if field.get("max") is not None and number > field["max"]:
                raise HTTPException(status_code=400, detail=f"{field['label']} quá lớn")
        values[name] = value

    brief = str(config.get("brief_template") or "")
    for name, value in values.items():
        brief = brief.replace("{" + name + "}", value)
    if len(brief) > 12_000:
        raise HTTPException(status_code=400, detail="Brief dự án quá dài")
    return values, brief.strip() or None


# Watch-loop hot path: pure string comparison, no per-path filesystem calls
# (change batches can be thousands of paths during a render).
import os as _os

_PROJECTS_ROOT_STR = _os.path.normcase(str(PROJECTS_DIR.resolve()))


def _project_of_change(path_str: str) -> Optional[str]:
    """Map a changed filesystem path to a project id (None = irrelevant)."""
    norm = _os.path.normcase(_os.path.normpath(path_str))
    if not norm.startswith(_PROJECTS_ROOT_STR):
        return None
    rel = norm[len(_PROJECTS_ROOT_STR):].lstrip("\\/")
    if not rel:
        return None
    parts = rel.replace("\\", "/").split("/")
    if _IGNORE_PARTS.intersection(parts):
        return None
    return parts[0]


async def _watch_projects() -> None:
    """Background task: watch projects/ and publish debounced changes."""
    try:
        from watchfiles import awatch
    except ImportError:
        return  # watcher unavailable → board still works via manual refresh
    if not PROJECTS_DIR.is_dir():
        return
    async for changes in awatch(PROJECTS_DIR, recursive=True, step=400):
        touched: set[str] = set()
        for _change, path_str in changes:
            pid = _project_of_change(path_str)
            if pid:
                touched.add(pid)
        for pid in touched:
            _invalidate_summary(pid)
            hub.publish(pid)


@asynccontextmanager
async def _lifespan(app: FastAPI):
    """Own and cleanly stop the project watcher with FastAPI's lifespan API."""

    task = asyncio.create_task(_watch_projects())
    app.state.watch_task = task
    try:
        yield
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task


def create_app() -> FastAPI:
    app = FastAPI(title="Backlot", docs_url=None, redoc_url=None, lifespan=_lifespan)

    # ---- API ----------------------------------------------------------

    @app.get("/api/health")
    async def health() -> dict:
        return {"ok": True, "app": "backlot"}

    @app.get("/api/version")
    async def version() -> dict[str, str]:
        return version_payload()

    @app.get("/api/app-update")
    async def app_update(force: bool = False) -> dict:
        return await asyncio.to_thread(update_status, force=force)

    @app.post("/api/app-update/install", status_code=202)
    async def install_app_update() -> dict:
        try:
            return await asyncio.to_thread(start_update)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/api/settings/providers")
    async def provider_settings() -> dict:
        return settings_status()

    @app.put("/api/settings/providers")
    async def save_provider_settings(payload: dict) -> dict:
        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="Payload phải là object")
        updates = payload.get("updates", {}) if isinstance(payload, dict) else {}
        clear = payload.get("clear", []) if isinstance(payload, dict) else []
        if not isinstance(updates, dict) or not isinstance(clear, list):
            raise HTTPException(status_code=400, detail="updates phải là object và clear phải là mảng")
        try:
            cost_kwargs = {}
            if "cost_profile" in payload:
                cost_kwargs["profile"] = payload["cost_profile"]
            if "budget_usd" in payload:
                cost_kwargs["budget_usd"] = payload["budget_usd"]
            validate_cost_settings(**cost_kwargs)
            await asyncio.to_thread(update_provider_settings, updates, clear)
            await asyncio.to_thread(update_cost_settings, **cost_kwargs)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"ok": True, **settings_status()}

    @app.get("/api/free-models")
    async def free_models() -> list[dict]:
        return await asyncio.to_thread(free_model_catalog)

    @app.get("/api/model-installs")
    async def model_installs() -> list[dict]:
        return await asyncio.to_thread(install_catalog)

    @app.post("/api/model-installs/{model_id}", status_code=202)
    async def install_model(model_id: str, payload: dict | None = None) -> dict:
        try:
            return await asyncio.to_thread(
                start_install,
                model_id,
                accept_license=bool((payload or {}).get("accept_license", False)),
            )
        except ValueError as exc:
            detail = str(exc).split("\n\nFailed validating", 1)[0].strip()
            raise HTTPException(status_code=409, detail=detail[:600]) from exc

    @app.delete("/api/model-installs/{model_id}")
    async def remove_model(model_id: str) -> dict:
        try:
            return await asyncio.to_thread(uninstall_model, model_id)
        except ValueError as exc:
            detail = str(exc).split("\n\nFailed validating", 1)[0].strip()
            raise HTTPException(status_code=409, detail=detail[:600]) from exc

    @app.post("/api/model-installs/{model_id}/runtime", status_code=202)
    async def repair_model_runtime(model_id: str) -> dict:
        try:
            return await asyncio.to_thread(start_runtime_repair, model_id)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/api/runtime")
    async def runtime() -> dict:
        return await asyncio.to_thread(runtime_status)

    @app.get("/api/projects")
    async def projects() -> list:
        return await asyncio.to_thread(_cached_summaries)

    @app.post("/api/projects", status_code=201)
    async def create_project(payload: dict) -> dict:
        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="Payload phải là object")

        project_id = payload.get("project_id")
        title = payload.get("title")
        pipeline_type = payload.get("pipeline_type")
        if not isinstance(project_id, str) or not PROJECT_ID_RE.fullmatch(project_id):
            raise HTTPException(
                status_code=400,
                detail="Mã dự án chỉ dùng chữ thường, số và dấu gạch ngang",
            )
        if len(project_id) > MAX_PROJECT_ID_LENGTH:
            raise HTTPException(status_code=400, detail="Mã dự án quá dài")
        if not isinstance(title, str) or not title.strip():
            raise HTTPException(status_code=400, detail="Tên dự án không được để trống")
        title = title.strip()
        if len(title) > MAX_PROJECT_TITLE_LENGTH:
            raise HTTPException(status_code=400, detail="Tên dự án quá dài")
        if not isinstance(pipeline_type, str) or pipeline_type == "framework-smoke":
            raise HTTPException(status_code=400, detail="Luồng sản xuất không hợp lệ")

        try:
            manifest = await asyncio.to_thread(load_pipeline_readonly, pipeline_type)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=400, detail="Luồng sản xuất không tồn tại") from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail="Manifest luồng sản xuất không hợp lệ") from exc

        project_dir = PROJECTS_DIR / project_id
        if project_dir.exists():
            raise HTTPException(status_code=409, detail="Mã dự án đã tồn tại")

        intake, initial_brief = _validate_project_intake(manifest, payload.get("intake"))
        intake_config = manifest.get("project_intake") or {}
        style_playbook = intake_config.get("style_playbook")
        style_field = intake_config.get("style_playbook_field")
        if isinstance(style_field, str) and intake.get(style_field):
            style_playbook = intake[style_field]
        await asyncio.to_thread(
            init_project,
            project_id,
            title=title,
            pipeline_type=pipeline_type,
            pipeline_dir=PROJECTS_DIR,
            style_playbook=style_playbook,
            initial_brief=initial_brief,
            intake=intake or None,
        )
        _invalidate_summary(project_id)
        hub.publish(project_id)
        return {
            "ok": True,
            "project_id": project_id,
            "title": title,
            "pipeline_type": pipeline_type,
            "style_playbook": style_playbook,
            "brief_ready": bool(initial_brief),
            "url": f"/p/{project_id}",
        }

    @app.get("/api/workflows")
    async def workflows() -> list:
        return await asyncio.to_thread(_workflow_catalog)

    @app.get("/api/project/{project_id}/run")
    async def project_run_status(project_id: str) -> dict:
        _safe_project_dir(project_id)
        return await asyncio.to_thread(get_run, project_id)

    @app.post("/api/project/{project_id}/run", status_code=202)
    async def project_run(project_id: str, payload: dict) -> dict:
        _safe_project_dir(project_id)
        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="Payload phải là object")
        try:
            return await asyncio.to_thread(
                start_run,
                project_id,
                brief=payload.get("brief", ""),
                agent=payload.get("agent"),
                model=payload.get("model"),
                allow_automation=payload.get("allow_automation", False),
            )
        except ValueError as exc:
            detail = str(exc)
            status = 409 if "đang chạy" in detail else 400
            raise HTTPException(status_code=status, detail=detail) from exc

    @app.post("/api/project/{project_id}/review")
    async def project_review(project_id: str, payload: dict) -> dict:
        _safe_project_dir(project_id)
        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="Payload phải là object")
        try:
            result = await asyncio.to_thread(
                review_gate,
                project_id,
                stage=payload.get("stage", ""),
                action=payload.get("action", ""),
                note=payload.get("note", ""),
            )
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        _invalidate_summary(project_id)
        hub.publish(project_id)
        return result

    @app.get("/api/project/{project_id}/assets/materialization")
    async def project_asset_materialization(project_id: str) -> dict:
        _safe_project_dir(project_id)
        try:
            return await asyncio.to_thread(materialization_status, project_id)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/api/project/{project_id}/assets/materialization", status_code=202)
    async def materialize_project_assets(project_id: str) -> dict:
        _safe_project_dir(project_id)
        try:
            result = await asyncio.to_thread(start_materialization, project_id)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        _invalidate_summary(project_id)
        hub.publish(project_id)
        return result

    @app.get("/api/agents")
    async def agents() -> list[dict]:
        return await asyncio.to_thread(available_agents)

    @app.post("/api/agents/ollama/models", status_code=202)
    async def pull_ollama_model(payload: dict | None = None) -> dict:
        model = (payload or {}).get("model") or DEFAULT_MODEL
        try:
            return await asyncio.to_thread(start_model_pull, model)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/api/agents/ollama/models/{model:path}")
    async def ollama_model_job(model: str) -> dict:
        return await asyncio.to_thread(model_pull_status, model)

    @app.get("/api/project/{project_id}/state")
    async def project_state(project_id: str) -> dict:
        project_dir = _safe_project_dir(project_id)
        return await asyncio.to_thread(load_board_state, project_dir)

    @app.get("/api/project/{project_id}/events")
    async def project_events(project_id: str, request: Request) -> StreamingResponse:
        _safe_project_dir(project_id)  # 404 early for unknown projects

        async def stream():
            q = hub.subscribe(project_id)
            try:
                yield _sse({"type": "hello", "project_id": project_id})
                while True:
                    if await request.is_disconnected():
                        return
                    try:
                        await asyncio.wait_for(q.get(), timeout=SSE_HEARTBEAT_SECONDS)
                    except asyncio.TimeoutError:
                        yield _sse({"type": "heartbeat", "ts": time.time()})
                        continue
                    # Coalesce bursts: drain anything else queued.
                    while not q.empty():
                        try:
                            q.get_nowait()
                        except asyncio.QueueEmpty:
                            break
                    yield _sse({"type": "change", "project_id": project_id})
            finally:
                hub.unsubscribe(q)

        return StreamingResponse(stream(), media_type="text/event-stream", headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        })

    @app.get("/api/library/events")
    async def library_events(request: Request) -> StreamingResponse:
        async def stream():
            q = hub.subscribe()
            try:
                yield _sse({"type": "hello"})
                while True:
                    if await request.is_disconnected():
                        return
                    try:
                        changed = await asyncio.wait_for(q.get(), timeout=SSE_HEARTBEAT_SECONDS)
                    except asyncio.TimeoutError:
                        yield _sse({"type": "heartbeat", "ts": time.time()})
                        continue
                    while not q.empty():
                        try:
                            q.get_nowait()
                        except asyncio.QueueEmpty:
                            break
                    yield _sse({"type": "change", "project_id": changed})
            finally:
                hub.unsubscribe(q)

        return StreamingResponse(stream(), media_type="text/event-stream", headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        })

    # ---- Thumbnails (downscaled, cached on disk) ------------------------

    @app.get("/thumb/{project_id}/{file_path:path}")
    async def thumb(project_id: str, file_path: str, w: int = 640) -> FileResponse:
        project_dir = _safe_project_dir(project_id)
        target = (project_dir / file_path).resolve()
        try:
            target.relative_to(project_dir.resolve())
        except ValueError:
            raise HTTPException(status_code=403, detail="path escapes project")
        if not target.is_file():
            raise HTTPException(status_code=404, detail="media not found")
        width = min(THUMB_WIDTHS, key=lambda x: abs(x - w))
        cached = await asyncio.to_thread(_thumbnail_for, target, width)
        if cached is None:
            # Never fall back to raw video bytes for an <img> consumer (F-03);
            # non-thumbable images are safe to serve as-is.
            if target.suffix.lower() in {".mp4", ".webm", ".mov"}:
                raise HTTPException(status_code=404, detail="no poster frame available")
            return FileResponse(target)
        return FileResponse(cached, media_type="image/jpeg")

    # ---- Media (range requests handled by FileResponse) ---------------

    @app.get("/media/{project_id}/{file_path:path}")
    async def media(project_id: str, file_path: str) -> FileResponse:
        project_dir = _safe_project_dir(project_id)
        target = (project_dir / file_path).resolve()
        try:
            target.relative_to(project_dir.resolve())
        except ValueError:
            raise HTTPException(status_code=403, detail="path escapes project")
        if not target.is_file():
            raise HTTPException(status_code=404, detail="media not found")
        return FileResponse(target)

    # ---- UI ------------------------------------------------------------

    @app.get("/p/{project_id}")
    async def board_page(project_id: str) -> HTMLResponse:
        return _ui_html("board.html", ("board.css", "board.js"))

    @app.get("/p/{project_path:path}")
    async def board_page_path(project_path: str) -> HTMLResponse:
        return _ui_html("board.html", ("board.css", "board.js"))

    @app.get("/")
    async def library_page() -> HTMLResponse:
        return _ui_html("index.html", ("board.css", "library.js"))

    @app.get("/settings")
    async def settings_page() -> HTMLResponse:
        return _ui_html("settings.html", ("settings.css", "settings.js"))

    if UI_DIR.is_dir():
        app.mount("/ui", StaticFiles(directory=UI_DIR), name="ui")

    # The board is a long-lived SPA: a tab keeps running whatever board.js it
    # loaded, and browsers heuristically cache /ui assets. no-cache forces a
    # conditional revalidation (cheap 304 via ETag) on every load so UI fixes
    # show up on a plain refresh. Media/thumb responses keep normal caching.
    @app.middleware("http")
    async def ui_no_cache(request, call_next):
        response = await call_next(request)
        path = request.url.path
        if path == "/" or path.startswith("/ui") or path.startswith("/p/"):
            response.headers["Cache-Control"] = "no-cache"
        return response

    return app


def _safe_project_dir(project_id: str) -> Path:
    # ':' rejects Windows drive-relative ids like "C:" (PROJECTS_DIR / "C:"
    # collapses back to PROJECTS_DIR itself).
    if any(c in project_id for c in "/\\:") or project_id in (".", ".."):
        raise HTTPException(status_code=400, detail="invalid project id")
    project_dir = PROJECTS_DIR / project_id
    if not project_dir.is_dir():
        raise HTTPException(status_code=404, detail=f"unknown project: {project_id}")
    return project_dir


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload)}\n\n"


def _thumbnail_for(source: Path, width: int) -> Optional[Path]:
    """Downscale an image (or extract a video poster frame) to a cached JPEG."""
    suffix = source.suffix.lower()
    is_image = suffix in {".png", ".jpg", ".jpeg", ".webp", ".gif"}
    is_video = suffix in {".mp4", ".webm", ".mov"}
    if not (is_image or is_video):
        return None
    try:
        import hashlib
        stat = source.stat()
        key = hashlib.sha1(
            f"{source}|{stat.st_mtime_ns}|{stat.st_size}|{width}".encode()
        ).hexdigest()[:20]
        cached = THUMB_CACHE_DIR / f"{key}.jpg"
        if cached.is_file():
            return cached
        THUMB_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        # Unique temp per request — concurrent misses for the same source
        # must not write (and replace from) the same temp file.
        import uuid
        tmp = THUMB_CACHE_DIR / f"{key}.{uuid.uuid4().hex[:8]}.tmp.jpg"
        if is_video:
            import subprocess
            result = subprocess.run(
                ["ffmpeg", "-y", "-loglevel", "error", "-ss", "1.5",
                 "-i", str(source), "-frames:v", "1",
                 "-vf", f"scale={width}:-2", str(tmp)],
                capture_output=True, timeout=30,
            )
            if result.returncode != 0 or not tmp.is_file():
                return None
        else:
            from PIL import Image
            with Image.open(source) as img:
                img = img.convert("RGB")
                img.thumbnail((width, width * 3))
                img.save(tmp, "JPEG", quality=82)
        tmp.replace(cached)
        return cached
    except Exception:
        return None


app = create_app()
