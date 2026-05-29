#!/usr/bin/env bash
# scripts/sink-claim.sh — Atomic open→running claim with stale-takeover.
#
# Usage:
#   scripts/sink-claim.sh \
#     --entry=<id> \
#     --run=<run-id> \
#     --sink-root=<path> \
#     [--allow-stale]
#
# Lock-ordering invariant (MANDATORY per SPEC §Concurrency-model):
#   Per-entry lock FIRST, then global.  This prevents deadlock.
#
# Exit codes:
#   0  success — prints claim ticket JSON to stdout; per-entry lock is held
#   2  validation error (missing / unknown argument)
#   3  not claimable (status is not open after acquiring per-entry lock)
#   4  staleness drift detected and --allow-stale was NOT passed
#   5  lock timeout (could not acquire per-entry or global lock)
#   7  depth-1 refusal (entry is inert; consumer refuses to claim depth-1)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CLAIM_PY="${SCRIPT_DIR}/sink-claim-helpers.py"

# ── arg parsing ───────────────────────────────────────────────────────────────

ENTRY_ID=""
RUN_ID=""
SINK_ROOT=""
ALLOW_STALE="false"

for arg in "$@"; do
    case "$arg" in
        --entry=*)      ENTRY_ID="${arg#--entry=}" ;;
        --run=*)        RUN_ID="${arg#--run=}" ;;
        --sink-root=*)  SINK_ROOT="${arg#--sink-root=}" ;;
        --allow-stale)  ALLOW_STALE="true" ;;
        *)
            echo "sink-claim: unknown argument: $arg" >&2
            exit 2
            ;;
    esac
done

# ── delegate to Python ────────────────────────────────────────────────────────
exec python3 "$CLAIM_PY" \
    --entry="$ENTRY_ID" \
    --run="$RUN_ID" \
    --sink-root="$SINK_ROOT" \
    --allow-stale="$ALLOW_STALE"
