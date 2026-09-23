"""Local Ollama workflow agent for MOSA TOOL ALL.

The worker talks to Ollama over its local HTTP API and exposes a deliberately
small tool surface. It can inspect the bundled production instructions, write
inside one project workspace, execute registered on-device tools, and persist
validated checkpoints. Cloud/API tools are never exposed to this runner.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import os
import re
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from lib.checkpoint import get_pipeline_stages, write_checkpoint
from lib.paths import REPO_ROOT


DEFAULT_MODEL = "granite3.3:8b"
MAX_AGENT_ROUNDS = 30
MAX_TOOL_OUTPUT_CHARS = 48_000
MAX_CONSECUTIVE_TOOL_ERRORS = 5
_MODEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$")
_SENSITIVE_PATH_PARTS = {".env", ".git", "credentials", "secrets"}
_PULL_LOCK = threading.Lock()
_PULL_JOBS: dict[str, dict[str, Any]] = {}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def ollama_base_url() -> str:
    value = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434").strip().rstrip("/")
    if not value.startswith(("http://", "https://")):
        value = f"http://{value}"
    return value


def _request_json(
    path: str,
    payload: dict[str, Any] | None = None,
    *,
    timeout: float = 5.0,
) -> dict[str, Any]:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        f"{ollama_base_url()}{path}",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST" if data is not None else "GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            result = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        try:
            detail = exc.read().decode("utf-8", errors="replace")
        except Exception:
            detail = str(exc)
        raise RuntimeError(f"Ollama trả lỗi HTTP {exc.code}: {detail[:500]}") from exc
    except (OSError, urllib.error.URLError) as exc:
        raise RuntimeError(
            "Không kết nối được Ollama tại "
            f"{ollama_base_url()}. Hãy cài và mở Ollama trước."
        ) from exc
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise RuntimeError("Ollama trả về dữ liệu không hợp lệ") from exc
    if not isinstance(result, dict):
        raise RuntimeError("Ollama trả về dữ liệu không hợp lệ")
    return result


def ollama_status(*, timeout: float = 1.0) -> dict[str, Any]:
    try:
        payload = _request_json("/api/tags", timeout=timeout)
    except RuntimeError as exc:
        return {
            "online": False,
            "models": [],
            "error": str(exc),
            "host": ollama_base_url(),
        }
    models = []
    for item in payload.get("models") or []:
        if isinstance(item, dict) and isinstance(item.get("name"), str):
            models.append(item["name"])
    return {
        "online": True,
        "models": sorted(set(models)),
        "error": None,
        "host": ollama_base_url(),
    }


def _pull_worker(model: str) -> None:
    with _PULL_LOCK:
        _PULL_JOBS[model] = {
            "model": model,
            "status": "downloading",
            "started_at": _PULL_JOBS[model]["started_at"],
            "detail": "Ollama đang tải model về máy…",
        }
    try:
        _request_json("/api/pull", {"model": model, "stream": False}, timeout=7200)
    except Exception as exc:
        with _PULL_LOCK:
            _PULL_JOBS[model].update({
                "status": "error",
                "finished_at": _now(),
                "detail": str(exc),
            })
        return
    with _PULL_LOCK:
        _PULL_JOBS[model].update({
            "status": "completed",
            "finished_at": _now(),
            "detail": "Đã tải model. Có thể bắt đầu workflow local.",
        })


def start_model_pull(model: str = DEFAULT_MODEL) -> dict[str, Any]:
    model = (model or DEFAULT_MODEL).strip()
    if not _MODEL_RE.fullmatch(model):
        raise ValueError("Tên model Ollama không hợp lệ")
    status = ollama_status(timeout=2.0)
    if not status["online"]:
        raise ValueError(status["error"])
    if model in status["models"]:
        return {
            "model": model,
            "status": "completed",
            "detail": "Model đã có sẵn trên máy.",
        }
    with _PULL_LOCK:
        current = _PULL_JOBS.get(model)
        if current and current.get("status") in {"queued", "downloading"}:
            return dict(current)
        job = {
            "model": model,
            "status": "queued",
            "started_at": _now(),
            "detail": "Đã xếp hàng tải model từ Ollama.",
        }
        _PULL_JOBS[model] = job
    threading.Thread(target=_pull_worker, args=(model,), name="ollama-model-pull", daemon=True).start()
    return dict(job)


def model_pull_status(model: str = DEFAULT_MODEL) -> dict[str, Any]:
    with _PULL_LOCK:
        job = _PULL_JOBS.get(model)
        return dict(job) if job else {"model": model, "status": "idle"}


def _inside(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


def _is_sensitive_path(path: Path) -> bool:
    return any(part.lower() in _SENSITIVE_PATH_PARTS for part in path.parts)


class LocalWorkflowTools:
    def __init__(self, project_id: str, project_dir: Path, pipeline_type: str, model: str) -> None:
        self.project_id = project_id
        self.project_dir = project_dir.resolve()
        self.projects_dir = self.project_dir.parent
        self.pipeline_type = pipeline_type
        self.model = model

    @property
    def schemas(self) -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": "list_files",
                    "description": "List files under the project workspace or bundled repository.",
                    "parameters": {
                        "type": "object",
                        "required": ["base"],
                        "properties": {
                            "base": {"type": "string", "enum": ["project", "repo"]},
                            "path": {"type": "string", "default": "."},
                            "pattern": {"type": "string", "default": "*"},
                        },
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "read_file",
                    "description": "Read a UTF-8 text file from the project or bundled repository.",
                    "parameters": {
                        "type": "object",
                        "required": ["base", "path"],
                        "properties": {
                            "base": {"type": "string", "enum": ["project", "repo"]},
                            "path": {"type": "string"},
                            "start_line": {"type": "integer", "minimum": 1, "default": 1},
                            "max_lines": {"type": "integer", "minimum": 1, "maximum": 400, "default": 200},
                        },
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "write_project_file",
                    "description": "Write a UTF-8 artifact or production file inside this project workspace.",
                    "parameters": {
                        "type": "object",
                        "required": ["path", "content"],
                        "properties": {
                            "path": {"type": "string"},
                            "content": {"type": "string"},
                        },
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "list_local_tools",
                    "description": "List names of available zero-cost on-device MOSA media and render tools.",
                    "parameters": {"type": "object", "properties": {}},
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "describe_local_tool",
                    "description": "Read the input schema and purpose of one available local MOSA tool.",
                    "parameters": {
                        "type": "object",
                        "required": ["tool_name"],
                        "properties": {"tool_name": {"type": "string"}},
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "run_local_tool",
                    "description": "Execute one available on-device MOSA tool. Cloud, hybrid, paid and network tools are blocked.",
                    "parameters": {
                        "type": "object",
                        "required": ["tool_name", "inputs"],
                        "properties": {
                            "tool_name": {"type": "string"},
                            "inputs": {"type": "object"},
                        },
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "save_checkpoint",
                    "description": "Validate and save a MOSA pipeline checkpoint. Use awaiting_human for an approval gate.",
                    "parameters": {
                        "type": "object",
                        "required": ["stage", "status", "artifacts"],
                        "properties": {
                            "stage": {"type": "string"},
                            "status": {"type": "string", "enum": ["completed", "awaiting_human", "failed", "in_progress"]},
                            "artifacts": {"type": "object"},
                            "error": {"type": "string"},
                            "metadata": {"type": "object"},
                        },
                    },
                },
            },
        ]

    def _root(self, base: str) -> Path:
        if base == "project":
            return self.project_dir
        if base == "repo":
            return REPO_ROOT.resolve()
        raise ValueError("base phải là project hoặc repo")

    def _safe_path(self, base: str, relative: str) -> Path:
        root = self._root(base)
        target = (root / relative).resolve()
        if not _inside(target, root):
            raise ValueError("Đường dẫn nằm ngoài phạm vi được phép")
        if _is_sensitive_path(target.relative_to(root)):
            raise ValueError("Không được đọc file môi trường, credential hoặc secret")
        return target

    def list_files(self, base: str, path: str = ".", pattern: str = "*") -> dict[str, Any]:
        directory = self._safe_path(base, path)
        if not directory.is_dir():
            raise ValueError("Thư mục không tồn tại")
        files = []
        for candidate in directory.rglob(pattern or "*"):
            if candidate.is_file() and not _is_sensitive_path(candidate.relative_to(self._root(base))):
                files.append(str(candidate.relative_to(self._root(base))))
            if len(files) >= 200:
                break
        return {"files": files, "truncated": len(files) >= 200}

    def read_file(
        self,
        base: str,
        path: str,
        start_line: int = 1,
        max_lines: int = 200,
    ) -> dict[str, Any]:
        target = self._safe_path(base, path)
        if not target.is_file():
            raise ValueError("File không tồn tại")
        lines = target.read_text(encoding="utf-8", errors="replace").splitlines()
        start = max(0, int(start_line) - 1)
        count = max(1, min(400, int(max_lines)))
        selected = lines[start:start + count]
        return {
            "path": path,
            "start_line": start + 1,
            "end_line": start + len(selected),
            "total_lines": len(lines),
            "content": "\n".join(selected),
        }

    def write_project_file(self, path: str, content: str) -> dict[str, Any]:
        target = self._safe_path("project", path)
        protected = {"project.json", "agent_run.json", "agent_prompt.md", "agent_run.log"}
        if target.name in protected or target.name.startswith("checkpoint"):
            raise ValueError("File hệ thống phải được cập nhật bằng tool chuyên dụng")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return {
            "path": target.relative_to(self.project_dir).as_posix(),
            "bytes": len(content.encode("utf-8")),
        }

    def _available_local_tools(self) -> dict[str, Any]:
        from tools.base_tool import ToolRuntime, ToolStatus
        from tools.tool_registry import registry

        registry.ensure_discovered()
        allowed = {}
        for name in registry.list_all():
            tool = registry.get(name)
            if tool is None or tool.provider == "selector":
                continue
            if tool.runtime not in {ToolRuntime.LOCAL, ToolRuntime.LOCAL_GPU}:
                continue
            if tool.get_status() != ToolStatus.AVAILABLE:
                continue
            if tool.resource_profile.network_required:
                continue
            allowed[name] = tool
        return allowed

    def list_local_tools(self) -> dict[str, Any]:
        tools = self._available_local_tools()
        return {
            "tools": [
                {
                    "name": name,
                    "capability": tool.capability,
                    "runtime": tool.runtime.value,
                }
                for name, tool in sorted(tools.items())
            ],
            "count": len(tools),
            "instruction": "Gọi describe_local_tool trước khi chạy một tool cụ thể.",
        }

    def describe_local_tool(self, tool_name: str) -> dict[str, Any]:
        tool = self._available_local_tools().get(tool_name)
        if tool is None:
            raise ValueError("Tool không khả dụng hoặc không phải tool local miễn phí")
        return {
            "name": tool_name,
            "capability": tool.capability,
            "runtime": tool.runtime.value,
            "input_schema": tool.input_schema,
            "best_for": tool.best_for,
        }

    def _validate_input_paths(self, value: Any, key: str = "") -> None:
        if isinstance(value, dict):
            for child_key, child in value.items():
                self._validate_input_paths(child, str(child_key))
            return
        if isinstance(value, list):
            for child in value:
                self._validate_input_paths(child, key)
            return
        if not isinstance(value, str) or not any(token in key.lower() for token in ("path", "file", "dir")):
            return
        if value.startswith(("http://", "https://")):
            raise ValueError("Local runner không cho phép URL trong input đường dẫn")
        target = Path(value).expanduser()
        if not target.is_absolute():
            target = self.project_dir / target
        target = target.resolve()
        output_like = any(token in key.lower() for token in ("output", "destination", "target"))
        roots = (self.project_dir,) if output_like else (self.project_dir, REPO_ROOT.resolve())
        if not any(_inside(target, root) for root in roots):
            raise ValueError(f"Đường dẫn {key!r} nằm ngoài project/runtime")

    def run_local_tool(self, tool_name: str, inputs: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(inputs, dict):
            raise ValueError("inputs phải là object")
        if len(json.dumps(inputs, ensure_ascii=False)) > 100_000:
            raise ValueError("Tool input quá lớn")
        tools = self._available_local_tools()
        tool = tools.get(tool_name)
        if tool is None:
            raise ValueError("Tool không khả dụng hoặc không phải tool local miễn phí")
        self._validate_input_paths(inputs)
        estimate = float(tool.estimate_cost(inputs) or 0.0)
        if estimate > 0:
            raise ValueError("Tool có chi phí nên bị chặn trong Ollama local runner")
        result = tool.execute(inputs)
        payload = dataclasses.asdict(result) if dataclasses.is_dataclass(result) else result
        return {"tool": tool_name, "result": payload}

    def save_checkpoint(
        self,
        stage: str,
        status: str,
        artifacts: dict[str, Any] | str,
        error: str | None = None,
        metadata: dict[str, Any] | str | None = None,
    ) -> dict[str, Any]:
        if isinstance(artifacts, str):
            try:
                artifacts = json.loads(artifacts)
            except json.JSONDecodeError as exc:
                raise ValueError("artifacts phải là JSON object") from exc
        if isinstance(metadata, str):
            try:
                metadata = json.loads(metadata)
            except json.JSONDecodeError as exc:
                raise ValueError("metadata phải là JSON object") from exc
        if not isinstance(artifacts, dict):
            raise ValueError("artifacts phải là object")
        if metadata is not None and not isinstance(metadata, dict):
            raise ValueError("metadata phải là object")
        path = write_checkpoint(
            self.projects_dir,
            self.project_id,
            stage,
            status,
            artifacts,
            pipeline_type=self.pipeline_type,
            error=error,
            metadata={
                **(metadata or {}),
                "runner": "ollama",
                "model": self.model,
            },
        )
        return {"path": str(path), "stage": stage, "status": status}

    def call(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        function = getattr(self, name, None)
        if name.startswith("_") or not callable(function):
            raise ValueError(f"Tool không được phép: {name}")
        return function(**arguments)


def _select_model(requested: str | None, installed: list[str]) -> str:
    if requested:
        if requested not in installed:
            raise RuntimeError(f"Model {requested!r} chưa được tải trong Ollama")
        return requested
    for preferred in (DEFAULT_MODEL, "llama3.1:latest", "llama3.1"):
        if preferred in installed:
            return preferred
    if installed:
        return installed[0]
    raise RuntimeError("Ollama chưa có model. Hãy tải Llama 3.1 8B trong app trước.")


def _terminal_checkpoint(project_dir: Path, stages: list[str]) -> dict[str, Any] | None:
    for stage in stages:
        path = project_dir / f"checkpoint_{stage}.json"
        if not path.is_file():
            continue
        try:
            checkpoint = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if checkpoint.get("status") in {"completed", "awaiting_human", "failed"}:
            return checkpoint
    return None


def _active_stage(project_dir: Path, stages: list[str]) -> str:
    for stage in stages:
        checkpoint = project_dir / f"checkpoint_{stage}.json"
        if not checkpoint.is_file():
            return stage
        try:
            status = json.loads(checkpoint.read_text(encoding="utf-8")).get("status")
        except (OSError, json.JSONDecodeError, AttributeError):
            return stage
        if status == "in_progress":
            return stage
        if status not in {"completed", "awaiting_human"}:
            return stage
    return stages[-1]


def _normalize_tool_calls(candidates: Any) -> list[dict[str, Any]]:
    if not isinstance(candidates, list):
        return []
    calls: list[dict[str, Any]] = []
    seen: set[str] = set()
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        function = candidate.get("function")
        if not isinstance(function, dict):
            function = candidate
        name = function.get("name")
        arguments = function.get("arguments", function.get("parameters"))
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments)
            except json.JSONDecodeError:
                continue
        if not isinstance(name, str) or not isinstance(arguments, dict):
            continue
        signature = json.dumps([name, arguments], ensure_ascii=False, sort_keys=True)
        if signature in seen:
            continue
        seen.add(signature)
        calls.append({"function": {"name": name, "arguments": arguments}})
    return calls


def _content_tool_calls(content: Any) -> list[dict[str, Any]]:
    """Recover tool calls that a local model emitted as JSON text.

    Some Ollama models occasionally describe a valid function call in the
    assistant content instead of populating ``message.tool_calls``. Only JSON
    objects with the same small function-call shape accepted by the native API
    are recovered; prose and malformed objects remain inert.
    """
    if not isinstance(content, str) or not content.strip():
        return []
    decoder = json.JSONDecoder()
    candidates_found: list[Any] = []
    index = 0
    while index < len(content):
        start = content.find("{", index)
        if start < 0:
            break
        try:
            value, end = decoder.raw_decode(content, start)
        except json.JSONDecodeError:
            index = start + 1
            continue
        index = end
        candidates: list[Any]
        if isinstance(value, dict) and isinstance(value.get("tool_calls"), list):
            candidates = value["tool_calls"]
        else:
            candidates = [value]
        candidates_found.extend(candidates)
    return _normalize_tool_calls(candidates_found)


def run_agent(project_dir: Path, prompt_file: Path, requested_model: str | None = None) -> int:
    project_dir = project_dir.resolve()
    marker = json.loads((project_dir / "project.json").read_text(encoding="utf-8"))
    project_id = str(marker["project_id"])
    pipeline_type = str(marker["pipeline_type"])
    prompt = prompt_file.read_text(encoding="utf-8")
    status = ollama_status(timeout=3.0)
    if not status["online"]:
        raise RuntimeError(status["error"])
    model = _select_model(requested_model, status["models"])
    tools = LocalWorkflowTools(project_id, project_dir, pipeline_type, model)
    stages = get_pipeline_stages(pipeline_type)
    active_stage = _active_stage(project_dir, stages)
    system = f"""Bạn là local production agent của MOSA TOOL ALL, chạy hoàn toàn qua Ollama.
