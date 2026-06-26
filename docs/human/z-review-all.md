# z-review-all

> Last updated: 2026-06-24
> Covers source: skills/z-review-all/SKILL.md, docs/human/z-review-all.md

## Overview

`/z-review-all` is the final-gate review for a completed plan. It compares the cumulative diff against the plan contract (legacy SPEC/PLAN/TASKS or INTENT.frozen.md + LEDGER), runs Gemini/Codex final-review consultants, aggregates findings, and promotes actionable work into `REVIEW-TASKS.md`.

It is broader than `/z-execute` per-task review: it catches cross-task implementation drift, plan gaps, completed-task contradictions, and premise failures that only appear in aggregate.

## Finding promotion contract

Every promoted finding carries Source, Class, Severity, Evidence, Pushback, Files, Disposition, and Acceptance. Classes map to dispositions:

| Class | Disposition |
|---|---|
| `implementation_drift` | `candidate_task` fixup. |
| `spec_gap` | `amendment_proposal` routed through `/z-amend`. |
| `completed_task_contradiction` | `superseding_task`, never mutate completed `[x]` tasks in place. |
| `premise_failure` | escalation section. |
| `observation` | evidence/report only. |

If there are no actionable findings or escalations, the command writes `shipped.md` and omits REVIEW-TASKS.

## Phase 6.5 and 6.6

Phase 6.5 auto-applies every `amendment_proposal` regardless of severity. It uses `/z-amend --skip-user-gate`, logs `auto-amend-log.md`, emits `auto_amend_applied`, and never auto-implements code changes. Candidate fixups, superseding tasks, and premise-failure escalations remain for the user.

Phase 6.6 builds `{corrections, approach_concerns}`, calls `scripts/amendment-brief.py`, and writes archive `amendment-brief.md` unless both lists are empty. Finalize prefers that brief over `findings.md` for run-brief approach bullets.

## Key entry points

<!-- AUTO-START: entry-points -->
- `skills/z-review-all/SKILL.md:269` — Phase 3.6 — optional pre-review cycle gated by `runtime.pre_review`.
- `skills/z-review-all/SKILL.md:562` — Phase 4 — Gemini/Codex final-review consultants.
- `skills/z-review-all/SKILL.md:674` — finding promotion contract — required fields and Class enum.
- `skills/z-review-all/SKILL.md:755` — Phase 6 — writes `REVIEW-TASKS.md` or clean `shipped.md`.
- `skills/z-review-all/SKILL.md:821` — Phase 6.5 — auto-amends every amendable amendment proposal.
- `skills/z-review-all/SKILL.md:892` — Phase 6.6 — amendment brief renderer integration.
- `skills/z-review-all/SKILL.md:976` — Phase 6.6 skip gate — skip only when corrections and approach_concerns are both empty.
- `skills/z-review-all/SKILL.md:1005` — Phase 6.7 — finalizes tier2 context and significance gate.
- `skills/z-review-all/SKILL.md:1058` — Run Brief finalize — renders outcome/next/approach from run-brief.json.
- `skills/z-review-all/SKILL.md:1112` — `APPROACH_FILE` selection — prefers archive amendment-brief.md.
- `skills/z-review-all/SKILL.md:1179` — Phase 7 memory review — dispatches review-agent and optional axiom extractor.
<!-- AUTO-END: entry-points -->

## Invariants

- Final consultants are the production-grade review gate; pre-review is opt-in context only.
- `spec_gap` amendment proposals are auto-amended; no per-finding "do you want to amend?" prompt.
- `[x]` completed tasks are never mutated in place; contradictions become superseding tasks.
- Phase 6.6 is skipped only when both corrections and approach concerns are empty.
- `.review_state.json` is deleted after Phase 6.5 cleanup so the next run starts fresh.
- Run Brief is the completion surface; avoid independent duplicated prose.

## Memories

<!-- DO NOT EDIT this section by hand — regenerated from docs/llm/z-review-all.json by doc-updater. Use /z-suggest-memory to add or edit memories. -->

_Note: no memories recorded for this concept yet._
