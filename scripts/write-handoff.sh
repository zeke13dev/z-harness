#!/usr/bin/env bash
# write-handoff.sh — Write handoff.json to the plan directory at a clear checkpoint.
#
# Called by the legacy /z-execute checkpoint flow after the context-curator writes
# SESSION.md. Reads plan state (TASKS.md, SESSION.md, env vars) and produces a
# handoff.json conforming to docs/schemas/handoff.schema.json (handoff-v1).
#
# Env vars (read):
#   Z_HARNESS_PLAN_DIR  — plan directory (required; handoff.json written here)
#   Z_HARNESS_SLUG       — plan slug (optional; if unset, slug is null)
#   Z_HARNESS_MODEL      — model name (optional; falls back to "unknown")
#   Z_HARNESS_CONTEXT_PCT — context usage percentage (optional)
#   Z_HARNESS_AGENT      — agent name (optional; default "pi")
#   Z_HARNESS_HANDOFF_STATUS — status override (optional; default clean_break)
#   Z_HARNESS_HANDOFF_NEXT_STEP — next_step override (optional)
#
# Attend-yield env vars (read ONLY when Z_HARNESS_ATTEND_RESUME=1 — these populate
# the optional attend_resume predicate and bump protocol_version to "1.1"):
#   Z_HARNESS_ATTEND_RESUME          — set to "1" to emit a 1.1 handoff with attend_resume
#   Z_HARNESS_ATTEND_HEAD_SHA        — git HEAD sha captured at yield
#   Z_HARNESS_ATTEND_PHASE           — chain step to re-enter at
#   Z_HARNESS_ATTEND_DONE_SET_HASH   — session-helpers.sh done_set_hash of TASKS.md
#   Z_HARNESS_ATTEND_DIRTY_FP        — digest of git status --porcelain
#   Z_HARNESS_ATTEND_SESSION_ID      — yield-time session id
#
# Output:
#   Writes $Z_HARNESS_PLAN_DIR/handoff.json
#   Prints "STATUS: written bytes=<n>" on success to stdout
#   Exits non-zero on failure

set -euo pipefail

# ---------------------------------------------------------------------------
# Validate required env
# ---------------------------------------------------------------------------
if [ -z "${Z_HARNESS_PLAN_DIR:-}" ]; then
  echo "[write-handoff] Z_HARNESS_PLAN_DIR is not set" >&2
  exit 1
fi

PLAN_DIR="$Z_HARNESS_PLAN_DIR"
SLUG="${Z_HARNESS_SLUG:-}"
AGENT="${Z_HARNESS_AGENT:-pi}"
MODEL="${Z_HARNESS_MODEL:-unknown}"
CONTEXT_PCT="${Z_HARNESS_CONTEXT_PCT:-}"
HANDOFF_STATUS="${Z_HARNESS_HANDOFF_STATUS:-clean_break}"
HANDOFF_NEXT_STEP_OVERRIDE="${Z_HARNESS_HANDOFF_NEXT_STEP:-}"

case "$HANDOFF_STATUS" in
  context_pressure|clean_break|complete|blocked) ;;
  *)
    echo "[write-handoff] invalid Z_HARNESS_HANDOFF_STATUS: $HANDOFF_STATUS" >&2
    exit 1
    ;;
esac


HANDOFF_FILE="$PLAN_DIR/handoff.json"
TASKS_FILE="$PLAN_DIR/TASKS.md"
SESSION_FILE="$PLAN_DIR/SESSION.md"

# ---------------------------------------------------------------------------
# Derive timestamp
# ---------------------------------------------------------------------------
TIMESTAMP="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"

# ---------------------------------------------------------------------------
# Count tasks from TASKS.md
# ---------------------------------------------------------------------------
TASKS_COMPLETED=0
TASKS_TOTAL=0

if [ -f "$TASKS_FILE" ]; then
  TASKS_COMPLETED="$(grep -cE '^\s*[-*]?\s*\[x\]' "$TASKS_FILE" 2>/dev/null || echo 0)"
  TASKS_TOTAL="$(grep -cE '^\s*[-*]?\s*\[[x ]\]' "$TASKS_FILE" 2>/dev/null || echo 0)"
  case "$TASKS_COMPLETED" in ''|*[!0-9]*) TASKS_COMPLETED=0 ;; esac
  case "$TASKS_TOTAL" in ''|*[!0-9]*) TASKS_TOTAL=0 ;; esac
