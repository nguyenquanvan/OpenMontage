# Proposal Director — Health Infographic

## When to Use

Use after research to propose three differentiated health-explainer concepts and lock production decisions before any paid generation.

## Proposal Requirements

For each concept provide: hook, audience promise, structure, visual grammar, disclaimer strategy, citation strategy, duration, narration architecture, provider/model options, itemized cost, and an honest limitation. Keep the reference video's useful grammar—calm narration, editorial layouts, ingredient photography, mechanism diagrams, comparisons—but create an original sequence and viewpoint.

## Composition Runtime Gate

Query `video_compose.get_info()["render_engines"]`. When both are available, **present both** Remotion and hyperframes to the user before locking `render_runtime`:

- Remotion: strongest fit for reusable stat cards, charts, comparisons, subtitles, and deterministic long-form rendering.
- HyperFrames: strongest fit for bespoke HTML/CSS/GSAP editorial layouts and kinetic typography.

Do not silently default. Recommend one, wait for approval, then write a `render_runtime_selection` decision with the approved `render_runtime`. Also lock `composition_mode` (`templated` or `atelier`).

## Chalkboard Style (`health-chalkboard`)

When the project's style playbook is `health-chalkboard`, every scene is a chalk drawing on a dark board with one chalk sentence. Lock the chalk text mode in the proposal and log it as `decision_log` `category: "playbook_selection"`, `subject: "Chalk text mode"`:

- `overlay` (default, recommend first): the image tool draws text-free chalk drawings and the Remotion `chalk_scene` writes the sentence. Free with local `comfyui_image`, spelling is always right, and Vietnamese diacritics render correctly.
- `in_image`: `google_imagen` (`gemini-2.5-flash-image`) or `openai_image` draws the sentence on the board itself. Closest to text-in-picture references, but costs every image (about 0.04–0.05 USD each), can misspell, and is unreliable with Vietnamese diacritics. Offer it only for English narration.

For English narration recommend the local `kokoro_tts` voice `am_michael` (Apache-2.0, free) at speed 0.95. Budget one image per 8–15 seconds of narration. `chalk_scene` exists only in Remotion, so recommend Remotion with `composition_mode: "templated"` for this style and say why when presenting both runtimes.

## Own Script Mode (Kịch bản có sẵn)

When the brief says `Kịch bản có sẵn: có — inputs/own-script.md ...`, do not generate concepts: the narration, its structure, and its duration (word count at about 140 words per minute) are fixed. Still present and lock everything else — both composition runtimes and `composition_mode`, image and TTS providers and voice, chalk text mode when the style is `health-chalkboard`, music plan, disclaimer text, citation display, and itemized cost. The 10–15 second sample uses the script's opening sentences, read verbatim. List the research rows marked `unverified` so the user sees which sentences still lack a source before approving spend. The `proposal_packet` schema still needs three `concept_options`: write three that share the script verbatim (hook = its opening sentence, structure = its paragraphs) and differ only in visual approach, provider path, and cost, so the user chooses by cost and look, never by rewriting.

## Approval Packet

- Present at least one low-cost/local path and one quality-first path when available.
- Name every paid provider and estimated usage. Do not call it yet.
- Include a 10–15 second sample plan: hook, one mechanism visual, actual voice, subtitle, citation, and music bed.
- Include the exact educational-use disclaimer text for approval.
- Record how health claims will be sourced on screen and in the description.

## Quality Checklist

- Concepts differ by insight and structure, not just title.
- Runtime, authoring mode, provider/model, cost, and rights are explicit.
- Medical safety and citation presentation are part of the creative design.
- Approval remains pending until the user chooses a concept and budget.
