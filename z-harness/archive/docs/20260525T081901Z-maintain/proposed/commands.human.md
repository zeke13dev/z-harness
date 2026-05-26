# Commands

> Last updated: 2026-05-25
> Covers source: commands/z-amend.md, commands/z-audit.md, commands/z-audit-plan.md, commands/z-brainstorm.md, commands/z-debug.md, commands/z-do.md, commands/z-fix.md, commands/z-implement-all.md, commands/z-implement-next.md, commands/z-improve.md, commands/z-init-docs.md, commands/z-maintain-docs.md, commands/z-mr-review.md, commands/z-plan-light.md, commands/z-plan-split.md, commands/z-plan.md, commands/z-research.md, commands/z-review-all.md, commands/z-skill-fix.md, commands/z-stats.md, commands/z-suggest-memory.md, commands/z-test.md

## Overview

The commands concept covers the complete set of slash commands that provide a structured CLI-like interface for executing z-harness tasks. These commands partition harness behaviors into clear logical operations — such as parallel brainstorming, deep pre-plan terrain research, comprehensive planning, targeted hotfixes, checklist implementation, automatic code review, test case generation, and documentation maintenance.

Each command is specified in a Markdown file under the commands/ directory, which details the strict multi-phase procedures, setup configurations, input arguments, telemetry logging expectations, and safety checks required for the orchestrator model to follow.

## Key entry points

- `commands/z-amend.md:1` — `z-amend` — Propagates targeted plan changes consistently across planning and task artifacts.
- `commands/z-audit.md:1` — `z-audit` — Executes multi-dimensional, rubrics-grounded code reviews in parallel.
- `commands/z-audit-plan.md:1` — `z-audit-plan` — Read-only audit of existing SPEC/PLAN/TASKS artifacts before implementation; routes to `/z-plan` when plan artifacts are absent and to `/z-amend` or `/z-maintain-docs` after audit when appropriate.
- `commands/z-brainstorm.md:1` — `z-brainstorm` — Seeds plans via parallel candidate generation and bias checking.
- `commands/z-debug.md:1` — `z-debug` — Investigates regressions with hypothesis isolation and lightweight fix loops.
- `commands/z-do.md:1` — `z-do` — Performs small, plan-free coding changes with review safety gates.
- `commands/z-fix.md:1` — `z-fix` — Lightweight bug-fix for diagnosed issues: single light-fix consult, inline implementation, non-negotiable Codex review, optional post-mortem.
- `commands/z-implement-all.md:1` — `z-implement-all` — Automates task implementation with parallel agents and peer reviews; supports `--tasks=<path>` to consume promoted review artifacts such as REVIEW-TASKS.md or MR-REVIEW.md.
- `commands/z-implement-next.md:1` — `z-implement-next` — Implements the next pending task from the plan queue with review.
- `commands/z-improve.md:1` — `z-improve` — Suggests platform improvements based on aggregate post-run telemetry logs.
- `commands/z-init-docs.md:1` — `z-init-docs` — Bootstraps the human and LLM-tier two-tier documentation system in a repo.
- `commands/z-maintain-docs.md:1` — `z-maintain-docs` — Scans for doc drifts and auto-refreshes outdated concept documentation; `--audit` mode runs cross-LLM verification with a pre-audit compaction breakpoint.
- `commands/z-mr-review.md:1` — `z-mr-review` — Orchestrates multi-LLM code-quality review of a branch diff; writes P0-P4 findings to MR-REVIEW.md as a task-shaped promotion artifact consumable via `/z-implement-all --tasks`.
- `commands/z-plan-light.md:1` — `z-plan-light` — Handles targeted bug fixes and refactor plans without subagent overhead.
- `commands/z-plan-split.md:1` — `z-plan-split` — Decomposes high-scope plans across multiple parallel cluster-planners.
- `commands/z-plan.md:1` — `z-plan` — Runs the rigorous planning pipeline producing SPEC.md, PLAN.md, and TASKS.md.
- `commands/z-research.md:1` — `z-research` — Performs early codebase scans and terrain mapping before designing a plan.
- `commands/z-review-all.md:1` — `z-review-all` — Audits the entire task diff queue against the complete design spec; promotes accepted findings into REVIEW-TASKS.md; supports HEAD-aware fast-forward resume from pre-Phase-4 state.
- `commands/z-skill-fix.md:1` — `z-skill-fix` — Safely applies direct changes to z-harness platform skills.
- `commands/z-stats.md:1` — `z-stats` — Evaluates local runtime performance and token costs across past runs.
- `commands/z-suggest-memory.md:1` — `z-suggest-memory` — Appends lessons-learned memories to targeted concept documentation files.
- `commands/z-test.md:1` — `z-test` — Drafts semantic test plans targeting edge cases and off-by-ones.

## How it interacts with others

- `skills` — Commands are the user-facing entry points that invoke the deeper instructions and checklists stored within the skills directory.
- `agents` — Commands instantiate and direct subagent teams (e.g. auditors, reviewers, implementers, plan consultants) to safely delegate heavy workloads. Planning-family commands may call `planning-router` only for ambiguous route decisions after deterministic signals have been collected.
- `scripts` — Commands execute core utility scripts to version resources, log telemetry timing, and synchronize sandboxes.
- Review-family commands (`z-review-all`, `z-audit`, `z-mr-review`) share a finding-promotion pattern: preserve evidence in a report, promote only actionable findings into task-shaped artifacts, and let `/z-implement-all --tasks <path>` consume the approved survivors.
- Planning-family commands share a route policy: primary routes are `/z-do`, `/z-plan-light`, `/z-plan`, `/z-plan-split`, `/z-brainstorm`, and `/z-research`; contextual exits are `/z-audit-plan`, `/z-fix`, `/z-debug`, `/z-amend`, and `/z-maintain-docs`. A route writes `route-decision.md`, emits `plan_route_decision`, presents an AskUser handoff gate, and never auto-executes the recommended command.

