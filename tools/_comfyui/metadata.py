"""Shared metadata helpers for ComfyUI provider tools."""

from __future__ import annotations

import hashlib
import json
from typing import Any


COMFYUI_SETUP_OFFER: dict[str, Any] = {
    "kind": "local_server",
    "fix_complexity": "1-minute env-var if ComfyUI is already running; otherwise local install",
    "env_var": "COMFYUI_SERVER_URL",
    "default_url": "http://127.0.0.1:8188",
    "health_check": "GET /system_stats",
    "what_it_unlocks": [
        "free local image generation through ComfyUI workflows",
        "free local video generation through ComfyUI workflows",
        "community workflow_json/workflow_path execution",
    ],
    # Optional: point image/video generation at separate ComfyUI instances
    # (e.g. different GPUs). Each overrides COMFYUI_SERVER_URL for its own
    # tool only; single-server setups can ignore this entirely.
    "per_capability_env_var_overrides": {
        "comfyui_image": "COMFYUI_IMAGE_SERVER_URL",
        "comfyui_video": "COMFYUI_VIDEO_SERVER_URL",
        "comfyui_music": "COMFYUI_MUSIC_SERVER_URL",
    },
}


BUNDLED_MODEL_STACKS: dict[str, list[dict[str, Any]]] = {
    "minimax-h3-local": [
        {
            "role": "diffusion_model",
            "name": "minimax_h3_fl2va_pruned_int8_convrot.safetensors",
            "quantization": "INT8 ConvRot",
            "destination_hint": "ComfyUI/models/diffusion_models/",
            "download_url": "https://huggingface.co/Comfy-Org/MiniMax-H3/tree/main/diffusion_models",
        },
        {
            "role": "text_encoder",
            "name": "qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors",
            "quantization": "NVFP4 AWQ",
            "destination_hint": "ComfyUI/models/text_encoders/",
            "download_url": "https://huggingface.co/Comfy-Org/MiniMax-H3/tree/main/text_encoders",
        },
        {
            "role": "video_vae",
            "name": "minimax_h3_video_vae_fp16.safetensors",
            "destination_hint": "ComfyUI/models/vae/",
            "download_url": "https://huggingface.co/Comfy-Org/MiniMax-H3/tree/main/vae",
        },
        {
            "role": "audio_vae",
            "name": "minimax_h3_audio_vae_fp32.safetensors",
            "destination_hint": "ComfyUI/models/vae/",
            "download_url": "https://huggingface.co/Comfy-Org/MiniMax-H3/tree/main/vae",
        },
    ],
    "flux2-txt2img": [
        {
            "role": "diffusion_model",
            "name": "flux2-dev-nvfp4.safetensors",
            "quantization": "NVFP4",
            "destination_hint": "ComfyUI/models/diffusion_models/",
            "download_url": (
                "https://huggingface.co/black-forest-labs/FLUX.2-dev-NVFP4"
            ),
        },
        {
            "role": "text_encoder",
            "name": "mistral_3_small_flux2_fp4_mixed.safetensors",
            "quantization": "FP4 mixed",
            "destination_hint": "ComfyUI/models/text_encoders/",
            "download_url": (
                "https://huggingface.co/Comfy-Org/flux2-dev/tree/main/"
                "split_files/text_encoders"
            ),
        },
        {
            "role": "vae",
            "name": "flux2-vae.safetensors",
            "destination_hint": "ComfyUI/models/vae/",
            "download_url": (
                "https://huggingface.co/Comfy-Org/flux2-dev/blob/main/"
                "split_files/vae/flux2-vae.safetensors"
            ),
        },
    ],
    "flux1-schnell-gguf-txt2img": [
        {
            "role": "diffusion_model",
            "name": "flux1-schnell-Q4_K_S.gguf",
            "quantization": "GGUF Q4_K_S",
            "destination_hint": "ComfyUI/models/unet/ (needs the ComfyUI-GGUF custom node)",
            "download_url": "https://huggingface.co/city96/FLUX.1-schnell-gguf",
        },
        {
            "role": "text_encoder",
            "name": "t5-v1_1-xxl-encoder-Q4_K_M.gguf",
            "quantization": "GGUF Q4_K_M",
            "destination_hint": "ComfyUI/models/clip/",
            "download_url": "https://huggingface.co/city96/t5-v1_1-xxl-encoder-gguf",
        },
        {
            "role": "clip",
            "name": "clip_l.safetensors",
            "destination_hint": "ComfyUI/models/clip/",
            "download_url": "https://huggingface.co/comfyanonymous/flux_text_encoders",
        },
        {
            "role": "vae",
            "name": "ae.safetensors",
            "destination_hint": "ComfyUI/models/vae/",
            "download_url": "https://huggingface.co/black-forest-labs/FLUX.1-schnell",
        },
    ],
    "wan22-t2v-4step": [
        {
            "role": "text_encoder",
            "name": "umt5_xxl_fp8_e4m3fn_scaled.safetensors",
            "quantization": "FP8",
            "destination_hint": "ComfyUI/models/text_encoders/",
            "download_url": (
                "https://huggingface.co/Comfy-Org/Wan_2.2_ComfyUI_Repackaged/"
                "tree/main/split_files/text_encoders"
            ),
        },
        {
            "role": "diffusion_model_high_noise",
            "name": "wan2.2_t2v_high_noise_14B_fp8_scaled.safetensors",
            "quantization": "FP8",
            "destination_hint": "ComfyUI/models/diffusion_models/",
            "download_url": (
                "https://huggingface.co/Comfy-Org/Wan_2.2_ComfyUI_Repackaged/"
                "blob/main/split_files/diffusion_models/"
                "wan2.2_t2v_high_noise_14B_fp8_scaled.safetensors"
            ),
        },
        {
            "role": "diffusion_model_low_noise",
            "name": "wan2.2_t2v_low_noise_14B_fp8_scaled.safetensors",
            "quantization": "FP8",
            "destination_hint": "ComfyUI/models/diffusion_models/",
            "download_url": (
                "https://huggingface.co/Comfy-Org/Wan_2.2_ComfyUI_Repackaged/"
                "tree/main/split_files/diffusion_models"
            ),
        },
        {
            "role": "vae",
            "name": "wan_2.1_vae.safetensors",
            "destination_hint": "ComfyUI/models/vae/",
            "download_url": (
                "https://huggingface.co/Comfy-Org/Wan_2.1_ComfyUI_repackaged/"
                "tree/main/split_files/vae"
            ),
        },
        {
            "role": "lora",
            "name": "wan2.2_t2v_lightx2v_4steps_lora_v1.1_high_noise.safetensors",
            "strength_model": 1.0,
            "destination_hint": "ComfyUI/models/loras/",
            "download_url": (
                "https://huggingface.co/Comfy-Org/Wan_2.2_ComfyUI_Repackaged/"
                "tree/main/split_files/loras"
            ),
        },
        {
            "role": "lora",
            "name": "wan2.2_t2v_lightx2v_4steps_lora_v1.1_low_noise.safetensors",
            "strength_model": 1.0,
            "destination_hint": "ComfyUI/models/loras/",
            "download_url": (
                "https://huggingface.co/Comfy-Org/Wan_2.2_ComfyUI_Repackaged/"
                "tree/main/split_files/loras"
            ),
        },
    ],
    "wan22-i2v-4step": [
        {
            "role": "text_encoder",
            "name": "umt5_xxl_fp8_e4m3fn_scaled.safetensors",
            "quantization": "FP8",
            "destination_hint": "ComfyUI/models/text_encoders/",
            "download_url": (
                "https://huggingface.co/Comfy-Org/Wan_2.2_ComfyUI_Repackaged/"
                "tree/main/split_files/text_encoders"
            ),
        },
        {
            "role": "diffusion_model_high_noise",
            "name": "wan2.2_i2v_high_noise_14B_fp8_scaled.safetensors",
            "quantization": "FP8",
            "destination_hint": "ComfyUI/models/diffusion_models/",
            "download_url": (
                "https://huggingface.co/Comfy-Org/Wan_2.2_ComfyUI_Repackaged/"
                "blob/main/split_files/diffusion_models/"
                "wan2.2_i2v_high_noise_14B_fp8_scaled.safetensors"
            ),
        },
        {
            "role": "diffusion_model_low_noise",
            "name": "wan2.2_i2v_low_noise_14B_fp8_scaled.safetensors",
            "quantization": "FP8",
            "destination_hint": "ComfyUI/models/diffusion_models/",
            "download_url": (
                "https://huggingface.co/Comfy-Org/Wan_2.2_ComfyUI_Repackaged/"
                "tree/main/split_files/diffusion_models"
            ),
        },
        {
            "role": "vae",
            "name": "wan_2.1_vae.safetensors",
            "destination_hint": "ComfyUI/models/vae/",
            "download_url": (
                "https://huggingface.co/Comfy-Org/Wan_2.1_ComfyUI_repackaged/"
                "tree/main/split_files/vae"
            ),
        },
        {
            "role": "lora",
            "name": "wan2.2_i2v_lightx2v_4steps_lora_v1_high_noise.safetensors",
            "strength_model": 1.0,
            "destination_hint": "ComfyUI/models/loras/",
            "download_url": (
                "https://huggingface.co/Comfy-Org/Wan_2.2_ComfyUI_Repackaged/"
                "tree/main/split_files/loras"
            ),
        },
        {
            "role": "lora",
            "name": "wan2.2_i2v_lightx2v_4steps_lora_v1_low_noise.safetensors",
            "strength_model": 1.0,
            "destination_hint": "ComfyUI/models/loras/",
            "download_url": (
                "https://huggingface.co/Comfy-Org/Wan_2.2_ComfyUI_Repackaged/"
                "tree/main/split_files/loras"
            ),
        },
    ],
    "ace-step-1-t2a": [
        {
            "role": "checkpoint",
            "name": "ace_step_v1_3.5b.safetensors",
            "destination_hint": "ComfyUI/models/checkpoints/",
            "download_url": (
                "https://huggingface.co/Comfy-Org/ACE-Step_ComfyUI_repackaged/"
                "blob/main/all_in_one/ace_step_v1_3.5b.safetensors"
            ),
        },
    ],
}


