#!/usr/bin/env bash
# check-compaction.sh — Evaluate clear-checkpoint conditions at durable boundaries.
#
# Run at each durable boundary. Context-pressure percentage policy is primary
# and cheap enough to evaluate every time, including non-/z-execute producer
# seams where REPORT.md/MANIFEST.md exists before TASKS.md. Legacy task-count
# and wall-clock thresholds remain fallback heuristics only when TASKS.md exists
# and percentage estimation is disabled or unavailable.
#
# Env vars (read):
#   Z_HARNESS_PLAN_DIR         — plan directory (required; TASKS.md optional for context pressure)
#   Z_HARNESS_CONTEXT_USED_TOKENS
#   Z_HARNESS_CONTEXT_WINDOW_TOKENS
#                               — optional host/editor context-pressure token
#                                 counts consumed by context-budget.py.
#   Z_HARNESS_CONTEXT_CHECKPOINT_THRESHOLD_PERCENT
#   Z_HARNESS_PAUSE_AT_PCT     — legacy alias for checkpoint threshold (default 85)
#   Z_HARNESS_CONTEXT_WARN_THRESHOLD_PERCENT
#                               — optional checkpoint_soon threshold (default 70)
#   Z_HARNESS_CONTEXT_PRESSURE_ENABLED
#                               — false/0/off disables percentage estimation
#   Z_HARNESS_CONTEXT_PRESSURE_STRICT
#                               — true/1/on fails closed when estimation fails
#   Z_HARNESS_CONTEXT_WARN_NOTIFY
#                               — true/1/on prints a warning for checkpoint_soon
#   Z_IMPLEMENT_PAUSE_TASKS    — legacy [x] tasks since last pause heuristic (default 5)
#   Z_IMPLEMENT_PAUSE_MINUTES  — legacy wall minutes since last pause heuristic (default 30)
#   Z_HARNESS_SLUG             — plan slug (optional; passed to log-event.sh)
#   Z_HARNESS_BASE_DIR         — redirects artifacts (optional; passed through)
#   LEVEL_EXECUTE_SUPPRESS_COMPACTION
#                               — 1 makes the check a no-op while the INTENT
#                                 BFS Main loop is inside an unflushed level
# Optional mode:
#   --context-pressure-json    — emit the rough context-pressure JSON contract
#                               for $Z_HARNESS_PLAN_DIR plus canonical repo
#                               aggregate metrics, then exit 0.
#
# Returns:
#   0 — no pausing trigger; continue
#   1 — percentage or legacy pause; orchestrator should follow clear-checkpoint protocol
#   2 — strict context-pressure estimate failure; halt without checkpoint handling
# State file: $Z_HARNESS_PLAN_DIR/.last-compaction-check
#   Format: <epoch> <completed_count>
#   clock starts at TASKS.md mtime when present, otherwise plan-dir mtime for
#   context-pressure-only seams; count starts at 0.

set -euo pipefail

# ---------------------------------------------------------------------------
# Resolve plugin root
# ---------------------------------------------------------------------------
_PLUGIN_ROOT="${ANTIGRAVITY_PLUGIN_ROOT:-${CLAUDE_PLUGIN_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}}"
STRICT_CONTEXT_PRESSURE_EXIT=2

bool_enabled() {
  case "${1:-}" in
    0|false|FALSE|False|off|OFF|Off|no|NO|No) return 1 ;;
    *) return 0 ;;
  esac
}

bool_true() {
  case "${1:-}" in
    1|true|TRUE|True|on|ON|On|yes|YES|Yes) return 0 ;;
    *) return 1 ;;
  esac
}

positive_int_or_default() {
  local value="${1:-}"
  local default_value="$2"
  case "$value" in
    ''|*[!0-9]*) printf '%s\n' "$default_value" ;;
    *) printf '%s\n' "$value" ;;
  esac
}

config_value_or_default() {
  local key="$1"
  local default_value="$2"
  local value
  value="$(python3 "$_PLUGIN_ROOT/scripts/config.py" get "$key" 2>/dev/null)" || value="$default_value"
  if [ -z "$value" ]; then
    value="$default_value"
  fi
  printf '%s\n' "$value"
}

