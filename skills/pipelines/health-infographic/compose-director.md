# Compose Director — Health Infographic

## When to Use

Use to render the approved health infographic edit and perform final technical and editorial QA.

## Runtime Routing

Read `edit_decisions.render_runtime` and route without substitution. For `remotion`, use the scene-component stack for text, images, comparisons, charts, citations, subtitles, and audio. For `hyperframes`, run HyperFrames doctor/lint/validate before rendering the approved workspace. If the locked runtime fails, surface a blocker and request approval before changing it.

## Render and QA

1. Render the locked composition at the selected media profile.
2. Mix narration, optional music, and restrained effects; verify no clipping and intelligible speech.
3. Probe the output with ffprobe and inspect representative frames from hook, mechanism, comparison, evidence, and disclaimer sections.
4. Check text overflow, citation legibility, subtitle safe areas, chart labels, visual-source alignment, and pronunciation against the transcript.
5. Write `render_report` and `final_review`; do not hide warnings.
6. Inspect at least one frame from every Professional Motion Pack scene type used and verify transitions at the scene boundaries.

## Quality Checklist

- Output is playable and within duration/resolution tolerance.
- `render_runtime` matches the approved proposal; HyperFrames is never used as a silent fallback.
- Narration, visuals, subtitles, citations, and disclaimer remain synchronized.
- No broken text, black frames, missing assets, or audio clipping exists.
- Final review lists any claims that still require human medical review.
- Professional Motion Pack scenes render without missing labels, clipped cards, or excessive motion; transition families stay within the approved limit.
