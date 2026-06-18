# System Invariants

**Total invariants:** 8

---

## inv_001 — Every test produced by /z-test must exercise a behavioral invariant — not just verify function-call correctness. A test that calls a function and asserts a return value without verifying a system-level property is a unit test, not an invariant test.

**Severity:** blocker

**Tags:** correctness, data-quality

**Failure class:** Invariant test reduces to unit test — no behavioral property verified

**Source files:** `commands/z-test.md`

**Fixture schema:** `{"type": "object", "required": ["test_code", "assertion_section"], "properties": {"test_code": {"type": "string"}, "assertion_section": {"type": "string"}}}`
---

## inv_002 — Adversarial test fixtures must be structurally valid against the invariant's fixture_schema. A fixture that doesn't match its schema is not a valid falsification attempt.

**Severity:** blocker

**Tags:** correctness, schema

**Failure class:** Adversarial fixture fails schema validation

**Source files:** `commands/z-test.md`

**Fixture schema:** `{"type": "object", "required": ["fixture_data", "schema_ref"], "properties": {"fixture_data": {"type": "object"}, "schema_ref": {"type": "string"}}}`
---

## inv_003 — INVARIANTS.json write must be atomic — no partial file on disk at any time. Use write to tempfile → flush → fsync → os.replace().

**Severity:** blocker

**Tags:** correctness, data-quality

**Failure class:** Partial INVARIANTS.json left on disk after half-failed update

**Source files:** `commands/z-init-docs.md`
---

## inv_004 — Phase 5.5 (or any post-review invariant extraction) must NOT halt the /z-review-all pipeline on extraction failure. If extraction fails, log the error and continue — the review itself is the priority.

**Severity:** major

**Tags:** correctness

**Failure class:** Review pipeline halted by invariant extraction failure

**Source files:** `commands/z-review-all.md`
---

## inv_005 — Cross-LLM consultant subagents (consultant-primary, consultant-secondary) MUST be able to dispatch even when doc-staleness is high. The compaction breakpoint gate must not block consultant dispatch.

**Severity:** blocker

**Tags:** correctness, deprecation

**Failure class:** Docs-staleness gate blocked consultant dispatch

**Source files:** `commands/z-review-all.md`
---

## inv_006 — Every exported z-command (export-pi.py, export-codex-*) must expose the full set of behavioral rules from the base skill. An export that drops critical rules (e.g., structural test vs invariant test distinction, fixture_schema validation) produces broken behavior.

**Severity:** blocker

**Tags:** correctness, schema

**Failure class:** Export omits critical behavioral rules

**Source files:** `exports/export-pi.py`, `scripts/export-codex-skills.py`
---

## inv_007 — All plan artifacts (SPEC.md, PLAN.md, TASKS.md) plus INVARIANTS.json and all TESTS.md files must be committed to the repo. An uncommitted artifact may represent incomplete work that could be lost on checkout.

**Severity:** major

**Tags:** correctness

**Failure class:** Uncommitted plan or test artifacts

**Source files:** `scripts/z-harness-check.sh`
---

## inv_008 — Feed connectivity checks at tier boundaries (model output → strategy signal → order submission) must be non-interactive and reliable. A failed feed check must produce clear log output, not a silent deg or crash.

**Severity:** blocker

**Tags:** correctness, data-quality, observability

**Failure class:** Feed connectivity check fails silently

**Source files:** `src/feed/processor.rs`
---
