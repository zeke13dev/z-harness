#!/usr/bin/env bash
# write-clear-checkpoint.sh — Write watcher-readable clear checkpoint artifacts.
#
# This is the common command-side producer for z-harness clear/yield boundaries.
# It writes handoff.json unconditionally, preserves SESSION.md/SESSION_CONTEXT.md
# support through write-handoff.sh, emits stable watcher telemetry, and can own
# a small phase fast-forward state file so workflow skills do not open-code local
# ack files.
#
# Env vars (read):
#   Z_HARNESS_PLAN_DIR            — plan directory (required)
#   Z_HARNESS_SLUG                — plan slug (optional)
#   Z_HARNESS_AGENT               — provenance agent for handoff.json (optional; default pi)
#   RUN                           — current run id for telemetry (optional; default orchestration)
#   Z_HARNESS_CHECKPOINT_STATUS   — handoff status (default context_pressure; falls back to Z_HARNESS_HANDOFF_STATUS)
#   Z_HARNESS_CHECKPOINT_NEXT_STEP — override handoff next_step (falls back to Z_HARNESS_HANDOFF_NEXT_STEP)
#   Z_HARNESS_CHECKPOINT_RESUME_COMMAND — status-line/event resume command override (optional)
#   Z_HARNESS_CHECKPOINT_PHASE_NAME — human phase label for telemetry/state (optional)
#   Z_HARNESS_CHECKPOINT_PHASE_ID — stable phase id; enables default state file (optional)
#   Z_HARNESS_CHECKPOINT_STATE_FILE — explicit state file path; relative paths are under the plan dir (optional)
#   Z_HARNESS_CHECKPOINT_COMPLETED_ARTIFACT — durable artifact that must exist for checkpoint/fast-forward (optional)
#   Z_HARNESS_CHECKPOINT_FAST_FORWARD_GUARD — caller-computed stale-state guard, e.g. HEAD/hash/fingerprint (optional)
#   Z_HARNESS_CHECKPOINT_STALE_MODE — reject|refresh|ignore when existing state is stale (default reject)
#   Z_HARNESS_CHECKPOINT_PRODUCER — logical workflow producer name for telemetry/state (optional)
#   Z_HARNESS_CHECKPOINT_PRODUCER_META_JSON — JSON object with producer metadata (optional)
#
# Output:
#   Writes $Z_HARNESS_PLAN_DIR/handoff.json via write-handoff.sh.
#   Writes a checkpoint state file when phase/state/guard/artifact metadata is set.
#   Prints STATUS: clear_checkpoint ... on a newly written checkpoint.
#   Prints STATUS: clear_checkpoint_fast_forward ... when existing state is current.

set -euo pipefail

_PLUGIN_ROOT="${ANTIGRAVITY_PLUGIN_ROOT:-${CLAUDE_PLUGIN_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}}"

if [[ -z "${Z_HARNESS_PLAN_DIR:-}" ]]; then
  echo "[write-clear-checkpoint] Z_HARNESS_PLAN_DIR is not set" >&2
  exit 1
fi

PLAN_DIR="$Z_HARNESS_PLAN_DIR"
HANDOFF_FILE="$PLAN_DIR/handoff.json"
SESSION_FILE="$PLAN_DIR/SESSION.md"
TASKS_FILE="$PLAN_DIR/TASKS.md"
STATUS_VALUE="${Z_HARNESS_CHECKPOINT_STATUS:-${Z_HARNESS_HANDOFF_STATUS:-context_pressure}}"
RUN_ID="${RUN:-orchestration}"
RESUME_COMMAND="${Z_HARNESS_CHECKPOINT_RESUME_COMMAND:-}"
PHASE_NAME="${Z_HARNESS_CHECKPOINT_PHASE_NAME:-}"
PHASE_ID="${Z_HARNESS_CHECKPOINT_PHASE_ID:-}"
COMPLETED_ARTIFACT="${Z_HARNESS_CHECKPOINT_COMPLETED_ARTIFACT:-}"
FAST_FORWARD_GUARD="${Z_HARNESS_CHECKPOINT_FAST_FORWARD_GUARD:-}"
STALE_MODE="${Z_HARNESS_CHECKPOINT_STALE_MODE:-reject}"
PRODUCER="${Z_HARNESS_CHECKPOINT_PRODUCER:-write-clear-checkpoint.sh}"
PRODUCER_META_JSON="${Z_HARNESS_CHECKPOINT_PRODUCER_META_JSON:-}"
if [[ -z "$PRODUCER_META_JSON" ]]; then
  PRODUCER_META_JSON="${Z_HARNESS_CHECKPOINT_PRODUCER_METADATA:-}"
