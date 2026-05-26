# Phase 0 — Premise Check (revised after user confirmation)

## What we're actually doing

1. **Delete usage-% awareness** from `/z-implement-all` (and any other commands that reference `Z_HARNESS_PAUSE_AT_PCT` or "current usage %"). The orchestrator cannot read its own token usage; the guard never functioned.
2. **Add deterministic compaction/clear triggers** at task / phase boundaries in:
   - `/z-implement-all` (between tasks or every N tasks)
   - `/z-maintain-docs` (before / between concept refreshes)
   - `/z-review-all` (before the cumulative-diff review)
3. **Investigate qt-bot run logs** (`metrics.jsonl` + per-run `events.jsonl`) to see:
   - Whether subagent quality / retry rate degrades after a `/compact` boundary.
   - Where main-thread context actually grows (token spend by phase).
   This informs (a) cadence defaults and (b) which commands most benefit from inserted compaction points.

## Mechanism note

The orchestrator can't self-invoke `/compact` or `/clear` — both are user-side. The actual lever is **pause + push-notify** with explicit instructions ("`/compact`, then `/z-implement-all` to resume"). The 90% guard already used this mechanism; we keep the mechanism, change the trigger.

The orchestrator *can* also reduce its own context growth structurally — e.g. write subagent returns to disk and only read tight summaries — but that's a separate optimization, not "compaction."

## Out of scope

- Auto-`/compact` (impossible).
- Usage-% trigger (deleted, not replaced).
- Wholesale rewrite of orchestration loops — we're inserting trigger points, not redesigning.

## Open question deferred to Phase 1

What does qt-bot's `metrics.jsonl` actually show about per-phase token spend and post-compact regression rate? Phase 1 will dispatch a remote-runner to check.
