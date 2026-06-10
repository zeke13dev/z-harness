# Rewrite /z-test for System-Level Invariant Tests

**Converged premise — ready for full pipeline.**

## The Problem

/z-test currently produces function-level unit tests that always pass green (9/9 clean). But z-review-all consistently catches real issues: spec drift, feed connectivity failures, fee enforcement gaps, degenerate model output, missing INDEX.json entries, task completion verification gaps. The tests verify code correctness in isolation but never catch the things that actually break.

## The Solution: System-Level Invariant Tests

1. **INVARIANTS.md** — A permanent per-repo file declaring system-level truths, each with tags + fixture schema. These are durable invariants the system must uphold, not per-task test cases.

2. **Tag-based mapping** — /z-test matches invariant tags against task descriptions to know which invariants each task touches.

3. **Behavioral (not structural) tests** — Test assert composed behavior is sane ("fees moved correctly", "no look-ahead leakage") not structural proof ("function was called").

4. **Hybrid fixture ownership** — INVARIANTS.md declares the invariant + fixture schema, the plan provides specific fixture values.

5. **Multi-layer testing** — Per-task behavioral tests (with recorded fixtures) + final assembly full-chain tests.

6. **CI per-PR gate** — Fast, deterministic, no real capital required. Model-degenerate checks are optional/per-strategy.

7. **Not qt-bot specific** — /z-test itself must produce these for any plan/codebase.

## User Decision on Consult Bundle

The consult bundle (5 decisions) is accepted as-is — no changes, no flips, no overrides.

Proceed with the full pipeline:
1. Cross-LLM consult on the 5 flagged decisions (D1, D2, D6, D4, D7)
2. Produce SPEC.md / PLAN.md / TASKS.md
3. Run the audit/plan-review phase (z-audit-plan / post-plan audit as per pipeline)

/go z-plan
