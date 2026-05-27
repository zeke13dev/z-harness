# Phase 1 Scaffolding — fanout-escalate-primitive

**input_hash:** f4e108675edd6cca

## Topic

Extract recurring breakup+auto-escalate pattern across z-plan-light/z-plan/z-plan-split and z-audit/z-review-all into a single reusable primitive (skill/agent/script-lib?) with fan-out along a strategy/idea axis, automatic escalation thresholds, subagent dispatch of appropriate z-commands, and main-orchestrator reconciliation of heterogeneous artifacts.

## Doc-fetcher synthesis (from docs/llm/commands.json + docs/llm/agents.json)

### Key commands (fan-out / escalation relevant)
- **z-brainstorm**: 3 parallel ideators (claude+codex+gemini), identical scaffolding, anti-bias merge. Cost target 200K.
- **z-audit**: 1 auditor per dimension in parallel (auditor.md agent), each writes findings-<dim>.md; merge+cross-LLM dedup; hard bail >30 findings or >10 CRITICAL/HIGH → escalation.md; recommend /z-plan.
- **z-research**: 1–3 parallel Explores (user-gated Phase 0), bundled cross-LLM critique.
- **z-implement-all**: up to N=3 task tracks parallel; per-track: spec-precheck → implementer → reviewer. MAX_ATTEMPTS=2/task, MAX_TASK_WALL_MS=45min, MAX_BATCH_STALL_MS=30min, MAX_DISTINCT_HALTS=3/task. Soft compaction pause at Z_IMPLEMENT_PAUSE_TASKS=5/Z_IMPLEMENT_PAUSE_MINUTES=30.
- **z-plan-light**: auto-bail to /z-plan if scope >5 files or >2 non-obvious decisions. Ships via FIX.md.
- **z-do**: auto-bails to z-plan-light at ~3 files.
- **z-debug**: auto-bails to /z-plan when scope grows beyond architectural change. Phase 10 memory review.
- **z-plan-split**: splits large work into one-level cluster plans using cluster-planner subagent.
- **z-review-all**: final-gate reviews cumulative implementation; Phase 7 auto memory review.
- **z-audit-plan**: audits existing SPEC/PLAN/TASKS and routes contextually; read-only.

### Key agents
- **auditor**: read-only Sonnet single-dimension; writes findings file, returns counts.
- **implementer**: implements exactly one task block; mandatory self-check.
- **reviewer**: post-implementation gate.
- **spec-precheck**: drift detection before implementer.
- **complexity-classifier**: Haiku task classifier (low|medium|high) for model routing.
- **planning-router**: Haiku advisory router for ambiguous plan decisions.
- **cluster-planner**: z-plan-split leaf planner; writes cluster SPEC/PLAN/TASKS.
- **consultant-primary/secondary**: LLM proxy supporting 11+ modes.

### Key invariants
- All subagents are fresh-context; no shared state across parallel branches.
- Review-family commands preserve evidence separately; promote only actionable findings into task-shaped artifacts.
- Atomic tmp-then-rename TASKS.md writes at batch boundary.
- Cross-task notes thread via cross_task_notes: [{task_id, note}].
- Review delta compression cycle≥2: diff -u prior current → delta.patch (~50% Opus saving).
- Route chains prevent ping-pong; after two entries or immediate return-to-prior, ask user.

## Explore synthesis
(skipped — Z_HARNESS_BRAINSTORM_EXPLORE not set)

## RESEARCH.md
(not present)
