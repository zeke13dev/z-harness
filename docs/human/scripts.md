# Scripts

> Last updated: 2026-05-27
> Covers source: scripts/extract-dismissals.py, scripts/log-event.sh, scripts/log-phase.sh, scripts/regenerate-memories-flat.py, scripts/remote-sandbox-sync.sh, scripts/run-memory-review.sh, scripts/version.sh, scripts/config.py, scripts/config.sh, scripts/propose-prefs.py, scripts/test_config.py, scripts/scope-probe-calibrate.py, scripts/CALIBRATION.md, scripts/test-scope-probe-calibrate.py

## Overview

The scripts concept covers the shell and Python utility scripts that form the operational backbone of the z-harness pipeline. They handle structured event telemetry (logging individual events and wrapping entire phases with start/end timing), memory document regeneration across all concept JSONs, plugin version introspection, the lifecycle gate logic for the memory-review agent, MR-review dismissal signature extraction across archived run snapshots, rsync-based remote sandbox synchronization, and the calibration harness for the scope-probe classifier. The layered TOML config loader (`config.py`) has grown significantly: it now exposes `resolve-question`, `set`, and `list-question-ids` subcommands backed by a `QUESTION_IDS` registry, a `RESULT_MAP` lookup table, and startup guards that enforce registry consistency at module load. A new `propose-prefs.py` script detects repeated command-pair patterns in `metrics.jsonl` and emits a JSON proposal when a user's repetition count crosses a threshold.

These scripts share a common dependency on `python3` (used for JSON serialization, millisecond-precision timing on macOS, and document generation) and on `git` (used to resolve the repository root, detect dirty state, and compute diffs). They honor the `Z_HARNESS_SLUG`, `Z_HARNESS_PLAN_DIR`, `ANTIGRAVITY_PLUGIN_ROOT`, `CLAUDE_PLUGIN_ROOT`, and `Z_HARNESS_PLUGIN_ROOT` environment variables to support both slug-namespaced and legacy flat plan layouts and to locate the plugin root across different host environments. `log-event.sh` sources `scripts/plan-path.sh` for canonical plan path resolution.

## Key entry points

