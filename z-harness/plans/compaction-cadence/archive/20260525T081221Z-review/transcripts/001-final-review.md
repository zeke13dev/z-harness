# Final Review — Compaction-Cadence Plan
**Mode:** final-review-2pronged  
**Date:** 2026-05-25  
**Reviewer:** Claude Code (Haiku 4.5)  

## PRONG A: Implementation Faithfulness

### A1: BLOCKER — Batch-settle trigger check placement ambiguity

**Severity:** BLOCKER  
**Evidence:** commands/z-implement-all.md step 8, sub-step 6  

**Issue:** The diff embeds the "Batch-settle compaction check" as sub-step 6 of "Mark done" (step 8), which is a per-task step executed inside the parallel loop. However, the SPEC mandates the trigger check runs **once per batch** after all tracks finish. This is a structural contradiction: if the check runs per-task, it will fire multiple times per batch.

The SPEC requires strict ordering (Invariant 1, lines 18–24):
1. Terminal statuses reached
2. TASKS.md atomic write completed  
3. `batch_done` event emitted
4. Halt signals surfaced to user
5. **Only then** trigger check runs

**Pushback:** One counterargument is that the description says "once per batch" as a semantic contract and the implementer will ensure single execution. However, embedding a batch-level check in a per-task step is error-prone — future maintainers will reasonably assume step 8 sub-step 6 runs per task. The safer path is to move the trigger check outside the per-task loop into a dedicated batch-settle phase after `batch_done` and halt-flush, before looping to step 1.

---

### A2: MAJOR — Finalize skip condition not enforced

**Severity:** MAJOR  
**Evidence:** commands/z-implement-all.md lines 234, 236, 495–497  

**Issue:** The SPEC says "exit without running Finalize" when compaction fires. The diff narrates this: "the Finalize section is **skipped**" — but provides no code or pseudocode implementing the conditional. How does the main loop know to skip Finalize? Is there a `COMPACTION_FIRED` flag? The behavior is narrated but not gated.

**Pushback:** Possibly the orchestrator uses `exit` rather than `break` when the trigger fires, naturally skipping Finalize. But this should be stated explicitly, not left implicit.

---

### A3: MINOR — Missing PENDING_REMAINING computation statement

**Severity:** MINOR  
**Evidence:** commands/z-implement-all.md "Compaction breakpoint policy" section  

**Issue:** Event emission references `$PENDING_REMAINING` but the trigger-check pseudocode doesn't show where this variable is set. The narrative says "count the remaining `[ ]` tasks" but only in the "On trigger" subsection, not in the main trigger-check block. Should be part of pre-trigger setup.

**Pushback:** Minor — narrative makes intent unambiguous; pseudocode is incomplete but clear enough for implementation.

---

### A4: MINOR — maintain-docs pre-consult event run-id

**Severity:** MINOR  
**Evidence:** commands/z-maintain-docs.md Phase 2.3  

**Issue:** Pre-consult event uses `log-event.sh "docs" compaction_pause` rather than `log-event.sh "$RRUN" ...`. Unlike `/z-review-all`, `/z-maintain-docs` may lack a traditional run-scoped ID. Pattern should be consistent across breakpoints. The context is not clarified.

**Pushback:** `/z-maintain-docs` might be stateless; `"docs"` context might be intentional. Should be explicitly justified.

---

### A5: MINOR — /z-plan and /z-plan-split scope creep unspecified

**Severity:** MINOR  
**Evidence:** TASKS.md T001 note; cumulative.diff includes `commands/z-plan.md`, `commands/z-plan-split.md`  

**Issue:** SPEC.md and PLAN.md do not mention `/z-plan` or `/z-plan-split`, only `/z-implement-all` and `skills/z-implement-all/SKILL.md` for phase 1. Yet the diff edits z-plan files. TASKS.md T001 calls this "scope creep — /z-plan and /z-plan-split also held the dead guard. Swept as part of T001." This drift was introduced post-hoc, outside SPEC scope.

**Pushback:** The SPEC does mention exports regeneration. If `/z-plan` and `/z-plan-split` have exports and held the dead guard, cleaning them is correct. But the SPEC should have been explicit to avoid surprise scope creep.

