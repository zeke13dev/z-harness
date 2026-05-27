# TASKS — C3: driver-antigravity

cluster-id: C3
run-id: 20260527T050549Z-harness-distribution-strategy

---

- [ ] **T001 — agy availability pre-flight check**
  - **Files:** runtime/drivers/antigravity/preflight.py
  - **Depends:** none
  - **Acceptance:**
    - `preflight.py` runs `agy --version` (subprocess, timeout 10s) and captures stdout
    - On success: emits `agy_preflight_pass` telemetry event with `agy_version` field; returns the version string
    - On failure (binary not found, non-zero exit, timeout): emits `agy_preflight_fail` with `reason` and `recommendation: "defer_c3"` fields; raises `DriverUnavailableError` with a message stating "agy is not publicly available; consider deferring C3 until distribution is confirmed"
    - `DriverUnavailableError` is a typed exception class defined in `preflight.py`
    - Pre-flight can be run standalone: `python3 -m runtime.drivers.antigravity.preflight` prints availability status to stdout
    - No side effects (no file writes, no config changes) on failure
  - **Complexity:** medium

- [ ] **T002 — stream-json output parser**
  - **Files:** runtime/drivers/antigravity/stream_parser.py
  - **Depends:** none
  - **Acceptance:**
    - `parse_stream(iterable_of_lines)` is a generator that yields normalized dicts for each valid JSONL event line
    - Normalized dict has at minimum: `{"type": str, "raw": dict}` where `type` is extracted from the JSONL event's type field
    - Malformed lines (JSON decode error, missing type field): emits `agy_stream_parse_error` telemetry; yields `{"type": "parse_error", "raw_line": "<truncated to 200 chars>", "error": str}`; does not raise
    - At least 3 fixture-based unit tests in `runtime/drivers/antigravity/tests/test_stream_parser.py` covering: valid multi-event stream, single malformed line in otherwise valid stream, empty stream
    - Parser does not import `driver.py` (no circular dependency)
  - **Complexity:** low

- [ ] **T003 — CLI-tier driver: subprocess dispatch**
  - **Files:** runtime/drivers/antigravity/driver.py
  - **Depends:** T001, T002
  - **Acceptance:**
    - `AntigravityDriver` class with `dispatch(prompt: str) -> Iterator[dict]` method
    - `dispatch` calls `preflight.check()` before launching subprocess; raises `DriverUnavailableError` if pre-flight fails
    - Subprocess invocation: `['agy', '-p', prompt, '--output-format', 'stream-json']` via `subprocess.Popen` with `stdout=PIPE`, `stderr=PIPE`, text mode
    - Stdout lines are fed through `stream_parser.parse_stream()`; each parsed dict is yielded to caller
    - Emits `agy_dispatch_start` before launch (with `prompt_len`) and `agy_dispatch_end` after exit (with `exit_code`, `events_parsed`, `elapsed_ms`)
    - On non-zero exit code: checks parsed events for an error-type event; if found, raises `DriverDispatchError` with the error message; if not found, raises `DriverDispatchError` with raw stderr (truncated to 500 chars)
    - Includes a probe method `probe() -> bool` that dispatches a minimal no-op prompt ("ping") and returns True if at least one non-error event is received; writes `READY` marker on first successful probe (emits `agy_ready_written`)
    - Nesting detection: if `agy -p` stderr contains "nested session" or equivalent text, raises `DriverConstraintError` with message explaining the non-nesting limitation
    - `DriverDispatchError` and `DriverConstraintError` are typed exceptions defined in `driver.py`
  - **Complexity:** medium

- [ ] **T004 — package init and interface stub**
  - **Files:** runtime/drivers/antigravity/__init__.py
  - **Depends:** T003
  - **Acceptance:**
    - `__init__.py` exports: `AntigravityDriver`, `DriverUnavailableError`, `DriverDispatchError`, `DriverConstraintError`
    - Contains a comment block: `# C1 interface conformance: AntigravityDriver will implement runtime.contract.BaseDriver once C1 (runtime-core) ships its contract. Until then, the public surface is dispatch(prompt: str) -> Iterator[dict].`
    - Package is importable as `from runtime.drivers.antigravity import AntigravityDriver` without error (assuming `runtime/` is on the Python path)
    - `__all__` is explicitly defined
  - **Complexity:** low

