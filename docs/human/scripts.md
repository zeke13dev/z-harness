# Scripts

> Last updated: 2026-05-28
> Covers source: scripts/extract-dismissals.py, scripts/log-event.sh, scripts/log-phase.sh, scripts/regenerate-memories-flat.py, scripts/remote-sandbox-sync.sh, scripts/run-memory-review.sh, scripts/version.sh, scripts/config.py, scripts/config.sh, scripts/test_config.py, scripts/test_log_phase.sh, scripts/run-status.sh, scripts/normalize-task-state.sh, scripts/lint-askuser.sh, scripts/overnight-preflight.sh, scripts/morning-report.py, scripts/preflight.sh

## Overview

The scripts concept covers the shell and Python utility scripts that form the operational backbone of the z-harness pipeline. They handle structured event telemetry (logging individual events and wrapping entire phases with start/end timing), memory document regeneration across all concept JSONs, plugin version introspection, the lifecycle gate logic for the memory-review agent, MR-review dismissal signature extraction across archived run snapshots, rsync-based remote sandbox synchronization, layered TOML configuration and workflow-question resolution, run terminal-state classification, overnight preflight collision detection, TASKS.md normalization, AskUserQuestion callsite auditing, morning-report generation, and the local preflight harness.

The layered TOML config loader (`config.py`) is the most complex script. It exposes subcommands: `get`, `export-env`, `ensure-defaults`, `explain`, `should-notify`, `list-question-ids`, `resolve-question`, `check-no-ask`, `set`, and `migrate`. The `resolve-question` subcommand is backed by a `QUESTION_IDS` registry (single source of truth for workflow prompts), a `RESULT_MAP` lookup table that translates option-domain values to resolver result-domain values (`ask`, `skip`, `prefill`), and a `_load_memory_matches` function that walks `docs/llm/*.json` for `routing-preference` memory entries. Startup guards run at module load and exit 2 if the registry is internally inconsistent. `log-phase.sh` includes a `check_wall_ms` helper that detects and suppresses anomalous timing values before writing `*_end` events, emitting a `telemetry_anomaly` event instead. `remote-sandbox-sync.sh` uses a two-level remote layout with hardlink overlays and atomic mkdir-based locking. `run-status.sh` classifies the terminal state of a completed run by reading `events.jsonl` against explicit clean/halt/error allowlists. `overnight-preflight.sh` provides Phase-0 slug-collision detection for `/z-overnight`. `morning-report.py` generates `MORNING_REPORT.md` from an overnight run's `overnight-state.json` and `events.jsonl`, covering chain summary, phase results table, unilateral decisions, test outcomes, and recommended next action.

## Key entry points