## Edge cases / gotchas

- Namespacing is strictly enforced via the `Z_HARNESS_SLUG` environment variable. Every shell call and subagent invocation must inherit this slug to target files in the correct run directory.
- Grounding checks during planning commands use `doc-fetcher` to consult the `docs/llm/INDEX.json` instead of reading files directly to preserve main context tokens.
- `z-review-all` must not mutate `SPEC.md` or canonical `TASKS.md` directly. Spec gaps become amendment proposals and completed-task contradictions become superseding review tasks.
- `/z-audit-plan` is contextual only: it requires existing plan artifacts, remains read-only, and is not a substitute front door for `/z-plan`.
- Route chains prevent ping-pong between commands. If the chain already has two entries or the recommendation would immediately return to the prior command, commands ask the user to choose explicitly.
- `/z-implement-all` with `--tasks=<path>` bypasses slug discovery and tree-rooted MANIFEST validation entirely; `--ack` and `--force-partial` are no-ops in this mode.
- `/z-plan` and `/z-plan-split` no longer gate on `Z_HARNESS_PAUSE_AT_PCT`; the old usage-% pause guard was removed. Route to `/z-maintain-docs` if staleness threshold (`Z_HARNESS_DOC_STALENESS_THRESHOLD`, default 20%) is exceeded, via the normal route-decision flow.

## Compaction breakpoints

Long runs in `/z-implement-all` and cross-LLM consult phases in `/z-review-all` and `/z-maintain-docs --audit` accumulate significant orchestrator context. Deterministic compaction breakpoints are inserted at the highest-context-pressure boundaries so the user can clear context before it degrades subagent quality.

### `/z-implement-all` — task-count and wall-time triggers

(`commands/z-implement-all.md:162`)

Two env vars control when a breakpoint fires:

| Env var | Default | Meaning |
|---|---|---|
| `Z_IMPLEMENT_PAUSE_TASKS` | `5` | Pause after this many `[x]` completions since last pause |
| `Z_IMPLEMENT_PAUSE_MINUTES` | `30` | Pause after this many wall-clock minutes since last pause |

Either var set to `0` disables that trigger; both `0` disables `/z-implement-all` compaction breakpoints entirely.

The trigger fires **after each batch-settle**, strictly after: all in-flight tasks reach terminal status, the atomic TASKS.md write completes, the `batch_done` event is emitted, and all halt signals from the batch have been surfaced and resolved or deferred by the user. Only `[x]` completions count; retries and rollbacks do not. On trigger a `compaction_pause` event is emitted (fields: `trigger`, `tasks_since_pause`, `wall_minutes_since_pause`, `pending_remaining`) and the loop exits cleanly.

### `/z-review-all` — Pre-Phase-0 resume check + Phase 3.7 pre-consult breakpoint

(`commands/z-review-all.md:8`, `commands/z-review-all.md:147`)

Before entering Phase 0, the command checks for a prior state file at `$Z_HARNESS_PLAN_DIR/.review_state.json`. If the file exists, HEAD matches the stored `head_sha`, and the diff artifacts are still on disk, the command fast-forwards directly to Phase 4, skipping the expensive diff-build phases.

An unconditional Phase 3.7 breakpoint fires before the cross-LLM consultant batch spawns (between Phase 3.5 and Phase 4). No env var gate. An `AskUserQuestion` offers two options: "Pause for /clear" (exit, no state written) or "Proceed now" (write the slug-scoped state file at `$Z_HARNESS_PLAN_DIR/.review_state.json` and continue). On the next invocation, if HEAD matches and the diff file is still present, the command fast-forwards to Phase 4 without re-running Phases 0–3.5. The state file is deleted unconditionally at the end of Phase 6 to ensure subsequent invocations start fresh.

### `/z-maintain-docs --audit` — pre-audit-consult breakpoint

(`commands/z-maintain-docs.md:79`)

An unconditional breakpoint fires before the first audit-consultant batch dispatches (Phase 2.3). Same two-option `AskUserQuestion` pattern. State file: `docs/llm/.maintain_docs_audit_state.json` (not slug-scoped — `/z-maintain-docs` has no plan slug). Fast-forward triggers when the current stale concept set matches `stale_concepts_at_ack`; stale-set changes invalidate the marker and re-prompt. Plain (non-`--audit`) `/z-maintain-docs` runs are not affected.

### Why `/clear` over `/compact`

`/clear` is the recommended action at every breakpoint. The harness's durable state lives in TASKS.md and the slug-scoped state files — there is no cross-task state in orchestrator memory. Clearing reclaims more context than `/compact` with no safety loss. Use `/compact` only when you need to preserve chat history for debugging a specific task failure.

## Examples

- Bootstrapping a repository's documentation:
  `/z-init-docs`
- Starting a fresh feature design phase:
  `/z-plan "Implement client-side request timeout handling"`
- Applying promoted MR review findings as implementation tasks:
  `/z-implement-all --tasks=z-harness/mr-style-reviewer/MR-REVIEW.md`
