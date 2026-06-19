# z-test-prune

> Last updated: 2026-06-19
> Covers source: commands/z-test-prune.md

## Overview

`/z-test-prune` is a **read-only** test-suite pruning planner. It combats AI over-production of
tests by scanning an existing test suite, classifying low-value/redundant tests behind hard
safety guards, running a mandatory cross-LLM adversarial defend-pass, and emitting a curated
`TEST-PRUNE.md` deletion plan. It is the backward complement to `/z-test` (the forward,
plan-time test planner): `/z-test` adds tests; `/z-test-prune` proposes removing bloat.

The command **never deletes anything itself**. It produces a `TASKS.md`-shaped promotion artifact
(mirroring `/z-mr-review`'s `MR-REVIEW.md`) that the user curates, then applies via
`/z-implement-all --tasks=<path>/TEST-PRUNE.md`. Deleting a test removes coverage, so the
read-only contract plus the guards below are the load-bearing safety mechanism.

## Scope

- **Default:** the whole test suite. `--path <glob>` narrows; `--base <ref>` restricts to
  test files changed on the current branch.
- **Optional inputs:** `--coverage <report>` (upgrades redundancy proposals to High confidence
  when two tests provably cover identical lines/branches) and `--test-results <report>` (enables
  the currently-failing keep-guard). Both degrade gracefully when absent — the command never runs
  the suite or coverage tooling itself.
- **Large-suite guard:** past 50 discovered clusters the command warns and recommends narrowing
  scope, logging the cost rather than hiding it.

## Prunable categories

| # | Category | What it catches |
|---|----------|-----------------|
| 1 | Tautological / trivial | Asserts language/framework behavior; mock-vs-mock; "returns / no exception" with no further constraint |
| 2 | Coverage-blind | Exercises a branch/exception made unreachable by an earlier guard (added only for % coverage) |
| 3 | Redundant / subsumed | Another test covers the same failure-mode signature on the same path — decided by assertion+exception mapping and setup equivalence, **never** name/token similarity |
| 4 | Brittle internal-mock | Over-mocks **internal** business logic, or snapshot tests that break on refactor catching no bug (boundary mocks of I/O/network/time/DB are legitimate and exempt) |

## Hard keep-guards (never proposed for bulk deletion)

- The only test covering a SPEC/INTENT invariant (or tagged INVARIANT/MUST/DANGER).
- The only test on a high-risk / domain-critical path (money, ordering, position/PnL sign,
  state machine, schema migration).
- Integration-boundary tests (serialization, network/RPC, DB I/O or schema version,
  protocol/back-compat) — routed to a separate "confirm individually" section.
- One half of a symmetric positive/negative pair.
- The only test asserting a specific error code / exception.
- A currently-failing test (applied only when `--test-results` is supplied — a failure is a bug
  signal, not bloat).

## Ranking and safety

- **Single rank:** every proposal carries a confidence tier (High / Med / Low) — there is no
  P0-P4 severity axis. Medium and Low proposals are never auto-acted upon; the user confirms each.
- **Adversarial defend-pass:** `consultant-primary` + `consultant-secondary` argue *against* each
  proposed deletion. A prune survives only if neither can cite a concrete regression scenario
  (with code). Defended tests are dropped from `TEST-PRUNE.md`.
- **Consult-off:** when no consultant is configured, the defend-pass is skipped, tiers are left
  unchanged, and a mandatory disclosure banner is prepended to `TEST-PRUNE.md` warning that the
  candidates were not cross-LLM reviewed.

## Output

`TEST-PRUNE.md` — one curated block per prune action with the source test path, category,
confidence tier, evidence, the failure class preserved elsewhere, and acceptance criteria
(delete the test + re-run the full suite green). Integration-boundary candidates live in their
own section. Apply survivors with:

```
/z-implement-all --tasks=<plan-dir>/TEST-PRUNE.md
```

A full-suite re-baseline after applying is strongly recommended — `/z-implement-all`'s final gate
covers this.

## Relationship to other commands

- **`/z-test`** — forward test planner (drafts tests at plan time). `/z-test-prune` is its inverse.
- **`/z-mr-review`** — targets defensive bloat / over-engineering on a *diff*; `/z-test-prune`
  targets the accumulated *test suite*.
- **`/z-implement-all --tasks=`** — executes the curated deletion plan.
