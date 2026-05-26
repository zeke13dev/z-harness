Mode: bundled-decisions

You are reviewing z-harness planning artifacts for a planned change. Be concise and actionable.

Input artifact (verbatim decisions doc):

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

Repo context and concrete prompt surfaces:

- /z-do already has inline bail thresholds: if >3 files need editing, any non-obvious decision, cross-module/cross-crate impact or schema change, or user says it grew, it halts, writes `z-harness/adhoc/archive/$RUN/escalation.md`, logs `do_escalation`, and suggests /z-plan-light or /z-plan. It also has a mid-implementation AskUser gate with options continue, escalate to /z-plan-light, escalate to /z-plan, abandon.
- /z-plan-light already says it is for small focused changes; bails if >5 candidate files, >2 non-obvious decisions, cross-module/cross-crate impact, or user says bigger. Current bail writes `$Z_HARNESS_PLAN_DIR/escalation.md`, push-notifies, and recommends `/z-plan <task>`. Mid-implementation it offers continue in light mode, switch to /z-plan, spawn implementer subagent.
- /z-plan is the rigorous pipeline producing SPEC/PLAN/TASKS. It already recommends /z-audit-plan, /z-test, and /z-implement-all after completion. It dispatches `complexity-classifier` only after TASKS.md exists, once per task, to stamp low/medium/high for implementer model selection.
- /z-plan-split is a pre-emptive scope splitter for topics likely to create sprawling >=40-task plans. It refuses fewer than 2 cluster seams with recommendation to run /z-plan directly, refuses more than 6 seams by asking user to narrow/coarsen, and emits structured early-exit telemetry.
- /z-research maps terrain only, with cost gate, doc-fetcher then Explore, research-review consult, and final next-step recommendations: /z-brainstorm or /z-plan. It explicitly must not recommend an approach.
- /z-brainstorm is cheap pre-plan ideation, writes BRAINSTORM.md, then recommends /z-research or /z-plan. It is precontext, not a plan producer.
- /z-audit-plan audits an existing SPEC/PLAN/TASKS tree. It is read-only and currently asks the user after PLAN_AUDIT_REPORT.md: Amend Plan (Run z-amend), Proceed as-is, or Reject & Re-plan.
- Existing complexity-classifier is task-level and post-plan: it receives one TASKS.md task block, optionally reads SPEC.md, returns `STATUS: classified`, `TASK`, `TIER`, `REASON`, and is used to pick implementer model. It is not currently designed to classify a user request into a planning route.

Constraints:
- Current command/skill/export surfaces are standalone Markdown prompts; there is no runtime include mechanism.
- This planning run needs artifacts only, not code.
- Preserve standalone exports for Cursor/Codex/Antigravity.
- Prefer deterministic, auditable rubric text; use subagents only where they add value.
- Avoid introducing routing loops between commands; telemetry should make route decisions analyzable.
- Keep DRY/KISS/SOLID in spirit, but do not make exported prompts dependent on missing includes.

Ask:
Critique D1-D4. For each, say whether you agree, what could go wrong, and any concrete changes the plan should make. Specifically address:
- whether classifier should be a new planning-router agent vs extension of complexity-classifier vs main-thread heuristic;
- whether halt-with-recommendation is too conservative;
- whether /z-audit-plan belongs in the route matrix.

Return a concise actionable review. For each consult-flagged decision, recommend with reasoning, tradeoffs, missed considerations, and decision interactions.
