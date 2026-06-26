#!/usr/bin/env bash
# DEPRECATED for Discord `so`: MCP orchestration now lives in
# scripts/hermes/mcp-hermes-orchestrator.py. This script remains only for legacy
# z-harness watchdog notifications and must not be used as the `so` backend.
#
# notify-watchdog.sh — Out-of-band human alert for watchdog events.
#
# Usage:
#   notify-watchdog.sh --run <run_id> --event <watchdog_stall|watchdog_timeout> \
#                       --message <text> [--pid <pid>] \
#                       [--slug <slug>] [--severity <severity>] [--next-step <text>]
#
# Behavior:
#   1. Gates on `config.py should-notify --event <event>`: exits 0 silently if "no".
#   2. Sends to all available channels (best-effort):
#      - Hermes webhook (if notify.hermes_webhook_url is set): platform-neutral payload,
#        HMAC-signed, curl --max-time 3 (3 s hard timeout)
#      - Discord webhook (if notify.discord_webhook_url is set): curl -fsS -m 10
#      - macOS desktop notification (if osascript is available)
#   3. When --pid is given, appends "To kill: kill <pid>" to the message.
#   4. Never fails the caller.

# No set -e here — we must never fail the caller.

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CONFIG_PY="${SCRIPT_DIR}/config.py"

# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

RUN=""
EVENT=""
MESSAGE=""
PID=""
SLUG=""
SEVERITY=""
NEXT_STEP=""
JOB_ID="${HERMES_SO_JOB_ID:-}"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --run)
            RUN="${2:-}"
            shift 2
            ;;
        --event)
            EVENT="${2:-}"
            shift 2
            ;;
        --message)
            MESSAGE="${2:-}"
            shift 2
            ;;
        --pid)
            PID="${2:-}"
            shift 2
            ;;
        --slug)
            SLUG="${2:-}"
            shift 2
            ;;
        --severity)
            SEVERITY="${2:-}"
            shift 2
            ;;
        --job-id)
            JOB_ID="${2:-}"
            shift 2
            ;;
        --next-step)
            NEXT_STEP="${2:-}"
            shift 2
            ;;
        *)
            # Unknown arg — ignore, best-effort
            shift
            ;;
    esac
done

# ---------------------------------------------------------------------------
# Gate: config.py should-notify
# ---------------------------------------------------------------------------

if [[ -z "$EVENT" ]]; then
    # No event specified — cannot gate, exit silently.
    exit 0
fi

SHOULD_NOTIFY="$(python3 "$CONFIG_PY" should-notify --event "$EVENT" 2>/dev/null || true)"
if [[ "$SHOULD_NOTIFY" != "yes" ]]; then
    exit 0
fi

# ---------------------------------------------------------------------------
# Build the full message (append "To kill: kill <pid>" when pid is given)
# ---------------------------------------------------------------------------

FULL_MESSAGE="$MESSAGE"
if [[ -n "$PID" ]]; then
    FULL_MESSAGE="${FULL_MESSAGE}
To kill: kill ${PID}"
fi

TITLE="z-harness watchdog: ${EVENT} (run: ${RUN:-unknown})"

# ---------------------------------------------------------------------------
# Channel 1: Hermes webhook (platform-neutral, HMAC-signed, best-effort)
# ---------------------------------------------------------------------------
# Schema: always "1" — contract version owned by this notifier (not the config schema_version).
_HERMES_SCHEMA_VERSION="1"

HERMES_URL="$(python3 "$CONFIG_PY" get notify.hermes_webhook_url 2>/dev/null || true)"
if [[ -n "$HERMES_URL" ]]; then
    # Source harness_version from version.sh (z_harness_version field).
    _HARNESS_VERSION=""
    if [[ -x "${SCRIPT_DIR}/version.sh" ]]; then
        _HARNESS_VERSION="$(bash "${SCRIPT_DIR}/version.sh" 2>/dev/null \
            | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d.get("z_harness_version","unknown"))' \
            2>/dev/null || true)"
    fi
    [[ -z "$_HARNESS_VERSION" ]] && _HARNESS_VERSION="unknown"

    # Derive repo from git toplevel (best-effort; empty string if outside a repo).
    _REPO="$(git -C "${SCRIPT_DIR}" rev-parse --show-toplevel 2>/dev/null || true)"

    # Build the platform-neutral payload via python3 for safe JSON escaping.
    _HERMES_PAYLOAD="$(python3 -c '
import json, sys, time, uuid, os

