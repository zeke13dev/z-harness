# Plan Audit Report — rewrite-z-test-invariants

- **Date (UTC):** 2026-06-10T02:14Z
- **Slug:** rewrite-z-test-invariants
- **Run ID:** 20260610T020904Z-rewrite-z-test-invariants-audit-plan
- **Reviewers:** 3 × pre-reviewer (DeepSeek V4 Flash) + orchestrator synthesis
- **Consultants:** Unavailable (pi environment — consultant-primary/secondary not registered); substituted with 3 pre-reviewers

## Summary

The plan is **sound in architecture** — DRY/KISS/SOLID compliance is well-considered, task dependency graph is sensible, and the phased approach (schema → bootstrap → rewrite → consumers → CI) is the right order. However, the review surfaced **2 blockers** and **5 majors** that should be addressed before implementation via `/z-amend`.

The blockers are real: the bootstrap scan path won't find any SPEC.md files, and full-chain test code has no owner. The majors are mostly dependency-gap and convention-violation issues that are easy to fix spec-side.

---

## reality-check Reality Check findings

### BLOCKER — T003/T004 bootstrap scan path produces zero matches

**Location:** T003 acceptance criteria, SPEC.md Section 6

The plan says to scan `z-harness/plans/*/archive/*/SPEC.md` and the legacy flat `z-harness/SPEC.md`. In the actual codebase:

