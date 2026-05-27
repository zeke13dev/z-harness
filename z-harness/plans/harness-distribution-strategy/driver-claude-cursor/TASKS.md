---
cluster_id: C4
cluster_name: driver-claude-cursor
run_id: 20260527T050549Z-harness-distribution-strategy
---

# TASKS — C4: driver-claude-cursor

## Phase A — Claude driver foundation

- [ ] **T001 — Implement env_hygiene.py: CLAUDECODE clearing + --bare flag helper**
  - **Files:** runtime/drivers/claude/env_hygiene.py
  - **Depends:** none
  - **Acceptance:**
    - `build_subprocess_env()` returns a dict with CLAUDECODE set to empty string, regardless of parent env
    - `CLAUDECODE_VAR` and `BARE_FLAG` are module-level constants (no string literals elsewhere)
    - `apply_env_hygiene(base_env)` merges base_env with the required overrides and returns a new dict (does not mutate input)
    - A `detect_self_hosted()` helper returns True iff `os.environ.get("CLAUDECODE")` is non-empty
    - Unit test: calling `apply_env_hygiene({"CLAUDECODE": "1"})` yields `{"CLAUDECODE": ""}` merged with base
    - `cleared_vars` list emitted to caller (for telemetry); does not log values
  - **Complexity:** low

- [ ] **T002 — Implement SelfHostDriver skeleton (in-process HostDriver)**
  - **Files:** runtime/drivers/claude/self_host_driver.py, runtime/drivers/claude/__init__.py
  - **Depends:** T001
  - **Acceptance:**
    - `SelfHostDriver` implements C1 `HostDriver` protocol (all abstract methods present)
    - `__init__` asserts `detect_self_hosted()` is True or `force=True` kwarg is passed; raises `DriverInitError` otherwise
    - `execute_command(cmd, context)` delegates to in-process tool primitives (Read/Edit/Bash/Agent) rather than spawning a subprocess — initial implementation may raise `NotImplementedError` for tool primitives pending C1 interface definition, but the dispatch skeleton must be in place
    - `driver_selected` event is emitted with `detection_method="env"` or `"explicit"`
    - No subprocess is spawned under any code path in this class
  - **Complexity:** medium

- [ ] **T003 — Implement SubprocessClaudeDriver skeleton (claude -p --bare)**
  - **Files:** runtime/drivers/claude/subprocess_driver.py
  - **Depends:** T001
  - **Acceptance:**
    - `SubprocessClaudeDriver` implements C1 `HostDriver` protocol
    - `_build_args()` always includes `--bare` and `--output-format stream-json --verbose`
    - `_spawn(prompt, session_id=None)` calls `apply_env_hygiene()` before `subprocess.Popen`; never inherits parent CLAUDECODE
    - If `session_id` is provided, validates it is a UUID4 string before passing `--resume <id>`; raises `ValueError` on invalid format
    - `subprocess_spawn` and `subprocess_exit` telemetry events are emitted; args list is redacted (no API key values)
    - On non-zero exit code, reads `is_error` from last stream-json line before raising `DriverExecutionError`
  - **Complexity:** medium

## Phase B — Claude session + failure modes

- [ ] **T004 — Implement Claude session.py: stream-json parser + failure-mode detection**
  - **Files:** runtime/drivers/claude/session.py
  - **Depends:** T003
  - **Acceptance:**
    - `parse_stream_line(line: str) -> dict | None` parses one JSONL line; returns None on parse error and logs the raw line at DEBUG level (never silently swallows)
    - `is_error_response(parsed: dict) -> bool` checks `parsed.get("is_error")` — does not rely on exit code alone
    - `detect_failure_mode(line: str) -> str | None` returns one of `"task_state_desync"`, `"process_transport_death"`, `"windows_init_timeout"`, or None, based on documented error indicators from claude-code#59962, claude-agent-acp#338, claude-code#50559
    - When a failure mode is detected, emits `failure_mode_detected` event with `failure_mode` and `raw_indicator` fields
    - `validate_session_id(s: str) -> bool` returns True iff `s` is a valid UUID (any version); uses `uuid.UUID(s)` try/except
  - **Complexity:** medium

## Phase C — Cursor CLI driver

- [ ] **T005 — Implement cursor/cli_driver.py: cursor-agent -p CLI tier**
  - **Files:** runtime/drivers/cursor/cli_driver.py, runtime/drivers/cursor/__init__.py
  - **Depends:** none (parallel with Phase A)
  - **Acceptance:**
    - `CursorCLIDriver` implements C1 `HostDriver` protocol
    - `_build_args(mode)` maps z-harness command mode to `--mode ask|plan|agent`; defaults to `ask`
    - Auth: reads `CURSOR_API_KEY` from env; raises `DriverConfigError` if missing
    - Uses `cursor-agent -p` binary (not `cursor`); raises `DriverInitError` if binary not on PATH
    - Passes `--output-format stream-json` (not `text`)
    - `subprocess_spawn` and `subprocess_exit` telemetry events emitted
    - `driver_selected` event emitted with `host="cursor"`, `tier="cli"`
  - **Complexity:** medium

- [ ] **T006 — Implement cursor/session.py: stream-json parser + agent_busy guard**
  - **Files:** runtime/drivers/cursor/session.py
  - **Depends:** T005
  - **Acceptance:**
    - `parse_stream_line(line: str) -> dict | None` — same contract as Claude session.py (DEBUG log on parse error, never swallow)
    - `is_error_response(parsed: dict) -> bool` — Cursor-specific is_error check
    - `AgentBusyError` is a subclass of `DriverBusyError` (C1 type); NOT a fatal error
    - `handle_agent_busy(agent_id, attempt, max_attempts=3)` implements exponential backoff + emits `driver_busy_retry` event; raises `AgentBusyError` after max_attempts
    - HTTP 409 from `cursor-agent -p` output is detected via `parse_stream_line` result, not raw exit code
  - **Complexity:** medium

