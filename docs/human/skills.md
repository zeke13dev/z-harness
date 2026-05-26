# Skills

> Last updated: 2026-05-26
> Covers source: skills/z-amend/SKILL.md, skills/z-audit-plan/SKILL.md, skills/z-brainstorm/SKILL.md, skills/z-debug/SKILL.md, skills/z-do/SKILL.md, skills/z-implement-all/SKILL.md, skills/z-implement-next/SKILL.md, skills/z-improve/SKILL.md, skills/z-init-docs/SKILL.md, skills/z-maintain-docs/SKILL.md, skills/z-plan-light/SKILL.md, skills/z-plan-split/SKILL.md, skills/z-plan/SKILL.md, skills/z-research/SKILL.md, skills/z-review-all/SKILL.md, skills/z-stats/SKILL.md, skills/z-suggest-memory/SKILL.md, skills/z-test/SKILL.md, skills/z-update/SKILL.md, skills/z-uplift/SKILL.md

## Overview

The skills concept covers the operational playbooks behind z-harness slash commands. Each `skills/<name>/SKILL.md` file defines a command's phases, telemetry, user gates, subagent dispatches, output artifacts, and hard safety rules. These files are the practical source of truth for how planning, research, debugging, implementation orchestration, test-case planning, final review, docs maintenance, memory authoring, statistics reporting, self-update, and bulk codebase quality uplift should run.

The skill family shares a route-policy model: planning and execution skills collect deterministic signals, call the advisory `planning-router` only when signals conflict, write `route-decision.md`, emit `plan_route_decision`, present an AskUser handoff gate, and stop rather than auto-running the next command. Skills reference stable provider-registry agent roles (`consultant-primary`, `consultant-secondary`, `reviewer`) and shared scripts for path resolution and logging. Three skills have auto memory-review phases: `z-implement-all` (Phase 9), `z-review-all` (Phase 7), and `z-suggest-memory` (sole memory authoring path, supports `--from-candidate-json` for review-agent output). `z-stats` exposes Phase 4b to surface recent memory-review activity alongside halt diagnostics. `z-implement-next` implements one task at a time from a fresh context window, selecting the implementer model from the task block's `**Complexity:**` stamp. `z-test` is an optional planning-time step that produces a `TESTS.md` artifact via cross-LLM consult so tests land in the same diff as production code. `z-update` detects symlink vs tarball installs and refreshes the plugin safely. The newest skill, `z-uplift`, adds bulk codebase quality uplift by decomposing a repo into components, running a cross-cutting pass for global issues, dispatching per-component `auditor` subagents across `correctness`, `cleanliness`, and `design` dimensions in parallel, then driving sequential per-component implementation via `/z-implement-all --tasks=`.

## Key entry points

