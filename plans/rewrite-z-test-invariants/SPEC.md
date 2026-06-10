# SPEC: Rewrite /z-test for System-Level Invariant Tests

**Plan slug:** `rewrite-z-test-invariants`
**Status:** spec — awaiting implementation

## Planning Inputs

| Artifact | Path | generated_at |
|----------|------|--------------|
| BRAINSTORM.md | n/a — converged premise from interactive refinement | n/a |
| RESEARCH.md | absent | — |
| MAP.md | absent | — |

---

## Overview

Replace `/z-test`'s current function-level unit-test drafting (which catches nothing useful) with a system-level invariant-test framework. Instead of drafting per-function structural tests that always pass green, `/z-test` produces behavioral tests keyed to durable system invariants declared in a permanent per-repo `INVARIANTS.md` + `INVARIANTS.json`. Tests assert composed behavior ("fees moved correctly", "no look-ahead leakage") rather than structural proofs ("function was called"). A tag-based mapping connects invariants to tasks, hybrid fixture ownership separates schema (INVARIANTS.json) from values (TESTS.md), and multi-layer testing covers per-task + final-assembly.

## Design principles

- **DRY:** INVARIANTS.json is the single source of truth for system-level behavioral constraints. SPEC.md invariants are plan-scoped; TESTS.md is generated output.
- **KISS:** Each invariant declares `id`, `description`, `tags[]`, `failure_class`. No abstract test framework — concrete behavioral assertions.
- **SOLID:** INVARIANTS.json is open for extension (new invariants) but closed for modification (existing IDs are stable). TESTS.md consumption is versioned (v1 legacy, v2 new format).

---

## Files

### 1. `docs/INVARIANTS.json` (NEW — authoritative machine store)

**Purpose:** Permanent per-repo, cross-cutting system-level invariant declarations. The canonical source consumed by /z-test.

**Schema (per entry):**
```json
{
  "id": "inv_001",                          // stable, kebab-case, unique
  "description": "Fees are never silently dropped during feed processing",
  "tags": ["correctness", "data-quality"],
  "failure_class": "Silent fee drop — feed processes but fee field is zeroed or absent",
  "fixture_schema": {                       // OPTIONAL — JSON Schema shape
    "type": "object",
    "required": ["feed_records", "expected_fees"],
    "properties": {
      "feed_records": {"type": "array", "minItems": 1},
      "expected_fees": {"type": "object"}
    }
  },
  "fixture_defaults": {                     // OPTIONAL — only when fixture_schema present
    "feed_records": [{"price": 100.0, "fee": 0.5}],
    "expected_fees": {"total": 0.5}
  },
  "severity": "blocker",                    // blocker | major | minor
  "source_files": ["src/feed/processor.rs"],
  "last_updated": "2026-06-09T00:00:00Z",
  "source": "spec"                          // spec | plan | user-concern | code-review | axiom-derived
}
```

**Top-level structure:**
```json
{
  "version": 1,
  "generated_at": "<iso>",
  "invariants": [ ... ]
}
```

**Invariants:**
- `id`: stable kebab-case identifier. Must be unique. Never changes once created (rename = new ID + deprecate old).
- `description`: one-sentence system-level truth.
- `tags[]`: from controlled set in `docs/llm/TAGS.txt` (correctness, perf, data-quality, schema, time-window, units, api-boundary, retry-loop, race-condition, dependency, deprecation, lossy-default, ux, observability, compliance). At least one tag required.
- `failure_class`: one-line description of the real bug this invariant prevents. Phrased in domain terms, not code terms.
- `fixture_schema`: OPTIONAL JSON Schema describing the shape of test fixture data. If present, must include at least one constraint that prevents trivial pass-through (e.g., `minItems: 1`, `minimum: 1`, `not: {const: 0}`). Absent for pure behavioral invariants.
- `fixture_defaults`: OPTIONAL. Only valid when fixture_schema is present. Must satisfy fixture_schema. Provides fallback test values.
- `severity`: `blocker` (PR gate fail), `major` (PR gate warn), `minor` (informational).
- `source_files[]`: paths to source code this invariant derives from. Used for staleness detection (mtime vs last_updated).
- `last_updated`: ISO timestamp. Compared to source_files mtime for staleness.
- `source`: provenance enum. Where this invariant was mined from.

**Atomic writes:** tmpfile → flush → fsync → os.replace(). Same as docs/llm/ write discipline.

**Staleness:** /z-maintain-docs compares source_files max mtime to last_updated. /z-test re-checks at draft time.

