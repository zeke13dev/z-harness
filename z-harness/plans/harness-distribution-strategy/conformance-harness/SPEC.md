---
cluster_id: C5
cluster_name: conformance-harness
parent_slug: harness-distribution-strategy
run_id: 20260527T050549Z-harness-distribution-strategy
status: draft
---

# SPEC — C5 conformance-harness

## Overview

The conformance harness asserts that the same `/z-*` command invocation against each supported driver produces equivalent artifacts: the same event types in the event log, the same set of artifact file paths created, the same exit status, and normalized content that matches golden fixtures after stripping known nondeterministic fields. It owns `tests/conformance/` and the golden-output fixtures stored therein. It defines the gating rule for new drivers: no driver lands without a passing conformance row, and no change breaks conformance without an explicit fixture bump accompanied by rationale. The harness is test infrastructure — it does not implement any driver or define the runtime contract; it consumes those artifacts as test subjects.

## Surface

Files this cluster owns:

```
tests/conformance/
tests/conformance/run_conformance.py          # main runner script
tests/conformance/normalize.py               # nondeterminism stripper (timestamps, run-ids, model-latency)
tests/conformance/fixtures/
tests/conformance/fixtures/z-do/
tests/conformance/fixtures/z-do/claude-code/ # golden fixtures for claude-code driver
tests/conformance/fixtures/z-do/claude-code/events.golden.jsonl
tests/conformance/fixtures/z-do/claude-code/artifacts.golden.txt   # newline-sep list of relative paths
tests/conformance/fixtures/z-do/claude-code/exit.golden            # "0" or "nonzero"
tests/conformance/fixtures/z-do/codex/       # golden fixtures for codex driver
tests/conformance/fixtures/z-do/codex/events.golden.jsonl
tests/conformance/fixtures/z-do/codex/artifacts.golden.txt
tests/conformance/fixtures/z-do/codex/exit.golden
tests/conformance/fixtures/z-do/agy/         # placeholder; skipped if agy unavailable
tests/conformance/fixtures/z-do/cursor-agent/  # placeholder; skipped if cursor-agent unavailable
tests/conformance/replay/
tests/conformance/replay/z-do/               # recorded LLM response fixtures per driver
tests/conformance/replay/z-do/claude-code.jsonl
tests/conformance/replay/z-do/codex.jsonl
tests/conformance/conftest.py                # pytest fixtures + driver-availability gates
tests/conformance/test_matrix.py             # parameterized pytest test file
.github/workflows/conformance.yml            # CI path-filter + matrix job
Makefile                                     # `make conformance` local target (append-only)
```

## Non-goals

- Does not implement any driver (C2 driver-codex, C3 driver-agy, C4 driver-cursor own that).
- Does not define the runtime contract or event schema (C1 runtime-core owns that).
- Does not test performance, latency, or token cost.
- Does not test the full `/z-plan` command (too large for deterministic fixture capture; pilot is `/z-do` only in v1).
- Does not test the shipping / install flow (C6 shipping owns that).
- Does not provide end-to-end integration tests that require all drivers simultaneously available; each driver row is independently skippable.

## Invariants

1. **No driver row silently passes when the driver binary is absent.** Unavailable drivers are marked `skipped: <binary> unavailable`, not `passed`.
2. **Fixture files are checked into the repo.** Golden fixtures are source-controlled; they are not generated at CI time from live runs.
3. **Replay mode is the CI default.** Live-model calls are never made in CI without explicit `--mode=live` flag.
4. **A new driver PR must add fixture rows.** The CI job fails if a driver directory exists under `drivers/` with no corresponding fixture directory under `tests/conformance/fixtures/z-do/<driver>/`.
5. **Fixture bumps require rationale.** The PR description must include a `CONFORMANCE-BUMP: <reason>` line when any golden file is modified; the CI job enforces this via a git-diff check.
6. **Normalization is applied before diffing.** The runner never diffs raw output; it always applies `normalize.py` first.

## Telemetry / events

The runner emits a structured conformance report to stdout in JSONL format with these event types:

- `conformance_run_start` — `{command, mode, drivers: [...], run_id}`
- `driver_run_start` — `{driver, command, mode}`
- `driver_run_end` — `{driver, command, result: "pass"|"fail"|"skipped", reason?, diff_lines?}`
- `conformance_run_end` — `{command, passed, failed, skipped, total}`

These events are separate from the z-harness `events.jsonl` produced by the driver under test; they describe the test execution, not the command execution.