schema_version = sys.argv[1]
harness_version = sys.argv[2]
event = sys.argv[3]
run_id = sys.argv[4]
slug = sys.argv[5]
repo = sys.argv[6]
severity = sys.argv[7]
reason = sys.argv[8]
pid_str = sys.argv[9]
job_id = sys.argv[10]
next_step = sys.argv[11]

payload = {
    "schema_version": schema_version,
    "harness_version": harness_version,
    "source": "z-harness",
    "event": event,
    "event_id": str(uuid.uuid4()),
    "run_id": run_id,
    "slug": slug,
    "repo": repo,
    "severity": severity if severity else "warning",
    "reason": reason,
    "ts": int(time.time()),
}
if job_id:
    payload["job_id"] = job_id
if pid_str:
    try:
        payload["pid"] = int(pid_str)
    except ValueError:
        pass
if next_step:
    payload["next_step"] = next_step

print(json.dumps(payload))
' "$_HERMES_SCHEMA_VERSION" \
  "$_HARNESS_VERSION" \
  "${EVENT}" \
  "${RUN:-}" \
  "${SLUG:-}" \
  "${_REPO:-}" \
  "${SEVERITY:-}" \
  "${FULL_MESSAGE:-${MESSAGE:-}}" \
  "${PID:-}" \
  "${JOB_ID:-}" \
  "${NEXT_STEP:-}" \
  2>/dev/null || true)"

    if [[ -n "$_HERMES_PAYLOAD" ]]; then
        # HMAC-sign the payload with the configured secret (empty secret → unsigned header).
        _SECRET="$(python3 "$CONFIG_PY" get notify.hermes_webhook_secret 2>/dev/null || true)"
        _HMAC_SIG=""
        if [[ -n "$_SECRET" ]] && command -v openssl >/dev/null 2>&1; then
            _HMAC_SIG="$(printf '%s' "$_HERMES_PAYLOAD" \
                | openssl dgst -sha256 -hmac "$_SECRET" -hex 2>/dev/null \
                | awk '{print $NF}' || true)"
        fi

        # POST with explicit 3 s max-time; errors are swallowed (best-effort).
        if [[ -n "$_HMAC_SIG" ]]; then
            curl --max-time 3 -fsS \
                -H "Content-Type: application/json" \
                -H "X-Z-Harness-Signature: sha256=${_HMAC_SIG}" \
                -X POST \
                -d "$_HERMES_PAYLOAD" \
                "$HERMES_URL" \
                >/dev/null 2>&1 || true
        else
            curl --max-time 3 -fsS \
                -H "Content-Type: application/json" \
                -X POST \
                -d "$_HERMES_PAYLOAD" \
                "$HERMES_URL" \
                >/dev/null 2>&1 || true
        fi
    fi
fi

# ---------------------------------------------------------------------------
# Channel 2: Discord webhook (best-effort)
# ---------------------------------------------------------------------------

WEBHOOK_URL="$(python3 "$CONFIG_PY" get notify.discord_webhook_url 2>/dev/null || true)"
if [[ -n "$WEBHOOK_URL" ]]; then
    # Build the JSON payload with python3 to handle escaping safely.
    PAYLOAD="$(python3 -c '
import json, sys
title = sys.argv[1][:256]
desc  = sys.argv[2][:4096]
print(json.dumps({"embeds": [{"title": title, "description": desc, "color": 15548997}]}))
' "$TITLE" "$FULL_MESSAGE" 2>/dev/null || true)"

    if [[ -n "$PAYLOAD" ]]; then
        curl -fsS -m 10 \
            -H "Content-Type: application/json" \
            -X POST \
            -d "$PAYLOAD" \
            "$WEBHOOK_URL" \
            >/dev/null 2>&1 || true
    fi
fi

# ---------------------------------------------------------------------------
# Channel 3: macOS desktop notification (best-effort, if osascript available)
# ---------------------------------------------------------------------------

if command -v osascript >/dev/null 2>&1; then
    # Truncate to keep the AppleScript manageable; escape double-quotes.
    NOTIF_BODY="$(printf '%s' "$FULL_MESSAGE" | head -c 500 | sed 's/"/\\"/g')"
    NOTIF_TITLE="$(printf '%s' "$TITLE" | head -c 200 | sed 's/"/\\"/g')"
    osascript -e "display notification \"${NOTIF_BODY}\" with title \"${NOTIF_TITLE}\"" \
        >/dev/null 2>&1 || true
fi

exit 0
