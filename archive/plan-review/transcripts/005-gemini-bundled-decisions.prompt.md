MODE: bundled-decisions

## Context

This is a decisions-bundle consult for the z-harness project. The plan is to enrich z-harness two-tier docs system with curated "memories" + ripgrep lookup augment. The orchestrator has already locked these constraints:
- Ship blind without dogfooding z-harness's own docs
- /z-suggest-memory is mandatory in /z-debug and /z-improve retros
- Keep existing invariants/gotchas short-string fields alongside the new memories array (no Gemini-style deprecation)
- Memories are mutable (not append-only)

The chosen framing (Claude, from BRAINSTORM.md): memories array + SEARCH.txt flat file + grep second phase in doc-fetcher. The core insight is that authoring-burden is the primary failure mode — memories only accrue value if written at discovery time (during /z-debug post-mortems, /z-improve retros, /z-plan decisions logs).

---

## Decision Bundle

### D1. Memory JSON schema — fields + enums + source format

Options:
- (a) Codex shape verbatim: {type, text, source, date, tags}. type ∈ {anti_pattern, abandoned_path, incident, performance_trap, decision_rationale, open_question}. source = strict-prefix string (incident:<slug> | spec:<plan-slug>/<run-id> | debug:<run-id> | human_review:<name>). text ≤ 200 chars.
- (b) (a) + confidence: high|medium|low field.
- (c) Same as (a) but source is structured object {kind: enum, ref: string}.
- (d) (a) + optional expires: YYYY-MM-DD for author-set decay date.

**Tentative call:** (a) + (d). Strict-prefix source is ripgrep-parseable without JSON. Confidence is implicit in source kind. Optional expires is cheap insurance.

### D2. Tag taxonomy

Options:
- (a) Controlled set (~15): correctness, perf, data-quality, schema, time-window, units, api-boundary, retry-loop, race-condition, dependency, deprecation, lossy-default, ux, observability, compliance.
- (b) Free-form, no validation.
- (c) Hybrid: controlled set as recommended chips, free-form allowed.
- (d) Per-repo TAGS.txt file.

**Tentative call:** (c) Hybrid. Pure-controlled is wrong on day one for any specific repo; pure free-form gets noisy.

### D3. MEMORIES-FLAT.md line format

Options:
- (a) `## <concept-slug>` heading per concept, lines `[<TYPE> <DATE>] <text> (tags: ...)`.
- (b) JSON-Lines: `{"slug":...,"type":...,"date":...,"text":...,"tags":[...]}`.
- (c) Pipe-delimited: `<slug> | <type> | <date> | <tags> | <text>`.
- (d) Per-line slug prefix: `[<slug>] [<TYPE> <DATE>] <text> (tags: ...)`. No nested headings; every match line self-contained.

**Tentative call:** (d). Eliminates the need for ripgrep -B context; every match line parseable in isolation.

### D4. doc-fetcher second-phase contract

Options:
- (a) Reuse existing `query` parameter only.
- (b) Add optional `memory_query` parameter.
- (c) Add optional `tags` parameter.
- (d) (a) + (c): reuse query by default, accept optional tags.
- (e) Add `memories_only: bool` for retro callers.

**Tentative call:** (d). Backward-compatible; tags hint for precision callers; memories_only deferred.

### D5. /z-suggest-memory target-concept resolution

Options:
- (a) Caller MUST pass `concept: <slug>` explicitly.
- (b) Skill prompts user with multi-select over all INDEX.json concepts.
- (c) Skill auto-detects from calling context (PROBLEM.md `relevant_concepts`, etc.) and asks user to override.
- (d) Caller passes `concept_hints: [<slug>...]`; skill pre-selects hints in AskUserQuestion.

**Tentative call:** (d). /z-debug and /z-improve already have hint sources; user confirmation is one click for the common case.

---

## Task

For each decision (D1–D5):

1. **Name one concrete failure mode** of the tentative call.
2. **Identify any interaction** with other decisions in this bundle.
3. **Recommend the option** you'd actually ship, with reasoning.

Be concise — this is a bundled review, not a per-decision essay.
