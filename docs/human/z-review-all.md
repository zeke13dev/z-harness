# z-review-all

> Last updated: 2026-07-11
> Covers source: skills/z-review-all/SKILL.md, docs/human/z-review-all.md

## Overview

`/z-review-all` is the final-gate review for a completed plan. It compares the cumulative diff against the plan contract (legacy SPEC/PLAN/TASKS or INTENT.frozen.md + LEDGER), runs Gemini/Codex final-review consultants, aggregates findings, and promotes actionable work into `REVIEW-TASKS.md`.

It is broader than `/z-execute` per-task review: it catches cross-task implementation drift, plan gaps, completed-task contradictions, and premise failures that only appear in aggregate. A resume mechanism (pre-Phase-0 `.review_state.json` check) lets a run that reached the Phase 3.7 clear checkpoint fast-forward straight to Phase 4 on a later invocation, skipping the (potentially expensive) diff/test/pre-review phases when HEAD hasn't moved.

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

Phase 6.5 auto-applies every `amendment_proposal` regardless of severity. It invokes `/z-amend "<amendment text>"` inline (same session, not a subagent). Step 3 of the phase already skips any finding that would touch a `[x]` completed task, so `/z-amend`'s own Phase 4 gate always finds an empty "Touched-but-completed tasks" list for these amendments and auto-proceeds straight to Phase 5 without asking — no caller flag is needed to suppress the prompt. Phase 6.5 logs `auto-amend-log.md`, emits `auto_amend_applied`, and never auto-implements code changes. Candidate fixups, superseding tasks, and premise-failure escalations remain for the user.

Phase 6.6 builds `{corrections, approach_concerns}`, calls `scripts/amendment-brief.py`, and writes archive `amendment-brief.md` unless both lists are empty. Finalize prefers that brief over `findings.md` for run-brief approach bullets.

## Key entry points

<!-- AUTO-START: entry-points -->
- `skills/z-review-all/SKILL.md:70` — Pre-Phase 0 resume check — validates `.review_state.json` against current HEAD and fast-forwards straight to Phase 4 when a prior run reached the Phase 3.7 checkpoint and nothing has changed.
- `skills/z-review-all/SKILL.md:379` — Phase 3.6 — optional pre-review cycle gated by `runtime.pre_review`.
- `skills/z-review-all/SKILL.md:651` — Phase 4 — Gemini/Codex final-review consultants.
- `skills/z-review-all/SKILL.md:763` — finding promotion contract — required fields and Class enum.
- `skills/z-review-all/SKILL.md:844` — Phase 6 — writes `REVIEW-TASKS.md` or clean `shipped.md`.
- `skills/z-review-all/SKILL.md:910` — Phase 6.5 — auto-amends every amendable amendment proposal via `/z-amend` inline invocation, relying on `/z-amend`'s own empty-touched-completed-tasks gate to auto-proceed.
- `skills/z-review-all/SKILL.md:981` — Phase 6.6 — amendment brief renderer integration.
- `skills/z-review-all/SKILL.md:1065` — Phase 6.6 skip gate — skip only when corrections and approach_concerns are both empty.
- `skills/z-review-all/SKILL.md:1094` — Phase 6.7 — finalizes tier2 context and significance gate.
- `skills/z-review-all/SKILL.md:1147` — Run Brief finalize — renders outcome/next/approach from run-brief.json.
- `skills/z-review-all/SKILL.md:1201` — `APPROACH_FILE` selection — prefers archive amendment-brief.md.
- `skills/z-review-all/SKILL.md:1268` — Phase 7 memory review — dispatches review-agent and optional axiom extractor.
<!-- AUTO-END: entry-points -->

## How it interacts with others

- `z-execute` — produces the TASKS.md/LEDGER.md/SPEC.md (or frozen INTENT) that `/z-review-all` diffs against, recommends `/z-review-all` as its own next step, and later consumes `REVIEW-TASKS.md` via `/z-execute --tasks REVIEW-TASKS.md`.
- `z-amend` — Phase 6.5 invokes `/z-amend "<amendment text>"` inline (same session) to auto-apply `spec_gap` amendment proposals; since Phase 6.5 already excludes findings touching `[x]` completed tasks, `/z-amend`'s Phase 4 gate finds an empty "Touched-but-completed tasks" list and auto-proceeds without a user prompt (no `--skip-user-gate` flag — that flag was removed corpus-wide).
- `amendment-brief` (`scripts/amendment-brief.py`) — Phase 6.6 renders `corrections` + `approach_concerns` into `amendment-brief.md`, shared with `z-audit-plan`.
- `active-plan-registry` — the shared plan-discovery/base-ref machinery this command reuses in Phase 0/2.
- `run-brief-contract` — Finalize and halt-finalize both render through the shared run-brief fragment; never author independent completion prose.
- `tier2-doc-rationale` — Phase 6.7 finalizes `tier2-context.json` and, when significant, recommends `/z-doc-rationale` next; that command requires a `tier2-context.json` to exist.
- `review-agent` — Phase 7 dispatches this subagent (plus optional `axiom-extractor`) to propose memory candidates from the cumulative diff.
- `z-maintain-docs` — recommended as the next step after a clean (`shipped_clean`) review.

## Edge cases / gotchas

- Phase 6.5's heading says "severity-based" but the current rule auto-amends blocker/major/minor amendment proposals alike — severity does not gate the decision.
- Phase 6.5 no longer passes a `--skip-user-gate` flag to `/z-amend` (that flag was removed corpus-wide). The same no-prompt behavior is now achieved because Phase 6.5's step 3 already filters out any amendment touching a completed `[x]` task before invoking `/z-amend`, so `/z-amend`'s Phase 4 "Touched-but-completed tasks" gate is always empty for these calls and auto-proceeds.
- A clean review writes `shipped.md` and omits `REVIEW-TASKS.md`; Phase 6.5/6.6 then have nothing to do and are skipped without logs.
- `amendment-brief.md` lives under `archive/$RRUN/`, not `$BASE` directly.
- Phase 7 memory review can dispatch `axiom-extractor` alongside `review-agent` when an `AXIOM_READY` line is present in `run-memory-review.sh` output; the axiom-extractor only proposes candidates, never auto-approves.
- `.review_state.json` resume logic treats a corrupt/missing-field/stale (HEAD-mismatched) state file as a signal to delete and re-run fully from Phase 0 — it never silently trusts a partially-valid state file.
- Phase 0 aborts early if a follow-up consumer is actively running against the same project sink, to avoid racing shared state.

## Memories

<!-- DO NOT EDIT this section by hand — regenerated from docs/llm/z-review-all.json by doc-updater. Use /z-suggest-memory to add or edit memories. -->

_Note: no memories recorded for this concept yet._
