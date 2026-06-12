# /z-maintain-docs

You are running **z-harness `/z-maintain-docs`**. Goal: keep `docs/human/` and `docs/llm/` in sync with the current state of the code.

This command **applies refreshed docs by default** — routine updates are written without asking. Pass `--dry-run` to preview the diffs without writing anything. It stops for a targeted per-concept confirmation only when a genuine-risk signal fires (a `memories_lost` mismatch, or — under `--audit` — a doc the consultants flagged as inaccurate or disputed). For scoped refresh, pass `--scope <concept-slug>`. Pass `--glossary` to additionally refresh the `CONTEXT.md` domain-language glossary (user-initiated; see Phase 1.5). Pass `--audit` to additionally run cross-LLM verification on each proposed doc update (recommended when you don't fully trust the `doc-updater`'s output).

## Phase 0 — Preflight

1. `cd` to repo root. Read `docs/llm/INDEX.json`. If missing, tell the user to run `/z-init-docs` first; abort.
2. Determine mode:
   - `--dry-run` flag present → preview only; present proposed diffs and write nothing.
   - `--glossary` flag present → also run Phase 1.5 (CONTEXT.md glossary refresh) after Phase 1.
   - Otherwise (default) → apply: write accepted updates directly (after the risk triage in Phase 3).
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

If nothing is stale and `--glossary` was not passed → tell the user "All docs are current."; log `maintain_docs_end` with `stale_count: 0`; stop.

If nothing is stale but `--glossary` was passed → skip directly to Phase 1.5.

## Phase 1.5 — Glossary refresh (only if `--glossary` flag set)

This phase runs when the user explicitly passes `--glossary`. It refreshes the `CONTEXT.md` domain-language glossary at the repo root. Glossary staleness has no natural mtime trigger — there is no hard staleness gate here, and this phase is never triggered automatically. If `CONTEXT.md` looks potentially outdated (last commit older than 90 days), you may note "glossary may be stale" as an advisory, but this advisory does not block or gate the workflow.

If `CONTEXT.md` does not exist at the repo root, recommend the user run `/z-init-docs` to bootstrap it and skip the rest of this phase.

**Step 1: Re-extract candidate domain terms.**

<!-- agent dispatch / skill invocation not supported in Codex CLI; see CAPABILITIES.md -->
```
<!-- agent dispatch / skill invocation not supported in Codex CLI; see CAPABILITIES.md -->
  subagent_type="explore",
  model="haiku",
  description="Re-extract domain terms for glossary refresh",
  prompt="Re-extract candidate domain terms from the codebase — recurring nouns in module, type, and function names that are not standard English dictionary words. For each term: provide a concise one-line definition and note any synonyms or aliases in use. Return a flat list of (term, definition, avoid-list) triples.\nrepo_root: <abs path>"
)
```

**Step 2: Diff against current CONTEXT.md.**

Read `CONTEXT.md`. Parse all `### <Term>` headings under the `## Terms` section. Compute:
- **New terms** — extracted by Explore but not yet in CONTEXT.md.
- **Changed terms** — existing entries whose definition or avoid-list appears to have drifted (compare extracted definition against current prose).
- **Unchanged terms** — no action needed.

Terms that exist in CONTEXT.md but were not extracted by Explore are left untouched; do not propose deletions automatically (user-authored terms must be preserved).

**Step 3: Propose additions/edits.**

Present a summary of the proposed changes:

```
Glossary refresh — proposed changes:
  New terms (N):
    + <Term>: <one-line definition>  [Avoid: <synonyms>]
    + ...
  Changed terms (M):
    ~ <Term>: current: "<old>" → proposed: "<new>"
    ~ ...
  Unchanged: <K> terms — no action.
```

**Step 4: Apply or preview.**

- **Default mode (no `--dry-run`):** write the proposed additions and edits to `CONTEXT.md` directly. Extend the existing `## Terms` section: append new `### <Term>` blocks at the end; update changed definitions in-place. Never remove existing `### <Term>` entries. Never overwrite any section other than `## Terms`.
- **`--dry-run` mode:** present the proposed changes above but write nothing. Tell the user to re-run with `--glossary` (without `--dry-run`) to apply.

