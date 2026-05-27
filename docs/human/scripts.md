# Scripts

> Last updated: 2026-05-27
> Covers source: scripts/extract-dismissals.py, scripts/log-event.sh, scripts/log-phase.sh, scripts/regenerate-memories-flat.py, scripts/remote-sandbox-sync.sh, scripts/run-memory-review.sh, scripts/version.sh, scripts/config.py, scripts/config.sh, scripts/test_config.py

## Overview

The scripts concept covers the shell and Python utility scripts that form the operational backbone of the z-harness pipeline. They handle structured event telemetry (logging individual events and wrapping entire phases with start/end timing), memory document regeneration across all concept JSONs, plugin version introspection, the lifecycle gate logic for the memory-review agent, MR-review dismissal signature extraction across archived run snapshots, and rsync-based remote sandbox synchronization. All scripts reside in the `scripts/` directory at the repository root and are invoked directly by commands, skills, and subagents rather than being imported as libraries.

These scripts share a common dependency on `python3` — used for JSON serialization, millisecond-precision timing on macOS, and document generation — and on `git` — used to resolve the repository root, detect dirty state, and compute diffs. They honor the `Z_HARNESS_SLUG`, `Z_HARNESS_PLAN_DIR`, `ANTIGRAVITY_PLUGIN_ROOT`, `CLAUDE_PLUGIN_ROOT`, and `Z_HARNESS_PLUGIN_ROOT` environment variables to support both slug-namespaced and legacy flat plan layouts and to locate the plugin root across different host environments. `log-event.sh` sources `scripts/plan-path.sh` for canonical plan path resolution.

## Key entry points

- `scripts/log-event.sh:1` — `log-event.sh` — Appends a structured JSON event line to `<run>/events.jsonl` and the repo-wide `z-harness/metrics.jsonl`; uses `flock` when available for concurrent-safe appends.
- `scripts/log-phase.sh:1` — `log-phase.sh` — Sugar layer over `log-event.sh`; supports three modes: `start` (emits `<phase>_start`, returns an opaque timing token), `end` (emits `<phase>_end` with `wall_ms` merged in), and `wrap` (wraps an arbitrary command end-to-end and captures its exit code).
- `scripts/regenerate-memories-flat.py:1` — `regenerate-memories-flat.py` — Scans all `docs/llm/*.json` files (excluding `INDEX.json`), extracts `memories[]` entries, sorts them by slug ascending then date descending, and writes `docs/llm/MEMORIES-FLAT.md` atomically via a temp-file rename.
- `scripts/version.sh:1` — `version.sh` — Prints a single-line JSON blob with the plugin's git short-SHA, dirty flag, branch, and optional tag; used at `run_start` events for post-run correlation.
- `scripts/run-memory-review.sh:1` — `run-memory-review.sh` — Gate script called by `/z-implement-all`, `/z-review-all`, and `/z-debug`; accepts `<RUN> <parent_command>` (where `parent_command` is `implement-all`, `review-all`, or `debug`); evaluates skip conditions using a 4-state terminal taxonomy (`skipped_broken_context`, `not_applicable`, `ready`, `dispatched`), writes a truncated cumulative diff to the run archive, and prints artifact paths on stdout.
- `scripts/extract-dismissals.py:480` — `main` — CLI entry point; extracts dismissed MR-review or plan-style-audit finding signatures by comparing consecutive archived run snapshots; supports `--global` to scan all slugs and `--filename` to target alternate snapshot files (e.g. `PLAN_STYLE_AUDIT.md`); outputs `{"signatures": [...], "n_runs_scanned": N}` to stdout.
- `scripts/extract-dismissals.py:384` — `extract_dismissals_from_runs` — Core pairwise algorithm: for each consecutive run pair (R_i, R_{i+1}), compares R_i snapshot against R_{i+1}'s `.previous-*` user-edited copy to identify dismissed findings.
- `scripts/remote-sandbox-sync.sh:1` — `remote-sandbox-sync.sh` — Rsync the local working tree to a per-(slug, task-id) remote sandbox at `~/dev/qt-bot-sandbox/<slug>/<task-id>/`; invoked by the remote-runner agent before running cargo or qtctl on the remote host.
- `scripts/config.py:1` — `config.py` — Layered TOML config loader (slice 1: `notify.level`, `docs.always_apply`). See `config-design` concept for deep docs.
- `scripts/config.sh:1` — `config.sh` — Thin shell wrapper: `exec python3 scripts/config.py "$@"`. See `config-design` concept for deep docs.
- `scripts/test_config.py:1` — `test_config.py` — End-to-end smoke-test suite for `config.py` using hermetic `XDG_CONFIG_HOME` temp dirs. See `config-design` concept for deep docs.

## How it interacts with others

