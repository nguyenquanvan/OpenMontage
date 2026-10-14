"""Find, start and stop the ComfyUI that the comfyui_image/video/music tools talk to.

Model Center can install "ComfyUI portable" under the app's data folder; the owner may also point
MOSA_COMFYUI_DIR at a ComfyUI they already have. When a ComfyUI tool runs and the server is not
answering, ``ensure_running`` starts the first launchable install and waits for it, so staff never
have to open ComfyUI by hand. Only a server this module started is stopped on app exit.
"""

from __future__ import annotations

import json
import os
import subprocess
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from lib.paths import DATA_DIR

PORTABLE_DIRNAME = "ComfyUI_windows_portable"
DEFAULT_SERVER_URL = "http://127.0.0.1:8188"
START_TIMEOUT_SECONDS = 240
# 8 GB cards run FLUX.1 schnell Q4 only with some VRAM kept free for the desktop; harmless on bigger cards.
RESERVE_VRAM_GB = "0.6"
_LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}
_LOCK = threading.Lock()
_last_error = ""


def managed_portable_dir() -> Path:
    return DATA_DIR / "ComfyUI" / PORTABLE_DIRNAME


def candidate_roots() -> list[Path]:
    """Where a ComfyUI checkout (main.py + models/) may live, most specific first."""
    roots: list[Path] = []
    configured = os.environ.get("MOSA_COMFYUI_DIR")
    if configured:
        roots.append(Path(configured).expanduser())
    roots.append(managed_portable_dir() / "ComfyUI")
    roots.extend([Path.home() / "Applications" / "ComfyUI", Path.home() / "ComfyUI", DATA_DIR / "ComfyUI"])
    return roots


def is_comfyui_root(path: Path) -> bool:
    return (path / "main.py").is_file() and (path / "models").is_dir()


def detect_root() -> Path | None:
    for root in candidate_roots():
        if is_comfyui_root(root):
            return root
    return None


def python_for(root: Path) -> Path | None:
    """The interpreter that runs this ComfyUI: the portable's embedded Python or the checkout's venv."""
    for name in ("python.exe", "python"):
        portable = root.parent / "python_embeded" / name
        if portable.is_file():
            return portable
    for relative in ("Scripts/python.exe", "bin/python"):
        for venv in (".venv", "venv"):
            python = root / venv / relative
            if python.is_file():
                return python
    return None


def launcher(root: Path, port: int) -> tuple[list[str], Path] | None:
    """(command, cwd) that starts this ComfyUI on 127.0.0.1:port, or None when its Python is unknown."""
    python = python_for(root)
    if python is None:
        return None
    if python.parent.name == "python_embeded":
        command = [str(python), "-s", str(Path("ComfyUI") / "main.py"), "--windows-standalone-build"]
        cwd = root.parent
    else:
        command = [str(python), "main.py"]
        cwd = root
    command += ["--listen", "127.0.0.1", "--port", str(port), "--disable-auto-launch", "--reserve-vram", RESERVE_VRAM_GB]
    return command, cwd


def has_gguf_node(root: Path) -> bool:
    return (root / "custom_nodes" / "ComfyUI-GGUF" / "nodes.py").is_file()


def offline_models(root: Path) -> dict[str, list[str]]:
    """Model files on disk, shaped like ComfyUIClient.list_models(), for when the server is not up yet."""
    models = root / "models"

    def names(folder: str, suffixes: tuple[str, ...] | None = None) -> list[str]:
        directory = models / folder
        if not directory.is_dir():
            return []
        return sorted(p.name for p in directory.iterdir()
                      if p.is_file() and (suffixes is None or p.suffix.lower() in suffixes))

    weights = (".safetensors", ".sft", ".pt", ".pth", ".ckpt", ".bin")
    return {
        "checkpoints": names("checkpoints", weights),
        "diffusion_models": names("diffusion_models", weights) + names("unet", weights),
        "vae": names("vae", weights),
        "clip": names("clip", weights) + names("text_encoders", weights),
        "loras": names("loras", weights),
        "unet_gguf": names("unet", (".gguf",)) + names("diffusion_models", (".gguf",)),
        "clip_gguf": names("clip") + names("text_encoders"),
    }


def _state_path() -> Path:
    return DATA_DIR / ".backlot" / "comfyui-managed.json"