## Phase D — Cursor MCP config writer + SDK stub

- [ ] **T007 — Implement cursor/mcp_config.py: mcp.json writer with MCPoison guard**
  - **Files:** runtime/drivers/cursor/mcp_config.py
  - **Depends:** none
  - **Acceptance:**
    - `MCP_KEY_NAME = "z-harness"` is a module-level constant
    - `register_mcp_server(server_def, project_root=None)` writes to `~/.cursor/mcp.json` (global) and optionally `.cursor/mcp.json` (project); merges, does not clobber existing entries
    - `_assert_key_name(key)` raises `MCPKeyNameError` if `key != MCP_KEY_NAME`; called before any write
    - Config file is read, merged (dict update), then atomically written (write to `.tmp`, then rename)
    - `mcp_config_write` event emitted with `config_path`, `key_name`, `server_count` (total entries after merge)
    - If config file does not exist, creates it with `{"mcpServers": {MCP_KEY_NAME: server_def}}`
    - Does not validate server_def schema beyond asserting it is a dict (schema is C1's responsibility)
  - **Complexity:** low

- [ ] **T008 — Implement cursor/sdk_driver.py: @cursor/sdk stub**
  - **Files:** runtime/drivers/cursor/sdk_driver.py
  - **Depends:** none
  - **Acceptance:**
    - `CursorSDKDriver` implements C1 `HostDriver` protocol (all abstract methods present)
    - Every method raises `NotImplementedError` with message: "CursorSDKDriver is not implemented in v1. See v2 milestone: @cursor/sdk (public beta 2026-04-29). Use CursorCLIDriver for v1."
    - `__init__` does NOT import `@cursor/sdk` (no import at module level that would fail if the package is absent)
    - A docstring at class level references PLAN.md C4-D3 and the v2 milestone
  - **Complexity:** low

## Phase E — Driver selection wiring

- [ ] **T009 — Implement driver selection: env-detect + --driver override**
  - **Files:** runtime/drivers/claude/env_hygiene.py (detect_self_hosted already there), runtime/drivers/__init__.py (or dispatcher shim per C1 interface)
  - **Depends:** T001, T002, T003, T005
  - **Acceptance:**
    - `select_driver(host: str, driver_override: str | None = None) -> HostDriver` factory function
    - For `host="claude"`: if `driver_override="claude-self"` or `detect_self_hosted()` is True → return `SelfHostDriver()`; else → return `SubprocessClaudeDriver()`
    - For `host="cursor"`: returns `CursorCLIDriver()` in v1 (SDK tier raises `NotImplementedError` if explicitly requested via `driver_override="cursor-sdk"`)
    - Emits `driver_selected` event with `driver_class`, `host`, `detection_method`
    - If `host` is unknown, raises `DriverNotFoundError` (C1 type)
  - **Complexity:** low

## Phase F — Smoke tests

- [ ] **T010 — Unit tests for env_hygiene.py and Claude session.py**
  - **Files:** tests/drivers/claude/test_env_hygiene.py, tests/drivers/claude/test_session.py
  - **Depends:** T001, T004
  - **Acceptance:**
    - `test_apply_env_hygiene_clears_claudecode`: env with CLAUDECODE=1 → output has CLAUDECODE=""
    - `test_apply_env_hygiene_does_not_mutate_input`: original dict unchanged after call
    - `test_detect_self_hosted_true`: with CLAUDECODE=1 in env → True
    - `test_detect_self_hosted_false`: with CLAUDECODE unset → False
    - `test_parse_stream_line_valid_json`: returns dict
    - `test_parse_stream_line_invalid_json`: returns None, logs at DEBUG (monkeypatched logger checked)
    - `test_detect_failure_mode_task_state_desync`: line matching claude-code#59962 indicator → "task_state_desync"
    - `test_validate_session_id_valid_uuid`: returns True
    - `test_validate_session_id_invalid`: returns False (no exception)
  - **Complexity:** low

- [ ] **T011 — Unit tests for Cursor mcp_config.py**
  - **Files:** tests/drivers/cursor/test_mcp_config.py
  - **Depends:** T007
  - **Acceptance:**
    - `test_register_creates_new_file`: non-existent config path → file created with correct structure
    - `test_register_merges_existing`: existing file with other keys → z-harness key added, existing keys preserved
    - `test_register_wrong_key_raises`: passing key != "z-harness" → `MCPKeyNameError`
    - `test_atomic_write`: uses tmp file + rename (mocked os.rename call verified)
    - `test_mcp_config_write_event_emitted`: event emitted with correct fields
    - All tests use tmp_path fixture (no writes to real ~/.cursor/)
  - **Complexity:** low

- [ ] **T012 — Integration smoke test: SubprocessClaudeDriver env hygiene**
  - **Files:** tests/drivers/claude/test_subprocess_driver.py
  - **Depends:** T003, T004
  - **Acceptance:**
    - Test uses `unittest.mock.patch("subprocess.Popen")` to intercept spawn
    - Asserts spawned env has `CLAUDECODE=""` regardless of test process env
    - Asserts `--bare` is in args
    - Asserts `--output-format stream-json` and `--verbose` are in args
    - Asserts non-UUID session_id raises `ValueError` before spawn
    - Does NOT require `claude` binary to be on PATH
  - **Complexity:** low