- `scripts/log-event.sh:1` — `log-event.sh` — Appends a structured JSON event line to `<run>/events.jsonl` and the repo-wide `z-harness/metrics.jsonl`; uses `flock` when available for concurrent-safe appends; sources `scripts/plan-path.sh` for canonical path resolution.
- `scripts/log-phase.sh:1` — `log-phase.sh` — Sugar layer over `log-event.sh`; supports three modes: `start` (emits `<phase>_start`, returns an opaque timing token), `end` (emits `<phase>_end` with `wall_ms` merged in), and `wrap` (wraps an arbitrary command end-to-end and captures its exit code); anomaly detection via `check_wall_ms`.
- `scripts/log-phase.sh:71` — `check_wall_ms` — Anomaly guard: emits a `telemetry_anomaly` event and returns exit code 1 (suppressing the bogus `*_end` event) when `wall_ms > 604_800_000 ms` (7-day threshold) or when `wall_ms < 0` (clock skew / NTP jump); called from both `end` and `wrap` modes.
- `scripts/regenerate-memories-flat.py:1` — `regenerate-memories-flat.py` — Scans all `docs/llm/*.json` files (excluding `INDEX.json`), extracts `memories[]` entries, sorts them by slug ascending then date descending, and writes `docs/llm/MEMORIES-FLAT.md` atomically via a temp-file rename.
- `scripts/version.sh:1` — `version.sh` — Prints a single-line JSON blob with the plugin's git short-SHA, dirty flag, branch, and optional tag; used at `run_start` events for post-run correlation; resolves plugin root via `Z_HARNESS_PLUGIN_ROOT`, `ANTIGRAVITY_PLUGIN_ROOT`, `CLAUDE_PLUGIN_ROOT`, or script-relative walk.
- `scripts/run-memory-review.sh:1` — `run-memory-review.sh` — Gate script called by `/z-implement-all`, `/z-review-all`, and `/z-debug`; accepts `<RUN> <parent_command>` (`implement-all`, `review-all`, or `debug`); evaluates skip conditions using a 4-state terminal taxonomy; writes a truncated cumulative diff to the run archive and prints artifact paths on stdout.
- `scripts/extract-dismissals.py:480` — `main` — CLI entry point; extracts dismissed MR-review or plan-style-audit finding signatures by comparing consecutive archived run snapshots; supports `--global` to scan all slugs and `--filename` to target alternate snapshot files (e.g. `PLAN_STYLE_AUDIT.md`); outputs `{"signatures": [...], "n_runs_scanned": N}` to stdout.
- `scripts/extract-dismissals.py:384` — `extract_dismissals_from_runs` — Core pairwise algorithm: for each consecutive run pair (R_i, R_{i+1}), compares R_i snapshot against R_{i+1}'s `.previous-*` user-edited copy to identify dismissed findings.
- `scripts/remote-sandbox-sync.sh:1` — `remote-sandbox-sync.sh` — Rsync the local working tree to a per-(slug, task-id) remote sandbox using a two-level layout: a shared warm base at `~/dev/qt-bot-sandbox/<slug>/base/` (seeded once per slug with atomic mkdir-based locking) and a per-task overlay at `~/dev/qt-bot-sandbox/<slug>/<task-id>/` linked via `--link-dest`; REMOTE_HOME resolved via SSH `printf`; SLUG and TASK_ID validated to reject path-traversal patterns.
- `scripts/remote-sandbox-sync.sh:105` — `seed_base` — Acquires remote lock via `mkdir` (atomic), seeds the shared base via rsync, writes a `.base-ready` marker with the local HEAD SHA, then releases the lock; losers poll for the marker up to 600s.
- `scripts/config.py:1` — `config.py` — Layered TOML config loader; subcommands: `get`, `export-env`, `ensure-defaults`, `explain`, `should-notify`, `list-question-ids`, `resolve-question`, `check-no-ask`, `set`, `migrate`; `QUESTION_IDS` registry + `RESULT_MAP`; startup guards at module load.
- `scripts/config.py:163` — `_run_startup_guards` — Module-load guard: asserts every `QUESTION_IDS` key exists in `VALIDATORS`, has a non-null `skill_default`, and every `RESULT_MAP` `(question_id, choice)` references a known question_id and valid choice; exits 2 on any violation.
- `scripts/config.py:750` — `cmd_list_question_ids` — Prints sorted JSON array of registered question IDs from the `QUESTION_IDS` registry.
- `scripts/config.py:1452` — `cmd_resolve_question` — Returns a JSON resolver envelope `{result, default, source, rule_id, strength, reason, sources}`; consults 4-layer config then `routing-preference` memory entries from `docs/llm/*.json`; honors `Z_HARNESS_ASK_ALL`, `Z_HARNESS_NO_ASK`, and `Z_HARNESS_EXPLAIN_RESOLUTION`; post-processes via `_apply_overnight_overrides` for halt-from-ask / overnight allowlist behavior.
- `scripts/config.py:1575` — `cmd_check_no_ask` — Returns JSON `{result: halt|proceed, question_id, rule_id}`; gate for overnight mode: if `Z_HARNESS_NO_ASK != halt` always proceeds; if halt, builds the resolution envelope, applies overnight overrides, and maps to halt/proceed.
- `scripts/config.py:1698` — `cmd_set` — Atomic read-modify-write of a config key in global or project TOML; validates key+value before writing; exits 2 on validation failure, 4 on I/O error.
- `scripts/config.sh:1` — `config.sh` — Thin shell wrapper: `exec python3 scripts/config.py "$@"`.
- `scripts/run-status.sh:1` — `run-status.sh` — Classifies the terminal state of a z-harness run as `clean | halted | errored | unknown`; two subcommands: `classify <run-id-or-path> [--command <name>]` and `last-event <run-id-or-path>`; sources `plan-path.sh` for layout resolution; supports both canonical and legacy archive layouts.
- `scripts/run-status.sh:198` — `classify_by_kind` — Core classifier: matches event kind against clean allowlist, halt allowlist, and `*_error / fatal` pattern; returns one of four terminal states.
- `scripts/run-status.sh:250` — `cmd_classify` — Subcommand entry point; handles the `/z-implement-all` special case (requires last event to be `implement_end` or `compaction_pause` AND all TASKS.md checkboxes to be `[x]` or `[~]` before declaring clean).
- `scripts/normalize-task-state.sh:1` — `normalize-task-state.sh` — Resets in-progress task markers: replaces every `- [~]` prefix in `<plan-dir>/TASKS.md` with `- [ ]`; writes atomically via `.tmp.$$.` sibling rename; always exits 0 (best-effort); includes `--self-test` mode with 4 assertions.
- `scripts/lint-askuser.sh:1` — `lint-askuser.sh` — Audits `AskUserQuestion` callsites in `commands/` and `skills/`; tags each callsite `REGISTERED` (same file also contains `resolve-question` or `check-no-ask`) or `UNREGISTERED`; `--strict` flag exits 1 on any unregistered callsite; default exit 0 (advisory).
- `scripts/overnight-preflight.sh:1` — `overnight-preflight.sh` — Phase-0 preflight for `/z-overnight`; subcommand `check-collisions --chain <steps> --base <dir>` exits 0 if safe, emits `slug_collision_halt` event and exits 1 on collision; `--self-test` runs 8 assertions; chain grammar: comma- or arrow-separated.
- `scripts/overnight-preflight.sh:233` — `cmd_check_collisions` — v1 rule (SPEC C13): collision only when first step is `plan` or `research` AND `<base>/PLAN.md` already exists; always `cd`s to repo root before calling `log-event.sh` so paths resolve correctly regardless of caller cwd.
- `scripts/morning-report.py:427` — `cmd_generate` — Locates the latest overnight run dir for a slug, loads `overnight-state.json` and `events.jsonl`, calls `generate_report`, writes `MORNING_REPORT.md` atomically; exits 1 on any I/O or parse error.
- `scripts/morning-report.py:376` — `generate_report` — Assembles five sections: chain summary (with HEAD SHA mismatch banner), phase results table, unilateral decisions table, test outcomes, and recommended next action (branching on halt reason: `no_ask_blocked`, `slug_collision_halt`, `skill_tool_failure`, or generic resume).
- `scripts/morning-report.py:518` — `cmd_self_test` — Golden-file comparison against fixtures in `z-harness/overnight-run/tests/morning-report-fixtures/`; runs root fixture plus any sub-directories with a `MORNING_REPORT.md.golden` file.
- `scripts/preflight.sh:1` — `preflight.sh` — Local pre-commit/pre-PR harness; runs `lint-askuser.sh --strict` and maps exit 1 (unregistered callsites) to an advisory warning while propagating exit 2+ as hard failures.
- `scripts/test_config.py:1` — `test_config.py` — End-to-end smoke-test suite for `config.py` using hermetic `XDG_CONFIG_HOME` temp dirs; 18+ test classes covering defaults, env overrides, repo-local precedence, schema errors, `ensure-defaults` edge cases, `export-env` event dedup, `resolve-question`, overnight overrides, `check-no-ask`, `list-question-ids`, 3-level nesting (`roles.*`), `migrate`, and `_KEY_RE` validation.
- `scripts/test_log_phase.sh:1` — `test_log_phase.sh` — Bash regression harness for `log-phase.sh`; 4 TEST groups, 21 assertions; hermetic isolation via `Z_HARNESS_PLANS_DIR` + `Z_HARNESS_SLUG` temp dirs; covers overflow guard, normal happy path, negative wall_ms (clock skew), and 26-hour false-positive regression.

