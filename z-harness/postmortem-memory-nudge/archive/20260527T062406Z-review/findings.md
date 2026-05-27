# Final review — postmortem-memory-nudge
Run: 20260527T062406Z-review
Base ref: HEAD (work uncommitted; diff = working tree)
Diff stats: 8 plan-relevant files + docs (T009 deferred); core: ~750 insertions / ~50 deletions

## Prong A — Implementation drift

### Severity: blocker

**A-1. z-debug Phase 10 review-agent dispatch has wrong field name + missing required field**
- *From: Gemini, verified.*
- `skills/z-debug/SKILL.md` Phase 10 step 3.d dispatches with `slug: <Z_HARNESS_SLUG>` and no `run_id:`. The other two orchestrators pass `run_id: <RUN|RRUN>` (verified in `skills/z-implement-all/SKILL.md` and `skills/z-review-all/SKILL.md`). The review-agent contract uses `run_id` to construct candidate `source: incident:<run_id>`.
- *One reason it might be wrong:* The agent could fall back to `slug` if `run_id` is absent. Verified: it can't — the contract has no such fallback.
- **Fix:** Replace `slug: <Z_HARNESS_SLUG>` with `run_id: <RUN>` in the dispatch prompt.

**A-2. Phase 7 (z-review-all) violates SPEC §301 "agent failures are NOT terminal states"**
- *From: Codex, verified.*
- `skills/z-review-all/SKILL.md` Phase 7 step 5 emits `memory_review_terminal{state:ran_empty, skip_reason:review_agent_failed}` on both no-fenced-block and malformed-json paths.
- `skills/z-implement-all/SKILL.md` Phase 9 step 5 explicitly does NOT (matches SPEC: "No memory_review_terminal event — this is an agent failure class, not a skip or terminal state.").
- SPEC §`/z-stats Phase 4b` line 300-303: "All other `review_agent_failed` or `review_agent_malformed` events are NOT remapped to terminal states — they remain orthogonal failure classes."
- *One reason it might be wrong:* The T006 per-task reviewer instructed the implementer to add this; could be defensible as "single terminal event per invocation." Verified against SPEC — invariant explicitly forbids. Implementer followed reviewer; reviewer was wrong vs SPEC.
- **Fix:** Remove the two `memory_review_terminal` emissions on agent-failure paths in z-review-all Phase 7 step 5. Keep `review_agent_failed` / `review_agent_malformed` events; emit no terminal event.

### Severity: major
- (none unique to Prong A beyond the above blockers)

### Severity: minor
- `commands/z-debug.md` Phase 10 description summary references the SKILL but doesn't restate the `run_id` field — would inherit the A-1 bug. Same fix applies.

## Prong B — Spec gaps

### Severity: blocker
- (none)

### Severity: major

**B-1. SPEC under-specifies the z-debug review-agent dispatch field list**
- *From: Gemini.*
- SPEC §`skills/z-debug/SKILL.md` Phase 10 step 5 says: "Dispatch review-agent with `parent_command: debug` and the input fields: `cumulative_diff_path`, `spec_path`, `tags_path`, `debug_md_path`."
- Omits `run_id`, `run_dir`, `index_path` — all required per `agents/review-agent.md`.
- This omission directly enabled A-1.
- **Fix:** Expand the SPEC field list to be explicit. Or replace with "all fields per `agents/review-agent.md` input contract, with `debug_md_path` from LINES[4]."

**B-2. SPEC has stale mapping-table entry `debug_not_shipped`**
- *From: Gemini.*
- `SPEC.md` §`run-memory-review.sh` mapping table contains `debug_not_shipped`, leftover from Phase 7 review's earlier draft. Final skip reason is `debug_md_missing` (consistent everywhere else in SPEC + impl).
- **Fix:** Replace `debug_not_shipped` with `debug_md_missing` in the mapping table.

**B-3. SPEC silent on what `/z-stats` does with old `review_agent_call` events**
- *From: Codex.*
- SPEC §`z-stats` Phase 4b documents back-compat for old `phase_end{name:memory_review}` and `review_agent_failed{reason:tags_missing}`. It does not address `review_agent_call` events (which existed pre-refactor and recorded successful-dispatch counts).
- Implementer made the correct call (omit from terminal-state aggregation; they remain queryable separately).
- **Fix:** Add a one-line SPEC clarification that `review_agent_call` events are NOT remapped into terminal states.

### Severity: minor
- SPEC phrasing "Line 5 is debug-only" could be clearer ("for non-debug parents, stdout ends at line 4"). Implementation is correct.
- SPEC §Phase C wording on dedup-clear timing is ambiguous ("once per top-level invocation"). Implementation correctly clears at Phase 0 / top of Phase 10.

## Consensus vs disagreement

**Both LLMs flagged (high-confidence):** none directly overlap, but the two blockers (A-1 from Gemini, A-2 from Codex) are independently confirmed against the diff and SPEC. They cover different aspects of cross-orchestrator consistency.

**Only one flagged:**
- Gemini: A-1 (z-debug field name), B-1 (under-specified field list), B-2 (stale `debug_not_shipped`).
- Codex: A-2 (Phase 7 invariant violation), B-3 (`review_agent_call` back-compat silence).

Both reviewers missed the other's primary finding. Both findings are real after verification — they were just looking at different cross-task edges.

## Summary

- 2 Prong-A blockers (both real, both fixable in <10 lines).
- 3 Prong-B major spec gaps (B-1 directly caused A-1; B-2 is stale text; B-3 is a one-line clarification).
- No P-A majors, no P-B blockers.

The cross-skill consistency invariants (`run_id` field across all dispatches; "agent failures are orthogonal" everywhere) are violated in exactly the place a per-task review can't see — between separate task implementations of "mirror this pattern."
