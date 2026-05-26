# Commands

> Last updated: 2026-05-25
> Covers source: commands/z-amend.md, commands/z-audit.md, commands/z-audit-plan.md, commands/z-brainstorm.md, commands/z-debug.md, commands/z-do.md, commands/z-fix.md, commands/z-implement-all.md, commands/z-implement-next.md, commands/z-improve.md, commands/z-init-docs.md, commands/z-maintain-docs.md, commands/z-mr-review.md, commands/z-plan-light.md, commands/z-plan-split.md, commands/z-plan.md, commands/z-research.md, commands/z-review-all.md, commands/z-skill-fix.md, commands/z-stats.md, commands/z-suggest-memory.md, commands/z-test.md

## Overview
The `commands` concept covers the slash-command specifications that drive z-harness workflows. Each command lives as a Markdown procedure under `commands/` and defines a user-facing orchestration path: planning, research, debugging, fixing, implementation, review, docs maintenance, memory authoring, audits, tests, stats, and skill repair.

The current command surface is centered on explicit routing and durable artifacts. Planning-family commands collect deterministic route signals, optionally consult `planning-router` only when signals conflict, write `route-decision.md`, emit `plan_route_decision`, and ask the user before switching; review-family commands preserve evidence and promote only actionable findings into task-shaped artifacts that `/z-implement-all --tasks <path>` can consume.

## Key entry points
- `commands/z-amend.md:1` — `z-amend` — Propagates approved changes through existing plan artifacts.
- `commands/z-audit.md:1` — `z-audit` — Runs read-only multi-dimension audits and emits task artifacts.
- `commands/z-audit-plan.md:1` — `z-audit-plan` — Audits existing SPEC/PLAN/TASKS and routes contextually.
- `commands/z-brainstorm.md:1` — `z-brainstorm` — Seeds planning with parallel ideation and anti-bias checks.
- `commands/z-debug.md:1` — `z-debug` — Runs heavy unknown-root-cause debugging with post-mortem.
- `commands/z-do.md:1` — `z-do` — Executes tiny plan-free changes with review gates.
- `commands/z-fix.md:1` — `z-fix` — Ships diagnosed bug fixes with consult and Codex review.
- `commands/z-implement-all.md:1` — `z-implement-all` — Orchestrates task queues with fresh subagents and reviewers.
- `commands/z-implement-next.md:1` — `z-implement-next` — Implements one pending task with model selection and review.
- `commands/z-improve.md:1` — `z-improve` — Retrospects one run and proposes harness improvements.
- `commands/z-init-docs.md:1` — `z-init-docs` — Bootstraps two-tier human and LLM documentation.
- `commands/z-maintain-docs.md:1` — `z-maintain-docs` — Refreshes stale docs and previews proposed updates.
- `commands/z-mr-review.md:1` — `z-mr-review` — Reviews branch diffs into ranked task-shaped findings.
- `commands/z-plan-light.md:1` — `z-plan-light` — Plans and ships small focused changes via FIX.md.
- `commands/z-plan-split.md:1` — `z-plan-split` — Splits large work into one-level cluster plans.
- `commands/z-plan.md:1` — `z-plan` — Produces SPEC.md, PLAN.md, and TASKS.md for coherent work.
- `commands/z-research.md:1` — `z-research` — Maps terrain with citations without recommending an approach.
- `commands/z-review-all.md:1` — `z-review-all` — Final-gate reviews cumulative implementation against the plan.
- `commands/z-skill-fix.md:1` — `z-skill-fix` — Diagnoses and patches misleading skill or command files.
- `commands/z-stats.md:1` — `z-stats` — Reports read-only run progress, timing, cost, and next step.
- `commands/z-suggest-memory.md:1` — `z-suggest-memory` — Delegates memory authoring to the memory skill.
- `commands/z-test.md:1` — `z-test` — Drafts semantic TESTS.md cases and links them to tasks.

## How it interacts with others
- `agents` — Commands dispatch specialized subagents such as implementers, reviewers, consultants, doc-updaters, doc-fetchers, auditors, cluster-planners, remote-runners, and the advisory `planning-router`.
- `scripts` — Commands rely on shared scripts for version stamping, event logging, phase timing, plan path resolution, memory flattening, and remote support.
- `skills` — Skills expose or wrap the command flows for different clients and are the main consumer of the command specifications.
- Review-family artifacts — `/z-audit`, `/z-review-all`, and `/z-mr-review` preserve evidence separately from promoted task artifacts; survivors are applied through `/z-implement-all --tasks <path>`.
- Planning-family route policy — `/z-plan`, `/z-plan-light`, `/z-plan-split`, `/z-research`, `/z-brainstorm`, and `/z-do` share route checks that record route artifacts and never auto-execute a different command.

## Edge cases / gotchas
- `/z-audit-plan` is contextual-only: with no existing plan artifacts it routes to `/z-plan` rather than pretending an audit can proceed.
- `planning-router` is advisory and only used after deterministic route thresholds fail to decide; malformed or unavailable output falls back to deterministic routing or an explicit user choice.
- Route chains prevent ping-pong. Once a chain has two entries, or a recommendation would return to the immediate prior command, the user must choose explicitly.
- `/z-implement-all --tasks=<path>` derives `BASE` from the tasks file directory and bypasses normal slug/tree discovery; this is how review promotion artifacts are consumed.
- `z-review-all` and `z-maintain-docs --audit` have pre-consult compaction breakpoints with state files so expensive consultant phases can resume safely.
- `/z-suggest-memory` is intentionally thin: it delegates to `skills/z-suggest-memory/SKILL.md`, which owns memory mutation and `MEMORIES-FLAT.md` regeneration.

## Examples
- Start a rigorous plan: `/z-plan "add request timeout handling"`
- Use the light path for a known small fix: `/z-plan-light "fix stale cache invalidation"`
- Debug an observed symptom with unknown cause: `/z-debug "orders double-submit after reconnect"`
- Apply promoted review findings: `/z-implement-all --tasks z-harness/<slug>/REVIEW-TASKS.md`
- Refresh stale docs after implementation: `/z-maintain-docs --audit`
