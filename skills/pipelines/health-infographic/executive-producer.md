# Executive Producer — Health Infographic

## When to Use

Use this skill for narration-led health, nutrition, food-science, anatomy, or wellness explainers built from editorial imagery, diagrams, comparisons, data cards, and subtitles.

## Operating Contract

1. Load `pipeline_defs/health-infographic.yaml`, `styles/health-editorial.yaml`, and every stage director before executing that stage.
2. Run stages serially: `research → proposal → script → scene_plan → assets → edit → compose → publish`.
3. Treat research, claim wording, citations, disclaimers, runtime, provider, model, and budget as production decisions. Record changes in the decision log.
4. Never spend provider credit before the proposal gate is approved. Produce a 10–15 second sample before full paid asset generation unless the user explicitly declines after being advised.
5. Stop at every gated checkpoint. A health claim that lacks a source is a blocker, not a copy-edit issue.
6. A reference video supplies pacing and visual grammar only. Do not copy its script, images, thumbnail, sequence, or distinctive layout. When the reference analysis fails (no transcript, download blocked, missing tool), log a `fallback_decision` and continue with the style playbook's grammar; a failed reference analysis is never a blocker and never a reason to pause a gate.

## Own Script Mode (Kịch bản có sẵn)

Active when the brief says `Kịch bản có sẵn: có — inputs/own-script.md ...` and `<workspace>/inputs/own-script.md` exists, where `<workspace>` is the project directory named in the run prompt (in the desktop app it lives under the app's data folder, not the repository). Read that file before the research stage; it is the production's narration.

1. Stage order is unchanged. Each stage director has its own "Own Script Mode" section; the script gate still runs so the user confirms the split, the source refs, and the unverified list.
2. The user's text is the narration, verbatim. You may split it into sections, add pronunciation guides and delivery cues, and append the educational disclaimer when the text has none. You must not rewrite, shorten, reorder, merge, or "improve" sentences — not even to soften a claim. The narration language is the script's language; the "Ngôn ngữ" field then applies to subtitles and metadata only, and you say so once in the proposal when they differ.
3. Duration comes from the text: `len(text.split())` words at about 140 words per minute. Ignore the "Thời lượng" field; mention the gap once if it is large.
4. An unsupported claim is never silently removed. Research marks its row `unverified`, the script collects it in `metadata.unverified_claims`, and the proposal, `final_review`, and publish summary list every entry so the user decides. This is how Operating Contract #5 is met in this mode. Under "Chạy thẳng đến video cuối" it is the one gate that still stops: when `metadata.unverified_claims` is not empty, write the script checkpoint as `awaiting_human` (with the script artifact) and end your turn, so the user decides before any spend.
5. Copy check, at the start of the first stage: when "Video tham khảo" is set, fetch its transcript with `transcript_fetcher` and compare the script's sentences against it after normalizing case, punctuation, and whitespace. If a large share — about a third or more — of the script's sentences appear in the reference transcript, write the current stage checkpoint as a blocker pause — `write_checkpoint(..., status="awaiting_human", artifacts={}, error="Kịch bản trùng lời thoại của video tham khảo")`, see "Blocker checkpoint" in the checkpoint protocol — and stop: end your turn. This stop applies even when the run was pre-approved ("Chạy thẳng đến video cuối"); that pre-authorization covers gates, not a copy of someone else's script. If the transcript cannot be fetched, say so in the research checkpoint and continue.

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
