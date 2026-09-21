"""Isolated execution entrypoint for optional MOSA local-model runtimes."""

from __future__ import annotations

import inspect
import json
import os
import sys
from pathlib import Path


def _payload() -> tuple[str, dict]:
    if len(sys.argv) != 3:
        raise ValueError("usage: model_worker.py <operation> <payload-json>")
    value = json.loads(sys.argv[2])
    if not isinstance(value, dict):
        raise ValueError("payload must be an object")
    return sys.argv[1], value


def _result(**values):
    print(json.dumps(values, ensure_ascii=False))


def _construct(factory, candidates: dict):
    parameters = inspect.signature(factory).parameters
    return factory(**{key: value for key, value in candidates.items() if key in parameters})


def vieneu_tts(data: dict) -> None:
    from vieneu import Vieneu

    model_dir = data["model_dir"]
    engine = _construct(
        Vieneu,
        {
            "model_dir": model_dir,
            "model_path": model_dir,
            "local_dir": model_dir,
            "precision": data.get("precision", "int8"),
        },
    )
    kwargs = {"voice": data.get("voice")}
    if data.get("reference_audio"):
        kwargs["ref_audio"] = data["reference_audio"]
    audio = engine.infer(data["text"], **{key: value for key, value in kwargs.items() if value})
    output = Path(data["output_path"])
    output.parent.mkdir(parents=True, exist_ok=True)
    engine.save(audio, str(output))
    _result(output=str(output), voice=data.get("voice"), sample_rate=48000)


def kokoro_tts(data: dict) -> None:
    import numpy as np
    import soundfile as sf
    from kokoro import KPipeline

    candidates = {"lang_code": data.get("language", "a"), "repo_id": data["model_dir"]}
    pipeline = _construct(KPipeline, candidates)
    chunks = [audio for _, _, audio in pipeline(data["text"], voice=data.get("voice", "af_heart"))]
    if not chunks:
        raise RuntimeError("Kokoro did not produce audio")
    output = Path(data["output_path"])
    output.parent.mkdir(parents=True, exist_ok=True)
    sf.write(output, np.concatenate(chunks), 24000)
    _result(output=str(output), voice=data.get("voice", "af_heart"), sample_rate=24000)


def mlx_transcribe(data: dict) -> None:
    import mlx_whisper

    response = mlx_whisper.transcribe(
        data["input_path"],
        path_or_hf_repo=data["model_dir"],
        language=data.get("language"),
        word_timestamps=True,
    )
    output = Path(data["output_path"])
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(response, ensure_ascii=False, indent=2), encoding="utf-8")
    _result(output=str(output), language=response.get("language"), segments=response.get("segments", []))


def faster_whisper_transcribe(data: dict) -> None:
    from faster_whisper import WhisperModel

    model = WhisperModel(data["model_dir"], device="cpu", compute_type="int8")
    segments_iter, info = model.transcribe(
        data["input_path"],
        language=data.get("language"),
        word_timestamps=True,
        vad_filter=True,
    )
    segments = []
    words = []
    for segment in segments_iter:
        item = {"id": segment.id, "start": segment.start, "end": segment.end, "text": segment.text.strip()}
        item_words = []
        for word in segment.words or []:
            entry = {"word": word.word, "start": word.start, "end": word.end, "probability": word.probability}
            item_words.append(entry)
            words.append(entry)
        item["words"] = item_words
        segments.append(item)
    response = {"segments": segments, "word_timestamps": words, "language": info.language, "duration_seconds": info.duration}
    output = Path(data["output_path"])
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(response, ensure_ascii=False, indent=2), encoding="utf-8")
    _result(output=str(output), **response)


def piper_tts(data: dict) -> None:
    import wave
    from piper import PiperVoice

    model_dir = Path(data["model_dir"])
    model = model_dir / "vi_VN-vais1000-medium.onnx"
    config = model_dir / "vi_VN-vais1000-medium.onnx.json"
    voice = PiperVoice.load(str(model), config_path=str(config))
    output = Path(data["output_path"])
    output.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(output), "wb") as wav_file:
        voice.synthesize_wav(data["text"], wav_file)
    _result(output=str(output), model=str(model))