## How it interacts with others

- `commands` — Every z-harness command that tracks execution time calls `log-phase.sh start`/`end`. `/z-plan`, `/z-implement-all`, `/z-implement-next`, `/z-review-all`, `/z-audit`, `/z-fix`, `/z-do`, `/z-uplift`, and `/z-maintain-docs` call `version.sh` and `log-event.sh` at run start/end events. `/z-mr-review` and `/z-audit-plan-style` call `extract-dismissals.py` to load prior dismissal signatures. `/z-style-init` calls `extract-dismissals.py --global` to seed a new reviewer. `/z-plan`, `/z-fix`, `/z-audit-plan`, `/z-audit-plan-style`, and `/z-uplift` call `config.py resolve-question` to determine whether to show or skip workflow confirmation prompts; `/z-audit-plan` also calls `config.py set` to apply accepted preference proposals. `/z-overnight` calls `config.py check-no-ask` to gate questions before dispatching, calls `overnight-preflight.sh check-collisions` as Phase 0, and calls `morning-report.py` at run end.
- `skills` — `/z-implement-all`, `/z-review-all`, and `/z-debug` skills call `run-memory-review.sh` (via `mapfile`) to gate the memory-review subagent. The `z-plan-light`, `z-brainstorm`, `z-map`, and `z-debug` skills call `config.py resolve-question workflow.slug_confirm`. `/z-implement-all` calls `normalize-task-state.sh` on resume to reset in-progress markers. `/z-overnight` calls `run-status.sh classify` after each step to record terminal state.
- `agents` — The remote-runner agent calls `remote-sandbox-sync.sh` before executing cargo or qtctl on the remote host; the doc-updater agent calls `log-phase.sh` and `log-event.sh` for doc-update telemetry; the memory-review agent receives artifact paths from `run-memory-review.sh`.
- `review-agent` — `run-memory-review.sh` is the dedicated lifecycle helper for the memory-review agent; on `STATUS: ready` it outputs artifact paths: cumulative diff, SPEC.md (or empty if absent), TAGS.txt, and (debug parent only) DEBUG.md.
- `config` — `config.py` and `config.sh` implement the layered TOML config system and workflow resolver; the `config` concept doc has deep coverage of invariants and the question registry.
- `z-suggest-memory` — When a `resolve-question` result source is `memory` or `conflict`, the calling command may dispatch `/z-suggest-memory --kind routing-preference` to author or update routing-preference memory entries that `config.py resolve-question` reads via `_load_memory_matches`.
- `overnight-run` — `overnight-preflight.sh`, `morning-report.py`, and `run-status.sh` are the primary script-layer support for the `/z-overnight` concept; `normalize-task-state.sh` is called on resume; `lint-askuser.sh` and `preflight.sh` surface the overnight halt-from-ask audit gap as an advisory warning.