fi
if [[ -z "$PRODUCER_META_JSON" ]]; then
  PRODUCER_META_JSON="{}"
fi
STATE_FILE="${Z_HARNESS_CHECKPOINT_STATE_FILE:-}"

case "$STATUS_VALUE" in
  context_pressure|clean_break|complete|blocked) ;;
  *)
    echo "[write-clear-checkpoint] invalid Z_HARNESS_CHECKPOINT_STATUS: $STATUS_VALUE" >&2
    exit 2
    ;;
esac

case "$STALE_MODE" in
  reject|refresh|ignore) ;;
  *)
    echo "[write-clear-checkpoint] invalid Z_HARNESS_CHECKPOINT_STALE_MODE: $STALE_MODE" >&2
    exit 2
    ;;
esac

python3 -c '
import json, sys
try:
    value = json.loads(sys.argv[1] or "{}")
except json.JSONDecodeError as exc:
    print(f"[write-clear-checkpoint] invalid Z_HARNESS_CHECKPOINT_PRODUCER_META_JSON: {exc}", file=sys.stderr)
    raise SystemExit(2)
if not isinstance(value, dict):
    print("[write-clear-checkpoint] Z_HARNESS_CHECKPOINT_PRODUCER_META_JSON must be a JSON object", file=sys.stderr)
    raise SystemExit(2)
' "$PRODUCER_META_JSON"

