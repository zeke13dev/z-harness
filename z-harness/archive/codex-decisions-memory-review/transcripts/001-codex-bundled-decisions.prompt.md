# Mode: bundled-decisions

## Context: z-harness memory system review — 4-state terminal taxonomy for Phase 9 of /z-implement-all

### Input artifact: Decision summary (12 decisions, 5 consult-flagged)

**CONSULT-FLAGGED DECISIONS:**

**D1. Locus of 4-state terminal computation**
- Tentative: In `run-memory-review.sh` (single source of skip-condition logic)
- Alternative: Compute in each SKILL.md caller

**D2. New event shape?**
- Tentative: New `memory_review_terminal` event with {state, skip_reason?, parent_command, candidates?, accepted?}
- Alternative: Overload `phase_end` with `terminal_state` field

**D5. Wire /z-debug post-mortem to dispatch review-agent?**
- Tentative: YES — Phase 9b in skills/z-debug/SKILL.md, calls run-memory-review.sh with parent_command=debug, feeds DEBUG.md as extra context. /z-debug post-mortems contain the densest memory signal in the harness; not dispatching is leaving signal on the floor.
- Alternative: NO — narrative-only

**D7. How does review-agent learn DEBUG.md?**
- Tentative: Add optional `debug_md_path` field to its input contract
- Alternative: Replace `spec_path` with `debug_md_path` when parent_command=debug

**D11. Default behavior on skipped_broken_context?**
- Tentative: Push-notify the user once per run with the reason (whole point is visibility)
- Alternative B: Silent
- Alternative C: Notify only for env bugs (no_plan_dir/missing_args), silent for tags_missing

### Relevant code context

Current `run-memory-review.sh` skip conditions (lines 47-96):
- empty_diff → emits phase_end with skip_reason (OK)
- all_tasks_skipped → emits phase_end with skip_reason (OK)
- tags_missing → emits review_agent_failed semantic mismatch — it's a context skip, not agent failure
- no_plan_dir → emits NOTHING (invisible failure)
- missing_args → emits NOTHING (invisible failure)

review-agent inputs (agents/review-agent.md lines 14-22):
```
run_dir, cumulative_diff_path, spec_path, tags_path, index_path, run_id, parent_command
```
Currently no provision for debug_md_path when parent_command=debug.

z-debug SKILL.md Phase 9 appends to single DEBUG.md file (unified artifact pattern). Currently: no post-mortem dispatch to review-agent.

### Non-consult decisions (context only):
- D3: Fix tags_missing mis-classification
- D4: no_plan_dir/missing_args emit terminal event (soft-skip)
- D6: Extend run-memory-review.sh for parent_command=debug vs sibling helper
- D8: Manual smoke test of /z-improve
- D9: qt-bot-remote check via qt-bot-remote skill
- D10: Surface in /z-stats Phase 4b
- D12: No retroactive migration

### Ask

For each consult-flagged decision (D1, D2, D5, D7, D11):
1. **Recommendation** — what should we do?
2. **≥1 concrete risk** — what could go wrong?
3. **Cross-decision interactions** — any dependencies or conflicts you spot among these 5?

Be terse (2-4 bullets per decision).
