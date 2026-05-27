---
artifact: brainstorm
slug: fanout-escalate-primitive
generated_at: 2026-05-27T17:08:00Z
command: /z-brainstorm fanout-escalate-primitive (restart)
input_hash: 52fcc138fff3c652
depends_on: []
ideators:
  - claude
  - codex
  - gemini
ideator_models:
  claude: sonnet
  codex: default
  gemini: default
status: complete
chosen_framing: claude
---

## Framing: claude

### Framing
Current system treats scope discovery as emergent — each command stumbles into complexity mid-flight, then bails (sunk cost) or escalates (user interruption). This is architecturally backwards. Scope is knowable in advance with high fidelity because the natural decomposition axes are **structural properties of the codebase**, not semantic properties of the work. `/z-audit trader` doesn't need to *run* to discover it should fan out across 4 strategies + shared infra — that structure is already encoded in directory trees, import graphs, and module boundaries. The router is a **scope probe**, not a policy rule; the natural axis is *discovered* from topic + codebase structure, not chosen by the router.

### Core hypothesis
Standalone Haiku subagent **`scope-probe`**, invoked as **Phase 0 of every z-* command**. Returns a typed manifest (mode + axis + chunks + rationale) before the command's real Phase 1 begins.

- **Placement:** Skill-level, not script-level. Each z-* skill calls `scope-probe` as its literal first agent dispatch.
- **Ephemeral artifact:** `z-harness/SCOPE.json`, overwritten each run; commands read to branch.
- **Axis discovery protocol:**
  1. Parse topic slug into candidate entities (file paths, module names, strategy/component names).
  2. Walk directory structure 2 levels deep under each candidate.
  3. Count seams: subdirectories with own entry points, files with distinct import profiles, named clusters (`strategies/`, `components/`, `hypotheses/`).
  4. Query doc-fetcher for pre-existing cluster docs.
  5. Output: `{mode: HEAVY, axis: per_strategy, chunks: [momentum, mean_revert, arb, hedger], rationale: ...}`.
- **Per-command fanout shape:**
  - `/z-audit`: chunks → parallel auditor subagents per chunk; synthesizer merges findings, dedups cross-chunk issues, elevates systemic patterns.
  - `/z-debug`: chunks → parallel hypothesis-cluster investigators; synthesis picks the causal chain.
  - `/z-plan`: chunks → parallel domain-planners (like /z-plan-split but pre-flight); synthesis reconciles inter-cluster deps before unified TASKS.md.
  - `/z-review-all`: chunks → parallel reviewers per component; synthesis computes aggregate risk + cross-component coupling violations.
- **Synthesis:** command-specific but structurally identical — one Sonnet reconciler agent receives all chunk outputs in a single prompt, runs a conflict/overlap pass, produces unified artifacts. No multi-round ping-pong.
- **Thresholds:** LIGHT (≤1 file/component, no seams); MEDIUM (2–5 files/components, ≤2 seams); HEAVY (≥3 seams OR named sub-cluster dir OR module name with ≥4 direct children).
- **Key departure from today:** mid-flight escalation chains (z-plan-light up-route, z-debug architectural bail) are **removed**. They become assertions, not decisions.

### Risks
- **Probe accuracy vs codebase structure** — flat repos have no structural signal; default to MEDIUM incorrectly. Mitigation: fall back to doc-fetcher; ask user.
- **SCOPE.json race conditions** — parallel runs overwrite each other. Mitigation: timestamp file per invocation.
- **Axis mismatch across commands** — debug wants hypotheses; audit wants components. Mitigation: probe is topic+command-aware.
- **Ambiguous user topic** — "trader" = module / strategy / subprocess. Mitigation: confidence-low → confirmation gate before dispatch.
- **Synthesis agent becomes new critical path** — if input chunks diverge too much, forced merge produces mush. Mitigation: fallback "raw chunks + manual reconciliation needed" flag.
- **LIGHT-run tax** — every run pays ~5–10s Haiku overhead. Mitigation: commands with strong structural priors can skip and hardcode LIGHT.

