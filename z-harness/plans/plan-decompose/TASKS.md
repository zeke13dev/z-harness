# TASKS — plan-decompose (`/z-plan-split`)

## Phase A — Foundations

- [x] **T001 — Create `cluster-planner` agent**
  - **Files:** `/Users/zeke/dev/z-harness/agents/cluster-planner.md` (new)
  - **Depends:** none
  - **Acceptance:**
    - Agent frontmatter: `model: sonnet`, `tools: <reasonable for sub-/z-plan — Read, Write, Edit, Bash, Grep, Glob, Agent, AskUserQuestion>`.
    - 6-phase contract from SPEC §"`cluster-planner` agent" implemented prose-completely: Phase 0 (anti-self-nesting + premise check), Phase 1 (exploration via doc-fetcher iff INDEX.json exists, else direct Read/Grep ≤10 files, NO Explore subagent), Phase 2 (identify ≤3 decisions, halt with `STATUS: decision_needed` if 4+ surface), Phase 3 (resolution with conservative-flagging rubric verbatim from SPEC: triggers a/b/c/d/e/f), Phase 4 (write SPEC.md + PLAN.md compressed — no consult section, no plan-review), Phase 5 (write TASKS.md with `complexity-classifier` subagent for stamping, same as /z-plan Phase 8), Phase 6 (return).
    - Conservative-flagging rubric reproduced verbatim with the 6 trigger categories. Explicit examples for each trigger (e.g., trigger (c): "adding a column to `schema.sql`" → escalate).
    - Structured `decision_needed` return payload format documented: DECISION_ID, QUESTION, OPTIONS, RECOMMENDED_OPTION, IMPACT, AFFECTED_FILES.
    - Re-spawn semantics: on re-invocation with `RESOLVED_DECISION:` block in prompt, resume from Phase 4 (skip Phase 0-3).
    - Return shape: `STATUS: ok | decision_needed | spec_problem | unable_to_complete | anti_nesting_violation`, plus `CLUSTER_ID`, `TASKS_COUNT`, `DECISIONS_RESOLVED`, `DECISIONS_ESCALATED` (always 0 on STATUS: ok), `FILES_TOUCHED` (JSON array of workspace-relative paths).
    - Telemetry: log `cluster_planner_start` at top, `cluster_planner_end` at bottom via `${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-phase.sh`.
    - Anti-nesting guard: walk slug-dir ancestors looking for `MANIFEST.md`; if found return `STATUS: anti_nesting_violation` with `ancestor_manifest_path` populated.
    - "No Explore subagent" is explicit; comment cites cost discipline.
  - **DOCS:** none (z-harness has no `docs/llm/INDEX.json`)
  - **Complexity:** high

## Phase B — `/z-plan-split` command

- [x] **T002 — Create `/z-plan-split` command + skill mirror**
  - **Files:**
    - `/Users/zeke/dev/z-harness/commands/z-plan-split.md` (new)
    - `/Users/zeke/dev/z-harness/skills/z-plan-split/SKILL.md` (new)
  - **Depends:** T001
  - **Acceptance:**
    - Both files exist; `diff commands/z-plan-split.md skills/z-plan-split/SKILL.md` produces zero output (matches the z-plan / z-brainstorm / z-research mirror precedent — frontmatter is identical).
    - Setup phase: slug derivation (auto OR `--slug=<slug>` OR `--clusters="a,b,c"`); existing-slug-dir prompt (overwrite/abort, drop "append"); Z_HARNESS_SLUG export; RUN id; mkdir; version stamp; `plan_split_run_start` event with `topic_chars`.
    - Phase 1 (Cluster proposal): main thread (no subagent) reads topic + doc-fetcher synthesis (iff INDEX.json exists). Propose 2-6 narrow scopes in kebab-case. Hard limits: refuse <2 clusters (recommend /z-plan); refuse >6 (recommend topic narrowing). Write `archive/$RUN/proposed-clusters.md`. AskUserQuestion with previews (name + scope per cluster). Options: approve as proposed / edit (free-text) / abandon. Write `archive/$RUN/confirmed-clusters.md` post-approval.
    - Phase 2 (Parallel dispatch): ONE message with N parallel `Agent(subagent_type="cluster-planner", ...)` calls. Each receives identical root-topic context + sibling-cluster list. Each gets its own `cluster-id`, `cluster-name`, `cluster-scope`, `output-path=z-harness/<root>/<cluster-id>/`.
    - Phase 3 (Collect returns): parse each leaf's return per the STATUS branching from SPEC §"Phase 3 — Collect leaf returns". STATUS: ok → mark `ready` in MANIFEST + `attempts: 1`. STATUS: decision_needed → halt only that leaf, structured AskUserQuestion using OPTIONS/RECOMMENDED_OPTION, re-spawn with RESOLVED_DECISION block, increment attempts, others continue. STATUS: spec_problem / anti_nesting_violation / unable_to_complete → mark `failed`. If all fail → halt with `total_cluster_failure`.
    - Phase 4 (Reconciliation): parse each cluster's TASKS.md `**Files:**` lines (canonical) AND validate against returned FILES_TOUCHED — disagreement → mark cluster `failed` + log `cluster_files_inconsistent`. Path normalization: workspace-relative, strip `./`, collapse `.`/`..`, normalize separator, reject escapes. Apply cascading severity heuristics (high > medium > low) per SPEC §"SHARED-CONCERNS.md schema". Files touched by exactly 1 cluster excluded.
    - Phase 5 (Write artifacts): write `SHARED-CONCERNS.md` with frontmatter (`acknowledged: false`, `overlap_count`, `partial_tree: <bool>`). Write `MANIFEST.md` with cluster table, run-order, attempts tracking. Log `plan_split_run_end` with full payload. Push-notify with next-step recommendation.
    - Per-phase telemetry pattern from /z-plan (T0 + phase_end wall_ms + user_wait bracketing).
    - Negative-case acceptance: <2 clusters → exit with recommendation; >6 clusters → refuse with explanation; all clusters fail → `total_cluster_failure` event + halt; 1 cluster fails → continue + `partial_tree: true` + push-notify.
  - **DOCS:** none
  - **Complexity:** high

