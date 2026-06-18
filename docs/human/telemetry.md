# Telemetry

> Last updated: 2026-05-27

All events are appended to `<base>/metrics.jsonl` via `scripts/log-event.sh`,
where `<base>` is the resolved artifact base — external by default
(`$XDG_STATE_HOME/z-harness/<repo-id>/`, e.g. `~/.local/state/z-harness/...`);
see the README for the `Z_HARNESS_EXTERNAL_DEFAULT` / `Z_HARNESS_BASE_DIR`
overrides, or run `/z-where` to print it.
Standard fields on every event: `ts`, `run`, `kind` (and `slug` when set). The
fields `prompt_chars`, `response_chars`, and `wall_ms` are optional — they
appear only on subagent-bracket events, not on lifecycle or gate events.

## Event kinds

### `/z-brainstorm`, `/z-map`, and `/z-research`

| Event | Emitted by |
|---|---|
| `brainstorm_run_start` | `/z-brainstorm` setup |
| `brainstorm_run_end` | `/z-brainstorm` Phase 4 |
| `research_run_start` | `/z-research` setup |
| `research_run_end` | `/z-research` Phase 6 |
| `ideator_failed` | `/z-brainstorm` Phase 2 (fields: `vendor`, `reason`) |
| `total_ideator_failure` | `/z-brainstorm` Phase 2 when all three ideators fail |
| `research_temptation` | `/z-map` (`commands/z-map.md`) when orchestrator drafts a recommendation it must not make (note: `commands/z-map.md` emits `map_temptation` for the same invariant) |
| `precontext_source_deleted` | `/z-plan` Setup step 10 freshness check (higher severity than stale-mtime) |
| `precontext_freshness_check_failed` | `/z-plan` Setup step 10 freshness check parse failure |
| `cost_gate_decision` | `/z-research` Phase 0 cost-confirmation gate |
| `explore_failure` | any command that dispatches an Explore subagent that does not return |

### `/z-plan-split` and tree-walking branch of `/z-implement-all`

| Event | Emitted by |
|---|---|
| `plan_split_run_start` | `/z-plan-split` Setup |
| `plan_split_run_end` | `/z-plan-split` finalize (every exit path; `status` distinguishes exit reason) |
| `cluster_proposed` | `/z-plan-split` Phase 1c (per proposed cluster) |
| `cluster_confirmed` | `/z-plan-split` Phase 1e (per confirmed cluster) |
| `cluster_planner_start` | `cluster-planner` subagent, first call |
| `cluster_planner_end` | `cluster-planner` subagent, last call (every exit path) |
| `cluster_failed` | `/z-plan-split` Phase 3 (per failed cluster; `failure_reason` field) |
| `cluster_decision_escalated` | `cluster-planner` Phase 2/3 when conservative-flagging rubric escalates |
| `cluster_files_inconsistent` | `/z-plan-split` Phase 4 when `FILES_TOUCHED` ↔ TASKS.md disagree |
| `total_cluster_failure` | `/z-plan-split` Phase 3 or Phase 4 when every cluster ends `failed` |
| `overlap_detected` | `/z-plan-split` Phase 4 (per overlapping path) |
| `overlap_index_rebuilt` | `/z-plan-split` Phase 4 after any post-Phase-3 cluster demotion |
| `shared_concerns_missing` | `/z-implement-all` Setup 2b when SHARED-CONCERNS.md is absent on a tree-rooted slug |
| `shared_concerns_unacknowledged` | `/z-implement-all` Setup 2b ack-gate (halt; no override) |
| `shared_concerns_ack_override` | `/z-implement-all` Setup 2b ack-gate when `--ack` was supplied |
| `manifest_frontmatter_inconsistent` | `/z-implement-all` Setup 2b when frontmatter counts disagree with the table |
| `manifest_run_order_invalid` | `/z-implement-all` Setup 2b when run order doesn't bijectively match the table |
| `tree_depth_exceeded` | `/z-implement-all` Setup 2b when a nested MANIFEST.md is found inside the tree |
| `partial_tree_blocked` | `/z-implement-all` Setup 2b partial-tree gate (halt; no `--force-partial`) |
| `partial_tree_force_override` | `/z-implement-all` Setup 2b partial-tree gate when `--force-partial` was supplied |
| `anti_nesting_violation` | `cluster-planner` Phase 0a when an ancestor MANIFEST.md is detected |
| `cluster_not_ready` | `/z-implement-all` Setup 2b cluster-readiness gate |

### Compaction breakpoints

| Event | Payload schema | Emitted by |
|---|---|---|
| `compaction_pause` | `{trigger, detail}` — `trigger` is one of `"task_count"`, `"wall_time"`, or `"pre_consult"`; `detail` carries trigger-specific fields | `/z-implement-all` batch-settle; `/z-review-all` Phase 3.7; `/z-maintain-docs --audit` pre-consult breakpoint |

### Config

| Event | Emitted by |
|---|---|
| `config_resolved` | `scripts/config.py export-env` once per `$Z_HARNESS_RUN` (see [config.md](config.md)) |

---

## Compaction policy

Long `/z-implement-all` runs and cross-LLM consult phases in `/z-review-all`
and `/z-maintain-docs --audit` accumulate significant orchestrator context. The
compaction policy inserts deterministic breakpoints at the highest-context-pressure
boundaries.

### `/z-implement-all` — task-count and wall-time triggers

Two env vars control when a breakpoint fires (see [environment-knobs.md](environment-knobs.md)):

| Env var | Default | Meaning |
|---|---|---|
| `Z_IMPLEMENT_PAUSE_TASKS` | `5` | Pause after this many `[x]` completions since last pause |
| `Z_IMPLEMENT_PAUSE_MINUTES` | `30` | Pause after this many wall-clock minutes since last pause |

The trigger fires **at the end of each batch-settle**, strictly after: all
in-flight tasks reach terminal status → TASKS.md atomic write → `batch_done`
event → halt-flush resolved. Only `[x]` completions count toward
`Z_IMPLEMENT_PAUSE_TASKS`; retries and rollbacks do not.

On trigger: a `compaction_pause` event is emitted, a push notification fires,
and the loop exits cleanly. Re-invoke `/z-implement-all` to resume from TASKS.md.

### `/z-review-all` and `/z-maintain-docs --audit` — pre-consult breakpoints

Both commands insert an unconditional breakpoint before the cross-LLM consultant
batch dispatches. You are shown an `AskUserQuestion` with two options:

- **Pause for /clear** — exit cleanly; no state written. Re-invoke to continue.
- **Proceed now** — write a slug-scoped state file and continue into the consult phase.

### Why `/clear` over `/compact`

`/clear` is the recommended action at every compaction breakpoint. The harness's
durable state lives entirely in TASKS.md (and slug-scoped state files) — there
is no cross-task state in orchestrator memory. Clearing reclaims more context
than `/compact` with no safety loss.

Use `/compact` only when you need to preserve chat history for debugging a
specific task failure.
