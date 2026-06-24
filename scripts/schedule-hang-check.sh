#!/usr/bin/env bash
# schedule-hang-check.sh — schedule a ONE-SHOT hang-check at a future horizon
# (statusline-hud Workstream B, T008). Replaces the daemon poller: instead of a
# long-lived sweep, the orchestrator schedules one of these per run at the
# predicted-finish horizon. On macOS it uses a self-removing launchd job (survives
# the spawning shell exiting and the machine sleeping, unlike a backgrounded sleep);
# elsewhere it falls back to a detached `nohup sleep && hang-check`.
#
# Horizons here are multi-minute (per-class p90 thresholds from hang-threshold.py),
# so launchd's minute-granularity StartCalendarInterval is fine.
#
# Usage:
#   schedule-hang-check.sh --run R --threshold-secs N [--delay-secs D] [--reason K] [--label L]
#       Schedule hang-check.sh --run R --threshold-secs N to fire in D secs
#       (default D = N). --print emits the plan without scheduling. --self-test
#       proves launchd can actually run our job (fires, not just registers).
#
# Exit codes: 0 ok / 2 bad args / 3 schedule error.

set -uo pipefail
SCRIPTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HANG_CHECK="${SCHEDULE_HANG_CHECK_SCRIPT:-$SCRIPTS_DIR/hang-check.sh}"

RUN="" THRESHOLD="" DELAY="" REASON="" LABEL="" PRINT=0 SELFTEST=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --run) RUN="$2"; shift 2 ;;
    --threshold-secs) THRESHOLD="$2"; shift 2 ;;
    --delay-secs) DELAY="$2"; shift 2 ;;
    --reason) REASON="$2"; shift 2 ;;
    --label) LABEL="$2"; shift 2 ;;
    --print) PRINT=1; shift ;;
    --self-test) SELFTEST=1; shift ;;
    -h|--help) sed -n '2,20p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "schedule-hang-check.sh: unknown arg: $1" >&2; exit 2 ;;
  esac
done

_uid="$(id -u)"
_agents_dir="${SCHEDULE_HANG_AGENTS_DIR:-$HOME/Library/LaunchAgents}"

# --- helpers ----------------------------------------------------------------
_target_cal() {  # echo "<min> <hour> <day> <month>" for now+delay
  python3 - "$1" <<'PY'
import sys, time
t = time.localtime(time.time() + max(60, int(sys.argv[1])))  # >=60s so it's in the future
print(t.tm_min, t.tm_hour, t.tm_mday, t.tm_mon)
PY
}

_xml_escape() {
  python3 - "$1" <<'PY'
import html, sys
print(html.escape(sys.argv[1], quote=True))
PY
}

_shell_quote() {
  python3 - "$1" <<'PY'
import shlex, sys
print(shlex.quote(sys.argv[1]))
PY
}

_safe_component() {
  [[ "$1" =~ ^[A-Za-z0-9._-]+$ ]]
}

_string_arg_xml() {
  printf '    <string>%s</string>\n' "$(_xml_escape "$1")"
}


_plist() {  # $1 label  $2 program-args-xml
  local label_xml
  label_xml="$(_xml_escape "$1")"
  cat <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$label_xml</string>
  <key>ProgramArguments</key>
  <array>
$2
  </array>
  <key>RunAtLoad</key><false/>
$3
</dict>
</plist>
EOF
}

_cal_xml() {  # $1 min $2 hour $3 day $4 month
  cat <<EOF
  <key>StartCalendarInterval</key>
  <dict>
    <key>Minute</key><integer>$1</integer>
    <key>Hour</key><integer>$2</integer>
    <key>Day</key><integer>$3</integer>
    <key>Month</key><integer>$4</integer>
  </dict>
EOF
}

