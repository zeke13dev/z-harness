MODE: light-fix

Problem: Adding `/z-audit-plan-style` — a peer of `/z-audit-plan` (201 lines) and `/z-mr-review` (869 lines). It audits PLAN artifacts (SPEC.md, PLAN.md, TASKS.md) for code-quality issues BEFORE code is written — flagging defensive bloat, premature abstractions, DRY/KISS/SOLID violations, STYLE.md drift in proposed names/patterns.

## Shape of the decision

Input: plan markdown files (not a unified diff like mr-review takes).
Output: findings feed into `/z-amend`, not `/z-implement-all`.
Findings need: severity (BLOCKER/MAJOR/MINOR like audit-plan uses, NOT the P0-P4 model), category (defensive-bloat, premature-abstraction, dry-kiss-violation, test-noise, hygiene, style-drift — same categories as mr-reviewer's 5), file citations (to SPEC.md/PLAN.md/TASKS.md lines, not diff line numbers), dismissal-signature handling (don't re-raise findings user has previously dismissed), multi-voice consensus (claude + codex + gemini).

The critical difference vs mr-review: mr-reviewer analyzes diffs (unified text format, per-file line ranges, can chunk by file). plan-style-reviewer analyzes narrative plan markdown — no diff hunks, no line numbers per se, findings reference "proposed names" and "task N" rather than code locations.

## Three candidate implementations

**Option A:** Brand-new `plan-style-reviewer` agent (sibling of mr-reviewer).
- Pros: clean separation; input contract is markdown not diff; agent speaks natively about "proposed names", "planned abstractions", "task acceptance criteria"; no code duplication.
- Cons: separate agent means duplicating severity model, output JSON schema, voice dispatch, dismissal handling from mr-reviewer (700+ lines of orchestration logic).

**Option B:** Extend existing `mr-reviewer` agent to accept `mode: plan` (alongside `full`, `per-chunk`, `abstraction-only`).
- Pros: no code duplication; one agent owns the severity/category/voice contract; reuses existing abstraction-symbol-finding and dismissal-filtering logic.
- Cons: cross-cutting changes to a 700+ line agent; "plan mode" is genuinely different (no diff hunks, no line ranges, different kinds of citations); agent grows conditional logic that makes it harder to reason about.

**Option C:** No new agent — orchestrator dispatches `consultant-primary` (Gemini) and `consultant-secondary` (Codex) directly (like /z-audit-plan's Phase 3 does).
- Pros: simplest implementation; reuses generic consultants; no new agent code.
- Cons: gives up multi-voice merge logic; no shared dismissal handling; no structured JSON contract (consultants return text); P0-P4 severity rigor lost.

## Key constraints
- The audit-plan command uses BLOCKER/MAJOR/MINOR severities; plan-style-audit should use the same severity model, NOT adopt mr-review's P0-P4 model.
- Dismissal handling must work: findings should be signature-filtered against prior runs so the user doesn't see the same complaint twice.
- "Promotion to /z-amend" flow should feel natural — output artifact type and location should fit the existing `/z-amend` input conventions.
- Code duplication in orchestration (run setup, voice dispatch, dismissal extraction, JSON merge, telemetry) is expensive to maintain.

Ask: Recommend Option A, B, C, or a hybrid. Reasoning. Tradeoffs around (a) code duplication, (b) future maintenance, (c) signal quality, (d) how naturally "promotion to /z-amend" flows. Anything missed? Be concise — single small fix.

CONTEXT — relevant files:

z-audit-plan.md Phase 3 (lines 118–135): dispatches consultant-primary and consultant-secondary with a generic advisory role, merges findings.

z-mr-review.md Phase 1 (lines 34–174) and Phase 2 (lines 414–525): setup logic (slug, style gate, diff capture, chunking, dismissal extraction, voice dispatch). 700+ lines of this is reusable.

z-mr-review.md Phase 3 (lines 529–771): JSON extraction, dedup, severity aggregation, findings_index, YAML frontmatter — this is the "structured output" backbone.

mr-reviewer.md: 600+ line agent that reads diff, applies five categories (defensive-bloat, test-noise, abstraction, hygiene, style-drift), returns severity (P0-P4) + findings JSON + summary block.
