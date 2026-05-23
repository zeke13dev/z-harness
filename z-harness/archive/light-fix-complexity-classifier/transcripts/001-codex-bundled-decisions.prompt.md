# Mode: bundled decisions (single decision, focused consult)

## Input artifact

**Problem:** z-harness dispatches every task to Sonnet implementer on first attempt. Hard tasks waste a Sonnet cycle before failing Codex review and getting upgraded via env-var signal.

**Solution:** Right-size implementer model per task using a Haiku complexity classifier.

**Taxonomy:** `low` (reserved, maps to Sonnet today), `medium` (Sonnet — current default), `high` (Opus on first attempt). Retry bump stays: any task failing Codex review once gets bumped one tier.

**Current tooling:** `Agent(...)` now supports per-call `model` override parameter (e.g., `model="sonnet"` or `model="opus"`).

---

## Decision

**Where should task-complexity classification happen?**

### Option A — Plan-time stamping

**Mechanism:**
- During `/z-plan` Phase 8 (TASKS.md generation) and `/z-amend` (full-mode TASKS.md edits), dispatch a Haiku `complexity-classifier` subagent in parallel per task.
- Append `**Complexity:** low|medium|high` to each task block in TASKS.md.
- The stamp is visible to the user, hand-editable as override.
- `/z-implement-all` reads the stamp at dispatch time.

**Tradeoffs:**
- **Cost timing:** Pays classifier cost once per task at plan time, even if task is later removed/superseded by `/z-amend` (sunk cost).
- **Visibility:** Dial is visible and overridable in task file itself.
- **Z-amend churn:** Requires `/z-amend` to re-classify added/modified tasks. Risk if classifier outputs differ on re-run (non-deterministic? input-sensitive?).
- **State accumulation:** No access to prior-task outcomes; could incorporate them if we added state, but we don't today.

### Option B — Dispatch-time classification

**Mechanism:**
- `/z-implement-all` and `/z-implement-next` dispatch the Haiku classifier *just before* spawning the implementer for each task.
- No edits to TASKS.md.
- Classifier result not written anywhere unless we log it.

**Tradeoffs:**
- **Cost timing:** Pays classifier cost every dispatch, including every retry. Could cache in memory per task if we want to avoid re-classifying on retry, but that's new state.
- **Visibility:** Invisible unless we log to events.jsonl. User cannot hand-override without editing orchestrator code.
- **Z-amend:** No interaction — tasks added via `/z-amend` get classified fresh on dispatch, no re-run risk.
- **Learning:** Could in principle look at prior tasks' outcomes (T003 misclassified as low, failed; bump T004 if similar signature). But that requires tracking similarity + prior outcomes, which we don't have today.

### Option C — Hybrid (cache + on-edit re-check)

**Mechanism:**
- Store classifier result in TASKS.md as `**Complexity:**` stamp (like Option A).
- But at dispatch time: if task block has been edited since stamp was written (computed via hash of task block or timestamp), re-classify before dispatch.
- Otherwise, use cached stamp.

**Tradeoffs:**
- **Cost timing:** Amortizes to plan-time cost for stable tasks, dispatch-time cost only for changed tasks.
- **Churn risk:** Only re-classifies if task *has* changed, reducing spurious re-runs if classifier is non-deterministic.
- **Visibility + override:** Keeps visible stamp + override capability from Option A, without the "stale stamp when task changes" risk.
- **Complexity:** Adds logic to detect "has this task changed since the stamp" — doable via `mtime` on TASKS.md or hash of the task block itself.

---

## Context / constraints

### Existing code patterns

**z-implement-all.md lines 158-170:** Currently sets `Z_HARNESS_RETRY_UPGRADE=opus` env var if task has `**Complexity:** high` or if retry cycle ≥ 2. This is an *advisory signal*, not a model override — implementer reads it in its prompt.

**Agent() tool:**  Now supports `model="sonnet"` / `model="opus"` per-call override, so we can pass the model directly when dispatching.

**z-plan.md line 224:** TASKS.md generation happens in Phase 8.

### Open questions

1. **Is the "/z-amend churn" risk real?** If classifier is deterministic on same input, Option A's churn risk is zero. If it has non-determinism or its output drifts based on order/context, churn could happen and confuse the user ("why'd the complexity jump?").

2. **What's the actual cost of dispatch-time classification?** Haiku classifier is cheap (≤10s probably), but every task × every retry × every re-dispatch adds up. Is it negligible vs. plan-time cost?

3. **Is Option C's "edit detection" worth the added logic?** Or is Option A's simplicity better — just re-classify on `/z-amend` if it changes the task?

4. **Learning from prior outcomes:** Should we design for future "look at T003's outcome and adjust T004 classification" capability, even if we don't build it now? That would favor Option B (dispatch-time) or Option C (hybrid with outcome-aware cache). Option A (pure plan-time) would require retrofitting a state table.

---

## Ask

**For this single decision, recommend A / B / or C** with reasoning. Flag:
- Any tradeoff I've missed
- Whether the "/z-amend churn" risk is real (and if so, how to mitigate in Option A)
- Whether Option C's complexity is justified or if one of A/B is simpler-right
- Any design interaction with retry logic, caching, or future outcome-learning
- Your assessment of "how much does dispatch-time cost add up"

**Constraints:**
- This is a light fix, not a feature. Prefer simplicity.
- Must integrate cleanly with existing `/z-implement-all` and `/z-amend` orchestration.
- Codex review is universal (non-negotiable), so retry bump remains a separate concern.
