#!/usr/bin/env bash
# write-clear-checkpoint.sh — Write watcher-readable clear checkpoint artifacts.
#
# This is the generic producer for z-harness clear/yield boundaries. It writes
# handoff.json unconditionally (unlike the legacy Hermes-gated /z-execute path),
# preserves SESSION.md if present, emits a stable event for any watcher, and
# prints a parseable STATUS line. It does not clear context itself; drivers or
# external watchers decide whether/how to perform /clear.
#
# Env vars (read):
#   Z_HARNESS_PLAN_DIR            — plan directory (required)
#   Z_HARNESS_SLUG                — plan slug (optional)
#   Z_HARNESS_AGENT               — provenance agent (optional; default pi)
#   RUN                           — current run id for telemetry (optional; default orchestration)
#   Z_HARNESS_CHECKPOINT_STATUS   — handoff status (default context_pressure; falls back to Z_HARNESS_HANDOFF_STATUS)
#   Z_HARNESS_CHECKPOINT_NEXT_STEP — override handoff next_step (falls back to Z_HARNESS_HANDOFF_NEXT_STEP)
#   Z_HARNESS_CHECKPOINT_RESUME_COMMAND — status-line/event resume command override (optional)
#
# Output:
#   Writes $Z_HARNESS_PLAN_DIR/handoff.json via write-handoff.sh.
#   Prints STATUS: clear_checkpoint ... on success.

set -euo pipefail

_PLUGIN_ROOT="${ANTIGRAVITY_PLUGIN_ROOT:-${CLAUDE_PLUGIN_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}}"

if [[ -z "${Z_HARNESS_PLAN_DIR:-}" ]]; then
  echo "[write-clear-checkpoint] Z_HARNESS_PLAN_DIR is not set" >&2
  exit 1
fi

PLAN_DIR="$Z_HARNESS_PLAN_DIR"
HANDOFF_FILE="$PLAN_DIR/handoff.json"
SESSION_FILE="$PLAN_DIR/SESSION.md"
TASKS_FILE="$PLAN_DIR/TASKS.md"
STATUS_VALUE="${Z_HARNESS_CHECKPOINT_STATUS:-${Z_HARNESS_HANDOFF_STATUS:-context_pressure}}"
RUN_ID="${RUN:-orchestration}"
RESUME_COMMAND="${Z_HARNESS_CHECKPOINT_RESUME_COMMAND:-}"

case "$STATUS_VALUE" in
  context_pressure|clean_break|complete|blocked) ;;
  *)
    echo "[write-clear-checkpoint] invalid Z_HARNESS_CHECKPOINT_STATUS: $STATUS_VALUE" >&2
    exit 2
    ;;
esac

export Z_HARNESS_HANDOFF_STATUS="$STATUS_VALUE"
if [[ -n "${Z_HARNESS_CHECKPOINT_NEXT_STEP:-${Z_HARNESS_HANDOFF_NEXT_STEP:-}}" ]]; then
  export Z_HARNESS_HANDOFF_NEXT_STEP="${Z_HARNESS_CHECKPOINT_NEXT_STEP:-${Z_HARNESS_HANDOFF_NEXT_STEP:-}}"
fi

HANDOFF_OUT="$(bash "$_PLUGIN_ROOT/scripts/write-handoff.sh" 2>&1)" || {
  rc=$?
  echo "$HANDOFF_OUT" >&2
  exit "$rc"
}

HANDOFF_BYTES="$(wc -c < "$HANDOFF_FILE" | tr -d '[:space:]')"
SESSION_PATH=""
if [[ -f "$SESSION_FILE" ]]; then
  SESSION_PATH="$SESSION_FILE"
fi

NEXT_PENDING=""
if [[ -f "$TASKS_FILE" ]]; then
  NEXT_PENDING="$(bash "$_PLUGIN_ROOT/scripts/session-helpers.sh" next_pending_task "$TASKS_FILE" 2>/dev/null || true)"
fi

if [[ -z "$RESUME_COMMAND" ]]; then
  RESUME_COMMAND="/z-execute"
  if [[ -n "${Z_HARNESS_SLUG:-}" ]]; then
    RESUME_COMMAND="/z-execute ${Z_HARNESS_SLUG}"
  fi
fi

PAYLOAD="$(python3 -c '
import json, sys
print(json.dumps({
  "handoff_path": sys.argv[1],
  "session_path": sys.argv[2] or None,
  "status": sys.argv[3],
  "resume_command": sys.argv[4],
  "next_pending": sys.argv[5] or None,
  "producer": "write-clear-checkpoint.sh",
  "consumer": "watcher"
}))
' "$HANDOFF_FILE" "$SESSION_PATH" "$STATUS_VALUE" "$RESUME_COMMAND" "$NEXT_PENDING")"

bash "$_PLUGIN_ROOT/scripts/log-event.sh" "$RUN_ID" clear_checkpoint_written "$PAYLOAD" >/dev/null 2>&1 || true

printf 'STATUS: clear_checkpoint handoff=%s session=%s status=%s resume=%q bytes=%s\n' \
  "$HANDOFF_FILE" "${SESSION_PATH:-none}" "$STATUS_VALUE" "$RESUME_COMMAND" "$HANDOFF_BYTES"
