You are reviewing code that Claude just wrote for task T002: Add 5th stdout line (DEBUG.md path) for debug parent + conditional spec_path.

Spec (excerpt from SPEC.md):

### `scripts/run-memory-review.sh`

**Existing surface (preserved):**
- Args: `<RUN> <parent_command>`
- Stdout line 1: `STATUS: ready | STATUS: skipped <reason>`
- Stdout lines 2-4 (when ready): absolute paths to cumulative.diff, SPEC.md, TAGS.txt
- Exit 0 always

**Additions:**

1. Accept `parent_command: debug` as a third valid value. For `debug`, skip the `all_tasks_skipped` check, and additionally require `$BASE/DEBUG.md` to exist and be readable. If absent, emit `STATUS: skipped debug_md_missing`.

2. Line 5 (debug parent only): For `parent_command: debug` and `STATUS: ready`, additionally emit a **fifth** stdout line: the absolute path to DEBUG.md. Lines 1-4 remain the existing contract (STATUS / cumulative.diff / SPEC.md / TAGS.txt). Line 5 is debug-only.

3. **spec_path conditional emission:** If `$BASE/SPEC.md` does not exist (fresh `/z-debug` runs may have no SPEC), emit an empty line for line 3 rather than the path.

4. **Gate change:** The orchestrator caller (Phase 10 of `/z-debug`) is responsible for invoking this helper only on the `status: shipped` finalize branch. The helper itself only checks that `$BASE/DEBUG.md` **exists and is readable** (`[[ -r "$DEBUG_MD" ]]`); if not, emit `STATUS: skipped debug_md_missing`.

**Invariants:**
- Always exit 0 (skip is success).
- Never write outside `$BASE/archive/$RUN/`.
- Never mutate INDEX.json or memory files.

Acceptance criteria:
- For parent_command: debug and STATUS: ready, line 5 is absolute path to DEBUG.md
- For all parents, line 3 emits empty line if $BASE/SPEC.md does not exist
- Lines 1-4 remain backward-compatible for implement-all/review-all

Diff (primary artifact — focus your scrutiny on what changed):

```diff
diff --git a/scripts/run-memory-review.sh b/scripts/run-memory-review.sh
index 753525b..f5594fb 100755
--- a/scripts/run-memory-review.sh
+++ b/scripts/run-memory-review.sh
@@ -1,13 +1,14 @@
 #!/usr/bin/env bash
-# Helper called by /z-implement-all and /z-review-all.
+# Helper called by /z-implement-all, /z-review-all, and /z-debug.
 # Encapsulates the review-agent lifecycle skip-conditions and artifact prep.
 #
 # Usage: bash scripts/run-memory-review.sh <RUN> <parent_command>
-#   parent_command: implement-all | review-all
+#   parent_command: implement-all | review-all | debug
 #
 # Exit 0 always (skip is success).
 # Stdout line 1 is always: STATUS: ready | STATUS: skipped <reason>
-# If ready, lines 2-4 are absolute paths to: cumulative.diff, SPEC.md, TAGS.txt
+# If ready, lines 2-4 are absolute paths to: cumulative.diff, SPEC.md (or empty if missing), TAGS.txt
+# Line 5 (debug parent only): absolute path to DEBUG.md
 
 set -euo pipefail
 
@@ -84,6 +85,15 @@ if [[ -f "$TASKS_FILE" && "$PARENT_COMMAND" == "implement-all" ]]; then
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
@@ -105,7 +115,14 @@ set -o pipefail
 # --- Print ready + artifact paths (all absolute) ---
 echo "STATUS: ready"
 echo "$DIFF_FILE"
-echo "$BASE/SPEC.md"
+if [[ -f "$BASE/SPEC.md" ]]; then
+  echo "$BASE/SPEC.md"
+else
+  echo ""
+fi
 echo "$TAGS_FILE"
+if [[ "$PARENT_COMMAND" == "debug" ]]; then
+  echo "$BASE/DEBUG.md"
+fi
 
 exit 0
```

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
