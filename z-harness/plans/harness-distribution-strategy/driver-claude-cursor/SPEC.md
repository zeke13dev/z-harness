---
cluster_id: C4
cluster_name: driver-claude-cursor
run_id: 20260527T050549Z-harness-distribution-strategy
root_slug: harness-distribution-strategy
generated_at: 2026-05-27
---

# SPEC — C4: driver-claude-cursor

## 1. Overview

This cluster implements two host drivers for the z-harness host-neutral runtime (defined in C1
runtime-core): the Claude-self driver and the Cursor driver. The Claude-self driver is
structurally distinct from all other drivers because z-harness typically runs AS a Claude Code
plugin — making "the host" the parent process, not a subprocess. It therefore provides two
concrete classes: `SelfHostDriver` (in-process delegation to Claude Code tool primitives when
running inside Claude Code) and `SubprocessClaudeDriver` (spawns `claude -p --bare` as a child
process, with CLAUDECODE env-hygiene, for use when another host wants to delegate to Claude as a
backend). The Cursor driver implements the `cursor-agent -p` CLI tier in v1, with the
`@cursor/sdk` TypeScript SDK tier stubbed for v2.

## 2. Surface — files this cluster owns

```
runtime/drivers/claude/__init__.py
runtime/drivers/claude/self_host_driver.py        # SelfHostDriver — in-process tool delegation
runtime/drivers/claude/subprocess_driver.py       # SubprocessClaudeDriver — claude -p --bare
runtime/drivers/claude/env_hygiene.py             # CLAUDECODE="" env helper + failure-mode guards
runtime/drivers/claude/session.py                 # Session state, stream-json parser, exit-code handling
runtime/drivers/cursor/__init__.py
runtime/drivers/cursor/cli_driver.py              # cursor-agent -p CLI tier (v1)
runtime/drivers/cursor/sdk_driver.py              # @cursor/sdk stub (NotImplementedError, v2 TODO)
runtime/drivers/cursor/mcp_config.py              # ~/.cursor/mcp.json + .cursor/mcp.json writer
runtime/drivers/cursor/session.py                 # stream-json parser, agent_busy guard
```

## 3. Non-goals

- Runtime contract / HostDriver base class / dispatcher: owned by C1 runtime-core.
- Codex driver (`runtime/drivers/codex/`): owned by C2.
- Antigravity driver (`runtime/drivers/antigravity/`): owned by C3.
- Conformance test suite: owned by C5.
- Install scripts, packaging, symlink injection: owned by C6.
- Cursor REST API Background Agents (`/v1/agents/*`): v2 non-goal; not stubbed, only documented here.
- MCP server implementation: if z-harness ships an MCP server it is a separate module; this
  cluster only handles MCP *client-side* config writing (mcp_config.py registers z-harness's
  MCP server in Cursor's config files). The MCP server itself is out of scope.
- Windows support for SubprocessClaudeDriver: `claude-code#50559` Windows subprocess init timeout
  is a known failure mode; mitigation is documented but not implemented in v1.
- OAuth credential sharing between host CLIs and z-harness SDK tier: not possible without vendor
  policy change; all SDK tiers require explicit API key provisioning.

## 4. Invariants

1. `SelfHostDriver` MUST only be instantiated when `CLAUDECODE` env var is non-empty (or
   `--driver=claude-self` is forced). It MUST NOT spawn a subprocess.
2. `SubprocessClaudeDriver` MUST always pass `--bare` to `claude -p` and MUST override
   `CLAUDECODE=""` in the child process env. It MUST NOT inherit the parent's `CLAUDECODE` value.
3. All subprocess drivers MUST parse `is_error` from the stream-json output for error detection.
   Exit code 1 alone is insufficient (RESEARCH.md confirmed exit codes are only 0/1).
4. Session IDs passed to `claude -p` (if using `--resume`) MUST be valid UUIDs. Non-UUID session
   IDs silently fail.
5. Cursor CLI tier MUST use `cursor-agent -p` (not `cursor`). Auth MUST come from `CURSOR_API_KEY`
   env var.
6. Cursor `agent_busy` (HTTP 409) MUST be surfaced as a retryable `DriverBusyError`, not a fatal
   error. Concurrency is modeled as N agents, not N runs per agent.
7. MCP config key MUST be the literal string `"z-harness"`. `mcp_config.py` MUST assert this at
   registration time and refuse to write a different key name (CVE-2025-54136 mitigation).
8. The `@cursor/sdk` SDK driver stub MUST raise `NotImplementedError` with a message pointing to
   the v2 milestone; it MUST NOT silently degrade or partially execute.

## 5. Telemetry / events

These events are emitted by driver code and consumed by the z-harness runtime event log
(`events.jsonl`):

| Event | Emitter | Key fields |
|---|---|---|
| `driver_selected` | driver init | `driver_class`, `host`, `detection_method` (env/explicit) |
| `subprocess_spawn` | SubprocessClaudeDriver, cursor/cli_driver | `command`, `args_redacted`, `pid` |
| `subprocess_exit` | same | `exit_code`, `is_error`, `wall_ms` |
| `driver_busy_retry` | cursor/session | `attempt`, `agent_id`, `wait_ms` |
| `mcp_config_write` | mcp_config.py | `config_path`, `key_name`, `server_count` |
| `env_hygiene_applied` | env_hygiene.py | `cleared_vars` (list of names, NOT values) |
| `failure_mode_detected` | session.py | `failure_mode` (one of: task_state_desync, process_transport_death, windows_init_timeout), `raw_indicator` |

No event payload MUST include secret values (API keys, auth tokens, env var values).
