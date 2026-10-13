# Asset Director — Health Infographic

## When to Use

Use after scene approval to create narration, text-free visuals, diagrams, optional music, and citation data.

## Process

1. Read the approved provider/model and budget decisions. Never substitute providers silently.
2. Generate and approve a short voice sample before full narration when paid TTS is selected.
3. Generate images without embedded text, charts, labels, logos, or watermarks, except the chalk sentence in the chalkboard style's approved `in_image` mode. Keep anatomy plausible and non-sensational.
4. Build diagrams from verified relationships in the research brief. A visual arrow must not imply causation beyond the evidence.
5. Store provenance, prompt, model, license/rights status, cost, scene linkage, and `source_ref` in the asset manifest.
6. Probe every audio duration and send sections back for script revision when timing exceeds tolerance.

## Chalkboard Style (`health-chalkboard`)

- Prompt = the playbook's `image_prompt_prefix` + the scene's subject; negative prompt = the playbook's `image_negative_prompt`. Use a 16:9 image for landscape renders.
- `overlay` text mode: the drawing carries no words; the sentence lives in the `chalk_scene` cut.
- `in_image` text mode: remove markdown symbols (`*`, `#`, `_`, backticks) from the sentence, then add `Handwritten chalk text across the top of the board reads: "<sentence>"` to the prompt. View every generated image and compare its sentence letter by letter with the script; regenerate a mismatch up to twice, then flag that scene to the user instead of shipping it.
- Record `chalk_text_mode` and the exact sentence for every image in the asset manifest.
- Batch the work: draw images with `comfyui_image` `batch` (about 25 per call) and narrate every scene with one `kokoro_tts` `batch` call, instead of one tool call per scene. Look at every image afterwards; local FLUX schnell sometimes adds stray words, a frame, or a chalk tray, so redraw those with a new seed.

## Quality Checklist

- Narration is complete, correctly pronounced, and free of clipping.
- Visuals share the health-editorial palette and do not contain broken AI text.
- Diagrams match the claim evidence matrix.
- All files resolve on disk and costs stay within the approved cap.
- Human review occurs before composition locks assets.
