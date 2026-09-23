# Executive Producer — Health Infographic

## When to Use

Use this skill for narration-led health, nutrition, food-science, anatomy, or wellness explainers built from editorial imagery, diagrams, comparisons, data cards, and subtitles.

## Operating Contract

1. Load `pipeline_defs/health-infographic.yaml`, `styles/health-editorial.yaml`, and every stage director before executing that stage.
2. Run stages serially: `research → proposal → script → scene_plan → assets → edit → compose → publish`.
3. Treat research, claim wording, citations, disclaimers, runtime, provider, model, and budget as production decisions. Record changes in the decision log.
4. Never spend provider credit before the proposal gate is approved. Produce a 10–15 second sample before full paid asset generation unless the user explicitly declines after being advised.
5. Stop at every gated checkpoint. A health claim that lacks a source is a blocker, not a copy-edit issue.
6. A reference video supplies pacing and visual grammar only. Do not copy its script, images, thumbnail, sequence, or distinctive layout.

## Cross-Stage Safety Checks

- Every factual narration section must carry `source_ref` into the script.
- Every diagram must preserve the evidence level: hypothesis, preclinical, observational, randomized trial, review, or official guidance.
- Never turn “may”, “associated with”, or “observed in animals” into “does”, “prevents”, or “treats”.
- Preserve the approved disclaimer and citation display through edit and compose.
- If evidence conflicts, show the uncertainty instead of selecting the most sensational claim.

## Quality Checklist

- Research is current, traceable, and appropriately qualified.
- The video remains understandable to the declared audience.
- Visuals explain mechanisms rather than decorate narration.
- Runtime, providers, costs, and rights are explicit.
- Final output passes playback, ffprobe, subtitle, citation, and disclaimer checks.
