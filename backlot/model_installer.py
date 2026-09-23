"""On-demand local model downloads for the desktop Model Center."""

from __future__ import annotations

import json
import fnmatch
import os
import platform
import shutil
import subprocess
import tarfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from backlot.settings import update_provider_settings
from lib.paths import DATA_DIR


MODEL_ROOT = Path(os.environ.get("MOSA_MODEL_DIR") or DATA_DIR / "models")
STATE_ROOT = MODEL_ROOT / ".install-state"
MODEL_RUNTIME_ROOT = Path(os.environ.get("MOSA_MODEL_RUNTIME_DIR") or DATA_DIR / "model-runtime")
MIN_FREE_RESERVE_BYTES = 12 * 1024**3
_LOCK = threading.Lock()
_JOBS: dict[str, dict[str, Any]] = {}


@dataclass(frozen=True)
class DownloadFile:
    url: str
    relative_path: str
    size_bytes: int = 0
    extract_to: str | None = None
    remove_after_extract: bool = True


def _hf_url(repo: str, path: str) -> str:
    return f"https://huggingface.co/{repo}/resolve/main/{urllib.parse.quote(path)}?download=true"


INSTALL_SPECS: dict[str, dict[str, Any]] = {
    "local-image-diffusers": {
        "label": "Stable Diffusion 2.1 Base",
        "kind": "snapshot",
        "repo": "stabilityai/stable-diffusion-2-1-base",
        "target": "diffusers/stabilityai--stable-diffusion-2-1-base",
        "estimated_bytes": 5_200_000_000,
        "min_memory_gb": 12,
        "license": "OpenRAIL++",
        "settings": {"LOCAL_IMAGE_MODEL": "{target}"},
    },
    "comfyui-image": {
        "label": "Flux 2 Dev NVFP4",
        "kind": "files",
        "target": "comfyui",
        "estimated_bytes": 34_000_000_000,
        "min_memory_gb": 32,
        "license": "FLUX Dev Non-Commercial",
        "commercial_restricted": True,
        "files": (
            DownloadFile(_hf_url("black-forest-labs/FLUX.2-dev-NVFP4", "flux2-dev-nvfp4.safetensors"), "diffusion_models/flux2-dev-nvfp4.safetensors", 21_000_000_000),
            DownloadFile(_hf_url("Comfy-Org/flux2-dev", "split_files/text_encoders/mistral_3_small_flux2_fp4_mixed.safetensors"), "text_encoders/mistral_3_small_flux2_fp4_mixed.safetensors"),
            DownloadFile(_hf_url("Comfy-Org/flux2-dev", "split_files/vae/flux2-vae.safetensors"), "vae/flux2-vae.safetensors"),
        ),
    },
    "local-video-wan": {
        "label": "WAN 2.1 T2V 1.3B",
        "kind": "snapshot",
        "repo": "Wan-AI/Wan2.1-T2V-1.3B-Diffusers",
        "target": "diffusers/Wan-AI--Wan2.1-T2V-1.3B-Diffusers",
        "estimated_bytes": 29_000_000_000,
        "min_memory_gb": 18,
        "license": "Apache-2.0",
        "settings": {
            "VIDEO_GEN_LOCAL_ENABLED": "true",
            "VIDEO_GEN_LOCAL_MODEL": "wan2.1-1.3b",
        },
    },
    "local-video-ltx": {
        "label": "LTX-2 Local",
        "kind": "unsupported",
        "estimated_bytes": 45_000_000_000,
        "min_memory_gb": 64,
        "license": "LTX-2 Community License",
        "blocked_reason": "LTX-2 đầy đủ không phù hợp máy phổ thông; cần ít nhất 64 GB RAM và chấp nhận giấy phép riêng.",
    },
    "comfyui-video": {
        "label": "WAN 2.2 T2V 14B FP8",
        "kind": "files",
        "target": "comfyui",
        "estimated_bytes": 38_000_000_000,
        "min_memory_gb": 32,
        "license": "Apache-2.0",
        "files": tuple(
            DownloadFile(_hf_url("Comfy-Org/Wan_2.2_ComfyUI_Repackaged", path), target)
            for path, target in (
                ("split_files/text_encoders/umt5_xxl_fp8_e4m3fn_scaled.safetensors", "text_encoders/umt5_xxl_fp8_e4m3fn_scaled.safetensors"),
                ("split_files/diffusion_models/wan2.2_t2v_high_noise_14B_fp8_scaled.safetensors", "diffusion_models/wan2.2_t2v_high_noise_14B_fp8_scaled.safetensors"),
                ("split_files/diffusion_models/wan2.2_t2v_low_noise_14B_fp8_scaled.safetensors", "diffusion_models/wan2.2_t2v_low_noise_14B_fp8_scaled.safetensors"),
                ("split_files/vae/wan_2.1_vae.safetensors", "vae/wan_2.1_vae.safetensors"),
                ("split_files/loras/wan2.2_t2v_lightx2v_4steps_lora_v1.1_high_noise.safetensors", "loras/wan2.2_t2v_lightx2v_4steps_lora_v1.1_high_noise.safetensors"),
                ("split_files/loras/wan2.2_t2v_lightx2v_4steps_lora_v1.1_low_noise.safetensors", "loras/wan2.2_t2v_lightx2v_4steps_lora_v1.1_low_noise.safetensors"),
            )
        ),
    },
    "piper-tts": {
        "label": "Piper tiếng Việt — vais1000 medium",
        "kind": "files",
        "target": "piper/vi_VN-vais1000-medium",
        "estimated_bytes": 64_000_000,
        "min_memory_gb": 2,
        "license": "MIT",
        "files": (
            DownloadFile(_hf_url("rhasspy/piper-voices", "vi/vi_VN/vais1000/medium/vi_VN-vais1000-medium.onnx"), "vi_VN-vais1000-medium.onnx", 63_201_294),
            DownloadFile(_hf_url("rhasspy/piper-voices", "vi/vi_VN/vais1000/medium/vi_VN-vais1000-medium.onnx.json"), "vi_VN-vais1000-medium.onnx.json", 4_860),
        ),
        "runtime_estimated_bytes": 250_000_000,
        "runtime_packages": ("piper-tts",),
        "settings": {"PIPER_MODEL": "{target}/vi_VN-vais1000-medium.onnx"},
    },
    "whisper-local": {
        "label": "faster-whisper Base",
        "kind": "snapshot",
        "repo": "Systran/faster-whisper-base",
        "target": "whisper/faster-whisper-base",
        "estimated_bytes": 150_000_000,
        "min_memory_gb": 4,
        "license": "MIT",
        "runtime_estimated_bytes": 450_000_000,
        "runtime_packages": ("faster-whisper",),
        "settings": {"WHISPER_MODEL_SIZE": "{target}"},
    },
    "comfyui-music": {
        "label": "ACE-Step 1 3.5B",
        "kind": "files",
        "target": "comfyui",
        "estimated_bytes": 7_700_000_000,
        "min_memory_gb": 16,
        "license": "Apache-2.0",
        "files": (
            DownloadFile(_hf_url("Comfy-Org/ACE-Step_ComfyUI_repackaged", "all_in_one/ace_step_v1_3.5b.safetensors"), "checkpoints/ace_step_v1_3.5b.safetensors", 7_700_000_000),
        ),
    },
    "vieneu-tts": {
        "label": "VieNeu-TTS v3 Turbo INT8",
        "kind": "snapshot",
        "repo": "pnnbao-ump/VieNeu-TTS-v3-Turbo",
        "target": "tts/vieneu-v3-turbo",
        "estimated_bytes": 245_000_000,
        "runtime_estimated_bytes": 650_000_000,
        "min_memory_gb": 4,
        "license": "Apache-2.0",
        "license_url": "https://huggingface.co/pnnbao-ump/VieNeu-TTS-v3-Turbo",
        "source_url": "https://github.com/pnnbao97/VieNeu-TTS",
        "tier": "essential",
        "snapshot_include": (
            "onnx_int8/*",
            "denoiser.onnx",
            "speaker_encoder.onnx",
            "config.json",
            "tokenizer.json",
            "tokenizer_config.json",
            "special_tokens_map.json",
        ),
        "runtime_packages": ("vieneu==3.7.1",),
        "settings": {"VIENEU_MODEL_DIR": "{target}"},
    },
    "kokoro-tts": {
        "label": "Kokoro 82M — English TTS",
        "kind": "files",
        "target": "tts/kokoro-82m",
        "estimated_bytes": 330_000_000,
        "runtime_estimated_bytes": 1_200_000_000,
        "min_memory_gb": 4,
        "license": "Apache-2.0",
        "license_url": "https://huggingface.co/hexgrad/Kokoro-82M",
        "source_url": "https://github.com/hexgrad/kokoro",
        "tier": "essential",
        "files": (
            DownloadFile(_hf_url("hexgrad/Kokoro-82M", "kokoro-v1_0.pth"), "kokoro-v1_0.pth", 327_212_226),
            DownloadFile(_hf_url("hexgrad/Kokoro-82M", "config.json"), "config.json", 2_351),
            DownloadFile(_hf_url("hexgrad/Kokoro-82M", "voices/af_heart.pt"), "voices/af_heart.pt", 523_425),
            DownloadFile(_hf_url("hexgrad/Kokoro-82M", "voices/am_michael.pt"), "voices/am_michael.pt", 523_435),
            DownloadFile(_hf_url("hexgrad/Kokoro-82M", "voices/bf_emma.pt"), "voices/bf_emma.pt", 523_420),
            DownloadFile(_hf_url("hexgrad/Kokoro-82M", "voices/bm_george.pt"), "voices/bm_george.pt", 523_430),
        ),
        "runtime_packages": ("kokoro>=0.9.4", "soundfile"),
        "settings": {"KOKORO_MODEL_DIR": "{target}"},
    },
    "realesrgan": {
        "label": "Real-ESRGAN x2/x4",
        "kind": "files",
        "target": "enhancement/realesrgan",
        "estimated_bytes": 155_000_000,
        "min_memory_gb": 4,
        "license": "BSD-3-Clause",
        "license_url": "https://github.com/xinntao/Real-ESRGAN/blob/master/LICENSE",
        "source_url": "https://github.com/xinntao/Real-ESRGAN",
        "tier": "essential",
        "files": (
            DownloadFile("https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.1/RealESRGAN_x2plus.pth", "RealESRGAN_x2plus.pth", 67_061_725),
            DownloadFile("https://github.com/xinntao/Real-ESRGAN/releases/download/v0.1.0/RealESRGAN_x4plus.pth", "RealESRGAN_x4plus.pth", 67_040_989),
            DownloadFile("https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.2.4/RealESRGAN_x4plus_anime_6B.pth", "RealESRGAN_x4plus_anime_6B.pth", 17_938_799),
        ),
        "runtime_packages": ("realesrgan", "opencv-python-headless"),
        "settings": {"REALESRGAN_MODEL_DIR": "{target}"},
    },
    "rembg-u2net": {
        "label": "rembg — U2Net + Silueta",
        "kind": "files",
        "target": "enhancement/rembg",
        "estimated_bytes": 220_000_000,
        "runtime_estimated_bytes": 450_000_000,
        "min_memory_gb": 3,
        "license": "MIT",
        "license_url": "https://github.com/danielgatis/rembg/blob/main/LICENSE.txt",
        "source_url": "https://github.com/danielgatis/rembg",
        "tier": "essential",
        "files": (
            DownloadFile("https://github.com/danielgatis/rembg/releases/download/v0.0.0/u2net.onnx", "u2net.onnx", 176_000_000),
            DownloadFile("https://github.com/danielgatis/rembg/releases/download/v0.0.0/silueta.onnx", "silueta.onnx", 44_000_000),
        ),
        "runtime_packages": ("rembg[cpu]",),
        "settings": {"U2NET_HOME": "{target}"},
    },
    "face-restore": {
        "label": "GFPGAN 1.4 + CodeFormer",
        "kind": "files",
        "target": "enhancement/face-restore",
        "estimated_bytes": 730_000_000,
        "runtime_estimated_bytes": 2_500_000_000,
        "min_memory_gb": 8,
        "license": "Apache-2.0 + S-Lab non-commercial",
        "license_url": "https://github.com/sczhou/CodeFormer/blob/master/LICENSE",
        "source_url": "https://github.com/TencentARC/GFPGAN",
        "tier": "research",
        "commercial_restricted": True,
        "files": (
            DownloadFile("https://github.com/TencentARC/GFPGAN/releases/download/v1.3.4/GFPGANv1.4.pth", "GFPGANv1.4.pth", 348_632_874),
            DownloadFile("https://github.com/TencentARC/GFPGAN/releases/download/v1.3.4/CodeFormer.pth", "CodeFormer.pth", 376_637_898),
        ),
        "runtime_packages": ("gfpgan", "realesrgan", "opencv-python-headless"),
        "settings": {"FACE_RESTORE_MODEL_DIR": "{target}"},
    },
    "rife-interpolation": {
        "label": "RIFE NCNN — nội suy khung hình",
        "kind": "files",
        "target": "video/rife-ncnn",
        "estimated_bytes": 440_000_000,
        "min_memory_gb": 4,
        "license": "MIT",
        "license_url": "https://github.com/nihui/rife-ncnn-vulkan/blob/master/LICENSE",
        "source_url": "https://github.com/hzwer/Practical-RIFE",
        "tier": "essential",
        "platform_files": {
            "darwin-arm64": (DownloadFile("https://github.com/nihui/rife-ncnn-vulkan/releases/download/20221029/rife-ncnn-vulkan-20221029-macos.zip", "rife-macos.zip", 436_537_917, extract_to="."),),
            "darwin-x64": (DownloadFile("https://github.com/nihui/rife-ncnn-vulkan/releases/download/20221029/rife-ncnn-vulkan-20221029-macos.zip", "rife-macos.zip", 436_537_917, extract_to="."),),
            "win32-x64": (DownloadFile("https://github.com/nihui/rife-ncnn-vulkan/releases/download/20221029/rife-ncnn-vulkan-20221029-windows.zip", "rife-windows.zip", 431_540_241, extract_to="."),),
        },
        "settings": {"RIFE_MODEL_DIR": "{target}"},
    },
    "florence-vision": {
        "label": "Florence-2 Base",
        "kind": "snapshot",
        "repo": "microsoft/Florence-2-base",
        "target": "vision/florence-2-base",
        "estimated_bytes": 468_000_000,
        "runtime_estimated_bytes": 2_500_000_000,
        "min_memory_gb": 8,
        "license": "MIT",
        "license_url": "https://huggingface.co/microsoft/Florence-2-base/blob/main/LICENSE",
        "source_url": "https://huggingface.co/microsoft/Florence-2-base",
        "tier": "essential",
        "snapshot_exclude": ("pytorch_model.bin", "README.md", "SECURITY.md", "CODE_OF_CONDUCT.md", "SUPPORT.md"),
        "runtime_packages": ("torch", "torchvision", "transformers>=4.49", "accelerate"),
        "settings": {"FLORENCE_MODEL_DIR": "{target}"},
    },
    "paddleocr": {
        "label": "PaddleOCR v5 Mobile — Latin/Vietnamese",
        "kind": "files",
        "target": "vision/paddleocr-v5-mobile",
        "estimated_bytes": 15_000_000,
        "runtime_estimated_bytes": 1_600_000_000,
        "min_memory_gb": 4,
        "license": "Apache-2.0",
        "license_url": "https://github.com/PaddlePaddle/PaddleOCR/blob/main/LICENSE",
        "source_url": "https://github.com/PaddlePaddle/PaddleOCR",
        "tier": "essential",
        "files": (
            DownloadFile("https://paddle-model-ecology.bj.bcebos.com/paddlex/official_inference_model/paddle3.0.0/PP-OCRv5_mobile_det_infer.tar", "det.tar", 4_935_680, extract_to="det"),
            DownloadFile("https://paddle-model-ecology.bj.bcebos.com/paddlex/official_inference_model/paddle3.0.0/latin_PP-OCRv5_mobile_rec_infer.tar", "rec.tar", 8_202_240, extract_to="rec"),
        ),
        "runtime_packages": ("paddleocr", "paddlepaddle"),
        "settings": {"PADDLEOCR_MODEL_DIR": "{target}"},
    },
    "depth-anything": {
        "label": "Depth Anything V2 Small",
        "kind": "snapshot",
        "repo": "depth-anything/Depth-Anything-V2-Small-hf",
        "target": "vision/depth-anything-v2-small",
        "estimated_bytes": 100_000_000,
        "runtime_estimated_bytes": 2_500_000_000,
        "min_memory_gb": 8,
        "license": "Apache-2.0 (Small only)",
        "license_url": "https://github.com/DepthAnything/Depth-Anything-V2#license",
        "source_url": "https://github.com/DepthAnything/Depth-Anything-V2",
        "tier": "advanced",
        "runtime_packages": ("torch", "torchvision", "transformers", "opencv-python-headless"),
        "settings": {"DEPTH_ANYTHING_MODEL_DIR": "{target}"},
    },
    "sam2-segmentation": {
        "label": "SAM 2.1 Hiera Tiny",
        "kind": "snapshot",
        "repo": "facebook/sam2.1-hiera-tiny",
        "target": "vision/sam2.1-hiera-tiny",
        "estimated_bytes": 160_000_000,
        "runtime_estimated_bytes": 2_700_000_000,
        "min_memory_gb": 8,
        "license": "Apache-2.0",
        "license_url": "https://github.com/facebookresearch/sam2/blob/main/LICENSE",
        "source_url": "https://github.com/facebookresearch/sam2",
        "tier": "advanced",
        "snapshot_exclude": ("sam2.1_hiera_tiny.pt", "README.md"),
        "runtime_packages": ("torch>=2.5.1", "torchvision>=0.20.1", "git+https://github.com/facebookresearch/sam2.git"),
        "settings": {"SAM2_MODEL_DIR": "{target}"},
    },
    "musetalk-lipsync": {
        "label": "MuseTalk 1.5 Lip Sync",
        "kind": "files",
        "target": "avatar/musetalk-1.5/models",
        "estimated_bytes": 5_900_000_000,
        "runtime_estimated_bytes": 4_000_000_000,
        "min_memory_gb": 16,
        "license": "MIT / commercial model weights",
        "license_url": "https://github.com/TMElyralab/MuseTalk#license",
        "source_url": "https://github.com/TMElyralab/MuseTalk",
        "tier": "advanced",
        "files": (
            DownloadFile("https://github.com/TMElyralab/MuseTalk/archive/refs/heads/main.zip", "musetalk-source.zip", 25_000_000, extract_to=".."),
            DownloadFile(_hf_url("TMElyralab/MuseTalk", "musetalkV15/unet.pth"), "musetalkV15/unet.pth", 3_400_074_924),
            DownloadFile(_hf_url("TMElyralab/MuseTalk", "musetalkV15/musetalk.json"), "musetalkV15/musetalk.json", 748),
            DownloadFile(_hf_url("stabilityai/sd-vae-ft-mse", "diffusion_pytorch_model.bin"), "sd-vae/diffusion_pytorch_model.bin", 334_707_217),
            DownloadFile(_hf_url("stabilityai/sd-vae-ft-mse", "config.json"), "sd-vae/config.json", 547),
            DownloadFile(_hf_url("openai/whisper-tiny", "pytorch_model.bin"), "whisper/pytorch_model.bin", 151_095_027),
            DownloadFile(_hf_url("openai/whisper-tiny", "config.json"), "whisper/config.json", 1_983),
            DownloadFile(_hf_url("openai/whisper-tiny", "preprocessor_config.json"), "whisper/preprocessor_config.json", 184_990),
            DownloadFile(_hf_url("yzd-v/DWPose", "dw-ll_ucoco_384.pth"), "dwpose/dw-ll_ucoco_384.pth", 406_878_486),
            DownloadFile(_hf_url("ByteDance/LatentSync", "latentsync_syncnet.pt"), "syncnet/latentsync_syncnet.pt", 1_488_019_828),
            DownloadFile(_hf_url("ManyOtherFunctions/face-parse-bisent", "79999_iter.pth"), "face-parse-bisent/79999_iter.pth", 53_289_463),
            DownloadFile(_hf_url("ManyOtherFunctions/face-parse-bisent", "resnet18-5c106cde.pth"), "face-parse-bisent/resnet18-5c106cde.pth", 46_827_520),
        ),
        "python_version": "3.10",
        "runtime_packages": (
            "torch", "torchvision", "diffusers==0.30.2", "accelerate==0.28.0",
            "opencv-python-headless==4.9.0.80", "soundfile==0.12.1", "transformers==4.39.2",
            "huggingface_hub==0.30.2", "librosa==0.11.0", "einops==0.8.1", "omegaconf",
            "ffmpeg-python", "moviepy", "gdown", "imageio[ffmpeg]",
        ),
        "settings": {"MUSETALK_MODEL_DIR": "{target}"},
    },
    "wav2lip-research": {
        "label": "Wav2Lip GAN — research only",
        "kind": "files",
        "target": "avatar/wav2lip",
        "estimated_bytes": 245_000_000,
        "runtime_estimated_bytes": 2_500_000_000,
        "min_memory_gb": 8,
        "license": "Personal / research / non-commercial",
        "license_url": "https://github.com/Rudrabha/Wav2Lip#license-and-citation",
        "source_url": "https://github.com/Rudrabha/Wav2Lip",
        "tier": "research",
        "commercial_restricted": True,
        "python_version": "3.10",
        "files": (
            DownloadFile("https://github.com/Rudrabha/Wav2Lip/archive/refs/heads/master.zip", "wav2lip-source.zip", 8_000_000, extract_to="source"),
            DownloadFile("https://drive.usercontent.google.com/download?id=15G3U08c8xsCkOqQxE38Z2XXDnPcOptNk&export=download&confirm=t", "source/Wav2Lip-master/checkpoints/wav2lip_gan.pth", 145_829_145),
            DownloadFile("https://www.adrianbulat.com/downloads/python-fan/s3fd-619a316812.pth", "source/Wav2Lip-master/face_detection/detection/sfd/s3fd.pth", 89_843_225),
        ),
        "runtime_packages": (
            "torch", "torchvision", "librosa", "numpy<2", "opencv-python-headless",
            "scipy", "tqdm", "numba", "soundfile",
        ),
        "settings": {"WAV2LIP_PATH": "{target}/source/Wav2Lip-master"},
    },
    "mlx-whisper": {
        "label": "MLX Whisper Base — Apple Silicon",
        "kind": "snapshot",
        "repo": "mlx-community/whisper-base-mlx",
        "target": "whisper/mlx-whisper-base",
        "estimated_bytes": 145_000_000,
        "runtime_estimated_bytes": 650_000_000,
        "min_memory_gb": 8,
        "license": "MIT",
        "license_url": "https://github.com/ml-explore/mlx-examples/blob/main/LICENSE",
        "source_url": "https://github.com/ml-explore/mlx-examples/tree/main/whisper",
        "tier": "essential",
        "platforms": ("darwin-arm64",),
        "runtime_packages": ("mlx-whisper",),
        "settings": {"MLX_WHISPER_MODEL_DIR": "{target}"},
    },
    "musicgen-research": {
        "label": "MusicGen Small — research",
        "kind": "snapshot",
        "repo": "facebook/musicgen-small",
        "target": "research/musicgen-small",
        "estimated_bytes": 3_450_000_000,
        "runtime_estimated_bytes": 3_000_000_000,
        "min_memory_gb": 12,
        "license": "CC-BY-NC-4.0",
        "license_url": "https://github.com/facebookresearch/audiocraft/blob/main/LICENSE_weights",
        "source_url": "https://github.com/facebookresearch/audiocraft",
        "tier": "research",
        "commercial_restricted": True,
        "snapshot_exclude": ("pytorch_model.bin", "README.md"),
        "runtime_packages": ("transformers", "torch", "sentencepiece"),
        "settings": {"MUSICGEN_MODEL_DIR": "{target}"},
    },
    "qwen-vl-research": {
        "label": "Qwen2.5-VL 3B — research",
        "kind": "snapshot",
        "repo": "Qwen/Qwen2.5-VL-3B-Instruct",
        "target": "research/qwen2.5-vl-3b",
        "estimated_bytes": 7_600_000_000,
        "runtime_estimated_bytes": 3_000_000_000,
        "min_memory_gb": 16,
        "license": "Qwen Research License",
        "license_url": "https://huggingface.co/Qwen/Qwen2.5-VL-3B-Instruct/blob/main/LICENSE",
        "source_url": "https://github.com/QwenLM/Qwen2.5-VL",
        "tier": "research",
        "commercial_restricted": True,
        "snapshot_exclude": ("README.md",),
        "runtime_packages": ("transformers", "qwen-vl-utils", "torch", "accelerate"),
        "settings": {"QWEN_VL_MODEL_DIR": "{target}"},
    },
}


