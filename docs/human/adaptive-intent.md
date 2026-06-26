# Adaptive INTENT — Lighter-than-SDD Operating Model

> Last updated: 2026-06-26
> Covers source: scripts/intent-schema.py, scripts/config.py, agents/intent-classifier.md, agents/task-tree-generator.md, skills/z-plan/SKILL.md, skills/z-execute/SKILL.md, skills/z-amend/SKILL.md, skills/z-review-all/SKILL.md, agents/implementer.md, agents/reviewer.md, docs/human/adaptive-intent.md

## Overview

Adaptive INTENT is the default planning mode (`workflow.planning_mode=intent`). It replaces the legacy SPEC/PLAN/TASKS up-front contract with a thinner frozen `INTENT.md`, an append-only `LEDGER.md`, and BFS-generated `TASKS.md` levels.

The design is thin-but-frozen, not mutable. `/z-plan` now makes the planning mode explicit before the hard cost gate: config and flags (`--full`, `--quick`, `--standard`, `--deep`) choose the recommended option, but the visible gate records the actual Intent-vs-Full SDD choice. Intent mode authors `INTENT.md` and an initial generated `TASKS.md`; `/z-execute` freezes INTENT at the execution boundary, snapshots it to the archive on first freeze, bootstraps LEDGER, then generates and executes BFS levels until acceptance is met or a guard halts. Legacy plans remain legacy whenever `SPEC.md` exists.

## Key entry points

<!-- AUTO-START: entry-points -->
- `scripts/intent-schema.py:216` — `validate_intent` — validates INTENT frontmatter and required sections by level.
- `scripts/intent-schema.py:297` — `lint_criteria` — flags non-observable acceptance checklist items.
- `scripts/intent-schema.py:377` — `reopen_intent` — resets `frozen_at` to `pending` for `/z-amend`.
- `scripts/intent-schema.py:439` — `freeze_intent` — stamps or reports existing frozen ISO timestamp.
- `scripts/intent-schema.py:494` — `bootstrap_ledger` — creates LEDGER.md frontmatter idempotently.
- `scripts/intent-schema.py:635` — `evaluate_acceptance` — evaluates checklist criteria against LEDGER and cumulative diff.
- `skills/z-plan/SKILL.md:431` — explicit planning-mode gate — config/flags set the recommendation; the visible gate records Intent vs Full SDD before the hard cost gate.
- `skills/z-plan/SKILL.md:446` — flag overrides — `--full`, `--quick`, `--standard`, `--deep` override config and cost-estimate shape.
- `skills/z-plan/SKILL.md:2262` — Phase 8 initial TASKS — intent mode dispatches `task-tree-generator` for level-0 `TASKS.md`; full mode hand-authors legacy tasks.
- `skills/z-plan/SKILL.md:2441` — Phase 8.4 post-artifact route check — may recommend `/z-plan-split`, `/z-sharpen`, or `/z-brainstorm`; never auto-dispatches.
- `skills/z-plan/SKILL.md:2480` — Phase 8.5 handoff producer — writes `HANDOFF.md` after TASKS and route checks.
- `skills/z-plan/SKILL.md:2578` — Phase 8.6 final handoff gate — user chooses fresh-session implementation, audit-first, stop with handoff, or amend.
- `skills/z-execute/SKILL.md:433` — SPEC-vs-INTENT mode detection — SPEC wins; INTENT used only when SPEC absent.
- `skills/z-execute/SKILL.md:468` — freeze and archive snapshot — first execution freezes INTENT and writes `INTENT.frozen.md`.
- `skills/z-execute/SKILL.md:540` — BFS guard config — reads `workflow.intent_bfs_level_cap` with fallback 6.
- `skills/z-execute/SKILL.md:674` — task-tree-generator dispatch — generates each BFS level from frozen INTENT and LEDGER.
- `skills/z-execute/SKILL.md:792` — INTENT mode context — injects `intent_snapshot:` and `ledger_path:` into implementer/reviewer prompts.
- `skills/z-amend/SKILL.md:241` — stale TASKS marker — sets `stale_reason: amended-intent` so tasks regenerate.
<!-- AUTO-END: entry-points -->

