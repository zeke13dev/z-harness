# z-reconcile

> Last updated: 2026-06-19
> Covers source: commands/z-reconcile.md, scripts/reconcile.py, scripts/plan-claim.sh

## Overview

`/z-reconcile` is a read-mostly workspace audit command that surveys the developer's z-harness environment — git worktrees, plan slugs and their artifacts, the active-plan registry, claim locks, uncommitted work, and follow-up entries — then cross-references them into a single consistency report. Each item is classified and given a recommended action.

The command's novel value is the *join* across these surfaces: no existing primitive finds worktrees whose branch is merged but still on disk, plans whose tasks are all complete but never merged, orphaned claim locks with no live registry record, or uncommitted work belonging to an abandoned plan. A default run is **zero mutations** — it only prints the report and exits. Every cleanup action is opt-in, per-category, and individually confirmed via `AskUserQuestion`.

## When to use it

- After a burst of parallel work to audit which worktrees and plans can be cleaned up.
- When you suspect stale claim locks or orphaned registry records are interfering with `plan-claim.sh`.
- To check whether any plan slugs have all tasks marked `[x]` but no merge evidence.
- To produce a persistent RECONCILE.md snapshot of workspace health.
- As a lightweight alternative to manual `git worktree list` + `active-plan-registry.py list` inspection.

## Invocation

```
/z-reconcile [--prune-worktrees] [--reap-registry] [--clean-locks] [--archive-plans] [--open-followups] [--save] [<save-path>]
```

With no flags the command runs in read-only mode and prints the report to stdout. The optional positional `<save-path>` implies `--save`.

## Flag semantics

| Flag | Phase | What it enables |
|---|---|---|
| `--prune-worktrees` | Phase 2 | Remove worktrees classified `dead` (per-item confirm via `AskUserQuestion` before each `git worktree remove`). |
| `--archive-plans` | Phase 3 | Move plans classified `precontext-only-aged` or `stale-in-progress` to `<base>/plans/.abandoned/<slug>/`; writes a `RECONCILE-ARCHIVED.md` sentinel. Never touches `tasks-complete-unmerged` plans. |
| `--clean-locks` | Phase 4 | Remove claim locks that are free/stale/corrupt per `plan-claim.sh reap-stale`, have no matching live registry record, and whose daemon PID is not alive (all three conditions required). |
| `--reap-registry` | Phase 5 | Deregister stale registry records individually via `active-plan-registry.py deregister --run-id`. Never calls the global `reap` subcommand (all-or-nothing). |
| `--open-followups` | Phase 6 | Create follow-up entries via `sink-add.sh` for advisory findings (plans classified `tasks-complete-unmerged`); idempotent via content-hash dedup. |
| `--save` | Phase 7 | Write the Phase 1 report to disk. Defaults to `RECONCILE.md` at the repo root. Overridden by the positional `<save-path>` argument. |

Multiple flags may be combined. Phase order is fixed (1 → 7); flags control which phases execute.

## Report format

The report has exactly six sections:

```
=== /z-reconcile report — <ISO timestamp> ===

## Worktrees
  <path>  [<class>]  <recommended action>  [surface-only | auto-prune-eligible]

## Plans
  <slug>  [<class>]  <recommended action>

## Registry
  <run_id>  slug=<slug>  status=<status>  hb_age=<age>  pid=<pid>

## Locks
  <slug>  lock=<lock_path>  reap=<reap_status>  daemon_alive=<true|false>
  [orphan — no live registry record]

## Uncommitted
  <slug>  <N> files with uncommitted changes attributed to this plan slug

## Follow-ups
  Advisory findings flagged:
    <slug>  tasks-complete-unmerged — all tasks [x] but no merge evidence

=== Cross-reference flags ===
  merged_worktree_on_disk:         <true|false>
  complete_plan_no_merge_evidence: <true|false>
  orphan_claim_lock:               <true|false>
  uncommitted_work_for_plan:       <true|false>
```

## Worktree classification taxonomy

Classification is performed by `scripts/reconcile.py classify_worktree` using pre-collected facts. The six classes are:

| Class | Meaning | Auto-prune-eligible? |
|---|---|---|
| `dead` | Clean working tree, no unpushed commits, HEAD is a commit-ancestry ancestor of the default branch. | Yes, with `--prune-worktrees` + per-item confirm. |
| `dirty` | Working tree has uncommitted changes. | Never. Surface-only. |
| `detached` | HEAD is detached; no branch reference exists. | Never. Surface-only. |
| `merged-uncertain` | Branch appears merged via squash or other ambiguous evidence (e.g. commit subject contains `(#…)` pattern). | Never. Surface-only. |
| `unknown-remote` | Remote was unreachable or the unpushed-check was skipped for any reason. The reachability probe uses `timeout 5 git ls-remote`; a timeout (exit 124) or any failure sets `remote_reachable=false`. | Never. Surface-only. |
| `active` | Does not meet the criteria for any other class; keeping in place is the safe choice. | Never. |

Only `dead` is ever offered for auto-prune. All others are `[surface-only]` regardless of what flags are passed.

The default branch is resolved dynamically via `git symbolic-ref refs/remotes/origin/HEAD`; it is never hardcoded.

## Plan classification taxonomy

Classification is performed by `scripts/reconcile.py classify_plan` using pre-collected plan facts. Staleness is evaluated as `max(latest events.jsonl timestamp for the slug, artifact mtime) vs 14-day threshold`. The four classes are:

