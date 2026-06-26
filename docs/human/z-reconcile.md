# z-reconcile

> Last updated: 2026-06-24
> Covers source: skills/z-reconcile/SKILL.md, scripts/reconcile.py, scripts/plan-claim.sh

## Overview

`/z-reconcile` is a read-mostly workspace audit command. It surveys git worktrees, plan slugs/artifacts, active-plan registry records, claim locks, uncommitted work, and follow-up opportunities, then joins those surfaces into one consistency report.

A default run is zero mutations. Cleanup requires an explicit flag and an individual `AskUserQuestion` per item.

## Invocation

```text
/z-reconcile [--prune-worktrees] [--reap-registry] [--clean-locks] [--archive-plans] [--open-followups] [--save] [<save-path>]
```

`<save-path>` implies `--save`; default save target is `RECONCILE.md` at the repo root.

## Report sections

The Phase 1 report has six sections plus cross-reference flags:

1. Worktrees
2. Plans
3. Registry
4. Locks
5. Uncommitted
6. Follow-ups

Cross-reference flags: `merged_worktree_on_disk`, `complete_plan_no_merge_evidence`, `orphan_claim_lock`, `uncommitted_work_for_plan`.

## Classification model

`scripts/reconcile.py` contains testable classifiers; collection is done by the skill body.

Worktree precedence: `detached > dirty > unknown-remote > merged-uncertain > dead > active`. Only `dead` is auto-prune-eligible, and only under `--prune-worktrees`.

Plan classes: `precontext-only-aged`, `tasks-complete-unmerged`, `in-progress`, `stale-in-progress`. `tasks-complete-unmerged` is advisory only and may create follow-ups under `--open-followups`; it is never archived automatically.

Staleness uses latest activity (events/artifact mtimes) against a 14-day threshold, not raw directory age.

## Safety rules

- Worktree removal: only `dead`; per-item confirm before `git worktree remove`.
- Plan archive: only stale/precontext classes; move to `.abandoned/<slug>/` with sentinel, never delete.
- Lock cleanup: requires `plan-claim.sh reap-stale` status free/stale/corrupt, no live registry record, and dead daemon PID.
- Registry cleanup: individual `deregister --run-id`, never global reap.
- Follow-up creation: idempotent sink add for advisory findings.

## Key entry points

<!-- AUTO-START: entry-points -->
- `skills/z-reconcile/SKILL.md:20` — Phase 0 — parse flags and save path.
- `skills/z-reconcile/SKILL.md:43` — Phase 1 — collect facts and render zero-mutation report.
- `skills/z-reconcile/SKILL.md:58` — default branch resolution — dynamic origin/HEAD with main fallback.
- `skills/z-reconcile/SKILL.md:67` — worktree fact collection — status, remote reachability, unpushed, merge evidence.
- `skills/z-reconcile/SKILL.md:90` — plan fact collection — tasks, merge evidence, latest activity.
- `skills/z-reconcile/SKILL.md:154` — cross-reference join — calls `cross_ref_join` with all surfaces.
- `scripts/reconcile.py:258` — `classify_worktree` — six-class precedence and dead-only prune eligibility.
- `scripts/reconcile.py:344` — `classify_plan` — four plan classes with 14-day staleness default.
- `scripts/reconcile.py:404` — `cross_ref_join` — computes the four cross-reference booleans.
- `scripts/plan-claim.sh:416` — `reap-stale` statuses — free/stale/corrupt/held without acquiring or killing.
<!-- AUTO-END: entry-points -->

## Memories

<!-- DO NOT EDIT this section by hand — regenerated from docs/llm/z-reconcile.json by doc-updater. Use /z-suggest-memory to add or edit memories. -->

_Note: no memories recorded for this concept yet._
