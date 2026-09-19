"""Local provider settings for the Backlot control plane.

Secrets stay on the local machine in ``.env``.  The HTTP API exposes only
configuration metadata and masked suffixes, never the stored values.
"""

from __future__ import annotations

import os
import re
import secrets
import math
from pathlib import Path
from typing import Any

from lib.paths import REPO_ROOT

ENV_PATH = Path(os.environ.get("OPENMONTAGE_ENV_PATH") or (REPO_ROOT / ".env"))
_KEY_RE = re.compile(r"^\s*(?:export\s+)?([A-Z][A-Z0-9_]*)\s*=")
_MAX_VALUE_LENGTH = 4096

PROVIDER_FIELDS: tuple[dict[str, str], ...] = (
    {"key": "FAL_KEY", "label": "fal.ai", "group": "Hình ảnh & video", "hint": "FLUX, Veo, Kling, MiniMax, Recraft và Seedance qua fal.ai."},
    {"key": "FAL_AI_API_KEY", "label": "fal.ai (tên thay thế)", "group": "Hình ảnh & video", "hint": "Tên biến thay thế cho FAL_KEY; chỉ cần điền một trong hai."},
    {"key": "KLING_API_KEY", "label": "Kling", "group": "Hình ảnh & video", "hint": "Kling chính thức: video, ảnh, TTS, avatar và lip-sync."},
    {"key": "MINIMAX_API_KEY", "label": "MiniMax", "group": "Hình ảnh & video", "hint": "MiniMax/Hailuo image và video."},
    {"key": "REPLICATE_API_TOKEN", "label": "Replicate", "group": "Hình ảnh & video", "hint": "Các model video được lưu trên Replicate."},
    {"key": "HIGGSFIELD_API_KEY", "label": "Higgsfield key", "group": "Hình ảnh & video", "hint": "Dùng cùng HIGGSFIELD_API_SECRET."},
    {"key": "HIGGSFIELD_API_SECRET", "label": "Higgsfield secret", "group": "Hình ảnh & video", "hint": "Secret đi kèm Higgsfield key."},
    {"key": "GOOGLE_API_KEY", "label": "Google AI", "group": "Hình ảnh & video", "hint": "Imagen, Google TTS và Veo."},
    {"key": "GEMINI_API_KEY", "label": "Gemini (tên thay thế)", "group": "Hình ảnh & video", "hint": "Tên thay thế cho GOOGLE_API_KEY."},
    {"key": "XAI_API_KEY", "label": "xAI / Grok", "group": "Hình ảnh & video", "hint": "Grok image và video."},
    {"key": "TENCENT_TOKENHUB_API_KEY", "label": "Tencent Hunyuan", "group": "Hình ảnh & video", "hint": "Hunyuan image và video qua TokenHub."},
    {"key": "DASHSCOPE_API_KEY", "label": "Alibaba DashScope", "group": "Hình ảnh & video", "hint": "Qwen image, TTS và ASR."},
    {"key": "ARK_API_KEY", "label": "Volcengine Ark", "group": "Hình ảnh & video", "hint": "Seedance trực tiếp qua Volcengine Ark."},
    {"key": "HEYGEN_API_KEY", "label": "HeyGen", "group": "Hình ảnh & video", "hint": "Avatar và video qua HeyGen gateway."},
    {"key": "RUNWAY_API_KEY", "label": "Runway", "group": "Hình ảnh & video", "hint": "Runway và các model video được hỗ trợ."},
    {"key": "OPENAI_API_KEY", "label": "OpenAI", "group": "Giọng nói & ảnh", "hint": "OpenAI TTS và GPT Image."},
    {"key": "ELEVENLABS_API_KEY", "label": "ElevenLabs", "group": "Giọng nói & ảnh", "hint": "Voice, nhạc và hiệu ứng âm thanh cao cấp."},
    {"key": "DOUBAO_SPEECH_API_KEY", "label": "Doubao Speech", "group": "Giọng nói & ảnh", "hint": "TTS tiếng Trung/đa ngôn ngữ của Volcengine."},
    {"key": "FISH_AUDIO_API_KEY", "label": "Fish Audio", "group": "Giọng nói & ảnh", "hint": "TTS và voice cloning theo reference_id."},
    {"key": "SUNO_API_KEY", "label": "Suno", "group": "Âm nhạc", "hint": "Tạo nhạc nền và instrumental bằng AI."},
    {"key": "PEXELS_API_KEY", "label": "Pexels", "group": "Kho footage", "hint": "Video và ảnh stock miễn phí."},
    {"key": "PIXABAY_API_KEY", "label": "Pixabay", "group": "Kho footage", "hint": "Video, ảnh và nhạc stock miễn phí."},
    {"key": "UNSPLASH_ACCESS_KEY", "label": "Unsplash", "group": "Kho footage", "hint": "Ảnh stock miễn phí."},
    {"key": "HF_TOKEN", "label": "Hugging Face", "group": "Phân tích", "hint": "Speaker diarization và model phân tích."},
    {"key": "AZURE_SPEECH_KEY", "label": "Azure Speech key", "group": "Phân tích", "hint": "Azure STT/TTS; cần thêm AZURE_SPEECH_REGION."},
    {"key": "AZURE_SPEECH_REGION", "label": "Azure Speech region", "group": "Phân tích", "hint": "Ví dụ: eastus. Đây là cấu hình, không phải secret."},
)

