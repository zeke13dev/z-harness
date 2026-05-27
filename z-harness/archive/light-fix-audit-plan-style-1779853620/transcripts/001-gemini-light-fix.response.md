Option B is the strongest path. Here is my analysis of the tradeoffs you flagged:

**1. Does dismissal handling matter for a plan audit?**
Yes, and it is arguably *more* critical here. If a user justifies and dismisses a planned abstraction or intentional "defensive bloat" (e.g., for legacy bridging) during the planning phase, that dismissal signature needs to persist. They shouldn't have to fight the exact same finding again downstream during `/z-mr-review` after the code is written. Dismissal handling bridges the intent across phases.

**2. Is the increased severity/rigor vs. `/z-audit-plan` good or bad?**
It is a strictly good thing. Consistency with the `/z-amend` and `/z-mr-review` ingestion contract is far more valuable than narrative consistency with the rest of the "audit" family. Since these findings are meant to feed directly into `/z-amend` task blocks, they *must* be structured, actionable, and squishable. A narrative report would just be advisory theater.

**Proposed Implementation Strategy (Option B):**
*   **`mr-reviewer.md`**: Add `mode: plan`. The agent will accept a combined markdown artifact file via `diff_path`. The `Step 3` Abstraction Sub-Pass will be updated to extract proposed symbols from markdown code blocks or inline backticks instead of diff headers. The core severity logic, multi-voice dispatch, and dismissal handling will remain completely unified.
*   **`z-audit-plan-style.md`**: Create the command orchestration. It will concatenate `SPEC.md`, `PLAN.md`, and `TASKS.md` into a single `plan_artifacts.md` file, invoke `mr-reviewer` with `mode: plan`, and output a `PLAN-STYLE-REVIEW.md` file (using the exact same P0-P4 task block format as `MR-REVIEW.md`) which can be seamlessly fed into `/z-amend`.

Does this approach and rationale align with your vision? Once you confirm, I will draft the formal implementation plan.
