---
cluster_id: C5
cluster_name: conformance-harness
parent_slug: harness-distribution-strategy
run_id: 20260527T050549Z-harness-distribution-strategy
status: draft
---

# TASKS — C5 conformance-harness

- [ ] **T001 — Create tests/conformance/ directory skeleton**
  - **Files:** tests/conformance/__init__.py, tests/conformance/fixtures/z-do/.gitkeep, tests/conformance/replay/z-do/.gitkeep
  - **Depends:** none
  - **Acceptance:**
    - `tests/conformance/` exists and is importable as a Python package.
    - `tests/conformance/fixtures/z-do/` and `tests/conformance/replay/z-do/` exist.
    - `.gitkeep` files are committed so empty dirs are tracked.
  - **Complexity:** low

- [ ] **T002 — Implement normalize.py (nondeterminism stripper)**
  - **Files:** tests/conformance/normalize.py
  - **Depends:** T001
  - **Acceptance:**
    - `normalize_events(jsonl_str: str) -> str` strips timestamps (ISO 8601), run-IDs (`YYYYMMDDTHHMMSSZ-*`), `latency_ms`, `duration_ms`, `elapsed_s`, `cache_hit`, `cache_miss`, `cached_tokens`, `input_tokens`, `output_tokens` fields from each JSONL line.
    - Replacement values: timestamps -> `"__TIMESTAMP__"`, run-IDs -> `"__RUN_ID__"`, numeric nondeterministic fields -> removed from the dict (not replaced with a sentinel).
    - Lines that are not valid JSON are passed through unchanged.
    - `normalize_artifact_list(paths: list[str]) -> list[str]` sorts the list and strips any path prefix containing `__RUN_ID__`-matching segments.
    - All behaviors covered by unit tests in `tests/conformance/test_normalize.py`.
  - **Complexity:** low

- [ ] **T003 — Unit tests for normalize.py**
  - **Files:** tests/conformance/test_normalize.py
  - **Depends:** T002
  - **Acceptance:**
    - At least 6 test cases: timestamp stripped, run-id stripped, numeric field removed, non-JSON line passed through, empty input handled, artifact path prefix stripped.
    - `pytest tests/conformance/test_normalize.py` passes with no failures.
  - **Complexity:** low

- [ ] **T004 — Implement run_conformance.py (main runner)**
  - **Files:** tests/conformance/run_conformance.py
  - **Depends:** T002
  - **Acceptance:**
    - CLI: `python tests/conformance/run_conformance.py --command z-do --mode replay|live [--record] [--drivers claude-code,codex,agy,cursor-agent]`.
    - Driver availability: checks `which <binary>` for each driver; marks unavailable drivers as `skipped`.
    - Replay mode: loads `tests/conformance/replay/z-do/<driver>.jsonl` and passes it to the driver invocation as a mock response feed (exact interface TBD by C1/C2 runtime hook; runner accepts a `--replay-hook` env var that points to a shim script if the driver does not natively support replay).
    - For each available driver: invokes the driver, captures events.jsonl output path and artifact paths from the driver's exit metadata, runs `normalize_events()` on captured events, diffs against `fixtures/z-do/<driver>/events.golden.jsonl`, diffs artifact path list against `fixtures/z-do/<driver>/artifacts.golden.txt`, checks exit code against `fixtures/z-do/<driver>/exit.golden`.
    - `--record` mode: runs live driver, normalizes output, writes to fixtures and replay dirs.
    - Emits structured JSONL to stdout: `conformance_run_start`, `driver_run_start`, `driver_run_end`, `conformance_run_end` events as specified in SPEC.md.
    - Returns exit code 0 if all non-skipped drivers pass, nonzero otherwise.
  - **Complexity:** medium

- [ ] **T005 — Create placeholder golden fixtures for claude-code driver**
  - **Files:** tests/conformance/fixtures/z-do/claude-code/events.golden.jsonl, tests/conformance/fixtures/z-do/claude-code/artifacts.golden.txt, tests/conformance/fixtures/z-do/claude-code/exit.golden
  - **Depends:** T001
  - **Acceptance:**
    - Placeholder files exist with a header comment: `# PLACEHOLDER: run with --record once claude-code driver is wired (C1+C2 dependency)`.
    - `exit.golden` contains the string `0`.
    - `artifacts.golden.txt` contains one placeholder line: `# PLACEHOLDER`.
    - `events.golden.jsonl` is an empty file (zero lines).
    - These files are committed; they cause conformance to fail (by design) until replaced by a real `--record` run.
  - **Complexity:** low