build_metrics_args() {
  METRICS_ARGS=()
  if [ -n "${Z_HARNESS_BASE_DIR:-}" ]; then
    METRICS_ARGS=(--metrics "$Z_HARNESS_BASE_DIR/metrics.jsonl")
  else
    local base_dir
    base_dir="$(_Z_HARNESS_RESOLVING_BASE=1 bash "$_PLUGIN_ROOT/scripts/plan-path.sh" base_dir 2>/dev/null || true)"
    if [ -n "$base_dir" ]; then
      METRICS_ARGS=(--metrics "$base_dir/metrics.jsonl")
    fi
  fi
}

build_pressure_args() {
  PRESSURE_ARGS=()
  if [ -n "${Z_HARNESS_CONTEXT_CHECKPOINT_THRESHOLD_PERCENT:-}" ]; then
    PRESSURE_ARGS+=(--checkpoint-threshold-percent "$Z_HARNESS_CONTEXT_CHECKPOINT_THRESHOLD_PERCENT")
  elif [ -n "${Z_HARNESS_PAUSE_AT_PCT:-}" ]; then
    PRESSURE_ARGS+=(--checkpoint-threshold-percent "$Z_HARNESS_PAUSE_AT_PCT")
  fi
  if [ -n "${Z_HARNESS_CONTEXT_WARN_THRESHOLD_PERCENT:-}" ]; then
    PRESSURE_ARGS+=(--checkpoint-warn-percent "$Z_HARNESS_CONTEXT_WARN_THRESHOLD_PERCENT")
  fi
}

emit_event() {
  local kind="$1"
  local payload="$2"
  bash "$_PLUGIN_ROOT/scripts/log-event.sh" "orchestration" "$kind" "$payload" >/dev/null 2>&1 || true
}

pressure_error() {
  local reason="$1"
  local detail="${2:-}"
  if bool_true "$CONTEXT_PRESSURE_STRICT_VALUE"; then
    local payload
    payload="$(python3 -c '
import json, sys
reason, detail, exit_code = sys.argv[1], sys.argv[2], int(sys.argv[3])
print(json.dumps({
    "trigger": "context_pressure",
    "reason": reason,
    "detail": detail,
    "strict": True,
    "exit_code": exit_code,
    "halt": True,
}, separators=(",", ":")))
' "$reason" "$detail" "$STRICT_CONTEXT_PRESSURE_EXIT")"
    emit_event "context_pressure_error" "$payload"
    if [ -n "$detail" ]; then
      echo "[check-compaction] $reason: $detail — strict fail-closed; exiting $STRICT_CONTEXT_PRESSURE_EXIT (not compaction_pause)" >&2
    else
      echo "[check-compaction] $reason — strict fail-closed; exiting $STRICT_CONTEXT_PRESSURE_EXIT (not compaction_pause)" >&2
    fi
    exit "$STRICT_CONTEXT_PRESSURE_EXIT"
  fi
  if [ -n "$detail" ]; then
    echo "[check-compaction] $reason: $detail — continuing fail-open" >&2
  else
    echo "[check-compaction] $reason — continuing fail-open" >&2
  fi
}

# ---------------------------------------------------------------------------
# Validate Z_HARNESS_PLAN_DIR
# ---------------------------------------------------------------------------
if [ -z "${Z_HARNESS_PLAN_DIR:-}" ]; then
  echo "[check-compaction] Z_HARNESS_PLAN_DIR is not set — cannot locate TASKS.md" >&2
  exit 0
fi

TASKS_FILE="$Z_HARNESS_PLAN_DIR/TASKS.md"
STATE_FILE="$Z_HARNESS_PLAN_DIR/.last-compaction-check"
TASKS_AVAILABLE=0


# INTENT BFS invokes the reusable Main loop with this guard set so a legacy
# batch-settle check inside the level cannot pause before LEDGER.md and
# .bfs_level_state are flushed. The BFS caller clears the flag and evaluates the
# threshold once at the durable level boundary.
if [ "${LEVEL_EXECUTE_SUPPRESS_COMPACTION:-0}" = "1" ]; then
  exit 0
