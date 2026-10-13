"""The Kokoro worker reads the Model Center folder and narrates batches in one load."""

from __future__ import annotations

import json
import sys
import types

import numpy as np
import pytest

from runtime_workers import model_worker


class _FakeModel:
    loads: list[dict] = []

    def __init__(self, **kwargs):
        _FakeModel.loads.append(kwargs)

    def eval(self):
        return self


class _FakePipeline:
    calls: list[tuple[str, str, float]] = []

    def __init__(self, lang_code, repo_id, model):
        assert repo_id == "hexgrad/Kokoro-82M"
        self.model = model

    def __call__(self, text, voice, speed):
        _FakePipeline.calls.append((text, voice, speed))
        yield None, None, np.zeros(24000, dtype=np.float32)


@pytest.fixture
def fake_kokoro(monkeypatch, tmp_path):
    _FakeModel.loads, _FakePipeline.calls = [], []
    module = types.SimpleNamespace(KModel=_FakeModel, KPipeline=_FakePipeline)
    monkeypatch.setitem(sys.modules, "kokoro", module)
    # soundfile lives only in the model runtime, not the app's test environment.
    soundfile = types.SimpleNamespace(write=lambda path, audio, rate: open(path, "wb").write(b"RIFF"))
    monkeypatch.setitem(sys.modules, "soundfile", soundfile)
    model_dir = tmp_path / "kokoro-82m"
    (model_dir / "voices").mkdir(parents=True)
    (model_dir / "voices" / "am_michael.pt").write_bytes(b"voice")
    return model_dir


def test_batch_loads_the_local_model_once_and_writes_every_segment(fake_kokoro, tmp_path, capsys):
    model_worker.kokoro_tts({
        "model_dir": str(fake_kokoro),
        "voice": "am_michael",
        "speed": 0.95,
        "batch": [
            {"text": "Number five: Greek yogurt.", "output_path": str(tmp_path / "out" / "s1.wav")},
            {"text": "Strength exercise helps.", "output_path": str(tmp_path / "out" / "s2.wav")},
        ],
    })

    result = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert len(_FakeModel.loads) == 1
    assert _FakeModel.loads[0]["model"].endswith("kokoro-v1_0.pth")
    assert [call[1] for call in _FakePipeline.calls] == [str(fake_kokoro / "voices" / "am_michael.pt")] * 2
    assert _FakePipeline.calls[0][2] == 0.95
    assert [item["duration_seconds"] for item in result["outputs"]] == [1.0, 1.0]
    assert (tmp_path / "out" / "s2.wav").is_file()
    assert result["voice"] == "am_michael"


def test_single_segment_keeps_the_output_field(fake_kokoro, tmp_path, capsys):
    model_worker.kokoro_tts({
        "model_dir": str(fake_kokoro),
        "voice": "am_michael",
        "text": "Hello.",
        "output_path": str(tmp_path / "one.wav"),
    })

    result = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert result["output"] == str(tmp_path / "one.wav")


def test_runtime_bridge_lists_every_batch_output_as_an_artifact(monkeypatch, tmp_path):
    from lib import model_runtime

    outputs = [{"output": str(tmp_path / "a.wav")}, {"output": str(tmp_path / "b.wav")}]
    monkeypatch.setattr(model_runtime, "model_runtime_info", lambda model_id: {
        "installed": True, "python": sys.executable, "target": str(tmp_path),
    })
    monkeypatch.setattr(model_runtime.subprocess, "run", lambda *a, **k: types.SimpleNamespace(
        returncode=0, stdout=json.dumps({"outputs": outputs}), stderr="",
    ))

    result = model_runtime.run_model_worker("kokoro-tts", "kokoro_tts", {"batch": []})

    assert result.success
    assert result.artifacts == [item["output"] for item in outputs]
