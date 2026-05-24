2026-05-24T00:32:30.919603Z ERROR codex_core::session: failed to load skill /Users/zeke/.codex/skills/z-maintain-docs/SKILL.md: invalid YAML: did not find expected key at line 3 column 41, while parsing a block mapping
2026-05-24T00:32:30.920348Z ERROR codex_core::session: failed to load skill /Users/zeke/.codex/skills/z-stats/SKILL.md: invalid YAML: did not find expected key at line 3 column 32, while parsing a block mapping
2026-05-24T00:32:30.920355Z ERROR codex_core::session: failed to load skill /Users/zeke/.codex/skills/z-review-all/SKILL.md: invalid YAML: did not find expected key at line 3 column 32, while parsing a block mapping
OpenAI Codex v0.125.0 (research preview)
--------
workdir: /Users/zeke/dev/z-harness
model: gpt-5.5
provider: openai
approval: never
sandbox: workspace-write [workdir, /tmp, $TMPDIR, /Users/zeke/.codex/memories]
reasoning effort: medium
reasoning summaries: none
session id: 019e5765-d212-7221-a3fd-d9b0d4526e8b
--------
user
You are reviewing documentation that Claude just wrote for task T014: Documentation for mr-reviewer + style-init (human + LLM tiers, INDEX, scripts/agents/commands inventory, README).

Spec excerpt (from /Users/zeke/dev/z-harness/z-harness/mr-style-reviewer/SPEC.md, relevant sections):

The mr-reviewer feature provides code-quality review (not correctness review) for branch diffs. It targets five categories: abstraction, defensive-bloat, test-noise, hygiene, and style-drift. Findings are ranked P0-P4 and written to z-harness/<slug>/MR-REVIEW.md in TASKS.md-compatible shape. Users triage by deleting unwanted findings. Three LLM voices (Claude, Codex, Gemini) are fanned out in parallel; findings are deduplicated by (file, category, normalized_text) signature and tagged with which voices raised them. Voice consensus promotes findings one tier; minority voice demotes one tier; P0 is exempt from both adjustments.

The style-init feature creates and maintains the project STYLE.md that /z-mr-review requires. Bootstrap mode uses a 'Capture' approach: identifies top 5 most idiomatic existing source files, reads them, asks up to 4 interview questions, drafts STYLE.md, critiques it via codex+gemini consultants, then asks for user approval. Amend mode reads recent archive dismissal patterns via extract-dismissals.py, clusters similar dismissals, proposes new STYLE.md rules per cluster, and lets the user accept/edit/reject each proposed rule.

Acceptance criteria:
- docs/human/mr-reviewer.md, docs/human/style-init.md (new) — user-facing
- docs/llm/mr-reviewer.json, docs/llm/style-init.json (new) — token-compact concept docs
- docs/llm/INDEX.json edited with 2 new entries
- docs/llm/commands.json + agents.json + scripts.json updated
- README.md updated with new commands

Scope: docs review only — verify accuracy against the actual implementation files. Skim, don't deep-dive. Look for: (1) stale or inaccurate claims about behavior; (2) JSON parse-correctness of the four new/edited JSON files; (3) INDEX.json shape consistency with existing entries; (4) README.md doesn't break existing listing structure; (5) docs/human concepts cover the surface (P0-P4 rubric, 5 categories, falsifiability, --deep flag, --amend mode).

Diff (primary artifact — focus your scrutiny on what changed):

