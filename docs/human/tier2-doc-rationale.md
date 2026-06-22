# tier2-doc-rationale

> Last updated: 2026-06-19
> Covers source: commands/z-doc-rationale.md, scripts/append-tier2-context.py

## Overview

Tier 2 is the end-of-pipeline narrative doc layer of the two-tier automatic doc maintenance system. It reads `tier2-context.json` — a structured JSON file accumulated incrementally across pipeline phases — and produces Architecture Decision Records (ADRs), design rationale, tradeoff explanations, and migration guides. The system is composed of two parts: `scripts/append-tier2-context.py`, which accumulates structured context during pipeline execution, and the `/z-doc-rationale` command, which spawns a Sonnet subagent to produce the final narrative outputs.

Currently, only `z-review-all` calls `append-tier2-context.py`: Phase 5.5 accumulates aggregate review patterns, and Phase 6.7 finalizes the file and evaluates the three-signal OR significance gate (cross-LLM consultant findings, breaking changes, or plan deviations). The script is designed to accept `--phase plan|implement|review` and support accumulation from any pipeline stage, but z-plan and z-execute do not currently invoke it. The user runs `/z-doc-rationale` after the full pipeline completes if the significance gate fired.

## Key entry points

- `commands/z-doc-rationale.md:1` — `z-doc-rationale` — Four-phase command: Setup (slug discovery, finalized validation, memoization), Phase 1 (Sonnet draft generation), Phase 2 (gap-fill conversation), Phase 3 (write finals + cross-link concept docs + memoize)
- `scripts/append-tier2-context.py:112` — `main` — CLI entry point; parses --phase, --field, --json, --upsert, --mark-amended and writes atomically to tier2-context.json
- `scripts/append-tier2-context.py:70` — `validate_payload` — Per-field schema validator enforcing required keys before any write
- `scripts/append-tier2-context.py:92` — `save_context` — Atomic write via tmp file + os.replace
- `scripts/append-tier2-context.py:101` — `upsert_entry` — Deduplication by key fields (task/id) for repeated pipeline runs

## How it interacts with others

- `z-review-all` — The only current caller of append-tier2-context.py: accumulates review_patterns (Phase 5.5), finalizes the file and evaluates the significance gate (Phase 6.7), then optionally recommends /z-doc-rationale
- `tier1-doc-updater` — Tier 1 handles per-task mechanical doc sync during implementation; Tier 2 handles narrative docs from the accumulated pipeline context after review is complete
- `commands` — /z-doc-rationale is part of the commands concept surface; exports exist for pi, agy, codex, and the MCP server

## Edge cases / gotchas

- `tier2-context.json` must be marked `finalized: true` before `/z-doc-rationale` can run; it aborts if not.
- Only z-review-all currently writes to tier2-context.json. The script supports `--phase plan|implement|review` for future use, but z-plan and z-execute do not call it.
- Significance gate is a three-signal OR: consultant_findings non-empty, breaking_changes non-empty, OR deviations non-empty. If none fire, the pipeline reports "No significant design decisions. Tier 2 skipped."
- Memoization: if tier2-context.json has not changed since the last run (hash comparison via .memo file), regeneration is skipped entirely.
- Documents ship with honest gaps — missing human override reasons are flagged with "> Warning: Reason not captured at decision time." Never fabricated.
- Tried-and-failed entries carry a confidence caveat: "Auto-generated from implementer self-reports. Reviewer validation: partial."
- ADR numbering: reads `docs/adr/` for the max existing N, allocates N+1 sequentially. Starts at ADR-001 if `docs/adr/` does not exist.
- Upsert mode (`--upsert`): deduplicates by task field for tried_and_failed/deviations/breaking_changes, by id for decisions. Without --upsert, entries always append.
- `--mark-amended` appends a plan_amended event to `amend_events[]` (not a standard schema field; handled ad-hoc).

## Memories

<!-- DO NOT EDIT this section by hand — regenerated from docs/llm/tier2-doc-rationale.json by doc-updater. Use /z-suggest-memory to add or edit memories. -->

_No memories recorded yet._

## Examples

- Full pipeline flow: z-plan → z-execute → z-review-all (accumulates review_patterns, finalizes) → /z-doc-rationale (if significance gate fired)
- Accumulate a review pattern: `python3 scripts/append-tier2-context.py --phase review --field review_patterns --json '{"pattern":"...", "source":"consultant-primary", "finding":"...", "recommendation":"..."}'`
- Upsert a task deviation: `python3 scripts/append-tier2-context.py --phase review --field deviations --upsert --json '{"task":"T001", "deviation":"...", "reason":"..."}'`
- Check significance: inspect `consultant_findings`, `breaking_changes`, and `deviations` arrays in tier2-context.json after z-review-all