- `z-harness/plans/` subdirectory has **zero** SPEC.md files (it only has `doc-updater-agent/` which contains a SPEC.md, but the glob pattern `z-harness/plans/*/archive/*/SPEC.md` won't reach it because there are no archive/ subdirectories under `plans/`).
- Real SPEC.md files live at:
  - `z-harness/<slug>/SPEC.md` (6 files — active plans)
  - `z-harness/<slug>/archive/<run>/SPEC.md` (3 files — archived plans)
  - `plans/<slug>/SPEC.md` (1 file)
  - State-dir: `~/.local/state/z-harness/.../plans/<slug>/SPEC.md`
- No legacy flat `z-harness/SPEC.md` exists.

**Impact:** `/z-init-docs --invariants` will silently produce an empty INVARIANTS.json. The bootstrap is dead on arrival.

**Fix:** Change scan globs to: `z-harness/*/SPEC.md`, `z-harness/*/archive/*/SPEC.md`, `plans/*/SPEC.md`. Also resolve the state-dir base via `plan-path.sh base_dir` and scan `$BASE/plans/*/SPEC.md`.

**One-reason-this-might-be-wrong check:** PASSED. Verified with actual `ls` — `z-harness/plans/*/archive/*/SPEC.md` returns zero results. The fix globs were also verified — they return 10 combined matches.

---

### BLOCKER — Full-chain tests have no implementation task

**Location:** T010 acceptance, T011 acceptance, SPEC.md Section 3 (Phase 3 — Cross-LLM consult evolved)

The plan defines `layer: full-chain` test entries in TESTS.md v2. T010 explicitly instructs the implementer to **skip** `layer: full-chain` entries ("implemented later"). T011 instructs /z-review-all Phase 3.5 to **run** full-chain tests. **No task exists to write the test code for full-chain entries.**

**Impact:** /z-review-all would attempt to run tests from non-existent test files, producing errors or false failure reports. Full-chain invariant coverage is promised but never delivered.

**Fix:** Option A: Add a task (T010b or T017) that writes full-chain test code after all per-task tests are implemented. Option B: Specify in T011 that /z-review-all gracefully skips full-chain tests if the target file doesn't exist, and document full-chain as "future work."

**One-reason-this-might-be-wrong check:** PASSED. T010 says "Skip `layer: full-chain` entries (implemented later)" — "later" is never defined. T011 says "run per-task tests AND full-chain tests" — but the code doesn't exist.

---

## design-check Design & Style findings

### MAJOR — T001 JSON Schema draft version mismatch

**Location:** T001 acceptance criteria

T001 says "validates against JSON Schema draft-07" but the pattern to follow (`docs/schemas/axiom.schema.json`) and all 5 schemas in `docs/schemas/` use `https://json-schema.org/draft/2020-12/schema`. Draft-07 meta-schema validation would reject a draft-2020-12 schema.

**Fix:** Change acceptance criterion to "validates against JSON Schema draft-2020-12."

---

### MAJOR — T014 exit code 2 collides with STYLE.md P-002

**Location:** T014 acceptance criteria, STYLE.md P-002

STYLE.md P-002 reserves exit code 2 for "wrong invocation" (usage errors). Every shell script in `scripts/` follows this convention. T014 plans exit code 2 for "coverage gap" — a semantic failure, not a usage error. Two semantically distinct failure modes sharing the same exit code breaks CI scripting.

**Fix:** Use exit code 3 for "coverage gap." STYLE.md P-002 allows codes 3-125 for application-specific failures. Update T015 --ci to match (exit 3 for coverage gap).

**One-reason-this-might-be-wrong check:** PASSED. Verified STYLE.md line 145: `"exit 2 is the POSIX convention distinguishing 'wrong invocation' from 'runtime failure'"` and confirmed all scripts in `scripts/` use exit 2 for usage.

---

### MAJOR — T015 --ci JSON `failed_tests` field is dead

**Location:** SPEC.md Section 5

The `--ci` JSON schema includes `"failed_tests": []` but T015 explicitly says `--ci` "does NOT run tests" — it only validates fixtures and metadata. The field is always empty, misleading CI consumers that expect test results.

**Fix:** Remove `failed_tests` from the `--ci` JSON schema, or run tests in `--ci` mode and populate it honestly.

---

### MAJOR — Missing dependency: T015 on T002

**Location:** TASKS.md dependency graph

T015 (`--ci` flag) validates fixtures against schemas (acceptance: "validate all fixtures against schemas"). The validation logic is built in T002 (`scripts/validate-invariants.py`). The dependency graph shows T015 depends only on T008. Without T002, T015 must either duplicate the validation logic or fail.

**Fix:** Add T002 as a dependency of T015 in the graph.

---

### MAJOR — Missing dependency: T013 on T002

**Location:** TASKS.md dependency graph

T013 (invariant promotion nudge) writes entries to INVARIANTS.json (acceptance: "User-selected invariants are written to INVARIANTS.json"). Without T002's validation, written entries could violate uniqueness, required fields, or tag constraints, producing an invalid INVARIANTS.json.

**Fix:** Add T002 as a dependency of T013 in the graph.

---

## adversarial Adversarial Consult findings

(Pre-reviewers substituted for consultant-primary/secondary)

### MAJOR — No validate-on-load for corrupt INVARIANTS.json

**Location:** SPEC.md edge cases, /z-test Phase 1

Edge cases list "No INVARIANTS.json" and "stale invariants" but not "INVARIANTS.json exists but fails schema validation" (manual edit corruption, partial write from crash). /z-test Phase 1 loads INVARIANTS.json with no validation step, so it would crash or produce garbage on corrupt input.

**Fix:** Add validate-on-load in /z-test Phase 1: run `validate-invariants.py` on load, warn user on failure, fall back to SPEC.md-only extraction.

---

## Consensus vs Disagreement

### consensus (flagged by multiple reviewers)
- **Bootstrap scan path broken** — flagged by pre-reviewer 1 (reality) and pre-reviewer 3 (logic) independently
- **Full-chain tests orphaned** — flagged by pre-reviewer 3 (logic), architecture gap visible to multiple reviewers
- **T015 --ci / invariant-check.sh overlap** — flagged by pre-reviewer 2 (design) and pre-reviewer 3 (logic)

### outlier (single reviewer, worth scrutiny)
- **T013 violates SRP** — pre-reviewer 2 flagged it as MAJOR. Scrutiny: /z-plan already has post-Phase-6 steps (Phase 7 review, Phase 8 TASKS.md). The nudge is gated on 3 conditions and user-approved. Demoted to MINOR.
- **T002 exit code 3 non-standard** — pre-reviewer 2 flagged it. Scrutiny: POSIX allows 0-125, and 4 distinct codes is clean. Demoted to MINOR.
- **T004 ID collision on re-runs** — pre-reviewer 3 flagged it. Scrutiny: first bootstrap starts at 001 correctly; re-runs need max+1, which is a minor implementation detail. MINOR.

---

## Actionable Recommendations

### Must fix before implementation (BLOCKER)

| # | Finding | Fix | Tasks affected |
|---|---------|-----|----------------|
| 1 | Bootstrap scan path finds zero SPEC.md files | Change scan globs to `z-harness/*/SPEC.md`, `z-harness/*/archive/*/SPEC.md`, `plans/*/SPEC.md`, and resolve state-dir base | T003, T004, SPEC.md §6 |
| 2 | Full-chain test code has no implementation owner | Add T010b (write full-chain test code) or specify graceful skip in T011 for missing target files | T010, T011, SPEC.md §3 |

### Should fix (MAJOR)

| # | Finding | Fix | Tasks affected |
|---|---------|-----|----------------|
| 3 | JSON Schema draft-07 vs draft-2020-12 | Change T001 acceptance to draft-2020-12 | T001 |
| 4 | Exit code 2 collides with STYLE.md P-002 | Use exit 3 for "coverage gap" | T014, T015 |
| 5 | --ci JSON `failed_tests` is dead field | Remove field or run tests in --ci mode | T015, SPEC.md §5 |
| 6 | T015 missing dependency on T002 | Add T002 → T015 dependency edge | TASKS.md graph |
| 7 | T013 missing dependency on T002 | Add T002 → T013 dependency edge | TASKS.md graph |

### Nice to fix (MINOR)

| # | Finding | Fix | Tasks affected |
|---|---------|-----|----------------|
| 8 | Cursor exports not in SPEC.md §12 | Add cursor export paths | T016, SPEC.md §12 |
| 9 | No validate-on-load for corrupt INVARIANTS.json | Add validation step in /z-test Phase 1 | T006 |
| 10 | T004 ID assignment edge case on re-runs | Start from max(existing_id)+1 | T004 |
| 11 | --ci and invariant-check.sh function overlap | Document split: invariant-check.sh for CI, --ci for manual validation | SPEC.md §5 |

---

## Verdict

**2 blockers, 5 majors, 4 minors.** The architecture is sound and the plan is otherwise well-structured. The blockers are fixable — both are specification corrections (wrong glob paths, missing task) rather than design flaws. Recommend running `/z-amend` to apply the blocker and major fixes to SPEC.md, PLAN.md, and TASKS.md, then proceeding to `/z-implement-all`.
