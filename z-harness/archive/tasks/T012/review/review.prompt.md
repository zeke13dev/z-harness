You are reviewing code that Claude just wrote for task T012: Update commands/z-improve.md + skills/z-improve/SKILL.md POSTMORTEM/PROBLEM/POST-MORTEM references to DEBUG.md section form.

Spec (excerpt):
The task requires updating two files identically to reference the new unified DEBUG.md artifact structure from the z-fix-hypothesis-driven feature. The spec defines at line 45:

- debug: `z-harness/<slug>/DEBUG.md ## Problem` and `DEBUG.md ## Post-mortem` if present

(Note: This is from the SPEC.md Phase 1 section which documents all the read locations for the /z-improve command.)

Acceptance criteria:
- Both files updated identically
- References point to DEBUG.md ## Post-mortem / DEBUG.md ## Problem
- No other broken refs introduced

Diff (primary artifact — focus your scrutiny on what changed):

```diff
diff --git a/commands/z-improve.md b/commands/z-improve.md
index 6942e66..531b135 100644
--- a/commands/z-improve.md
+++ b/commands/z-improve.md
@@ -42,7 +42,7 @@ Read (all from main thread — these are tight):
  - light plan: `z-harness/<slug>/FIX.md`
  - z-do: `$RUN_DIR/approach.md` + `$RUN_DIR/premise.md`
  - audit: `z-harness/<slug>/REPORT.md`
- - debug: `z-harness/<slug>/POST-MORTEM.md` if present, else `PROBLEM.md`
+ - debug: `z-harness/<slug>/DEBUG.md ## Problem` and `DEBUG.md ## Post-mortem` if present
  - Codex review transcripts (under `$RUN_DIR/transcripts/`) if present — read at most 2, the most recent.
  
  Save a one-paragraph "run summary" to scratch (don't write it to disk yet).
diff --git a/skills/z-improve/SKILL.md b/skills/z-improve/SKILL.md
index 6167791..66e26eb 100644
--- a/skills/z-improve/SKILL.md
+++ b/skills/z-improve/SKILL.md
@@ -42,7 +42,7 @@ Read (all from main thread — these are tight):
  - light plan: `z-harness/<slug>/FIX.md`
  - z-do: `$RUN_DIR/approach.md` + `$RUN_DIR/premise.md`
  - audit: `z-harness/<slug>/REPORT.md`
- - debug: `z-harness/<slug>/POST-MORTEM.md` if present, else `PROBLEM.md`
+ - debug: `z-harness/<slug>/DEBUG.md ## Problem` and `DEBUG.md ## Post-mortem` if present
  - Codex review transcripts (under `$RUN_DIR/transcripts/`) if present — read at most 2, the most recent.
  
  Save a one-paragraph "run summary" to scratch (don't write it to disk yet).
```

Surrounding file context:

=== commands/z-improve.md (lines 40-50) ===
- The run's primary artifact, if present:
  - full plan: `z-harness/<slug>/{SPEC,PLAN,TASKS}.md`
  - light plan: `z-harness/<slug>/FIX.md`
  - z-do: `$RUN_DIR/approach.md` + `$RUN_DIR/premise.md`
  - audit: `z-harness/<slug>/REPORT.md`
  - debug: `z-harness/<slug>/DEBUG.md ## Problem` and `DEBUG.md ## Post-mortem` if present
- Codex review transcripts (under `$RUN_DIR/transcripts/`) if present — read at most 2, the most recent.

=== skills/z-improve/SKILL.md (lines 40-50) ===
(identical)

Scrutinize this code rigorously. Claude is prone to: over-engineering, premature abstraction, plausible-looking-but-wrong logic, missed edge cases, and silently expanding scope beyond the spec.

Report:
1. Bugs or correctness issues
2. Spec violations or missed acceptance criteria
3. Missed edge cases / error handling gaps
4. DRY / KISS / SOLID violations
5. Security concerns
6. Anything else worth flagging

For each finding: severity (blocker / major / minor / nit), location, and a suggested fix.

OUTPUT BUDGET — respect strictly:
- Total response under 8000 characters.
- Report blockers and majors only. Skip minors and nits unless a "minor" hides a correctness bug — in which case promote it to major.
- One finding per bullet. Two sentences max per finding (one for the problem, one for the fix).
- No re-stating of code already in the diff. No summaries of what the code does. No restating the spec.
