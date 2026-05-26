# PLAN — compaction-cadence

## Goal

Replace a non-functioning context-pressure mechanism (`Z_HARNESS_PAUSE_AT_PCT`) with deterministic compaction breakpoints in the three most context-heavy commands.

## Approved decisions (recap from phase3-decisions-final.md)

- **D1.** Delete `Z_HARNESS_PAUSE_AT_PCT` everywhere.
- **D2.** `/z-implement-all` multi-trigger: 5 tasks OR 30 wall-minutes since last pause. Retries don't count. Pause at batch-settle only.
- **D3.** `/z-review-all` unconditional pre-Phase-4 breakpoint, dismissable.
- **D4.** `/z-maintain-docs` breakpoint only on `--audit` path.
- **D5.** New event name `compaction_pause`; retire `usage_pause`.
- **D6.** Recommend `/clear`, mention `/compact` as debug fallback.
- **D7.** Doc updates to README, `docs/human/commands.md`, `docs/llm/commands.json`.

## Non-goals

- Auto-`/compact` (impossible — slash commands are user-side).
- Reading orchestrator token usage (impossible — no API).
- Wholesale rewrite of orchestration loops in any of the three commands.
- Cadence tuning based on qt-bot performance data — that's a follow-up TASK after ship.

## No shortcuts

All decisions land on the robust path; no shortcuts approved.

## Phases

1. **Delete the dead guard.** Remove `Z_HARNESS_PAUSE_AT_PCT` from `commands/z-implement-all.md`, `skills/z-implement-all/SKILL.md`, `README.md`. Sweep exports.
2. **Add `/z-implement-all` breakpoints.** New env vars, new counters, batch-settle trigger check, `compaction_pause` emission, push notification, clean exit.
3. **Add `/z-review-all` pre-Phase-4 breakpoint.** New Phase 3.7 step with `AskUserQuestion`, marker-file resume semantics.
4. **Add `/z-maintain-docs --audit` breakpoint.** Same pattern as (3), pre-first-consultant-batch.
5. **Doc updates.** README "Compaction policy" subsection; `docs/human/commands.md`; `docs/llm/commands.json`. Bump `last_updated`.
6. **Export sync.** Re-run `/z-export` to propagate to `exports/agy`, `exports/codex`, `exports/cursor`.
7. **Optional follow-up (low-priority TASK):** qt-bot post-compact regression probe — read-only analysis of metrics.jsonl after a few real runs ship through the new breakpoints.

## DRY / KISS / SOLID

- **DRY:** Pre-consult breakpoint pattern (Phase 3.7 in `/z-review-all`, audit-gate in `/z-maintain-docs`) shares event shape + `AskUserQuestion` shape + marker-file scheme. If a single helper snippet is natural, extract; otherwise tolerate the duplication.
- **KISS:** Two env vars, both numeric with `0`-disables. One new event type. Unconditional pre-consult pauses (no threshold logic). Idempotent resume from TASKS.md (no new state file).
- **SOLID:** Single responsibility per breakpoint (one trigger, one pause). Open for extension via new `trigger` / `phase` enum values without touching surrounding code. Removing the dead guard collapses a fake responsibility.
