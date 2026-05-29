#!/usr/bin/env bash
# scripts/sink-compact.sh — log compaction for the follow-up sink.
#
# Usage:
#   sink-compact.sh <sink-root>
#
# Replays index.jsonl once, archives events for terminal (done/dismissed)
# entries into index.archive.jsonl, rewrites index.jsonl with only non-
# terminal events, invalidates the T010 checkpoint by removing index.view.json,
# and runs a fresh --full rebuild so the view and checkpoint are correct.
#
# Environment:
#   Z_HARNESS_FOLLOWUP_GLOBAL_LOCK  path to the global cross-tool lock file
#                                   (default: ~/.z-harness/.followup-vs-implement.lock)
#
# Exit codes:
#   0  success (or no-op: no terminal entries found)
#   1  usage / argument error
#   2  sink-root not found or not a directory
#   3  journal corruption detected; no changes made
#   4  not invoked under global lock (lock is free; caller must hold it)
#
# The script MUST be called with the global lock already held by the caller.
# It verifies the lock using the same dual-check as sink-view-rebuild.sh:
#   1. JSON content check: lock file contains non-empty JSON with a "holder" field.
#   2. OS flock check: a non-blocking exclusive flock on the .flock sentinel FAILS
#      (EWOULDBLOCK), meaning another process holds it.
# If either check indicates the lock is held, the script proceeds.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
IMPL_PY="${SCRIPT_DIR}/sink-compact-impl.py"

# ── argument check ────────────────────────────────────────────────────────────
if [[ $# -lt 1 ]]; then
    echo "usage: sink-compact.sh <sink-root>" >&2
    exit 1
fi

SINK_ROOT="$1"

# ── lock-file resolution ──────────────────────────────────────────────────────
LOCK_FILE="${Z_HARNESS_FOLLOWUP_GLOBAL_LOCK:-${HOME}/.z-harness/.followup-vs-implement.lock}"

# Ensure the lock file's parent directory and the sentinel file exist
mkdir -p "$(dirname "$LOCK_FILE")"
SENTINEL="${LOCK_FILE}.flock"
touch "$SENTINEL"

# ── lock-held check via JSON content OR OS flock ─────────────────────────────
# exit 4 = "lock is held" (proceed); exit 0 = "lock is free" (refuse)
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
    echo "sink-compact: ERROR: must be called while global lock is held by caller" >&2
    echo "  lock sentinel: ${SENTINEL}" >&2
    exit 4
fi
# LOCK_STATUS == 4 → lock is held by caller → proceed

# ── delegate to Python impl ───────────────────────────────────────────────────
exec python3 "$IMPL_PY" "$SINK_ROOT"
