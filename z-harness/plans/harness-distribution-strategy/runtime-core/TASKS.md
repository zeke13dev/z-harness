---
artifact: tasks
cluster_id: C1
cluster_name: runtime-core
root_slug: harness-distribution-strategy
run_id: 20260527T050549Z-harness-distribution-strategy
schema_version: 1
generated_at: 2026-05-27T05:05:49Z
---

# TASKS — C1: runtime-core

## Phase A — Schema definitions

- [ ] **T001 — Write command.schema.json**
  - **Files:** runtime/contract/command.schema.json
  - **Depends:** none
  - **Acceptance:**
    - File is valid JSON Schema Draft 7 (`$schema` declaration present).
    - Top-level `schema_version: 1` field present.
    - Schema requires: `id` (kebab-case string pattern), `description` (string), `argument_hint` (string, optional), `body` (string), `schema_version` (integer const 1).
    - A sample fixture `{"id":"z-plan","description":"Run planning pipeline","body":"...","schema_version":1}` validates without errors.
    - A fixture missing `id` fails validation with a descriptive error path.
  - **Complexity:** medium

- [ ] **T002 — Write agent.schema.json**
  - **Files:** runtime/contract/agent.schema.json
  - **Depends:** none
  - **Acceptance:**
    - Valid JSON Schema Draft 7 with `schema_version: 1`.
    - Schema requires: `name` (string), `description` (string), `model` (enum: `haiku`, `sonnet`, `opus`), `tools` (array of strings, optional), `triggers` (array of strings, optional), `schema_version` (integer const 1).
    - Sample fixture for `implementer` agent validates.
    - Fixture with invalid `model` value fails validation.
  - **Complexity:** medium

- [ ] **T003 — Write provider.schema.json**
  - **Files:** runtime/contract/provider.schema.json
  - **Depends:** none
  - **Acceptance:**
    - Valid JSON Schema Draft 7 with `schema_version: 1`.
    - Schema accepts (does not break) the existing `.z-harness/providers.json` shape: top-level `version` (integer), `roles` (object of string→string), `providers` (object of string→provider-entry).
    - Each provider entry requires: `kind` (enum: `cli`, `sdk`), `command` (string), `args_template` (array), `stdin` (boolean), `timeout_s` (integer), `model_label` (string).
    - Each provider entry optionally allows: `auth_env` (string — the env-var name holding the API key for SDK-tier auth), `session_resumable` (boolean, default false).
    - The existing `.z-harness/providers.json` (no `auth_env` field) validates successfully (field is optional).
    - A provider entry with `kind: "sdk"` and `auth_env: "ANTHROPIC_API_KEY"` validates successfully.
  - **Complexity:** medium

- [ ] **T004 — Write event.schema.json**
  - **Files:** runtime/contract/event.schema.json
  - **Depends:** none
  - **Acceptance:**
    - Valid JSON Schema Draft 7 with `schema_version: 1`.
    - Schema requires: `run_id` (string), `kind` (string), `ts` (string, ISO 8601 pattern), `schema_version` (integer const 1), `payload` (object, additional properties allowed).
    - Extends today's log-event.sh event shape: existing events (which lack `schema_version`) fail validation (this is expected — compat shim adds the field before dispatch).
    - Sample `dispatch_start` event fixture validates.
    - Sample `schema_validation_error` event fixture validates.
  - **Complexity:** medium

- [ ] **T005 — Write skill.schema.json**
  - **Files:** runtime/contract/skill.schema.json
  - **Depends:** none
  - **Acceptance:**
    - Valid JSON Schema Draft 7 with `schema_version: 1`.
    - Schema requires: `id` (kebab-case string), `description` (string), `schema_version` (integer const 1).
    - Optional fields: `input_schema` (JSON Schema object), `output_schema` (JSON Schema object), `tags` (array of strings).
    - Sample fixture validates; fixture missing `id` fails.
  - **Complexity:** medium

## Phase B — Dispatch package scaffold

