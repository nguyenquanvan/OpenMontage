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

if __package__ in (None, "") and not getattr(sys, "frozen", False):
    # Run as `python desktop/app.py` (agents call --run-tool this way from a source checkout).
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib.app_version import APP_NAME, APP_VERSION
from lib.runtime import configure_bundled_runtime


LEGACY_APP_NAME = "OpenMontage"
DEFAULT_PORT = 4750
LOG_MAX_BYTES = 5 * 1024 * 1024
_STDIO_SINKS: list[Any] = []


def _open_stdio_sink() -> Any:
    """Windowed builds have no console: keep their stdout/stderr in <data>/logs/desktop.log.

    The previous log moves to desktop.log.1 once it passes LOG_MAX_BYTES; if the
    data folder cannot be written, output is discarded as before.
    """
    try:
        log_dir = user_data_dir() / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        path = log_dir / "desktop.log"
        if path.exists() and path.stat().st_size > LOG_MAX_BYTES:
            os.replace(path, log_dir / "desktop.log.1")
        sink = open(path, "a", encoding="utf-8", errors="backslashreplace", buffering=1)
        sink.write(f"\n--- {APP_NAME} {APP_VERSION} started {time.strftime('%Y-%m-%d %H:%M:%S')} pid {os.getpid()}\n")
        return sink
    except OSError:
        return open(os.devnull, "w", encoding="utf-8")


def ensure_standard_streams() -> None:
    """Provide UTF-8 streams for windowed builds and Windows worker logs."""
    os.environ.setdefault("PYTHONUTF8", "1")
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name)
        if stream is None:
            if not _STDIO_SINKS:
                _STDIO_SINKS.append(_open_stdio_sink())
            setattr(sys, stream_name, _STDIO_SINKS[0])
            continue
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8", errors="backslashreplace")
            except (OSError, ValueError):
                # Some redirected or test streams cannot be reconfigured.
                pass


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


def configure_agent_path() -> None:
    """Expose user-installed coding agents to a GUI app's minimal PATH."""
    candidates = [
        Path.home() / ".local" / "bin",
        Path.home() / ".npm-global" / "bin",
    ]
    if sys.platform == "darwin":
        candidates.extend([
            Path("/opt/homebrew/bin"),
            Path("/usr/local/bin"),
            Path("/Applications/ChatGPT.app/Contents/Resources"),
        ])
    elif sys.platform == "win32":
        appdata = os.environ.get("APPDATA")
        if appdata:
            candidates.append(Path(appdata) / "npm")
        local_appdata = os.environ.get("LOCALAPPDATA")
        if local_appdata:
            local = Path(local_appdata)
            candidates.append(local / "Microsoft" / "WinGet" / "Links")
            codex_bin = local / "OpenAI" / "Codex" / "bin"
            if codex_bin.is_dir():
                candidates.extend(
                    path for path in codex_bin.iterdir()
                    if path.is_dir() and (path / "codex.exe").is_file()
                )
    current = [entry for entry in os.environ.get("PATH", "").split(os.pathsep) if entry]
    additions = [str(path) for path in candidates if path.is_dir() and str(path) not in current]
    if additions:
        os.environ["PATH"] = os.pathsep.join(additions + current)


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


FLASHW_ALL = 0x3
FLASHW_TIMERNOFG = 0xC
MB_ICONASTERISK = 0x40
MB_ICONEXCLAMATION = 0x30


def attention_listener(window_title: str, user32: Any = None):
    """Flash the app on the taskbar until it is focused, and play a sound, when an agent run stops."""

    def notify(project_id: str, status: str, detail: str) -> None:
        if sys.platform != "win32":
            return
        import ctypes

        api = user32 or ctypes.windll.user32

        class FLASHWINFO(ctypes.Structure):
            _fields_ = [
                ("cbSize", ctypes.c_uint),
                ("hwnd", ctypes.c_void_p),
                ("dwFlags", ctypes.c_ulong),
                ("uCount", ctypes.c_uint),
                ("dwTimeout", ctypes.c_ulong),
            ]

        hwnd = api.FindWindowW(None, window_title)
        if hwnd:
            info = FLASHWINFO(ctypes.sizeof(FLASHWINFO), hwnd, FLASHW_ALL | FLASHW_TIMERNOFG, 0, 0)
            api.FlashWindowEx(ctypes.byref(info))
        api.MessageBeep(MB_ICONEXCLAMATION if status == "failed" else MB_ICONASTERISK)

    return notify


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
    parser.add_argument("--ollama-worker", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--project-dir", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--prompt-file", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--model", help=argparse.SUPPRESS)
    tools = parser.add_argument_group("Chạy tool của app (dành cho agent)")
    tools.add_argument("--list-tools", action="store_true", help="Ghi danh sách tool và trạng thái ra JSON")
    tools.add_argument("--describe-tool", metavar="TÊN", help="Ghi thông tin đầy đủ và input_schema của một tool")
    tools.add_argument("--run-tool", metavar="TÊN", help="Chạy một tool với input JSON")
    tools.add_argument("--tool-input", type=Path, metavar="FILE", help="File JSON input cho --run-tool")
    tools.add_argument("--tool-output", type=Path, metavar="FILE", help="Nơi ghi kết quả JSON")
    tools.add_argument("--allow-cost", action="store_true", help="Cho phép chạy tool có chi phí")
    args = parser.parse_args(argv)

    data_dir = user_data_dir()
    configure_user_paths(data_dir)
    configure_bundled_runtime()
    configure_agent_path()
    if args.list_tools or args.describe_tool or args.run_tool:
        from backlot.tool_cli import cli_main

        return cli_main(args)
    if args.ollama_worker:
        if args.project_dir is None or args.prompt_file is None:
            parser.error("--ollama-worker requires --project-dir and --prompt-file")
        from backlot.ollama_agent import run_agent

        try:
            return run_agent(args.project_dir, args.prompt_file, args.model)
        except Exception as exc:
            print(f"[ollama] LỖI: {exc}", flush=True)
            return 1
    port = choose_port(args.port)
    server = start_server(port)
    if not args.server_only:
        from backlot import notifications

        notifications.add_listener(attention_listener(f"{APP_NAME} {APP_VERSION}"))
    update_stop = threading.Event()
    if not args.server_only and getattr(sys, "frozen", False):
        from backlot.app_updater import automatic_update_loop

        threading.Thread(
            target=automatic_update_loop,
            args=(update_stop,),
            name="mosa-auto-update-check",
            daemon=True,
        ).start()
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
        update_stop.set()
        server.should_exit = True
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
