#!/usr/bin/env bash
# log-providers.sh
#
# Resolves all three provider roles, prints a one-line summary, and emits
# a provider_resolved event per role via log-event.sh.
#
# Invoke from each command that may dispatch a consultant or reviewer:
#   source "$(dirname "$0")/log-providers.sh"  -- or --
#   bash scripts/log-providers.sh
#
# Requires: Z_HARNESS_RUN_ID (optional — falls back to "unknown-run").
# Depends on: scripts/resolve-provider.sh, scripts/log-event.sh.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RESOLVE="${SCRIPT_DIR}/resolve-provider.sh"
LOG_EVENT="${SCRIPT_DIR}/log-event.sh"

RUN_ID="${Z_HARNESS_RUN_ID:-unknown-run}"

ROLES=(consultant_primary consultant_secondary reviewer)
SUMMARY_PARTS=()

for ROLE in "${ROLES[@]}"; do
  # resolve-provider.sh exits nonzero if role is unbound or CLI missing.
  DESCRIPTOR="$(bash "$RESOLVE" "$ROLE" 2>/dev/null)" || {
    SUMMARY_PARTS+=("${ROLE}=UNBOUND")
    continue
  }

  PROVIDER="$(python3 -c 'import json,sys; d=json.loads(sys.stdin.read()); print(d["provider"])' <<<"$DESCRIPTOR")"
  MODEL_LABEL="$(python3 -c 'import json,sys; d=json.loads(sys.stdin.read()); print(d.get("model_label",""))' <<<"$DESCRIPTOR")"
  COMMAND="$(python3 -c 'import json,sys; d=json.loads(sys.stdin.read()); print(d["command"])' <<<"$DESCRIPTOR")"

  if [[ -n "$MODEL_LABEL" ]]; then
    SUMMARY_PARTS+=("${ROLE}=${PROVIDER}(${MODEL_LABEL})")
  else
    SUMMARY_PARTS+=("${ROLE}=${PROVIDER}")
  fi

  # Emit provider_resolved event (best-effort — non-fatal if log-event.sh unavailable).
  if [[ -x "$LOG_EVENT" ]]; then
    PAYLOAD="$(python3 -c '
import json, sys
role, provider, command, model_label = sys.argv[1:5]
print(json.dumps({"role": role, "provider": provider, "command": command, "model_label": model_label}))
' "$ROLE" "$PROVIDER" "$COMMAND" "$MODEL_LABEL")"
    bash "$LOG_EVENT" "$RUN_ID" "provider_resolved" "$PAYLOAD" 2>/dev/null || true
  fi
done

# Print one-line summary to stdout.
printf '[providers] %s\n' "$(IFS='  '; echo "${SUMMARY_PARTS[*]}")"
