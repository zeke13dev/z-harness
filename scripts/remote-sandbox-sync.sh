#!/usr/bin/env bash
# Sync the local working tree to a per-(slug, task-id) sandbox on the
# remote host, honoring an excludes list. Invoked by the remote-runner
# subagent before running cargo/qtctl on remote.
#
# Usage:
#   remote-sandbox-sync.sh <remote-host> <slug> <task-id> [--no-delete]
#
# Examples:
#   remote-sandbox-sync.sh zeke-pc expand-sports-ml T030
#   remote-sandbox-sync.sh zeke-pc data-overhaul C-001 --no-delete
#
# Remote path layout:
#   <user@host>:~/dev/qt-bot-sandbox/<slug>/<task-id>/
#
# Exclude file lookup order:
#   1. $(pwd)/.z-harness-rsync-exclude         (per-project override)
#   2. $CLAUDE_PLUGIN_ROOT/.z-harness-rsync-exclude  (plugin default)
#
# Output: writes rsync's stats summary to stdout. Exits non-zero on rsync error.

set -euo pipefail

if [[ $# -lt 3 ]]; then
  echo "usage: remote-sandbox-sync.sh <remote-host> <slug> <task-id> [--no-delete]" >&2
  exit 2
fi

REMOTE_HOST="$1"
SLUG="$2"
TASK_ID="$3"
shift 3

DELETE_FLAG="--delete"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --no-delete) DELETE_FLAG="" ;;
    *) echo "unknown flag: $1" >&2; exit 2 ;;
  esac
  shift
done

LOCAL_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"

EXCLUDE_FILE=""
if [[ -f "$LOCAL_ROOT/.z-harness-rsync-exclude" ]]; then
  EXCLUDE_FILE="$LOCAL_ROOT/.z-harness-rsync-exclude"
elif [[ -f "$PLUGIN_ROOT/.z-harness-rsync-exclude" ]]; then
  EXCLUDE_FILE="$PLUGIN_ROOT/.z-harness-rsync-exclude"
else
  echo "warning: no .z-harness-rsync-exclude found; rsync will ship everything" >&2
fi

REMOTE_PATH="~/dev/qt-bot-sandbox/$SLUG/$TASK_ID/"

# Ensure remote dir exists.
ssh "$REMOTE_HOST" "mkdir -p $REMOTE_PATH" >/dev/null

RSYNC_ARGS=(
  -az
  --info=stats2
  $DELETE_FLAG
)
if [[ -n "$EXCLUDE_FILE" ]]; then
  RSYNC_ARGS+=(--exclude-from="$EXCLUDE_FILE")
fi

# Trailing slash on source means "contents of dir", not the dir itself.
rsync "${RSYNC_ARGS[@]}" "$LOCAL_ROOT/" "$REMOTE_HOST:$REMOTE_PATH"