- `scripts/log-event.sh:1` — `log-event.sh` — Appends a structured JSON event line to `<run>/events.jsonl` and the repo-wide `z-harness/metrics.jsonl`; uses `flock` when available for concurrent-safe appends.
- `scripts/log-phase.sh:1` — `log-phase.sh` — Sugar layer over `log-event.sh`; supports three modes: `start` (emits `<phase>_start`, returns an opaque timing token), `end` (emits `<phase>_end` with `wall_ms` merged in), and `wrap` (wraps an arbitrary command end-to-end and captures its exit code).
- `scripts/regenerate-memories-flat.py:1` — `regenerate-memories-flat.py` — Scans all `docs/llm/*.json` files (excluding `INDEX.json`), extracts `memories[]` entries, sorts them by slug ascending then date descending, and writes `docs/llm/MEMORIES-FLAT.md` atomically via a temp-file rename.
- `scripts/version.sh:1` — `version.sh` — Prints a single-line JSON blob with the plugin's git short-SHA, dirty flag, branch, and optional tag; used at `run_start` events for post-run correlation.
- `scripts/run-memory-review.sh:1` — `run-memory-review.sh` — Gate script called by `/z-implement-all`, `/z-review-all`, and `/z-debug`; accepts `<RUN> <parent_command>` (where `parent_command` is `implement-all`, `review-all`, or `debug`); evaluates skip conditions using a 4-state terminal taxonomy (`skipped_broken_context`, `not_applicable`, `ready`, `dispatched`), writes a truncated cumulative diff to the run archive, and prints artifact paths on stdout.
- `scripts/extract-dismissals.py:480` — `main` — CLI entry point; extracts dismissed MR-review or plan-style-audit finding signatures by comparing consecutive archived run snapshots; supports `--global` to scan all slugs and `--filename` to target alternate snapshot files (e.g. `PLAN_STYLE_AUDIT.md`); outputs `{"signatures": [...], "n_runs_scanned": N}` to stdout.
- `scripts/extract-dismissals.py:384` — `extract_dismissals_from_runs` — Core pairwise algorithm: for each consecutive run pair (R_i, R_{i+1}), compares R_i snapshot against R_{i+1}'s `.previous-*` user-edited copy to identify dismissed findings.
- `scripts/remote-sandbox-sync.sh:1` — `remote-sandbox-sync.sh` — Rsync the local working tree to a per-(slug, task-id) remote sandbox at `~/dev/qt-bot-sandbox/<slug>/<task-id>/`; invoked by the remote-runner agent before running cargo or qtctl on the remote host.
- `scripts/config.py:1` — `config.py` — Layered TOML config loader with subcommands: `get`, `export-env`, `ensure-defaults`, `explain`, `should-notify`, `list-question-ids`, `resolve-question`, and `set`. The `QUESTION_IDS` registry is the single source of truth for question routing; `RESULT_MAP` maps `(question_id, option_value)` pairs to resolver result-domain values (`ask`, `skip`, `prefill`). Startup guards fire at module load and exit 2 if the registry is internally inconsistent.
- `scripts/config.sh:1` — `config.sh` — Thin shell wrapper: `exec python3 scripts/config.py "$@"`. See `config` concept for deep docs.
- `scripts/propose-prefs.py:1` — `propose-prefs.py` — Scans `metrics.jsonl` for repeated command-pair patterns (e.g., `z-audit-plan` always followed by `z-amend` within an hour on the same slug) and emits a single JSON proposal `{question_id, proposed_value, evidence, scope_recommendation}` to stdout when the repetition count reaches a threshold. Called with `--check <command-name>` at the end of certain commands. Never blocks or crashes the calling command (wraps main in a bare except that exits 0).
- `scripts/test_config.py:1` — `test_config.py` — End-to-end smoke-test suite for `config.py` using hermetic `XDG_CONFIG_HOME` temp dirs. See `config` concept for deep docs.
- `scripts/scope-probe-calibrate.py:373` — `main` — CLI entry point for the scope-probe calibration harness; walks `z-harness/*/archive/*/` runs that have `manifest.json`, computes ground-truth LIGHT/MEDIUM/HEAVY labels per CALIBRATION.md rubric_version 1, dispatches the scope-probe N times per run (or reads a fixture file in `--fixture-mode`), applies majority vote, prints a confusion matrix and tripwire report, and emits `scripts/calibration-epoch-<N>.json` atomically.
- `scripts/scope-probe-calibrate.py:36` — `classify_ground_truth` — Implements the rubric_version 1 classification rule: HEAVY if any `escalation_*` event or `tasks_total >= 16`; LIGHT if `tasks_total <= 5` AND `tasks_complexity.high == 0` AND no `plan_route_decision` event; MEDIUM otherwise.
- `scripts/CALIBRATION.md:1` — `CALIBRATION.md` — Human-readable canonical reference for the ground-truth classification rubric. When the Python implementation and this document conflict, this document wins.
- `scripts/test-scope-probe-calibrate.py:308` — `main` — Unit test runner for `scope-probe-calibrate.py`; loads the production module via `importlib` (bypassing the hyphenated filename), runs six test suites; exits 0 on full pass, 1 on any failure.

## How it interacts with others

