#!/usr/bin/env bash
# emit-hermes-marker.sh — Append a JSON-line hermes marker to HERMES_MARKER_FILE.
#
# Usage: emit-hermes-marker.sh <kind> <task> <payload-json>
#
# When HERMES_MARKER_FILE is unset or empty: exits 0 immediately (strict no-op —
# nothing is written, nothing is printed). This is the normal case for every
# z-harness run that is NOT managed by hermes.
#
# When HERMES_MARKER_FILE is set: appends ONE JSON line to the file:
#   {"v": 1, "ts": "<ISO8601 UTC>", "kind": "<kind>", "task": "<task>", "payload": {...}}
#
# Valid kinds: status, heartbeat, needs_input, handoff_continue, handoff_decision, handoff_fanout, done
# Unknown kind: no-op (exit 0). Best-effort: always exits 0.
#
# The marker file is created (and its parent dir) if needed.
# Flock-safe append — mirrors the idiom in log-event.sh.

# Guard: no-op when HERMES_MARKER_FILE unset or empty
if [[ -z "${HERMES_MARKER_FILE:-}" ]]; then
  exit 0
fi

if [[ $# -lt 3 ]]; then
  # Malformed call — best-effort no-op
  exit 0
fi

KIND="$1"
TASK="$2"
PAYLOAD_JSON="$3"

# Validate kind — unknown kind is a no-op
case "$KIND" in
  status|heartbeat|needs_input|handoff_continue|handoff_decision|handoff_fanout|done) ;;
  *) exit 0 ;;
esac

# Build the envelope via python3 so:
#   - v stays integer 1 (not the string "1.0")
#   - ts format matches datetime.now(tz=timezone.utc).isoformat() in markers.py
#   - payload is a proper dict (json.loads validated)
LINE="$(python3 - "$KIND" "$TASK" "$PAYLOAD_JSON" <<'PY'
import json, sys
from datetime import datetime, timezone

kind, task, payload_raw = sys.argv[1], sys.argv[2], sys.argv[3]

# Parse and validate payload; fall back to empty dict on malformed input
try:
    payload = json.loads(payload_raw)
    if not isinstance(payload, dict):
        payload = {}
except (json.JSONDecodeError, ValueError):
    payload = {}

obj = {
    "v": 1,
    "ts": datetime.now(tz=timezone.utc).isoformat(),
    "kind": kind,
    "task": task,
    "payload": payload,
}
print(json.dumps(obj, separators=(",", ":")))
PY
)" 2>/dev/null || exit 0

if [[ -z "$LINE" ]]; then
  exit 0
fi

# Create parent directory if needed
mkdir -p "$(dirname "$HERMES_MARKER_FILE")" 2>/dev/null || true

# Flock-safe append — mirrors the append() idiom in log-event.sh
if command -v flock >/dev/null 2>&1; then
  ( flock 9; printf '%s\n' "$LINE" >> "$HERMES_MARKER_FILE" ) 9>>"${HERMES_MARKER_FILE}.lock" 2>/dev/null || true
else
  printf '%s\n' "$LINE" >> "$HERMES_MARKER_FILE" 2>/dev/null || true
fi

exit 0
