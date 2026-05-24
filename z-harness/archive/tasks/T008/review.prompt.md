You are reviewing code that Claude just wrote for task T008: Refresh z-debug entry in docs/llm/commands.json (summary + last_updated).

Spec (excerpt from SPEC.md):

## File: `docs/llm/commands.json` (UPDATE)

Add a new concept entry for `z-fix` and revise the `z-debug` entry to reflect the new heavy pipeline.

`z-debug` entry: update `last_updated`, refresh `summary` to mention the hypothesis tournament + 3-LLM 2-round generation + ordinal Bayesian scoring + unified DEBUG.md artifact. Update `depends_on` to include the new consultant modes (still under `agents`).

Acceptance criteria:
- z-debug entry last_updated set to 2026-05-24
- summary mentions hypothesis tournament, 3-LLM 2-round generation, ordinal Bayesian scoring, unified DEBUG.md
- JSON validates
- Only the z-debug entry touched

Diff (primary artifact):

```diff
diff --git a/docs/llm/commands.json b/docs/llm/commands.json
index d72fa38..cdb6352 100644
--- a/docs/llm/commands.json
+++ b/docs/llm/commands.json
@@ -1,12 +1,14 @@
 {
   "concept": "commands",
-  "last_updated": "2026-05-23",
+  "last_updated": "2026-05-24",
    "covers_spec": "none",
   "source_file": [
     "commands/z-amend.md",
     "commands/z-audit.md",
     "commands/z-brainstorm.md",
     "commands/z-debug.md",
+    "commands/z-mr-review.md",
+    "commands/z-style-init.md",
     "commands/z-do.md",
     "commands/z-implement-all.md",
     "commands/z-implement-next.md",
@@ -21,10 +23,25 @@
      "commands/z-skill-fix.md",
      "commands/z-stats.md",
      "commands/z-suggest-memory.md",
+    "commands/z-fix.md",
      "commands/z-test.md"
    ],
    "confidence": "high",
    "entry_points": [
+    {
+      "file": "commands/z-mr-review.md",
+      "line": 1,
+      "symbol": "z-mr-review",
+      "kind": "module",
+      "summary": "Orchestrates multi-LLM code-quality review of a branch diff; writes P0-P4 findings to MR-REVIEW.md."
+    },
+    {
+      "file": "commands/z-style-init.md",
+      "line": 1,
+      "symbol": "z-style-init",
+      "kind": "module",
+      "summary": "Authors or amends the project STYLE.md via Capture-first grounding and interactive interview."
+    },
     {
       "file": "commands/z-amend.md",
       "line": 1,
@@ -51,7 +68,8 @@
        "line": 1,
        "symbol": "z-debug",
        "kind": "module",
-      "summary": "Coordinates regression investigation, hypothesis isolation, and fix loops."
+      "summary": "Heavy hypothesis-tournament debugging pipeline: 3-LLM 2-round adversarial hypothesis generation, ordinal Bayesian scoring, consensus-first ranking with forced outlier carve-out, 3-5 isolation rounds, fix-gate requires highest posterior and full evidence coverage. Single unified DEBUG.md artifact.",
+      "last_updated": "2026-05-24"
      },
      {
        "file": "commands/z-do.md",
@@ -151,6 +169,13 @@
        "kind": "module",
        "summary": "Appends key lessons and edge case memories to concept documentation JSON."
      },
+    {
+      "file": "commands/z-fix.md",
+      "line": 1,
+      "symbol": "z-fix",
+      "kind": "module",
+      "summary": "Lightweight bug-fix command for the case where the user already has a diagnosis; single light-fix consult, inline implementation, non-negotiable Codex review, optional post-mortem."
+    },
      {
        "file": "commands/z-test.md",
        "line": 1,
@@ -161,7 +186,8 @@
    ],
    "depends_on": [
      "agents",
-    "scripts"
+    "scripts",
+    "z-plan-light"
    ],
    "consumed_by": [
      "skills"
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

OUTPUT BUDGET — respect strictly:
- Total response under 8000 characters.
- Report **blockers and majors only**. Skip minors and nits unless a "minor" hides a correctness bug.
- One finding per bullet. Two sentences max per finding.
