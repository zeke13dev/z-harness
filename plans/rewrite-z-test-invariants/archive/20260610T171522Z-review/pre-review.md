# Pre-review summary — rewrite-z-test-invariants
Run: 20260610T171522Z-review

## Pre-review 1 — correctness & spec drift

### Blockers
- **exports/pi/prompts/z-test.md not regenerated** — Zero references to INVARIANTS.json, invariant_id, fixture_schema, or Phase 0 Discovery. Still has old "Phase 0 — Slug discovery + plan sanity check" body. SPEC section 12 explicitly requires regeneration from the rewritten skill.
- **exports/codex/prompts/z-test.md not regenerated** — Same problem as pi export. Still old format. SPEC section 12 explicitly requires this regeneration.
- **exports/agy/prompts/z-test.md only partially updated** — Frontmatter description was updated, but the body (Phase 0 onward) still uses the old format ("Slug discovery + plan sanity check") without INVARIANTS.json loading logic. SPEC section 12 requires full regeneration.

### Major
- **Missing exit code 1 in validate-invariants.py** — SPEC T002 requires distinct exit codes: 0=valid, 1=schema error, 2=constraint violation, 3=IO error. The script never returns exit code 1 (only 0, 2, 3). All non-IO structural errors are folded into exit code 2. This breaks downstream consumers that branch on exit code 1.
- **Top-level `generated_at` field not validated** — SPEC requires INVARIANTS.json top-level structure to have `version`, `generated_at`, `invariants`. The schema file covers per-entry fields only. The validator checks `version` and `invariants` but does **not** validate `generated_at` presence/format.

## Pre-review 2 — spec gaps & edge cases

### Blockers
- **`docs/INVARIANTS.json` and `docs/INVARIANTS.md` do not exist.** SPEC Sections 1 & 2 define these as foundational artifacts; T005 lists them as done. Without INVARIANTS.json, /z-test always falls back to legacy v1 mode, the /z-plan nudge never fires, invariant-check.sh always exits 4 (I/O error), and every skill that references INVARIANTS.json describes an unreachable code path.

### Major
- **/z-test Phase 8 writes actual test code, contradicting the core design principle.** The skill's opening lines state "It does NOT write or run any test code" but Phase 8 spawns a Python script that writes test files. This crosses the planning/implementation boundary delegated to /z-implement-all (T010).
- **Chicken-and-egg bootstrap problem.** /z-init-docs --invariants needs SPEC.md files to find invariants. /z-plan's nudge needs INVARIANTS.json to exist. A repo with no plans never gets INVARIANTS.json.
- **/z-plan nudge (T013) can pollute INVARIANTS.json with non-durable invariants.** The nudge's durability check is weaker than /z-init-docs --invariants (which requires multi-plan evidence). Plan-specific ephemeral invariants can be promoted into the permanent store.
- **Staleness detection covers INVARIANTS.json but not the SPEC.md fallback.**
- **No combinatorial guard on fixture_schema.** One invariant with multiple optional fields could consume 10+ draft slots with combinatorial fixture variants.

## Pre-review 3 — code quality & structural issues

### Blockers
- None clear-cut.

### Major
- **scripts/validate-invariants.py — Hand-rolled JSON Schema validator** (~70 lines of fragile custom logic). `validate_fixture_against_schema` reimplements schema keywords without a library. Missing keywords silently pass. `format: date-time` on `last_updated` is defined in the schema but never validated.
- **Duplicate atomic write idiom in 4+ files.**
- **Redundant awk-based TESTS.md parsing in 3 separate locations** (implement-all, review-all, invariant-check.sh).
- **94 files changed, 13,574 diff lines in exports/** for ~5-file conceptual change. Consider symlink or single-source-of-truth approach.
- **Fragile `load_tags()` section-detection** — blank-line intolerant parsing.

**VERDICT:** BLOCKERS_FOUND, MAJORS_FOUND
