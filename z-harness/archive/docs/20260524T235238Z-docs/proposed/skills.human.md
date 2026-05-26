# Skills

> Last updated: 2026-05-24
> Covers source: skills/z-amend/SKILL.md, skills/z-brainstorm/SKILL.md, skills/z-debug/SKILL.md, skills/z-do/SKILL.md, skills/z-implement-all/SKILL.md, skills/z-implement-next/SKILL.md, skills/z-improve/SKILL.md, skills/z-init-docs/SKILL.md, skills/z-maintain-docs/SKILL.md, skills/z-plan-light/SKILL.md, skills/z-plan-split/SKILL.md, skills/z-plan/SKILL.md, skills/z-research/SKILL.md, skills/z-review-all/SKILL.md, skills/z-stats/SKILL.md, skills/z-suggest-memory/SKILL.md, skills/z-test/SKILL.md

## Overview

The skills concept covers the core operational guidelines, detailed checklists, and phase-by-phase procedures that govern every z-harness slash command execution. Each slash command maps to a matching skill directory containing a SKILL.md file. These documents are the ultimate authority on how planning, implementation, review, debugging, and documentation-maintenance runs are structured — including exact telemetry event shapes, subagent dispatch patterns, user-gate rules, and hard safety caps.

All skills share a common set of infrastructure assumptions established in the 2026-05-24 portable-harness migration: plan artifacts are resolved via `scripts/plan-path.sh` to `$Z_HARNESS_PLAN_DIR` (rather than hardcoded `z-harness/<slug>/` paths), cross-LLM consults use the provider-registry agents `consultant-primary` and `consultant-secondary`, and code review uses the `reviewer` agent. These agent names are stable identifiers that map to actual CLI vendors through the provider registry — skills never reference `gemini-consultant`, `codex-consultant`, or `codex-reviewer` directly.

## Key entry points

- `skills/z-amend/SKILL.md:1` — `z-amend` — Amend SPEC/PLAN/TASKS or FIX.md artifacts consistently. Phase 0 discovers the plan slug via `$Z_HARNESS_PLAN_DIR`. Complexity re-classification fires in Phase 6 for any task block whose body changed.
- `skills/z-brainstorm/SKILL.md:1` — `z-brainstorm` — Parallel pre-plan ideation: three vendor-diverse ideators (Claude + consultant-primary + consultant-secondary) with mandatory anti-bias check, producing BRAINSTORM.md with `chosen_framing`.
- `skills/z-debug/SKILL.md:1` — `z-debug` — Heavy hypothesis-tournament debug pipeline. Phase 0 wrong-tool gate redirects to `/z-fix` if user already has a hypothesis. Phases 3a/3b use rounds of parallel consultant hypothesis generation. Phase 9 post-mortem optionally invokes `/z-mr-review` and `/z-suggest-memory`.
- `skills/z-do/SKILL.md:1` — `z-do` — Lightest harness on-ramp for plan-less small tasks. Logs to `z-harness/adhoc/`. Codex review via `reviewer` agent is mandatory. Auto-bails at 3 files or non-obvious decisions.
- `skills/z-implement-all/SKILL.md:1` — `z-implement-all` — Orchestrates full task queue implementation. Supports `--tasks <path>` fast path for review artifacts (REVIEW-TASKS.md, MR-REVIEW.md). Tree-rooted plan support with MANIFEST.md/SHARED-CONCERNS.md validation gates and `--ack`/`--force-partial` overrides. Hard caps: `MAX_ATTEMPTS=2`, `MAX_TASK_WALL_MS=45min`, `MAX_DISTINCT_HALTS=3` per task.
- `skills/z-implement-next/SKILL.md:1` — `z-implement-next` — Single-task implementation. Picks implementer model from the task block's `**Complexity:**` stamp (`low|medium` → Sonnet, `high` → Opus). Single-shot; does not auto-retry on review failure.
- `skills/z-improve/SKILL.md:1` — `z-improve` — Post-run retro: analyzes `events.jsonl` friction signals, proposes ≤5 edits to z-harness files, applies accepted edits, then invokes `/z-suggest-memory` with derived `concept_hints`.
- `skills/z-init-docs/SKILL.md:1` — `z-init-docs` — Bootstraps the two-tier docs system. Phase 2 spawns `doc-updater` subagents per concept. Phase 4 writes `TAGS.txt` (15-tag controlled seed) and initializes `MEMORIES-FLAT.md` via `scripts/regenerate-memories-flat.py`.
- `skills/z-maintain-docs/SKILL.md:1` — `z-maintain-docs` — Refreshes stale docs. Phase 2 spawns `doc-updater` subagents with `dedup_tags: true`. Phase 3 surfaces stale memories and TAG_COLLISIONS. Phase 4.5 regenerates MEMORIES-FLAT.md after every write. Supports `--apply` and `--audit` flags.
- `skills/z-plan-light/SKILL.md:1` — `z-plan-light` — Lightweight planner for small fixes. Inline orchestrator implementation (no implementer subagent); Codex review via `reviewer` is non-negotiable. FIX.md is the only artifact. Auto-bails at >5 files or >2 non-obvious decisions.
- `skills/z-plan-split/SKILL.md:1` — `z-plan-split` — Pre-emptive scope splitter into 2-6 clusters. Enforces kebab-slug security gate. Phase 4 reconciles file-path overlaps from TASKS.md (canonical) against `FILES_TOUCHED` summary. Writes MANIFEST.md and SHARED-CONCERNS.md. MANIFEST uses stable `cluster_id` (C1…CN) for telemetry and `cluster_slug` for on-disk paths.
- `skills/z-plan/SKILL.md:1` — `z-plan` — Full rigorous planning pipeline. Docs-freshness gate checks `INDEX.json` staleness before Phase 1. Explore capped at 3 subagents. Phase 8 complexity-classifier stamps each task in parallel (Haiku).
- `skills/z-research/SKILL.md:1` — `z-research` — Terrain-mapping pre-plan research. Cost gate at Phase 0 (up to 3 Explores or 1). Phase 4 bundled cross-LLM critique. RESEARCH.md has mandatory `## No-recommendation` section with locked canonical text.
- `skills/z-review-all/SKILL.md:1` — `z-review-all` — Final-gate two-pronged cross-LLM review of cumulative diff. Phase 3.5 runs the full TESTS.md suite across affected modules before consulting LLMs (blocker if any test fails). Promotes findings to REVIEW-TASKS.md.
- `skills/z-stats/SKILL.md:1` — `z-stats` — Read-only diagnostic. Shell + jq + awk only; no subagent dispatch; no writes. Phases: plan progress, wall time per phase, token spend by model, recent halts, stall detection, plugin version history, suggested next command.
- `skills/z-suggest-memory/SKILL.md:1` — `z-suggest-memory` — Sole authoring path for `memories[]` in concept JSONs. Supports append/edit/delete modes. Validates against memory schema, writes atomically, regenerates MEMORIES-FLAT.md, optionally refreshes human-tier doc. Default outcome is Cancel.
- `skills/z-test/SKILL.md:1` — `z-test` — Semantic test-case planner between `/z-plan` and `/z-implement-all`. Risk-ranks tasks on domain criticality, surface area, and test-gap signal. Non-trivial failure classes required; trivial mechanical tests rejected by cross-LLM consult. Writes TESTS.md and cross-links `**Tests:**` lines into TASKS.md.

