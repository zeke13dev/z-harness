# Decisions: plan-bail-router

## D1 — Router Shape

**Decision:** How should the plan-family routing policy be represented?

**Options:**
- Shared deterministic rubric embedded in every relevant command/skill: self-contained after export, but some repeated text.
- New single source file only: DRYer, but current command/export surfaces have no include mechanism, so commands would not be standalone.
- New slash command that users run before every plan variant: explicit, but adds friction and does not make variants able to bail from inside their own flows.

**Tentative call:** Define a canonical "Plan Route Check" rubric in the source docs/memory layer, then embed a compact self-contained version in each relevant command and skill. Treat the embedded block as generated-by-policy, not a runtime include.

**Consult?** yes

**Trigger:** Affects more than one module and changes command behavior across exported public surfaces.

## D2 — Route Targets and Boundaries

**Decision:** Which commands participate in the bail matrix, and where should they route?

**Options:**
- Planning-only set: `/z-plan-light`, `/z-plan`, `/z-plan-split`, `/z-brainstorm`, `/z-research`, `/z-audit-plan`.
- Include tiny and adjacent gates too: add `/z-do`, and allow references to `/z-fix`, `/z-debug`, `/z-amend`, `/z-maintain-docs` when the wrong-tool signal is clear.
- Fully general command router: include every z-harness command.

**Tentative call:** Include the plan-family plus `/z-do` as the tiny on-ramp. Allow narrow off-family recommendations only for clear wrong-tool cases: diagnosed bug to `/z-fix`, unknown bug to `/z-debug`, stale docs to `/z-maintain-docs`, existing plan changes to `/z-amend`.

**Consult?** yes

**Trigger:** Defines public command boundaries and affects cross-command behavior.

## D3 — Complexity Metric and Classifier Role

**Decision:** Should routing use only deterministic thresholds or ask a cheap classifier subagent?

**Options:**
- Deterministic only: predictable and cheap, but brittle for ambiguous tasks.
- Classifier always: more flexible, but slower and may make simple commands feel heavy.
- Hybrid: deterministic fast path with classifier only for an uncertain band.

**Tentative call:** Hybrid. Use deterministic signals first: likely edit-file count, expected task count, number of non-obvious decisions, cluster seam count, terrain uncertainty, existing artifact state, cross-module/API/schema impact, and whether the work is implementation vs precontext vs plan audit. Dispatch a cheap routing/classifier subagent only when these signals conflict or land in an ambiguous band.

**Consult?** yes

**Trigger:** Algorithm/policy choice with materially different cost and reliability tradeoffs.

## D4 — Bail Semantics and Loop Prevention

**Decision:** What does "bail to another variant" mean operationally?

**Options:**
- Automatic handoff: the current command starts the target command flow.
- Halt with a recommendation and context artifact: safer but requires user re-invocation.
- Ask-user handoff gate: current command writes context, asks whether to continue in the recommended variant, then stops or resumes based on user choice.

**Tentative call:** Halt with a recommendation and context artifact for now. Each bail writes an escalation/route note under the current run, logs a structured route event, and recommends the exact next command. Do not auto-run another command because artifact shapes, setup phases, and approval gates differ.

**Consult?** yes

**Trigger:** Cross-command state and reversibility; a wrong choice can create looped runs or mismatched artifacts.

## D5 — Telemetry Contract

**Decision:** What event should route decisions emit?

**Options:**
- Keep existing command-specific events only (`do_escalation`, light escalation notes, split abort statuses).
- Add one shared event name used by every participant.
- Add a shared event plus keep existing command-specific terminal events.

**Tentative call:** Add `plan_route_decision` with fields like `from_command`, `to_command`, `reason`, `signals`, `confidence`, `classifier_used`, `artifact_path`, and `prior_route`. Preserve existing command-specific run-end/status events for backward compatibility.

**Consult?** no

**Trigger:** Mostly mechanical once D4 is decided; follows existing logging patterns.

## D6 — Source, Export, and Docs Propagation

**Decision:** Which files should implementation touch directly?

**Options:**
- Edit canonical command and skill sources only, then run export scripts and docs maintenance.
- Hand-edit source and generated export files together.
- Add a new script to inject the router block everywhere.

**Tentative call:** Edit canonical `commands/` and `skills/` sources, update docs/memory indexes for `z-audit-plan` drift and router semantics, then regenerate exports via `/z-export` or export scripts. Do not add a block-injection script in this plan; it is a separate refactor if repetition becomes painful.

**Consult?** no

**Trigger:** Existing export pipeline already provides the propagation mechanism; no new abstraction needed for v1.

## Consult Bundle

Consult-flagged decisions: D1, D2, D3, D4.

Open items for consultants:

- Whether the hybrid classifier should be a new `planning-router` agent, an extension of `complexity-classifier`, or a documented main-thread heuristic with optional consultant fallback.
- Whether halt-with-recommendation is too conservative for user experience.
- Whether `/z-audit-plan` belongs in the mutual routing matrix or should remain strictly post-plan.
