# Phase 3 — Decisions final

## Cross-LLM verdict

Both consultants endorse the overall architecture but flag two concrete corrections plus several interaction risks. Gemini's biggest contribution is the stdout-pollution warning + the "memory parsing must be JSON, not grep MEMORIES-FLAT.md" pivot. Codex's biggest contribution is the **D2 hard constraint** (verified: `scripts/config.py:61` enforces `^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$` — hyphens are illegal) and the v1-scope pushback on D7.

## Per-decision final calls

### D1. Resolver entry point — extend `scripts/config.py resolve-question`
- **One reason it might be wrong:** `config.py` is currently slim and adding a 5-tier resolver + memory parser bloats it. Standalone module is conceptually cleaner.
- **Counter-pushback:** The 4-layer precedence ladder is the most expensive shared logic; duplicating it would create two sources of truth. The bloat is real but bounded by D7 trim (see below).
- **Final call:** **Accept tentative — extend config.py.** Add stdout discipline: resolver subcommand writes JSON only to stdout; all logging/diagnostics route to stderr. Test gate: `python3 -m json.tool` on every resolver output succeeds.

### D2. Question_id naming + `[workflow]` namespace — **AMENDED**
- **Original tentative:** `workflow.audit-to-amend`, `workflow.slug-confirm` (hyphens).
- **Codex catch (verified):** `scripts/config.py:61` `_KEY_RE` rejects hyphens. Using hyphenated keys would require either patching the regex or running outside the validator — both bad.
- **One reason the underscore fix might be wrong:** Hyphens are more idiomatic in slug naming across z-harness (e.g. `workflow-preference`, `askuser-prefs-hook`). Mixing conventions is mildly ugly.
- **Counter-pushback:** TOML key conventions are settled; underscores everywhere is the lower-friction choice.
- **Final call:** **`workflow.audit_to_amend`, `workflow.slug_confirm`.** Underscores. Env transliteration becomes `Z_HARNESS_WORKFLOW_AUDIT_TO_AMEND`, `Z_HARNESS_WORKFLOW_SLUG_CONFIRM`.

### D3. Memory routing-preference schema — **AMENDED**
- **Original tentative:** Resolver greps `MEMORIES-FLAT.md`.
- **Gemini pivot (validated):** `MEMORIES-FLAT.md` is a derived artifact; parse the source JSONs directly.
- **One reason JSON parsing might be wrong:** Cross-slug memory enumeration requires walking every `docs/llm/<slug>.json` file. `MEMORIES-FLAT.md` is denormalized exactly for cheap reads.
- **Counter-pushback:** The walk is ~20 files at most; Python `glob` is microseconds. Type safety on `strength` and `question_id` enums is worth the file walk.
- **Final call:** **Schema accepted; parsing changes to JSON walk.** Resolver iterates `glob("docs/llm/*.json")`, filters for `memories[].type == "routing-preference"`, matches on `question_id`. Schema fields: `{type: "routing-preference", question_id, value, scope: "global"|"project", strength: "weak"|"strong"|"very_strong", reason, date}`.

### D5. resolve-question return contract — **EXPANDED**
- **Original tentative:** `{result, default, source, rule_id, strength}` JSON on stdout.
- **Codex expansion (accepted):** add `reason` (string from config or memory entry) and `sources[]` (list of source identifiers — supports the `conflict` case where two sources disagree).
- **One reason expansion might be wrong:** Wider envelope means more brittleness; consumers may forget to handle new fields.
- **Counter-pushback:** Phase 5 needs the data; better to ship the full envelope once than retrofit later.
- **Final call:** **JSON shape:** `{result, default, source, rule_id, strength, reason, sources}`. `sources` is a list; on `conflict` it has two entries with `{kind, value, location}` each. Exit codes: 0=ok, 2=bad payload, 3=unknown question_id, 4=io_error.