```diff
diff --git a/README.md b/README.md
index bc4a19e..6333f5d 100644
--- a/README.md
+++ b/README.md
@@ -33,10 +33,15 @@ Every command writes its artifacts under `z-harness/<slug>/`, with run-frozen ar
 - **`/z-implement-all`** — Orchestrates the full TASKS.md queue: one fresh `implementer` subagent per task → per-task `codex-reviewer` safety gate → retry once on review failure → push-notify at every task boundary. Walks a tree-rooted plan produced by `/z-plan-split` (one cluster at a time, in MANIFEST run order) as well as legacy single-slug plans. Flags: `--ack` (override the SHARED-CONCERNS.md ack-gate) and `--force-partial` (proceed against a tree where some clusters failed planning, excluding the failed ones from the run set). Both flags are inert for legacy single-slug plans.
 - **`/z-implement-next`** — Same loop, one task at a time.
 
+### Code quality
+
+- **`/z-style-init`** — Author the project `STYLE.md` interactively, grounded in the repo's most idiomatic existing files (Capture). Required before `/z-mr-review` will run. Pass `--amend` to add rules derived from repeated review dismissals instead of bootstrapping.
+- **`/z-mr-review`** — Multi-LLM code-quality review of the current branch diff against `STYLE.md`. Fans out to Claude, Codex, and Gemini; deduplicates and ranks findings P0–P4; writes `z-harness/<slug>/MR-REVIEW.md` in `TASKS.md`-compatible shape. Never blocks — delete findings you don't want, then run `/z-implement-all --tasks=MR-REVIEW.md`. Targets five categories: abstraction, defensive-bloat, test-noise, hygiene, and style-drift. Distinct from `/z-audit`, which gates correctness.
+
 ### Audit, debug, review
 
 - **`/z-audit <target>`** — Read-only audit pipeline. Pre-flight scopes (target, dimensions, optional `.claude/audit-rubrics/<component>.md`), spawns one `auditor` subagent per dimension in parallel (correctness / perf / cleanliness / design), bundled Gemini+Codex consult on findings, emits REPORT.md + TASKS.md in `/z-implement-all`-compatible format, codex-reviewer safety gate.
-- **`/z-debug <symptom>`** — Investigate a known-bad behavior with explicit repro / hypothesis / evidence / isolation phases; cross-LLM consult at hypothesis and fix stages; auto-bails to `/z-plan` if scope grows; writes a post-mortem.
+- **`/z-debug <symptom>`** — Investigate a known-bad behavior with explicit repro / hypothesis / evidence / isolation phases; cross-LLM consult at hypothesis and fix stages; auto-bails to `/z-plan` if scope grows; writes a post-mortem. Post-mortem phase optionally invokes `mr-reviewer` on the fix diff; P0/P1 findings are promoted to the post-mortem's preventative-action list automatically.
 - **`/z-review-all`** — Final-gate cross-LLM review of a completed plan's cumulative diff against SPEC.md — catches implementation drift and aggregate-only spec gaps.
 - **`/z-skill-fix <skill>`** — Meta-command. Patches any `.claude/skills/*/SKILL.md` (or `commands/*.md` / `agents/*.md` inside z-harness itself). Inline diagnosis → surgical edit → codex-reviewer safety gate.
```

Diff continues with agents/commands/scripts tables and directory tree — all consistent with the actual added files.

Surrounding file context (excerpt from actual implementation files):

=== /Users/zeke/dev/z-harness/commands/z-mr-review.md ===
- `--slug <value>` → capture as `SLUG_OVERRIDE`
- `--base <ref>` → capture as `BASE_OVERRIDE`
- `--include-untracked` flag → set `INCLUDE_UNTRACKED=true` (default `false`)
- `--deep` flag → set `DEEP=true` (default `false`). Upgrades the abstraction pass to Opus
- `--force-on-trunk` flag → set `FORCE_ON_TRUNK=true` (default `false`)

=== /Users/zeke/dev/z-harness/agents/mr-reviewer.md ===
Severity rubric:
- **P0** — would actively cause future bugs or maintenance pain (e.g. silent `except`/`_ =` over a real failure mode)
- **P1** — clear quality regression vs the rest of the codebase
- **P2** — STYLE.md violation or noticeable idiom drift
- **P3** — minor hygiene
- **P4** — taste-only

Consensus tier-bump rules:
- If all voices raised it: promote one tier (P4→P3 ... P1→P0; **P0 stays P0**)
- If only one voice raised it: demote one tier (P1→P2 ... P4 stays P4; **P0 stays P0**)
- If only one voice available: no bump in either direction

Dismissal-pattern match:
- Append `[previously-dismissed-pattern]` to detail
- If P1–P4: demote one tier
- If P0: keep P0; tag only

=== /Users/zeke/dev/z-harness/docs/llm/mr-reviewer.json ===
JSON is valid and includes all required fields:
- concept, last_updated, covers_spec, source_files, confidence
- entry_points array with file, line, symbol, kind, summary
- description (full prose)
- invariants array (5 items, all correct)
- gotchas array (5 items)
- five_categories array
- severity_rubric object
- falsifiability_thresholds object
- telemetry_events array
- related_concepts, depends_on, consumed_by arrays

=== /Users/zeke/dev/z-harness/docs/llm/style-init.json ===
JSON is valid and includes:
- concept, last_updated, covers_spec, source_files, confidence
- entry_points array (1 item)
- description
- invariants array (6 items)
- gotchas array (4 items)
- capture_insight string
- modes object (bootstrap, amend)
- style_md_sections array
- telemetry_events array
- related_concepts, depends_on, consumed_by arrays

=== /Users/zeke/dev/z-harness/docs/human/mr-reviewer.md ===
Contains:
- "What it does" section: correct summary of multi-voice review, P0-P4 ranking, never blocks, TASKS.md shape
- "When to use it" section: bootstrap case, rapid sprint case, /z-debug post-mortem integration
- "The five review categories" table: abstraction, defensive-bloat, test-noise, hygiene, style-drift — all match spec
- "P0–P4 severity rubric" table: matches agent implementation exactly
- "Multi-voice consensus and dismissal adjustment" section: explains tier-bumps correctly, P0 exemption noted
- "Large-diff chunking" section: mentions Z_MR_DIFF_CHUNK_BYTES default 320000 bytes, --deep flag upgrade to Opus
- "Dismissal learning" section: extract-dismissals.py, ≥3 findings suggest /z-style-init --amend
- "Falsifiability thresholds" section: retire category at 30% dismissal rate, fold into /z-audit at 90% parity
- "Telemetry events" table: 8 events listed (mr_run_start, mr_run_end, mr_finding_emitted, mr_finding_dismissed, mr_style_missing, mr_voice_failed, mr_all_voices_failed, mr_voices_degraded)
- "Integration: /z-debug post-mortem hook" section: P0/P1 findings auto-appended to post-mortem, P2–P4 stay in MR-REVIEW.md

=== /Users/zeke/dev/z-harness/docs/human/style-init.md ===
Contains:
- "What it does" section: bootstrap vs amend modes, STYLE.md schema ref
- "Bootstrap mode" section with 4 subsections: Capture phase (heuristic prefilter, Sonnet ranking, user confirmation), Interview phase (4 questions), Critique and approval
- "Amend mode" section: scan archives, cluster by Jaccard, propose rules, user review
- "Rule ID convention" section: EH-, T-, C-, N-, P- prefixes, append-only, tombstone comments for retired rules
- Capture prefilter details: excludes <50 or >800 lines, hardcoded list (node_modules/, vendor/, dist/, target/, *.pb.go, *_pb2.py, migrations/, __generated__/, .min.*, lock files)
- Amend cluster: Jaccard >=0.6, stopword list, --global flag, 2-member minimum
- --ingest <path> skips interview and uses existing guide

Scrutinize this documentation rigorously. Claude is prone to: over-engineering, premature abstraction, plausible-looking-but-wrong logic, missed edge cases, and silently expanding scope beyond the spec.

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
- If there are no blockers or majors, respond with exactly: `No blockers or majors found.` (plus an optional 1-line note if something needs the implementer's attention but is below the bar).

codex
I’ll skim the changed docs against the implementation entry points and JSON structure, focusing only on blocker/major issues per your output constraints.
exec
/bin/zsh -lc "sed -n '1,260p' commands/z-mr-review.md && sed -n '1,280p' agents/mr-reviewer.md" in /Users/zeke/dev/z-harness
exec
/bin/zsh -lc 'python -m json.tool docs/llm/mr-reviewer.json >/tmp/mr-reviewer.json.ok && python -m json.tool docs/llm/style-init.json >/tmp/style-init.json.ok && python -m json.tool docs/llm/INDEX.json >/tmp/index.json.ok && python -m json.tool docs/llm/commands.json >/tmp/commands.json.ok && python -m json.tool docs/llm/agents.json >/tmp/agents.json.ok && python -m json.tool docs/llm/scripts.json >/tmp/scripts.json.ok && echo JSON_OK' in /Users/zeke/dev/z-harness
exec
/bin/zsh -lc 'git status --short && git diff -- README.md docs/human/mr-reviewer.md docs/human/style-init.md docs/llm/mr-reviewer.json docs/llm/style-init.json docs/llm/INDEX.json docs/llm/commands.json docs/llm/agents.json docs/llm/scripts.json' in /Users/zeke/dev/z-harness
exec
/bin/zsh -lc "sed -n '1,280p' commands/z-style-init.md && sed -n '1,260p' scripts/extract-dismissals.py" in /Users/zeke/dev/z-harness
 succeeded in 0ms:
 M README.md
 M agents/codex-consultant.md
 M agents/gemini-consultant.md
 M commands/z-debug.md
 M commands/z-implement-all.md
 M docs/llm/INDEX.json
 M docs/llm/agents.json
 M docs/llm/commands.json
 M docs/llm/scripts.json
 M z-harness/archive/tasks/T001/events.jsonl
 M z-harness/archive/tasks/T002/events.jsonl
 M z-harness/archive/tasks/T003/events.jsonl
 M z-harness/archive/tasks/T004/events.jsonl
 M z-harness/archive/tasks/T005/events.jsonl
 M z-harness/archive/tasks/T006/events.jsonl
 M z-harness/archive/tasks/T007/events.jsonl
 M z-harness/archive/tasks/T008/events.jsonl
 M z-harness/archive/tasks/T009/events.jsonl
 M z-harness/archive/tasks/T010/events.jsonl
 M z-harness/archive/tasks/T011/events.jsonl
 M z-harness/archive/tasks/T012/events.jsonl
 M z-harness/metrics.jsonl
?? agents/mr-reviewer.md
?? archive/
?? commands/z-mr-review.md
?? commands/z-style-init.md
?? docs/human/STYLE-md-schema.md
?? docs/human/mr-reviewer.md
?? docs/human/style-init.md
?? docs/llm/mr-reviewer.json
?? docs/llm/style-init.json
?? scripts/__pycache__/
?? scripts/extract-dismissals.py
?? scripts/test_extract_dismissals.py
?? z-harness/archive/1779573317775/
?? z-harness/archive/1779575377159/
?? z-harness/archive/1779575384116/
?? z-harness/archive/20260523-mr-style-reviewer-decisions/
?? z-harness/archive/20260523T192415Z-mr-style-reviewer/
?? z-harness/archive/20260523T192534Z-mr-style-reviewer/
?? z-harness/archive/brainstorm-1779564399/
?? z-harness/archive/docs/
?? z-harness/archive/dummy-token-unused/
?? z-harness/archive/mr-style-reviewer-plan-review/
?? z-harness/archive/tasks/T006/review.prompt.md
?? z-harness/archive/tasks/T006/review.response.md
?? z-harness/archive/tasks/T010/review/
?? z-harness/archive/tasks/T014/
?? z-harness/mr-style-reviewer/
diff --git a/README.md b/README.md
index bc4a19e..6333f5d 100644
--- a/README.md
+++ b/README.md
@@ -33,10 +33,15 @@ Every command writes its artifacts under `z-harness/<slug>/`, with run-frozen ar
 - **`/z-implement-all`** — Orchestrates the full TASKS.md queue: one fresh `implementer` subagent per task → per-task `codex-reviewer` safety gate → retry once on review failure → push-notify at every task boundary. Walks a tree-rooted plan produced by `/z-plan-split` (one cluster at a time, in MANIFEST run order) as well as legacy single-slug plans. Flags: `--ack` (override the SHARED-CONCERNS.md ack-gate) and `--force-partial` (proceed against a tree where some clusters failed planning, excluding the failed ones from the run set). Both flags are inert for legacy single-slug plans.
 - **`/z-implement-next`** — Same loop, one task at a time.
 
+### Code quality
+
+- **`/z-style-init`** — Author the project `STYLE.md` interactively, grounded in the repo's most idiomatic existing files (Capture). Required before `/z-mr-review` will run. Pass `--amend` to add rules derived from repeated review dismissals instead of bootstrapping.
+- **`/z-mr-review`** — Multi-LLM code-quality review of the current branch diff against `STYLE.md`. Fans out to Claude, Codex, and Gemini; deduplicates and ranks findings P0–P4; writes `z-harness/<slug>/MR-REVIEW.md` in `TASKS.md`-compatible shape. Never blocks — delete findings you don't want, then run `/z-implement-all --tasks=MR-REVIEW.md`. Targets five categories: abstraction, defensive-bloat, test-noise, hygiene, and style-drift. Distinct from `/z-audit`, which gates correctness.
+
 ### Audit, debug, review
 
 - **`/z-audit <target>`** — Read-only audit pipeline. Pre-flight scopes (target, dimensions, optional `.claude/audit-rubrics/<component>.md`), spawns one `auditor` subagent per dimension in parallel (correctness / perf / cleanliness / design), bundled Gemini+Codex consult on findings, emits REPORT.md + TASKS.md in `/z-implement-all`-compatible format, codex-reviewer safety gate.
-- **`/z-debug <symptom>`** — Investigate a known-bad behavior with explicit repro / hypothesis / evidence / isolation phases; cross-LLM consult at hypothesis and fix stages; auto-bails to `/z-plan` if scope grows; writes a post-mortem.
+- **`/z-debug <symptom>`** — Investigate a known-bad behavior with explicit repro / hypothesis / evidence / isolation phases; cross-LLM consult at hypothesis and fix stages; auto-bails to `/z-plan` if scope grows; writes a post-mortem. Post-mortem phase optionally invokes `mr-reviewer` on the fix diff; P0/P1 findings are promoted to the post-mortem's preventative-action list automatically.
 - **`/z-review-all`** — Final-gate cross-LLM review of a completed plan's cumulative diff against SPEC.md — catches implementation drift and aggregate-only spec gaps.
 - **`/z-skill-fix <skill>`** — Meta-command. Patches any `.claude/skills/*/SKILL.md` (or `commands/*.md` / `agents/*.md` inside z-harness itself). Inline diagnosis → surgical edit → codex-reviewer safety gate.
 
@@ -55,6 +60,7 @@ Every command writes its artifacts under `z-harness/<slug>/`, with run-frozen ar
 | Agent | Model | Role |
 |---|---|---|
 | `implementer` | sonnet | Implements one task in fresh context |
+| `mr-reviewer` | sonnet | Fans out to codex/gemini consultants, deduplicates findings, applies P0-P4 rubric |
 | `auditor` | sonnet | Audits one dimension, returns structured findings |
 | `cluster-planner` | sonnet | Runs a narrow sub-/z-plan for one cluster of a `/z-plan-split` tree |
 | `gemini-consultant` | (CLI) | Cross-LLM consult via Gemini |
@@ -203,8 +209,10 @@ z-harness/
 │   ├── z-implement-next.md
 │   ├── z-audit.md
 │   ├── z-debug.md
+│   ├── z-mr-review.md
 │   ├── z-review-all.md
 │   ├── z-skill-fix.md
+│   ├── z-style-init.md
 │   ├── z-init-docs.md
 │   ├── z-maintain-docs.md
 │   ├── z-suggest-memory.md
@@ -216,10 +224,12 @@ z-harness/
 │   ├── codex-reviewer.md
 │   ├── codex-consultant.md
 │   ├── gemini-consultant.md
+│   ├── mr-reviewer.md
 │   ├── spec-precheck.md
 │   ├── doc-updater.md
 │   └── remote-runner.md
 ├── scripts/
+│   ├── extract-dismissals.py
 │   ├── log-event.sh
 │   ├── log-phase.sh
 │   ├── remote-sandbox-sync.sh
diff --git a/docs/llm/INDEX.json b/docs/llm/INDEX.json
index 25adddf..884d648 100644
--- a/docs/llm/INDEX.json
+++ b/docs/llm/INDEX.json
@@ -3,6 +3,43 @@
   "generated_at": "2026-05-23T19:31:00Z",
   "z_harness_version": "64a3dbe",
   "concepts": [
+    {
+      "slug": "mr-reviewer",
+      "source_file": [
+        "commands/z-mr-review.md",
+        "agents/mr-reviewer.md",
+        "scripts/extract-dismissals.py"
+      ],
+      "last_updated": "2026-05-23",
+      "confidence": "high",
+      "depends_on": [
+        "agents",
+        "scripts",
+        "style-init"
+      ],
+      "consumed_by": [
+        "commands"
+      ],
+      "summary": "Multi-LLM code-quality reviewer for branch diffs; ranks P0-P4, never blocks, writes TASKS.md-shape MR-REVIEW.md."
+    },
+    {
+      "slug": "style-init",
+      "source_file": [
+        "commands/z-style-init.md",
+        "scripts/extract-dismissals.py"
+      ],
+      "last_updated": "2026-05-23",
+      "confidence": "high",
+      "depends_on": [
+        "agents",
+        "scripts"
+      ],
+      "consumed_by": [
+        "commands",
+        "mr-reviewer"
+      ],
+      "summary": "Capture-first STYLE.md bootstrap and amend flow; required before /z-mr-review will run."
+    },
     {
       "slug": "agents",
       "source_file": [
diff --git a/docs/llm/agents.json b/docs/llm/agents.json
index 073351d..ea9d788 100644
--- a/docs/llm/agents.json
+++ b/docs/llm/agents.json
@@ -4,6 +4,7 @@
   "covers_spec": "none",
   "source_file": [
     "agents/auditor.md",
+    "agents/mr-reviewer.md",
     "agents/cluster-planner.md",
     "agents/codex-consultant.md",
     "agents/codex-reviewer.md",
@@ -17,6 +18,13 @@
   ],
   "confidence": "high",
   "entry_points": [
+    {
+      "file": "agents/mr-reviewer.md",
+      "line": 1,
+      "symbol": "mr-reviewer",
+      "kind": "module",
+      "summary": "Fans out to codex/gemini consultants, deduplicates findings by (file, category, normalized_text), applies consensus tier-bumps and dismissal-pattern matches, returns structured findings JSON to orchestrator."
+    },
     {
       "file": "agents/auditor.md",
       "line": 1,
diff --git a/docs/llm/commands.json b/docs/llm/commands.json
index d72fa38..2920987 100644
--- a/docs/llm/commands.json
+++ b/docs/llm/commands.json
@@ -7,6 +7,8 @@
     "commands/z-audit.md",
     "commands/z-brainstorm.md",
     "commands/z-debug.md",
+    "commands/z-mr-review.md",
+    "commands/z-style-init.md",
     "commands/z-do.md",
     "commands/z-implement-all.md",
     "commands/z-implement-next.md",
@@ -25,6 +27,20 @@
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
diff --git a/docs/llm/scripts.json b/docs/llm/scripts.json
index 2062722..d48f29a 100644
--- a/docs/llm/scripts.json
+++ b/docs/llm/scripts.json
@@ -3,6 +3,7 @@
   "last_updated": "2026-05-23",
   "covers_spec": "none",
   "source_file": [
+    "scripts/extract-dismissals.py",
     "scripts/log-event.sh",
     "scripts/log-phase.sh",
     "scripts/regenerate-memories-flat.py",
@@ -11,6 +12,13 @@
   ],
   "confidence": "high",
   "entry_points": [
+    {
+      "file": "scripts/extract-dismissals.py",
+      "line": 1,
+      "symbol": "extract-dismissals.py",
+      "kind": "module",
+      "summary": "Computes dismissed finding signatures from consecutive MR-REVIEW.md archive snapshots; shared by /z-mr-review and /z-style-init --amend."
+    },
     {
       "file": "scripts/log-event.sh",
       "line": 1,

 exited 127 in 0ms:
zsh:1: command not found: python

 succeeded in 0ms:
---
description: Multi-LLM code-quality review of the current branch diff against STYLE.md. Never blocks; ranks P0-P4; output is a TASKS.md-shape file you edit and feed to /z-implement-all.
argument-hint: [--slug <slug>] [--base <git-ref>] [--include-untracked] [--deep] [--force-on-trunk]
---

You are running the **z-harness `/z-mr-review`** pipeline.

Arguments (from `$ARGUMENTS`):

$ARGUMENTS

## Argument parsing

Parse `$ARGUMENTS` before doing anything else:

- `--slug <value>` → capture as `SLUG_OVERRIDE`. Overrides the auto-derived slug.
- `--base <ref>` → capture as `BASE_OVERRIDE`. Overrides the default base ref computation.
- `--include-untracked` flag → set `INCLUDE_UNTRACKED=true` (default `false`).
- `--deep` flag → set `DEEP=true` (default `false`). Upgrades the abstraction pass to Opus (plumbed in T006+ agent dispatch).
- `--force-on-trunk` flag → set `FORCE_ON_TRUNK=true` (default `false`). Allows running on `main`/`master`/`trunk`.

---

## Phase 1 — Setup

### Step 1a — Slug resolution

Resolve the slug by which this run is namespaced (`z-harness/<slug>/`):

**If `--slug` was provided:**

Validate the override before accepting it — reject empty values or any character outside `[a-z0-9-]`:

```bash
if [ -z "$SLUG_OVERRIDE" ] || ! echo "$SLUG_OVERRIDE" | grep -qE '^[a-z0-9-]+$'; then
  echo "Error: --slug value '$SLUG_OVERRIDE' is invalid. Must match ^[a-z0-9-]+$ (lowercase alphanumeric and hyphens only)." >&2
  exit 1
fi
SLUG="$SLUG_OVERRIDE"
```

**Trunk guard applies regardless of `--slug`.** Always inspect the actual current branch:

```bash
CURRENT_BRANCH="$(git branch --show-current 2>/dev/null)"
if [ "$CURRENT_BRANCH" = "main" ] || [ "$CURRENT_BRANCH" = "master" ] || [ "$CURRENT_BRANCH" = "trunk" ]; then
  if [ "${FORCE_ON_TRUNK:-false}" != "true" ]; then
    echo "Error: current branch is '$CURRENT_BRANCH'. /z-mr-review is almost certainly meant for a feature branch, not trunk. Run with --force-on-trunk if you intend to review a trunk diff." >&2
    exit 1
  fi
fi
```

Export the slug for child processes:

```bash
export Z_HARNESS_SLUG="$SLUG"
```

**Otherwise, derive from the current branch:**

```bash
CURRENT_BRANCH="$(git symbolic-ref --short HEAD 2>/dev/null)"
```

If `git symbolic-ref --short HEAD` exits nonzero (detached HEAD), refuse with:

> Error: repository is in detached HEAD state. Use `--slug=<name>` to specify a slug explicitly.

Exit nonzero.

If `CURRENT_BRANCH` is empty after the check, apply the same detached-HEAD refusal.

Normalize the branch name to a slug:
1. Lowercase the branch name.
2. Replace `/` with `-`.
3. Strip any character that is not alphanumeric or `-`.

```bash
SLUG="$(echo "$CURRENT_BRANCH" | tr '[:upper:]' '[:lower:]' | tr '/' '-' | tr -cd 'a-z0-9-')"
```

Export the slug for child processes:

```bash
export Z_HARNESS_SLUG="$SLUG"
```

**Trunk guard:** If `CURRENT_BRANCH` is one of `main`, `master`, or `trunk` AND `FORCE_ON_TRUNK` is `false`, refuse with:

> Error: current branch is `<CURRENT_BRANCH>`. `/z-mr-review` is almost certainly meant for a feature branch, not trunk. Run with `--force-on-trunk` if you intend to review a trunk diff.

Exit nonzero.

### Step 1b — STYLE.md gate

Check that `STYLE.md` exists at the repo root:

```bash
ls ./STYLE.md 2>/dev/null
```

If `STYLE.md` does not exist, log `mr_style_missing`, then refuse:

> Error: no `STYLE.md` found at the repo root. Run `/z-style-init` first. There is no `--no-style` escape.

Exit nonzero.

### Step 1c — Run ID and archive setup

Pick a run ID and create the archive directory **before** any telemetry calls:

```bash
RUN="$(date -u +%Y%m%dT%H%M%SZ)-mr-review"
SLUG_DIR="z-harness/$SLUG"
ARCHIVE_DIR="$SLUG_DIR/archive/$RUN"
mkdir -p "$ARCHIVE_DIR/chunks"
export SLUG RUN ARCHIVE_DIR SLUG_DIR
```

### Step 1d — Voice availability pre-check

Check which multi-LLM voices are available:

```bash
command -v codex >/dev/null 2>&1 && CODEX_AVAILABLE=true || CODEX_AVAILABLE=false
command -v gemini >/dev/null 2>&1 && GEMINI_AVAILABLE=true || GEMINI_AVAILABLE=false
```

Build the `VOICES_AVAILABLE` list:

- Always include `claude`.
- If `CODEX_AVAILABLE=true`, include `codex`.
- If `GEMINI_AVAILABLE=true`, include `gemini`.

```bash
VOICES_AVAILABLE="claude"
[ "$CODEX_AVAILABLE" = "true" ] && VOICES_AVAILABLE="$VOICES_AVAILABLE,codex"
[ "$GEMINI_AVAILABLE" = "true" ] && VOICES_AVAILABLE="$VOICES_AVAILABLE,gemini"
```

If `VOICES_AVAILABLE` is only `claude` (neither codex nor gemini is available), warn the user and log a degraded event:

> Warning: neither `codex` nor `gemini` CLI is available. Running in single-voice (Claude-only) mode. Consensus tier-bump/demote logic is disabled. Install the missing CLIs for full multi-voice review.

```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" mr_voices_degraded \
  "$(printf '{"slug":"%s","voices_available":"%s"}' "$SLUG" "$VOICES_AVAILABLE")"
```

### Step 1e — Archive any existing MR-REVIEW.md

If `z-harness/<slug>/MR-REVIEW.md` already exists, archive it before overwriting:

```bash
EXISTING="$SLUG_DIR/MR-REVIEW.md"
if [ -f "$EXISTING" ]; then
  N=1
  while [ -f "$ARCHIVE_DIR/MR-REVIEW.md.previous-$N" ]; do
    N=$(( N + 1 ))
  done
  cp "$EXISTING" "$ARCHIVE_DIR/MR-REVIEW.md.previous-$N"
fi
```

### Step 1f — Version stamp and run-start log

```bash
VERSION_BLOB="$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/version.sh")"
```

### Step 1g — Base ref and diff capture

Determine the base git ref:

- If `--base` was provided, use `BASE_OVERRIDE`.
- Otherwise: check if `main` exists (`git rev-parse --verify main 2>/dev/null`); if so, use `main`.
- Otherwise: check if `master` exists (`git rev-parse --verify master 2>/dev/null`); if so, use `master`.
- Otherwise: refuse with "Cannot determine base ref: neither `main` nor `master` exists. Use `--base=<ref>` to specify one."

```bash
if [ -n "$BASE_OVERRIDE" ]; then
  BASE_REF="$BASE_OVERRIDE"
elif git rev-parse --verify main >/dev/null 2>&1; then
  BASE_REF="main"
elif git rev-parse --verify master >/dev/null 2>&1; then
  BASE_REF="master"
else
  echo "Error: Cannot determine base ref: neither 'main' nor 'master' exists. Use --base=<ref> to specify one." >&2
  exit 1
fi
```

Validate the resolved `BASE_REF` before using it — a bad `--base` value must error, not silently produce an empty diff:

```bash
if ! git rev-parse --verify "$BASE_REF" >/dev/null 2>&1; then
  echo "Error: base ref '$BASE_REF' does not exist in this repository." >&2
  exit 1
fi
BASE_SHA="$(git rev-parse "$BASE_REF")"
```

Capture the diff. `git diff` exits nonzero on error; an empty result is OK only when the diff command itself succeeds:

```bash
if ! git diff "$BASE_REF"...HEAD > "$ARCHIVE_DIR/diff.patch"; then
  echo "Error: 'git diff $BASE_REF...HEAD' failed — check that the base ref is reachable." >&2
  exit 1
fi
```

If `--include-untracked` is set, append untracked files using `git diff --no-index` directly (no custom header prepending to avoid malformed/duplicated hunks):

```bash
if [ "$INCLUDE_UNTRACKED" = "true" ]; then
  git ls-files --others --exclude-standard | while IFS= read -r f; do
    git diff --no-index -- /dev/null "$f" 2>/dev/null >> "$ARCHIVE_DIR/diff.patch" || true
  done
fi
```

If `diff.patch` is empty (zero bytes), exit cleanly:

> No changes vs `<BASE_REF>`; nothing to review.

```bash
if [ ! -s "$ARCHIVE_DIR/diff.patch" ]; then
  echo "No changes vs '$BASE_REF'; nothing to review."
  exit 0
fi
```

Compute diff stat for logging:

```bash
DIFF_STAT="$(git diff --stat "$BASE_REF"...HEAD | tail -1)"
```

### Step 1h — Size and chunking decision

Read the env-configurable threshold (default 320000 bytes ≈ 80k tokens):

```bash
CHUNK_THRESHOLD="${Z_MR_DIFF_CHUNK_BYTES:-320000}"
DIFF_BYTES="$(wc -c < "$ARCHIVE_DIR/diff.patch")"
```

If `DIFF_BYTES <= CHUNK_THRESHOLD`, set `MODE=full`. Otherwise set `MODE=per-chunk`.

```bash
if [ "$DIFF_BYTES" -le "$CHUNK_THRESHOLD" ]; then
  MODE="full"
else
  MODE="per-chunk"
fi
```

**If `MODE=per-chunk`**, split `diff.patch` into per-file chunks now:

---
name: mr-reviewer
description: Multi-LLM code-quality reviewer for branch diffs. Assumes correctness; targets AI-shaped and human-shaped slop. Ranks P0-P4, never blocks, never finds correctness bugs (those belong to codex-reviewer).
tools: Bash, Read, Grep, Glob, Edit, Write, Agent
model: sonnet
---

You review a branch diff for code quality — not correctness. You assume the code is correct and does what the author intended. Your job is to catch AI-shaped slop, defensive bloat, test noise, abstraction failures, and style drift. You rank findings P0–P4 and return them as a fenced JSON block plus a `## Summary` markdown block. You never write MR-REVIEW.md yourself — the orchestrator does that from your return.

## Hardcoded principles (apply independent of STYLE.md)

- **Assume correctness.** Do not raise correctness bugs. Those belong to `codex-reviewer`. If you spot one, note it in a one-line `## Cross-dimension note` at the end and move on.
- **Every added line must justify its weight.** Relative to the existing abstractions, local style, and the behavioral surface it supports, gratuitous diff growth is suspect; necessary growth is not. When in doubt, P4 — not P0.
- **When flagging abstraction, cite the existing duplicate by file:line.** Without a citation you have an opinion; with a citation you have a finding.

## Severity rubric

- **P0** — would actively cause future bugs or maintenance pain (e.g. silent `except`/`_ =` over a real failure mode, abstraction collapse that destroys a key invariant).
- **P1** — clear quality regression vs the rest of the codebase (defensive bloat against impossible state, dead AI-generated comment scaffolding, missed-extraction of significant duplication — ≥10 lines of near-identical logic).
- **P2** — STYLE.md violation or noticeable idiom drift.
- **P3** — minor hygiene (stale comment, mildly confusing name, redundant test, cosmetic nit with a fix).
- **P4** — taste-only, debatable, purely optional. Leave it; don't invest a P1 slot on it.

## Five review categories

- **defensive-bloat** — null-checks on values the type system already guarantees non-null; try/catch around code that cannot throw; fallback paths for impossible states; feature flags wrapping a single code path; over-parameterized functions where callers always pass the same value.
- **test-noise** — tests that assert on implementation details (internal call counts, log message text, private field values); tests that duplicate each other at the same level of abstraction without covering a new edge case; test helper scaffolding that dwarfs the assertion it enables; mock setups so elaborate they obscure what is actually being tested.
- **abstraction** — new function / class / type that duplicates logic already present in the codebase; missed extraction opportunity (≥10 lines appearing ≥2 times with only literal substitution); wrapping a thin single-use function around a one-liner that is already readable; premature generalization (generics / polymorphism for a single concrete caller).
- **hygiene** — misleading or stale comments (comment says X, code does Y); names that are inconsistent with the local naming convention without a clear reason; dead code left in (commented-out blocks, unused imports); verbose phrasing where the idiomatic form is obvious.
- **style-drift** — violation of a rule in STYLE.md, cited by rule ID (e.g. `STYLE.md:EH-001`). Covers only rules in STYLE.md; do not invent style rules not present there.

## Inputs from caller

The caller passes the following fields as a prompt block:

```
slug: <slug>
run_id: <RUN>
slug_dir: <abs path to z-harness/<slug>/>
base: <git ref, e.g. main>
base_sha: <resolved SHA of base ref>
diff_path: <abs path to a single .patch file>
style_path: <abs path to STYLE.md>
dismissed_signatures_path: <abs path to dismissed_signatures.json>
voices_available: [claude] | [claude, codex] | [claude, codex, gemini] | ...
mode: full | per-chunk | abstraction-only
chunk_meta: null | {index: N, total: M, manifest_path: <abs path>}
deep: true | false
```

`diff_path` is always a single `.patch` file. The agent never branches on whether this is a chunk or a full diff — it treats both identically.

`base_sha` lets you `git show <base_sha>:<path>` to read pre-change file context when verifying interface adherence.

`mode` controls which categories are active:
- `full` → all five categories.
- `per-chunk` → four categories (skip `abstraction` — a separate `abstraction-only` pass handles cross-file cases).
- `abstraction-only` → only the `abstraction` category, using Grep/Glob to find duplicates across the full repo.

`deep` → if `true` AND `mode != per-chunk`, upgrade the abstraction sub-pass to Opus (see Step 4).

## Procedure

### Step 1 — Read inputs

Read all three inputs before forming any findings:

1. STYLE.md at `style_path` in full. Note the rule IDs and their prose.
2. The diff at `diff_path` in full.
3. `dismissed_signatures.json` at `dismissed_signatures_path`. Schema: `{"signatures": [{"file": "...", "category": "...", "normalized_snippet": "...", "prior_run_id": "..."}, ...], "n_runs_scanned": N}`. If the file is missing or its `signatures` array is empty, proceed as if no dismissed signatures exist.

### Step 2 — Determine active categories

From `mode`:
- `full` → `[defensive-bloat, test-noise, abstraction, hygiene, style-drift]`
- `per-chunk` → `[defensive-bloat, test-noise, hygiene, style-drift]`
- `abstraction-only` → `[abstraction]`

### Step 3 — Inline Claude review

Run your own inline review of the diff against the active categories. For each category, scan the diff carefully and produce findings. Apply the severity rubric strictly — a finding with no concrete location and no quotable evidence is not a finding; drop it.

For **style-drift** findings: cite the STYLE.md rule ID in the `citation` field using the format `STYLE.md:EH-001`. If the drift does not correspond to any rule in STYLE.md, do not raise a style-drift finding (use `hygiene` instead).

For **abstraction** findings: you MUST cite the existing duplicate symbol or code by `file:line`. Use Grep/Glob to find duplicates — do not raise an abstraction finding without a concrete citation.

#### Abstraction sub-pass — symbol extraction and Grep

When `abstraction` is in the active categories, run the following sub-pass:

**Step A — Extract symbols from the diff.**

Parse the diff (lines beginning with `+`, excluding the `+++` header lines) for function, method, and class definitions using the following language-aware regexes. Detect the language from the file extension in the diff header (`--- a/<file>` / `+++ b/<file>`).

| Language | File extensions | Regexes to apply |
|----------|----------------|-----------------|
| Rust | `*.rs` | `fn\s+(\w+)`, `struct\s+(\w+)`, `enum\s+(\w+)`, `trait\s+(\w+)` |
| Python | `*.py` | `def\s+(\w+)`, `class\s+(\w+)` |
| TypeScript / JavaScript | `*.ts`, `*.tsx`, `*.js`, `*.jsx` | `function\s+(\w+)`, `(?:const\|let\|var)\s+(\w+)\s*=`, `class\s+(\w+)` |

Collect all captured group values (the symbol names). Record which diff file and approximate line each symbol came from.

**Step B — Apply common-name suppression.**

Discard any symbol whose name matches the following hardcoded suppression list (exact, case-sensitive):

```
format, parse, init, get, set, new, build, run, main, default, from, to, into, as, value, name, key, id, data, result, item, handle
```

**Step C — Grep for existing definitions, excluding the diff's own files.**

For each remaining symbol, run a Grep across the repo:

```bash
# Rust example
Grep -n "\bmy_symbol\b" --include="*.rs"

# Python example
Grep -n "\bmy_symbol\b" --include="*.py"

# TS/JS example — search all four extensions
Grep -n "\bmy_symbol\b" --include="*.ts"
Grep -n "\bmy_symbol\b" --include="*.tsx"
Grep -n "\bmy_symbol\b" --include="*.js"
Grep -n "\bmy_symbol\b" --include="*.jsx"
```

From the Grep results, **exclude any hit whose file path appears in the diff** (the new code being reviewed). You are looking for pre-existing occurrences in the rest of the codebase.

To identify which files belong to the diff, extract modified-file paths by parsing `diff_path` headers: collect every line matching `^--- a/(.+)$` and `^\+\+\+ b/(.+)$` (drop `/dev/null` entries from the `---` side, which appear for newly-added files that have no prior version). Deduplicate the collected paths — this is the `diff_own_files` set. Any Grep hit whose file path is in `diff_own_files` is excluded from Step C results.

**Step D — Definition check (reject call-site-only hits).**

For each Grep hit on a file NOT in the diff, Read that file at the reported line (±3 lines of context). Emit a candidate finding only if the matching line contains a **defining keyword** appropriate for the language:

- Rust: the line (or the line immediately before, for multi-line signatures) contains `fn `, `struct `, `enum `, or `trait `.
- Python: the line contains `def ` or `class `.
- TypeScript / JavaScript: the line contains `function `, `class `, `const `, `let `, or `var ` and the match is to the left of `=` (i.e. a declaration, not just a reference).

If the only hits are call sites (no defining keyword found near the match), **do not emit an abstraction finding for that symbol**. A definition citation is required.

**Step E — Emit finding with citation.**

For each symbol where a definition was confirmed in a non-diff file, emit an abstraction finding:

- `citation`: `"<other-file>:<line>"` pointing to the existing definition.
- `detail`: name the symbol introduced in the diff, the file:line where it appears in the diff, and the pre-existing definition at the cited location.
- `severity`: P1 if the existing definition is substantially similar (same parameter shape, same return type, same semantic purpose); P2 if similar in name only and possibly coincidental.

**Step F — Opus upgrade (mode=abstraction-only AND deep=true only).**

When `mode=abstraction-only` AND `deep=true`, after collecting candidate pairs via Steps A–E, dispatch a sub-pass as Opus for deeper structural reasoning:

```
Agent(
  subagent_type="general-purpose",
  model="opus",
  description="Deep abstraction analysis",
  prompt="You are analyzing whether the following code pairs represent meaningful duplication or coincidental similarity. For each pair, determine if they share the same semantic intent, the same data flow, and whether refactoring to a shared abstraction would reduce total complexity or increase it.\n\n<paste each candidate pair with file:line citations and the relevant source excerpts>\n\nReturn findings as JSON: {\"pairs\": [{\"symbol\": \"...\", \"file_a\": \"...\", \"line_a\": N, \"file_b\": \"...\", \"line_b\": N, \"is_meaningful_duplication\": true|false, \"rationale\": \"...\"}]}"
)
```

Use the Opus analysis to decide which abstraction findings to keep and which to drop:
- `is_meaningful_duplication: true` → keep the finding (promote to P1 if it was P2).
- `is_meaningful_duplication: false` → drop the finding entirely.

When `deep=false` or `mode != abstraction-only`, skip the Opus dispatch. The Grep + definition check from Steps C–E is sufficient; no sub-agent needed.

#### Extending the language list

The table above covers Rust, Python, and TS/JS. To add support for additional languages, add a row with:
- The language name and its file glob(s).
- The regex(es) that match definition lines and capture the symbol name in group 1.
- Any suppression-list additions that are idiomatic no-ops for that language.

Examples for commonly requested additions:

| Language | File extensions | Example definition regexes |
|----------|----------------|---------------------------|
| Go | `*.go` | `func\s+(?:\(\w+\s+\*?\w+\)\s+)?(\w+)`, `type\s+(\w+)\s+(?:struct\|interface)` |
| Java | `*.java` | `(?:public\|private\|protected\|static\|final\|\s)+\w+\s+(\w+)\s*\(`, `class\s+(\w+)`, `interface\s+(\w+)` |
| Ruby | `*.rb` | `def\s+(\w+)`, `class\s+(\w+)`, `module\s+(\w+)` |

Add corresponding entries to the Grep include-glob list in Step C and the definition-check keywords in Step D.

### Step 4 — Multi-voice dispatch (when voices_available includes codex or gemini)

When `voices_available` contains voices beyond `claude`, dispatch the non-Claude voices in parallel — a single message with one `Agent()` call per non-Claude voice. Claude's inline findings from Step 3 are already in hand; this step collects the others.

**Consultant prompt shape (same for both codex-consultant and gemini-consultant):**

```
Agent(
  subagent_type="codex-consultant",   # or "gemini-consultant"
  description="Codex MR-review voice for <slug>",
  prompt="MODE: mr-review
active_categories: [<comma-separated active category names>]
run_id: <run_id>

STYLE.md:
<full contents of style_path>

DIFF:
<full contents of diff_path>

Return findings as a fenced ```json block with EXACTLY this schema — no other keys:
{\"findings\": [{\"severity\": \"P0|P1|P2|P3|P4\", \"category\": \"<one of: defensive-bloat|test-noise|abstraction|hygiene|style-drift>\", \"file\": \"<relative path from repo root>\", \"line_start\": <integer or null>, \"line_end\": <integer or null>, \"title\": \"<short one-line title>\", \"detail\": \"<prose explanation — what is wrong and why it matters>\", \"citation\": \"<STYLE.md:EH-001 or file:line for abstraction, or null>\"}]}

Constraints:
- Do NOT raise correctness bugs (those belong to codex-reviewer).
- Only raise style-drift findings for rules present in STYLE.md (cite by rule ID).
- Only raise abstraction findings with a concrete file:line citation for the existing duplicate.
- category must be exactly one of the five named values above."
)
```

Dispatch all non-Claude voices in one message (parallel `Agent()` calls). Do not wait for one before dispatching the next.

**Parse failure handling:** for each voice's return, attempt to extract the fenced `json` block (look for a code fence tagged `json` containing a `findings` key). If the parse fails for any reason, log `mr_voice_failed {voice: "<name>", reason: "malformed_json"}` via:

```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$run_id" mr_voice_failed \
  "$(printf '{"voice":"%s","reason":"malformed_json"}' "<voice_name>")"
```

Then skip that voice's findings entirely — do not retry, do not fall back to a partial parse.

Track:
- `voices_succeeded`: list of voices that returned parseable JSON (`claude` always included; external voices only if parse succeeded).
- `voices_failed`: list of voices that returned malformed JSON.

### Step 5 — Merge findings and apply dismissal-pattern matching

You have findings from Step 3 (Claude inline) and Step 4 (any additional voices). Merge them as follows:

**Dedup:** identify findings with the same `(file, category, normalized_text)` signature. To normalize the text: concatenate `title` + `" "` + `detail`, lowercase, collapse internal whitespace to a single space, strip leading/trailing punctuation. Keep one finding per signature. Set `voices: [<list of all voices that raised this finding>]` on the merged finding — if both Claude and Codex raised a finding with the same signature, the merged finding's `voices` is `["claude", "codex"]`.

**Consensus tier-bump:** applied after dedup, using the per-finding `voices` list and `voices_succeeded` (the set of voices that returned parseable JSON — not `voices_available`). Voices that failed JSON parse are excluded from the denominator and do not affect tier-bump. Consensus is computed against `voices_succeeded`.
- If `len(voices_succeeded) >= 2` AND `len(finding.voices) == len(voices_succeeded)`: **promote one tier** (P4→P3, P3→P2, P2→P1, P1→P0; **P0 stays P0**).
- If `len(voices_succeeded) >= 2` AND `len(finding.voices) == 1`: **demote one tier** (P1→P2, P2→P3, P3→P4, P4 stays P4; **P0 stays P0 — never demote P0**).
- If `len(voices_succeeded) == 1`: no bump in either direction (single-voice mode, no consensus signal).

**Dismissal-pattern match:** for each finding, compute a normalized snippet = lowercase of `title`, whitespace collapsed, leading/trailing punctuation stripped. Compare to each `normalized_snippet` in `dismissed_signatures.json` using Jaccard token-overlap after removing stopwords (`the, a, an, this, that, is, are, in, on, of, to, for, and, or, with, by`). This is a **boolean per finding**: if ANY dismissed signature in the file has a matching `file`, matching `category`, AND Jaccard ≥ 0.6, stop checking further signatures for this finding (early exit on first match) and apply the tag + demotion exactly once:
- Append `[previously-dismissed-pattern]` to the `detail` field.
- If severity is P1–P4: demote one tier (P1→P2, P2→P3, P3→P4, P4 stays P4).
- If severity is P0: keep severity as P0; tag only. **Never demote a P0.**

**Jaccard computation steps:**
1. Tokenize both strings by splitting on whitespace.
2. Remove all stopword tokens (`the, a, an, this, that, is, are, in, on, of, to, for, and, or, with, by`) from both token sets.
3. If `|union| == 0` (both token sets are empty after stopword removal), score = 0 — treat as non-match.
4. Otherwise: Jaccard = `|intersection| / |union|` of the two token sets (set semantics — duplicate tokens in one string don't inflate the score).
5. If Jaccard ≥ 0.6, it is a match.

Increment `dismissal_pattern_matches` by 1 for each finding that matches (used in the Summary block count). A finding that matches multiple dismissed signatures still increments by exactly 1.

### Step 6 — Return findings

Return your findings as a fenced JSON block, then a `## Summary` markdown block. The orchestrator parses the JSON block to build MR-REVIEW.md; the Summary block is surfaced to the user directly.

**JSON schema (required — schema fidelity matters for orchestrator parsing):**

```json
{
  "findings": [
    {
      "severity": "P0|P1|P2|P3|P4",
      "category": "defensive-bloat|test-noise|abstraction|hygiene|style-drift",
      "file": "<relative path from repo root>",
      "line_start": <integer or null>,
      "line_end": <integer or null>,
      "title": "<short one-line title>",
      "detail": "<prose explanation — what is wrong and why it matters>",
      "citation": "<STYLE.md:EH-001 for style-drift, or file:line for abstraction citing the duplicate, or null>",
      "voices": ["<list of voices that raised this finding, e.g. claude, codex, gemini>"]
    }
  ],
  "voices_used": ["<list of all voices that successfully contributed findings>"]
}

 succeeded in 0ms:
---
description: Author the project STYLE.md interactively, grounded in the repo's most idiomatic existing files (Capture). Required before /z-mr-review will run.
argument-hint: [--amend] [--ingest <path-to-existing-guide>]
---

You are running the **z-harness `/z-style-init`** pipeline.

Arguments (from `$ARGUMENTS`):

$ARGUMENTS

## Argument parsing

Parse `$ARGUMENTS` before doing anything else:

- `--amend` flag present → **Mode B** (amend). See Mode B section below.
- `--ingest <path>` → capture the path as `INGEST_PATH`; interview phase will be skipped and this file read instead.
- No flags → **Mode A** (bootstrap).

---

## Mode A — Bootstrap (no `--amend`)

### Setup

1. **Check for existing STYLE.md.** Run:
   ```bash
   ls ./STYLE.md 2>/dev/null
   ```
   If `STYLE.md` already exists at the repo root, refuse:
   > `STYLE.md` already exists. Pass `--amend` to add rules from recent dismissals (pending T011), or delete `STYLE.md` manually to start over.
   Exit without writing anything.

2. **Derive repo name** from the current directory basename:
   ```bash
   basename "$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
   ```

3. **Pick a run id:**
   ```bash
   RUN=$(date -u +%Y%m%dT%H%M%SZ)-style-init
   ```
   (No slug-dir is needed for `/z-style-init` — STYLE.md writes to repo root, not to a z-harness subdirectory.)

4. **Version stamp + log run start:**
   ```bash
   VERSION_BLOB="$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/version.sh")"
   START_PAYLOAD="$(python3 -c '
   import json, sys
   v = json.loads(sys.argv[1])
   v["ingest_path"] = sys.argv[2]
   print(json.dumps(v))
   ' "$VERSION_BLOB" "${INGEST_PATH:-}")"
   bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" style_init_start "$START_PAYLOAD"
   ```

5. **Notification policy:** read env `Z_HARNESS_NOTIFY` (default `approval_only`). Values: `off`, `approval_only`, `all`.

---

## Phase telemetry (mandatory)

At the **start** of each phase (1 through 5), record `T0=$(date +%s%3N)`. At the **end**, log:

```bash
WALL_MS=$(( $(date +%s%3N) - T0 ))
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" phase_end \
  "$(printf '{"phase":%d,"name":"%s","wall_ms":%d,"user_wait_ms":%d}' \
     <phase-num> "<phase-name>" "$WALL_MS" "$USER_WAIT_MS_THIS_PHASE")"
```

If a phase blocks on `AskUserQuestion`, bracket the wait:

```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" user_wait_start '{"phase":<n>,"reason":"<short>"}'
# ... AskUserQuestion ...
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" user_wait_end '{"phase":<n>,"wall_ms":<delta>}'
```

---

## Phase 1 — Capture

**Goal:** identify the 5 most idiomatic source files in the repo to ground the style guide.

### Step 1a — Heuristic prefilter

Build the candidate list from tracked files:

```bash
git ls-files
```

Exclude files matching any of the following patterns (exact path prefix or glob):

- `node_modules/`
- `vendor/`
- `dist/`
- `target/`
- `__pycache__/`
- `*.pb.go`
- `*_pb2.py`
- `migrations/`
- `__generated__/`
- `*.min.*`
- `package-lock.json`
- `yarn.lock`
- `Cargo.lock`
- `poetry.lock`

Also exclude any file whose line count (via `wc -l`) is **< 50** or **> 800**.

Run line-count filtering in a shell loop or via `awk`. Record the surviving paths as `CANDIDATES`.

If `CANDIDATES` is empty, tell the user:

> No candidate files found after filtering (gitignored + exclusion list + size band 50-800 lines). The repo may be too small or entirely generated. STYLE.md cannot be bootstrapped without idiomatic examples. You may pass `--ingest <path>` to supply an existing guide instead.

Then exit.

### Step 1b — Sonnet rank

Dispatch a Sonnet subagent to pick the top 5 most idiomatic files from `CANDIDATES`:

```
Agent(
  subagent_type="general-purpose",
  model="sonnet",
  description="Rank idiomatic source files for STYLE.md capture",
  prompt="You are helping author a project style guide. Below is a list of tracked source files (already filtered for size and excludes).

Your task: rank them by 'idiomatic-ness' — that is, which files are most likely to reflect the project's deliberate coding conventions (not just the biggest files, not generated code, not scaffolding). Prefer files that appear to be hand-authored business logic, helpers, or core modules. Avoid test fixtures, example files, and entry-point boilerplate unless the repo is almost entirely composed of them.

Return exactly 5 file paths from the list, one per line, ranked best-first. No explanation needed — just the 5 paths.

Repo language hint (from file extensions): <detect dominant extension from CANDIDATES list>

Candidate files:
<CANDIDATES, one per line>"
)
```

Capture the agent's return as `RANKED_5` (a list of 5 paths).

If the agent returns fewer than 5 paths (e.g. `CANDIDATES` had fewer than 5 entries), use all available.

### Step 1c — User confirmation of Capture set

Present the ranked 5 to the user via `AskUserQuestion`:

```
The following 5 files will anchor your STYLE.md (ranked by idiomatic-ness):

1. <path1>
2. <path2>
3. <path3>
4. <path4>
5. <path5>

Options:
  use these       — proceed with this list
  edit list       — provide a replacement list (free-text, one path per line)
  re-pick         — ask the ranker for a different set of 5
  abandon         — exit without writing STYLE.md
```

Log `user_wait_start` before presenting; log `user_wait_end` after reply. Track `USER_WAIT_MS_THIS_PHASE`.

Branch on reply:

- **use these** → `FINAL_5 = RANKED_5`; proceed.
- **edit list** → treat the user's reply as a newline-separated list of paths; verify each exists with `git ls-files <path>`; warn about any untracked/missing paths (but do not block); set `FINAL_5` to the provided list; proceed.
- **re-pick** → repeat Step 1b with a note in the prompt: "Do not return the same set as before: <RANKED_5>." Loop back to Step 1c.
- **abandon** → exit cleanly. Log `style_init_abandoned` event.

### Step 1d — Read Capture files

Read the contents of the `FINAL_5` files into context (using the Read tool for each). These will be passed verbatim to the Draft phase.

---

## Phase 2 — Interview (or Ingest)

**If `--ingest <path>` was specified:**

Read the file at `INGEST_PATH` into context as `EXISTING_GUIDE`. Skip the interview questions below. Set `SOURCE = ingest`. Proceed to Phase 3.

**Otherwise (no `--ingest`), ask up to 4 questions via `AskUserQuestion`:**

Ask all 4 in a single `AskUserQuestion` call (multi-part prompt), then wait for a single reply. If the user skips a question or gives a blank answer for it, treat that section as "no preference stated."

```
To write a style guide grounded in your project's actual conventions, please answer the following (skip any you don't care about):

1. Error handling philosophy: Do you prefer defensive error handling (wrap-and-log everywhere, guard clauses, early returns) or propagating errors upward (let callers decide)? Or something specific to your stack?

2. Testing posture: Mostly unit tests with mocks? Integration / end-to-end heavy? Mixed? Any testing anti-patterns you want to ban?

3. Comment policy: When should code be commented? Are there formats you require (e.g. JSDoc, rustdoc, /// only for public items)? What types of comments do you want to avoid?

4. Project-specific rules: Anything else this codebase insists on that wouldn't appear in a generic style guide? (e.g. "no direct DB calls outside the repository layer", "all datetimes in UTC", "never import from sibling packages")
```

Record answers as `INTERVIEW_ANSWERS`. Set `SOURCE = capture` (primary source is the Capture files).

---

## Phase 3 — Draft STYLE.md

Dispatch a Sonnet subagent to draft the full STYLE.md:

```
Agent(
  subagent_type="general-purpose",
  model="sonnet",
  description="Draft STYLE.md from captured files and interview answers",
  prompt="You are writing a project STYLE.md. You will produce a style guide in a specific schema. The guide must have:

FRONTMATTER (YAML, required fields):
  schema_version: 1
  source: <SOURCE value>
  source_files: [<FINAL_5 paths, or empty list if ingest>]
  repo: <REPO_NAME>
  revision: <output of: git rev-parse HEAD>
  generated_at: <current ISO 8601 UTC timestamp>

BODY (five required sections, in this order, each with at least one rule):
  ## Error handling   (rule IDs: EH-001, EH-002, ...)
  ## Tests            (rule IDs: T-001, T-002, ...)
  ## Comments         (rule IDs: C-001, C-002, ...)
  ## Naming           (rule IDs: N-001, N-002, ...)
  ## Project-specific (rule IDs: P-001, P-002, ...)

Each rule must follow this format exactly:
  ### EH-001: <short rule title>
  <one-paragraph rule prose — concrete and actionable, not vague>
  Rationale: <one sentence explaining why this matters for the project>

Rule IDs are append-only within each section. Use sequential numbering starting at 001.

Aim for 3-5 rules per section. Draw directly from the source files and interview answers. Do not invent rules that contradict what you observe in the source files. If the source files show no evidence for a rule, omit it rather than guess.

Captured source files (read these carefully for observed conventions):
<contents of FINAL_5 files, one after another with path headers>

Interview answers (user preferences to encode as rules):
<INTERVIEW_ANSWERS or 'No interview answers — derived from ingest guide below' + EXISTING_GUIDE>

Return the complete STYLE.md content (frontmatter + body) as a single fenced markdown block."
)
```

Capture the agent return as `DRAFT_STYLE_MD`. Extract the content from the fenced block.

---

## Phase 4 — Cross-LLM Critique

Dispatch `codex-consultant` and `gemini-consultant` **in parallel in a single message** with `MODE: style-critique`:

```
Agent(
  subagent_type="codex-consultant",
  description="Style-critique STYLE.md draft",
  prompt="MODE: style-critique

Review the STYLE.md draft below. Flag:
- Missing rule categories (e.g. a section with zero rules, or a clearly missing topic given the observed source files)
- Vague rules (prose that is not actionable — e.g. 'write clean code')
- Contradictions between rules (e.g. EH-001 says propagate; EH-003 says swallow)
- Rule IDs that are out of sequence or duplicated

Return your findings as a numbered list. Each finding: one sentence describing the problem + one sentence proposing a fix. If you find no problems, return 'No findings.'

STYLE.md draft:
<DRAFT_STYLE_MD>"
)

Agent(
  subagent_type="gemini-consultant",
#!/usr/bin/env python3
"""
Extract dismissed MR-review findings from archived run snapshots.

Usage:
    python3 scripts/extract-dismissals.py <slug-dir> [--max-runs N] [--global]

For each pair of consecutive runs (R_i, R_{i+1}) in chronological order:
  1. Snapshot at archive/R_i/MR-REVIEW.md = original findings.
  2. Pre-edit copy at archive/R_{i+1}/MR-REVIEW.md.previous-* = what was
     there just before R_{i+1} overrode it (the user-edited version).
  3. Dismissed = findings in (1) whose signature (file, category, normalized_snippet)
     does NOT appear in (2).

Output (stdout): JSON {"signatures": [...], "n_runs_scanned": N}

Exit codes:
  0 — success (even if no dismissals found)
  1 — argument error
"""

import argparse
import json
import re
import string
import sys
from pathlib import Path


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------

def normalize_snippet(text: str) -> str:
    """
    Normalize a finding's title/detail for signature matching.

    Steps:
    1. Lowercase.
    2. Collapse internal whitespace to a single space.
    3. Strip leading/trailing punctuation.
    """
    text = text.lower()
    text = re.sub(r"\s+", " ", text)
    text = text.strip(string.punctuation + " ")
    return text


# ---------------------------------------------------------------------------
# Frontmatter parser (stdlib only — no PyYAML dependency)
# ---------------------------------------------------------------------------

def _parse_frontmatter_block(fm_text: str) -> dict:
    """
    Parse a minimal subset of YAML frontmatter sufficient for MR-REVIEW.md.

    Handles:
      - Simple scalar fields:  key: value
      - Block list fields (findings_index):
          findings_index:
            - {id: T-MR-001, severity: P0, category: abstraction, file: src/foo.rs}
            - ...
      - Inline list fields:   voices_available: [claude, codex, gemini]

    Returns a dict. On any parse error, returns {}.
    """
    result: dict = {}
    lines = fm_text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        # Skip blank lines and comments
        if not line.strip() or line.strip().startswith("#"):
            i += 1
            continue

        # Top-level key: value  (no leading whitespace)
        m = re.match(r'^([A-Za-z_][A-Za-z0-9_]*):\s*(.*)', line)
        if not m:
            i += 1
            continue

        key = m.group(1)
        raw_val = m.group(2).strip()

        if raw_val == "":
            # Possibly a block list follows
            block_items = []
            i += 1
            while i < len(lines):
                item_line = lines[i]
                # A list item must start with whitespace + "- "
                if re.match(r'^\s+-\s+', item_line):
                    # Extract the dict literal in braces, or plain value
                    item_content = re.sub(r'^\s+-\s+', '', item_line).strip()
                    parsed_item = _parse_inline_value(item_content)
                    block_items.append(parsed_item)
                    i += 1
                elif item_line.strip() == "" or item_line.startswith(" ") or item_line.startswith("\t"):
                    # Continuation of block or blank line inside block
                    i += 1
                else:
                    # Back to top level
                    break
            result[key] = block_items
        else:
            result[key] = _parse_inline_value(raw_val)
            i += 1

    return result


def _parse_inline_value(raw: str):
    """
    Parse a raw YAML inline value.

    Handles:
      - Inline dict:  {key: val, key2: val2}
      - Inline list:  [a, b, c]
      - Quoted string: "foo" or 'foo'
      - Bare string / number
    """
    raw = raw.strip()
    if raw.startswith("{") and raw.endswith("}"):
        return _parse_inline_dict(raw[1:-1])
    if raw.startswith("[") and raw.endswith("]"):
        return _parse_inline_list(raw[1:-1])
    if (raw.startswith('"') and raw.endswith('"')) or \
       (raw.startswith("'") and raw.endswith("'")):
        return raw[1:-1]
    # Try integer
    try:
        return int(raw)
    except ValueError:
        pass
    return raw


def _parse_inline_dict(inner: str) -> dict:
    """Parse the interior of {key: val, key2: val2}."""
    result = {}
    # Split on commas that are not inside nested braces/brackets
    parts = _split_respecting_nesting(inner)
    for part in parts:
        part = part.strip()
        colon_idx = part.find(":")
        if colon_idx == -1:
            continue
        k = part[:colon_idx].strip()
        v = part[colon_idx + 1:].strip()
        result[k] = _parse_inline_value(v)
    return result


def _parse_inline_list(inner: str) -> list:
    """Parse the interior of [a, b, c]."""
    if not inner.strip():
        return []
    parts = _split_respecting_nesting(inner)
    return [_parse_inline_value(p.strip()) for p in parts if p.strip()]


def _split_respecting_nesting(text: str) -> list[str]:
    """Handles YAML scalar splitting at top-level commas; understands single+double quoted strings (with single-quote escape via doubled '') and bracket/brace nesting. Does NOT support YAML block scalars (|, >) or multi-line values — those are not emitted by mr-reviewer's findings_index writer.

    Quote state is only entered when the quote character appears in a YAML
    string-delimiter context: immediately after ``{``, ``[``, ``(``, ``,``, or
    ``:`` (with optional intervening whitespace), or at the very start of the
    current token.  A bare apostrophe inside a plain scalar (e.g. ``Don't``)
    is treated as ordinary text so it does not cause a fake quote state that
    would merge subsequent fields.
    """
    # Characters that, when they are the last non-whitespace character before a
    # quote, signal that the quote is a YAML string delimiter rather than plain
    # text (e.g. an apostrophe in a word like "Don't").
    _DELIMITER_CHARS = frozenset("{[(,:")

    parts = []
    depth = 0
    in_quote: str | None = None  # None, '"', or "'"
    current: list[str] = []
    i = 0
    while i < len(text):
        ch = text[i]
        if in_quote is not None:
            # Inside a quoted string: only an unescaped matching quote ends it
            if ch == "\\" and i + 1 < len(text):
                # Escaped character — consume both
                current.append(ch)
                i += 1
                current.append(text[i])
            elif ch == in_quote:
                if in_quote == "'" and i + 1 < len(text) and text[i + 1] == "'":
                    # YAML single-quote escape: doubled '' stays in quote state
                    current.append(ch)
                    i += 1
                    current.append(text[i])
                else:
                    in_quote = None
                    current.append(ch)
            else:
                current.append(ch)
        elif ch in ('"', "'"):
            # Only enter quote state when in a delimiter context:
            # the last non-whitespace character already consumed is a
            # YAML delimiter, or the current token is empty (token start).
            current_str = "".join(current).rstrip()
            in_delimiter_context = (
                not current_str  # token start
                or current_str[-1] in _DELIMITER_CHARS
            )
            if in_delimiter_context:
                in_quote = ch
            current.append(ch)
        elif ch in "([{":
            depth += 1
            current.append(ch)
        elif ch in ")]}":
            depth -= 1
            current.append(ch)
        elif ch == "," and depth == 0:
            parts.append("".join(current))
            current = []
        else:
            current.append(ch)
        i += 1
    if current:
        parts.append("".join(current))
    return parts


def parse_mr_review_frontmatter(path: Path) -> dict:
    """
    Parse the YAML frontmatter block from an MR-REVIEW.md file.

    Returns {} if the file is missing, empty, or has no frontmatter.
    """
    if not path.exists():
        return {}
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return {}

    if not text.startswith("---"):
        return {}

    # Find closing ---
    end_idx = text.find("\n---", 3)
    if end_idx == -1:
        return {}

    fm_text = text[3:end_idx]
    return _parse_frontmatter_block(fm_text)


# ---------------------------------------------------------------------------
# Signature extraction
# ---------------------------------------------------------------------------


codex
The first pass shows `python` is not on PATH here, so I’m rerunning JSON validation with `python3` and narrowing the read to the new docs plus the command details that can contradict them.
exec
/bin/zsh -lc "sed -n '1,260p' docs/human/mr-reviewer.md && sed -n '1,280p' docs/human/style-init.md" in /Users/zeke/dev/z-harness
exec
/bin/zsh -lc 'python3 -m json.tool docs/llm/mr-reviewer.json >/tmp/mr-reviewer.json.ok && python3 -m json.tool docs/llm/style-init.json >/tmp/style-init.json.ok && python3 -m json.tool docs/llm/INDEX.json >/tmp/index.json.ok && python3 -m json.tool docs/llm/commands.json >/tmp/commands.json.ok && python3 -m json.tool docs/llm/agents.json >/tmp/agents.json.ok && python3 -m json.tool docs/llm/scripts.json >/tmp/scripts.json.ok && echo JSON_OK' in /Users/zeke/dev/z-harness
exec
/bin/zsh -lc "sed -n '1,260p' docs/llm/mr-reviewer.json && sed -n '1,260p' docs/llm/style-init.json && sed -n '1,160p' docs/llm/INDEX.json" in /Users/zeke/dev/z-harness
exec
/bin/zsh -lc "rg -n \"z-implement-all|--tasks|MR-REVIEW|style_init|mr_|P0|P1|post-mortem|preventative|Z_MR|global|Jaccard|ingest|extract-dismissals|dismiss\" README.md commands agents docs/human docs/llm scripts -g '"'!scripts/__pycache__/**'"'" in /Users/zeke/dev/z-harness
 succeeded in 162ms:
# MR Reviewer

> Last updated: 2026-05-23
> Covers source: commands/z-mr-review.md, agents/mr-reviewer.md, scripts/extract-dismissals.py

## What it does

`/z-mr-review` performs a code-quality review of the current branch diff against the project's `STYLE.md`. It is distinct from `/z-audit` and `/z-review-all`, which gate correctness; the MR reviewer assumes the code is correct and instead targets AI-shaped and human-shaped quality slop.

The review fans out to all available LLM voices (Claude Sonnet inline, Codex via `codex-consultant`, Gemini via `gemini-consultant`). Findings are deduplicated, tagged by which voices raised them, ranked P0–P4, and written to `z-harness/<slug>/MR-REVIEW.md` in `TASKS.md`-compatible shape. The command **never blocks** — you triage by deleting unwanted findings from MR-REVIEW.md, then run `/z-implement-all --tasks=MR-REVIEW.md` on survivors.

## When to use it

- After landing a feature branch and before merging: catch quality regressions before they compound.
- After a rapid prototyping sprint where you traded quality for speed.
- As an optional post-mortem step in `/z-debug`: the debug command can invoke `mr-reviewer` on the fix diff and automatically promote P0/P1 findings to the post-mortem's preventative-action list.

Run `/z-style-init` first if the project has no `STYLE.md`; `/z-mr-review` refuses to proceed without one (no `--no-style` escape).

## The five review categories

| Category | What it targets |
|---|---|
| `abstraction` | Duplicated logic, missed extractions, cross-file symbol collisions. |
| `defensive-bloat` | Guards against impossible states; over-long error-handling chains. |
| `test-noise` | Redundant, brittle, or dead test code introduced by the diff. |
| `hygiene` | Stale comments, cosmetic naming oddities, unnecessary logging. |
| `style-drift` | Violations of rules defined in the project's `STYLE.md`. |

## P0–P4 severity rubric

| Severity | Meaning |
|---|---|
| **P0** | Would actively cause future bugs or maintenance pain (e.g. silent except-pass, abstraction collapse). Findings at this tier are never demoted — not by low voice consensus, not by a dismissal match. |
| **P1** | Clear quality regression vs the rest of the codebase (defensive bloat against impossible state, dead AI-generated scaffolding, significant missed extraction). |
| **P2** | STYLE.md violation or noticeable idiom drift. |
| **P3** | Minor hygiene (stale comments, naming oddities, redundant tests). |
| **P4** | Taste-only nits. |

P0–P2 are worth acting on. P3–P4 are informational. Delete freely.

## Multi-voice consensus and dismissal adjustment

Findings raised by all available voices are promoted one tier (P3 → P2, etc.). Findings raised by only one voice are demoted one tier (P3 → P4, etc.). P0 is exempt from both adjustments — it stays at P0 regardless of consensus.

Findings whose text signature matches a prior-run dismissal pattern get tagged `[previously-dismissed-pattern]` and are demoted one tier (P1 → P2, etc.). P0 findings that match a dismissal pattern are tagged but **not demoted**.

## Large-diff chunking

When the diff exceeds `Z_MR_DIFF_CHUNK_BYTES` (default 320 000 bytes, roughly 80K tokens), the orchestrator splits the diff per file and dispatches the `mr-reviewer` agent once per chunk. A final whole-diff abstraction-only pass catches cross-file duplication that per-chunk passes cannot see. The `--deep` flag upgrades that abstraction pass to Opus.

## Dismissal learning and `/z-style-init --amend`

Every run archives a snapshot of MR-REVIEW.md at `z-harness/<slug>/archive/<run-id>/MR-REVIEW.md`. The `scripts/extract-dismissals.py` utility compares consecutive run snapshots to identify findings the user deleted. When ≥ 3 findings in a run match prior dismissal patterns, the command suggests `/z-style-init --amend` to codify the pattern into STYLE.md so future reviews don't raise it again.

## Falsifiability thresholds (living criteria)

These thresholds determine when to retire or re-examine this reviewer. They are not enforced in code — they require a human decision.

- **Retire the category:** if a category's dismissal rate exceeds **30% over ≥ 10 runs**, the category is generating noise. Run `/z-stats` — it surfaces per-category dismissal rates and emits a warning when this threshold is crossed. Consider removing that category from active review or tightening its criteria.
- **Fold into `/z-audit`:** if the reviewer's findings achieve **>90% audit parity** with `/z-audit --dimension=cleanliness` on the same diffs, the two commands are redundant and `mr-reviewer` should be retired in favor of the audit pipeline.

## Telemetry events

| Event | When emitted |
|---|---|
| `mr_run_start` | Command setup complete, diff computed |
| `mr_run_end` | All findings written to MR-REVIEW.md |
| `mr_finding_emitted` | Once per finding (fields: severity, category, voices_count, dismissal_match) |
| `mr_finding_dismissed` | Once per dismissed signature on each subsequent run |
| `mr_style_missing` | Command refused: no STYLE.md found |
| `mr_voice_failed` | A consultant voice returned malformed JSON |
| `mr_all_voices_failed` | All voices failed; command exits nonzero |
| `mr_voices_degraded` | Only Claude is available; single-voice mode |

## Integration: `/z-debug` post-mortem hook

After committing a fix, `/z-debug`'s post-mortem phase offers (via `AskUserQuestion`) to run `/z-mr-review` on the fix diff. If accepted, the `mr-reviewer` agent runs with the debug run's slug. P0 and P1 findings are automatically appended to the post-mortem's "Preventative actions" section as bullet items, cited by `T-MR-NNN` ID. P2–P4 findings stay in MR-REVIEW.md only. See `commands/z-debug.md` for the integration details.

## See also

- `docs/human/style-init.md` — how to create and amend the STYLE.md this command requires.
- `docs/human/STYLE-md-schema.md` — the full STYLE.md schema reference including rule ID format and a worked example.
# Style Init

> Last updated: 2026-05-23
> Covers source: commands/z-style-init.md

## What it does

`/z-style-init` authors a project `STYLE.md` — the style guide that `/z-mr-review` uses to detect rule violations and idiom drift. The command has two modes: **bootstrap** (create a new STYLE.md from scratch) and **amend** (add rules derived from repeated dismissal patterns in past review runs).

`STYLE.md` lives at the repository root. Its schema is documented in `docs/human/STYLE-md-schema.md`.

## Bootstrap mode (no `--amend`)

Run `/z-style-init` on a repo that has no STYLE.md. The command refuses if STYLE.md already exists — use `--amend` instead.

### The Capture phase

The command builds your STYLE.md from the most idiomatic files in your repo, not from templates. This is the "Capture" insight: style rules grounded in code you already consider correct are more accurate and less controversial than rules invented from scratch.

Steps:

1. **Heuristic prefilter.** All tracked files are listed via `git ls-files`. Files that are generated, vendor, or too short/long (< 50 or > 800 lines) are excluded. The exclusion list includes `node_modules/`, `vendor/`, `dist/`, `target/`, `*.pb.go`, `*_pb2.py`, `migrations/`, lock files, and minified assets.
2. **Idiomatic-file ranking.** A Sonnet subagent ranks the candidates by idiomatic-ness and picks the top 5.
3. **User confirmation.** You are shown the 5 chosen files and may accept them, edit the list, ask for a different 5, or abandon. This gate prevents legacy god-objects from anchoring STYLE.md to bad patterns.
4. **File read.** The confirmed 5 files are read into context as Capture material.

### Interview phase

Up to 4 questions are asked interactively (via `AskUserQuestion`):

- Error handling philosophy — defensive or propagate-up?
- Testing posture — mock-heavy, integration-heavy, or mixed?
- Comment policy — when to comment and when not to?
- Anything else the project insists on (free text).

If you pass `--ingest <path>`, the interview is skipped and your existing guide at `<path>` is used as the input instead.

### Critique and approval

After the draft is generated from the Capture files and interview answers, `codex-consultant` and `gemini-consultant` critique it in parallel (flagging missing categories, vague rules, contradictions). The critique is applied, and you are asked to approve, edit, re-critique, or abandon.

Approved STYLE.md is written to the repo root. The `style_init_complete` event is logged and a push notification is sent.

## Amend mode (`--amend`)

Run `/z-style-init --amend` to add new rules derived from findings you have repeatedly dismissed in past `/z-mr-review` runs. The command refuses if no STYLE.md exists yet.

Steps:

1. **Scan archives.** `scripts/extract-dismissals.py` walks `z-harness/*/archive/*/MR-REVIEW.md` snapshots (default: most recent 10 runs, `--global` scans all slugs) to identify dismissed finding signatures.
2. **Cluster.** Dismissed signatures are grouped by category and text similarity (Jaccard token-overlap ≥ 0.6 after stopword removal). Clusters with fewer than 2 members are discarded — single-occurrence dismissals are not considered patterns.
3. **Propose rules.** A Sonnet subagent examines each cluster alongside the current STYLE.md and proposes new rules with stable IDs in the next-free range for each section.
4. **User review.** You review proposed rules per cluster: add as-drafted, add with edits, or reject. Approved rules are appended to the relevant STYLE.md sections.

The `style_amend_complete` event is logged with cluster counts. The `schema_version` frontmatter field is unchanged by amend.

## Rule ID convention

Rules use section-prefixed, zero-padded, three-digit IDs:

| Section | Prefix | Example |
|---|---|---|
| Error handling | `EH-` | `EH-001` |
| Tests | `T-` | `T-001` |
| Comments | `C-` | `C-001` |
| Naming | `N-` | `N-001` |
| Project-specific | `P-` | `P-001` |

Rule IDs are **append-only and never reused**. When a rule is retired, it is replaced by a tombstone comment (`<!-- EH-003 retired 2026-06-01 -->`) so that historical `mr-reviewer` citations remain traceable. The `mr-reviewer` agent cites rules by their ID (e.g. `Citation: EH-001`).

## See also

- `docs/human/STYLE-md-schema.md` — full schema reference with a worked Rust example.
- `docs/human/mr-reviewer.md` — the review command that consumes STYLE.md.

 succeeded in 127ms:
{
  "concept": "mr-reviewer",
  "last_updated": "2026-05-23",
  "covers_spec": "z-harness/mr-style-reviewer/SPEC.md",
  "source_files": [
    "commands/z-mr-review.md",
    "agents/mr-reviewer.md",
    "scripts/extract-dismissals.py"
  ],
  "confidence": "high",
  "entry_points": [
    {
      "file": "commands/z-mr-review.md",
      "line": 1,
      "symbol": "z-mr-review",
      "kind": "module",
      "summary": "Orchestrates multi-LLM code-quality review of a branch diff against STYLE.md."
    },
    {
      "file": "agents/mr-reviewer.md",
      "line": 1,
      "symbol": "mr-reviewer",
      "kind": "module",
      "summary": "Sonnet agent that fans out to codex/gemini consultants, deduplicates findings, and returns structured JSON to the orchestrator."
    },
    {
      "file": "scripts/extract-dismissals.py",
      "line": 1,
      "symbol": "extract-dismissals.py",
      "kind": "module",
      "summary": "Computes dismissed-finding signatures by diffing consecutive MR-REVIEW.md archive snapshots."
    }
  ],
  "description": "The MR-reviewer feature provides code-quality review (not correctness review) for branch diffs. It targets five categories: abstraction, defensive-bloat, test-noise, hygiene, and style-drift. Findings are ranked P0-P4 and written to z-harness/<slug>/MR-REVIEW.md in TASKS.md-compatible shape. The command never blocks — users triage by deleting unwanted findings. Three LLM voices (Claude, Codex, Gemini) are fanned out in parallel; findings are deduplicated by (file, category, normalized_text) signature and tagged with which voices raised them. Voice consensus promotes findings one tier; minority voice demotes one tier; P0 is exempt from both adjustments.",
  "invariants": [
    "P0 findings are never demoted — not by voice consensus, not by dismissal-pattern match. Only tagged [previously-dismissed-pattern].",
    "The mr-reviewer agent always receives a single diff_path pointing to one .patch file. Orchestrator handles chunking; agent contract is not polymorphic.",
    "Orchestrator writes MR-REVIEW.md and the archive snapshot, not the agent. Agent returns structured JSON findings only.",
    "STYLE.md must exist before /z-mr-review will run. There is no --no-style escape.",
    "extract-dismissals.py is the single source of truth for dismissal signatures; both /z-mr-review and /z-style-init --amend use the same script.",
    "Dismissal signature format: (file, category, normalized_text) — no line-range. Normalization: lowercase, collapse whitespace, strip punctuation."
  ],
  "gotchas": [
    "Large diffs (> Z_MR_DIFF_CHUNK_BYTES, default 320000 bytes) trigger chunked-pass mode: N per-chunk passes + 1 whole-diff abstraction-only pass. The abstraction-only pass is the only one that can catch cross-file duplication.",
    "Voice availability is checked via `command -v` at setup. If only Claude is available, mr_voices_degraded is logged and the run continues in single-voice mode (no consensus tier-bump possible).",
    "Dismissal rate is computed by /z-stats. If a category's rate exceeds 30% over >= 10 runs, /z-stats emits a retire-warning.",
    "The abstraction tooling uses a hardcoded suppression list of common symbol names (format, parse, init, get, set, new, build, run, main, etc.) to avoid flooding findings with spurious matches.",
    "base_sha is passed to the agent so it can `git show <base_sha>:<path>` to read pre-change file context for interface-adherence verification."
  ],
  "five_categories": [
    "abstraction — duplicated logic, missed extractions, cross-file symbol collisions",
    "defensive-bloat — guards against impossible states, over-long error chains",
    "test-noise — redundant, brittle, or dead test code",
    "hygiene — stale comments, naming oddities, unnecessary logging",
    "style-drift — violations of STYLE.md rules (cited by rule ID)"
  ],
  "severity_rubric": {
    "P0": "Would actively cause future bugs or maintenance pain.",
    "P1": "Clear quality regression vs rest of codebase.",
    "P2": "STYLE.md violation or noticeable idiom drift.",
    "P3": "Minor hygiene.",
    "P4": "Taste-only nit."
  },
  "falsifiability_thresholds": {
    "retire_category": ">30% dismissal rate over >= 10 runs per category",
    "fold_into_audit": ">90% finding parity with /z-audit --dimension=cleanliness"
  },
  "telemetry_events": [
    "mr_run_start",
    "mr_run_end",
    "mr_finding_emitted",
    "mr_finding_dismissed",
    "mr_style_missing",
    "mr_voice_failed",
    "mr_all_voices_failed",
    "mr_voices_degraded"
  ],
  "related_concepts": [
    "style-init",
    "agents",
    "commands",
    "scripts"
  ],
  "depends_on": [
    "agents",
    "scripts"
  ],
  "consumed_by": [
    "commands"
  ],
  "memories": []
}
{
  "concept": "style-init",
  "last_updated": "2026-05-23",
  "covers_spec": "z-harness/mr-style-reviewer/SPEC.md",
  "source_files": [
    "commands/z-style-init.md",
    "scripts/extract-dismissals.py"
  ],
  "confidence": "high",
  "entry_points": [
    {
      "file": "commands/z-style-init.md",
      "line": 1,
      "symbol": "z-style-init",
      "kind": "module",
      "summary": "Bootstrap or amend a project STYLE.md via Capture-first grounding and interactive interview."
    }
  ],
  "description": "z-style-init creates and maintains the project STYLE.md that /z-mr-review requires. Bootstrap mode (no --amend) uses a 'Capture' approach: it identifies the top 5 most idiomatic existing source files (heuristic prefilter → Sonnet ranking → user confirmation gate), reads them, asks up to 4 interview questions about error handling / testing / comments / project specifics, drafts STYLE.md, critiques it via codex+gemini consultants, then asks for user approval before writing. Amend mode (--amend) reads recent archive dismissal patterns via extract-dismissals.py, clusters similar dismissals (Jaccard >= 0.6), proposes new STYLE.md rules per cluster, and lets the user accept/edit/reject each proposed rule.",
  "invariants": [
    "Bootstrap mode refuses if STYLE.md already exists (use --amend).",
    "Amend mode refuses if STYLE.md does not exist.",
    "The Capture user-confirmation gate (step 2.5) is mandatory — it cannot be bypassed. This prevents legacy god-objects from anchoring STYLE.md to bad patterns.",
    "Rule IDs are append-only and never reused. Retired rules get a tombstone comment so historical mr-reviewer citations remain traceable.",
    "Amend clusters require >= 2 members (single-occurrence dismissals are not patterns).",
    "extract-dismissals.py is shared with /z-mr-review — same script, same output schema."
  ],
  "gotchas": [
    "The Capture prefilter excludes files < 50 or > 800 lines and a hardcoded list: node_modules/, vendor/, dist/, target/, *.pb.go, *_pb2.py, migrations/, __generated__/, .min.*, lock files.",
    "Amend uses --global flag on extract-dismissals.py to scan all slugs (not just the current slug), giving a cross-plan dismissal view.",
    "Amend cluster similarity uses Jaccard token-overlap >= 0.6 after dropping stopwords (the, a, an, this, that, is, are, in, on, of, to, for, and, or, with, by).",
    "schema_version frontmatter is not incremented by --amend; it is only bumped on breaking schema changes.",
    "--ingest <path> skips the interview phase entirely and uses the user's existing guide as the sole input."
  ],
  "capture_insight": "STYLE.md rules are grounded in the project's own idiomatic code (top-5 file ranking), making rules accurate and uncontroversial rather than template-imposed.",
  "modes": {
    "bootstrap": "No --amend. Creates STYLE.md from scratch via Capture + interview + codex/gemini critique.",
    "amend": "--amend flag. Adds rules from repeated dismissal pattern clusters to existing STYLE.md."
  },
  "style_md_sections": [
    "## Error handling (EH-NNN)",
    "## Tests (T-NNN)",
    "## Comments (C-NNN)",
    "## Naming (N-NNN)",
    "## Project-specific (P-NNN)"
  ],
  "telemetry_events": [
    "style_init_complete",
    "style_amend_complete"
  ],
  "related_concepts": [
    "mr-reviewer",
    "agents",
    "commands",
    "scripts"
  ],
  "depends_on": [
    "agents",
    "scripts"
  ],
  "consumed_by": [
    "commands",
    "mr-reviewer"
  ],
  "memories": []
}
{
  "version": "1",
  "generated_at": "2026-05-23T19:31:00Z",
  "z_harness_version": "64a3dbe",
  "concepts": [
    {
      "slug": "mr-reviewer",
      "source_file": [
        "commands/z-mr-review.md",
        "agents/mr-reviewer.md",
        "scripts/extract-dismissals.py"
      ],
      "last_updated": "2026-05-23",
      "confidence": "high",
      "depends_on": [
        "agents",
        "scripts",
        "style-init"
      ],
      "consumed_by": [
        "commands"
      ],
      "summary": "Multi-LLM code-quality reviewer for branch diffs; ranks P0-P4, never blocks, writes TASKS.md-shape MR-REVIEW.md."
    },
    {
      "slug": "style-init",
      "source_file": [
        "commands/z-style-init.md",
        "scripts/extract-dismissals.py"
      ],
      "last_updated": "2026-05-23",
      "confidence": "high",
      "depends_on": [
        "agents",
        "scripts"
      ],
      "consumed_by": [
        "commands",
        "mr-reviewer"
      ],
      "summary": "Capture-first STYLE.md bootstrap and amend flow; required before /z-mr-review will run."
    },
    {
      "slug": "agents",
      "source_file": [
        "agents/auditor.md",
        "agents/cluster-planner.md",
        "agents/codex-consultant.md",
        "agents/codex-reviewer.md",
        "agents/complexity-classifier.md",
        "agents/doc-fetcher.md",
        "agents/doc-updater.md",
        "agents/gemini-consultant.md",
        "agents/implementer.md",
        "agents/remote-runner.md",
        "agents/spec-precheck.md"
      ],
      "last_updated": "2026-05-23",
      "confidence": "high",
      "depends_on": [
        "scripts"
      ],
      "consumed_by": [
        "commands",
        "skills"
      ],
      "summary": "Scrutinizes codebase targets across correctness/perf/cleanliness/design."
    },
    {
      "slug": "commands",
      "source_file": [
        "commands/z-amend.md",
        "commands/z-audit.md",
        "commands/z-brainstorm.md",
        "commands/z-debug.md",
        "commands/z-do.md",
        "commands/z-implement-all.md",
        "commands/z-implement-next.md",
        "commands/z-improve.md",
        "commands/z-init-docs.md",
        "commands/z-maintain-docs.md",
        "commands/z-plan-light.md",
        "commands/z-plan-split.md",
        "commands/z-plan.md",
        "commands/z-research.md",
        "commands/z-review-all.md",
        "commands/z-skill-fix.md",
        "commands/z-stats.md",
        "commands/z-suggest-memory.md",
        "commands/z-test.md"
      ],
      "last_updated": "2026-05-23",
      "confidence": "high",
      "depends_on": [
        "agents",
        "scripts"
      ],
      "consumed_by": [
        "skills"
      ],
      "summary": "Propagates targeted plan amendments consistently across plan artifacts."
    },
    {
      "slug": "scripts",
      "source_file": [
        "scripts/log-event.sh",
        "scripts/log-phase.sh",
        "scripts/regenerate-memories-flat.py",
        "scripts/remote-sandbox-sync.sh",
        "scripts/version.sh"
      ],
      "last_updated": "2026-05-23",
      "confidence": "high",
      "depends_on": [],
      "consumed_by": [
        "agents",
        "commands",
        "skills"
      ],
      "summary": "Appends standard JSON events to run and global logs."
    },
    {
      "slug": "skills",
      "source_file": [
        "skills/z-amend/SKILL.md",
        "skills/z-brainstorm/SKILL.md",
        "skills/z-debug/SKILL.md",
        "skills/z-do/SKILL.md",
        "skills/z-implement-all/SKILL.md",
        "skills/z-implement-next/SKILL.md",
        "skills/z-improve/SKILL.md",
        "skills/z-init-docs/SKILL.md",
        "skills/z-maintain-docs/SKILL.md",
        "skills/z-plan-light/SKILL.md",
        "skills/z-plan-split/SKILL.md",
        "skills/z-plan/SKILL.md",
        "skills/z-research/SKILL.md",
        "skills/z-review-all/SKILL.md",
        "skills/z-stats/SKILL.md",
        "skills/z-suggest-memory/SKILL.md",
        "skills/z-test/SKILL.md"
      ],
      "last_updated": "2026-05-23",
      "confidence": "high",
      "depends_on": [
        "agents",
        "commands",
        "scripts"
      ],
      "consumed_by": [],
      "summary": "Checklists for amending spec, plan, and task checklists consistently."
    }
  ]
}

 succeeded in 131ms:
README.md:28:  Typical chain for a murky multi-component problem: `/z-research → /z-brainstorm → /z-plan-split → /z-implement-all`.
README.md:33:- **`/z-implement-all`** — Orchestrates the full TASKS.md queue: one fresh `implementer` subagent per task → per-task `codex-reviewer` safety gate → retry once on review failure → push-notify at every task boundary. Walks a tree-rooted plan produced by `/z-plan-split` (one cluster at a time, in MANIFEST run order) as well as legacy single-slug plans. Flags: `--ack` (override the SHARED-CONCERNS.md ack-gate) and `--force-partial` (proceed against a tree where some clusters failed planning, excluding the failed ones from the run set). Both flags are inert for legacy single-slug plans.
README.md:38:- **`/z-style-init`** — Author the project `STYLE.md` interactively, grounded in the repo's most idiomatic existing files (Capture). Required before `/z-mr-review` will run. Pass `--amend` to add rules derived from repeated review dismissals instead of bootstrapping.
README.md:39:- **`/z-mr-review`** — Multi-LLM code-quality review of the current branch diff against `STYLE.md`. Fans out to Claude, Codex, and Gemini; deduplicates and ranks findings P0–P4; writes `z-harness/<slug>/MR-REVIEW.md` in `TASKS.md`-compatible shape. Never blocks — delete findings you don't want, then run `/z-implement-all --tasks=MR-REVIEW.md`. Targets five categories: abstraction, defensive-bloat, test-noise, hygiene, and style-drift. Distinct from `/z-audit`, which gates correctness.
README.md:43:- **`/z-audit <target>`** — Read-only audit pipeline. Pre-flight scopes (target, dimensions, optional `.claude/audit-rubrics/<component>.md`), spawns one `auditor` subagent per dimension in parallel (correctness / perf / cleanliness / design), bundled Gemini+Codex consult on findings, emits REPORT.md + TASKS.md in `/z-implement-all`-compatible format, codex-reviewer safety gate.
README.md:44:- **`/z-debug <symptom>`** — Investigate a known-bad behavior with explicit repro / hypothesis / evidence / isolation phases; cross-LLM consult at hypothesis and fix stages; auto-bails to `/z-plan` if scope grows; writes a post-mortem. Post-mortem phase optionally invokes `mr-reviewer` on the fix diff; P0/P1 findings are promoted to the post-mortem's preventative-action list automatically.
README.md:63:| `mr-reviewer` | sonnet | Fans out to codex/gemini consultants, deduplicates findings, applies P0-P4 rubric |
README.md:134:- `Z_HARNESS_LOCAL_CARGO_CLEAN` — set to `1` at the start of `/z-implement-all` to trigger a one-time local `cargo clean`.
README.md:158:Event kinds introduced by `/z-plan-split` and the tree-walking branch of `/z-implement-all`:
README.md:174:| `shared_concerns_missing` | `/z-implement-all` Setup 2b when SHARED-CONCERNS.md is absent on a tree-rooted slug |
README.md:175:| `shared_concerns_unacknowledged` | `/z-implement-all` Setup 2b ack-gate (halt; no override) |
README.md:176:| `shared_concerns_ack_override` | `/z-implement-all` Setup 2b ack-gate when `--ack` was supplied |
README.md:177:| `manifest_frontmatter_inconsistent` | `/z-implement-all` Setup 2b when frontmatter counts disagree with the table |
README.md:178:| `manifest_run_order_invalid` | `/z-implement-all` Setup 2b when run order doesn't bijectively match the table |
README.md:179:| `tree_depth_exceeded` | `/z-implement-all` Setup 2b when a nested MANIFEST.md is found inside the tree |
README.md:180:| `partial_tree_blocked` | `/z-implement-all` Setup 2b partial-tree gate (halt; no `--force-partial`) |
README.md:181:| `partial_tree_force_override` | `/z-implement-all` Setup 2b partial-tree gate when `--force-partial` was supplied |
README.md:183:| `cluster_not_ready` | `/z-implement-all` Setup 2b cluster-readiness gate |
README.md:189:- **`/z-plan-split`: no cross-cluster task parallelism.** `/z-implement-all` walks clusters sequentially in MANIFEST run-order; intra-cluster parallelism (N=3) is honored, cross-cluster is v2.
README.md:192:- **`/z-plan-split`: one-level recursion cap.** Cluster-planners refuse to write inside an existing MANIFEST.md tree, and `/z-implement-all` halts with `tree_depth_exceeded` if it finds a nested MANIFEST.md. A tree-of-trees is structurally unsupported.
README.md:208:│   ├── z-implement-all.md
README.md:232:│   ├── extract-dismissals.py
docs/human/style-init.md:8:`/z-style-init` authors a project `STYLE.md` — the style guide that `/z-mr-review` uses to detect rule violations and idiom drift. The command has two modes: **bootstrap** (create a new STYLE.md from scratch) and **amend** (add rules derived from repeated dismissal patterns in past review runs).
docs/human/style-init.md:36:If you pass `--ingest <path>`, the interview is skipped and your existing guide at `<path>` is used as the input instead.
docs/human/style-init.md:42:Approved STYLE.md is written to the repo root. The `style_init_complete` event is logged and a push notification is sent.
docs/human/style-init.md:46:Run `/z-style-init --amend` to add new rules derived from findings you have repeatedly dismissed in past `/z-mr-review` runs. The command refuses if no STYLE.md exists yet.
docs/human/style-init.md:50:1. **Scan archives.** `scripts/extract-dismissals.py` walks `z-harness/*/archive/*/MR-REVIEW.md` snapshots (default: most recent 10 runs, `--global` scans all slugs) to identify dismissed finding signatures.
docs/human/style-init.md:51:2. **Cluster.** Dismissed signatures are grouped by category and text similarity (Jaccard token-overlap ≥ 0.6 after stopword removal). Clusters with fewer than 2 members are discarded — single-occurrence dismissals are not considered patterns.
docs/llm/skills.json:10:    "skills/z-implement-all/SKILL.md",
docs/llm/skills.json:45:      "summary": "Checklists for bug isolation, hypothesis generation, and post-mortems."
docs/llm/skills.json:55:      "file": "skills/z-implement-all/SKILL.md",
docs/llm/skills.json:57:      "symbol": "z-implement-all",
scripts/test_extract_dismissals.py:2:pytest tests for scripts/extract-dismissals.py
scripts/test_extract_dismissals.py:9:          MR-REVIEW.md          (snapshot: findings A, B, C)
scripts/test_extract_dismissals.py:11:          MR-REVIEW.md          (snapshot: findings A, D)
scripts/test_extract_dismissals.py:12:          MR-REVIEW.md.previous-1  (user kept A, deleted B and C)
scripts/test_extract_dismissals.py:14:          MR-REVIEW.md          (snapshot: findings D, E)
scripts/test_extract_dismissals.py:15:          MR-REVIEW.md.previous-1  (user kept D, deleted A)
scripts/test_extract_dismissals.py:17:Expected dismissals:
scripts/test_extract_dismissals.py:18:  run-001 → run-002 pair: B and C dismissed (not in .previous-1 of run-002)
scripts/test_extract_dismissals.py:19:  run-002 → run-003 pair: A dismissed (not in .previous-1 of run-003)
scripts/test_extract_dismissals.py:36:    "extract_dismissals",
scripts/test_extract_dismissals.py:37:    SCRIPTS_DIR / "extract-dismissals.py",
scripts/test_extract_dismissals.py:45:# Helpers to build synthetic MR-REVIEW.md files
scripts/test_extract_dismissals.py:48:def make_mr_review(
scripts/test_extract_dismissals.py:54:    Produce a minimal MR-REVIEW.md string with YAML frontmatter.
scripts/test_extract_dismissals.py:77:    "severity": "P1",
scripts/test_extract_dismissals.py:98:    "severity": "P0",
scripts/test_extract_dismissals.py:157:        snapshot_text = make_mr_review(
scripts/test_extract_dismissals.py:162:        snapshot_path = run_dir / "MR-REVIEW.md"
scripts/test_extract_dismissals.py:167:            prev_text = make_mr_review(
scripts/test_extract_dismissals.py:172:            prev_path = run_dir / "MR-REVIEW.md.previous-1"
scripts/test_extract_dismissals.py:206:        text = make_mr_review([FINDING_A, FINDING_B])
scripts/test_extract_dismissals.py:216:        result = ed.parse_mr_review_frontmatter(p)
scripts/test_extract_dismissals.py:221:        result = ed.parse_mr_review_frontmatter(p)
scripts/test_extract_dismissals.py:228:            {"id": "T-MR-001", "severity": "P1", "category": "hygiene",
scripts/test_extract_dismissals.py:239:            {"id": "T-MR-001", "severity": "P1", "category": "hygiene",
scripts/test_extract_dismissals.py:274:    def test_correct_dismissals_identified(self, archive_root):
scripts/test_extract_dismissals.py:276:        Core invariant: B and C are dismissed in run-001→run-002 pair;
scripts/test_extract_dismissals.py:277:        A is dismissed in run-002→run-003 pair.
scripts/test_extract_dismissals.py:280:        signatures, n_runs = ed.extract_dismissals_from_runs(run_dirs, max_runs=10)
scripts/test_extract_dismissals.py:282:        dismissed_snippets = {s["normalized_snippet"] for s in signatures}
scripts/test_extract_dismissals.py:285:        assert ed.normalize_snippet(FINDING_B["title"]) in dismissed_snippets
scripts/test_extract_dismissals.py:286:        assert ed.normalize_snippet(FINDING_C["title"]) in dismissed_snippets
scripts/test_extract_dismissals.py:289:        assert ed.normalize_snippet(FINDING_A["title"]) in dismissed_snippets
scripts/test_extract_dismissals.py:291:    def test_non_dismissed_not_in_output(self, archive_root):
scripts/test_extract_dismissals.py:294:        E was never dismissed (it's in run-003 snapshot but there's no following run).
scripts/test_extract_dismissals.py:295:        Neither should appear as dismissed.
scripts/test_extract_dismissals.py:298:        signatures, _ = ed.extract_dismissals_from_runs(run_dirs, max_runs=10)
scripts/test_extract_dismissals.py:300:        dismissed_snippets = {s["normalized_snippet"] for s in signatures}
scripts/test_extract_dismissals.py:302:        assert ed.normalize_snippet(FINDING_D["title"]) not in dismissed_snippets
scripts/test_extract_dismissals.py:303:        assert ed.normalize_snippet(FINDING_E["title"]) not in dismissed_snippets
scripts/test_extract_dismissals.py:307:        _, n_runs = ed.extract_dismissals_from_runs(run_dirs, max_runs=10)
scripts/test_extract_dismissals.py:312:        signatures, _ = ed.extract_dismissals_from_runs(run_dirs, max_runs=10)
scripts/test_extract_dismissals.py:320:        signatures, _ = ed.extract_dismissals_from_runs(run_dirs, max_runs=10)
scripts/test_extract_dismissals.py:328:        signatures, n_runs = ed.extract_dismissals_from_runs(run_dirs, max_runs=2)
scripts/test_extract_dismissals.py:331:        dismissed_snippets = {s["normalized_snippet"] for s in signatures}
scripts/test_extract_dismissals.py:333:        # Only A is dismissed in run-002→run-003 pair
scripts/test_extract_dismissals.py:334:        assert ed.normalize_snippet(FINDING_A["title"]) in dismissed_snippets
scripts/test_extract_dismissals.py:337:        assert ed.normalize_snippet(FINDING_B["title"]) not in dismissed_snippets
scripts/test_extract_dismissals.py:338:        assert ed.normalize_snippet(FINDING_C["title"]) not in dismissed_snippets
scripts/test_extract_dismissals.py:345:        sigs, n_runs = ed.extract_dismissals_from_runs(run_dirs, max_runs=10)
scripts/test_extract_dismissals.py:354:        sigs, n_runs = ed.extract_dismissals_from_runs(run_dirs, max_runs=10)
scripts/test_extract_dismissals.py:369:        script = SCRIPTS_DIR / "extract-dismissals.py"
scripts/test_extract_dismissals.py:397:        script = SCRIPTS_DIR / "extract-dismissals.py"
scripts/test_extract_dismissals.py:408:    def test_global_flag(self, archive_root, tmp_path):
scripts/test_extract_dismissals.py:409:        """--global scans all slugs under z-harness/ from repo root."""
scripts/test_extract_dismissals.py:413:        # repo root for --global is tmp_path (contains z-harness/)
scripts/test_extract_dismissals.py:414:        script = SCRIPTS_DIR / "extract-dismissals.py"
scripts/test_extract_dismissals.py:416:            [sys.executable, str(script), "--global"],
scripts/test_extract_dismissals.py:436:            {"id": "T-MR-001", "severity": "P1", "category": "hygiene",
scripts/test_extract_dismissals.py:442:    def test_t_mr_nnn_id_not_used_as_snippet(self):
scripts/test_extract_dismissals.py:445:        They are re-numbered each run and would produce spurious dismissals.
scripts/test_extract_dismissals.py:460:            {"id": "T-MR-001", "severity": "P1", "category": "hygiene",
scripts/test_extract_dismissals.py:470:            {"id": "T-MR-001", "severity": "P1", "category": "hygiene",
scripts/test_extract_dismissals.py:488:        Create a run dir named "<timestamp>-mr-review" with an MR-REVIEW.md snapshot.
scripts/test_extract_dismissals.py:494:        content = make_mr_review([finding])
scripts/test_extract_dismissals.py:495:        (run_dir / "MR-REVIEW.md").write_text(content, encoding="utf-8")
scripts/test_extract_dismissals.py:520:    def test_iso_prefix_dismissal_order_correct(self, tmp_path):
scripts/test_extract_dismissals.py:522:        End-to-end: with ISO-named runs whose mtimes are reversed, the dismissal
scripts/test_extract_dismissals.py:523:        algorithm must still identify findings dismissed in the chronologically
scripts/test_extract_dismissals.py:535:        (run1_dir / "MR-REVIEW.md").write_text(
scripts/test_extract_dismissals.py:536:            make_mr_review([FINDING_A, FINDING_B]), encoding="utf-8"
scripts/test_extract_dismissals.py:543:        (run2_dir / "MR-REVIEW.md").write_text(
scripts/test_extract_dismissals.py:544:            make_mr_review([FINDING_A]), encoding="utf-8"
scripts/test_extract_dismissals.py:546:        (run2_dir / "MR-REVIEW.md.previous-1").write_text(
scripts/test_extract_dismissals.py:547:            make_mr_review([FINDING_A]), encoding="utf-8"
scripts/test_extract_dismissals.py:552:        sigs, _ = ed.extract_dismissals_from_runs(run_dirs, max_runs=10)
scripts/test_extract_dismissals.py:554:        dismissed = {s["normalized_snippet"] for s in sigs}
scripts/test_extract_dismissals.py:555:        assert ed.normalize_snippet(FINDING_B["title"]) in dismissed, (
scripts/test_extract_dismissals.py:556:            "B must be dismissed (dropped by user between run1 and run2)"
scripts/test_extract_dismissals.py:558:        assert ed.normalize_snippet(FINDING_A["title"]) not in dismissed, (
scripts/test_extract_dismissals.py:559:            "A must NOT be dismissed (user kept it)"
scripts/test_extract_dismissals.py:564:# Fix #3 — --global mode: pairwise per-slug, not interleaved
scripts/test_extract_dismissals.py:586:            (run_dir / "MR-REVIEW.md").write_text(
scripts/test_extract_dismissals.py:587:                make_mr_review(run["snapshot_findings"], slug=slug, run_id=run["name"]),
scripts/test_extract_dismissals.py:591:                (run_dir / "MR-REVIEW.md.previous-1").write_text(
scripts/test_extract_dismissals.py:592:                    make_mr_review(run["previous_findings"], slug=slug, run_id=f"{run['name']}-prev"),
scripts/test_extract_dismissals.py:600:    def test_global_pairwise_per_slug(self, tmp_path):
scripts/test_extract_dismissals.py:628:        slug_runs = ed.collect_slug_run_dirs_global(tmp_path)
scripts/test_extract_dismissals.py:632:            sigs, n = ed.extract_dismissals_from_runs(run_dirs, max_runs=10)
scripts/test_extract_dismissals.py:636:        dismissed = {s["normalized_snippet"] for s in all_sigs}
scripts/test_extract_dismissals.py:638:        # B dismissed in slug-alpha; D dismissed in slug-beta
scripts/test_extract_dismissals.py:639:        assert ed.normalize_snippet(FINDING_B["title"]) in dismissed
scripts/test_extract_dismissals.py:640:        assert ed.normalize_snippet(FINDING_D["title"]) in dismissed
scripts/test_extract_dismissals.py:642:        # A and C were kept, not dismissed
scripts/test_extract_dismissals.py:643:        assert ed.normalize_snippet(FINDING_A["title"]) not in dismissed
scripts/test_extract_dismissals.py:644:        assert ed.normalize_snippet(FINDING_C["title"]) not in dismissed
scripts/test_extract_dismissals.py:649:    def test_global_cli_pairwise_per_slug(self, tmp_path):
scripts/test_extract_dismissals.py:651:        CLI --global must not interleave: dismissal signatures from each slug
scripts/test_extract_dismissals.py:658:        # slug-alpha: B dismissed
scripts/test_extract_dismissals.py:667:        # slug-beta: D dismissed
scripts/test_extract_dismissals.py:677:        script = SCRIPTS_DIR / "extract-dismissals.py"
scripts/test_extract_dismissals.py:679:            [sys.executable, str(script), "--global"],
scripts/test_extract_dismissals.py:687:        dismissed_snippets = {s["normalized_snippet"] for s in data["signatures"]}
scripts/test_extract_dismissals.py:688:        assert ed.normalize_snippet(FINDING_B["title"]) in dismissed_snippets
scripts/test_extract_dismissals.py:689:        assert ed.normalize_snippet(FINDING_D["title"]) in dismissed_snippets
scripts/test_extract_dismissals.py:730:        End-to-end: an MR-REVIEW.md whose findings_index has a title with a
scripts/test_extract_dismissals.py:735:            '  - {id: T-MR-001, severity: P1, category: hygiene, '
commands/z-plan-split.md:324:If `partial_tree: true`, set `partial_tree: true` in the frontmatter. This is consumed by `/z-implement-all`'s partial-tree gate (refuses without `--force-partial`).
commands/z-plan-split.md:382:Clusters execute sequentially in this order under `/z-implement-all`. Cross-cluster task parallelism is v2.
commands/z-plan-split.md:388:See SHARED-CONCERNS.md for detected file-overlap observations (count: <N>). Ack-gate enforced by `/z-implement-all`.
commands/z-plan-split.md:417:     (or pass --ack to /z-implement-all).
commands/z-plan-split.md:418:  2. /z-implement-all   — walks the tree in MANIFEST run-order.
commands/z-plan-split.md:421:For the partial-tree branch, the push notification also names the failed clusters and reminds the user that `/z-implement-all` will refuse without `--force-partial` until the failures are addressed (drop the cluster, re-plan it, or override the gate).
commands/z-plan-split.md:433:- **Ack-gate is mandatory.** `/z-implement-all` refuses to walk a tree with `acknowledged: false` (unless `overlap_count: 0` auto-acks).
docs/human/INDEX.md:25:| [scripts](./scripts.md) | high | `scripts/log-event.sh`, `scripts/log-phase.sh`, `scripts/regenerate-memories-flat.py` | Appends standard JSON events to run and global logs. |
docs/llm/INDEX.json:11:        "scripts/extract-dismissals.py"
docs/llm/INDEX.json:23:      "summary": "Multi-LLM code-quality reviewer for branch diffs; ranks P0-P4, never blocks, writes TASKS.md-shape MR-REVIEW.md."
docs/llm/INDEX.json:29:        "scripts/extract-dismissals.py"
docs/llm/INDEX.json:77:        "commands/z-implement-all.md",
docs/llm/INDEX.json:120:      "summary": "Appends standard JSON events to run and global logs."
docs/llm/INDEX.json:129:        "skills/z-implement-all/SKILL.md",
agents/implementer.md:3:description: Implements a single task from z-harness/TASKS.md in a fresh context. Invoked by /z-implement-all once per task to keep main orchestrator context lean. Reads only the slice of SPEC.md/PLAN.md it needs, edits files, returns a structured summary.
docs/llm/scripts.json:6:    "scripts/extract-dismissals.py",
docs/llm/scripts.json:16:      "file": "scripts/extract-dismissals.py",
docs/llm/scripts.json:18:      "symbol": "extract-dismissals.py",
docs/llm/scripts.json:20:      "summary": "Computes dismissed finding signatures from consecutive MR-REVIEW.md archive snapshots; shared by /z-mr-review and /z-style-init --amend."
docs/llm/scripts.json:27:      "summary": "Appends standard JSON events to run and global logs."
commands/z-review-all.md:2:description: Final-gate cross-LLM review of a completed z-harness plan. Runs Gemini + Codex on the cumulative diff against SPEC.md to surface (a) implementation drift across tasks and (b) spec gaps that only surface in aggregate. Use after /z-implement-all completes.
commands/z-review-all.md:6:You are running the **z-harness `/z-review-all`** final-gate review. This is a holistic cross-task cross-LLM review, intentionally distinct from the per-task review that `/z-implement-all` already performs. Per-task review catches per-task issues; this catches issues that only show up when looking at all tasks together.
commands/z-review-all.md:10:Same logic as `/z-implement-all` / `/z-implement-next`:
commands/z-review-all.md:64:If `cumulative.diff` exceeds ~500k lines, warn the user — the LLMs will be unable to ingest it; you may need to chunk by directory or by phase.
commands/z-review-all.md:68:If `$BASE/TESTS.md` was produced by `/z-test` and `$BASE/test-runner.json` was populated by `/z-implement-all`, run the full test suite for modules touched by `cumulative.diff` before spawning the consultants. Reasoning: per-task acceptance checks only ran each test in isolation; running the suite together catches inter-test ordering bugs and shared-state regressions that the per-task gate misses.
commands/z-review-all.md:182:- **Open drift fixup tasks** → append new tasks (e.g. `T100-fixup-drift`) to `$BASE/TASKS.md`, mark them `[ ]`. User can then run `/z-implement-all` again.
scripts/log-phase.sh:5:# `*_start` and `*_end` event kinds the z-implement-all spec mandates,
docs/human/skills.md:4:> Covers source: skills/z-amend/SKILL.md, skills/z-brainstorm/SKILL.md, skills/z-debug/SKILL.md, skills/z-do/SKILL.md, skills/z-implement-all/SKILL.md, skills/z-implement-next/SKILL.md, skills/z-improve/SKILL.md, skills/z-init-docs/SKILL.md, skills/z-maintain-docs/SKILL.md, skills/z-plan-light/SKILL.md, skills/z-plan-split/SKILL.md, skills/z-plan/SKILL.md, skills/z-research/SKILL.md, skills/z-review-all/SKILL.md, skills/z-stats/SKILL.md, skills/z-suggest-memory/SKILL.md, skills/z-test/SKILL.md
docs/human/skills.md:14:- `skills/z-debug/SKILL.md:1` — `z-debug` — Method for regression isolation, hypothesis building, and post-mortems.
docs/human/skills.md:16:- `skills/z-implement-all/SKILL.md:1` — `z-implement-all` — Checklist workflow for implementing all tasks via subagents and codex peer review.
docs/llm/commands.json:13:    "commands/z-implement-all.md",
docs/llm/commands.json:35:      "summary": "Orchestrates multi-LLM code-quality review of a branch diff; writes P0-P4 findings to MR-REVIEW.md."
docs/llm/commands.json:80:      "file": "commands/z-implement-all.md",
docs/llm/commands.json:82:      "symbol": "z-implement-all",
docs/llm/agents.json:26:      "summary": "Fans out to codex/gemini consultants, deduplicates findings by (file, category, normalized_text), applies consensus tier-bumps and dismissal-pattern matches, returns structured findings JSON to orchestrator."
docs/llm/style-init.json:7:    "scripts/extract-dismissals.py"
docs/llm/style-init.json:19:  "description": "z-style-init creates and maintains the project STYLE.md that /z-mr-review requires. Bootstrap mode (no --amend) uses a 'Capture' approach: it identifies the top 5 most idiomatic existing source files (heuristic prefilter → Sonnet ranking → user confirmation gate), reads them, asks up to 4 interview questions about error handling / testing / comments / project specifics, drafts STYLE.md, critiques it via codex+gemini consultants, then asks for user approval before writing. Amend mode (--amend) reads recent archive dismissal patterns via extract-dismissals.py, clusters similar dismissals (Jaccard >= 0.6), proposes new STYLE.md rules per cluster, and lets the user accept/edit/reject each proposed rule.",
docs/llm/style-init.json:25:    "Amend clusters require >= 2 members (single-occurrence dismissals are not patterns).",
docs/llm/style-init.json:26:    "extract-dismissals.py is shared with /z-mr-review — same script, same output schema."
docs/llm/style-init.json:30:    "Amend uses --global flag on extract-dismissals.py to scan all slugs (not just the current slug), giving a cross-plan dismissal view.",
docs/llm/style-init.json:31:    "Amend cluster similarity uses Jaccard token-overlap >= 0.6 after dropping stopwords (the, a, an, this, that, is, are, in, on, of, to, for, and, or, with, by).",
docs/llm/style-init.json:33:    "--ingest <path> skips the interview phase entirely and uses the user's existing guide as the sole input."
docs/llm/style-init.json:38:    "amend": "--amend flag. Adds rules from repeated dismissal pattern clusters to existing STYLE.md."
docs/llm/style-init.json:48:    "style_init_complete",
scripts/version.sh:7:# Used by /z-plan, /z-implement-all, /z-implement-next, /z-review-all at
docs/human/mr-reviewer.md:4:> Covers source: commands/z-mr-review.md, agents/mr-reviewer.md, scripts/extract-dismissals.py
docs/human/mr-reviewer.md:10:The review fans out to all available LLM voices (Claude Sonnet inline, Codex via `codex-consultant`, Gemini via `gemini-consultant`). Findings are deduplicated, tagged by which voices raised them, ranked P0–P4, and written to `z-harness/<slug>/MR-REVIEW.md` in `TASKS.md`-compatible shape. The command **never blocks** — you triage by deleting unwanted findings from MR-REVIEW.md, then run `/z-implement-all --tasks=MR-REVIEW.md` on survivors.
docs/human/mr-reviewer.md:16:- As an optional post-mortem step in `/z-debug`: the debug command can invoke `mr-reviewer` on the fix diff and automatically promote P0/P1 findings to the post-mortem's preventative-action list.
docs/human/mr-reviewer.md:30:## P0–P4 severity rubric
docs/human/mr-reviewer.md:34:| **P0** | Would actively cause future bugs or maintenance pain (e.g. silent except-pass, abstraction collapse). Findings at this tier are never demoted — not by low voice consensus, not by a dismissal match. |
docs/human/mr-reviewer.md:35:| **P1** | Clear quality regression vs the rest of the codebase (defensive bloat against impossible state, dead AI-generated scaffolding, significant missed extraction). |
docs/human/mr-reviewer.md:40:P0–P2 are worth acting on. P3–P4 are informational. Delete freely.
docs/human/mr-reviewer.md:42:## Multi-voice consensus and dismissal adjustment
docs/human/mr-reviewer.md:44:Findings raised by all available voices are promoted one tier (P3 → P2, etc.). Findings raised by only one voice are demoted one tier (P3 → P4, etc.). P0 is exempt from both adjustments — it stays at P0 regardless of consensus.
docs/human/mr-reviewer.md:46:Findings whose text signature matches a prior-run dismissal pattern get tagged `[previously-dismissed-pattern]` and are demoted one tier (P1 → P2, etc.). P0 findings that match a dismissal pattern are tagged but **not demoted**.
docs/human/mr-reviewer.md:50:When the diff exceeds `Z_MR_DIFF_CHUNK_BYTES` (default 320 000 bytes, roughly 80K tokens), the orchestrator splits the diff per file and dispatches the `mr-reviewer` agent once per chunk. A final whole-diff abstraction-only pass catches cross-file duplication that per-chunk passes cannot see. The `--deep` flag upgrades that abstraction pass to Opus.
docs/human/mr-reviewer.md:54:Every run archives a snapshot of MR-REVIEW.md at `z-harness/<slug>/archive/<run-id>/MR-REVIEW.md`. The `scripts/extract-dismissals.py` utility compares consecutive run snapshots to identify findings the user deleted. When ≥ 3 findings in a run match prior dismissal patterns, the command suggests `/z-style-init --amend` to codify the pattern into STYLE.md so future reviews don't raise it again.
docs/human/mr-reviewer.md:60:- **Retire the category:** if a category's dismissal rate exceeds **30% over ≥ 10 runs**, the category is generating noise. Run `/z-stats` — it surfaces per-category dismissal rates and emits a warning when this threshold is crossed. Consider removing that category from active review or tightening its criteria.
docs/human/mr-reviewer.md:67:| `mr_run_start` | Command setup complete, diff computed |
docs/human/mr-reviewer.md:68:| `mr_run_end` | All findings written to MR-REVIEW.md |
docs/human/mr-reviewer.md:69:| `mr_finding_emitted` | Once per finding (fields: severity, category, voices_count, dismissal_match) |
docs/human/mr-reviewer.md:70:| `mr_finding_dismissed` | Once per dismissed signature on each subsequent run |
docs/human/mr-reviewer.md:71:| `mr_style_missing` | Command refused: no STYLE.md found |
docs/human/mr-reviewer.md:72:| `mr_voice_failed` | A consultant voice returned malformed JSON |
docs/human/mr-reviewer.md:73:| `mr_all_voices_failed` | All voices failed; command exits nonzero |
docs/human/mr-reviewer.md:74:| `mr_voices_degraded` | Only Claude is available; single-voice mode |
docs/human/mr-reviewer.md:76:## Integration: `/z-debug` post-mortem hook
docs/human/mr-reviewer.md:78:After committing a fix, `/z-debug`'s post-mortem phase offers (via `AskUserQuestion`) to run `/z-mr-review` on the fix diff. If accepted, the `mr-reviewer` agent runs with the debug run's slug. P0 and P1 findings are automatically appended to the post-mortem's "Preventative actions" section as bullet items, cited by `T-MR-NNN` ID. P2–P4 findings stay in MR-REVIEW.md only. See `commands/z-debug.md` for the integration details.
docs/human/scripts.md:12:- `scripts/log-event.sh:1` — `log-event.sh` — Bash script to append standard JSON events to run and global logs.
commands/z-implement-next.md:43:**Discover relevant_docs.** If `docs/llm/INDEX.json` exists, identify concept docs relevant to this task (same logic as `/z-implement-all` step 4b): (a) `**DOCS:** <slug>` lines in task block; (b) `source_file` overlap with the task's `Files:`. Cap at 5 concept paths. Pass as `relevant_docs` below.
commands/z-implement-next.md:67:`/z-implement-next` is a single-shot command and does not auto-retry on Codex review failure. If you want a retry with `model="opus"` (the "always-Opus-on-retry" policy from `/z-implement-all`), re-invoke `/z-implement-next` after manually flipping the task's stamp to `**Complexity:** high`, or run `/z-implement-all` which handles the retry loop internally.
docs/llm/mr-reviewer.json:8:    "scripts/extract-dismissals.py"
docs/llm/mr-reviewer.json:27:      "file": "scripts/extract-dismissals.py",
docs/llm/mr-reviewer.json:29:      "symbol": "extract-dismissals.py",
docs/llm/mr-reviewer.json:31:      "summary": "Computes dismissed-finding signatures by diffing consecutive MR-REVIEW.md archive snapshots."
docs/llm/mr-reviewer.json:34:  "description": "The MR-reviewer feature provides code-quality review (not correctness review) for branch diffs. It targets five categories: abstraction, defensive-bloat, test-noise, hygiene, and style-drift. Findings are ranked P0-P4 and written to z-harness/<slug>/MR-REVIEW.md in TASKS.md-compatible shape. The command never blocks — users triage by deleting unwanted findings. Three LLM voices (Claude, Codex, Gemini) are fanned out in parallel; findings are deduplicated by (file, category, normalized_text) signature and tagged with which voices raised them. Voice consensus promotes findings one tier; minority voice demotes one tier; P0 is exempt from both adjustments.",
docs/llm/mr-reviewer.json:36:    "P0 findings are never demoted — not by voice consensus, not by dismissal-pattern match. Only tagged [previously-dismissed-pattern].",
docs/llm/mr-reviewer.json:38:    "Orchestrator writes MR-REVIEW.md and the archive snapshot, not the agent. Agent returns structured JSON findings only.",
docs/llm/mr-reviewer.json:40:    "extract-dismissals.py is the single source of truth for dismissal signatures; both /z-mr-review and /z-style-init --amend use the same script.",
docs/llm/mr-reviewer.json:44:    "Large diffs (> Z_MR_DIFF_CHUNK_BYTES, default 320000 bytes) trigger chunked-pass mode: N per-chunk passes + 1 whole-diff abstraction-only pass. The abstraction-only pass is the only one that can catch cross-file duplication.",
docs/llm/mr-reviewer.json:45:    "Voice availability is checked via `command -v` at setup. If only Claude is available, mr_voices_degraded is logged and the run continues in single-voice mode (no consensus tier-bump possible).",
docs/llm/mr-reviewer.json:58:    "P0": "Would actively cause future bugs or maintenance pain.",
docs/llm/mr-reviewer.json:59:    "P1": "Clear quality regression vs rest of codebase.",
docs/llm/mr-reviewer.json:65:    "retire_category": ">30% dismissal rate over >= 10 runs per category",
docs/llm/mr-reviewer.json:69:    "mr_run_start",
docs/llm/mr-reviewer.json:70:    "mr_run_end",
docs/llm/mr-reviewer.json:71:    "mr_finding_emitted",
docs/llm/mr-reviewer.json:72:    "mr_finding_dismissed",
docs/llm/mr-reviewer.json:73:    "mr_style_missing",
docs/llm/mr-reviewer.json:74:    "mr_voice_failed",
docs/llm/mr-reviewer.json:75:    "mr_all_voices_failed",
docs/llm/mr-reviewer.json:76:    "mr_voices_degraded"
agents/mr-reviewer.md:3:description: Multi-LLM code-quality reviewer for branch diffs. Assumes correctness; targets AI-shaped and human-shaped slop. Ranks P0-P4, never blocks, never finds correctness bugs (those belong to codex-reviewer).
agents/mr-reviewer.md:8:You review a branch diff for code quality — not correctness. You assume the code is correct and does what the author intended. Your job is to catch AI-shaped slop, defensive bloat, test noise, abstraction failures, and style drift. You rank findings P0–P4 and return them as a fenced JSON block plus a `## Summary` markdown block. You never write MR-REVIEW.md yourself — the orchestrator does that from your return.
agents/mr-reviewer.md:13:- **Every added line must justify its weight.** Relative to the existing abstractions, local style, and the behavioral surface it supports, gratuitous diff growth is suspect; necessary growth is not. When in doubt, P4 — not P0.
agents/mr-reviewer.md:18:- **P0** — would actively cause future bugs or maintenance pain (e.g. silent `except`/`_ =` over a real failure mode, abstraction collapse that destroys a key invariant).
agents/mr-reviewer.md:19:- **P1** — clear quality regression vs the rest of the codebase (defensive bloat against impossible state, dead AI-generated comment scaffolding, missed-extraction of significant duplication — ≥10 lines of near-identical logic).
agents/mr-reviewer.md:22:- **P4** — taste-only, debatable, purely optional. Leave it; don't invest a P1 slot on it.
agents/mr-reviewer.md:44:dismissed_signatures_path: <abs path to dismissed_signatures.json>
agents/mr-reviewer.md:70:3. `dismissed_signatures.json` at `dismissed_signatures_path`. Schema: `{"signatures": [{"file": "...", "category": "...", "normalized_snippet": "...", "prior_run_id": "..."}, ...], "n_runs_scanned": N}`. If the file is missing or its `signatures` array is empty, proceed as if no dismissed signatures exist.
agents/mr-reviewer.md:149:- `severity`: P1 if the existing definition is substantially similar (same parameter shape, same return type, same semantic purpose); P2 if similar in name only and possibly coincidental.
agents/mr-reviewer.md:165:- `is_meaningful_duplication: true` → keep the finding (promote to P1 if it was P2).
agents/mr-reviewer.md:208:{\"findings\": [{\"severity\": \"P0|P1|P2|P3|P4\", \"category\": \"<one of: defensive-bloat|test-noise|abstraction|hygiene|style-drift>\", \"file\": \"<relative path from repo root>\", \"line_start\": <integer or null>, \"line_end\": <integer or null>, \"title\": \"<short one-line title>\", \"detail\": \"<prose explanation — what is wrong and why it matters>\", \"citation\": \"<STYLE.md:EH-001 or file:line for abstraction, or null>\"}]}
agents/mr-reviewer.md:220:**Parse failure handling:** for each voice's return, attempt to extract the fenced `json` block (look for a code fence tagged `json` containing a `findings` key). If the parse fails for any reason, log `mr_voice_failed {voice: "<name>", reason: "malformed_json"}` via:
agents/mr-reviewer.md:223:bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$run_id" mr_voice_failed \
agents/mr-reviewer.md:233:### Step 5 — Merge findings and apply dismissal-pattern matching
agents/mr-reviewer.md:240:- If `len(voices_succeeded) >= 2` AND `len(finding.voices) == len(voices_succeeded)`: **promote one tier** (P4→P3, P3→P2, P2→P1, P1→P0; **P0 stays P0**).
agents/mr-reviewer.md:241:- If `len(voices_succeeded) >= 2` AND `len(finding.voices) == 1`: **demote one tier** (P1→P2, P2→P3, P3→P4, P4 stays P4; **P0 stays P0 — never demote P0**).
agents/mr-reviewer.md:244:**Dismissal-pattern match:** for each finding, compute a normalized snippet = lowercase of `title`, whitespace collapsed, leading/trailing punctuation stripped. Compare to each `normalized_snippet` in `dismissed_signatures.json` using Jaccard token-overlap after removing stopwords (`the, a, an, this, that, is, are, in, on, of, to, for, and, or, with, by`). This is a **boolean per finding**: if ANY dismissed signature in the file has a matching `file`, matching `category`, AND Jaccard ≥ 0.6, stop checking further signatures for this finding (early exit on first match) and apply the tag + demotion exactly once:
agents/mr-reviewer.md:245:- Append `[previously-dismissed-pattern]` to the `detail` field.
agents/mr-reviewer.md:246:- If severity is P1–P4: demote one tier (P1→P2, P2→P3, P3→P4, P4 stays P4).
agents/mr-reviewer.md:247:- If severity is P0: keep severity as P0; tag only. **Never demote a P0.**
agents/mr-reviewer.md:249:**Jaccard computation steps:**
agents/mr-reviewer.md:253:4. Otherwise: Jaccard = `|intersection| / |union|` of the two token sets (set semantics — duplicate tokens in one string don't inflate the score).
agents/mr-reviewer.md:254:5. If Jaccard ≥ 0.6, it is a match.
agents/mr-reviewer.md:256:Increment `dismissal_pattern_matches` by 1 for each finding that matches (used in the Summary block count). A finding that matches multiple dismissed signatures still increments by exactly 1.
agents/mr-reviewer.md:260:Return your findings as a fenced JSON block, then a `## Summary` markdown block. The orchestrator parses the JSON block to build MR-REVIEW.md; the Summary block is surfaced to the user directly.
agents/mr-reviewer.md:268:      "severity": "P0|P1|P2|P3|P4",
agents/mr-reviewer.md:285:- `severity` must be exactly `P0`, `P1`, `P2`, `P3`, or `P4`. No other values.
agents/mr-reviewer.md:299:by_severity: P0=N P1=N P2=N P3=N P4=N
agents/mr-reviewer.md:303:dismissal_pattern_matches: N
agents/mr-reviewer.md:306:The counts must be accurate. `voices_succeeded` lists all voices that returned parseable JSON findings (always includes `claude`). `voices_failed` lists any voices that returned malformed JSON. `dismissal_pattern_matches` is the count of findings that matched a dismissed signature via Jaccard ≥ 0.6.
agents/mr-reviewer.md:313:- Adds a `try/except Exception: pass` block (should trigger defensive-bloat P0).
agents/mr-reviewer.md:315:- Adds a function `def format_price(x): return f"${x:.2f}"` where an identical function already exists in the codebase (should trigger abstraction P1 with file:line citation).
agents/mr-reviewer.md:319:**`dismissed_signatures_path`** — `{"signatures": [], "n_runs_scanned": 0}` (empty, no prior dismissals).
agents/mr-reviewer.md:325:- All findings have `severity` matching `P0|P1|P2|P3|P4`, `category` from the five names, `file` as a relative path, and `citation` that is either null or a `STYLE.md:XX-NNN` / `file:line` string.
agents/mr-reviewer.md:332:- Does not write MR-REVIEW.md. The orchestrator does.
agents/mr-reviewer.md:334:- Does not emit telemetry events except `mr_voice_failed` for malformed external voice JSON. The orchestrator handles all other telemetry.
agents/spec-precheck.md:3:description: Pre-flight sanity check that runs BEFORE the implementer for each task in /z-implement-all. Verifies SPEC.md references (symbols, table names, column names, config keys, file paths) actually exist in the codebase as described — so spec drift is caught before any code is written. Returns STATUS: ok or STATUS: spec_problem with the specific stale reference.
agents/remote-runner.md:87:Also: at the START of a fresh `/z-implement-all` invocation (caller-signaled via env var `Z_HARNESS_LOCAL_CARGO_CLEAN=1`), run a one-time `cargo clean` on the LOCAL checkout. This is the only local cargo work this agent does.
docs/human/STYLE-md-schema.md:14:source: capture | interview | ingest | natural-language | amend
docs/human/STYLE-md-schema.md:25:| `source` | enum | How the file was authored. One of: `capture` (derived from idiomatic repo files), `interview` (answers to interactive questions), `ingest` (read from a user-supplied existing guide), `natural-language` (free-text input), `amend` (added rules from dismissal patterns via `--amend`). A single STYLE.md may combine sources; use the primary one here. |
docs/human/STYLE-md-schema.md:26:| `source_files` | list of strings | Relative paths to the files that the Capture phase read (top-5 idiomatic files). Empty list if source is `ingest` or `natural-language`. |
docs/human/STYLE-md-schema.md:185:Route handlers that need rate limiting must apply `RateLimiter::new(...)` from the shared middleware, not roll their own in-handler counter logic. Custom counters in handlers are P0 findings.
docs/human/STYLE-md-schema.md:189:Adding a new `router.route(...)` entry without a corresponding OpenAPI path entry is a P1 finding. The `openapi.yaml` is the contract with downstream consumers.
docs/human/commands.md:4:> Covers source: commands/z-amend.md, commands/z-audit.md, commands/z-brainstorm.md, commands/z-debug.md, commands/z-do.md, commands/z-implement-all.md, commands/z-implement-next.md, commands/z-improve.md, commands/z-init-docs.md, commands/z-maintain-docs.md, commands/z-plan-light.md, commands/z-plan-split.md, commands/z-plan.md, commands/z-research.md, commands/z-review-all.md, commands/z-skill-fix.md, commands/z-stats.md, commands/z-suggest-memory.md, commands/z-test.md
docs/human/commands.md:17:- `commands/z-implement-all.md:1` — `z-implement-all` — Automates task implementation with parallel agents and peer reviews.
commands/z-style-init.md:3:argument-hint: [--amend] [--ingest <path-to-existing-guide>]
commands/z-style-init.md:17:- `--ingest <path>` → capture the path as `INGEST_PATH`; interview phase will be skipped and this file read instead.
commands/z-style-init.md:31:   > `STYLE.md` already exists. Pass `--amend` to add rules from recent dismissals (pending T011), or delete `STYLE.md` manually to start over.
commands/z-style-init.md:51:   v["ingest_path"] = sys.argv[2]
commands/z-style-init.md:54:   bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" style_init_start "$START_PAYLOAD"
commands/z-style-init.md:117:> No candidate files found after filtering (gitignored + exclusion list + size band 50-800 lines). The repo may be too small or entirely generated. STYLE.md cannot be bootstrapped without idiomatic examples. You may pass `--ingest <path>` to supply an existing guide instead.
commands/z-style-init.md:174:- **abandon** → exit cleanly. Log `style_init_abandoned` event.
commands/z-style-init.md:184:**If `--ingest <path>` was specified:**
commands/z-style-init.md:186:Read the file at `INGEST_PATH` into context as `EXISTING_GUIDE`. Skip the interview questions below. Set `SOURCE = ingest`. Proceed to Phase 3.
commands/z-style-init.md:188:**Otherwise (no `--ingest`), ask up to 4 questions via `AskUserQuestion`:**
commands/z-style-init.md:222:  source_files: [<FINAL_5 paths, or empty list if ingest>]
commands/z-style-init.md:247:<INTERVIEW_ANSWERS or 'No interview answers — derived from ingest guide below' + EXISTING_GUIDE>
commands/z-style-init.md:320:Source files used: <FINAL_5 paths, or 'ingest: <path>'>
commands/z-style-init.md:337:- **abandon** → exit cleanly. Log `style_init_abandoned` event.
commands/z-style-init.md:345:Log `style_init_complete`:
commands/z-style-init.md:348:bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" style_init_complete \
commands/z-style-init.md:391:   If the branch is empty/detached or `SLUG_DIR` does not exist as a directory, use the first available `z-harness/*/` directory (via `ls -d z-harness/*/`). If no `z-harness/*/` directory exists at all, `SLUG_DIR` can be any valid path string — the `--global` flag causes `extract-dismissals.py` to scan all slugs, so a missing slug-dir simply yields an empty result set.
commands/z-style-init.md:397:### Phase MB-1 — Scan dismissal archives
commands/z-style-init.md:399:**Goal:** extract normalized finding snippets that users have repeatedly dismissed in past MR-REVIEW runs.
commands/z-style-init.md:405:python3 scripts/extract-dismissals.py "${SLUG_DIR}" --max-runs 10 --global
commands/z-style-init.md:409:> Could not extract dismissal signatures (extract-dismissals.py failed). Check that `scripts/extract-dismissals.py` exists and the z-harness archive structure is intact.
commands/z-style-init.md:413:**Empty-dismissals early exit:** If `N_SIGNATURES == 0` (the signatures array is empty or absent), output:
commands/z-style-init.md:414:> No recent dismissals found. STYLE.md unchanged.
commands/z-style-init.md:422:  "$(printf '{"phase":"MB-1","name":"scan-dismissals","wall_ms":%d,"n_signatures":%d}' \
commands/z-style-init.md:428:### Phase MB-2 — Cluster dismissals
commands/z-style-init.md:430:**Goal:** group similar dismissed findings into clusters so that one STYLE.md rule can address each cluster.
commands/z-style-init.md:445:3. **Within each category, build clusters with Jaccard ≥ 0.6:**
commands/z-style-init.md:447:   - For each remaining unassigned signature in the same category, compute Jaccard similarity:
commands/z-style-init.md:451:   - If Jaccard ≥ 0.6, add to the candidate cluster.
commands/z-style-init.md:472:No dismissal clusters found (need ≥2 similar dismissed findings per cluster). Nothing to amend.
commands/z-style-init.md:480:  "$(printf '{"phase":"MB-2","name":"cluster-dismissals","wall_ms":%d,"n_clusters":%d}' \
commands/z-style-init.md:500:  description="Propose STYLE.md rule amendments from dismissal clusters",
commands/z-style-init.md:501:  prompt="You are helping maintain a project STYLE.md. The user has repeatedly dismissed certain code-review findings in past review runs. Your job is to propose new STYLE.md rules — one per cluster — that would prevent those findings from being raised again.
commands/z-style-init.md:517:2. For each dismissal cluster below, propose ONE new rule. Map the cluster to the most appropriate STYLE.md section based on the cluster's category:
commands/z-style-init.md:523:3. The rule must encode the intent behind the dismissals — why were these findings repeatedly rejected? What convention should the reviewer learn to stop flagging?
commands/z-style-init.md:579:Proposed new rule for cluster <cluster_id> (category: <category>, <member_count> dismissed findings):
commands/z-style-init.md:581:Representative dismissed finding:
commands/z-style-init.md:661:> STYLE.md amended: <N_RULES_ADDED> rule(s) added across <K> section(s) (from <N_CLUSTERS> dismissal clusters). Run `/z-mr-review` to see new findings against the updated guide.
scripts/extract-dismissals.py:3:Extract dismissed MR-review findings from archived run snapshots.
scripts/extract-dismissals.py:6:    python3 scripts/extract-dismissals.py <slug-dir> [--max-runs N] [--global]
scripts/extract-dismissals.py:9:  1. Snapshot at archive/R_i/MR-REVIEW.md = original findings.
scripts/extract-dismissals.py:10:  2. Pre-edit copy at archive/R_{i+1}/MR-REVIEW.md.previous-* = what was
scripts/extract-dismissals.py:18:  0 — success (even if no dismissals found)
scripts/extract-dismissals.py:55:    Parse a minimal subset of YAML frontmatter sufficient for MR-REVIEW.md.
scripts/extract-dismissals.py:61:            - {id: T-MR-001, severity: P0, category: abstraction, file: src/foo.rs}
scripts/extract-dismissals.py:232:def parse_mr_review_frontmatter(path: Path) -> dict:
scripts/extract-dismissals.py:234:    Parse the YAML frontmatter block from an MR-REVIEW.md file.
scripts/extract-dismissals.py:270:      [{id: T-MR-001, severity: P0, category: abstraction, file: src/foo.rs, title: ...}, ...]
scripts/extract-dismissals.py:276:    dismissal matches.
scripts/extract-dismissals.py:344:    Each run dir must contain an MR-REVIEW.md snapshot to be included.
scripts/extract-dismissals.py:351:        if d.is_dir() and (d / "MR-REVIEW.md").exists()
scripts/extract-dismissals.py:359:    Find the MR-REVIEW.md.previous-* file in next_run_dir (the user-edited
scripts/extract-dismissals.py:365:    candidates = list(next_run_dir.glob("MR-REVIEW.md.previous-*"))
scripts/extract-dismissals.py:383:def extract_dismissals_from_runs(
scripts/extract-dismissals.py:391:      - R_i snapshot: archive/R_i/MR-REVIEW.md
scripts/extract-dismissals.py:392:      - User-edited version: archive/R_{i+1}/MR-REVIEW.md.previous-*
scripts/extract-dismissals.py:395:    Returns (list_of_dismissed_signature_dicts, n_runs_scanned).
scripts/extract-dismissals.py:401:    dismissed: list[dict] = []
scripts/extract-dismissals.py:407:        snapshot_path = r_i / "MR-REVIEW.md"
scripts/extract-dismissals.py:414:        snapshot_fm = parse_mr_review_frontmatter(snapshot_path)
scripts/extract-dismissals.py:415:        previous_fm = parse_mr_review_frontmatter(previous_path)
scripts/extract-dismissals.py:425:                dismissed.append({
scripts/extract-dismissals.py:432:    return dismissed, n_runs
scripts/extract-dismissals.py:441:def collect_slug_run_dirs_global(repo_root: Path) -> dict[Path, list[Path]]:
scripts/extract-dismissals.py:445:    The pairwise dismissal algorithm (R_i → R_{i+1}) must be applied WITHIN each
scripts/extract-dismissals.py:469:        description="Extract dismissed MR-review findings from archived run snapshots."
scripts/extract-dismissals.py:476:             "Required unless --global is set.",
scripts/extract-dismissals.py:486:        "--global",
scripts/extract-dismissals.py:487:        dest="global_scan",
scripts/extract-dismissals.py:489:        help="Scan z-harness/*/archive/*/MR-REVIEW.md across all slugs.",
scripts/extract-dismissals.py:497:    if args.global_scan:
scripts/extract-dismissals.py:506:        slug_runs = collect_slug_run_dirs_global(repo_root)
scripts/extract-dismissals.py:516:            sigs, n = extract_dismissals_from_runs(slug_run_dirs, args.max_runs)
scripts/extract-dismissals.py:527:                "ERROR: slug_dir is required unless --global is set.",
scripts/extract-dismissals.py:546:    signatures, n_runs = extract_dismissals_from_runs(run_dirs, args.max_runs)
commands/z-maintain-docs.md:149:- After `/z-implement-all` finalizes, the orchestrator's recommended-next push-notification lists `/z-maintain-docs`.
commands/z-init-docs.md:200:If `<repo-root>/.z-harness-rsync-exclude` doesn't exist, copy the default from `${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/.z-harness-rsync-exclude`. This file is used by the `remote-runner` subagent during `/z-implement-all` remote verification.
commands/z-amend.md:180:   - **full mode with new/modified `[ ]` tasks** → `/z-implement-next` or `/z-implement-all`
commands/z-stats.md:10:Same as `/z-implement-all` Phase 0:
commands/z-stats.md:74:Reuse the gap-detection awk from `/z-implement-all` Detecting Stalls section. Flag any gap > 30 min between consecutive same-run events.
commands/z-stats.md:93:| Some tasks `[ ]` and no in-flight halts | `/z-implement-all` |
commands/z-stats.md:95:| Plan is fresh (no `task_start` events yet) and `$BASE/TESTS.md` absent | `/z-test` (optional, recommended for risky / financial code) then `/z-implement-all` |
commands/z-stats.md:96:| Plan is fresh and `$BASE/TESTS.md` present with `Status: drafted` | `/z-implement-all` (will pick up TESTS.md automatically) |
commands/z-stats.md:99:| Debug plan with `POSTMORTEM.md` action items not yet tasked | "Convert post-mortem action items via the AskUserQuestion path documented in /z-debug Phase 7 (option C seeds a /z-test follow-up)" |
agents/cluster-planner.md:262:Task IDs are cluster-scoped: `T001`, `T002`, … within this cluster. (The parent MANIFEST holds cluster ordering; task IDs do not need to be globally unique.)
commands/z-plan.md:37:7. Usage-limit guard policy: read env `Z_HARNESS_PAUSE_AT_PCT` (default `90`). If Claude Code surfaces a usage indicator and current usage ≥ this %, **don't dispatch new phases**; instead emit `usage_pause`, push-notify, and finalize whatever phase you're on cleanly. The user resumes by re-invoking `/z-plan` with the same task (or `/z-implement-all` if planning is already done).
commands/z-plan.md:281:If a task block already contains a user-authored `**Complexity:** <tier>` line (rare at plan-time, but possible if the user is editing TASKS.md in-flight), the classifier returns `REASON: user-authored override` and you leave the stamp alone. The orchestrator `/z-implement-all` reads this stamp at dispatch time to pick the implementer model (`low|medium` → Sonnet, `high` → Opus).
commands/z-plan.md:294:  /z-implement-all  — orchestrate the queue (auto-includes TESTS.md if present, or /z-implement-next for one-at-a-time)
commands/z-plan.md:299:The `/z-test` step is optional but high-value when the plan touches money, ordering, signal generation, or any other domain where mechanical correctness (which `/z-implement-all`'s codex-reviewer catches) is not enough to catch semantic bugs (notional sign flips, feature schema mismatches, unit confusion). It produces a `TESTS.md` artifact that `/z-implement-all`'s implementer subagent reads alongside TASKS.md, so test code lands in the same diff as the production code it exercises.
commands/z-test.md:2:description: Semantic test-case planner. Reads SPEC.md + PLAN.md + TASKS.md for an existing plan, risk-ranks the tasks, drafts non-trivial test cases that catch real semantic bugs (sign errors, schema/feature mismatches, time-window off-by-one, unit confusion, state-machine invariants), runs bundled cross-LLM consult (Gemini + Codex, mode test-cases) to add missed coverage and drop trivial drafts, writes TESTS.md, and cross-links TEST-NNN entries back into TASKS.md. Tests are then implemented by /z-implement-all in the same task as their production code.
commands/z-test.md:6:You are running **z-harness `/z-test`** — the semantic test-case planner. This is an **optional planning-time step** between `/z-plan` and `/z-implement-all`. It does NOT write or run any test code. It produces a structured `TESTS.md` artifact that the implementer subagent reads alongside TASKS.md, so tests get implemented in the same diff as the code they exercise.
commands/z-test.md:12:Same logic as `/z-implement-all` Phase 0:
commands/z-test.md:162:**Status:** drafted (awaiting /z-implement-all)
commands/z-test.md:216:     /z-implement-all   — implements tasks AND their linked TESTS.md entries together
commands/z-test.md:225:- **No test execution.** `/z-test` is planning, not execution. The implementer writes the test code (in the same task as its production code); `/z-implement-all`'s per-task acceptance check runs it; `/z-review-all`'s final gate runs the suite.
commands/z-test.md:232:- Does not run any tests (deferred to /z-implement-all + /z-review-all).
commands/z-implement-all.md:5:You are the **z-harness `/z-implement-all`** orchestrator. Your job is to drive the task queue to completion without losing the per-task fresh-context guarantee. You do not implement code yourself — you delegate each task to a fresh `implementer` subagent and each review to a fresh `codex-reviewer` subagent.
commands/z-implement-all.md:13:- `--tasks=<path>` — Override the default tasks file location. By default the orchestrator reads `$BASE/TASKS.md` (discovered via slug detection in Setup step 2). When `--tasks=<path>` is provided, that file is used as the task queue instead. `<path>` may be repo-relative (e.g. `z-harness/mr-style-reviewer/MR-REVIEW.md`) or absolute. `$BASE` is derived from the directory containing the tasks file — e.g. `--tasks=z-harness/mr-style-reviewer/MR-REVIEW.md` sets `BASE=z-harness/mr-style-reviewer` so SPEC.md, PLAN.md, and archive paths resolve correctly. Slug detection (step 2) is skipped when `--tasks` is supplied; tree-rooted and MANIFEST validation are bypassed for the single overridden file. `--ack` and `--force-partial` are no-ops when `--tasks` is active.
commands/z-implement-all.md:21:   **`--tasks` fast path.** If the user invoked with `--tasks=<path>`, resolve the path to absolute and derive `BASE` as its parent directory:
commands/z-implement-all.md:29:   **Example:** `/z-implement-all --tasks=z-harness/mr-style-reviewer/MR-REVIEW.md` reads task blocks from `MR-REVIEW.md` (e.g. `T-MR-001`, `T-MR-002`, …) and resolves SPEC.md at `z-harness/mr-style-reviewer/SPEC.md`.
commands/z-implement-all.md:38:   - Multiple candidates → `AskUserQuestion` to pick. Mixed legacy + tree-rooted slugs are allowed in the same `/z-implement-all` invocation: the user picks one, validation/expansion below depends on its kind.
commands/z-implement-all.md:118:3. From here on, **`BASE`** = `z-harness/$Z_HARNESS_SLUG` for legacy slugs (or `z-harness` for legacy flat). For tree-rooted slugs, `BASE` is rebound per-cluster as the orchestrator iterates the run-order sequence from 2c. When `--tasks` was provided, `BASE` was set in step 1's fast path. All paths use `$BASE`.
commands/z-implement-all.md:120:   **Set the default tasks file now that `BASE` is bound** (the `--tasks` fast path already set `TASKS_FILE` in step 1, so the `:-` default leaves it alone):
commands/z-implement-all.md:145:8. **Usage-limit guard policy.** Read env `Z_HARNESS_PAUSE_AT_PCT` (default `90`). At each batch boundary, check whether Claude Code surfaces current usage %. If ≥ this threshold: emit a `usage_pause` event, push-notify ("Usage at <N>%; pausing. Reply or re-invoke `/z-implement-all` to resume."), finalize the loop cleanly (no new dispatch; in-flight tasks complete), and exit. Re-invocation picks up from current TASKS.md state — no manual recovery needed.
commands/z-implement-all.md:162:- **`MAX_ATTEMPTS=2` per task ID for the entire `/z-implement-all` run.** "Attempt" = a fresh dispatch through step 5 (implementer). Retries inside step 7 (review-failure re-spawn) count as part of the same attempt. After 2 attempts that don't reach `task_done`, halt the task, push-notify, and present to the user with options: skip / override / re-spec / abandon. Override via `Z_HARNESS_MAX_ATTEMPTS=N`.
commands/z-implement-all.md:203:- **I'll run it myself** — leave `[ ]`, exclude for now; user will mark `[x]` manually when done, then re-invoke `/z-implement-all` to resume.
commands/z-do.md:52:Per the global rule, if `docs/llm/INDEX.json` exists, dispatch `doc-fetcher` (Haiku) BEFORE any other reading:
commands/z-do.md:153:- **Doc-fetcher first** (per global CLAUDE.md rule) whenever `docs/llm/INDEX.json` exists.
commands/z-audit.md:2:description: Audit a target component across one or more dimensions (correctness / perf / cleanliness / design). Pre-flight scopes (target, dimensions, optional rubric file), spawns one auditor subagent per dimension in parallel, runs bundled Gemini+Codex consult on findings, emits REPORT.md + TASKS.md under z-harness/<slug>-audit/ in the exact shape /z-implement-all consumes. Read-only — never edits the target.
commands/z-audit.md:6:You are running **z-harness `/z-audit`** — a structured, read-only audit pipeline. The output is `REPORT.md` (everything found) plus a curated `TASKS.md` (actionable subset, in `/z-implement-all`-compatible format) under `z-harness/<slug>-audit/`.
commands/z-audit.md:14:This command is **read-only**. Never edit the target. Fixes happen later via `/z-implement-all` consuming the emitted `TASKS.md`.
commands/z-audit.md:154:Write `$BASE/TASKS.md` in the **exact format `/z-implement-all` consumes** (mirror `agents/implementer.md` shape):
commands/z-audit.md:174:**Note in `$BASE/SPEC.md`:** `/z-implement-all` will read `$BASE/SPEC.md`. Audits don't produce a SPEC, but the implementer reads it. Write a minimal `$BASE/SPEC.md`:
commands/z-audit.md:197:This three-file set (SPEC.md / PLAN.md / TASKS.md) is what `/z-implement-all` requires.
commands/z-audit.md:223:- Task count and recommended next step (`/z-implement-all` if findings are point fixes; `/z-plan` if structural)
commands/z-audit.md:238:- **TASKS.md format must match what `/z-implement-all` consumes** — otherwise the audit is a dead-end artifact.
commands/z-debug.md:2:description: Investigate a known-bad behavior with explicit repro / hypothesis / evidence / isolation phases, then ship a fix using the /z-plan-light flow, then write a post-mortem with preventative action items. Cross-LLM consult at the hypothesis stage and again at the fix stage. Auto-bails to /z-plan when scope grows beyond architectural change.
commands/z-debug.md:30:6. Record start time `T0_DEBUG=$(date -u +%Y-%m-%dT%H:%M:%SZ)` — used for post-mortem timeline.
commands/z-debug.md:216:**After the codex review passes**, write `z-harness/$Z_HARNESS_SLUG/POSTMORTEM.md`. This is mandatory for `/z-debug` (not just paperwork — surfaces preventative gaps):
commands/z-debug.md:247:## Action items (preventative)
commands/z-debug.md:261:- "Run MR-style review (Recommended)" — invoke `/z-mr-review` on the fix diff; P0/P1 findings will be appended to the post-mortem's preventative action items automatically.
commands/z-debug.md:262:- "Skip" — leave the post-mortem as-is and proceed to the action-item conversion prompts.
commands/z-debug.md:265:1. Invoke `/z-mr-review` as a best-effort step (on any failure, append a note to POSTMORTEM.md and continue — do NOT halt the post-mortem):
commands/z-debug.md:272:   - MR-REVIEW.md is written by `/z-mr-review` to the canonical path: `$(git rev-parse --show-toplevel)/z-harness/$Z_HARNESS_SLUG/MR-REVIEW.md`.
commands/z-debug.md:274:2. If `/z-mr-review` succeeds, parse `$(git rev-parse --show-toplevel)/z-harness/$Z_HARNESS_SLUG/MR-REVIEW.md` for P0/P1 findings using a defensive Python inline block (treat malformed/missing as "no findings" — never fall back to prose parsing):
commands/z-debug.md:278:   mr_path = "<abs_path_to_MR-REVIEW.md>"
commands/z-debug.md:280:       with open(mr_path) as f:
commands/z-debug.md:297:           if sev in ("P0", "P1"):
commands/z-debug.md:300:               print(f"- [ ] [{fid}] {title} (from MR-REVIEW.md quality review)")
commands/z-debug.md:302:       print("NOTE: MR-REVIEW.md not found — MR review produced no output")
commands/z-debug.md:304:       print(f"NOTE: MR-REVIEW.md parse error ({e}) — treating as no findings")
commands/z-debug.md:307:   Collect the printed lines. If no `- [ ]` lines were printed (no P0/P1 findings or parse fallback), use a single note: `- MR quality review found no P0/P1 findings.`
commands/z-debug.md:309:3. Append the collected finding lines (or the "no findings" note) to POSTMORTEM.md's "Action items (preventative)" section.
commands/z-debug.md:312:- "Convert action items into follow-up tasks?" → If yes, the orchestrator appends them to a designated `TASKS.md` (user picks which slug, or creates a fresh `audit-<topic>` slug) and the user can later `/z-implement-all` them.
commands/z-debug.md:313:- "Convert regression-test action items into a /z-test follow-up" → For each action item shaped like `Add regression test ...`, record the invariant + failure-class + target-file hint into `z-harness/<slug>/test-followups.md` (a flat list of seed entries shaped like Phase 2 drafts in `/z-test`). On the next `/z-plan` + `/z-test` cycle (or if the user re-runs `/z-test` on this same slug after seeding follow-up production tasks), these become mandatory TESTS.md entries. Closes the post-mortem loop automatically — the next plan run cannot ship without the regression test the post-mortem flagged.
commands/z-debug.md:339:- **Never skip the post-mortem.** Even on a trivial bug — the preventative action-items habit is what makes /z-debug different from /z-plan-light.
commands/z-brainstorm.md:96:### 1c. RESEARCH.md ingestion
commands/z-brainstorm.md:103:Record `depends_on: [RESEARCH.md]` in the eventual BRAINSTORM.md frontmatter if RESEARCH.md was ingested.
commands/z-brainstorm.md:189:   depends_on: [<RESEARCH.md if ingested>]
commands/z-suggest-memory.md:2:description: Authoring skill for the docs/llm/ memory layer. Called mandatorily from /z-debug post-mortem and /z-improve retro. Validates input against the memory schema, writes to docs/llm/<slug>.json, regenerates docs/llm/MEMORIES-FLAT.md, optionally extracts into docs/human/<slug>.md.
commands/z-mr-review.md:2:description: Multi-LLM code-quality review of the current branch diff against STYLE.md. Never blocks; ranks P0-P4; output is a TASKS.md-shape file you edit and feed to /z-implement-all.
commands/z-mr-review.md:103:If `STYLE.md` does not exist, log `mr_style_missing`, then refuse:
commands/z-mr-review.md:147:bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" mr_voices_degraded \
commands/z-mr-review.md:151:### Step 1e — Archive any existing MR-REVIEW.md
commands/z-mr-review.md:153:If `z-harness/<slug>/MR-REVIEW.md` already exists, archive it before overwriting:
commands/z-mr-review.md:156:EXISTING="$SLUG_DIR/MR-REVIEW.md"
commands/z-mr-review.md:159:  while [ -f "$ARCHIVE_DIR/MR-REVIEW.md.previous-$N" ]; do
commands/z-mr-review.md:162:  cp "$EXISTING" "$ARCHIVE_DIR/MR-REVIEW.md.previous-$N"
commands/z-mr-review.md:245:CHUNK_THRESHOLD="${Z_MR_DIFF_CHUNK_BYTES:-320000}"
commands/z-mr-review.md:332:Invoke `scripts/extract-dismissals.py` to compute prior dismissal signatures:
commands/z-mr-review.md:335:if ! python3 "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/extract-dismissals.py" \
commands/z-mr-review.md:338:  > "$ARCHIVE_DIR/dismissed_signatures.json" 2>/dev/null; then
commands/z-mr-review.md:339:  echo '{"signatures":[],"n_runs_scanned":0}' > "$ARCHIVE_DIR/dismissed_signatures.json"
commands/z-mr-review.md:340:  bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" mr_dismissal_extract_failed \
commands/z-mr-review.md:345:**Emit one `mr_finding_dismissed` event per dismissed signature:**
commands/z-mr-review.md:356:with open(os.path.join(archive_dir, 'dismissed_signatures.json')) as f:
commands/z-mr-review.md:369:        'mr_finding_dismissed',
commands/z-mr-review.md:375:### Step 1j — Log mr_run_start
commands/z-mr-review.md:378:bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" mr_run_start \
commands/z-mr-review.md:403:DISMISSED_PATH="$REPO_ROOT/$ARCHIVE_DIR/dismissed_signatures.json"
commands/z-mr-review.md:426:dismissed_signatures_path: <DISMISSED_PATH>
commands/z-mr-review.md:474:dismissed_signatures_path: <DISMISSED_PATH>
commands/z-mr-review.md:498:dismissed_signatures_path: <DISMISSED_PATH>
commands/z-mr-review.md:510:## Phase 3 — Parse agent return(s) and write MR-REVIEW.md
commands/z-mr-review.md:518:If no valid JSON block is found, log `mr_all_voices_failed` and exit nonzero with:
commands/z-mr-review.md:529:Parse each return in `CHUNK_AGENT_RETURNS` by locating its first fenced `json` block. For chunk returns that fail to parse (no valid JSON block), log `mr_voice_failed {voice: "mr-reviewer-chunk-<INDEX>", reason: "malformed_json"}` and skip. Collect all parseable per-chunk findings into `CHUNK_FINDINGS` (union; duplicates not yet removed).
commands/z-mr-review.md:531:Parse `ABSTRACTION_AGENT_RETURN` by locating its first fenced `json` block. If the abstraction-only return fails to parse, log `mr_voice_failed {voice: "mr-reviewer-abstraction", reason: "malformed_json"}` and treat abstraction findings as empty.
commands/z-mr-review.md:541:If `ALL_FINDINGS` is empty AND `MODE=per-chunk` AND all chunk parses failed, log `mr_all_voices_failed` and exit nonzero with:
commands/z-mr-review.md:551:**Chunked-pass mode:** parse the `## Summary` block from `ABSTRACTION_AGENT_RETURN`. Additionally, for each chunk return in `CHUNK_AGENT_RETURNS`, parse its `## Summary` block and union the `voices_succeeded` and `voices_failed` lists. Aggregate `dismissal_pattern_matches` by summing across all returns.
commands/z-mr-review.md:556:- `dismissal_pattern_matches` — integer
commands/z-mr-review.md:558:If parsing fails for any field, default to: `voices_succeeded=[claude]`, `voices_failed=[]`, `dismissal_pattern_matches=0`.
commands/z-mr-review.md:569:by_severity = {"P0": 0, "P1": 0, "P2": 0, "P3": 0, "P4": 0}
commands/z-mr-review.md:582:# Group findings by severity for ordered output (P0 first)
commands/z-mr-review.md:583:severity_order = ["P0", "P1", "P2", "P3", "P4"]
commands/z-mr-review.md:585:    "P0": "would cause future bugs",
commands/z-mr-review.md:586:    "P1": "clear regression",
commands/z-mr-review.md:601:Assign T-MR-NNN IDs by iterating findings in severity order (P0 first, then P1, P2, P3, P4), then in original finding order within each severity group. IDs start at T-MR-001.
commands/z-mr-review.md:614:  - {id: T-MR-001, severity: P1, category: defensive-bloat, file: src/foo.rs, title: "Short title here"}
commands/z-mr-review.md:617:### Step 3e — Write MR-REVIEW.md
commands/z-mr-review.md:619:Build the full MR-REVIEW.md content using this exact structure:
commands/z-mr-review.md:635:by_severity: {P0: N, P1: N, P2: N, P3: N, P4: N}
commands/z-mr-review.md:637:  - {id: T-MR-001, severity: P1, category: defensive-bloat, file: src/foo.rs, title: "..."}
commands/z-mr-review.md:643:Findings ranked P0-P4. **Delete any finding you don't want fixed.** Then `/z-implement-all --tasks=z-harness/<SLUG>/MR-REVIEW.md`.
commands/z-mr-review.md:645:## P0 — would cause future bugs
commands/z-mr-review.md:647:(findings with severity=P0, each as a task block; omit section if empty)
commands/z-mr-review.md:658:## P1 — clear regression
commands/z-mr-review.md:660:(findings with severity=P1; omit section if empty)
commands/z-mr-review.md:682:1. `z-harness/<SLUG>/MR-REVIEW.md` — canonical (overwrites any prior file)
commands/z-mr-review.md:683:2. `<ARCHIVE_DIR>/MR-REVIEW.md` — snapshot (identical content)
commands/z-mr-review.md:695:canonical = os.path.join(slug_dir, 'MR-REVIEW.md')
commands/z-mr-review.md:696:snapshot  = os.path.join(archive_dir, 'MR-REVIEW.md')
commands/z-mr-review.md:710:For each finding emit one `mr_finding_emitted` event:
commands/z-mr-review.md:713:bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" mr_finding_emitted \
commands/z-mr-review.md:714:  "$(printf '{"slug":"%s","run_id":"%s","id":"%s","severity":"%s","category":"%s","voices_count":1,"dismissal_match":false}' \
commands/z-mr-review.md:718:### Step 3g — Log mr_run_end
commands/z-mr-review.md:720:Compute `N_DISPATCHES` before emitting `mr_run_end`. In per-chunk mode, `N_DISPATCHES` = (number of chunks) + 1 (the abstraction-only pass). In full mode, `N_DISPATCHES` = 1.
commands/z-mr-review.md:732:bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" mr_run_end \
commands/z-mr-review.md:735:slug, run_id, total, by_sev_json, by_cat_json, voices_s, voices_f, dismissal_matches, mode, n_dispatches = \
commands/z-mr-review.md:747:  "dismissal_matches": dismissal_matches,
commands/z-mr-review.md:765:Results: z-harness/<SLUG>/MR-REVIEW.md
commands/z-mr-review.md:768:  P0: <N>  P1: <N>  P2: <N>  P3: <N>  P4: <N>
commands/z-mr-review.md:772:Delete what you don't want, then /z-implement-all --tasks=z-harness/<SLUG>/MR-REVIEW.md to apply the survivors.
commands/z-mr-review.md:778:Note: <N> finding(s) match prior dismissal patterns. Consider `/z-style-init --amend` to codify these preferences into STYLE.md so they are not raised again.
commands/z-mr-review.md:824:   - `z-harness/feature-smoke-test/MR-REVIEW.md` is created with valid YAML frontmatter, at least one finding, `T-MR-001` block present, and the "Delete what you don't want" footer line.
commands/z-mr-review.md:831:2. Set `Z_MR_DIFF_CHUNK_BYTES=1` to force per-chunk mode regardless of actual diff size.
commands/z-mr-review.md:835:   - `archive/$RUN/MR-REVIEW.md` exists and has valid frontmatter.
commands/z-mr-review.md:836:   - MR-REVIEW.md frontmatter shows `mode: per-chunk` in the run_end log.
commands/z-mr-review.md:838:   - MR-REVIEW.md contains both per-chunk category findings (defensive-bloat, test-noise, hygiene, style-drift) and possibly abstraction findings from the abstraction-only pass.
commands/z-mr-review.md:849:- **Archive before overwrite.** Existing `MR-REVIEW.md` is always archived before being replaced.

 succeeded in 384ms:
JSON_OK

codex
JSON parsing is clean. I’ve found one likely user-facing command-path issue and I’m checking whether the style-init amend scan description matches the actual command contract before deciding if it clears the major bar.
exec
/bin/zsh -lc "sed -n '260,520p' commands/z-style-init.md" in /Users/zeke/dev/z-harness
 succeeded in 0ms:

```
Agent(
  subagent_type="codex-consultant",
  description="Style-critique STYLE.md draft",
  prompt="MODE: style-critique

Review the STYLE.md draft below. Flag:
- Missing rule categories (e.g. a section with zero rules, or a clearly missing topic given the observed source files)
- Vague rules (prose that is not actionable — e.g. 'write clean code')
- Contradictions between rules (e.g. EH-001 says propagate; EH-003 says swallow)
- Rule IDs that are out of sequence or duplicated

Return your findings as a numbered list. Each finding: one sentence describing the problem + one sentence proposing a fix. If you find no problems, return 'No findings.'

STYLE.md draft:
<DRAFT_STYLE_MD>"
)

Agent(
  subagent_type="gemini-consultant",
  description="Style-critique STYLE.md draft",
  prompt="MODE: style-critique

Review the STYLE.md draft below. Flag:
- Missing rule categories (e.g. a section with zero rules, or a clearly missing topic given the observed source files)
- Vague rules (prose that is not actionable — e.g. 'write clean code')
- Contradictions between rules
- Rule IDs that are out of sequence or duplicated

Return your findings as a numbered list. Each finding: one sentence describing the problem + one sentence proposing a fix. If you find no problems, return 'No findings.'

STYLE.md draft:
<DRAFT_STYLE_MD>"
)
```

Wait for both returns. Collect findings. If a consultant errors or times out, log `style_critic_failed {voice, reason}` and proceed with the other consultant's findings only.

**Apply findings:** for each non-trivial finding (skip duplicates and taste-only nits), apply the suggested fix to `DRAFT_STYLE_MD`. Use your own judgment to resolve contradictions between the two consultants' suggestions. The goal is a tighter, more actionable style guide — do not add rules that conflict with what the source files show.

Record the revised content as `REVISED_STYLE_MD`.

---

## Phase 5 — User approval and write

Present the draft to the user via `AskUserQuestion`:

```
STYLE.md draft is ready (after cross-LLM critique). Here's a summary:

Sections:
  - Error handling: <N> rules
  - Tests: <N> rules
  - Comments: <N> rules
  - Naming: <N> rules
  - Project-specific: <N> rules
Total rules: <total>

Source files used: <FINAL_5 paths, or 'ingest: <path>'>
Critique applied from: <codex|gemini|both|neither (if both failed)>

Options:
  accept            — write STYLE.md to repo root and finish
  edit-and-resave   — I'll paste an edited version; use that instead
  re-critique       — run another critique pass on the current draft
  abandon           — exit without writing STYLE.md
```

Log `user_wait_start` before presenting; log `user_wait_end` after reply.

Branch on reply:

- **accept** → proceed to write step.
- **edit-and-resave** → `AskUserQuestion` asking the user to paste the edited STYLE.md content. Accept the paste, set `REVISED_STYLE_MD` to the pasted content. Proceed to write step.
- **re-critique** → loop back to Phase 4 with the current `REVISED_STYLE_MD` as input.
- **abandon** → exit cleanly. Log `style_init_abandoned` event.

### Write step

Write `REVISED_STYLE_MD` to `./STYLE.md` at the repo root (use the Write tool).

Count the total number of rules across all sections (search for `### [A-Z]+-[0-9]+:` pattern). Count the number of non-empty sections.

Log `style_init_complete`:

```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" style_init_complete \
  "$(printf '{"source":"%s","sections_populated":%d,"rule_count":%d}' \
     "<SOURCE>" "<SECTIONS_WITH_RULES>" "<TOTAL_RULE_COUNT>")"
```

Push-notify (if `Z_HARNESS_NOTIFY` ≠ `off`):

> STYLE.md written to repo root (<TOTAL_RULE_COUNT> rules across <SECTIONS_WITH_RULES> sections). Run `/z-mr-review` to review a branch diff against it.

---

---

## Mode B — Amend (`--amend`)

### Setup

1. **Check for STYLE.md.** Run:
   ```bash
   ls ./STYLE.md 2>/dev/null
   ```
   If `STYLE.md` does NOT exist, refuse:
   > No STYLE.md found. Run `/z-style-init` (without `--amend`) first to bootstrap one.
   Exit without writing anything.

2. **Pick a run id:**
   ```bash
   RUN=$(date -u +%Y%m%dT%H%M%SZ)-style-amend
   ```

3. **Version stamp + log run start:**
   ```bash
   VERSION_BLOB="$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/version.sh")"
   bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" style_amend_start \
     "$(python3 -c 'import json,sys; v=json.loads(sys.argv[1]); print(json.dumps(v))' "$VERSION_BLOB")"
   ```

4. **Derive slug-dir.** Attempt to read the current branch:
   ```bash
   BRANCH="$(git branch --show-current 2>/dev/null)"
   SLUG="$(printf '%s' "$BRANCH" | tr '[:upper:]' '[:lower:]' | tr '/' '-' | sed 's/[^a-z0-9-]//g')"
   SLUG_DIR="z-harness/${SLUG}/"
   ```
   If the branch is empty/detached or `SLUG_DIR` does not exist as a directory, use the first available `z-harness/*/` directory (via `ls -d z-harness/*/`). If no `z-harness/*/` directory exists at all, `SLUG_DIR` can be any valid path string — the `--global` flag causes `extract-dismissals.py` to scan all slugs, so a missing slug-dir simply yields an empty result set.

5. **Notification policy:** read env `Z_HARNESS_NOTIFY` (default `approval_only`). Values: `off`, `approval_only`, `all`.

---

### Phase MB-1 — Scan dismissal archives

**Goal:** extract normalized finding snippets that users have repeatedly dismissed in past MR-REVIEW runs.

Record `T0=$(date +%s%3N)`.

Run:
```bash
python3 scripts/extract-dismissals.py "${SLUG_DIR}" --max-runs 10 --global
```

Capture stdout as `DISMISSED_JSON`. If the script exits nonzero or produces invalid JSON, log `style_amend_extract_failed {reason}` and exit with:
> Could not extract dismissal signatures (extract-dismissals.py failed). Check that `scripts/extract-dismissals.py` exists and the z-harness archive structure is intact.

Parse `DISMISSED_JSON` into `DISMISSED_SIGNATURES` (the array at `.signatures`). Record `N_SIGNATURES = len(DISMISSED_SIGNATURES)`.

**Empty-dismissals early exit:** If `N_SIGNATURES == 0` (the signatures array is empty or absent), output:
> No recent dismissals found. STYLE.md unchanged.

Log `style_amend_complete {clusters: 0, rules_added: 0}` and exit cleanly. Do not proceed to Phase MB-2.

Log phase end:
```bash
WALL_MS=$(( $(date +%s%3N) - T0 ))
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" phase_end \
  "$(printf '{"phase":"MB-1","name":"scan-dismissals","wall_ms":%d,"n_signatures":%d}' \
     "$WALL_MS" "$N_SIGNATURES")"
```

---

### Phase MB-2 — Cluster dismissals

**Goal:** group similar dismissed findings into clusters so that one STYLE.md rule can address each cluster.

Record `T0=$(date +%s%3N)`.

**Stopword list** (hardcoded): `the a an this that is are in on of to for and or with by`

**Algorithm:**

1. **Tokenize each signature's `normalized_snippet`:**
   - Lowercase, collapse internal whitespace to a single space, strip leading/trailing punctuation.
   - Split on whitespace into a token list.
   - Remove all stopword tokens. Record as `tokens[i]`.

2. **Group by category first.** Signatures with different `category` values are placed in different clusters regardless of text similarity.

3. **Within each category, build clusters with Jaccard ≥ 0.6:**
   - For each signature not yet assigned to a cluster, start a new candidate cluster with that signature as seed.
   - For each remaining unassigned signature in the same category, compute Jaccard similarity:
     ```
     jaccard(A, B) = |tokens(A) ∩ tokens(B)| / |tokens(A) ∪ tokens(B)|
     ```
   - If Jaccard ≥ 0.6, add to the candidate cluster.
   - Mark all added signatures as assigned.
   - Repeat until all signatures in the category are assigned.

4. **Discard clusters with fewer than 2 members.**

Record `CLUSTERS` = the surviving clusters, each as:
```json
{
  "cluster_id": "<category>-<sequential-int>",
  "category": "<category>",
  "member_count": <int>,
  "representative_snippet": "<normalized_snippet of the seed signature>",
  "all_snippets": ["<snippet1>", "<snippet2>", ...]
}
```

Record `N_CLUSTERS = len(CLUSTERS)`.

If `N_CLUSTERS == 0`:
```
No dismissal clusters found (need ≥2 similar dismissed findings per cluster). Nothing to amend.
```
Log `style_amend_complete {clusters: 0, rules_added: 0}` and exit.

Log phase end:
```bash
WALL_MS=$(( $(date +%s%3N) - T0 ))
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" phase_end \
  "$(printf '{"phase":"MB-2","name":"cluster-dismissals","wall_ms":%d,"n_clusters":%d}' \
     "$WALL_MS" "$N_CLUSTERS")"
```

---

### Phase MB-3 — Propose amendments (Sonnet)

**Goal:** for each cluster, propose a new STYLE.md rule that would prevent those findings from being raised again.

Record `T0=$(date +%s%3N)`.

Read `./STYLE.md` (full content) into `CURRENT_STYLE_MD`.

Dispatch a Sonnet subagent:

```
Agent(
  subagent_type="general-purpose",
  model="sonnet",
  description="Propose STYLE.md rule amendments from dismissal clusters",
  prompt="You are helping maintain a project STYLE.md. The user has repeatedly dismissed certain code-review findings in past review runs. Your job is to propose new STYLE.md rules — one per cluster — that would prevent those findings from being raised again.

STYLE.md uses these sections with these rule-ID prefixes:
  ## Error handling   → EH-NNN
  ## Tests            → T-NNN
  ## Comments         → C-NNN
  ## Naming           → N-NNN
  ## Project-specific → P-NNN

Rule format (strictly required):
  ### EH-005: <short rule title>
  <one-paragraph rule prose — concrete and actionable, not vague>
  Rationale: <one sentence explaining why this matters for the project>

Instructions:
1. Read the current STYLE.md below carefully. For each section, identify the highest existing rule number (e.g. if EH-001 through EH-004 exist, the next free ID is EH-005).
2. For each dismissal cluster below, propose ONE new rule. Map the cluster to the most appropriate STYLE.md section based on the cluster's category:
   - category 'style-drift' or 'hygiene' → ## Project-specific or ## Naming
   - category 'defensive-bloat' → ## Error handling
   - category 'test-noise' → ## Tests

exec
/bin/zsh -lc "sed -n '300,790p' commands/z-mr-review.md" in /Users/zeke/dev/z-harness
 succeeded in 0ms:
    chunks.append({
        'index': idx,
        'path': chunk_path,
        'files_touched': [file_path],
        'line_count': line_count
    })

manifest = {
    'chunks': chunks,
    'total_bytes': os.path.getsize(diff_path),
    'generated_at': os.popen('date -u +%Y-%m-%dT%H:%M:%SZ').read().strip()
}
manifest_path = os.path.join(chunks_dir, 'manifest.json')
with open(manifest_path, 'w') as mf:
    json.dump(manifest, mf, indent=2)

print(f"Chunked diff into {len(chunks)} file patches. Manifest: {manifest_path}")
PYEOF
```

After chunking, verify the manifest contains at least one chunk. If `MODE=per-chunk` and the manifest has zero chunks, the diff was either empty (shouldn't reach here) or the chunker failed to parse any file boundaries — fail fast with a clear error:

```bash
CHUNK_COUNT_CHECK="$(python3 -c 'import json; m=json.load(open("'"$ARCHIVE_DIR/chunks/manifest.json"'")); print(len(m["chunks"]))')"
if [ "$CHUNK_COUNT_CHECK" -eq 0 ]; then
  echo "Error: MODE=per-chunk but manifest contains zero chunks. The diff may be empty or malformed — check $ARCHIVE_DIR/diff.patch." >&2
  exit 1
fi
```

### Step 1i — Dismissal signature extraction

Invoke `scripts/extract-dismissals.py` to compute prior dismissal signatures:

```bash
if ! python3 "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/extract-dismissals.py" \
  "z-harness/$SLUG/" \
  --max-runs 10 \
  > "$ARCHIVE_DIR/dismissed_signatures.json" 2>/dev/null; then
  echo '{"signatures":[],"n_runs_scanned":0}' > "$ARCHIVE_DIR/dismissed_signatures.json"
  bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" mr_dismissal_extract_failed \
    "$(printf '{"slug":"%s"}' "$SLUG")"
fi
```

**Emit one `mr_finding_dismissed` event per dismissed signature:**

```bash
python3 - <<'PYEOF'
import json, os, subprocess

archive_dir = os.environ['ARCHIVE_DIR']
slug = os.environ['SLUG']
run_id = os.environ['RUN']
plugin_root = os.environ.get('ANTIGRAVITY_PLUGIN_ROOT') or os.environ.get('CLAUDE_PLUGIN_ROOT', '')

with open(os.path.join(archive_dir, 'dismissed_signatures.json')) as f:
    data = json.load(f)

for sig in data.get('signatures', []):
    payload = json.dumps({
        'slug': slug,
        'category': sig.get('category', ''),
        'prior_run_id': sig.get('prior_run_id') or sig.get('run_id', '')
    })
    subprocess.run([
        'bash',
        os.path.join(plugin_root, 'scripts/log-event.sh'),
        run_id,
        'mr_finding_dismissed',
        payload
    ])
PYEOF
```

### Step 1j — Log mr_run_start

```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" mr_run_start \
  "$(python3 -c '
import json, sys
v = json.loads(sys.argv[1])
v["slug"] = sys.argv[2]
v["run_id"] = sys.argv[3]
v["base"] = sys.argv[4]
v["diff_stat"] = sys.argv[5]
v["mode"] = sys.argv[6]
v["voices_available"] = sys.argv[7].split(",")
v["deep"] = sys.argv[8] == "true"
print(json.dumps(v))
' "$VERSION_BLOB" "$SLUG" "$RUN" "$BASE_REF" "$DIFF_STAT" "$MODE" "$VOICES_AVAILABLE" "${DEEP:-false}")"
```

---

## Phase 2 — Agent dispatch

### Step 2a — Resolve absolute paths for agent inputs

```bash
REPO_ROOT="$(git rev-parse --show-toplevel)"
STYLE_PATH="$REPO_ROOT/STYLE.md"
DIFF_PATH="$REPO_ROOT/$ARCHIVE_DIR/diff.patch"
DISMISSED_PATH="$REPO_ROOT/$ARCHIVE_DIR/dismissed_signatures.json"
SLUG_DIR_ABS="$REPO_ROOT/$SLUG_DIR"
MANIFEST_PATH="$REPO_ROOT/$ARCHIVE_DIR/chunks/manifest.json"
```

### Step 2b — Dispatch mr-reviewer agent

The agent always receives one `diff_path` pointing to a single `.patch` file — polymorphism lives in the orchestrator only.

**If `MODE=full`:** dispatch the agent once with the full diff.

```
Agent(
  subagent_type="mr-reviewer",
  model="sonnet",
  description="MR review for <SLUG>",
  prompt="slug: <SLUG>
run_id: <RUN>
slug_dir: <SLUG_DIR_ABS>
base: <BASE_REF>
base_sha: <BASE_SHA>
diff_path: <DIFF_PATH>
style_path: <STYLE_PATH>
dismissed_signatures_path: <DISMISSED_PATH>
voices_available: [<VOICES_AVAILABLE>]
mode: full
chunk_meta: null
deep: <DEEP>"
)
```

Capture the agent's full return text as `AGENT_RETURN`. Proceed to Phase 3 (single-return merge path).

**If `MODE=per-chunk`:** dispatch one agent per chunk in parallel (single message, one `Agent()` call per chunk), then one additional abstraction-only pass sequentially after all per-chunk agents return.

Read `manifest.json` to enumerate chunks. Normalize each chunk path to an absolute path (manifests store paths as written by the chunker, which may be relative):

```python
python3 - <<'PYEOF'
import json, os

manifest_path = os.environ['MANIFEST_PATH']
repo_root = os.environ['REPO_ROOT']
with open(manifest_path) as f:
    manifest = json.load(f)

# Emit one line per chunk: INDEX|CHUNK_PATH (absolute)
for chunk in manifest['chunks']:
    chunk_path = chunk['path']
    # Normalize to absolute path so agent always receives an absolute path
    if not os.path.isabs(chunk_path):
        chunk_path = os.path.join(repo_root, chunk_path)
    print(f"{chunk['index']}|{chunk_path}")
PYEOF
```

For each chunk listed in the manifest, dispatch one `Agent()` call. Dispatch all chunk agents in parallel — a single message with one `Agent()` call per chunk:

```
# Repeat this Agent() call once per chunk, all in the same message (parallel dispatch):
Agent(
  subagent_type="mr-reviewer",
  model="sonnet",
  description="MR review for <SLUG> — chunk <INDEX> of <TOTAL>",
  prompt="slug: <SLUG>
run_id: <RUN>
slug_dir: <SLUG_DIR_ABS>
base: <BASE_REF>
base_sha: <BASE_SHA>
diff_path: <CHUNK_PATH>
style_path: <STYLE_PATH>
dismissed_signatures_path: <DISMISSED_PATH>
voices_available: [<VOICES_AVAILABLE>]
mode: per-chunk
chunk_meta: {\"index\": <INDEX>, \"total\": <TOTAL>, \"manifest_path\": \"<MANIFEST_PATH>\"}
deep: <DEEP>"
)
```

Collect all per-chunk agent returns as a list `CHUNK_AGENT_RETURNS` (one entry per chunk).

After all per-chunk agents complete, dispatch one additional abstraction-only pass with the full diff. This pass runs AFTER the per-chunk batch (sequential, not parallel with the chunks):

```
Agent(
  subagent_type="mr-reviewer",
  model="sonnet",
  description="MR abstraction-only pass for <SLUG>",
  prompt="slug: <SLUG>
run_id: <RUN>
slug_dir: <SLUG_DIR_ABS>
base: <BASE_REF>
base_sha: <BASE_SHA>
diff_path: <DIFF_PATH>
style_path: <STYLE_PATH>
dismissed_signatures_path: <DISMISSED_PATH>
voices_available: [<VOICES_AVAILABLE>]
mode: abstraction-only
chunk_meta: null
deep: <DEEP>"
)
```

Capture this return as `ABSTRACTION_AGENT_RETURN`. Proceed to Phase 3 (N+1-return merge path).

---

## Phase 3 — Parse agent return(s) and write MR-REVIEW.md

### Step 3a — Extract findings JSON

**Single-pass mode (`MODE=full`):**

Parse the agent return (`AGENT_RETURN`) by locating the first fenced `json` block (` ```json ... ``` `). Extract and parse its contents as JSON with schema `{"findings": [...]}`. Each finding has: `severity`, `category`, `file`, `line_start`, `line_end`, `title`, `detail`, `citation`.

If no valid JSON block is found, log `mr_all_voices_failed` and exit nonzero with:

```
Error: mr-reviewer agent returned no parseable findings JSON. The agent return was:
<AGENT_RETURN>
```

Set `ALL_FINDINGS` = the parsed findings list.

**Chunked-pass mode (`MODE=per-chunk`):**

Parse each return in `CHUNK_AGENT_RETURNS` by locating its first fenced `json` block. For chunk returns that fail to parse (no valid JSON block), log `mr_voice_failed {voice: "mr-reviewer-chunk-<INDEX>", reason: "malformed_json"}` and skip. Collect all parseable per-chunk findings into `CHUNK_FINDINGS` (union; duplicates not yet removed).

Parse `ABSTRACTION_AGENT_RETURN` by locating its first fenced `json` block. If the abstraction-only return fails to parse, log `mr_voice_failed {voice: "mr-reviewer-abstraction", reason: "malformed_json"}` and treat abstraction findings as empty.

**Dedup per-chunk findings:** identify findings from `CHUNK_FINDINGS` with the same `(file, category, normalized_text)` signature. Normalize: concatenate `title` + `" "` + `detail`, lowercase, collapse internal whitespace to single space, strip leading/trailing punctuation. Keep one finding per signature; merge the `voices` arrays of duplicates.

**Append abstraction findings:** add all abstraction-only findings to the deduped set. Per-chunk findings exclude the `abstraction` category entirely, so there is no overlap between the two sets.

**Final dedup pass:** after appending abstraction findings, run one final dedup pass over the full combined set using the same `(file, category, normalized_text)` key. This ensures any edge-case overlap (e.g., an abstraction finding that duplicates a per-chunk finding with same signature) is eliminated before setting `ALL_FINDINGS`.

Set `ALL_FINDINGS` = deduplicated combined set (per-chunk findings union abstraction findings, with any cross-set duplicates removed).

If `ALL_FINDINGS` is empty AND `MODE=per-chunk` AND all chunk parses failed, log `mr_all_voices_failed` and exit nonzero with:

```
Error: all mr-reviewer chunk agents returned no parseable findings JSON.
```

### Step 3b — Extract summary block

**Single-pass mode:** parse the `## Summary` block from `AGENT_RETURN` (the section after the JSON block).

**Chunked-pass mode:** parse the `## Summary` block from `ABSTRACTION_AGENT_RETURN`. Additionally, for each chunk return in `CHUNK_AGENT_RETURNS`, parse its `## Summary` block and union the `voices_succeeded` and `voices_failed` lists. Aggregate `dismissal_pattern_matches` by summing across all returns.

From the summary block(s), extract these fields:
- `voices_succeeded` — list, e.g. `[claude]`
- `voices_failed` — list
- `dismissal_pattern_matches` — integer

If parsing fails for any field, default to: `voices_succeeded=[claude]`, `voices_failed=[]`, `dismissal_pattern_matches=0`.

### Step 3c — Compute aggregates

From `ALL_FINDINGS` (the merged list from Step 3a — one item per deduplicated finding):

```python
import json as _json, os as _os
_archive_dir = _os.environ['ARCHIVE_DIR']
# `findings` here refers to ALL_FINDINGS from Step 3a
total_findings = len(findings)
by_severity = {"P0": 0, "P1": 0, "P2": 0, "P3": 0, "P4": 0}
by_category = {}
for f in findings:
    by_severity[f["severity"]] += 1
    cat = f.get("category", "uncategorized")
    by_category[cat] = by_category.get(cat, 0) + 1

# Serialize to files so the shell can read them back
with open(f"{_archive_dir}/by_severity.json", "w") as _fh:
    _fh.write(_json.dumps(by_severity))
with open(f"{_archive_dir}/by_category.json", "w") as _fh:
    _fh.write(_json.dumps(by_category))

# Group findings by severity for ordered output (P0 first)
severity_order = ["P0", "P1", "P2", "P3", "P4"]
by_severity_label = {
    "P0": "would cause future bugs",
    "P1": "clear regression",
    "P2": "style drift",
    "P3": "minor hygiene",
    "P4": "taste-only nits",
}
```

Then read back into shell variables:

```bash
BY_SEVERITY_JSON="$(cat "$ARCHIVE_DIR/by_severity.json")"
BY_CATEGORY_JSON="$(cat "$ARCHIVE_DIR/by_category.json")"
TOTAL_FINDINGS="$(python3 -c 'import json,sys; print(sum(json.load(open(sys.argv[1])).values()))' "$ARCHIVE_DIR/by_severity.json")"
```

Assign T-MR-NNN IDs by iterating findings in severity order (P0 first, then P1, P2, P3, P4), then in original finding order within each severity group. IDs start at T-MR-001.

Compute `STYLE_MD_REVISION`:

```bash
STYLE_MD_REVISION="$(git rev-parse HEAD:STYLE.md 2>/dev/null || echo 'unknown')"
```

### Step 3d — Build findings_index

For each finding (in T-MR-NNN order), build a YAML findings_index entry:

```yaml
  - {id: T-MR-001, severity: P1, category: defensive-bloat, file: src/foo.rs, title: "Short title here"}
```

### Step 3e — Write MR-REVIEW.md

Build the full MR-REVIEW.md content using this exact structure:

```markdown
---
artifact: mr-review
slug: <SLUG>
run_id: <RUN>
generated_at: <ISO timestamp — date -u +%Y-%m-%dT%H:%M:%SZ>
base: <BASE_REF>
base_sha: <BASE_SHA>
diff_stat: <DIFF_STAT>
mode: <MODE>
style_md_revision: <STYLE_MD_REVISION>
voices_available: [<VOICES_AVAILABLE comma-separated>]
voices_succeeded: [<voices_succeeded from summary>]
total_findings: <N>
by_severity: {P0: N, P1: N, P2: N, P3: N, P4: N}
findings_index:
  - {id: T-MR-001, severity: P1, category: defensive-bloat, file: src/foo.rs, title: "..."}
  # ... one entry per finding
---

# MR Review — <SLUG>

Findings ranked P0-P4. **Delete any finding you don't want fixed.** Then `/z-implement-all --tasks=z-harness/<SLUG>/MR-REVIEW.md`.

## P0 — would cause future bugs

(findings with severity=P0, each as a task block; omit section if empty)

- [ ] T-MR-NNN. <title>
  **File:** <file>:<line_start>-<line_end>
  **Category:** <category>
  **Voices:** <voices list, comma-separated>
  **Citation:** <citation or "none">
  **Finding:** <detail>
  **Acceptance criteria:**
  - Address the finding in <file> per the detail above.

## P1 — clear regression

(findings with severity=P1; omit section if empty)

## P2 — style drift

(findings with severity=P2; omit section if empty)

## P3 — minor hygiene

(findings with severity=P3; omit section if empty)

## P4 — taste-only nits

(findings with severity=P4; omit section if empty)
```

Rules:
- Omit any severity section that has zero findings — do not emit an empty `## P2 — style drift` section.
- For `line_start`/`line_end`: if both are non-null, format as `<file>:<line_start>-<line_end>`. If only `line_start` is non-null, format as `<file>:<line_start>`. If both are null, just `<file>`.
- `voices` in each finding block: use the per-finding `voices` array from the merged `ALL_FINDINGS` list. In single-voice mode this is always `[claude]`; in multi-voice mode it reflects all voices that raised that finding.
- `Citation`: use the `citation` field from the finding JSON. If null, write `none`.

Write the completed content to **both** paths:
1. `z-harness/<SLUG>/MR-REVIEW.md` — canonical (overwrites any prior file)
2. `<ARCHIVE_DIR>/MR-REVIEW.md` — snapshot (identical content)

```bash
mkdir -p "$SLUG_DIR"
# Write both files with the same content
python3 - <<'PYEOF'
import os

slug_dir = os.environ['SLUG_DIR']
archive_dir = os.environ['ARCHIVE_DIR']
content = os.environ['MR_REVIEW_CONTENT']

canonical = os.path.join(slug_dir, 'MR-REVIEW.md')
snapshot  = os.path.join(archive_dir, 'MR-REVIEW.md')

with open(canonical, 'w') as f:
    f.write(content)
with open(snapshot, 'w') as f:
    f.write(content)

print(f"Wrote {canonical}")
print(f"Wrote {snapshot}")
PYEOF
```

### Step 3f — Emit per-finding telemetry

For each finding emit one `mr_finding_emitted` event:

```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" mr_finding_emitted \
  "$(printf '{"slug":"%s","run_id":"%s","id":"%s","severity":"%s","category":"%s","voices_count":1,"dismissal_match":false}' \
     "$SLUG" "$RUN" "$FINDING_ID" "$FINDING_SEVERITY" "$FINDING_CATEGORY")"
```

### Step 3g — Log mr_run_end

Compute `N_DISPATCHES` before emitting `mr_run_end`. In per-chunk mode, `N_DISPATCHES` = (number of chunks) + 1 (the abstraction-only pass). In full mode, `N_DISPATCHES` = 1.

```bash
if [ "$MODE" = "per-chunk" ]; then
  CHUNK_COUNT="$(python3 -c 'import json; m=json.load(open("'"$ARCHIVE_DIR/chunks/manifest.json"'")); print(len(m["chunks"]))')"
  N_DISPATCHES=$(( CHUNK_COUNT + 1 ))
else
  N_DISPATCHES=1
fi
```

```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" mr_run_end \
  "$(python3 -c '
import json, sys
slug, run_id, total, by_sev_json, by_cat_json, voices_s, voices_f, dismissal_matches, mode, n_dispatches = \
  sys.argv[1], sys.argv[2], int(sys.argv[3]), sys.argv[4], sys.argv[5], sys.argv[6], sys.argv[7], int(sys.argv[8]), sys.argv[9], int(sys.argv[10])
by_sev = json.loads(by_sev_json)
by_cat = json.loads(by_cat_json)
print(json.dumps({
  "slug": slug,
  "run_id": run_id,
  "total_findings": total,
  "by_severity": by_sev,
  "by_category": by_cat,
  "voices_succeeded": voices_s.split(",") if voices_s else [],
  "voices_failed": voices_f.split(",") if voices_f else [],
  "dismissal_matches": dismissal_matches,
  "mode": mode,
  "n_dispatches": n_dispatches,
}))
' "$SLUG" "$RUN" "$TOTAL_FINDINGS" "$BY_SEVERITY_JSON" "$BY_CATEGORY_JSON" "$VOICES_SUCCEEDED" "$VOICES_FAILED" "$DISMISSAL_MATCHES" "$MODE" "$N_DISPATCHES")"
```

---

## Phase 4 — Final user message

`N_DISPATCHES` was computed in Step 3g above. Use it directly here.

After writing both files, output a final message to the user:

```
MR review complete.

Results: z-harness/<SLUG>/MR-REVIEW.md
  Mode: <MODE>  Dispatches: <N_DISPATCHES>
  Total findings: <N>
  P0: <N>  P1: <N>  P2: <N>  P3: <N>  P4: <N>
  Voices: <VOICES_AVAILABLE>
  Run ID: <RUN>

Delete what you don't want, then /z-implement-all --tasks=z-harness/<SLUG>/MR-REVIEW.md to apply the survivors.
```

If `DISMISSAL_MATCHES >= 3`, append after the main message:

```
Note: <N> finding(s) match prior dismissal patterns. Consider `/z-style-init --amend` to codify these preferences into STYLE.md so they are not raised again.
```

---

## End-to-end smoke test (manual)

To manually verify this command end-to-end on a small synthetic diff:

1. Create a scratch repo with `git init scratch-repo && cd scratch-repo && git commit --allow-empty -m "init"`.
2. Create a minimal `STYLE.md` with one rule:
   ```markdown
   ---

exec
/bin/zsh -lc "sed -n '220,320p' commands/z-debug.md && sed -n '1,50p' commands/z-implement-all.md" in /Users/zeke/dev/z-harness
 succeeded in 0ms:

## Summary
<2-3 sentences: what happened, impact, time-to-resolution>

## Timeline
- <T0_DEBUG>            — symptom first observed (per PROBLEM.md)
- <T_PHASE2>            — repro confirmed (per EVIDENCE.md)
- <T_ROOT_CAUSE>        — root cause identified (per ISOLATION.md final cycle)
- <T_FIX_SHIPPED>       — fix shipped (codex review passed)
- Total wall time: <delta>

## Root cause
<one-paragraph explanation. Reference PROBLEM.md, EVIDENCE.md, ISOLATION.md by section.>

## Fix
- Files changed: <from FIX.md>
- Summary: <one paragraph>

## Why we didn't catch it earlier
Pick at least one. Be honest:
- Spec gap — `<which spec section was missing or wrong>`
- Test gap — `<which test should have caught this>`
- Missing assertion — `<where>`
- Monitoring/alerting gap — `<what would have surfaced this in prod>`
- Doc gap — `<which docs/llm/ concept didn't mention this invariant>`
- Other — `<explain>`

## Action items (preventative)
- [ ] <regression test path + what it should cover>
- [ ] <SPEC.md / docs/llm/<concept>.json update with the invariant that was violated>
- [ ] <monitoring/alerting addition>
- [ ] <other follow-ups>

## Confidence
- **Root cause confidence:** <yes | partial — explain>
- **Similar bugs likely elsewhere?** <list any places worth auditing; or "none — this is localized">
```

After writing POSTMORTEM.md, ask the user via `AskUserQuestion` (before the action-item conversion prompts):

**"Run MR-style quality review on the fix diff?"**
- "Run MR-style review (Recommended)" — invoke `/z-mr-review` on the fix diff; P0/P1 findings will be appended to the post-mortem's preventative action items automatically.
- "Skip" — leave the post-mortem as-is and proceed to the action-item conversion prompts.

If user accepts:
1. Invoke `/z-mr-review` as a best-effort step (on any failure, append a note to POSTMORTEM.md and continue — do NOT halt the post-mortem):
   ```bash
   /z-mr-review --slug $Z_HARNESS_SLUG --base $PRE_FIX_SHA --force-on-trunk
   ```
   - `PRE_FIX_SHA` was captured at Phase 6 step 6 (before any fix edits). Pass it as `--base` so the diff covers exactly the fix changes.
   - `--force-on-trunk` allows the review to run on whatever branch `/z-debug` is operating from.
   - `/z-mr-review` already gates on `STYLE.md` existence and will refuse with "Run /z-style-init first." if it's missing. Do NOT try to handle this here — let it fail-fast. On failure, log "MR review skipped: STYLE.md missing" (or "MR review skipped: /z-mr-review failed — <reason>") and continue.
   - MR-REVIEW.md is written by `/z-mr-review` to the canonical path: `$(git rev-parse --show-toplevel)/z-harness/$Z_HARNESS_SLUG/MR-REVIEW.md`.

2. If `/z-mr-review` succeeds, parse `$(git rev-parse --show-toplevel)/z-harness/$Z_HARNESS_SLUG/MR-REVIEW.md` for P0/P1 findings using a defensive Python inline block (treat malformed/missing as "no findings" — never fall back to prose parsing):
   ```bash
   python3 - <<'PYEOF'
   import sys, yaml
   mr_path = "<abs_path_to_MR-REVIEW.md>"
   try:
       with open(mr_path) as f:
           raw = f.read()
       # Extract frontmatter between first --- delimiters
       parts = raw.split("---")
       if len(parts) < 3:
           raise ValueError("No valid frontmatter found")
       fm = yaml.safe_load(parts[1])
       if not isinstance(fm, dict):
           raise ValueError("Frontmatter is not a mapping")
       findings = fm.get("findings_index")
       if not isinstance(findings, list):
           print("NOTE: findings_index missing or not a list — treating as no findings")
           sys.exit(0)
       for entry in findings:
           if not isinstance(entry, dict):
               continue
           sev = entry.get("severity", "")
           if sev in ("P0", "P1"):
               fid = entry.get("id", "T-MR-???")
               title = entry.get("title", entry.get("file", "<no title>"))
               print(f"- [ ] [{fid}] {title} (from MR-REVIEW.md quality review)")
   except FileNotFoundError:
       print("NOTE: MR-REVIEW.md not found — MR review produced no output")
   except (yaml.YAMLError, ValueError, KeyError) as e:
       print(f"NOTE: MR-REVIEW.md parse error ({e}) — treating as no findings")
   PYEOF
   ```
   Collect the printed lines. If no `- [ ]` lines were printed (no P0/P1 findings or parse fallback), use a single note: `- MR quality review found no P0/P1 findings.`

3. Append the collected finding lines (or the "no findings" note) to POSTMORTEM.md's "Action items (preventative)" section.

After writing, ask the user via `AskUserQuestion`:
- "Convert action items into follow-up tasks?" → If yes, the orchestrator appends them to a designated `TASKS.md` (user picks which slug, or creates a fresh `audit-<topic>` slug) and the user can later `/z-implement-all` them.
- "Convert regression-test action items into a /z-test follow-up" → For each action item shaped like `Add regression test ...`, record the invariant + failure-class + target-file hint into `z-harness/<slug>/test-followups.md` (a flat list of seed entries shaped like Phase 2 drafts in `/z-test`). On the next `/z-plan` + `/z-test` cycle (or if the user re-runs `/z-test` on this same slug after seeding follow-up production tasks), these become mandatory TESTS.md entries. Closes the post-mortem loop automatically — the next plan run cannot ship without the regression test the post-mortem flagged.
- "Just record and move on" → leave POSTMORTEM.md as a standalone record.

Push-notify: "Post-mortem ready: `z-harness/<slug>/POSTMORTEM.md`. Action items: <N> (converted to tasks: <yes/no>)."

## Phase 8 — Finalize

1. Log:
---
description: Orchestrate implementation of ALL pending tasks in z-harness/TASKS.md, spawning a fresh implementer subagent per task and a codex-reviewer per task. Halts on blockers, retries once on review failure, push-notifies user on every gate.
---

You are the **z-harness `/z-implement-all`** orchestrator. Your job is to drive the task queue to completion without losing the per-task fresh-context guarantee. You do not implement code yourself — you delegate each task to a fresh `implementer` subagent and each review to a fresh `codex-reviewer` subagent.

Notification policy: read env `Z_HARNESS_NOTIFY` (default `approval_only`).

## Flags

- `--ack` — Override the SHARED-CONCERNS.md ack-gate when iterating a tree-rooted plan produced by `/z-plan-split`. Equivalent to manually flipping `acknowledged: true` in the file. No-op for legacy single-slug plans.
- `--force-partial` — Override the partial-tree gate when iterating a tree-rooted plan whose SHARED-CONCERNS.md has `partial_tree: true` (i.e. one or more clusters failed planning). Implies the user accepts that overlap detection is a lower bound on a partial tree. No-op for legacy single-slug plans.
- `--tasks=<path>` — Override the default tasks file location. By default the orchestrator reads `$BASE/TASKS.md` (discovered via slug detection in Setup step 2). When `--tasks=<path>` is provided, that file is used as the task queue instead. `<path>` may be repo-relative (e.g. `z-harness/mr-style-reviewer/MR-REVIEW.md`) or absolute. `$BASE` is derived from the directory containing the tasks file — e.g. `--tasks=z-harness/mr-style-reviewer/MR-REVIEW.md` sets `BASE=z-harness/mr-style-reviewer` so SPEC.md, PLAN.md, and archive paths resolve correctly. Slug detection (step 2) is skipped when `--tasks` is supplied; tree-rooted and MANIFEST validation are bypassed for the single overridden file. `--ack` and `--force-partial` are no-ops when `--tasks` is active.

Both `--ack` and `--force-partial` are inert for legacy (single-slug) plans and only affect tree-rooted discovery in Setup step 2.

## Setup

1. `cd` to the repo root. Abort if no `z-harness/` directory.

   **`--tasks` fast path.** If the user invoked with `--tasks=<path>`, resolve the path to absolute and derive `BASE` as its parent directory:
   ```bash
   TASKS_FILE="$(realpath <path>)"           # make absolute
   BASE="$(dirname "$TASKS_FILE")"           # e.g. /abs/z-harness/mr-style-reviewer
   Z_HARNESS_SLUG="$(basename "$BASE")"      # e.g. mr-style-reviewer (for logging only)
   ```
   Skip steps 2 (slug discovery) and 2a–2d (MANIFEST/SHARED-CONCERNS validation) entirely. Jump directly to step 3, binding `BASE` and the tasks file as derived above. `--ack` and `--force-partial` are no-ops in this mode.

   **Example:** `/z-implement-all --tasks=z-harness/mr-style-reviewer/MR-REVIEW.md` reads task blocks from `MR-REVIEW.md` (e.g. `T-MR-001`, `T-MR-002`, …) and resolves SPEC.md at `z-harness/mr-style-reviewer/SPEC.md`.

2. **Discover plan slug.** Multiple plans may coexist under `z-harness/<slug>/`. A `<slug>/` may be either a **legacy single-slug plan** (contains `TASKS.md` directly) or a **tree-rooted plan** produced by `/z-plan-split` (contains `MANIFEST.md` + per-cluster subdirectories, each with its own `TASKS.md`):

   **2a. Enumerate candidates.**
   - For each subdir of `z-harness/`: classify as `tree-rooted` if `<slug>/MANIFEST.md` exists, else `legacy` if `<slug>/TASKS.md` exists, else skip.
   - Also check for the legacy flat layout (`z-harness/TASKS.md` directly).
   - Zero candidates → tell user to run `/z-plan` first; abort.
   - One candidate → use it.
   - Multiple candidates → `AskUserQuestion` to pick. Mixed legacy + tree-rooted slugs are allowed in the same `/z-implement-all` invocation: the user picks one, validation/expansion below depends on its kind.
   - Export `Z_HARNESS_SLUG=<slug>` (or leave unset for legacy flat).

   **2b. If chosen slug is tree-rooted (has `<slug>/MANIFEST.md`), validate in order:**

   Parse MANIFEST.md once: extract (i) the YAML frontmatter (`status`, `total_clusters`, `clusters_ready`), (ii) the Clusters table (each row: `ID`, `Path`, `Status`, …), and (iii) the `## Run order` section (an ordered list of cluster IDs). The `Path` column is canonical — every downstream BASE binding in 2c reads it from there; do **not** synthesize paths from `<slug>/<cluster-id>/`.

   1. **Nested-MANIFEST gate (depth invariant).** One-level recursion is invariant per `/z-plan-split` SPEC. Check `find z-harness/$Z_HARNESS_SLUG/*/ -name MANIFEST.md` (excluding the root MANIFEST). If any are found, halt with `tree_depth_exceeded` event:
      ```bash
      bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "orchestration" tree_depth_exceeded \
        "$(printf '{"slug":"%s","nested_paths":%s}' "$Z_HARNESS_SLUG" "$NESTED_JSON_ARRAY")"
      ```
      Push-notify and abort. No override — a tree-of-trees is structurally unsupported in v1.

exec
/bin/zsh -lc "rg -n \"--tasks=MR-REVIEW|z-harness/\\"'$|--global|extract-dismissals.py|MR-REVIEW.md|style_amend_complete|style_init_complete|push notification|Citation:" docs/human docs/llm README.md commands/z-style-init.md commands/z-mr-review.md' in /Users/zeke/dev/z-harness
 exited 2 in 0ms:
rg: unrecognized flag --tasks

exec
/bin/zsh -lc "sed -n '520,760p' commands/z-style-init.md" in /Users/zeke/dev/z-harness
 succeeded in 0ms:
   - category 'test-noise' → ## Tests
   - category 'abstraction' → ## Project-specific
   If uncertain, use ## Project-specific.
3. The rule must encode the intent behind the dismissals — why were these findings repeatedly rejected? What convention should the reviewer learn to stop flagging?
4. Return each proposed rule as a standalone markdown block preceded by a comment indicating which cluster it addresses and which STYLE.md section it belongs to.

Format your response as:

<!-- Cluster: <cluster_id> → Section: <section heading> -->
### <RULE-ID>: <short rule title>
<rule prose>
Rationale: <one sentence>

(one block per cluster, separated by blank lines)

Current STYLE.md:
<CURRENT_STYLE_MD>

Dismissal clusters (JSON):
<CLUSTERS as JSON>"
)
```

Capture the agent return as `PROPOSED_RULES_RAW`. If the agent errors or returns output that cannot be parsed into at least one valid `<!-- Cluster: ... → Section: ... -->` / rule-block pair, log:
```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" style_amend_propose_failed \
  "$(printf '{"reason":"%s"}' "<error description>")"
```
Then exit with the message:
> Could not generate rule proposals. Check the agent output and retry.

Parse `PROPOSED_RULES_RAW` into a list `PROPOSED_RULES`:
- Each entry: `{cluster_id, section, rule_id, rule_markdown}` extracted from the comment + rule block pairs.

Log phase end:
```bash
WALL_MS=$(( $(date +%s%3N) - T0 ))
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" phase_end \
  "$(printf '{"phase":"MB-3","name":"propose-amendments","wall_ms":%d,"n_proposed":%d}' \
     "$WALL_MS" "${#PROPOSED_RULES[@]}")"
```

---

### Phase MB-4 — User review

**Goal:** let the user accept or reject each proposed rule.

Record `T0=$(date +%s%3N)`.

Log `user_wait_start`:
```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" user_wait_start \
  '{"phase":"MB-4","reason":"rule-review"}'
```

For each cluster / proposed rule, send a **separate `AskUserQuestion` call** — one cluster per call, sequentially. Do not batch multiple clusters into a single `AskUserQuestion`.

```
Proposed new rule for cluster <cluster_id> (category: <category>, <member_count> dismissed findings):

Representative dismissed finding:
  "<representative_snippet>"

Proposed rule (for <section>):
  <rule_markdown, indented 2 spaces>

Options:
  add-as-drafted     — append this rule to STYLE.md as written above
  reject             — skip this rule; do not add it
```

> **Implementation note (v1):** "add-with-edits" interactive free-text flow is deferred to v2. In v1, user can reject and manually edit STYLE.md afterward if they want a customized version of the rule. This is a known limitation flagged for v2 follow-up.

Collect responses. Track `APPROVED_RULES` (all entries where user chose `add-as-drafted`).

Log `user_wait_end`:
```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" user_wait_end \
  "$(printf '{"phase":"MB-4","wall_ms":%d,"approved":%d,"rejected":%d}' \
     "$USER_WAIT_MS_THIS_PHASE" "${#APPROVED_RULES[@]}" \
     "$(( N_CLUSTERS - ${#APPROVED_RULES[@]} ))")"
```

If no rules approved, exit:
```
No rules approved. STYLE.md unchanged.
```
Log `style_amend_complete {clusters: N_CLUSTERS, rules_added: 0}` and exit.

Log phase end:
```bash
WALL_MS=$(( $(date +%s%3N) - T0 ))
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" phase_end \
  "$(printf '{"phase":"MB-4","name":"user-review","wall_ms":%d,"user_wait_ms":%d}' \
     "$WALL_MS" "$USER_WAIT_MS_THIS_PHASE")"
```

---

### Phase MB-5 — Append approved rules to STYLE.md

**Goal:** write approved rules to the correct sections in `./STYLE.md`.

Record `T0=$(date +%s%3N)`.

For each approved rule in `APPROVED_RULES`:
1. Identify the target section heading (e.g. `## Error handling`).
2. Find the last rule block in that section (last `### <PREFIX>-NNN:` heading). Verify the proposed rule ID (`EH-005` etc.) is indeed the next free ID. If a collision is detected (the ID already exists in the file), increment the ID number until a free one is found.
3. Append the rule markdown immediately after the last rule block in that section (before the next `##`-level heading or end of file).

Use the Edit tool to append each rule to the correct section. Do not restructure or reformat the existing STYLE.md content.

After writing all approved rules, update the STYLE.md frontmatter field `source` to include `amend` if not already present. Specifically:
- If `source:` currently reads `capture`, change to `capture,amend`.
- If it already contains `amend`, leave unchanged.
- For any other value, append `,amend`.

(Do not change `schema_version` or any other frontmatter field.)

Count `N_RULES_ADDED = len(APPROVED_RULES)`.

Log phase end:
```bash
WALL_MS=$(( $(date +%s%3N) - T0 ))
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" phase_end \
  "$(printf '{"phase":"MB-5","name":"append-rules","wall_ms":%d,"rules_added":%d}' \
     "$WALL_MS" "$N_RULES_ADDED")"
```

---

### Mode B completion

Log `style_amend_complete`:
```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" style_amend_complete \
  "$(printf '{"clusters":%d,"rules_added":%d}' "$N_CLUSTERS" "$N_RULES_ADDED")"
```

Push-notify (if `Z_HARNESS_NOTIFY` ≠ `off`):
> STYLE.md amended: <N_RULES_ADDED> rule(s) added across <K> section(s) (from <N_CLUSTERS> dismissal clusters). Run `/z-mr-review` to see new findings against the updated guide.

---

## Operating principles

- **Capture before drafting.** The style guide is grounded in observed code, not invented conventions.
- **User confirms the file list.** The Capture set is shown and confirmed before reading file content (prevents god-objects from anchoring the guide).
- **Cross-LLM critique is mandatory.** Both consultants run in parallel; findings applied before user sees the draft.
- **Refuse without STYLE.md gate.** If STYLE.md already exists in Mode A, refuse immediately — do not overwrite silently. In Mode B, refuse if STYLE.md does NOT exist.
- **Log everything** via `scripts/log-event.sh`.
- **Never read `docs/llm/*.json` from main thread.** Dispatch `doc-fetcher` if INDEX.json exists and context is needed.

exec
/bin/zsh -lc 'rg -n -- "--tasks=MR-REVIEW|--tasks=z-harness|--global|extract-dismissals.py|Citation:|style_amend_complete|style_init_complete|push notification|MR-REVIEW.md" docs/human docs/llm README.md commands/z-style-init.md commands/z-mr-review.md' in /Users/zeke/dev/z-harness
 succeeded in 0ms:
README.md:39:- **`/z-mr-review`** — Multi-LLM code-quality review of the current branch diff against `STYLE.md`. Fans out to Claude, Codex, and Gemini; deduplicates and ranks findings P0–P4; writes `z-harness/<slug>/MR-REVIEW.md` in `TASKS.md`-compatible shape. Never blocks — delete findings you don't want, then run `/z-implement-all --tasks=MR-REVIEW.md`. Targets five categories: abstraction, defensive-bloat, test-noise, hygiene, and style-drift. Distinct from `/z-audit`, which gates correctness.
README.md:129:- `Z_HARNESS_NOTIFY` — `off` | `approval_only` (default) | `all`. Controls push notifications.
README.md:232:│   ├── extract-dismissals.py
commands/z-mr-review.md:151:### Step 1e — Archive any existing MR-REVIEW.md
commands/z-mr-review.md:153:If `z-harness/<slug>/MR-REVIEW.md` already exists, archive it before overwriting:
commands/z-mr-review.md:156:EXISTING="$SLUG_DIR/MR-REVIEW.md"
commands/z-mr-review.md:159:  while [ -f "$ARCHIVE_DIR/MR-REVIEW.md.previous-$N" ]; do
commands/z-mr-review.md:162:  cp "$EXISTING" "$ARCHIVE_DIR/MR-REVIEW.md.previous-$N"
commands/z-mr-review.md:332:Invoke `scripts/extract-dismissals.py` to compute prior dismissal signatures:
commands/z-mr-review.md:335:if ! python3 "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/extract-dismissals.py" \
commands/z-mr-review.md:510:## Phase 3 — Parse agent return(s) and write MR-REVIEW.md
commands/z-mr-review.md:617:### Step 3e — Write MR-REVIEW.md
commands/z-mr-review.md:619:Build the full MR-REVIEW.md content using this exact structure:
commands/z-mr-review.md:643:Findings ranked P0-P4. **Delete any finding you don't want fixed.** Then `/z-implement-all --tasks=z-harness/<SLUG>/MR-REVIEW.md`.
commands/z-mr-review.md:653:  **Citation:** <citation or "none">
commands/z-mr-review.md:682:1. `z-harness/<SLUG>/MR-REVIEW.md` — canonical (overwrites any prior file)
commands/z-mr-review.md:683:2. `<ARCHIVE_DIR>/MR-REVIEW.md` — snapshot (identical content)
commands/z-mr-review.md:695:canonical = os.path.join(slug_dir, 'MR-REVIEW.md')
commands/z-mr-review.md:696:snapshot  = os.path.join(archive_dir, 'MR-REVIEW.md')
commands/z-mr-review.md:765:Results: z-harness/<SLUG>/MR-REVIEW.md
commands/z-mr-review.md:772:Delete what you don't want, then /z-implement-all --tasks=z-harness/<SLUG>/MR-REVIEW.md to apply the survivors.
commands/z-mr-review.md:824:   - `z-harness/feature-smoke-test/MR-REVIEW.md` is created with valid YAML frontmatter, at least one finding, `T-MR-001` block present, and the "Delete what you don't want" footer line.
commands/z-mr-review.md:835:   - `archive/$RUN/MR-REVIEW.md` exists and has valid frontmatter.
commands/z-mr-review.md:836:   - MR-REVIEW.md frontmatter shows `mode: per-chunk` in the run_end log.
commands/z-mr-review.md:838:   - MR-REVIEW.md contains both per-chunk category findings (defensive-bloat, test-noise, hygiene, style-drift) and possibly abstraction findings from the abstraction-only pass.
commands/z-mr-review.md:849:- **Archive before overwrite.** Existing `MR-REVIEW.md` is always archived before being replaced.
commands/z-style-init.md:345:Log `style_init_complete`:
commands/z-style-init.md:348:bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" style_init_complete \
commands/z-style-init.md:391:   If the branch is empty/detached or `SLUG_DIR` does not exist as a directory, use the first available `z-harness/*/` directory (via `ls -d z-harness/*/`). If no `z-harness/*/` directory exists at all, `SLUG_DIR` can be any valid path string — the `--global` flag causes `extract-dismissals.py` to scan all slugs, so a missing slug-dir simply yields an empty result set.
commands/z-style-init.md:405:python3 scripts/extract-dismissals.py "${SLUG_DIR}" --max-runs 10 --global
commands/z-style-init.md:409:> Could not extract dismissal signatures (extract-dismissals.py failed). Check that `scripts/extract-dismissals.py` exists and the z-harness archive structure is intact.
commands/z-style-init.md:416:Log `style_amend_complete {clusters: 0, rules_added: 0}` and exit cleanly. Do not proceed to Phase MB-2.
commands/z-style-init.md:474:Log `style_amend_complete {clusters: 0, rules_added: 0}` and exit.
commands/z-style-init.md:608:Log `style_amend_complete {clusters: N_CLUSTERS, rules_added: 0}` and exit.
commands/z-style-init.md:654:Log `style_amend_complete`:
commands/z-style-init.md:656:bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" style_amend_complete \
docs/llm/INDEX.json:11:        "scripts/extract-dismissals.py"
docs/llm/INDEX.json:23:      "summary": "Multi-LLM code-quality reviewer for branch diffs; ranks P0-P4, never blocks, writes TASKS.md-shape MR-REVIEW.md."
docs/llm/INDEX.json:29:        "scripts/extract-dismissals.py"
docs/llm/commands.json:35:      "summary": "Orchestrates multi-LLM code-quality review of a branch diff; writes P0-P4 findings to MR-REVIEW.md."
docs/llm/scripts.json:6:    "scripts/extract-dismissals.py",
docs/llm/scripts.json:16:      "file": "scripts/extract-dismissals.py",
docs/llm/scripts.json:18:      "symbol": "extract-dismissals.py",
docs/llm/scripts.json:20:      "summary": "Computes dismissed finding signatures from consecutive MR-REVIEW.md archive snapshots; shared by /z-mr-review and /z-style-init --amend."
docs/llm/mr-reviewer.json:8:    "scripts/extract-dismissals.py"
docs/llm/mr-reviewer.json:27:      "file": "scripts/extract-dismissals.py",
docs/llm/mr-reviewer.json:29:      "symbol": "extract-dismissals.py",
docs/llm/mr-reviewer.json:31:      "summary": "Computes dismissed-finding signatures by diffing consecutive MR-REVIEW.md archive snapshots."
docs/llm/mr-reviewer.json:34:  "description": "The MR-reviewer feature provides code-quality review (not correctness review) for branch diffs. It targets five categories: abstraction, defensive-bloat, test-noise, hygiene, and style-drift. Findings are ranked P0-P4 and written to z-harness/<slug>/MR-REVIEW.md in TASKS.md-compatible shape. The command never blocks — users triage by deleting unwanted findings. Three LLM voices (Claude, Codex, Gemini) are fanned out in parallel; findings are deduplicated by (file, category, normalized_text) signature and tagged with which voices raised them. Voice consensus promotes findings one tier; minority voice demotes one tier; P0 is exempt from both adjustments.",
docs/llm/mr-reviewer.json:38:    "Orchestrator writes MR-REVIEW.md and the archive snapshot, not the agent. Agent returns structured JSON findings only.",
docs/llm/mr-reviewer.json:40:    "extract-dismissals.py is the single source of truth for dismissal signatures; both /z-mr-review and /z-style-init --amend use the same script.",
docs/human/style-init.md:42:Approved STYLE.md is written to the repo root. The `style_init_complete` event is logged and a push notification is sent.
docs/human/style-init.md:50:1. **Scan archives.** `scripts/extract-dismissals.py` walks `z-harness/*/archive/*/MR-REVIEW.md` snapshots (default: most recent 10 runs, `--global` scans all slugs) to identify dismissed finding signatures.
docs/human/style-init.md:55:The `style_amend_complete` event is logged with cluster counts. The `schema_version` frontmatter field is unchanged by amend.
docs/human/style-init.md:69:Rule IDs are **append-only and never reused**. When a rule is retired, it is replaced by a tombstone comment (`<!-- EH-003 retired 2026-06-01 -->`) so that historical `mr-reviewer` citations remain traceable. The `mr-reviewer` agent cites rules by their ID (e.g. `Citation: EH-001`).
docs/llm/style-init.json:7:    "scripts/extract-dismissals.py"
docs/llm/style-init.json:19:  "description": "z-style-init creates and maintains the project STYLE.md that /z-mr-review requires. Bootstrap mode (no --amend) uses a 'Capture' approach: it identifies the top 5 most idiomatic existing source files (heuristic prefilter → Sonnet ranking → user confirmation gate), reads them, asks up to 4 interview questions about error handling / testing / comments / project specifics, drafts STYLE.md, critiques it via codex+gemini consultants, then asks for user approval before writing. Amend mode (--amend) reads recent archive dismissal patterns via extract-dismissals.py, clusters similar dismissals (Jaccard >= 0.6), proposes new STYLE.md rules per cluster, and lets the user accept/edit/reject each proposed rule.",
docs/llm/style-init.json:26:    "extract-dismissals.py is shared with /z-mr-review — same script, same output schema."
docs/llm/style-init.json:30:    "Amend uses --global flag on extract-dismissals.py to scan all slugs (not just the current slug), giving a cross-plan dismissal view.",
docs/llm/style-init.json:48:    "style_init_complete",
docs/llm/style-init.json:49:    "style_amend_complete"
docs/human/mr-reviewer.md:4:> Covers source: commands/z-mr-review.md, agents/mr-reviewer.md, scripts/extract-dismissals.py
docs/human/mr-reviewer.md:10:The review fans out to all available LLM voices (Claude Sonnet inline, Codex via `codex-consultant`, Gemini via `gemini-consultant`). Findings are deduplicated, tagged by which voices raised them, ranked P0–P4, and written to `z-harness/<slug>/MR-REVIEW.md` in `TASKS.md`-compatible shape. The command **never blocks** — you triage by deleting unwanted findings from MR-REVIEW.md, then run `/z-implement-all --tasks=MR-REVIEW.md` on survivors.
docs/human/mr-reviewer.md:54:Every run archives a snapshot of MR-REVIEW.md at `z-harness/<slug>/archive/<run-id>/MR-REVIEW.md`. The `scripts/extract-dismissals.py` utility compares consecutive run snapshots to identify findings the user deleted. When ≥ 3 findings in a run match prior dismissal patterns, the command suggests `/z-style-init --amend` to codify the pattern into STYLE.md so future reviews don't raise it again.
docs/human/mr-reviewer.md:68:| `mr_run_end` | All findings written to MR-REVIEW.md |
docs/human/mr-reviewer.md:78:After committing a fix, `/z-debug`'s post-mortem phase offers (via `AskUserQuestion`) to run `/z-mr-review` on the fix diff. If accepted, the `mr-reviewer` agent runs with the debug run's slug. P0 and P1 findings are automatically appended to the post-mortem's "Preventative actions" section as bullet items, cited by `T-MR-NNN` ID. P2–P4 findings stay in MR-REVIEW.md only. See `commands/z-debug.md` for the integration details.
docs/human/STYLE-md-schema.md:62:Rules are **append-only and never reused**. When a rule is retired, it is replaced by a short tombstone comment (`<!-- EH-003 retired 2026-06-01 -->`) so that old `mr-reviewer` citations remain traceable. The `mr-reviewer` agent cites rules by their ID (e.g. `Citation: EH-001`).

codex
- **major** — `README.md:39` and `docs/human/mr-reviewer.md:10` tell users to run `/z-implement-all --tasks=MR-REVIEW.md`, but the generated file lives at `z-harness/<slug>/MR-REVIEW.md` and the command’s own implementation/examples expect that repo-relative path. Fix both docs to use `/z-implement-all --tasks=z-harness/<slug>/MR-REVIEW.md`.

- **major** — `docs/human/style-init.md:52` and `docs/llm/style-init.json` describe amend-mode review as accept/edit/reject, but `commands/z-style-init.md` v1 only supports `add-as-drafted` or `reject` and explicitly defers add-with-edits to v2. Fix the docs to state the current two-option behavior and mention manual editing after rejection if needed.
2026-05-24T00:33:39.302000Z ERROR codex_core::session: failed to record rollout items: thread 019e5765-d212-7221-a3fd-d9b0d4526e8b not found
tokens used
93,967
- **major** — `README.md:39` and `docs/human/mr-reviewer.md:10` tell users to run `/z-implement-all --tasks=MR-REVIEW.md`, but the generated file lives at `z-harness/<slug>/MR-REVIEW.md` and the command’s own implementation/examples expect that repo-relative path. Fix both docs to use `/z-implement-all --tasks=z-harness/<slug>/MR-REVIEW.md`.

- **major** — `docs/human/style-init.md:52` and `docs/llm/style-init.json` describe amend-mode review as accept/edit/reject, but `commands/z-style-init.md` v1 only supports `add-as-drafted` or `reject` and explicitly defers add-with-edits to v2. Fix the docs to state the current two-option behavior and mention manual editing after rejection if needed.
