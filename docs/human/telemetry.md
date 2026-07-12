# Telemetry

> Last updated: 2026-06-28

All events are appended to `<base>/metrics.jsonl` via `scripts/log-event.sh`,
where `<base>` is the resolved artifact base — external by default
(`$XDG_STATE_HOME/z-harness/<repo-id>/`, e.g. `~/.local/state/z-harness/...`);
see the README for the `Z_HARNESS_EXTERNAL_DEFAULT` / `Z_HARNESS_BASE_DIR`
overrides, or run `/z-stats` to print it.
Standard fields on every event: `ts`, `run`, `kind` (and `slug` when set). The
fields `prompt_chars`, `response_chars`, and `wall_ms` are optional — they
appear only on subagent-bracket events, not on lifecycle or gate events.

## Event kinds

### `/z-brainstorm`, `/z-explore --depth=deep`, and `/z-research`

| Event | Emitted by |
|---|---|
| `brainstorm_run_start` | `/z-brainstorm` setup |
| `brainstorm_run_end` | `/z-brainstorm` Phase 4 |
| `research_run_start` | `/z-research` setup |
| `research_run_end` | `/z-research` Phase 6 |
| `ideator_failed` | `/z-brainstorm` Phase 2 (fields: `vendor`, `reason`) |
| `total_ideator_failure` | `/z-brainstorm` Phase 2 when all three ideators fail |
| `explore_run_start` | `/z-explore --depth=deep` setup for current terrain mapping; the same event kind is also used by other `/z-explore` depths and records `depth` |
| `explore_run_end` | `/z-explore --depth=deep` Phase 5 finalize; deep mode writes the `MAP.md` artifact and records `map_written`, `citation_count`, `gap_count`, and `critique_status` |
| `research_subcommand_complete` | `/z-research` when the current `z-explore` or `z-brainstorm` subcommand completes, is reused, or is skipped |
| `phase_end` | `/z-explore --depth=deep` and `/z-research` phase checkpoints (fields: `phase`, `name`, `wall_ms`, `user_wait_ms`) |
| `user_wait_start` / `user_wait_end` | `/z-explore --depth=deep` AskUser gates, including cost and collision decisions |
| `research_temptation` / `map_temptation` | Legacy compatibility telemetry for older terrain-mapping archives/docs only; current `/z-explore --depth=deep` telemetry uses `explore_run_*` plus `MAP.md` artifact fields |
| `precontext_source_deleted` | `/z-plan` Setup step 10 freshness check (higher severity than stale-mtime) |
| `precontext_freshness_check_failed` | `/z-plan` Setup step 10 freshness check parse failure |
| `cost_gate_decision` | `/z-research` Phase 0 cost-confirmation gate; `/z-explore --depth=deep` cost gate |
| `explore_failure` | `/z-explore --depth=deep` or any command that dispatches an Explore subagent that does not return |

The legacy terrain-mapping command is not a current telemetry producer. Mentions of `map_*` event names
above are legacy compatibility only; `MAP.md` is the deep terrain artifact written
by `/z-explore --depth=deep`.

### `/z-plan-split` and tree-walking branch of `/z-execute`

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
| `shared_concerns_missing` | `/z-execute` Setup 2b when SHARED-CONCERNS.md is absent on a tree-rooted slug |
| `shared_concerns_unacknowledged` | `/z-execute` Setup 2b ack-gate (halt; no override) |
| `shared_concerns_ack_override` | `/z-execute` Setup 2b ack-gate when `--ack` was supplied |
| `manifest_frontmatter_inconsistent` | `/z-execute` Setup 2b when frontmatter counts disagree with the table |
| `manifest_run_order_invalid` | `/z-execute` Setup 2b when run order doesn't bijectively match the table |
| `tree_depth_exceeded` | `/z-execute` Setup 2b when a nested MANIFEST.md is found inside the tree |
| `partial_tree_blocked` | `/z-execute` Setup 2b partial-tree gate (halt; no `--force-partial`) |
| `partial_tree_force_override` | `/z-execute` Setup 2b partial-tree gate when `--force-partial` was supplied |
| `anti_nesting_violation` | `cluster-planner` Phase 0a when an ancestor MANIFEST.md is detected |
| `cluster_not_ready` | `/z-execute` Setup 2b cluster-readiness gate |

### Clear checkpoints

| Event | Payload schema | Emitted by |
|---|---|---|
| `compaction_pause` | `{trigger, detail}` — `trigger` is one of `"task_count"`, `"wall_time"`, or `"pre_consult"`; `detail` carries trigger-specific fields | `/z-execute` batch-settle; `/z-review-all` Phase 3.7; `/z-maintain-docs --audit` pre-consult breakpoint |
| `clear_checkpoint_written` | `{handoff_path, session_path, status, resume_command, next_pending, producer, consumer}` | `scripts/write-clear-checkpoint.sh`; watcher signal for OMP/Hermes/MCP |

### Config

| Event | Emitted by |
|---|---|
| `config_resolved` | `scripts/config.py export-env` once per `$Z_HARNESS_RUN` (see [config.md](config.md)) |

---

## Clear checkpoint policy

Long `/z-execute` runs and cross-LLM consult phases in `/z-review-all`
and `/z-maintain-docs --audit` accumulate significant orchestrator context. The
clear checkpoint policy inserts deterministic breakpoints at the highest-context-pressure
boundaries and writes watcher-readable resume artifacts.

### `/z-execute` — task-count and wall-time triggers

Two env vars control when a breakpoint fires (see [environment-knobs.md](environment-knobs.md)):

| Env var | Default | Meaning |
|---|---|---|
| `Z_IMPLEMENT_PAUSE_TASKS` | `5` | Pause after this many `[x]` completions since last pause |
| `Z_IMPLEMENT_PAUSE_MINUTES` | `30` | Pause after this many wall-clock minutes since last pause |

The trigger fires **at the end of each batch-settle**, strictly after: all
in-flight tasks reach terminal status → TASKS.md atomic write → `batch_done`
event → halt-flush resolved. Only `[x]` completions count toward
`Z_IMPLEMENT_PAUSE_TASKS`; retries and rollbacks do not.

On trigger: a `compaction_pause` compatibility event is emitted, `write-clear-checkpoint.sh` writes `handoff.json`, `clear_checkpoint_written` is emitted for watchers, a push notification fires, and the loop exits cleanly. Re-invoke `/z-execute` or let a watcher resume from the handoff.

### `/z-review-all` and `/z-maintain-docs --audit` — pre-consult breakpoints

Both commands insert an unconditional checkpoint before the cross-LLM consultant
batch dispatches. The target shape is checkpoint-and-exit: write enough state for
the next invocation or watcher to resume, then clear before the heavy consult.
Older prompt text may still call this a compaction breakpoint; the durable event
to watch is `clear_checkpoint_written`.

### Why `/clear` over `/compact`

`/clear` is the recommended action at every checkpoint. The harness's
durable state lives in TASKS.md, SESSION.md, handoff.json, and slug-scoped state
files — there is no cross-task state that must stay only in orchestrator memory.
Clearing reclaims more context than `/compact` with no safety loss when a
checkpoint exists.
