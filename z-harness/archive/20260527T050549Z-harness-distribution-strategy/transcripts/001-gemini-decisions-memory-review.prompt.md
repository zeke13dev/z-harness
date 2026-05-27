# Mode: bundled-decisions

## Context: z-harness memory system review — 4-state terminal taxonomy for Phase 9 of /z-implement-all

This is Phase 3 of /z-plan for the memory-system review. The brainstorm (Phase 2) settled on Codex framing: instrument Phase 9 of /z-implement-all with a 4-state terminal taxonomy before deciding any policy change on memory emission.

**Confirmed empirical signal:**
- MEMORIES-FLAT.md has 2 header lines / 0 memories (file effectively empty).
- Phase 9 fires (per z-implement-all SKILL.md) but is invisible — no user notification of skip conditions.

**Current scripts/run-memory-review.sh skip-condition vocabulary:**
- `ready` / `skipped {empty_diff, all_tasks_skipped, tags_missing, no_plan_dir, missing_args}`

**Real bugs found in current code:**
1. Line 92: `tags_missing` emits `review_agent_failed` event — semantically wrong, it's a context skip not agent failure
2. Lines 15, 29: `no_plan_dir` + `missing_args` emit NOTHING to stdout — entirely invisible
3. Phase 9 fires but user never sees skip-reason; Phase 9 success/failure distinction is opaque

## 5 consult-flagged decisions

### D1. Compute 4-state terminal in run-memory-review.sh vs in SKILL.md callers
- Tentative: In `run-memory-review.sh` (single source of skip-condition logic)
- Alternative: Compute in each SKILL.md caller (/z-implement-all, /z-review-all, /z-debug Phase 9b)
- Tradeoff: Centralization vs. caller-specific context capture

### D2. New `memory_review_terminal` event vs overload existing `phase_end`
- Tentative: New event with {state, skip_reason?, parent_command, candidates?, accepted?}
- Alternative: Overload existing `phase_end` with `terminal_state` field
- Tradeoff: Explicit new event (breaks existing log parsers) vs. backward-compat field nesting

### D5. Wire /z-debug Phase 9 post-mortem to dispatch review-agent
- Tentative: YES — Phase 9b in skills/z-debug/SKILL.md, calls run-memory-review.sh with parent_command=debug
- Alternative: NO — narrative-only post-mortem
- Rationale: /z-debug post-mortems contain the densest memory signal in harness (failures, action items, timeline); not dispatching is leaving signal on the floor. Currently invisible.

### D7. Add optional `debug_md_path` to review-agent input contract vs replace spec_path
- Tentative: Optional additive (spec_path unchanged when parent_command=debug, add debug_md_path)
- Alternative: Replace spec_path with debug_md_path when parent_command=debug
- Tradeoff: Contract stability vs. semantic clarity (spec vs. debug as primary input)

### D11. On skipped_broken_context: push-notify user vs silent vs notify-only-for-env-bugs
- Tentative: Push-notify once per run with reason
- Alternative B: Silent (no notification)
- Alternative C: Notify only for env bugs (no_plan_dir/missing_args), silent for tags_missing
- Rationale: Visibility is why Phase 9 exists; silent skips defeat the purpose.

## Relevant code context

**run-memory-review.sh skip conditions (current):**
```bash
# Line 47–69: empty_diff
if git diff --quiet "${BASE_REF}..HEAD"; then
  echo "STATUS: skipped empty_diff"
  if [[ -x "$LOG_EVENT" ]]; then
    bash "$LOG_EVENT" "$RUN" "phase_end" \
      '{"name":"memory_review","skipped":true,"skip_reason":"empty_diff"}' || true
  fi
  exit 0
fi

# Line 72–85: all_tasks_skipped (only if implement-all)
if [[ -f "$TASKS_FILE" && "$PARENT_COMMAND" == "implement-all" ]]; then
  COMPLETED_COUNT="$(grep -c '\[x\]' "$TASKS_FILE" 2>/dev/null || true)"
  if [[ "${COMPLETED_COUNT:-0}" -eq 0 ]]; then
    echo "STATUS: skipped all_tasks_skipped"
    if [[ -x "$LOG_EVENT" ]]; then
      bash "$LOG_EVENT" "$RUN" "phase_end" \
        '{"name":"memory_review","skipped":true,"skip_reason":"all_tasks_skipped"}' || true
    fi
    exit 0
  fi
fi

# Line 88–96: tags_missing (SEMANTIC BUG)
if [[ ! -f "$TAGS_FILE" ]]; then
  echo "STATUS: skipped tags_missing"
  if [[ -x "$LOG_EVENT" ]]; then
    bash "$LOG_EVENT" "$RUN" "review_agent_failed"  # <-- WRONG EVENT
      '{"reason":"tags_missing"}' || true
  fi
  exit 0
fi

# Line 14–16: missing_args (NO EVENT)
if [[ $# -lt 2 ]]; then
  echo "STATUS: skipped missing_args"
  exit 0
fi

# Line 28–30: no_plan_dir (NO EVENT)
if [[ -z "$BASE" ]]; then
  echo "STATUS: skipped no_plan_dir"
  exit 0
fi
```

**review-agent inputs (agents/review-agent.md line 14–22):**
```
- run_dir: path to run directory
- cumulative_diff_path: pre-computed diff
- spec_path: SPEC.md if it exists (may be empty)
- tags_path: docs/llm/TAGS.txt
- index_path: docs/llm/INDEX.json
- run_id: RUN string
- parent_command: "implement-all" | "review-all"
```
Currently no provision for `debug_md_path` when parent_command=debug.

**z-debug SKILL.md Phase 9 (current):**
- Phase 9 writes `## Post-mortem` section to single unified DEBUG.md file
- No dispatch to review-agent; post-mortem is narrative-only
- User is asked: "Convert action items into follow-up tasks?" — manual entry point
- No signal mining from the post-mortem itself

**z-implement-all SKILL.md Phase 9 (current):**
- Calls `bash scripts/run-memory-review.sh "$RUN" "implement-all"`
- Parses three artifact paths from stdout (lines 2–4)
- Dispatches review-agent with those paths
- Parse failure → soft skip with push-notify + telemetry
- Success → review-agent returns fenced JSON with up to 3 candidates

## Ask

For each of the 5 consult-flagged decisions (D1, D2, D5, D7, D11):

1. **Recommendation** — which option should we pick and why?
2. **Concrete risk** — what could go wrong with the chosen path?
3. **Cross-decision interactions** — any dependencies, conflicts, or second-order effects you spot among D1, D2, D5, D7, D11?

Be terse: 2–4 bullets per decision. Do not recommend process changes, only technical/architectural choices on these 5 decisions. This is internal planning, not sensitive data.
