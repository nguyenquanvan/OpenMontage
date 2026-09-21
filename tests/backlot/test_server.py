"""Server/API tests for Backlot.

These cover the deterministic eval surface in internal/evals/BACKLOT_EVAL_PLAN.md:
API shape, path safety, media/thumb serving, range requests, and loose
performance budgets.
"""

from __future__ import annotations

import io
import json
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from backlot import server as server_mod
from backlot import settings as settings_mod
from backlot import state as state_mod


@pytest.fixture
def projects_root(tmp_path, monkeypatch):
    root = tmp_path / "projects"
    root.mkdir()
    monkeypatch.setattr(state_mod, "PROJECTS_DIR", root)
    monkeypatch.setattr(server_mod, "PROJECTS_DIR", root)
    monkeypatch.setattr(server_mod, "_summary_cache", {})
    monkeypatch.setattr(server_mod, "_PROJECTS_ROOT_STR", __import__("os").path.normcase(str(root.resolve())))
    monkeypatch.setattr(server_mod, "THUMB_CACHE_DIR", tmp_path / "thumbs")
    return root


@pytest.fixture
def client(projects_root, monkeypatch):
    async def no_watch():
        return None

    monkeypatch.setattr(server_mod, "_watch_projects", no_watch)
    with TestClient(server_mod.create_app()) as c:
        yield c


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def _make_project(root: Path, project_id: str = "film") -> Path:
    project = root / project_id
    (project / "artifacts").mkdir(parents=True)
    (project / "assets" / "images").mkdir(parents=True)
    (project / "assets" / "video").mkdir(parents=True)
    (project / "renders").mkdir(parents=True)
    _write_json(
        project / "project.json",
        {
            "project_id": project_id,
            "title": "Film",
            "pipeline_type": "cinematic",
            "created_at": "2026-07-02T00:00:00Z",
        },
    )
    _write_json(
        project / "checkpoint_script.json",
        {
            "version": "1.0",
            "project_id": project_id,
            "pipeline_type": "cinematic",
            "stage": "script",
            "status": "awaiting_human",
            "timestamp": "2026-07-02T00:01:00Z",
            "artifacts": {},
        },
    )
    return project


def _write_png(path: Path, color: tuple[int, int, int] = (200, 40, 80)) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    img = Image.new("RGB", (24, 16), color)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    path.write_bytes(buf.getvalue())


