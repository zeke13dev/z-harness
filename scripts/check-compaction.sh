#!/usr/bin/env bash
# check-compaction.sh — Evaluate compaction breakpoint conditions at batch-settle.
#
# Run at each /z-implement-all batch boundary. Reads TASKS.md's [x] count and
# a state file (.last-compaction-check) from the plan directory, then signals
# whether the orchestrator should pause for context compaction.
#
# Env vars (read):
#   Z_HARNESS_PLAN_DIR         — plan directory (required; contains TASKS.md)
#   Z_IMPLEMENT_PAUSE_TASKS    — [x] tasks since last pause to trigger (default 5)
#   Z_IMPLEMENT_PAUSE_MINUTES  — wall minutes since last pause to trigger (default 30)
#   Z_HARNESS_SLUG             — plan slug (optional; passed to log-event.sh)
#   Z_HARNESS_BASE_DIR         — redirects artifacts (optional; passed through)
#
# Returns:
#   0 — no trigger; continue
#   1 — trigger fired; orchestrator should follow pause protocol
#
# State file: $Z_HARNESS_PLAN_DIR/.last-compaction-check
#   Format: <epoch> <completed_count>
#   Created on first trigger. Absent file means "never paused" — clock starts
#   at TASKS.md mtime (or epoch 0 if that fails); count starts at 0.

set -euo pipefail

# ---------------------------------------------------------------------------
# Resolve plugin root
# ---------------------------------------------------------------------------
_PLUGIN_ROOT="${ANTIGRAVITY_PLUGIN_ROOT:-${CLAUDE_PLUGIN_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}}"

# ---------------------------------------------------------------------------
# Validate Z_HARNESS_PLAN_DIR
# ---------------------------------------------------------------------------
if [ -z "${Z_HARNESS_PLAN_DIR:-}" ]; then
  echo "[check-compaction] Z_HARNESS_PLAN_DIR is not set — cannot locate TASKS.md" >&2
  exit 0
fi

TASKS_FILE="$Z_HARNESS_PLAN_DIR/TASKS.md"
STATE_FILE="$Z_HARNESS_PLAN_DIR/.last-compaction-check"

if [ ! -f "$TASKS_FILE" ]; then
  echo "[check-compaction] TASKS.md not found at $TASKS_FILE — nothing to check" >&2
  exit 0
fi

# ---------------------------------------------------------------------------
# Count completed [x] tasks
# ---------------------------------------------------------------------------
# Uses the same [x] detection regex as the orchestrator and session-helpers.sh:
#   ^\s*[-*]?\s*\[x\]
# This matches both "- [x] T001 ..." and "[x] ## T001" patterns.
COMPLETED="$(grep -cE '^\s*[-*]?\s*\[x\]' "$TASKS_FILE" 2>/dev/null || echo 0)"
# Ensure it's a number
case "$COMPLETED" in
  ''|*[!0-9]*) COMPLETED=0 ;;
esac

# ---------------------------------------------------------------------------
# Read state file (last pause epoch + last completed count)
# ---------------------------------------------------------------------------
LAST_EPOCH=0
LAST_COUNT=0

if [ -f "$STATE_FILE" ]; then
  read -r LAST_EPOCH LAST_COUNT < "$STATE_FILE" 2>/dev/null || true
  case "$LAST_EPOCH" in
    ''|*[!0-9]*) LAST_EPOCH=0 ;;
  esac
  case "$LAST_COUNT" in
    ''|*[!0-9]*) LAST_COUNT=0 ;;
  esac
else
  # No prior pause — use TASKS.md mtime as a proxy for "run started."
  # On macOS, stat -f %m; on Linux, stat -c %Y.
  if stat -f %m "$TASKS_FILE" >/dev/null 2>&1; then
    LAST_EPOCH="$(stat -f %m "$TASKS_FILE" 2>/dev/null)" || LAST_EPOCH=0
  else
    LAST_EPOCH="$(stat -c %Y "$TASKS_FILE" 2>/dev/null)" || LAST_EPOCH=0
  fi
  case "$LAST_EPOCH" in
    ''|*[!0-9]*) LAST_EPOCH=0 ;;
  esac
  LAST_COUNT=0
fi

# ---------------------------------------------------------------------------
# Compute deltas
# ---------------------------------------------------------------------------
TASKS_DONE_SINCE=$(( COMPLETED - LAST_COUNT ))
if [ "$TASKS_DONE_SINCE" -lt 0 ]; then
  # TASKS.md was rewritten with fewer [x] tasks (e.g. plan amend with rollback).
  # Reset: treat this as a fresh window.
  TASKS_DONE_SINCE="$COMPLETED"
  LAST_COUNT=0
fi

NOW="$(date +%s)"
WALL_MINUTES_SINCE=$(( (NOW - LAST_EPOCH) / 60 ))
if [ "$WALL_MINUTES_SINCE" -lt 0 ]; then
  WALL_MINUTES_SINCE=0
fi

# ---------------------------------------------------------------------------
# Evaluate triggers
# ---------------------------------------------------------------------------
Z_IMPLEMENT_PAUSE_TASKS="${Z_IMPLEMENT_PAUSE_TASKS:-5}"
Z_IMPLEMENT_PAUSE_MINUTES="${Z_IMPLEMENT_PAUSE_MINUTES:-30}"

TRIGGER=""
if [ "${Z_IMPLEMENT_PAUSE_TASKS}" -gt 0 ] && [ "${TASKS_DONE_SINCE}" -ge "${Z_IMPLEMENT_PAUSE_TASKS}" ]; then
  TRIGGER="task_count"
elif [ "${Z_IMPLEMENT_PAUSE_MINUTES}" -gt 0 ] && [ "${WALL_MINUTES_SINCE}" -ge "${Z_IMPLEMENT_PAUSE_MINUTES}" ]; then
  TRIGGER="wall_time"
fi

if [ -z "$TRIGGER" ]; then
  exit 0
fi

# ---------------------------------------------------------------------------
# Trigger — update state, emit event, signal pause
# ---------------------------------------------------------------------------

# Count pending tasks for the event payload
PENDING_REMAINING="$(grep -cE '^\s*[-*]?\s*\[\s\]' "$TASKS_FILE" 2>/dev/null || echo 0)"
case "$PENDING_REMAINING" in
  ''|*[!0-9]*) PENDING_REMAINING=0 ;;
esac

# Update state file so the next pause window starts fresh
printf '%s %s\n' "$NOW" "$COMPLETED" > "$STATE_FILE"

# Emit compaction_pause event
PAYLOAD="$(python3 -c '
import json, sys
print(json.dumps({
  "trigger": sys.argv[1],
  "tasks_completed_total": int(sys.argv[2]),
  "tasks_done_since_pause": int(sys.argv[3]),
  "wall_minutes_since_pause": int(sys.argv[4]),
  "pending_remaining": int(sys.argv[5])
}))
' "$TRIGGER" "$COMPLETED" "$TASKS_DONE_SINCE" "$WALL_MINUTES_SINCE" "$PENDING_REMAINING")"

bash "$_PLUGIN_ROOT/scripts/log-event.sh" "orchestration" compaction_pause "$PAYLOAD" >/dev/null 2>&1 || true

exit 1
