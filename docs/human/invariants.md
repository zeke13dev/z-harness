# Invariants

> Last updated: 2026-07-09
> Covers source: docs/INVARIANTS.json

## Overview

`docs/INVARIANTS.json` is the canonical durable invariant registry for z-harness. It is user-authored and optional, not generated automatically anywhere in the codebase (`/z-test`'s SKILL.md is explicit that "there is intentionally no generator for it"). The current registry is schema version 1 and contains 14 invariants (`inv_001` through `inv_014`) covering behavioral test quality, adversarial fixture validity, atomic writes, review-pipeline resilience, export fidelity, artifact commits, feed observability, INTENT/TASKS/LEDGER immutability, legacy-plan routing, config-not-env discipline, and Hermes gating.

Each invariant has a stable `inv_NNN` id, `description`, controlled `tags[]`, `failure_class`, `severity` (`blocker` / `major` / `minor` per the schema, though the current registry only uses `blocker` and `major`), `source_files[]`, `last_updated`, provenance `source`, and optional `fixture_schema` / `fixture_defaults` / sighting fields. The entry shape is enforced by `docs/schemas/invariant.schema.json` and validated by `scripts/validate-invariants.py`. Downstream commands read these entries as durable, repo-specific behavioral constraints; absence of the file is normal and every consumer falls back gracefully.

## Key entry points

- `docs/INVARIANTS.json:1` — top-level registry object with `version`, `generated_at`, and `invariants[]`.
- `docs/INVARIANTS.json:6` — `inv_001`: invariant tests must verify behavioral properties, not just unit-level function returns.
- `docs/INVARIANTS.json:36` — `inv_002`: adversarial fixtures must match the invariant's `fixture_schema`.
- `docs/INVARIANTS.json:66` — `inv_003`: writes to INVARIANTS.json must be atomic (tempfile + fsync + `os.replace()`).
- `docs/INVARIANTS.json:95` — `inv_005`: consultant subagents must be able to dispatch even when doc staleness is high.
- `docs/INVARIANTS.json:140` — `inv_008`: feed connectivity checks at tier boundaries must stay observable, not fail silently.
- `docs/INVARIANTS.json:156` — `inv_009`: frozen INTENT.md is immutable after `frozen_at` is stamped.
- `docs/INVARIANTS.json:172` — `inv_010`: a level's TASKS.md is immutable while that level executes.
- `docs/INVARIANTS.json:187` — `inv_011`: LEDGER.md is append-only.
- `docs/INVARIANTS.json:203` — `inv_012`: legacy SPEC/PLAN/TASKS plans stay on the legacy execution path.
- `docs/INVARIANTS.json:219` — `inv_013`: new behavior must not be driven by new env vars; use `scripts/config.py`-resolvable file config.
- `docs/INVARIANTS.json:234` — `inv_014`: old Hermes machinery is gated by `workflow.hermes_enabled=true`.
- `docs/schemas/invariant.schema.json:1` — the JSON Schema every entry must satisfy (required fields, tag enum, severity enum, source enum).
- `scripts/validate-invariants.py:1` — CLI validator: id uniqueness, tag subset of `docs/llm/TAGS.txt`, fixture_schema/defaults consistency, severity enum, non-empty source_files.
- `scripts/invariant-check.sh:1` — CI-friendly gate: reads INVARIANTS.json + TESTS.md, runs the test command, exits non-zero on mandatory-invariant coverage gaps or failures.

## How it interacts with others

- `/z-test` — when `docs/INVARIANTS.json` exists, uses its entries as additional behavioral test seeds (tagged `seed: invariants-json`); falls back to extracting seeds from the plan contract directly when the file is absent.
- `/z-execute` — resolves `INVARIANTS_PATH` once per run and threads it through to the `implementer` and `reviewer` subagent prompts as `invariants_path:`; both subagents are instructed to treat a violation as a blocking `spec_problem` / review finding.
- `/z-review-all` — in INTENT mode, passes INVARIANTS.json as part of the durable tier (`$INVARIANTS_PATH`) so consultants can flag invariant violations directly in `findings.md`.
- Adaptive INTENT — `inv_009`, `inv_010`, and `inv_011` encode the immutability rules for frozen INTENT, per-level TASKS, and append-only LEDGER that the BFS execution engine must respect.
- `scripts/validate-invariants.py` / `scripts/invariant-check.sh` / `docs/schemas/invariant.schema.json` — structural and CI-gate consumers; they enforce shape and coverage but are not part of the registry's source of truth.

## Edge cases / gotchas

- Do not auto-generate INVARIANTS.json; hollow invariants without domain judgment are worse than absence.
- `id` values are stable and never reused; deprecate rather than recycle (rename = new id + deprecate old, per the schema).
- `source_files` inside entries may themselves become stale while the behavioral invariant remains valid; update the entry instead of treating the whole registry as generated output.
- `fixture_defaults` is meaningful only alongside `fixture_schema`, and must itself validate against that schema.
- Several schema field descriptions describe integrations that are not currently wired up in the actual skills: `sighting_count` / `last_sighting` / `anchor_module` are documented as being set by "`z-review-all` Phase 5.5 on first match," but the current Phase 5.5 in `skills/z-review-all/SKILL.md` accumulates `tier2-context.json` review patterns, not per-invariant sightings. Likewise `/z-init-docs --invariants` discovery and `/z-maintain-docs` `source_files`-mtime staleness detection (both referenced in the schema's field descriptions) have no corresponding logic in `skills/z-init-docs/SKILL.md` or `skills/z-maintain-docs/SKILL.md` today. Treat these fields/flows as reserved/forward-looking, not live behavior, until confirmed otherwise.
- Tags must stay within the controlled tag set in `docs/llm/TAGS.txt` (currently: correctness, perf, data-quality, schema, time-window, units, api-boundary, retry-loop, race-condition, dependency, deprecation, lossy-default, ux, observability, compliance); `scripts/validate-invariants.py` enforces this.

## Memories

<!-- DO NOT EDIT this section by hand — regenerated from docs/llm/invariants.json by doc-updater. Use /z-suggest-memory to add or edit memories. -->

_No memories recorded yet._

## Examples

- Schema-allowed severities: `blocker`, `major`, `minor`; the current registry only uses `blocker` and `major`.
- Schema-allowed provenance (`source`) values: `spec`, `plan`, `user-concern`, `code-review`, `axiom-derived`; every current entry uses `spec`.
- Stable id format: `inv_001` .. `inv_014`, zero-padded 3-digit sequence.