ALLOWED_KEYS = {field["key"] for field in PROVIDER_FIELDS}

LOCAL_FIELDS: tuple[dict[str, Any], ...] = (
    {"key": "VIDEO_GEN_LOCAL_ENABLED", "label": "Bật video local", "type": "boolean", "hint": "Cho phép selector dùng WAN/Hunyuan/CogVideo/LTX chạy trên máy."},
    {"key": "VIDEO_GEN_LOCAL_MODEL", "label": "Model video local", "type": "select", "options": ["wan2.2-ti2v-5b", "wan2.1-1.3b", "wan2.1-14b", "hunyuan-1.5", "ltx2-local", "cogvideo-5b", "cogvideo-2b"], "hint": "Chọn theo GPU/VRAM của máy."},
    {"key": "LOCAL_IMAGE_MODEL", "label": "Model ảnh local", "type": "text", "hint": "Hugging Face model id cho diffusers; mặc định Stable Diffusion 2.1."},
    {"key": "WHISPER_MODEL_SIZE", "label": "Model Whisper local", "type": "select", "options": ["tiny", "base", "small", "medium", "large-v2", "large-v3"], "hint": "base là điểm cân bằng; large cần nhiều RAM/VRAM hơn."},
    {"key": "PIPER_MODEL", "label": "Voice model Piper", "type": "text", "hint": "Đường dẫn hoặc tên voice model Piper đã tải trên máy."},
    {"key": "COMFYUI_SERVER_URL", "label": "ComfyUI server", "type": "url", "hint": "Mặc định http://localhost:8188."},
    {"key": "COMFYUI_IMAGE_SERVER_URL", "label": "ComfyUI ảnh riêng", "type": "url", "hint": "Tuỳ chọn: server ComfyUI dành riêng cho ảnh."},
    {"key": "COMFYUI_VIDEO_SERVER_URL", "label": "ComfyUI video riêng", "type": "url", "hint": "Tuỳ chọn: server ComfyUI dành riêng cho video."},
    {"key": "COMFYUI_MUSIC_SERVER_URL", "label": "ComfyUI nhạc riêng", "type": "url", "hint": "Tuỳ chọn: server ComfyUI dành riêng cho ACE-Step."},
)
LOCAL_ALLOWED_KEYS = {field["key"] for field in LOCAL_FIELDS}

COST_PROFILES: tuple[dict[str, str], ...] = (
    {
        "key": "economy",
        "label": "Tiết kiệm",
        "description": "Ưu tiên model local, stock và chi phí thấp trước.",
    },
    {
        "key": "balanced",
        "label": "Cân bằng",
        "description": "Cân bằng chất lượng, độ ổn định và chi phí.",
    },
    {
        "key": "quality",
        "label": "Chất lượng cao",
        "description": "Ưu tiên chất lượng và khả năng kiểm soát hình ảnh/video.",
    },
)
COST_PROFILE_KEYS = {profile["key"] for profile in COST_PROFILES}
DEFAULT_COST_PROFILE = "balanced"
COST_PROFILE_ENV = "OPENMONTAGE_COST_PROFILE"
BUDGET_ENV = "OPENMONTAGE_BUDGET_USD"
_UNSET = object()


def _read_env() -> str:
    try:
        return ENV_PATH.read_text(encoding="utf-8")
    except FileNotFoundError:
        return ""


def _env_values() -> dict[str, str]:
    values: dict[str, str] = {}
    for line in _read_env().splitlines():
        match = _KEY_RE.match(line)
        if not match:
            continue
        key = match.group(1)
        raw = line.split("=", 1)[1].strip()
        if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in {"'", '"'}:
            raw = raw[1:-1]
        values[key] = raw
    return values


def _mask(value: str | None) -> str | None:
    if not value:
        return None
    return f"••••{value[-4:]}" if len(value) >= 4 else "••••"


