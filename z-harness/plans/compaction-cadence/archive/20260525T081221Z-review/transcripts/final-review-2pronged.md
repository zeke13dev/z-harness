# FINAL REVIEW: compaction-cadence plan

Date: 2026-05-25
Diff size: 1564 lines, 14 files touched
Complexity: high (three commands + mirrors + docs + exports)

---

## PRONG A — Implementation Faithfulness

### Finding A1: ✅ PASS — Strict ordering for `/z-implement-all` step-8 compaction trigger

**Evidence:** `commands/z-implement-all.md` line ~491–498 (from diff)

The trigger-check placement is correct:
```
5. Increment `tasks_since_pause` by 1 (this task reached `[x]`)
6. **Batch-settle compaction check** — "When all parallel tracks in this outer iteration 
   have completed (all have reached terminal status, the atomic TASKS.md write is done, 
   `batch_done` is emitted, and all halt signals have been surfaced and resolved or 
   deferred by the user), run the trigger check..."
```

The description explicitly codifies the strict ordering: terminal → TASKS.md write → batch_done → halt-flush → THEN trigger check. The earlier "Main loop" section declares this as exit condition (3), separate from Finalize, and notes that Finalize is **skipped** when condition (3) fires.

**Confidence:** High. The text is explicit, and the trigger check is conditionally placed *after* halt-flush.

---

### Finding A2: ✅ PASS — `/z-review-all` resume logic (state file + HEAD match + artifact presence)

**Evidence:** `commands/z-review-all.md` "Pre-Phase 0 — Resume check" (from diff, ~60 lines)

The resume state machine is correctly specified:
1. Parse state file; if invalid → delete and re-run.
2. Check `git rev-parse HEAD` against `head_sha`.
3. Check both `cumulative_diff_path` and `cumulative_stat_path` exist on disk.
4. If all pass → fast-forward to Phase 4, restore environment from state fields, emit `review_resume_fast_forward`.
5. If HEAD changed OR artifacts missing → delete state file, full re-run from Phase 0.

The fast-forward environment restore explicitly sets: `Z_HARNESS_SLUG`, `Z_HARNESS_PLAN_DIR`, `BASE`, `BASE_REF`, `HEAD_SHA`, `RRUN`, `cumulative_diff_path`, `cumulative_stat_path`.

**Confidence:** High. State invalidation logic is explicit and handles both artifact presence and HEAD mismatch.

---

### Finding A3: ⚠️ MINOR — `/z-review-all` state file schema drift from SPEC

**Evidence:** 
- SPEC.md line 78–86: state file schema includes `phase_3_7_acknowledged`, `base_ref`, `head_sha`, `cumulative_diff_path`, `acknowledged_at`
- Diff shows state file now also includes `run_id`, `cumulative_stat_path`, `acknowledged_at` (unchanged)

**Drift detail:**
The SPEC specifies schema with 5 fields:
```json
{
  "phase_3_7_acknowledged": true,
  "base_ref": "<git ref captured in Phase 2>",
  "head_sha": "<git rev-parse HEAD>",
  "cumulative_diff_path": "<absolute path>",
  "acknowledged_at": "<iso timestamp>"
}
```

The diff shows the actual implementation includes an additional `run_id` field:
```json
{
  "phase_3_7_acknowledged": true,
  "run_id": "<RRUN — the current review run id>",
  "base_ref": "...",
  "head_sha": "...",
  "cumulative_diff_path": "...",
  "cumulative_stat_path": "...",
  "acknowledged_at": "..."
}
```

