# Plan shipped — z-fix-hypothesis-driven
**Run:** 20260524T075413Z-review
**Status:** SHIPPED with spec amendment

## Outcome
17/17 tasks completed; per-task review cycles documented in `archive/tasks/T*/SUMMARY.md`.

## Final-review findings handling
- Prong A (implementation): 0 blockers, 2 majors, 3 minors — all accepted as documented edge cases (consultant-failure handling, mr-review fail-silent, INDEX.json depends_on metadata, checkpoint durability, no-very_high-after-5-cycles).
- Prong B (spec): 0 blockers, 3 majors, 4 minors.
  - **3 majors patched into SPEC.md inline:**
    1. Round-2 NEW restatement: dropped → merged into matching pool row via `proposed_by` union + cap-3 (SPEC line ~231)
    2. Likelihood-bucket calibration: 5-bucket descriptive guide added (SPEC ~line 235)
    3. `orthogonal_with_reason` decision rule: added with examples (SPEC ~line 271)
  - 4 minors carried forward; address opportunistically in real usage.

## Not patched (deferred)
- Codex Prong-A majors (consultant-failure handling, mr-review fail-silent) — both flagged as design tradeoffs with reasonable v1 defaults; revisit if patterns emerge in real /z-debug runs.
- Codex Prong-B minors (z-fix Phase 0 modify-no-regate, test_cost calibration, posterior tie-breaking, top-2 outlier definition) — minor refinements suitable for v2 spec pass.

## Recommended next
- `/z-maintain-docs` — refresh docs/llm/ and docs/human/ concepts (commands, agents, z-fix, z-debug, z-improve, z-stats, z-suggest-memory) for any drift from the implementation
