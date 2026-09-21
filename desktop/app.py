"""MOSA TOOL ALL desktop launcher.

The desktop shell owns a local Backlot server and presents it in a native
pywebview window. Project data and API keys live in the user's OS data folder,
never inside the packaged application bundle.
"""

from __future__ import annotations

import argparse
import os
import socket
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path
from typing import Any

from lib.app_version import APP_NAME, APP_VERSION
from lib.runtime import configure_bundled_runtime


LEGACY_APP_NAME = "OpenMontage"
DEFAULT_PORT = 4750
_STDIO_SINKS: list[Any] = []


def _open_stdio_sink() -> Any:
    return open(os.devnull, "w", encoding="utf-8")


def ensure_standard_streams() -> None:
    """Provide harmless streams for windowed builds without a console."""
    for stream_name in ("stdout", "stderr"):
        if getattr(sys, stream_name) is None:
            sink = _open_stdio_sink()
            _STDIO_SINKS.append(sink)
            setattr(sys, stream_name, sink)


def user_data_dir() -> Path:
    """Return the per-user writable data directory for the current OS."""
    override = os.environ.get("OPENMONTAGE_DATA_DIR")
    if override:
        return Path(override).expanduser()
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    preferred = base / APP_NAME
    legacy = base / LEGACY_APP_NAME
    return legacy if legacy.is_dir() and not preferred.exists() else preferred


def configure_user_paths(data_dir: Path) -> None:
    """Point mutable app state at a writable user directory before imports."""
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "projects").mkdir(parents=True, exist_ok=True)
    (data_dir / ".backlot").mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("OPENMONTAGE_DATA_DIR", str(data_dir))
    os.environ.setdefault("OPENMONTAGE_PROJECTS_DIR", str(data_dir / "projects"))
    os.environ.setdefault("OPENMONTAGE_ENV_PATH", str(data_dir / ".env"))
    os.environ.setdefault("OPENMONTAGE_CACHE_DIR", str(data_dir / ".backlot"))


def choose_port(preferred: int = DEFAULT_PORT) -> int:
    """Use the familiar development port when free, otherwise pick a port."""
    for candidate in (preferred, 0):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                probe.bind(("127.0.0.1", candidate))
            except OSError:
                continue
            return int(probe.getsockname()[1])
    raise RuntimeError(f"Không tìm được cổng local để chạy {APP_NAME}")


def wait_for_server(port: int, timeout: float = 20.0) -> None:
    """Wait until the health endpoint is reachable."""
    deadline = time.monotonic() + timeout
    url = f"http://127.0.0.1:{port}/api/health"
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1.0) as response:
                if response.status == 200:
                    return
        except Exception as exc:  # pragma: no cover - timing dependent
            last_error = exc
        time.sleep(0.15)
    detail = f": {last_error}" if last_error else ""
    raise RuntimeError(f"Backlot không khởi động được{detail}")


def server_config(application: Any, port: int) -> Any:
    """Build a Uvicorn config that is safe for a windowed desktop app."""
    import uvicorn

    return uvicorn.Config(
        application,
        host="127.0.0.1",
        port=port,
        log_level="warning",
        access_log=False,
        log_config=None,
    )


def start_server(port: int) -> Any:
    """Start Uvicorn in a daemon thread and return its server object."""
    import uvicorn
    from backlot.server import app

    config = server_config(app, port)
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, name="mosa-tool-all-backlot", daemon=True)
    thread.start()
    wait_for_server(port)
    return server


def open_window(url: str, *, browser_only: bool = False) -> None:
    """Show the app in a native window, falling back to the default browser."""
    if browser_only:
        webbrowser.open(url)
        return
    try:
        import webview
    except ImportError:
        webbrowser.open(url)
        return

    webview.create_window(
        f"{APP_NAME} {APP_VERSION}",
        url,
        width=1440,
        height=920,
        min_size=(1024, 680),
        text_select=True,
    )
    webview.start(debug=False)


def main(argv: list[str] | None = None) -> int:
    ensure_standard_streams()
    parser = argparse.ArgumentParser(prog=APP_NAME)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--browser", action="store_true", help="Mở bằng trình duyệt thay vì cửa sổ native")
    parser.add_argument(
        "--server-only",
        action="store_true",
        help="Chỉ chạy Backlot server, dùng cho kiểm tra bản đóng gói",
    )
    args = parser.parse_args(argv)

    data_dir = user_data_dir()
    configure_user_paths(data_dir)
    configure_bundled_runtime()
    port = choose_port(args.port)
    server = start_server(port)
    url = f"http://127.0.0.1:{port}/"
    try:
        if args.server_only:
            while True:
                time.sleep(3600)
        open_window(url, browser_only=args.browser)
        if args.browser:
            # Keep the local server alive when running the explicit browser mode.
            while True:
                time.sleep(3600)
    except KeyboardInterrupt:
        return 0
    finally:
        server.should_exit = True
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
