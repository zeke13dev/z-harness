# SPEC — compaction-cadence

## Overview

Delete the never-functioning `Z_HARNESS_PAUSE_AT_PCT` usage-% guard, and replace its mechanism (pause + push-notify) with deterministic breakpoints inserted at the highest-context-pressure boundaries in `/z-implement-all`, `/z-review-all`, and the `--audit` path of `/z-maintain-docs`.

Recommend `/clear` over `/compact` on resume — the harness's durable state lives in TASKS.md, so clearing reclaims more context with no safety loss. Codify "no cross-task state in orchestrator memory" as a SPEC invariant.

## Planning Inputs

| Artifact | Path | generated_at |
|----------|------|--------------|
| BRAINSTORM.md | (none) | n/a |
| RESEARCH.md | (none) | n/a |

## Invariants (must hold post-change)

1. **Pause only at batch-settle, AFTER halt-flush.** No new compaction breakpoint may fire mid-batch. The required ordering at batch-settle is strict:
   1. Every in-flight task has reached terminal status (`[x]` done, or rolled back to `[ ]` after halt/abandon).
   2. TASKS.md atomic write completed.
   3. `batch_done` event emitted.
   4. **All halt signals collected during the batch** (spec_problem, decision_needed, unable_to_complete) are surfaced to the user via the existing halt-flush path. The user resolves halts FIRST (or chooses to defer them as `[ ]` with a `**Note:**`).
   5. **Only after halts are resolved/deferred** does the compaction-trigger check run.
   This ordering prevents losing halt context to a `/clear`.
2. **No orchestrator-side cross-task memory.** Any signal needed by a downstream task must be persisted to TASKS.md (as a `**Note:** ...` line on the dependent task) **before** the producing task is marked `[x]`. The implementer subagent already returns a `cross_task_notes: [...]` field in its result schema; the orchestrator's mark-done step (`commands/z-implement-all.md:418`) gets a new sub-step: **before** flipping `[~]` to `[x]`, if `cross_task_notes` is non-empty, append each note as a `**Note:** <text>` line to the named downstream task in TASKS.md. If the implementer doesn't return a `cross_task_notes` field, treat as empty (backward-compatible).
3. **Resume is idempotent and slug-scoped.**
   - `/z-implement-all`: re-invoking after a `compaction_pause` re-reads TASKS.md and proceeds. No state file needed because counters legitimately reset on a fresh run — if the user `/clear`-ed before resuming, context is fresh and a new 5-task / 30-minute window is correct. If they didn't `/clear`, they're choosing to forgo the breakpoint's benefit; that's their call.
   - `/z-review-all` and `/z-maintain-docs --audit`: state lives in a **slug-scoped** file (NOT run-timestamp-scoped) so a fresh invocation finds it:
     - `z-harness/plans/<slug>/.review_state.json` for review-all
     - `z-harness/plans/<slug>/.maintain_docs_audit_state.json` for maintain-docs --audit
4. **`usage_pause` event name retired.** New event: `compaction_pause` with payload `{trigger: "task_count"|"wall_time"|"pre_consult", detail: {...}}`. Existing `metrics.jsonl` consumers (`/z-stats`) handle missing event types gracefully — no migration.

## Files to change

### `commands/z-implement-all.md`

**Delete:** the entire "Usage-limit guard policy" subsection at line 154 (env var `Z_HARNESS_PAUSE_AT_PCT`, all language about "current usage %" and the 90% threshold).

**Add:** a new "Compaction breakpoint policy" subsection (same location) with this behavior:

- **Env vars:**
  - `Z_IMPLEMENT_PAUSE_TASKS` (default `5`) — completed tasks since last pause that triggers a breakpoint.
  - `Z_IMPLEMENT_PAUSE_MINUTES` (default `30`) — wall minutes since last pause (or run_start) that triggers a breakpoint.
  - Either env var set to `0` disables that trigger; both `0` disables compaction breakpoints entirely.

- **Counters (orchestrator-side, in-memory; reset on every pause and on re-invocation):**
  - `tasks_since_pause`: incremented when a task transitions to `[x]` (done). **NOT** incremented on retries (a single task with 3 retries counts as 1 completion) and **NOT** incremented when a task is rolled back to `[ ]` after a halt or abandon. A task surfaced as a halt and explicitly deferred by the user (left `[ ]` with a `**Note:**`) also does not count — only `[x]` increments.
  - `pause_clock_start`: epoch seconds set at run_start and on every resume.