## Edge cases / gotchas

- `log-phase.sh` `check_wall_ms`: threshold is 604_800_000 ms (7 days). Values above this indicate seconds-vs-ms confusion (the original bug produced epoch-scale values > 1e12 ms). Values below 0 indicate clock skew. Both cases emit `telemetry_anomaly` with a `t_start`, `t_end`, `computed_wall_ms`, and `reason` field, then exit 0 to suppress the bogus `*_end` event. Sessions up to 7 days long produce no false positives.
- `config.py` startup guards run at module load via `_run_startup_guards()`. They enforce: every key in `QUESTION_IDS` must exist in `VALIDATORS`; every entry must have a non-null `skill_default`; every `(question_id, choice)` key in `RESULT_MAP` must reference a known question_id and valid choice. Violations exit 2 immediately.
- `config.py resolve-question` returns a JSON envelope with `result` in `{ask, skip, prefill, halt}` (the resolver result-domain), not the option-domain value. The `RESULT_MAP` handles translation. Callers must parse stdout as JSON.
- `config.py resolve-question` honors `Z_HARNESS_ASK_ALL=1` as a short-circuit that forces `result: ask` regardless of config or memory. `Z_HARNESS_EXPLAIN_RESOLUTION=1` activates verbose explain output on stderr. `Z_HARNESS_NO_ASK=halt` activates overnight/halt-from-ask behavior via `_apply_overnight_overrides`.
- `config.py resolve-question` reads `routing-preference` memory entries from `docs/llm/*.json` (harness-relative, not project-relative). Project scope filtering uses `Z_HARNESS_PROJECT_ROOT` or `git rev-parse`. Outside a git repo, all entries are treated as global.
- `config.py resolve-question` conflict resolution: if config is non-default AND memory disagrees, `result=ask` with `source=conflict`. If multiple memory entries disagree, also `result=ask` with `source=conflict`. Memory strength mapping: `very_strong` → `skip`; `strong` or `weak` → `prefill` (when config is at default `ask`).
- `config.py check-no-ask` result is `halt` (fail-closed) for unregistered question IDs when `Z_HARNESS_NO_ASK=halt`; it also emits `unknown_ask_blocked` event.
- `config.py resolve-question` exits 5 when `Z_HARNESS_ASK_ALL=1` and `Z_HARNESS_NO_ASK=halt` are both set (mutually exclusive config conflict).
- `config.py set` performs a read-modify-write using atomic temp-file rename. It validates the key against `_KEY_RE` and `VALIDATORS` before writing; exits 2 on validation failure, 4 on I/O error. Default scope is `project`; pass `--scope=global` for the global config.
- `config.py export-env` emits a `config_resolved` event exactly once per `Z_HARNESS_RUN` via an `O_EXCL` stamp file in `$TMPDIR`. `roles.*` keys are not exported as env vars (3-level keys lack a 2-segment env var form).
- `remote-sandbox-sync.sh` two-level layout: the `base/` directory is seeded once per slug using an atomic remote `mkdir` lock. Concurrent invocations poll for the `.base-ready` marker (up to 600s). The per-task overlay uses `--link-dest` so unchanged files are hard-linked rather than copied.
- `remote-sandbox-sync.sh` resolves REMOTE_HOME via `ssh <host> 'printf %s "$HOME"'` rather than relying on tilde expansion, which is unreliable inside `--link-dest`.
- `remote-sandbox-sync.sh` TASK_ID rejects the literal value `base` (reserved for the shared base directory) in addition to path-traversal patterns.
- `run-memory-review.sh` uses a 4-state terminal taxonomy in `memory_review_terminal` events: `skipped_broken_context` (missing args, no plan dir, tags file absent), `not_applicable` (empty diff, all tasks skipped, debug_md missing); `ready` and `dispatched` are orchestrator-owned.
- `run-memory-review.sh` stdout contract: line 1 is always `STATUS: ready | STATUS: skipped <reason>`; if ready, lines 2–4 are absolute paths to `cumulative.diff`, `SPEC.md` (or empty string if missing), and `TAGS.txt`; line 5 is present only for the `debug` parent and holds the absolute path to `DEBUG.md`.
- The env var controlling the plan base dir is `Z_HARNESS_PLAN_DIR` (singular), not `Z_HARNESS_PLANS_DIR`.
- `log-phase.sh` uses a `python3` fallback (`time.time()*1000`) to get millisecond timestamps because macOS BSD `date` does not support `%3N`.
- `log-event.sh` validates JSON payloads via `python3`; malformed payloads are silently wrapped in `{"raw": ...}` rather than failing.
- `log-event.sh` performs mid-flight legacy run detection: if a run directory already exists at the old flat layout path, it writes there instead of the slug-namespaced path.
- `run-memory-review.sh` uses `set +o pipefail` around the `git diff | head -n 5000` pipeline to avoid SIGPIPE failures.
- `version.sh` degrades gracefully if the plugin root is not a git repo, returning non-git sentinel values.
- `regenerate-memories-flat.py` writes atomically using `os.replace()` on a PID+random-suffixed temp file.
- `extract-dismissals.py` drops findings that lack a `title` field; it does NOT fall back to T-MR-NNN ids (renumbered each run, would produce spurious matches).
- `extract-dismissals.py --global` applies the pairwise algorithm within each slug independently to prevent cross-slug run interleaving.
- `remote-sandbox-sync.sh` warns (but does not fail) when no `.z-harness-rsync-exclude` file is found.
- `run-status.sh classify` for `--command implement-all` requires BOTH a clean last-event kind (`implement_end` or `compaction_pause`) AND all TASKS.md checkboxes to be `[x]` or `[~]` before returning `clean`; a TASKS.md with zero checkboxes is treated as incomplete.
- `run-status.sh classify` exits 0 and returns `unknown` when `events.jsonl` is missing, empty, or contains no valid JSON lines.
- `normalize-task-state.sh` is best-effort: exits 0 on missing TASKS.md and on failed atomic write (after cleaning up the temp file). It does not emit any events.
- `normalize-task-state.sh` only replaces the `- [~]` prefix at the start of a line; it does not modify `- [ ]` (pending) or `- [x]` (done) markers.
- `lint-askuser.sh` classification is file-level, not callsite-level: if a file has `AskUserQuestion` AND `resolve-question` anywhere in it, all callsites in that file are tagged `REGISTERED` regardless of pairing.
- `overnight-preflight.sh check-collisions` uses `cd "$REPO_ROOT"` before calling `log-event.sh` to ensure the canonical plan dir resolves correctly when invoked from outside the repo (e.g. from `/tmp`).
- `morning-report.py` emits a `CRITICAL: HEAD SHA mismatch at resume` banner in the chain summary section when a `head_sha_mismatch_at_resume` event is found in `events.jsonl`.
- `morning-report.py` `_build_recommended_next` branches on three specific halt reasons: `no_ask_blocked` / `unknown_ask_blocked` (shows lint-askuser remediation steps), `slug_collision_halt` (shows fresh-slug or resume options), `skill_tool_failure` (shows captured error message). All other halts receive a generic resume instruction.
- `morning-report.py` finds the latest overnight run by lexical sort of directory names containing the substring `-overnight-`; the lexical sort works because run IDs use ISO-8601 timestamps as prefixes.
- `preflight.sh` maps `lint-askuser.sh` exit 1 to an advisory warning only; exits 2 and 3+ from `lint-askuser.sh` are propagated as hard failures.

