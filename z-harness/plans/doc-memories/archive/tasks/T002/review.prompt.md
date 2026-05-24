You are reviewing code that Claude just wrote for task T002: Update doc-updater contract — add memories[] to LLM JSON shape, add ## Memories section to human-tier template with DO-NOT-EDIT comment, add "never invent memories" hard rule, add MEMORIES_PRESERVED to return shape.

Spec (excerpt from /Users/zeke/dev/z-harness/z-harness/doc-memories/SPEC.md):

### Per-file changes: `agents/doc-updater.md`

- LLM-tier JSON contract gains `memories: []` (default empty, preserved across refreshes — doc-updater MUST round-trip existing memories from the input JSON unless the caller explicitly says otherwise).
- Human-tier markdown contract gains a `## Memories` section (rendered after `## Edge cases / gotchas`, before `## Examples`). The section ALWAYS opens with a literal HTML comment so humans don't lose edits to the next refresh:
  ```
  ## Memories

  <!-- DO NOT EDIT this section by hand — regenerated from docs/llm/<slug>.json by doc-updater. Use /z-suggest-memory to add or edit memories. -->

  - **<DATE> <TYPE>** ([<source>](#)) — <text> _(tags: t1, t2)_
  ```
  Section is omitted entirely if `memories: []`.
- Procedure step 3 amended: when reading the current LLM doc, preserve existing `memories[]` verbatim. Never invent memories during a refresh — doc-updater is a structural agent, not an authoring one. Return shape adds `MEMORIES_PRESERVED: <N>` line so callers can verify round-trip.
- New procedure step 3.5: **tag dedup pass** (only invoked when caller passes `dedup_tags: true`). Scan all `memories[].tags` across the concept; if two tags differ only by stem (`perf` / `performance`, `cache` / `caching`) per a simple shared-prefix-≥4 + Levenshtein-≤2 heuristic, include them under a `TAG_COLLISIONS` block in the return for /z-maintain-docs to surface. Do not auto-merge.

Acceptance criteria:
- doc-updater.md documents memories field in LLM JSON shape
- Human-tier template includes the section + DO-NOT-EDIT comment
- "Never invent memories" hard rule added
- Return shape gains MEMORIES_PRESERVED

Diff (primary artifact — focus your scrutiny on what changed):

diff --git a/agents/doc-updater.md b/agents/doc-updater.md
index e3269e1..0fade98 100644
--- a/agents/doc-updater.md
+++ b/agents/doc-updater.md
@@ -34,6 +34,8 @@ TOKEN="$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-phase
 
 ### 3. Produce updated docs
 
+**Memory preservation (mandatory).** Before drafting either tier, read the `memories[]` array from the existing LLM-tier JSON (if it exists). Copy it verbatim into the refreshed JSON. Do NOT add, remove, or alter any memory entry. Count the entries and report the count as `MEMORIES_PRESERVED: <N>` in the return. If no LLM-tier JSON exists yet, `MEMORIES_PRESERVED: 0`.
+
 **Human-tier markdown** at the given path. Structure:
 
 ```markdown
@@ -55,6 +57,14 @@ Two-paragraph plain-language description of what this concept is and where it li
 ## Edge cases / gotchas
 - ...
 
+## Memories
+
+<!-- DO NOT EDIT this section by hand — regenerated from docs/llm/<slug>.json by doc-updater. Use /z-suggest-memory to add or edit memories. -->
+
+- **<DATE> <TYPE>** ([<source>](#)) — <text> _(tags: t1, t2)_
+
+_Note: this section is omitted entirely when `memories: []`._
+
 ## Examples
 - ...
 ```
@@ -74,10 +84,13 @@ Two-paragraph plain-language description of what this concept is and where it li
   "depends_on": ["<other-concept-slugs>"],
   "consumed_by": ["<other-concept-slugs>"],
   "invariants": ["<short statements>"],
-  "gotchas": ["<short statements>"]
+  "gotchas": ["<short statements>"],
+  "memories": []
 }
 ```
 
+`memories` defaults to `[]`. When the existing LLM-tier doc has a non-empty `memories[]`, those entries MUST be copied verbatim into the refreshed JSON — doc-updater NEVER invents or modifies memories.
+
 Both tiers MUST stay synced — same set of entry points, same dependency graph.
 
 ### 4. Return shape (required)
@@ -86,6 +99,7 @@ Both tiers MUST stay synced — same set of entry points, same dependency graph.
 STATUS: ok | not_enough_info
 CONCEPT: <name>
 MODE: dry-run | write
+MEMORIES_PRESERVED: <N>
 HUMAN_DOC:
 <full proposed human-tier markdown, fenced if needed>
 LLM_DOC:
@@ -108,5 +122,6 @@ bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-phase.sh" end
 - **NEVER write to disk in `dry-run` mode** (default). The caller wants to review first.
 - **Always keep human and LLM tiers in sync** — same entry points, same dependency graph.
 - **Don't invent confidence**: if you can't verify a claim from the source files, mark `confidence: low` and explain in NOTES.
+- **NEVER invent memories.** doc-updater is a structural refresh agent, not a memory authoring agent. Existing `memories[]` entries are copied verbatim; no new entries are created. All memory authoring goes through `/z-suggest-memory`.
 - **Stay focused on the one concept** — don't expand to neighboring concepts. The caller handles concept iteration.
 - **No emojis** anywhere in the output.

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

