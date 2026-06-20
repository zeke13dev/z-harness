#!/usr/bin/env bash
# notify-watchdog.sh — Out-of-band human alert for watchdog events.
#
# Usage:
#   notify-watchdog.sh --run <run_id> --event <watchdog_stall|watchdog_timeout> \
#                       --message <text> [--pid <pid>]
#
# Behavior:
#   1. Gates on `config.py should-notify --event <event>`: exits 0 silently if "no".
#   2. Sends to all available channels (best-effort):
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
# Channel 1: Discord webhook (best-effort)
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
# Channel 2: macOS desktop notification (best-effort, if osascript available)
# ---------------------------------------------------------------------------

if command -v osascript >/dev/null 2>&1; then
    # Truncate to keep the AppleScript manageable; escape double-quotes.
    NOTIF_BODY="$(printf '%s' "$FULL_MESSAGE" | head -c 500 | sed 's/"/\\"/g')"
    NOTIF_TITLE="$(printf '%s' "$TITLE" | head -c 200 | sed 's/"/\\"/g')"
    osascript -e "display notification \"${NOTIF_BODY}\" with title \"${NOTIF_TITLE}\"" \
        >/dev/null 2>&1 || true
fi

exit 0
