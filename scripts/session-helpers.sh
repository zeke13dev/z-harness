#!/usr/bin/env bash
# session-helpers.sh — Pure query helpers for SESSION.md handoff
#
# Usage (callable):
#   bash scripts/session-helpers.sh <fn> <args...>
#
# Usage (sourceable):
#   source scripts/session-helpers.sh
#   done_set_hash "$TASKS_FILE"
#
# All functions:
#   - stdout only, no side effects
#   - exit 0 always (empty output signals "not found")
#   - [x] detection reuses the orchestrator's exact pattern: ^\s*[-*]?\s*\[x\]
#
# Functions:
#   done_set_hash <tasks_file>
#     Prints the sha256 of the sorted, newline-joined list of [x] task-ids.
#     Empty done-set hashes the canonical empty string "".
#     Order-independent: same [x] set in any line order → identical hash.
#
#   last_done_task <tasks_file>
#     Prints the id of the last [x] task (human hint only; not load-bearing).
#
#   next_pending_task <tasks_file>
#     Prints the first [ ] task id whose deps are all [x] (empty if none).
#
#   last_curated_marker <events_file>
#     Prints the ts of the most recent context_curated event ("none" if absent).
#
#   session_frontmatter_field <session_file> <field>
#     Prints the scalar value of a YAML frontmatter field (empty if missing).

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

# _sh_sha256 <string>
# Compute sha256 of a string (portable: sha256sum or shasum -a 256).
_sh_sha256() {
  local input="$1"
  local hex
  hex="$(printf '%s' "$input" | sha256sum 2>/dev/null | cut -c1-64)" \
    || hex="$(printf '%s' "$input" | shasum -a 256 2>/dev/null | cut -c1-64)"
  printf '%s' "$hex"
}

# ---------------------------------------------------------------------------
# done_set_hash <tasks_file>
# ---------------------------------------------------------------------------
# Prints the sha256 of the sorted, newline-joined list of [x] task-ids.
# Task-id extraction: the heading id from a line matching
#   ## <ID> — <title> with a preceding or same line matching ^\s*[-*]?\s*\[x\]
#
# The [x] detection regex MUST match the orchestrator's pattern: ^\s*[-*]?\s*\[x\]
# Task-ids are extracted from the ## heading on (or adjacent to) the [x] line.
#
# TASKS.md format observed in this repo:
#   ## T001 — session-helpers.sh ... `[x]`
# or (alternate):
#   - [x] ## T001
#
# We extract the first whitespace-delimited word after "## " that starts on any
# "## <ID>" heading line, but only emit it when a [x] marker is present on
# that same heading line OR the heading immediately follows a [x] list-item line.
done_set_hash() {
  local tasks_file="$1"
  if [[ ! -f "$tasks_file" ]]; then
    _sh_sha256 ""
    return 0
  fi

  # Collect all [x] task-ids, sort them, join with newlines, then sha256.
  # Two patterns in TASKS.md:
  #   Pattern A: ## T001 — ... `[x]`  (the [x] is on the heading line itself)
  #   Pattern B: - [x] T001 — ...     (the [x] is a list checkbox on the heading)
  #
  # We emit the task-id for any line that:
  #   - matches the [x] orchestrator regex  AND
  #   - contains a bare task-id token (word starting with a capital letter followed
  #     by digits, e.g. T001, T042, REV-001)
  # OR for any "## <ID>" heading whose inline backtick status is `[x]`.

  local ids
  ids="$(python3 - "$tasks_file" <<'PYEOF'
import sys, re

tasks_file = sys.argv[1]
# [x] detection pattern — reuses orchestrator pattern
DONE_RE = re.compile(r'^\s*[-*]?\s*\[x\]', re.IGNORECASE)
# Heading pattern: ## <ID> — ...  where ID is the task id token
HEADING_RE = re.compile(r'^##\s+(\S+)')
# Inline backtick status on a heading line: `[x]` or `[ ]` or `[~]`
INLINE_STATUS_RE = re.compile(r'`\[([x ~])\]`', re.IGNORECASE)

ids = []
with open(tasks_file, 'r', encoding='utf-8', errors='replace') as fh:
    prev_done = False
    for line in fh:
        line_stripped = line.rstrip('\n')

        heading_m = HEADING_RE.match(line_stripped)
        if heading_m:
            task_id = heading_m.group(1)
            # Check for inline `[x]` status on the heading line itself
            status_m = INLINE_STATUS_RE.search(line_stripped)
            if status_m and status_m.group(1).lower() == 'x':
                ids.append(task_id)
            elif prev_done:
                # Previous line was a bare [x] list item pointing to this heading
                ids.append(task_id)
            prev_done = False
            continue

        # Non-heading line: check if it's a [x] checkbox
        if DONE_RE.match(line_stripped):
            # It might carry a task-id inline (e.g. "- [x] T001 — ...")
            # Strip the [x] prefix and look for a task-id
            rest = re.sub(r'^\s*[-*]?\s*\[x\]\s*', '', line_stripped, flags=re.IGNORECASE)
            id_m = re.match(r'(\S+)', rest)
            if id_m:
                ids.append(id_m.group(1))
            else:
                # bare [x] line — next heading is the task
                prev_done = True
        else:
            prev_done = False

for tid in sorted(set(ids)):
    print(tid)
PYEOF
)"

  if [[ -z "$ids" ]]; then
    _sh_sha256 ""
  else
    _sh_sha256 "$ids"
  fi
  return 0
}

