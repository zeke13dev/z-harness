# Fix: per-task-model-selection

**Run:** 20260522T051054Z-per-task-model-selection
**Status:** shipped
**Plugin version:** z-harness (self-edit)

## Problem

`/z-implement-all` and `/z-implement-next` dispatch every task to a Sonnet implementer on first attempt. Hard tasks waste a Sonnet cycle before failing Codex review. The existing `Z_HARNESS_RETRY_UPGRADE=opus` env var and `**Complexity:** high` opt-in are documented as advisory care signals only — they do not actually change the model. The `Agent(...)` tool now supports a per-call `model` parameter, so we can right-size implementer model per task.

## Root cause

`agents/implementer.md` declares `model: sonnet` in frontmatter; orchestrator dispatch sites in `commands/z-implement-all.md:158-170` and `commands/z-implement-next.md:55` only set an env var rather than passing `model=` on the `Agent(...)` call. The wire is missing.

## Approach

1. **New `agents/complexity-classifier.md`** (Haiku subagent). Reads one task block + a SPEC.md slice the caller passes; returns `STATUS: classified\nTIER: low|medium|high\nREASON: <one line>`. No file edits. Self-contained.
2. **`/z-plan` Phase 8**: after writing TASKS.md, dispatch the classifier per task in parallel (single message, multiple Agent calls). Append `**Complexity:** <tier>` to each task block. Log a `task_classified` event per task to `events.jsonl` capturing the tier and rationale.
3. **`/z-amend` full-mode Phase 6**: for tasks added or whose acceptance/files block was materially modified, dispatch the classifier and update/append the `**Complexity:**` line. Preserve existing stamps on untouched tasks. Light mode unaffected — no implementer subagent runs there.
4. **`/z-implement-all` step 5 + `/z-implement-next`**: read `**Complexity:**` from the task block. Pass `model="sonnet"` for `low|medium` and `model="opus"` for `high` on the implementer `Agent(...)` call. If the stamp is missing, default to `model="sonnet"` and log a `missing_complexity_stamp` warning event.
5. **Retry bump**: on cycle ≥ 2 dispatch (after Codex review blockers/majors), always pass `model="opus"` regardless of stamp. Remove the `Z_HARNESS_RETRY_UPGRADE=opus` env-var pattern — direct model param replaces it. Keep an in-prompt "this is retry v<N> — apply Opus-level care to the fix" text signal so the implementer's prompt still primes for careful work.
6. **`agents/implementer.md`**: frontmatter stays `model: sonnet` as the fallback default (when no override is passed). Rewrite the "Optional: **prior-attempt reviewer feedback** if this is a retry. If `Z_HARNESS_RETRY_UPGRADE=opus` is set..." prose to reflect that the orchestrator now picks the model directly via `Agent(model=...)`, not via env-var care signal. Keep the `**Complexity:** high` user opt-in language — it still works as a user override that the classifier and orchestrator both respect.

## Files to change

- `/Users/zeke/dev/z-harness/agents/complexity-classifier.md` (new)
- `/Users/zeke/dev/z-harness/agents/implementer.md`
- `/Users/zeke/dev/z-harness/commands/z-plan.md`
- `/Users/zeke/dev/z-harness/commands/z-amend.md`
- `/Users/zeke/dev/z-harness/commands/z-implement-all.md`
- `/Users/zeke/dev/z-harness/commands/z-implement-next.md`

## Acceptance

- [x] `agents/complexity-classifier.md` exists with Haiku frontmatter, declares its return shape (`STATUS:`, `TIER:`, `REASON:`), and is read-only (no Edit/Write tools).
- [x] `/z-plan` Phase 8 documents the parallel-classifier dispatch and the `**Complexity:**` stamp.
- [x] `/z-amend` full-mode Phase 6 documents re-classification for new/modified tasks and stamp preservation for untouched tasks.
- [x] `/z-implement-all` step 5 documents reading the stamp and passing `model=` on the implementer Agent call; the retry-bump block is rewritten to use `model="opus"` directly; the env-var paragraph is replaced.
- [x] `/z-implement-next` documents the same dispatch logic (single-task variant).
- [x] `agents/implementer.md` "Inputs from caller" section is updated to reflect orchestrator-driven model selection.
- [x] No `Z_HARNESS_RETRY_UPGRADE` references remain in the harness command/agent files.
- [x] Codex review of the diff returns no blockers or majors.

## Cross-LLM consensus

- Gemini: Plan-time stamping (Option A) with conservative `/z-amend` re-classification — *(Gemini API was rate-limited; CLI returned a fallback synthesis that converged with Codex; transcript archived.)*
- Codex:  Plan-time stamping (Option A); flagged that today's `low → medium` bump would still map to Sonnet, recommending "any failed review → Opus" rather than `+1 tier`.
- Synthesized call: Option A (plan-time stamping). Retry bump = always Opus (per Codex). Missing-stamp fallback = `medium` (Sonnet) with logged warning. Remove `Z_HARNESS_RETRY_UPGRADE` env var; replace with direct `model=` parameter on `Agent(...)`. Classifier rationale logged to `events.jsonl`, not stamped into TASKS.md.

## Approved shortcuts

None.

## Docs touched

None — `z-harness/` itself has no `docs/llm/INDEX.json`; the agent and command markdown files *are* the documentation.
