# Commands

> Last updated: 2026-05-23
> Covers source: commands/z-amend.md, commands/z-audit.md, commands/z-brainstorm.md, commands/z-debug.md, commands/z-do.md, commands/z-implement-all.md, commands/z-implement-next.md, commands/z-improve.md, commands/z-init-docs.md, commands/z-maintain-docs.md, commands/z-plan-light.md, commands/z-plan-split.md, commands/z-plan.md, commands/z-research.md, commands/z-review-all.md, commands/z-skill-fix.md, commands/z-stats.md, commands/z-suggest-memory.md, commands/z-test.md

## Overview
The commands concept covers the complete set of slash commands that provide a structured CLI-like interface for executing z-harness tasks. These commands partition harness behaviors into clear logical operations—such as parallel brainstorming, deep pre-plan terrain research, comprehensive planning, targeted hotfixes, checklist implementation, automatic code review, test case generation, and documentation maintenance.

Each command is specified in a Markdown file under the commands/ directory, which details the strict multi-phase procedures, setup configurations, input arguments, telemetry logging expectations, and safety checks required for the orchestrator model to follow.

## Key entry points
- `commands/z-amend.md:1` — `z-amend` — Propagates target plan changes consistently across planning and task artifacts.
- `commands/z-audit.md:1` — `z-audit` — Executes multi-dimensional, rubrics-grounded code reviews in parallel.
- `commands/z-brainstorm.md:1` — `z-brainstorm` — Seeds plans via parallel candidate generation and bias checking.
- `commands/z-debug.md:1` — `z-debug` — Investigates regressions with hypothesis isolation and lightweight fix loops.
- `commands/z-do.md:1` — `z-do` — Performs small, plan-free coding changes with review safety gates.
- `commands/z-implement-all.md:1` — `z-implement-all` — Automates task implementation with parallel agents and peer reviews.
- `commands/z-implement-next.md:1` — `z-implement-next` — Implements the next pending task from the plan queue with review.
- `commands/z-improve.md:1` — `z-improve` — Suggests platform improvements based on aggregate post-run telemetry logs.
- `commands/z-init-docs.md:1` — `z-init-docs` — Bootstraps the human and LLM-tier two-tier documentation system in a repo.
- `commands/z-maintain-docs.md:1` — `z-maintain-docs` — Scans for doc drifts and auto-refreshes outdated concept documentation.
- `commands/z-plan-light.md:1` — `z-plan-light` — Handles targeted bug fixes and refactor plans without subagent overhead.
- `commands/z-plan-split.md:1` — `z-plan-split` — Decomposes high-scope plans across multiple sub-planners.
- `commands/z-plan.md:1` — `z-plan` — Runs the rigorous planning pipeline producing SPEC.md, PLAN.md, and TASKS.md.
- `commands/z-research.md:1` — `z-research` — Performs early codebase scans and terrain mapping before designing a plan.
- `commands/z-review-all.md:1` — `z-review-all` — Audits the entire task diff queue against the complete design spec.
- `commands/z-skill-fix.md:1` — `z-skill-fix` — Safely applies direct changes to z-harness platform skills.
- `commands/z-stats.md:1` — `z-stats` — Evaluates local runtime performance and token costs across past runs.
- `commands/z-suggest-memory.md:1` — `z-suggest-memory` — appends lessons-learned memories to targeted concept documentation files.
- `commands/z-test.md:1` — `z-test` — Drafts semantic test plans targeting edge cases and off-by-ones.

## How it interacts with others
- `skills` — Commands are the user-facing entry points that invoke the deeper instructions and checklists stored within the skills directory.
- `agents` — Commands instantiate and direct subagent teams (e.g. auditors, reviewers, implementers, plan consultants) to safely delegate heavy workloads.
- `scripts` — Commands execute core utility scripts to version resources, log telemetry timing, and synchronize sandboxes.

## Edge cases / gotchas
- Namespacing is strictly enforced via the `Z_HARNESS_SLUG` environment variable. Every shell call and subagent invocation must inherit this slug to target files in the correct run directory.
- Grounding checks during planning commands use `doc-fetcher` to consult the `docs/llm/INDEX.json` instead of reading files directly to preserve main context tokens.

## Examples
- Bootstrapping a repository's documentation:
  `/z-init-docs`
- Starting a fresh feature design phase:
  `/z-plan "Implement client-side request timeout handling"`