def _read_state() -> dict[str, Any]:
    try:
        return json.loads(_state_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _write_state(state: dict[str, Any] | None) -> None:
    path = _state_path()
    if not state:
        path.unlink(missing_ok=True)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        result = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH", "/FO", "CSV"],
                                capture_output=True, text=True, check=False)
        return f'"{pid}"' in (result.stdout or "")
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def reachable(server_url: str, timeout: float = 3.0) -> bool:
    try:
        with urllib.request.urlopen(f"{server_url.rstrip('/')}/system_stats", timeout=timeout) as response:
            return response.status == 200
    except (urllib.error.URLError, OSError, ValueError):
        return False


def _local_port(server_url: str) -> int | None:
    parts = urlsplit(server_url)
    if parts.hostname not in _LOCAL_HOSTS:
        return None
    return parts.port or (443 if parts.scheme == "https" else 80)


def last_error() -> str:
    return _last_error


def ensure_running(server_url: str = DEFAULT_SERVER_URL, timeout: float = START_TIMEOUT_SECONDS,
                   popen: Any = subprocess.Popen) -> bool:
    """Return True once a ComfyUI answers at server_url, starting the app's install if it has to."""
    global _last_error
    if reachable(server_url):
        return True
    port = _local_port(server_url)
    if port is None:
        _last_error = f"ComfyUI ở {server_url} không phải máy này nên app không tự bật được."
        return False
    with _LOCK:
        if reachable(server_url):
            return True
        state = _read_state()
        if not (state.get("port") == port and _pid_alive(int(state.get("pid") or 0))):
            root = detect_root()
            launch = launcher(root, port) if root else None
            if launch is None:
                _last_error = ("Chưa có ComfyUI nào để bật: cài gói \"FLUX.1 schnell\" trong Model Center, "
                               "hoặc đặt MOSA_COMFYUI_DIR trỏ tới thư mục ComfyUI có sẵn.")
                return False
            command, cwd = launch
            log_dir = DATA_DIR / "logs"
            log_dir.mkdir(parents=True, exist_ok=True)
            log = open(log_dir / "comfyui.log", "a", encoding="utf-8")
            log.write(f"\n--- start {time.strftime('%Y-%m-%d %H:%M:%S')} {' '.join(command)}\n")
            log.flush()
            env = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}
            kwargs: dict[str, Any] = {"cwd": str(cwd), "env": env, "stdin": subprocess.DEVNULL,
                                      "stdout": log, "stderr": subprocess.STDOUT}
            if os.name == "nt":
                kwargs["creationflags"] = (getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
                                           | getattr(subprocess, "CREATE_NO_WINDOW", 0))
            else:
                kwargs["start_new_session"] = True
            try:
                process = popen(command, **kwargs)
            except OSError as exc:
                _last_error = f"Không bật được ComfyUI: {exc}"
                return False
            state = {"pid": process.pid, "port": port, "root": str(root), "started_at": time.time()}
            _write_state(state)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if reachable(server_url, timeout=2.0):
                _last_error = ""
                return True
            if not _pid_alive(int(state.get("pid") or 0)):
                _last_error = ("ComfyUI thoát ngay sau khi bật; xem logs/comfyui.log trong thư mục dữ liệu của app.")
                _write_state(None)
                return False
            time.sleep(1.5)
        _last_error = f"ComfyUI chưa trả lời sau {int(timeout)} giây; xem logs/comfyui.log."
        return False


def stop_managed() -> bool:
    """Stop the ComfyUI this module started (never one the owner started). Returns True when a process was stopped."""
    state = _read_state()
    pid = int(state.get("pid") or 0)
    _write_state(None)
    if not _pid_alive(pid):
        return False
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, check=False)
    else:
        try:
            os.kill(pid, 15)
        except OSError:
            return False
    return True


def status(server_url: str = DEFAULT_SERVER_URL) -> dict[str, Any]:
    root = detect_root()
    port = _local_port(server_url) or 8188
    python = python_for(root) if root else None
    pid = int(_read_state().get("pid") or 0)
    return {
        "server_url": server_url,
        "running": reachable(server_url),
        "root": str(root) if root else None,
        "launchable": bool(root and launcher(root, port)),
        "gguf_node": bool(root and has_gguf_node(root)),
        "managed_pid": pid if _pid_alive(pid) else None,
        "python": str(python) if python else None,
        "last_error": _last_error,
    }