# ---------------------------------------------------------------------------
# last_done_task <tasks_file>
# ---------------------------------------------------------------------------
# Prints the id of the LAST [x] heading in the file (human hint, not load-bearing).
last_done_task() {
  local tasks_file="$1"
  if [[ ! -f "$tasks_file" ]]; then
    return 0
  fi

  python3 - "$tasks_file" <<'PYEOF'
import sys, re

tasks_file = sys.argv[1]
DONE_RE = re.compile(r'^\s*[-*]?\s*\[x\]', re.IGNORECASE)
HEADING_RE = re.compile(r'^##\s+(\S+)')
INLINE_STATUS_RE = re.compile(r'`\[([x ~])\]`', re.IGNORECASE)

last_id = None
prev_done = False
with open(tasks_file, 'r', encoding='utf-8', errors='replace') as fh:
    for line in fh:
        line_stripped = line.rstrip('\n')
        heading_m = HEADING_RE.match(line_stripped)
        if heading_m:
            task_id = heading_m.group(1)
            status_m = INLINE_STATUS_RE.search(line_stripped)
            if status_m and status_m.group(1).lower() == 'x':
                last_id = task_id
            elif prev_done:
                last_id = task_id
            prev_done = False
            continue

        if DONE_RE.match(line_stripped):
            rest = re.sub(r'^\s*[-*]?\s*\[x\]\s*', '', line_stripped, flags=re.IGNORECASE)
            id_m = re.match(r'(\S+)', rest)
            if id_m:
                last_id = id_m.group(1)
            else:
                prev_done = True
        else:
            prev_done = False

if last_id:
    print(last_id)
PYEOF
  return 0
}

