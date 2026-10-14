"""Contracts for the evidence-led health infographic workflow."""

from pathlib import Path

from lib.pipeline_loader import get_required_tools, get_stage_order, load_pipeline
from schemas.artifacts import validate_artifact
from styles.playbook_loader import load_playbook


ROOT = Path(__file__).resolve().parent.parent.parent


def test_health_infographic_manifest_is_complete() -> None:
    manifest = load_pipeline("health-infographic")

    assert manifest["category"] == "health"
    assert manifest["reference_input"]["supported"] is True
    assert get_stage_order(manifest) == [
        "research",
        "proposal",
        "script",
        "scene_plan",
        "assets",
        "edit",
        "compose",
        "publish",
    ]
    assert {"tts_selector", "image_selector", "video_compose", "audio_mixer"} <= get_required_tools(manifest)


def test_health_infographic_intake_is_ready_for_backlot() -> None:
    intake = load_pipeline("health-infographic")["project_intake"]
    fields = {field["name"]: field for field in intake["fields"]}

    assert intake["style_playbook"] == "health-editorial-pro"
    assert intake["style_playbook_field"] == "visual_style"
    assert fields["topic"]["required"] is True
    assert fields["duration_minutes"]["default"] == "8"
    assert fields["visual_style"]["default"] == "health-editorial-pro"
    assert fields["motion_intensity"]["default"] == "balanced"
    assert fields["aspect_ratio"]["default"] == "16:9"
    assert "{topic}" in intake["brief_template"]
    assert "không thay thế tư vấn y tế" in intake["brief_template"]


def test_health_professional_playbooks_validate() -> None:
    for name in ("health-editorial-pro", "health-clinical-3d", "health-food-documentary"):
        playbook = load_playbook(name)
        assert playbook["identity"]["category"] in {"motion-graphics", "cinematic"}
        assert "embedded text" in playbook["asset_generation"]["image_negative_prompt"]
        assert any("source_ref" in rule for rule in playbook["quality_rules"])


def test_health_stage_skills_enforce_evidence_and_runtime_governance() -> None:
    manifest = load_pipeline("health-infographic")
    bodies = {}
    for stage in manifest["stages"]:
        path = ROOT / "skills" / f"{stage['skill']}.md"
        assert path.is_file(), f"Missing health director skill: {path}"
        bodies[stage["name"]] = path.read_text(encoding="utf-8")

    assert "claim_evidence_matrix" in bodies["research"]
    assert "source_ref" in bodies["script"]
    assert "present both" in bodies["proposal"]
    assert "render_runtime" in bodies["proposal"]
    assert "HyperFrames" in bodies["compose"]
    assert "Professional Motion Pack" in bodies["scene_plan"]
    assert "mechanism_flow" in bodies["edit"]
    assert "20% strong motion" in bodies["scene_plan"]
    assert "không sao chép" in manifest["project_intake"]["brief_template"]


def test_own_script_field_is_optional_and_stored_as_file() -> None:
    intake = load_pipeline("health-infographic")["project_intake"]
    fields = {field["name"]: field for field in intake["fields"]}

    own_script = fields["own_script"]
    assert own_script["required"] is False
    assert own_script["type"] == "textarea"
    assert own_script["store"] == "file"
    assert own_script["max_length"] == 200000
    assert own_script["rows"] == 10
    assert "{own_script}" in intake["brief_template"]
    assert "không viết lại" in intake["brief_template"]


def test_own_script_mode_is_taught_to_every_affected_director() -> None:
    manifest = load_pipeline("health-infographic")
    skills = {stage["name"]: stage["skill"] for stage in manifest["stages"]}
    skills["executive_producer"] = manifest["orchestration"]["skill"]

    for name in ("executive_producer", "research", "proposal", "script", "compose", "publish"):
        body = (ROOT / "skills" / f"{skills[name]}.md").read_text(encoding="utf-8")
        assert "Kịch bản có sẵn" in body or "own-script.md" in body, name


