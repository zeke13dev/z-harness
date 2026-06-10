# PLAN: Rewrite /z-test for System-Level Invariant Tests

**Plan slug:** `rewrite-z-test-invariants`
**Status:** plan — awaiting implementation
**Based on SPEC.md:** same directory

---

## Goals

1. Replace `/z-test`'s function-level structural test drafting with system-level invariant behavioral test drafting
2. Create `docs/INVARIANTS.json` + `docs/INVARIANTS.md` as permanent per-repo system-level invariant stores
3. Implement tag-based mapping from invariants to plan tasks (explicit `**Invariants:**` annotations + fuzzy discovery hints)
4. Implement hybrid fixture ownership: INVARIANTS.json declares schema + defaults, TESTS.md provides/overrides concrete values
5. Add multi-layer test organization (per-task + full-chain) with `layer:` field
6. Add CI-per-PR gate via `scripts/invariant-check.sh` and `/z-test --ci` flag
7. Evolve cross-LLM consult prompt to include INVARIANTS.json coverage analysis
8. Maintain full backward compatibility with v1 TESTS.md format
9. Bootstrap INVARIANTS.json via `/z-init-docs --invariants` with durability heuristic
10. Nudge `/z-plan` to promote durable SPEC.md invariants to INVARIANTS.json

---

## Non-goals

