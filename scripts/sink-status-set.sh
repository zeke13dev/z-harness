#!/usr/bin/env bash
# scripts/sink-status-set.sh — Generic status transition primitive for the follow-up sink.
#
# Usage:
#   scripts/sink-status-set.sh \
#     --entry=<id> \
#     --to=<status> \
#     --by=<actor> \
#     --sink-root=<path> \
#     [--evidence=<path>] \
#     [--reason='<text>'] \
#     [--completion-mode=<mode>] \
#     [--via-claim-ticket=<json>] \
#     [--diff=<path>]
#
# Lock ordering: per-entry lock must already be held by caller (via --via-claim-ticket),
# or this script re-acquires it. Global lock acquired after per-entry lock is confirmed.
#
# Exit codes:
#   0  success
#   2  validation error (missing/invalid args)
#   3  illegal transition (state machine violation)
#   4  evidence rejected (audit or auto-close check failed)
#   5  lock-timeout
#   6  completion-mode conflict (mutex violation)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
IMPL_PY="${SCRIPT_DIR}/sink-status-set-impl.py"

# ── arg parsing ───────────────────────────────────────────────────────────────

ENTRY_ID=""
TO_STATUS=""
BY_ACTOR=""
SINK_ROOT=""
EVIDENCE=""
REASON=""
COMPLETION_MODE=""
VIA_CLAIM_TICKET=""
DIFF=""

for arg in "$@"; do
    case "$arg" in
        --entry=*)             ENTRY_ID="${arg#--entry=}" ;;
        --to=*)                TO_STATUS="${arg#--to=}" ;;
        --by=*)                BY_ACTOR="${arg#--by=}" ;;
        --sink-root=*)         SINK_ROOT="${arg#--sink-root=}" ;;
        --evidence=*)          EVIDENCE="${arg#--evidence=}" ;;
        --reason=*)            REASON="${arg#--reason=}" ;;
        --completion-mode=*)   COMPLETION_MODE="${arg#--completion-mode=}" ;;
        --via-claim-ticket=*)  VIA_CLAIM_TICKET="${arg#--via-claim-ticket=}" ;;
        --diff=*)              DIFF="${arg#--diff=}" ;;
        *)
            echo "sink-status-set: unknown argument: $arg" >&2
            exit 2
            ;;
    esac
done

# ── delegate to Python ────────────────────────────────────────────────────────
exec python3 "$IMPL_PY" \
    --entry="$ENTRY_ID" \
    --to="$TO_STATUS" \
    --by="$BY_ACTOR" \
    --sink-root="$SINK_ROOT" \
    --evidence="$EVIDENCE" \
    --reason="$REASON" \
    --completion-mode="$COMPLETION_MODE" \
    --via-claim-ticket="$VIA_CLAIM_TICKET" \
    --diff="$DIFF"
