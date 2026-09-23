# Edit Director — Health Infographic

## When to Use

Use to convert the approved scene and asset plans into deterministic edit decisions.

## Timeline Rules

- Cut to narration ideas, not every sentence. Give diagrams enough time to build and settle.
- Use restrained transitions and no rapid zooms on health imagery.
- Keep subtitles short, high-contrast, and clear of labels and citations.
- Hold citation footers for at least three seconds and the final disclaimer long enough to read.
- Duck music under narration and remove music where cautions or uncertainty need focus.
- Copy the approved `render_runtime` and `composition_mode` from the proposal unchanged.
- Copy `motion_intensity` from project intake into top-level `motionIntensity`; use per-cut `motion_intensity` only when a scene intentionally deviates.
- Use no more than three transition families. A strong effect is a punctuation mark, not the default cut.
- Keep the target rhythm near 20% strong motion, 60% medium motion, and 20% rest/reading scenes.

## Professional Motion Pack Contracts

- `mechanism_flow` requires `mechanismNodes` with 2–5 `{label, detail?, emphasis?}` entries.
- `evidence_ladder` requires `evidenceLevels` with 2–5 `{label, detail?, strength?, status?}` entries.
- `myth_reality` requires `myth` and `reality`; use `takeaway` only when the source supports it.
- `timeline_steps` requires `timelineSteps` with 2–6 `{label, detail?, time?}` entries.
- `ingredient_spotlight` requires `title`; use `ingredientImage` or `source`, plus up to four `facts`.
- Set `sourceLabel` for every scene that communicates a factual health claim.
- Map project intake ratio to the render profile: `16:9` → `youtube_landscape`, `9:16` → `youtube_shorts`, `1:1` → `instagram_feed`; pass that profile to `video_compose` without changing it silently.

## Quality Checklist

- No timeline gaps, overlaps, or missing assets.
- Claims, source refs, citations, and visuals align scene by scene.
- Subtitles and diagrams do not compete for the same space.
- The edit remains original relative to the reference.
- Runtime and budget decisions remain intact.
