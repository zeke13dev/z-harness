# Scripts

> Last updated: 2026-06-02
> Covers source: scripts/extract-dismissals.py, scripts/log-event.sh, scripts/log-phase.sh, scripts/regenerate-memories-flat.py, scripts/remote-sandbox-sync.sh, scripts/run-memory-review.sh, scripts/version.sh, scripts/config.py, scripts/config.sh, scripts/test_config.py, scripts/test_log_phase.sh, scripts/persona-stats.py, scripts/active-plan-registry.py

## Overview

The scripts concept covers the shell and Python utility scripts that form the operational backbone of the z-harness pipeline. The core cohort handles structured event telemetry (`log-event.sh` / `log-phase.sh`), memory document regeneration (`regenerate-memories-flat.py`), plugin version introspection (`version.sh`), memory-review lifecycle gating (`run-memory-review.sh`), MR-review dismissal signature extraction (`extract-dismissals.py`), rsync-based remote sandbox synchronization (`remote-sandbox-sync.sh`), layered TOML configuration and workflow-question resolution (`config.py` / `config.sh`), run terminal-state classification (`run-status.sh`), TASKS.md normalization (`normalize-task-state.sh`), AskUserQuestion callsite auditing (`lint-askuser.sh`), overnight preflight collision detection (`overnight-preflight.sh`), morning-report generation (`morning-report.py`), and the local preflight harness (`preflight.sh`). Test scripts (`test_config.py`, `test_log_phase.sh`) provide regression coverage. `log-event.sh` routes all base-path resolution through `z_harness_base()` from `plan-path.sh`, which implements a 5-tier fallback chain and supports the `Z_HARNESS_BASE_DIR` external-base redirect required for benchmark task isolation.

`scripts/active-plan-registry.py` is a lockless per-run active-plan registry. Each run owns exactly one record at `<active_plans_dir>/<run-id>.json`; all writes are atomic (`tmpfile + os.replace`) and no global lock is taken. Subcommands: `session-id` (derive or echo a stable session token), `register` (write schema-v1 record, emits `plan_registered`), `heartbeat` (update `last_heartbeat`/phase/task — non-fatal), `update-scope` (merge a scope array of `{path, confidence, reason}` items — non-fatal), `list [--json]` (scan active dir, skip torn files), `overlaps [--strict] [--scope-json]` (compute path intersection against live peers; exit 0=none, 10=advisory, 20=blocking), `reap` (conservative reaper: delete on dead-local-pid or 2× stale margin; mark `status:stale` on 1× remote stale), `deregister [--status complete|aborted]` (atomic unlink, emits `plan_deregistered` — non-fatal). The registry is consumed by `/z-plan`, `/z-audit`, `/z-do`, `/z-brainstorm`, `/z-debug`, `/z-where`, `/z-stats`, and `migrate-plan-layout.sh`. The `Z_HARNESS_REGISTRY_ENABLED=0` env var disables all coordination writes (mutating subcommands become silent no-ops); non-mutating reads (`list`, `session-id`) are always permitted.

`scripts/persona-stats.py` is a read-only analysis tool for the persona-rotation experiment. It reads `<base>/metrics.jsonl` (the resolved artifact base), joins `persona_random_selected` draw events to `persona_attempt_outcome` terminal events by `attempt_id` (with `draw_id` as a secondary key), and groups by `persona_id × role × complexity_tier`. Within each stratum it computes outcome metrics (`review_cycles`, `retries`, `blocker_count`, `wall_ms`, `diff_size`, `completion_rate`) and a delta versus the baseline — baseline resolution order: `no-persona` (primary null baseline) within the stratum, then `boring-anchor` (secondary bland control), then `None`. `fallback_empty_pool` draws are quarantined to a separate section and never folded into any persona's stats or baseline. Reviewer rows are derived from `persona_bound` events and segmented by `reviewer_participant`. Supports `--json`, `--min-diff-size N`, `--since DATE`, and `--include-unknown-run`.

