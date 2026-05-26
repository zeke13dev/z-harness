# TASKS — compaction-cadence

Status legend: `[ ]` pending · `[~]` in-progress · `[x]` done

---

## T001 — Delete the dead usage-% guard  `[x]`

**Note:** Reviewer flagged scope creep — /z-plan and /z-plan-split also held the dead guard. Swept as part of T001 (additional files: commands/z-plan.md, skills/z-plan/SKILL.md, commands/z-plan-split.md, skills/z-plan-split/SKILL.md). Step numbering downstream of the deleted setup step renumbered. `usage_paused` removed from z-plan-split early-exit telemetry contract.

**Files touched:**
- `commands/z-implement-all.md`
- `skills/z-implement-all/SKILL.md`
- `README.md`

**Depends on:** none

**Acceptance criteria:**
- Section "Usage-limit guard policy" (around `commands/z-implement-all.md:154` and `skills/z-implement-all/SKILL.md:144`) is removed entirely.
- All references to `Z_HARNESS_PAUSE_AT_PCT` are removed across the three files (grep returns zero hits).
- `usage_pause` event name no longer mentioned anywhere as the active emission name (a one-line "(deprecated; replaced by `compaction_pause`)" note is acceptable in the README event-type table if such a table exists).

**Complexity:** low

---

## T002 — Add `compaction_pause` event type to log-event docs  `[x]`

**Files touched:**
- `scripts/log-event.sh` (no logic change; only the example/comment lines)
- `docs/human/commands.md` (event-type reference, if it exists)
- README event-type table (if it exists)

**Depends on:** T001

**Acceptance criteria:**
- Event-type tables list `compaction_pause` with payload schema `{trigger, detail}`.
- No code path emits `usage_pause` anymore.

**Complexity:** low

---

## T003 — Implement `/z-implement-all` compaction breakpoint  `[x]`

**Files touched:**
- `commands/z-implement-all.md`
- `skills/z-implement-all/SKILL.md`

**Depends on:** T001, T002

**Acceptance criteria:**
- New "Compaction breakpoint policy" subsection (same location vacated by T001) documents:
  - `Z_IMPLEMENT_PAUSE_TASKS` (default 5), `Z_IMPLEMENT_PAUSE_MINUTES` (default 30), `0`-disables semantics.
  - Counter rules: `tasks_since_pause` increments only on `[x]`, NOT on retries or rollbacks.
  - Trigger placement: strict ordering per SPEC Invariant 1 (terminal statuses → TASKS.md write → `batch_done` → halt-flush resolved → THEN trigger check).
  - Emission: `compaction_pause {trigger, tasks_since_pause, wall_minutes_since_pause, pending_remaining}`.
  - Push notification text recommending `/clear` with `/compact` as debug fallback.
  - Clean exit (no new dispatch).
- The pre-existing per-task loop is unchanged in structure; only step 8's end-of-batch logic is extended.

**Complexity:** medium

---

## T004 — Enforce Invariant 2 in implementer return + mark-done  `[x]`

**Note:** Implementer flagged that `docs/llm/agents.json`'s `implementer` concept should mention the new `cross_task_notes` return field — will land via a `/z-maintain-docs` pass (out of scope for this plan; agent doc refresh).

**Files touched:**
- `agents/implementer.md` (add `cross_task_notes: [{task_id, note}]` to the return schema)
- `commands/z-implement-all.md` (mark-done step ~line 418: process `cross_task_notes` before flipping to `[x]`)
- `skills/z-implement-all/SKILL.md` (mirror)

**Depends on:** T003

**Acceptance criteria:**
- Implementer agent doc declares `cross_task_notes` in its return contract (optional field, default empty list — backward-compatible).
- Mark-done step in `/z-implement-all` documents: before flipping `[~]` to `[x]`, iterate `cross_task_notes`; for each `{task_id, note}`, append `**Note:** <note>` to the named task block in TASKS.md. If the named task doesn't exist, log a warning and skip (do not fail the producing task).
- No-op when the field is absent or empty.

**Complexity:** medium

---

## T005 — Implement `/z-review-all` pre-Phase-4 breakpoint + slug-scoped state file  `[x]`

**Files touched:**
- `commands/z-review-all.md`
- `skills/z-review-all/SKILL.md` (if it exists)
- `agents/mr-reviewer.md` (only if it owns the Phase 4 spawn; otherwise skip)

**Depends on:** T002

**Acceptance criteria:**
- New "Phase 3.7 — pre-consult compaction breakpoint" between current Phase 3.5 and Phase 4.
- AskUserQuestion with two options: "Pause for /clear" (exit, no state file written) and "Proceed now" (write `.review_state.json`, continue).
- State file path: `z-harness/plans/<slug>/.review_state.json` with schema specified in SPEC (phase_3_7_acknowledged, base_ref, head_sha, cumulative_diff_path, acknowledged_at).
- Resume logic at top of every `/z-review-all` invocation:
  1. State file + HEAD matches + diff file present → fast-forward to Phase 4, emit `review_resume_fast_forward`.
  2. State file but HEAD changed or diff missing → delete file, full re-run.
  3. No state file → normal Phase 0 entry.