## Examples

- Start a named phase and capture the timing token:
  `TOKEN="$(bash scripts/log-phase.sh start "tasks/T020" precheck '{"id":"T020"}')"`
- End the phase with status:
  `bash scripts/log-phase.sh end "$TOKEN" '{"status":"ok","references_checked":11}'`
- Wrap a command end-to-end (auto-times and logs exit code):
  `bash scripts/log-phase.sh wrap "tasks/T020" cargo_test '{}' -- cargo test --release`
- Run the log-phase regression harness (21 assertions):
  `bash scripts/test_log_phase.sh`
- Gate the memory-review agent from implement-all:
  `mapfile -t LINES < <(bash scripts/run-memory-review.sh "$RUN" "implement-all")`
- Gate the memory-review agent from debug (line 5 is DEBUG.md path):
  `mapfile -t LINES < <(bash scripts/run-memory-review.sh "$RUN" "debug")`
- Regenerate the flat memory index in dry-run mode:
  `python3 scripts/regenerate-memories-flat.py --repo-root /path/to/repo --dry-run`
- Extract dismissal signatures for a slug:
  `python3 scripts/extract-dismissals.py z-harness/mr-style-reviewer/ --max-runs 10`
- Extract plan-style-audit dismissal signatures globally:
  `python3 scripts/extract-dismissals.py --global --filename PLAN_STYLE_AUDIT.md`
