# Invariants

> Last updated: 2026-06-19
> Covers source: docs/INVARIANTS.json, docs/schemas/invariant.schema.json, scripts/validate-invariants.py, scripts/invariant-check.sh

## Overview

`docs/INVARIANTS.json` is the per-repo durable invariant registry — a hand-authored (never auto-generated) catalog of system-level behavioral truths that must hold across all plan implementations. Each entry names a concrete failure class, severity tier (blocker/major/minor), controlled tag set, provenance source, and optional fixture schema for structured test data. The file is versioned (currently schema v1 with 14 entries, inv_001 through inv_014) and must be written atomically (tempfile → flush → fsync → os.replace) per inv_003.

The registry feeds two downstream consumers: `/z-test` uses it as the primary seed for behavioral test planning — mapping invariants to tasks by tag overlap and generating TESTS.md entries keyed to stable `inv_NNN` IDs — and `/z-review-all` passes the full file as the durable tier to each consultant subagent in INTENT mode, so reviewers can flag acceptance-criterion violations against declared invariants. A thin validation layer (`scripts/validate-invariants.py`) enforces structural and semantic constraints (id uniqueness, tag subset, fixture_schema non-triviality, fixture_defaults compatibility) at write time; `scripts/invariant-check.sh` provides a CI gate that reads TESTS.md, checks blocker-invariant coverage, and runs the test suite.

## Key entry points

- `docs/INVARIANTS.json:1` — top-level registry: `{"version": 1, "generated_at": "...", "invariants": [...]}`
- `docs/schemas/invariant.schema.json:1` — JSON Schema draft-2020-12 for each invariant entry; 11 fields (id, description, tags, failure_class, fixture_schema, fixture_defaults, severity, source_files, last_updated, source, sighting_count/last_sighting/anchor_module optional)
- `scripts/validate-invariants.py:145` — `validate_invariants_file()`: exit 0=valid, 1=schema error, 2=constraint violation, 3=I/O error; also exposes `--fixture`+`--schema` mode for fixture-only validation
- `scripts/invariant-check.sh:1` — CI runner: reads TESTS.md + INVARIANTS.json, gates on uncovered blocker invariants (exit 3), runs test suite, optionally runs full-chain tests; exit 0=pass, 1=test failure, 3=coverage gap, 4=I/O error
- `commands/z-test.md:83` — primary consumer: loads INVARIANTS.json as v2 seed path; absence is expected (falls back to SPEC.md/INTENT.md extraction)
- `commands/z-review-all.md:203` — passes `$INVARIANTS_PATH` (docs/INVARIANTS.json) as durable tier to both consultant subagents in INTENT mode

## How it interacts with others

- `z-test` — primary consumer; maps invariant entries to TASKS.md tasks by tag-keyword overlap, produces TESTS.md entries with stable `invariant_id: inv_NNN` references; INVARIANTS.json absence falls back gracefully to v1 mode
- `z-review-all` — in INTENT mode, passes the full INVARIANTS.json as the durable tier alongside frozen INTENT and LEDGER; consultants flag acceptance-criterion violations against declared invariants
- `z-init-docs` — writer; the atomic-write discipline for INVARIANTS.json is declared in inv_003 and enforced by `validate-invariants.py`
- `adaptive-intent` — inv_009 (INTENT.md immutability) and inv_010/inv_011 (per-level TASKS.md and LEDGER.md immutability) are entries in INVARIANTS.json that the INTENT engine must honor
- `scripts` (TAGS.txt) — `validate-invariants.py` reads `docs/llm/TAGS.txt` to enforce that invariant `tags[]` entries are a subset of the controlled tag set

## Edge cases / gotchas

- INVARIANTS.json is user-authored and optional. Its absence is explicitly designed for and not an error — `/z-test` and `/z-review-all` both degrade gracefully. Attempting to auto-generate it will produce hollow entries without domain knowledge.
- The `docs/INVARIANTS.md` file is a rendered human-readable view generated from INVARIANTS.json; it currently shows only 8 invariants while the canonical JSON has 14. The JSON is authoritative — the `.md` is stale.
- inv_006 references `exports/export-pi.py` and `scripts/export-codex-skills.py` as source files; both paths are from the pre-export-runtime-drivers era. The actual export logic now lives in `runtime/drivers/*/export.py`. The inv_006 source_files are stale but the behavioral property itself is still valid.
- `fixture_defaults` is only valid when `fixture_schema` is also present. `validate-invariants.py` enforces this (constraint exit 2), not the JSON Schema.
- `invariant-check.sh` auto-discovers TESTS.md under `z-harness/plans/*/` and `plans/*/`; it does not search the legacy flat `z-harness/TASKS.md` path. If the plan dir is non-standard, pass `--tests-file` explicitly.
- `sighting_count`, `last_sighting`, and `anchor_module` are optional fields that `/z-review-all` Phase 5.5 increments on finding matches. None of the current 14 entries have these fields populated (never yet sighted via a review run).
- Tag validation against TAGS.txt is done at validate time; if a new tag is needed, add it to TAGS.txt first.

## Examples

- Invariant id pattern: `inv_001`, `inv_014` — sequential 3-digit zero-padded; never reused after deprecation
- Provenance sources: `spec` (mined from SPEC.md), `plan`, `user-concern`, `code-review`, `axiom-derived`
- Severity tiers: `blocker` (PR gate fail), `major` (PR gate warn), `minor` (informational)
- Current entries by category: test-quality (inv_001, inv_002), write-atomicity (inv_003), pipeline-resilience (inv_004, inv_005), export-fidelity (inv_006), artifact-commit (inv_007), feed-observability (inv_008), INTENT-engine immutability (inv_009, inv_010, inv_011), legacy-routing (inv_012), config-file-only knobs (inv_013), Hermes-flag-gate (inv_014)
