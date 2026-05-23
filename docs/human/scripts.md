# Scripts

> Last updated: 2026-05-23
> Covers source: scripts/log-event.sh, scripts/log-phase.sh, scripts/regenerate-memories-flat.py, scripts/remote-sandbox-sync.sh, scripts/version.sh

## Overview
The scripts concept contains shell and Python scripts used for versioning, telemetry logging, workspace synchronization, and document generation. These utilities orchestrate core operations of the planning and implementation pipeline.

These scripts reside in the scripts directory at the project root and provide foundational capabilities like structured logging of execution events, tracking phase transitions, compiling memories across concepts, synchronizing workspaces to remote host sandboxes for testing, and fetching version metadata.

## Key entry points
- `scripts/log-event.sh:1` — `log-event.sh` — Bash script to append standard JSON events to run and global logs.
- `scripts/log-phase.sh:1` — `log-phase.sh` — Bash script to log process start/end and handle timing telemetry.
- `scripts/regenerate-memories-flat.py:1` — `regenerate-memories-flat.py` — Python script compiling memories across concepts into MEMORIES-FLAT.md.
- `scripts/remote-sandbox-sync.sh:1` — `remote-sandbox-sync.sh` — Bash script mapping local files to remote testing VM via rsync.
- `scripts/version.sh:1` — `version.sh` — Bash script providing git-anchored plugin version JSON.

## How it interacts with others
- `commands` — Several commands invoke scripts to log event telemetry, track time-in-phase metrics, and synchronize remote files before test suites run.
- `skills` — Action steps within planning, implementation, and maintenance skills run scripts directly to log phase boundaries, capture exit codes, and compile memories.
- `agents` — Subagents use logging and synchronization scripts to report progress and prepare remote execution environments.

## Edge cases / gotchas
- Timing relies on a python3 fallback inside `log-phase.sh` to obtain millisecond precision when the host macOS BSD `date` command lacks support for the `%3N` format.
- Exclude lists are checked in a specific priority order in `remote-sandbox-sync.sh`: first the repository override, then the plugin default.

## Examples
- Logging a start event:
  `TOKEN="$(scripts/log-phase.sh start docs/scripts init_docs_start '{"reason": "init"}')"`
- Ending the logged phase:
  `scripts/log-phase.sh end "$TOKEN" '{"status": "ok"}'`