Log the glossary refresh outcome:

```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "docs" glossary_refresh \
  "$(printf '{"mode":"%s","new_terms":%d,"changed_terms":%d,"unchanged_terms":%d}' \
     "<dry-run|apply>" "$NEW" "$CHANGED" "$UNCHANGED")"
```

If nothing is stale (concept docs are current) and `--glossary` was the only flag, finalize after this phase: log `maintain_docs_end` with `stale_count: 0` and stop.

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

For each stale concept, spawn a `doc-updater` subagent. **Always pass `mode: dry-run`** — the updater returns proposed text but writes nothing. This command owns all writes (Phase 4) in both apply and `--dry-run` mode, so it can inspect the risk signals (`memories_lost`, audit verdicts) and gate before anything lands on disk.

<!-- agent dispatch / skill invocation not supported in Codex CLI; see CAPABILITIES.md -->
```
<!-- agent dispatch / skill invocation not supported in Codex CLI; see CAPABILITIES.md -->
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

## Phase 2.3 — Pre-audit compaction breakpoint (only if `--audit` flag set)

Before spawning any audit consultant, check the state file and optionally pause for context compaction.

**State file path:** `docs/llm/.maintain_docs_audit_state.json`

**On every `--audit` invocation, run these steps before Phase 2.5:**

1. Compute the current stale concept set (the slugs identified in Phase 1).
2. If `docs/llm/.maintain_docs_audit_state.json` exists:
   - Read it and compare `stale_concepts_at_ack` (as a set) to the current stale concept set.
   - If the sets are **equal**: fast-forward — skip the AskUserQuestion below, proceed directly to Phase 2.5. Log a `maintain_docs_audit_fast_forward` event.
   - If the sets **differ**: delete the stale state file and continue to the AskUserQuestion prompt below (re-prompt).
3. If the state file does not exist (or was just deleted): emit the `compaction_pause` event, push-notify, and prompt:

```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "docs" compaction_pause \
  '{"trigger":"pre_consult","phase":"maintain_docs_audit"}'
```

Push-notify (this is a hard pause prompt — fires regardless of notification level; see [docs/human/config.md](docs/human/config.md)):
> "About to audit <N> concept docs via consultants. Recommended: `/clear`, then re-invoke `/z-maintain-docs --audit` to continue. Dismiss to proceed now."

<!-- RUNTIME-GATE: ask_user; category=decision; non-supporting drivers must surface the compaction-pause decision (pause for /clear / proceed now) via their native channel. Silent omission is forbidden. -->
`AskUserQuestion` with two options:
- **(a) Pause for /clear** — exit cleanly. Do **NOT** write the state file. On the next invocation, Phase 2.3 will fire again.
- **(b) Proceed now** — write the state file and continue into Phase 2.5:
  ```json
  {
    "audit_acknowledged": true,
    "stale_concepts_at_ack": ["<slug1>", "<slug2>", "..."],
    "acknowledged_at": "<iso timestamp>"
  }
  ```
  If the state file write fails, log a warning to stderr and proceed (filesystem errors are non-blocking).

## Phase 2.5 — Cross-LLM audit (only if `--audit` flag set)

<!-- agent dispatch / skill invocation not supported in Codex CLI; see CAPABILITIES.md -->

<!-- agent dispatch / skill invocation not supported in Codex CLI; see CAPABILITIES.md -->
```
<!-- agent dispatch / skill invocation not supported in Codex CLI; see CAPABILITIES.md -->
  subagent_type="consultant-primary",
  description="Doc audit (Gemini) for <concept>",
  prompt="MODE: doc-audit\n\nConcept: <slug>\nProposed human-tier markdown:\n<verbatim from doc-updater HUMAN_DOC>\n\nProposed LLM-tier JSON:\n<verbatim from doc-updater LLM_DOC>\n\nSource files (read these):\n<list of abs paths>\n\nPrior doc (if any):\n<verbatim or 'none — fresh init'>\n\nAsk: does the proposed doc accurately describe the source files? List specific claims that don't match (file:line). List concepts the doc should cover but doesn't."
)
<!-- agent dispatch / skill invocation not supported in Codex CLI; see CAPABILITIES.md -->
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

