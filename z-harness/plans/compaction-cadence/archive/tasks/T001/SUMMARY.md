# T001 — done

Removed Z_HARNESS_PAUSE_AT_PCT + usage_pause from:
- commands/z-implement-all.md, skills/z-implement-all/SKILL.md, README.md (original scope)
- commands/z-plan.md, skills/z-plan/SKILL.md (scope extension after reviewer)
- commands/z-plan-split.md, skills/z-plan-split/SKILL.md (scope extension after reviewer)

Renumbered downstream setup steps; removed `usage_paused` from z-plan-split early-exit telemetry.

Reviewer: 0 blockers, 3 majors (only finding 1 actioned — sweep /z-plan*; findings 2 (exports) deferred to T009; finding 3 (worktree snapshots) ignored as ephemeral).

Grep verification: `Z_HARNESS_PAUSE_AT_PCT|usage_pause` returns zero hits across commands/ skills/ README.md.
