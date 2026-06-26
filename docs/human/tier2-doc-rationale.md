# tier2-doc-rationale

> Last updated: 2026-06-24
> Covers source: skills/z-doc-rationale/SKILL.md, scripts/append-tier2-context.py

## Overview

`tier2-doc-rationale` is the narrative documentation layer for completed z-harness pipelines. It consumes finalized `tier2-context.json` and produces ADRs, design rationale, tradeoff explanations, migration guides, and cross-links back into concept docs. It is intentionally downstream of implementation and review: Tier 1 keeps machine-truth fields synchronized during execution, while Tier 2 captures why important decisions were made after enough context exists.

`/z-doc-rationale` discovers a plan dir, validates that `tier2-context.json` is finalized, skips regeneration when the memoized hash matches, dispatches a Sonnet `doc-updater` to draft narrative outputs, asks only for missing gap content, then writes final files under `$Z_HARNESS_PLAN_DIR/tier2/`. `scripts/append-tier2-context.py` is the accumulator used by pipeline phases; currently `/z-review-all` is the active writer, accumulating review patterns and finalizing the context/significance gate.

## Key entry points

- `skills/z-doc-rationale/SKILL.md:1` — `/z-doc-rationale` command surface and runtime contract.
- `skills/z-doc-rationale/SKILL.md:13` — setup: discover plan slug/dir or abort if no `tier2-context.json` exists.
- `skills/z-doc-rationale/SKILL.md:29` — finalized validation: aborts unless `tier2-context.json.finalized` is true.
- `skills/z-doc-rationale/SKILL.md:45` — memoization: hash `tier2-context.json` and skip if `$Z_HARNESS_PLAN_DIR/tier2/.memo` matches.
- `skills/z-doc-rationale/SKILL.md:56` — draft generation: Sonnet doc-updater produces ADRs, rationale, migration guide, and tried-and-failed material.
- `skills/z-doc-rationale/SKILL.md:103` — gap-fill conversation: asks only for missing gap fields; skipped gaps are documented honestly.
- `skills/z-doc-rationale/SKILL.md:119` — final writes: ADR numbering, rationale, optional migration guide, concept-doc cross-links, and memo file.
- `scripts/append-tier2-context.py:70` — `validate_payload()` — validates per-field payload shape before any write.
- `scripts/append-tier2-context.py:92` — `save_context()` — atomic write to `tier2-context.json` using temp file and `os.replace`.
- `scripts/append-tier2-context.py:101` — `upsert_entry()` — deduplicates by task/id key fields.
- `scripts/append-tier2-context.py:112` — `main()` — CLI for `--phase plan|implement|review`, `--field`, `--json`, `--upsert`, and `--mark-amended`.

## How it interacts with others

- `z-review-all` — current active caller for accumulation and finalization; significant context triggers a recommendation to run `/z-doc-rationale`.
- `tier1-doc-updater` — complementary mechanical sync layer; Tier 2 is narrative and decision-oriented.
- `doc-updater` — used as the Sonnet drafting agent for narrative docs.
- Concept docs — final phase can append/update `design-decisions` AUTO sections linking ADRs.

## Edge cases / gotchas

- `tier2-context.json` must be finalized; draft generation is blocked until the full pipeline completes.
- Only `/z-review-all` currently writes Tier 2 context, even though the accumulator supports plan/implement/review phases.
- Significance is a three-signal OR: consultant findings, breaking changes, or deviations. If none fire, Tier 2 is skipped.
- Tried-and-failed entries must carry the confidence caveat that they come from implementer self-reports and are only partially reviewer-validated.
- Missing human override reasons are never fabricated; docs ship with an honest gap note.
- ADR numbers are allocated from existing `docs/adr/` max N, starting at ADR-001 if absent.
- `--mark-amended` appends to an ad-hoc `amend_events[]` field, not the standard skeleton.

## Memories

<!-- DO NOT EDIT this section by hand — regenerated from docs/llm/tier2-doc-rationale.json by doc-updater. Use /z-suggest-memory to add or edit memories. -->

_No memories recorded yet._

## Examples

```bash
/z-doc-rationale
python3 scripts/append-tier2-context.py --phase review --field review_patterns --json '{"pattern":"...","source":"consultant-primary","finding":"...","recommendation":"..."}'
python3 scripts/append-tier2-context.py --phase review --field deviations --upsert --json '{"task":"T001","deviation":"...","reason":"..."}'
```
