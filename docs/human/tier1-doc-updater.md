# tier1-doc-updater

> Last updated: 2026-06-24
> Covers source: agents/tier1-doc-updater.md, scripts/reconcile-tier1-staged.py, scripts/add-doc-markers.py

## Overview

`tier1-doc-updater` is the cheap, mechanical Tier 1 documentation sync layer. It is a Haiku subagent that receives one completed task diff, reverse-lookups changed files against `docs/llm/INDEX.json`, and stages surgical updates for affected concepts. Its core rule is: the diff is the spec. It does not author narrative prose, infer design rationale, or inspect unrelated source code; it pattern-matches additions/removals against machine-truth sections.

The agent never writes live `docs/human/` or `docs/llm/` files. It writes staged `human.md` and `llm.json` files under `$Z_HARNESS_PLAN_DIR/tier1-staged/<concept>/`; `scripts/reconcile-tier1-staged.py` later merges AUTO-marked human sections and selected LLM fields into live docs, updates INDEX metadata, and regenerates `MEMORIES-FLAT.md`.

## Key entry points

<!-- AUTO-START: entry-points -->
- `agents/tier1-doc-updater.md:1` — Haiku agent definition; tools constrained to `Read, Grep, Glob, Write, Bash`.
- `agents/tier1-doc-updater.md:24` — reverse lookup: changed files -> concept slugs via `source_files`/`source_file` in INDEX.
- `agents/tier1-doc-updater.md:34` — human update rules: only `AUTO-START`/`AUTO-END` delimited machine-truth sections.
- `agents/tier1-doc-updater.md:56` — LLM JSON update rules: `entry_points`, source-file arrays, and `last_updated`; preserve metadata and memories.
- `scripts/reconcile-tier1-staged.py:36` — `merge_human_doc()` — replaces matching AUTO sections in live human docs.
- `scripts/reconcile-tier1-staged.py:77` — `merge_llm_json()` — merges machine fields while preserving dependencies, confidence, invariants, gotchas, and memories.
- `scripts/reconcile-tier1-staged.py:106` — `update_index()` — updates touched concept metadata in INDEX during reconciliation.
- `scripts/reconcile-tier1-staged.py:128` — `main()` — scans `tier1-staged/`, merges staged docs, and regenerates memories flatfile.
- `scripts/add-doc-markers.py:36` — `add_markers_to_doc()` — idempotently adds AUTO markers around machine-truth sections.
- `scripts/add-doc-markers.py:82` — `main()` — scans human docs and supports `--dry-run`.
<!-- AUTO-END: entry-points -->

## How it interacts with others

- `/z-execute` — dispatches Tier 1 after a task's reviewer passes, then reconciles staged docs during finalization.
- `/z-maintain-docs` / `doc-updater` — Tier 1 is narrow mechanical sync; maintain-docs is the fuller concept refresh path.
- `tier2-doc-rationale` — Tier 2 produces narrative ADR/rationale/migration docs from warm pipeline context, not per-diff machine fields.
- `docs/llm/INDEX.json` — source-file reverse lookup and later index metadata reconciliation.
- `regenerate-memories-flat.py` — run after reconciliation to keep memory projections current.

## Edge cases / gotchas

- The agent must never write live docs; staging only.
- It never edits prose outside AUTO markers and never touches `memories[]`.
- Concepts without AUTO markers are skipped and reported in NOTES; staged human updates would otherwise be silently dropped by reconciliation.
- Visibility-only changes such as `pub` -> `pub(crate)` are out of scope.
- Latest staged update wins if multiple staged updates touch the same concept.
- The model is `haiku`, not `flash`; `flash` was not a valid Claude Code model identifier.

## Memories

<!-- DO NOT EDIT this section by hand — regenerated from docs/llm/tier1-doc-updater.json by doc-updater. Use /z-suggest-memory to add or edit memories. -->

_No memories recorded yet._

## Examples

```bash
python3 scripts/add-doc-markers.py --dry-run
python3 scripts/reconcile-tier1-staged.py --dry-run --plan-dir /path/to/plan
```
