MODE: plan-review

SPEC and PLAN review for postmortem-memory-nudge feature.

Key changes proposed:
- run-memory-review.sh: emit memory_review_terminal events with 4-state taxonomy
- review-agent.md: add optional debug_md_path and parent_command:debug support
- z-implement-all/z-review-all Phase 9: emit memory_review_terminal on ran_empty/needs_user
- z-debug Phase 9b: new phase gated on DEBUG.md status:shipped
- z-stats Phase 4b: read memory_review_terminal events with backward-compat support

Task: Critique for wire-format mistakes, missing edge cases, integration risks, breaking changes.
