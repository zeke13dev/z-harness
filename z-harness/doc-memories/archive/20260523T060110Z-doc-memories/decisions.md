# Phase 2 — Decisions

13 decisions enumerated. 5 flagged for cross-LLM consult (at the bundle cap).

## D1. Memory JSON schema — fields + enums + source format

**Consult? YES** — public-ish surface (every doc-updater output, every doc-fetcher input, every /z-suggest-memory write). Hard to rename later. Rule trigger: "names something on a public surface", ">1 module affected", "wire format".

**Options:**
- (a) Codex shape verbatim: `{type, text, source, date, tags}` with `type ∈ {anti_pattern, abandoned_path, incident, performance_trap, decision_rationale, open_question}` and `source` as strict-prefix string (`incident:<slug>` / `spec:<plan-slug>/<run-id>` / `debug:<run-id>` / `human_review:<name>`). `text ≤ 200 chars`.
- (b) Same but add `confidence: high|medium|low` per Codex risk-mitigation suggestion. One extra field; aligns with existing per-concept `confidence`.
- (c) Same as (a) but `source` is structured object `{kind: enum, ref: string}` instead of prefix-string. Cleaner for parsing; verbose.
- (d) Add `expires` optional `YYYY-MM-DD` field so memories can carry their own decay date (separate from the 18-month staleness flag).

**Tentative call:** (a) + (d). Strict-prefix source is parseable by ripgrep regex (`source: ?incident:` etc.) without JSON parsing. Confidence is bundled into `source` (an `incident:` memory is inherently higher-confidence than a `human_review:`). Optional `expires` is cheap insurance for memories the author knows will rot.

**Trigger:** public schema, multi-module impact.

## D2. Tag taxonomy

**Consult? YES** — wide impact (ripgrep query construction, /z-suggest-memory UX, /z-maintain-docs flagging). Hard to migrate later if free-form tags get sprawled. Rule trigger: "names something on a public surface", "reversibility >1hr".

**Options:**
- (a) Controlled small set (~15 tags) curated upfront: `correctness, perf, data-quality, schema, time-window, units, api-boundary, retry-loop, race-condition, dependency, deprecation, lossy-default, ux, observability, compliance`. /z-suggest-memory enforces — rejects free-form additions.
- (b) Free-form, no validation. Authoring is frictionless; ripgrep queries get noisy.
- (c) Hybrid: small controlled set as recommended chips, but free-form allowed. Best of both; allows organic taxonomy growth.
- (d) Per-repo taxonomy file at `docs/llm/TAGS.txt`. Each repo defines its own. Heavy for a small repo.

**Tentative call:** (c) Hybrid. Codex's risk doc explicitly says "controlled tag taxonomy" but the BRAINSTORM also flags it as "deferred to /z-plan Phase 2". A pure-controlled set will be wrong on day one for any specific repo; pure free-form gets noisy. Hybrid lets /z-suggest-memory show the recommended chips first while permitting overrides.

**Trigger:** API surface, multi-module impact, reversibility low.

## D3. MEMORIES-FLAT.md line format

**Consult? YES** — this is the ripgrep target. The format IS the contract. Future doc-fetcher logic depends on it being grep-friendly. Rule trigger: "wire format", "names a public surface".

**Options:**
- (a) Codex format: `## <concept-slug>` block per concept, then one line per memory `[<TYPE> <DATE>] <text> (tags: t1, t2)`. Readable; grep matches the bracket-prefix.
- (b) JSON-Lines: one line per memory `{"slug":"...","type":"...","date":"...","text":"...","tags":[...]}`. Machine-precise; grep still works on string contents.
- (c) Pure flat per-line: `<slug> | <type> | <date> | <tags> | <text>`. Pipe-delimited; trivial to parse with `awk` or `rg --json` fallback.
- (d) (a) + per-line concept-slug prefix: `[<slug>] [<TYPE> <DATE>] <text> (tags: ...)`. No nested headings; every line carries its own slug → ripgrep returns are self-contained without `-B` context lookups.

**Tentative call:** (d). Without per-line slug, ripgrep returns require `-B <n>` context to find which `## <concept-slug>` block the hit belongs to. (d) eliminates that — every match line is parseable in isolation. Readable: a human can `cat` the file and scan. Backward-compatible with a future JSON-Lines version (line-prefix is preserved).

**Trigger:** wire format.

## D4. doc-fetcher second-phase contract

**Consult? YES** — public agent contract. Affects every caller of doc-fetcher. Rule trigger: "defines public API".

