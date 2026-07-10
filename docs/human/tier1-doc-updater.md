# tier1-doc-updater

> Last updated: 2026-07-09
> Covers source: agents/tier1-doc-updater.md, scripts/reconcile-tier1-staged.py, scripts/add-doc-markers.py

## Overview

`tier1-doc-updater` is the cheap, mechanical Tier 1 documentation sync layer. It is a Haiku subagent dispatched **once at the end of a `/z-execute` run**, over the run's combined set of per-task diffs (`archive/tasks/*/diff.patch`). It reverse-lookups every changed file against `docs/llm/INDEX.json` and stages surgical updates for affected concepts. Its core rule is: the diff is the spec. It does not author narrative prose, infer design rationale, or inspect unrelated source code; it pattern-matches additions/removals against machine-truth sections.

Running once per run (rather than once per task) is deliberate: it guarantees exactly one staged doc per concept, which removes the cross-task write race that per-task dispatch would create under parallel execution. Each staged file is a full-doc snapshot, so two concurrent tasks touching the same concept would otherwise clobber each other's machine-truth updates.

The agent never writes live `docs/human/` or `docs/llm/` files. It writes staged `human.md` and `llm.json` files under `<staging_dir>/<concept>/` (the /z-execute step passes `staging_dir = $Z_HARNESS_PLAN_DIR/tier1-staged`); `scripts/reconcile-tier1-staged.py` then merges AUTO-marked human sections and selected LLM fields into live docs, updates INDEX metadata, and regenerates `MEMORIES-FLAT.md` before the run deregisters.

## Key entry points

<!-- AUTO-START: entry-points -->
- `agents/tier1-doc-updater.md:1` — Haiku agent definition; tools constrained to `Read, Grep, Glob, Write, Bash`.
- `agents/tier1-doc-updater.md:26` — reverse lookup: union of changed files across the diff set -> concept slugs via `source_files`/`source_file` in INDEX.
- `agents/tier1-doc-updater.md:36` — human update rules: only `AUTO-START`/`AUTO-END` delimited machine-truth sections.
- `agents/tier1-doc-updater.md:58` — LLM JSON update rules: `entry_points`, source-file arrays, and `last_updated`; preserve metadata and memories.
- `scripts/reconcile-tier1-staged.py:36` — `merge_human_doc()` — replaces matching AUTO sections in live human docs.
- `scripts/reconcile-tier1-staged.py:77` — `merge_llm_json()` — merges machine fields while preserving dependencies, confidence, invariants, gotchas, and memories.
- `scripts/reconcile-tier1-staged.py:106` — `update_index()` — updates touched concept metadata in INDEX during reconciliation.
- `scripts/reconcile-tier1-staged.py:128` — `main()` — scans `tier1-staged/`, merges staged docs, and regenerates memories flatfile.
- `scripts/add-doc-markers.py:36` — `add_markers_to_doc()` — idempotently adds AUTO markers around machine-truth sections.
- `scripts/add-doc-markers.py:82` — `main()` — scans human docs and supports `--dry-run`.
<!-- AUTO-END: entry-points -->

## How it interacts with others

- `/z-execute` — at Finalize (before deregister), dispatches ONE Tier 1 updater over the run's combined task diffs, then runs `reconcile-tier1-staged.py` to merge the staged docs. Best-effort: a doc-sync failure never aborts the run. Gated on `docs/llm/INDEX.json` existing.
- `/z-maintain-docs` / `doc-updater` — Tier 1 is narrow mechanical sync; maintain-docs is the fuller concept refresh path.
- `tier2-doc-rationale` — Tier 2 produces narrative ADR/rationale/migration docs from warm pipeline context, not per-diff machine fields.
- `docs/llm/INDEX.json` — source-file reverse lookup and later index metadata reconciliation.
- `regenerate-memories-flat.py` — run after reconciliation to keep memory projections current.

## Edge cases / gotchas

- The agent must never write live docs; staging only.
- It never edits prose outside AUTO markers and never touches `memories[]`.
- Concepts without AUTO markers are skipped and reported in NOTES; staged human updates would otherwise be silently dropped by reconciliation.
- Visibility-only changes such as `pub` -> `pub(crate)` are out of scope.
- One updater per run ⇒ exactly one staged doc per concept, so there is no cross-task staging race. (Do not revert to per-task dispatch without also making reconciliation merge sections at entry granularity — a per-task full-doc snapshot reverts sibling tasks' updates to the same concept.)
- The model is `haiku`, not `flash`; `flash` was not a valid Claude Code model identifier.

## Memories

<!-- DO NOT EDIT this section by hand — regenerated from docs/llm/tier1-doc-updater.json by doc-updater. Use /z-suggest-memory to add or edit memories. -->

_No memories recorded yet._

## Examples

```bash
python3 scripts/add-doc-markers.py --dry-run
python3 scripts/reconcile-tier1-staged.py --dry-run --plan-dir /path/to/plan
```
