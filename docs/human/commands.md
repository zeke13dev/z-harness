# Commands

> Last updated: 2026-05-26
> Covers source: commands/z-amend.md, commands/z-audit.md, commands/z-audit-plan.md, commands/z-brainstorm.md, commands/z-debug.md, commands/z-do.md, commands/z-fix.md, commands/z-implement-all.md, commands/z-implement-next.md, commands/z-improve.md, commands/z-init-docs.md, commands/z-maintain-docs.md, commands/z-mr-review.md, commands/z-plan-light.md, commands/z-plan-split.md, commands/z-plan.md, commands/z-research.md, commands/z-review-all.md, commands/z-skill-fix.md, commands/z-stats.md, commands/z-suggest-memory.md, commands/z-test.md, commands/z-update.md, commands/z-uplift.md

## Overview

The `commands` concept covers the slash-command specifications that drive z-harness workflows. Each command lives as a Markdown procedure under `commands/` and defines a user-facing orchestration path: planning, research, debugging, fixing, implementation, review, docs maintenance, memory authoring, audits, tests, stats, skill repair, plugin updates, and bulk codebase uplift.

The command surface is organized around explicit routing, durable artifacts, and a closed-loop memory layer. Planning-family commands collect deterministic route signals, consult `planning-router` only when signals conflict, write `route-decision.md`, emit `plan_route_decision`, and ask the user before switching. Review-family commands preserve evidence separately from promotion artifacts and route actionable findings through `/z-implement-all --tasks`. Both `/z-implement-all` (Phase 9) and `/z-review-all` (Phase 7) close the loop by running `run-memory-review.sh` after each plan completes, dispatching a `review-agent` to surface memory candidates, and presenting them sequentially for user acceptance — accepted candidates are persisted via `/z-suggest-memory --from-candidate-json`. `/z-uplift` adds a tiered bulk-uplift path: it decomposes the repo into components, runs a cross-cutting pass, dispatches per-component audits, produces per-component TASKS.md files, and drives sequential implementation via `/z-implement-all`.

## Key entry points

- `commands/z-amend.md:1` — `z-amend` — Propagates approved changes through existing plan artifacts.
- `commands/z-audit.md:1` — `z-audit` — Runs read-only multi-dimension audits and emits task artifacts.
- `commands/z-audit-plan.md:1` — `z-audit-plan` — Audits existing SPEC/PLAN/TASKS and routes contextually.
- `commands/z-brainstorm.md:1` — `z-brainstorm` — Seeds planning with parallel ideation and anti-bias checks.
- `commands/z-debug.md:1` — `z-debug` — Runs heavy unknown-root-cause debugging with post-mortem.
- `commands/z-do.md:1` — `z-do` — Executes tiny plan-free changes with review gates.
- `commands/z-fix.md:1` — `z-fix` — Ships diagnosed bug fixes with consult and Codex review.
- `commands/z-implement-all.md:1` — `z-implement-all` — Orchestrates task queues with fresh subagents, reviewers, and auto memory review (Phase 9).
- `commands/z-implement-next.md:1` — `z-implement-next` — Implements one pending task with model selection and review.
- `commands/z-improve.md:1` — `z-improve` — Retrospects one run and proposes harness improvements.
- `commands/z-init-docs.md:1` — `z-init-docs` — Bootstraps two-tier human and LLM documentation.
- `commands/z-maintain-docs.md:1` — `z-maintain-docs` — Refreshes stale docs and previews proposed updates.
- `commands/z-mr-review.md:1` — `z-mr-review` — Reviews branch diffs into ranked task-shaped findings.
- `commands/z-plan-light.md:1` — `z-plan-light` — Plans and ships small focused changes via FIX.md.
- `commands/z-plan-split.md:1` — `z-plan-split` — Splits large work into one-level cluster plans.
- `commands/z-plan.md:1` — `z-plan` — Produces SPEC.md, PLAN.md, and TASKS.md for coherent work.
- `commands/z-research.md:1` — `z-research` — Maps terrain with citations without recommending an approach.
- `commands/z-review-all.md:1` — `z-review-all` — Final-gate reviews cumulative implementation against the plan, then auto-runs memory review (Phase 7).
- `commands/z-skill-fix.md:1` — `z-skill-fix` — Diagnoses and patches misleading skill or command files.
- `commands/z-stats.md:1` — `z-stats` — Reports read-only run progress, timing, cost, next step, and recent memory-review activity (Phase 4b).
- `commands/z-suggest-memory.md:1` — `z-suggest-memory` — Delegates memory authoring to the memory skill; accepts `--from-candidate-json` for automated candidate ingestion.
- `commands/z-test.md:1` — `z-test` — Drafts semantic TESTS.md cases and links them to tasks.
- `commands/z-update.md:1` — `z-update` — Updates the z-harness plugin to the latest version.
- `commands/z-uplift.md:1` — `z-uplift` — Tiered bulk codebase quality uplift: decompose, cross-cut, per-component audit, implement.

## How it interacts with others

