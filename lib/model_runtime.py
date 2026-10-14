"""Bridge production tools to Model Center isolated Python runtimes."""

from __future__ import annotations

import json
import os
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


_CUDA_OOM_MARKERS = ("cuda out of memory", "outofmemoryerror", "cublas_status_alloc_failed",
                     "cudaerrormemoryallocation", "cudnn_status_alloc_failed")


def _cuda_out_of_memory(text: str) -> bool:
    lowered = text.lower()
    return any(marker in lowered for marker in _CUDA_OOM_MARKERS)


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
    command = [info["python"], str(worker), operation, json.dumps(request, ensure_ascii=False)]
    # The packaged app reads pipes in the ANSI code page unless told otherwise; Vietnamese paths need UTF-8 both ways.
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}

    def run(environment: dict[str, str]) -> subprocess.CompletedProcess:
        return subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace",
                              timeout=timeout, check=False, env=environment)

    result = run(env)
    device_fallback = None
    if result.returncode != 0 and _cuda_out_of_memory(result.stderr or result.stdout or ""):
        # ComfyUI often holds most of an 8 GB card; finish the job on the CPU rather than fail it.
        # An empty CUDA_VISIBLE_DEVICES still exposes the card on Windows; -1 hides every device.
        result = run({**env, "CUDA_VISIBLE_DEVICES": "-1"})
        device_fallback = "cpu"
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
    if device_fallback:
        data["device_fallback"] = device_fallback
    if data.get("output"):
        artifacts = [data["output"]]
    else:
        artifacts = [item["output"] for item in data.get("outputs") or [] if item.get("output")]
    return ToolResult(
        success=True,
        data=data,
        artifacts=artifacts,
        duration_seconds=round(time.time() - started, 2),
        model=model_id,
    )
