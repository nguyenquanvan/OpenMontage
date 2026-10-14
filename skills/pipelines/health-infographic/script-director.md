# Script Director — Health Infographic

## When to Use

Use after proposal approval to write the narration and on-screen information plan for a health infographic video.

## Structure

Build a clear arc: surprising but accurate hook → define the question → explain the mechanism → compare conditions/forms → interpret human evidence → practical, cautious takeaway → disclaimer. Target about 130–150 spoken words per minute and leave breathing room for diagrams and citations.

## Claim Discipline

- Every factual section must set `source_ref` to a claim ID or direct source in the research brief.
- Preserve qualifiers exactly. Prefer “may”, “was associated with”, or “in this study” when evidence requires it.
- State whether evidence is in humans, animals, cells, or chemical analysis.
- Avoid diagnosis, prescriptions, personalized dosage, guaranteed outcomes, fear, and miracle language.
- If the title/hook is strong, the body must immediately narrow it to what the evidence actually shows.

## Own Script Mode (Kịch bản có sẵn)

When the brief says `Kịch bản có sẵn: có — inputs/own-script.md ...`, assemble the user's text instead of writing:

- `sections` are the script's paragraphs in their original order and `text` is each paragraph verbatim. Do not rewrite, shorten, reorder, or merge; add only `pronunciation_guides`, `delivery_cues`, and overlay suggestions.
- Each section's `source_ref` is always the `claim_id` of its matrix row — also for rows whose `status` is `unverified`, so the reason stays reachable. Every unverified sentence goes into `metadata.unverified_claims` as `{section_id, claim_id, sentence, reason}`. Do not delete or soften them.
- The narration language is the script's language; the "Ngôn ngữ" field only shapes subtitles and metadata.
- `total_duration_seconds` and section timings derive from the text: `len(text.split())` words at about 140 words per minute, not from the "Thời lượng" field.
- Append the educational-use disclaimer as a final section only when the script has none.
- For `health-chalkboard`, each scene's chalk sentence is drawn from the script's own sentences (a clause of one when it exceeds 14 words), never newly written.

## Voice and Captions

Write conversational sentences, pronunciation guides for scientific terms, purposeful pauses before comparisons, and short overlay text rather than duplicating full narration. End with an educational-use disclaimer and, where relevant, a prompt to consult a qualified clinician.

## Quality Checklist

- Word count matches the approved duration within 10%.
- Every claim is traceable and safely worded.
- The hook does not overstate the conclusion.
- Scientific terms are explained once in plain language.
- Disclaimer and citations are part of the timed script.