### Plan implications
- **Delete:** z-plan-light Phase 1 up-route, z-plan pre-Phase-1 Plan Route Check, z-debug mid-flight architectural bail. Surviving mid-flight checks become assertions.
- **Add:** `scope-probe` Haiku subagent; SCOPE.json schema; per-command synthesis prompts (audit / debug / plan / review); low-confidence confirmation gate UI.
- **Modify:** Phase 0 of each z-* skill becomes scope-probe dispatch + SCOPE.json read; `planning-router` is retired or demoted to ambiguous-topic confirmation; `/z-plan-split` becomes an internal implementation of /z-plan's HEAVY path, not a user-facing command.
- **Sequencing:** scope-probe BEFORE doc-fetcher (probe determines which docs to fetch per chunk).
- **Calibration plan:** run scope-probe against 5–6 historical z-harness invocations; compare HEAVY/MEDIUM/LIGHT classification to actual mid-flight routing decisions; tune thresholds.

### What would change my mind
1. Empirical: ≥70% of z-* runs are already MEDIUM (probe overhead > prevented cost).
2. Synthesis agent consistently produces worse output than single MEDIUM run.
3. HEAVY is rare (<20% of runs) — probe latency for no benefit.
4. Natural axis turns out to be semantically determined (which strategies are logically related) not structurally — Haiku can't do it; Sonnet costs as much as just running the command.

---

## Framing: codex

### Framing
A **shared pre-dispatch router with command-specific adapters**, NOT a new standalone z-command and NOT logic pasted into every skill. The reusable layer owns cheap signal extraction, LIGHT/MEDIUM/HEAVY classification, route artifacts, child-run manifests, telemetry, loop prevention, and fanout limits. Each command owns *what split axes are valid* and *what synthesis means*. Key distinction: the router does NOT ask "which z-command should this become?" — it asks **"what execution topology should this requested command use before expensive work starts?"**

### Core hypothesis
The real primitive is the pipeline: `intent → command profile → terrain sketch → candidate axes → chunk contract → synthesis contract`.

Natural-axis discovery should be **constrained and evidence-seeking, not open-ended invention**. Use cheap signals first: explicit noun phrases, docs concepts, candidate files, changed files, prior artifacts, command defaults, known phase thresholds. Advisory router only ranks or arbitrates candidate axes.

**Per-command axis taxonomies:**
- `/z-audit`: by component, risk domain, invariant, workflow, or existing audit dimension.
- `/z-debug`: by hypothesis, failure mode, suspected subsystem, repro path.
- `/z-plan`: by feature cluster, architecture boundary, migration phase, data/control boundary.
- `/z-review-all`: by task range, changed module, risk tier, ownership boundary.

**Router output (structured):** route class, confidence, reason codes, chosen axis, **rejected axes** (with reasons), chunk specs, shared surfaces, **child routing mode**, synthesis contract.

### Risks
- **Fake decomposition** — broad-looking topics can be one tightly coupled state machine, schema change, or public contract. Splitting early hides the central invariant.
- **Artifact incoherence** — multiple locally valid sub-runs can produce outputs that don't combine into one canonical audit/debug/plan/review result.
- **Recursive orchestration sprawl** — child runs must default to `router_mode=child`: may narrow, may NOT HEAVY fan out again without explicit parent permission.
- **Lossy synthesis** — main thread must preserve contradictions and shared-surface warnings, not smooth everything into a generic summary.
- **Cost inversion** — if axis discovery requires real exploration, the router becomes `/z-research` or `/z-plan` Phase 1 in disguise.

### Plan implications
Build `scope-router` as `scripts/lib` package + small command adapters. Pieces:
- `classify_scope(command, topic, context) -> LIGHT | MEDIUM | HEAVY`
- `discover_axes(command, topic, context) -> ranked axis candidates`
- `build_chunks(axis, command, topic, context) -> bounded child specs`
- `build_synthesis_contract(command, axis) -> merge schema`
- `ROUTE.md` / `SCOPE.md` written before command execution
- Parent manifest for HEAVY: child run ids, chunk scopes, input hashes, route chain, synthesis status

**Synthesis is command-specific** (NOT a generic reconciler):
- Audit: dedupe findings, normalize severity, preserve dissent, call out cross-chunk systemic risks.
- Debug: compare hypotheses by evidence, maintain shared repro facts, choose next isolation/fix.
- Plan: reconcile shared files/contracts, emit one coherent SPEC/PLAN/TASKS OR explicit split artifacts.
- Review: collapse into blocker/non-blocker sets, identify systemic regressions across chunks.

