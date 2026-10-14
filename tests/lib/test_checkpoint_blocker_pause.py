"""A blocker pause is a valid checkpoint, and an invalid one never bricks a project.

The first real desktop run paused at proposal with ``awaiting_human``, no
artifact and an ``error`` explaining why. ``read_checkpoint`` rejected that
file on every read, so the run watcher thread died, "Bắt đầu workflow" failed
and the board offered an approve button that could only error.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from lib.checkpoint import (  # noqa: E402
    CheckpointValidationError,
    get_completed_stages,
    get_next_stage,
    read_checkpoint,
    validate_checkpoint,
)
from tests.contracts.test_phase0_contracts import sample_artifact  # noqa: E402

BOM = bytes([0xEF, 0xBB, 0xBF])


def _checkpoint(stage, status, artifacts, **extra):
    base = {
        "version": "1.0",
        "project_id": "proj",
        "pipeline_type": "health-infographic",
        "stage": stage,
        "status": status,
        "timestamp": "2026-10-14T01:27:06+00:00",
        "artifacts": artifacts,
    }
    base.update(extra)
    return base


def _completed_research():
    return _checkpoint("research", "completed", {"research_brief": sample_artifact("research_brief")})


def test_awaiting_human_with_an_error_needs_no_artifact():
    validate_checkpoint(_checkpoint(
        "proposal", "awaiting_human", {},
        error="Reference analysis blocked: missing yt_dlp",
    ))


def test_awaiting_human_without_an_error_still_needs_its_artifact():
    with pytest.raises(CheckpointValidationError, match="proposal_packet"):
        validate_checkpoint(_checkpoint("proposal", "awaiting_human", {}))
    with pytest.raises(CheckpointValidationError, match="proposal_packet"):
        validate_checkpoint(_checkpoint("proposal", "awaiting_human", {}, error="   "))


def test_completed_never_skips_the_artifact_even_with_an_error():
    with pytest.raises(CheckpointValidationError, match="proposal_packet"):
        validate_checkpoint(_checkpoint("proposal", "completed", {}, error="x"))


def test_checkpoint_with_a_bom_is_read(tmp_path):
    project = tmp_path / "proj"
    project.mkdir()
    payload = json.dumps(_completed_research()).encode("utf-8")
    (project / "checkpoint_research.json").write_bytes(BOM + payload)

    checkpoint = read_checkpoint(tmp_path, "proj", "research")

    assert checkpoint["status"] == "completed"


def test_an_unreadable_checkpoint_does_not_count_and_does_not_raise(tmp_path, caplog):
    project = tmp_path / "proj"
    project.mkdir()
    (project / "checkpoint_research.json").write_text(json.dumps(_completed_research()), encoding="utf-8")
    # The agent's own hand-written proposal pause, minus the error field that
    # would make it valid.
    (project / "checkpoint_proposal.json").write_text(
        json.dumps(_checkpoint("proposal", "awaiting_human", {})), encoding="utf-8",
    )
    (project / "checkpoint_script.json").write_text("{not json", encoding="utf-8")

    with caplog.at_level("WARNING"):
        completed = get_completed_stages(tmp_path, "proj", "health-infographic")

    assert completed == ["research"]
    assert get_next_stage(tmp_path, "proj", "health-infographic") == "proposal"
    assert "checkpoint proj/proposal" in caplog.text
