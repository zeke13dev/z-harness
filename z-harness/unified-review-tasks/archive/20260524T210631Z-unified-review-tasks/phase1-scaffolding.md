# Phase 1 Scaffolding

## Topic

z-brainstorm Every time I run a review-all and there are amendments claude always asks me what to do (amend to spec inline, fix now, etc.). We need to unify this output into actionable tasks and make the decision once now. I am thinking that we might need to extend this idea to (possibly audit, though audit is closer to z-plan, mr-review, and any other places it might fit)

## Doc-Fetcher Synthesis

STATUS: partial - INDEX covers `commands`, `skills`, and `agents` for review, amendment, audit, and mr-review, but it does not record a cross-workflow policy for unifying review-all amendment decisions into actionable tasks. Caller should Explore for that gap.

### commands

The closest command-tier wiring is split: `z-review-all` validates cumulative diffs against spec, `z-amend` propagates targeted amendments across plan artifacts, `z-audit` coordinates multi-dimensional audits, and `z-mr-review` writes P0-P4 branch-review findings to `MR-REVIEW.md`. The docs imply actionable work should flow through plan/task artifacts rather than ad hoc report prose.

Key files: `commands/z-review-all.md`, `commands/z-amend.md`, `commands/z-audit.md`, `commands/z-mr-review.md`.

Invariants / gotchas: commands must log execution events and resolve plan dirs via `scripts/plan-path.sh`; large plans should delegate to subagents.

### skills

Skill docs say the operational discipline lives in SKILL checklists. Relevant skills are `z-review-all` for cumulative diff/spec review, `z-amend` for consistent SPEC/PLAN/TASKS mutation, and `z-implement-all` / `z-implement-next` for executing pending task files. This supports a task-unification design where findings are normalized into TASKS-shaped work before execution.

Key files: `skills/z-review-all/SKILL.md`, `skills/z-amend/SKILL.md`, `skills/z-implement-all/SKILL.md`.

Invariants / gotchas: all skills must be idempotent; phase telemetry must be logged; do not bypass skill checklists.

### agents

Agent-tier docs identify `mr-reviewer` as deduplicating consultant findings and returning structured findings JSON, and `auditor` as producing dimension-specific findings. `implementer` is the executor for discrete task files, so the missing unification layer likely belongs between review/audit finding outputs and implementer-consumable task artifacts.

Key files: `agents/mr-reviewer.md`, `agents/auditor.md`, `agents/implementer.md`.

Invariants / gotchas: subagents are isolated; subagents are read-only except explicitly authorized output files.

DRIFT WARNING: `agents` concept JSON references missing files: `agents/codex-consultant.md`, `agents/codex-reviewer.md`, `agents/gemini-consultant.md`.

## Explore Synthesis

Skipped because `Z_HARNESS_BRAINSTORM_EXPLORE` is unset.

## RESEARCH.md

No `z-harness/unified-review-tasks/RESEARCH.md` found.

## Input Hash

`59d9bcd2f9d74b6b`
