Mode: plan-review

Input artifact (verbatim from caller)

SPEC.md:

# Spec: Plan Bail Router

## Overview

Add a shared routing policy for the z-harness planning family so each entry point can detect when a different workflow is a better fit, write a route artifact, log structured telemetry, and present a user-gated handoff. The change is planning-only: no command should automatically execute another command in v1.

## Planning Inputs

none - fresh /z-plan run.

## Definitions

Primary matrix: /z-do, /z-plan-light, /z-plan, /z-plan-split, /z-brainstorm, /z-research.
Contextual exits: /z-audit-plan, /z-fix, /z-debug, /z-amend, /z-maintain-docs.

Route contract: write route artifact, emit plan_route_decision, present AskUser handoff unless terminal hard-refusal branch, stop current workflow if switch, preserve existing telemetry.
Route artifact: route-decision.md under active run archive with recommendation, reason, signals, route chain, resume context.
Telemetry fields: from_command, to_command, route_class, reason_codes, signals, confidence, classifier_used, artifact_path, route_chain, user_choice.
Signals: candidate_files, expected_tasks, non_obvious_decisions, cluster_seams, cross_module, schema_or_persistence, public_api_or_wire_format, terrain_uncertain, approach_uncertain, has_bug_diagnosis, has_unknown_bug_symptom, has_existing_plan, has_fix_artifact, docs_stale_or_drifted.
Thresholds map tiny to /z-do, small fixes to /z-plan-light, medium to /z-plan, large/seamed to /z-plan-split, unknown terrain to /z-research, approach uncertainty to /z-brainstorm, existing plan audit to /z-audit-plan, existing plan changes to /z-amend, diagnosed bug to /z-fix, unknown bug to /z-debug, docs staleness to /z-maintain-docs.
Loop prevention: max 2 prior route entries, no immediate ping-pong, user continue suppresses same reason_codes in same run.
AskUser options: switch, continue if allowed, abandon.
Add agents/planning-router.md with haiku/read-only parseable return: STATUS, RECOMMENDED, ROUTE_CLASS, CONFIDENCE, REASON_CODES, REASON.
Add sentineled Plan Route Check blocks to commands and skills for z-do, z-plan-light, z-plan, z-plan-split, z-brainstorm, z-research, z-audit-plan.
Update docs/human and docs/llm command/skill/agent docs. Regenerate exports.

PLAN.md:

Goal: Make z-harness planning-family entry points mutually route-aware.
Non-goals: no automatic execution, no replacing safety gates, no making z-audit-plan front-door, no generated include system, no production code during planning.
Decisions: canonical docs/memory + embedded route blocks with sentinels; primary vs contextual route classes; deterministic first + new planning-router for ambiguity; AskUser handoff; plan_route_decision telemetry; canonical sources then exports.
Implementation phases: 1 add planning-router agent and docs; 2 command route blocks; 3 skill route blocks; 4 docs/memory route updates and z-audit-plan drift; 5 regenerate exports; 6 validation via json.tool, export scripts, sentinel search.
Acceptance: route blocks in all primary commands and skills; planning-router exists; telemetry specified; z-audit-plan contextual only; docs/memory include z-audit-plan and planning-router; exports regenerate.

Context from current repo (selected)

- Existing entry points already have command-specific bail/escalation rules. /z-do bails >3 files or any non-obvious decision to /z-plan-light, and cross-module/schema to /z-plan; writes z-harness/adhoc/archive/$RUN/escalation.md and logs do_escalation. /z-plan-light bails >5 candidate files, >2 non-obvious decisions, or cross-module/public API/wire/schema to /z-plan; writes escalation.md. /z-plan already has docs freshness routing to /z-maintain-docs and pre-plan BRAINSTORM.md/RESEARCH.md continuation logic. /z-audit-plan discovers an existing plan slug and is read-only, so it is contextual rather than a fresh-task front door.
- Archive path conventions differ: /z-do uses z-harness/adhoc/archive/$RUN; plan-family commands use $Z_HARNESS_PLAN_DIR/archive/$RUN; /z-audit-plan uses $BASE/archive/$RUN.
- Export system is script-based: /z-export runs python3 scripts/export-cursor.py, export-codex.py, export-agy.py sequentially; canonical source is commands/, agents/, skills/ and generated outputs live under exports/.
- docs/llm/commands.json source_file excerpt includes many commands but not commands/z-audit-plan.md, even though commands/z-audit-plan.md exists. The plan mentions docs/memory and z-audit-plan drift but acceptance is broad.
- Consultant conventions expect parseable, mode-specific prompt/response wrappers. Existing agent frontmatter uses tools/model fields; new planning-router must fit those conventions.

Constraints / evaluation lens

This is a prompt/workflow repository. Fragility likely comes from ambiguous command instructions, duplicate thresholds, telemetry schemas that are not parseable, inconsistent archive paths, route loops, and generated exports drifting from canonical sources. Keep scope to planning-family commands/skills/exports/docs unless contextual commands truly need entry-point changes. Preserve existing telemetry consumers like z-improve/z-stats.

Ask

Critique this plan: what's wrong, missing, or fragile? Focus on spec gaps, implementation drift risks, missing acceptance criteria, and over/under-scoping. Be concise with actionable findings. Do not rewrite the plan; identify concrete fixes to make before implementation.

