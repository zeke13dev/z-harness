# Z-harness improvement: surface /z-improve after orchestrated runs

**Date:** 2026-06-02
**Source:** direct user request during the multi-run retro session
**Status:** complete (uncommitted in worktree)

## Motivation
`/z-improve` is opt-in and was never surfaced anywhere, so retros never happened — which is exactly why the `improvements/` loop sat empty until this session. The user: *"z-improve should be suggested — the user is never nudged to do that after we merge and commit."*

## Decisions
- **Trigger:** end of orchestrated runs (in-harness), not a git/Claude-Code hook. Chosen for reliability — doesn't depend on hooks being installed, and the harness controls the run-end moment.
- **Gating:** only when the run logged friction signals. No nudge-fatigue on clean runs.
- **Shape:** a *suggestion*, never auto-firing — preserves z-improve's deliberate opt-in design.

## Changes
1. **`scripts/improve-nudge.sh` (new).** Read-only, fail-open. Resolves a run's `events.jsonl` (via `log-event.sh resolve-run-dir`, so it honours `Z_HARNESS_SLUG` / `Z_HARNESS_BASE_DIR` exactly like the writer), scans for friction-class signals (halt, doc drift, review retries, degraded consult, escalation, premise redirect, telemetry anomaly, spec drift, review escalations), and prints one `/z-improve <target>` line only if any fired. Prints nothing on a clean/missing run.
2. **`scripts/log-event.sh` (refactor).** Extracted run-dir resolution into a `resolve_run_dir` function and added a read-only `resolve-run-dir <run-id>` subcommand so the nudge helper reuses the canonical 5-tier path logic instead of duplicating it.
3. **Wiring:** `commands/z-implement-all.md` (Finalize step 2.5), `commands/z-review-all.md` (after `review_all_end`), `commands/z-do.md` (replaced the prior informal "if friction surfaced, suggest…" line with the deterministic helper call).

## Notable bug caught during implementation
The first refactor of `log-event.sh` routed the no-slug write path through `RUN_DIR="$(resolve_run_dir)"` — an extra command-substitution fork the original didn't have. Under macOS objc fork-safety this **segfaulted (exit 139)** on the write path, while HEAD wrote cleanly (exit 0). A second bug: `SLUG` was scoped `local` inside the function but is consumed later in event construction. Both fixed by having `resolve_run_dir` set the global `RUN_DIR` (run in the current shell, no subshell) and keeping `SLUG` global — making the write path byte-for-byte behaviour-equivalent to HEAD. Verified via a HEAD-vs-mine write comparison plus slug-path and end-to-end nudge tests.

## Diffs
`improvement-5-log-event-resolver.diff`, `improvement-6-nudge-helper.diff`, `improvement-7-nudge-wiring.diff`.
