# Tests for z-test-error-points

**Run:** 20260610T223549Z-test
**Version:** 2
**Status:** drafted (awaiting /z-implement-all)
**Invariants file:** docs/INVARIANTS.json
**Error points file:** docs/ERROR_POINTS.json
**Interleave ratio:** 70:30
**Plugin version:** 1.0.0
**Cross-LLM consensus:** user-validated (subagents unavailable)
**Counts:** 7 mandatory, 1 recommended, 0 optional
**Cross-LLM delta:** dropped 0 trivial, added 3 gaps, strengthened 2
**Cross-source merged:** 0 entries merged
**Covered invariants:** inv_001, inv_002, inv_003, inv_004, inv_005
**Uncovered invariants (blocker):** inv_006, inv_008
**Uncovered invariants (major):** inv_007
**Covered error points:** ep_001, ep_002, ep_003
**Uncovered error points (blocker):** none
**Uncovered error points (major):** none

## TEST-001 (covers T003)
**Error point ID:** ep_001
**Error point pattern:** Bare except clause silently swallows errors in hermes-execute
**Failure class:** Silent error suppression — bare except: pass discards all exception types including KeyboardInterrupt and SystemExit
**Layer:** per-task
**Target file:** tests/test_error_suppression.py
**Fixture:**
  code_snippet: |
    try:
        do_work()
    except:
        pass
  expected_behavior: re_raise_interrupt
**Assertion:** bare `except: pass` must not suppress KeyboardInterrupt or SystemExit — the handler must either log+re-raise or use `except Exception:` with explicit pass-through for non-Exception BaseExceptions. Additionally, `except: pass` outside interrupt context must be flagged; acceptable patterns use `except Exception:`.
**Seed:** error-point
**Mandatory:** yes

## TEST-002 (covers T003)
**Error point ID:** ep_002
**Error point pattern:** TODO comments flag relay stall with no follow-up task or tracking issue
**Failure class:** Unresolved TODO — task stall or merge conflict handling deferred without tracking mechanism
**Layer:** per-task
**Target file:** tests/test_todo_tracking.py
**Fixture:**
  source_files:
    - scripts/hermes-execute.py
  required_issue_refs:
    - "TODO:.*https?://"
    - "FIXME:.*https?://"
**Assertion:** Every TODO/FIXME/HACK/BUG comment in source files must reference a tracking issue URL (https://github.com/... or equivalent) — a TODO without a tracker is a deferred decision that blocks release. The checker must distinguish TODO-with-tracker (permitted) from TODO-without-tracker (violation).
**Seed:** error-point
**Mandatory:** yes

## TEST-003 (covers T003)
**Error point ID:** ep_003
**Error point pattern:** Error output silently discarded via || true in test scripts
**Failure class:** Silent test failure — || true suppresses non-zero exits from grep and other commands in test assertions
**Layer:** per-task
**Target file:** tests/test_shell_assertions.py
**Fixture:**
  commands:
    - "grep ERROR /var/log/app.log || true"
    - "grep pattern file || :"
  desired_behavior: test_fail_on_no_match
**Assertion:** A shell command that checks for expected output (grep, test, diff) must not end with `|| true` or `|| :` — such silencing masks assertion failures; the command should either exit non-zero to fail the test or use explicit `|| log_and_exit` patterns.
**Seed:** error-point
**Mandatory:** yes

## TEST-004 (covers T005)
**Invariant ID:** inv_001
**Invariant description:** Every test produced by /z-test must exercise a behavioral invariant — not just verify function-call correctness
**Failure class:** Invariant test reduces to unit test — no behavioral property verified
**Layer:** per-task
**Target file:** tests/test_invariant_behavioral_check.sh
**Fixture:**
  test_block: { assertion_count: 2, behavioral_terms: ["must", "must not", "must never", "invariant"] }
**Assertion:** Every generated test entry must reference a failure_class and contain an assertion that uses "must" / "must not" / "must never" / "invariant" language describing a system-level property. A test whose only assertion is `assert result == expected` fails the behavioral-invariant check and must be flagged during Phase 4 synthesis.
**Seed:** spec
**Mandatory:** yes

## TEST-005 (covers T005)
**Invariant ID:** inv_002
**Invariant description:** Adversarial test fixtures must be structurally valid against the invariant's fixture_schema
**Failure class:** Adversarial fixture fails schema validation
**Layer:** per-task
**Target file:** tests/test_fixture_validation.py
**Fixture:**
  fixture_data: { valid: true }
  schema_ref: docs/schemas/error_points.schema.json
**Assertion:** Adversarial test fixtures must satisfy the invariant's fixture_schema — an invalid fixture is not a valid falsification attempt and must be rejected before test generation. The validator must reject fixtures with missing required fields, wrong types, or constraint violations.
**Seed:** spec
**Mandatory:** yes

## TEST-006 (covers T001, T002, T003)
**Invariant ID:** inv_003
**Invariant description:** INVARIANTS.json write must be atomic — no partial file on disk at any time
**Failure class:** Partial INVARIANTS.json left on disk after half-failed update
**Layer:** per-task
**Target file:** tests/test_atomic_write.py
**Fixture:**
  tmp_path: /tmp/test_z_harness
  corrupt_write: false
**Assertion:** After a simulated mid-write crash (kill -9 or write interruption at the tempfile stage), the target file (INVARIANTS.json or ERROR_POINTS.json) must contain either the full old content or the full new content — never a truncated or partial JSON document. The atomic write pattern (tmpfile -> fsync -> os.replace()) must guarantee this.
**Seed:** spec
**Mandatory:** yes

## TEST-007 (covers T004)
**Invariant ID:** inv_004
**Invariant description:** Phase 5.5 must NOT halt z-review-all pipeline on extraction failure
**Failure class:** Review pipeline halted by extraction failure
**Layer:** per-task
**Target file:** tests/test_review_pipeline_resilience.py
**Fixture:**
  extraction_phase: error_point_extraction
  simulate_crash: true
**Assertion:** When invariant or error-point extraction fails (bad JSON from Haiku, file read error, subagent crash, validation failure), z-review-all must log the error to `$BASE/archive/$RRUN/invariant-extraction-error.log` and continue to Phase 6. The pipeline must never halt on extraction failure — invariants and error points are soft phases.
**Seed:** spec
**Mandatory:** yes

## TEST-008 (covers T004, T005)
**Invariant ID:** inv_005
**Invariant description:** Cross-LLM consultant subagents must be able to dispatch even when doc-staleness is high
**Failure class:** Docs-staleness gate blocked consultant dispatch
**Layer:** per-task
**Target file:** tests/test_consultant_dispatch.py
**Fixture:**
  staleness_days: 90
  gate_config: compaction_breakpoint
**Assertion:** The compaction breakpoint gate must not block consultant dispatch when doc files are stale — stale docs should produce a warning in the event log, not a halt. The `compaction_pause` trigger must always route to the no-ask resolver, not to a hard abort.
**Seed:** spec
**Mandatory:** yes
