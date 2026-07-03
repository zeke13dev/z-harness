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
# Unknown kind: no-op (exit 0). Best-effort by default: always exits 0.
#
# Strict mode: pass --strict as the FIRST argument. When --strict is given AND
# HERMES_MARKER_FILE is set, a genuine failure to write the marker (malformed
# call, invalid kind, envelope build error, or append failure) returns non-zero
# instead of the default best-effort exit 0. Callers that MUST NOT silently drop
# a marker — e.g. /z-handoff's Hermes-managed path, where a dropped marker
# strands the session — pass --strict. Default (no flag) stays best-effort for
# every other caller. An unset/empty HERMES_MARKER_FILE is always a legit
# non-Hermes no-op (exit 0), never a strict failure.
#
# The marker file is created (and its parent dir) if needed.
# Flock-safe append — mirrors the idiom in log-event.sh.

# Parse leading --strict flag (must precede the positional args).
STRICT=0
if [[ "${1:-}" == "--strict" ]]; then
  STRICT=1
  shift
fi

# _die <msg>: fail loud (exit 1 + stderr) in strict mode; best-effort exit 0 otherwise.
_die() {
  if [[ "$STRICT" == "1" ]]; then
    echo "emit-hermes-marker: $1" >&2
    exit 1
  fi
  exit 0
}

# Guard: no-op when HERMES_MARKER_FILE unset or empty. This is the normal
# non-Hermes case and is NOT a failure even under --strict.
if [[ -z "${HERMES_MARKER_FILE:-}" ]]; then
  exit 0
fi

if [[ $# -lt 3 ]]; then
  _die "malformed call: expected <kind> <task> <payload-json>"
fi

KIND="$1"
TASK="$2"
PAYLOAD_JSON="$3"

# Validate kind — unknown kind cannot be emitted.
case "$KIND" in
  status|heartbeat|needs_input|handoff_continue|handoff_decision|handoff_fanout|done) ;;
  *) _die "invalid kind: $KIND" ;;
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
)" 2>/dev/null || _die "failed to build marker envelope"

if [[ -z "$LINE" ]]; then
  _die "failed to build marker envelope"
fi

# Create parent directory if needed
mkdir -p "$(dirname "$HERMES_MARKER_FILE")" 2>/dev/null || true

# Flock-safe append — mirrors the append() idiom in log-event.sh
if command -v flock >/dev/null 2>&1; then
  ( flock 9; printf '%s\n' "$LINE" >> "$HERMES_MARKER_FILE" ) 9>>"${HERMES_MARKER_FILE}.lock" 2>/dev/null \
    || _die "append to HERMES_MARKER_FILE failed: $HERMES_MARKER_FILE"
else
  printf '%s\n' "$LINE" >> "$HERMES_MARKER_FILE" 2>/dev/null \
    || _die "append to HERMES_MARKER_FILE failed: $HERMES_MARKER_FILE"
fi

exit 0
