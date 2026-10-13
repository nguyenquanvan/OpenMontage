"""Agents run the app's tools through `MOSA TOOL ALL.exe --run-tool`, since the packaged app has no tools/*.py."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from backlot import runner as runner_mod
from backlot import tool_cli
from desktop import app as desktop_app
from tools.base_tool import BaseTool, ToolResult
from tools.tool_registry import ToolRegistry


class FreeTool(BaseTool):
    name = "fake_free"
    capability = "image_generation"
    input_schema = {"type": "object", "required": ["prompt"], "properties": {"prompt": {"type": "string"}}}
    license_terms = {"name": "Apache-2.0", "commercial_use": True}

    def execute(self, inputs):
        return ToolResult(success=True, data={"echo": inputs["prompt"], "path": Path("out.png")}, artifacts=["out.png"])


class PaidTool(BaseTool):
    name = "fake_paid"
    executed = False

    def estimate_cost(self, inputs):
        return 0.4

    def execute(self, inputs):
        PaidTool.executed = True
        return ToolResult(success=True)


class BrokenTool(BaseTool):
    name = "fake_broken"

    def execute(self, inputs):
        return ToolResult(success=False, error="model missing")


@pytest.fixture
def registry(monkeypatch):
    fake = ToolRegistry()
    for cls in (FreeTool, PaidTool, BrokenTool):
        fake.register(cls())
    monkeypatch.setattr(tool_cli, "_registry", lambda: fake)
    PaidTool.executed = False
    return fake


def cli_args(**values):
    defaults = {"list_tools": False, "describe_tool": None, "run_tool": None, "tool_input": None,
                "tool_output": None, "allow_cost": False}
    return SimpleNamespace(**{**defaults, **values})


def test_list_reports_status_and_license(registry):
    listing = tool_cli.list_tools()

    entry = next(item for item in listing["tools"] if item["name"] == "fake_free")
    assert listing["count"] == 3
    assert entry["status"] == "available"
    assert entry["license"]["commercial_use"] is True


def test_describe_returns_the_input_schema(registry):
    assert tool_cli.describe_tool("fake_free")["input_schema"]["required"] == ["prompt"]
    with pytest.raises(LookupError):
        tool_cli.describe_tool("nope")


def test_run_returns_the_tool_result_as_json_ready_data(registry):
    code, payload = tool_cli.run_tool("fake_free", {"prompt": "làng tuyết"})

    assert code == 0
    assert payload["success"] is True
    assert payload["data"]["echo"] == "làng tuyết"
    assert payload["tool"] == "fake_free"


def test_paid_tools_need_allow_cost(registry):
    code, payload = tool_cli.run_tool("fake_paid", {})
    assert code == tool_cli.USAGE_ERROR
    assert payload["estimated_cost_usd"] == 0.4
    assert PaidTool.executed is False

    code, _ = tool_cli.run_tool("fake_paid", {}, allow_cost=True)
    assert code == 0
    assert PaidTool.executed is True


def test_cli_writes_results_and_exit_codes(registry, tmp_path):
    request = tmp_path / "in.json"
    request.write_text(json.dumps({"prompt": "p"}), encoding="utf-8")
    out = tmp_path / "io" / "out.json"

    assert tool_cli.cli_main(cli_args(run_tool="fake_free", tool_input=request, tool_output=out)) == 0
    assert json.loads(out.read_text(encoding="utf-8"))["data"]["path"] == "out.png"

    assert tool_cli.cli_main(cli_args(run_tool="fake_broken", tool_output=out)) == 1
    assert json.loads(out.read_text(encoding="utf-8"))["error"] == "model missing"

    assert tool_cli.cli_main(cli_args(run_tool="missing", tool_output=out)) == tool_cli.USAGE_ERROR
    assert "--list-tools" in json.loads(out.read_text(encoding="utf-8"))["error"]

    request.write_text("[1, 2]", encoding="utf-8")
    assert tool_cli.cli_main(cli_args(run_tool="fake_free", tool_input=request, tool_output=out)) == tool_cli.USAGE_ERROR


def test_desktop_entry_point_dispatches_tool_commands(registry, tmp_path, monkeypatch):
    for name in ("OPENMONTAGE_DATA_DIR", "OPENMONTAGE_PROJECTS_DIR", "OPENMONTAGE_ENV_PATH", "OPENMONTAGE_CACHE_DIR"):
        monkeypatch.setenv(name, str(tmp_path / name.lower()))
    monkeypatch.setenv("PATH", desktop_app.os.environ.get("PATH", ""))
    out = tmp_path / "tools.json"

    assert desktop_app.main(["--list-tools", "--tool-output", str(out)]) == 0

    assert {item["name"] for item in json.loads(out.read_text(encoding="utf-8"))["tools"]} == {
        "fake_free", "fake_paid", "fake_broken"}


def test_agent_prompt_tells_the_agent_how_to_call_app_tools(tmp_path):
    prompt = runner_mod._build_prompt("p", tmp_path, {"pipeline_type": "animation"}, "Phim ngắn")

    assert "--run-tool <tên>" in prompt
    assert " ".join(f'"{part}"' for part in tool_cli.tool_command()) in prompt
    assert "commercial_use" in prompt
    assert "--allow-cost" in prompt