def workflow_hash(workflow: dict[str, Any]) -> str:
    """Return a stable hash of the final workflow JSON submitted to ComfyUI."""
    payload = json.dumps(workflow, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def model_stack(
    workflow_key: str | None, inputs: dict[str, Any]
) -> list[dict[str, Any]]:
    """Return bundled or caller-supplied model stack metadata."""
    if workflow_key:
        return [dict(item) for item in BUNDLED_MODEL_STACKS[workflow_key]]
    stack = inputs.get("workflow_model_stack")
    return stack if isinstance(stack, list) else []


def missing_models_payload(
    missing: list[str],
    *,
    workflow_key: str,
    workflow_name: str,
    operation: str | None = None,
) -> dict[str, Any]:
    """Build a machine-readable missing-model error payload."""
    stack_by_name = {
        item["name"]: item for item in BUNDLED_MODEL_STACKS.get(workflow_key, [])
    }
    items = []
    for name in missing:
        meta = dict(stack_by_name.get(name, {}))
        meta.setdefault("name", name)
        meta.setdefault("role", "unknown")
        meta.setdefault(
            "destination_hint", "ComfyUI/models/ matching the workflow node"
        )
        meta.setdefault("download_url", None)
        items.append(meta)

    return {
        "provider": "comfyui",
        "workflow": workflow_name,
        "operation": operation,
        "missing_models": items,
        "setup_offer": COMFYUI_SETUP_OFFER,
    }
