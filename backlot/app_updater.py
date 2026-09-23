"""Secure GitHub Release updater for the MOSA TOOL ALL desktop app."""

from __future__ import annotations

import hashlib
import os
import re
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

import requests

from lib.app_version import APP_BUILD, APP_VERSION


UPDATE_REPOSITORY = os.environ.get("MOSA_UPDATE_REPOSITORY", "nguyenquanvan/OpenMontage")
GITHUB_API_URL = f"https://api.github.com/repos/{UPDATE_REPOSITORY}/releases/latest"
RELEASE_URL = f"https://github.com/{UPDATE_REPOSITORY}/releases/latest"
CHECKSUM_ASSET_NAME = "SHA256SUMS.txt"
CACHE_SECONDS = 15 * 60
_SAFE_ASSET_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]+$")
_lock = threading.Lock()
_cached_release: tuple[float, dict[str, Any]] | None = None
_job: dict[str, Any] = {
    "status": "idle",
    "progress": 0,
    "detail": "",
    "asset_name": None,
}


def _version_parts(value: str) -> tuple[int, ...]:
    clean = value.strip().lower().lstrip("v").split("+", 1)[0].split("-", 1)[0]
    parts = clean.split(".")
    if not parts or any(not part.isdigit() for part in parts):
        raise ValueError(f"Phiên bản không hợp lệ: {value}")
    return tuple(int(part) for part in parts)


def is_newer_version(candidate: str, current: str = APP_VERSION) -> bool:
    candidate_parts = _version_parts(candidate)
    current_parts = _version_parts(current)
    width = max(len(candidate_parts), len(current_parts))
    return candidate_parts + (0,) * (width - len(candidate_parts)) > current_parts + (0,) * (width - len(current_parts))


def _platform_name() -> str:
    if sys.platform == "win32":
        return "windows"
    if sys.platform == "darwin":
        return "macos"
    return "unsupported"


def _asset_for_platform(assets: list[dict[str, Any]], platform_name: str) -> dict[str, Any] | None:
    for asset in assets:
        name = str(asset.get("name") or "")
        if platform_name == "windows" and name.startswith("MOSA-TOOL-ALL-Setup-") and name.endswith("-win-x64.exe"):
            return asset
        if platform_name == "macos" and name == "MOSA-TOOL-ALL-macOS.dmg":
            return asset
    return None


def _release_payload(force: bool = False) -> dict[str, Any]:
    global _cached_release
    now = time.monotonic()
    with _lock:
        if not force and _cached_release and now - _cached_release[0] < CACHE_SECONDS:
            return _cached_release[1]

    response = requests.get(
        GITHUB_API_URL,
        headers={"Accept": "application/vnd.github+json", "User-Agent": f"MOSA-TOOL-ALL/{APP_VERSION}"},
        timeout=15,
    )
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict) or not isinstance(payload.get("assets"), list):
        raise RuntimeError("GitHub trả về thông tin bản phát hành không hợp lệ")
    with _lock:
        _cached_release = (now, payload)
    return payload


def update_status(*, force: bool = False) -> dict[str, Any]:
    platform_name = _platform_name()
    try:
        release = _release_payload(force=force)
        tag = str(release.get("tag_name") or "")
        latest_version = tag.lstrip("v")
        assets = release.get("assets") or []
        asset = _asset_for_platform(assets, platform_name)
        checksum = next((item for item in assets if item.get("name") == CHECKSUM_ASSET_NAME), None)
        available = is_newer_version(latest_version)
        error = None
    except Exception as exc:
        tag = ""
        latest_version = None
        asset = None
        checksum = None
        available = False
        error = str(exc)

    with _lock:
        job = dict(_job)
    return {
        "current_version": APP_VERSION,
        "current_build": APP_BUILD,
        "platform": platform_name,
        "repository": UPDATE_REPOSITORY,
        "release_url": RELEASE_URL,
        "latest_version": latest_version,
        "latest_tag": tag or None,
        "update_available": available,
        "install_supported": platform_name in {"windows", "macos"} and bool(asset and checksum),
        "asset_name": asset.get("name") if asset else None,
        "asset_size": asset.get("size") if asset else None,
        "error": error,
        "job": job,
    }


def _download(url: str, destination: Path, *, progress_start: int, progress_end: int) -> None:
    response = requests.get(url, headers={"User-Agent": f"MOSA-TOOL-ALL/{APP_VERSION}"}, stream=True, timeout=(15, 120))
    response.raise_for_status()
    total = int(response.headers.get("Content-Length") or 0)
    received = 0
    temporary = destination.with_suffix(destination.suffix + ".part")
    with temporary.open("wb") as output:
        for chunk in response.iter_content(chunk_size=1024 * 1024):
            if not chunk:
                continue
            output.write(chunk)
            received += len(chunk)
            if total:
                progress = progress_start + int((progress_end - progress_start) * received / total)
                _set_job(progress=min(progress, progress_end))
    os.replace(temporary, destination)


