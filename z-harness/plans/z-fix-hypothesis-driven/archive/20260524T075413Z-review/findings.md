# Final review — z-fix-hypothesis-driven
Run: 20260524T075413Z-review
Base ref: 338e138 (last commit before this plan)
Diff stats: 16 files, ~1604 additions, ~287 deletions

## Prong A — Implementation drift

### blocker
(none)

### major
- **[codex] Consultant-failure handling in Phase 3a unspecified.** If only 1 of 2 consultants returns in R1 (or R2), the prior bucket math (`3→high, 2→med, 1→low`) silently degrades. No documented fallback/halt/retry path. **One reason it might be wrong:** the failure path is arguably covered by the per-call subagent retry; if both fail the orchestrator naturally halts. Still worth a SPEC note.
- **[codex] /z-debug Phase 9 mr-review fail-silent.** Spec says "log a note and continue" on /z-mr-review failure. If the fix introduced a real P0 finding and mr-review crashed, the post-mortem misses it. **One reason it might be wrong:** /z-mr-review failures are rare and visible in logs; the design trade-off was correctly chosen for v1. Still worth flagging.

### minor
- **[gemini] z-fix `depends_on` imprecision in docs/llm/INDEX.json.** SPEC asks `["agents","scripts","z-plan-light"]`; implementation has `["agents","commands"]`. Metadata-only.
- **[codex] Phase 3a checkpoint durability not specified.** No explicit fsync requirement for the round1-orchestrator.md checkpoint; in practice fine for a single-process orchestrator.
- **[codex] Posterior table doesn't define "what if no very_high after 5 cycles."** Cycle cap is documented but the "best posterior is high" exit case isn't.

## Prong B — Spec gaps

### blocker
(none)

### major
- **[codex] Round 2 "no restatement" creates a small perverse incentive.** If a consultant independently arrives at a hypothesis already in the pool, the current filter drops it. Spec could be clarified: NEW row restatements should bump `overlap_count` via `proposed_by` union (the same set-cap-3 logic from T006-v2 fix), not be dropped. The CRITIQUES table's "no agreement" rule still applies.
- **[codex] Likelihood-bucket assignment lacks calibration guidance.** The orchestrator-only likelihood rule (D3/D4) is sound for contamination, but the strongly_supported vs weakly_supported vs inconclusive boundary is wholly subjective. Spec should add concrete examples ("error rate dropped 50%→0.1% with 1000 samples = strongly_supported").
- **[codex] ORTHOGONAL_WITH_REASON vs UNEXPLAINED has no decision rule.** Fix-gate requires zero `unexplained`, but users can effectively unlock the gate by marking confusing evidence as ORTHOGONAL. Spec should add: "Mark ORTHOGONAL only if the root cause would hold even if that evidence didn't exist."

### minor
- **[codex] /z-fix Phase 0 "modify hypothesis" doesn't re-check auto-bail.** A user can iterate from "cache bug" to "5-service distributed cache bug" and the gate doesn't re-evaluate cross-module thresholds. Add auto-bail re-check after each modify cycle.
- **[codex] test_cost buckets lack calibration examples** (free|cheap|medium|expensive — what's the cutoff?). Doesn't affect correctness; affects consistency.
- **[codex] Posterior tie-breaking unspecified.** Two hypotheses with identical posteriors after a cycle — spec doesn't say test-in-parallel vs serial vs user-pick.
- **[codex] Outlier carve-out "top 2" with overlap=1 — what defines "top"?** Likely lowest test_cost, but not specified.

## Consensus vs disagreement
- **Items both LLMs flagged:** essentially none. Gemini saw only the minor INDEX.json metadata issue; Codex saw 4 major spec gaps + several minors. This is informative: the implementation is faithful (per Gemini's thorough invariant-by-invariant check); the spec has documented edges (per Codex's adversarial probing).
- **Implementation invariants verified by Gemini:** DEBUG.md sections in order; posterior table verbatim; Phase-visibility matrix correct; Round-2 schemas mirror-equivalent across codex/gemini consultants AND commands/z-debug.md Phase 3b dispatch prompt; commands/z-debug.md body == skills/z-debug/SKILL.md body; fix-gate has both preconditions; H<NNN>/EVID-NNN consistent; /z-fix correctly omits round-1/round-2 modes; /z-fix Phase 0 non-skippable.

## Recommendation
The implementation is faithful to SPEC. The spec gaps Codex surfaced are real but not blockers — they're refinements that would benefit a v2 SPEC pass. Recommend: ship as-is with a spec-amend follow-up to address the 3 Prong-B majors (Round 2 restatement rule, likelihood calibration, ORTHOGONAL_WITH_REASON rule).
