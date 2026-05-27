# Phase 1 scaffolding — fanout-escalate-primitive

## Topic

Extract recurring breakup+auto-escalate pattern across z-plan-light/z-plan/z-plan-split and z-audit/z-review-all into a single reusable primitive (skill/agent/script-lib?) with fan-out along a strategy/idea axis, automatic escalation thresholds, subagent dispatch of appropriate z-commands, and main-orchestrator reconciliation of heterogeneous artifacts.

## Doc-fetcher synthesis

### Existing fan-out architecture
- `/z-brainstorm`: 3 parallel ideators (Claude+Codex+Gemini), identical scaffolding, anti-bias merge.
- `/z-audit`: 1 auditor per dimension in parallel, each writes `findings-<dim>.md`, merged + cross-LLM critique in Phase 3.
- `/z-research`: 1–3 parallel Explores (user-gated Phase 0), bundled cross-LLM critique Phase 4.
- `/z-implement-all`: up to N=3 task tracks in parallel (`Z_HARNESS_PARALLEL`); per-track sequential spec-precheck → implementer → reviewer; intra-batch only, cross-cluster v2.
- All subagents get **fresh context**; no shared state across parallel branches.
- Cost gating per command (`/z-research` user-gates ~2M/1M/abort; `/z-brainstorm` soft 200K warn; `/z-audit` hard bail >30 findings or >10 HIGH).

### Auto-escalation / bail thresholds (`/z-implement-all`)
- Hard caps: `MAX_ATTEMPTS=2`/task, `MAX_TASK_WALL_MS=45min`, `MAX_BATCH_STALL_MS=30min`, `MAX_DISTINCT_HALTS=3`/task.
- Soft compaction: `Z_IMPLEMENT_PAUSE_TASKS=5`, `Z_IMPLEMENT_PAUSE_MINUTES=30`.
- `/z-audit` bail: >30 findings OR >10 CRITICAL/HIGH → write `escalation.md`, recommend `/z-plan`.
- Spec-drift precheck (`spec-precheck`, fresh) before implementer — catches drift 30–60min earlier.
- Review escalation: 1 retry with prior-attempt feedback; second failure on cycle ≥2 halts; never auto-retry past cycle 2.
- Non-attempt halts (`needs_clarification`, `decision_needed`) do not burn `MAX_ATTEMPTS`.

### Reconciliation patterns
- Atomic `tmp-then-rename` writes to TASKS.md at batch boundary; never partial.
- Cross-task notes thread via `cross_task_notes: [{task_id, note}]` returned by implementer.
- Batch settlement: all tracks terminal → atomic write → `batch_done` → check compaction.
- Review delta compression cycle≥2: `diff -u prior current > delta.patch`; ~50% Opus saving, ~70% reviewer prompt saving.
- `/z-audit`: merge findings, cross-LLM critique drops dupes/scores, promote safe subset → TASKS.md; escalation-level stays in `escalation.md`.
- `/z-brainstorm`: all ideators identical scaffolding; Phase 3 anti-bias check post hoc.
- Tree-rooted plans: clusters run sequentially per MANIFEST `## Run order`; intra-cluster N=3 honored.
- File-overlap dedup: same-file tasks defer to next batch.

### Key infra
- `scripts/log-event.sh <run-id> <event> <payload>` → `events.jsonl`.
- `scripts/plan-path.sh resolve_plan_path <slug>` → `z-harness/plans/<slug>` or `z-harness/<slug>`.
- `scripts/version.sh` blob in `run_start`.

### Not-yet-implemented (v2)
- Cross-cluster parallelism, per-call wall-clock timeout for subagents, recursive tree-of-trees nesting.

## Explore synthesis
(skipped — `Z_HARNESS_BRAINSTORM_EXPLORE` unset)

## RESEARCH.md
(none for this slug)