## Phase 3 — Risk triage + targeted review

For each doc-updater return, compute the diff between the current doc on disk and the proposed update, and write the proposed update to `z-harness/archive/docs/<RRUN>/proposed/<concept>.human.md` and `<concept>.llm.json` so it's inspectable regardless of mode.

Classify each concept:
- **deferred** — `STATUS: not_enough_info`. The doc-updater couldn't produce confident output; never written. Reported, not prompted.
- **flagged** — a genuine-risk signal fired: a `memories_lost` mismatch (Phase 2), OR (only under `--audit`) an audit verdict of `rejected` or `needs review`.
- **clean** — everything else.

Present a summary to the user:

```
Concepts to refresh:
  • kalshi-trades-projection — 8 lines (human), 3 fields (LLM) [clean → applying]
  • sport-ticker-parser      — 22 lines (human), 6 fields (LLM) [flagged: audit needs review]
  • backfill-runner          — 15 lines (human), 4 fields (LLM) [flagged: audit rejected — claim mismatch]
  • feed-router              — 5 lines  (human), 1 field  (LLM) [flagged: memories_lost — preserved 3 of 4]
  • alpha-eval               — (deferred: not_enough_info — left unchanged)

[full diffs at z-harness/archive/docs/<RRUN>/proposed/]
[audit findings at z-harness/archive/docs/<RRUN>/audit-<concept>.md]
```

**Clean concepts apply with no prompt** (in default mode; in `--dry-run` they are previewed only). Sort flagged entries first so the user sees what needs attention: `audit rejected` > `audit needs review` > `memories_lost`.

<!-- RUNTIME-GATE: ask_user; category=decision; non-supporting drivers must surface the per-flagged-concept review question (apply anyway / skip) via their native channel. Silent omission is forbidden. -->
For each **flagged** concept (default mode only — `--dry-run` writes nothing so it skips this), ask via inline `AskUserQuestion`:
- **Apply anyway** — include this concept in Phase 4's write set despite the flag.
- **Skip this concept** — leave it unchanged; it stays flagged for the next run.

Default selection: `Skip this concept` for `audit rejected`; `Apply anyway` for `memories_lost` / `audit needs review` (lower-severity). Concepts the user skips are excluded from Phase 4.

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

<!-- RUNTIME-GATE: ask_user; category=archiving; non-supporting drivers must surface the stale-memory disposition question (keep / edit / delete) for each stale entry via their native channel. Silent omission is forbidden. -->
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

If any doc-updater subagent from Phase 2 was invoked with `dedup_tags: true` and returned a `TAG_COLLISIONS` block, surface those collisions here as a **non-blocking report** — they're advisory (cosmetic tag drift), so they do not gate the doc apply:

```
Tag collisions detected (advisory — not blocking):
  • <slug>: "perf" (5 uses) vs "performance" (2 uses) — consider consolidating
  • <slug>: "cache" (3 uses) vs "caching" (1 use) — consider consolidating

  To consolidate: /z-suggest-memory --edit <slug> <index> to rename a tag, or add a
  canonical = alias line to docs/llm/TAGS.txt section 2 (the next run auto-collapses it).
```

Do not prompt per collision. The user acts on them later if they care; tags are not on the doc-content critical path.

## Phase 4 — Apply

The **apply set** = every `clean` concept, plus every `flagged` concept the user chose **Apply anyway** in Phase 3. `deferred` (not_enough_info) and user-skipped concepts are excluded.

**Default mode:** for each concept in the apply set, write the proposed `human_path` and `llm_path` files. Update `docs/llm/INDEX.json` with the new `last_updated`, `confidence`, `depends_on`, `consumed_by`, `summary` fields.

