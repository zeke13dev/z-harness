# Adaptive INTENT — Lighter-than-SDD Operating Model

> Last updated: 2026-07-09
> Covers source: scripts/intent-schema.py, scripts/config.py, agents/intent-classifier.md, agents/task-tree-generator.md, skills/z-plan/SKILL.md, skills/z-execute/SKILL.md, skills/z-amend/SKILL.md, skills/z-review-all/SKILL.md, agents/implementer.md, agents/reviewer.md, docs/human/adaptive-intent.md

## Overview

Adaptive INTENT is the default planning mode (`workflow.planning_mode=intent`). It replaces the legacy SPEC/PLAN/TASKS up-front contract with a thinner frozen `INTENT.md`, an append-only `LEDGER.md`, and a durable append-only **known-work graph** (`work-graph.json`) that `/z-plan` seeds and `/z-execute` grows and schedules over.

The design is thin-but-frozen, not mutable. `/z-plan` makes the planning mode explicit before the hard cost gate: config and flags (`--full`, `--quick`, `--standard`, `--deep`) choose the recommended option, but the visible gate records the actual Intent-vs-Full SDD choice. Intent mode authors `INTENT.md`, an initial generated `TASKS.md`, and (as of the 2026-07-04 known-work-DAG redesign) an initial `work-graph.json` frontier; `/z-execute` freezes INTENT at the execution boundary, snapshots it to the archive on first freeze, bootstraps LEDGER, then repeatedly expands and schedules the known-work graph until acceptance is met or a guard halts. Legacy plans remain legacy whenever `SPEC.md` exists.

**2026-07-04 redesign in brief:** `task-tree-generator` was reframed from a strict "BFS level generator" into a **known-work graph expander**. It no longer just emits one flat batch per level; when dispatched with `scheduler_mode: known_work_graph` it appends newly-knowable nodes to `work-graph.json` (an append-only DAG with explicit `depends_on` edges), and `/z-execute`'s loop computes the ready frontier from that graph rather than assuming the next monotonic BFS level is the only unit of work. "Levels" are now scheduler-depth hints over the DAG, not semantic planning phases — closer to a CPU scheduler picking runnable work than a wave-by-wave BFS. TASKS.md remains the human-readable / `session-helpers.sh`-parseable projection of implementation nodes.

## Key entry points

