# Phase 4 — Synthesis

**Run:** 20260610T223549Z-test

## Per-draft critique

### TEST-001 (ep_001 — Bare except suppression)
- **Verdict:** KEEP. Strengthen: fixture should also test that `except: pass` in a non-interrupt context is flagged. The assertion should differentiate between `except: pass` (bad) and `except Exception: log_and_re_raise` (acceptable).
- **Anti-rubber-stamp check:** This test is NOT trivial — it tests whether a runtime behavior (interrupt suppression) is prevented, which is a real concern in CLI scripts.
- **Triviality check:** Pass — the test would fail on current code if a bare except is present.

### TEST-002 (ep_002 — TODO tracking)
- **Verdict:** KEEP. Strengthen: the fixture should include both examples (TODO with tracker, TODO without tracker) to test the scanner correctly distinguishes them.
- **Anti-rubber-stamp check:** The test is about metadata quality, not runtime behavior — this is an unusual category but valid for a CI-check pattern.
- **Triviality check:** Pass — tests a lint-like invariant that is not currently enforced.

### TEST-003 (ep_003 — || true silencing)
- **Verdict:** KEEP. Strengthen: the assertion must also cover `||:` (colon) which is an alternative to `|| true` in POSIX shell. The fixture should include `grep pattern file || :` as an edge case.
- **Anti-rubber-stamp check:** Valid — this is a real footgun in shell test scripts.
- **Triviality check:** Pass.

### TEST-004 (inv_001 — Behavioral invariant requirement)
- **Verdict:** KEEP with strengthening. The current assertion vagueness ("must contain at least one domain-term") is weak. Strengthen: the assertion should require that the test's assertion section references a failure_class or a "must/must not/must never" clause. A test whose only assertion is `assert result == expected` fails the check.
- **Anti-rubber-stamp check:** This is a meta-test — it tests test quality, not code quality. Valid for the spec-level invariant.
- **Triviality check:** Borderline — the invariant is described in the spec but has no enforcement mechanism. The test would be the first enforcement, so it's not trivial yet.

### TEST-005 (inv_002 — Fixture validity)
- **Verdict:** KEEP. The assertion correctly tests schema validation for adversarial fixtures. No strengthening needed.
- **Anti-rubber-stamp check:** Valid — tests a real check that requires fixture validation to be implemented.
- **Triviality check:** Pass — requires both a schema and a validator to exist.

## Uncovered error points
All 3 error points have test entries. None uncovered.

## Uncovered invariants
6 of 8 invariants lack test coverage:
- **inv_003 (blocker) — Atomic write discipline** — uncovered. PROPOSE TEST-006.
- **inv_004 (major) — Phase 5.5 soft-failure** — uncovered. PROPOSE TEST-007.
- **inv_005 (blocker) — Cross-LLM consultant dispatch** — uncovered. PROPOSE TEST-008.
- **inv_006 (blocker) — Export preserves behavioral rules** — uncovered. Not relevant to this plan's tests; skip.
- **inv_007 (major) — Artifacts committed** — uncovered. Not relevant to test generation; skip.
- **inv_008 (blocker) — Feed connectivity check** — uncovered. Domain-specific (feed processor); skip for this plan.

## Additional test entries (from uncovered invariants)

### TEST-006 (invariant-driven) — Atomic write discipline
- **Invariant ID:** inv_003
- **Invariant description:** INVARIANTS.json write must be atomic — no partial file on disk at any time
- **Failure class:** Partial INVARIANTS.json left on disk after half-failed update
- **Task:** T001/T002/T003
- **Layer:** per-task
- **Target file:** tests/test_atomic_write.py
- **Fixture:** {"tmp_path": "/tmp/test_z_harness", "corrupt_write": false}
- **Assertion:** After a simulated mid-write crash, the target file (INVARIANTS.json or ERROR_POINTS.json) must contain either the full old content or the full new content — never a truncated or partial JSON document
- **Seed:** spec
- **Mandatory:** yes

### TEST-007 (invariant-driven) — Phase 5.5 soft-failure
- **Invariant ID:** inv_004
- **Invariant description:** Phase 5.5 must NOT halt z-review-all pipeline on extraction failure
- **Failure class:** Review pipeline halted by extraction failure
- **Task:** T004
- **Layer:** per-task
- **Target file:** tests/test_review_pipeline_resilience.py
- **Fixture:** {"extraction_phase": "error_point_extraction", "simulate_crash": true}
- **Assertion:** When invariant or error-point extraction fails (bad JSON, file read error, subagent crash), z-review-all must log the error and continue to Phase 6 — the pipeline must never halt on extraction failure
- **Seed:** spec
- **Mandatory:** yes

### TEST-008 (invariant-driven) — Cross-LLM consultant dispatch
- **Invariant ID:** inv_005
- **Invariant description:** Cross-LLM consultant subagents must be able to dispatch even when doc-staleness is high
- **Failure class:** Docs-staleness gate blocked consultant dispatch
- **Task:** T004/T005
- **Layer:** per-task
- **Target file:** tests/test_consultant_dispatch.py
- **Fixture:** {"staleness_days": 90, "gate_config": "compaction_breakpoint"}
- **Assertion:** The compaction breakpoint gate must not block consultant dispatch — high doc-staleness must produce a warning, not a halt
- **Seed:** spec
- **Mandatory:** yes

## Cross-source deduplication
No overlapping entries across sources — all 5 original entries have distinct failure_classes and target_files. Three new invariant entries (TEST-006, TEST-007, TEST-008) are also distinct. No merge needed.

## Summary
- 5 original drafts: 3 EP + 2 INV → all KEEP (1-2 with strengthening)
- 3 new entries from uncovered invariants (blocker/major)
- 0 entries dropped (no trivial drafts)
- 2 entries strengthened (TEST-001, TEST-004)
- 0 cross-source merges needed
- Total: 8 entries (3 EP + 5 INV)
