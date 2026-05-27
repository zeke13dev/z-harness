---
cluster_id: C5
cluster_name: conformance-harness
parent_slug: harness-distribution-strategy
run_id: 20260527T050549Z-harness-distribution-strategy
status: draft
---

# PLAN — C5 conformance-harness

## Goal

C5 builds the cross-driver conformance test matrix for the harness-distribution-strategy runtime. The core job is: run a canonical `/z-do` invocation against each available driver, capture the output (events.jsonl shape, artifact paths created, exit status), normalize away known nondeterministic fields (timestamps, run-ids, model latency markers), and diff against checked-in golden fixtures. Any deviation is a conformance failure. The matrix gates new driver PRs and fixture changes. The v1 scope is deliberately narrow: one pilot command (`/z-do`), two to four driver rows (claude-code confirmed, codex confirmed, agy and cursor-agent gated on binary availability), replay mode for CI determinism, and a lightweight GitHub Actions path-filter job. No performance testing, no multi-command matrix, no full `/z-plan` in v1.

## Decisions

| ID | Question | Chosen option | Rationale |
|----|----------|---------------|-----------|
| C5-D1 | Which command is the pilot? | `/z-do` | Smallest command that exercises all required behaviors (subagent dispatch, AskUserQuestion, push notification, event log, artifact write) without hitting Antigravity's 12k limit that breaks `/z-plan`. |
| C5-D2 | What does "equivalent" mean? | Four-criteria equivalence | (a) same event type+field names modulo timestamps/run-ids; (b) same artifact path set; (c) same exit status; (d) normalized content matches fixture. Byte-identical rejected as too strict. |
| C5-D3 | Runner language? | Python | Matches existing `tests/` baseline; subprocess invocation pattern already established in `tests/test_resolve_provider.py`. |
| C5-D4 | When does CI run conformance? | Path-filter: `tests/conformance/`, `runtime/`, `drivers/` | Avoids running expensive driver invocations on every PR; catches the changes that matter. |
| C5-D5 | LLM mock strategy? | Replay mode (recorded fixtures) + live mode (manual) | Replay is fully deterministic and safe for CI; live mode enables smoke tests and fixture recording. `--record` flag captures a live run and writes replay fixtures. |

## Non-goals (v1)

- Full `/z-plan` in the conformance matrix.
- Performance or latency assertions.
- Multi-command matrix beyond `/z-do`.
- Testing the install / packaging flow.
- Driver implementation (owned by C2/C3/C4).
- Runtime contract definition (owned by C1).
- Concurrent driver execution (sequential in v1, one driver at a time).

## Approved shortcuts

- Golden fixtures for `agy` and `cursor-agent` drivers are placeholder directories only in v1; they are populated when the driver lands, not before.
- Replay fixtures are recorded from a single live run; no statistical sampling of nondeterminism in v1.
- `Makefile` entry is a simple `python -m pytest tests/conformance` invocation; no parallelism or distributed runner.

## Phases

### Phase A — Normalization layer

Build `normalize.py`: the function that takes raw JSONL and strips/replaces nondeterministic fields before comparison.

Nondeterminism sources per RESEARCH.md:
- Timestamps: replace with `"__TIMESTAMP__"` (ISO 8601 pattern match).
- Run-IDs: replace with `"__RUN_ID__"` (matches `YYYYMMDDTHHMMSSZ-*` pattern).
- Model latency: strip `latency_ms`, `duration_ms`, `elapsed_s` fields.
- Prompt-cache state: strip `cache_hit`, `cache_miss`, `cached_tokens` fields.
- Token counts: strip `input_tokens`, `output_tokens` (vary by model version and cache state).

Normalization is applied to both the captured output and the golden fixture before diffing, so fixtures themselves can be stored in raw form (easier to read) or normalized form (smaller diff surface). Decision: store fixtures normalized — simpler diff, simpler record step.

### Phase B — Golden fixture capture (claude-code driver)