- Not writing or running actual test code (still done by /z-implement-all's implementer)
- Not modifying /z-plan's SPEC.md invariant syntax (`**INVARIANT:**` / `**MUST:**` lines stay)
- Not replacing the existing docs/llm/ memory system's per-concept invariants arrays
- Not adding a new subagent type (reuses consultant-primary + consultant-secondary)
- Not changing how tests are executed (still via test-runner.json + /z-implement-all step 7b)
- Not qt-bot specific — works for any codebase

---

## Decisions (with rationale)

**Consult-flagged decisions (5 of 12):** D1, D2, D4, D6, D7, D9. Consult completed in /z-plan Phase 3 (design-time consult on architecture).

**Non-consult decisions:** D3 (tag matching — hybrid, no schema change), D5 (tag taxonomy — reuse TAGS.txt), D8 (staleness detection — follows existing pattern), D10 (cross-LLM consult evolution — mechanical extension), D11 (multi-layer organization — local structural), D12 (model-degenerate — just another failure class). These are implemented as specified in SPEC.md without needing cross-LLM rationale.

**Two consult scopes:** (a) Design-time consult (/z-plan Phase 3) on architectural decisions D1-D9. (b) Execution-time consult (/z-test Phase 3) on drafted test cases — different scope, same mechanism.

### D1: INVARIANTS.md location — `docs/INVARIANTS.md` + `docs/INVARIANTS.json`
**Why:** Follows the proven two-tier docs pattern (human Markdown + machine JSON). Added to `docs/llm/INDEX.json` for doc-fetcher discoverability. Repo-global scope is correct for SYSTEM-level invariants (cross-cutting truths, not per-plan implementation details).
**Rejected:** Single-file (harder to parse), `.z-harness/` (hidden, less discoverable), inside docs/llm/ namespace (different abstraction level — per-concept vs cross-cutting).

### D2: Invariant schema — 10 fields including optional fixture_schema + source
**Why:** `fixture_schema` is load-bearing for hybrid ownership and validation. `source` (from pre-reviewer) preserves provenance. `fixture_schema` and `fixture_defaults` are explicit optional to avoid burdening simple behavioral invariants. Severity drives CI gating.
**Rejected:** Minimal 4-field (no fixture validation, no staleness), Full with rationale/examples (bloat).

### D3: Tag matching — Hybrid (explicit primary, fuzzy hint)
**Why:** Explicit `**Invariants:**` annotations in TASKS.md are the ground truth — zero ambiguity. Fuzzy matching on task descriptions + tag keywords is a discovery aid to catch missed matches. Both surfaced for user approval.
**Rejected:** Explicit-only (plan author burden), fuzzy-only (false positives/negatives).

### D4: Fixture ownership — INVARIANTS.json schema + defaults, TESTS.md overrides
**Why:** Defaults prevent vacuous fixtures when plan authors don't know domain values. Schema validation ensures TESTS.md `fixture:` satisfies constraints. Guardrail: fixture_schema must have ≥1 non-trivial constraint (minimum, non-zero, etc.) to prevent trivial pass-through.
**Rejected:** Schema-only (risk of trivial placeholders), TESTS-only (invariants can't carry defaults).

### D5: Tag taxonomy — Reuse TAGS.txt + free-text failure_class
**Why:** TAGS.txt (15 controlled tags) is already established and test-relevant. `failure_class` is a free-text field for the invariant's specific bug class — no new taxonomy needed.
**Rejected:** New test-specific taxonomy (overlaps with failure_class, adds maintenance burden).

### D6: TESTS.md format — v2 with Invariant ID, optional quote, fixture, layer
**Why:** `**Invariant ID:**` is a stable, machine-verifiable traceability link to INVARIANTS.json. `**Invariant:**` quote retained as optional for SPEC-only invariants during bootstrap. `**Fixture:**` inline JSON enables schema validation. `**Layer:**` separates per-task from full-chain. `version: 2` frontmatter enables backward compatibility.
**Rejected:** Drop quote entirely (breaks traceability during bootstrap — pre-reviewer catch), keep-only format (doesn't add stable ID).

### D7: Bootstrapping — /z-init-docs --invariants + /z-plan nudge
**Why:** `/z-init-docs --invariants` scans existing SPEC.md files for durable invariants (multi-plan OR cross-module heuristic). `/z-plan` nudge is gated on INVARIANTS.json existence + non-match + durability signal — prevents spamming.
**Rejected:** Manual-only (most repos won't bother), gradual prompting only (too slow, no bulk bootstrap).

### D9: CI gate — scripts/invariant-check.sh + --ci flag
**Why:** Standalone script reads INVARIANTS.json + TESTS.md, runs tests, exits non-zero on mandatory-invariant violations. `--ci` flag emits machine-readable JSON. CI config is repo-specific and out of scope.
**Rejected:** /z-review-all hook (tied to harness, not CI-portable), --ci only (no script, harder for CI to run).

---

## Approved shortcuts

None. All decisions resolve to robust long-lasting solutions. No temporary workarounds accepted.

---

## Implementation phases (ordered)

### Phase A: INVARIANTS.json schema + validation (repo infrastructure)
Define the 10-field invariant schema (SPEC.md Section 1), implement write-time validation in the /z-init-docs extension (Phase B), and add the validation module consumed by both /z-init-docs and /z-test. This phase produces reusable code (schema constant, validate function), not a per-repo file.

### Phase B: /z-init-docs extension (bootstrap)
Add `--invariants` flag. Uses Phase A's schema + validation to create and populate `docs/INVARIANTS.json` from existing SPEC.md files. This is the first consumer of the Phase A infrastructure.

### Phase C: /z-test rewrite
Complete rewrite of skills/z-test/SKILL.md and commands/z-test.md. New phases: load INVARIANTS.json, tag-based matching, behavioral test drafting, fixture validation, v2 TESTS.md output, evolved cross-LLM consult.

### Phase D: Consumer updates
Update /z-implement-all (v2 TESTS.md parsing), /z-review-all (full-chain test execution), /z-maintain-docs (INVARIANTS.json staleness).

### Phase E: /z-plan nudge
Add invariant promotion nudge to /z-plan Phase 6.

### Phase F: CI gate
Create scripts/invariant-check.sh, add --ci flag to /z-test.

### Phase G: Exports + docs
Regenerate all export prompts. Update INDEX.json. Copy to .agent/ directory.

---

## DRY / KISS / SOLID compliance

- **DRY:** INVARIANTS.json is the single source of truth for system invariants. TESTS.md is generated output, not manually maintained. SPEC.md invariants are plan-scoped, not duplicated.
- **KISS:** Each invariant is a simple JSON object with 10 fields. No abstract test framework, no plugin system. Tag matching is a string comparison, not an ML classifier. Fixture validation is JSON Schema, a standard.
- **SOLID:**
  - **Single responsibility:** INVARIANTS.json stores invariants. /z-test drafts tests. /z-implement-all implements them. invariant-check.sh gates.
  - **Open/closed:** INVARIANTS.json is open for adding new invariants but closed for modifying existing IDs. TESTS.md v2 extends v1 without breaking it.
  - **Liskov substitution:** v2 TESTS.md entries are substitutable for v1 in consumer code (consumers read version field, branch).
  - **Interface segregation:** INVARIANTS.json's fixture_schema is optional — behavioral invariants don't pay the complexity cost of schemas.
  - **Dependency inversion:** /z-test depends on INVARIANTS.json (abstraction), not on specific INVARIANTS.json entries (details).

---

## Risk register

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| INVARIANTS.json becomes stale/outdated | Medium | High | Staleness detection via source_files mtime; /z-maintain-docs coverage |
| Plan authors don't annotate `**Invariants:**` in TASKS.md | High | Medium | Fuzzy matching as discovery aid; /z-plan nudge |
| Default fixtures create false confidence | Medium | High | Schema must have ≥1 non-trivial constraint; validation at /z-test Phase 4 |
| Bootstrap imports ephemeral invariants | Medium | Low | Durability heuristic (≥2 plans OR cross-module) filters candidates |
| CI gate is too strict (flaky tests block PRs) | Low | Medium | Severity grading (blocker halts, major warns, minor info); invariant-check.sh returns distinct exit codes |
| Migration of existing TESTS.md artifacts | Low | Low | Version field enables backward compat; v1 is inert (no migration needed) |
