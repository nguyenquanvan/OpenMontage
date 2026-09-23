from __future__ import annotations

import json
import os

from backlot import asset_materializer as materializer
from backlot import state as state_mod
from tools import base_tool


def _write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def test_asset_file_report_requires_real_nonempty_files(tmp_path):
    project = tmp_path / "project"
    ready = project / "assets" / "video" / "ready.mp4"
    ready.parent.mkdir(parents=True)
    ready.write_bytes(b"x" * 2_048)
    manifest = {
        "version": "1.0",
        "assets": [
            {"id": "ready", "type": "video", "path": "assets/video/ready.mp4"},
            {"id": "missing", "type": "video", "path": "assets/video/missing.mp4"},
        ],
    }

    report = materializer.asset_file_report(project, manifest)

    assert report["total"] == 2
    assert report["ready"] == 1
    assert report["missing"] == 1
    assert report["complete"] is False
    assert report["missing_entries"][0]["id"] == "missing"


def test_materialization_status_combines_disk_and_job_state(tmp_path, monkeypatch):
    projects = tmp_path / "projects"
    project = projects / "film"
    _write_json(
        project / "artifacts" / "asset_manifest.json",
        {
            "version": "1.0",
            "assets": [
                {"id": "clip", "type": "video", "path": "assets/video/clip.mp4"},
            ],
        },
    )
    monkeypatch.setattr(state_mod, "PROJECTS_DIR", projects)
    monkeypatch.setattr(materializer, "_JOBS", {})

    status = materializer.materialization_status("film")

    assert status["missing"] == 1
    assert status["job"]["status"] == "idle"


def test_start_materialization_launches_one_background_job(tmp_path, monkeypatch):
    projects = tmp_path / "projects"
    project = projects / "film"
    _write_json(
        project / "artifacts" / "asset_manifest.json",
        {
            "version": "1.0",
            "assets": [
                {"id": "clip", "type": "video", "path": "assets/video/clip.mp4"},
            ],
        },
    )
    monkeypatch.setattr(state_mod, "PROJECTS_DIR", projects)
    monkeypatch.setattr(materializer, "_JOBS", {})
    launched = []

    class FakeThread:
        def __init__(self, **kwargs):
            launched.append(kwargs)

        def start(self):
            return None

    monkeypatch.setattr(materializer.threading, "Thread", FakeThread)

    status = materializer.start_materialization("film")
    second = materializer.start_materialization("film")

    assert status["job"]["status"] == "queued"
    assert second["job"]["status"] == "queued"
    assert len(launched) == 1


def test_tool_dotenv_uses_desktop_user_data_path(tmp_path, monkeypatch):
    env_path = tmp_path / "MOSA TOOL ALL" / ".env"
    env_path.parent.mkdir(parents=True)
    env_path.write_text('PEXELS_API_KEY="saved-locally"\n', encoding="utf-8")
    monkeypatch.setenv("OPENMONTAGE_ENV_PATH", str(env_path))
    monkeypatch.delenv("PEXELS_API_KEY", raising=False)

    base_tool._load_dotenv()

    assert os.environ["PEXELS_API_KEY"] == "saved-locally"
