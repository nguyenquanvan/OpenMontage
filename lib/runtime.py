"""Runtime discovery for bundled and system media/composition dependencies."""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any


def resource_root() -> Path:
    """Return the frozen bundle root or the repository root in development."""
    frozen_root = getattr(sys, "_MEIPASS", None)
    if frozen_root:
        return Path(frozen_root)
    return Path(__file__).resolve().parent.parent


def configure_bundled_runtime(root: Path | None = None) -> dict[str, str | None]:
    """Prepend bundled Node/FFmpeg binaries to PATH when present."""
    root = root or resource_root()
    runtime_root = Path(os.environ.get("OPENMONTAGE_RUNTIME_DIR") or root / "runtime")
    if not runtime_root.is_dir():
        return {"runtime_dir": None, "ffmpeg": None, "node": None}

    if os.name == "nt":
        node_dir = runtime_root / "node"
        ffmpeg_path = runtime_root / "ffmpeg" / "ffmpeg.exe"
        ffprobe_path = runtime_root / "ffmpeg" / "ffprobe.exe"
    else:
        node_dir = runtime_root / "node" / "bin"
        ffmpeg_path = runtime_root / "ffmpeg" / "ffmpeg"
        ffprobe_path = runtime_root / "ffmpeg" / "ffprobe"

    path_entries = [str(path) for path in (node_dir, ffmpeg_path.parent) if path.is_dir()]
    if path_entries:
        current = os.environ.get("PATH", "")
        os.environ["PATH"] = os.pathsep.join(path_entries + ([current] if current else []))
    if ffmpeg_path.is_file():
        os.environ.setdefault("OPENMONTAGE_FFMPEG_PATH", str(ffmpeg_path))
    if ffprobe_path.is_file():
        os.environ.setdefault("OPENMONTAGE_FFPROBE_PATH", str(ffprobe_path))
    if node_dir.is_dir():
        os.environ.setdefault("OPENMONTAGE_NODE_DIR", str(node_dir))
    os.environ.setdefault("OPENMONTAGE_RUNTIME_DIR", str(runtime_root))
    return {
        "runtime_dir": str(runtime_root),
        "ffmpeg": str(ffmpeg_path) if ffmpeg_path.is_file() else None,
        "ffprobe": str(ffprobe_path) if ffprobe_path.is_file() else None,
        "node": str(node_dir) if node_dir.is_dir() else None,
    }


def _version(command: str, args: list[str] | None = None) -> str | None:
    path = shutil.which(command)
    if not path:
        return None
    version_args = args or (["-version"] if command in {"ffmpeg", "ffprobe"} else ["--version"])
    try:
        result = subprocess.run(
            [path, *version_args],
            capture_output=True,
            text=True,
            timeout=8,
            check=False,
        )
    except OSError:
        return None
    if result.returncode != 0:
        return None
    output = (result.stdout or result.stderr).strip().splitlines()
    return output[0] if output else None


def runtime_status() -> dict[str, Any]:
    """Return user-facing readiness for the bundled production runtimes."""
    root = resource_root()
    configured = configure_bundled_runtime(root)
    composer = root / "remotion-composer"
    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")
    node = shutil.which("node")
    npm = shutil.which("npm") or shutil.which("npm.cmd")
    npx = shutil.which("npx") or shutil.which("npx.cmd")
    return {
        "platform": platform.platform(),
        "architecture": platform.machine(),
        "bundle_root": str(root),
        "runtime_dir": configured["runtime_dir"],
        "ffmpeg": {"available": bool(ffmpeg), "path": ffmpeg, "version": _version("ffmpeg")},
        "ffprobe": {"available": bool(ffprobe), "path": ffprobe, "version": _version("ffprobe")},
        "node": {"available": bool(node), "path": node, "version": _version("node")},
        "npm": {"available": bool(npm), "path": npm, "version": _version("npm")},
        "npx": {"available": bool(npx), "path": npx, "version": _version("npx")},
        "remotion": {
            "composer_dir": str(composer),
            "available": composer.is_dir() and (composer / "node_modules").is_dir(),
        },
    }