def provider_status() -> list[dict[str, Any]]:
    values = _env_values()
    return [
        {
            **field,
            "configured": bool(values.get(field["key"]) or os.environ.get(field["key"])),
            "masked": _mask(values.get(field["key"]) or os.environ.get(field["key"])),
        }
        for field in PROVIDER_FIELDS
    ]


def _setting_value(key: str) -> str | None:
    values = _env_values()
    return values.get(key) or os.environ.get(key)


def _parse_budget(value: Any) -> float | None:
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    if isinstance(value, bool):
        raise ValueError("budget_usd phải là số không âm")
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("budget_usd phải là số không âm") from exc
    if not math.isfinite(parsed) or parsed < 0 or parsed > 1_000_000:
        raise ValueError("budget_usd phải nằm trong khoảng từ 0 đến 1,000,000")
    return round(parsed, 10)


def cost_settings() -> dict[str, Any]:
    profile = _setting_value(COST_PROFILE_ENV) or DEFAULT_COST_PROFILE
    if profile not in COST_PROFILE_KEYS:
        profile = DEFAULT_COST_PROFILE
    raw_budget = _setting_value(BUDGET_ENV)
    try:
        budget = _parse_budget(raw_budget)
    except ValueError:
        budget = None
    return {
        "cost_profile": profile,
        "budget_usd": budget,
        "cost_profiles": list(COST_PROFILES),
    }


def settings_status() -> dict[str, Any]:
    values = _env_values()
    local_settings = []
    for field in LOCAL_FIELDS:
        key = field["key"]
        local_settings.append({
            **field,
            "value": values.get(key) or os.environ.get(key) or "",
        })
    return {**cost_settings(), "providers": provider_status(), "local_settings": local_settings}


def _quote(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _write_env(values: dict[str, str | None]) -> None:
    original = _read_env()
    lines = original.splitlines()
    seen: set[str] = set()
    output: list[str] = []
    for line in lines:
        match = _KEY_RE.match(line)
        if not match:
            output.append(line)
            continue
        key = match.group(1)
        if key not in values:
            output.append(line)
            continue
        seen.add(key)
        value = values[key]
        output.append(f"{key}={_quote(value)}" if value else f"{key}=")
    for key, value in values.items():
        if key not in seen:
            if output and output[-1] != "":
                output.append("")
            output.append(f"{key}={_quote(value)}" if value else f"{key}=")
    content = "\n".join(output).rstrip("\n") + "\n"
    ENV_PATH.parent.mkdir(parents=True, exist_ok=True)
    temp = ENV_PATH.with_name(f".{ENV_PATH.name}.{secrets.token_hex(8)}.tmp")
    try:
        temp.write_text(content, encoding="utf-8")
        temp.chmod(0o600)
        os.replace(temp, ENV_PATH)
        ENV_PATH.chmod(0o600)
    finally:
        if temp.exists():
            temp.unlink()


def update_provider_settings(updates: dict[str, Any], clear: list[Any]) -> list[dict[str, Any]]:
    unknown = (set(updates) | {str(key) for key in clear}) - (ALLOWED_KEYS | LOCAL_ALLOWED_KEYS)
    if unknown:
        raise ValueError(f"Unknown provider setting: {sorted(unknown)[0]}")

    changed: dict[str, str | None] = {}
    for key, value in updates.items():
        if not isinstance(key, str) or not isinstance(value, str):
            raise ValueError("Provider setting names and values must be text")
        value = value.strip()
        if len(value) > _MAX_VALUE_LENGTH or "\n" in value or "\r" in value:
            raise ValueError(f"Invalid value for {key}")
        if value:
            changed[key] = value
    for key in clear:
        if not isinstance(key, str):
            raise ValueError("Provider setting names must be text")
        changed[key] = None

    if changed:
        _write_env(changed)
        for key, value in changed.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
    return provider_status()


def update_cost_settings(profile: Any = _UNSET, budget_usd: Any = _UNSET) -> dict[str, Any]:
    validate_cost_settings(profile=profile, budget_usd=budget_usd)
    changed: dict[str, str | None] = {}
    if profile is not _UNSET:
        changed[COST_PROFILE_ENV] = profile
    if budget_usd is not _UNSET:
        parsed_budget = _parse_budget(budget_usd)
        changed[BUDGET_ENV] = None if parsed_budget is None else format(parsed_budget, ".10g")

    if changed:
        _write_env(changed)
        for key, value in changed.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
    return cost_settings()


def validate_cost_settings(*, profile: Any = _UNSET, budget_usd: Any = _UNSET) -> None:
    if profile is not _UNSET and (not isinstance(profile, str) or profile not in COST_PROFILE_KEYS):
        raise ValueError("cost_profile không hợp lệ")
    if budget_usd is not _UNSET:
        _parse_budget(budget_usd)