- `skills/z-amend/SKILL.md:1` — `z-amend` — Amends SPEC/PLAN/TASKS or FIX.md artifacts while preserving completed-task state; changed task blocks get complexity re-classified.
- `skills/z-audit-plan/SKILL.md:1` — `z-audit-plan` — Read-only audit of existing plan artifacts; verifies references/design, runs adversarial consultants, and routes contextually when no plan, plan changes, or doc drift blocks confidence.
- `skills/z-brainstorm/SKILL.md:1` — `z-brainstorm` — Cheap pre-plan ideation with three vendor-diverse ideators, identical scaffolding, mandatory anti-bias checks, and BRAINSTORM.md output.
- `skills/z-debug/SKILL.md:1` — `z-debug` — Heavy unknown-root-cause debugging flow with a wrong-tool gate (Phase 0), hypothesis rounds (3a round-1 + 3b adversarial), posterior scoring table, fix-gate (posterior == very_high + zero unexplained evidence), verification, optional MR-style review on the fix diff, and mandatory post-mortem.
- `skills/z-do/SKILL.md:1` — `z-do` — Plan-less small-task runner with premise check, doc-fetcher grounding, inline implementation, mandatory reviewer gate, and route handoff when scope grows.
- `skills/z-implement-all/SKILL.md:1` — `z-implement-all` — Full task-queue orchestrator with `--tasks` fast path for promoted artifacts, tree-rooted MANIFEST/SHARED-CONCERNS gates, spec-precheck, implementer/reviewer batching, hard caps, compaction breakpoints, and Phase 9 auto memory-review after Finalize.
- `skills/z-implement-next/SKILL.md:1` — `z-implement-next` — Single-task implementation with model selection from `**Complexity:**` stamp; reviewer gate; no auto-retry (re-invoke or use `/z-implement-all` for retry loop).
- `skills/z-improve/SKILL.md:1` — `z-improve` — Post-run retro that reads events/artifacts, proposes up to five harness improvements, applies accepted edits, and invokes `/z-suggest-memory` with a concept_hints list derived from touched file paths.
- `skills/z-init-docs/SKILL.md:1` — `z-init-docs` — Bootstraps docs/human and docs/llm, initializes INDEX files, writes the controlled TAGS.txt seed, and regenerates MEMORIES-FLAT.md.
- `skills/z-maintain-docs/SKILL.md:1` — `z-maintain-docs` — Refreshes stale docs via doc-updater (always with `dedup_tags: true`), validates memory preservation, optionally audits proposals with a pre-audit compaction state file, surfaces stale memories and tag collisions, and regenerates MEMORIES-FLAT.md after writes.
- `skills/z-plan-light/SKILL.md:1` — `z-plan-light` — Lightweight planner for small fixes; produces FIX.md, runs bundled consultant review, implements inline, and uses a mandatory reviewer gate.
- `skills/z-plan-split/SKILL.md:1` — `z-plan-split` — Splits large topics into 2-6 clusters, enforces slug safety, plans leaves in parallel, reconciles file overlap with path normalization and severity heuristics, writes MANIFEST.md plus SHARED-CONCERNS.md, and emits a strict early-exit telemetry contract for every exit path.
- `skills/z-plan/SKILL.md:1` — `z-plan` — Full rigorous planning flow with docs-freshness route gate, doc-fetcher/Explore grounding (Haiku by default; cap 3 Explores), decisions, bundled consult, SPEC/PLAN/TASKS, and parallel complexity-classifier dispatch.
- `skills/z-research/SKILL.md:1` — `z-research` — Terrain-mapping flow with cost gate, `--slug` flag parsing, doc-fetcher-first scaffolding, up to three Explore calls tracked as dispatched vs succeeded, bundled critique with per-consultant retry-once policy, and a mandatory no-recommendation invariant.
- `skills/z-review-all/SKILL.md:1` — `z-review-all` — Final-gate review with Pre-Phase 0 resume check (`.review_state.json` fast-forward), sanity checks, optional TESTS.md suite gate, Phase 3.7 pre-consult compaction breakpoint, two-pronged consultant review (implementation faithfulness + spec correctness), REVIEW-TASKS promotion, and Phase 7 auto memory-review.
- `skills/z-stats/SKILL.md:1` — `z-stats` — Read-only shell/jq/awk diagnostic for progress, wall time, token estimates, halts, Phase 4b memory-review activity, stalls, version history, and next-command suggestions.
- `skills/z-suggest-memory/SKILL.md:1` — `z-suggest-memory` — Sole authoring path for `memories[]`; supports append/edit/delete, `--from-candidate-json` for review-agent output, validates memory schema, writes atomically, regenerates MEMORIES-FLAT.md, and optionally refreshes human docs.
- `skills/z-test/SKILL.md:1` — `z-test` — Optional planning-time semantic test-case planner; risk-ranks tasks, drafts non-trivial test cases, runs cross-LLM consult (mode `test-cases`), writes TESTS.md, and cross-links TEST-NNN entries into TASKS.md so tests are implemented alongside production code.
- `skills/z-update/SKILL.md:1` — `z-update` — Updates the z-harness plugin; detects symlink (git pull) vs tarball (atomic swap) installs; emits `harness_updated` telemetry; reinstalls Codex plugin cache if applicable.
- `skills/z-uplift/SKILL.md:1` — `z-uplift` — Bulk codebase quality uplift: decomposes repo into components, runs a cross-cutting pass for global issues, dispatches per-component `auditor` subagents across correctness/cleanliness/design dimensions in parallel, and drives sequential implementation via `/z-implement-all --tasks=`. Triggers on "bulk codebase quality", "uplift the codebase", "audit the whole repo", "review every component".

