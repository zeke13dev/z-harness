CRITIQUE MODE — plan-review for /z-brainstorm + /z-research

## SPEC.md + PLAN.md context

This is the z-harness slash-command framework. Two new commands (/z-brainstorm, /z-research) produce seed artifacts (BRAINSTORM.md, RESEARCH.md) that /z-plan consumes as Phase 0 context. Previous consultant rounds converged on the artifact/ideator/slug decisions; this critique evaluates the implementation-detail SPEC + task decomposition PLAN.

## SPEC.md summary
- Two new artifacts: BRAINSTORM.md (3 ideators competing on framings) and RESEARCH.md (findings, constraints, open questions, no recommendation).
- Two new commands: /z-brainstorm <topic> and /z-research <question>, each with phases.
- Agent extensions: MODE: brainstorm and MODE: research-review added to codex-consultant and gemini-consultant.
- /z-plan Phase 0 integration: Setup step 10 detects precontext artifacts, checks RESEARCH.md source freshness, surfaces conflicts.
- Out-of-scope: pluggable ideators, auto-detection of precontext need, streaming returns.

## PLAN.md summary
- 8 decisions (D1-D8), all picked the robust option (no shortcuts).
- 5 phases: A (agent extensions), B (/z-brainstorm), C (/z-research), D (/z-plan integration), E (README).
- 5 risks (R1-R5) with mitigation strategies noted.
- Precontext: none (this run was fresh).

## Critique scope (focus on):
1. Internal consistency between SPEC and PLAN.
2. Underspecified sections where an implementer could get stuck (edge cases).
3. Task decomposition (PLAN's phase/task structure) that could drift or waste review cycles.
4. Risk mitigation adequacy (R1-R5).
5. In-scope vs out-of-scope boundary clarity.

Return:
- Specific, concise findings (not generic reviews).
- Tradeoffs and potential fragile spots.
- Anything missing that should be IN scope, or over-specified that should be OUT.
- Do NOT recommend changes; flag for the caller to decide.