# ---------------------------------------------------------------------------
# next_pending_task <tasks_file>
# ---------------------------------------------------------------------------
# Prints the first [ ] task id whose deps are all [x] (empty if none).
# "Depends on: —" or "Depends on:" means no deps (always eligible).
next_pending_task() {
  local tasks_file="$1"
  if [[ ! -f "$tasks_file" ]]; then
    return 0
  fi

  python3 - "$tasks_file" <<'PYEOF'
import sys, re

tasks_file = sys.argv[1]

DONE_RE = re.compile(r'^\s*[-*]?\s*\[x\]', re.IGNORECASE)
PENDING_RE = re.compile(r'^\s*[-*]?\s*\[ \]', re.IGNORECASE)
HEADING_RE = re.compile(r'^##\s+(\S+)')
INLINE_STATUS_RE = re.compile(r'`\[([x~ ])\]`', re.IGNORECASE)
DEPS_RE = re.compile(r'^\s*\*\*Depends\s+on:\*\*\s*(.*)', re.IGNORECASE)

# First pass: collect all [x] task-ids as the done set
done_ids = set()
prev_done = False
with open(tasks_file, 'r', encoding='utf-8', errors='replace') as fh:
    for line in fh:
        line_stripped = line.rstrip('\n')
        heading_m = HEADING_RE.match(line_stripped)
        if heading_m:
            task_id = heading_m.group(1)
            status_m = INLINE_STATUS_RE.search(line_stripped)
            if status_m and status_m.group(1).lower() == 'x':
                done_ids.add(task_id)
            elif prev_done:
                done_ids.add(task_id)
            prev_done = False
            continue

        if DONE_RE.match(line_stripped):
            rest = re.sub(r'^\s*[-*]?\s*\[x\]\s*', '', line_stripped, flags=re.IGNORECASE)
            id_m = re.match(r'(\S+)', rest)
            if id_m:
                done_ids.add(id_m.group(1))
            else:
                prev_done = True
        else:
            prev_done = False

# Second pass: find pending tasks with deps satisfied
# Track current task context: id, status (pending/done/other), deps list
tasks = []  # list of (id, is_pending, deps_ids)
current_id = None
current_pending = False
current_deps = None
prev_done = False

with open(tasks_file, 'r', encoding='utf-8', errors='replace') as fh:
    for line in fh:
        line_stripped = line.rstrip('\n')
        heading_m = HEADING_RE.match(line_stripped)
        if heading_m:
            # Save previous task
            if current_id is not None:
                tasks.append((current_id, current_pending, current_deps))
            task_id = heading_m.group(1)
            status_m = INLINE_STATUS_RE.search(line_stripped)
            is_done = (status_m and status_m.group(1).lower() == 'x') or prev_done
            is_pending = (status_m and status_m.group(1) == ' ') if status_m else False
            current_id = task_id
            current_pending = is_pending
            current_deps = None
            prev_done = False
            continue

        if current_id is not None:
            deps_m = DEPS_RE.match(line_stripped)
            if deps_m:
                raw_deps = deps_m.group(1).strip()
                if raw_deps in ('—', '-', '', 'none', 'None'):
                    current_deps = []
                else:
                    # Parse comma-separated dep ids, stripping whitespace and backticks
                    current_deps = [
                        d.strip().strip('`')
                        for d in raw_deps.split(',')
                        if d.strip().strip('`')
                    ]

        if DONE_RE.match(line_stripped):
            rest = re.sub(r'^\s*[-*]?\s*\[x\]\s*', '', line_stripped, flags=re.IGNORECASE)
            id_m = re.match(r'(\S+)', rest)
            if not id_m:
                prev_done = True
        elif PENDING_RE.match(line_stripped):
            rest = re.sub(r'^\s*[-*]?\s*\[ \]\s*', '', line_stripped, flags=re.IGNORECASE)
            id_m = re.match(r'(\S+)', rest)
            if id_m:
                if current_id is None:
                    current_id = id_m.group(1)
                    current_pending = True
                    current_deps = None
            prev_done = False
        else:
            prev_done = False

    # Save last task
    if current_id is not None:
        tasks.append((current_id, current_pending, current_deps))

# Find the first pending task with all deps satisfied
for task_id, is_pending, deps in tasks:
    if not is_pending:
        continue
    if deps is None:
        # No deps field found — assume no deps
        deps = []
    if all(d in done_ids for d in deps):
        print(task_id)
        break
PYEOF
  return 0
}

# ---------------------------------------------------------------------------
# last_curated_marker <events_file>
# ---------------------------------------------------------------------------
# Prints the ts of the most recent context_curated event in events_file.
# Prints "none" if no such event exists or the file is missing.
last_curated_marker() {
  local events_file="$1"
  if [[ ! -f "$events_file" ]]; then
    printf 'none'
    return 0
  fi

  local ts
  ts="$(python3 - "$events_file" <<'PYEOF'
import sys, json

events_file = sys.argv[1]
last_ts = None
try:
    with open(events_file, 'r', encoding='utf-8', errors='replace') as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                if obj.get('kind') == 'context_curated':
                    ts = obj.get('ts') or obj.get('last_gate') or obj.get('t')
                    if ts:
                        last_ts = ts
            except (json.JSONDecodeError, AttributeError):
                pass
except OSError:
    pass
if last_ts:
    print(last_ts)
PYEOF
)"

  if [[ -z "$ts" ]]; then
    printf 'none'
  else
    printf '%s' "$ts"
  fi
  return 0
}

