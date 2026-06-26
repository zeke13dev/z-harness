# Adaptive INTENT — Lighter-than-SDD Operating Model

> Last updated: 2026-06-24
> Covers source: scripts/intent-schema.py, scripts/config.py, agents/intent-classifier.md, agents/task-tree-generator.md, skills/z-plan/SKILL.md, skills/z-execute/SKILL.md, skills/z-amend/SKILL.md, skills/z-review-all/SKILL.md, agents/implementer.md, agents/reviewer.md, docs/human/adaptive-intent.md

## Overview

Adaptive INTENT is the default planning mode (`workflow.planning_mode=intent`). It replaces the legacy SPEC/PLAN/TASKS up-front contract with a thinner frozen `INTENT.md`, an append-only `LEDGER.md`, and BFS-generated `TASKS.md` levels.

The design is thin-but-frozen, not mutable. `/z-plan` authors INTENT and an initial level-0 task batch; `/z-execute` freezes INTENT at the execution boundary, snapshots it to the archive on first freeze, bootstraps LEDGER, then generates and executes BFS levels until acceptance is met or a guard halts. Legacy plans remain legacy whenever `SPEC.md` exists.

## Key entry points

<!-- AUTO-START: entry-points -->
- `scripts/intent-schema.py:216` — `validate_intent` — validates INTENT frontmatter and required sections by level.
- `scripts/intent-schema.py:297` — `lint_criteria` — flags non-observable acceptance checklist items.
- `scripts/intent-schema.py:377` — `reopen_intent` — resets `frozen_at` to `pending` for `/z-amend`.
- `scripts/intent-schema.py:439` — `freeze_intent` — stamps or reports existing frozen ISO timestamp.
- `scripts/intent-schema.py:494` — `bootstrap_ledger` — creates LEDGER.md frontmatter idempotently.
- `scripts/intent-schema.py:635` — `evaluate_acceptance` — evaluates checklist criteria against LEDGER and cumulative diff.
- `skills/z-plan/SKILL.md:369` — planning-mode branch — reads `workflow.planning_mode` and level flags/config.
- `skills/z-plan/SKILL.md:385` — mode flags — `--full`, `--quick`, `--standard`, `--deep` override config.
- `skills/z-execute/SKILL.md:433` — SPEC-vs-INTENT mode detection — SPEC wins; INTENT used only when SPEC absent.
- `skills/z-execute/SKILL.md:468` — freeze and archive snapshot — first execution freezes INTENT and writes `INTENT.frozen.md`.
- `skills/z-execute/SKILL.md:540` — BFS guard config — reads `workflow.intent_bfs_level_cap` with fallback 6.
- `skills/z-execute/SKILL.md:674` — task-tree-generator dispatch — generates each BFS level from frozen INTENT and LEDGER.
- `skills/z-execute/SKILL.md:792` — INTENT mode context — injects `intent_snapshot:` and `ledger_path:` into implementer/reviewer prompts.
- `skills/z-amend/SKILL.md:241` — stale TASKS marker — sets `stale_reason: amended-intent` so tasks regenerate.
<!-- AUTO-END: entry-points -->

## Execution model

1. Detect mode after `BASE` is bound: `SPEC.md` -> legacy; else `INTENT.md` -> intent; else halt.
2. In intent mode, freeze INTENT and persist the freeze commit in the archive.
3. Generate a BFS level with `task-tree-generator`, passing unmet checklist items, prior LEDGER outcomes, level cap, budget, and task id start.
4. Execute that level via the existing per-task engine; no new task engine exists.
5. Inject `intent_snapshot:` and `ledger_path:` into every implementer/reviewer/retry prompt. Optional durable-tier paths (`kernel_path`, `invariants_path`, `style_path`) are forwarded when present.
6. Flush pending LEDGER content at level end, checkpoint done-set hash, evaluate acceptance, then either stop or increment level.

## Config surface

- `workflow.planning_mode`: `intent` (default) or `full`.
- `workflow.intent_level`: `auto`, `quick`, `standard`, or `deep`.
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

## Memories

<!-- DO NOT EDIT this section by hand — regenerated from docs/llm/adaptive-intent.json by doc-updater. Use /z-suggest-memory to add or edit memories. -->

_Note: no memories recorded for this concept yet._