**`--dry-run` mode:** write nothing. The presented diffs + the `proposed/` archive are the deliverable; tell the user to re-run without `--dry-run` to apply.

`deferred` concepts are never written — surface them to the user so they know those docs stayed stale.

## Phase 4.5 — Regenerate MEMORIES-FLAT.md

After all accepted concept files have been written in Phase 4, unconditionally regenerate `docs/llm/MEMORIES-FLAT.md` from all current `docs/llm/<slug>.json` files:

```bash
python3 scripts/regenerate-memories-flat.py --repo-root <abs_path>
```

This step runs after Phase 4 writes (default mode) and whenever a memory was deleted during Phase 3's stale-memories review. It covers the case where a memory was edited or deleted but no source file changed. Do not skip this step even if zero concepts were updated. (In `--dry-run` mode nothing was written, so there is nothing to regenerate — skip it.)

If the script exits non-zero, surface the error to the user and halt (do not proceed to Phase 5 with a potentially corrupt MEMORIES-FLAT.md).

## Phase 5 — Finalize

1. If `--audit` was used, delete the state file `docs/llm/.maintain_docs_audit_state.json` if it exists (cleanup; ignore errors).
2. Summary to user:
   ```
   docs/ refreshed:
     <N> concepts updated, <M> deferred (not_enough_info), <K> skipped (flagged → user skipped).
   ```
   If `--glossary` was used, append:
   ```
     Glossary: <NEW> terms added, <CHANGED> terms updated, <UNCHANGED> unchanged.
   ```
   Always end with:
   ```
   Recommended next:
     git add docs/ CONTEXT.md && git commit -m "Refresh z-harness docs"
   ```
3. Log:
   ```bash
   bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "docs" maintain_docs_end \
     "$(printf '{"mode":"%s","updated":%d,"deferred":%d,"skipped":%d}' "<mode>" "$U" "$D" "$S")"
   ```

## Hard rules

- **Default = apply.** Routine (`clean`) concepts are written without asking. Pass `--dry-run` to preview without writing. Only `flagged` concepts (`memories_lost`, or audit `rejected`/`needs review` under `--audit`) require per-concept confirmation before writing. The `--glossary` path follows the same apply-by-default posture.
- **Never modify code files.** This command only touches `docs/` and (with `--glossary`) `CONTEXT.md`.
- **Atomic per-concept writes.** A concept's human + LLM tiers update together or not at all (don't leave them out of sync).
- **Preserve git history.** Write to existing paths; don't create _v2 files.
- **Glossary is additive.** The `--glossary` refresh never removes existing `### <Term>` entries — only adds new ones or updates definitions. User-authored terms are preserved.
- **No emojis** in docs.

## Trigger patterns

- After `/z-implement-all` finalizes, the orchestrator's recommended-next push-notification lists `/z-maintain-docs`.
- After `/z-review-all` accepts a plan, same.
- Standalone: user runs whenever they suspect drift.
- Could be wired into CI as `claude /z-maintain-docs` (applies by default) if the user wants automated freshness.

---

## Runtime contract conformance

| Feature | Used | Gates |
|---------|------|-------|
| `subagent` | yes | Phase 1.5 Explore term extraction (only with `--glossary`); Phase 2 doc-updater (one per stale concept, up to 3 in parallel); Phase 2.5 consultant-primary + consultant-secondary (only with `--audit`) |
| `ask_user` | yes | Phase 2.3 compaction-pause decision (only with `--audit`); Phase 3 per-flagged-concept review (apply anyway / skip — fires only on `memories_lost` or audit reject/needs-review); Phase 3 stale-memory disposition (keep / edit / delete) |
| `skill_invoke` | no | — |

Driver support requirements: see frontmatter `driver_features_required`.

Non-supporting drivers **must surface and skip** any gated block — silent
omission is forbidden. Each gated call site is annotated with a
`<!-- RUNTIME-GATE: ... -->` comment immediately before the call.