fi
build_metrics_args
build_pressure_args
CONTEXT_PRESSURE_ENABLED_VALUE="${Z_HARNESS_CONTEXT_PRESSURE_ENABLED:-$(config_value_or_default runtime.context_pressure_enabled true)}"
CONTEXT_PRESSURE_STRICT_VALUE="${Z_HARNESS_CONTEXT_PRESSURE_STRICT:-$(config_value_or_default runtime.context_pressure_strict false)}"
CONTEXT_WARN_NOTIFY_VALUE="${Z_HARNESS_CONTEXT_WARN_NOTIFY:-$(config_value_or_default runtime.context_warn_notify false)}"


if [ "${1:-}" = "--context-pressure-json" ]; then
  python3 "$_PLUGIN_ROOT/scripts/context-budget.py" context-pressure "$Z_HARNESS_PLAN_DIR" "${METRICS_ARGS[@]}" "${PRESSURE_ARGS[@]}"
  exit 0
fi

if [ -f "$TASKS_FILE" ]; then
  TASKS_AVAILABLE=1
  # ---------------------------------------------------------------------------
  # Count completed/pending tasks
  # ---------------------------------------------------------------------------
  # Use the same inline-heading/list-checkbox parser as SESSION resume and
  # context-curator metadata. This keeps per-task, per-batch, and BFS-boundary
  # checkpoint gates aligned with the durable done-set hash.
  TASK_COUNTS="$(bash "$_PLUGIN_ROOT/scripts/session-helpers.sh" task_status_counts "$TASKS_FILE" 2>/dev/null || true)"
  case "$TASK_COUNTS" in
    *done=*pending=*) eval "$TASK_COUNTS" ;;
    *) done=0 pending=0 in_progress=0 other=0 ;;
  esac
  COMPLETED="${done:-0}"
  PENDING_REMAINING="${pending:-0}"
  case "$COMPLETED" in
    ''|*[!0-9]*) COMPLETED=0 ;;
  esac
  case "$PENDING_REMAINING" in
    ''|*[!0-9]*) PENDING_REMAINING=0 ;;
  esac
else
  echo "[check-compaction] TASKS.md not found at $TASKS_FILE — evaluating context pressure only" >&2
  COMPLETED=0
  PENDING_REMAINING=0
fi

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
  # No prior pause. Use TASKS.md mtime for task-backed runs; for non-/z-execute
  # producer seams that intentionally have no TASKS.md yet, use the plan-dir
  # mtime only to populate context-pressure telemetry. Legacy wall-time fallback
  # remains disabled without TASKS.md below.
  MTIME_SOURCE="$TASKS_FILE"
  if [ "$TASKS_AVAILABLE" != "1" ]; then
    MTIME_SOURCE="$Z_HARNESS_PLAN_DIR"
  fi
  # On macOS, stat -f %m; on Linux, stat -c %Y.
  if stat -f %m "$MTIME_SOURCE" >/dev/null 2>&1; then
    LAST_EPOCH="$(stat -f %m "$MTIME_SOURCE" 2>/dev/null)" || LAST_EPOCH=0
  else
    LAST_EPOCH="$(stat -c %Y "$MTIME_SOURCE" 2>/dev/null)" || LAST_EPOCH=0
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

TRIGGER=""
PAYLOAD=""
CONTEXT_PRESSURE_DECISION_MADE=0

# ---------------------------------------------------------------------------
# Primary percentage-threshold policy
# ---------------------------------------------------------------------------
if bool_enabled "$CONTEXT_PRESSURE_ENABLED_VALUE"; then
  PRESSURE_ERR="$(mktemp "${TMPDIR:-/tmp}/zh-context-pressure-err.XXXXXX")"
  PRESSURE_JSON=""
  if ! PRESSURE_JSON="$(python3 "$_PLUGIN_ROOT/scripts/context-budget.py" context-pressure "$Z_HARNESS_PLAN_DIR" "${METRICS_ARGS[@]}" "${PRESSURE_ARGS[@]}" 2>"$PRESSURE_ERR")"; then
    PRESSURE_DETAIL="$(tr '\n' ' ' < "$PRESSURE_ERR" 2>/dev/null || true)"
    rm -f "$PRESSURE_ERR"
    pressure_error "context pressure estimate failed" "$PRESSURE_DETAIL"
  else
    rm -f "$PRESSURE_ERR"
    DECISION_OUTPUT=""
    if ! DECISION_OUTPUT="$(PRESSURE_JSON="$PRESSURE_JSON" python3 - "$COMPLETED" "$TASKS_DONE_SINCE" "$WALL_MINUTES_SINCE" "$PENDING_REMAINING" <<'PY'
