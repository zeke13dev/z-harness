MODE: plan-review

You are reviewing a plan for a new Haiku subagent called `scope-probe` that will be integrated as Phase 0 of two host commands: `/z-audit` and `/z-brainstorm`.

## SPEC.md (high-level requirements)

The SPEC defines:
- A Haiku `scope-probe` agent that classifies tasks as LIGHT / MEDIUM / HEAVY based on codebase structure
- Caller supplies `axis_taxonomy` parameter at runtime (different per host command)
- Hybrid output contract: line-prefix routing fields + fenced JSON chunks
- 3-state graceful degradation: high-confidence / low-confidence / refuse
- Two per-host reconcilers (Sonnet): `scope-reconciler-audit` and `scope-reconciler-brainstorm`
- Calibration harness: `scripts/scope-probe-calibrate.py` validates 4 falsifiability tripwires
- SCOPE-*.json schema (live + archived, namespaced per host)
- v1a is integration-only; deletions of existing escalation chains deferred to v1b

## PLAN.md (execution roadmap)

Five phases:
- **Phase A:** Define agents and schema
- **Phase B:** Build calibration harness (before host integration)
- **Phase C:** Edit host commands to add Phase 0 blocks
- **Phase D:** Run calibration, tune thresholds, verify tripwires
- **Phase E:** Update documentation

## Host command integration context

**Current `/z-audit` structure (from commands/z-audit.md):**
- Setup (1-7)
- Phase 1: Pre-flight scoping
- Phase 2: Parallel auditor dispatch
- Phase 3: Merge findings
- Phase 4: Cross-LLM consult
- Phase 5: Promote to TASKS.md
- Phase 6: Codex safety gate
- Phase 7: Present + finalize

**Current `/z-brainstorm` structure (from commands/z-brainstorm.md):**
- Setup (1-7)
- Plan Route Check (after Setup, before Phase 1)
- Phase 1: Scaffolding
- Phase 2: Parallel ideator dispatch
- Phase 3: Synthesis + anti-bias check
- Phase 4: Finalize

**Current planning ecosystem:**
- `planning-router` (Haiku): advisory on route decisions, reads signals, never recommends a different host command
- `complexity-classifier` (Haiku): classify task complexity

## Critique request

Analyze the SPEC and PLAN for:
1. **Internal consistency:** Do SPEC and PLAN align on requirements? Are thresholds coherent?
2. **Missing edge cases:** What corner cases does the SPEC not cover?
3. **Calibration validation:** Can the calibration harness actually validate the 4 falsifiability tripwires given the rubric (tasks_total + tasks_complexity + escalation events)?
4. **Phase ordering:** Is there a circular dependency between phases? Can Phase B (build calibration harness) execute BEFORE Phase C (edit host commands)?
5. **Integration points:** 
   - SPEC says Phase 0 inserts "between Setup and Phase 1" for `/z-audit`. Does this actually fit the `/z-audit` doc structure?
   - SPEC says Phase 0 for `/z-brainstorm` inserts "after Plan Route Check, before Phase 1 scaffolding." Does the actual command doc support this insertion point?
   - HEAVY fanout in `/z-audit` Phase 0 dispatches sub-flows with `--scope-from <chunk-path>` flag. But `/z-audit` doesn't define this flag anywhere.

What's wrong, missing, or fragile? Focus on showstoppers (stuff that breaks the design) vs. polish issues.

Return: (1) Internal consistency issues, (2) Missing edge cases, (3) Calibration concerns, (4) Phase ordering concerns, (5) Integration-point reality check, (6) Net verdict (ship / fix-before-ship / restructure).