## Planning model

1. Resolve route signals and the recommended planning mode from config/flags, then surface the explicit Intent-vs-Full SDD gate before any expensive Agent dispatch.
2. In intent mode, choose or classify the intent level (`quick`, `standard`, `deep`), write `INTENT.md` with `frozen_at: pending`, and generate the initial canonical `TASKS.md` through `task-tree-generator`.
3. In full mode, write the legacy `SPEC.md`, `PLAN.md`, and `TASKS.md` artifact set. A pre-existing `SPEC.md` forces this path so legacy plans are never overwritten by INTENT.
4. After `TASKS.md` exists, Phase 8.4 may recommend `/z-plan-split`, `/z-sharpen`, or `/z-brainstorm` if the artifacts show too many tasks, question-heavy framing, or unsettled approaches. These are route recommendations only; the user must choose switch/continue/abandon and no command is auto-dispatched.
5. Phase 8.5 writes `HANDOFF.md` after TASKS sanity and route checks. Phase 8.6 then asks for exactly one next step: fresh-session `/z-execute`, audit-first `/z-audit-plan`, stop with handoff, or `/z-amend`.

## Execution model

1. Detect mode after `BASE` is bound: `SPEC.md` -> legacy; else `INTENT.md` -> intent; else halt.
2. In intent mode, freeze INTENT and persist the freeze commit in the archive.
3. Generate a BFS level with `task-tree-generator`, passing unmet checklist items, prior LEDGER outcomes, level cap, budget, and task id start.
4. Execute that level via the existing per-task engine; no new task engine exists.
5. Inject `intent_snapshot:` and `ledger_path:` into every implementer/reviewer/retry prompt. Optional durable-tier paths (`kernel_path`, `invariants_path`, `style_path`) are forwarded when present.
6. Flush pending LEDGER content at level end, checkpoint done-set hash, evaluate acceptance, then either stop or increment level.

## Config surface

- `workflow.planning_mode`: `intent` (default recommendation) or `full`; the visible mode gate records the actual per-run choice unless unattended/no-ask uses the recommendation.
- `workflow.intent_level`: `auto`, `quick`, `standard`, or `deep`; level flags override this and bypass the classifier.
- `workflow.intent_parallel_levels`: default `false`; allows parallel siblings within a BFS level only.
- `workflow.intent_bfs_level_cap`: runtime-read guard; absent from DEFAULTS, so empty/None falls back to 6.
- `workflow.hermes_enabled`: gates old Hermes cross-cluster/parallel machinery; does not by itself enable intent parallelism.

## Gotchas

- `SPEC.md` presence is binary and wins forever for that slug; adding INTENT does not switch an existing legacy plan.
- `frozen_at: pending` is valid before execution; do not remove it.
- `stale_reason: amended-intent` in TASKS frontmatter means regenerate on next execute.
- `.bfs_level_state` stores the last completed level and done-set hash; hash mismatch restarts from level 0.
- `evaluate_acceptance` treats unknown as unmet. A LEDGER citation without a cumulative diff is not enough.
- Cross-level parallelism is not supported; `intent_parallel_levels` is within-level only.
- `/z-plan` route checks and final gate options are non-auto-dispatch surfaces: they write route/handoff artifacts and ask the user, but they never invoke `/z-sharpen`, `/z-brainstorm`, `/z-audit-plan`, `/z-execute`, or `/z-amend` themselves.
- `HANDOFF.md` is produced after `TASKS.md`; it is an index and summary for the next session, not a replacement contract.

## Memories

<!-- DO NOT EDIT this section by hand — regenerated from docs/llm/adaptive-intent.json by doc-updater. Use /z-suggest-memory to add or edit memories. -->

_Note: no memories recorded for this concept yet._