A second cohort — added by the notion-followup-sink plan — implements the follow-up sink subsystem: a persistent, durable queue of actionable work items discovered during harness runs. It consists of eleven scripts with single-responsibility contracts. `sink-lock.sh` provides a generic per-entry `fcntl.flock` + heartbeat + stale-takeover primitive. `sink-add.sh` / `sink-add-helpers.py` is the writer primitive callable by any skill. `sink-claim.sh` / `sink-claim-helpers.py` implements an atomic `open→running` claim with the mandatory lock-ordering invariant (per-entry lock first, then global). `sink-status-set.sh` / `sink-status-set-impl.py` drives the seven-state machine. `sink-view-rebuild.sh` / `sink-view-reducer.py` replay `index.jsonl` into a materialized `index.view.json` via atomic rename. `sink-audit-validate.py` runs an 11-point check before a `done` transition. `sink-auto-close-check.py` gates the `auto_closed_low_risk` completion mode. `notion-push.py` performs a one-way idempotent push to Notion. `followup-reconcile-notion.sh` / `followup-reconcile-notion-impl.py` sweep all `notion_sync_pending` entries and re-attempt push. `parse-followups-block.py` tolerantly parses the `**FOLLOWUPS:**` fenced JSON block emitted by reviewers. `validate-followup-schemas.sh` runs JSON Schema validation assertions.

## Key entry points

