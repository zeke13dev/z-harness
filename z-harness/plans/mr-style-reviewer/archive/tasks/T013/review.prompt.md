You are reviewing code that Claude just wrote for task T013: Verify 2 blockers + 4 majors addressed in commands/z-debug.md.

Spec excerpt (from SPEC.md):
Integration: `/z-debug` post-mortem hand-off

The spec mandates:
1. After writing POSTMORTEM.md, add an AskUserQuestion: "Run MR-style quality review on the fix diff?"
2. If yes, invoke `/z-mr-review` (NOT a direct agent dispatch), passing `--slug` and `--base`
3. `/z-mr-review` must fail-fast on missing STYLE.md; do NOT handle it in `/z-debug`
4. Parse MR-REVIEW.md for P0/P1 findings using defensive Python (treat malformed/missing as "no findings")
5. Append P0/P1 findings to POSTMORTEM.md's "Action items (preventative)" section

Prior findings (v1):
- B1: directly dispatched mr-reviewer agent; expected MR-REVIEW.md to exist. Fix: delegate to /z-mr-review SlashCommand.
- B2: style_path null fallback. Fix: let /z-mr-review fail-fast.
- M3: relative slug_dir path. Fix: absolute via git rev-parse.
- M4: frontmatter parser robustness. Fix: defensive Python with specific exceptions.
- M5: no agent failure handling. Fix: best-effort, append note, continue.
- M6: unreliable base SHA. Fix: capture PRE_FIX_SHA before fix edits.

Acceptance criteria (v1):
1. Delegate to /z-mr-review SlashCommand (not direct agent dispatch)
2. Robust frontmatter parser with specific exception handling (yaml.YAMLError, ValueError, KeyError)
3. PRE_FIX_SHA captured at Phase 6 step 6 before any edits, passed as --base
4. Absolute path via git rev-parse --show-toplevel
5. Best-effort invocation: on /z-mr-review failure, append note to POSTMORTEM.md and continue
6. Parse only findings_index from frontmatter; no prose fallback

Diff (primary artifact):
--- /Users/zeke/dev/z-harness/z-harness/mr-style-reviewer/archive/tasks/T013/diff-v1.patch	2026-05-23 17:02:23
+++ /Users/zeke/dev/z-harness/z-harness/mr-style-reviewer/archive/tasks/T013/diff.patch	2026-05-23 17:04:57
@@ -1,60 +1,76 @@
 diff --git a/commands/z-debug.md b/commands/z-debug.md
-index 469e119..aa08c8c 100644
+index 469e119..33a3a09 100644
 --- a/commands/z-debug.md
 +++ b/commands/z-debug.md
-@@ -254,6 +254,55 @@ Pick at least one. Be honest:
+@@ -205,8 +205,9 @@ You now have a confirmed root cause. The remainder of `/z-debug` is structurally
+    ## Approved shortcuts
+    ## Docs touched
+    ```
+-6. **Inline implementation** (same as `/z-plan-light` Phase 7).
+-7. **Codex review** (same as `/z-plan-light` Phase 8 — non-negotiable).
++6. **Capture pre-fix SHA** (before touching any files): `PRE_FIX_SHA=$(git rev-parse HEAD)`. This is passed to `/z-mr-review` later as `--base`. If the fix involves multiple commits, this records the state before any Phase 6 changes.
++7. **Inline implementation** (same as `/z-plan-light` Phase 7).
++8. **Codex review** (same as `/z-plan-light` Phase 8 — non-negotiable).
  
  Auto-bail still active: if the fix turns out to touch >5 files or introduce architectural change, halt and recommend `/z-plan`.
  
 @@ -254,6 +255,59 @@ Pick at least one. Be honest:
  - **Similar bugs likely elsewhere?** <list any places worth auditing; or "none — this is localized">
  ```
  
 +After writing POSTMORTEM.md, ask the user via `AskUserQuestion` (before the action-item conversion prompts):
 +
 +**"Run MR-style quality review on the fix diff?"**