- [ ] **T005 — MCP config read/write helpers**
  - **Files:** runtime/drivers/antigravity/mcp_config.py
  - **Depends:** T001
  - **Acceptance:**
    - `read_mcp_config(scope: str = "global") -> dict` reads `~/.gemini/config/mcp_config.json` (global) or `.agents/mcp_config.json` (project); returns parsed dict or empty dict if file missing
    - Emits `agy_mcp_config_read` with `path` and `server_count`
    - `add_stdio_server(name: str, command: str, args: list[str], *, write: bool = False) -> dict` returns the updated config dict; if `write=True`, writes back to the config file and emits `agy_mcp_config_write`
    - `write=False` is the default (read-only safety)
    - Inline comment documents known env-var-expansion bug (May 2026): "Do not use environment variable references in mcp_config.json values; expansion is broken as of agy May 2026. Use literal paths."
    - Does not attempt to validate or expand env vars in existing config entries
    - No support for SSE or Streamable HTTP transport in v1 (stdio only); raises `NotImplementedError` if caller requests other transport types
  - **Complexity:** low

- [ ] **T006 — auth validation helper**
  - **Files:** runtime/drivers/antigravity/auth.py
  - **Depends:** T001
  - **Acceptance:**
    - `check_auth() -> dict` returns `{"cli_auth": bool, "sdk_auth": bool, "warnings": list[str]}`
    - `cli_auth` is True if `~/.gemini/oauth_creds.json` exists (presence check only; no content validation)
    - `sdk_auth` is True if `GEMINI_API_KEY` env var is set and non-empty
    - `warnings` includes at least: "SDK tier is deferred to v2; GEMINI_API_KEY is not required for CLI-tier dispatch" (always), and "~/.gemini/oauth_creds.json not found; run `agy auth login` to authenticate" (if `cli_auth` is False)
    - Does NOT perform OAuth flow, does NOT read token content, does NOT make network calls
    - Module is standalone-runnable: `python3 -m runtime.drivers.antigravity.auth` prints auth status as JSON to stdout
  - **Complexity:** low

- [ ] **T007 — READY marker write + probe integration**
  - **Files:** runtime/drivers/antigravity/driver.py, runtime/drivers/antigravity/READY
  - **Depends:** T003
  - **Acceptance:**
    - `READY` file (plain text) is written to `runtime/drivers/antigravity/READY` by `AntigravityDriver.probe()` on first successful round-trip
    - `READY` file content: `agy_version=<version>\nverified_at=<ISO8601 timestamp>\n`
    - `probe()` only writes `READY` once (idempotent; checks for existing file before writing)
    - Emits `agy_ready_written` telemetry event with `path` field
    - `READY` file is listed in `.gitignore` (or a comment in README explains it should not be committed since it reflects runtime state)
    - If pre-flight fails during probe, `READY` is not written and any existing `READY` is left untouched
  - **Complexity:** low

- [ ] **T008 — driver README**
  - **Files:** runtime/drivers/antigravity/README.md
  - **Depends:** T001, T002, T003, T004, T005, T006, T007
  - **Acceptance:**
    - README covers: prerequisites (agy must be installed, Google account required), pre-flight (`python3 -m runtime.drivers.antigravity.preflight`), auth setup (`agy auth login`), CLI-tier usage (`AntigravityDriver.dispatch(prompt)`), MCP config helpers (`mcp_config.py` read/write, env-var-expansion bug warning), known limitations (12k body limit bypassed by CLI-tier; 100-tool IDE MCP limit; env-var expansion broken; Extension SDK deferred to v2; no session resumability across process restarts), handoff note for C6 (C6 reads `READY` file to confirm driver is verified before switching default dispatch path from `export-agy.py`)
    - README is under 120 lines
    - No marketing language; no emojis
  - **Complexity:** low
