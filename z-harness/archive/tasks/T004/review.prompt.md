You are reviewing code that Claude just wrote for task T004: Author scripts/run-memory-review.sh per SPEC.md — bash helper that runs skip-condition checks, captures cumulative diff, prints STATUS line + paths for orchestrator to dispatch the review-agent.

Spec (excerpt):
From scripts/run-memory-review.sh section of SPEC.md:

Bash helper called by both `/z-implement-all` and `/z-review-all`. Encapsulates the review-agent lifecycle so the two command files stay DRY.

Signature: `bash scripts/run-memory-review.sh <RUN> <parent_command>`

Where `<parent_command>` is `implement-all` or `review-all`.

Behavior (in order):
1. Resolve `$BASE = $Z_HARNESS_PLAN_DIR` and `$RUN_DIR = $BASE/archive/$RUN`.
2. **Skip-conditions check** (D7 refined):
   - Compute `git merge-base HEAD origin/main` (fallback `HEAD~5`); store base ref.
   - Diff `<base>..HEAD`; if empty → emit `phase_end` with `name: memory_review`, `skipped: true`, `skip_reason: empty_diff`, exit 0.
   - Parse `$BASE/TASKS.md`; count `[x]`. If zero AND parent_command is `implement-all` → skip with `skip_reason: all_tasks_skipped`, exit 0.
   - NOTE: do NOT skip on halt — halted runs are high-signal.
