#!/usr/bin/env bash
# Wrap a phase with start/end telemetry events.
#
# This is a thin sugar layer over log-event.sh so subagents can emit the
# `*_start` and `*_end` event kinds the z-implement-all spec mandates,
# without each agent having to hand-roll `T0=$(date +%s%3N)` timing.
#
# Usage (two forms):
#
#   1. start a phase, get a token back, end it later:
#      TOKEN="$(./log-phase.sh start "tasks/T020" precheck '{"id":"T020"}')"
#      # ... do work ...
#      ./log-phase.sh end "$TOKEN" '{"status":"ok","references_checked":11}'
#
#   2. wrap a command end-to-end, auto-time it:
#      ./log-phase.sh wrap "tasks/T020" precheck '{"id":"T020"}' -- \
#        codex exec - < prompt.txt
#
# Token telemetry (v2): callers SHOULD include these fields in the end-payload
# when the data is available, so post-run analysis can compute per-subagent
# Claude token spend:
#   subagent_model       (string)  -- "haiku" | "sonnet" | "opus"
#   subagent_input_tokens (int)    -- input tokens consumed by the subagent
#   subagent_output_tokens (int)   -- output tokens emitted by the subagent
#   prompt_chars         (int)     -- fallback if token counts unavailable; we
#   response_chars       (int)        estimate tokens ≈ chars/4 in analysis
#
# Honors Z_HARNESS_SLUG just like log-event.sh.

set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
PLUGIN_ROOT="${ANTIGRAVITY_PLUGIN_ROOT:-${CLAUDE_PLUGIN_ROOT:-$(dirname "$(dirname "$0")")}}"
LOG_EVENT="$PLUGIN_ROOT/scripts/log-event.sh"

if [[ ! -x "$LOG_EVENT" ]]; then
  echo "log-phase.sh: cannot find $LOG_EVENT" >&2
  exit 2
fi

# Portable ms-since-epoch. macOS BSD `date` does not support %3N, so fall
# back to python3 (already a hard dep of log-event.sh).
now_ms() { python3 -c 'import time; print(int(time.time()*1000))'; }

# Default-empty-to-`{}` without using `${VAR:-{}}` — bash parameter expansion
# parses the `{}` inside the default and leaves a stray `}` literal.
default_payload() {
  if [[ -n "${1:-}" ]]; then
    printf '%s' "$1"
  else
    printf '{}'
  fi
}

# check_wall_ms RUN PHASE T0 T1 WALL_MS
#
# Emits a telemetry_anomaly event and returns exit code 1 when WALL_MS is
# suspicious (> 86_400_000 ms, i.e. overflow/seconds-vs-ms confusion, OR
# negative, i.e. clock skew).  Returns exit code 0 on the normal path.
#
# Callers MUST exit 0 (suppressing the bogus *_end event) when this function
# returns 1.
check_wall_ms() {
  local run="$1" phase="$2" t0="$3" t1="$4" wall_ms="$5"
  local reason=""
  if [[ "$wall_ms" -gt 86400000 ]]; then
    reason="wall_ms_overflow"
  elif [[ "$wall_ms" -lt 0 ]]; then
    reason="wall_ms_negative"
  fi
  if [[ -n "$reason" ]]; then
    local anomaly_payload
    anomaly_payload="$(python3 -c '
import json, sys
print(json.dumps({
  "phase": sys.argv[1],
  "reason": sys.argv[2],
  "t_start": int(sys.argv[3]),
  "t_end": int(sys.argv[4]),
  "computed_wall_ms": int(sys.argv[5]),
}, separators=(",", ":")))
' "$phase" "$reason" "$t0" "$t1" "$wall_ms")"
    bash "$LOG_EVENT" "$run" "telemetry_anomaly" "$anomaly_payload"
    return 1
  fi
  return 0
}

mode="${1:-}"
shift || true

case "$mode" in
  start)
    RUN="${1:?usage: start <run> <phase> <json-payload>}"
    PHASE="${2:?usage: start <run> <phase> <json-payload>}"
    PAYLOAD="$(default_payload "${3:-}")"
    T0="$(now_ms)"
    bash "$LOG_EVENT" "$RUN" "${PHASE}_start" "$PAYLOAD" >&2 || true
    printf '%s|%s|%s\n' "$RUN" "$PHASE" "$T0"
    ;;
  end)
    TOKEN="${1:?usage: end <token-from-start> <json-payload>}"
    PAYLOAD="$(default_payload "${2:-}")"
    IFS='|' read -r RUN PHASE T0 <<< "$TOKEN"
    T1="$(now_ms)"
    WALL_MS=$((T1 - T0))
    check_wall_ms "$RUN" "$PHASE" "$T0" "$T1" "$WALL_MS" || exit 0
    MERGED="$(python3 -c '
import json, sys
p = json.loads(sys.argv[1])
p["wall_ms"] = int(sys.argv[2])
print(json.dumps(p, separators=(",", ":")))
' "$PAYLOAD" "$WALL_MS")"
    bash "$LOG_EVENT" "$RUN" "${PHASE}_end" "$MERGED"
    ;;
  wrap)
    RUN="${1:?usage: wrap <run> <phase> <json-payload> -- <cmd> [args...]}"
    PHASE="${2:?usage: wrap <run> <phase> <json-payload> -- <cmd> [args...]}"
    PAYLOAD="$(default_payload "${3:-}")"
    shift 3
    if [[ "${1:-}" != "--" ]]; then
      echo "log-phase.sh wrap: expected -- before command" >&2
      exit 2
    fi
    shift
    T0="$(now_ms)"
    bash "$LOG_EVENT" "$RUN" "${PHASE}_start" "$PAYLOAD" >&2 || true
    EXIT_CODE=0
    "$@" || EXIT_CODE=$?
    T1="$(now_ms)"
    WALL_MS=$((T1 - T0))
    check_wall_ms "$RUN" "$PHASE" "$T0" "$T1" "$WALL_MS" || exit 0
    END_PAYLOAD="$(python3 -c '
import json, sys
p = json.loads(sys.argv[1])
p["wall_ms"] = int(sys.argv[2])
p["exit_code"] = int(sys.argv[3])
print(json.dumps(p, separators=(",", ":")))
' "$PAYLOAD" "$WALL_MS" "$EXIT_CODE")"
    bash "$LOG_EVENT" "$RUN" "${PHASE}_end" "$END_PAYLOAD"
    exit "$EXIT_CODE"
    ;;
  *)
    echo "usage: log-phase.sh {start|end|wrap} ..." >&2
    exit 2
    ;;
esac