- [ ] **T006 — Create runtime package init and validate.py**
  - **Files:** runtime/__init__.py, runtime/validate.py
  - **Depends:** T001, T002, T003, T004, T005
  - **Acceptance:**
    - `runtime/__init__.py` exports `__version__ = "0.1.0"` and `SCHEMA_VERSION = 1`.
    - `runtime/validate.py` exports `validate(schema_name: str, instance: dict) -> None` that loads the named schema from `runtime/contract/<schema_name>.schema.json` and raises `jsonschema.ValidationError` on failure.
    - `validate("command", {...})` succeeds for a valid command fixture.
    - `validate("command", {})` raises `ValidationError`.
    - No external dependencies beyond `jsonschema` are introduced.
  - **Complexity:** low

- [ ] **T007 — Implement HostDriver ABC (driver.py)**
  - **Files:** runtime/dispatch/driver.py, runtime/dispatch/__init__.py
  - **Depends:** T006
  - **Acceptance:**
    - `HostDriver` is an abstract base class (Python `abc.ABC`).
    - Three methods: `init(provider_config: dict) -> None` (abstract), `dispatch(command_id: str, args: list[str], env: dict) -> DispatchResult` (abstract), `teardown() -> None` (concrete no-op default).
    - Attempting to instantiate `HostDriver` directly raises `TypeError`.
    - A minimal concrete subclass that implements `init` and `dispatch` can be instantiated.
    - Docstring on each method documents the expected behavior contract for driver implementers (C2/C3/C4).
  - **Complexity:** medium

- [ ] **T008 — Implement DispatchResult dataclass (result.py)**
  - **Files:** runtime/dispatch/result.py
  - **Depends:** T006
  - **Acceptance:**
    - `DispatchResult` is a Python dataclass with fields: `exit_code: int`, `is_error: bool`, `stdout_events: list[dict]`, `stderr: str`, `wall_ms: float`, `session_id: str | None`.
    - `DispatchResult.success` property returns `True` iff `exit_code == 0 and not is_error`.
    - `DispatchResult` can be constructed with minimal args: `DispatchResult(exit_code=0, is_error=False, stdout_events=[], stderr="", wall_ms=0.0, session_id=None)`.
  - **Complexity:** medium

- [ ] **T009 — Implement env hygiene module (env.py)**
  - **Files:** runtime/dispatch/env.py
  - **Depends:** T003, T006
  - **Acceptance:**
    - `build_env(provider_config: dict, base_env: dict | None = None) -> dict` function.
    - If `base_env` is None, starts from `os.environ.copy()`.
    - Always sets `CLAUDECODE = ""` (empty string, not unset) in the returned dict.
    - If `provider_config` contains `auth_env` key (string), reads that env-var from `base_env` (or os.environ) and injects it under its own name in the returned dict. If the env-var is not set, the key is omitted from the returned dict (not set to empty).
    - Returns a new dict; does not mutate `base_env`.
    - Unit-testable without subprocess: pass a synthetic `base_env`.
  - **Complexity:** medium

- [ ] **T010 — Implement timeout + reap (timeout.py)**
  - **Files:** runtime/dispatch/timeout.py
  - **Depends:** T006
  - **Acceptance:**
    - `TimeoutReaper` context manager that wraps a `subprocess.Popen` instance.
    - Constructor accepts `proc: Popen`, `timeout_s: int`.
    - On exit, if `proc` is still running: send SIGTERM, wait 5s, then SIGKILL if still alive.
    - Raises `DispatchTimeoutError(timeout_s, pid)` (a custom exception defined in this module) if the timeout expires before the process exits normally.
    - Does not raise if the process exits within `timeout_s`.
  - **Complexity:** medium

- [ ] **T011 — Stub session resumption helpers (session.py)**
  - **Files:** runtime/dispatch/session.py
  - **Depends:** T006
  - **Acceptance:**
    - `generate_session_id() -> str` returns a UUID4 string.
    - `assert_uuid_format(session_id: str) -> None` raises `ValueError` if the string is not a valid UUID.
    - `resume_session(session_id: str, driver: HostDriver) -> None` raises `NotImplementedError` with message "Session resumption is not yet implemented. See RESEARCH.md open questions."
    - Module-level docstring explains the stub status and cites the RESEARCH.md open question.
  - **Complexity:** medium

## Phase C — Dispatcher core