def florence_vision(data: dict) -> None:
    import torch
    from PIL import Image
    from transformers import AutoModelForCausalLM, AutoProcessor

    device = "cuda" if torch.cuda.is_available() else "mps" if torch.backends.mps.is_available() else "cpu"
    dtype = torch.float16 if device != "cpu" else torch.float32
    model = AutoModelForCausalLM.from_pretrained(data["model_dir"], trust_remote_code=True, torch_dtype=dtype).to(device)
    processor = AutoProcessor.from_pretrained(data["model_dir"], trust_remote_code=True)
    image = Image.open(data["input_path"]).convert("RGB")
    task = data.get("task", "<MORE_DETAILED_CAPTION>")
    inputs = processor(text=task, images=image, return_tensors="pt")
    inputs = {key: value.to(device, dtype=dtype) if value.is_floating_point() else value.to(device) for key, value in inputs.items()}
    generated = model.generate(**inputs, max_new_tokens=int(data.get("max_new_tokens", 512)), do_sample=False)
    text = processor.batch_decode(generated, skip_special_tokens=False)[0]
    parsed = processor.post_process_generation(text, task=task, image_size=image.size)
    output = Path(data["output_path"])
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(parsed, ensure_ascii=False, indent=2), encoding="utf-8")
    _result(output=str(output), task=task, result=parsed)


def paddle_ocr(data: dict) -> None:
    from paddleocr import PaddleOCR

    model_dir = Path(data["model_dir"])
    detection_dir = model_dir / "det"
    recognition_dir = model_dir / "rec"
    detection_children = [path for path in detection_dir.iterdir() if path.is_dir()] if detection_dir.is_dir() else []
    recognition_children = [path for path in recognition_dir.iterdir() if path.is_dir()] if recognition_dir.is_dir() else []
    if len(detection_children) == 1:
        detection_dir = detection_children[0]
    if len(recognition_children) == 1:
        recognition_dir = recognition_children[0]
    engine = _construct(
        PaddleOCR,
        {
            "lang": data.get("language", "en"),
            "use_doc_orientation_classify": False,
            "use_doc_unwarping": False,
            "use_textline_orientation": False,
            "text_detection_model_dir": str(detection_dir),
            "text_recognition_model_dir": str(recognition_dir),
            "det_model_dir": str(detection_dir),
            "rec_model_dir": str(recognition_dir),
            "use_angle_cls": False,
        },
    )
    if hasattr(engine, "predict"):
        raw = list(engine.predict(data["input_path"]))
        values = [item.json if hasattr(item, "json") else str(item) for item in raw]
    else:
        values = engine.ocr(data["input_path"], cls=False)
    output = Path(data["output_path"])
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(values, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    _result(output=str(output), results=values)


def depth_anything(data: dict) -> None:
    from PIL import Image
    from transformers import pipeline

    estimator = pipeline("depth-estimation", model=data["model_dir"])
    result = estimator(Image.open(data["input_path"]).convert("RGB"))
    output = Path(data["output_path"])
    output.parent.mkdir(parents=True, exist_ok=True)
    result["depth"].save(output)
    _result(output=str(output))


def rembg_remove(data: dict) -> None:
    from PIL import Image
    import rembg

    os.environ["U2NET_HOME"] = data["model_dir"]
    image = Image.open(data["input_path"])
    output_image = rembg.remove(
        image,
        session=rembg.new_session(data.get("model", "u2net")),
        alpha_matting=bool(data.get("alpha_matting", False)),
    )
    output = Path(data["output_path"])
    output.parent.mkdir(parents=True, exist_ok=True)
    output_image.save(output)
    _result(output=str(output), model=data.get("model", "u2net"))


def realesrgan_upscale(data: dict) -> None:
    import cv2
    from basicsr.archs.rrdbnet_arch import RRDBNet
    from realesrgan import RealESRGANer

    scale = int(data.get("scale", 4))
    model_name = data.get("model", "RealESRGAN_x4plus")
    blocks = 6 if "anime_6B" in model_name else 23
    network_scale = 2 if "x2plus" in model_name else 4
    network = RRDBNet(num_in_ch=3, num_out_ch=3, num_feat=64, num_block=blocks, num_grow_ch=32, scale=network_scale)
    model_path = str(Path(data["model_dir"]) / f"{model_name}.pth")
    upsampler = RealESRGANer(
        scale=network_scale,
        model_path=model_path,
        model=network,
        tile=int(data.get("tile", 0)),
        tile_pad=10,
        pre_pad=0,
        half=False,
    )
    image = cv2.imread(data["input_path"], cv2.IMREAD_UNCHANGED)
    if image is None:
        raise ValueError("Could not read input image")
    result, _ = upsampler.enhance(image, outscale=scale)
    output = Path(data["output_path"])
    output.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(output), result)
    _result(output=str(output), model=model_name, scale=scale, width=int(result.shape[1]), height=int(result.shape[0]))


