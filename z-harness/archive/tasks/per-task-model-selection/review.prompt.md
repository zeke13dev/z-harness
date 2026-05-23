You are reviewing a v2 (retry) implementation of task `per-task-model-selection`. The v1 review flagged 4 majors; this review is to confirm they were addressed and to spot any NEW blockers/majors introduced by the fix delta. Do NOT re-flag scope-creep (the doc-fetcher/z-plan Phase 1 changes and the entire z-amend command+skill files are pre-existing uncommitted dirt from a different WIP, NOT part of this fix).

The 4 prior majors and the implementer's claim of fix:
1. /z-amend re-classification was disabled because heuristic #1 treated any existing stamp as user-authored override. Claim: strip the existing **Complexity:** line BEFORE dispatching, unless user explicitly named a tier.
2. Modified-task trigger too narrow (Files/Acceptance/Tests only). Claim: broadened to "any line OTHER than the **Complexity:** line itself" enumerating title, Files, Depends, Acceptance, **Tests:**, **REMOTE_VERIFY:**, **DOCS:**.
3. /z-implement-next had an orphaned retry-override paragraph (single-shot, no auto-retry). Claim: removed orphan, added clarifying paragraph.
4. Missing-stamp fallback under-specified. Claim: added concrete log-event.sh shell snippets in both /z-implement-all and /z-implement-next (and skill mirrors).

SPEC excerpt (FIX.md Approach section):
- /z-plan Phase 8: parallel classifier dispatch, append **Complexity:** stamp.
- /z-amend full-mode Phase 6: re-classify new/modified tasks; preserve untouched stamps; light mode unaffected.
- /z-implement-all + /z-implement-next: read **Complexity:**, pass model="sonnet" for low|medium, model="opus" for high. Missing stamp → default sonnet + log missing_complexity_stamp warning.
- Retry: cycle ≥ 2 always model="opus". Remove Z_HARNESS_RETRY_UPGRADE env var.
- Implementer frontmatter stays model: sonnet as fallback.

Diff (delta v1→v2, focused excerpts):

=== commands/z-amend.md Phase 6 TASKS.md item (and skill mirror identical) ===
- **Re-classify complexity** for new tasks and for `[ ]` tasks whose block changed in any line OTHER than the `**Complexity:**` line itself (title, Files, Depends, Acceptance, `**Tests:**`, `**REMOTE_VERIFY:**`, `**DOCS:**` — any of these can materially shift complexity). For each affected task, **strip the existing `**Complexity:**` line BEFORE dispatching** the `complexity-classifier` (Haiku) subagent — otherwise the classifier's heuristic #1 will return `REASON: user-authored override` and the auto-stamp will never refresh. Exception: if the user *explicitly named* a complexity tier in their amendment instruction (e.g. "and mark T007 as high"), preserve that as a user-authored stamp and skip the classifier. Dispatch in parallel for the affected tasks only; append the new `**Complexity:** <tier>` line per the classifier's return. **Do not re-classify** tasks whose blocks are otherwise unchanged in this amendment — preserve their existing stamp byte-for-byte (avoids stamp churn the user did not ask for). Log one `task_classified` event per re-classified task to `events.jsonl` with `{task, tier, reason, amend_run: "$RUN"}`.

=== commands/z-implement-all.md step 5 (and skill mirror identical) ===
**Pick the implementer model from the task block's `**Complexity:**` stamp** (stamped by `/z-plan` or `/z-amend`):
- `low` or `medium` → `model="sonnet"`
- `high` → `model="opus"`
- **Stamp missing** (legacy plan, or hand-deleted): default to `model="sonnet"` AND log a `missing_complexity_stamp` warning event. Do not block; do not JIT-classify.
  ```bash
  bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" missing_complexity_stamp \
    "$(printf '{"task":"%s","fallback_model":"sonnet"}' "<task-id>")"
  ```

**Retry override.** If this dispatch is cycle ≥ 2 (i.e. a retry after Codex review blockers/majors), force `model="opus"` regardless of the stamp. The in-prompt `RETRY v<N>` header is the implementer's signal to apply Opus-level care to the fix.

[Agent() call uses model="<sonnet|opus per the rules above>"]

Replaces previous Z_HARNESS_RETRY_UPGRADE env-var pattern. **User-authored override.** If user writes `**Complexity:** high` directly, classifier preserves it (returns `REASON: user-authored override`).

Cycle ≥ 2 prompt block now passes model="opus" explicitly in the Agent() call.

=== commands/z-implement-next.md (and skill mirror identical) ===
**Pick the implementer model from the task block's `**Complexity:**` stamp**:
- `low` or `medium` → `model="sonnet"`
- `high` → `model="opus"`
- **Stamp missing**: default to `model="sonnet"` and log a `missing_complexity_stamp` warning event:
  ```bash
  bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" missing_complexity_stamp \
    "$(printf '{"task":"%s","fallback_model":"sonnet"}' "<task-id>")"
  ```

[Agent() call uses model="<sonnet|opus per the rules above>"]

This replaces the prior `Z_HARNESS_RETRY_UPGRADE=opus` env-var pattern; `Agent(...)` supports per-call `model` override directly.

`/z-implement-next` is a single-shot command and does not auto-retry on Codex review failure. If you want a retry with `model="opus"`, re-invoke `/z-implement-next` after manually flipping the task's stamp to `**Complexity:** high`, or run `/z-implement-all` which handles the retry loop internally.

=== commands/z-plan.md Phase 8 (unchanged from v1) ===
**Complexity stamp (parallel Haiku classifier).** After writing all task blocks, dispatch the `complexity-classifier` (Haiku) once per task in parallel. Parse TIER/REASON, Edit TASKS.md to append `**Complexity:** <tier>`. Log `task_classified` event. If task block already has user-authored stamp, classifier returns `REASON: user-authored override` and you leave it alone.

Confirm whether the 4 prior majors are now resolved. Identify any NEW blockers or majors introduced by THIS delta (the strip-before-dispatch rule, broadened trigger, single-shot clarification, missing-stamp shell snippets).

OUTPUT BUDGET: under 8000 chars. Blockers and majors only. One finding per bullet, two sentences max. If clean, respond exactly: `No blockers or majors found.` (plus optional 1-line note).
