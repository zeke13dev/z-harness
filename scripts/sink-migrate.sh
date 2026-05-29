#!/usr/bin/env bash
# scripts/sink-migrate.sh — Schema migration driver for the follow-up sink.
#
# Usage:
#   sink-migrate.sh <sink-root> [--from=<N>] [--to=<N>]
#
# Arguments:
#   <sink-root>    Path to the sink directory (must contain index.jsonl).
#   --from=N       Source schema version (default: 1).
#   --to=N         Target schema version (default: 1).
#
# Exit codes:
#   0  success (migration completed or no-op because from==to)
#   1  usage / argument error
#   2  unsupported migration path (from→to not implemented)
#   4  must be called while global lock is held by caller (see sink-view-rebuild.sh)
#
# Migration contract
# ==================
# The follow-up sink uses append-only event sourcing: all state is derived by
# replaying index.jsonl through sink-view-reducer.py.  When the entry schema
# bumps from version N to version N+1, the migration path is:
#
#   1. Rebuild the materialized view (sink-view-rebuild.sh) so the reducer
#      picks up any new field defaults for existing events.
#   2. Write new events (or a special schema_migrated sentinel event) at the
#      new schema_version so future appends use the updated shape.
#   3. Append a "schema_migrated" event to index.jsonl to make the migration
#      auditable.  The event shape is:
#
#        {
#          "ts": "<ISO-8601-UTC>",
#          "kind": "schema_migrated",
#          "from_version": <N>,
#          "to_version": <M>,
#          "migrated_by": "scripts/sink-migrate.sh"
#        }
#
#   4. Any backfill of old entries (re-writing them at schema_version=M) is
#      done by appending corrective events, NEVER by editing existing lines in
#      index.jsonl.  The log is append-only; in-place edits break replay
#      determinism.
#
# For v1→v1 (the current version) this script is a documented no-op: it
# confirms the sink root exists and exits 0 with a message.  No event is
# appended because there is no actual migration to record.
#
# The script MUST be called with the global lock already held by the caller
# (same requirement as sink-view-rebuild.sh).  It verifies this using the
# same dual JSON-content / OS-flock sentinel check.

set -euo pipefail

# ── paths ─────────────────────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ── argument parsing ───────────────────────────────────────────────────────────
if [[ $# -lt 1 ]]; then
    echo "usage: sink-migrate.sh <sink-root> [--from=N] [--to=N]" >&2
    exit 1
fi

SINK_ROOT="$1"
FROM_VERSION=1
TO_VERSION=1

for arg in "${@:2}"; do
    case "$arg" in
        --from=*)  FROM_VERSION="${arg#--from=}" ;;
        --to=*)    TO_VERSION="${arg#--to=}" ;;
        *)
            echo "sink-migrate: unknown argument: $arg" >&2
            exit 1
            ;;
    esac
done

# Validate versions are integers before any arithmetic comparison — otherwise
# `[[ "$FROM_VERSION" -eq ... ]]` crashes under `set -u`/`set -e` instead of
# giving a clean usage error.
if ! [[ "$FROM_VERSION" =~ ^[0-9]+$ ]]; then
    echo "sink-migrate: --from must be a non-negative integer: $FROM_VERSION" >&2
    exit 1
fi
if ! [[ "$TO_VERSION" =~ ^[0-9]+$ ]]; then
    echo "sink-migrate: --to must be a non-negative integer: $TO_VERSION" >&2
    exit 1
fi

# ── validate sink root ────────────────────────────────────────────────────────
if [[ ! -d "$SINK_ROOT" ]]; then
    echo "sink-migrate: sink root does not exist: $SINK_ROOT" >&2
    exit 1
fi

if [[ ! -f "$SINK_ROOT/index.jsonl" ]]; then
    echo "sink-migrate: no index.jsonl found in sink root: $SINK_ROOT" >&2
    exit 1
fi

# ── lock-file resolution ──────────────────────────────────────────────────────
LOCK_FILE="${Z_HARNESS_FOLLOWUP_GLOBAL_LOCK:-${HOME}/.z-harness/.followup-vs-implement.lock}"
mkdir -p "$(dirname "$LOCK_FILE")"
SENTINEL="${LOCK_FILE}.flock"
touch "$SENTINEL"

