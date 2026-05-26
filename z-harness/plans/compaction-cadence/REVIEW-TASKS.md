---
artifact: review-tasks
slug: compaction-cadence
run_id: 20260525T081221Z-review
source_findings: archive/20260525T081221Z-review/findings.md
drift_findings: 0
spec_gap_findings: 1
escalations: 0
---

# Review Tasks — compaction-cadence

Findings promoted from `/z-review-all`. Delete any candidate you do not want fixed, then run:

`/z-implement-all --tasks z-harness/plans/compaction-cadence/REVIEW-TASKS.md`

## Candidate fixup tasks

_none — no Prong A drift met the promotion bar._

## Amendment proposals

### [ ] T-REV-001 — [major] Amend SPEC: document maintain-docs state file as repo-wide exception  `[ ]`
- **Class:** spec_gap
- **Disposition:** amendment_proposal
- **Source:** Prong B; both consultants flagged independently; finding "SPEC asserts slug-scoping but `/z-maintain-docs` has no slug"
- **Pushback:** This was already flagged in TASKS.md T006 Note at implementation time and the override is internally consistent; arguably only a one-line erratum is needed, not a structural amendment.
- **Files:** `z-harness/plans/compaction-cadence/SPEC.md`, `z-harness/plans/compaction-cadence/PLAN.md`
- **Depends on:** none
- **Acceptance:** Run `/z-amend "document that /z-maintain-docs --audit state file at docs/llm/.maintain_docs_audit_state.json is a documented exception to the slug-scoped-state-file invariant; /z-maintain-docs has no slug concept since it operates on the repo's docs/ tree"`. Resulting SPEC.md acknowledges the exception; PLAN.md's slug-scoping decision is annotated; completed-task state preserved.

## Superseding tasks

_none._

## Escalations

_none._

## Report-only observations

- **[minor] State file schema extras** — `/z-review-all` state file gained `run_id` and `cumulative_stat_path` fields beyond SPEC. Forward-compatible improvement; SPEC could be tightened to mention them as recommended but not required.
- **[minor] Tree-rooted compaction counter reset** — implementation resets `tasks_since_pause` per-cluster (sensible); SPEC silent.
- **[minor] Empty stale-concept set on `--audit`** — breakpoint fires regardless; SPEC silent (acceptable).
- **[minor] `--tasks=<path>` flag** added to `/z-implement-all` for promoted-artifact iteration is outside compaction-cadence SPEC scope; orthogonal feature.
- **T010 (qt-bot post-compact regression probe)** remains intentionally pending per the plan — requires real qt-bot runs through the new breakpoints before it can produce useful data.
