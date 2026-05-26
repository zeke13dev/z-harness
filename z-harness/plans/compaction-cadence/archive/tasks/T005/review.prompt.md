You are reviewing code that Claude just wrote for task T005: Implement /z-review-all pre-Phase-4 breakpoint + slug-scoped state file (.review_state.json) with HEAD-aware fast-forward

Spec (excerpt from SPEC.md):

**On every `/z-review-all` invocation, BEFORE entering Phase 0:**
1. If `.review_state.json` exists in the slug dir, read it.
2. If `head_sha` matches `git rev-parse HEAD` AND the referenced `cumulative_diff_path` file still exists, **fast-forward**: skip Phase 0–3.5, reuse the existing diff and test results, enter Phase 4 directly. Log a `review_resume_fast_forward` event.
3. If HEAD has changed OR the diff path is missing, **delete the stale state file** and start a fresh run from Phase 0 (the marker is invalidated; the user must reconfirm at the new Phase 3.7).
4. If `.review_state.json` does not exist, run Phase 0–3.7 normally.

**Phase 3.7 — Pre-consult compaction breakpoint:**
- Emit `compaction_pause` event with payload `{trigger: "pre_consult", phase: "review_all_phase_4"}`.
- Use `AskUserQuestion` with two options:
  - **(a) Pause for /clear** — exit cleanly so the user can `/clear` and re-invoke. Do **NOT** write any state file. On the next invocation, Phase 3.7 will fire again (correct — user wanted to re-evaluate).
  - **(b) Proceed now** — continue into Phase 4. **Only on this choice** write the state file.

**State file schema:**
```json
{
  "phase_3_7_acknowledged": true,
  "base_ref": "<git ref captured in Phase 2>",
  "head_sha": "<git rev-parse HEAD at time of acknowledgement>",
  "cumulative_diff_path": "<absolute path to the diff in the current archive/<run>/>",
  "acknowledged_at": "<iso timestamp>"
}
```

Acceptance Criteria:
- New "Phase 3.7 — pre-consult compaction breakpoint" between Phase 3.5 and Phase 4.
- AskUserQuestion with two options: "Pause for /clear" (exit, no state file written) and "Proceed now" (write .review_state.json, continue).
- State file path: z-harness/plans/<slug>/.review_state.json with schema (phase_3_7_acknowledged, base_ref, head_sha, cumulative_diff_path, acknowledged_at).
- Resume logic at top of every invocation:
  1. State file + HEAD matches + diff file present → fast-forward to Phase 4, emit review_resume_fast_forward.
  2. State file but HEAD changed or diff missing → delete file, full re-run.
  3. No state file → normal Phase 0 entry.
- State file deleted in the finalize phase on successful run completion.
- Emits compaction_pause {trigger: "pre_consult", phase: "review_all_phase_4"}.

Diff (primary artifact — focus scrutiny on what changed):

diff --git a/commands/z-review-all.md b/commands/z-review-all.md
index c7c102d..af53622 100644
--- a/commands/z-review-all.md
+++ b/commands/z-review-all.md
@@ -5,6 +5,35 @@ argument-hint: [--slug <slug>] [--base <git-ref>]
 
 You are running the **z-harness `/z-review-all`** final-gate review. This is a holistic cross-task cross-LLM review, intentionally distinct from the per-task review that `/z-implement-all` already performs. Per-task review catches per-task issues; this catches issues that only show up when looking at all tasks together.
 
