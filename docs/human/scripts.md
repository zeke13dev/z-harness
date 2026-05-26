# Scripts

> Last updated: 2026-05-25
> Covers source: scripts/log-event.sh, scripts/log-phase.sh, scripts/regenerate-memories-flat.py, scripts/remote-sandbox-sync.sh, scripts/version.sh, scripts/run-memory-review.sh, scripts/extract-dismissals.py

## Overview

The scripts concept covers the shell and Python utility scripts that form the operational backbone of the z-harness pipeline. They handle structured event telemetry (logging individual events and wrapping entire phases with start/end timing), workspace synchronization to remote test sandboxes via rsync, memory document regeneration across all concept JSONs, plugin version introspection, and lifecycle gate logic for the memory-review agent. All scripts reside in the `scripts/` directory at the repository root and are invoked directly by commands, skills, and subagents rather than being imported as libraries.

These scripts share a common dependency on `python3` — used for JSON serialization, millisecond-precision timing on macOS, and document generation — and on `git` — used to resolve the repository root, detect dirty state, and compute diffs. They honor the `Z_HARNESS_SLUG`, `Z_HARNESS_PLANS_DIR`, `ANTIGRAVITY_PLUGIN_ROOT`, and `CLAUDE_PLUGIN_ROOT` environment variables to support both slug-namespaced and legacy flat plan layouts and to locate the plugin root across different host environments.

## Key entry points

- `scripts/log-event.sh:1` — `log-event.sh` — Appends a structured JSON event line to `<run>/events.jsonl` and the repo-wide `z-harness/metrics.jsonl`; uses `flock` when available for concurrent-safe appends.
- `scripts/log-phase.sh:1` — `log-phase.sh` — Sugar layer over `log-event.sh`; supports three modes: `start` (emits `<phase>_start`, returns an opaque timing token), `end` (emits `<phase>_end` with `wall_ms` merged in), and `wrap` (wraps an arbitrary command end-to-end and captures its exit code).
- `scripts/regenerate-memories-flat.py:1` — `regenerate-memories-flat.py` — Scans all `docs/llm/*.json` files (excluding `INDEX.json`), extracts `memories[]` entries, sorts them by slug ascending then date descending, and writes `docs/llm/MEMORIES-FLAT.md` atomically via a temp-file rename.
- `scripts/remote-sandbox-sync.sh:1` — `remote-sandbox-sync.sh` — Rsyncs the local working tree to `~/dev/qt-bot-sandbox/<slug>/<task-id>/` on a remote host; looks up an exclude file in the project root first, then in the plugin root.
- `scripts/version.sh:1` — `version.sh` — Prints a single-line JSON blob with the plugin's git short-SHA, dirty flag, branch, and optional tag; used at `run_start` events for post-run correlation.
- `scripts/run-memory-review.sh:1` — `run-memory-review.sh` — Gate script called by `/z-implement-all` and `/z-review-all`; evaluates skip conditions (empty diff, zero completed tasks, missing `TAGS.txt`), writes a truncated cumulative diff to the run archive, and prints artifact paths for the review agent.
- `scripts/extract-dismissals.py:1` — `extract-dismissals.py` — Mines historical review artifacts to extract dismissed finding patterns for the dismissal-pattern-match pipeline.

## How it interacts with others

- `commands` — Every z-harness command that tracks execution time calls `log-phase.sh start`/`end`; commands that drive remote test runs call `remote-sandbox-sync.sh`; `/z-plan`, `/z-implement-all`, `/z-implement-next`, and `/z-review-all` call `version.sh` at `run_start`.
- `skills` — Skills invoke `log-phase.sh` and `log-event.sh` directly from their telemetry steps; `/z-implement-all` and `/z-review-all` call `run-memory-review.sh` to gate the memory-review subagent.
- `agents` — The remote-runner subagent calls `remote-sandbox-sync.sh` before executing cargo or qtctl on the remote host; the doc-updater calls `log-phase.sh`/`log-event.sh` for doc-update telemetry; the memory-review agent receives artifact paths from `run-memory-review.sh`; the mr-reviewer consumes dismissal patterns produced by `extract-dismissals.py`.
- `review-agent` — `run-memory-review.sh` is the dedicated lifecycle helper for the memory-review agent; it resolves all three artifact paths (`cumulative.diff`, `SPEC.md`, `TAGS.txt`) that the agent requires.

## Edge cases / gotchas

- `log-phase.sh` uses a `python3` fallback (`time.time()*1000`) to get millisecond timestamps because macOS BSD `date` does not support the `%3N` format specifier.
- `log-event.sh` validates JSON payloads via `python3`; malformed payloads are silently wrapped in `{"raw": ...}` rather than failing.
- `log-event.sh` performs mid-flight legacy run detection: if a run directory already exists at the old flat layout path, it writes there instead of the slug-namespaced path, to avoid splitting a run's events across two locations.
- `remote-sandbox-sync.sh` warns to stderr (but does not fail) when no `.z-harness-rsync-exclude` file is found in either lookup location.
- `run-memory-review.sh` uses `set +o pipefail` around the `git diff | head -n 5000` pipeline to avoid SIGPIPE failures when the diff is shorter than 5000 lines.
- `version.sh` resolves the plugin root via four environment variables in priority order: `Z_HARNESS_PLUGIN_ROOT`, `ANTIGRAVITY_PLUGIN_ROOT`, `CLAUDE_PLUGIN_ROOT`, then script-relative path walk. It gracefully degrades if the plugin root is not a git repo.
- `regenerate-memories-flat.py` writes atomically using `os.replace()` on a PID+random-suffixed temp file; a partial write will never corrupt the canonical `MEMORIES-FLAT.md`.

## Examples

- Start a named phase and capture the timing token:
  `TOKEN="$(bash scripts/log-phase.sh start "tasks/T020" precheck '{"id":"T020"}')"`
- End the phase with status:
  `bash scripts/log-phase.sh end "$TOKEN" '{"status":"ok","references_checked":11}'`
- Wrap a command end-to-end (auto-times and logs exit code):
  `bash scripts/log-phase.sh wrap "tasks/T020" cargo_test '{}' -- cargo test --release`
- Regenerate the flat memory index in dry-run mode:
  `python3 scripts/regenerate-memories-flat.py --repo-root /path/to/repo --dry-run`
- Sync to remote sandbox:
  `bash scripts/remote-sandbox-sync.sh zeke-pc expand-sports-ml T030`
- Gate the memory-review agent (called from /z-implement-all):
  `bash scripts/run-memory-review.sh "$RUN" implement-all`
