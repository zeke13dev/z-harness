#!/usr/bin/env bash
# scripts/sink-add.sh — writer primitive for the follow-up sink.
#
# Usage:
#   scripts/sink-add.sh \
#     --sink=<project|global> \
#     --priority=<P0|P1|P2|P3> \
#     --name='<short title>' \
#     --recommended-command='/z-<cmd> ...' \
#     --source-artifact='<path>' \
#     --cited-paths='<comma-sep paths>' \
#     [--auto-close-eligible] \
#     [--safe-to-retry] \
#     [--prompt-body='<inline body>'|--prompt-body-file='<path>']
#
# Exit codes:
#   0  success
#   2  validation error
#   3  dedup-skip (duplicate entry already exists)
#   4  depth-exceeded
#   5  lock-timeout
#   6  diffuse-cited-paths (common ancestor too shallow)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HELPERS_PY="${SCRIPT_DIR}/sink-add-helpers.py"

# ── arg parsing ───────────────────────────────────────────────────────────────

SINK=""
PRIORITY=""
NAME=""
RECOMMENDED_COMMAND=""
SOURCE_ARTIFACT=""
CITED_PATHS=""
AUTO_CLOSE_ELIGIBLE="false"
SAFE_TO_RETRY="false"
PROMPT_BODY=""
PROMPT_BODY_FILE=""

for arg in "$@"; do
    case "$arg" in
        --sink=*)              SINK="${arg#--sink=}" ;;
        --priority=*)          PRIORITY="${arg#--priority=}" ;;
        --name=*)              NAME="${arg#--name=}" ;;
        --recommended-command=*) RECOMMENDED_COMMAND="${arg#--recommended-command=}" ;;
        --source-artifact=*)   SOURCE_ARTIFACT="${arg#--source-artifact=}" ;;
        --cited-paths=*)       CITED_PATHS="${arg#--cited-paths=}" ;;
        --auto-close-eligible) AUTO_CLOSE_ELIGIBLE="true" ;;
        --safe-to-retry)       SAFE_TO_RETRY="true" ;;
        --prompt-body=*)       PROMPT_BODY="${arg#--prompt-body=}" ;;
        --prompt-body-file=*)  PROMPT_BODY_FILE="${arg#--prompt-body-file=}" ;;
        *)
            echo "sink-add: unknown argument: $arg" >&2
            exit 2
            ;;
    esac
done

# ── delegate all logic to Python ──────────────────────────────────────────────
exec python3 "$HELPERS_PY" \
    --sink="$SINK" \
    --priority="$PRIORITY" \
    --name="$NAME" \
    --recommended-command="$RECOMMENDED_COMMAND" \
    --source-artifact="$SOURCE_ARTIFACT" \
    --cited-paths="$CITED_PATHS" \
    --auto-close-eligible="$AUTO_CLOSE_ELIGIBLE" \
    --safe-to-retry="$SAFE_TO_RETRY" \
    --prompt-body="$PROMPT_BODY" \
    --prompt-body-file="$PROMPT_BODY_FILE"
