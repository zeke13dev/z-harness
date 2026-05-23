You are reviewing code that Claude just wrote for task T003: doc-updater TAG_COLLISIONS dedup pass.

Task description: Add procedure step 3.5 (shared-prefix-≥4 + Levenshtein-≤2 heuristic, never auto-merge), document dedup_tags input, add TAG_COLLISIONS return block.

Acceptance criteria:
- doc-updater.md documents step 3.5 and TAG_COLLISIONS return
- Format matches `[{"concept", "tag_a", "tag_b", "count_a", "count_b"}, ...]` verbatim

Diff (primary artifact — focus your scrutiny on what changed):

diff --git a/agents/doc-updater.md b/agents/doc-updater.md
index e3269e1..445de16 100644
--- a/agents/doc-updater.md
+++ b/agents/doc-updater.md
@@ -15,6 +15,7 @@ You refresh a single concept's docs from the current state of the code. The call
 - **Source file paths** the concept covers (from the LLM tier's `source_file` field, or from caller's discovery)
 - **Reason for refresh** — `init` (no doc yet), `stale` (`last_updated` predates a `source_file` change), `spec_change` (a recent /z-plan touched this concept's surface), `drift` (a /z-plan Phase 1 noticed the doc was wrong)
 - **Mode** — `dry-run` (default; just return proposed text) or `write` (also write the files)
+- **dedup_tags** — `true | false` (default `false`). When `true`, activates step 3.5 to scan memory tags for near-duplicates and emit a `TAG_COLLISIONS` block in the return.
 
 ## Procedure
 
@@ -34,6 +35,8 @@ TOKEN="$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-phase
 
 ### 3. Produce updated docs
 
+**Memory preservation (mandatory).** Before drafting either tier, read the `memories[]` array from the existing LLM-tier JSON (if it exists). Copy it verbatim into the refreshed JSON. Do NOT add, remove, or alter any memory entry. Count the entries and report the count as `MEMORIES_PRESERVED: <N>` in the return. If no LLM-tier JSON exists yet, `MEMORIES_PRESERVED: 0`.
+
 **Human-tier markdown** at the given path. Structure:
 
 ```markdown
@@ -55,6 +58,14 @@ Two-paragraph plain-language description of what this concept is and where it li
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
@@ -74,26 +85,49 @@ Two-paragraph plain-language description of what this concept is and where it li
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
 
+### 3.5. Tag dedup pass (only when `dedup_tags: true`)
+
+Scan every tag string across all entries in `memories[]` for the concept being refreshed. For each pair of distinct tags `(tag_a, tag_b)`:
+
+1. Compute the length of their longest common prefix.
+2. Compute their Levenshtein distance.
+3. If **shared prefix ≥ 4 characters AND Levenshtein distance ≤ 2**, treat them as a collision candidate.
+
+For each collision candidate, record the number of memory entries that carry each tag (`count_a`, `count_b`). Collect all candidates into the `TAG_COLLISIONS` return block. **Never auto-merge tags** — the block is advisory only; /z-maintain-docs surfaces it for human review.
+
+If `dedup_tags: false` (the default), skip this step entirely and omit `TAG_COLLISIONS` from the return.
+
 ### 4. Return shape (required)
 
 ```
 STATUS: ok | not_enough_info
 CONCEPT: <name>
 MODE: dry-run | write
+MEMORIES_PRESERVED: <N>
 HUMAN_DOC:
 <full proposed human-tier markdown, fenced if needed>
 LLM_DOC:
 <full proposed LLM-tier JSON, parseable>
+TAG_COLLISIONS:
+[
+  {"concept": "<slug>", "tag_a": "perf", "tag_b": "performance", "count_a": 5, "count_b": 2},
+  ...
+]
 NOTES (optional):
   <anything the caller should know — e.g. "couldn't find a clear consumer for fn X; marked confidence=medium">
 ```
 
+`TAG_COLLISIONS` is present only when `dedup_tags: true`. When present and no collisions are detected, emit an empty JSON array (`[]`). When `dedup_tags: false`, omit the field entirely.
+
 If `MODE: write`: also actually write the two files to their given paths and report `WROTE: <human-path>, <llm-path>` in the return.
 
 ### 5. Telemetry: end
@@ -108,5 +142,6 @@ bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-phase.sh" end
 - **NEVER write to disk in `dry-run` mode** (default). The caller wants to review first.
 - **Always keep human and LLM tiers in sync** — same entry points, same dependency graph.
 - **Don't invent confidence**: if you can't verify a claim from the source files, mark `confidence: low` and explain in NOTES.
+- **NEVER invent memories.** doc-updater is a structural refresh agent, not a memory authoring agent. Existing `memories[]` entries are copied verbatim; no new entries are created. All memory authoring goes through `/z-suggest-memory`.
 - **Stay focused on the one concept** — don't expand to neighboring concepts. The caller handles concept iteration.
 - **No emojis** anywhere in the output.

Surrounding downstream context (z-maintain-docs Phase 3):

From `/z-maintain-docs` SKILL.md:

### TAG_COLLISIONS

If any doc-updater subagent from Phase 2 was invoked with `dedup_tags: true` and returned a `TAG_COLLISIONS` block, surface those collisions here before the AskUserQuestion:

```
Tag collisions detected:
  • <slug>: "perf" (5 uses) vs "performance" (2 uses) — consider consolidating
  • <slug>: "cache" (3 uses) vs "caching" (1 use) — consider consolidating
```

Inform the user that `/z-maintain-docs` does not auto-merge tags; they should use `/z-suggest-memory --edit` to update individual memory entries.

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
- Total response under 8000 characters.
- Report blockers and majors only. Skip minors and nits unless a "minor" hides a correctness bug.
- One finding per bullet. Two sentences max per finding.
- No re-stating of code already in the diff. No summaries. No restating spec.
- If there are no blockers or majors, respond with exactly: `No blockers or majors found.`
