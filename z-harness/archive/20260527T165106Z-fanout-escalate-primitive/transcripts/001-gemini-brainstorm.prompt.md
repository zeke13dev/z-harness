# Brainstorm: Extract recurring breakup+auto-escalate pattern

**Mode:** brainstorm

## Topic
Extract the recurring breakup+auto-escalate pattern across z-plan-light/z-plan/z-plan-split and z-audit/z-review-all into a single reusable primitive (skill/agent/script-lib?) with:
- Fan-out along a strategy/idea axis
- Automatic escalation thresholds
- Subagent dispatch of appropriate z-commands
- Main-orchestrator reconciliation of heterogeneous artifacts

## Scaffolding: Existing patterns

### Fan-out architecture today
- /z-brainstorm: 3 parallel ideators (Claude+Codex+Gemini), identical scaffolding, anti-bias merge.
- /z-audit: 1 auditor per dimension in parallel, each writes findings-<dim>.md, merged + cross-LLM critique.
- /z-research: 1–3 parallel Explores (user-gated Phase 0), bundled cross-LLM critique.
- /z-implement-all: up to N=3 task tracks in parallel; per-track sequential spec-precheck → implementer → reviewer.
- All subagents fresh-context; no shared state across parallel branches.
- Cost gating per command (/z-research user-gates ~2M/1M/abort; /z-brainstorm soft 200K warn; /z-audit hard bail >30 findings or >10 HIGH).

### Auto-escalation / bail thresholds today
- /z-implement-all: MAX_ATTEMPTS=2/task, MAX_TASK_WALL_MS=45min, MAX_BATCH_STALL_MS=30min, MAX_DISTINCT_HALTS=3/task, soft compaction Z_IMPLEMENT_PAUSE_TASKS=5/Z_IMPLEMENT_PAUSE_MINUTES=30.
- /z-audit bail: >30 findings OR >10 CRITICAL/HIGH → escalation.md, recommend /z-plan.
- /z-plan-light auto-bail to /z-plan if scope >5 files or >2 non-obvious decisions; /z-do auto-bails to /z-plan-light at ~3 files.
- /z-debug auto-bails to /z-plan when scope grows beyond architectural change.
- Spec-drift precheck before implementer; review escalation: 1 retry, then halt; non-attempt halts (needs_clarification, decision_needed) do not burn attempts.

### Reconciliation patterns today
- Atomic tmp-then-rename TASKS.md writes at batch boundary.
- Cross-task notes thread via cross_task_notes: [{task_id, note}] returned by implementer.
- Batch settlement → atomic write → batch_done → compaction check.
- Review delta compression cycle≥2: diff -u prior current > delta.patch; ~50% Opus saving.
- /z-audit: merge findings, cross-LLM dedup+score, promote safe subset → TASKS.md; escalation-level → escalation.md.
- /z-brainstorm: identical scaffolding to all ideators; Phase 3 anti-bias check.
- Tree-rooted plans: clusters sequential per MANIFEST run order; intra-cluster N=3.
- File-overlap dedup: same-file tasks defer.

### Infra
- scripts/log-event.sh <run-id> <event> <payload> → events.jsonl
- scripts/plan-path.sh resolve_plan_path <slug>
- scripts/version.sh blob in run_start

## Ask
Return exactly five sections:
1. **Framing** — the core shape of what we're extracting
2. **Core hypothesis** — why this works as a single primitive
3. **Risks** — what could go wrong with unification
4. **Plan implications** — how the z-harness command layout would change
5. **What would change my mind** — observations that would argue for a different approach

Mark any section `<missing>` if you cannot produce it. Do not add other sections or a recommendation. Be bold and distinct — this is one of three parallel ideator voices (Claude+Codex+Gemini), so diversity is the point.
