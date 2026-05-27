# Phase 3 — Decisions final

## Cross-LLM verdict

Both Gemini and Codex endorse all 5 tentative calls (D1, D2, D5, D7, D11) and
flag overlapping risks. No disagreements.

## Mandatory "one reason it might be wrong" check + final calls

### D1. Compute 4-state terminal in `run-memory-review.sh`
- **Reason it might be wrong:** Caller-specific semantics could turn the helper
  into a giant `if [[ parent_command == … ]]` tree (implement-all wants
  completed-task count, debug wants `status: shipped`, review-all has neither).
  Argument creep risk.
- **Mitigation accepted:** Use a single switch on `$PARENT_COMMAND` for the
  small differences in skip-rules; refuse to absorb any logic beyond
  skip-classification + terminal-state emission.
- **Final call:** Compute in the helper, with a hard limit: the helper only
  decides "should the agent run, and if not, why" and emits the terminal
  event. The orchestrator owns everything else.

### D2. New `memory_review_terminal` event
- **Reason it might be wrong:** Adds a fourth event kind that `/z-stats`
  Phase 4b must parse (alongside `phase_end`, `review_agent_failed`,
  `review_agent_malformed`). Orphaned events risk if `/z-stats` integration
  isn't shipped in the same plan.
- **Mitigation accepted:** `/z-stats` Phase 4b update is in-scope as a task
  in this plan (D10), not deferred. The new event isn't released into the wild
  without a consumer.
- **Final call:** New event. Payload schema:
  ```json
  {
    "state": "not_applicable|skipped_broken_context|ran_empty|needs_user",
    "skip_reason": "empty_diff|all_tasks_skipped|tags_missing|no_plan_dir|missing_args|null",
    "parent_command": "implement-all|review-all|debug",
    "candidates": 0,    // 0 unless state == needs_user or ran_empty
    "accepted": 0       // 0 unless state == needs_user
  }
  ```

### D5. Wire `/z-debug` post-mortem to dispatch review-agent
- **Reason it might be wrong:** `/z-debug` post-mortems written before fix
  verification settles can produce speculative / single-run-specific
  candidates that pollute the knowledge base. (Gemini's "noise risk";
  Codex's "thin or speculative post-mortems" risk.)
- **Mitigation accepted:**
  - Gate Phase 9b on DEBUG.md `status: shipped` (already set at the end of
    Phase 10 in `/z-debug`).
  - Update the review-agent prompt to explicitly say: "for parent_command=debug,
    filter for generalizable invariants and root-cause patterns, NOT
    single-run patches."
- **Final call:** YES. Add Phase 9b in `skills/z-debug/SKILL.md` after the
  Post-mortem section is finalized.

### D7. Optional additive `debug_md_path` in review-agent input contract
- **Reason it might be wrong:** Agent prompt now has a 2-way conditional
  ("which artifact is primary, spec_path or debug_md_path?"). Prompt
  complexity creep.
- **Mitigation accepted:** One explicit rule in the agent prompt:
  > When `parent_command: debug`, `debug_md_path` is the primary artifact;
  > `spec_path` is supplementary context. Otherwise, `spec_path` is primary
  > and `debug_md_path` is unset.
- **Final call:** Optional additive field. No conditional removal of
  `spec_path` (D7 alternative B rejected).

### D11. Push-notify on `skipped_broken_context`
- **Reason it might be wrong:** The user might run `/z-implement-all` on a
  third-party repo without docs/llm/, generating a notify they can't act on.
- **Mitigation accepted:**
  - One notify per `<slug, skip_reason>` per session (de-dup): if the user
    saw "memory review skipped: tags_missing" once on this slug, don't fire
    again for the same combo in the same run.
  - Honor existing `Z_HARNESS_NOTIFY=off` env var.
- **Final call:** Push-notify once per `(slug, skip_reason)` per session.
  Add ENV opt-out via the existing `Z_HARNESS_NOTIFY` rather than a new var.

## Cross-decision interactions (both consultants flagged the same)

- D1 + D11 must coordinate: the once-per-session de-dup guard lives in the
  helper alongside terminal classification.
- D2 is prerequisite for D11: the terminal event is the source of truth for
  whether to notify.
- D5 ↔ D7 are tightly coupled: shipped together.
- D1 enables D5: same helper handles `parent_command: debug` cleanly.

## Shortcuts (none proposed)

No consultant recommended a shortcut. The plan delivers the robust
long-lasting solution everywhere.

## Non-consult decisions stand

D3, D4, D6, D8, D9, D10, D12 — accepted as drafted.