- `scripts/log-event.sh:1` — `log-event.sh` — Appends a structured JSON event line to `<run>/events.jsonl` and the repo-wide `z-harness/metrics.jsonl`; resolves the artifact base via `z_harness_base()` (5-tier fallback from `plan-path.sh`); uses `flock` for concurrent-safe appends; supports mid-flight legacy run detection and `Z_HARNESS_BASE_DIR` external-base redirect.
- `scripts/log-phase.sh:1` — `log-phase.sh` — Sugar layer over `log-event.sh`; supports three modes: `start` (emits `<phase>_start`, returns an opaque timing token), `end` (emits `<phase>_end` with `wall_ms` merged in), and `wrap` (wraps an arbitrary command end-to-end and captures its exit code); anomaly detection via `check_wall_ms`.
- `scripts/log-phase.sh:71` — `check_wall_ms` — Anomaly guard: emits a `telemetry_anomaly` event and returns exit code 1 (suppressing the bogus `*_end` event) when `wall_ms > 604_800_000 ms` (7-day threshold) or when `wall_ms < 0` (clock skew / NTP jump).
- `scripts/regenerate-memories-flat.py:1` — `regenerate-memories-flat.py` — Scans all `docs/llm/*.json` files (excluding `INDEX.json`), extracts `memories[]` entries, sorts them by slug ascending then date descending, and writes `docs/llm/MEMORIES-FLAT.md` atomically via a temp-file rename.
- `scripts/version.sh:1` — `version.sh` — Prints a single-line JSON blob with the plugin's git short-SHA, dirty flag, branch, and optional tag; resolves plugin root via `Z_HARNESS_PLUGIN_ROOT`, `ANTIGRAVITY_PLUGIN_ROOT`, `CLAUDE_PLUGIN_ROOT`, or script-relative walk.
- `scripts/run-memory-review.sh:1` — `run-memory-review.sh` — Gate script called by `/z-implement-all`, `/z-review-all`, and `/z-debug`; accepts `<RUN> <parent_command>`; evaluates skip conditions using a 4-state terminal taxonomy; writes a truncated cumulative diff to the run archive and prints artifact paths on stdout.
- `scripts/extract-dismissals.py:480` — `main` — CLI entry point; extracts dismissed MR-review or plan-style-audit finding signatures from consecutive archived run pairs; supports `--global` and `--filename`; outputs `{"signatures": [...], "n_runs_scanned": N}`.
- `scripts/extract-dismissals.py:384` — `extract_dismissals_from_runs` — Core pairwise algorithm: compares R_i snapshot against R_{i+1}'s `.previous-*` user-edited copy.
- `scripts/remote-sandbox-sync.sh:1` — `remote-sandbox-sync.sh` — Rsync the local working tree to a per-(slug, task-id) remote sandbox using a two-level layout: a shared warm base at `~/dev/qt-bot-sandbox/<slug>/base/` (seeded once per slug with atomic mkdir-based locking) and a per-task overlay at `~/dev/qt-bot-sandbox/<slug>/<task-id>/` linked via `--link-dest`.
- `scripts/remote-sandbox-sync.sh:105` — `seed_base` — Acquires remote lock via `mkdir`, seeds the shared base via rsync, writes a `.base-ready` marker with the local HEAD SHA; losers poll up to 600s.
- `scripts/config.py:1` — `config.py` — Layered TOML config loader; subcommands: `get`, `export-env`, `ensure-defaults`, `explain`, `should-notify`, `list-question-ids`, `resolve-question`, `check-no-ask`, `set`, `migrate`, `inspect-all`; `QUESTION_IDS` registry + `RESULT_MAP`; `[followup]` section (9 keys + denylist); startup guards at module load.
- `scripts/config.py:204` — `_run_startup_guards` — Module-load guard: asserts every `QUESTION_IDS` key exists in `VALIDATORS`, has a non-null `skill_default`, and every `RESULT_MAP` `(question_id, choice)` references a known question_id and valid choice; exits 2 on any violation.
- `scripts/config.py:811` — `cmd_list_question_ids` — Prints sorted JSON array of registered question IDs.
- `scripts/config.py:1513` — `cmd_resolve_question` — Returns a JSON resolver envelope `{result, default, source, rule_id, strength, reason, sources}`; consults 4-layer config then `routing-preference` memory entries; honors `Z_HARNESS_ASK_ALL`, `Z_HARNESS_NO_ASK`, and `Z_HARNESS_EXPLAIN_RESOLUTION`.
- `scripts/config.py:1636` — `cmd_check_no_ask` — Returns JSON `{result: halt|proceed, question_id, rule_id}`; gate for overnight mode; unregistered qids always halt with `unknown_ask_blocked` event.
- `scripts/config.py:1842` — `cmd_set` — Atomic read-modify-write of a config key; validates key+value before writing; exits 2 on validation failure, 4 on I/O error.
- `scripts/config.sh:1` — `config.sh` — Thin shell wrapper: `exec python3 scripts/config.py "$@"`.
- `scripts/active-plan-registry.py:1` — `active-plan-registry.py` — Lockless per-run active-plan registry; 8 subcommands (session-id, register, heartbeat, update-scope, list, overlaps, reap, deregister); all writes are atomic; no global lock; resolves active_plans_dir via plan-path.sh; `Z_HARNESS_REGISTRY_ENABLED=0` silences all coordination writes.
- `scripts/active-plan-registry.py:389` — `cmd_session_id` — Prints a stable session-id token: echoes `Z_HARNESS_SESSION_ID` if set, otherwise derives `<ppid>-<start_epoch>` (Linux /proc) or `<ppid>-<epoch>` (macOS fallback); always exits 0.
- `scripts/active-plan-registry.py:408` — `cmd_register` — Writes schema-v1 record atomically; validates run-id as safe basename; exits 3 on failure (LOUD — callers must gate on this); emits `plan_registered`.
- `scripts/active-plan-registry.py:455` — `cmd_heartbeat` — Updates `last_heartbeat`/phase/current_task; non-fatal; if record is absent, emits `registry_error(reason:missing_record)` and returns 0 (no-op, does NOT fabricate zombie records).
- `scripts/active-plan-registry.py:511` — `cmd_update_scope` — Merges scope array `[{path, confidence, reason}]` into record; non-fatal; self-logs `registry_error` on any internal error.
- `scripts/active-plan-registry.py:700` — `cmd_overlaps` — Computes path intersection of caller's scope against all other live records; exit 0=no overlap, 10=advisory, 20=blocking (strict + explicit×explicit); same run-id or session-id is skipped; stale peers included but marked non-blocking; emits `scope_overlap_detected` or `active_plan_scan_complete`.
- `scripts/active-plan-registry.py:889` — `cmd_reap` — Conservative reaper; deletes on dead-local-pid (a) or 2× stale margin (b); marks `status:stale` on 1× threshold for remote/unknown hosts (c); `FileNotFoundError` on unlink is benign; non-fatal overall.
- `scripts/active-plan-registry.py:1065` — `main` — Argument parser dispatch; checks `Z_HARNESS_REGISTRY_ENABLED=0` before mutating subcommands.
- `scripts/persona-stats.py:1` — `persona-stats.py` — Read-only analysis for persona-rotation experiment; joins `persona_random_selected` draw events to `persona_attempt_outcome` by `attempt_id`; groups by `persona_id × role × complexity_tier`; baseline resolution: `no-persona` first, `boring-anchor` second, `None` third; reviewer rows from `persona_bound`; quarantines `fallback_empty_pool` draws; supports `--json`, `--min-diff-size`, `--since`, `--include-unknown-run`.
- `scripts/persona-stats.py:69` — `NO_PERSONA` — Constant `'no-persona'`; primary null baseline persona_id for delta computation.
- `scripts/persona-stats.py:70` — `CONTROL_PERSONA` — Constant `'boring-anchor'`; secondary bland control baseline.
- `scripts/persona-stats.py:75` — `NUMERIC_METRICS` — Tuple `('review_cycles', 'retries', 'blocker_count', 'wall_ms', 'diff_size')`; aggregated (mean) per group.
- `scripts/persona-stats.py:78` — `OUTCOME_KIND` — Constant `'persona_attempt_outcome'`; the terminal event kind joined against draw events.
- `scripts/run-status.sh:1` — `run-status.sh` — Classifies terminal state as `clean | halted | errored | unknown`; subcommands: `classify`, `last-event`.
- `scripts/run-status.sh:198` — `classify_by_kind` — Core classifier: matches event kind against allowlists and `*_error/fatal` pattern.
- `scripts/run-status.sh:250` — `cmd_classify` — Implement-all special case: requires `implement_end|compaction_pause` as last event AND all TASKS.md checkboxes `[x]|[~]`.
- `scripts/normalize-task-state.sh:1` — `normalize-task-state.sh` — Resets `- [~]` in-progress markers to `- [ ]` in `TASKS.md`; atomic rename; always exits 0; `--self-test` mode.
- `scripts/lint-askuser.sh:1` — `lint-askuser.sh` — Audits `AskUserQuestion` callsites; tags `REGISTERED` or `UNREGISTERED` at file level; `--strict` exits 1 on unregistered.
- `scripts/overnight-preflight.sh:1` — `overnight-preflight.sh` — Phase-0 preflight for `/z-overnight`; `check-collisions --chain <steps> --base <dir>`; exits 0 if safe, emits `slug_collision_halt` and exits 1 on collision; `--self-test` runs 8 assertions.
- `scripts/overnight-preflight.sh:233` — `cmd_check_collisions` — SPEC C13: collision when first chain step is `plan|research` AND `<base>/PLAN.md` exists.
- `scripts/morning-report.py:427` — `cmd_generate` — Locates latest overnight run dir, loads state/events, writes `MORNING_REPORT.md` atomically; exits 1 on I/O error.
- `scripts/morning-report.py:376` — `generate_report` — Assembles five sections: chain summary (HEAD SHA mismatch banner), phase results table, unilateral decisions table, test outcomes, recommended next action.
- `scripts/morning-report.py:518` — `cmd_self_test` — Golden-file comparison against fixtures in `z-harness/overnight-run/tests/morning-report-fixtures/`.
- `scripts/preflight.sh:1` — `preflight.sh` — Local pre-commit/pre-PR harness; runs `lint-askuser.sh --strict`; maps exit 1 to advisory warning; propagates exit 2+ as hard failures.
- `scripts/test_config.py:1` — `test_config.py` — End-to-end smoke-test suite for `config.py`; 18+ test classes with hermetic `XDG_CONFIG_HOME` temp dirs.
- `scripts/test_log_phase.sh:1` — `test_log_phase.sh` — Bash regression harness for `log-phase.sh`; 4 TEST groups, 21 assertions.
- `scripts/sink-lock.sh:1` — `sink-lock.sh` — Generic per-entry `fcntl.flock` + heartbeat + stale-takeover primitive; subcommands: `acquire`, `heartbeat`, `release`, `check-stale`; exit 0=acquired, 1=contention, 2=stale-takeover, 3=corrupt.
- `scripts/sink-lock.sh:149` — `cmd_acquire` — Forks a background daemon that holds `LOCK_EX|LOCK_NB` on a `.flock` sentinel; daemon's own PID (not caller's) is recorded in JSON. Stale-takeover (exit 2) if PID dead or heartbeat > TTL.
- `scripts/sink-add.sh:1` — `sink-add.sh` — Writer primitive for the follow-up sink; delegates to `sink-add-helpers.py`. Exit codes: 0=success, 2=validation, 3=dedup-skip, 4=depth-exceeded, 5=lock-timeout, 6=diffuse-cited-paths.
- `scripts/sink-add-helpers.py:479` — `main` — Full writer pipeline: depth check → validate → dedup (pre-lock) → build entry → acquire global lock → TOCTOU dedup recheck → write prompt-page → append `entry_created` → rebuild view → optional Notion push → emit `followup_created`.
- `scripts/sink-add-helpers.py:136` — `content_hash` — SHA-256 of `name + NUL + recommended_command + NUL + source_artifact`; dedup key under global lock.
- `scripts/sink-claim.sh:1` — `sink-claim.sh` — Atomic `open→running` claim; prints claim ticket JSON on exit 0. Exit codes: 0=success, 2=validation, 3=not-claimable, 4=staleness-drift, 5=lock-timeout, 7=depth-1-refusal.
- `scripts/sink-claim-helpers.py:255` — `do_claim` — Full claim: per-entry lock first (mandatory) → stale-takeover recovery → depth-1 refusal → status==open → staleness → global lock → append `status_changed open→running` → rebuild view.
- `scripts/sink-status-set.sh:1` — `sink-status-set.sh` — Generic status transition primitive; flags: `--entry`, `--to`, `--by`, optional `--evidence`, `--reason`, `--completion-mode`, `--via-claim-ticket`.
- `scripts/sink-status-set-impl.py:474` — `main` — Drives seven-state machine; validates via `ALLOWED_TRANSITIONS`; enforces completion_mode mutex; appends `status_changed`; rebuilds view.
- `scripts/sink-view-rebuild.sh:1` — `sink-view-rebuild.sh` — Must be called while global lock is held; verifies lock via JSON content OR OS flock sentinel; delegates to `sink-view-reducer.py`; exit 4 if lock free.
- `scripts/sink-view-reducer.py:138` — `reduce_journal` — Reads `index.jsonl` and applies events; unknown kinds warned and skipped; never crashes.
- `scripts/sink-view-reducer.py:168` — `write_view` — Writes `index.view.json` atomically via tmpfile+rename; `indent=2, sort_keys=True`.
- `scripts/sink-audit-validate.py:54` — `validate` — 11-point check on `audit_evidence.json` vs entry JSON; short-circuits on first failure; returns `{passed, rejected_check, reason}`.
- `scripts/sink-audit-validate.py:310` — `main` — CLI for audit validation; exits 0 on pass, 1 on fail.
- `scripts/sink-auto-close-check.py:357` — `main` — Auto-close ceiling check; denylist takes precedence over allowlist; outputs `{passed, reason, mode}`.
- `scripts/notion-push.py:493` — `main` — One-way idempotent Notion push; 3 retries with backoff [1, 4, 16]s; exit codes: 0=success, 4=retry-exhausted, 5=idempotency-mismatch, 6=auth-missing, 7=config-missing.
- `scripts/followup-reconcile-notion.sh:1` — `followup-reconcile-notion.sh` — Thin shell wrapper; accepts `--project-sink-root`, `--global-sink-root`, `--dry-run`.
- `scripts/followup-reconcile-notion-impl.py:291` — `main` — Sweeps both sinks for `notion_sync_pending` entries; re-invokes `notion-push.py`; outputs `{swept_count, succeeded, failed, conflicts}` JSON; always exits 0.
- `scripts/parse-followups-block.py:228` — `main` — Tolerant parser for `**FOLLOWUPS:**` fenced JSON block; per-entry errors log and skip; outputs JSON list (may be `[]`); exits 0 even on empty result.
- `scripts/validate-followup-schemas.sh:1` — `validate-followup-schemas.sh` — JSON Schema test runner (draft-2020-12); 3 followup-entry fixtures + 2 audit-evidence fixtures + mutex test + enum literal tests; exits 0 on all pass.

