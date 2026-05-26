MODE: plan-review

## Artifact: SPEC.md & PLAN.md for compaction-cadence

The orchestrator (/z-implement-all) replaces a non-functioning Z_HARNESS_PAUSE_AT_PCT guard with deterministic breakpoints:
- /z-implement-all: triggers on (5 tasks completed) OR (30 wall-minutes) at batch-settle
- /z-review-all: unconditional pre-Phase-4 breakpoint, dismissable via marker file
- /z-maintain-docs --audit: pre-consultant-batch breakpoint, dismissable via marker file

Resume is idempotent via re-reading TASKS.md. New event: `compaction_pause` with trigger/phase payload.

## Invariant 2 (critical): "No orchestrator-side cross-task memory"

Any signal needed by a downstream task must be persisted to TASKS.md (e.g. as **Note:** line) before current task is marked complete. This makes /clear safe.

## Context: Current dispatcher behavior

From z-implement-all.md lines 125, 418, 302, 163:
- Main thread re-reads TASKS_FILE between batches: "You'll re-read between batches to pick up status flips."
- Task completion (step 8): "Flip [~] to [x] in $TASKS_FILE. Add a one-line completion note (e.g. 'T004 done; reviewer flagged 1 minor (deferred); 3/3 tests passed')."
- Halt semantics (step 4 parallelism): "If one track returns spec_problem/decision_needed/needs_clarification, that *track* halts and you collect the question. **In-flight tracks for other tasks continue.** Only after the batch completes do you present the collected halts to the user."
- Decision gates (line 302): "Record the decision in $BASE/archive/$RUN/decisions-late.md. After answer, re-spawn implementer."

From z-review-all.md (pre-consult breakpoint spec):
- Phase 3.7 writes marker file `.pre_consult_acknowledged` when user chooses (b) Proceed now.
- Resume: "write a marker file archive/<run>/.pre_consult_acknowledged when user chooses (b); presence of this marker on resume means 'Phase 3.7 already decided, skip directly to Phase 4'."

## Critique focus

**Invariant 2:** Is it actually true today? Anything in implementer/reviewer dispatch that violates it? 
**Batch-settle pause point:** Fragile? Missing synchronization?
**Marker-file resume scheme:** In /z-review-all, any holes in idempotence?

Critique this plan — what's wrong, missing, or fragile? Focus on invariant 2 violations, batch-settle timing, and marker-file semantics. Be specific. ≤300 words.