if [[ -n "$STATE_FILE" ]]; then
  case "$STATE_FILE" in
    /*) ;;
    *) STATE_FILE="$PLAN_DIR/$STATE_FILE" ;;
  esac
elif [[ -n "$PHASE_ID" || -n "$FAST_FORWARD_GUARD" || -n "$COMPLETED_ARTIFACT" ]]; then
  SAFE_PHASE_ID="$(python3 -c '
import re, sys
raw = sys.argv[1] or "checkpoint"
safe = re.sub(r"[^A-Za-z0-9_.-]+", "-", raw).strip("-._")
print(safe or "checkpoint")
' "$PHASE_ID")"
  STATE_FILE="$PLAN_DIR/.clear-checkpoint-${SAFE_PHASE_ID}.json"
fi

if [[ -z "$RESUME_COMMAND" ]]; then
  RESUME_COMMAND="/z-execute"
  if [[ -n "${Z_HARNESS_SLUG:-}" ]]; then
    RESUME_COMMAND="/z-execute ${Z_HARNESS_SLUG}"
  fi
fi

if [[ -n "$COMPLETED_ARTIFACT" && ! -f "$COMPLETED_ARTIFACT" ]]; then
  echo "[write-clear-checkpoint] completed artifact does not exist: $COMPLETED_ARTIFACT" >&2
  exit 3
fi

if [[ -n "$STATE_FILE" && -f "$STATE_FILE" ]]; then
  STATE_CHECK="$(python3 - "$STATE_FILE" "$PHASE_ID" "$FAST_FORWARD_GUARD" "$COMPLETED_ARTIFACT" <<'PY'
import json
import sys
from pathlib import Path

state_path, phase_id, guard, completed_artifact = sys.argv[1:5]
try:
    data = json.loads(Path(state_path).read_text(encoding="utf-8"))
except Exception as exc:
    print(json.dumps({"result": "stale", "reason": "invalid_state_json", "detail": str(exc)}))
    raise SystemExit(0)

if phase_id and data.get("phase_id") != phase_id:
    print(json.dumps({"result": "stale", "reason": "phase_id_mismatch", "stored": data.get("phase_id"), "current": phase_id}))
elif guard and data.get("fast_forward_guard") != guard:
    print(json.dumps({"result": "stale", "reason": "fast_forward_guard_mismatch", "stored": data.get("fast_forward_guard"), "current": guard}))
elif completed_artifact and data.get("completed_artifact") and data.get("completed_artifact") != completed_artifact:
    print(json.dumps({"result": "stale", "reason": "completed_artifact_mismatch", "stored": data.get("completed_artifact"), "current": completed_artifact}))
else:
    artifact = completed_artifact or data.get("completed_artifact") or ""
    if artifact and not Path(artifact).is_file():
        print(json.dumps({"result": "stale", "reason": "completed_artifact_missing", "completed_artifact": artifact}))
    else:
        data["result"] = "fast_forward"
        print(json.dumps(data))
PY
)"
  STATE_RESULT="$(printf '%s' "$STATE_CHECK" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("result","stale"))')"
  if [[ "$STATE_RESULT" == "fast_forward" ]]; then
    FAST_FORWARD_PAYLOAD="$(python3 - "$STATE_CHECK" "$STATE_FILE" "$RESUME_COMMAND" "$PRODUCER_META_JSON" <<'PY'
import json
import sys

state = json.loads(sys.argv[1])
payload = {
    "checkpoint_state_path": sys.argv[2],
    "handoff_path": state.get("handoff_path"),
    "session_path": state.get("session_path"),
    "status": state.get("status"),
    "resume_command": sys.argv[3],
    "producer": state.get("producer") or "write-clear-checkpoint.sh",
    "consumer": "watcher",
    "fast_forward": True,
}
for key in ("phase_name", "phase_id", "completed_artifact", "fast_forward_guard"):
    if state.get(key):
        payload[key] = state[key]
metadata = state.get("producer_metadata")
if metadata is None:
    metadata = json.loads(sys.argv[4] or "{}")
if metadata:
    payload["producer_metadata"] = metadata
print(json.dumps(payload))
PY
)"
    bash "$_PLUGIN_ROOT/scripts/log-event.sh" "$RUN_ID" clear_checkpoint_fast_forward "$FAST_FORWARD_PAYLOAD" >/dev/null 2>&1 || true
    printf 'STATUS: clear_checkpoint_fast_forward state=%s phase_id=%s resume=%q\n' \
      "$STATE_FILE" "${PHASE_ID:-none}" "$RESUME_COMMAND"
    exit 0
  fi

  STALE_REASON="$(printf '%s' "$STATE_CHECK" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("reason","unknown"))')"
  case "$STALE_MODE" in
    reject)
      echo "[write-clear-checkpoint] stale checkpoint state rejected: $STATE_FILE reason=$STALE_REASON" >&2
      exit 3
      ;;
    refresh)
      rm -f "$STATE_FILE"
      ;;
    ignore)
      ;;
  esac
fi

export Z_HARNESS_HANDOFF_STATUS="$STATUS_VALUE"
if [[ -n "${Z_HARNESS_CHECKPOINT_NEXT_STEP:-${Z_HARNESS_HANDOFF_NEXT_STEP:-}}" ]]; then
  export Z_HARNESS_HANDOFF_NEXT_STEP="${Z_HARNESS_CHECKPOINT_NEXT_STEP:-${Z_HARNESS_HANDOFF_NEXT_STEP:-}}"
fi

HANDOFF_OUT="$(bash "$_PLUGIN_ROOT/scripts/write-handoff.sh" 2>&1)" || {
  rc=$?
  echo "$HANDOFF_OUT" >&2
  exit "$rc"
}

HANDOFF_BYTES="$(wc -c < "$HANDOFF_FILE" | tr -d '[:space:]')"
SESSION_PATH=""
if [[ -f "$SESSION_FILE" ]]; then
  SESSION_PATH="$SESSION_FILE"
fi

NEXT_PENDING=""
if [[ -f "$TASKS_FILE" ]]; then
  NEXT_PENDING="$(bash "$_PLUGIN_ROOT/scripts/session-helpers.sh" next_pending_task "$TASKS_FILE" 2>/dev/null || true)"
fi

PAYLOAD="$(python3 - "$HANDOFF_FILE" "$SESSION_PATH" "$STATUS_VALUE" "$RESUME_COMMAND" "$NEXT_PENDING" "$PRODUCER" "$PHASE_NAME" "$PHASE_ID" "$COMPLETED_ARTIFACT" "$FAST_FORWARD_GUARD" "$STATE_FILE" "$PRODUCER_META_JSON" "$STALE_MODE" <<'PY'
import json
import sys

(
    handoff_path,
    session_path,
    status,
    resume_command,
    next_pending,
    producer,
    phase_name,
    phase_id,
    completed_artifact,
    fast_forward_guard,
    state_file,
    producer_meta_json,
    stale_mode,
) = sys.argv[1:14]

payload = {
    "handoff_path": handoff_path,
    "session_path": session_path or None,
    "status": status,
    "resume_command": resume_command,
    "next_pending": next_pending or None,
    "producer": producer,
    "consumer": "watcher",
}
if phase_name:
    payload["phase_name"] = phase_name
if phase_id:
    payload["phase_id"] = phase_id
if completed_artifact:
    payload["completed_artifact"] = completed_artifact
if fast_forward_guard:
    payload["fast_forward_guard"] = fast_forward_guard
if state_file:
    payload["checkpoint_state_path"] = state_file
    payload["stale_mode"] = stale_mode
metadata = json.loads(producer_meta_json or "{}")
if metadata:
    payload["producer_metadata"] = metadata
print(json.dumps(payload))
PY
)"

if [[ -n "$STATE_FILE" ]]; then
  mkdir -p "$(dirname "$STATE_FILE")"
  STATE_TMP="$STATE_FILE.tmp.$$"
  python3 - "$STATE_TMP" "$PAYLOAD" "$RUN_ID" <<'PY'
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

state_path, payload_json, run_id = sys.argv[1:4]
payload = json.loads(payload_json)
state = {
    "schema_version": 1,
    "written_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    "run": run_id,
    "handoff_path": payload["handoff_path"],
    "session_path": payload.get("session_path"),
    "status": payload["status"],
    "resume_command": payload["resume_command"],
    "producer": payload["producer"],
}
for key in (
    "phase_name",
    "phase_id",
    "completed_artifact",
    "fast_forward_guard",
    "producer_metadata",
):
    if payload.get(key):
        state[key] = payload[key]
Path(state_path).write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
PY
  mv "$STATE_TMP" "$STATE_FILE"
fi

bash "$_PLUGIN_ROOT/scripts/log-event.sh" "$RUN_ID" clear_checkpoint_written "$PAYLOAD" >/dev/null 2>&1 || true

printf 'STATUS: clear_checkpoint handoff=%s session=%s status=%s resume=%q bytes=%s phase_id=%s state=%s\n' \
  "$HANDOFF_FILE" "${SESSION_PATH:-none}" "$STATUS_VALUE" "$RESUME_COMMAND" "$HANDOFF_BYTES" \
  "${PHASE_ID:-none}" "${STATE_FILE:-none}"

# Human copy-paste resume block — printed AFTER the STATUS line so prefix
# parsers (`case "$CHECKPOINT_OUT" in STATUS:\ clear_checkpoint*)` and the
# startswith() test assertions) are unaffected. This is for a human operator
# driving the /clear + resume by hand.
printf '\nResume after /clear — copy-paste:\n\n```\n%s\n```\n' "$RESUME_COMMAND"