## How it interacts with others

- `commands` — Every z-harness command that tracks execution time calls `log-phase.sh start`/`end`. `/z-plan`, `/z-implement-all`, `/z-implement-next`, `/z-review-all`, `/z-audit`, `/z-fix`, `/z-do`, `/z-uplift`, and `/z-maintain-docs` call `version.sh` and `log-event.sh` at run start/end events. `/z-mr-review` and `/z-audit-plan-style` call `extract-dismissals.py`. `/z-plan`, `/z-fix`, `/z-audit-plan`, `/z-audit-plan-style`, and `/z-uplift` call `config.py resolve-question`. `/z-overnight` calls `config.py check-no-ask`, `overnight-preflight.sh check-collisions`, and `morning-report.py`. `/z-plan` and `/z-audit` call `active-plan-registry.py session-id`, `register`, `heartbeat`, `update-scope`, and `deregister`. `/z-do` calls `active-plan-registry.py session-id`. `/z-where` calls `active-plan-registry.py list --json` and `overlaps`. `/z-stats` reads `active-plan-registry.py list --json`. Skills that discover out-of-SPEC items during `/z-implement-next` Phase 4 may call `sink-add.sh` when `workflow.spec_retro_discovery` resolves to `defer-to-sink`.
- `skills` — `/z-implement-all`, `/z-review-all`, and `/z-debug` skills call `run-memory-review.sh` to gate the memory-review subagent. `/z-implement-all` calls `normalize-task-state.sh` on resume. `/z-overnight` calls `run-status.sh classify` after each step. The review-all skill calls `parse-followups-block.py` and `sink-add.sh`. `/z-plan`, `/z-plan-light`, `/z-brainstorm`, and `/z-debug` skills call `active-plan-registry.py session-id`, `register`, and `deregister`.
- `agents` — The remote-runner agent calls `remote-sandbox-sync.sh`; the doc-updater agent calls `log-phase.sh` and `log-event.sh`; the memory-review agent receives artifact paths from `run-memory-review.sh`.
- `config` — `config.py` / `config.sh` implement the layered TOML config system and workflow resolver; the `config` concept doc has deep coverage of invariants and the question registry. The `[followup]` section keys feed `sink-add-helpers.py`, `sink-claim-helpers.py`, `sink-auto-close-check.py`, and `followup-reconcile-notion-impl.py`.
- `active-plan-registry` — The dedicated concept doc (`docs/human/active-plan-registry.md`) covers the per-run registry in detail. From the scripts layer: `scripts/migrate-plan-layout.sh` calls `active-plan-registry.py list --json` to guard against migration while runs are live.
- `overnight-run` — `overnight-preflight.sh`, `morning-report.py`, and `run-status.sh` are the primary script-layer support for the `/z-overnight` concept; `normalize-task-state.sh` is called on resume.
- `followup-sink` (cross-concept) — `sink-lock.sh`, `sink-add.sh`/`helpers`, `sink-claim.sh`/`helpers`, `sink-status-set.sh`/`impl`, `sink-view-rebuild.sh`, `sink-view-reducer.py`, `sink-audit-validate.py`, `sink-auto-close-check.py`, `notion-push.py`, `followup-reconcile-notion.sh`/`impl`, and `parse-followups-block.py` collectively implement the follow-up sink. The global cross-tool lock file is at `~/.z-harness/.followup-vs-implement.lock`. The project sink lives at `<repo>/z-harness/followups/`; the global sink at `~/.z-harness/followups/`.

