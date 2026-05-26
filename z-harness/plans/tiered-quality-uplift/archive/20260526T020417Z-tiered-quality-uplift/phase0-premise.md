# Phase 0 — Premise accepted

## Goal
Build a tiered, one-time-or-on-demand bulk codebase quality uplift workflow as a new top-level command `/z-uplift`, layered above existing per-component `/z-audit` and `/z-implement-all`.

## Approach (confirmed via user gate)
1. **Decompose**: auto-detect components (Rust crates / Python packages / top-level dirs) → user confirms.
2. **Cross-cutting scan**: repo-wide `/z-review-all`-style pass that surfaces inter-component issues (duplicated abstractions, style drift, dead code at boundaries) BEFORE per-component audits.
3. **Per-component audits**: dispatch `/z-audit`-equivalent per component, each emitting its own TASKS.md, with cross-cutting findings injected as input.
4. **All audits complete** → user reviews the aggregated queue → drives `/z-implement-all` sequentially per component.

## Premise notes
- "N plans to amend" in original prompt → really N audit-produced TASKS.md files, NOT `/z-amend`. Confirmed.
- Single dedicated `/z-uplift` entry point with progress tracking across components.
- No pipelining (audit C1 → implement C1 → audit C2…) — full picture before any code changes.
