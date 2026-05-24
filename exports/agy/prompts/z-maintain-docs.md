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

For each stale concept, spawn a `doc-updater` subagent. In dry-run mode, leave `mode: dry-run` (default); in apply mode, set `mode: write`.

```
<!-- agent dispatch / skill invocation not supported in Antigravity; see CAPABILITIES.md -->
  subagent_type="doc-updater",
  description="Refresh docs for <concept>",
  prompt="concept: <slug>\nhuman_path: docs/human/<slug>.md\nllm_path: docs/llm/<slug>.json\nsource_files: <paths from INDEX.json>\nreason: <stale|drift|spec_change>\nmode: <dry-run|write>\nrepo_root: <abs path>"
)
```

Up to 3 in parallel per batch (`Z_HARNESS_PARALLEL=N` env override).

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

Ask via `AskUserQuestion`:
- **Apply all** → re-run this command with `--apply` (or apply now in-place; user choice).
- **Apply a subset** → user picks which concepts.
- **Skip** → leave docs as-is; concepts stay flagged for next run.

## Phase 4 — Apply (apply mode only)

For each accepted concept, write the proposed `human_path` and `llm_path` files. Update `docs/llm/INDEX.json` with the new `last_updated`, `confidence`, `depends_on`, `consumed_by`, `summary` fields.

If any concept's source files changed enough that the doc-updater couldn't produce confident output (`STATUS: not_enough_info`), DO NOT write — surface to user.

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
