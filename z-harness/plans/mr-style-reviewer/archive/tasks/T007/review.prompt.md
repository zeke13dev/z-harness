You are reviewing code that Claude just wrote for task T007: Multi-voice fan-out in agents/mr-reviewer.md (Codex + Gemini parallel dispatch, consensus tier-bump).

ACCEPTANCE CRITERIA:
1. Dispatches codex-consultant + gemini-consultant in parallel (single message, multiple Agent() calls)
2. MODE: mr-review with JSON contract (severity, category, file, line_start, line_end, title, detail, citation)
3. Parse failure → log mr_voice_failed, continue, no retry
4. Merge: dedup by (file, category, normalized_text); tag voices: [...]
5. Tier-bump: 3/3 promote (P0 stays), 1/3 demote (P0 stays — never demote P0), single-available no bump
6. voices_used top-level + per-finding voices in JSON
7. 3-line additions to codex-consultant.md + gemini-consultant.md permitted

SPEC EXCERPT (from z-harness/mr-style-reviewer/SPEC.md — consensus tier-bump rules):
- If `len(voices_available) >= 2` AND `len(finding.voices) == len(voices_available)`: **promote one tier** (P4→P3, P3→P2, P2→P1, P1→P0; **P0 stays P0**).
- If `len(voices_available) >= 2` AND `len(finding.voices) == 1`: **demote one tier** (P1→P2, P2→P3, P3→P4, P4 stays P4; **P0 stays P0 — never demote P0**).
- If `len(voices_available) == 1`: no bump in either direction (single-voice mode, no consensus signal).

DEDUP NORMALIZATION (from SPEC.md Step 5):
To normalize the text: concatenate `title` + `" "` + `detail`, lowercase, collapse internal whitespace to a single space, strip leading/trailing punctuation.

DIFF (primary artifact):

