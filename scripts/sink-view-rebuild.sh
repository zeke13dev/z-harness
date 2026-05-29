#!/usr/bin/env bash
# scripts/sink-view-rebuild.sh — replays index.jsonl into index.view.json
#
# Usage:
#   sink-view-rebuild.sh <sink-root> [--repair] [--full]
#
# Options:
#   --repair  Pass through to sink-view-reducer.py: strip a broken trailing
#             line from index.jsonl (logging what was dropped) and rebuild
#             the view. Only a truncated TAIL is repairable; interior
#             corruption hard-errors even under --repair.
#   --full    Pass through to sink-view-reducer.py: force a full cold replay,
#             ignoring any existing checkpoint (the rebuilt view still carries
#             a fresh checkpoint).
#
# Environment:
#   Z_HARNESS_FOLLOWUP_GLOBAL_LOCK  path to the global cross-tool lock file
#                                   (default: ~/.z-harness/.followup-vs-implement.lock)
#
# Exit codes:
#   0  success
#   1  usage / argument error
#   3  journal corruption detected (propagated from reducer)
#   4  not invoked under global lock (lock is free; caller must hold it)
#
# The script MUST be called with the global lock already held by the caller.
# It verifies the lock is held using two complementary checks (either is sufficient):
#
#   1. JSON content check: the lock file contains non-empty JSON with a "holder" field.
#      This is the primary check; it is compatible with sink-lock.sh's JSON-based
#      bookkeeping where "held" state is represented by non-empty JSON.
#
#   2. OS flock check: a non-blocking exclusive flock on the .flock sentinel FAILS
#      (EWOULDBLOCK), meaning another process holds it.  This is a legacy compat
#      check for callers that hold the OS flock directly (e.g. the T005 test harness
#      and sink-claim.sh before it was updated to use sink-lock.sh).
#
# If either check indicates the lock is held, the script proceeds.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REDUCER_PY="${SCRIPT_DIR}/sink-view-reducer.py"

# ── argument check ────────────────────────────────────────────────────────────
if [[ $# -lt 1 ]]; then
    echo "usage: sink-view-rebuild.sh <sink-root> [--repair] [--full]" >&2
    exit 1
fi

SINK_ROOT="$1"
shift
REDUCER_FLAGS=()
for arg in "$@"; do
    case "$arg" in
        --repair|--full)
            REDUCER_FLAGS+=("$arg")
            ;;
        *)
            echo "sink-view-rebuild: ERROR: unknown argument '$arg'" >&2
            echo "usage: sink-view-rebuild.sh <sink-root> [--repair] [--full]" >&2
            exit 1
            ;;
    esac
done

# ── lock-file resolution ──────────────────────────────────────────────────────
LOCK_FILE="${Z_HARNESS_FOLLOWUP_GLOBAL_LOCK:-${HOME}/.z-harness/.followup-vs-implement.lock}"

# Ensure the lock file's parent directory and the sentinel file exist
mkdir -p "$(dirname "$LOCK_FILE")"
SENTINEL="${LOCK_FILE}.flock"
touch "$SENTINEL"

# ── lock-held check via JSON content OR OS flock ─────────────────────────────
# exit 4 = "lock is held" (proceed); exit 0 = "lock is free" (refuse)
#
# NOTE: `set -e` would abort on non-zero, so disable temporarily.
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

if [[ $LOCK_STATUS -eq 0 ]]; then
    echo "sink-view-rebuild: ERROR: must be called while global lock is held by caller" >&2
    echo "  lock sentinel: ${SENTINEL}" >&2
    exit 4
fi
# LOCK_STATUS == 4 → lock is held by caller → proceed

# ── delegate to Python reducer ────────────────────────────────────────────────
exec python3 "$REDUCER_PY" "$SINK_ROOT" ${REDUCER_FLAGS[@]+"${REDUCER_FLAGS[@]}"}
