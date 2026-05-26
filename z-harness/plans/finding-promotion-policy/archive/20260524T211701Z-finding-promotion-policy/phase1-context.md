# Phase 1 Context

## Problem

`/z-review-all` currently ends by asking the user what to do with final-review findings: open drift fixup tasks, patch the spec inline, do both, ship as-is, or reject and re-plan. That means the workflow-shaping decision happens late and repeatedly, even though the desired direction from `z-harness/unified-review-tasks/BRAINSTORM.md` is to normalize review findings into durable evidence plus candidate task/amendment artifacts and let the user make one artifact-level decision.

## Context

The nearby commands already point in different directions. `commands/z-review-all.md` aggregates Prong A implementation drift and Prong B spec gaps, then asks the user which action mode to take. `commands/z-audit.md` is already closer to the target shape: it emits `REPORT.md`, then promotes actionable findings into a `/z-implement-all`-compatible `TASKS.md`, with minimal `SPEC.md` and `PLAN.md` scaffolding. `commands/z-mr-review.md` also emits a task-shaped `MR-REVIEW.md` and tells the user to delete unwanted findings before feeding survivors to `/z-implement-all`. `skills/z-review-all/SKILL.md` mirrors the older interactive behavior, while `skills/z-amend/SKILL.md` preserves the important invariant that spec/plan/task mutations require an explicit amendment gate and completed tasks must be superseded rather than silently edited.

## Light-Mode Threshold Check

This is not a light-mode fix. A real plan needs to reconcile at least these surfaces:

- `commands/z-review-all.md`
- `skills/z-review-all/SKILL.md`
- `commands/z-audit.md`
- `commands/z-mr-review.md`
- `skills/z-amend/SKILL.md`
- likely exported Cursor/Codex/Antigravity command and skill copies
- possibly `agents/implementer.md` or task-consumer docs if candidate review tasks become first-class inputs

The change also includes more than two non-obvious decisions: the artifact contract, whether candidate tasks live in `TASKS.md` or a review-specific file, how spec gaps route through `z-amend`, how to preserve completed-task supersession, and how much to align `z-audit`/`z-mr-review` versus only piloting in `z-review-all`.
