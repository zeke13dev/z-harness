MODE: brainstorm

Topic: Pre-dispatch scope-decomposition router that runs BEFORE any z-* command (audit, debug, plan, review). Given "/z-audit trader", the router decides LIGHT (narrowed single run), MEDIUM (single normal run), or HEAVY (fan out the sub-command along a natural axis — per strategy, per component, per hypothesis, per cluster — into N parallel sub-runs; main thread reconciles). Same pattern across /z-audit, /z-debug, /z-plan, /z-review-all. Sub-commands work on chunks; main thread does synthesis. Where does routing live (skill? subagent? script lib?), how is the natural axis discovered, what does main-thread synthesis look like per command, and how does this differ from today's mid-flight auto-bail/escalation chains?

Scaffolding:

## CURRENT STATE — no universal pre-flight scope router exists.
- /z-do: deterministic file/decision thresholds AFTER approach.md exploration → /z-plan-light or /z-plan or /z-research; conflicts → planning-router.
- /z-plan-light: Plan Route Check after Phase 1; up-routes to /z-plan on >5 files / >2 decisions / cross-module.
- /z-plan: docs-freshness gate; Plan Route Check pre-Phase 1 AND post-Phase 5; >25 tasks AND 2-6 cluster seams → /z-plan-split.
- /z-plan-split: NOT pre-flight — Phase 1 auto-proposes 2-6 cluster seams; N parallel cluster-planner subagents produce per-cluster SPEC/PLAN/TASKS. No recursive split.
- /z-debug: mid-flight escalation only.

## EXISTING ADVISORY
- planning-router (Haiku) — called only on threshold conflict, signal-driven, loop-prevented.
- complexity-classifier (Haiku) — per-task model picker, not scope router.
- doc-fetcher (Haiku) — INDEX.json synthesis.

## EXISTING FAN-OUT
- /z-brainstorm: 3 ideators, identical scaffolding, anti-bias merge.
- /z-audit: 1 auditor per dimension, parallel.
- /z-research: 1-3 Explores parallel.
- /z-implement-all: N=3 task tracks parallel.
- /z-plan-split: N parallel cluster-planners.

## THE GAP
- No universal pre-flight scope router.
- No way to fan out an arbitrary z-command along a natural axis from the topic.
- All escalation is mid-flight; user pays for full work then bails.

Return exactly five sections: (1) Framing, (2) Core hypothesis, (3) Risks, (4) Plan implications, (5) What would change my mind. Mark missing sections as `<missing>`. Be bold and distinct.
