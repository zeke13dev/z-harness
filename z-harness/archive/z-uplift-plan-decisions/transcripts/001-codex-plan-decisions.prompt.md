MODE: plan-decisions

## Decision blocks to evaluate (D1–D4; D5–D8 listed for context)

### D1 — Output layout
- (a) z-harness/plans/<slug>/components/<comp>/{REPORT.md,TASKS.md}
- (b) z-harness/plans/<slug>/ flat with TASKS-<comp>.md
- (c) z-harness/plans/<slug>-<comp>/{REPORT.md,TASKS.md,SPEC.md,PLAN.md} — each component a sibling plan, parent <slug>/MANIFEST is the index

Tentative: (c). /z-implement-all --tasks=<path> derives $BASE from the tasks file's parent dir and reads SPEC/PLAN from $BASE. (a) forces a shared root SPEC/PLAN that doesn't fit per-component scope. (c) keeps each component self-contained, resumable.

### D2 — Component decomposition
- (a) Polyglot detection: Cargo workspace + pyproject + package.json workspaces + top-level-dir fallback with denylist
- (b) Rust-only first cut
- (c) Always top-level dirs minus denylist

Tentative: (a). Haiku subagent or inline python; user confirms.

### D3 — Cross-cutting pass
- (a) New 'uplift-cross-cutting' agent (Sonnet)
- (b) Reuse bundled gemini+codex consultants on a curated source map → CROSS-CUTTING.md (same pattern as /z-review-all Prong B without a SPEC)
- (c) Skip; tag findings cross-component during per-component audits and reconcile after

Tentative: (b). YAGNI on new agent. CROSS-CUTTING.md handed as input context to every per-component auditor.

### D4 — Per-component audit dispatch
- (a) Shell out: /z-audit --target <comp> per component (re-entrant slash)
- (b) Inline replication: dispatch auditor agents per (component × dimension) directly inside /z-uplift outer loop, mirroring /z-audit Phases 2–6
- (c) Extract shared "audit-one-component" subroutine that both /z-audit and /z-uplift call

Tentative: (b). Re-entrant slash collides with run-ids/push-notifications/compaction breakpoints. (c) correct long-term but premature with one second caller.

### D5–D8 (skip-consult)
- D5: inherit /z-audit's >30 / >10 CRIT-HIGH bail; bailed components excluded.
- D6: sequential per-component /z-implement-all with AskUser gates.
- D7: MANIFEST.md is the resume authority.
- D8: name = '/z-uplift'.

## Task

For D1–D4: recommend on each with reasoning, tradeoffs, missed considerations, and decision interactions. For D5–D8: scan for anything obviously wrong.
