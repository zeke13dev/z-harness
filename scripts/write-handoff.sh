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
#   Z_HARNESS_HANDOFF_SESSION_CONTEXT — optional mid-session agent brief; when set,
#       written to $Z_HARNESS_PLAN_DIR/SESSION_CONTEXT.md and included as session_log
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
HANDOFF_SESSION_CONTEXT="${Z_HARNESS_HANDOFF_SESSION_CONTEXT:-}"

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
HUMAN_HANDOFF_FILE="$PLAN_DIR/HANDOFF.md"
SESSION_CONTEXT_FILE="$PLAN_DIR/SESSION_CONTEXT.md"

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
  TASK_COUNTS="$(awk '
    BEGIN {
      staged_completed = staged_total = 0
      legacy_completed = legacy_total = 0
    }
    /^[[:space:]]*##[[:space:]]+T[0-9][0-9][0-9][[:space:]]/ && /`\[[xX ]\]`/ {
      staged_total++
      if ($0 ~ /`\[[xX]\]`/) staged_completed++
      next
    }
    /^[[:space:]]*[-*]?[[:space:]]*\[[xX ]\]/ {
      legacy_total++
      if ($0 ~ /^[[:space:]]*[-*]?[[:space:]]*\[[xX]\]/) legacy_completed++
    }
    END {
      if (staged_total > 0) {
        print staged_completed, staged_total
      } else {
        print legacy_completed, legacy_total
      }
    }
  ' "$TASKS_FILE")"
  set -- $TASK_COUNTS
  TASKS_COMPLETED="${1:-0}"
  TASKS_TOTAL="${2:-0}"
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
# Optional live session context
# ---------------------------------------------------------------------------
# SESSION.md is curated from durable plan telemetry; it cannot know the live
# agent's conversational state. /z-handoff may pass a compact brief through
# Z_HARNESS_HANDOFF_SESSION_CONTEXT so the next agent can recover the exact
# mid-session work, decisions, questions, and landmines that are otherwise only
# in the current context window.
SESSION_CONTEXT_WRITTEN=0
if [ -n "$HANDOFF_SESSION_CONTEXT" ]; then
  SESSION_CONTEXT_TMP="$SESSION_CONTEXT_FILE.tmp.$$"
  python3 -c '
import sys
from datetime import datetime, timezone

path, slug, status, note = sys.argv[1:5]
ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
with open(path, "w", encoding="utf-8") as f:
    f.write("---\n")
    f.write("artifact: session_context\n")
    f.write(f"slug: {slug or 'null'}\n")
    f.write(f"status: {status}\n")
    f.write(f"generated_at: {ts}\n")
    f.write("generated_by: write-handoff.sh\n")
    f.write("---\n\n")
    # note is the section content below "# Session context"
    f.write(note.rstrip() + "\n")
' "$SESSION_CONTEXT_TMP" "$SLUG" "$HANDOFF_STATUS" "$HANDOFF_SESSION_CONTEXT"
  mv "$SESSION_CONTEXT_TMP" "$SESSION_CONTEXT_FILE"
  SESSION_CONTEXT_WRITTEN=1
fi

# ---------------------------------------------------------------------------
# Compose next_step (continuation prompt for the next agent session)
# ---------------------------------------------------------------------------
if [ -n "$NEXT_PENDING" ] && [ "$NEXT_PENDING" != "none" ]; then
  NEXT_STEP="Resume /z-execute for ${SLUG:-this plan}. ${TASKS_COMPLETED}/${TASKS_TOTAL} tasks done. Start at ${NEXT_PENDING}. Read TASKS.md for acceptance criteria, SESSION_CONTEXT.md for live mid-session state if present, and SESSION.md for curated plan context."
else
  NEXT_STEP="Resume /z-execute for ${SLUG:-this plan}. ${TASKS_COMPLETED}/${TASKS_TOTAL} tasks done. Read TASKS.md for current state, SESSION_CONTEXT.md for live mid-session state if present, and SESSION.md for curated plan context."
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

# Priority order: live session context first, then plan artifacts by importance.
# Only include SESSION_CONTEXT.md if freshly written (not stale from a prior handoff).
[ "$SESSION_CONTEXT_WRITTEN" = 1 ] && _add_ctx "$SESSION_CONTEXT_FILE" "session_log"
_add_ctx "$HUMAN_HANDOFF_FILE" "handoff"
_add_ctx "$HUMAN_HANDOFF_FILE" "invariants"
_add_ctx "$HUMAN_HANDOFF_FILE" "rejected_approaches"
_add_ctx "$HUMAN_HANDOFF_FILE" "decisions_archive"
_add_ctx "$HUMAN_HANDOFF_FILE" "verification_commands"
_add_ctx "$PLAN_DIR/INTENT.md" "intent"
_add_ctx "$PLAN_DIR/SPEC.md" "spec"
_add_ctx "$PLAN_DIR/PLAN.md" "plan"
_add_ctx "$TASKS_FILE" "tasks"
_add_ctx "$PLAN_DIR/FIX.md" "plan"
_add_ctx "$PLAN_DIR/workstreams.json" "workstreams"
_add_ctx "$PLAN_DIR/LEDGER.md" "ledger"
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
