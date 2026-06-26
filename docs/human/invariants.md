# Invariants

> Last updated: 2026-06-24
> Covers source: docs/INVARIANTS.json

## Overview

`docs/INVARIANTS.json` is the canonical durable invariant registry for z-harness. It is user-authored and optional, not generated automatically. The current registry is schema version 1 and contains 14 invariants (`inv_001, inv_002, inv_003, inv_004, inv_005, inv_006, inv_007, inv_008, inv_009, inv_010, inv_011, inv_012, inv_013, inv_014`) covering behavioral test quality, adversarial fixture validity, atomic writes, pipeline resilience, export fidelity, artifact commits, feed observability, INTENT immutability, legacy routing, configuration discipline, and Hermes gating.

Each invariant has a stable `inv_NNN` id, severity, controlled tags, failure class, provenance source, `source_files`, `last_updated`, and optional `fixture_schema`/`fixture_defaults` or sighting fields. Downstream commands can use these entries as durable, repo-specific behavioral constraints; absence of the file is normal and consumers must fall back gracefully.

## Key entry points

- `docs/INVARIANTS.json:1` — top-level registry object with `version`, `generated_at`, and `invariants[]`.
- `docs/INVARIANTS.json:6` — `inv_001`: invariant tests must verify behavioral properties, not just unit-level function returns.
- `docs/INVARIANTS.json:36` — `inv_002`: adversarial fixtures must match the invariant fixture schema.
- `docs/INVARIANTS.json:65` — `inv_003`: writes to INVARIANTS.json must be atomic.
- `docs/INVARIANTS.json:94` — `inv_005`: consultant subagents must be able to dispatch even when the repo lacks a generated providers config.
- `docs/INVARIANTS.json:139` — `inv_008`: feed connectivity checks at tier boundaries must stay observable.
- `docs/INVARIANTS.json:155` — `inv_009`: frozen INTENT.md is immutable.
- `docs/INVARIANTS.json:171` — `inv_010`: a level's TASKS.md is immutable while that level executes.
- `docs/INVARIANTS.json:186` — `inv_011`: LEDGER.md is append-only.
- `docs/INVARIANTS.json:202` — `inv_012`: legacy SPEC/PLAN/TASKS plans stay on the legacy path.
- `docs/INVARIANTS.json:218` — `inv_013`: new behavior must not be driven by new env vars; use config files.
- `docs/INVARIANTS.json:233` — `inv_014`: old Hermes machinery is gated by `workflow.hermes_enabled=true`.

## How it interacts with others

- `/z-test` — can seed behavioral test plans from stable `inv_NNN` ids when INVARIANTS.json exists; falls back to SPEC/INTENT extraction when absent.
- `/z-review-all` — in INTENT mode, passes INVARIANTS.json as part of the durable tier so consultants can flag invariant violations.
- Adaptive INTENT — inv_009, inv_010, and inv_011 encode immutability rules for frozen INTENT, per-level TASKS, and append-only LEDGER.
- Validation/check scripts — external validators enforce structure, tag discipline, fixture constraints, and blocker coverage; those scripts are consumers, while this concept's source of truth is the JSON file itself.

## Edge cases / gotchas

- Do not auto-generate INVARIANTS.json; hollow invariants without domain judgment are worse than absence.
- `id` values are stable and never reused; deprecate rather than recycle.
- `source_files` inside entries may themselves become stale while the behavioral invariant remains valid; update the entry instead of treating the whole registry as generated output.
- `fixture_defaults` is meaningful only alongside `fixture_schema`.
- Optional sighting fields (`sighting_count`, `last_sighting`, `anchor_module`) may be absent when no review run has triggered the invariant.
- Tags must stay within the controlled tag set used by the docs/memory layer.

## Memories

<!-- DO NOT EDIT this section by hand — regenerated from docs/llm/invariants.json by doc-updater. Use /z-suggest-memory to add or edit memories. -->

_No memories recorded yet._

## Examples

- Current severities: blocker and major.
- Current provenance values include `spec`, `plan`, `user-concern`, `code-review`, and `axiom-derived`.
- Stable id format: `inv_001`, `inv_014`.
