#!/usr/bin/env bash
# Emit a normalized decision event to the run's event log.
#
# Usage:
#   log-decision.sh <run> <question_id> <chosen> \
#     [--options <json-array>] [--tentative <val>] [--source <command>] \
#     [--kind user_choice|user_override|auto]
#
# Thin wrapper over log-event.sh that enforces a normalized decision payload
# so the axiom extractor (axiom-extract.py) has a stable grouping key.
#
# Payload written:
#   { question_id, decision_key, chosen, options, tentative,
#     source_command, event_id }
# where decision_key == question_id (the extractor's R8 grouping key).
#
# event_id formula: e-<sha1(run + question_id + chosen + ts)[:8]>
# ts is the ISO-8601 timestamp generated at runtime; it makes event_id unique
# per emission (callers cite run+event_id together).
#
# Gating: if axioms.auto_extract_post_run is "false", this script is a silent
# no-op (exit 0, writes nothing).  "true" (or unset/missing config) = emit.

set -euo pipefail

# Gating check first — cheap early exit.
# Read axioms.auto_extract_post_run via config.py; fall back to "true" (emit) if config unavailable.
_LOG_DECISION_SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
_AXIOM_EXTRACT="$(python3 "$_LOG_DECISION_SCRIPT_DIR/config.py" get axioms.auto_extract_post_run 2>/dev/null || echo "true")"
if [[ "$_AXIOM_EXTRACT" == "false" ]]; then
  exit 0
fi

if [[ $# -lt 3 ]]; then
  echo "usage: log-decision.sh <run> <question_id> <chosen> [--options <json-array>] [--tentative <val>] [--source <command>] [--kind user_choice|user_override|auto]" >&2
  exit 2
fi

RUN="$1"
QUESTION_ID="$2"
CHOSEN="$3"
shift 3

# Defaults
OPTIONS="[]"
TENTATIVE=""
SOURCE_COMMAND=""
KIND_ARG="auto"

# Parse optional flags
while [[ $# -gt 0 ]]; do
  case "$1" in
    --options)
      OPTIONS="${2:?--options requires a json-array value}"
      shift 2
      ;;
    --tentative)
      TENTATIVE="${2:?--tentative requires a value}"
      shift 2
      ;;
    --source)
      SOURCE_COMMAND="${2:?--source requires a value}"
      shift 2
      ;;
    --kind)
      KIND_ARG="${2:?--kind requires user_choice|user_override|auto}"
      shift 2
      ;;
    *)
      echo "log-decision.sh: unknown flag: $1" >&2
      exit 2
      ;;
  esac
done

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
LOG_EVENT="$SCRIPT_DIR/log-event.sh"

if [[ ! -x "$LOG_EVENT" ]]; then
  echo "log-decision.sh: cannot find executable $LOG_EVENT" >&2
  exit 2
fi

# Generate timestamp + event_id + payload via python3 stdlib only.
PAYLOAD="$(python3 - "$RUN" "$QUESTION_ID" "$CHOSEN" "$OPTIONS" "$TENTATIVE" "$SOURCE_COMMAND" "$KIND_ARG" <<'PYEOF'
import hashlib, json, sys, datetime

run, question_id, chosen, options_raw, tentative, source_command, kind_arg = sys.argv[1:8]

# Timestamp — timezone-aware UTC (datetime.timezone available since Python 3.2)
ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

# event_id: e-<sha1(run + question_id + chosen + ts)[:8]>
digest = hashlib.sha1((run + question_id + chosen + ts).encode()).hexdigest()
event_id = "e-" + digest[:8]

# Validate options is a JSON array; fall back to [] on error.
try:
    options = json.loads(options_raw)
    if not isinstance(options, list):
        options = []
except (ValueError, TypeError):
    options = []

# Kind selection
if kind_arg == "auto":
    if tentative and chosen != tentative:
        kind = "user_override"
    else:
        kind = "user_choice"
elif kind_arg in ("user_choice", "user_override"):
    kind = kind_arg
else:
    print(f"log-decision.sh: invalid --kind value: {kind_arg}", file=sys.stderr)
    sys.exit(2)

payload = {
    "ts": ts,
    "question_id": question_id,
    "decision_key": question_id,
    "chosen": chosen,
    "options": options,
    "tentative": tentative if tentative else None,
    "source_command": source_command if source_command else None,
    "event_id": event_id,
}

# Emit two lines: kind on first, payload JSON on second.
print(kind)
print(json.dumps(payload, separators=(",", ":")))
PYEOF
)"

# Split the two-line output: first line = kind, second line = JSON payload.
KIND="$(printf '%s\n' "$PAYLOAD" | head -n1)"
PAYLOAD_JSON="$(printf '%s\n' "$PAYLOAD" | tail -n+2)"

bash "$LOG_EVENT" "$RUN" "$KIND" "$PAYLOAD_JSON"