### D7. Memory strength heuristic — **DEFERRED-TO-USER (shortcut decision)**
- **Original tentative:** Explicit strength field on memory entry; user picks at write time. Full 5-tier resolver enabled including memory-based `very_strong → skip`.
- **Codex pushback:** v1 should ship config-only `hard|none` for the actual skip-decisions; design the memory schema (so `/z-suggest-memory` writes the right shape) but use memory **only for prefill** in v1, not for skip. Defer memory-based skip to v2 once enum validation, conflict detection, and the JSON-walk parser have shaken out.
- **One reason Codex might be wrong:** User explicitly picked "Full 5-tier from Codex framing" in Phase 0 gate. Trimming silently is not OK.
- **One reason Codex is probably right:** Implementing memory-based skip means: (a) JSON memory parser with type validation, (b) collision-check enforcement even when resolver returns `skip`, (c) conflict-detection logic between config and memory, (d) /z-suggest-memory write path for routing-preference type, (e) /z-suggest-memory detection-and-redirect (D4) — all in v1. That's a meaningful surface for a v1 ship.
- **Final call:** **Surface to user as Phase 5 shortcut decision.** Two paths:
  - **Path X (full 5-tier as picked):** ship memory-based `very_strong → skip` in v1. Heavier; ~13-15 tasks.
  - **Path Y (Codex trim):** ship config-only `hard|none` skip + memory-design-only (schema in place, /z-suggest-memory writes routing-preference, but resolver uses memory only for `prefill` not `skip` until v2). Lighter; ~10-11 tasks. The public schema is preserved.
- **Note:** Both paths ship the same memory schema (D3), the same return contract (D5), the same retrofit prose (D10). The only difference is whether the resolver acts on memory `very_strong` entries by skipping or only by prefilling.

## Cross-decision interactions (both consultants flagged)

- **D1 ↔ D5 (stdout discipline):** `config.py resolve-question` reserves stdout exclusively for JSON. All logging → stderr. Add a `python3 -m json.tool` validator test for this subcommand.
- **D2 ↔ D3 (question_id registry):** Single `QUESTION_IDS` dict in `config.py` is the source of truth for: (a) config-key validation, (b) /z-suggest-memory enum validation when writing routing-preference, (c) resolver lookup. Per Codex: `assert set(QUESTION_IDS) <= set(VALIDATORS)` at startup.
- **D7 ↔ collision checks:** Slug-confirm `very_strong → skip` does NOT bypass the slug-collision check inside skill prose. The resolver answers "should we ask?"; collision detection is orthogonal and unchanged. SPEC must spell this out explicitly.
- **D3 ↔ scope (Gemini):** Memory `scope: "global"` is read from any `docs/llm/<slug>.json` regardless of project; `scope: "project"` means "only when invoked under this project root." Resolver must know the current `Z_HARNESS_PROJECT_ROOT` to enforce.

## Premise-level concerns (consult-flagged)

- **Memory-vs-config user confusion (Gemini):** when config says X and memory says Y, the `conflict` tier surfaces the question but the user may not understand why. Add `--explain` flag (or `Z_HARNESS_EXPLAIN_RESOLUTION=1` env) to resolver that prints both sources verbatim. Not flagged for consult — internal UX.
- **Slug-derivation skip blast radius (Gemini):** even `very_strong → skip`, the collision check stays. Already captured above; SPEC will reinforce.

## Shortcuts surfaced for Phase 5 approval

- **Shortcut S1:** v1 ships Codex-trimmed memory-prefill-only (Path Y above) instead of full 5-tier memory-skip. Memory schema and write paths are present but resolver does not honor memory `very_strong` for skip; defers that to v2. Saves ~3-4 tasks of conflict-detection + collision-enforcement-around-memory-skip + integration tests.

## Non-consult decisions stand

- D4 (/z-suggest-memory redirect detection at Phase 3a)
- D6 (v1 inventory: audit→amend 2 sites + slug-confirm 7 sites)
- D8 (conflict tier always asks + shows sources)
- D9 (inherit existing 4-layer precedence; no new layer)
- D10 (explicit prose convention for retrofit)
- D11 (`askuser_resolved` event on every resolver invocation)
- D12 (extend existing `config` concept doc, not new)
- D13 (`Z_HARNESS_ASK_ALL=1` env var bypass)
