# Skills

> Last updated: 2026-05-25
> Covers source: skills/z-amend/SKILL.md, skills/z-audit-plan/SKILL.md, skills/z-brainstorm/SKILL.md, skills/z-debug/SKILL.md, skills/z-do/SKILL.md, skills/z-implement-all/SKILL.md, skills/z-implement-next/SKILL.md, skills/z-improve/SKILL.md, skills/z-init-docs/SKILL.md, skills/z-maintain-docs/SKILL.md, skills/z-plan-light/SKILL.md, skills/z-plan-split/SKILL.md, skills/z-plan/SKILL.md, skills/z-research/SKILL.md, skills/z-review-all/SKILL.md, skills/z-stats/SKILL.md, skills/z-suggest-memory/SKILL.md, skills/z-test/SKILL.md

## Overview

The skills concept covers the operational playbooks behind z-harness slash commands. Each `skills/<name>/SKILL.md` file defines a command's phases, telemetry, user gates, subagent dispatches, output artifacts, and hard safety rules. These files are the practical source of truth for how planning, research, debugging, implementation orchestration, final review, docs maintenance, memory authoring, and statistics reporting should run.

The current skill family has converged on a shared route-policy model. Planning and execution skills collect deterministic signals, call the advisory `planning-router` only when those signals conflict, write `route-decision.md`, emit `plan_route_decision`, preserve command-specific telemetry, present an AskUser handoff, and stop rather than auto-running the recommended target. The skills also assume the provider-registry agent names (`consultant-primary`, `consultant-secondary`, `reviewer`), shared scripts for path resolution and logging, and docs/memory maintenance through `doc-updater`, `/z-maintain-docs`, and `/z-suggest-memory`. Following the memory-self-improve-loop plan, three skills gained auto memory-review phases: `z-implement-all` (Phase 9), `z-review-all` (Phase 7), and `z-suggest-memory` gained a `--from-candidate-json` flag for piping review-agent output directly into the write pipeline. `z-stats` gained Phase 4b to surface recent memory-review activity alongside halt diagnostics.

## Key entry points

- `skills/z-amend/SKILL.md:1` — `z-amend` — Amends SPEC/PLAN/TASKS or FIX.md artifacts while preserving completed-task state; changed task blocks get complexity re-classified.
- `skills/z-audit-plan/SKILL.md:1` — `z-audit-plan` — Read-only audit of existing plan artifacts; verifies references/design, runs adversarial consultants, and routes contextually when no plan, plan changes, or doc drift blocks confidence.
- `skills/z-brainstorm/SKILL.md:1` — `z-brainstorm` — Cheap pre-plan ideation with three vendor-diverse ideators, identical scaffolding, anti-bias checks, and BRAINSTORM.md output.
- `skills/z-debug/SKILL.md:1` — `z-debug` — Heavy unknown-root-cause debugging flow with a wrong-tool gate, hypothesis rounds, fix-gate, verification, and mandatory post-mortem.
- `skills/z-do/SKILL.md:1` — `z-do` — Plan-less small-task runner with premise check, doc-fetcher grounding, inline implementation, mandatory reviewer gate, and route handoff when scope grows.
- `skills/z-implement-all/SKILL.md:1` — `z-implement-all` — Full task-queue orchestrator with `--tasks` fast path, tree-rooted MANIFEST/SHARED-CONCERNS gates, spec-precheck, implementer/reviewer batching, hard caps, compaction breakpoints, and Phase 9 auto memory-review after Finalize.
- `skills/z-implement-next/SKILL.md:1` — `z-implement-next` — Single-task implementation flow; selects Sonnet or Opus from the task's `**Complexity:**` stamp and performs one reviewer pass.
- `skills/z-improve/SKILL.md:1` — `z-improve` — Post-run retro that reads events/artifacts, proposes up to five harness improvements, applies accepted edits, and then calls `/z-suggest-memory`.
- `skills/z-init-docs/SKILL.md:1` — `z-init-docs` — Bootstraps docs/human and docs/llm, initializes INDEX files, writes the controlled TAGS.txt seed, and regenerates MEMORIES-FLAT.md.
- `skills/z-maintain-docs/SKILL.md:1` — `z-maintain-docs` — Refreshes stale docs via doc-updater, validates memory preservation, optionally audits proposals, surfaces stale memories and tag collisions, and regenerates MEMORIES-FLAT.md after writes.
- `skills/z-plan-light/SKILL.md:1` — `z-plan-light` — Lightweight planner for small fixes; produces FIX.md, runs bundled consultant review, implements inline, and uses a mandatory reviewer gate.
- `skills/z-plan-split/SKILL.md:1` — `z-plan-split` — Splits large topics into 2-6 clusters, enforces slug safety, plans leaves in parallel, reconciles file overlap, and writes MANIFEST.md plus SHARED-CONCERNS.md.
- `skills/z-plan/SKILL.md:1` — `z-plan` — Full rigorous planning flow with docs-freshness route gate, doc-fetcher/Explore grounding, decisions, bundled consult, SPEC/PLAN/TASKS, and complexity stamps.
- `skills/z-research/SKILL.md:1` — `z-research` — Terrain-mapping flow with cost gate, doc-fetcher-first scaffolding, up to three Explore calls, critique, citations, and a mandatory no-recommendation invariant.
- `skills/z-review-all/SKILL.md:1` — `z-review-all` — Final-gate review of cumulative diff against plan artifacts; includes resume state, optional TESTS.md suite gate, pre-consult compaction pause, REVIEW-TASKS promotion, and Phase 7 auto memory-review.
- `skills/z-stats/SKILL.md:1` — `z-stats` — Read-only shell/jq/awk diagnostic for progress, wall time, token estimates, halts, Phase 4b memory-review activity, stalls, version history, and next-command suggestions.
- `skills/z-suggest-memory/SKILL.md:1` — `z-suggest-memory` — Sole authoring path for `memories[]`; supports append/edit/delete, `--from-candidate-json` for review-agent output, validates memory schema, writes atomically, regenerates MEMORIES-FLAT.md, and optionally refreshes human docs.
- `skills/z-test/SKILL.md:1` — `z-test` — Semantic test planner that risk-ranks plan tasks, drafts non-trivial failure-class tests, consults both LLMs, writes TESTS.md, and cross-links task blocks.

