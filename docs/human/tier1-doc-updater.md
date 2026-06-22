# tier1-doc-updater

> Last updated: 2026-06-19
> Covers source: agents/tier1-doc-updater.md, scripts/reconcile-tier1-staged.py, scripts/add-doc-markers.py

## Overview

Tier 1 is the per-task mechanical doc sync layer of the two-tier automatic doc maintenance system. A Haiku subagent (labeled "Flash-tier" in the plan, but pinned to `model: haiku` in Claude Code) reads the task diff and applies surgical updates to machine-truth fields in `<!-- AUTO-START -->` / `<!-- AUTO-END -->` delimited sections of human-tier and LLM-tier documentation. The core principle is: the diff IS the spec — no reasoning, no prose writing, only pattern-matching diff additions and removals against known machine-truth sections.

Tier 1 is dispatched automatically from `/z-execute` after each task's reviewer passes. Updated docs are staged under `$Z_HARNESS_PLAN_DIR/tier1-staged/<concept>/` and reconciled into `docs/` after all tasks complete via `scripts/reconcile-tier1-staged.py`. The agent is constrained to `Read, Grep, Glob, Write, Bash` tools only — it does not have access to Agent() and cannot spawn sub-subagents.

## Key entry points

<!-- AUTO-START: entry-points -->
- `agents/tier1-doc-updater.md:1` — `tier1-doc-updater` — Haiku subagent definition for per-task mechanical doc sync; tools constrained to Read/Grep/Glob/Write/Bash; model: haiku
- `scripts/reconcile-tier1-staged.py:128` — `main()` — CLI entry: merges staged AUTO-START/AUTO-END sections from `tier1-staged/` into live `docs/`; updates INDEX.json; regenerates MEMORIES-FLAT.md
- `scripts/reconcile-tier1-staged.py:36` — `merge_human_doc()` — Merges staged human doc sections into live human doc by replacing matching AUTO-START/AUTO-END blocks
- `scripts/reconcile-tier1-staged.py:77` — `merge_llm_json()` — Merges `entry_points`, `source_file`, `source_files`, `last_updated` from staged LLM JSON into live LLM JSON; preserves `depends_on`, `consumed_by`, `summary`, `confidence`, `memories`, `invariants`, `gotchas`
- `scripts/reconcile-tier1-staged.py:106` — `update_index()` — Updates INDEX.json `last_updated` for all touched concepts
- `scripts/add-doc-markers.py:36` — `add_markers_to_doc()` — Idempotent: wraps `## Key entry points`, `## Public API`, `## Exports`, `## Configuration` sections in AUTO-START/AUTO-END markers
- `scripts/add-doc-markers.py:82` — `main()` — CLI entry: scans `docs/human/*.md` and applies markers; `--dry-run` supported
<!-- AUTO-END: entry-points -->

## How it interacts with others

- **z-execute** — Dispatches `tier1-doc-updater` (Haiku) per task after the reviewer passes; runs `reconcile-tier1-staged.py` in Finalize phase.
- **doc-updater** — Tier 1 handles per-task mechanical sync; `doc-updater` (Sonnet) is the deep-clean agent for `/z-maintain-docs` full concept refreshes.
- **tier2-doc-rationale** — Sibling system; Tier 2 handles narrative docs (ADRs, design rationale, migration guides) accumulated from plan/implement/review context. `tier2-doc-rationale` depends on `tier1-doc-updater`.
- **INDEX.json** — Used for file-to-concept reverse lookup during Tier 1 dispatch (`source_files` and `source_file` arrays).
- **regenerate-memories-flat.py** — Called by `reconcile-tier1-staged.py` post-merge to keep `MEMORIES-FLAT.md` current.

## Edge cases / gotchas

- Tier 1 NEVER writes to `docs/` directly — all output goes to the staging directory.
- If a concept doc lacks `<!-- AUTO-START -->` / `<!-- AUTO-END -->` markers, Tier 1 skips that concept and logs in NOTES; use `add-doc-markers.py` to instrument docs first.
- Visibility-only changes (`pub` → `pub(crate)`) are out of scope and intentionally ignored.
- Tier 1 never touches `memories[]` — memory authoring always goes through `/z-suggest-memory`.
- The agent frontmatter uses `model: haiku`; the old `model: flash` was an invalid identifier that resolved to nothing in Claude Code.
- The agent has an explicit `tools:` constraint (`Read, Grep, Glob, Write, Bash`); previously it inherited ALL tools (including Agent). Sibling mechanical agents (doc-fetcher, context-curator) use the same constrained set.
- If the live doc has no AUTO-START sections, `merge_human_doc()` returns the live content unchanged — staged human updates are silently dropped.
- Reconciliation uses a latest-wins strategy for overlapping staged updates to the same concept.

## Examples

- After a task adds a new `fn parse_event(...)` to a source file covered by concept `followup-sink`, Tier 1 reads the diff, finds the `entry-points` AUTO section in `docs/human/followup-sink.md`, appends the new entry, and stages the result to `$Z_HARNESS_PLAN_DIR/tier1-staged/followup-sink/human.md`.
- `python3 scripts/add-doc-markers.py --dry-run` previews which docs would receive markers without writing anything.
- `python3 scripts/reconcile-tier1-staged.py --dry-run --plan-dir /path/to/plan` shows what would be merged.
