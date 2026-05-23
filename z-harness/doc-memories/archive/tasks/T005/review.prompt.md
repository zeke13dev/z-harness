You are reviewing code that Claude just wrote for task T005: z-maintain-docs SKILL.md — Phase 4.5 unconditional regenerate-memories-flat.py call; Phase 3 "Stale memories" UX with Keep/Edit/Delete + memory_deleted event; Phase 3 surfaces TAG_COLLISIONS

Acceptance criteria:
- Phase 4.5 documented
- Phase 3 stale-memories UX documented including Keep/Edit/Delete and memory_deleted event
- TAG_COLLISIONS surfaced

Diff (primary artifact — focus your scrutiny on what changed):

diff --git a/skills/z-maintain-docs/SKILL.md b/skills/z-maintain-docs/SKILL.md
index 5ed0fff..91a48f6 100644
--- a/skills/z-maintain-docs/SKILL.md
+++ b/skills/z-maintain-docs/SKILL.md
@@ -109,6 +109,45 @@ When `--audit` was used, prefix each entry with the audit verdict so the user ca
 
 Write the proposed updates to `z-harness/archive/docs/<RRUN>/proposed/<concept>.human.md` and `<concept>.llm.json` so the user can inspect before applying.
 
+### Stale memories
+
+After presenting the doc diffs, scan every `docs/llm/<slug>.json` for memories where either:
+- `expires` is present and `expires < today`, OR
+- `date < today - $Z_HARNESS_MEMORY_STALE_DAYS` (default 547 days)
+
+For each stale memory, display it as:
+
+```
+Stale memory in <slug> (index <N>):
+  [<TYPE> <DATE>] <text> (tags: t1, t2)
+  Reason: expired / age > 547 days
+```
+
+For each stale entry, ask via inline `AskUserQuestion` with three choices:
+- **Keep** (default) — no change, memory remains as-is.
+- **Edit** — hand off to `/z-suggest-memory --edit <slug> <index>` and return after the edit completes.
+- **Delete** — splice out `memories[index]` from the concept JSON (atomic write), regenerate `docs/llm/MEMORIES-FLAT.md` via `python3 scripts/regenerate-memories-flat.py --repo-root <abs_path>`, then log the deletion:
+  ```bash
+  bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "docs" memory_deleted \
+    "$(printf '{"concept":"%s","index":%d,"text_preview":"%s"}' "<slug>" <N> "<first 60 chars of text>")"
+  ```
+
+Stale memories are **never auto-deleted** — every removal requires an explicit human choice.
+
+If no stale memories are found, skip this section silently.
+
+### TAG_COLLISIONS
+
+If any doc-updater subagent from Phase 2 was invoked with `dedup_tags: true` and returned a `TAG_COLLISIONS` block, surface those collisions here before the AskUserQuestion:
+
+```
+Tag collisions detected:
+  • <slug>: "perf" (5 uses) vs "performance" (2 uses) — consider consolidating
+  • <slug>: "cache" (3 uses) vs "caching" (1 use) — consider consolidating
+```
+
+Inform the user that `/z-maintain-docs` does not auto-merge tags; they should use `/z-suggest-memory --edit` to update individual memory entries.
+
 Ask via `AskUserQuestion`:
 - **Apply all** → re-run this command with `--apply` (or apply now in-place; user choice).
 - **Apply a subset** → user picks which concepts.
@@ -120,6 +159,18 @@ For each accepted concept, write the proposed `human_path` and `llm_path` files.
 
 If any concept's source files changed enough that the doc-updater couldn't produce confident output (`STATUS: not_enough_info`), DO NOT write — surface to user.
 
+## Phase 4.5 — Regenerate MEMORIES-FLAT.md
+
+After all accepted concept files have been written in Phase 4, unconditionally regenerate `docs/llm/MEMORIES-FLAT.md` from all current `docs/llm/<slug>.json` files:
+
+```bash
+python3 scripts/regenerate-memories-flat.py --repo-root <abs_path>
+```
+
+This step runs in both `--apply` mode (after writes) and whenever a memory was deleted during Phase 3's stale-memories review. It covers the case where a memory was edited or deleted but no source file changed. Do not skip this step even if zero concepts were updated.
+
+If the script exits non-zero, surface the error to the user and halt (do not proceed to Phase 5 with a potentially corrupt MEMORIES-FLAT.md).
+
 ## Phase 5 — Finalize
 
 1. Summary to user:

Surrounding file context:

=== regenerate-memories-flat.py ===
The script is a complete, working Python utility that:
- Takes --repo-root and --dry-run arguments
- Loads all docs/llm/*.json files (except INDEX.json)
- Extracts memories[] arrays
- Sorts by slug ascending, then by date descending (using inverted-date logic for desc)
- Outputs to docs/llm/MEMORIES-FLAT.md with atomic write (tmp file + os.replace)
- Exits 0 on success, 1 on input error, 2 on write error
- Handles missing "memories" field gracefully

=== doc-updater.md ===
Key contract surfaces touched by the diff:
- dedup_tags parameter (line 18): "true | false (default false). When true, activates step 3.5 to scan memory tags..."
- TAG_COLLISIONS return block (lines 97–107): "Collect all candidates into the TAG_COLLISIONS return block. Never auto-merge tags — the block is advisory only; /z-maintain-docs surfaces it for human review."
- Return shape (lines 109–132): Shows TAG_COLLISIONS is present only when dedup_tags: true

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
- One finding per bullet. Two sentences max per finding.
- No re-stating of code already in the diff. No summaries of what the code does. No restating the spec.
- If there are no blockers or majors, respond with exactly: `No blockers or majors found.` (plus an optional 1-line note if something needs the implementer's attention but is below the bar).
