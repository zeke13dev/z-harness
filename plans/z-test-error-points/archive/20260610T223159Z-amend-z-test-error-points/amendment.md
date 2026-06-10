# Amendment: Fix pattern_signature computation, add validation, clean schema

**Run:** 20260610T223159Z-amend-z-test-error-points
**Mode:** full
**Requested change:** Apply 4 review findings from /z-review-all:
- T-REV-001 [blocker] — Recompute 3 pattern_signatures in ERROR_POINTS.json
- T-REV-002 [blocker] — Align Phase 5.5 signature computation documentation
- T-REV-005 [major] — Add --check-signatures to validate-error-points.py
- T-REV-006 [minor] — Remove staleness_score from error_points.schema.json

## What this affects

### SPEC.md
- No section changes needed — the existing SPEC already defines the correct algorithm. The fix is in the data (ERROR_POINTS.json).

### PLAN.md
- No decision changes. All four amendments are corrective, not re-design.

### TASKS.md
- **New tasks:** None. The edits are to files outside the TASKS.md scope (ERROR_POINTS.json is T003, but the fix is corrective; Phase 5.5 documentation is T004; validator extension is T002; schema cleanup is T001).
- **Modified tasks:** None — the acceptance criteria in TASKS.md already require valid signatures.
- **Removed tasks:** None.

### FIX.md
- N/A (full mode)

## Risk
- Schema change (removing staleness_score): minimal — the field was never stored, only documented.
- No cross-module impact, no new deps, no API change.
- **Consult trigger:** None that warrant cross-LLM dispatch. The changes are data-corrective, not design-changing.
