# Phase 3 — Decisions Final

## D1. Delete `Z_HARNESS_PAUSE_AT_PCT` outright
**(no consult; from user)** — confirmed. Delete env var + "Usage-limit guard policy" block from `commands/z-implement-all.md`, `skills/z-implement-all/SKILL.md`, README. Sweep agy / cursor / codex exports.

## D2. Primary breakpoint trigger in `/z-implement-all` — **multi-trigger (Codex's d)**

**Rule:** Pause after batch-settle if **either**:
- `completed_tasks_since_last_pause >= Z_IMPLEMENT_PAUSE_TASKS` (default `5`), OR
- `wall_minutes_since_last_pause >= Z_IMPLEMENT_PAUSE_MINUTES` (default `30`).

**Counting rules:**
- Only successful task completions (status `[x]`) or deferrals (`[!]` blocked-by-decision) count toward the task counter. Retries do **not** count.
- Pause happens at the **batch-settle boundary**, never mid-batch — guarantees TASKS.md is in a durable state before pause.

**Why not pure task count (a):** Gemini correctly noted that one task with retry=4 burns ~4× context. Wall-time catches this.
**Why not subagent count (c):** opaque to the user's mental model; harder to explain "5 of 8" subagents than "5 of 20" tasks.
**One reason this might still be wrong:** wall-time is environment-dependent (slow machine pauses more often for no real context reason). Mitigation: env vars are user-tunable; defaults are conservative.

## D3. Pre-Phase-4 breakpoint in `/z-review-all` — **unconditional yes (Gemini's a)**

**Rule:** Before spawning the cumulative-diff consultants in Phase 4, emit a push notification: *"About to spawn consultants on cumulative diff (heaviest context burn). Recommended: `/clear`, then re-invoke `/z-review-all` to continue from this point. Dismiss to proceed now."*

**Why unconditional over Codex's conditional gating:** the conditional (diff > 100k lines, etc.) adds complexity without benefit — the user can dismiss instantly if context is fresh. KISS wins.
**One reason this might be wrong:** users dismissing reflexively will not actually compact, defeating the breakpoint. Mitigation: doc the rationale clearly so dismissal is informed.

## D6. Recommend `/clear` over `/compact` — **(b), with `/compact` as debugging fallback**

**Resume message template:**
> "Compaction breakpoint hit (<trigger>: <detail>). Run `/clear`, then re-invoke `/z-implement-all` to resume from TASKS.md. Use `/compact` instead if you need this chat history for debugging."

**Why `/clear` is safe:** resume is idempotent — orchestrator re-reads TASKS.md and picks the next eligible pending task. No cross-task state lives in orchestrator memory; all durable state is on disk.

**Critical guardrail (from Gemini's interaction warning):** for `/clear` recommendation to remain safe, the orchestrator must never carry cross-task insights in main-thread memory only. SPEC will require: any cross-task signal (e.g. "implementer learned X about library Y on T003 that T007 should know") MUST be appended to TASKS.md as a `**Note:** ...` line on the relevant downstream task. This matches the current architecture (subagents are fresh-context; main thread mostly dispatches) — codifying the existing invariant.

**One reason this might be wrong:** if a future feature introduces persistent orchestrator-side state (e.g. an in-memory cache of recent decisions), `/clear` becomes unsafe. Mitigation: SPEC encodes the invariant explicitly so future changes can't quietly break it.

## Shortcuts identified

None. No shortcuts proposed — all decisions land on the robust option.
