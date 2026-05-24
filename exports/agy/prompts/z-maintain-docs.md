---
description: Refresh stale docs in docs/human/ and docs/llm/. Reads docs/llm/INDEX.json to find concepts whose source files changed since each doc's last_updated. Spawns doc-updater subagents (Sonnet) per stale concept. Dry-run preview by default — user review...
role: workflow
---

You are running **z-harness `/z-maintain-docs`**. Goal: keep `docs/human/` and `docs/llm/` in sync with the current state of the code.

This command runs in **dry-run preview mode by default**. Pass `--apply` to actually write the changes (after the user has reviewed). For scoped refresh, pass `--scope <concept-slug>`. Pass `--audit` to additionally run cross-LLM verification on each proposed doc update (recommended when you don't fully trust the `doc-updater`'s output).

## Phase 0 — Preflight

1. `cd` to repo root. Read `docs/llm/INDEX.json`. If missing, tell the user to run `/z-init-docs` first; abort.
2. Determine mode:
   - `--apply` flag present → write changes after preview.
   - Otherwise → dry-run preview only; user must re-run with `--apply` to commit.
3. **Version stamp + log:**
   ```bash
   VERSION_BLOB="$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/version.sh")"
   bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "docs" maintain_docs_start \
     "$(python3 -c 'import json,sys; v=json.loads(sys.argv[1]); v["mode"]=sys.argv[2]; print(json.dumps(v))' "$VERSION_BLOB" "<dry-run|apply>")"
   ```

## Phase 1 — Find stale concepts

For each concept in `INDEX.json`:

- Read its `last_updated` date.
- For each path in its `source_file` list, check `git log -1 --format=%cI -- <path>` to get the file's last commit timestamp.
- If any source file is newer than `last_updated` → mark concept as **stale**.

Also include in the stale list:
- Concepts referenced by any `task_done` event in `z-harness/*/metrics.jsonl` since the concept's `last_updated` (recent plans touched these).
- Concepts with `doc_drift` events logged (a `/z-plan` Phase 1 Explore noticed the doc was wrong).

If `--scope <slug>` was passed, restrict to that one concept (even if not detected as stale).

If nothing is stale → tell the user "All docs are current."; log `maintain_docs_end` with `stale_count: 0`; stop.

## Phase 2 — Spawn doc-updaters (parallel, up to 3 concurrent)

**Before spawning each doc-updater**, capture the baseline memory count from the existing LLM-tier JSON (if it exists). Store it per concept so Phase 3 can validate the return:

```python
import json, os

baseline_memories = {}  # slug -> int
for slug in stale_concepts:
    llm_path = f"docs/llm/{slug}.json"
    if os.path.exists(llm_path):
        data = json.load(open(llm_path))
        baseline_memories[slug] = len(data.get("memories", []))
    else:
        baseline_memories[slug] = 0
```

For each stale concept, spawn a `doc-updater` subagent. In dry-run mode, leave `mode: dry-run` (default); in apply mode, set `mode: write`.

```
<!-- agent dispatch / skill invocation not supported in Antigravity; see CAPABILITIES.md -->
  subagent_type="doc-updater",
  description="Refresh docs for <concept>",
  prompt="concept: <slug>\nhuman_path: docs/human/<slug>.md\nllm_path: docs/llm/<slug>.json\nsource_files: <paths from INDEX.json>\nreason: <stale|drift|spec_change>\nmode: <dry-run|write>\nrepo_root: <abs path>\ndedup_tags: true"
)
```

Up to 3 in parallel per batch (`Z_HARNESS_PARALLEL=N` env override).

When each doc-updater returns, check its `MEMORIES_PRESERVED: <N>` value against the stored baseline:

```python
preserved = int(doc_updater_return["MEMORIES_PRESERVED"])
baseline = baseline_memories[slug]
if preserved != baseline:
    warn(f"memories_lost: {slug} — doc-updater preserved {preserved} memories but baseline was {baseline}. Check docs/llm/{slug}.json manually.")
```

Surface any `memories_lost` warning prominently in Phase 3 before presenting diffs. A mismatch indicates doc-updater may have dropped memories, which is a hard-rule violation (doc-updater must copy memories verbatim).

## Phase 2.5 — Cross-LLM audit (only if `--audit` flag set)

<!-- agent dispatch / skill invocation not supported in Antigravity; see CAPABILITIES.md -->

