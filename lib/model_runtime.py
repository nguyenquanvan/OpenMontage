"""Bridge production tools to Model Center isolated Python runtimes."""

from __future__ import annotations

import json
import subprocess
import time
from typing import Any

from backlot.model_installer import model_runtime_info
from lib.runtime import resource_root
from tools.base_tool import ToolResult


def managed_model_available(model_id: str) -> bool:
    try:
        info = model_runtime_info(model_id)
    except ValueError:
        return False
    worker = resource_root() / "runtime_workers" / "model_worker.py"
    return bool(info["installed"] and info["python"] and worker.is_file())


def run_model_worker(
    model_id: str,
    operation: str,
    payload: dict[str, Any],
    *,
    timeout: int = 3600,
) -> ToolResult:
    info = model_runtime_info(model_id)
    if not info["installed"] or not info["python"]:
        return ToolResult(success=False, error=f"Model {model_id} chưa được cài từ Model Center")
    worker = resource_root() / "runtime_workers" / "model_worker.py"
    request = {**payload, "model_dir": info["target"]}
    started = time.time()
    result = subprocess.run(
        [info["python"], str(worker), operation, json.dumps(request, ensure_ascii=False)],
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "Local model failed").strip()
        try:
            error = json.loads(detail.splitlines()[-1]).get("error", detail)
        except (json.JSONDecodeError, AttributeError):
            error = detail
        return ToolResult(success=False, error=str(error)[-2000:], duration_seconds=round(time.time() - started, 2))
    lines = [line for line in result.stdout.splitlines() if line.strip()]
    try:
        data = json.loads(lines[-1]) if lines else {}
    except json.JSONDecodeError:
        data = {"stdout": result.stdout.strip()}
    artifacts = [data["output"]] if data.get("output") else []
    return ToolResult(
        success=True,
        data=data,
        artifacts=artifacts,
        duration_seconds=round(time.time() - started, 2),
        model=model_id,
    )
