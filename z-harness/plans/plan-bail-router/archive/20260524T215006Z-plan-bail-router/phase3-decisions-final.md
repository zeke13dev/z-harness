# Phase 3: Final Decisions After Consultation

## Consultant Summary

Gemini agreed with an embedded standalone router rubric and with including `/z-do` plus narrow wrong-tool routes. It disagreed with using a classifier, recommending deterministic main-thread heuristics only, and suggested `/z-audit-plan` should not be a normal bail target because it requires existing plan artifacts. Gemini also preferred an AskUser handoff gate over a pure halt-with-recommendation.

Codex agreed with the overall plan but recommended sentinel-marked embedded blocks to reduce drift, a separate cheap `planning-router` agent rather than extending `complexity-classifier`, and route-chain loop prevention. Codex treated `/z-audit-plan` as a contextual route only when existing plan artifacts are present.

## Pushback Checks

- Gemini's deterministic-only recommendation might be wrong because ambiguous pre-plan prompts are exactly where deterministic signals are least reliable, and the user explicitly raised a cheap Haiku-style classifier as a possible metric.
- Gemini's objection to `/z-audit-plan` as a route target might be wrong if "route target" includes contextual exits after a plan already exists, not only front-door planning commands.
- Gemini's AskUser handoff gate might be wrong because it adds another approval prompt to commands that already try to be lightweight.
- Codex's new `planning-router` agent recommendation might be wrong because adding an agent increases surface area, exports, docs, and maintenance load for a policy that may be expressible as a short rubric.
- Codex's sentinel-marked embedded blocks might be wrong because command Markdown is human-authored, and visible sentinels can make prompts feel generated and noisy.
- Codex's route-chain cap might be wrong if legitimate flows need multiple precontext hops, such as `/z-research` -> `/z-brainstorm` -> `/z-plan`.

## Synthesized Calls

### D1 — Router Shape

Final call: keep the canonical policy in docs/memory and embed compact standalone "Plan Route Check" sections in each command and skill that participates in routing. Add unobtrusive HTML sentinels around the embedded blocks so drift can be detected later without changing rendered Markdown much.

Rationale: exports need standalone prompts; a pure runtime include is not compatible with current command surfaces. Sentinels address Codex's drift concern without requiring a new injection script in v1.

### D2 — Route Targets and Boundaries

Final call: define two route classes.

- Primary route matrix: `/z-do`, `/z-plan-light`, `/z-plan`, `/z-plan-split`, `/z-brainstorm`, `/z-research`.
- Contextual exits: `/z-audit-plan`, `/z-fix`, `/z-debug`, `/z-amend`, `/z-maintain-docs`.

`/z-audit-plan` belongs in the policy only when plan artifacts already exist or the current command just produced plan artifacts and is recommending a validation step. It is not a replacement for `/z-plan`, `/z-plan-light`, `/z-plan-split`, `/z-brainstorm`, or `/z-research`.

### D3 — Complexity Metric and Classifier Role

Final call: hybrid router with deterministic first pass and optional cheap `planning-router` agent for ambiguous cases. Do not extend `complexity-classifier`; that agent classifies post-plan task blocks, while routing has a different input shape and output contract.

Deterministic signals:

- likely edit-file count
- expected task count
- number of non-obvious decisions
- cross-module / API / schema / persistence impact
- terrain uncertainty and need for citations
- approach-space uncertainty and need for ideation
- cluster seam count
- existing artifact state (`BRAINSTORM.md`, `RESEARCH.md`, `SPEC.md`, `PLAN.md`, `TASKS.md`, `FIX.md`)
- whether the user has a diagnosed bug, an unknown symptom, a planning request, or an implementation request

Classifier use:

- Only dispatch `planning-router` when deterministic signals conflict or confidence is `medium`.
- Never dispatch it for obvious tiny tasks, obvious full plans, or commands whose own phase gate already has a cheaper deterministic answer.
- Classifier output is advisory; the orchestrator remains responsible for the final route decision.

### D4 — Bail Semantics and Loop Prevention

Final call: use an AskUser handoff gate that writes a route artifact and logs telemetry before presenting the recommendation. The command does not auto-run the next command. The user-facing options should normally be:

- "Switch to `<recommended command>`" — stop current run after writing context and show exact invocation.
- "Continue here" — allowed only if the command's hard thresholds do not forbid it; log explicit override.
- "Abandon" — end the run cleanly.

Loop prevention:

- Every route artifact records `route_chain`, `from_command`, `to_command`, and `reason_codes`.
- If `route_chain` already has two prior entries, do not route again; ask the user to choose one command explicitly.
- If the recommended target equals the immediate prior `from_command`, do not ping-pong; surface both route notes and ask the user to choose.

### D5 — Telemetry Contract

Final call: add shared `plan_route_decision` telemetry while preserving existing command-specific events. Minimum fields:

- `from_command`
- `to_command`
- `route_class`
- `reason_codes`
- `signals`
- `confidence`
- `classifier_used`
- `artifact_path`
- `route_chain`
- `user_choice`

### D6 — Source, Export, and Docs Propagation

Final call: edit canonical source files first, regenerate exports, and update docs/memory. Include `z-audit-plan` in the command/skill docs indexes as part of this plan because exploration found drift.

## Approved Shortcuts

None yet.

## Remaining Clarification

No scope clarification needed. The only user approval needed is whether to accept the synthesized change from pure halt-with-recommendation to AskUser handoff gate, and whether the new `planning-router` agent is acceptable as the ambiguity resolver.
