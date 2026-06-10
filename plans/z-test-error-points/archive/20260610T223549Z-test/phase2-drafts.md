# Phase 2 Drafts — z-test dual-source

**Run:** 20260610T223549Z-test
**Mode:** dual
**Ratio:** 70:30
**Plan slug:** z-test-error-points

## Error point entries

### TEST-001 (error-point-driven, slot 1)
- **Error point ID:** ep_001
- **Error point pattern:** Bare except clause silently swallows errors in hermes-execute
- **Failure class:** Silent error suppression — bare except: pass discards all exception types including KeyboardInterrupt and SystemExit
- **Task:** T003 (ERROR_POINTS.json seed data)
- **Layer:** per-task
- **Target file:** tests/test_error_suppression.py
- **Fixture:** { "code_snippet": "try:\n    do_work()\nexcept:\n    pass", "expected_behavior": "re_raise_interrupt" }
- **Assertion:** bare `except: pass` must not suppress KeyboardInterrupt or SystemExit — the handler must either log+re-raise or use `except Exception:` with explicit pass-through for non-Exception BaseExceptions
- **Seed:** error-point
- **Mandatory:** yes

### TEST-002 (error-point-driven, slot 3)
- **Error point ID:** ep_002
- **Error point pattern:** TODO comments flag relay stall with no follow-up task or tracking issue
- **Failure class:** Unresolved TODO — task stall or merge conflict handling deferred without tracking mechanism
- **Task:** T003 (ERROR_POINTS.json seed data)
- **Layer:** per-task
- **Target file:** tests/test_todo_tracking.py
- **Fixture:** { "source_files": ["scripts/hermes-execute.py"], "required_issue_refs": ["TODO:.*https?://|FIXME:.*https?://"] }
- **Assertion:** Every TODO/FIXME/HACK comment in source files must reference a tracking issue URL (`https://github.com/...` or equivalent) — a TODD without a tracker is a deferred decision that blocks release
- **Seed:** error-point
- **Mandatory:** yes

### TEST-003 (error-point-driven, slot 5)
- **Error point ID:** ep_003
- **Error point pattern:** Error output silently discarded via || true in test scripts
- **Failure class:** Silent test failure — || true suppresses non-zero exits from grep and other commands in test assertions
- **Task:** T003 (ERROR_POINTS.json seed data)
- **Layer:** per-task
- **Target file:** tests/test_shell_assertions.py
- **Fixture:** { "command": "grep ERROR /var/log/app.log || true", "desired_behavior": "test_fail_on_no_match" }
- **Assertion:** A shell command that checks for expected output (grep, test, diff) must not end with `|| true` or `||:` — such silencing masks assertion failures; the command should either exit non-zero to fail the test or use explicit `|| log_and_exit` patterns
- **Seed:** error-point
- **Mandatory:** yes

## Invariant entries

### TEST-004 (invariant-driven, slot 2)
- **Invariant ID:** inv_001
- **Invariant description:** Every test produced by /z-test must exercise a behavioral invariant — not just verify function-call correctness
- **Failure class:** Invariant test reduces to unit test — no behavioral property verified
- **Task:** T005 (z-test SKILL.md rewrite)
- **Layer:** per-task
- **Target file:** tests/test_invariant_behavioral_check.sh
- **Fixture:** { "test_block": { "assertion_count": 1, "behavioral_terms": ["must", "invariant", "always", "never"] } }
- **Assertion:** Every generated test must assert a behavioral invariant (system-level property), not just a function return value — the test's assertion section must contain at least one domain-term describing what SHOULD NOT HAPPEN
- **Seed:** spec
- **Mandatory:** yes

### TEST-005 (invariant-driven, slot 4)
- **Invariant ID:** inv_002
- **Invariant description:** Adversarial test fixtures must be structurally valid against the invariant's fixture_schema
- **Failure class:** Adversarial fixture fails schema validation
- **Task:** T005 (z-test SKILL.md rewrite)
- **Layer:** per-task
- **Target file:** tests/test_fixture_validation.py
- **Fixture:** { "fixture_data": {"valid": true}, "schema_ref": "docs/schemas/error_points.schema.json" }
- **Assertion:** Adversarial test fixtures must satisfy the invariant's fixture_schema — an invalid fixture is not a valid falsification attempt and must be rejected before test generation
- **Seed:** spec
- **Mandatory:** yes
