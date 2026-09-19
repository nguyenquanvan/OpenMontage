"""Catalog and readiness checks for free/local model paths.

The catalog is deliberately advisory: it never downloads large model weights or
starts a local server without an explicit user action. Status is derived from the
same tool registry used by the production selectors.
"""

from __future__ import annotations

from typing import Any


FREE_MODEL_DEFINITIONS: tuple[dict[str, Any], ...] = (
    {
        "id": "local-image-diffusers",
        "name": "Stable Diffusion / Diffusers",
        "category": "Ảnh",
        "tool": "local_diffusion",
        "runtime": "local_gpu",
        "model": "stabilityai/stable-diffusion-2-1-base",
        "cost": "0 USD / lượt",
        "requirements": "diffusers + PyTorch; GPU khuyến nghị, CPU vẫn chạy được nhưng chậm",
        "setup": "pip install diffusers transformers accelerate torch",
        "env": ["LOCAL_IMAGE_MODEL"],
    },
    {
        "id": "comfyui-image",
        "name": "ComfyUI — Flux 2 / workflow ảnh",
        "category": "Ảnh",
        "tool": "comfyui_image",
        "runtime": "local_gpu",
        "model": "Flux 2 hoặc workflow tự chọn",
        "cost": "0 USD / lượt",
        "requirements": "ComfyUI đang chạy và model weights đã tải",
        "setup": "Cài ComfyUI, chạy tại http://localhost:8188",
        "env": ["COMFYUI_SERVER_URL", "COMFYUI_IMAGE_SERVER_URL"],
    },
    {
        "id": "local-video-wan",
        "name": "WAN / Hunyuan / CogVideo local",
        "category": "Video",
        "tool": "wan_video",
        "runtime": "local_gpu",
        "model": "WAN 2.1/2.2, HunyuanVideo, CogVideoX",
        "cost": "0 USD / lượt",
        "requirements": "diffusers + PyTorch; NVIDIA GPU hoặc Apple Silicon MPS",
        "setup": "Bật VIDEO_GEN_LOCAL_ENABLED và chọn VIDEO_GEN_LOCAL_MODEL",
        "env": ["VIDEO_GEN_LOCAL_ENABLED", "VIDEO_GEN_LOCAL_MODEL"],
    },
    {
        "id": "local-video-ltx",
        "name": "LTX-2 local",
        "category": "Video",
        "tool": "ltx_video_local",
        "runtime": "local_gpu",
        "model": "Lightricks/LTX-2",
        "cost": "0 USD / lượt",
        "requirements": "diffusers + PyTorch; GPU khuyến nghị",
        "setup": "Bật VIDEO_GEN_LOCAL_ENABLED=true và chọn ltx2-local",
        "env": ["VIDEO_GEN_LOCAL_ENABLED", "VIDEO_GEN_LOCAL_MODEL"],
    },
    {
        "id": "comfyui-video",
        "name": "ComfyUI — WAN video / workflow video",
        "category": "Video",
        "tool": "comfyui_video",
        "runtime": "local_gpu",
        "model": "WAN 2.2 hoặc workflow tự chọn",
        "cost": "0 USD / lượt",
        "requirements": "ComfyUI đang chạy và model weights đã tải",
        "setup": "Cài ComfyUI, chạy tại http://localhost:8188",
        "env": ["COMFYUI_SERVER_URL", "COMFYUI_VIDEO_SERVER_URL"],
    },
    {
        "id": "piper-tts",
        "name": "Piper TTS local",
        "category": "Giọng nói",
        "tool": "piper_tts",
        "runtime": "local",
        "model": "en_US-lessac-medium hoặc voice model tương thích",
        "cost": "0 USD / lượt",
        "requirements": "piper binary và voice model",
        "setup": "pip install piper-tts rồi tải voice model",
        "env": ["PIPER_MODEL"],
    },
    {
        "id": "whisper-local",
        "name": "faster-whisper local",
        "category": "Phân tích âm thanh",
        "tool": "transcriber",
        "runtime": "local",
        "model": "tiny / base / small / medium / large-v3",
        "cost": "0 USD / lượt",
        "requirements": "faster-whisper; CPU được, GPU giúp nhanh hơn",
        "setup": "pip install faster-whisper",
        "env": ["WHISPER_MODEL_SIZE"],
    },
    {
        "id": "comfyui-music",
        "name": "ACE-Step local qua ComfyUI",
        "category": "Âm nhạc",
        "tool": "comfyui_music",
        "runtime": "local_gpu",
        "model": "ACE-Step 1 / 3.5B",
        "cost": "0 USD / lượt",
        "requirements": "ComfyUI và ACE-Step checkpoint",
        "setup": "Cài ComfyUI, tải ACE-Step checkpoint, chạy local server",
        "env": ["COMFYUI_SERVER_URL", "COMFYUI_MUSIC_SERVER_URL"],
    },
)


def free_model_catalog() -> list[dict[str, Any]]:
    """Return model definitions enriched with live registry readiness."""
    from tools.tool_registry import registry

    registry.ensure_discovered()
    tools = {name: registry.get(name) for name in registry.list_all()}
    catalog: list[dict[str, Any]] = []
    for definition in FREE_MODEL_DEFINITIONS:
        item = dict(definition)
        tool = tools.get(item["tool"])
        if tool is None:
            item.update({"available": False, "status": "missing", "status_label": "Chưa có tool"})
        else:
            try:
                status = tool.get_status().value
            except Exception:
                status = "unavailable"
            item.update({
                "available": status == "available",
                "status": status,
                "status_label": "SẴN SÀNG" if status == "available" else "CHƯA SẴN SÀNG",
                "tool_version": getattr(tool, "version", None),
            })
        catalog.append(item)
    return catalog