- Sync local working tree to remote sandbox (first call seeds base, subsequent calls use hard-link overlay):
  `bash scripts/remote-sandbox-sync.sh zeke-pc add-rate-limit T030`
- Resolve a config key (falls through to default if no config file exists):
  `python3 scripts/config.py get notify.level`
- Export all config keys as shell environment variables:
  `eval "$(python3 scripts/config.py export-env)"`
- Write the global config file with defaults if it does not exist:
  `python3 scripts/config.py ensure-defaults`
- List all registered question IDs:
  `python3 scripts/config.py list-question-ids`
- Resolve a question (returns JSON envelope with result, default, source, strength):
  `python3 scripts/config.py resolve-question workflow.audit_to_amend`
- Check whether a question can proceed in overnight mode:
  `python3 scripts/config.py check-no-ask --question-id workflow.slug_confirm`
- Set a config key in the project scope:
  `python3 scripts/config.py set workflow.audit_to_amend amend --scope=project`
- Explain which config layer is winning for a key:
  `python3 scripts/config.py explain notify.level`
- Run the end-to-end config smoke tests (18+ test classes):
  `python3 scripts/test_config.py`
- Classify the terminal state of a run:
  `bash scripts/run-status.sh classify 20260527T155455Z-amend-runtime-core`
- Classify terminal state for an implement-all run:
  `bash scripts/run-status.sh classify "$RUN" --command implement-all`
- Print the last valid JSON event from a run:
  `bash scripts/run-status.sh last-event 20260527T155455Z-amend-runtime-core`
- Reset in-progress task markers before resuming a plan:
  `bash scripts/normalize-task-state.sh z-harness/plans/my-slug/`
- Self-test the normalize script (4 assertions):
  `bash scripts/normalize-task-state.sh --self-test`
- Audit AskUserQuestion callsites (advisory):
  `bash scripts/lint-askuser.sh`
- Audit AskUserQuestion callsites (strict, exit 1 on unregistered):
  `bash scripts/lint-askuser.sh --strict`
- Check for slug collision before an overnight plan run:
  `bash scripts/overnight-preflight.sh check-collisions --chain "plan,test,implement-all" --base z-harness/plans/my-slug`
- Self-test the overnight preflight (8 assertions):
  `bash scripts/overnight-preflight.sh --self-test`
- Generate MORNING_REPORT.md for a slug:
  `python3 scripts/morning-report.py my-slug`
- Self-test morning-report against golden fixtures:
  `python3 scripts/morning-report.py --self-test`
- Run local preflight checks before a commit:
  `bash scripts/preflight.sh`
