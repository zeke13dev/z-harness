MODE: brainstorm

TOPIC: Pre-dispatch scope-decomposition router that runs BEFORE any z-* command (audit, debug, plan, review). Given "/z-audit trader", the router decides LIGHT (narrowed single run), MEDIUM (single normal run), or HEAVY (fan out the sub-command along a natural axis — per strategy, per component, per hypothesis, per cluster — into N parallel sub-runs; main thread reconciles). Same pattern across /z-audit, /z-debug, /z-plan, /z-review-all. Sub-commands work on chunks; main thread does synthesis. Where does routing live (skill? subagent? script lib?), how is the natural axis discovered, what does main-thread synthesis look like per command, and how does this differ from today's mid-flight auto-bail/escalation chains?

SCAFFOLDING:

**CURRENT STATE** — no universal pre-flight scope router exists.
- /z-do: deterministic file/decision thresholds AFTER approach.md exploration → /z-plan-light or /z-plan or /z-research; conflicts → planning-router.
- /z-plan-light: Plan Route Check after Phase 1; up-routes to /z-plan on >5 files / >2 decisions / cross-module.
- /z-plan: docs-freshness gate; Plan Route Check pre-Phase 1 AND post-Phase 5; >25 tasks AND 2-6 cluster seams → /z-plan-split.
- /z-plan-split: NOT pre-flight — Phase 1 auto-proposes 2-6 cluster seams; N parallel cluster-planner subagents produce per-cluster SPEC/PLAN/TASKS. No recursive split.
- /z-debug: mid-flight escalation only.

**EXISTING ADVISORY**
- planning-router (Haiku) — signal-driven, loop-prevented.
- complexity-classifier (Haiku) — per-task model picker.
- doc-fetcher (Haiku) — INDEX.json synthesis.

**EXISTING FAN-OUT**
- /z-brainstorm: 3 ideators, identical scaffolding, anti-bias merge.
- /z-audit: 1 auditor per dimension, parallel.
- /z-research: 1-3 Explores parallel.
- /z-implement-all: N=3 task tracks parallel.
- /z-plan-split: N parallel cluster-planners.

**THE GAP**
- No universal pre-flight scope router.
- No way to fan out an arbitrary z-command along a natural axis from the topic.
- All escalation is mid-flight; user pays for full work then bails.

CONTEXT:

/z-plan-split already captures one fan-out pattern: Phase 1 reads the problem statement + raw SPEC draft, uses complexity metrics (file count, decision count, cross-module linkage) to propose 1-6 "cluster seams" (natural decomposition axes), then spawns N parallel cluster-planner subagents that each own a cluster. The main orchestrator collects per-cluster SPEC/PLAN/TASKS, validates overlap via SHARED-CONCERNS.md, and sequences implementation via /z-implement-all's sequential cluster iteration.

/z-review-all and /z-implement-all both have soft-phase memory-review stages (Phase 9 and Phase 7 respectively) that are post-flight reconciliation loops. Memory-review discovers new concepts or amendments worth capturing, but it runs after all work is done.

Today's routing is ad-hoc:
- /z-plan uses hardcoded file-count thresholds (>25 tasks → /z-plan-split).
- /z-debug has no pre-flight routing — it starts a hypothesis tournament mid-flight and only escalates if it hits complexity caps.
- /z-audit has no fan-out; it runs 1 auditor per dimension but never splits by component or strategy.
- /z-review-all and /z-implement-all have no pre-flight scope check; they assume a single plan slug and iterate sequentially.

KEY COMMANDS & EXISTING PATTERNS (from docs):

1. **Commands that fan out today:**
   - /z-plan-split (Phase 1): proposes cluster seams, dispatches N cluster-planners in parallel, collects per-cluster artifacts.
   - /z-audit: dispatches 1 auditor per dimension (correctness, cleanliness, design, [perf]) in parallel; no per-component split.
   - /z-brainstorm: 3 parallel ideators with identical scaffolding.
   - /z-implement-all: N=3 parallel task tracks within a single cluster; clusters are sequential (from MANIFEST run order).

2. **Commands that don't fan out but could:**
   - /z-debug: hypothesis tournament mid-flight; no pre-flight decomposition by hypothesis subspace or component.
   - /z-review-all: no pre-flight routing; assumes single SPEC/PLAN/TASKS.
   - /z-audit: no per-component split; runs monolithic dimension audits.

3. **Existing discovery mechanisms:**
   - /z-plan Phase 1 extracts file-list and decision-list from initial problem statement to decide routing.
   - docs/llm/INDEX.json cross-references files to concepts; can be used to group files by domain.
   - SPEC.md structure (e.g. "Strategy: Foo", "Strategy: Bar") can signal natural boundaries.

RETURN EXACTLY FIVE SECTIONS: (1) Framing, (2) Core hypothesis, (3) Risks, (4) Plan implications, (5) What would change my mind. Mark missing sections as `<missing>`. Do not add other sections or a recommendation.
