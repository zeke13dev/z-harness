MODE: light-fix

Decision: implementing `/z-audit-plan-style` — a code-quality pre-implementation audit of a PLAN's proposed names, abstractions, and patterns (vs style/design rigor), not yet written code.

Context: this is a peer of two existing commands:
- `/z-audit-plan`: 4-phase PRE-IMPLEMENTATION audit (reality check, best practices, cross-LLM adversarial, merge); reads SPEC/PLAN/TASKS; outputs PLAN_AUDIT_REPORT.md (BLOCKER/MAJOR/MINOR).
- `/z-mr-review`: MR-quality review on git DIFF; hard gate on STYLE.md; dispatches the `mr-reviewer` agent (700 line agent with multi-voice dispatch, dismissal handling, P0-P4 severities, 5 categories); outputs MR-REVIEW.md with task blocks; includes voice degradation handling.

User wants: `/z-audit-plan-style` = (audit-plan shape) × (mr-review's code-quality rigor). Audit the PLAN markdown for proposed defensive bloat, premature abstractions, DRY/KISS/SOLID violations, STYLE.md drift in proposed names/patterns — *before code is written*. Output feeds `/z-amend` (not `/z-implement-all`).

Three candidate approaches:

**Option A: Brand-new `plan-style-reviewer` agent** (sibling of `mr-reviewer`)
- Pros: clean separation; input contract is plan markdown not unified diff; agent prompt can speak natively about "proposed names", "planned abstractions", "task acceptance criteria"; same category/severity schema as mr-review.
- Cons: code duplication with mr-reviewer (severity model, output JSON schema, voice dispatch, dismissal handling, Jaccard match logic, consensus tier-bump).

**Option B: Reuse `mr-reviewer` with `mode: plan`** (alongside `full`, `per-chunk`, `abstraction-only`)
- Pros: no code duplication; single agent owns severity/category/voice contract; extends existing, proven agent.
- Cons: 700+ line agent grows cross-cutting "plan" conditional logic throughout; `plan_artifacts_path` vs `diff_path` is fundamentally different (plan markdown vs patch; no line numbers in same sense; symbols appear in acceptance criteria, not just definitions); Grep-based abstraction finding changes shape entirely.

**Option C: Orchestrator dispatches consultants directly** (Gemini + Codex) like `/z-audit-plan` does for phase 3
- Pros: simplest; reuses generic consultants (no new agent).
- Cons: loses multi-voice merge logic, dismissal handling, P0-P4 severity rigor, structured JSON contract, consensus tier-bump, Jaccard signature matching — all the things that make mr-review powerful. Reduces `/z-audit-plan-style` to "best-effort LLM advice" rather than structured findings you can amend.

Key question: how much of mr-reviewer's machinery (voice dispatch, dismissal matching, consensus bumps, JSON schema) is *essential* for plan-style findings to be actionable in `/z-amend` flow?

My read: plan-style findings will be pulled into `/z-amend` task blocks just like MR-REVIEW findings are pulled into `/z-implement-all`. That means dismissal handling and severity rigor matter just as much. If findings are too noisy (no consensus bumping, no prior-dismissal tracking), users will ignore them, and the command becomes advisory theater.

Trade-off summary to help you decide:
- **Signal quality**: B ≈ A > C. B gets full mr-reviewer machinery; A is cleaner but duplicative; C is weakest.
- **Code duplication**: B > A > C. B avoids it; A owns its complexity; C owns nothing.
- **Future maintenance**: B > A > C. B: one agent to patch; A: two agents to patch in sync; C: consultants are generic, little to patch.
- **"Promotion to /z-amend" flow**: B ≈ A >> C. B/A have structured JSON; C is advisory text that user must manually abstract.
- **Readability of agent code**: A > B > C. A is focused; B is bloated with conditionals; C is shallow.

What's missing from this frame? Does dismissal handling actually matter for a pre-implementation audit (vs post-code review)? Would users even *want* to dismiss plan-style findings the way they do MR findings?

Recommend: **Option B**, with a specific caveat. Reuse `mr-reviewer`; treat `mode: plan` as first-class. Yes, it grows conditional logic, but:
1. The dismissal + consensus tier-bump + Jaccard logic is *proven* and *hard to replicate correctly*.
2. Plan-style findings *will* feed `/z-amend` task blocks, so severity/rigor matters.
3. You can isolate the `mode: plan` branching to a `_read_plan_artifacts()` helper + a `_find_in_plan_text()` Grep equivalent, keeping the rest unified.
4. The agent's multi-voice dispatch is agnostic to diff vs. plan — consultants receive the same `active_categories` list; only the evidence form changes.

If you find the agent bloating unmanageably (>1000 lines), split later: extract a shared `findings-merger` sub-agent that both `mr-reviewer` and `plan-style-reviewer` call for dedup/consensus/dismissal, leaving the subject-specific review logic separate. That's a cleaner refactor than trying to inherit a 700-line agent.

Tradeoff to flag: B means plan-style findings will be *more* severe/structured than `/z-audit-plan`'s narrative report. Is that good (consistency with `/z-mr-review` flow) or bad (user gets surprised by a different signal contract within the audit family)?