**Validation at write time:**
- `id` uniqueness enforced
- `tags[]` subset of TAGS.txt
- `fixture_schema` validates `fixture_defaults` if both present
- `fixture_schema` if present must have ≥1 non-trivial constraint
- `severity` is valid enum value

---

### 2. `docs/INVARIANTS.md` (NEW — human-readable rendering)

**Purpose:** Generated Markdown rendering of INVARIANTS.json for human browsing and editing guidance.

**Content:** Auto-generated from INVARIANTS.json. Each invariant rendered as a Markdown section:
```markdown
## inv_001 — Fees are never silently dropped during feed processing
**Tags:** correctness, data-quality
**Severity:** blocker
**Failure class:** Silent fee drop — feed processes but fee field is zeroed or absent
**Source files:** src/feed/processor.rs
**Source:** spec (from SPEC.md)
```

**Regeneration:** On every INVARIANTS.json write, regenerate INVARIANTS.md. Same pattern as MEMORIES-FLAT.md regeneration.

---

### 3. `skills/z-test/SKILL.md` (REWRITE)

**Complete rewrite.** Current skill (per-task semantic test-case planner post-/z-plan) becomes:

**New `/z-test` phases:**

#### Phase 0 — Discovery
1. If repo has `docs/INVARIANTS.json`, load it. If absent, warn: "No INVARIANTS.json found — run /z-init-docs --invariants to bootstrap." Continue with SPEC.md invariants only (fallback to legacy mode).
2. Discover plan: same slug discovery as current (enumerate `$Z_HARNESS_PLAN_DIR/`, `--slug` arg).
3. Require SPEC.md + PLAN.md + TASKS.md. Abort if missing.
4. Implementation-underway warning: same as current.

#### Phase 1 — Load invariants + risk-rank
1. Load INVARIANTS.json → all invariants with tags, severities, fixture schemas.
2. Load SPEC.md → extract `**INVARIANT:**` / `**MUST:**` / `**MUST NOT:**` / `**DANGER:**` lines (fallback for invariants not yet in INVARIANTS.json).
3. For each task in TASKS.md:
   - If task has explicit `**Invariants:** inv_001, inv_003` line → direct match.
   - If no explicit line → fuzzy match: scan task description + acceptance criteria for tag keywords from invariants. Prefer exact tag matches; fall back to description substring matches. Present fuzzy matches as suggestions, not bindings.
   - Risk-rank: domain criticality (from SPEC.md severity tags), surface area (file count), test-gap signal.
4. Ask user: "What specific bug classes worry you most?" (same as current).

#### Phase 2 — Draft behavioral test cases
For each matched invariant + high-risk task + user concern:
```
- id: TEST-001
  task: T007
  invariant_id: inv_001                         # NEW — stable ID from INVARIANTS.json
  invariant: "Fees are never silently dropped"   # RETAINED — optional, for SPEC-only invariants
  invariant_description: "Feed processing must preserve all fee fields"
  test_name: feed_fee_preservation
  target_file: tests/test_feed_processor.py
  failure_class: "Silent fee drop — feed processes but fee field is zeroed or absent"
  layer: per-task                                # NEW — per-task | full-chain
  fixture:                                       # NEW — inline JSON satisfying fixture_schema
    feed_records: [{"price": 100.0, "fee": 0.5}]
    expected_fees: {"total": 0.5}
  assertion: "assert feed_output.total_fees == 0.5 for input with fee 0.5"
  seed: spec
  mandatory: yes
```

**Key format changes from current:**
- `invariant_id:` replaces `invariant:` as primary traceability (stable ID from INVARIANTS.json)
- `invariant:` retained as optional secondary (for SPEC-only invariants not yet in INVARIANTS.json)
- `invariant_description:` new field — one-line human-readable
- `layer:` new field — `per-task` or `full-chain`
- `fixture:` new field — inline JSON that satisfies the invariant's fixture_schema
- `version: 2` frontmatter on TESTS.md

**Behavioral assertion discipline:**
- Assert composed behavior: "output.total_fees == input.sum(fee)" not "process_feed() was called"
- Assert invariants hold across module boundaries: "strategy.position == pipeline.position after sync"
- Every assertion must name a specific failure class in domain terms
- Assertions must be observable (numeric, type-shape, or invariant on output)

#### Phase 3 — Cross-LLM consult (evolved)
Existing prompt extended with:
- "INVARIANTS.json (verbatim): <contents>" added
- New question: "Which INVARIANTS.json invariants have no corresponding test entry?"
- New question: "Which fixture values would expose a violation of invariant X?"
- Same per-draft critique, coverage-gap detection, trivial-drop identification
- Both consultant-primary + consultant-secondary dispatched in parallel