## Phase C — `/z-implement-all` extension

- [x] **T003 — Extend `/z-implement-all` for nested-slug discovery**
  - **Files:**
    - `/Users/zeke/dev/z-harness/commands/z-implement-all.md`
    - `/Users/zeke/dev/z-harness/skills/z-implement-all/SKILL.md`
  - **Depends:** T002 (needs the MANIFEST.md schema to be defined)
  - **Acceptance:**
    - Setup step 2 (slug discovery) is extended. When enumerating subdirs of `z-harness/`, for each `<slug>/` check if `<slug>/MANIFEST.md` exists.
    - If MANIFEST.md exists → "tree-rooted plan." Validate (in order):
      1. Every cluster path in MANIFEST has a finalized `TASKS.md` (parses cleanly, ≥1 task block). Any cluster with `status: planning` or `status: failed` → halt with `cluster_not_ready` event.
      2. No nested MANIFEST.md anywhere reachable: `find <root>/*/ -name MANIFEST.md` must return empty (excluding root MANIFEST). Any found → halt with `tree_depth_exceeded` event, payload `{nested_paths: [...]}`.
      3. `<root>/SHARED-CONCERNS.md` exists. If `overlap_count > 0` AND `acknowledged != true` → halt with `shared_concerns_unacknowledged` event. Override via `--ack` flag.
      4. If `partial_tree: true` in SHARED-CONCERNS → halt with `partial_tree_blocked` event naming failed clusters. Override via `--force-partial` flag.
    - On all validations passing: expand the slug into a sequence of cluster paths in MANIFEST run-order. Iterate clusters **sequentially**. Within each cluster, use the existing N=3 parallel-batching as today (intra-cluster parallelism honored; cross-cluster parallelism is v2).
    - Single-slug (legacy) behavior unchanged. Multi-slug discovery still works (e.g. user has both legacy slugs and tree-rooted slugs coexisting).
    - `--ack` and `--force-partial` flags documented in command help text.
    - Negative-case acceptance: tree with one failed cluster → halt unless --force-partial; tree with unacknowledged SHARED-CONCERNS → halt unless --ack; nested MANIFEST → tree_depth_exceeded halt; mixed legacy + tree slugs work in same /z-implement-all run.
    - Mirror byte-identity preserved: `diff commands/z-implement-all.md skills/z-implement-all/SKILL.md` matches the existing tolerance (only frontmatter + blank-line differences, OR zero diff matching the /z-plan precedent).
  - **DOCS:** none
  - **Complexity:** medium

## Phase D — Documentation

- [x] **T004 — Update README with `/z-plan-split` documentation**
  - **Files:** `/Users/zeke/dev/z-harness/README.md`
  - **Depends:** T002, T003
  - **Acceptance:**
    - New section documenting `/z-plan-split`: purpose, when to use (topic feels ≥40 tasks across natural seams), cost target (rough rule: cheaper than full /z-plan if user actually needed N narrow plans; otherwise more expensive — opt-in).
    - Example chain: `/z-research → /z-brainstorm → /z-plan-split → /z-implement-all` for a murky multi-component problem.
    - New event types listed: `plan_split_run_start/end`, `cluster_proposed/confirmed/planner_start/end/failed/decision_escalated/files_inconsistent`, `total_cluster_failure`, `overlap_detected`, `shared_concerns_acknowledged/unacknowledged`, `tree_depth_exceeded`, `partial_tree_blocked`, `anti_nesting_violation`, `cluster_not_ready`.
    - Subagents section gains: `cluster-planner` row (model: sonnet; runs a narrow sub-/z-plan for one cluster of a /z-plan-split tree).
    - `/z-implement-all` description updated to mention nested-tree walking + `--ack` and `--force-partial` flags.
    - Known v1 limitations: no cross-cluster task parallelism; path-only overlap detection (no semantic); no `--from-audit`/`--from-brainstorm` input chains; one-level recursion cap.
    - Style: match existing README voice. Don't reorganize unrelated sections.
  - **DOCS:** none
  - **Complexity:** low