class TestBacklotServerApi:
    def test_health(self, client):
        response = client.get("/api/health")
        assert response.status_code == 200
        assert response.json() == {"ok": True, "app": "backlot"}

    def test_version_is_exposed(self, client):
        response = client.get("/api/version")
        assert response.status_code == 200
        payload = response.json()
        assert payload["app"] == "MOSA TOOL ALL"
        assert payload["version"]
        assert payload["build"]
        assert payload["label"].startswith("v")

    def test_provider_settings_are_masked_and_persisted_locally(self, client, tmp_path, monkeypatch):
        env_path = tmp_path / ".env"
        monkeypatch.setattr(settings_mod, "ENV_PATH", env_path)
        monkeypatch.delenv("FAL_KEY", raising=False)
        monkeypatch.delenv("OPENMONTAGE_COST_PROFILE", raising=False)
        monkeypatch.delenv("OPENMONTAGE_BUDGET_USD", raising=False)

        initial = client.get("/api/settings/providers")
        assert initial.status_code == 200
        assert initial.json()["cost_profile"] == "balanced"
        assert initial.json()["budget_usd"] is None
        fal = next(item for item in initial.json()["providers"] if item["key"] == "FAL_KEY")
        assert fal["configured"] is False
        assert fal["masked"] is None

        saved = client.put(
            "/api/settings/providers",
            json={"updates": {"FAL_KEY": "fal-secret-1234"}, "clear": []},
        )
        assert saved.status_code == 200
        assert "fal-secret-1234" not in saved.text
        fal = next(item for item in saved.json()["providers"] if item["key"] == "FAL_KEY")
        assert fal["configured"] is True
        assert fal["masked"] == "••••1234"
        assert 'FAL_KEY="fal-secret-1234"' in env_path.read_text(encoding="utf-8")
        assert env_path.stat().st_mode & 0o777 == 0o600

        cleared = client.put(
            "/api/settings/providers",
            json={"updates": {}, "clear": ["FAL_KEY"]},
        )
        assert cleared.status_code == 200
        fal = next(item for item in cleared.json()["providers"] if item["key"] == "FAL_KEY")
        assert fal["configured"] is False
        assert 'FAL_KEY=' in env_path.read_text(encoding="utf-8")

    def test_local_model_settings_are_exposed_and_persisted(self, client, tmp_path, monkeypatch):
        env_path = tmp_path / ".env"
        monkeypatch.setattr(settings_mod, "ENV_PATH", env_path)
        initial = client.get("/api/settings/providers").json()
        local_keys = {item["key"] for item in initial["local_settings"]}
        assert "VIDEO_GEN_LOCAL_ENABLED" in local_keys
        assert "VIDEO_GEN_LOCAL_MODEL" in local_keys

        saved = client.put(
            "/api/settings/providers",
            json={
                "updates": {
                    "VIDEO_GEN_LOCAL_ENABLED": "true",
                    "VIDEO_GEN_LOCAL_MODEL": "ltx2-local",
                    "COMFYUI_SERVER_URL": "http://localhost:8188",
                },
                "clear": [],
            },
        )
        assert saved.status_code == 200
        values = {item["key"]: item["value"] for item in saved.json()["local_settings"]}
        assert values["VIDEO_GEN_LOCAL_ENABLED"] == "true"
        assert values["VIDEO_GEN_LOCAL_MODEL"] == "ltx2-local"
        assert 'VIDEO_GEN_LOCAL_MODEL="ltx2-local"' in env_path.read_text(encoding="utf-8")

    def test_free_model_catalog_reports_tool_readiness(self, client):
        response = client.get("/api/free-models")
        assert response.status_code == 200
        catalog = response.json()
        assert {item["tool"] for item in catalog} >= {
            "local_diffusion", "wan_video", "piper_tts", "transcriber",
        }
        assert all("available" in item and "requirements" in item for item in catalog)
        assert all("installer" in item for item in catalog)

    def test_model_center_exposes_install_plans(self, client):
        response = client.get("/api/model-installs")
        assert response.status_code == 200
        installs = {item["id"]: item for item in response.json()}
        assert installs["piper-tts"]["size_label"]
        assert installs["whisper-local"]["install_supported"] is True
        assert installs["local-video-ltx"]["install_supported"] is False
        assert installs["vieneu-tts"]["tier"] == "essential"
        assert installs["musicgen-research"]["commercial_restricted"] is True
        assert "runtime_installed" in installs["florence-vision"]

    def test_model_center_rejects_unknown_or_unsupported_models(self, client):
        unknown = client.post("/api/model-installs/not-real", json={})
        assert unknown.status_code == 409
        unsupported = client.post("/api/model-installs/local-video-ltx", json={})
        assert unsupported.status_code == 409

    def test_model_center_uninstall_endpoint(self, client, monkeypatch):
        monkeypatch.setattr("backlot.server.uninstall_model", lambda model_id: {"id": model_id, "installed": False})
        response = client.delete("/api/model-installs/piper-tts")
        assert response.status_code == 200
        assert response.json() == {"id": "piper-tts", "installed": False}

    def test_runtime_status_exposes_production_dependencies(self, client):
        response = client.get("/api/runtime")
        assert response.status_code == 200
        payload = response.json()
        assert {"ffmpeg", "ffprobe", "node", "npm", "npx", "remotion"} <= payload.keys()
        assert {"available", "path", "version"} <= payload["ffmpeg"].keys()
        assert {"available", "path", "version"} <= payload["node"].keys()
        assert "available" in payload["remotion"]

    def test_cost_settings_are_persisted_and_validated(self, client, tmp_path, monkeypatch):
        env_path = tmp_path / ".env"
        monkeypatch.setattr(settings_mod, "ENV_PATH", env_path)
        monkeypatch.delenv("OPENMONTAGE_COST_PROFILE", raising=False)
        monkeypatch.delenv("OPENMONTAGE_BUDGET_USD", raising=False)

        saved = client.put(
            "/api/settings/providers",
            json={"updates": {}, "clear": [], "cost_profile": "economy", "budget_usd": 1.5},
        )
        assert saved.status_code == 200
        assert saved.json()["cost_profile"] == "economy"
        assert saved.json()["budget_usd"] == 1.5
        env_text = env_path.read_text(encoding="utf-8")
        assert 'OPENMONTAGE_COST_PROFILE="economy"' in env_text
        assert 'OPENMONTAGE_BUDGET_USD="1.5"' in env_text

        invalid_profile = client.put(
            "/api/settings/providers",
            json={"updates": {}, "clear": [], "cost_profile": "unlimited"},
        )
        assert invalid_profile.status_code == 400
        assert "cost_profile" in invalid_profile.json()["detail"]

        cleared = client.put(
            "/api/settings/providers",
            json={"updates": {}, "clear": [], "cost_profile": "quality", "budget_usd": None},
        )
        assert cleared.status_code == 200
        assert cleared.json()["cost_profile"] == "quality"
        assert cleared.json()["budget_usd"] is None

    def test_settings_page_is_available(self, client):
        page = client.get("/settings")
        assert page.status_code == 200
        assert "Cài đặt API" in page.text
        assert "/ui/settings.js" in page.text

    def test_workflow_catalog_exposes_pipeline_menu(self, client):
        response = client.get("/api/workflows")
        assert response.status_code == 200
        workflows = response.json()
        names = {workflow["name"] for workflow in workflows}
        assert "cinematic" in names
        assert "documentary-montage" in names
        assert all(workflow["stages"] for workflow in workflows if workflow["name"] != "framework-smoke")
        assert all("description" in workflow for workflow in workflows)

    def test_create_project_initializes_workspace_and_rejects_duplicates(self, client, projects_root):
        created = client.post(
            "/api/projects",
            json={
                "project_id": "product-launch",
                "title": "Product Launch",
                "pipeline_type": "cinematic",
            },
        )
        assert created.status_code == 201
        assert created.json()["url"] == "/p/product-launch"
        marker = projects_root / "product-launch" / "project.json"
        assert marker.is_file()
        marker_data = json.loads(marker.read_text(encoding="utf-8"))
        assert marker_data["title"] == "Product Launch"
        assert marker_data["pipeline_type"] == "cinematic"
        assert (projects_root / "product-launch" / "assets" / "images").is_dir()

        duplicate = client.post(
            "/api/projects",
            json={
                "project_id": "product-launch",
                "title": "Another title",
                "pipeline_type": "animation",
            },
        )
        assert duplicate.status_code == 409

    @pytest.mark.parametrize(
        "payload",
        [
            {"project_id": "Bad ID", "title": "Demo", "pipeline_type": "cinematic"},
            {"project_id": "demo", "title": "Demo", "pipeline_type": "missing"},
            {"project_id": "demo", "title": "", "pipeline_type": "cinematic"},
        ],
    )
    def test_create_project_validates_input(self, client, payload):
        response = client.post("/api/projects", json=payload)
        assert response.status_code == 400

    def test_provider_settings_reject_unknown_keys(self, client):
        response = client.put(
            "/api/settings/providers",
            json={"updates": {"NOT_A_REAL_KEY": "secret"}, "clear": []},
        )
        assert response.status_code == 400
        assert "Unknown provider setting" in response.json()["detail"]

    def test_projects_shape_and_state(self, client, projects_root):
        _make_project(projects_root, "film")

        projects = client.get("/api/projects")
        assert projects.status_code == 200
        body = projects.json()
        assert len(body) == 1
        assert body[0]["project_id"] == "film"
        assert body[0]["awaiting_human"] is True
        assert "stage_states" in body[0]

        state = client.get("/api/project/film/state")
        assert state.status_code == 200
        state_body = state.json()
        assert state_body["project_id"] == "film"
        assert state_body["title"] == "Film"
        assert state_body["stages"]

    @pytest.mark.parametrize(
        ("url", "status"),
        [
            ("/api/project/../state", 404),
            ("/api/project/C:/state", 400),
            ("/api/project/nope/state", 404),
        ],
    )
    def test_project_id_rejects_bad_or_unknown_ids(self, client, url, status):
        response = client.get(url)
        assert response.status_code == status

    def test_media_rejects_path_traversal(self, client, projects_root):
        _make_project(projects_root, "film")
        response = client.get("/media/film/%2E%2E/project.json")
        assert response.status_code == 403

    def test_media_serves_range_requests(self, client, projects_root):
        project = _make_project(projects_root, "film")
        media = project / "renders" / "final.mp4"
        media.write_bytes(b"0123456789")

        response = client.get("/media/film/renders/final.mp4", headers={"Range": "bytes=2-5"})

        assert response.status_code == 206
        assert response.content == b"2345"
        assert response.headers["content-range"].startswith("bytes 2-5/10")

    def test_thumb_downscales_image_and_passes_through_non_media(self, client, projects_root):
        project = _make_project(projects_root, "film")
        _write_png(project / "assets" / "images" / "sc1.png")
        text = project / "artifacts" / "note.txt"
        text.write_text("hello", encoding="utf-8")

        image = client.get("/thumb/film/assets/images/sc1.png?w=320")
        assert image.status_code == 200
        assert image.headers["content-type"] == "image/jpeg"
        assert image.content.startswith(b"\xff\xd8")

        passthrough = client.get("/thumb/film/artifacts/note.txt")
        assert passthrough.status_code == 200
        assert passthrough.content == b"hello"