- **Trigger check:** at the **end of each batch-settle, AFTER the halt-flush step** (see Invariant 1 ordering: terminal statuses → atomic TASKS.md write → `batch_done` event → halt-flush surfaced and resolved → THEN trigger check), evaluate:
  ```
  if Z_IMPLEMENT_PAUSE_TASKS > 0 and tasks_since_pause >= Z_IMPLEMENT_PAUSE_TASKS:
      trigger = "task_count"
  elif Z_IMPLEMENT_PAUSE_MINUTES > 0 and (now - pause_clock_start) / 60 >= Z_IMPLEMENT_PAUSE_MINUTES:
      trigger = "wall_time"
  else:
      trigger = None
  ```

- **On trigger:** emit `compaction_pause` event with payload:
  ```json
  {"trigger": "<task_count|wall_time>", "tasks_since_pause": N, "wall_minutes_since_pause": M, "pending_remaining": K}
  ```
  Push-notify (regardless of `Z_HARNESS_NOTIFY` value — this is a hard pause):
  > "Compaction breakpoint: <N> tasks completed (or <M> min wall). <K> pending tasks remain. Run `/clear`, then re-invoke `/z-implement-all` to resume from TASKS.md. Use `/compact` instead if you need chat history for debugging."

  Finalize the loop cleanly (no new dispatch). Exit with status 0.

### `commands/z-review-all.md`

**Add:** a new step between Phase 3.5 (test run) and Phase 4 (consultant spawn) — "Phase 3.7 — pre-consult compaction breakpoint":

- Emit `compaction_pause` event with payload `{trigger: "pre_consult", phase: "review_all_phase_4"}`.
- Use `AskUserQuestion` with two options:
  - **(a) Pause for /clear** — exit cleanly so the user can `/clear` and re-invoke. Do **NOT** write any state file. On the next invocation, Phase 3.7 will fire again (correct — user wanted to re-evaluate).
  - **(b) Proceed now** — continue into Phase 4. **Only on this choice** write the state file (see below).

**State file:** `z-harness/plans/<slug>/.review_state.json` (slug-scoped, not run-scoped; survives across invocations). Schema:
```json
{
  "phase_3_7_acknowledged": true,
  "base_ref": "<git ref captured in Phase 2>",
  "head_sha": "<git rev-parse HEAD at time of acknowledgement>",
  "cumulative_diff_path": "<absolute path to the diff in the current archive/<run>/>",
  "acknowledged_at": "<iso timestamp>"
}
```

**On every `/z-review-all` invocation, BEFORE entering Phase 0:**
1. If `.review_state.json` exists in the slug dir, read it.
2. If `head_sha` matches `git rev-parse HEAD` AND the referenced `cumulative_diff_path` file still exists, **fast-forward**: skip Phase 0–3.5, reuse the existing diff and test results, enter Phase 4 directly. Log a `review_resume_fast_forward` event.
3. If HEAD has changed OR the diff path is missing, **delete the stale state file** and start a fresh run from Phase 0 (the marker is invalidated; the user must reconfirm at the new Phase 3.7).
4. If `.review_state.json` does not exist, run Phase 0–3.7 normally.

This makes the pause/proceed semantics correct in all cases:
- Pause + `/clear` + resume: no marker, Phase 3.7 fires again (user reconfirms).
- Proceed + run completes: state file is deleted at run end (cleanup hook in finalize phase).
- Proceed + run interrupted before Phase 4 completes + re-invoked with HEAD unchanged: fast-forward to Phase 4.
- Proceed + run interrupted + HEAD changed: state invalidated; full re-run from Phase 0.

### `commands/z-maintain-docs.md`

**Add:** in the `--audit` flag handler (where cross-LLM consultants are spawned per concept), insert a single pre-audit breakpoint BEFORE the first consultant batch dispatches:

- Emit `compaction_pause {trigger: "pre_consult", phase: "maintain_docs_audit"}`.
- Push-notify:
  > "About to audit <N> concept docs via consultants. Recommended: `/clear`, then re-invoke `/z-maintain-docs --audit` to continue. Dismiss to proceed now."
- Same `AskUserQuestion` two-option pattern as `/z-review-all`.
- **State file:** `z-harness/plans/<slug>/.maintain_docs_audit_state.json` (slug-scoped). Schema:
  ```json
  {
    "audit_acknowledged": true,
    "stale_concepts_at_ack": ["<slug>", "..."],
    "acknowledged_at": "<iso timestamp>"
  }
  ```
- On every `/z-maintain-docs --audit` invocation, BEFORE entering audit consult dispatch:
  1. If state file exists AND the stale concept set matches (set equality with `stale_concepts_at_ack`), fast-forward past the breakpoint.
  2. If stale concept set has changed, delete the state file and re-prompt at the breakpoint.
  3. State file is deleted at run end.

