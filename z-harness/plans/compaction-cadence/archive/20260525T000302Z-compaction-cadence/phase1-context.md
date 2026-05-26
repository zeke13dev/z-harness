# Phase 1 — Context

## Where pause+notify breakpoints already exist or could be inserted

| Command | Loop shape | Existing pause | Natural breakpoints |
|---|---|---|---|
| `/z-implement-all` | per-task loop, batches ≤3 parallel tracks | `Z_HARNESS_PAUSE_AT_PCT=90` at batch boundary (spec only — never fires) | between task batches; before reviewer spawn |
| `/z-maintain-docs` | Phase 2 doc-updater batches ≤3 | none | between batches; before optional `--audit` consult prong |
| `/z-review-all` | one-shot Phase 4 consultant spawn | none | before Phase 3.5 test run; before Phase 4 consultants |

## Key spec touch points (file:line)

- `commands/z-implement-all.md:154` — Usage-limit guard policy (the broken spec)
- `skills/z-implement-all/SKILL.md:144` — same text, mirrored
- `commands/z-review-all.md:49–142` — Phase 4 consultant dispatch (no pause)
- `commands/z-maintain-docs.md:23–77` — Phase 1–2 detection + dispatch (no pause)

## Evidence from qt-bot's metrics.jsonl (most recent ~508 events)

- **0 `usage_pause` events** across full history → confirms the guard never fires; the signal `Z_HARNESS_PAUSE_AT_PCT` reads doesn't exist.
- **8 `consult` events total**; top run `20260519T022355Z-data-overhaul` logged 100,571 prompt chars + 28,344 response chars across 4 consults — these are the largest single context burns.
- **Retry pattern signal:** 5 tasks required ≥2 retries. T006 (data-overhaul) hit retry=4 and ended `unable_to_complete` after 53 min of wall time — strongest available evidence that long uninterrupted runs degrade. Other retry-2+ tasks succeeded.

## What this tells us for the plan

1. The `Z_HARNESS_PAUSE_AT_PCT` block can be deleted, not preserved. The "usage_pause" event type stays (still useful if we ever get a real signal), but the trigger does not.
2. Deterministic breakpoints (every N tasks, or after high-token consult phases) are the only mechanism we can rely on.
3. Heaviest context concentration is in **consultant returns** (consult events) and in long task chains without compaction. Inserting breakpoints **before consultant spawns** in `/z-review-all` and **between task batches** in `/z-implement-all` targets the right hot spots.
4. `/z-maintain-docs` runs are short enough that breakpoints are low-value unless stale concept count is large (>10).

## Open questions resolved or deferred

- Did compaction degrade qt-bot performance? **Cannot answer from current data** — no runs in the sample bracketed a compact. Deferred: collect data after this plan ships.
- Does T006's failure prove context pressure? Weakly suggestive, not conclusive. Treat as a motivating data point, not a controlled experiment.
