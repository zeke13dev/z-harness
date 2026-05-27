You are reviewing code that Claude just wrote for task T001: Extend run-memory-review.sh to accept parent_command: debug.

Spec (excerpt from z-harness/postmortem-memory-nudge/SPEC.md, section "scripts/run-memory-review.sh"):

**Existing surface (preserved):**
- Args: `<RUN> <parent_command>`
- Stdout line 1: `STATUS: ready | STATUS: skipped <reason>`
- Stdout lines 2-4 (when ready): absolute paths to cumulative.diff, SPEC.md, TAGS.txt
- Exit 0 always

**Additions:**

1. Accept `parent_command: debug` as a third valid value (alongside
   `implement-all`, `review-all`). For `debug`, skip the
   `all_tasks_skipped` check (no TASKS.md `[x]` semantics apply), and
   additionally require `$BASE/DEBUG.md` to exist and contain
   `status: shipped` in its frontmatter. If absent, emit
   `STATUS: skipped debug_not_shipped` and the corresponding terminal event.

2. Emit a `memory_review_terminal` event at every exit path (replacing the
   inconsistent `phase_end`/`review_agent_failed` emissions). Payload:
   ```json
   {
     "state": "not_applicable|skipped_broken_context|ran_empty|needs_user",
     "skip_reason": "<one of the STATUS suffixes>|null",
     "parent_command": "implement-all|review-all|debug",
     "candidates": 0,
     "accepted": 0,
     "slug": "<$Z_HARNESS_SLUG or null>"
   }
   ```
   The script emits the event with `candidates: 0` and `accepted: 0` for
   the skip states it owns.

3. STATUS → terminal-state mapping (script-owned):
   | STATUS | state | skip_reason |
   |---|---|---|
   | `skipped empty_diff` | `not_applicable` | `empty_diff` |
   | `skipped all_tasks_skipped` | `not_applicable` | `all_tasks_skipped` |
   | `skipped debug_not_shipped` | `not_applicable` | `debug_not_shipped` |
   | `skipped tags_missing` | `skipped_broken_context` | `tags_missing` |
   | `skipped no_plan_dir` | `skipped_broken_context` | `no_plan_dir` |
   | `skipped missing_args` | `skipped_broken_context` | `missing_args` |
   | `ready` | (orchestrator emits later) | null |

4. For `parent_command: debug` and `STATUS: ready`, additionally emit a
   **fifth** stdout line: the absolute path to DEBUG.md. Lines 1-4 remain
   the existing contract (STATUS / cumulative.diff / SPEC.md / TAGS.txt).
   Line 5 is debug-only.

5. **spec_path conditional emission.** If `$BASE/SPEC.md` does not exist
   (fresh `/z-debug` runs may have no SPEC), emit an empty line for line 3
   rather than the path.

6. Stop emitting `review_agent_failed` from this script for `tags_missing`.
   That event kind is reserved for actual agent-dispatch failures owned by
   the orchestrator.

7. **Gate change for `parent_command: debug`** The helper itself only checks that
   `$BASE/DEBUG.md` **exists and is readable** (`[[ -r "$DEBUG_MD" ]]`); if
   not, emit `STATUS: skipped debug_md_missing` (terminal state:
   `not_applicable`). The "shipped vs abandoned" gate moves to the caller.