**Do NOT add a breakpoint** in plain (non-`--audit`) `/z-maintain-docs` runs — doc-updaters are fresh-context Sonnet subagents; orchestrator pressure is low.

### `skills/z-implement-all/SKILL.md`

Mirror the changes in `commands/z-implement-all.md`. This file currently has the same "Usage-limit guard policy" block at line 144; delete and replace identically.

### `skills/z-review-all/SKILL.md`, `skills/z-maintain-docs/SKILL.md`

Mirror the changes in their respective `commands/*.md` siblings if these skill files exist with corresponding sections. (Verify presence; the harness ships some commands without a matching skill body.)

### `README.md`

- Delete the `Z_HARNESS_PAUSE_AT_PCT` row from any env-var table.
- Add a new subsection "Compaction policy" describing:
  - The two `Z_IMPLEMENT_PAUSE_*` env vars (defaults, semantics, how to disable).
  - The pre-consult breakpoints in `/z-review-all` and `/z-maintain-docs --audit` (no env var; always on, dismissable).
  - Why we recommend `/clear` over `/compact` (idempotent resume, no orchestrator-side state).

### `docs/human/commands.md`

- Add a "Compaction breakpoints" section describing the same as README.md, with cross-links to each affected command's section.

### `docs/llm/commands.json`

- Update the `compaction_breakpoints` field on each affected command entry (`z-implement-all`, `z-review-all`, `z-maintain-docs`) to record:
  - `triggers: ["task_count" | "wall_time" | "pre_consult"]`
  - `env_vars: ["Z_IMPLEMENT_PAUSE_TASKS", "Z_IMPLEMENT_PAUSE_MINUTES"]` (only on z-implement-all)
  - `recommended_action: "clear"`
- Remove the `usage_pct_guard` field from `z-implement-all` (if present).
- Bump `last_updated` to today's date.

### Exports (mirror)

The harness exports to `exports/agy/`, `exports/codex/`, `exports/cursor/`. The export-sync script (`scripts/export-sync.sh` or invoked via `/z-export`) regenerates these from the source commands/skills/agents. Implementation note: after editing the canonical command/skill files, re-run `/z-export` (or document that the user should) to propagate. The plan must NOT hand-edit exports — they are derived artifacts.

## Edge cases

- **Run completes mid-counter-window.** If `tasks_since_pause` is 3 when the final task completes, no breakpoint fires; orchestrator emits `run_complete` normally. Correct: there's no work left to compact for.
- **Single very long task.** A task that runs 45 min by itself will trigger the wall-time breakpoint AFTER it completes (at batch-settle), not during. Acceptable — pausing inside an in-flight subagent dispatch is impossible.
- **Env vars both set to 0.** Compaction breakpoints in `/z-implement-all` disabled entirely. Pre-consult breakpoints in `/z-review-all` and `/z-maintain-docs --audit` are unaffected (no env var gates them).
- **User dismisses pre-consult breakpoint.** Marker file `.pre_consult_acknowledged` / `.audit_acknowledged` written; subsequent re-invocations skip the breakpoint until a new run.
- **`compaction_pause` event during precontext phases.** Not applicable — precontext (BRAINSTORM/RESEARCH) and planning phases are not part of this plan's scope.

## Error handling

- Failure to write the marker file: log a warning, proceed with the user's chosen option (don't block on filesystem hiccup).
- Failure to emit the event to events.jsonl: log to stderr, proceed (event logging is best-effort throughout the harness).
- User aborts (Ctrl-C) during the `AskUserQuestion`: same as picking "Pause" — exit cleanly without marker.

## DRY / KISS / SOLID

- **DRY:** The pre-consult breakpoint pattern is shared between `/z-review-all` and `/z-maintain-docs --audit` — both emit the same event type with different `phase` payloads, both use the same `AskUserQuestion` two-option shape. The implementer SHOULD factor a helper if a natural place exists (a shared snippet in a script under `scripts/`); SHOULD NOT introduce a new abstraction layer just for two call sites.
- **KISS:** Pre-consult breakpoints are unconditional (no diff-size thresholds, no token estimators). Two env vars, both numeric, both with `0`-disables semantics. One new event type with a small payload.
- **SOLID:** The compaction policy is now a single concern (breakpoint placement) with clear extension points (add a new `trigger` value, add a new `phase` value). Removing `Z_HARNESS_PAUSE_AT_PCT` eliminates a fictitious "usage-% awareness" responsibility the orchestrator never had.
