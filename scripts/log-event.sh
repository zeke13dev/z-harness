#!/usr/bin/env bash
# Append a structured event to the run's events.jsonl.
#
# Usage: log-event.sh <run-id-or-relpath> <kind> <json-payload>
#
# Slug namespacing: if env var Z_HARNESS_SLUG is set (non-empty), all output
# paths are namespaced under z-harness/<slug>/ so multiple plans can coexist
# in the same repo. If unset, the legacy flat layout (z-harness/archive/...)
# is used for backward compat with old plans.
#
# Example:
#   Z_HARNESS_SLUG=add-rate-limit \
#   log-event.sh 20260517T144200Z-add-rate-limit consult \
#     '{"llm":"gemini","phase":3,"prompt_chars":4821,"wall_ms":18204,"transcript":"001-gemini.md"}'
#
# Writes to (with Z_HARNESS_SLUG set):
#   z-harness/<slug>/archive/<run>/events.jsonl   (per-run log, append-only)
#   z-harness/metrics.jsonl                       (repo-wide aggregate, slug added to event)
#
# Writes to (legacy, no slug):
#   z-harness/archive/<run>/events.jsonl
#   z-harness/metrics.jsonl
#
# Both files are JSON Lines. Append-safe under concurrent calls via flock when available.

set -euo pipefail

if [[ $# -lt 3 ]]; then
  echo "usage: log-event.sh <run-id-or-relpath> <kind> <json-payload>" >&2
  exit 2
fi

RUN="$1"
KIND="$2"
PAYLOAD="$3"

# Resolve repo root (caller's cwd is assumed to be inside the target repo).
REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"

# Slug namespacing — see header comment.
SLUG="${Z_HARNESS_SLUG:-}"
if [[ -n "$SLUG" ]]; then
  RUN_DIR="$REPO_ROOT/z-harness/$SLUG/archive/$RUN"
else
  RUN_DIR="$REPO_ROOT/z-harness/archive/$RUN"
fi
mkdir -p "$RUN_DIR"

TS="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

# Validate payload is JSON; if not, wrap it as a string.
if ! printf '%s' "$PAYLOAD" | python3 -c 'import json,sys; json.loads(sys.stdin.read())' 2>/dev/null; then
  PAYLOAD="$(printf '%s' "$PAYLOAD" | python3 -c 'import json,sys; print(json.dumps({"raw": sys.stdin.read()}))')"
fi

EVENT="$(python3 -c '
import json, sys
ts, run, kind, slug, payload = sys.argv[1:6]
obj = {"ts": ts, "run": run, "kind": kind}
if slug:
    obj["slug"] = slug
obj.update(json.loads(payload))
print(json.dumps(obj, separators=(",", ":")))
' "$TS" "$RUN" "$KIND" "$SLUG" "$PAYLOAD")"

append() {
  local target="$1"
  if command -v flock >/dev/null 2>&1; then
    ( flock 9; printf '%s\n' "$EVENT" >> "$target" ) 9>>"$target.lock"
  else
    printf '%s\n' "$EVENT" >> "$target"
  fi
}

append "$RUN_DIR/events.jsonl"
append "$REPO_ROOT/z-harness/metrics.jsonl"