- `commands` — Every z-harness command that tracks execution time calls `log-phase.sh start`/`end`; `/z-plan`, `/z-implement-all`, `/z-implement-next`, `/z-review-all`, `/z-audit`, `/z-fix`, `/z-do`, `/z-uplift`, and `/z-maintain-docs` call `version.sh` and `log-event.sh` at run start and end events. `/z-mr-review` and `/z-audit-plan-style` call `extract-dismissals.py` to load prior dismissal signatures. `/z-style-init` calls `extract-dismissals.py --global` to seed a new reviewer with all known dismissals.
- `skills` — `/z-implement-all`, `/z-review-all`, and `/z-debug` skills call `run-memory-review.sh` (via `mapfile`) to gate the memory-review subagent; the helper emits the `memory_review_terminal` telemetry event on all skip paths using a 4-state taxonomy.
- `agents` — The remote-runner agent calls `remote-sandbox-sync.sh` before executing cargo or qtctl on the remote host; the doc-updater agent calls `log-phase.sh` and `log-event.sh` for doc-update telemetry; the memory-review agent receives artifact paths from `run-memory-review.sh`.
- `review-agent` — `run-memory-review.sh` is the dedicated lifecycle helper for the memory-review agent; on `STATUS: ready` it outputs five lines: the cumulative diff path, SPEC.md path (or empty if absent), TAGS.txt path, and (for `debug` parent only) the DEBUG.md path.
- `config-design` — `config.py` and `config.sh` implement the layered TOML config system; deep documentation, invariants, and test coverage live in the `config-design` concept.

## Edge cases / gotchas

- `run-memory-review.sh` uses a 4-state terminal taxonomy in `memory_review_terminal` events: `skipped_broken_context` (missing args, no plan dir, tags file absent), `not_applicable` (empty diff, all tasks skipped, debug_md missing), `ready` (orchestrator path — no terminal event emitted by this script), and `dispatched` (owned by orchestrator after review-agent returns).
- `run-memory-review.sh` accepts a mandatory second argument `parent_command` (`implement-all`, `review-all`, or `debug`). When `parent_command` is `debug`, an additional skip condition applies: if `DEBUG.md` is not readable in the plan base dir, the script exits with `STATUS: skipped debug_md_missing` and emits state `not_applicable`.
- `run-memory-review.sh` stdout contract: line 1 is always `STATUS: ready | STATUS: skipped <reason>`; if ready, lines 2-4 are absolute paths to `cumulative.diff`, `SPEC.md` (or empty string if missing), and `TAGS.txt`; line 5 is present only for the `debug` parent and holds the absolute path to `DEBUG.md`.
- `run-memory-review.sh` emits exactly one `memory_review_terminal` event per invocation (on all skip paths). The orchestrator owns the terminal event for non-skip paths.
- `run-memory-review.sh` contains a pure-bash JSON fallback in `_build_terminal_payload` for environments where `python3` is unavailable; this path avoids any external JSON library.
- The env var controlling the plan base dir is `Z_HARNESS_PLAN_DIR` (singular), not `Z_HARNESS_PLANS_DIR`.
- `log-phase.sh` uses a `python3` fallback (`time.time()*1000`) to get millisecond timestamps because macOS BSD `date` does not support the `%3N` format specifier.
- `log-event.sh` validates JSON payloads via `python3`; malformed payloads are silently wrapped in `{"raw": ...}` rather than failing.
- `log-event.sh` performs mid-flight legacy run detection: if a run directory already exists at the old flat layout path, it writes there instead of the slug-namespaced path, to avoid splitting a run's events across two locations.
- `run-memory-review.sh` uses `set +o pipefail` around the `git diff | head -n 5000` pipeline to avoid SIGPIPE failures when the diff is shorter than 5000 lines.
- `version.sh` resolves the plugin root via four environment variables in priority order: `Z_HARNESS_PLUGIN_ROOT`, `ANTIGRAVITY_PLUGIN_ROOT`, `CLAUDE_PLUGIN_ROOT`, then script-relative path walk. It gracefully degrades if the plugin root is not a git repo.
- `regenerate-memories-flat.py` writes atomically using `os.replace()` on a PID+random-suffixed temp file; a partial write will never corrupt the canonical `MEMORIES-FLAT.md`.
- `extract-dismissals.py` drops findings that lack a `title` field in the `findings_index` frontmatter; it does NOT fall back to the T-MR-NNN id as a snippet because those ids are renumbered each run.
- `extract-dismissals.py`'s `--filename` flag allows targeting `PLAN_STYLE_AUDIT.md` instead of the default `MR-REVIEW.md`; `--global` mode applies within each slug independently to prevent cross-slug run interleaving.
- `remote-sandbox-sync.sh` warns (but does not fail) when no `.z-harness-rsync-exclude` file is found; it checks the project root first, then the plugin root.

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
- Extract dismissal signatures globally across all slugs:
  `python3 scripts/extract-dismissals.py --global`
- Sync local working tree to remote sandbox:
  `bash scripts/remote-sandbox-sync.sh zeke-pc add-rate-limit T030`
- Resolve a config key (falls through to default if no config file exists):
  `python3 scripts/config.py get notify.level`
- Export all config keys as shell environment variables:
  `eval "$(python3 scripts/config.py export-env)"`
- Write the global config file with defaults if it does not exist:
  `python3 scripts/config.py ensure-defaults`
- Run the end-to-end config smoke tests:
  `python3 scripts/test_config.py`
