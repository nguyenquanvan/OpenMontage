"""Tell the desktop shell when an agent run stops (finished, waiting for review, or failed).

A run that stops while nobody is looking can sit idle for hours; listeners registered here (the
desktop window flashes the taskbar and plays a sound) make sure the owner notices.
"""

from __future__ import annotations

from typing import Callable

Listener = Callable[[str, str, str], None]
_listeners: list[Listener] = []


def add_listener(listener: Listener) -> None:
    _listeners.append(listener)


def run_stopped(project_id: str, status: str, detail: str = "") -> None:
    """Call every listener with (project_id, status, detail); a failing listener never breaks the runner."""
    for listener in list(_listeners):
        try:
            listener(project_id, status, detail)
        except Exception:
            pass
