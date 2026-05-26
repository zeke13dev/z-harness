Mode: bundled-decisions / z-plan decision consult

Repo: /Users/zeke/dev/z-harness
Plan slug / run id: plan-bail-router

Input artifact (approved decisions doc):

# Decisions: plan-bail-router

## D1 — Router Shape
Decision: How should the plan-family routing policy be represented?
Options:
- Shared deterministic rubric embedded in every relevant command/skill: self-contained after export, but some repeated text.
- New single source file only: DRYer, but current command/export surfaces have no include mechanism, so commands would not be standalone.
- New slash command that users run before every plan variant: explicit, but adds friction and does not make variants able to bail from inside their own flows.
Tentative call: Define a canonical "Plan Route Check" rubric in the source docs/memory layer, then embed a compact self-contained version in each relevant command and skill. Treat the embedded block as generated-by-policy, not a runtime include.
Consult: yes

## D2 — Route Targets and Boundaries
Decision: Which commands participate in the bail matrix, and where should they route?
Options:
- Planning-only set: /z-plan-light, /z-plan, /z-plan-split, /z-brainstorm, /z-research, /z-audit-plan.
- Include tiny and adjacent gates too: add /z-do, and allow references to /z-fix, /z-debug, /z-amend, /z-maintain-docs when the wrong-tool signal is clear.
- Fully general command router: include every z-harness command.
Tentative call: Include the plan-family plus /z-do as the tiny on-ramp. Allow narrow off-family recommendations only for clear wrong-tool cases: diagnosed bug to /z-fix, unknown bug to /z-debug, stale docs to /z-maintain-docs, existing plan changes to /z-amend.
Consult: yes

## D3 — Complexity Metric and Classifier Role
Decision: Should routing use only deterministic thresholds or ask a cheap classifier subagent?
Options:
- Deterministic only: predictable and cheap, but brittle for ambiguous tasks.
- Classifier always: more flexible, but slower and may make simple commands feel heavy.
- Hybrid: deterministic fast path with classifier only for an uncertain band.
Tentative call: Hybrid. Use deterministic signals first: likely edit-file count, expected task count, number of non-obvious decisions, cluster seam count, terrain uncertainty, existing artifact state, cross-module/API/schema impact, and whether the work is implementation vs precontext vs plan audit. Dispatch a cheap routing/classifier subagent only when these signals conflict or land in an ambiguous band.
Consult: yes

## D4 — Bail Semantics and Loop Prevention
Decision: What does "bail to another variant" mean operationally?
Options:
- Automatic handoff: the current command starts the target command flow.
- Halt with a recommendation and context artifact: safer but requires user re-invocation.
- Ask-user handoff gate: current command writes context, asks whether to continue in the recommended variant, then stops or resumes based on user choice.
Tentative call: Halt with a recommendation and context artifact for now. Each bail writes an escalation/route note under the current run, logs a structured route event, and recommends the exact next command. Do not auto-run another command because artifact shapes, setup phases, and approval gates differ.
Consult: yes

D5: add plan_route_decision telemetry; D6: edit canonical command/skill sources and docs, then regenerate exports.

Existing context / prompt excerpts:

1. /z-do already has inline auto-bail thresholds:
- If >3 files need editing -> recommend /z-plan-light
- Any non-obvious decision -> recommend /z-plan-light
- Cross-module/cross-crate/schema -> recommend /z-plan
- Halt: write z-harness/adhoc/archive/$RUN/escalation.md, log do_escalation, push-notify, suggest command.

2. /z-plan-light already has inline auto-bail thresholds:
- >5 candidate files, >2 non-obvious decisions, cross-module/cross-crate/public API/wire/schema, or user says bigger -> STOP.
- Writes $Z_HARNESS_PLAN_DIR/escalation.md, push-notify, recommend /z-plan.
- Mid-implementation escape hatch asks whether to continue in light mode, switch to /z-plan, spawn implementer, or abandon; hard limit >7 files.

3. /z-plan is the full rigorous planner:
- Produces SPEC.md / PLAN.md / TASKS.md only; implementation later.
- Does doc staleness gate and precontext detection for BRAINSTORM.md / RESEARCH.md.
- Runs decisions doc, user gate, bundled cross-LLM consult, final review, TASKS.md with complexity-classifier stamps.

4. /z-plan-split is preemptive scope splitter:
- For sprawling topics that would otherwise produce >=40 task /z-plan run.
- Proposes 2-6 clusters only; below 2 refuses and recommends /z-plan directly; above 6 refuses and asks to narrow.
- Produces MANIFEST.md and SHARED-CONCERNS.md, no production code.

5. /z-brainstorm and /z-research are precontext-only:
- /z-brainstorm emits BRAINSTORM.md, recommends /z-research or /z-plan next; cheap ideation, no SPEC/PLAN/TASKS.
- /z-research emits RESEARCH.md, explicitly no recommendation; recommends /z-brainstorm or /z-plan next; has a user cost gate.

6. /z-audit-plan is read-only plan artifact audit:
- Discovers existing plan slug, audits SPEC.md / PLAN.md / TASKS.md.
- Emits PLAN_AUDIT_REPORT.md.
- Phase 5 asks user: Amend Plan (Run z-amend), Proceed as-is, or Reject & Re-plan.
- It is not a generator of a new plan; it routes based on findings after auditing an existing plan.

7. Adjacent wrong-tool commands:
- /z-fix: for known-diagnosis bugs; non-skippable gate recommends /z-debug when root cause unknown; bails to /z-plan on broad scope.
- /z-debug: for unknown-root-cause bugs; non-skippable gate recommends /z-fix when user has concrete hypothesis; bails to /z-plan for architectural/public-surface/cross-module fix.
- /z-amend: modifies existing SPEC/PLAN/TASKS or FIX.md; if no plan exists suggests /z-plan or /z-plan-light; if amendment grows past ~30% of plan, stops and recommends /z-plan from scratch.

8. Existing complexity-classifier agent:
- Reads one TASKS.md task block plus optional SPEC slice and returns TIER: low|medium|high for implementer model selection.
- It is task-level and used after TASKS.md exists, not before planning variant selection.
- Heuristics: low for mechanical one-file small edits; medium default; high for concurrency/migrations/money/state-machine/etc or >3 files, >5 acceptance criteria, invariant-heavy tests.

Constraints:
- Current command/skill prompts are standalone Markdown surfaces exported to Cursor, Codex, and Antigravity; no runtime include mechanism.
- Need planning artifacts only, not code.
- Preserve command self-containment after export.
- Avoid making light/tiny commands feel heavy.
- DRY/KISS/SOLID: prefer a canonical policy source plus generated embedded snippets if that is less fragile than runtime indirection.
- Need loop prevention and telemetry. Proposed telemetry event: plan_route_decision.

Ask:
Critique D1-D4. For each, say whether you agree, what could go wrong, and concrete changes the plan should make. Specifically address:
- whether classifier should be a new planning-router agent vs extension of complexity-classifier vs main-thread heuristic;
- whether halt-with-recommendation is too conservative;
- whether /z-audit-plan belongs in the route matrix.
Be concise and actionable. For each consult-flagged decision, recommend with reasoning, tradeoffs, missed considerations, and decision interactions.
