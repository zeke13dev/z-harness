# Known Limitations (v1)

> Last updated: 2026-05-27

- **No per-subagent wall-clock timeout.** `Agent()` does not expose a per-call
  timeout; subagents that hang block the entire run. User-facing escape: ctrl-c
  to abort.
- **No doc-fetcher caching across precontext and plan runs.** If you run
  `/z-research` and then `/z-plan` in the same slug, doc-fetcher is dispatched
  twice (once per command). Marked as a v2 candidate; the cost is low today.
- **`/z-plan-split`: no cross-cluster task parallelism.** `/z-execute`
  walks clusters sequentially in MANIFEST run-order; intra-cluster parallelism
  (N=3) is honored, cross-cluster is v2.
- **`/z-plan-split`: path-only overlap detection.** SHARED-CONCERNS.md is built
  from file-path intersections across cluster TASKS.md `**Files:**` lines. No
  semantic overlap detection (two clusters that touch disjoint files but conflict
  on the same in-memory invariant will not surface here).
- **`/z-plan-split`: no `--from-audit` / `--from-brainstorm` input chains.** The
  topic is taken verbatim from `$ARGUMENTS`; there is no structured handoff from
  `/z-audit`, `/z-research`, or `/z-brainstorm` artifacts. v2 candidate.
- **`/z-plan-split`: one-level recursion cap.** Cluster-planners refuse to write
  inside an existing MANIFEST.md tree, and `/z-execute` halts with
  `tree_depth_exceeded` if it finds a nested MANIFEST.md.
