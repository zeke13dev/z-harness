# Skills

> Last updated: 2026-05-23
> Covers source: skills/z-amend/SKILL.md, skills/z-brainstorm/SKILL.md, skills/z-debug/SKILL.md, skills/z-do/SKILL.md, skills/z-implement-all/SKILL.md, skills/z-implement-next/SKILL.md, skills/z-improve/SKILL.md, skills/z-init-docs/SKILL.md, skills/z-maintain-docs/SKILL.md, skills/z-plan-light/SKILL.md, skills/z-plan-split/SKILL.md, skills/z-plan/SKILL.md, skills/z-research/SKILL.md, skills/z-review-all/SKILL.md, skills/z-stats/SKILL.md, skills/z-suggest-memory/SKILL.md, skills/z-test/SKILL.md

## Overview
The skills concept covers the core operational guidelines, detailed instructions, and checklists that govern z-harness plugin executions. Every slash command maps to a matching skill directory containing a SKILL.md file at its root. These markdown documents represent the ultimate repository of procedural discipline for plan creation, implementation steps, testing guidelines, and post-run retrospective analysis.

Skills structure the entire agent lifecycle, specifying how the orchestrator model must split plan scope, construct decision tables, review subagent outputs, preserve memories, run tests in isolated sandbox environments, and maintain accurate concept documentation.

## Key entry points
- `skills/z-amend/SKILL.md:1` — `z-amend` — Instructions for amending active spec/plan/task checklists consistently.
- `skills/z-brainstorm/SKILL.md:1` — `z-brainstorm` — Guide for parallel brainstorming, bias mapping, and seed framings.
- `skills/z-debug/SKILL.md:1` — `z-debug` — Method for regression isolation, hypothesis building, and post-mortems.
- `skills/z-do/SKILL.md:1` — `z-do` — Instructions for small targeted refactoring without explicit plans.
- `skills/z-implement-all/SKILL.md:1` — `z-implement-all` — Checklist workflow for implementing all tasks via subagents and codex peer review.
- `skills/z-implement-next/SKILL.md:1` — `z-implement-next` — Guide for executing the next pending task from the plan queue.
- `skills/z-improve/SKILL.md:1` — `z-improve` — Instructions for aggregate friction analysis and platform improvement plans.
- `skills/z-init-docs/SKILL.md:1` — `z-init-docs` — Guide for bootstrapping the two-tier human and LLM documentation system.
- `skills/z-maintain-docs/SKILL.md:1` — `z-maintain-docs` — Checklist for verifying doc drift, running audits, and cleaning stale memories.
- `skills/z-plan-light/SKILL.md:1` — `z-plan-light` — Simplified planning workflow designed for minor targeted enhancements.
- `skills/z-plan-split/SKILL.md:1` — `z-plan-split` — Steps for splitting large design spaces across parallel planning agents.
- `skills/z-plan/SKILL.md:1` — `z-plan` — Deep planning instructions covering premise checks, decisions, specs, and tasks.
- `skills/z-research/SKILL.md:1` — `z-research` — Guidelines for mapping codebase terrain and finding constraints before planning.
- `skills/z-review-all/SKILL.md:1` — `z-review-all` — Specifications for verifying the cumulative task diff against the master plan.
- `skills/z-stats/SKILL.md:1` — `z-stats` — Procedures for evaluating execution metrics, wall times, and model costs.
- `skills/z-suggest-memory/SKILL.md:1` — `z-suggest-memory` — Guide for authoring and cataloging lessons and invariants.
- `skills/z-test/SKILL.md:1` — `z-test` — Method for drafting rich semantic test plans linking test IDs back to tasks.

## How it interacts with others
- `commands` — Commands act as the user interface layer that reads, parses, and executes the rich checklists and phase loops defined in skills.
- `agents` — Skills define the exact parameters, systems prompts, tools, and execution models configured for subagents spawned during runs.
- `scripts` — Skill phase steps execute shell scripts to extract versions, log telemetry, sync remote trees, and build memories.

## Edge cases / gotchas
- Every skill implementation enforces strict idempotent execution rules, ensuring that re-running commands (e.g. docs initialization or plan amendment) modifies only the targeted resources without damaging pre-existing files or git history.
- Phase boundaries in skills require wrapping with log-phase.sh start/end commands to preserve complete telemetry and time-tracking metrics.

## Examples
- Reviewing instructions for plan amendments:
  Read `skills/z-amend/SKILL.md` to see the exact checklists and validation gates for updating active spec, plan, and task checklists.
