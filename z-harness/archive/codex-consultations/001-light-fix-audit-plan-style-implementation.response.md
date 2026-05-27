## Codex Consultation: Hybrid Recommendation

**Recommendation:** Implement a **Hybrid approach: Option A agent (new `plan-style-reviewer`) + Option B orchestration extraction**.

**Reasoning:**

Create a new `plan-style-reviewer` agent purpose-built for markdown plan review, but **do not** duplicate the 700 lines of `/z-mr-review` command orchestration logic. Instead, factor the expensive shared review-family machinery out into reusable sections:

- run setup, archive, telemetry
- voice availability and dispatch
- JSON extraction and malformed-voice handling
- dedup and consensus aggregation
- dismissal-signature extraction/filtering
- findings index and YAML frontmatter generation

This keeps both the agent input contract and orchestration clean while avoiding code duplication.

**Tradeoffs / Risks Flagged:**

- **Code duplication:** Pure Option A would duplicate 700 lines; hybrid factors shared mechanics to avoid this.
- **Future maintenance:** Option B (extending mr-reviewer with `mode: plan`) is the wrong pressure point. That agent is deeply diff-shaped: `diff_path`, hunks, added-line symbols, `line_start`, `line_end`, P0-P4. Plan markdown review will keep adding exceptions; the agent becomes harder to reason about.
- **Signal quality:** A markdown-native agent can reason natively about `Task T003`, proposed names, planned abstractions, acceptance criteria, and STYLE.md drift. Generic consultants (Option C) would be noisier and harder to merge with fidelity.
- **Promotion to `/z-amend`:** Emit a canonical `PLAN_STYLE_AUDIT.md` (not `MR-REVIEW.md`). Make each finding an amendment-shaped block with `SPEC.md:line`, `PLAN.md:line`, or `TASKS.md:line` plus suggested amendment text. Then `/z-amend --from z-harness/<slug>/PLAN_STYLE_AUDIT.md` feels natural.

**Additional Considerations Codex Raised:**

1. **Category taxonomy ambiguity:** You listed "same categories as mr-reviewer's 5" but named six categories (defensive-bloat, premature-abstraction, dry-kiss-violation, test-noise, hygiene, style-drift). Clarify: either keep five and make `premature-abstraction` / `dry-kiss-violation` subtypes of `abstraction`, OR explicitly introduce a six-category plan-style taxonomy.

2. **Concrete artifact shape:**
   - New agent: `agents/plan-style-reviewer.md`
   - New command: `commands/z-audit-plan-style.md`
   - Shared schema: `BLOCKER | MAJOR | MINOR` (not P0-P4)
   - Finding fields: `severity`, `category`, `source_file`, `line_start`, `line_end`, `task_id`, `proposed_symbol`, `title`, `detail`, `recommendation`, `voices`
   - Artifact: `z-harness/<slug>/PLAN_STYLE_AUDIT.md`
   - Dismissal signature: `(source_file, category, normalized_title/detail, optional task_id/proposed_symbol)`

3. **Reject pure Option B:** Muddies a good diff reviewer with plan-specific logic.

4. **Reject pure Option C:** Gives up the three things you called critical—structured severity (BLOCKER/MAJOR/MINOR), dismissal handling, and multi-voice consensus.

**Raw Response Excerpt:**

> Recommend **Hybrid: Option A agent, Option B orchestration extraction**. Create a new `plan-style-reviewer` agent, but do **not** duplicate the 700 lines of `/z-mr-review` command logic. Instead, factor the shared review-family mechanics out... Why: Code duplication: A pure Option A duplicates too much. A new agent plus shared orchestration keeps the input model clean while preserving the expensive machinery. Future maintenance: Extending `mr-reviewer` with `mode: plan` is the wrong pressure point. That agent is deeply diff-shaped...