- [ ] **T006 — Create placeholder golden fixtures for codex driver**
  - **Files:** tests/conformance/fixtures/z-do/codex/events.golden.jsonl, tests/conformance/fixtures/z-do/codex/artifacts.golden.txt, tests/conformance/fixtures/z-do/codex/exit.golden
  - **Depends:** T001
  - **Acceptance:**
    - Same placeholder structure as T005 but for the codex driver.
    - `exit.golden` contains `0`.
  - **Complexity:** low

- [ ] **T007 — Create placeholder golden fixtures for agy and cursor-agent drivers**
  - **Files:** tests/conformance/fixtures/z-do/agy/events.golden.jsonl, tests/conformance/fixtures/z-do/agy/artifacts.golden.txt, tests/conformance/fixtures/z-do/agy/exit.golden, tests/conformance/fixtures/z-do/cursor-agent/events.golden.jsonl, tests/conformance/fixtures/z-do/cursor-agent/artifacts.golden.txt, tests/conformance/fixtures/z-do/cursor-agent/exit.golden
  - **Depends:** T001
  - **Acceptance:**
    - Same placeholder structure as T005 for both `agy` and `cursor-agent`.
    - Runner's driver-availability check skips these rows gracefully when the binary is absent.
  - **Complexity:** low

- [ ] **T008 — Implement conftest.py and test_matrix.py (pytest integration)**
  - **Files:** tests/conformance/conftest.py, tests/conformance/test_matrix.py
  - **Depends:** T004, T005, T006, T007
  - **Acceptance:**
    - `conftest.py` provides: `tmp_workdir` fixture (tmpdir with a minimal repo stub), `driver_available(driver_name)` helper that returns True/False based on `which` check, `DRIVERS` list constant.
    - `test_matrix.py` has a single parameterized test `test_driver_conformance[driver]` that calls `run_conformance.py` via subprocess with `--mode=replay --drivers <driver>` and asserts exit 0 (or skips if driver unavailable).
    - `pytest tests/conformance/ -k "not record"` runs without errors (placeholder fixtures cause the claude-code and codex rows to report "fail" on the diff check, but the pytest test itself passes with an `xfail` mark on rows that have placeholder fixtures — these are expected failures until real fixtures are recorded).
    - Running `pytest tests/conformance/test_normalize.py` still passes independently.
  - **Complexity:** medium

- [ ] **T009 — GitHub Actions conformance.yml CI job**
  - **Files:** .github/workflows/conformance.yml
  - **Depends:** T008
  - **Acceptance:**
    - Triggers on `pull_request` and `workflow_dispatch`.
    - `paths` filter: `tests/conformance/**`, `runtime/**`, `drivers/**`.
    - Job: `python -m pytest tests/conformance/ --mode=replay --junitxml=conformance-report.xml`.
    - Uploads `conformance-report.xml` as a CI artifact.
    - Advisory fixture-bump check: if `git diff --name-only origin/main... | grep -q "tests/conformance/fixtures"`, then `gh pr view --json body` is checked for `CONFORMANCE-BUMP:`; emits a warning (not failure) if absent.
    - Job does NOT require agy or cursor-agent to be installed; those rows are automatically skipped.
  - **Complexity:** low

- [ ] **T010 — Makefile conformance target**
  - **Files:** Makefile
  - **Depends:** T008
  - **Acceptance:**
    - `make conformance` runs `python -m pytest tests/conformance/ --mode=replay -v`.
    - `make conformance-live` runs `python -m pytest tests/conformance/ --mode=live -v` (manual only, not in CI).
    - `make conformance-record DRIVER=<driver>` runs `python tests/conformance/run_conformance.py --command z-do --mode live --record --drivers <driver>`.
    - Existing Makefile targets are not modified.
  - **Complexity:** low
