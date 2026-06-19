# z-review-all

> Last updated: 2026-06-19
> Covers source: commands/z-review-all.md

## Overview

`/z-review-all` is the final-gate cross-LLM review for a completed z-harness plan. It runs
two consultant subagents (Gemini + Codex) on the cumulative diff against the plan contract
(SPEC.md in legacy mode; frozen INTENT.md + LEDGER.md in INTENT mode). It surfaces:

- **Implementation drift** (Prong A): code changes that diverge from the spec/intent.
- **Spec/intent gaps** (Prong B): defects in the plan artifacts that only appear when looking at
  all tasks together.

Use after `/z-implement-all` completes. Per-task review is done by `/z-implement-all`; this
command catches issues that span tasks.

## Phase pipeline

| Phase | Name | Key output |
|-------|------|------------|
| 0 | Setup / Resume check | Slug resolution, state file, run brief init |
| 1 | Sanity check task status | All tasks complete guard |
| 2 | Determine base git ref | `BASE_REF` |
| 3 | Build cumulative diff | `cumulative.diff`, `cumulative.stat` |
| 3.5 | Full test suite (if TESTS.md) | Test results |
| 3.6 | Pre-review (opt-in) | Optional self-reviewer pass |
| 3.7 | Pre-consult compaction | `proceed` gate; consultant context prep |
| 4 | Spawn consultant subagents (parallel) | Prong A (drift) + Prong B (spec gaps) findings |
| 5 | Aggregate findings | `findings.md` |
| 6 | Promote findings to review tasks | `REVIEW-TASKS.md` |
| 6.5 | Auto-amend spec_gap findings | Automatic `/z-amend --skip-user-gate` per amendment proposal |
| 6.6 | Render amendment brief | `amendment-brief.md` in archive; registered in run-brief pipeline |
| 6.7 | Tier 2 context finalization | `tier2-context.json`, significance gate |
| 7 | Memory review | `review-agent` subagent dispatch |

## Class enum (line 716)

Every promoted finding must carry a **Class** field using this enum:

| Class | Meaning | Default action |
|-------|---------|---------------|
| `implementation_drift` | Code deviates from plan | Candidate fixup task |
| `spec_gap` | Plan artifact is incorrect | Amendment proposal → `/z-amend` |
| `completed_task_contradiction` | Finding contradicts completed work | Superseding task |
| `premise_failure` | Plan approach is questionable | Escalation section |
| `observation` | Informational only | Evidence artifact only |

This enum is shared by `/z-audit-plan` Phase 4 (which restricts to `spec_gap` and
`premise_failure` only).

## Phase 6.5 — Auto-amend spec_gap findings

After `REVIEW-TASKS.md` is built, Phase 6.5 automatically applies every `amendment_proposal`
finding (Class: `spec_gap`) via `/z-amend --skip-user-gate`. This is unconditional — the
cross-LLM review already validated the findings. Skipping the "do you want to amend?" question
per finding saves tokens without sacrificing correctness.

Rules:
- Only `amendment_proposal` tasks are auto-amended; `candidate_task` and `superseding_task` are
  left in REVIEW-TASKS.md for the user.
- Completed (`[x]`) tasks are not touched.
- Only plan artifacts (SPEC.md, PLAN.md, TASKS.md) are touched; code changes are never
  auto-implemented.
- An `auto-amend-log.md` is written to the archive and an `auto_amend_applied` event emitted per
  amendment.

## Phase 6.6 — Amendment brief

After Phase 6.5, Phase 6.6 renders a unified amendment brief via `scripts/amendment-brief.py`
from both finding streams:

- **`corrections`** — every `spec_gap` amendment proposal successfully auto-amended in Phase 6.5.
  Each entry carries `title` (task title from REVIEW-TASKS.md), `why` (source finding reference),
  and `target` (amended artifact path).
- **`approach_concerns`** — every `premise_failure` escalation from the `## Escalations` section
  of REVIEW-TASKS.md. Each entry carries `concern` (finding text) and optionally `affected`
  (affected scope/file).

The brief is written to `$BASE/archive/$RRUN/amendment-brief.md`. The Finalize phase's
`APPROACH_FILE` resolution **prefers** `amendment-brief.md` over the older approach seed, so the
amendment brief becomes the active presentation surface in the run-brief pipeline.

The `## Escalations` heading in REVIEW-TASKS.md is preserved as a structured archive record.
The run-brief pipeline (amendment-brief.md → approach bullets in run-brief.json → Finalize render)
is the active presentation layer.

Phase 6.6 is skipped entirely when both `corrections` and `approach_concerns` are empty — no brief
file is written and no pipeline entry is created.

## Key entry points

<!-- AUTO-START: entry-points -->
- `commands/z-review-all.md:1` — command definition — role, consultant subagents, INTENT vs legacy mode
- `commands/z-review-all.md:716` — Class enum — canonical finding classes; consumed by z-audit-plan Phase 4
- `commands/z-review-all.md:787` — Phase 6 — promote findings to REVIEW-TASKS.md; per-class promotion rules
- `commands/z-review-all.md:853` — Phase 6.5 — auto-amend amendment_proposal tasks; unconditional /z-amend --skip-user-gate
- `commands/z-review-all.md:924` — Phase 6.6 — build amendment brief JSON from corrections + approach_concerns; call amendment-brief.py; write to archive
- `commands/z-review-all.md:995` — Phase 6.6 skip gate — skip when both lists empty
- `commands/z-review-all.md:1132` — Finalize APPROACH_FILE — prefers amendment-brief.md over approach seed when present
<!-- AUTO-END: entry-points -->

## How it interacts with others

- `scripts/amendment-brief.py` — shared renderer called in Phase 6.6 to produce the amendment brief.
- `/z-amend --skip-user-gate` — called unconditionally in Phase 6.5 for each `amendment_proposal`.
- `/z-audit-plan` — shares the Class enum defined at line 716; both commands use the same
  `spec_gap`/`premise_failure` discriminator and the same `amendment-brief.py` renderer.
- `scripts/run-brief.sh` — run-brief pipeline populated by Phase 6.6 (APPROACH_FILE preference)
  and Finalize.
- `scripts/render-run-brief.py` — Finalize render; uses amendment-brief.md as approach source
  when present.

## Telemetry events

| Event | Phase | Payload fields |
|-------|-------|---------------|
| `auto_amend_applied` | 6.5 (per amendment) | `finding_id`, `severity` |
| `z_review_all_verdict` | Finalize | `status`, `drift_findings`, `spec_gap_findings`, `review_tasks`, `escalations`, `user_action` |
