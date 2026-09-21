"""Production-tool adapters for Model Center managed local runtimes."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import time
from abc import ABC
from pathlib import Path
from typing import Any

from backlot.model_installer import model_runtime_info
from lib.model_runtime import managed_model_available, run_model_worker
from tools.base_tool import (
    BaseTool,
    Determinism,
    ExecutionMode,
    ResourceProfile,
    ToolResult,
    ToolRuntime,
    ToolStability,
    ToolStatus,
    ToolTier,
)


class ManagedLocalModel(BaseTool, ABC):
    version = "1.0.0"
    stability = ToolStability.BETA
    execution_mode = ExecutionMode.SYNC
    determinism = Determinism.DETERMINISTIC
    runtime = ToolRuntime.LOCAL
    model_id = ""
    operation = ""

    def get_status(self) -> ToolStatus:
        return ToolStatus.AVAILABLE if managed_model_available(self.model_id) else ToolStatus.UNAVAILABLE

    def _run_worker(self, payload: dict[str, Any], timeout: int = 3600) -> ToolResult:
        return run_model_worker(self.model_id, self.operation, payload, timeout=timeout)


class VieNeuTTS(ManagedLocalModel):
    name = "vieneu_tts"
    tier = ToolTier.VOICE
    capability = "tts"
    provider = "vieneu"
    model_id = "vieneu-tts"
    operation = "vieneu_tts"
    capabilities = ["text_to_speech", "vietnamese_tts", "voice_cloning", "streaming_tts"]
    best_for = ["Vietnamese narration", "three-region Vietnamese voices", "local voice cloning"]
    install_instructions = "Cài VieNeu-TTS trong Cài đặt API > Model miễn phí"
    input_schema = {"type": "object", "required": ["text", "output_path"], "properties": {
        "text": {"type": "string"}, "output_path": {"type": "string"}, "voice": {"type": "string"},
        "reference_audio": {"type": "string"}, "precision": {"type": "string", "enum": ["int8", "fp32"]},
    }}
    resource_profile = ResourceProfile(cpu_cores=4, ram_mb=4096, disk_mb=1000)

    def execute(self, inputs: dict[str, Any]) -> ToolResult:
        return self._run_worker(inputs)


class KokoroTTS(ManagedLocalModel):
    name = "kokoro_tts"
    tier = ToolTier.VOICE
    capability = "tts"
    provider = "kokoro"
    model_id = "kokoro-tts"
    operation = "kokoro_tts"
    capabilities = ["text_to_speech", "english_tts"]
    best_for = ["fast local English narration", "offline drafts"]
    install_instructions = "Cài Kokoro 82M trong Model Center"
    input_schema = {"type": "object", "required": ["text", "output_path"], "properties": {
        "text": {"type": "string"}, "output_path": {"type": "string"}, "voice": {"type": "string"},
        "language": {"type": "string", "default": "a"},
    }}
    resource_profile = ResourceProfile(cpu_cores=4, ram_mb=4096, disk_mb=1500)

    def execute(self, inputs: dict[str, Any]) -> ToolResult:
        return self._run_worker(inputs)


class MLXTranscriber(ManagedLocalModel):
    name = "mlx_transcriber"
    tier = ToolTier.CORE
    capability = "analysis"
    provider = "apple_mlx"
    model_id = "mlx-whisper"
    operation = "mlx_transcribe"
    capabilities = ["transcribe", "word_timestamps", "language_detection"]
    best_for = ["fast transcription on Apple Silicon"]
    install_instructions = "Chỉ khả dụng trên macOS Apple Silicon; cài từ Model Center"
    input_schema = {"type": "object", "required": ["input_path"], "properties": {
        "input_path": {"type": "string"}, "output_path": {"type": "string"}, "language": {"type": "string"},
    }}
    resource_profile = ResourceProfile(cpu_cores=4, ram_mb=4096, disk_mb=800)

    def execute(self, inputs: dict[str, Any]) -> ToolResult:
        source = Path(inputs["input_path"])
        payload = {**inputs, "output_path": inputs.get("output_path", str(source.with_name(f"{source.stem}_mlx_transcript.json")))}
        return self._run_worker(payload)


class FlorenceVision(ManagedLocalModel):
    name = "florence_vision"
    tier = ToolTier.ANALYZE
    capability = "analysis"
    provider = "microsoft"
    runtime = ToolRuntime.LOCAL_GPU
    model_id = "florence-vision"
    operation = "florence_vision"
    capabilities = ["image_caption", "object_detection", "visual_grounding", "shot_analysis"]
    best_for = ["source-footage indexing", "shot descriptions", "object-aware scene planning"]
    install_instructions = "Cài Florence-2 Base từ Model Center"
    input_schema = {"type": "object", "required": ["input_path"], "properties": {
        "input_path": {"type": "string"}, "output_path": {"type": "string"}, "task": {"type": "string"},
        "max_new_tokens": {"type": "integer", "default": 512},
    }}
    resource_profile = ResourceProfile(cpu_cores=4, ram_mb=8192, vram_mb=2048, disk_mb=3000)

    def execute(self, inputs: dict[str, Any]) -> ToolResult:
        source = Path(inputs["input_path"])
        payload = {**inputs, "output_path": inputs.get("output_path", str(source.with_name(f"{source.stem}_vision.json")))}
        return self._run_worker(payload)


class PaddleOCRLocal(ManagedLocalModel):
    name = "paddle_ocr"
    tier = ToolTier.ANALYZE
    capability = "analysis"
    provider = "paddlepaddle"
    model_id = "paddleocr"
    operation = "paddle_ocr"
    capabilities = ["ocr", "subtitle_extraction", "document_text"]
    best_for = ["Vietnamese text in frames", "screen recordings", "subtitle extraction"]
    install_instructions = "Cài PaddleOCR v5 Mobile từ Model Center"
    input_schema = {"type": "object", "required": ["input_path"], "properties": {
        "input_path": {"type": "string"}, "output_path": {"type": "string"}, "language": {"type": "string"},
    }}
    resource_profile = ResourceProfile(cpu_cores=4, ram_mb=4096, disk_mb=1800)

    def execute(self, inputs: dict[str, Any]) -> ToolResult:
        source = Path(inputs["input_path"])
        payload = {**inputs, "output_path": inputs.get("output_path", str(source.with_name(f"{source.stem}_ocr.json")))}
        return self._run_worker(payload)


class DepthEstimator(ManagedLocalModel):
    name = "depth_estimator"
    tier = ToolTier.ANALYZE
    capability = "analysis"
    provider = "depth_anything"
    runtime = ToolRuntime.LOCAL_GPU
    model_id = "depth-anything"
    operation = "depth_anything"
    capabilities = ["depth_estimation", "parallax_map", "2_5d_support"]
    best_for = ["2.5D parallax", "depth-aware camera moves"]
    install_instructions = "Cài Depth Anything V2 Small từ Model Center"
    input_schema = {"type": "object", "required": ["input_path"], "properties": {
        "input_path": {"type": "string"}, "output_path": {"type": "string"},
    }}
    resource_profile = ResourceProfile(cpu_cores=4, ram_mb=8192, vram_mb=2048, disk_mb=3000)

    def execute(self, inputs: dict[str, Any]) -> ToolResult:
        source = Path(inputs["input_path"])
        payload = {**inputs, "output_path": inputs.get("output_path", str(source.with_name(f"{source.stem}_depth.png")))}
        return self._run_worker(payload)


class SAM2Segment(ManagedLocalModel):
    name = "sam2_segment"
    tier = ToolTier.ANALYZE
    capability = "analysis"
    provider = "meta"
    runtime = ToolRuntime.LOCAL_GPU
    model_id = "sam2-segmentation"
    operation = "sam2_segment"
    capabilities = ["image_segmentation", "object_mask", "video_object_tracking"]
    best_for = ["subject masks", "object isolation", "tracking preparation"]
    install_instructions = "Cài SAM 2.1 Tiny từ Model Center"
    input_schema = {"type": "object", "required": ["input_path", "points"], "properties": {
        "input_path": {"type": "string"}, "output_path": {"type": "string"},
        "points": {"type": "array"}, "labels": {"type": "array"},
    }}
    resource_profile = ResourceProfile(cpu_cores=4, ram_mb=8192, vram_mb=3072, disk_mb=3500)

    def execute(self, inputs: dict[str, Any]) -> ToolResult:
        source = Path(inputs["input_path"])
        payload = {**inputs, "output_path": inputs.get("output_path", str(source.with_name(f"{source.stem}_mask.png")))}
        return self._run_worker(payload)


class MusicGenLocal(ManagedLocalModel):
    name = "musicgen_local"
    tier = ToolTier.GENERATE
    capability = "music_generation"
    provider = "meta_research"
    runtime = ToolRuntime.LOCAL_GPU
    model_id = "musicgen-research"
    operation = "musicgen"
    determinism = Determinism.STOCHASTIC
    capabilities = ["text_to_music"]
    best_for = ["non-commercial music experiments"]
    not_good_for = ["commercial production"]
    install_instructions = "Research-only; cài và xác nhận license trong Model Center"
    input_schema = {"type": "object", "required": ["prompt", "output_path"], "properties": {
        "prompt": {"type": "string"}, "output_path": {"type": "string"}, "max_new_tokens": {"type": "integer"},
    }}
    resource_profile = ResourceProfile(cpu_cores=6, ram_mb=12288, vram_mb=4096, disk_mb=7000)

    def execute(self, inputs: dict[str, Any]) -> ToolResult:
        return self._run_worker(inputs)


class QwenVLLocal(ManagedLocalModel):
    name = "qwen_vl_local"
    tier = ToolTier.ANALYZE
    capability = "analysis"
    provider = "qwen_research"
    runtime = ToolRuntime.LOCAL_GPU
    model_id = "qwen-vl-research"
    operation = "qwen_vision"
    capabilities = ["visual_question_answering", "image_caption"]
    best_for = ["non-commercial visual-language experiments"]
    not_good_for = ["commercial production"]
    install_instructions = "Research-only; cài và xác nhận license trong Model Center"
    input_schema = {"type": "object", "required": ["input_path"], "properties": {
        "input_path": {"type": "string"}, "output_path": {"type": "string"}, "prompt": {"type": "string"},
    }}
    resource_profile = ResourceProfile(cpu_cores=6, ram_mb=16384, vram_mb=6000, disk_mb=11000)

    def execute(self, inputs: dict[str, Any]) -> ToolResult:
        source = Path(inputs["input_path"])
        payload = {**inputs, "output_path": inputs.get("output_path", str(source.with_name(f"{source.stem}_qwen.json")))}
        return self._run_worker(payload)


class MuseTalkLipSync(ManagedLocalModel):
    name = "musetalk_lipsync"
    tier = ToolTier.GENERATE
    capability = "avatar"
    provider = "musetalk"
    runtime = ToolRuntime.LOCAL_GPU
    model_id = "musetalk-lipsync"
    operation = ""
    determinism = Determinism.STOCHASTIC
    capabilities = ["lip_sync", "audio_video_alignment", "talking_head"]
    best_for = ["commercial local lip-sync", "Vietnamese dubbing"]
    install_instructions = "Cài MuseTalk 1.5 từ Model Center; NVIDIA GPU được khuyến nghị"
    input_schema = {"type": "object", "required": ["inference_config", "output_dir"], "properties": {
        "inference_config": {"type": "string"}, "output_dir": {"type": "string"},
    }}
    resource_profile = ResourceProfile(cpu_cores=6, ram_mb=16384, vram_mb=8000, disk_mb=10000)

    def execute(self, inputs: dict[str, Any]) -> ToolResult:
        info = model_runtime_info(self.model_id)
        if not info["installed"] or not info["python"]:
            return ToolResult(success=False, error="MuseTalk chưa được cài từ Model Center")
        config = Path(inputs["inference_config"])
        output_dir = Path(inputs["output_dir"])
        output_dir.mkdir(parents=True, exist_ok=True)
        command = [
            info["python"], "-m", "scripts.inference",
            "--inference_config", str(config),
            "--result_dir", str(output_dir),
            "--unet_model_path", str(Path(info["target"]) / "musetalkV15" / "unet.pth"),
            "--unet_config", str(Path(info["target"]) / "musetalkV15" / "musetalk.json"),
            "--version", "v15",
            "--ffmpeg_path", str(Path(shutil.which("ffmpeg") or "ffmpeg").parent),
        ]
        started = time.time()
        source_root = Path(info["target"]).parent / "MuseTalk-main"
        environment = os.environ.copy()
        environment["PYTHONPATH"] = os.pathsep.join(filter(None, (str(source_root), environment.get("PYTHONPATH"))))
        result = subprocess.run(
            command,
            cwd=Path(info["target"]).parent,
            env=environment,
            capture_output=True,
            text=True,
            timeout=7200,
            check=False,
        )
        if result.returncode != 0:
            return ToolResult(success=False, error=(result.stderr or result.stdout)[-2000:])
        artifacts = [str(path) for path in output_dir.rglob("*.mp4")]
        return ToolResult(success=True, data={"output_dir": str(output_dir), "outputs": artifacts}, artifacts=artifacts, duration_seconds=round(time.time() - started, 2), model="MuseTalk 1.5")


class FrameInterpolate(BaseTool):
    name = "frame_interpolate"
    version = "1.0.0"
    tier = ToolTier.ENHANCE
    capability = "video_post"
    provider = "rife_ncnn"
    stability = ToolStability.BETA
    execution_mode = ExecutionMode.SYNC
    determinism = Determinism.DETERMINISTIC
    runtime = ToolRuntime.LOCAL_GPU
    capabilities = ["frame_interpolation", "fps_conversion", "slow_motion"]
    best_for = ["2x FPS", "smooth slow motion"]
    install_instructions = "Cài RIFE NCNN từ Model Center"
    input_schema = {"type": "object", "required": ["input_path", "output_path"], "properties": {
        "input_path": {"type": "string"}, "output_path": {"type": "string"}, "fps_multiplier": {"type": "integer", "enum": [2]},
    }}
    resource_profile = ResourceProfile(cpu_cores=4, ram_mb=4096, vram_mb=2048, disk_mb=4000)

    def _binary(self) -> Path | None:
        try:
            info = model_runtime_info("rife-interpolation")
        except ValueError:
            return None
        if not info["installed"]:
            return None
        names = {"rife-ncnn-vulkan", "rife-ncnn-vulkan.exe"}
        return next((path for path in Path(info["target"]).rglob("*") if path.name in names and path.is_file()), None)

    def get_status(self) -> ToolStatus:
        return ToolStatus.AVAILABLE if self._binary() and shutil.which("ffmpeg") and shutil.which("ffprobe") else ToolStatus.UNAVAILABLE

    def execute(self, inputs: dict[str, Any]) -> ToolResult:
        binary = self._binary()
        if not binary:
            return ToolResult(success=False, error="RIFE chưa được cài từ Model Center")
        source = Path(inputs["input_path"])
        output = Path(inputs["output_path"])
        output.parent.mkdir(parents=True, exist_ok=True)
        started = time.time()
        with tempfile.TemporaryDirectory(prefix="mosa-rife-") as temporary:
            root = Path(temporary)
            input_frames = root / "input"
            output_frames = root / "output"
            input_frames.mkdir()
            output_frames.mkdir()
            probe = subprocess.run(
                ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=r_frame_rate", "-of", "json", str(source)],
                capture_output=True, text=True, check=False,
            )
            if probe.returncode != 0:
                return ToolResult(success=False, error=probe.stderr.strip())
            rate = json.loads(probe.stdout)["streams"][0]["r_frame_rate"]
            numerator, denominator = (int(part) for part in rate.split("/"))
            fps = numerator / max(denominator, 1)
            for command in (
                ["ffmpeg", "-y", "-i", str(source), str(input_frames / "%08d.png")],
                [str(binary), "-i", str(input_frames), "-o", str(output_frames)],
                ["ffmpeg", "-y", "-framerate", f"{fps * 2:g}", "-i", str(output_frames / "%08d.png"), "-i", str(source), "-map", "0:v:0", "-map", "1:a?", "-c:v", "libx264", "-crf", "18", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(output)],
            ):
                result = subprocess.run(command, capture_output=True, text=True, check=False)
                if result.returncode != 0:
                    return ToolResult(success=False, error=(result.stderr or result.stdout)[-2000:])
        return ToolResult(success=True, data={"output": str(output), "fps": fps * 2}, artifacts=[str(output)], duration_seconds=round(time.time() - started, 2), model="rife-ncnn-vulkan")