fi

# ---------------------------------------------------------------------------
# Extract SESSION.md metadata and sections
# ---------------------------------------------------------------------------
SESSION_SUMMARY=""
SESSION_KEYS=""
NEXT_ACTIONS=""
NEXT_PENDING=""
DONE_COUNT=""

if [ -f "$SESSION_FILE" ]; then
  # Extract YAML frontmatter fields
  DONE_COUNT="$(sed -n '/^---$/,/^---$/p' "$SESSION_FILE" | grep '^done_count:' | sed 's/^done_count:\s*//' | tr -d '[:space:]' || true)"
  NEXT_PENDING="$(sed -n '/^---$/,/^---$/p' "$SESSION_FILE" | grep '^next_pending:' | sed 's/^next_pending:\s*//' | tr -d '[:space:]' || true)"
  case "$DONE_COUNT" in ''|*[!0-9]*) DONE_COUNT="" ;; esac

  # Extract section bodies (text between ## SectionName and the next ## or end of file)
  _extract_section() {
    local section="$1"
    # Match from "## SectionName" to the next "## " or end of file (after frontmatter)
    awk -v sec="## $section" '
      BEGIN { in_sec=0; after_fm=0 }
      /^---$/ { fm_count++; next }
      fm_count >= 2 && !after_fm { after_fm=1 }
      after_fm && $0 == sec { in_sec=1; next }
      after_fm && in_sec && /^## / { exit }
      after_fm && in_sec && /./ { print }
    ' "$SESSION_FILE"
  }

  # Compose session summary: first ~300 chars of Decisions section, trimmed
  _DECISIONS="$(_extract_section "Decisions" | head -6)"
  SESSION_SUMMARY="$(printf '%s' "$_DECISIONS" | tr '\n' ' ' | sed 's/  */ /g' | head -c 300)"

  # Session keys: first 5 entries from Decisions or Landmines, one per line
  _ALL_KEYS="$(_extract_section "Decisions"; echo "---"; _extract_section "Landmines")"
  SESSION_KEYS="$(printf '%s' "$_ALL_KEYS" | grep -v '^---$' | grep -v '^$' | head -5 | sed 's/^[-*] //' | sed 's/^**//;s/**$//' || true)"

  # Next actions: Open threads section entries
  _OPEN="$(_extract_section "Open threads" | head -5)"
  NEXT_ACTIONS="$(printf '%s' "$_OPEN" | grep -v '^$' | sed 's/^[-*] //' || true)"
fi

# ---------------------------------------------------------------------------
# Compose next_step (continuation prompt for the next agent session)
# ---------------------------------------------------------------------------
if [ -n "$NEXT_PENDING" ] && [ "$NEXT_PENDING" != "none" ]; then
  NEXT_STEP="Resume /z-execute for ${SLUG:-this plan}. ${TASKS_COMPLETED}/${TASKS_TOTAL} tasks done. Start at ${NEXT_PENDING}. Read TASKS.md for acceptance criteria and SESSION.md for context."
else
  NEXT_STEP="Resume /z-execute for ${SLUG:-this plan}. ${TASKS_COMPLETED}/${TASKS_TOTAL} tasks done. Read TASKS.md for current state and SESSION.md for context from the prior session."
fi

if [ -n "$HANDOFF_NEXT_STEP_OVERRIDE" ]; then
  NEXT_STEP="$HANDOFF_NEXT_STEP_OVERRIDE"
fi

# Truncate next_step to schema max (2000 chars)
if [ "${#NEXT_STEP}" -gt 2000 ]; then
  NEXT_STEP="$(printf '%s' "$NEXT_STEP" | head -c 1997)..."
fi

# ---------------------------------------------------------------------------
# Build context_files array
# ---------------------------------------------------------------------------
# List files that exist in the plan dir. Ordered by priority.
CTX_FILES="["
_sep=""

_add_ctx() {
  local fpath="$1"
  local role="$2"
  if [ -f "$fpath" ]; then
    # JSON-escape the path
    _escaped="$(printf '%s' "$fpath" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read().strip()))' 2>/dev/null || printf '"%s"' "$fpath")"
    CTX_FILES="${CTX_FILES}${_sep}{\"path\":${_escaped},\"role\":\"${role}\"}"
    _sep=","
  fi
}

