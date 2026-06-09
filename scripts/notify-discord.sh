#!/usr/bin/env bash
# notify-discord.sh — Send a Discord webhook notification
#
# Usage: notify-discord.sh <title> <body>
#   Reads notify.discord_webhook_url from z-harness config.
#   Posts a Markdown embed to Discord.
#   3-second timeout. Non-fatal on failure.
#   Does NOT log the webhook URL.
#
# Exit: 0 on success or if Discord is disabled (no URL), 1 on send failure.

set -euo pipefail

TITLE="${1:-z-harness notification}"
BODY="${2:-}"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CONFIG_PY="${SCRIPT_DIR}/config.py"

# Read webhook URL from config — empty means disabled
WEBHOOK_URL="$("$CONFIG_PY" get notify.discord_webhook_url 2>/dev/null || true)"
if [ -z "$WEBHOOK_URL" ]; then
    exit 0  # Discord disabled — not an error
fi

# Build Discord embed JSON payload
# Fields: title (first 256 chars), description (first 4096 chars), color, timestamp
TITLE_TRUNC="${TITLE:0:256}"
BODY_TRUNC="${BODY:0:4096}"
TIMESTAMP="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

PAYLOAD="$(python3 -c '
import json, sys
print(json.dumps({
    "embeds": [{
        "title": sys.argv[1],
        "description": sys.argv[2],
        "color": 3447003,  # blurple
        "timestamp": sys.argv[3]
    }]
}))
' "$TITLE_TRUNC" "$BODY_TRUNC" "$TIMESTAMP")"

# Send to Discord with 3s timeout
HTTP_CODE="$(curl -s -o /dev/null -w "%{http_code}" \
    -H "Content-Type: application/json" \
    -X POST \
    -d "$PAYLOAD" \
    --max-time 3 \
    "$WEBHOOK_URL" 2>/dev/null || true)"

if [ "$HTTP_CODE" = "204" ] || [ "$HTTP_CODE" = "200" ]; then
    exit 0
fi

# Log failure (no URL in log)
bash "${SCRIPT_DIR}/log-event.sh" "orchestration" discord_notify_failed \
    "$(printf '{"http_code":"%s","title":"%s"}' "$HTTP_CODE" "$TITLE_TRUNC")" 2>/dev/null || true
exit 1
