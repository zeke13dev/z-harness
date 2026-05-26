Mode: plan-review

Input artifact (verbatim from caller):

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

Context from repository:

- Commands and skills are markdown workflow files with YAML frontmatter. Example /z-plan setup already derives slug/RUN, creates `$Z_HARNESS_PLAN_DIR/archive/$RUN/transcripts`, logs run_start, checks docs freshness, detects BRAINSTORM/RESEARCH, then proceeds through phases. Route checks inserted before setup may not yet have RUN/archive path; inserted after setup may conflict with existing docs-staleness gate.
- /z-plan-light already has local auto-bail thresholds (>5 files, >2 non-obvious decisions, cross-module/schema impact) and writes `escalation.md`; /z-do similarly bails to /z-plan-light or /z-plan and writes `z-harness/adhoc/archive/$RUN/escalation.md`. The proposed route router must either replace or coordinate with these existing local bail mechanisms to avoid duplicate/conflicting behavior.
- /z-audit-plan is read-only and discovers an existing plan slug, then audits SPEC/PLAN/TASKS. It is not a front-door planner; the plan wants it contextual-only.
- Existing consultant agent docs require mode-prefixed prompts and archived transcripts; new `planning-router.md` is planned as haiku/read-only parseable return with fields STATUS, RECOMMENDED, ROUTE_CLASS, CONFIDENCE, REASON_CODES, REASON.
- docs/llm/INDEX.json currently lists command source files and agent source files, but depending on current branch state may not yet include z-audit-plan and planning-router. Export scripts are per-target: `scripts/export-agy.py`, `scripts/export-codex.py`, `scripts/export-cursor.py`, `scripts/export-common.py`.

Constraints:

- This repo primarily implements workflows as markdown command/skill/agent specs; acceptance criteria need to be checkable via text/search, JSON validation, and export regeneration.
- Preserve existing telemetry; do not introduce automatic command execution in v1.
- Keep DRY/KISS: the plan explicitly rejected a generated include system, so embedded route blocks must remain consistent across many command and skill files.
- Avoid over-broad front-door routing that turns every command into a planner before it has enough task/run context.

Ask:

Critique this plan: what is wrong, missing, or fragile? Focus on spec gaps, implementation drift risks, missing acceptance criteria, and over/under-scoping. Be concise with actionable findings. Do not rewrite the plan; list concrete issues and fixes.