#### Phase 4 — Synthesize (same as current, with additions)
- Merge, dedupe, apply verdicts
- For fixture values: validate each entry's `fixture:` against its invariant's `fixture_schema` (if present). Reject entries that don't satisfy the schema.
- For uncovered invariants: propose draft entries for user approval in Phase 5.

#### Phase 5 — Present + approve (same as current)
- Add: "N invariants from INVARIANTS.json have no test coverage" if any uncovered.

#### Phase 6 — Write TESTS.md
New format header:
```markdown
# Tests for <slug>
**Run:** <RRUN>
**Version:** 2
**Status:** drafted (awaiting /z-implement-all)
**Invariants file:** docs/INVARIANTS.json
**Covered invariants:** inv_001, inv_003, inv_007
**Uncovered invariants (blocker):** inv_012
**Uncovered invariants (major):** inv_005, inv_009
```

#### Phase 7 — Cross-link into TASKS.md (same as current)

#### Phase 8 — Finalize (same as current)
- Add uncovered-invariant counts to finalize event.

---

### 4. `commands/z-test.md` (UPDATE)

Update the command frontmatter and description to reflect the new system-level invariant test scope. Keep runtime contract conformance table updated.

**New description:** "System-level invariant test planner. Reads INVARIANTS.json + SPEC.md + PLAN.md + TASKS.md, matches invariants to tasks via tag-based mapping, drafts behavioral tests keyed to durable system invariants, cross-LLM consult, writes versioned TESTS.md."

**New frontmatter fields:** `version: 2`

---

### 5. `scripts/invariant-check.sh` (NEW)

**Purpose:** CI-friendly script that reads INVARIANTS.json + TESTS.md, runs the test suite, and exits non-zero on mandatory-invariant violations.

**Behavior:**
1. Parse `TESTS.md` frontmatter for `**Covered invariants:**` and `**Uncovered invariants (blocker):**`
2. If any uncovered blocker invariants → exit 2 (invariant coverage gap)
3. Run the test suite (via `test-runner.json` or default pytest/cargo test)
4. Parse test output for TEST-NNN results
5. For each failed mandatory test → log invariant ID + failure class
6. Exit 0 if all mandatory tests pass; exit 1 if any mandatory test fails

**--ci flag on /z-test:** Emit a machine-readable JSON summary consumable by CI:
```json
{
  "status": "pass|fail|coverage_gap",
  "covered_invariants": ["inv_001", "inv_003"],
  "uncovered_blockers": ["inv_012"],
  "test_command": "pytest tests/ -k 'test_feed or test_fee'"
}
```

---

### 6. `skills/z-init-docs/SKILL.md` (EXTEND)

**Add Phase: "Invariant discovery"** (gated on `--invariants` flag)

1. If `docs/INVARIANTS.json` exists → skip (idempotent).
2. Scan all discovery paths for `**INVARIANT:**` / `**MUST:**` / `**DANGER:**` lines:
   - `z-harness/*/SPEC.md` (active plans in repo root)
   - `z-harness/*/archive/*/SPEC.md` (archived plan versions)
   - `plans/*/SPEC.md` (repo-level plans)
   - `$BASE/plans/*/SPEC.md` (state-dir plans, resolved via `plan-path.sh base_dir`)
3. Apply durability heuristic: an invariant is durable if (a) it appears in ≥2 plans across different slugs, OR (b) it references cross-module contracts (multiple files from different directories).
4. For each durable candidate: propose as an INVARIANTS.json entry. Assign a stable `id`, auto-classify `tags[]` from TAGS.txt, set `source: spec`, set `source_files[]` to the cited files.
5. Write `docs/INVARIANTS.json` with proposed invariants.
6. Generate `docs/INVARIANTS.md` rendering.
7. Add to `docs/llm/INDEX.json` as a special entry: `{"slug": "invariants", "last_updated": "<iso>", "source_file": "docs/INVARIANTS.json"}`.

**Idempotent:** Re-running `--invariants` on an existing INVARIANTS.json scans for NEW durable invariants only (not already present by id or description match). Existing entries are not modified.

---

### 7. `skills/z-plan/SKILL.md` (EXTEND — Phase 6)

**Add invariant promotion nudge** after writing SPEC.md:

Gated on:
- `docs/INVARIANTS.json` exists
- SPEC.md contains `**INVARIANT:**` / `**MUST:**` lines not matching any existing INVARIANTS.json entry (by description fuzzy match)
- Invariant appears durable (references ≥2 modules or uses cross-cutting language)

