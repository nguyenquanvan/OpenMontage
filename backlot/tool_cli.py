"""Run MOSA TOOL ALL production tools from a command line, for Codex / Claude Code agents.

The packaged app ships its tools as compiled modules inside the executable, so an agent's own
Python cannot import them (there is no tools/*.py on disk). These commands run a tool inside the
app's interpreter instead, with the bundled FFmpeg/Node runtimes and the user's API keys:

    "MOSA TOOL ALL.exe" --list-tools --tool-output tools.json
    "MOSA TOOL ALL.exe" --describe-tool comfyui_image --tool-output info.json
    "MOSA TOOL ALL.exe" --run-tool comfyui_image --tool-input in.json --tool-output out.json

A windowed build has no console, so results are written as JSON to --tool-output. The exit code is
0 on success, 1 when the tool failed, 2 for a usage error (unknown tool, bad input, cost refused).
Tools with an estimated cost run only with --allow-cost.
"""

from __future__ import annotations

import dataclasses
import json
import sys
from pathlib import Path
from typing import Any

from lib.paths import REPO_ROOT

USAGE_ERROR = 2


def tool_command() -> list[str]:
    """argv prefix that runs this module's commands: the app itself when packaged."""
    if getattr(sys, "frozen", False):
        return [sys.executable]
    return [sys.executable, str(REPO_ROOT / "desktop" / "app.py")]


def _registry():
    from tools.tool_registry import registry

    registry.ensure_discovered()
    return registry


def list_tools() -> dict[str, Any]:
    registry = _registry()
    tools = []
    for name in sorted(registry.list_all()):
        tool = registry.get(name)
        try:
            # get_info carries the status and, for tools like comfyui_image, the license of the
            # workflow the connected server would actually run.
            info = tool.get_info()
            status, license_terms = info["status"], info.get("license")
        except Exception as exc:  # a broken provider check must not hide the other tools
            status, license_terms = f"error: {exc}", tool.license_terms or None
        tools.append({
            "name": name,
            "capability": tool.capability,
            "provider": tool.provider,
            "runtime": tool.runtime.value,
            "status": status,
            "best_for": list(tool.best_for)[:3],
            "license": license_terms,
        })
    return {"count": len(tools), "tools": tools}


def describe_tool(name: str) -> dict[str, Any]:
    tool = _registry().get(name)
    if tool is None:
        raise LookupError(name)
    return tool.get_info()


def run_tool(name: str, inputs: dict[str, Any], *, allow_cost: bool = False) -> tuple[int, dict[str, Any]]:
    tool = _registry().get(name)
    if tool is None:
        raise LookupError(name)
    estimate = float(tool.estimate_cost(inputs) or 0.0)
    if estimate > 0 and not allow_cost:
        return USAGE_ERROR, {
            "success": False,
            "tool": name,
            "estimated_cost_usd": estimate,
            "error": "Tool có chi phí; chỉ chạy khi đã được duyệt trong ngân sách và thêm --allow-cost.",
        }
    result = tool.execute(inputs)
    payload = dataclasses.asdict(result) if dataclasses.is_dataclass(result) else dict(result)
    payload["tool"] = name
    return (0 if payload.get("success") else 1), payload


def _write(output: Path | None, payload: dict[str, Any]) -> None:
    text = json.dumps(payload, ensure_ascii=False, indent=1, default=str)
    if output is None:
        print(text)
        return
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(text + "\n", encoding="utf-8")


def cli_main(args: Any) -> int:
    """Handle --list-tools / --describe-tool / --run-tool parsed by desktop.app.main."""
    output = args.tool_output
    try:
        if args.list_tools:
            _write(output, list_tools())
            return 0
        if args.describe_tool:
            _write(output, describe_tool(args.describe_tool))
            return 0
        inputs: dict[str, Any] = {}
        if args.tool_input is not None:
            inputs = json.loads(Path(args.tool_input).read_text(encoding="utf-8-sig"))
            if not isinstance(inputs, dict):
                raise ValueError("--tool-input phải là một JSON object")
        code, payload = run_tool(args.run_tool, inputs, allow_cost=args.allow_cost)
        _write(output, payload)
        return code
    except LookupError as exc:
        _write(output, {"success": False, "error": f"Không có tool tên {exc.args[0]!r}. Xem --list-tools."})
        return USAGE_ERROR
    except (OSError, ValueError) as exc:
        _write(output, {"success": False, "error": str(exc)})
        return USAGE_ERROR
    except Exception as exc:  # the agent needs the reason in the JSON, not a silent crash
        _write(output, {"success": False, "error": f"{type(exc).__name__}: {exc}"})
        return 1