- State file deleted in the finalize phase on successful run completion.
- Emits `compaction_pause {trigger: "pre_consult", phase: "review_all_phase_4"}`.

**Complexity:** high

---

## T006 — Implement `/z-maintain-docs --audit` breakpoint + slug-scoped state file  `[x]`

**Note (SPEC drift):** SPEC.md says state file lives at `z-harness/plans/<slug>/.maintain_docs_audit_state.json`, but `/z-maintain-docs` has no slug concept (it operates on the repo's docs/ tree). Orchestrator override applied: actual state file is `docs/llm/.maintain_docs_audit_state.json`. T008 (commands.json update) should reflect this corrected path.

**Files touched:**
- `commands/z-maintain-docs.md`
- `skills/z-maintain-docs/SKILL.md` (if it exists)

**Depends on:** T002

**Acceptance criteria:**
- Pre-audit-consultant breakpoint inserted before the first audit-consult batch dispatch (the `--audit` code path only — plain runs unchanged).
- State file: `z-harness/plans/<slug>/.maintain_docs_audit_state.json` per SPEC schema.
- Fast-forward when stale-concept set equality holds with `stale_concepts_at_ack`; otherwise invalidate and re-prompt.
- State file deleted at run end.
- Emits `compaction_pause {trigger: "pre_consult", phase: "maintain_docs_audit"}`.
- Plain (non-`--audit`) `/z-maintain-docs` is NOT modified.

**Complexity:** medium

---

## T007 — README "Compaction policy" subsection  `[x]`

**Files touched:**
- `README.md`

**Depends on:** T003, T005, T006

**Acceptance criteria:**
- New subsection documents:
  - The two `Z_IMPLEMENT_PAUSE_*` env vars (purpose, defaults, `0`-disables).
  - The pre-consult breakpoints in `/z-review-all` and `/z-maintain-docs --audit` (always on, dismissable).
  - Why `/clear` is recommended over `/compact` (idempotent resume).
  - The new `compaction_pause` event type and its `trigger` values.
- Cross-links to each affected command's section.

**Complexity:** low

---

## T008 — Update `docs/human/commands.md` + `docs/llm/commands.json`  `[x]`

**Files touched:**
- `docs/human/commands.md`
- `docs/llm/commands.json`

**Depends on:** T007

**Acceptance criteria:**
- `docs/human/commands.md` gets a "Compaction breakpoints" subsection paralleling the README, with file:line cross-links.
- `docs/llm/commands.json`:
  - Each of `z-implement-all`, `z-review-all`, `z-maintain-docs` entries gets a new `compaction_breakpoints` array field per SPEC.
  - `z-implement-all` entry: remove any `usage_pct_guard` field if present.
  - All three entries' `last_updated` bumped to today's date.

**DOCS:** commands

**Complexity:** low

---

## T009 — Re-run `/z-export` to propagate to agy / codex / cursor  `[x]`

**Note:** Initial export still showed 6 hits each for `Z_HARNESS_PAUSE_AT_PCT` and `usage_pause` — the T001 scope-extension's edits to `commands/z-plan.md` and `skills/z-plan/SKILL.md` had been overwritten between then and T009 (likely by a linter/sync after the parallel implementer pass). Re-applied the deletion + step renumbering manually before re-running exporters. Final state: 0 hits in source, 0 hits in exports.

**Files touched:**
- `exports/agy/**`
- `exports/codex/**`
- `exports/cursor/**`

**Depends on:** T001, T003, T005, T006, T007, T008

**Acceptance criteria:**
- After running `/z-export` (or the equivalent regeneration script), `git status` shows the export trees updated to reflect the new compaction policy.
- `grep -r Z_HARNESS_PAUSE_AT_PCT exports/` returns zero hits.
- `grep -r Z_IMPLEMENT_PAUSE_TASKS exports/` returns the expected hits in the implement-all mirror files.

**Complexity:** low (mostly mechanical / tool-driven)

---

## T010 — (low priority, post-ship) qt-bot post-compact regression probe  `[ ]`

**Files touched:**
- New report at `z-harness/plans/compaction-cadence/POST_SHIP_PROBE.md`

**Depends on:** T009 (and at least a few real qt-bot runs through the new breakpoints)

**Acceptance criteria:**
- Read-only remote-runner dispatch reads `~/dev/qt-bot/z-harness/metrics.jsonl` and any per-run `events.jsonl` that contain `compaction_pause` events.
- For each pause, compute retry/failure rate of the N tasks BEFORE vs AFTER the pause boundary.
- Report flags whether there's a >2x degradation post-pause (signal that `/clear` is hurting subagent quality somehow), no change, or improvement.
- Writes findings only; no code changes.

**Complexity:** low

---

## Task-count check

10 tasks. Within target range (10–20). ✓
