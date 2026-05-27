# Phase 1 scaffolding (RESTART) — fanout-escalate-primitive

## Topic (refined)

Pre-dispatch scope-decomposition router that runs BEFORE any z-* command (audit, debug, plan, review, etc). Given the user's request like "/z-audit trader", the router decides:
- **LIGHT** — narrowed single run (user asked about a specific component)
- **MEDIUM** — single normal run
- **HEAVY** — fan out the sub-command along a natural axis (per strategy, per component, per hypothesis, per cluster) into N parallel sub-runs that return IDEAS/findings; the main thread does the actual synthesis / planning / hypothesizing.

Same pattern reused across `/z-audit`, `/z-debug`, `/z-plan`, `/z-review-all`, etc. Sub-commands operate on manageable chunks; main thread reconciles.

Open questions: where does the routing live (skill? subagent? script lib?), how is the natural axis discovered (LLM, heuristic, command-supplied taxonomy?), what does main-thread synthesis look like per command, how does this differ from today's auto-bail/escalation chains which only fire AFTER work begins?

## Doc-fetcher synthesis: current state

**Critical finding: there is NO universal pre-flight scope router today.** Each command runs context-specific deterministic checks + optional advisory routing, and escalates **mid-flight** when evidence contradicts assumptions.

### Per-command escalation, today
- `/z-do`: collects deterministic signals after approach.md exploration; >3 files / non-obvious decision → /z-plan-light; >5 files / >2 decisions / cross-module/schema/public-API → /z-plan; unknown terrain → /z-research; conflicts → `planning-router` advisory.
- `/z-plan-light`: Plan Route Check after Phase 1 exploration, before decisions, again pre-implementation. Down-route to /z-do (tiny), up-route to /z-plan, contextual exits to /z-research, /z-brainstorm, /z-fix, /z-debug.
- `/z-plan`: docs-freshness gate (Setup step 8) → /z-maintain-docs if ≥20% stale; Plan Route Check runs **twice** (before Phase 1, after Phase 5); `expected_tasks > 25` AND `cluster_seams` in 2–6 → /z-plan-split; tiny → /z-do.
- `/z-plan-split`: not a pre-flight classifier itself — Phase 1 auto-proposes cluster seams (must be 2–6) or accepts user input; refuses outside that range. Dispatches N parallel `cluster-planner` subagents. No recursive split (clusters produce SPEC/PLAN/TASKS, not MANIFEST).
- `/z-debug`: only Phase 0 gates on "user already has diagnosis → /z-fix"; otherwise no pre-flight. Mid-flight escalation when architectural change / cross-module / schema needed → escalation.md + recommend /z-plan.

### Existing advisory infrastructure
- **`planning-router` agent** — called only when deterministic thresholds conflict. Takes compact `signals_json`. Decision rules in strict order: contextual exits → seam rules → file/task thresholds. Loop-prevention detects route chains and blocks ping-pong. Returns `STATUS: routed | ask_user | bad_input`. Orchestrator collects signals first, tries hard thresholds, calls router only when ambiguous.
- **`complexity-classifier` agent** — invoked per-TASK after TASKS.md is written; returns `low|medium|high` to pick implementer model. Does NOT drive command-scope decisions. First-match heuristics: user override → hard signals (concurrency/tx/money/>3 files/>5 AC) → soft signals (>3 files / ≥3 tests / invariant AC) → easy signals (1 file, ≤2 AC, rename/docstring) → default medium.

### Existing fan-out (for reconciliation reference)
- `/z-brainstorm`: 3 parallel ideators (Claude+Codex+Gemini), identical scaffolding, anti-bias merge.
- `/z-audit`: 1 auditor per dimension in parallel; merged + cross-LLM critique.
- `/z-research`: 1–3 parallel Explores (user-gated Phase 0).
- `/z-implement-all`: N=3 task tracks in parallel; per-track sequential spec-precheck → implementer → reviewer.
- `/z-plan-split` cluster-planners: N parallel per-cluster planning subagents producing per-cluster SPEC/PLAN/TASKS.

### Infra building blocks
- `scripts/log-event.sh`, `scripts/plan-path.sh`, `scripts/version.sh`.
- `planning-router` (advisory, signal-driven), `complexity-classifier` (task-level), `doc-fetcher` (Haiku, INDEX.json synthesis).

### The gap the user is pointing at
- **No universal pre-flight scope router.** Today each command bakes in its own up/down routing logic.
- **No mechanism to fan out an arbitrary z-command along a natural axis discovered from the topic.** /z-plan-split is the only existing fan-out *along scope*, and it's hard-coded to "cluster seams produce per-cluster SPEC/PLAN/TASKS." There's no equivalent for `/z-audit per-strategy`, `/z-debug per-hypothesis`, `/z-review-all per-PR-chunk`, etc.
- **All escalation is mid-flight, not pre-dispatch.** The user wants a router that decides light/medium/heavy *before* dispatch, so the right amount of work happens upfront — instead of paying for a full /z-audit and then bailing.

## Explore synthesis
(skipped — `Z_HARNESS_BRAINSTORM_EXPLORE` unset)

## RESEARCH.md
(none for this slug)