# ── lock-held check via JSON content OR OS flock ─────────────────────────────
# exit 4 = "lock is held" (proceed); exit 0 = "lock is free" (refuse).
# Mirrors the identical check in sink-view-rebuild.sh.
set +e
python3 - "$LOCK_FILE" "$SENTINEL" <<'PYEOF'
import sys, os, fcntl, json
from pathlib import Path

lock_path = Path(sys.argv[1])
sentinel_path = sys.argv[2]

# Check 1: JSON content — non-empty file with a "holder" field means held.
try:
    content = lock_path.read_text(encoding="utf-8").strip()
except OSError:
    content = ""

if content:
    try:
        data = json.loads(content)
        if data and data.get("holder"):
            sys.exit(4)   # 4 = "lock is held" via JSON
    except json.JSONDecodeError:
        pass  # corrupt — fall through to flock check

# Check 2: OS flock sentinel — if we CANNOT acquire LOCK_EX|LOCK_NB, someone holds it.
fd = os.open(sentinel_path, os.O_CREAT | os.O_RDWR, 0o644)
try:
    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    # Acquired → lock was free → refuse
    fcntl.flock(fd, fcntl.LOCK_UN)
    os.close(fd)
    sys.exit(0)   # 0 = "lock is free"
except OSError:
    # Could not acquire → someone else holds OS flock → okay to proceed
    os.close(fd)
    sys.exit(4)   # 4 = "lock is held" via OS flock
PYEOF
LOCK_STATUS=$?
set -e

# Accept ONLY the explicit "lock is held" signal (4). Anything else — "free" (0)
# or an unexpected interpreter error (1/3/…) — fails closed rather than falling
# through as if the lock were held.
if [[ $LOCK_STATUS -ne 4 ]]; then
    echo "sink-migrate: ERROR: must be called while global lock is held by caller" >&2
    echo "  lock check returned status ${LOCK_STATUS} (expected 4=held)" >&2
    echo "  lock sentinel: ${SENTINEL}" >&2
    exit 4
fi
# LOCK_STATUS == 4 → lock is held by caller → proceed.
# NOTE: the JSON-content check above trusts any non-empty `holder` field (same
# as sink-view-rebuild.sh). A future real-migration branch that MUTATES the
# journal must additionally validate holder/pid liveness under .hb.lock before
# writing — a stale JSON record alone is not proof of a live caller.

# ── migration dispatch ────────────────────────────────────────────────────────
if [[ "$FROM_VERSION" -eq "$TO_VERSION" ]]; then
    echo "sink-migrate: no migration needed (schema_version=${FROM_VERSION} is current; no-op)" >&2
    exit 0
fi

# Future migration implementations go here.  Each bump adds a branch of the
# form:
#
#   if [[ "$FROM_VERSION" -eq 1 && "$TO_VERSION" -eq 2 ]]; then
#       # 1. Rebuild the view so the reducer picks up v2 defaults.
#       bash "$SCRIPT_DIR/sink-view-rebuild.sh" "$SINK_ROOT"
#       # 2. Backfill / transform entries by appending corrective events (NEVER
#       #    editing existing JSONL lines).
#       # ...
#       # 3. Append the schema_migrated sentinel.
#       python3 - "$SINK_ROOT" 1 2 <<'EOF'
#   import json, sys
#   from datetime import datetime, timezone
#   from pathlib import Path
#   now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
#   event = {"ts": now, "kind": "schema_migrated",
#            "from_version": int(sys.argv[2]), "to_version": int(sys.argv[3]),
#            "migrated_by": "scripts/sink-migrate.sh"}
#   sink_root = Path(sys.argv[1])
#   with (sink_root / "index.jsonl").open("a", encoding="utf-8") as fh:
#       fh.write(json.dumps(event, separators=(",", ":")) + "\n")
# EOF
#       exit 0
#   fi

echo "sink-migrate: unsupported migration path: ${FROM_VERSION}→${TO_VERSION}" >&2
echo "  Add an implementation branch in scripts/sink-migrate.sh" >&2
exit 2