**Options:**
- (a) Reuse the existing `query` parameter; doc-fetcher splits its own logic across INDEX.json substring + MEMORIES-FLAT.md ripgrep. Caller sees no change.
- (b) Add optional `memory_query` parameter; if absent, derive from `query`. Backward-compatible; future callers can search memories independently of code.
- (c) Add optional `tags` parameter for callers who already know which tags they want. Most precise; pushes complexity to caller.
- (d) (a) + (c): reuse `query` by default, also accept optional `tags` for precision callers.
- (e) Add `memories_only: bool` parameter for retro callers (/z-debug post-mortem might want "what memories exist for this slug?" without code grounding).

**Tentative call:** (d). Reuse `query` keeps the common case unchanged. Optional `tags` lets /z-suggest-memory and future precision callers narrow the ripgrep. `memories_only` is a feature we can defer — current callers don't need it.

**Trigger:** public API.

## D5. /z-suggest-memory target-concept resolution

**Consult? YES** — UX-defining. Wrong default makes the skill unusable. Rule trigger: "reversibility >1hr" if we ship the wrong default.

**Options:**
- (a) Caller (e.g. /z-debug) MUST pass `concept: <slug>` explicitly. Skill rejects otherwise. Forcing function for the caller to think about scope.
- (b) Skill prompts user via AskUserQuestion with all concepts from INDEX.json (multi-select). Slow but explicit.
- (c) Skill scans the calling context (PROBLEM.md / FIX.md / improvements doc) for `docs touched` / `relevant_concepts` hints, defaults to those, lets user override. Smart default; mild magic.
- (d) Caller passes `concept_hints: [<slug>...]` (zero or more); skill confirms via AskUserQuestion with hints pre-selected. Caller does the heavy lifting; user verifies.

**Tentative call:** (d). /z-debug already has PROBLEM.md "relevant_concepts" hints; /z-improve already names target files. Both can produce concept_hints cheaply. User confirmation via pre-selected AskUserQuestion is one click for the common case, fully overridable for the edge case.

**Trigger:** UX-defining default.

---

## Non-consult decisions (5 + 8 obvious calls)

### D6. Ripgrep availability — soft dependency with substring fallback.
Per BRAINSTORM. doc-fetcher checks for `rg` on PATH; if absent, falls back to case-insensitive substring scan of MEMORIES-FLAT.md (slower but functional). One-line check; reversible.

### D7. 18-month staleness threshold — env-overridable.
`Z_HARNESS_MEMORY_STALE_DAYS` (default 547 days ≈ 18 months). /z-maintain-docs surfaces stale memories in dry-run preview; never auto-deletes.

### D8. MEMORIES-FLAT.md regeneration triggers.
Regenerated by: (i) /z-init-docs Phase 4 (initial creation, possibly empty), (ii) /z-maintain-docs Phase 4 (after apply), (iii) /z-suggest-memory itself after writing a new memory. Always full regen from all `docs/llm/<slug>.json` (no incremental — file is small enough).

### D9. Two-tier sync mechanism.
LLM tier is authoritative. doc-updater reads `docs/llm/<slug>.json` `memories[]` and writes a `## Memories` section into `docs/human/<slug>.md`, formatted as a markdown list with date + type prefix. Human edits to the markdown section are NOT round-tripped back — humans wanting to add a memory use /z-suggest-memory (which writes the LLM tier).

### D10. /z-suggest-memory return shape.
```
STATUS: ok | skipped | bad_input
CONCEPT: <slug>
MEMORIES_WRITTEN: <N>
WROTE: docs/llm/<slug>.json
       docs/llm/MEMORIES-FLAT.md
```
Caller (/z-debug, /z-improve) logs this in its run telemetry but does not block on it.

### D11. Acceptance / testing strategy.
Per Phase 0 user decision (ship blind, dogfood later). Unit-level acceptance:
- doc-updater fixture test: feed it a synthetic source file + concept JSON with memories[]; assert output JSON preserves memories and human markdown contains `## Memories` block.
- doc-fetcher fixture test: synthetic MEMORIES-FLAT.md + INDEX.json; assert ripgrep hit returns concept slug; assert substring fallback works when PATH lacks `rg` (via `env -i PATH=/usr/bin`).
- No end-to-end against a real docs/llm/; manual validation in qt-bot post-merge.

### D12. Memory text length limit.
200 chars per Codex spec. Enforced by /z-suggest-memory at write time (rejects longer text, asks user to trim).

### D13. Memory mutation policy.
Memories are NOT append-only (per user choice — rejected Gemini's append-only ledger). /z-suggest-memory can edit or delete an existing memory via flag (`--edit <index>`, `--delete <index>`). Default mode is append. /z-maintain-docs flags old memories for human review but does not auto-delete.