-+- "Run MR-style review (Recommended)" — invoke the `mr-reviewer` agent on the fix diff; P0/P1 findings will be appended to the post-mortem's preventative action items automatically.
++- "Run MR-style review (Recommended)" — invoke `/z-mr-review` on the fix diff; P0/P1 findings will be appended to the post-mortem's preventative action items automatically.
 +- "Skip" — leave the post-mortem as-is and proceed to the action-item conversion prompts.
 +
 +If user accepts:
-+1. Derive the MR review run id: `MR_RUN=$(date -u +%Y%m%dT%H%M%SZ)-mr-review`.
-+2. `mkdir -p z-harness/$Z_HARNESS_SLUG/archive/$MR_RUN`.
-+3. Compute the pre-fix commit SHA (the commit immediately before the fix was applied): `BASE_SHA=$(git rev-parse HEAD~1)` (or the parent of the fix commit if more than one commit was made during Phase 6 — use the commit that existed before any Phase 6 changes).
-+4. Write the fix diff to `z-harness/$Z_HARNESS_SLUG/archive/$MR_RUN/diff.patch`:
++1. Invoke `/z-mr-review` as a best-effort step (on any failure, append a note to POSTMORTEM.md and continue — do NOT halt the post-mortem):
 +   ```bash
-+   git diff ${BASE_SHA}..HEAD > z-harness/$Z_HARNESS_SLUG/archive/$MR_RUN/diff.patch
++   /z-mr-review --slug $Z_HARNESS_SLUG --base $PRE_FIX_SHA --force-on-trunk
 +   ```
-+5. Write an empty dismissed signatures file (no prior archive to draw from in a fresh debug run):
++   - `PRE_FIX_SHA` was captured at Phase 6 step 6 (before any fix edits). Pass it as `--base` so the diff covers exactly the fix changes.
++   - `--force-on-trunk` allows the review to run on whatever branch `/z-debug` is operating from.
++   - `/z-mr-review` already gates on `STYLE.md` existence and will refuse with "Run /z-style-init first." if it's missing. Do NOT try to handle this here — let it fail-fast. On failure, log "MR review skipped: STYLE.md missing" (or "MR review skipped: /z-mr-review failed — <reason>") and continue.
++   - MR-REVIEW.md is written by `/z-mr-review` to the canonical path: `$(git rev-parse --show-toplevel)/z-harness/$Z_HARNESS_SLUG/MR-REVIEW.md`.
++
++2. If `/z-mr-review` succeeds, parse `$(git rev-parse --show-toplevel)/z-harness/$Z_HARNESS_SLUG/MR-REVIEW.md` for P0/P1 findings using a defensive Python inline block (treat malformed/missing as "no findings" — never fall back to prose parsing):
 +   ```bash
-+   echo '{"signatures": [], "n_runs_scanned": 0}' > z-harness/$Z_HARNESS_SLUG/archive/$MR_RUN/dismissed_signatures.json
++   python3 - <<'PYEOF'
++   import sys, yaml
++   mr_path = "<abs_path_to_MR-REVIEW.md>"
++   try:
++       with open(mr_path) as f:
++           raw = f.read()
++       # Extract frontmatter between first --- delimiters
++       parts = raw.split("---")
++       if len(parts) < 3:
++           raise ValueError("No valid frontmatter found")
++       fm = yaml.safe_load(parts[1])
++       if not isinstance(fm, dict):
++           raise ValueError("Frontmatter is not a mapping")
++       findings = fm.get("findings_index")
++       if not isinstance(findings, list):
++           print("NOTE: findings_index missing or not a list — treating as no findings")
++           sys.exit(0)
++       for entry in findings:
++           if not isinstance(entry, dict):
++               continue
++           sev = entry.get("severity", "")
++           if sev in ("P0", "P1"):
++               fid = entry.get("id", "T-MR-???")
++               title = entry.get("title", entry.get("file", "<no title>"))
++               print(f"- [ ] [{fid}] {title} (from MR-REVIEW.md quality review)")
++   except FileNotFoundError:
++       print("NOTE: MR-REVIEW.md not found — MR review produced no output")
++   except (yaml.YAMLError, ValueError, KeyError) as e:
++       print(f"NOTE: MR-REVIEW.md parse error ({e}) — treating as no findings")
++   PYEOF
 +   ```