Run `/z-do` against the claude-code driver in `--record` mode to produce the initial golden fixtures. This requires the C1 runtime-core and C2/C3/C4 drivers to be at least partially implemented. Phase B is a dependency on C1; it cannot complete until C1's `HostDriver` ABC and dispatcher exist and the claude-code driver is wired.

Record output:
- `fixtures/z-do/claude-code/events.golden.jsonl` — normalized JSONL of events.
- `fixtures/z-do/claude-code/artifacts.golden.txt` — newline-separated list of relative artifact paths.
- `fixtures/z-do/claude-code/exit.golden` — `"0"` or `"nonzero"`.
- `replay/z-do/claude-code.jsonl` — raw recorded LLM responses for replay mode.

### Phase C — Runner + driver-availability gating

Build `run_conformance.py`: discovers available drivers (checks `which <binary>` for each registered driver), skips unavailable ones with a structured `skipped` result, runs available drivers sequentially, normalizes output, diffs against fixture, emits conformance JSONL report.

Driver-availability check order:
1. `claude` binary (claude-code driver).
2. `codex` binary (codex driver).
3. `agy` binary (agy driver — may be unavailable; see RESEARCH.md open question on npm 404).
4. `cursor-agent` binary (cursor-agent driver).

### Phase D — Pytest integration + conftest

Wrap the runner in a pytest parameterized test (`test_matrix.py`) so the matrix integrates with the existing `pytest` invocation and produces JUnit XML for CI. `conftest.py` provides fixtures for temp workdirs and driver-availability marks (`@pytest.mark.skipif`).

### Phase E — CI job

Write `.github/workflows/conformance.yml` with:
- `paths` filter on `tests/conformance/**`, `runtime/**`, `drivers/**`.
- `on: [pull_request, workflow_dispatch]`.
- Single job: install Python deps, run `pytest tests/conformance --mode=replay --junitxml=...`.
- Upload JUnit XML as artifact.
- Fixture-bump check: if any `tests/conformance/fixtures/**` file is modified, assert PR description contains `CONFORMANCE-BUMP:` (via `gh pr view --json body`).
- `Makefile` target `conformance` for local use.

## Risks

1. **C1/C2 dependency.** Phase B (fixture capture) cannot run until C1's dispatcher and at least one driver exist. If C1 or C2 slip, Phase B and all subsequent phases block. Mitigation: Phase A (normalization) and Phase D (pytest scaffolding) can proceed independently; Phase C runner can be written against a mock driver interface.
2. **`agy` binary not publicly available.** RESEARCH.md flags `npm install -g @google/antigravity` → 404 as of 2026-05-21. If agy stays unavailable, the agy row remains a placeholder and never blocks CI. Risk is low for CI gating; risk is moderate for completeness of the conformance claim.
3. **LLM replay fixture staleness.** If C1 changes the prompt structure sent to the model, replay fixtures become stale and produce incorrect normalization diffs. Mitigation: `--record` step is cheap to re-run; fixture re-recording is documented as required whenever the prompt template changes.
4. **Normalization gap.** A nondeterministic field we did not anticipate (e.g. a new event type added by a driver) causes intermittent CI failures. Mitigation: normalization is a separate module with its own unit tests; adding a new stripping rule is a one-line change.
5. **Fixture-bump check brittleness.** The `gh pr view --json body` check may fail on draft PRs, forked PRs, or when `gh` is not authenticated. Mitigation: make the check advisory (warning, not failure) in v1.

## DRY / KISS / SOLID applied

- **KISS:** one pilot command, one runner script, one CI job. No framework abstraction layer in v1.
- **DRY:** `normalize.py` is imported by both `run_conformance.py` and `test_matrix.py`; normalization logic is not duplicated.
- **Single responsibility:** `normalize.py` strips nondeterminism; `run_conformance.py` orchestrates driver invocation and diffing; `test_matrix.py` is only the pytest wrapper. These are three separate files, not one god-script.
- **Open/closed:** adding a new driver row requires adding a fixture directory and a driver entry in a config list; no modification to `run_conformance.py` core logic.