## How it interacts with others

- `commands` — Commands are the user-facing surfaces that mirror or invoke these skill workflows. Route-policy changes must stay aligned between command markdown and skill markdown.
- `agents` — Skills define when to dispatch `doc-fetcher`, `doc-updater`, `planning-router`, `implementer`, `reviewer`, consultants, `review-agent`, and other subagents, plus the exact prompt contracts those agents receive.
- `scripts` — Skills rely on `plan-path.sh`, `log-event.sh`, `log-phase.sh`, `version.sh`, `regenerate-memories-flat.py`, and `run-memory-review.sh` for path resolution, telemetry, version stamping, memory flat-file sync, and memory-review orchestration.
- `multi-ide-exports` — Export pipelines consume these skill files to generate Cursor rules, Codex prompts/skills, and Antigravity skills/workflows, so source skill edits must propagate through exported surfaces.
- `providers-registry` — Skills refer to stable agent roles (`consultant-primary`, `consultant-secondary`, `reviewer`) while provider resolution happens behind those roles.

## Edge cases / gotchas

- Route handoffs are not command chaining. Skills write a route decision, emit telemetry, ask the user, and stop after presenting the next command.
- The `planning-router` is advisory only. Deterministic thresholds win, malformed output falls back to deterministic routing or AskUser, and loop-prevention blocks ping-pong route chains.
- `/z-audit-plan` is only valid when plan artifacts exist. If none are found, it writes a no-plan route decision toward `/z-plan` instead of fabricating an audit.
- `/z-do` may not route directly to `/z-plan-split`; larger work routes through `/z-plan`, `/z-plan-light`, `/z-research`, `/z-brainstorm`, `/z-fix`, or `/z-debug` based on signals.
- `/z-plan-split` keeps `cluster_id` (`C1`, `C2`, ...) separate from `cluster_slug` (the path segment). Swapping them breaks telemetry and on-disk layout.
- `/z-implement-all --tasks=<path>` bypasses normal slug/tree discovery and derives `$BASE` from the task file's parent; this is how promoted REVIEW-TASKS.md or MR-REVIEW.md queues are consumed.
- `/z-maintain-docs --audit` has a pre-audit compaction state file; fast-forward is allowed only if the stale concept set is unchanged.
- `memories[]` are never authored by doc-updater. `/z-suggest-memory` is the only supported mutation path, and both stale-memory deletes and memory edits use atomic JSON writes.
- Phase 9 (`z-implement-all`) and Phase 7 (`z-review-all`) are soft phases: all failure paths are silent skips — no halt, no retry. They call `run-memory-review.sh` to gate whether a review-agent dispatch is warranted.
- `--from-candidate-json` in `z-suggest-memory` bypasses Phases 3a–3f; the candidate object must have `type` and `text` fields or the skill returns `STATUS: bad_input`. Pass `-` as path to read from stdin.
- Phase 4b in `z-stats` reads `review_agent_call` events from metrics.jsonl; it is a read-only diagnostic and adds no writes.
- Adding a tag alias records TAGS.txt only; memory tags collapse on a later run.
- MEMORIES-FLAT.md regen is mandatory after doc writes or memory mutations.

## Examples

- To understand a route bailout from light mode, read `skills/z-plan-light/SKILL.md` Plan Route Check and Phase 1. The artifact to inspect is the run's `route-decision.md`.
- To debug why tree-rooted implementation refused to start, read `skills/z-implement-all/SKILL.md` Setup 2b for MANIFEST, SHARED-CONCERNS, partial-tree, and ack validation gates.
- To add a durable lesson after a debug or retro run, use `/z-suggest-memory`; do not edit `memories[]` directly and do not ask doc-updater to invent memory entries.
- To pipe a review-agent candidate directly into memory, run `/z-suggest-memory --concept <slug> --from-candidate-json <path> --source "incident:<run-id>"`.
- To see how many memory candidates the last implement-all run surfaced and how many were accepted, run `/z-stats` and check the Phase 4b output.