@lru_cache(maxsize=1)
def _memory_bytes() -> int:
    if platform.system() == "Darwin":
        try:
            return int(subprocess.check_output(["sysctl", "-n", "hw.memsize"], text=True).strip())
        except (OSError, ValueError, subprocess.SubprocessError):
            pass
    try:
        return int(os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES"))
    except (AttributeError, OSError, ValueError):
        return 0


def _comfyui_root() -> Path:
    configured = os.environ.get("MOSA_COMFYUI_DIR")
    candidates = [
        Path(configured).expanduser() if configured else None,
        Path.home() / "Applications" / "ComfyUI",
        Path.home() / "ComfyUI",
        DATA_DIR / "ComfyUI",
    ]
    for candidate in candidates:
        if candidate and (candidate / "models").is_dir():
            return candidate
    return DATA_DIR / "ComfyUI"


def _target_root(spec: dict[str, Any]) -> Path:
    if spec.get("target") == "comfyui":
        return _comfyui_root() / "models"
    return MODEL_ROOT / str(spec.get("target", "unknown"))


def _state_path(model_id: str) -> Path:
    return STATE_ROOT / f"{model_id}.json"


def _read_state(model_id: str) -> dict[str, Any]:
    try:
        return json.loads(_state_path(model_id).read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def _write_state(model_id: str, payload: dict[str, Any]) -> None:
    STATE_ROOT.mkdir(parents=True, exist_ok=True)
    temporary = _state_path(model_id).with_suffix(".json.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(_state_path(model_id))


def _format_bytes(value: int) -> str:
    if value >= 1024**3:
        return f"{value / 1024**3:.1f} GB"
    return f"{value / 1024**2:.0f} MB"


def _platform_key() -> str:
    machine = platform.machine().lower()
    architecture = "arm64" if machine in {"arm64", "aarch64"} else "x64"
    system = "win32" if os.name == "nt" else platform.system().lower()
    return f"{system}-{architecture}"


def _runtime_root(model_id: str) -> Path:
    return MODEL_RUNTIME_ROOT / model_id


def _runtime_python(model_id: str) -> Path:
    root = _runtime_root(model_id)
    return root / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def _uv_executable() -> str | None:
    configured = os.environ.get("OPENMONTAGE_UV_PATH")
    if configured and Path(configured).is_file():
        return configured
    return shutil.which("uv") or shutil.which("uv.exe")


def _spec_files(spec: dict[str, Any]) -> list[DownloadFile]:
    platform_files = spec.get("platform_files")
    if isinstance(platform_files, dict):
        return list(platform_files.get(_platform_key()) or ())
    return list(spec.get("files") or ())


def _compatibility(spec: dict[str, Any]) -> tuple[bool, str | None]:
    if spec.get("kind") == "unsupported":
        return False, str(spec.get("blocked_reason") or "Gói này chưa hỗ trợ cài tự động")
    platforms = tuple(spec.get("platforms") or ())
    if platforms and _platform_key() not in platforms:
        return False, f"Model này chỉ hỗ trợ: {', '.join(platforms)}. Máy hiện tại: {_platform_key()}."
    if spec.get("platform_files") and not _spec_files(spec):
        return False, f"Chưa có gói tải tự động cho {_platform_key()}."
    if spec.get("runtime_packages") and not _uv_executable():
        return False, "Thiếu uv runtime manager trong bản app; hãy cài bản desktop mới nhất."
    memory = _memory_bytes()
    minimum = int(spec.get("min_memory_gb", 0)) * 1024**3
    if memory and minimum and memory < minimum:
        return False, f"Cần tối thiểu {spec['min_memory_gb']} GB RAM; máy này có khoảng {round(memory / 1024**3)} GB."
    target = _target_root(spec)
    disk_probe = target
    while not disk_probe.exists() and disk_probe != disk_probe.parent:
        disk_probe = disk_probe.parent
    free = shutil.disk_usage(disk_probe).free
    required = (
        int(spec.get("estimated_bytes", 0))
        + int(spec.get("runtime_estimated_bytes", 0))
        + MIN_FREE_RESERVE_BYTES
    )
    if free < required:
        return False, f"Cần {_format_bytes(required)} trống (đã gồm 12 GB dự phòng); hiện còn {_format_bytes(free)}."
    return True, None


def _installed(model_id: str, spec: dict[str, Any]) -> bool:
    state = _read_state(model_id)
    if state.get("status") != "installed":
        return False
    target = _target_root(spec)
    files = state.get("files") or []
    files_ready = bool(files) and all((target / item).exists() for item in files)
    runtime_ready = not spec.get("runtime_packages") or _runtime_python(model_id).is_file()
    return files_ready and runtime_ready


def _files_installed(model_id: str, spec: dict[str, Any]) -> bool:
    state = _read_state(model_id)
    files = state.get("files") or []
    target = _target_root(spec)
    return bool(files) and all((target / item).exists() for item in files)


def install_catalog() -> list[dict[str, Any]]:
    result = []
    for model_id, spec in INSTALL_SPECS.items():
        with _LOCK:
            job = dict(_JOBS.get(model_id) or {})
        state = job or _read_state(model_id)
        compatible, reason = _compatibility(spec)
        installed = _installed(model_id, spec)
        weights_installed = _files_installed(model_id, spec)
        runtime_required = bool(spec.get("runtime_packages"))
        runtime_installed = _runtime_python(model_id).is_file()
        status = "installed" if installed else ("needs_runtime" if weights_installed and runtime_required and not runtime_installed else state.get("status", "not_installed"))
        result.append({
            "id": model_id,
            "label": spec["label"],
            "status": status,
            "installed": installed,
            "install_supported": spec.get("kind") != "unsupported",
            "compatible": compatible,
            "blocked_reason": reason,
            "estimated_bytes": int(spec.get("estimated_bytes", 0)),
            "size_label": _format_bytes(int(spec.get("estimated_bytes", 0))),
            "min_memory_gb": int(spec.get("min_memory_gb", 0)),
            "license": spec.get("license"),
            "commercial_restricted": bool(spec.get("commercial_restricted")),
            "tier": spec.get("tier", "advanced"),
            "license_url": spec.get("license_url"),
            "source_url": spec.get("source_url"),
            "weights_installed": weights_installed,
            "runtime_required": runtime_required,
            "runtime_installed": runtime_installed,
            "progress": int(state.get("progress", 100 if installed else 0)),
            "downloaded_bytes": int(state.get("downloaded_bytes", 0)),
            "total_bytes": int(state.get("total_bytes", spec.get("estimated_bytes", 0))),
            "detail": state.get("detail"),
            "target": str(_target_root(spec)),
            "runtime_target": str(_runtime_root(model_id)) if spec.get("runtime_packages") else None,
        })
    return result


def model_runtime_info(model_id: str) -> dict[str, Any]:
    spec = INSTALL_SPECS.get(model_id)
    if spec is None:
        raise ValueError("Model không tồn tại")
    state = _read_state(model_id)
    return {
        "id": model_id,
        "installed": _installed(model_id, spec),
        "target": str(_target_root(spec)),
        "python": str(_runtime_python(model_id)) if _runtime_python(model_id).is_file() else None,
        "state": state,
    }


def start_install(model_id: str, *, accept_license: bool = False) -> dict[str, Any]:
    spec = INSTALL_SPECS.get(model_id)
    if spec is None:
        raise ValueError("Model không tồn tại")
    if spec.get("kind") == "unsupported":
        raise ValueError(str(spec.get("blocked_reason") or "Model chưa hỗ trợ cài tự động"))
    if spec.get("commercial_restricted") and not accept_license:
        raise ValueError("Bạn cần xác nhận giấy phép sử dụng trước khi tải model này")
    compatible, reason = _compatibility(spec)
    if not compatible:
        raise ValueError(reason or "Máy không đáp ứng yêu cầu cài model")
    with _LOCK:
        current = _JOBS.get(model_id)
        if current and current.get("status") in {"queued", "downloading"}:
            return dict(current)
        job = {
            "id": model_id,
            "status": "queued",
            "progress": 0,
            "downloaded_bytes": 0,
            "total_bytes": int(spec.get("estimated_bytes", 0)),
            "detail": "Đang chuẩn bị danh sách file…",
            "started_at": time.time(),
        }
        _JOBS[model_id] = job
    threading.Thread(target=_run_install, args=(model_id, spec), daemon=True, name=f"model-install-{model_id}").start()
    return dict(job)


def start_runtime_repair(model_id: str) -> dict[str, Any]:
    spec = INSTALL_SPECS.get(model_id)
    if spec is None:
        raise ValueError("Model không tồn tại")
    if not spec.get("runtime_packages"):
        raise ValueError("Model này không cần Python runtime riêng")
    if not _files_installed(model_id, spec):
        raise ValueError("Hãy tải model trước khi sửa runtime")
    compatible, reason = _compatibility(spec)
    if not compatible:
        raise ValueError(reason or "Máy không đáp ứng yêu cầu runtime")
    with _LOCK:
        current = _JOBS.get(model_id)
        if current and current.get("status") in {"queued", "downloading", "installing_runtime"}:
            return dict(current)
        job = {
            "id": model_id,
            "status": "installing_runtime",
            "progress": 97,
            "downloaded_bytes": 0,
            "total_bytes": int(spec.get("runtime_estimated_bytes", 0)),
            "detail": "Đang sửa model runtime…",
            "started_at": time.time(),
        }
        _JOBS[model_id] = job
    threading.Thread(target=_run_runtime_repair, args=(model_id, spec), daemon=True, name=f"model-runtime-{model_id}").start()
    return dict(job)


def _run_runtime_repair(model_id: str, spec: dict[str, Any]) -> None:
    try:
        runtime_python = _install_runtime(model_id, spec)
        state = _read_state(model_id)
        state.update({
            "status": "installed",
            "progress": 100,
            "detail": "Model và runtime đã sẵn sàng",
            "runtime_python": runtime_python,
            "installed_at": time.time(),
        })
        _write_state(model_id, state)
        _set_job(model_id, **state)
    except Exception as exc:
        state = _read_state(model_id)
        state.update({"status": "error", "progress": 0, "detail": str(exc), "failed_at": time.time()})
        _write_state(model_id, state)
        _set_job(model_id, **state)


def _request(url: str) -> urllib.request.Request:
    headers = {"User-Agent": "MOSA-TOOL-ALL/1.0"}
    token = os.environ.get("HF_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return urllib.request.Request(url, headers=headers)


def _snapshot_files(spec: dict[str, Any]) -> list[DownloadFile]:
    repo = str(spec["repo"])
    endpoint = f"https://huggingface.co/api/models/{repo}/tree/main?recursive=true&expand=false"
    with urllib.request.urlopen(_request(endpoint), timeout=60) as response:
        entries = json.load(response)
    files = []
    excluded = {"README.md", ".gitattributes", "LICENSE", "LICENSE.md"}
    include_patterns = tuple(spec.get("snapshot_include") or ())
    exclude_patterns = tuple(spec.get("snapshot_exclude") or ())
    for entry in entries:
        path = entry.get("path")
        if entry.get("type") != "file" or not isinstance(path, str):
            continue
        if path in excluded or path.startswith(("assets/", "examples/")):
            continue
        if include_patterns and not any(fnmatch.fnmatch(path, pattern) for pattern in include_patterns):
            continue
        if any(fnmatch.fnmatch(path, pattern) for pattern in exclude_patterns):
            continue
        files.append(DownloadFile(_hf_url(repo, path), path, int(entry.get("size") or 0)))
    if not files:
        raise RuntimeError("Kho model không trả về file có thể tải")
    return files


def _set_job(model_id: str, **updates: Any) -> None:
    with _LOCK:
        job = _JOBS.setdefault(model_id, {"id": model_id})
        job.update(updates)


def _download_file(model_id: str, file: DownloadFile, destination: Path, counters: dict[str, int]) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_suffix(destination.suffix + ".part")
    existing = partial.stat().st_size if partial.is_file() else 0
    request = _request(file.url)
    if existing:
        request.add_header("Range", f"bytes={existing}-")
    mode = "ab" if existing else "wb"
    try:
        response = urllib.request.urlopen(request, timeout=120)
    except urllib.error.HTTPError as exc:
        if exc.code != 416:
            raise
        partial.replace(destination)
        counters["downloaded"] += existing
        return
    if existing and getattr(response, "status", 200) != 206:
        existing = 0
        mode = "wb"
    counters["downloaded"] += existing
    last_update = 0.0
    with response, partial.open(mode) as output:
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            output.write(chunk)
            counters["downloaded"] += len(chunk)
            now = time.monotonic()
            if now - last_update >= 0.4:
                total = max(counters["total"], 1)
                _set_job(
                    model_id,
                    status="downloading",
                    progress=min(99, int(counters["downloaded"] * 100 / total)),
                    downloaded_bytes=counters["downloaded"],
                    total_bytes=counters["total"],
                    detail=f"Đang tải {destination.name}",
                )
                last_update = now
    partial.replace(destination)


def _safe_archive_destination(root: Path, member_name: str) -> Path:
    destination = (root / member_name).resolve()
    if root.resolve() not in destination.parents and destination != root.resolve():
        raise RuntimeError(f"Archive chứa đường dẫn không an toàn: {member_name}")
    return destination


def _extract_archive(archive: Path, destination: Path) -> list[str]:
    # ``extract_to`` may intentionally contain ``..`` (MuseTalk keeps its
    # source checkout beside the weights directory).  Normalize the root once
    # so Windows Path.relative_to() compares two canonical absolute paths.
    destination = destination.resolve()
    destination.mkdir(parents=True, exist_ok=True)
    extracted: list[str] = []
    if zipfile.is_zipfile(archive):
        with zipfile.ZipFile(archive) as bundle:
            for member in bundle.infolist():
                target = _safe_archive_destination(destination, member.filename)
                if member.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                with bundle.open(member) as source, target.open("wb") as output:
                    shutil.copyfileobj(source, output)
                if member.external_attr >> 16:
                    target.chmod(member.external_attr >> 16)
                extracted.append(str(target.relative_to(destination)))
        return extracted
    if tarfile.is_tarfile(archive):
        with tarfile.open(archive) as bundle:
            for member in bundle.getmembers():
                target = _safe_archive_destination(destination, member.name)
                if member.isdir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                if not member.isfile():
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                source = bundle.extractfile(member)
                if source is None:
                    continue
                with source, target.open("wb") as output:
                    shutil.copyfileobj(source, output)
                target.chmod(member.mode & 0o777)
                extracted.append(str(target.relative_to(destination)))
        return extracted
    raise RuntimeError(f"Định dạng archive không hỗ trợ: {archive.name}")


def _install_runtime(model_id: str, spec: dict[str, Any]) -> str | None:
    packages = tuple(spec.get("runtime_packages") or ())
    if not packages:
        return None
    uv = _uv_executable()
    if not uv:
        raise RuntimeError("Không tìm thấy uv runtime manager")
    runtime_root = _runtime_root(model_id)
    python = _runtime_python(model_id)
    _set_job(model_id, status="installing_runtime", progress=97, detail="Đang tạo Python runtime riêng…")
    if not python.is_file():
        command = [
            uv,
            "venv",
            "--python",
            str(spec.get("python_version", "3.11")),
            "--python-preference",
            "managed",
            "--seed",
            str(runtime_root),
        ]
        result = subprocess.run(command, capture_output=True, text=True, timeout=900, check=False)
        if result.returncode != 0:
            raise RuntimeError((result.stderr or result.stdout or "Không tạo được model runtime").strip()[-1200:])
    _set_job(model_id, status="installing_runtime", progress=98, detail="Đang cài thư viện chạy model…")
    command = [uv, "pip", "install", "--python", str(python), *packages]
    result = subprocess.run(command, capture_output=True, text=True, timeout=3600, check=False)
    if result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout or "Không cài được thư viện model").strip()[-1200:])
    return str(python)


def _run_install(model_id: str, spec: dict[str, Any]) -> None:
    target = _target_root(spec)
    try:
        files = _snapshot_files(spec) if spec["kind"] == "snapshot" else _spec_files(spec)
        total = sum(item.size_bytes for item in files) or int(spec.get("estimated_bytes", 0))
        counters = {"downloaded": 0, "total": total}
        _set_job(model_id, status="downloading", total_bytes=total, detail="Bắt đầu tải model…")
        installed_files = []
        for file in files:
            destination = target / file.relative_path
            if not destination.is_file() or (file.size_bytes and destination.stat().st_size != file.size_bytes):
                _download_file(model_id, file, destination, counters)
            else:
                counters["downloaded"] += destination.stat().st_size
            if file.extract_to is not None:
                extraction_root = target / file.extract_to
                extracted = _extract_archive(destination, extraction_root)
                installed_files.extend(str((Path(file.extract_to) / item).as_posix()) for item in extracted)
                if file.remove_after_extract:
                    destination.unlink(missing_ok=True)
            else:
                installed_files.append(file.relative_path)
        runtime_python = _install_runtime(model_id, spec)
        settings = {
            key: str(value).format(target=target)
            for key, value in (spec.get("settings") or {}).items()
        }
        if settings:
            update_provider_settings(settings, [])
        state = {
            "id": model_id,
            "status": "installed",
            "progress": 100,
            "downloaded_bytes": counters["downloaded"],
            "total_bytes": total,
            "detail": "Đã tải model về máy",
            "files": installed_files,
            "target": str(target),
            "runtime_python": runtime_python,
            "installed_at": time.time(),
        }
        _write_state(model_id, state)
        _set_job(model_id, **state)
    except Exception as exc:
        state = {
            "id": model_id,
            "status": "error",
            "progress": 0,
            "detail": str(exc),
            "failed_at": time.time(),
        }
        _write_state(model_id, state)
        _set_job(model_id, **state)


def uninstall_model(model_id: str) -> dict[str, Any]:
    spec = INSTALL_SPECS.get(model_id)
    if spec is None:
        raise ValueError("Model không tồn tại")
    with _LOCK:
        current = _JOBS.get(model_id)
        if current and current.get("status") in {"queued", "downloading", "installing_runtime"}:
            raise ValueError("Không thể gỡ khi model đang được cài")
    state = _read_state(model_id)
    target = _target_root(spec)
    for relative in state.get("files") or []:
        path = target / str(relative)
        if path.is_dir():
            shutil.rmtree(path, ignore_errors=True)
        else:
            path.unlink(missing_ok=True)
    runtime_root = _runtime_root(model_id)
    if runtime_root.is_dir():
        shutil.rmtree(runtime_root)
    _state_path(model_id).unlink(missing_ok=True)
    with _LOCK:
        _JOBS.pop(model_id, None)
    return {"id": model_id, "status": "not_installed", "installed": False}