| Class | Meaning | Archivable? |
|---|---|---|
| `precontext-only-aged` | Only INTENT/precontext artifacts present (no TASKS.md, LEDGER.md, events.jsonl) and past the staleness threshold. | Yes, with `--archive-plans`. |
| `tasks-complete-unmerged` | All tasks in TASKS.md are marked `[x]` but no merge/commit evidence was found. | No. Advisory only; offered as follow-up via `--open-followups`. |
| `in-progress` | Plan has recent activity and tasks; no other class applies. | No. |
| `stale-in-progress` | Plan is in-progress but past the staleness threshold (inactive for >14 days). | Yes, with `--archive-plans`. |

Plans under `<base>/plans/.abandoned/` are excluded from slug scans entirely. A `RECONCILE-ARCHIVED.md` sentinel written by `--archive-plans` is how subsequent runs recognize already-archived plans.

## Safety model

Safety is the dominant constraint. The command defaults to surfacing over auto-acting; every ambiguous classification is biased toward "keep / surface."

**Default run:** zero mutations. No worktree is removed, no registry record deleted, no lock file touched, no plan directory moved, no follow-up created.

**Per-item confirmation:** every mutation phase gates each individual item behind `AskUserQuestion`. There is no batch confirmation. A `yes` answer triggers the single action for that item; any other answer skips it.

**Worktree prune policy (non-negotiable):** only `dead` worktrees are offered for prune. A worktree must satisfy all three: clean working tree, no unpushed commits, and HEAD is a commit-ancestry ancestor of the default branch. `dirty`, `detached`, `merged-uncertain`, `unknown-remote`, and `active` worktrees are never offered.

**Lock removal policy (non-negotiable):** all three conditions must hold simultaneously before a lock is eligible for removal:
1. `plan-claim.sh reap-stale --slug <S>` reports `free`, `stale`, or `corrupt` (exit codes 1, 2, 3).
2. No matching live registry record exists for the slug.
3. The daemon PID parsed from the lock file is not alive (`kill -0` fails).

`rm` is never called on a lock file without a preceding `reap-stale` check. A live daemon PID blocks removal unconditionally.

**Plan archive policy:** `tasks-complete-unmerged` plans are never auto-archived even when `--archive-plans` is passed. Archiving moves contents (never deletes); `INTENT.md`, `SPEC.md`, `TASKS.md`, and `LEDGER.md` are all preserved in the destination.

**Registry reap policy:** individual deregistration only via `deregister --run-id`. The global `active-plan-registry.py reap` subcommand is never called.

**Registry unavailability:** if the registry is absent or fails, the command prints `(registry unavailable)` in the Registry section and continues.

**`.abandoned/` exclusion:** plans already under `<base>/plans/.abandoned/` are excluded from slug scans; `RECONCILE-ARCHIVED.md` sentinels mark them as recognized.

## --save convention

`--save` writes the Phase 1 report to `RECONCILE.md` at the repo root. To write to a different path, pass the path as a positional argument (which implies `--save`):

```
/z-reconcile --save
# writes to <repo-root>/RECONCILE.md

/z-reconcile /tmp/ws-audit.md
# writes to /tmp/ws-audit.md

/z-reconcile --save /home/user/project/audit.md
# writes to /home/user/project/audit.md
```

Without `--save`, the command only writes to stdout. This matches the `/z-debt --save` convention.

## Cross-reference flags

The report's `=== Cross-reference flags ===` section shows four booleans computed by `scripts/reconcile.py cross_ref_join`:

| Flag | Condition |
|---|---|
| `merged_worktree_on_disk` | At least one worktree's branch is `merged` into the default branch but is not classified `dead` (e.g. it's `dirty` and merged). |
| `complete_plan_no_merge_evidence` | At least one plan has all tasks `[x]` but no merge/commit evidence. |
| `orphan_claim_lock` | At least one claim lock has no matching live registry record. |
| `uncommitted_work_for_plan` | At least one plan slug has uncommitted file changes attributed to it (file paths overlap the plan's directory). |

## Edge cases / gotchas

- The remote-reachability probe runs as `timeout 5 git -C <path> ls-remote --exit-code origin HEAD`; a 5-second timeout (exit 124) or any failure sets `remote_reachable=false`. This cap is mandatory — the audit iterates every worktree, and a slow or unreachable remote must not hang the read-only report.
- `unknown-remote` fires when `has_unpushed` is `None` for ANY reason, not just an unreachable remote — safety-conservative: if the unpushed-check could not run, the worktree stays surface-only.
- `merged_worktree_on_disk` does NOT trigger for `dead` worktrees — those are already on the `--prune-worktrees` path. The flag surfaces merged worktrees blocked by other conditions (e.g. `dirty` + merged).
- Staleness uses `latest_activity_ts` (max of events.jsonl mtime and artifact mtimes), NOT directory creation or modification date.
- `tasks-complete-unmerged` is advisory only even when `--archive-plans` is passed — never offered for archiving.
- The Follow-ups section is always rendered even without `--open-followups`; the flag only controls whether entries are actually created via `sink-add.sh`.

## Related commands

- `/z-where` — workspace orientation and current-plan summary; `/z-reconcile` is modelled on its `runtime: c1` design.
- `/z-debt` — technical debt surface with `--save` convention (same save pattern).
- `/z-followup-list` — view follow-up entries created by `--open-followups`.

## Examples

Read-only audit (no mutations):

```
/z-reconcile
```

Audit and prune confirmed-dead worktrees (per-item confirm for each):

```
/z-reconcile --prune-worktrees
```

Full cleanup run (all mutation phases; each item individually confirmed):

```
/z-reconcile --prune-worktrees --archive-plans --clean-locks --reap-registry --open-followups
```

Save report to disk:

```
/z-reconcile --save
# -> writes RECONCILE.md at repo root

/z-reconcile ~/Desktop/ws-audit.md
# -> writes to specified path
```
