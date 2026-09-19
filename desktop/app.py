"""OpenMontage desktop launcher.

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

from lib.runtime import configure_bundled_runtime


APP_NAME = "OpenMontage"
DEFAULT_PORT = 4750


def user_data_dir() -> Path:
    """Return the per-user writable data directory for the current OS."""
    override = os.environ.get("OPENMONTAGE_DATA_DIR")
    if override:
        return Path(override).expanduser()
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
        return base / APP_NAME
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_NAME
    return Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share") / APP_NAME


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
    raise RuntimeError("Không tìm được cổng local để chạy OpenMontage")


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


def start_server(port: int) -> Any:
    """Start Uvicorn in a daemon thread and return its server object."""
    import uvicorn
    from backlot.server import app

    config = uvicorn.Config(
        app,
        host="127.0.0.1",
        port=port,
        log_level="warning",
        access_log=False,
    )
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, name="openmontage-backlot", daemon=True)
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
        APP_NAME,
        url,
        width=1440,
        height=920,
        min_size=(1024, 680),
        text_select=True,
    )
    webview.start(debug=False)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="OpenMontage")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--browser", action="store_true", help="Mở bằng trình duyệt thay vì cửa sổ native")
    args = parser.parse_args(argv)

    data_dir = user_data_dir()
    configure_user_paths(data_dir)
    configure_bundled_runtime()
    port = choose_port(args.port)
    server = start_server(port)
    url = f"http://127.0.0.1:{port}/"
    try:
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