## How it interacts with others

- `commands` — Commands are the user-facing surfaces that mirror or invoke these skill workflows. Route-policy changes must stay aligned between command markdown and skill markdown.
- `agents` — Skills define when to dispatch `doc-fetcher`, `doc-updater`, `planning-router`, `implementer`, `reviewer`, `consultant-primary`, `consultant-secondary`, `review-agent`, `complexity-classifier`, `auditor`, and other subagents, plus the exact prompt contracts those agents receive.
- `scripts` — Skills rely on `plan-path.sh`, `log-event.sh`, `log-phase.sh`, `version.sh`, `regenerate-memories-flat.py`, and `run-memory-review.sh` for path resolution, telemetry, version stamping, memory flat-file sync, and memory-review orchestration.
- `multi-ide-exports` — Export pipelines consume these skill files to generate Cursor rules, Codex prompts/skills, and Antigravity skills/workflows, so source skill edits must propagate through exported surfaces.
- `providers-registry` — Skills refer to stable agent roles (`consultant-primary`, `consultant-secondary`, `reviewer`) while provider resolution happens behind those roles.

## Edge cases / gotchas

- Route handoffs are not command chaining. Skills write a route decision, emit telemetry, ask the user, and stop after presenting the next command.
- The `planning-router` is advisory only. Deterministic thresholds win, malformed output falls back to deterministic routing or AskUser, and loop-prevention blocks ping-pong route chains capped at two entries.
- `/z-audit-plan` is only valid when plan artifacts exist. If none are found, it writes a no-plan route decision toward `/z-plan` instead of fabricating an audit.
- `/z-do` may not route directly to `/z-plan-split`; larger work routes through `/z-plan`, `/z-plan-light`, `/z-research`, `/z-brainstorm`, `/z-fix`, or `/z-debug` based on signals.
- `/z-plan-split` keeps `cluster_id` (e.g. `C1`, `C2`) separate from `cluster_slug` (the path segment). Swapping them breaks telemetry and on-disk layout. The `--clusters` flag supplies names only; scopes must still be derived per cluster.
- `/z-implement-all --tasks=<path>` bypasses normal slug/tree discovery and derives `$BASE` from the task file's parent directory; this is how promoted `REVIEW-TASKS.md` or `MR-REVIEW.md` queues are consumed.
- `/z-implement-next` is single-shot — no auto-retry on review failure. For retry, manually set the task stamp to `**Complexity:** high` and re-invoke, or use `/z-implement-all` which handles the retry loop.
- `/z-maintain-docs --audit` has a pre-audit compaction state file (`docs/llm/.maintain_docs_audit_state.json`); fast-forward is allowed only if the stale concept set is unchanged between invocations.
- `memories[]` are never authored by doc-updater. `/z-suggest-memory` is the only supported mutation path, and both stale-memory deletes and memory edits use atomic JSON writes.
- Phase 9 (`z-implement-all`) and Phase 7 (`z-review-all`) are soft phases: all failure paths are silent skips — no halt, no retry. They call `run-memory-review.sh` to gate whether a review-agent dispatch is warranted.
- `--from-candidate-json` in `z-suggest-memory` bypasses Phases 3a–3f; the candidate object must have `type` and `text` fields or the skill returns `STATUS: bad_input`. Pass `-` as path to read from stdin.
- Phase 4b in `z-stats` reads `review_agent_call` events from metrics.jsonl; it is a read-only diagnostic and adds no writes.
- Adding a tag alias records TAGS.txt only; memory tags collapse on a later run when doc-updater's step 3.5 reads the updated TAGS.txt.
- MEMORIES-FLAT.md regen is mandatory after doc writes or memory mutations.
- `/z-debug` auto-bail thresholds no longer include `>5 files` as a trigger; only cross-module impact, architectural change, or new public surface trigger escalation. The hard cycle cap is 5; soft warning fires at cycle 3.
- `/z-review-all` Pre-Phase 0 deletes a stale `.review_state.json` and starts fresh if HEAD has changed or artifact files are missing; if the file is corrupt (bad JSON, missing fields), it also deletes and restarts.
- `/z-plan` Phase 8 dispatches one `complexity-classifier` (Haiku) per task in parallel after all task blocks are written; the classifier returns `REASON: user-authored override` and leaves existing stamps alone if the user pre-authored a `**Complexity:**` line.
- `/z-research` strips `--slug=<value>` from `$ARGUMENTS` before computing `input_hash`; the cleaned question plus remaining flags are what get canonicalized.
- `/z-test` cross-task tests (entries with `task: null`) are not linked into TASKS.md; they are deferred to `/z-review-all` or standalone follow-up tasks. The cross-LLM consult step is non-skippable — trivial test rejection is the whole value.
- `/z-update` in tarball mode halts if `Z_HARNESS_RELEASE_URL` still points at `example.com`; no real public release URL exists yet. Symlink mode aborts on dirty plugin tree.
- `/z-uplift` requires `STYLE.md` at the repo root; if missing it halts and recommends `/z-style-init`. Pass `--no-style` to proceed with a degraded generic rubric. The `perf` dimension is excluded from default dimensions to bound cost; add it explicitly via `--dimensions=correctness,cleanliness,design,perf`.
- `/z-uplift` MANIFEST.md is the single resume authority; all state transitions are atomic via tmp-then-rename writes. Slug collision detection on component names requires resolution via AskUserQuestion before COMPONENTS.md is written.
- `/z-uplift` cross-cutting context lines (C-NNN) are filtered per component slug using exact-match on the `component:` field; global or mismatched slugs are silently excluded from per-component prompts.

