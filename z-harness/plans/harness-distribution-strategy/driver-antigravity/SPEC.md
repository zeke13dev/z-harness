# SPEC — C3: driver-antigravity

cluster-id: C3
cluster-name: driver-antigravity
run-id: 20260527T050549Z-harness-distribution-strategy
root-slug: harness-distribution-strategy

---

## Overview

This cluster implements the concrete Antigravity (agy) driver for the z-harness host-neutral runtime. It owns `runtime/drivers/antigravity/` and is responsible for: (1) a pre-flight availability check that gates all subsequent tasks on whether `agy` is actually publicly distributed, (2) a CLI-tier driver that invokes `agy -p --output-format stream-json` as a subprocess and parses its JSONL output, (3) MCP config helpers for `~/.gemini/config/mcp_config.json`, (4) auth documentation (Google OAuth shared with `~/.gemini/`; no SDK-tier OAuth), and (5) a readiness signal for C6 (shipping) to consume when cutover from `export-agy.py` is appropriate. The Extension SDK tier (`sdk.cascade`, `sdk.monitor`, etc.) is explicitly deferred to v2 pending first-party API documentation.

---

## Surface

Files this cluster owns (all under `runtime/drivers/antigravity/` unless noted):

- `runtime/drivers/antigravity/__init__.py` — package init, exports `AntigravityDriver` class
- `runtime/drivers/antigravity/preflight.py` — agy availability pre-flight check
- `runtime/drivers/antigravity/driver.py` — CLI-tier driver: subprocess.Popen, stream-json parsing, prompt dispatch
- `runtime/drivers/antigravity/stream_parser.py` — JSONL stream-json output parser
- `runtime/drivers/antigravity/mcp_config.py` — read/write helpers for `~/.gemini/config/mcp_config.json`
- `runtime/drivers/antigravity/auth.py` — auth documentation + validation (Google OAuth check, GEMINI_API_KEY note)
- `runtime/drivers/antigravity/READY` — written by driver when CLI-tier is verified working; consumed by C6
- `runtime/drivers/antigravity/README.md` — driver-level documentation

These files are created new. No files outside `runtime/drivers/antigravity/` are modified by C3.

---

## Non-goals

- Does NOT modify `scripts/export-agy.py`. That file remains as the active dispatch path until C6 performs cutover.
- Does NOT implement the Antigravity Extension SDK tier (sdk.cascade / sdk.monitor / sdk.commands / sdk.ls / sdk.state). Deferred to v2.
- Does NOT define the runtime contract (command schema, provider registry, dispatcher interface). That is C1's responsibility. C3 implements the driver interface that C1 will publish.
- Does NOT implement MCP server logic. MCP config helpers are read/write utilities only.
- Does NOT touch Codex, Cursor, or Claude Code drivers (C2, C4).
- Does NOT write to C6 shipping files. C3 only writes the `READY` marker that C6 can detect.
- Does NOT perform the actual harness cutover from export-agy.py to the new driver.
- Does NOT implement the Antigravity Managed Agents REST API (`POST /v1beta/interactions`). That is a separate surface from the CLI tier and deferred.

Handoff boundaries:
- **C1 (runtime-core)**: C3 imports the `Driver` base class / interface from C1. C3 does not define it.
- **C5 (conformance-harness)**: C5 will run conformance tests against C3's driver. C3 must expose the interface C5 expects (defined by C1's contract).
- **C6 (shipping)**: C6 reads C3's `READY` file to determine when to switch the default dispatch path. C6 owns the cutover logic itself.

---

## Invariants

1. **Pre-flight is mandatory and synchronous.** No dispatch attempt is made before `preflight.py` runs and confirms `agy` is reachable via `agy --version` or equivalent. If pre-flight fails, the driver raises a typed `DriverUnavailableError` that the C1 dispatcher can handle.
2. **No side effects on unavailability.** If agy is unavailable, the driver writes nothing and modifies no config files.
3. **stream-json only.** The driver always passes `--output-format stream-json` to `agy -p`. Text and JSON (non-streaming) output formats are not supported by this driver.
4. **No workflow-file dispatch.** The CLI-tier driver sends prompts via `agy -p` (or `--prompt`), not via `agy chat --mode <workflow-id>`. The 12k-char limit is bypassed by keeping prompts in stdin rather than workflow files. Workflow-file dispatch remains `export-agy.py`'s domain until C6 cutover.
5. **No modification of `~/.gemini/config/mcp_config.json` without explicit caller opt-in.** `mcp_config.py` reads by default; writes require a flag.
6. **Extension SDK tier is absent.** No imports of `@google/antigravity` SDK or `sdk.*` surfaces. If the SDK becomes available, it lands in v2.
7. **READY marker is written only after a successful end-to-end dispatch round-trip.** Not after mere pre-flight success.

---

## Telemetry / events

The driver emits the following events via the harness telemetry infrastructure (`scripts/log-event.sh`):

| Event | When | Key fields |
|-------|------|------------|
| `agy_preflight_start` | Before availability check | `driver: "antigravity"` |
| `agy_preflight_pass` | agy confirmed available | `agy_version: "<version string>"` |
| `agy_preflight_fail` | agy not found or 404 | `reason: "<error>"`, `recommendation: "defer_c3"` |
| `agy_dispatch_start` | Before `agy -p` subprocess launch | `command_id: "<id>"`, `prompt_len: <int>` |
| `agy_dispatch_end` | After subprocess exits | `exit_code: <int>`, `events_parsed: <int>`, `elapsed_ms: <int>` |
| `agy_stream_parse_error` | Malformed JSONL line received | `line: "<truncated>"`, `error: "<msg>"` |
| `agy_mcp_config_read` | mcp_config.json read | `path: "<abs path>"`, `server_count: <int>` |
| `agy_mcp_config_write` | mcp_config.json written | `path: "<abs path>"`, `servers_added: <int>` |
| `agy_ready_written` | READY marker written | `path: "<abs path>"` |
