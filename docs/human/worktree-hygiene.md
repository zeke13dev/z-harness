# worktree-hygiene — cadence for cleaning up merged git worktrees

> Last updated: 2026-07-10
> Covers source: scripts/worktree-cleanup.sh, skills/z-reconcile/SKILL.md, scripts/reconcile.py, Makefile (`worktree-sweep`, `worktree-sweep-apply`), scripts/hermes/merge.py

## Why worktrees accumulate

Merging a branch and cleaning up its worktree are decoupled operations: `git merge`
(or a squash-merge PR) does not remove the worktree that produced it, and nothing
prompts you to do so afterward. `/z-reconcile`'s prune classifier historically only
trusted `git branch -r --merged` (remote-ancestor evidence), so it structurally missed
this repo's real workflow — local `f/claude/z/*` branches that are squash-merged or
never pushed. The result: worktrees pile up indefinitely even though their branches
are long since merged. `scripts/worktree-cleanup.sh` fixes the detection gap with
offline patch-identity (works without a remote, catches squash merges); this doc is
the cadence for using it.

## The three locations that must all be swept

A single repo's worktrees live in up to three separate parent directories — sweeping
only one gives a false sense of a clean tree:

1. `<repo>/.claude/worktrees/` — native `EnterWorktree` worktrees created in-repo.
2. `../<repo>-worktrees/` (external, sibling to the repo) — used by some workflows to
   keep worktrees out of the checked-out tree entirely.
3. `~/.hermes/worktrees/...` — Hermes-orchestrated workstream worktrees.

`scripts/worktree-cleanup.sh classify <repo-root>` and `make worktree-sweep` already
cover all three via a single `git worktree list` call — git tracks every worktree
regardless of parent directory — so you do not need to sweep each location by hand.

## Cadence

Run periodically (whenever you notice slow `git status`/IDE indexing, or on some
regular interval you choose — no auto-scheduling is wired in by default):

```
make worktree-sweep          # read-only: prints per-bucket counts
make worktree-sweep-apply    # dry-run: prints the exact remove commands, does not run them
```

or, for interactive per-item review:

```
/z-reconcile --prune-worktrees
```

**Always run these from the MAIN tree, never from inside a linked worktree.**
`scripts/worktree-cleanup.sh remove` refuses to remove the main worktree, but running
the sweep from a linked worktree risks resolving the wrong repo root for edge-case
git configurations, and mixes cleanup intent with whatever branch you're mid-task on.

## Safety model

The classifier sorts every worktree into one of four buckets:

| Bucket | Meaning | Auto-remove eligible? |
|---|---|---|
| `safe-remove` | Branch is merged (patch-identity match against local default) AND the tree is clean (no tracked changes) | Yes — `worktree-cleanup.sh remove` (no `--force` needed) |
| `merged-dirty` | Branch is merged but has uncommitted tracked changes | No — human review only |
| `unmerged-work` | Branch has commits not yet proven merged | No — human review only |
| `dead-pointer` | Worktree directory is gone but git still has a stale registration | Cleared by `git worktree prune` (via `remove`/`after-merge`) |

Only `safe-remove` is ever removed without `--force`. `merged-dirty` and
`unmerged-work` are always surfaced for a human decision — never force-removed by
`make worktree-sweep`, `worktree-sweep-apply`, or the classifier itself. `/z-reconcile
--prune-worktrees` asks for confirmation per item before removing anything.

## After every merge — clean up the worktree

Cleanup should always follow a successful merge immediately, not wait for the next
periodic sweep. Two call sites cover this:

- **Hermes** (`scripts/hermes/merge.py`): `merge_workstream()` invokes the shared
  helper automatically right after a successful `git merge --no-ff`, so a Hermes
  workstream's worktree and branch are gone by the time the merge call returns. No
  manual step needed here — Hermes is dormant/low-traffic today, but this is wired
  for correctness.
- **Native `EnterWorktree` / manual merge flow** (the actually load-bearing path in
  this repo): there is no single merge function to hook, so this is a manual (or
  orchestrator-scripted) step. Whenever a worktree branch is merged back into
  `main` — interactively or from an orchestrator command — immediately run:

  ```
  scripts/worktree-cleanup.sh after-merge <worktree-path> <branch>
  ```

  This asserts the branch is actually merged (offline patch-identity, refuses
  otherwise) and only then removes the worktree, deletes the branch, and prunes —
  the same safety-checked path the periodic sweep uses. If the worktree is already
  known-done-with (merged or otherwise) and just needs removing, `remove
  <worktree-path>` works too (same safety gate, no branch-merge assertion).

## Parallel-session-safety caveats

These matter more here than in most cleanup tasks, because worktree removal is
irreversible for anything not merged:

- **Never `git clean` the gitignored `z-harness/` plan-state tree.** A parallel
  session's in-progress plan lives there; `git clean -fdx` from any worktree of the
  same repo can wipe every session's plans at once. Worktree removal via
  `worktree-cleanup.sh` only ever touches the specific worktree path plus its merged
  branch — it never runs a blanket `git clean`.
- **Re-check `git rev-parse --abbrev-ref HEAD` before any commit**, including inside
  `worktree-cleanup.sh` call sites you script yourself. A parallel session can switch
  the shared main tree's branch out from under you between commands.
- Removing a worktree does not touch the branch of a *different* worktree, and the
  `remove` safety gate (dirty-or-unmerged refuses without `--force`) is the same
  regardless of which session invokes it.

## See also

- `scripts/worktree-cleanup.sh` — `classify` / `remove` / `after-merge` implementation
- `docs/human/active-plan-registry.md` — parallel-session coordination + the external-base
  design that keeps plan state safe from `git clean`
- `skills/z-reconcile/SKILL.md` — the interactive `--prune-worktrees` cleanup flow
