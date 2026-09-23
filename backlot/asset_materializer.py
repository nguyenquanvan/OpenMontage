"""Download and verify files referenced by an asset manifest."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlparse

import requests

from backlot import state as state_mod
from tools.video.direct_clip_search import DirectClipSearch
from tools.video.stock_sources import source_summary


MIN_FILE_BYTES = 1_024
DOWNLOAD_TIMEOUT_SECONDS = 300
_JOBS: dict[str, dict[str, Any]] = {}
_LOCK = threading.Lock()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}
    return value if isinstance(value, dict) else {}


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{threading.get_ident()}.tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temp, path)


def _asset_target(project_dir: Path, asset: dict[str, Any]) -> Path | None:
    raw = asset.get("path")
    if not isinstance(raw, str) or not raw.strip():
        return None
    target = (project_dir / raw).resolve()
    try:
        target.relative_to(project_dir.resolve())
    except ValueError:
        return None
    return target


def asset_file_report(project_dir: Path, manifest: dict[str, Any] | None = None) -> dict[str, Any]:
    manifest = manifest or _read_json(project_dir / "artifacts" / "asset_manifest.json")
    assets = [item for item in manifest.get("assets") or [] if isinstance(item, dict)]
    entries = []
    for asset in assets:
        target = _asset_target(project_dir, asset)
        exists = bool(target and target.is_file() and target.stat().st_size >= MIN_FILE_BYTES)
        entries.append({
            "id": str(asset.get("id") or ""),
            "scene_id": str(asset.get("scene_id") or ""),
            "type": str(asset.get("type") or ""),
            "path": str(asset.get("path") or ""),
            "provider": str(asset.get("provider") or ""),
            "exists": exists,
            "size_bytes": target.stat().st_size if exists and target else 0,
        })
    missing = [entry for entry in entries if not entry["exists"]]
    return {
        "total": len(entries),
        "ready": len(entries) - len(missing),
        "missing": len(missing),
        "complete": bool(entries) and not missing,
        "entries": entries,
        "missing_entries": missing,
    }


def materialization_status(project_id: str) -> dict[str, Any]:
    project_dir = state_mod.PROJECTS_DIR / project_id
    if not project_dir.is_dir():
        raise ValueError("Không tìm thấy workspace của dự án")
    report = asset_file_report(project_dir)
    with _LOCK:
        job = dict(_JOBS.get(project_id) or {})
    return {
        "project_id": project_id,
        **report,
        "job": job or {"status": "idle", "completed": report["ready"], "total": report["total"]},
        "sources": source_summary(),
    }


def _set_job(project_id: str, **updates: Any) -> None:
    with _LOCK:
        current = dict(_JOBS.get(project_id) or {})
        current.update(updates)
        _JOBS[project_id] = current


def start_materialization(project_id: str) -> dict[str, Any]:
    project_dir = state_mod.PROJECTS_DIR / project_id
    if not project_dir.is_dir():
        raise ValueError("Không tìm thấy workspace của dự án")
    manifest = _read_json(project_dir / "artifacts" / "asset_manifest.json")
    if not isinstance(manifest.get("assets"), list) or not manifest["assets"]:
        raise ValueError("Dự án chưa có asset_manifest để tải")
    already_running = False
    with _LOCK:
        current = _JOBS.get(project_id) or {}
        if current.get("status") in {"queued", "downloading"}:
            already_running = True
        else:
            report = asset_file_report(project_dir, manifest)
            _JOBS[project_id] = {
                "status": "queued",
                "completed": report["ready"],
                "total": report["total"],
                "failed": 0,
                "current": "",
                "errors": [],
                "started_at": _now(),
            }
    if already_running:
        return materialization_status(project_id)
    thread = threading.Thread(
        target=_run_materialization,
        args=(project_id, project_dir),
        name=f"mosa-assets-{project_id}",
        daemon=True,
    )
    thread.start()
    return materialization_status(project_id)


def _download_stream(url: str, target: Path, *, headers: dict[str, str] | None = None) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_name(f".{target.name}.part")
    try:
        with requests.get(url, headers=headers or {}, stream=True, timeout=DOWNLOAD_TIMEOUT_SECONDS) as response:
            response.raise_for_status()
            with partial.open("wb") as handle:
                for chunk in response.iter_content(chunk_size=1 << 17):
                    if chunk:
                        handle.write(chunk)
        if partial.stat().st_size < MIN_FILE_BYTES:
            raise ValueError("File tải về rỗng hoặc quá nhỏ")
        os.replace(partial, target)
    finally:
        if partial.exists():
            partial.unlink()


def _pexels_id(asset: dict[str, Any]) -> str | None:
    for value in (asset.get("original_url"), asset.get("path")):
        match = re.search(r"(?:-|_)(\d{5,})(?:/|\.|$)", str(value or ""))
        if match:
            return match.group(1)
    return None


def _download_pexels(asset: dict[str, Any], target: Path) -> dict[str, Any] | None:
    key = os.environ.get("PEXELS_API_KEY")
    video_id = _pexels_id(asset)
    if not key or not video_id:
        return None
    response = requests.get(
        f"https://api.pexels.com/videos/videos/{video_id}",
        headers={"Authorization": key},
        timeout=30,
    )
    response.raise_for_status()
    video = response.json()
    options = [
        item for item in video.get("video_files") or []
        if item.get("link") and item.get("file_type") == "video/mp4"
    ]
    if not options:
        return None
    suitable = [item for item in options if 720 <= int(item.get("width") or 0) <= 1920]
    selected = max(suitable or options, key=lambda item: int(item.get("width") or 0))
    _download_stream(selected["link"], target)
    return {
        "provider": "pexels",
        "original_url": video.get("url") or asset.get("original_url"),
        "license": "Pexels License (free, no attribution required)",
        "duration_seconds": float(video.get("duration") or 0),
        "resolution": f"{selected.get('width') or 0}x{selected.get('height') or 0}",
        "format": "mp4",
    }


def _archive_identifier(asset: dict[str, Any]) -> str | None:
    match = re.search(r"archive\.org/details/([^/?#]+)", str(asset.get("original_url") or ""))
    return match.group(1) if match else None


def _download_archive(asset: dict[str, Any], target: Path) -> dict[str, Any] | None:
    identifier = _archive_identifier(asset)
    if not identifier:
        return None
    response = requests.get(f"https://archive.org/metadata/{quote(identifier)}", timeout=30)
    response.raise_for_status()
    metadata = response.json()
    options = []
    for item in metadata.get("files") or []:
        name = str(item.get("name") or "")
        size = int(item.get("size") or 0)
        if name.lower().endswith(".mp4") and MIN_FILE_BYTES <= size <= 180 * 1024 * 1024:
            options.append((size, name, str(item.get("format") or "")))
    if not options:
        return None
    preferred = [item for item in options if item[2] in {"h.264", "MPEG4", "h.264 HD"}]
    size, name, _format = max(preferred or options, key=lambda item: item[0])
    _download_stream(f"https://archive.org/download/{quote(identifier)}/{quote(name)}", target)
    return {
        "provider": "archive_org",
        "original_url": f"https://archive.org/details/{identifier}",
        "license": asset.get("license") or "Public domain / license stated on Archive.org item",
        "format": target.suffix.lower().lstrip(".") or "mp4",
    }


def _slot_queries(project_dir: Path) -> dict[str, list[str]]:
    plan = _read_json(project_dir / "artifacts" / "scene_plan.json")
    slots = (plan.get("metadata") or {}).get("slots") or []
    queries: dict[str, list[str]] = {}
    for slot in slots:
        if not isinstance(slot, dict):
            continue
        values = [value.strip() for value in slot.get("queries") or [] if isinstance(value, str) and value.strip()]
        description = slot.get("description")
        if isinstance(description, str) and description.strip():
            values.append(description.strip())
        queries[str(slot.get("id") or "")] = values
    return queries


def _fallback_query(asset: dict[str, Any], queries: dict[str, list[str]]) -> str:
    scene_queries = queries.get(str(asset.get("scene_id") or "")) or []
    if scene_queries:
        return scene_queries[0]
    summary = str(asset.get("generation_summary") or "").split(".", 1)[0].strip()
    return summary or str(asset.get("scene_id") or "documentary footage")


def _download_fallback(
    project_dir: Path,
    asset: dict[str, Any],
    target: Path,
    queries: dict[str, list[str]],
) -> dict[str, Any] | None:
    available = source_summary()["available_source_names"]
    preferred = [name for name in ("pexels", "pixabay_video", "coverr", "archive_org", "nasa") if name in available]
    if not preferred:
        return None
    work_dir = project_dir / ".asset_downloads" / str(asset.get("id") or asset.get("scene_id") or "asset")
    result = DirectClipSearch().execute({
        "output_dir": str(work_dir),
        "queries": [{
            "query": _fallback_query(asset, queries),
            "slot_id": str(asset.get("scene_id") or ""),
            "kind": "video",
        }],
        "sources": preferred,
        "clips_per_query": 1,
        "filters": {"min_duration": 3, "max_duration": 90, "orientation": "landscape", "min_width": 1280},
        "extract_thumbnails": True,
        "timeout_seconds": 240,
    })
    clips = (result.data or {}).get("clips") or []
    if not result.success or not clips:
        return None
    clip = clips[0]
    source_path = Path(clip["path"])
    if not source_path.is_file():
        return None
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_name(f".{target.name}.part")
    shutil.copy2(source_path, partial)
    os.replace(partial, target)
    return {
        "provider": clip.get("source") or "free_stock",
        "original_url": clip.get("source_url") or asset.get("original_url"),
        "license": clip.get("license") or asset.get("license") or "Free stock license",
        "duration_seconds": float(clip.get("duration") or 0),
        "resolution": f"{clip.get('width') or 0}x{clip.get('height') or 0}",
        "format": target.suffix.lower().lstrip(".") or "mp4",
    }


def _generate_local_music(target: Path, duration: float) -> dict[str, Any]:
    ffmpeg = os.environ.get("OPENMONTAGE_FFMPEG_PATH") or shutil.which("ffmpeg")
    if not ffmpeg:
        raise ValueError("Không tìm thấy FFmpeg để tạo nhạc nền local")
    target.parent.mkdir(parents=True, exist_ok=True)
    duration = max(10.0, min(float(duration or 90), 900.0))
    command = [
        ffmpeg, "-y",
        "-f", "lavfi", "-i", f"sine=frequency=110:duration={duration}:sample_rate=48000",
        "-f", "lavfi", "-i", f"sine=frequency=164.81:duration={duration}:sample_rate=48000",
        "-f", "lavfi", "-i", f"sine=frequency=220:duration={duration}:sample_rate=48000",
        "-filter_complex",
        (
            "[0:a]volume=0.055[a0];[1:a]volume=0.025[a1];[2:a]volume=0.014[a2];"
            f"[a0][a1][a2]amix=inputs=3:normalize=0,lowpass=f=1100,"
            f"aecho=0.7:0.65:700:0.28,afade=t=in:st=0:d=5,"
            f"afade=t=out:st={max(0.0, duration - 7)}:d=7[out]"
        ),
        "-map", "[out]", "-c:a", "libmp3lame", "-b:a", "192k", str(target),
    ]
    completed = subprocess.run(command, capture_output=True, text=True, timeout=180, check=False)
    if completed.returncode != 0 or not target.is_file() or target.stat().st_size < MIN_FILE_BYTES:
        raise ValueError((completed.stderr or "Không tạo được nhạc local")[-500:])
    return {
        "provider": "local_ffmpeg",
        "license": "Original procedural audio generated locally — 0 USD",
        "original_url": None,
        "duration_seconds": duration,
        "format": "mp3",
        "generation_summary": "Nhạc nền ambient nguyên bản được tạo local bằng FFmpeg, chi phí 0 USD.",
    }


def _materialize_asset(
    project_dir: Path,
    asset: dict[str, Any],
    target: Path,
    queries: dict[str, list[str]],
) -> dict[str, Any]:
    asset_type = str(asset.get("type") or "")
    if asset_type in {"music", "audio", "sfx"} and not asset.get("original_url"):
        return _generate_local_music(target, float(asset.get("duration_seconds") or 90))
    provider = str(asset.get("provider") or "").lower()
    if provider == "pexels":
        exact = _download_pexels(asset, target)
        if exact:
            return exact
    if provider in {"archive_org", "archive.org"}:
        exact = _download_archive(asset, target)
        if exact:
            return exact
    fallback = _download_fallback(project_dir, asset, target, queries)
    if fallback:
        return fallback
    raise ValueError("Không tìm được file miễn phí phù hợp từ các provider đã cấu hình")


def _run_materialization(project_id: str, project_dir: Path) -> None:
    manifest_path = project_dir / "artifacts" / "asset_manifest.json"
    manifest = _read_json(manifest_path)
    assets = [item for item in manifest.get("assets") or [] if isinstance(item, dict)]
    queries = _slot_queries(project_dir)
    errors = []
    _set_job(project_id, status="downloading")
    for asset in assets:
        target = _asset_target(project_dir, asset)
        if target and target.is_file() and target.stat().st_size >= MIN_FILE_BYTES:
            continue
        asset_id = str(asset.get("id") or asset.get("scene_id") or "asset")
        _set_job(project_id, current=asset_id)
        try:
            if target is None:
                raise ValueError("Đường dẫn tài nguyên không hợp lệ")
            details = _materialize_asset(project_dir, asset, target, queries)
            asset.update({key: value for key, value in details.items() if value is not None})
            asset["source_tool"] = "asset_materializer"
            manifest.setdefault("metadata", {})["materialization"] = {
                "mode": "free_stock_and_local",
                "updated_at": _now(),
            }
            _write_json(manifest_path, manifest)
        except Exception as exc:
            errors.append({"id": asset_id, "error": str(exc)[:400]})
        report = asset_file_report(project_dir, manifest)
        _set_job(
            project_id,
            completed=report["ready"],
            total=report["total"],
            failed=len(errors),
            errors=errors[-20:],
        )
    report = asset_file_report(project_dir, manifest)
    materialization = {
        "mode": "free_stock_and_local",
        "updated_at": _now(),
        "files_ready": report["ready"],
        "files_total": report["total"],
        "files_missing": report["missing"],
        "complete": report["complete"],
    }
    metadata = manifest.setdefault("metadata", {})
    metadata["materialization"] = materialization
    search_stats = metadata.get("search_stats")
    if isinstance(search_stats, dict) and report["complete"]:
        video_scenes = {
            str(item.get("scene_id") or "")
            for item in assets
            if item.get("type") == "video" and item.get("scene_id")
        }
        search_stats["slots_filled"] = len(video_scenes)
        search_stats["slots_pending_selection"] = 0
        search_stats["music_pending_generation"] = False
        source_counts: dict[str, int] = {}
        for item in assets:
            provider = str(item.get("provider") or "unknown")
            source_counts[provider] = source_counts.get(provider, 0) + 1
        search_stats["sources_used"] = source_counts
    for item in assets:
        if item.get("provider") == "local_ffmpeg":
            item["generation_summary"] = (
                "Nhạc nền ambient nguyên bản được tạo local bằng FFmpeg, chi phí 0 USD."
            )
        for optional_key in (
            "original_url", "prompt", "model", "resolution", "format",
            "quality_score", "subtype", "generation_summary", "provider", "license",
        ):
            if item.get(optional_key) is None:
                item.pop(optional_key, None)
    if report["complete"]:
        metadata["gaps"] = []
        metadata["notes"] = "Đã tải và kiểm tra toàn bộ file trên máy; sẵn sàng duyệt để dựng phim."
    _write_json(manifest_path, manifest)

    checkpoint_path = project_dir / "checkpoint_assets.json"
    checkpoint = _read_json(checkpoint_path)
    if checkpoint.get("status") == "awaiting_human":
        review = checkpoint.setdefault("review", {})
        review["files_ready"] = report["ready"]
        review["files_total"] = report["total"]
        review["files_missing"] = report["missing"]
        review["all_files_exist"] = report["complete"]
        if report["complete"]:
            review["slots_filled"] = review.get("slots_total", review.get("slots_filled"))
            review["slots_pending_selection"] = 0
            review["music_pending_generation"] = False
            review["open_items"] = []
        checkpoint.setdefault("metadata", {})["materialization"] = materialization
        _write_json(checkpoint_path, checkpoint)

    _set_job(
        project_id,
        status="completed" if report["complete"] else "failed",
        completed=report["ready"],
        total=report["total"],
        failed=len(errors),
        current="",
        errors=errors[-20:],
        finished_at=_now(),
    )
