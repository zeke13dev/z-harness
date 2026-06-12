#!/usr/bin/env bash
# Emit a shortcut_proposed event and signal the caller to surface an inline ask.
#
# Usage:
#   surface-shortcut.sh --chosen "<looser path>" --declined "<robust alternative>" --why "<reason>"
#
# Exit-code contract (M3):
#   exit 1 — SUCCESS path: non-empty --declined + non-empty --chosen + RUN set,
#             shortcut_proposed event emitted OK. Deterministic 1 — the shortcut
#             signal the caller turns into an inline category=shortcut ask. This
#             is independent of log-event.sh's own return code.
#   exit 0 — empty or missing --declined: no-op, no event (Invariant 6: not a
#             shortcut without a namable alternative).
#   exit 2 — ERROR / infra condition; NO event is emitted (or the event was lost):
#             - non-empty --declined but empty/missing --chosen (caller wiring bug),
#             - RUN env var unset/empty (caller wiring bug),
#             - log-event.sh itself failed (event NOT recorded).
#
# The --why argument is optional; defaults to empty string.
# --chosen is required (non-empty) when --declined is non-empty.
#
# Environment:
#   RUN (required when --declined non-empty) — the current run id, passed to log-event.sh.
#         If unset/empty on the event path, the script exits 2 without logging.
#   PLUGIN_ROOT resolved via ANTIGRAVITY_PLUGIN_ROOT > CLAUDE_PLUGIN_ROOT > script dir parent.

set -euo pipefail

CHOSEN=""
DECLINED=""
WHY=""

# Parse flags
while [[ $# -gt 0 ]]; do
  case "$1" in
    --chosen)
      if [[ $# -lt 2 ]]; then
        echo "surface-shortcut.sh: --chosen requires a value" >&2
        exit 2
      fi
      CHOSEN="$2"
      shift 2
      ;;
    --declined)
      if [[ $# -lt 2 ]]; then
        echo "surface-shortcut.sh: --declined requires a value" >&2
        exit 2
      fi
      DECLINED="$2"
      shift 2
      ;;
    --why)
      if [[ $# -lt 2 ]]; then
        echo "surface-shortcut.sh: --why requires a value" >&2
        exit 2
      fi
      WHY="$2"
      shift 2
      ;;
    *)
      echo "surface-shortcut.sh: unknown flag: $1" >&2
      exit 2
      ;;
  esac
done

# Invariant 6: no namable alternative → not a shortcut; silent no-op.
if [[ -z "$DECLINED" ]]; then
  exit 0
fi

# A shortcut declines a namable robust alternative IN FAVOUR OF a chosen looser
# path. Both are mandatory; a non-empty --declined with no --chosen is a caller
# wiring bug, not a shortcut. Fail fast (exit 2) and emit NO event.
if [[ -z "$CHOSEN" ]]; then
  echo "surface-shortcut.sh: --chosen is required when --declined is non-empty (a shortcut needs both a chosen looser route and a declined alternative)" >&2
  exit 2
fi

# RUN must be set so the event is attributed to the correct run. An unset/empty
# RUN is a caller wiring bug; logging to a placeholder would hide it and corrupt
# telemetry. Fail fast (exit 2) and emit NO event — do NOT default to a placeholder.
if [[ -z "${RUN:-}" ]]; then
  echo "surface-shortcut.sh: RUN env var must be set (non-empty) to attribute the shortcut_proposed event to a run" >&2
  exit 2
fi

# Resolve plugin root the same way sibling scripts do.
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PLUGIN_ROOT="${ANTIGRAVITY_PLUGIN_ROOT:-${CLAUDE_PLUGIN_ROOT:-$(dirname "$SCRIPT_DIR")}}"
LOG_EVENT="$PLUGIN_ROOT/scripts/log-event.sh"

if [[ ! -x "$LOG_EVENT" ]]; then
  echo "surface-shortcut.sh: cannot find executable $LOG_EVENT" >&2
  exit 2
fi

# Build JSON payload via python3 to handle quoting correctly.
PAYLOAD="$(python3 - "$CHOSEN" "$DECLINED" "$WHY" <<'PYEOF'
import json, sys
chosen, declined, why = sys.argv[1], sys.argv[2], sys.argv[3]
obj = {"chosen": chosen, "declined": declined}
if why:
    obj["why"] = why
print(json.dumps(obj, separators=(",", ":")))
PYEOF
)"

# Emit the event, but DO NOT let log-event.sh's exit code leak into ours: the M3
# contract requires the success path to return a deterministic 1 (the shortcut
# signal the caller acts on), regardless of what log-event.sh returns. Capture
# its rc explicitly under `set -e` (|| true keeps the script alive on non-zero).
LOG_RC=0
bash "$LOG_EVENT" "$RUN" shortcut_proposed "$PAYLOAD" || LOG_RC=$?

if [[ "$LOG_RC" -ne 0 ]]; then
  # The event was NOT recorded. Surface a distinct infra-failure code (2) so a
  # silent event-loss can never masquerade as the shortcut signal (1) or success (0).
  echo "surface-shortcut.sh: log-event.sh failed (rc=$LOG_RC); shortcut_proposed event NOT recorded" >&2
  exit 2
fi

# Exit 1: deterministic shortcut signal — tells the caller to surface an inline
# category=shortcut ask. Independent of log-event.sh's own return code.
exit 1
