# runtime/drivers/antigravity

CLI-tier driver for the Antigravity (`agy`) binary.

---

## Prerequisites

- `agy` installed and on `PATH` (run `agy --version` to confirm)
- A Google account with CLI auth completed (`agy auth login`)
- Python 3.10+

---

## Pre-flight check

Before any dispatch, run the pre-flight module to confirm `agy` is reachable:

```
python3 -m runtime.drivers.antigravity.preflight
```

Output on success: `agy is available: <version>`
Output on failure: `agy is unavailable: <reason>` — do not proceed until resolved.

The driver calls `preflight.check()` internally on every `dispatch()` call.
If `agy` is not found it raises `DriverUnavailableError` and writes nothing.

---

## Auth setup

The CLI tier uses Google OAuth credentials stored in `~/.gemini/oauth_creds.json`.
This file is created by running:

```
agy auth login
```

Follow the browser prompt. The credential file is shared with the Gemini CLI;
no separate token is needed for `agy`.

To check auth status without network calls:

```python
from runtime.drivers.antigravity.auth import check_auth
print(check_auth())  # {"cli_auth": true, "sdk_auth": false, "warnings": [...]}
```

`sdk_auth` reflects whether `GEMINI_API_KEY` is set. The SDK tier is deferred
to v2; `GEMINI_API_KEY` is not required for CLI-tier dispatch.

---

## CLI-tier dispatch

```python
from runtime.drivers.antigravity.driver import AntigravityDriver

driver = AntigravityDriver()
for event in driver.dispatch("summarise the open issues"):
    print(event)
```

`dispatch(prompt)` calls `agy -p <prompt> --output-format stream-json` and
yields parsed event dicts. Raises on non-zero exit:

- `DriverUnavailableError` — `agy` not on PATH or pre-flight failed
- `DriverConstraintError` — `agy` refused due to nested session
- `DriverDispatchError` — `agy` exited non-zero

### probe() and the READY marker

`driver.probe()` dispatches a minimal "ping" prompt and returns `True` if at
least one non-error event is received. On first success it writes
`runtime/drivers/antigravity/READY` (`agy_version=<v>\nverified_at=<ISO8601>`).

---

## MCP config helpers

`mcp_config.py` provides read/write helpers for `~/.gemini/config/mcp_config.json`
(global) or `.agents/mcp_config.json` (project scope).

```python
from runtime.drivers.antigravity.mcp_config import read_mcp_config, add_stdio_server

config = read_mcp_config(scope="global")   # read only, no disk write
add_stdio_server("my-server", "npx", ["-y", "my-mcp-server"], write=True)
```

Only `stdio` transport is supported in v1; other transports raise `NotImplementedError`.

**Known bug (May 2026):** `$VAR` references in `mcp_config.json` values are not
expanded by `agy`. Use literal absolute paths.

---

## Known limitations

| Limitation | Detail |
|---|---|
| 12k body limit bypassed | CLI tier sends prompts via `agy -p` (stdin path); the 12k-char workflow-file limit does not apply. |
| 100-tool IDE MCP limit | Antigravity IDE enforces a hard 100-tool cap across all registered MCP servers. Plan server registrations accordingly. |
| Env-var expansion broken | `$VAR` references in `mcp_config.json` are not expanded. Use literal paths. |
| Extension SDK deferred | `sdk.cascade`, `sdk.monitor`, `sdk.commands`, `sdk.ls`, `sdk.state` are not implemented. Deferred to v2 pending first-party API documentation. |
| No session resumability | The driver is stateless between calls. There is no mechanism to resume a prior `agy` session across process restarts. |

---

## Handoff note for C6

C6 (shipping) reads `runtime/drivers/antigravity/READY` to confirm the driver
is verified before switching the default dispatch path from
`scripts/export-agy.py`. The file exists only after `driver.probe()` completes
a successful round-trip. If absent, cutover must not proceed.
