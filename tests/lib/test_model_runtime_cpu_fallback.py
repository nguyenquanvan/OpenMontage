"""A model worker that runs out of GPU memory is retried once on the CPU."""

from __future__ import annotations

import json

from lib import model_runtime


class Completed:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode, self.stdout, self.stderr = returncode, stdout, stderr


def installed(monkeypatch, tmp_path):
    monkeypatch.setattr(model_runtime, "model_runtime_info",
                        lambda model_id: {"installed": True, "python": "python", "target": str(tmp_path)})


def test_cuda_oom_is_retried_with_the_gpu_hidden(monkeypatch, tmp_path):
    installed(monkeypatch, tmp_path)
    calls = []

    def run(command, **kwargs):
        assert kwargs["encoding"] == "utf-8" and kwargs["errors"] == "replace"
        calls.append(kwargs.get("env"))
        if len(calls) == 1:
            return Completed(1, stderr='{"error": "OutOfMemoryError: CUDA out of memory. Tried to allocate 2.00 GiB"}')
        return Completed(0, stdout=json.dumps({"output": str(tmp_path / "up.png")}))

    monkeypatch.setattr(model_runtime.subprocess, "run", run)

    result = model_runtime.run_model_worker("realesrgan", "realesrgan_upscale", {"input_path": "a.png"})

    assert result.success
    assert "CUDA_VISIBLE_DEVICES" not in calls[0]
    assert calls[1]["CUDA_VISIBLE_DEVICES"] == "-1"
    assert calls[0]["PYTHONIOENCODING"] == calls[1]["PYTHONIOENCODING"] == "utf-8"
    assert result.data["device_fallback"] == "cpu"


def test_other_failures_are_not_retried(monkeypatch, tmp_path):
    installed(monkeypatch, tmp_path)
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        return Completed(1, stderr='{"error": "ValueError: Could not read input image"}')

    monkeypatch.setattr(model_runtime.subprocess, "run", run)

    result = model_runtime.run_model_worker("realesrgan", "realesrgan_upscale", {"input_path": "a.png"})

    assert not result.success
    assert len(calls) == 1
    assert "Could not read input image" in result.error