```patch
diff --git a/agents/mr-reviewer.md b/agents/mr-reviewer.md
new file mode 100644
index 0000000..1461c7c
--- /dev/null
+++ b/agents/mr-reviewer.md
@@ -0,0 +1,249 @@
+---
+name: mr-reviewer
+description: Multi-LLM code-quality reviewer for branch diffs. Assumes correctness; targets AI-shaped and human-shaped slop. Ranks P0-P4, never blocks, never finds correctness bugs (those belong to codex-reviewer).
+tools: Bash, Read, Grep, Glob, Edit, Write, Agent
+model: sonnet
+---
+
+You review a branch diff for code quality — not correctness. You assume the code is correct and does what the author intended. Your job is to catch AI-shaped slop, defensive bloat, test noise, abstraction failures, and style drift. You rank findings P0–P4 and return them as a fenced JSON block plus a `## Summary` markdown block. You never write MR-REVIEW.md yourself — the orchestrator does that from your return.
+
+## Hardcoded principles (apply independent of STYLE.md)
+
+- **Assume correctness.** Do not raise correctness bugs. Those belong to `codex-reviewer`. If you spot one, note it in a one-line `## Cross-dimension note` at the end and move on.
+- **Every added line must justify its weight.** Relative to the existing abstractions, local style, and the behavioral surface it supports, gratuitous diff growth is suspect; necessary growth is not. When in doubt, P4 — not P0.
+- **When flagging abstraction, cite the existing duplicate by file:line.** Without a citation you have an opinion; with a citation you have a finding.
+
+## Severity rubric
+
+...
+
+### Step 4 — Multi-voice dispatch (when voices_available includes codex or gemini)
+
+When `voices_available` contains voices beyond `claude`, dispatch the non-Claude voices in parallel — a single message with one `Agent()` call per non-Claude voice. Claude's inline findings from Step 3 are already in hand; this step collects the others.
+
+**Consultant prompt shape (same for both codex-consultant and gemini-consultant):**
+
+```
+Agent(
+  subagent_type="codex-consultant",   # or "gemini-consultant"
+  description="Codex MR-review voice for <slug>",
+  prompt="MODE: mr-review
+active_categories: [<comma-separated active category names>]
+run_id: <run_id>
+
+STYLE.md:
+<full contents of style_path>
+
+DIFF:
+<full contents of diff_path>
+
+Return findings as a fenced ```json block with EXACTLY this schema — no other keys:
+{\"findings\": [{\"severity\": \"P0|P1|P2|P3|P4\", \"category\": \"<one of: defensive-bloat|test-noise|abstraction|hygiene|style-drift>\", \"file\": \"<relative path from repo root>\", \"line_start\": <integer or null>, \"line_end\": <integer or null>, \"title\": \"<short one-line title>\", \"detail\": \"<prose explanation — what is wrong and why it matters>\", \"citation\": \"<STYLE.md:EH-001 or file:line for abstraction, or null>\"}]}
+
+Constraints:
+- Do NOT raise correctness bugs (those belong to codex-reviewer).
+- Only raise style-drift findings for rules present in STYLE.md (cite by rule ID).
+- Only raise abstraction findings with a concrete file:line citation for the existing duplicate.
+- category must be exactly one of the five named values above."
+)
+```
+
+Dispatch all non-Claude voices in one message (parallel `Agent()` calls). Do not wait for one before dispatching the next.
+
+**Parse failure handling:** for each voice's return, attempt to extract the fenced `json` block (look for a code fence tagged `json` containing a `findings` key). If the parse fails for any reason, log `mr_voice_failed {voice: "<name>", reason: "malformed_json"}` via:
+
+```bash
+bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$run_id" mr_voice_failed \
+  "$(printf '{"voice":"%s","reason":"malformed_json"}' "<voice_name>")"
+```
+
+Then skip that voice's findings entirely — do not retry, do not fall back to a partial parse.
+
+Track:
+- `voices_succeeded`: list of voices that returned parseable JSON (`claude` always included; external voices only if parse succeeded).
+- `voices_failed`: list of voices that returned malformed JSON.
+
+### Step 5 — Merge findings and apply dismissal-pattern matching
+
+You have findings from Step 3 (Claude inline) and Step 4 (any additional voices). Merge them as follows:
+
+**Dedup:** identify findings with the same `(file, category, normalized_text)` signature. To normalize the text: concatenate `title` + `" "` + `detail`, lowercase, collapse internal whitespace to a single space, strip leading/trailing punctuation. Keep one finding per signature. Set `voices: [<list of all voices that raised this finding>]` on the merged finding — if both Claude and Codex raised a finding with the same signature, the merged finding's `voices` is `["claude", "codex"]`.
+
+**Consensus tier-bump:** applied after dedup, using the per-finding `voices` list and the overall `voices_available` from the input:
+- If `len(voices_available) >= 2` AND `len(finding.voices) == len(voices_available)`: **promote one tier** (P4→P3, P3→P2, P2→P1, P1→P0; **P0 stays P0**).
+- If `len(voices_available) >= 2` AND `len(finding.voices) == 1`: **demote one tier** (P1→P2, P2→P3, P3→P4, P4 stays P4; **P0 stays P0 — never demote P0**).
+- If `len(voices_available) == 1`: no bump in either direction (single-voice mode, no consensus signal).
+
+**Dismissal-pattern match:** for each finding, compute a normalized snippet = lowercase of `detail`, whitespace collapsed, leading/trailing punctuation stripped. Compare to each `normalized_snippet` in `dismissed_signatures.json` using Jaccard token-overlap after removing stopwords (`the, a, an, this, that, is, are, in, on, of, to, for, and, or, with, by`). If Jaccard overlap ≥ 0.6 AND the `file` and `category` match:
+- Append `[previously-dismissed-pattern]` to the `detail` field.
+- If severity is P1–P4: demote one tier (P1→P2, P2→P3, P3→P4, P4 stays P4).
+- If severity is P0: keep severity as P0; tag only. **Never demote a P0.**
+
+**NOTE: Dismissal-pattern matching is added in T010. Until then, skip the Jaccard calculation entirely — treat `dismissed_signatures.json` as if it were empty regardless of content.** The `dismissal_pattern_matches` count in the Summary should be `0`.
+
+### Step 6 — Return findings
+
+...

**JSON schema:**
```json
{
+  "findings": [
+    {
+      "severity": "P0|P1|P2|P3|P4",
+      "category": "defensive-bloat|test-noise|abstraction|hygiene|style-drift",
+      "file": "<relative path from repo root>",
+      "line_start": <integer or null>,
+      "line_end": <integer or null>,
+      "title": "<short one-line title>",
+      "detail": "<prose explanation — what is wrong and why it matters>",
+      "citation": "<STYLE.md:EH-001 for style-drift, or file:line for abstraction citing the duplicate, or null>",
+      "voices": ["<list of voices that raised this finding, e.g. claude, codex, gemini>"]
+    }
+  ],
+  "voices_used": ["<list of all voices that successfully contributed findings>"]
+}
+```

...

**Summary block:**
```
## Summary
STATUS: ok
total_findings: N
by_severity: P0=N P1=N P2=N P3=N P4=N
by_category: defensive-bloat=N test-noise=N abstraction=N hygiene=N style-drift=N
voices_succeeded: [<actual list, e.g. claude, codex>]
voices_failed: [<actual list, e.g. gemini>]
dismissal_pattern_matches: 0
```

diff --git a/agents/codex-consultant.md b/agents/codex-consultant.md
index 1758b60..5086707 100644
--- a/agents/codex-consultant.md
+++ b/agents/codex-consultant.md
@@ -44,6 +44,7 @@ The caller signals a mode via a `MODE: <name>` prefix in the prompt. Handle each
  Codex must NOT recommend an approach. Research is terrain-mapping, not direction-picking. The prompt must explicitly instruct Codex to omit any recommendation.
 - **`doc-audit`** (`/z-maintain-docs --audit`): caller hands you a proposed human-tier markdown + LLM-tier JSON update + the source files + prior doc (if any). Ask Codex: does the proposed doc accurately describe the source files? List specific claims that don't match. List concepts the doc should cover but doesn't.
 - **`test-cases`** (Phase 3 of `/z-test`): caller hands you SPEC.md + PLAN.md + TASKS.md + a draft list of test cases + user-stated bug-class concerns + the source files referenced by the drafts. Ask Codex: (1) for each draft, is the assertion strong enough to catch a real bug or a tautology — if weak, propose a stronger assertion; (2) which SPEC invariants have no corresponding test (propose entries); (3) what dangerous bug classes specific to this codebase domain (trading: notional sign, fill-quantity sign, time-zone-aware bar boundaries, feature schema alignment between strategy and pipeline) are uncovered; (4) flag any draft that is mechanically trivial and should be dropped. Return structured: per-draft critique (keep | strengthen | drop), then a list of NEW test entries the caller missed.
+- **`mr-review`** (Step 4 of `mr-reviewer`): caller hands you active categories, full STYLE.md contents, and the full diff. Ask Codex to find quality issues (not correctness bugs) in the diff, citing STYLE.md rule IDs for style-drift findings and file:line for abstraction findings. Return RAW — the caller expects a fenced `json` block with `{"findings": [...]}` matching the schema in the prompt; do not apply the standard wrapper.
 
  ## Building the prompt to Codex
 
@@ -64,6 +65,7 @@ The caller gives you the input artifact + file pointers. You must:
       - `research-review`: "Critique this research draft with exactly three sections: (1) Gaps — things the draft missed, (2) Errors — claims that appear wrong, (3) Missing constraints — constraints not captured. Do NOT recommend an approach; research is terrain-mapping, not direction-picking."
       - `doc-audit`: "Does the proposed doc accurately describe the source files? List specific claims that don't match. List concepts the doc should cover but doesn't."
       - `test-cases`: "(1) For each draft test, is the assertion strong enough to catch a real bug or is it a tautology — if weak, propose a stronger assertion. (2) Which SPEC invariants have no corresponding test (propose entries)? (3) What dangerous bug classes specific to this codebase domain are uncovered? (4) Flag any draft that is mechanically trivial and should be dropped. Return structured: per-draft critique (keep | strengthen | drop), then a list of NEW test entries the caller missed."
+     - `mr-review`: Pass through the prompt verbatim to Codex. The prompt already contains the full ask and output schema. Return the fenced `json` block from Codex's response unchanged.
 
  ## Returning to the caller
 
@@ -84,7 +86,7 @@ For `bundled-decisions`, `plan-review`, `light-fix`, `debug-hypotheses`, `doc-a
  <short quote>
  ```
 
-For `brainstorm` and `research-review`, return Codex's raw section block unchanged — do NOT apply the wrapper above. For `brainstorm` that means the five-section block (Framing / Core hypothesis / Risks / Plan implications / What would change my mind). For `research-review` that means the three-section block (Gaps / Errors / Missing constraints).
+For `brainstorm`, `research-review`, and `mr-review`, return Codex's raw output unchanged — do NOT apply the wrapper above. For `brainstorm` that means the five-section block (Framing / Core hypothesis / Risks / Plan implications / What would change my mind). For `research-review` that means the three-section block (Gaps / Errors / Missing constraints). For `mr-review` that means the fenced `json` block with `{"findings": [...]}`.
 
  Do not editorialize or "improve." If `codex` errors, report the exact error so the caller can decide how to proceed.

diff --git a/agents/gemini-consultant.md b/agents/gemini-consultant.md
index 19af19c..5a09884 100644
--- a/agents/gemini-consultant.md
+++ b/agents/gemini-consultant.md
@@ -35,6 +35,7 @@ The caller signals a mode via a `MODE: <name>` prefix in the prompt. Handle each
   5. What would change my mind
 - **`doc-audit`** (`/z-maintain-docs --audit`): caller hands you a proposed human-tier markdown + LLM-tier JSON update + the source files the concept describes + the prior version of the doc. Ask Gemini: does the proposed doc accurately describe the source files? List specific claims that don't match. List concepts the doc should cover but doesn't.
 - **`test-cases`** (Phase 3 of `/z-test`): caller hands you SPEC.md + PLAN.md + TASKS.md + a draft list of test cases + user-stated bug-class concerns + the source files referenced by the drafts. Ask Gemini: (1) for each draft, is the assertion strong enough to catch a real bug or a tautology — if weak, propose a stronger assertion; (2) which SPEC invariants have no corresponding test (propose entries); (3) what dangerous bug classes specific to this codebase domain (trading: notional sign, fill-quantity sign, time-zone-aware bar boundaries, feature schema alignment between strategy and pipeline) are uncovered; (4) flag any draft that is mechanically trivial and should be dropped. Return structured: per-draft critique (keep | strengthen | drop), then a list of NEW test entries the caller missed.
+- **`mr-review`** (Step 4 of `mr-reviewer`): caller hands you active categories, full STYLE.md contents, and the full diff. Ask Gemini to find quality issues (not correctness bugs) in the diff, citing STYLE.md rule IDs for style-drift findings and file:line for abstraction findings. Return RAW — the caller expects a fenced `json` block with `{"findings": [...]}` matching the schema in the prompt; do not apply the standard wrapper.
 
  ## Building the prompt to Gemini
 
@@ -55,6 +56,7 @@ The caller gives you the input artifact + file pointers. You must:
       - `research-review`: "Critique this research draft with exactly three sections: (1) Gaps — things the draft missed, (2) Errors — claims that appear wrong, (3) Missing constraints — constraints not captured. Do NOT recommend an approach; research is terrain-mapping, not direction-picking."
       - `doc-audit`: "Does the proposed doc accurately describe the source files? List specific claims that don't match. List concepts the doc should cover but doesn't."
       - `test-cases`: "(1) For each draft test, is the assertion strong enough to catch a real bug or is it a tautology — if weak, propose a stronger assertion. (2) Which SPEC invariants have no corresponding test (propose entries)? (3) What dangerous bug classes specific to this codebase domain are uncovered? (4) Flag any draft that is mechanically trivial and should be dropped. Return structured: per-draft critique (keep | strengthen | drop), then a list of NEW test entries the caller missed."
+     - `mr-review`: Pass through the prompt verbatim to Gemini. The prompt already contains the full ask and output schema. Return the fenced `json` block from Gemini's response unchanged.
 
  ## Returning to the caller
 
@@ -75,7 +77,7 @@ For `bundled-decisions`, `plan-review`, `light-fix`, `debug-hypotheses`, `doc-a
  <short quote>
  ```
 
-For `brainstorm` and `research-review`, return Gemini's raw section block unchanged — do NOT apply the wrapper above. For `brainstorm` that means the five-section block (Framing / Core hypothesis / Risks / Plan implications / What would change my mind). For `research-review` that means the three-section block (Gaps / Errors / Missing constraints).
+For `brainstorm`, `research-review`, and `mr-review`, return Gemini's raw output unchanged — do NOT apply the wrapper above. For `brainstorm` that means the five-section block (Framing / Core hypothesis / Risks / Plan implications / What would change my mind). For `research-review` that means the three-section block (Gaps / Errors / Missing constraints). For `mr-review` that means the fenced `json` block with `{"findings": [...]}`.
 
  Do not editorialize or "improve." If `gemini` errors, report the exact error so the caller can decide how to proceed.
```