**Differs from today:** current escalation chains discover "too big / uncertain / wrong command" AFTER partial work. The router decides execution shape BEFORE committing — mid-flight checks survive as correction points (assertions), not decisions.

### What would change my mind
- If the only truly shared pieces across commands are logging and manifests — every useful axis and synthesis rule is command-local. Then the right design is a tiny shared helper lib, not a router.
- If pre-flight axis discovery needs enough exploration that it duplicates existing command phases.
- Strongest positive evidence: successful pilots where HEAVY improves outcomes — `/z-audit trader` finds sharper non-duplicated issues, `/z-debug <broad bug>` isolates faster without losing repro discipline, `/z-plan <large feature>` produces a cleaner task graph than today's `/z-plan` → `/z-plan-split`.

---

## Framing: gemini

### Framing
Current architecture is **reactive, mid-flight escalation**: commands launch assuming manageable scope, do initial exploration, only up-route when hardcoded thresholds hit. We have specific fan-out patterns (`/z-plan-split` clustering, `/z-brainstorm` ideators) but lack a universal, **proactive map-reduce layer**. Goal: a pre-dispatch router that intercepts any z-* command, sizes the bounding box before executing the primary skill, discovers natural structural seams, orchestrates N parallel narrowly-scoped sub-runs, followed by main-thread synthesis. Shifts the system from **"try and abort"** to **"measure and divide."**

### Core hypothesis
- **Where:** new lightweight universal CLI entrypoint (e.g. `z-dispatch` wrapper script) paired with a Haiku `scope-analyzer` subagent. Intercepts user prompt before underlying z-* skill is invoked.
- **How axis discovered:** rapid pass over `INDEX.json` + workspace directory tree + initial prompt. Looks for architectural boundaries (dirs/components), polymorphic patterns (multiple strategy implementations in trading system), distinct analytical dimensions. Outputs standard JSON schema: `{size, sub_targets}`.
- **Per-command synthesis:**
  - `/z-audit`: maps per component → reduces into prioritized risk matrix + unified summary.
  - `/z-debug`: maps per failure hypothesis or subsystem → reduces by comparing diagnostics, rejecting false hypotheses, synthesizing confirmed root cause + fix.
  - `/z-plan`: replaces `/z-plan-split` Phase 1 mid-flight cluster proposal entirely; maps per cluster seam; reduces via existing SHARED-CONCERNS.md.
  - `/z-review-all`: maps per feature/PR/logical commit chunk; reduces into deduplicated review memo.
- **Differs from today:** today, user pays time + token cost of a partial run that aborts and restarts. Pre-flight routing calculates the shape first; subagents spawn with strict non-overlapping boundaries from second zero.

### Risks
- **Unknown unknowns** — especially debugging; true scope often cannot be known until mid-flight exploration. Pre-flight routing might guess wrong axis entirely.
- **Synthesis lossiness** — merging N separate audit reports / debug traces is notoriously hard; reducer might drop critical nuanced cross-references → disjointed final output.
- **Over-splitting / context fragmentation** — decomposing a medium task into 5 micro-tasks robs sub-agents of holistic context → localized hallucinations that break the global system.
- **Latency overhead** — mandatory LLM scoping pass before every command makes genuinely simple commands feel sluggish.

### Plan implications
- Create `scope-analyzer` Haiku subagent emitting `{size, axis, targets}` payload.
- Refactor z-audit / z-debug / z-plan / z-review-all entrypoints to accept `--scope` flags so they act as headless workers for the orchestrator.
- Write distinct **reducer scripts/prompts per command** (combining debug logs ≠ combining plan clusters).
- **Bypass mechanism:** `--force-medium` or `--no-route` flag for known-quantity tasks.

### What would change my mind
- Token economics of huge-context models (Gemini 1.5 Pro etc) make monolithic single-pass processing significantly cheaper and more cohesive than N parallel Haiku + 1 orchestrator.
- Pre-flight scoping proves consistently inaccurate (e.g. splits by file type instead of feature capability) → mid-flight exploration is the only reliable way to measure complexity.
- Users report the added 5–10s latency creates a frustrating unresponsive UX.