```
<!-- agent dispatch / skill invocation not supported in Antigravity; see CAPABILITIES.md -->
  subagent_type="consultant-primary",
  description="Doc audit (Gemini) for <concept>",
  prompt="MODE: doc-audit\n\nConcept: <slug>\nProposed human-tier markdown:\n<verbatim from doc-updater HUMAN_DOC>\n\nProposed LLM-tier JSON:\n<verbatim from doc-updater LLM_DOC>\n\nSource files (read these):\n<list of abs paths>\n\nPrior doc (if any):\n<verbatim or 'none — fresh init'>\n\nAsk: does the proposed doc accurately describe the source files? List specific claims that don't match (file:line). List concepts the doc should cover but doesn't."
)
<!-- agent dispatch / skill invocation not supported in Antigravity; see CAPABILITIES.md -->
  subagent_type="consultant-secondary",
  description="Doc audit (Codex) for <concept>",
  prompt="MODE: doc-audit\n\n<same prompt body>"
)
```

Aggregate findings per concept into `z-harness/archive/docs/<RRUN>/audit-<concept>.md`:

```markdown
# Doc audit: <concept>
## Gemini findings
- agree | disagree (claim X doesn't match: <file:line>)
- missing concepts: <list>
## Codex findings
- agree | disagree (claim Y doesn't match: <file:line>)
- missing concepts: <list>
## Cross-LLM consensus
- Both agree the doc is accurate
- OR: Both flag <X> as inaccurate (high confidence — must fix before apply)
- OR: Gemini and Codex disagree about <Y> (surface to user)
```

**If both LLMs flag a blocker** → mark the concept's proposed update as **rejected**; do not include it in Phase 3's apply set unless the user explicitly overrides.

**If the LLMs disagree** → mark as **needs user review**; surface explicitly in Phase 3.

**If both agree the proposed update is accurate** → mark as **audit-passed**; proceed.

Cross-LLM audit doubles wall time of `/z-maintain-docs --audit` vs the default but provides the cross-LLM safety net the user wants on doc updates.

## Phase 3 — Present diffs (dry-run only)

For each doc-updater return, compute the diff between the current doc on disk and the proposed update. Present a summary to the user:

```
Stale concepts to refresh:
  • kalshi-trades-projection — 8 lines changed in human, 3 fields changed in LLM [audit: passed]
  • sport-ticker-parser      — 22 lines changed in human, 6 fields changed in LLM [audit: needs review]
  • backfill-runner          — 15 lines changed in human, 4 fields changed in LLM [audit: rejected — claim mismatch]

[full diffs at z-harness/archive/docs/<RRUN>/proposed/]
[audit findings at z-harness/archive/docs/<RRUN>/audit-<concept>.md]
```

When `--audit` was used, prefix each entry with the audit verdict so the user can prioritize review. Sort: `needs review` > `rejected` > `passed`.

Write the proposed updates to `z-harness/archive/docs/<RRUN>/proposed/<concept>.human.md` and `<concept>.llm.json` so the user can inspect before applying.

### Stale memories

After presenting the doc diffs, scan every `docs/llm/<slug>.json` for memories where either:
- `expires` is present and `expires < today`, OR
- `date < today - $Z_HARNESS_MEMORY_STALE_DAYS` (default 547 days)

For each stale memory, display it as:

```
Stale memory in <slug> (index <N>):
  [<TYPE> <DATE>] <text> (tags: t1, t2)
  Reason: expired / age > 547 days
```

For each stale entry, ask via inline `AskUserQuestion` with three choices:
- **Keep** (default) — no change, memory remains as-is.
- **Edit** — hand off to `/z-suggest-memory --edit <slug> <index>` and return after the edit completes.
- **Delete** — splice out `memories[index]` from the concept JSON using an atomic write, then log the deletion. MEMORIES-FLAT.md is **NOT** regenerated inline; Phase 4.5 handles regen after all deletes apply.

  **Atomic-write pattern for the splice:**
  1. Read the current `docs/llm/<slug>.json` into memory.
  2. Remove `memories[index]` from the in-memory array.
  3. Serialize the updated JSON to a temporary file (e.g. `<slug>.json.tmp`) in the same directory.
  4. `fsync` the tmpfile to flush to disk.
  5. Use `os.replace(<tmpfile>, <slug>.json)` to atomically swap the files.
  6. **If any step above fails** (read error, write error, replace error): surface the error to the user, leave the original JSON file untouched, and **do not** log `memory_deleted`. Do not attempt regeneration.
  7. Only after a successful `os.replace` log the deletion:
  ```bash
  bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "docs" memory_deleted \
    "$(printf '{"concept":"%s","index":%d,"text_preview":"%s"}' "<slug>" <N> "<first 60 chars of text>")"
  ```

Stale memories are **never auto-deleted** — every removal requires an explicit human choice.