This is **forward-compatible** (additional fields are benign) but represents **unspecced enhancement**. The `run_id` field is actually necessary for the resume logic to work (it's used in fast-forward and in the `review_resume_fast_forward` event emission), and `cumulative_stat_path` is actually used to validate artifact presence.

**Severity:** Minor. The implementation is *more correct* than the spec; the spec should have been tightened.

**Reason it might be wrong:** The spec is intentionally concise and leaves room for implementer judgment. Including `run_id` and `cumulative_stat_path` improves safety.

---

### Finding A4: ✅ PASS — `/z-maintain-docs --audit` state file path override (SPEC drift → internal consistency)

**Evidence:**
- SPEC.md line 109: says state file should be `z-harness/plans/<slug>/.maintain_docs_audit_state.json`
- TASKS.md T006 note: "SPEC drift — `/z-maintain-docs` has no slug concept (operates on docs/ tree). Orchestrator override: actual state file is `docs/llm/.maintain_docs_audit_state.json`"
- Diff shows: `commands/z-maintain-docs.md` Phase 2.3 uses `docs/llm/.maintain_docs_audit_state.json`
- Diff shows: `docs/llm/commands.json` line 144 declares `"state_file": "docs/llm/.maintain_docs_audit_state.json"`

**Analysis:**
The implementer made the right call. `/z-maintain-docs` is truly doc-repo-scoped, not plan-scoped. Using `z-harness/plans/<slug>/` would be nonsensical because the command doesn't have a slug. The override is **internally consistent**: both source and LLM-tier docs agree on the path.

**Severity:** Not an error; a known SPEC gap that was handled correctly.

---

### Finding A5: ✅ PASS — Implementer return schema: `cross_task_notes` field

**Evidence:**
- SPEC.md line 25: specifies "implementer's mark-done step (`commands/z-implement-all.md:418`) gets a new sub-step: before flipping `[~]` to `[x]`, if `cross_task_notes` is non-empty..."
- Diff shows `agents/implementer.md` updated with `cross_task_notes: [{task_id, note}]` field (optional, default empty)
- Diff shows `commands/z-implement-all.md` step 8 sub-step 0 processes the field before status flip (sub-step 1)
- Mark-done loop processes each note and appends `**Note:** <note>` to target task block in atomic TASKS.md write

**Confidence:** High. The processing order and atomic write semantics are correct.

---

### Finding A6: ✅ PASS — Event type `compaction_pause` payload across all three commands

**Evidence:**
- `/z-implement-all`: emits `compaction_pause` with `{trigger: "task_count"|"wall_time", tasks_since_pause, wall_minutes_since_pause, pending_remaining}`
- `/z-review-all` Phase 3.7: emits `compaction_pause` with `{trigger: "pre_consult", phase: "review_all_phase_4"}`
- `/z-maintain-docs --audit` Phase 2.3: emits `compaction_pause` with `{trigger: "pre_consult", phase: "maintain_docs_audit"}`
- README and `docs/llm/commands.json` document the event type with correct payload schema

**Confidence:** High. Payloads match SPEC and are self-consistent.

---

### Finding A7: ✅ PASS — Deleted `Z_HARNESS_PAUSE_AT_PCT` and `usage_pause` event

**Evidence:**
- Diff shows deletion across: `commands/z-implement-all.md`, `skills/z-implement-all/SKILL.md`, `commands/z-plan.md`, `skills/z-plan/SKILL.md`, `commands/z-plan-split.md`, `skills/z-plan-split/SKILL.md`, `README.md`
- TASKS.md T001 note: "T001 scope-extended to include `/z-plan` and `/z-plan-split` after reviewer flagged (additional files: commands/z-plan.md, skills/z-plan/SKILL.md, commands/z-plan-split.md, skills/z-plan-split/SKILL.md)"
- T009 note: exports re-run; final state shows 0 hits for `Z_HARNESS_PAUSE_AT_PCT` and `usage_pause` in source and exports

**Confidence:** High. Deletion is thorough and verified.

---

### Finding A8: ✅ PASS — Halt-flush occurs before trigger check in `/z-review-all` Phase 3.7

**Evidence:**
The Phase 3.7 breakpoint in `/z-review-all` fires *between Phase 3.5 (test run) and Phase 4 (consultant spawn)*, long before any halt collection. However, **this is NOT a violation** because:

1. Phase 3.7 is a **pre-consult gate**, not a batch-settle gate.
2. No halt signals are collected *during* Phase 3.7 (it's a user question, not a batch).
3. SPEC Invariant 1 applies only to `/z-implement-all` batch-settle: "No new compaction breakpoint may fire mid-batch."
4. The SPEC explicitly permits pre-consult breakpoints (line 71): "insert a new step between Phase 3.5 (test run) and Phase 4 (consultant spawn)".

**Confidence:** High. No violation.

---

### Finding A9: ⚠️ MINOR — Finalize skip behavior on compaction trigger is documented but not tested

**Evidence:**
- SPEC.md line 50: "the compaction-trigger check run... If a trigger fires: emit the `compaction_pause` event, push-notify, and exit cleanly with no new dispatch."
- Diff shows: "`If pending tasks remain but the loop exits due to a compaction trigger, the Finalize section is **skipped**`"
- No explicit test acceptance criteria in TASKS.md for "verify Finalize is not called on compaction pause"

**Analysis:**
The behavior is correct and documented. The lack of an explicit test case is a minor gap—acceptance criteria for T003 say "Clean exit (no new dispatch)" but don't explicitly verify Finalize skip. In practice, if Finalize runs when it shouldn't, the user will see spurious "no more eligible tasks" output, which is obvious. **Low risk.**

**Severity:** Minor (documentation/testing completeness, not behavior correctness).

---

### Finding A10: ✅ PASS — `/z-implement-all` counter logic (retries/rollbacks don't increment)

**Evidence:**
- SPEC.md line 47: "`tasks_since_pause`: incremented when a task transitions to `[x]` (done). **NOT** incremented on retries... **NOT** incremented when a task is rolled back to `[ ]`..."
- Diff shows: "`Increment `tasks_since_pause` by 1 (this task reached `[x]`; retries and rollbacks do not count)`"

**Confidence:** High. The step is placed *inside* the mark-done loop only when status actually flips to `[x]`, so rollbacks (which leave `[ ]`) and retries (which loop again but still end in `[x]` once) are handled correctly.

---

### Finding A11: ✅ PASS — Plain `/z-maintain-docs` (non-`--audit`) is unmodified

**Evidence:**
- SPEC.md line 122: "Do NOT add a breakpoint in plain (non-`--audit`) `/z-maintain-docs` runs"
- Diff shows: Phase 2.3 is gated with "only if `--audit` flag set"
- T006 acceptance criterion: "Plain (non-`--audit`) `/z-maintain-docs` is NOT modified"

**Confidence:** High.

---

## PRONG B — Spec Correctness & Gaps

### Finding B1: ⚠️ MAJOR — SPEC path for `/z-maintain-docs` audit state is incompatible with command design

**Evidence:**
- SPEC.md line 109: "`z-harness/plans/<slug>/.maintain_docs_audit_state.json` (slug-scoped)"
- Command structure: `/z-maintain-docs` does not have a slug parameter; it operates on the repo's entire docs/ tree
- Implementer resolution: uses `docs/llm/.maintain_docs_audit_state.json` instead

**Analysis:**
The SPEC asserts a slug-scoped path but the command is not slug-aware. This is a **SPEC error**, not an implementation error. The implementer correctly overrode it. However, **this is a known drift that was documented in TASKS.md T006**, so it was surfaced during implementation.

**Severity:** Major (SPEC is provably wrong). But **no action needed** — the implementer already fixed it and documented the divergence.

**Recommendation:** Amend SPEC.md or leave as-is? The SPEC is descriptive of intent ("slug-scoped"), but the implementation is correct. The drift is defensible as a SPEC simplification that didn't account for slug-free commands. **Acceptable as-is; document in amendment proposal if needed.**

---

### Finding B2: ⚠️ MAJOR — SPEC says "slug-scoped" for `/z-review-all` state file, but `/z-review-all` also doesn't have slug-aware invocation

**Evidence:**
- SPEC.md line 29: "`z-harness/plans/<slug>/.review_state.json` for review-all" (slug-scoped)
- SPEC.md line 89: "On every `/z-review-all` invocation, BEFORE entering Phase 0: ... 1. If `.review_state.json` exists in the slug dir, read it."

**Analysis:**
Unlike `/z-maintain-docs`, `/z-review-all` actually *does* have slug semantics—it receives a `--slug` argument (or discovers the slug from TASKS.md). The state file path is correctly slug-scoped in the implementation. **No error.**

---

### Finding B3: ✅ PASS — Edge case: single very long task (45 min) will trigger wall-time breakpoint after completion

**Evidence:**
- SPEC.md line 160: "Single very long task: A task that runs 45 min by itself will trigger the wall-time breakpoint AFTER it completes (at batch-settle), not during. **Acceptable** — pausing inside an in-flight subagent dispatch is impossible."

**Analysis:**
Correct. The spec acknowledges this and accepts it as reasonable. No issue.

---

### Finding B4: ✅ PASS — Edge case: run completes mid-counter-window (3/5 tasks done)

**Evidence:**
- SPEC.md line 159: "If `tasks_since_pause` is 3 when the final task completes, no breakpoint fires... **Correct: there's no work left to compact for.**"

**Analysis:**
Correct. No issue.

---

### Finding B5: ⚠️ MINOR — SPEC doesn't explicitly forbid compaction trigger during multi-cluster tree runs

**Evidence:**
- SPEC.md: specifies breakpoints for `/z-implement-all`, `/z-review-all`, `/z-maintain-docs --audit`
- Implementation supports tree-rooted plans from `/z-plan-split` (multiple `<slug>/<cluster>` paths)
- No explicit SPEC language on whether triggers behave per-cluster or globally

**Analysis:**
The `/z-implement-all` logic is per-invocation, so triggers reset on each cluster iteration in a tree run. This is correct (each cluster gets its own counter window). However, the SPEC doesn't state this explicitly. **No implementation error; just an edge case the SPEC could clarify.**

**Severity:** Minor (implementation is sensible; spec is silent).

---

### Finding B6: ✅ PASS — SPEC decision to recommend `/clear` over `/compact` is sound

**Evidence:**
- SPEC.md line 7: "Recommend `/clear` over `/compact` on resume — the harness's durable state lives in TASKS.md, so clearing reclaims more context with no safety loss. Codify 'no cross-task state in orchestrator memory' as a SPEC invariant."
- Invariant 2 (line 25): implements this by requiring cross-task notes be persisted before marking task `[x]`

**Analysis:**
Sound decision. SPEC Invariant 2 ensures durable state → `/clear` is safe.

---

### Finding B7: ✅ PASS — Env var defaults (5 tasks, 30 minutes) are reasonable

**Evidence:**
- SPEC.md line 42-43: defaults `5` and `30`
- PLAN.md D2: "multi-trigger: 5 tasks OR 30 wall-minutes"

**Analysis:**
Reasonable heuristics. No spec error.

---

### Finding B8: ⚠️ MINOR — SPEC doesn't address `/z-maintain-docs --audit` pre-consult breakpoint when stale concept set is empty

**Evidence:**
- SPEC.md line 118-120: "state file cleanup: deleted at run end"
- But: what if Phase 1 returns zero stale concepts? Does Phase 2.3 still fire?

**Analysis:**
Spec is silent. Implementation would still emit the breakpoint (no special case for empty set). **Acceptable**—even with zero stale concepts, the user gets to confirm they want to proceed with the audit (or not). Low risk.

---

### Finding B9: ✅ PASS — `--tasks` flag for `/z-implement-all` promotion artifacts is new and correctly specified

**Evidence:**
- Diff shows new `--tasks=<path>` flag in SKILL.md + commands.md
- SPEC.md doesn't mention this, but it's a new feature added alongside the compaction policy
- Implementation correctly derives `BASE` from the task file's parent directory

**Analysis:**
This is a **feature addition beyond SPEC scope** (SPEC.md is about compaction breakpoints, not artifact promotion). The feature is well-designed and correctly implemented. It should be mentioned in amendment/changelog, but it doesn't violate SPEC.

---

### Finding B10: ⚠️ MINOR — SPEC doesn't specify behavior if `/z-review-all` fast-forward environment restore partially fails (e.g., invalid `base_ref` variable expansion)

**Evidence:**
- Fast-forward logic: "set all variables Phase 4 requires from state-file fields"
- If a state-file field is malformed (e.g., `base_ref` points to deleted branch), no explicit error handling

**Analysis:**
The spec assumes git/bash don't fail during variable assignment. In practice, Phase 4 will fail immediately if `base_ref` is invalid (git will error), which is acceptable—the state file is corrupted. **No gap; fail-fast is appropriate.**

---

## Summary

### PRONG A (Implementation Faithfulness): **PASS with minor notes**

- Critical ordering for `/z-implement-all` batch-settle is correct ✅
- `/z-review-all` state invalidation logic is correct ✅
- `/z-maintain-docs` state file path override is correct and documented ✅
- Event payloads are consistent ✅
- **Minor drift (A3, A9):** State file schema adds fields not in SPEC, and Finalize skip lacks explicit test acceptance criterion. Both are low-risk.

**Overall:** Implementation is faithful to spec and correct. The minor drifts are improvements.

---

### PRONG B (Spec Correctness): **PASS with one known gap**

- **B1 (Major):** SPEC assumes `/z-maintain-docs` is slug-scoped, but it isn't. Implementer correctly overrode to `docs/llm/.maintain_docs_audit_state.json`. This is a **known drift documented in T006** and is acceptable.
- **B5 (Minor):** SPEC doesn't clarify behavior on tree-rooted plans (per-cluster vs global trigger reset). Implementation is correct (per-cluster).
- **B8 (Minor):** SPEC doesn't address empty stale concept set at audit breakpoint. Implementation fires breakpoint anyway; acceptable.
- **B9 (Minor):** New `--tasks` flag is outside SPEC scope but well-designed.

**Overall:** SPEC is sound. One major gap (B1) was already identified and handled. The rest are minor clarifications that don't affect correctness.

---

## Recommended Amendments

### Amendment A1: Tighten `/z-review-all` state file schema in SPEC

Amend SPEC.md line 78-86 to add `run_id` and `cumulative_stat_path` as required fields. These improve safety and are already implemented.

### Amendment A2: Clarify `/z-maintain-docs --audit` state file path

Amend SPEC.md line 109 to note: "State file: `docs/llm/.maintain_docs_audit_state.json`. Note: `/z-maintain-docs` is not slug-scoped, so the path is repo-rooted under docs/ instead of z-harness/plans/<slug>/."

### Amendment A3: Add explicit test acceptance criterion for Finalize skip

Amend TASKS.md T003 acceptance criteria to include: "Verify Finalize section is not called when compaction trigger fires during a batch (user sees no 'no more eligible tasks' summary)."

---

## Conclusion

**Status: READY TO SHIP** 

- Implementation is faithful to SPEC and correct.
- All known gaps (SPEC drift) were documented in TASKS.md and handled appropriately.
- No blockers or critical issues found.
- Three minor improvements (amendments A1–A3) recommended for SPEC tightening, but not required for this ship.