3. Write cumulative diff to `$RUN_DIR/cumulative.diff` (truncate to 5000 lines for context budget).
4. Verify `docs/llm/TAGS.txt` exists (if missing, emit `review_agent_failed` event with reason `tags_missing` and exit 0 — soft-skip).
5. (Caller — the orchestrator — handles the actual `Agent()` dispatch and JSON parse; this script's job is the deterministic plumbing.) Print to stdout, on separate lines: `STATUS: ready`, then `<RUN_DIR>/cumulative.diff`, then `<BASE>/SPEC.md`, then `docs/llm/TAGS.txt` (absolute paths).
6. Exit 0. The skip paths print `STATUS: skipped <reason>` on the first line and exit 0 (skipping is success, not failure).

Output contract: exit 0 always (skip is success); print `STATUS: <ready|skipped>` as first stdout line; if `ready`, also print absolute paths to the three artifacts the agent needs.

Acceptance criteria:
- Prints `STATUS: ready` followed by three absolute paths when conditions are met.
- Prints `STATUS: skipped empty_diff` and exits 0 when no diff.
- Prints `STATUS: skipped all_tasks_skipped` and exits 0 when TASKS.md has zero `[x]` and parent_command is implement-all.
- Prints `STATUS: skipped tags_missing` when docs/llm/TAGS.txt absent.
- chmod +x set.
- exit 0 always (skip is success, not failure).

Diff (primary artifact):

diff --git a/Users/zeke/dev/z-harness/scripts/run-memory-review.sh b/Users/zeke/dev/z-harness/scripts/run-memory-review.sh
new file mode 100755
index 0000000..3fa1f96
--- /dev/null
+++ b/Users/zeke/dev/z-harness/scripts/run-memory-review.sh
@@ -0,0 +1,89 @@
+#!/usr/bin/env bash
+# Helper called by /z-implement-all and /z-review-all.
+# Encapsulates the review-agent lifecycle skip-conditions and artifact prep.
+#
+# Usage: bash scripts/run-memory-review.sh <RUN> <parent_command>
+#   parent_command: implement-all | review-all
+#
+# Exit 0 always (skip is success).
+# Stdout line 1 is always: STATUS: ready | STATUS: skipped <reason>
+# If ready, lines 2-4 are absolute paths to: cumulative.diff, SPEC.md, TAGS.txt
+
+set -euo pipefail
+
+if [[ $# -lt 2 ]]; then
+  echo "usage: run-memory-review.sh <RUN> <parent_command>" >&2
+  exit 2
+fi
+
+RUN="$1"
+PARENT_COMMAND="$2"
+
+REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
+PLUGIN_ROOT="${ANTIGRAVITY_PLUGIN_ROOT:-${CLAUDE_PLUGIN_ROOT:-$REPO_ROOT}}"
+LOG_EVENT="$PLUGIN_ROOT/scripts/log-event.sh"
+
+# Resolve plan base dir
+BASE="${Z_HARNESS_PLAN_DIR:-}"
+if [[ -z "$BASE" ]]; then
+  echo "run-memory-review.sh: Z_HARNESS_PLAN_DIR is not set" >&2
+  exit 2
+fi
+
+RUN_DIR="$BASE/archive/$RUN"
+mkdir -p "$RUN_DIR"
+
+# --- Skip-condition 1: empty diff ---
+BASE_REF="$(git merge-base HEAD origin/main 2>/dev/null || echo "HEAD~5")"
+DIFF_OUTPUT="$(git diff "${BASE_REF}..HEAD" 2>/dev/null || true)"
+
+if [[ -z "$DIFF_OUTPUT" ]]; then
+  echo "STATUS: skipped empty_diff"
+  if [[ -x "$LOG_EVENT" ]]; then
+    bash "$LOG_EVENT" "$RUN" "phase_end" \
+      '{"name":"memory_review","skipped":true,"skip_reason":"empty_diff"}' || true
+  fi
+  exit 0
+fi
+
+# --- Skip-condition 2: zero completed tasks and parent is implement-all ---
+TASKS_FILE="$BASE/TASKS.md"
+if [[ -f "$TASKS_FILE" && "$PARENT_COMMAND" == "implement-all" ]]; then
+  COMPLETED_COUNT="$(grep -c '\[x\]' "$TASKS_FILE" 2>/dev/null || true)"
+  COMPLETED_COUNT="${COMPLETED_COUNT:-0}"
+  COMPLETED_COUNT="$(printf '%s' "$COMPLETED_COUNT" | tr -d '[:space:]')"
+  if [[ "${COMPLETED_COUNT:-0}" -eq 0 ]]; then
+    echo "STATUS: skipped all_tasks_skipped"
+    if [[ -x "$LOG_EVENT" ]]; then
+      bash "$LOG_EVENT" "$RUN" "phase_end" \
+        '{"name":"memory_review","skipped":true,"skip_reason":"all_tasks_skipped"}' || true
+    fi
+    exit 0
+  fi
+fi
+
+# --- Verify TAGS.txt exists ---
+TAGS_FILE="$REPO_ROOT/docs/llm/TAGS.txt"
+if [[ ! -f "$TAGS_FILE" ]]; then
+  echo "STATUS: skipped tags_missing"
+  if [[ -x "$LOG_EVENT" ]]; then
+    bash "$LOG_EVENT" "$RUN" "review_agent_failed" \
+      '{"reason":"tags_missing"}' || true
+  fi
+  exit 0
+fi
+
+# --- Write cumulative diff (truncated to 5000 lines) ---
+DIFF_FILE="$RUN_DIR/cumulative.diff"
+# Use set +e around head to avoid SIGPIPE exit 141 when diff is shorter than 5000 lines.
+set +o pipefail
+printf '%s\n' "$DIFF_OUTPUT" | head -n 5000 > "$DIFF_FILE"
+set -o pipefail
+
+# --- Print ready + artifact paths ---
+echo "STATUS: ready"
+echo "$DIFF_FILE"
+echo "$BASE/SPEC.md"
+echo "$TAGS_FILE"
+
+exit 0

Scrutinize this code rigorously. Claude is prone to: over-engineering, premature abstraction, plausible-looking-but-wrong logic, missed edge cases, and silently expanding scope beyond the spec.

Report:
1. Bugs or correctness issues
2. Spec violations or missed acceptance criteria
3. Missed edge cases / error handling gaps
4. DRY / KISS / SOLID violations
5. Security concerns
6. Anything else worth flagging

For each finding: severity (blocker / major / minor / nit), location, and a suggested fix.
