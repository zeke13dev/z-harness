#!/usr/bin/env bash
# scripts/followup-reconcile-notion.sh — sweep notion_sync_pending entries.
#
# Reads the materialized view for both project + global sinks.
# For each entry with notion_sync_pending == true, re-invokes notion-push.py.
# On success: appends notion_synced + notion_sync_cleared events to index.jsonl.
# Reports JSON summary {swept_count, succeeded, failed, conflicts} to stdout.
# Exits 0 even on partial success (best-effort sweep).
#
# Usage:
#   scripts/followup-reconcile-notion.sh [--project-sink-root=<path>]
#                                         [--global-sink-root=<path>]
#                                         [--dry-run]

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RECONCILE_PY="${SCRIPT_DIR}/followup-reconcile-notion-impl.py"

exec python3 "$RECONCILE_PY" "$@"