**Invariants:**
- Always exit 0 (skip is success).
- One `memory_review_terminal` event per invocation (the script's exit), no more, no less.
- Never write outside `$BASE/archive/$RUN/`.
- Never mutate INDEX.json or memory files.

Acceptance criteria:
- parent_command: debug recognized 3rd value alongside implement-all and review-all
- For debug: skip all_tasks_skipped check; instead check [[ -r "$BASE/DEBUG.md" ]] and emit `STATUS: skipped debug_md_missing` if not
- Existing implement-all and review-all behavior unchanged

Diff (primary artifact — focus your scrutiny on what changed):

diff --git a/scripts/run-memory-review.sh b/scripts/run-memory-review.sh
index 753525b..3880185 100755
--- a/scripts/run-memory-review.sh
+++ b/scripts/run-memory-review.sh
@@ -1,9 +1,9 @@
 #!/usr/bin/env bash
-# Helper called by /z-implement-all and /z-review-all.
+# Helper called by /z-implement-all, /z-review-all, and /z-debug.
 # Encapsulates the review-agent lifecycle skip-conditions and artifact prep.
 #
 # Usage: bash scripts/run-memory-sh <RUN> <parent_command>
-#   parent_command: implement-all | review-all
+#   parent_command: implement-all | review-all | debug
 #
 # Exit 0 always (skip is success).
 # Stdout line 1 is always: STATUS: ready | STATUS: skipped <reason>
@@ -84,6 +84,15 @@ if [[ -f "$TASKS_FILE" && "$PARENT_COMMAND" == "implement-all" ]]; then
   fi
 fi
 
+# --- Skip-condition 3: debug parent requires DEBUG.md to exist and be readable ---
+if [[ "$PARENT_COMMAND" == "debug" ]]; then
+  DEBUG_MD="$BASE/DEBUG.md"
+  if [[ ! -r "$DEBUG_MD" ]]; then
+    echo "STATUS: skipped debug_md_missing"
+    exit 0
+  fi
+fi
+
 # --- Verify TAGS.txt exists ---
 TAGS_FILE="$REPO_ROOT/docs/llm/TAGS.txt"
 if [[ ! -f "$TAGS_FILE" ]]; then

Surrounding file context (the full file with the diff applied):

#!/usr/bin/env bash
# Helper called by /z-implement-all, /z-review-all, and /z-debug.
# Encapsulates the review-agent lifecycle skip-conditions and artifact prep.
#
# Usage: bash scripts/run-memory-review.sh <RUN> <parent_command>
#   parent_command: implement-all | review-all | debug
#
# Exit 0 always (skip is success).
# Stdout line 1 is always: STATUS: ready | STATUS: skipped <reason>
# If ready, lines 2-4 are absolute paths to: cumulative.diff, SPEC.md, TAGS.txt

set -euo pipefail

if [[ $# -lt 2 ]]; then
  echo "STATUS: skipped missing_args"
  exit 0
fi

RUN="$1"
PARENT_COMMAND="$2"

REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
PLUGIN_ROOT="${ANTIGRAVITY_PLUGIN_ROOT:-${CLAUDE_PLUGIN_ROOT:-$REPO_ROOT}}"
LOG_EVENT="$PLUGIN_ROOT/scripts/log-event.sh"

# Resolve plan base dir — must be absolute
BASE="${Z_HARNESS_PLAN_DIR:-}"
if [[ -z "$BASE" ]]; then
  echo "STATUS: skipped no_plan_dir"
  exit 0
fi

# Normalize BASE to an absolute path
if [[ -d "$BASE" ]]; then
  BASE="$(cd "$BASE" && pwd)"
else
  # Directory doesn't exist yet; prefix with REPO_ROOT if relative
  case "$BASE" in
    /*) ;;  # already absolute
    *) BASE="$REPO_ROOT/$BASE" ;;
  esac
fi

RUN_DIR="$BASE/archive/$RUN"
mkdir -p "$RUN_DIR"

# --- Skip-condition 1: empty diff ---
# Resolve a valid base ref: prefer origin/main merge-base, then HEAD~5, then empty-tree.
EMPTY_TREE="4b825dc642cb6eb9a060e54bf8d69288fbee4904"
BASE_REF=""

MERGE_BASE="$(git merge-base HEAD origin/main 2>/dev/null || true)"
if [[ -n "$MERGE_BASE" ]] && git rev-parse --verify "${MERGE_BASE}^{commit}" >/dev/null 2>&1; then
  BASE_REF="$MERGE_BASE"
elif git rev-parse --verify "HEAD~5^{commit}" >/dev/null 2>&1; then
  BASE_REF="HEAD~5"
else
  BASE_REF="$EMPTY_TREE"
fi

# Test emptiness without loading the diff into memory, then stream to file.
if git diff --quiet "${BASE_REF}..HEAD" 2>/dev/null; then
  echo "STATUS: skipped empty_diff"
  if [[ -x "$LOG_EVENT" ]]; then
    bash "$LOG_EVENT" "$RUN" "phase_end" \
      '{"name":"memory_review","skipped":true,"skip_reason":"empty_diff"}' || true
  fi
  exit 0
fi

# --- Skip-condition 2: zero completed tasks and parent is implement-all ---
TASKS_FILE="$BASE/TASKS.md"
if [[ -f "$TASKS_FILE" && "$PARENT_COMMAND" == "implement-all" ]]; then
  COMPLETED_COUNT="$(grep -c '\[x\]' "$TASKS_FILE" 2>/dev/null || true)"
  COMPLETED_COUNT="${COMPLETED_COUNT:-0}"
  COMPLETED_COUNT="$(printf '%s' "$COMPLETED_COUNT" | tr -d '[:space:]')"
  if [[ "${COMPLETED_COUNT:-0}" -eq 0 ]]; then
    echo "STATUS: skipped all_tasks_skipped"
    if [[ -x "$LOG_EVENT" ]]; then
      bash "$LOG_EVENT" "$RUN" "phase_end" \
        '{"name":"memory_review","skipped":true,"skip_reason":"all_tasks_skipped"}' || true
    fi
    exit 0
  fi
fi

# --- Skip-condition 3: debug parent requires DEBUG.md to exist and be readable ---
if [[ "$PARENT_COMMAND" == "debug" ]]; then
  DEBUG_MD="$BASE/DEBUG.md"
  if [[ ! -r "$DEBUG_MD" ]]; then
    echo "STATUS: skipped debug_md_missing"
    exit 0
  fi
fi

# --- Verify TAGS.txt exists ---
TAGS_FILE="$REPO_ROOT/docs/llm/TAGS.txt"
if [[ ! -f "$TAGS_FILE" ]]; then
  echo "STATUS: skipped tags_missing"
  if [[ -x "$LOG_EVENT" ]]; then
    bash "$LOG_EVENT" "$RUN" "review_agent_failed" \
      '{"reason":"tags_missing"}' || true
  fi
  exit 0
fi

# --- Write cumulative diff (truncated to 5000 lines, streamed to avoid loading into memory) ---
DIFF_FILE="$RUN_DIR/cumulative.diff"
# Disable pipefail to tolerate SIGPIPE when diff output is shorter than 5000 lines.
set +o pipefail
git diff "${BASE_REF}..HEAD" | head -n 5000 > "$DIFF_FILE"
set -o pipefail

# --- Print ready + artifact paths (all absolute) ---
echo "STATUS: ready"
echo "$DIFF_FILE"
echo "$BASE/SPEC.md"
echo "$TAGS_FILE"

exit 0

Scrutinize this code rigorously. Claude is prone to: over-engineering, premature abstraction, plausible-looking-but-wrong logic, missed edge cases, and silently expanding scope beyond the spec.

Report:
1. Bugs or correctness issues
2. Spec violations or missed acceptance criteria
3. Missed edge cases / error handling gaps
4. DRY / KISS / SOLID violations
5. Security concerns
6. Anything else worth flagging

For each finding: severity (blocker / major / minor / nit), location, and a suggested fix.

**OUTPUT BUDGET — respect strictly:**
- Total response under **8000 characters**.
- Report **blockers and majors only**. Skip minors and nits unless a "minor" hides a correctness bug — in which case promote it to major.
- One finding per bullet. Two sentences max per finding (one for the problem, one for the fix).
- No re-stating of code already in the diff. No summaries of what the code does. No restating the spec.
- If there are no blockers or majors, respond with exactly: `No blockers or majors found.` (plus an optional 1-line note if something needs the implementer's attention but is below the bar).