+## Pre-Phase 0 — Resume check
+
+**Before entering Phase 0**, check for an existing state file from a prior invocation that reached Phase 3.7:
+
+```bash
+# Resolve slug from --slug arg or by enumerating z-harness/plans/*/TASKS.md
+# STATE_FILE="$Z_HARNESS_PLAN_DIR/.review_state.json"   (set after slug is known)
+# Perform a lightweight slug resolution here only to find the state file path.
+# If --slug was passed: EARLY_SLUG="<arg>"; EARLY_PLAN_DIR="$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/plan-path.sh" resolve_plan_path "$EARLY_SLUG")"
+# Otherwise: scan for a single TASKS.md candidate (same logic as Phase 0 step 1).
+```
+
+Once `EARLY_PLAN_DIR` is known:
+
+1. If `$EARLY_PLAN_DIR/.review_state.json` **does not exist** → proceed to Phase 0 normally.
+2. If it exists, read it and check:
+   - Run `git rev-parse HEAD` and compare with `head_sha` in the file.
+   - Check that the file at `cumulative_diff_path` still exists on disk.
+   - **If HEAD matches AND diff file is present:**
+     - Emit `review_resume_fast_forward` event:
+       ```bash
+       bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RRUN" review_resume_fast_forward \
+         '{"slug":"<slug>","head_sha":"<sha>","cumulative_diff_path":"<path>"}'
+       ```
+     - Skip Phases 0–3.5. Restore `BASE_REF` from the state file's `base_ref`. Restore `cumulative.diff` path from `cumulative_diff_path`. Jump directly to Phase 4.
+   - **If HEAD has changed OR the diff file is missing:**
+     - Delete the stale state file: `rm "$EARLY_PLAN_DIR/.review_state.json"`
+     - Proceed to Phase 0 for a full re-run.
 
 ## Phase 0 — Discover plan slug
 
@@ -96,6 +125,44 @@ done
 
 Skip this phase if either TESTS.md or test-runner.json is absent (no harm — older plans without /z-test predate this step).
 
+## Phase 3.7 — Pre-consult compaction breakpoint
+
+**Always runs** between Phase 3.5 and Phase 4 (unless fast-forwarded via the Pre-Phase 0 resume check).
+
+Emit the compaction pause event:
+```bash
+bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RRUN" compaction_pause \
+  '{"trigger":"pre_consult","phase":"review_all_phase_4"}'
+```
+
+Present an `AskUserQuestion` with exactly two options:
+
+> **Compaction breakpoint — pre-consultant spawn**
+>
+> You are about to dispatch the cross-LLM consultant subagents (Phase 4). These are context-heavy; starting them on a fresh context window improves quality.
+>
+> **Options:**
+> - **(a) Pause for /clear** — exit now so you can run `/clear`, then re-invoke `/z-review-all` to resume. No state file is written; Phase 3.7 will prompt again on the next invocation (correct — you wanted to re-evaluate).
+> - **(b) Proceed now** — continue into Phase 4 immediately. A state file will be written so a subsequent re-invocation (e.g. after an interruption) can fast-forward past Phases 0–3.5.
+
+**If the user picks (a) — Pause for /clear:**
+- Exit cleanly. Do **not** write `.review_state.json`.
+- The next `/z-review-all` invocation will run Phase 0–3.7 again.
+
+**If the user picks (b) — Proceed now:**
+- Write `$Z_HARNESS_PLAN_DIR/.review_state.json` with this schema:
+  ```json
+  {
+    "phase_3_7_acknowledged": true,
+    "base_ref": "<BASE_REF captured in Phase 2>",
+    "head_sha": "<output of git rev-parse HEAD at this moment>",
+    "cumulative_diff_path": "<absolute path to $BASE/archive/$RRUN/cumulative.diff>",
+    "acknowledged_at": "<ISO-8601 timestamp>"
+  }
+  ```
+  If the write fails, log a warning to stderr and proceed (do not block on a filesystem hiccup).
+- Continue to Phase 4.
+
 ## Phase 4 — Spawn final-review consultants (parallel)
 
 Spawn both in a single message via parallel `Agent()` calls. Each consultant gets the **same inputs**:

... (continuing with the rest of the diff covering Phase 5-6 and hard rules changes) ...

+**Finalize — delete state file on successful run completion:**
+```bash
+rm -f "$Z_HARNESS_PLAN_DIR/.review_state.json"
+```
+This ensures a subsequent `/z-review-all` starts a full fresh run rather than fast-forwarding into a stale Phase 4.

Scrutinize this code rigorously. Claude is prone to: over-engineering, premature abstraction, plausible-looking-but-wrong logic, missed edge cases, and silently expanding scope beyond the spec.

Report:
1. Bugs or correctness issues
2. Spec violations or missed acceptance criteria
3. Missed edge cases / error handling gaps
4. DRY / KISS / SOLID violations
5. Security concerns
6. Anything else worth flagging

For each finding: severity (blocker / major / minor / nit), location, and a suggested fix.