If no stale memories are found, skip this section silently.

### TAG_COLLISIONS

If any doc-updater subagent from Phase 2 was invoked with `dedup_tags: true` and returned a `TAG_COLLISIONS` block, surface those collisions here before the AskUserQuestion:

```
Tag collisions detected:
  • <slug>: "perf" (5 uses) vs "performance" (2 uses) — consider consolidating
  • <slug>: "cache" (3 uses) vs "caching" (1 use) — consider consolidating
```

For each collision, ask via an inline `AskUserQuestion` with four options:

- **Keep both** — leave both tags as-is; the collision will re-appear on the next run.
- **Rename one** — hand off to `/z-suggest-memory --edit` to update individual memory entries manually.
- **Add alias** — prompt the user to pick which of the two tags is canonical (radio; both options shown with their use counts to guide the decision). Then append the alias line to `docs/llm/TAGS.txt` section 2 using an atomic write:
  1. Read `docs/llm/TAGS.txt` into memory.
  2. Append `<canonical> = <alias>` after the last non-blank, non-comment line in section 2 (or after the blank separator if section 2 is empty).
  3. Write atomically via tmpfile + `os.replace()`.
  4. Log the alias addition:
     ```bash
     bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "docs" tag_alias_added \
       "$(printf '{"canonical":"%s","alias":"%s","concept":"%s"}' "<canonical>" "<alias>" "<slug>")"
     ```
  **Deferral note:** adding an alias here only records the mapping in `TAGS.txt`. The alias-collapse logic (doc-updater step 3.5 step A) is **not** triggered in the current run — no memory `tags[]` arrays are rewritten now. In-memory tag state for this run remains at the collision-tag values. On the next `/z-maintain-docs` (or doc-updater) invocation, step 3.5 reads the updated `TAGS.txt`, auto-collapses the alias in any memory that carries it, and emits `tag_aliased` log lines. Do not expect collapsed tags to appear in MEMORIES-FLAT.md until after that subsequent run.
- **Skip** — do nothing for this collision in this run.

After all per-collision questions, ask the top-level `AskUserQuestion` for the doc-refresh action:
- **Apply all** → re-run this command with `--apply` (or apply now in-place; user choice).
- **Apply a subset** → user picks which concepts.
- **Skip** → leave docs as-is; concepts stay flagged for next run.

## Phase 4 — Apply (apply mode only)

For each accepted concept, write the proposed `human_path` and `llm_path` files. Update `docs/llm/INDEX.json` with the new `last_updated`, `confidence`, `depends_on`, `consumed_by`, `summary` fields.

If any concept's source files changed enough that the doc-updater couldn't produce confident output (`STATUS: not_enough_info`), DO NOT write — surface to user.

## Phase 4.5 — Regenerate MEMORIES-FLAT.md

After all accepted concept files have been written in Phase 4, unconditionally regenerate `docs/llm/MEMORIES-FLAT.md` from all current `docs/llm/<slug>.json` files:

```bash
python3 scripts/regenerate-memories-flat.py --repo-root <abs_path>
```

This step runs in both `--apply` mode (after writes) and whenever a memory was deleted during Phase 3's stale-memories review. It covers the case where a memory was edited or deleted but no source file changed. Do not skip this step even if zero concepts were updated.

If the script exits non-zero, surface the error to the user and halt (do not proceed to Phase 5 with a potentially corrupt MEMORIES-FLAT.md).

## Phase 5 — Finalize

1. Summary to user:
   ```
   docs/ refreshed:
     <N> concepts updated, <M> deferred (not_enough_info), <K> skipped.
   
   Recommended next:
     git add docs/ && git commit -m "Refresh z-harness docs"
   ```
2. Log:
   ```bash
   bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "docs" maintain_docs_end \
     "$(printf '{"mode":"%s","updated":%d,"deferred":%d,"skipped":%d}' "<mode>" "$U" "$D" "$S")"
   ```

## Hard rules

- **Default = dry-run.** Never write to `docs/` without an explicit `--apply` or per-concept user confirmation.
- **Never modify code files.** This command only touches `docs/`.
- **Atomic per-concept writes.** A concept's human + LLM tiers update together or not at all (don't leave them out of sync).
- **Preserve git history.** Write to existing paths; don't create _v2 files.
- **No emojis** in docs.

## Trigger patterns

- After `/z-implement-all` finalizes, the orchestrator's recommended-next push-notification lists `/z-maintain-docs`.
- After `/z-review-all` accepts a plan, same.
- Standalone: user runs whenever they suspect drift.
- Could be wired into CI as `claude /z-maintain-docs --apply` if the user wants automated freshness.