def face_restore(data: dict) -> None:
    import cv2
    from gfpgan import GFPGANer

    model_name = data.get("model", "GFPGAN")
    filename = "CodeFormer.pth" if model_name == "CodeFormer" else "GFPGANv1.4.pth"
    arch = "CodeFormer" if model_name == "CodeFormer" else "clean"
    restorer = GFPGANer(
        model_path=str(Path(data["model_dir"]) / filename),
        upscale=int(data.get("upscale", 2)),
        arch=arch,
        channel_multiplier=2,
        bg_upsampler=None,
    )
    image = cv2.imread(data["input_path"], cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError("Could not read input image")
    _, faces, restored = restorer.enhance(
        image,
        has_aligned=False,
        only_center_face=False,
        paste_back=True,
        weight=float(data.get("fidelity", 0.5)) if model_name == "CodeFormer" else None,
    )
    output = Path(data["output_path"])
    output.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(output), restored)
    _result(output=str(output), model=model_name, faces_restored=len(faces or []))


def sam2_segment(data: dict) -> None:
    import numpy as np
    from PIL import Image
    from sam2.sam2_image_predictor import SAM2ImagePredictor

    predictor = SAM2ImagePredictor.from_pretrained(data["model_dir"])
    image = np.asarray(Image.open(data["input_path"]).convert("RGB"))
    predictor.set_image(image)
    points = np.asarray(data["points"], dtype=np.float32)
    labels = np.asarray(data.get("labels") or [1] * len(points), dtype=np.int32)
    masks, scores, _ = predictor.predict(point_coords=points, point_labels=labels, multimask_output=False)
    mask = (masks[0] * 255).astype("uint8")
    output = Path(data["output_path"])
    output.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(mask).save(output)
    _result(output=str(output), score=float(scores[0]))


def musicgen(data: dict) -> None:
    import soundfile as sf
    from transformers import pipeline

    generator = pipeline("text-to-audio", model=data["model_dir"], device=-1)
    response = generator(data["prompt"], forward_params={"max_new_tokens": int(data.get("max_new_tokens", 256))})
    output = Path(data["output_path"])
    output.parent.mkdir(parents=True, exist_ok=True)
    sf.write(output, response["audio"].T, response["sampling_rate"])
    _result(output=str(output), sample_rate=response["sampling_rate"])


def qwen_vision(data: dict) -> None:
    from transformers import pipeline

    pipe = pipeline("image-text-to-text", model=data["model_dir"], device_map="auto")
    messages = [{"role": "user", "content": [
        {"type": "image", "url": str(Path(data["input_path"]).resolve())},
        {"type": "text", "text": data.get("prompt", "Mô tả chi tiết hình ảnh này.")},
    ]}]
    response = pipe(text=messages, max_new_tokens=int(data.get("max_new_tokens", 512)))
    output = Path(data["output_path"])
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(response, ensure_ascii=False, indent=2), encoding="utf-8")
    _result(output=str(output), result=response)


OPERATIONS = {
    "vieneu_tts": vieneu_tts,
    "kokoro_tts": kokoro_tts,
    "mlx_transcribe": mlx_transcribe,
    "faster_whisper_transcribe": faster_whisper_transcribe,
    "piper_tts": piper_tts,
    "florence_vision": florence_vision,
    "paddle_ocr": paddle_ocr,
    "depth_anything": depth_anything,
    "rembg_remove": rembg_remove,
    "realesrgan_upscale": realesrgan_upscale,
    "face_restore": face_restore,
    "sam2_segment": sam2_segment,
    "musicgen": musicgen,
    "qwen_vision": qwen_vision,
}


def main() -> int:
    operation, data = _payload()
    handler = OPERATIONS.get(operation)
    if handler is None:
        raise ValueError(f"unknown operation: {operation}")
    handler(data)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(json.dumps({"error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False), file=sys.stderr)
        raise SystemExit(1)