def _expected_checksum(text: str, asset_name: str) -> str:
    for line in text.splitlines():
        fields = line.strip().split()
        if len(fields) >= 2 and fields[1].lstrip("*") == asset_name and re.fullmatch(r"[0-9a-fA-F]{64}", fields[0]):
            return fields[0].lower()
    raise RuntimeError(f"Không tìm thấy SHA-256 cho {asset_name}")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _set_job(**updates: Any) -> None:
    with _lock:
        _job.update(updates)


def _updates_dir() -> Path:
    root = Path(os.environ.get("OPENMONTAGE_DATA_DIR") or Path.home() / ".mosa-tool-all")
    path = root / "updates"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _launch_installer(path: Path) -> None:
    if sys.platform == "win32":
        creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | getattr(subprocess, "DETACHED_PROCESS", 0)
        subprocess.Popen(
            [
                str(path),
                "/SP-",
                "/SILENT",
                "/SUPPRESSMSGBOXES",
                "/CLOSEAPPLICATIONS",
                "/RESTARTAPPLICATIONS",
                "/CURRENTUSER",
            ],
            close_fds=True,
            creationflags=creationflags,
        )
        return
    if sys.platform == "darwin":
        subprocess.Popen(["open", str(path)], close_fds=True)
        return
    raise RuntimeError("Nền tảng này chưa hỗ trợ cài cập nhật tự động")


def _install_worker(release: dict[str, Any], asset: dict[str, Any], checksum_asset: dict[str, Any]) -> None:
    try:
        asset_name = str(asset.get("name") or "")
        if not _SAFE_ASSET_NAME.fullmatch(asset_name):
            raise RuntimeError("Tên file cập nhật không an toàn")
        version = str(release.get("tag_name") or "unknown").lstrip("v")
        release_dir = _updates_dir() / version
        release_dir.mkdir(parents=True, exist_ok=True)
        checksum_path = release_dir / CHECKSUM_ASSET_NAME
        installer_path = release_dir / asset_name

        _set_job(status="downloading", progress=2, detail="Đang tải chữ ký kiểm tra…", asset_name=asset_name)
        _download(str(checksum_asset["browser_download_url"]), checksum_path, progress_start=2, progress_end=5)
        expected = _expected_checksum(checksum_path.read_text(encoding="utf-8"), asset_name)
        _set_job(status="downloading", progress=5, detail="Đang tải bản cập nhật…")
        _download(str(asset["browser_download_url"]), installer_path, progress_start=5, progress_end=92)
        _set_job(status="verifying", progress=95, detail="Đang kiểm tra SHA-256…")
        if _sha256(installer_path) != expected:
            installer_path.unlink(missing_ok=True)
            raise RuntimeError("SHA-256 không khớp; bản cập nhật đã bị hủy")
        _set_job(status="launching", progress=100, detail="Đang mở trình cài đặt đã xác thực…")
        _launch_installer(installer_path)
        _set_job(status="launched", progress=100, detail="Trình cài đặt đã mở. App có thể tự đóng để cập nhật.")
    except Exception as exc:
        _set_job(status="error", detail=str(exc), progress=0)


def start_update() -> dict[str, Any]:
    with _lock:
        busy = _job["status"] in {"queued", "downloading", "verifying", "launching"}
    if busy:
        return update_status()
    try:
        release = _release_payload(force=True)
    except Exception as exc:
        raise ValueError(f"Không kết nối được GitHub Releases: {exc}") from exc
    latest_version = str(release.get("tag_name") or "").lstrip("v")
    if not is_newer_version(latest_version):
        raise ValueError("Bạn đang dùng phiên bản mới nhất")
    assets = release.get("assets") or []
    asset = _asset_for_platform(assets, _platform_name())
    checksum = next((item for item in assets if item.get("name") == CHECKSUM_ASSET_NAME), None)
    if not asset or not checksum:
        raise ValueError("Bản phát hành chưa có bộ cài hoặc SHA-256 phù hợp cho máy này")
    _set_job(status="queued", progress=0, detail="Đang chuẩn bị tải bản cập nhật…", asset_name=asset.get("name"))
    thread = threading.Thread(target=_install_worker, args=(release, asset, checksum), name="mosa-app-update", daemon=True)
    thread.start()
    return update_status()