---

### A6: PASS — State file paths correctly reflected in commands.json

**Severity:** PASS  
**Evidence:** docs/llm/commands.json entries  

**Result:** JSON correctly documents:
- `z-review-all`: `state_file: "z-harness/plans/<slug>/.review_state.json"`
- `z-maintain-docs`: `state_file: "docs/llm/.maintain_docs_audit_state.json"`

The maintain-docs override is captured in LLM tier.

---

## PRONG B: Spec Correctness

### B1: MAJOR — maintain-docs state file breaks slug-scoping invariant

**Severity:** MAJOR  

**Issue:** SPEC.md line 28 states state files are "slug-scoped, not run-scoped" (Invariant 3). But `/z-maintain-docs --audit` has no slug concept. The implementer placed the state file at `docs/llm/.maintain_docs_audit_state.json` (repo-wide, not slug-scoped). This violates the invariant: two concurrent plans calling `/z-maintain-docs --audit` will share the same state file, risking race conditions.

**Implication:** This is a SPEC gap, not an implementation bug. The SPEC assumed all state files would be slug-scoped but `/z-maintain-docs` invalidates that assumption.

**Amendment needed:** SPEC.md should either:
1. Acknowledge that `/z-maintain-docs` is slug-agnostic and place state file at `docs/llm/.maintain_docs_audit_state.json`, OR
2. Prescribe a different path scheme (e.g., state file names derived from audit batch ID).

Current state is acceptable for this ship but needs amendment to prevent future confusion.

---

### B2: MINOR — cross_task_notes append order not specified

**Severity:** MINOR  

**Issue:** SPEC.md line 25 and the diff say "append ... as a new line" but don't clarify: if a task already has a `**Note:**` line, should new notes append after existing ones or replace? The word "append" suggests stacking, but potential for clutter is not addressed.

**Pushback:** "Append" is clear — add the line. Multiple notes are acceptable.

---

### B3: MINOR — Corrupt state recovery event transient

**Severity:** MINOR  

**Issue:** Pre-Phase 0 recovery (z-review-all lines 23–29) emits `review_state_corrupt` with event run context `"pre-resume"`. This event will not attach to any run's event stream (no $RRUN established until Phase 0). Future analysis might miss it.

**Pushback:** Low impact — event is emitted regardless. Better practice is establish $RRUN early, but not critical.

---

### B4: PASS — Invariant 2 correctly implemented

**Severity:** PASS  

**Result:** SPEC Invariant 2 (line 25) — cross_task_notes processed before status flip — correctly implemented. Downstream tasks see notes before producing task marked [x].

---

### B5: PASS — Resume semantics for /z-implement-all idempotent

**Severity:** PASS  

**Result:** SPEC line 27 — /z-implement-all needs no state file. Diff correctly implements this: no state file, re-read TASKS.md and proceed.

---

## Summary

| Finding | Severity | Recommendation |
|---------|----------|-----------------|
| A1: Batch-settle trigger check placement | BLOCKER | Restructure loop to move trigger check outside per-task loop |
| A2: Finalize skip condition not enforced | MAJOR | Add explicit flag or exit statement to gate Finalize skip |
| A3: PENDING_REMAINING variable not computed | MINOR | Add variable assignment in trigger-check pseudocode |
| A4: maintain-docs event run-id inconsistent | MINOR | Document intentionality or align with /z-review-all pattern |
| A5: /z-plan scope creep | MINOR | Amend SPEC to explicitly include z-plan and z-plan-split in phase 1 |
| B1: maintain-docs violates slug-scoping invariant | MAJOR | Amend SPEC to acknowledge non-slug-scoped state file for maintain-docs |
| B2: cross_task_notes append order | MINOR | No change (append semantics clear) |
| B3: Corrupt state recovery event transient | MINOR | No change (low impact observability gap) |

**Ship gating:** Blockers A1 and A2 must be resolved before implementation is acceptable. Major findings B1 can ship but requires amendment post-ship. All others are minor clarifications.