- `commands` — Every z-harness command that tracks execution time calls `log-phase.sh start`/`end`. `/z-plan`, `/z-implement-all`, `/z-implement-next`, `/z-review-all`, `/z-audit`, `/z-fix`, `/z-do`, `/z-uplift`, and `/z-maintain-docs` call `version.sh` and `log-event.sh` at run start/end events. `/z-mr-review` and `/z-audit-plan-style` call `extract-dismissals.py` to load prior dismissal signatures. `/z-style-init` calls `extract-dismissals.py --global` to seed a new reviewer. `/z-audit-plan`, `/z-audit-plan-style`, and `/z-amend` call `propose-prefs.py --check <command-name>` after execution. `/z-plan`, `/z-fix`, `/z-audit-plan`, `/z-audit-plan-style`, and `/z-uplift` call `config.py resolve-question` to determine whether to show or skip workflow confirmation prompts; `/z-audit-plan` also calls `config.py set` to apply accepted preference proposals.
- `skills` — `/z-implement-all`, `/z-review-all`, and `/z-debug` skills call `run-memory-review.sh` (via `mapfile`) to gate the memory-review subagent. The `z-plan-light` skill calls `config.py resolve-question workflow.slug_confirm`. The `z-brainstorm`, `z-map`, `z-debug` skills call `config.py resolve-question workflow.slug_confirm`.
- `agents` — The remote-runner agent calls `remote-sandbox-sync.sh` before executing cargo or qtctl on the remote host; the doc-updater agent calls `log-phase.sh` and `log-event.sh` for doc-update telemetry; the memory-review agent receives artifact paths from `run-memory-review.sh`.
- `review-agent` — `run-memory-review.sh` is the dedicated lifecycle helper for the memory-review agent; on `STATUS: ready` it outputs five lines: the cumulative diff path, SPEC.md path (or empty if absent), TAGS.txt path, and (for `debug` parent only) the DEBUG.md path.
- `config` — `config.py` and `config.sh` implement the layered TOML config system + workflow resolver; deep documentation, invariants, and test coverage live in the `config` concept.
- `z-suggest-memory` — When a `resolve-question` result source is `memory` or `conflict`, the calling command may dispatch `/z-suggest-memory --kind routing-preference` to author or update routing-preference memory entries that `config.py resolve-question` reads via `_load_memory_matches`.
- `scope-probe` (future) — `scope-probe-calibrate.py` is the calibration harness for the scope-probe classifier concept; `dispatch_scope_probe_stub` currently returns MEDIUM as a placeholder until T014 integrates scope-probe as a real subprocess.

## Edge cases / gotchas