<!-- AUTO-START: entry-points -->
- `scripts/intent-schema.py:219` — `validate_intent` — validates INTENT frontmatter and required sections by level.
- `scripts/intent-schema.py:300` — `lint_criteria` — flags non-observable acceptance checklist items.
- `scripts/intent-schema.py:380` — `reopen_intent` — resets `frozen_at` to `pending` for `/z-amend`.
- `scripts/intent-schema.py:442` — `freeze_intent` — stamps or reports existing frozen ISO timestamp.
- `scripts/intent-schema.py:497` — `bootstrap_ledger` — creates LEDGER.md frontmatter idempotently.
- `scripts/intent-schema.py:865` — `evaluate_acceptance` — evaluates checklist criteria against LEDGER and cumulative diff.
- `agents/task-tree-generator.md:21` — `scheduler_mode` / `work_graph_path` dispatch inputs — when `scheduler_mode: known_work_graph` is set, the generator appends nodes to the durable graph instead of only emitting a flat TASKS.md batch.
- `agents/task-tree-generator.md:96` — Known-work rule — only append work knowable from frozen INTENT, accepted flags, existing graph, and the latest completed node's outcome; placeholder `expansion`/`handoff_required` nodes are explicit and sparing, never a fabricated complete downstream tree.
- `agents/task-tree-generator.md:102` — Phase 2, "Emit TASKS.md and append the graph" — appends new nodes with stable IDs (`T<NNN>` implementation, `W<NNN>` non-implementation), sets `status: "ready"` only when all `depends_on` are `done`, and appends an `append_log` entry per call.
- `skills/z-plan/SKILL.md:28` — default intent compiler — `/z-plan` default path is conversation → sharpened problem → optional ideated framing → intent contract → execution DAG; full SDD is explicit compatibility only.
- `skills/z-plan/SKILL.md:35` — sharpen always first — `/z-plan` must run shared `/z-sharpen` inline or consume fresh `GRILL.md` before planning.
- `skills/z-plan/SKILL.md:36` — brainstorm ask gate — `/z-plan` asks whether to run `/z-brainstorm` and may recommend it when alternatives remain; it never auto-dispatches brainstorm.
- `skills/z-plan/SKILL.md:38` — pre-planning watcher checkpoint seam — after sharpen and optional brainstorm artifacts stabilize, `/z-plan` evaluates the shared compaction/checkpoint seam before high-context planning.
- `skills/z-plan/SKILL.md:39` — INTENT iteration loop — `/z-plan` restates the sharpened problem/framing, grounds only missing source facts, drafts `INTENT.md`, and iterates with the user 1–2 times.
- `skills/z-plan/SKILL.md:40` — concern flags plus optional audit ask — before final read-through, `/z-plan` surfaces LLM concern/decision/assumption flags and asks whether to fold in `/z-audit-plan`.
- `skills/z-plan/SKILL.md:42` — execution strategy generation — `/z-plan` writes the initial `work-graph.json` known-work frontier (Phase 8, line ~2622) before deriving `execution-strategy.md` (line ~2713) from `TASKS.md` + `work-graph.json` + validated `workstreams.json`; `execution-strategy.md` generation now hard-fails if `work-graph.json` is missing.
- `skills/z-plan/SKILL.md:43` — pre-execute watcher checkpoint seam — after execution strategy and handoff artifacts stabilize, `/z-plan` evaluates the shared checkpoint seam before `/z-execute`.
- `skills/z-execute/SKILL.md:440` — SPEC-vs-INTENT mode detection — SPEC wins; INTENT used only when SPEC absent.
- `skills/z-execute/SKILL.md:506` — freeze and archive snapshot — first execution freezes INTENT and writes `INTENT.frozen.md`.
- `skills/z-execute/SKILL.md:545` / `skills/z-execute/SKILL.md:603` — `WORK_GRAPH_FILE` resolution — resolved via the same `_resolve_exact_plan_artifact` exact-name lookup used for `intent-readthrough-flags.md`/`brainstorm-choice.json`, falling back to `$BASE/work-graph.json`.
- `skills/z-execute/SKILL.md:639` — BFS/depth-cap guard config — reads `workflow.intent_bfs_level_cap` with fallback 6.
- `skills/z-execute/SKILL.md:689` — known-work DAG scheduler loop — re-reads `work-graph.json`, computes the ready frontier, dispatches it through the reusable per-task engine, and refills/appends as nodes return.
- `skills/z-execute/SKILL.md:794` — task-tree-generator dispatch — expands the known-work graph and refreshes the TASKS.md projection for the current frontier.
- `skills/z-execute/SKILL.md:930` — INTENT mode context injection — injects `intent_snapshot:`, `ledger_path:`, and (when present) `work_graph_path:` into implementer/reviewer prompts.
- `skills/z-execute/SKILL.md:1150` — work-graph status sync — after each settled frontier, recomputes node `status` (`ready`/`blocked`/`done`/`running`) from TASKS.md task markers and `depends_on`, and appends a `status_log` entry; this is the one place graph node status (not identity) mutates.
- `skills/z-amend/SKILL.md:241` — stale TASKS marker — sets `stale_reason: amended-intent` so tasks regenerate.
<!-- AUTO-END: entry-points -->

## Planning model

1. Resolve route signals and the recommended planning mode from config/flags, then surface the explicit Intent-vs-Full SDD gate before any expensive Agent dispatch.
2. In intent mode, choose or classify the intent level (`quick`, `standard`, `deep`), write `INTENT.md` with `frozen_at: pending`, and generate the initial canonical `TASKS.md` through `task-tree-generator`.
3. In full mode, write the legacy `SPEC.md`, `PLAN.md`, and `TASKS.md` artifact set. A pre-existing `SPEC.md` forces this path so legacy plans are never overwritten by INTENT.
4. After `TASKS.md` exists, Phase 8.4 may recommend `/z-plan-split`, `/z-sharpen`, or `/z-brainstorm` if the artifacts show too many tasks, question-heavy framing, or unsettled approaches. These are route recommendations only; the user must choose switch/continue/abandon and no command is auto-dispatched.
5. Phase 8 also writes `work-graph.json`, the initial append-only known-work DAG derived from `TASKS.md` (one node per task, `depends_on` from `**Depends on:**` lines, `level_hint` computed by DAG depth). This is the frontier `/z-execute` will grow, not a claimed-complete task tree.
6. `execution-strategy.md` is derived from `TASKS.md` + `work-graph.json` + validated `workstreams.json`; it now hard-fails Phase 8 if `work-graph.json` is missing.
7. Phase 8.5 writes `HANDOFF.md` after TASKS sanity and route checks; the handoff's primary-artifact list and machine `handoff.json` now include `work-graph.json` when present. Phase 8.6 then asks for exactly one next step: fresh-session `/z-execute`, audit-first `/z-audit-plan`, stop with handoff, or `/z-amend`.