- `agents` — Commands dispatch specialized subagents: implementers, reviewers, consultants, doc-updaters, doc-fetchers, auditors, cluster-planners, remote-runners, the advisory `planning-router`, and the `review-agent` (memory candidate generation). `/z-uplift` also dispatches `auditor` subagents in parallel per dimension per component.
- `scripts` — Commands rely on shared scripts for version stamping, event logging, phase timing, plan path resolution, memory flattening, remote support, and the `run-memory-review.sh` helper that gates Phase 9 / Phase 7.
- `skills` — Skills expose or wrap the command flows for different clients and are the main consumer of the command specifications.
- Review-family artifacts — `/z-audit`, `/z-review-all`, and `/z-mr-review` preserve evidence separately from promoted task artifacts; survivors are applied through `/z-implement-all --tasks <path>`.
- Planning-family route policy — `/z-plan`, `/z-plan-light`, `/z-plan-split`, `/z-research`, `/z-brainstorm`, and `/z-do` share route checks that record route artifacts and never auto-execute a different command.
- Memory loop — `/z-implement-all` Phase 9 and `/z-review-all` Phase 7 both call `run-memory-review.sh`, dispatch `review-agent`, and route accepted candidates into `/z-suggest-memory --from-candidate-json`. `/z-stats` Phase 4b surfaces `review_agent_call` events so the user can see memory-review history.
- Uplift pipeline — `/z-uplift` is a self-contained orchestration that sits above the planning and review families: it auto-decomposes the repo, calls consultant subagents for cross-cutting analysis, delegates per-component audits to auditor subagents, and then drives sequential implementation via existing `/z-implement-all` invocations. It gates on `STYLE.md` presence and doc-staleness before proceeding.

## Edge cases / gotchas

- `/z-audit-plan` is contextual-only: with no existing plan artifacts it routes to `/z-plan` rather than pretending an audit can proceed.
- `planning-router` is advisory and only used after deterministic route thresholds fail to decide; malformed or unavailable output falls back to deterministic routing or an explicit user choice.
- Route chains prevent ping-pong. Once a chain has two entries, or a recommendation would return to the immediate prior command, the user must choose explicitly.
- `/z-implement-all --tasks=<path>` derives `BASE` from the tasks file directory and bypasses normal slug/tree discovery; this is how review promotion artifacts are consumed.
- `z-review-all` and `z-maintain-docs --audit` have pre-consult compaction breakpoints with state files so expensive consultant phases can resume safely.
- `/z-suggest-memory` is intentionally thin: it delegates to `skills/z-suggest-memory/SKILL.md`, which owns memory mutation and `MEMORIES-FLAT.md` regeneration.
- Phase 9 (`z-implement-all`) and Phase 7 (`z-review-all`) are soft phases: all failure paths (malformed agent output, skipped helper, empty candidate array) exit silently without halting the run. They never interrupt implementation or review work.
- `--from-candidate-json` on `z-suggest-memory` accepts either a file path or `-` (stdin). It is used exclusively by the automated review-agent flow; manual callers should use the interactive path instead.
- `/z-stats` Phase 4b reads `review_agent_call` events from `metrics.jsonl`; if no memory-review phases have run yet, this phase outputs nothing.
- `/z-uplift` gates on `STYLE.md` before proceeding: if absent, it offers three options (run `/z-style-init` first, continue with degraded rubric, or abort). It does NOT auto-invoke `/z-style-init`.
- `/z-uplift` also gates on doc-staleness: if `stale_pct >= Z_HARNESS_DOC_STALENESS_THRESHOLD` (default 20%), it presents an `AskUserQuestion` to switch to `/z-maintain-docs`, continue anyway, or abandon. It does NOT auto-invoke `/z-maintain-docs`.
- `/z-uplift` is resumable via MANIFEST.md state: `[ ] pending` or `[~] auditing` rows resume at Phase 3; `[a] audited` rows resume at Phase 5. Use `--retry-bailed` to reset `[!] bailed` rows back to pending, and `--refresh-component <slug>` to re-audit a single named component.
- `perf` is excluded from `/z-uplift`'s default `--dimensions` set (`correctness,cleanliness,design`) to bound cost; pass `--dimensions=correctness,cleanliness,design,perf` to include it explicitly.
- The cross-cutting synthetic component (`<slug>-cross-cutting`) is inserted as the first MANIFEST row and is excluded from Phase 3 per-component audit iteration; it is handled separately in Phase 5.
- `/z-uplift` slug collision detection runs after decomposition: if two components share a slug, an `AskUserQuestion` is raised per collision before COMPONENTS.md is finalized and MANIFEST.md is written.

## Examples

- Start a rigorous plan: `/z-plan "add request timeout handling"`
- Use the light path for a known small fix: `/z-plan-light "fix stale cache invalidation"`
- Debug an observed symptom with unknown cause: `/z-debug "orders double-submit after reconnect"`
- Apply promoted review findings: `/z-implement-all --tasks z-harness/<slug>/REVIEW-TASKS.md`
- Refresh stale docs after implementation: `/z-maintain-docs --audit`
- Check memory-review history for a run: `/z-stats` (see Phase 4b output)
- Run bulk quality uplift across the whole repo: `/z-uplift`
- Uplift with perf dimension included: `/z-uplift --dimensions=correctness,cleanliness,design,perf`
- Resume a bailed uplift run: `/z-uplift --retry-bailed`
- Re-audit one component after fixing its issues: `/z-uplift --refresh-component <slug>`