- [ ] **T012 — Implement dispatcher core (dispatcher.py)**
  - **Files:** runtime/dispatch/dispatcher.py
  - **Depends:** T007, T008, T009, T010, T011
  - **Acceptance:**
    - `Dispatcher` class with `run(driver: HostDriver, command_id: str, args: list[str], provider_config: dict, session_id: str | None = None) -> DispatchResult` method.
    - Calls `build_env(provider_config)` to get the subprocess env.
    - Calls `driver.dispatch(command_id, args, env)` with the clean env.
    - Parses `--output-format stream-json` JSONL from the driver's stdout: each line is JSON-decoded; lines where `type == "result"` and `is_error == true` set `DispatchResult.is_error = True`. Non-JSON lines are collected in `stderr`.
    - Applies `TimeoutReaper` using `provider_config.get("timeout_s", 300)`.
    - Emits `dispatch_start` event (via `runtime/compat.py`) before calling `driver.dispatch()`.
    - Emits `dispatch_end` event (via `runtime/compat.py`) after `driver.dispatch()` returns, including `wall_ms`, `exit_code`, `is_error`.
    - Returns a `DispatchResult` in all cases (timeout → `is_error=True`, `exit_code=-1`).
  - **Complexity:** high

## Phase D — Compat shim

- [ ] **T013 — Implement runtime/compat.py**
  - **Files:** runtime/compat.py
  - **Depends:** T006, T004
  - **Acceptance:**
    - `resolve_provider(role: str, repo_root: str) -> dict` calls `scripts/resolve-provider.py <role>` as a subprocess and returns parsed JSON. Raises `RuntimeError` on non-zero exit.
    - `log_event(run_id: str, kind: str, payload: dict, repo_root: str, slug: str | None = None) -> None` adds `schema_version: 1` to `payload` if missing, then calls `scripts/log-event.sh <run_id> <kind> <json>` as a subprocess. Uses `Z_HARNESS_SLUG` env-var if `slug` is provided.
    - Neither function modifies the scripts themselves.
    - Both functions can be exercised in tests by pointing `repo_root` at the actual repo root.
  - **Complexity:** medium

## Phase E — Validation smoke tests

- [ ] **T014 — Write contract validation tests (test_contract.py)**
  - **Files:** runtime/tests/__init__.py, runtime/tests/test_contract.py, runtime/tests/fixtures/command_valid.json, runtime/tests/fixtures/agent_valid.json, runtime/tests/fixtures/provider_valid.json, runtime/tests/fixtures/event_valid.json, runtime/tests/fixtures/skill_valid.json
  - **Depends:** T001, T002, T003, T004, T005, T006
  - **Acceptance:**
    - `pytest runtime/tests/test_contract.py` passes with zero failures.
    - Each of the five schema files is validated against the JSON Schema meta-schema (Draft 7).
    - Each valid fixture validates without error.
    - An invalid fixture (missing required field) fails validation for each schema.
    - The existing `.z-harness/providers.json` file validates against `provider.schema.json` (backward compat invariant).
  - **Complexity:** low

- [ ] **T015 — Write dispatch unit tests (test_dispatch.py)**
  - **Files:** runtime/tests/test_dispatch.py
  - **Depends:** T007, T008, T009, T010, T011, T012
  - **Acceptance:**
    - `pytest runtime/tests/test_dispatch.py` passes with zero failures.
    - `HostDriver` cannot be instantiated directly (test asserts `TypeError`).
    - `env.py`: CLAUDECODE is always set to `""` in `build_env` output; `auth_env` injection works with synthetic base_env; no mutation of input dict.
    - `session.py`: `resume_session()` raises `NotImplementedError`.
    - `timeout.py`: `TimeoutReaper` sends SIGTERM on timeout (use a subprocess that sleeps forever; assert it is reaped within 6s).
    - `DispatchResult.success` returns correct values for (0, False), (1, False), (0, True) cases.
  - **Complexity:** high

- [ ] **T016 — Write compat shim integration test (test_compat.py)**
  - **Files:** runtime/tests/test_compat.py
  - **Depends:** T013
  - **Acceptance:**
    - `pytest runtime/tests/test_compat.py` passes with zero failures.
    - `resolve_provider("codex", repo_root)` returns a dict with keys `command`, `args_template`, `timeout_s` when the codex provider is present in `.z-harness/providers.json`.
    - `log_event(run_id, "test_event", {"x": 1}, repo_root)` writes a line to `z-harness/archive/<run_id>/events.jsonl` containing `schema_version: 1`.
    - Test uses a unique `run_id` prefix (`test-compat-XXXXXXXX`) and cleans up the archive dir after.
  - **Complexity:** medium