# ---------------------------------------------------------------------------
# session_frontmatter_field <session_file> <field>
# ---------------------------------------------------------------------------
# Prints the scalar value of a YAML frontmatter field from SESSION.md.
# Returns empty string if the file is missing, has no frontmatter, or the
# field is absent.
session_frontmatter_field() {
  local session_file="$1"
  local field="$2"
  if [[ ! -f "$session_file" ]]; then
    return 0
  fi

  python3 - "$session_file" "$field" <<'PYEOF'
import sys, re

session_file = sys.argv[1]
field = sys.argv[2]

try:
    with open(session_file, 'r', encoding='utf-8', errors='replace') as fh:
        content = fh.read()
except OSError:
    sys.exit(0)

# Extract YAML frontmatter between leading --- delimiters
fm_match = re.match(r'^---\r?\n(.*?)\r?\n---', content, re.DOTALL)
if not fm_match:
    sys.exit(0)

fm_body = fm_match.group(1)

# Simple scalar extraction: look for "field: value" lines
# Handles quoted and unquoted scalar values; does not parse complex YAML.
pattern = re.compile(
    r'^' + re.escape(field) + r'\s*:\s*(.+)',
    re.MULTILINE
)
m = pattern.search(fm_body)
if m:
    val = m.group(1).strip()
    # Strip surrounding quotes if present
    if (val.startswith('"') and val.endswith('"')) or \
       (val.startswith("'") and val.endswith("'")):
        val = val[1:-1]
    print(val)
PYEOF
  return 0
}

# ---------------------------------------------------------------------------
# validate_intent <intent_file> [lint]
# ---------------------------------------------------------------------------
# Thin wrapper around scripts/intent-schema.py.
#
# Usage:
#   validate_intent <INTENT.md>          — validate frontmatter + required sections
#   validate_intent <INTENT.md> lint     — also lint acceptance checklist items
#
# Exit codes mirror intent-schema.py: 0 = valid, 1 = errors found, 2 = usage error.
validate_intent() {
  local intent_file="$1"
  local mode="${2:-}"
  local _repo_root
  _repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
  local schema_py="$_repo_root/scripts/intent-schema.py"

  if [[ ! -f "$schema_py" ]]; then
    printf 'ERROR: intent-schema.py not found at %s\n' "$schema_py" >&2
    return 2
  fi

  # Always validate frontmatter + sections
  python3 "$schema_py" validate-intent "$intent_file"
  local rc=$?
  if [[ $rc -ne 0 ]]; then
    return $rc
  fi

  # Optionally lint criteria
  if [[ "$mode" == "lint" ]]; then
    python3 "$schema_py" lint-criteria "$intent_file"
    return $?
  fi

  return 0
}

# ---------------------------------------------------------------------------
# CLI wrapper — callable as: bash scripts/session-helpers.sh <fn> <args...>
# ---------------------------------------------------------------------------
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  if [[ $# -lt 1 ]]; then
    printf 'Usage: %s {done_set_hash|last_done_task|next_pending_task|last_curated_marker|session_frontmatter_field|validate_intent} [args...]\n' "$0" >&2
    exit 1
  fi
  cmd="$1"
  shift
  case "$cmd" in
    done_set_hash|last_done_task|next_pending_task|last_curated_marker|session_frontmatter_field|validate_intent)
      "$cmd" "$@"
      ;;
    *)
      printf 'Unknown function: %s\n' "$cmd" >&2
      printf 'Usage: %s {done_set_hash|last_done_task|next_pending_task|last_curated_marker|session_frontmatter_field|validate_intent} [args...]\n' "$0" >&2
      exit 1
      ;;
  esac
fi
