MODE: final-review-2pronged

Plan slug: tiered-quality-uplift
Plan goal: Build `/z-uplift` command — decompose repo, cross-cutting pass, per-component audits, sequential implement.

Mandate: Two-pronged review.

**Prong A — Implementation faithfulness.** Does the diff implement SPEC as written?
- Files SPEC said should change but didn't?
- Cross-task drift (MANIFEST schema / event payloads)?
- Phase-skip-guard correctness (SKIP_TO_PHASE)?
- Atomic-write patterns consistent?
- Deferred **Note:** items on T002/T003/T004 — actually safe or hidden landmines?
- Collision fix in export-cursor.py/export-codex.py — sound? Doesn't break existing?

**Prong B — Spec correctness.** Now that code exists, is SPEC correct/sufficient?
- PLAN decisions that materialized wrong?
- Invariants the code can't actually satisfy?
- Missing edge cases?
- Acceptance criteria gaps?

For each finding: Severity (blocker/major/minor), Prong (A/B), Location (file:line or task ID), Evidence (quoted excerpt), One reason this might be wrong, Recommendation.

[Evidence from code — 7 key sections reviewed for Phase 5 two-step handoff, SKIP_TO_PHASE guards, cross-cutting context extraction, MANIFEST schema, resume detection, collision handling, cross-cutting parser, auto-bail, rubric_path injection, telemetry, and export collision fix]
