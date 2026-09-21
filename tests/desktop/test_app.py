from __future__ import annotations

import io

from desktop import app


def test_windowed_build_replaces_missing_standard_streams(monkeypatch) -> None:
    stdout_sink = io.StringIO()
    stderr_sink = io.StringIO()
    sinks = iter((stdout_sink, stderr_sink))

    monkeypatch.setattr(app.sys, "stdout", None)
    monkeypatch.setattr(app.sys, "stderr", None)
    monkeypatch.setattr(app, "_open_stdio_sink", lambda: next(sinks))
    monkeypatch.setattr(app, "_STDIO_SINKS", [])

    app.ensure_standard_streams()

    assert app.sys.stdout is stdout_sink
    assert app.sys.stderr is stderr_sink
    assert app.sys.stdout.isatty() is False
    assert app.sys.stderr.isatty() is False


def test_uvicorn_config_does_not_initialize_console_logging(monkeypatch) -> None:
    monkeypatch.setattr(app.sys, "stdout", None)
    monkeypatch.setattr(app.sys, "stderr", None)

    config = app.server_config(object(), 4750)

    assert config.log_config is None
