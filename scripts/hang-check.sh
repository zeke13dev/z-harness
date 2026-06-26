#!/usr/bin/env bash
# hang-check.sh — one-shot scheduled hang detector (statusline-hud Workstream B,
# T007). Replaces the daemon poller layer of the old watchdog: instead of a
# long-lived sweep, the orchestrator schedules ONE of these (via T008) at a
# subagent's predicted-finish horizon. At fire time it asks "is this run's work
# still outstanding past its threshold?" and, if so, notifies once.
#
# Reuses existing primitives (retained, not reimplemented):
#   - liveness.sh    : unmatched <base>_start past a stale threshold
#   - notify-watchdog.sh : the notify path (Discord / macOS), config-gated
#
# Usage:
#   hang-check.sh --run <run_id> --threshold-secs <N> [--reason <key>] [--message <m>]
#
# Exit codes: 0 always (a scheduled check must never fail loudly). Prints a
# "HANG: ..." line to stdout when a stall is detected (also drives notify); silent
# otherwise. --reason gives the notify-once dedup key (default: the run id).

set -uo pipefail

SCRIPTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LIVENESS="${HANG_LIVENESS_SCRIPT:-$SCRIPTS_DIR/liveness.sh}"
NOTIFY="${HANG_NOTIFY_SCRIPT:-$SCRIPTS_DIR/notify-watchdog.sh}"

RUN=""
THRESHOLD=""
REASON=""
MESSAGE=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --run)            RUN="$2"; shift 2 ;;
    --threshold-secs) THRESHOLD="$2"; shift 2 ;;
    --reason)         REASON="$2"; shift 2 ;;
    --message)        MESSAGE="$2"; shift 2 ;;
    -h|--help)        sed -n '2,18p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "hang-check.sh: unknown arg: $1" >&2; exit 0 ;;  # never fail loudly
  esac
done

[[ -z "$RUN" ]] && { echo "hang-check.sh: --run required" >&2; exit 0; }
[[ "$THRESHOLD" =~ ^[0-9]+$ ]] || THRESHOLD=300
[[ -z "$REASON" ]] && REASON="$RUN"

# Detect: any unmatched <base>_start in this run older than the threshold?
LIVE_OUT=""
LIVE_RC=0
LIVE_OUT="$(bash "$LIVENESS" --run "$RUN" --stale-seconds "$THRESHOLD" 2>/dev/null)" || LIVE_RC=$?

# liveness.sh: 0 = nothing stale, 1 = stall(s) found, 2 = usage error.
if [[ "$LIVE_RC" -ne 1 ]]; then
  exit 0  # healthy (or could not evaluate) — stay silent
fi

[[ -z "$MESSAGE" ]] && MESSAGE="Possible hang in run ${RUN}: work outstanding past ${THRESHOLD}s threshold."
echo "HANG: run=${RUN} reason=${REASON} threshold=${THRESHOLD}s"

# Notify-once dedup, mirroring watchdog-sweep's marker pattern.
PLAN_DIR="${Z_HARNESS_PLAN_DIR:-}"
if [[ -z "$PLAN_DIR" ]]; then
  RUN_DIR="$(bash "$SCRIPTS_DIR/log-event.sh" resolve-run-dir "$RUN" 2>/dev/null || true)"
  PLAN_DIR="${RUN_DIR%/archive/*}"
fi
if [[ -n "$PLAN_DIR" ]]; then
  ACTIVE_DIR="$PLAN_DIR/active"
  mkdir -p "$ACTIVE_DIR" 2>/dev/null || true
  MARKER="$ACTIVE_DIR/${RUN}.hang-notified.${REASON}"
  if [[ -f "$MARKER" ]]; then
    exit 0  # already notified for this reason
  fi
  touch "$MARKER" 2>/dev/null || true
fi

# Best-effort notify (config-gated inside notify-watchdog.sh); never blocks/fails.
if [[ -n "${HERMES_SO_JOB_ID:-}" ]]; then
  bash "$NOTIFY" --run "$RUN" --event "watchdog_stall" --message "$MESSAGE" \
    --job-id "$HERMES_SO_JOB_ID" >/dev/null 2>&1 || true
else
  bash "$NOTIFY" --run "$RUN" --event "watchdog_stall" --message "$MESSAGE" \
    >/dev/null 2>&1 || true
fi

exit 0