def test_executive_producer_stops_when_own_script_duplicates_reference_transcript() -> None:
    skill = load_pipeline("health-infographic")["orchestration"]["skill"]
    body = (ROOT / "skills" / f"{skill}.md").read_text(encoding="utf-8")

    assert "transcript_fetcher" in body
    assert "awaiting_human" in body
    assert "Chạy thẳng" in body


def test_professional_motion_components_are_registered() -> None:
    explainer = (ROOT / "remotion-composer" / "src" / "Explainer.tsx").read_text(encoding="utf-8")
    scene_docs = (ROOT / "remotion-composer" / "SCENE_TYPES.md").read_text(encoding="utf-8")
    for scene_type in (
        "mechanism_flow",
        "evidence_ladder",
        "myth_reality",
        "timeline_steps",
        "ingredient_spotlight",
    ):
        assert f'cut.type === "{scene_type}"' in explainer
        assert f'`{scene_type}`' in scene_docs


def test_professional_motion_cut_validates_as_edit_decisions() -> None:
    validate_artifact(
        "edit_decisions",
        {
            "version": "1.0",
            "render_runtime": "remotion",
            "renderer_family": "explainer-data",
            "composition_mode": "templated",
            "motionIntensity": "balanced",
            "cuts": [
                {
                    "id": "mechanism-1",
                    "source": "",
                    "type": "mechanism_flow",
                    "in_seconds": 0,
                    "out_seconds": 5,
                    "title": "Cơ chế",
                    "sourceLabel": "Nguồn minh họa",
                    "mechanismNodes": [
                        {"label": "Bước 1"},
                        {"label": "Bước 2", "emphasis": True},
                    ],
                    "transition_in": "wipe-left",
                    "transition_out": "fade",
                    "transition_duration": 0.5,
                    "motion_intensity": "dynamic",
                }
            ],
        },
    )


def test_chalkboard_style_is_offered_and_composes_as_chalk_scenes() -> None:
    intake = load_pipeline("health-infographic")["project_intake"]
    fields = {field["name"]: field for field in intake["fields"]}
    styles = {option["value"] for option in fields["visual_style"]["options"]}
    assert "health-chalkboard" in styles

    playbook = load_playbook("health-chalkboard")
    assert playbook["asset_generation"]["scene_type"] == "chalk_scene"
    assert playbook["typography"]["headings"]["font"] == "Patrick Hand"
    assert "embedded text" in playbook["asset_generation"]["image_negative_prompt"]
    assert any("source_ref" in rule for rule in playbook["quality_rules"])


def test_chalk_scene_is_registered_and_loads_a_vietnamese_font() -> None:
    explainer = (ROOT / "remotion-composer" / "src" / "Explainer.tsx").read_text(encoding="utf-8")
    scene_docs = (ROOT / "remotion-composer" / "SCENE_TYPES.md").read_text(encoding="utf-8")
    component = (
        ROOT / "remotion-composer" / "src" / "components" / "ChalkScene.tsx"
    ).read_text(encoding="utf-8")
    assert 'cut.type === "chalk_scene"' in explainer
    assert "`chalk_scene`" in scene_docs
    assert '"vietnamese"' in component


def test_chalk_scene_cut_validates_as_edit_decisions() -> None:
    validate_artifact(
        "edit_decisions",
        {
            "version": "1.0",
            "render_runtime": "remotion",
            "renderer_family": "explainer-data",
            "composition_mode": "templated",
            "cuts": [
                {
                    "id": "chalk-1",
                    "source": "projects/demo/assets/images/chalk-1.png",
                    "type": "chalk_scene",
                    "in_seconds": 0,
                    "out_seconds": 9,
                    "text": "Sau 60 tuổi, cơ bắp giảm khoảng 3% mỗi năm",
                    "highlightWords": ["3%"],
                    "badge": "5",
                    "sourceLabel": "Harvard Health, 2026",
                    "transform": {"animation": "zoom-in"},
                    "transition_in": "fade",
                }
            ],
        },
    )