import json
import os
import sys

completed, done_since, wall_minutes, pending = map(int, sys.argv[1:5])
pressure = json.loads(os.environ["PRESSURE_JSON"])
thresholds = pressure.get("thresholds") or {}
policy = pressure.get("policy") or {}

percent = float(pressure.get("percent_used", 0.0))
threshold = thresholds.get("checkpoint_threshold_percent", thresholds.get("checkpoint_now_percent"))
threshold = float(threshold) if threshold is not None else 85.0
recommendation = str(pressure.get("recommendation", "continue"))
enabled = bool(policy.get("context_pressure_enabled", True))
warn_notify = bool(policy.get("context_warn_notify", False))

payload = {
    "trigger": "context_pressure",
    "tasks_completed_total": completed,
    "tasks_done_since_pause": done_since,
    "wall_minutes_since_pause": wall_minutes,
    "pending_remaining": pending,
    "context_pressure": pressure,
}

if not enabled:
    action = "continue"
elif recommendation == "checkpoint_now" or percent >= threshold:
    action = "pause"
elif recommendation == "checkpoint_soon":
    action = "warn_notify" if warn_notify else "warn"
else:
    action = "continue"

print(action)
print(json.dumps(payload, separators=(",", ":")))
PY
)"; then
      pressure_error "context pressure estimate produced malformed JSON" ""
    else
      ACTION="${DECISION_OUTPUT%%$'\n'*}"
      CONTEXT_PAYLOAD="${DECISION_OUTPUT#*$'\n'}"
      case "$ACTION" in
        pause)
          CONTEXT_PRESSURE_DECISION_MADE=1
          TRIGGER="context_pressure"
          PAYLOAD="$CONTEXT_PAYLOAD"
          ;;
        warn|warn_notify)
          CONTEXT_PRESSURE_DECISION_MADE=1
          emit_event "context_pressure" "$CONTEXT_PAYLOAD"
          if [ "$ACTION" = "warn_notify" ] || bool_true "$CONTEXT_WARN_NOTIFY_VALUE"; then
            echo "[check-compaction] context pressure checkpoint_soon — continuing without pause" >&2
          fi
          ;;
        continue)
          CONTEXT_PRESSURE_DECISION_MADE=1
          ;;
        *)
          pressure_error "context pressure estimate produced unknown action" "$ACTION"
          ;;
      esac
    fi
  fi
fi

# ---------------------------------------------------------------------------
# Legacy fallback/secondary heuristic triggers
# ---------------------------------------------------------------------------
Z_IMPLEMENT_PAUSE_TASKS="$(positive_int_or_default "${Z_IMPLEMENT_PAUSE_TASKS:-5}" 5)"
Z_IMPLEMENT_PAUSE_MINUTES="$(positive_int_or_default "${Z_IMPLEMENT_PAUSE_MINUTES:-30}" 30)"

if [ -z "$TRIGGER" ] && [ "$CONTEXT_PRESSURE_DECISION_MADE" != "1" ] && [ "$TASKS_AVAILABLE" = "1" ]; then
  if [ "${Z_IMPLEMENT_PAUSE_TASKS}" -gt 0 ] && [ "${TASKS_DONE_SINCE}" -ge "${Z_IMPLEMENT_PAUSE_TASKS}" ]; then
    TRIGGER="task_count"
  elif [ "${Z_IMPLEMENT_PAUSE_MINUTES}" -gt 0 ] && [ "${WALL_MINUTES_SINCE}" -ge "${Z_IMPLEMENT_PAUSE_MINUTES}" ]; then
    TRIGGER="wall_time"
  fi
fi

if [ -z "$TRIGGER" ]; then
  exit 0
fi

# ---------------------------------------------------------------------------
# Trigger — update state, emit event, signal pause
# ---------------------------------------------------------------------------

# Update state file so the next pause window starts fresh.
printf '%s %s\n' "$NOW" "$COMPLETED" > "$STATE_FILE"

if [ -z "$PAYLOAD" ]; then
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
fi

emit_event "compaction_pause" "$PAYLOAD"

exit 1