# --- self-test: prove launchd actually RUNS a job we submit -------------------
if [[ "$SELFTEST" -eq 1 ]]; then
  if ! command -v launchctl >/dev/null 2>&1; then
    echo "SELFTEST: SKIP (no launchctl — non-macOS; detached fallback will be used)"
    exit 0
  fi
  mkdir -p "$_agents_dir"
  sentinel="$(mktemp -t zh-hang-selftest.XXXXXX)"; rm -f "$sentinel"
  lbl="com.zharness.hangcheck.selftest.$$"
  plist="$_agents_dir/$lbl.plist"
  # RunAtLoad job that touches the sentinel immediately — proves execution.
  _plist "$lbl" "    <string>/bin/sh</string>
    <string>-c</string>
    <string>/usr/bin/touch '$sentinel'</string>" "  <key>RunAtLoad</key><true/>" \
    | sed 's#<key>RunAtLoad</key><false/>##' > "$plist"
  launchctl bootstrap "gui/$_uid" "$plist" >/dev/null 2>&1 || launchctl load "$plist" >/dev/null 2>&1 || true
  ok=0
  for _ in $(seq 1 30); do
    [[ -f "$sentinel" ]] && { ok=1; break; }
    sleep 0.2
  done
  launchctl bootout "gui/$_uid/$lbl" >/dev/null 2>&1 || launchctl unload "$plist" >/dev/null 2>&1 || true
  rm -f "$plist" "$sentinel"
  if [[ "$ok" -eq 1 ]]; then echo "SELFTEST: PASS (launchd ran the job)"; exit 0
  else echo "SELFTEST: FAIL (launchd did not run the job)"; exit 3; fi
fi

# --- normal scheduling -------------------------------------------------------
[[ -z "$RUN" ]] && { echo "schedule-hang-check.sh: --run required" >&2; exit 2; }
[[ "$THRESHOLD" =~ ^[0-9]+$ ]] || { echo "schedule-hang-check.sh: --threshold-secs N required" >&2; exit 2; }
[[ "$DELAY" =~ ^[0-9]+$ ]] || DELAY="$THRESHOLD"
[[ -z "$REASON" ]] && REASON="$RUN"
_safe_run="$(printf '%s' "$RUN" | tr -c 'A-Za-z0-9._-' '-')"
[[ "$RUN" == "$_safe_run" && -n "$RUN" ]] || { echo "schedule-hang-check.sh: --run must contain only A-Za-z0-9._-" >&2; exit 2; }
_safe_component "$REASON" || { echo "schedule-hang-check.sh: --reason must contain only A-Za-z0-9._-" >&2; exit 2; }
[[ -z "$LABEL" ]] && LABEL="com.zharness.hangcheck.$_safe_run"
_safe_component "$LABEL" || { echo "schedule-hang-check.sh: --label must contain only A-Za-z0-9._-" >&2; exit 2; }
plist="$_agents_dir/$LABEL.plist"

# Self-removing one-shot: run hang-check, then bootout + delete this plist.
cmd="bash $(_shell_quote "$HANG_CHECK") --run $(_shell_quote "$RUN") --threshold-secs $THRESHOLD --reason $(_shell_quote "$REASON"); launchctl bootout $(_shell_quote "gui/$_uid/$LABEL") 2>/dev/null; rm -f $(_shell_quote "$plist")"
prog="$(_string_arg_xml "/bin/sh")$(_string_arg_xml "-c")$(_string_arg_xml "$cmd")"
read -r mn hr dy mo < <(_target_cal "$DELAY")
body="$(_plist "$LABEL" "$prog" "$(_cal_xml "$mn" "$hr" "$dy" "$mo")")"

if [[ "$PRINT" -eq 1 ]]; then
  echo "# launchd plist ($plist):"
  echo "$body"
  echo "# load: launchctl bootstrap gui/$_uid $plist"
  exit 0
fi

if ! command -v launchctl >/dev/null 2>&1; then
  # Non-macOS fallback: detached delayed one-shot.
  nohup sh -c "sleep $DELAY; bash $(_shell_quote "$HANG_CHECK") --run $(_shell_quote "$RUN") --threshold-secs $THRESHOLD --reason $(_shell_quote "$REASON")" \
    >/dev/null 2>&1 &
  echo "scheduled (detached fallback): hang-check for $RUN in ${DELAY}s"
  exit 0
fi

mkdir -p "$_agents_dir"
printf '%s\n' "$body" > "$plist"
launchctl bootout "gui/$_uid/$LABEL" >/dev/null 2>&1 || true  # idempotent re-arm
if launchctl bootstrap "gui/$_uid" "$plist" >/dev/null 2>&1 || launchctl load "$plist" >/dev/null 2>&1; then
  echo "scheduled (launchd): $LABEL fires ~${mn}min (run $RUN, threshold ${THRESHOLD}s)"
  exit 0
fi
echo "schedule-hang-check.sh: launchctl failed to load $plist" >&2
exit 3