---

## Anti-bias check

**Framing** — *Codex wins.* Codex's "the router does NOT ask which z-command this should become — it asks what execution topology this command should use" is the sharpest non-obvious distinction. It cleanly separates pre-flight scope routing from the existing `planning-router` (which IS about which command). Claude's "scope is knowable in advance with high fidelity" is bold but assumes too much for non-structural codebases. Gemini's "map-reduce / measure-and-divide" reframe is descriptive but doesn't add a design constraint beyond what Codex already names.

**Core hypothesis** — *Codex wins on the structured contract; Claude wins on the discovery protocol.* Codex provides the most actionable router output schema: `{route class, confidence, reason codes, chosen axis, rejected axes (with reasons), chunk specs, shared surfaces, child routing mode, synthesis contract}`. Crucially Codex includes **rejected axes with reasons** — auditable transparency the other two miss. Claude offers the most concrete *how-to* for axis discovery (parse → walk dirs 2 levels → count seams → query doc-fetcher → emit typed manifest). *Claude-favoring justification for grafting in the discovery protocol: Codex says "constrained, evidence-seeking discovery" but never names the concrete heuristics. Claude's 5-step protocol fills exactly that gap.* Gemini's `{size, sub_targets}` schema is the thinnest of the three.

**Risks** — *Codex wins decisively (4/5 risks).* "Fake decomposition" (broad-looking topics that are actually one tightly coupled state machine — exactly the user's worry that pre-flight gets it wrong) and "recursive orchestration sprawl with `router_mode=child` default" are operationally specific safety rails the others don't surface. "Cost inversion" (if axis discovery needs real exploration, the router becomes /z-research in disguise) is the cleanest "are we even building the right thing" check. Claude contributes one risk Codex misses: **SCOPE.json race conditions** in parallel runs — a real infra detail. Gemini's "unknown unknowns" for debug is the strongest version of the "pre-flight can't know" risk and worth keeping.

**Plan implications** — *split.* Codex wins on the script-lib + adapter shape, the explicit `router_mode=child` rule, and the *command-specific synthesis* requirement (not a generic reconciler) — preserving dissent in audit/debug is critical and a generic reducer would smooth it away. Claude wins on the calibration plan ("run scope-probe against 5–6 historical invocations and tune") which is a concrete and cheap way to de-risk v1. Gemini wins on the **bypass flag** (`--force-medium` / `--no-route`) — a power-user escape that the other two miss. Claude's "delete mid-flight escalation chains entirely" is too aggressive for v1; Codex's "mid-flight survives as assertions, not decisions" is the right framing.

**What would change my mind** — *Claude wins on falsifiability.* Claude's numeric thresholds (≥70% MEDIUM kills it; HEAVY <20% kills it) are concrete and cheaply measurable from `events.jsonl`. Codex's pilot criteria (sharper /z-audit, faster /z-debug, cleaner /z-plan task graph) match real outcomes but are softer signals. Gemini surfaces the **monolithic-context counterfactual** that Claude/Codex don't — worth keeping as a falsifier.

**Net:** Codex wins **framing + risks + plan-implications-spine** (3.5/5). Claude wins **discovery protocol + calibration plan + falsifiability metrics** (1.5/5). Gemini wins **bypass flag + monolithic-context falsifier** (1/5 — meaningful grafts but not framing-level).

## Orchestrator recommendation

**Codex framing as the spine.** Build `scope-router` as a `scripts/lib` package + per-command adapters; structured router output including `rejected_axes` and `router_mode=child` for recursion safety; command-specific synthesis (not a generic reducer); mid-flight checks survive as assertions, not decisions.

**Graft in from Claude:** the concrete 5-step axis discovery protocol (parse → walk dirs 2 levels → count seams → query doc-fetcher → emit typed manifest); SCOPE.json race-condition handling (timestamp per invocation); calibration plan against 5–6 historical runs; numeric falsifiability thresholds (≥70% MEDIUM or <20% HEAVY kills it).

**Graft in from Gemini:** `--force-medium` / `--no-route` bypass flag; the monolithic-context counterfactual as an explicit falsifier to track.

**Defer/reject:** Claude's "delete all mid-flight escalation" (too aggressive for v1); Gemini's `z-dispatch` universal wrapper script (Codex's per-skill adapter is lower-risk); Claude's "/z-plan-split becomes internal" (good eventual target, but v1 should leave existing commands alone where possible).

**v1 scope:** start with `/z-audit` and `/z-brainstorm` integrations (cleanest axis taxonomies — dimensions and vendors respectively); validate the structured-output schema; only then expand to `/z-debug` and `/z-plan`. `/z-implement-all` is explicitly out of v1 — its semantics are too specialized.

## User choice

**Chosen: Claude (scope-probe) — pure form.**

Standalone Haiku **`scope-probe`** subagent invoked as the literal **Phase 0 of every z-* command**. Returns a typed manifest `{mode: LIGHT|MEDIUM|HEAVY, axis, chunks, rationale, confidence}` before the command's real Phase 1 begins.

**Placement:** skill-level. Each z-* skill calls `scope-probe` as its first agent dispatch. Ephemeral artifact `z-harness/SCOPE.json` (or timestamped per invocation for race safety) — commands read it to branch.

**Axis discovery protocol (5 steps):**
1. Parse topic slug into candidate entities (file paths, module names, strategy/component names).
2. Walk directory structure 2 levels deep under each candidate.
3. Count seams: subdirectories with own entry points, files with distinct import profiles, named clusters (`strategies/`, `components/`, `hypotheses/`).
4. Query `doc-fetcher` for pre-existing cluster docs.
5. Output the typed manifest.

**Per-command fanout shape:**
- `/z-audit`: chunks → parallel auditor subagents; synthesizer merges findings, dedups cross-chunk issues, elevates systemic patterns.
- `/z-debug`: chunks → parallel hypothesis-cluster investigators; synthesis picks the causal chain, discards the rest.
- `/z-plan`: chunks → parallel domain-planners (replacing /z-plan-split Phase 1 mid-flight cluster proposal); synthesis reconciles inter-cluster deps before unified TASKS.md.
- `/z-review-all`: chunks → parallel reviewers per component; synthesis computes aggregate risk + cross-component coupling violations.

**Synthesis:** command-specific but structurally identical — one Sonnet reconciler agent receives all chunk outputs in a single prompt, runs a conflict/overlap pass, produces unified artifacts. Fallback "raw chunks + manual reconciliation needed" flag if chunks diverge too much.

**Thresholds:**
- LIGHT: ≤1 file/component, no seams.
- MEDIUM: 2–5 files/components, ≤2 seams.
- HEAVY: ≥3 seams OR named sub-cluster directory exists OR module name with ≥4 direct children.

**Aggressive refactors accepted:**
- Delete z-plan-light Phase 1 up-route, z-plan pre-Phase-1 Plan Route Check, z-debug mid-flight architectural bail.
- Surviving mid-flight checks become assertions, not decisions.
- Retire (or demote) `planning-router` Haiku agent to ambiguous-topic confirmation only.
- `/z-plan-split` becomes an internal implementation detail of /z-plan's HEAVY path, not a user-facing command.

**Sequencing:** scope-probe BEFORE doc-fetcher (probe determines which docs to fetch per chunk).

**Calibration plan (v1 de-risk):** run scope-probe against 5–6 historical z-harness invocations from `z-harness/archive/`; compare HEAVY/MEDIUM/LIGHT classification to the actual mid-flight routing decisions those runs made; tune thresholds to match before any production use.

**Falsifiability tripwires (kill or rethink if any fire):**
1. ≥70% of z-* runs classify as MEDIUM → probe overhead > prevented cost.
2. HEAVY <20% of runs → probe latency for no benefit; mid-flight escalation sufficient.
3. Synthesis agent consistently produces worse output than single MEDIUM run.
4. Natural axis is semantically (not structurally) determined → Haiku can't do it; Sonnet costs as much as just running the command.

**Next step:** `/z-plan` on this BRAINSTORM.md to produce SPEC/PLAN/TASKS. Suggested first SPEC tasks: scope-probe subagent definition; SCOPE.json schema; calibration harness against historical runs; /z-audit integration as v1 pilot.