## Execution model

1. Detect mode after `BASE` is bound: `SPEC.md` -> legacy; else `INTENT.md` -> intent; else halt.
2. In intent mode, freeze INTENT and persist the freeze commit in the archive.
3. Resolve companion artifacts (`intent-readthrough-flags.md`, `brainstorm-choice.json`, `execution-strategy.md`, `workstreams.json`, `work-graph.json`) via exact-name lookup, never by scanning archives for a fuzzy match.
4. Loop: dispatch `task-tree-generator` with `scheduler_mode: known_work_graph` and `work_graph_path` set, so it appends newly knowable nodes (with explicit `depends_on`) instead of assuming a single flat next-level batch; pass unmet checklist items, prior outcomes, level/depth hint, budget, and task id start. The generator may widen a ready frontier only when siblings have precise, disjoint `**Files:**` scope; if independence cannot be proven, it must defer, serialize, or mark the blocker (e.g. `status: "blocked"` with `depends_on`) instead of inventing parallel work.
5. Execute the current ready frontier via the existing per-task engine; no new task engine exists. Same-frontier INTENT parallelism is default-on only under the `/z-execute` safety preconditions: precise parseable file scope for every sibling, no `scope_unknown`, bounded/partitioned fan-out (`INTENT_PARALLEL_FANOUT_LIMIT`, currently 3), and per-task review diff isolation or serialized review capture.
6. Inject `intent_snapshot:`, `ledger_path:`, and (when present) `work_graph_path:` into every implementer/reviewer/retry prompt. Optional durable-tier paths (`kernel_path`, `invariants_path`, `style_path`) are forwarded when present.
7. Flush pending LEDGER content at frontier end, sync `work-graph.json` node status from TASKS.md task markers (append-only node identity, mutable status), checkpoint the done-set hash, evaluate acceptance, then either stop or advance the scheduler depth.

## Pipelined Track Boundary

The 2026-07-04 known-work-DAG redesign changed this from a purely future/docs-only contract to a partially-live one: `work-graph.json` is now a real, always-written artifact (`/z-plan` seeds it, `/z-execute` appends to it and syncs node status after every settled frontier). What did **not** change is the actual dispatch mechanism available to the current native hosts: `Agent()` calls remain synchronous, so `/z-execute` still drains an entire ready frontier through the existing per-task engine, flushes LEDGER/`.bfs_level_state`/work-graph status, runs coalesced remote verify, and evaluates acceptance before dispatching `task-tree-generator` again — it does not spawn a new ready node the instant a sibling in the same frontier returns.

The contract now explicitly permits true node-by-node refill (dispatch another ready node as soon as any track reaches a durable terminal state, without waiting for the whole frontier) **only** when the driver exposes a durable background handle or completion notification per subagent track. A host that only launches synchronous `Agent()` calls may still preserve correctness by falling back to drain-then-refill, but it must not report the run as "concurrently refilled" in telemetry when it only ever drained-and-refilled a full frontier. `handoff.json` schema is unchanged.

Any future pipelined scheduler must persist durable per-track state (`queued`, `prechecking`, `implementing`, `reviewing`, `retrying`, `halted`, `done`) plus a durable background handle for each subagent track. A new fresh-session boundary rule also applies: a ready node with `fresh_session_required: true` / `kind: "handoff_required"`, or a generator return of `HANDOFF_REQUIRED: true`, stops refilling, drains already-started tracks to a durable terminal/paused state, writes a checkpoint/handoff, and expects a fresh session to resume — this is distinct from the level-cap/budget halt.

## Config surface

- `workflow.planning_mode`: `intent` (default recommendation) or `full`; the visible mode gate records the actual per-run choice unless unattended/no-ask uses the recommendation.
- `workflow.intent_level`: `auto`, `quick`, `standard`, or `deep`; level flags override this and bypass the classifier.
- `workflow.intent_parallel_levels`: default `true`; attempts same-frontier INTENT parallelism only when `/z-execute` can prove precise file scope, no `scope_unknown`, bounded/partitioned fan-out, and isolated or serialized review capture. Set `false` to opt out and serialize each frontier.
- `workflow.intent_bfs_level_cap`: runtime-read guard; absent from DEFAULTS, so empty/None falls back to 6.
- `workflow.hermes_enabled`: gates old Hermes cross-cluster/parallel machinery; does not by itself enable intent parallelism.
- `INTENT_PARALLEL_FANOUT_LIMIT` (hardcoded, currently `3`, not a config key): shared cap used both for the ready-frontier dispatch batch and the `ready_window` value passed to `task-tree-generator` so it does not append an unbounded frontier.