Bạn đang ở trong một agent loop và phải dùng tool để thực hiện công việc, không chỉ trả lời hướng dẫn.
MỖI phản hồi phải là đúng MỘT native tool call; content để trống. Không viết kế hoạch, không giải thích,
không đưa JSON tool call vào content và không hỏi người dùng xác nhận trong hội thoại. Khi cần đọc nhiều
file, gọi từng tool qua từng lượt. Chỉ dừng bằng một lần gọi save_checkpoint hợp lệ.
Chỉ được thao tác workspace dự án và runtime được cung cấp. Không đọc .env, không tìm API key, không gọi
cloud provider, không dùng tool hybrid/API, không phát sinh chi phí. Trước khi làm, đọc AGENT_GUIDE.md,
manifest pipeline và schema artifact cần thiết. Mỗi lượt chỉ hoàn thành stage kế tiếp còn thiếu. Kết thúc
bằng save_checkpoint với status completed hoặc awaiting_human; stage gated bắt buộc awaiting_human.
Chỉ dùng đúng các tool đã được cung cấp; không tự đặt tên tool như research_tool hoặc infographic_tool.
Nếu stage cần Internet/nguồn kiểm chứng mà không có tool phù hợp, gọi save_checkpoint với status
failed, artifacts rỗng và error ghi rõ giới hạn đó; awaiting_human chỉ dùng khi đã có artifact chuẩn
cần người dùng duyệt. Stage duy nhất cần xử lý trong lượt này là {active_stage!r}; không chọn stage khác.
Tuyệt đối không bịa nguồn hay kết quả. Model: {model}."""
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system},
        {"role": "user", "content": prompt},
    ]
    empty_rounds = 0
    consecutive_tool_errors = 0
    for round_index in range(MAX_AGENT_ROUNDS):
        response = _request_json(
            "/api/chat",
            {
                "model": model,
                "messages": messages,
                "tools": tools.schemas,
                "stream": False,
                "options": {"temperature": 0.2},
            },
            timeout=900,
        )
        message = response.get("message")
        if not isinstance(message, dict):
            raise RuntimeError("Ollama không trả về message hợp lệ")
        content = message.get("content")
        if content:
            print(f"[ollama] {content}", flush=True)
        tool_calls = _normalize_tool_calls(message.get("tool_calls") or [])
        if not tool_calls:
            tool_calls = _content_tool_calls(content)
            if tool_calls:
                message = {**message, "tool_calls": tool_calls}
                print(f"[ollama] Khôi phục {len(tool_calls)} tool call từ nội dung JSON", flush=True)
        messages.append(message)
        if not tool_calls:
            checkpoint = _terminal_checkpoint(project_dir, stages)
            if checkpoint:
                if checkpoint.get("status") == "failed":
                    print(f"[ollama] Stage thất bại: {checkpoint.get('error', 'không rõ lý do')}", flush=True)
                    return 1
                print(
                    f"[ollama] Hoàn tất checkpoint {checkpoint.get('stage')}: {checkpoint.get('status')}",
                    flush=True,
                )
                return 0
            empty_rounds += 1
            if empty_rounds >= 2:
                raise RuntimeError("Model dừng mà chưa ghi checkpoint hợp lệ")
            messages.append({
                "role": "user",
                "content": "Bạn chưa ghi checkpoint. Hãy dùng tool để hoàn thành stage kế tiếp và gọi save_checkpoint.",
            })
            continue
        empty_rounds = 0
        for tool_call in tool_calls:
            function = tool_call.get("function") if isinstance(tool_call, dict) else None
            name = function.get("name") if isinstance(function, dict) else None
            arguments = function.get("arguments") if isinstance(function, dict) else None
            if not isinstance(name, str) or not isinstance(arguments, dict):
                result: dict[str, Any] = {"ok": False, "error": "Tool call không hợp lệ"}
                tool_name = name or "unknown"
            else:
                tool_name = name
                try:
                    output = tools.call(name, arguments)
                    result = {"ok": True, "data": output}
                    consecutive_tool_errors = 0
                    print(f"[tool] {name}: ok", flush=True)
                except Exception as exc:
                    result = {"ok": False, "error": str(exc)}
                    consecutive_tool_errors += 1
                    print(f"[tool] {name}: {exc}", flush=True)
            serialized = json.dumps(result, ensure_ascii=False, default=str)
            messages.append({
                "role": "tool",
                "tool_name": tool_name,
                "content": serialized[:MAX_TOOL_OUTPUT_CHARS],
            })
            if result.get("ok") and tool_name == "save_checkpoint":
                checkpoint = _terminal_checkpoint(project_dir, stages)
                if checkpoint:
                    checkpoint_status = checkpoint.get("status")
                    print(
                        f"[ollama] Hoàn tất checkpoint {checkpoint.get('stage')}: {checkpoint_status}",
                        flush=True,
                    )
                    return 1 if checkpoint_status == "failed" else 0
            if consecutive_tool_errors >= MAX_CONSECUTIVE_TOOL_ERRORS:
                error = (
                    f"Model {model} gọi tool không hợp lệ {consecutive_tool_errors} lần liên tiếp. "
                    "Hãy chọn Codex/Claude cho pipeline phức tạp hoặc model Ollama mạnh hơn."
                )
                try:
                    tools.save_checkpoint(active_stage, "failed", {}, error=error)
                except Exception:
                    pass
                print(f"[ollama] LỖI: {error}", flush=True)
                return 1
    raise RuntimeError(f"Ollama vượt quá {MAX_AGENT_ROUNDS} vòng mà chưa tạo checkpoint")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-dir", type=Path, required=True)
    parser.add_argument("--prompt-file", type=Path, required=True)
    parser.add_argument("--model")
    args = parser.parse_args(argv)
    try:
        return run_agent(args.project_dir, args.prompt_file, args.model)
    except Exception as exc:
        print(f"[ollama] LỖI: {exc}", flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