## Edge cases / gotchas

- `log-event.sh` resolves all artifact paths via `z_harness_base()` from `plan-path.sh` (5-tier fallback). When `Z_HARNESS_BASE_DIR` is set, the mid-flight legacy fallback is skipped entirely to preserve the model.patch invariant.
- `log-phase.sh` `check_wall_ms`: threshold is 604_800_000 ms (7 days). Values above this indicate seconds-vs-ms confusion. Values below 0 indicate clock skew. Both cases emit `telemetry_anomaly` and suppress the bogus `*_end` event.
- `log-phase.sh` uses a `python3` fallback (`time.time()*1000`) to get millisecond timestamps because macOS BSD `date` does not support `%3N`.
- `log-event.sh` validates JSON payloads via `python3`; malformed payloads are silently wrapped in `{"raw": ...}` rather than failing.
- `log-event.sh` mid-flight legacy detection: writes to the old flat path if the run dir already exists there (but skips this when `Z_HARNESS_BASE_DIR` is set).
- `config.py` startup guards run at module load via `_run_startup_guards()`. Violations exit 2 immediately.
- `config.py resolve-question` returns result in `{ask, skip, prefill, halt, defer-to-sink}`. `workflow.spec_retro_discovery` can return `defer-to-sink`, which signals the caller to invoke `sink-add.sh`.
- `config.py resolve-question` honors `Z_HARNESS_ASK_ALL=1` (forces `result: ask`) and `Z_HARNESS_NO_ASK=halt` (activates overnight overrides). Setting both simultaneously exits 5.
- `config.py check-no-ask` is fail-closed: unregistered question IDs return `halt` when `Z_HARNESS_NO_ASK=halt` and emit `unknown_ask_blocked`.
- `active-plan-registry.py` lockless invariant: the lockless design is safe ONLY because overlap is advisory. No code may make overlap a hard gate without first replacing lockless delete with compare-and-delete or a registry lock.
- `active-plan-registry.py register` exits 3 on failure — callers MUST gate on this exit code; all other subcommands are non-fatal (exit 0 even on error, self-logging via `registry_error` events).
- `active-plan-registry.py heartbeat` does NOT fabricate a record when `<run-id>.json` is absent (never registered, reaped, or deregistered). Creating an empty record would pollute overlap detection with zombie records.
- `active-plan-registry.py overlaps` blocking exit code 20 fires only in strict mode (`--strict` or `Z_HARNESS_STRICT_OVERLAP=1`) AND when both peers share an `explicit`-confidence path match. Stale peers (status:stale OR heartbeat > `Z_HARNESS_REGISTRY_STALE_SECS`) are included in the report but marked non-blocking.
- `active-plan-registry.py reap` case (a): deletes only when the record host matches THIS host and the PID is dead. Case (b): deletes when `age_secs > stale_threshold * 2` regardless of host. Case (c): marks `status:stale` (no delete) when `age_secs > stale_threshold` and host is remote/unknown. `FileNotFoundError` on unlink is always benign (two reapers racing).
- `active-plan-registry.py session-id`: on Linux derives `<ppid>-<start_epoch>` from `/proc`; on macOS derives `<ppid>-<current_epoch>` (no subprocess, avoiding CoreFoundation fork-safety crash). Callers should `export Z_HARNESS_SESSION_ID="$(session-id)"` once at run start so repeated calls reuse the env var.
- `active-plan-registry.py` sets `OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES` at import time to prevent CoreFoundation fork-safety crashes when bash invokes Python with an existing CF-initialized parent.
- `persona-stats.py` baseline resolution: `no-persona` is the primary null baseline (true null prefix); `boring-anchor` is the secondary bland control. Both appear as their own rows in every section — neither is quarantined or hidden.
- `persona-stats.py` `--since` filter: events with a missing or unparseable `ts` field are excluded (conservative) when `--since` is active.
- `persona-stats.py` events with `run == "unknown-run"` are excluded by default (dev noise from ad-hoc subcommand/test draws); pass `--include-unknown-run` to opt back in.
- `run-memory-review.sh` uses a 4-state terminal taxonomy: `skipped_broken_context`, `not_applicable`, `ready`, `dispatched` (last two are orchestrator-owned). The `debug` parent adds a third skip condition: `debug_md_missing`.
- The env var controlling the plan base dir is `Z_HARNESS_PLAN_DIR` (singular), not `Z_HARNESS_PLANS_DIR`.
- `sink-lock.sh` holder PID is the background daemon's own `os.getpid()`, NOT `os.getppid()`. Stale-takeover (exit 2) fires when PID is dead OR heartbeat age >= TTL — either condition alone is sufficient.
- `sink-add-helpers.py` cited paths: `len(cited_paths) <= 16` records individual `git hash-object` SHAs; `> 16` uses the common ancestor directory's tree hash. Ancestor depth < 2 from repo root is rejected with exit 6.
- `sink-claim-helpers.py` mandatory lock-ordering: per-entry lock FIRST, global lock SECOND. Violating this order risks deadlock.
- `sink-status-set-impl.py` completion_mode mutex: only one of `human_confirmed`, `audit_confirmed`, or `auto_closed_low_risk` may be set per entry. Re-setting to a different non-null mode exits 6.
- `sink-view-rebuild.sh` must be called with global lock already held; exits 4 if called without the lock.
- `notion-push.py` idempotency: queries Notion by `z_harness_entry_id` before creating; exit 5 on mismatch. Token resolution order: `Z_HARNESS_NOTION_TOKEN` env → `secrets.toml`.
- `remote-sandbox-sync.sh` TASK_ID rejects the literal value `base` and all path-traversal patterns. `REMOTE_HOME` is resolved via `ssh printf` (not tilde expansion).