## Gotchas

- `SPEC.md` presence is binary and wins forever for that slug; adding INTENT does not switch an existing legacy plan.
- `frozen_at: pending` is valid before execution; do not remove it.
- `stale_reason: amended-intent` in TASKS frontmatter means regenerate on next execute.
- `.bfs_level_state` stores the last completed scheduler depth and done-set hash; hash mismatch restarts from depth 0. In known-work-graph mode this is a resume/telemetry hint only — the real ready set is always recomputed from `work-graph.json` node statuses and dependencies.
- `evaluate_acceptance` treats unknown as unmet. A LEDGER citation without a cumulative diff is not enough.
- Cross-frontier parallelism is not supported for synchronous hosts; `intent_parallel_levels` is within-frontier only, and unsafe same-frontier batches serialize rather than falling back to arbitrary fan-out.
- `work-graph.json` node identity and `append_log[]` are append-only — never delete or rewrite existing nodes — but the `status` field IS mutable scheduler state, resynced by `/z-execute` after every settled frontier (`skills/z-execute/SKILL.md:1150`) from TASKS.md task markers. Do not read "append-only" as "immutable status."
- `execution-strategy.md` generation now hard-fails (`SystemExit`) if `work-graph.json` is missing after Phase 8's work-graph write — a new required-artifact dependency introduced 2026-07-04.
- `WORK_GRAPH_FILE` resolution in `/z-execute` mirrors the intent-conversation companion artifacts: exact-name lookup via `_resolve_exact_plan_artifact`, never by scanning archive directories for a fuzzy match, with a `$BASE/work-graph.json` fallback if the resolver returns empty.
- True node-by-node pipelined refill (no frontier drain) is contract-only until a driver exposes durable background handles per track; the current native hosts still drain-then-refill a full frontier. Clear checkpoints remain durable DAG settle points (all live tracks drained/paused, work-graph.json + TASKS.md + LEDGER.md flushed).
- The task-tree generator should widen a frontier only for siblings with precise disjoint file scope and an executor fan-out that can be capped or partitioned; missing, unparseable, overlapping, or unknown scope is a serialization/dependency-edge signal, not a wide-batch signal.
- `/z-plan` route checks and final gate options are non-auto-dispatch surfaces: they write route/handoff artifacts and ask the user, but they never invoke `/z-sharpen`, `/z-brainstorm`, `/z-audit-plan`, `/z-execute`, or `/z-amend` themselves.
- `HANDOFF.md` is produced after `TASKS.md` and `work-graph.json`; it is an index and summary for the next session, not a replacement contract.

## Memories

<!-- DO NOT EDIT this section by hand — regenerated from docs/llm/adaptive-intent.json by doc-updater. Use /z-suggest-memory to add or edit memories. -->

- **2026-06-29 correctness** ([incident:20260629T182649Z-review](#)) — When INTENT acceptance promises DAG/workstream metadata, generator failure must halt or surface clearly; prose fallback/||true silently erases the execution contract. _(tags: correctness, lossy-default)_
- **2026-06-29 correctness** ([incident:20260629T182649Z-review](#)) — In adaptive INTENT BFS, later task-tree generation must receive concern flags, brainstorm choice, execution strategy, and task-to-intent/workstream context before tasks are drafted. _(tags: api-boundary, correctness)_
- **2026-06-29 invariant** ([incident:20260629T200634Z-review](#)) — For adaptive INTENT execution, aggregate review is a computed gate: log required/not-required from realized task count, workstreams, high-risk flags, and cross-workstream criteria; do not replace it with unconditional final review. _(tags: correctness, observability)_
- **2026-06-29 gotcha** ([incident:20260629T200634Z-review](#)) — Load-bearing intent-conversation artifacts must be resolved through stable plan-root pointers or exact handoff references, never by scanning archives for the latest matching flags or brainstorm choice. _(tags: correctness, api-boundary)_
- **2026-06-29 invariant** ([incident:20260629T200634Z-review](#)) — The brainstorm ask gate needs a durable route/choice artifact with skipped, existing, and routed states, and later /z-plan resumes must consume that artifact deterministically before drafting INTENT.md. _(tags: correctness, api-boundary)_
