"""ComfyUIClient.cancel stops only its own prompt: pending ones leave the queue, a running one is interrupted."""

from __future__ import annotations

import pytest

from tools._comfyui import client as module
from tools._comfyui.client import ComfyUIClient


class Response:
    def __init__(self, payload=None):
        self.payload = payload or {}

    def json(self):
        return self.payload

    def raise_for_status(self):
        return None


def item(prompt_id):
    # ComfyUI queue entries: (number, prompt_id, prompt, extra_data, outputs_to_execute)
    return [1, prompt_id, {}, {}, []]


@pytest.fixture
def server(monkeypatch):
    """A fake ComfyUI whose queue snapshots are served in order; records every POST."""
    state = {"snapshots": [], "posts": []}

    def get(url, timeout):
        assert url.endswith("/queue")
        snapshot = state["snapshots"].pop(0) if len(state["snapshots"]) > 1 else state["snapshots"][0]
        return Response(snapshot)

    def post(url, json, timeout):
        state["posts"].append((url.rsplit("/", 1)[-1], json))
        return Response()

    monkeypatch.setattr(module.requests, "get", get)
    monkeypatch.setattr(module.requests, "post", post)
    return state


def test_a_pending_prompt_is_removed_and_other_prompts_are_left_alone(server):
    server["snapshots"] = [{"queue_running": [item("theirs")], "queue_pending": [item("mine"), item("other")]},
                           {"queue_running": [item("theirs")], "queue_pending": [item("other")]}]

    assert ComfyUIClient("http://127.0.0.1:8188").cancel("mine") == "removed"
    assert server["posts"] == [("queue", {"delete": ["mine"]})]


def test_the_running_prompt_is_interrupted_by_id(server):
    server["snapshots"] = [{"queue_running": [item("mine")], "queue_pending": [item("other")]}]

    assert ComfyUIClient("http://127.0.0.1:8188").cancel("mine") == "interrupted"
    assert server["posts"] == [("interrupt", {"prompt_id": "mine"})]


def test_a_prompt_that_starts_during_the_cancel_is_still_interrupted(server):
    server["snapshots"] = [{"queue_running": [item("theirs")], "queue_pending": [item("mine")]},
                           {"queue_running": [item("mine")], "queue_pending": []}]

    assert ComfyUIClient("http://127.0.0.1:8188").cancel("mine") == "interrupted"
    assert server["posts"] == [("queue", {"delete": ["mine"]}), ("interrupt", {"prompt_id": "mine"})]


def test_someone_elses_running_prompt_is_never_interrupted(server):
    server["snapshots"] = [{"queue_running": [item("theirs")], "queue_pending": []}]

    assert ComfyUIClient("http://127.0.0.1:8188").cancel("mine") == "not_queued"
    assert server["posts"] == []