## Examples

- To understand a route bailout from light mode, read `skills/z-plan-light/SKILL.md` Plan Route Check and Phase 1. The artifact to inspect is the run's `route-decision.md`.
- To debug why tree-rooted implementation refused to start, read `skills/z-implement-all/SKILL.md` Setup 2b for MANIFEST, SHARED-CONCERNS, partial-tree, and ack validation gates.
- To add a durable lesson after a debug or retro run, use `/z-suggest-memory`; do not edit `memories[]` directly and do not ask doc-updater to invent memory entries.
- To pipe a review-agent candidate directly into memory, run `/z-suggest-memory --concept <slug> --from-candidate-json <path> --source "incident:<run-id>"`.
- To see how many memory candidates the last implement-all run surfaced and how many were accepted, run `/z-stats` and check the Phase 4b output.
- To resume a `/z-review-all` run that was interrupted after building the cumulative diff, re-invoke `/z-review-all`; if `.review_state.json` is valid and HEAD is unchanged, Phases 0–3.5 are skipped automatically.
- To consume a promoted REVIEW-TASKS.md queue without full plan discovery, run `/z-implement-all --tasks=z-harness/<slug>/REVIEW-TASKS.md`.
- To implement one task at a time (manual pacing), use `/z-implement-next`; it does not auto-advance and keeps each task in a fresh context.
- To plan semantic test cases before implementation, use `/z-test` after `/z-plan`; the TESTS.md it produces is consumed by `/z-implement-all` automatically.
- To run a full-codebase quality pass, use `/z-uplift`; for a single component only, use `/z-audit <target>`; for branch-diff review before merging, use `/z-mr-review`.
- To update the z-harness plugin itself, run `/z-update`; it detects symlink vs tarball and picks the safe update path automatically.