-+6. Invoke the `mr-reviewer` agent:
-+   ```
-+   Agent(
-+     subagent_type="mr-reviewer",
-+     model="sonnet",
-+     description="MR quality review for debug fix: <slug>",
-+     prompt="slug: <Z_HARNESS_SLUG>
-+   base: <BASE_SHA>
-+   base_sha: <BASE_SHA>
-+   diff_path: <abs path to archive/$MR_RUN/diff.patch>
-+   style_path: <abs path to STYLE.md if it exists in repo root, else omit>
-+   run_id: <MR_RUN>
-+   slug_dir: z-harness/<Z_HARNESS_SLUG>
-+   dismissed_signatures_path: <abs path to archive/$MR_RUN/dismissed_signatures.json>
-+   voices_available: [claude, codex, gemini]
-+   mode: full
-+   chunk_meta: null
-+   deep: false"
-+   )
-+   ```
-+   Note: if `STYLE.md` does not exist in the repo root, pass `style_path: null` in the prompt and the agent will skip style-drift checks.
-+7. After the agent returns, parse the FRONTMATTER of `z-harness/$Z_HARNESS_SLUG/archive/$MR_RUN/MR-REVIEW.md` — specifically the `findings_index` YAML list (NOT the prose body). Filter entries where `severity` is `P0` or `P1`. For each such entry, extract its `id` (e.g. `T-MR-001`) and `title` fields.
-+8. Append those filtered findings to POSTMORTEM.md's "Action items (preventative)" section, one line per finding:
-+   ```
-+   - [ ] [T-MR-NNN] <finding title> (from MR-REVIEW.md quality review)
-+   ```
-+   If there are no P0/P1 findings, append a single note:
-+   ```
-+   - MR quality review found no P0/P1 findings.
-+   ```
++   Collect the printed lines. If no `- [ ]` lines were printed (no P0/P1 findings or parse fallback), use a single note: `- MR quality review found no P0/P1 findings.`
 +
++3. Append the collected finding lines (or the "no findings" note) to POSTMORTEM.md's "Action items (preventative)" section.
++
  After writing, ask the user via `AskUserQuestion`:

Scrutinize this code rigorously against the 6 prior findings and spec. Verify:
1. `/z-mr-review` is invoked, NOT direct agent dispatch (B1, BLOCKER)
2. Delegated to /z-mr-review means shell command, not AskUserQuestion with agent arg (B1)
3. STYLE.md missing handling left to /z-mr-review fail-fast (B2, BLOCKER)
4. PRE_FIX_SHA captured at Phase 6 step 6 BEFORE edits, passed as --base (M6, MAJOR)
5. Absolute paths via git rev-parse --show-toplevel (M3, MAJOR)
6. Robust Python parser with yaml.YAMLError, ValueError, KeyError exceptions (M4, MAJOR)
7. Best-effort invocation: on failure, append note and continue (M5, MAJOR)
8. No prose fallback; findings_index only (M4)

Report:
1. Blockers or correctness issues
2. Spec violations or missed acceptance criteria
3. Missed edge cases / error handling gaps
4. DRY / KISS / SOLID violations
5. Security concerns
6. Anything else worth flagging

For each finding: severity (blocker / major / minor / nit), location, and a suggested fix.

OUTPUT BUDGET — respect strictly:
- Total response under **8000 characters**.
- Report **blockers and majors only**. Skip minors and nits unless a "minor" hides a correctness bug — in which case promote it to major.
- One finding per bullet. Two sentences max per finding.
- No re-stating of code already in the diff.