---

REVIEWER SCRUTINY FOCUS (per task):

1. **PARALLEL DISPATCH:** Does mr-reviewer.md Step 4 actually say "single message with one Agent() call per non-Claude voice"? Check line ~136.

2. **TIER-BUMP LOGIC:** Does Step 5 (lines ~157-160) correctly implement all four cases?
   - 3/3 voices promote (P0 stays) ✓
   - 2/3 voices stay (no mention in the spec) ✓
   - 1/3 voices demote (P0 stays) ✓
   - Single voice no-op ✓
   Verify P0 is truly never demoted in any branch.

3. **DEDUP NORMALIZATION:** Line ~155 specifies: concatenate `title + " " + detail`, lowercase, collapse whitespace, strip punctuation. Does this match the SPEC normalization word-for-word?

4. **MODE: MR-REVIEW ADDITIONS:** Lines added to codex-consultant.md and gemini-consultant.md:
   - Line 47 (codex) and 38 (gemini): "mr-review" mode listed with brief description. ✓
   - Line 68 (codex) and 59 (gemini): Pass-through prompt instruction. ✓
   - Line 89 (codex) and 80 (gemini): Return-raw instruction updated to include mr-review. ✓
   Total = 3 logical lines per file. ✓
   Do these additions disrupt the existing mode-handling logic (brainstorm, research-review, doc-audit, test-cases)?

5. **SINGLE-VOICE FALLBACK:** If voices_available=[claude] only, Step 4 dispatch is skipped, Step 5 tier-bump is also skipped (line 160: "If `len(voices_available) == 1`: no bump"). Does this cleanly fall back?

6. **JSON SCHEMA COMPLETENESS:** Lines 175-192 define the return JSON with voices field per finding and voices_used top-level. Are both present and correctly described?

Report:
1. Blockers or correctness issues
2. Spec violations or missed acceptance criteria
3. Missed edge cases / error handling gaps
4. DRY / KISS / SOLID violations
5. Security concerns
6. Anything else worth flagging

For each finding: severity (blocker / major / minor), location, and suggested fix.
OUTPUT BUDGET: 8000 characters, blockers + majors only (minors only if they hide a correctness bug).