## Examples

- Start a named phase and capture the timing token:
  `TOKEN="$(bash scripts/log-phase.sh start "tasks/T020" precheck '{"id":"T020"}')"`
- End the phase with status:
  `bash scripts/log-phase.sh end "$TOKEN" '{"status":"ok","references_checked":11}'`
- Gate the memory-review agent from implement-all:
  `mapfile -t LINES < <(bash scripts/run-memory-review.sh "$RUN" "implement-all")`
- Resolve a workflow question (returns JSON envelope):
  `python3 scripts/config.py resolve-question workflow.audit_to_amend`
- Check whether a question can proceed in overnight mode:
  `python3 scripts/config.py check-no-ask --question-id workflow.slug_confirm`
- Derive a stable session ID (export once at run start):
  `export Z_HARNESS_SESSION_ID="$(python3 scripts/active-plan-registry.py session-id)"`
- Register a run in the active-plan registry:
  `python3 scripts/active-plan-registry.py register --run-id "$RUN" --slug "$SLUG" --command "/z-plan" --phase "plan" --session "$Z_HARNESS_SESSION_ID"`
- Check for overlapping active plans:
  `python3 scripts/active-plan-registry.py overlaps --run-id "$RUN" --strict`
- Deregister a run on completion:
  `python3 scripts/active-plan-registry.py deregister --run-id "$RUN" --status complete`
- List all active plans as JSON:
  `python3 scripts/active-plan-registry.py list --json`
- Reap dead/stale registry records:
  `python3 scripts/active-plan-registry.py reap`
- Run persona-rotation analysis:
  `python3 scripts/persona-stats.py --min-diff-size 5 --since 2026-06-01`
- Add a follow-up entry to the project sink:
  `bash scripts/sink-add.sh --sink=project --priority=P2 --name='Fix linter gap' --recommended-command='/z-fix' --source-artifact='z-harness/plans/my-slug/REVIEW.md' --cited-paths='scripts/lint-askuser.sh'`
- Claim an open follow-up entry for processing:
  `TICKET="$(bash scripts/sink-claim.sh --entry=20260529T000000Z-fix-linter-gap --run="$RUN" --sink-root=z-harness/followups)"`
- Classify the terminal state of a run:
  `bash scripts/run-status.sh classify 20260527T155455Z-amend-runtime-core`
- Run local preflight checks before a commit:
  `bash scripts/preflight.sh`
