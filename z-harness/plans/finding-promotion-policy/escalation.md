# Escalation: finding-promotion-policy

**Run:** 20260524T211701Z-finding-promotion-policy
**Status:** escalated from `/z-plan-light`
**Reason:** Scope exceeds light-mode thresholds.

## Requested Change

Turn the `unified-review-tasks` brainstorm into an implementation plan: make `/z-review-all` stop asking late, repeated "what should I do with these findings?" questions and instead produce actionable task/amendment artifacts by default. Consider whether the same finding-promotion policy should apply to `/z-audit`, `/z-mr-review`, and related workflows.

## Why Light Mode Is Too Small

This is a cross-workflow design change, not a one-file fix. It touches the final-review command, its skill/export surfaces, existing audit and MR-review task-shaped outputs, and the `z-amend` safety boundary for spec/plan/task mutation.

Candidate files/surfaces already exceed the light-mode cap:

- `commands/z-review-all.md`
- `skills/z-review-all/SKILL.md`
- `commands/z-audit.md`
- `commands/z-mr-review.md`
- `skills/z-amend/SKILL.md`
- exported command/skill copies for Cursor, Codex, and Antigravity
- possibly task-consumer guidance in `agents/implementer.md` or `/z-implement-all` if review-produced task artifacts become first-class inputs

## Non-Obvious Decisions For Full Plan

- Define the shared finding-promotion schema: finding classes such as `implementation_drift`, `spec_gap`, `completed_task_contradiction`, `premise_failure`, and `observation`.
- Decide where promoted findings live: append directly to canonical `TASKS.md`, write a review-specific `REVIEW-TASKS.md`, or generate an amendment proposal plus task queue.
- Preserve `z-amend` as the authority for mutating `SPEC.md`, `PLAN.md`, and `TASKS.md`; review-all should not silently perform spec edits.
- Decide how completed `[x]` work is represented when final review finds contradictions: fresh superseding tasks versus re-opening old tasks.
- Determine how much of the policy is shared by `/z-audit` and `/z-mr-review`, which already emit task-shaped artifacts but use different severity models and lifecycle assumptions.
- Keep the "one reason this might be wrong" safety rule before promoting any LLM finding into executable work.

## Recommended Next Step

Run full planning:

```text
/z-plan unify review finding promotion across review-all audit and mr-review using z-harness/unified-review-tasks/BRAINSTORM.md
```

A good full-plan outcome should produce `SPEC.md`, `PLAN.md`, and `TASKS.md` for a shared finding-promotion contract, with `/z-review-all` as the pilot and explicit compatibility rules for `/z-audit` and `/z-mr-review`.