_add_ctx "$PLAN_DIR/SPEC.md" "spec"
_add_ctx "$PLAN_DIR/PLAN.md" "plan"
_add_ctx "$TASKS_FILE" "tasks"
_add_ctx "$SESSION_FILE" "session_log"

CTX_FILES="${CTX_FILES}]"

# ---------------------------------------------------------------------------
# Build JSON
# ---------------------------------------------------------------------------
# Slug: JSON null if empty
if [ -z "$SLUG" ]; then
  SLUG_JSON="null"
else
  SLUG_JSON="\"$SLUG\""
fi

# ---------------------------------------------------------------------------
# Attend-resume predicate (optional; protocol 1.1)
# ---------------------------------------------------------------------------
# When invoked from a /z-attend chain yield (Z_HARNESS_ATTEND_RESUME=1), emit
# protocol_version "1.1" and a nested attend_resume object built from the
# yield-time env vars. Otherwise emit protocol_version "1.0" with no
# attend_resume key for non-attend callers (manual handoff or clear checkpoint).
PROTOCOL_VERSION="1.0"
ATTEND_RESUME_JSON="null"

if [ "${Z_HARNESS_ATTEND_RESUME:-}" = "1" ]; then
  PROTOCOL_VERSION="1.1"

  # Every attend_resume sub-field is minLength:1 in the schema. An unset env var
  # would emit an empty string -> schema-invalid 1.1 handoff. Fail loudly here,
  # naming the missing var(s), rather than writing an invalid predicate.
  MISSING_ATTEND_VARS=""
  for _v in Z_HARNESS_ATTEND_HEAD_SHA Z_HARNESS_ATTEND_PHASE \
            Z_HARNESS_ATTEND_DONE_SET_HASH Z_HARNESS_ATTEND_DIRTY_FP \
            Z_HARNESS_ATTEND_SESSION_ID; do
    eval "_val=\${$_v:-}"
    if [ -z "$_val" ]; then
      MISSING_ATTEND_VARS="$MISSING_ATTEND_VARS $_v"
    fi
  done
  if [ -n "$MISSING_ATTEND_VARS" ]; then
    echo "ERROR: Z_HARNESS_ATTEND_RESUME=1 but required attend var(s) unset/empty:$MISSING_ATTEND_VARS" >&2
    exit 1
  fi

  ATTEND_RESUME_JSON="$(python3 -c '
import json, sys
print(json.dumps({
  "expected_head_sha": sys.argv[1],
  "expected_phase": sys.argv[2],
  "done_set_hash": sys.argv[3],
  "dirty_state_fingerprint": sys.argv[4],
  "session_id": sys.argv[5],
}))
' "${Z_HARNESS_ATTEND_HEAD_SHA:-}" "${Z_HARNESS_ATTEND_PHASE:-}" \
  "${Z_HARNESS_ATTEND_DONE_SET_HASH:-}" "${Z_HARNESS_ATTEND_DIRTY_FP:-}" \
  "${Z_HARNESS_ATTEND_SESSION_ID:-}")"
fi

# Write via Python for proper JSON encoding of all fields
HANDOFF_JSON="$(python3 -c '
import json, sys

data = {
  "protocol_version": sys.argv[1],
  "timestamp": sys.argv[2],
  "agent": sys.argv[3],
  "slug": json.loads(sys.argv[4]),
  "status": sys.argv[8],
  "next_step": sys.argv[5],
  "context_files": json.loads(sys.argv[6])
}

attend_resume = json.loads(sys.argv[7])
if attend_resume is not None:
  data["attend_resume"] = attend_resume

print(json.dumps(data, indent=2))
' "$PROTOCOL_VERSION" "$TIMESTAMP" "$AGENT" "$SLUG_JSON" "$NEXT_STEP" "$CTX_FILES" "$ATTEND_RESUME_JSON" "$HANDOFF_STATUS")"

# ---------------------------------------------------------------------------
# Atomic write
# ---------------------------------------------------------------------------
HANDOFF_TMP="$PLAN_DIR/handoff.json.tmp.$$"
printf '%s\n' "$HANDOFF_JSON" > "$HANDOFF_TMP"
mv "$HANDOFF_TMP" "$HANDOFF_FILE"

BYTES="$(wc -c < "$HANDOFF_FILE" | tr -d '[:space:]')"
echo "STATUS: written bytes=$BYTES"
exit 0
