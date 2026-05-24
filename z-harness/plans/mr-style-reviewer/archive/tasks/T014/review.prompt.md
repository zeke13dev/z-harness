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
