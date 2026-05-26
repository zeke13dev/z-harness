## Codex consultation: plan-review on compaction-cadence

**Key findings:**

1. **Invariant 2 is not true today.** Current `/z-implement-all` mostly passes durable paths, not cross-task memory. Retry state is task-local only. But nothing enforces "signals needed downstream are persisted to `TASKS.md` before `[x]`" — mark-done only says add a one-line completion note and write `SUMMARY.md`. So the invariant is a new requirement, not a property guaranteed by current dispatch.

2. **Batch-settle trigger is conceptually okay, but underspecified.** Current parallelism declares single-writer atomic `TASKS.md` updates after batch completion, so no true race if the pause check runs after that write. The fragility is wording mismatch: the SPEC mentions terminal statuses `[!]`/`[f]`, but current command only defines `[ ]`, `[~]`, `[x]` and skip handling. The patch must explicitly place the check after the batch's single `TASKS.md` write and `batch_done`.

3. **Marker resume is broken/missing as planned.** Current `/z-review-all` always creates a fresh `RRUN`, then writes fresh `cumulative.diff`. There is no way to rediscover a prior run's marker/artifacts. The plan must define "active paused review run" discovery.

The marker should only be written on "Proceed now"; if written on "Pause", skipping AskUserQuestion would be wrong. Even on "Proceed", stale diff is possible if HEAD changes after marker creation. Store `base_ref` and `head_sha`; reuse artifacts only when `HEAD` matches, otherwise rebuild Phase 3/3.5.

For `/z-maintain-docs --audit`, ack is intended per-run, but current command has no concrete `RRUN` setup for docs artifacts, only placeholders. That is missing.