class TestBacklotPerformanceBudgets:
    def test_projects_and_state_stay_within_loose_budgets(self, client, projects_root):
        for i in range(25):
            project = _make_project(projects_root, f"film-{i:02d}")
            _write_json(
                project / "artifacts" / "scene_plan.json",
                {"version": "1.0", "scenes": [{"id": "sc1", "start_seconds": 0, "end_seconds": 1}]},
            )

        t0 = time.perf_counter()
        cold = client.get("/api/projects")
        cold_s = time.perf_counter() - t0
        assert cold.status_code == 200
        assert cold_s < 2.0

        t1 = time.perf_counter()
        warm = client.get("/api/projects")
        warm_s = time.perf_counter() - t1
        assert warm.status_code == 200
        assert warm_s < 0.150

        t2 = time.perf_counter()
        state = client.get("/api/project/film-00/state")
        state_s = time.perf_counter() - t2
        assert state.status_code == 200
        assert state_s < 0.400

    def test_image_thumb_generation_stays_within_budget(self, client, projects_root):
        project = _make_project(projects_root, "film")
        _write_png(project / "assets" / "images" / "sc1.png")

        t0 = time.perf_counter()
        response = client.get("/thumb/film/assets/images/sc1.png?w=640")
        elapsed = time.perf_counter() - t0

        assert response.status_code == 200
        assert elapsed < 1.5


class TestFindingsFixes:
    """Regression tests for dogfood findings F-03 (thumb video fallback)."""

    def test_thumb_never_serves_raw_video_bytes(self, client, projects_root):
        p = _make_project(projects_root, "vid")
        fake_video = p / "renders" / "final.mp4"
        fake_video.parent.mkdir(parents=True, exist_ok=True)
        # Not a real video: ffmpeg poster extraction will fail.
        fake_video.write_bytes(b"\x00" * 4096)
        res = client.get("/thumb/vid/renders/final.mp4")
        assert res.status_code == 404  # never the raw video bytes (F-03)