## How it interacts with others

- `commands` — Slash commands are the user-facing triggers that invoke the skill pipelines defined here.
- `agents` — Skills define the exact subagent types, models, and prompt shapes dispatched during runs. The provider-registry agents (`consultant-primary`, `consultant-secondary`, `reviewer`) abstract CLI vendor selection away from skill logic.
- `scripts` — Skills call `plan-path.sh` to resolve `$Z_HARNESS_PLAN_DIR`, `log-event.sh` for telemetry, `version.sh` for run stamps, `log-phase.sh` for timing, and `regenerate-memories-flat.py` for memory flat-file sync.
- `z-amend` remains the authority for applying review-generated spec-gap proposals; promoted amendment tasks in REVIEW-TASKS.md are inputs to the amendment workflow, not permission for implementers to edit planning artifacts autonomously.

## Edge cases / gotchas

- All skills resolve plan artifact paths via `$Z_HARNESS_PLAN_DIR` (set by `scripts/plan-path.sh`), not by hardcoded `z-harness/<slug>/` paths. Legacy flat layout (`z-harness/TASKS.md`) is still supported by most skills.
- `z-implement-all --tasks <path>` skips slug discovery, tree validation, and `--ack`/`--force-partial` checks. `$BASE` is derived from the task file's parent directory, so SPEC.md and archive paths resolve next to the promoted artifact.
- `z-debug` Phase 0 wrong-tool gate is non-skippable. If the user already has a hypothesis, the skill exits with a `/z-fix` recommendation rather than proceeding.
- `z-plan-split` uses two distinct identifiers per cluster: `cluster_id` (`C1`, `C2`, …) for telemetry payloads, and `cluster_slug` (kebab-case name) for on-disk directory paths. These must never be swapped.
- `z-implement-all` has unconditional hard caps (`MAX_ATTEMPTS=2` per task, 45-min wall clock per track, `MAX_DISTINCT_HALTS=3`) that override skip-marker lists and cannot be caught by static text matching alone.
- `z-suggest-memory` bootstraps `docs/llm/TAGS.txt` in Phase 0 if it is absent; `z-init-docs` Phase 4 also writes it. Both use the same 15-tag controlled seed and atomic write pattern.
- Phase telemetry (log-phase.sh start/end) is mandatory for every skill. Missing brackets make `/z-stats` wall-time analysis incorrect.

## Examples

- Reading the z-amend workflow to understand how review-generated amendment proposals are routed:
  Read `skills/z-amend/SKILL.md` Phase 4 (user gate) and Phase 6 (propagation) for the full checklist.
- Checking why `/z-implement-all` refused a tree-rooted plan:
  Read `skills/z-implement-all/SKILL.md` Setup 2b for the MANIFEST validation gate sequence (6 checks before any task runs).
