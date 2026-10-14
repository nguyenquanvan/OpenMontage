# Research Director — Health Infographic

## When to Use

Use at the research stage for any health, nutrition, ingredient, circulation, metabolism, or food-science topic.

## Source Hierarchy

Prefer, in order: government/public-health guidance; clinical guidelines; systematic reviews/meta-analyses; randomized controlled trials; well-designed observational studies; primary laboratory studies. Use news, blogs, forums, and the reference video only for audience questions or landscape context, never as the sole support for a health claim.

## Process

1. Translate the intake topic into answerable questions: population, exposure/intervention, comparator, outcome, and time horizon where applicable.
2. Search authoritative and primary sources. Record publication date, population, sample size, study type, limitations, and conflicts of interest when available.
3. Build `metadata.claim_evidence_matrix` with one row per candidate claim: `claim_id`, exact wording, source URL, evidence type, population, confidence, limitations, and safe wording.
4. Build `metadata.medical_safety_notes`: contraindications, interactions, vulnerable groups, dosage uncertainty, and when professional advice is appropriate.
5. For food chemistry, distinguish changes measured in compounds from proven changes in human outcomes.
6. Produce the normal schema-valid `research_brief`; use its data points and sources as the public evidence trail.

## Own Script Mode (Kịch bản có sẵn)

When the brief says `Kịch bản có sẵn: có — inputs/own-script.md ...`, the script, not the topic, sets the research questions:

1. Split `inputs/own-script.md` into sentences and build `metadata.claim_evidence_matrix` from them: one row per factual claim, quoting the sentence exactly so the script director can match it back. Skip greetings, transitions, and opinions that make no checkable claim.
2. Search the source hierarchy above for each row and fill source URL, evidence type, population, confidence, and limitations as usual. Set `status` to `supported` when a source backs the sentence as written.
3. Rows you cannot support get `status: "unverified"` and a `reason` (no source found, evidence contradicts the sentence, causal wording stronger than the evidence, dosage not in guidance). Never drop or reword the sentence; the user decides later.
4. `metadata.medical_safety_notes` is still required.
5. The `research_brief` schema still requires at least five sources. When the script carries fewer sourced claims, add guideline or background sources for its topic (they also feed the safety notes); never pad the list with the reference video.

## Rejection Rules

- Reject claims supported only by testimonials, affiliate pages, unsourced infographics, or AI summaries.
- Reject causal wording from observational evidence.
- Reject precise dosage or treatment instructions unless authoritative guidance directly supports them.
- Mark animal, cell, and mechanistic studies explicitly; never generalize silently to humans.

## Quality Checklist

- At least five reliable sources and three usable data points exist.
- Every planned health claim appears in the evidence matrix.
- Contradictions and uncertainty are visible.
- Sources are current enough for the topic and linked directly.
- The research brief contains no copied script from the reference video.