If all gates pass, surface via `AskUserQuestion`:
- "N SPEC.md invariants look durable. Promote to INVARIANTS.json?"
- Options: "Promote all N", "Let me pick", "Skip"

User selects → /z-plan orchestrator writes entries to INVARIANTS.json (not the plan — the orchestrator has write access to the repo-level invariant store).

---

### 8. `skills/z-implement-all/SKILL.md` (UPDATE — implementer consumption)

**Update implementer's TESTS.md parsing** to handle version 2 format:

- Read TESTS.md frontmatter for `**Version:** 2`
- If v2: grep `## TEST-NNN` blocks. Read `**Invariant ID:**`, `**Fixture:**`, `**Layer:**`, `**Target file:**`, `**Assertion:**`. Skip `layer: full-chain` entries (implemented later).
- If v1 (no version field): use existing parsing (grep `## TEST-NNN`, read `**Target file:**`, `**Assertion:**`).
- Test code is written at `Target file:` path, using `Fixture:` values as test inputs.

**Per-task acceptance check (step 7b):** After implementer writes test code + production code, run the test command from `test-runner.json`, filtered to this task's TEST-NNN entries.

---

### 9. `skills/z-review-all/SKILL.md` (UPDATE — Phase 3.5)

**Update test-suite execution (Phase 3.5)** to distinguish per-task vs full-chain tests:

- Read TESTS.md frontmatter for `**Version:** 2`
- If v2: run per-task tests AND full-chain tests. Report separately.
- If v1: run all tests (legacy behavior).
- Full-chain test failures are surfaced as a distinct category ("full-chain invariant violations") in the review report.

---

### 10. `skills/z-maintain-docs/SKILL.md` (EXTEND)

**Add INVARIANTS.json to staleness scan:**

- In Phase 1 (stale concept detection): add `docs/INVARIANTS.json` as a staleness-checkable artifact.
- For each invariant entry: compare `source_files[]` max mtime to `last_updated`. Flag stale invariants.
- On staleness detection: dispatch doc-updater subagent with mode `invariants` to review and update affected entries.

---

### 11. `docs/llm/INDEX.json` (UPDATE)

**Add invariants entry:**
```json
{
  "slug": "invariants",
  "source_files": ["docs/INVARIANTS.json"],
  "last_updated": "<iso>",
  "confidence": "high",
  "summary": "System-level behavioral invariants — permanent per-repo truths consumed by /z-test for behavioral test generation."
}
```

---

### 12. Exports (UPDATE)

**Files to update:**
- `exports/pi/prompts/z-test.md` — regenerate from new skill
- `exports/pi/prompts/z-test-skill.md` — regenerate
- `exports/codex/prompts/z-test.md` — regenerate
- `exports/codex/prompts/z-test-skill.md` — regenerate
- `exports/agy/prompts/z-test.md` — regenerate
- `exports/agy/prompts/skill-z-test.md` — regenerate
- `.agent/skills/z-test/SKILL.md` — copy from skills/z-test/SKILL.md
- `.agent/workflows/z-test.md` — copy from commands/z-test.md

---

## Edge cases

1. **No INVARIANTS.json in repo:** /z-test falls back to SPEC.md invariant extraction only (legacy mode). Produces TESTS.md version 1 format. Warns user.
2. **INVARIANTS.json exists but no matching invariants for current plan:** /z-test drafts tests from SPEC.md invariants only. No invariant IDs in TESTS.md entries.
3. **Invariant ID collision:** INVARIANTS.json write-time validation rejects duplicate IDs.
4. **Fixture validation failure:** /z-test Phase 4 re-checks that TESTS.md `fixture:` satisfies `fixture_schema`. Failed entries are dropped with a warning.
5. **Stale invariant at /z-test time:** Re-check source_files mtime vs last_updated. Warn user. Offer: continue / skip stale invariants / abort.
6. **Old TESTS.md (v1) in plan directory:** /z-implement-all and /z-review-all detect missing `**Version:** 2` and use legacy parsing. No migration needed.
7. **Multiple /z-test runs on same plan:** Merge semantics in Phase 7 (cross-link into TASKS.md) handle this — `**Tests:**` lines are merged, not overwritten.
8. **TASKS.md has no `**Invariants:**` annotations:** Fuzzy matching operates on task descriptions. Discovery hints are surfaced to user.
9. **invariant-check.sh in CI without INVARIANTS.json:** Exit 0 with warning ("no invariants to check"). Not a failure.
10. **invariant-check.sh with v1 TESTS.md:** Run tests normally, report results without invariant linkage.