- `config.py` startup guards run at module load time via `_run_startup_guards()`. They enforce: every key in `QUESTION_IDS` must exist in `VALIDATORS`; every `QUESTION_IDS` entry must have a non-null `skill_default`; every `(question_id, choice)` key in `RESULT_MAP` must reference a known question_id and a valid choice. Violations exit 2 immediately.
- `config.py resolve-question` returns a JSON envelope with `result` in `{ask, skip, prefill}` (the resolver result-domain), not the option-domain value. The `RESULT_MAP` handles translation. Callers must parse stdout as JSON and must not assume the config option value equals the result value.
- `config.py resolve-question` honors `Z_HARNESS_ASK_ALL=1` as a short-circuit that forces `result: ask` regardless of config or memory. `Z_HARNESS_EXPLAIN_RESOLUTION=1` activates verbose explain output on stderr.
- `config.py resolve-question` reads `routing-preference` memory entries from `docs/llm/*.json` (harness-relative, not project-relative) and uses `Z_HARNESS_PROJECT_ROOT` or `git rev-parse` to determine project scope for `scope: project` entries. Outside a git repo, all entries are treated as global.
- `config.py set` performs a read-modify-write using atomic temp-file rename. It validates the key against `_KEY_RE` and `VALIDATORS` before writing; exits 2 on validation failure, 4 on I/O error.
- `propose-prefs.py` is invoked with `--check <command-name>` at the end of certain commands. It reads `metrics.jsonl`, identifies the last `max_runs` run boundaries, detects `(cmd_a, cmd_b)` pairs on the same slug within a time window, and proposes when count reaches the threshold. It checks `.z-harness/.propose-suppress` for per-question-id suppression entries. It emits at most one proposal per invocation and exits 0 always.
- `propose-prefs.py` scope recommendation logic: if detected pairs span more than one `project_root`, recommends `global`; if all are in the current project root, recommends `project`. The calling command is responsible for presenting the proposal and dispatching `/z-suggest-memory` or `config.py set`.
- `run-memory-review.sh` uses a 4-state terminal taxonomy in `memory_review_terminal` events: `skipped_broken_context` (missing args, no plan dir, tags file absent), `not_applicable` (empty diff, all tasks skipped, debug_md missing), `ready` and `dispatched` are orchestrator-owned.
- `run-memory-review.sh` stdout contract: line 1 is always `STATUS: ready | STATUS: skipped <reason>`; if ready, lines 2-4 are absolute paths to `cumulative.diff`, `SPEC.md` (or empty string if missing), and `TAGS.txt`; line 5 is present only for the `debug` parent and holds the absolute path to `DEBUG.md`.
- `run-memory-review.sh` emits exactly one `memory_review_terminal` event per invocation (on all skip paths). The orchestrator owns the terminal event for non-skip paths.
- `run-memory-review.sh` contains a pure-bash JSON fallback in `_build_terminal_payload` for environments where `python3` is unavailable.
- The env var controlling the plan base dir is `Z_HARNESS_PLAN_DIR` (singular), not `Z_HARNESS_PLANS_DIR`.
- `log-phase.sh` uses a `python3` fallback (`time.time()*1000`) to get millisecond timestamps because macOS BSD `date` does not support the `%3N` format specifier.
- `log-event.sh` validates JSON payloads via `python3`; malformed payloads are silently wrapped in `{"raw": ...}` rather than failing.
- `log-event.sh` performs mid-flight legacy run detection: if a run directory already exists at the old flat layout path, it writes there instead of the slug-namespaced path.
- `run-memory-review.sh` uses `set +o pipefail` around the `git diff | head -n 5000` pipeline to avoid SIGPIPE failures when the diff is shorter than 5000 lines.
- `version.sh` resolves the plugin root via four environment variables in priority order: `Z_HARNESS_PLUGIN_ROOT`, `ANTIGRAVITY_PLUGIN_ROOT`, `CLAUDE_PLUGIN_ROOT`, then script-relative path walk.
- `regenerate-memories-flat.py` writes atomically using `os.replace()` on a PID+random-suffixed temp file.
- `extract-dismissals.py` drops findings that lack a `title` field; it does NOT fall back to T-MR-NNN ids (renumbered each run).
- `extract-dismissals.py` `--global` mode applies within each slug independently to prevent cross-slug run interleaving.
- `remote-sandbox-sync.sh` warns (but does not fail) when no `.z-harness-rsync-exclude` file is found.
- `scope-probe-calibrate.py` exits 0 when no tripwires fire and exits 1 when at least one fires; exits 0 (with message) when no runs with `manifest.json` are found.
- `scope-probe-calibrate.py` `dispatch_scope_probe_stub` always returns MEDIUM — placeholder pending T014.
- `test-scope-probe-calibrate.py` uses `importlib.util.spec_from_file_location` to import `scope-probe-calibrate.py` because the hyphenated filename prevents a plain `import` statement.
- Tripwire 1 fires when `pct_medium >= 70%`; Tripwire 2 fires when `pct_heavy < 20%`; Tripwires 3 and 4 are manual-review-only.

## Examples

- Start a named phase and capture the timing token:
  `TOKEN="$(bash scripts/log-phase.sh start "tasks/T020" precheck '{"id":"T020"}')"`
- End the phase with status:
  `bash scripts/log-phase.sh end "$TOKEN" '{"status":"ok","references_checked":11}'`
- Wrap a command end-to-end (auto-times and logs exit code):
  `bash scripts/log-phase.sh wrap "tasks/T020" cargo_test '{}' -- cargo test --release`
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
- Sync local working tree to remote sandbox:
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
- Set a config key in the project scope:
  `python3 scripts/config.py set workflow.audit_to_amend amend --scope=project`
- Check for a preference proposal after z-audit-plan completes:
  `PROPOSE_OUT="$(python3 scripts/propose-prefs.py --check z-audit-plan 2>/dev/null)"`
- Run the end-to-end config smoke tests:
  `python3 scripts/test_config.py`
- Run the scope-probe calibration harness in fixture mode:
  `python3 scripts/scope-probe-calibrate.py --archive-root z-harness --epoch 1 --n-runs 6 --samples-per-run 3 --fixture-mode scripts/fixtures/t007-fixture.json`
- Run the unit tests for the calibration harness:
  `python3 scripts/test-scope-probe-calibrate.py`
