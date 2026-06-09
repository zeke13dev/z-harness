# tier2-doc-rationale

> Last updated: 2026-06-09
> Covers source: commands/z-doc-rationale.md, scripts/append-tier2-context.py

## Overview

Tier 2 is the end-of-pipeline narrative doc layer of the two-tier automatic doc maintenance system. It reads `tier2-context.json` — a 3-5K token JSON file accumulated incrementally across all pipeline phases — and produces Architecture Decision Records (ADRs), design rationale, tradeoff explanations, and migration guides.

Tier 2 fires after `/z-review-all` completes and is significance-gated: a three-signal OR gate (cross-LLM consult, breaking changes, or plan deviations) determines whether narrative docs are recommended. The user runs `/z-doc-rationale` when ready.

## Key entry points

<!-- AUTO-START: entry-points -->
- `commands/z-doc-rationale.md` — `/z-doc-rationale` command definition
- `scripts/append-tier2-context.py` — Incremental context accumulation script
<!-- AUTO-END: entry-points -->

## How it interacts with others

- **z-plan** — Initializes tier2-context.json with decisions and consultant findings during Phase 3.
- **z-implement-all** — Accumulates tried_and_failed, deviations, and breaking_changes per task. Captures human override reasons.
- **z-review-all** — Accumulates review_patterns. Finalizes tier2-context.json and evaluates the significance gate.
- **tier1-doc-updater** — Tier 1 handles per-task mechanical sync; Tier 2 handles narrative docs from accumulated context.
- **doc-updater** — Tier 2 produces ADRs and rationale; doc-updater (Sonnet) remains the quarterly deep-clean fallback.

## Edge cases / gotchas

- tier2-context.json must be marked `finalized: true` before `/z-doc-rationale` can run.
- Documents ship with honest gaps — missing human override reasons are flagged, never fabricated.
- Tried-and-failed entries include a confidence caveat: "Auto-generated from implementer self-reports."
- Memoization: if tier2-context.json hasn't changed since the last run, regeneration is skipped.
- ADR numbering: reads `docs/adr/` for max N, allocates N+1 sequentially.
