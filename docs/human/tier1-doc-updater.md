# tier1-doc-updater

> Last updated: 2026-06-09
> Covers source: agents/tier1-doc-updater.md, scripts/reconcile-tier1-staged.py, scripts/add-doc-markers.py

## Overview

Tier 1 is the per-task mechanical doc sync layer of the two-tier automatic doc maintenance system. A Flash subagent reads the task diff and applies surgical updates to machine-truth fields in delimited sections of human-tier and LLM-tier documentation.

Tier 1 runs automatically after each task's reviewer passes in `/z-implement-all`. Updated docs are staged to `tier1-staged/<concept>/` and reconciled into `docs/` after all tasks complete.

## Key entry points

<!-- AUTO-START: entry-points -->
- `scripts/reconcile-tier1-staged.py` — Reconcile staged Tier 1 updates into live docs
- `scripts/add-doc-markers.py` — Add AUTO-START/AUTO-END markers to existing human docs
- `agents/tier1-doc-updater.md` — Flash subagent definition
<!-- AUTO-END: entry-points -->

## How it interacts with others

- **z-implement-all** — Dispatches tier1-doc-updater per task after reviewer passes. Runs reconciliation in Finalize.
- **doc-updater** — Tier 1 handles per-task mechanical sync; doc-updater (Sonnet) remains the quarterly deep-clean fallback for `/z-maintain-docs`.
- **tier2-doc-rationale** — Tier 2 handles narrative docs (ADRs, rationale, migration guides) from accumulated context.
- **INDEX.json** — Used for file-to-concept reverse lookup during Tier 1 dispatch.

## Edge cases / gotchas

- Tier 1 NEVER writes to `docs/` directly — staging only.
- If a concept doc lacks AUTO-START/AUTO-END markers, Tier 1 skips it and logs `markers_missing`.
- Visibility-only changes (`pub` → `pub(crate)`) are out of scope for Tier 1.
- Tier 1 never touches `memories[]` — memory authoring always goes through `/z-suggest-memory`.
