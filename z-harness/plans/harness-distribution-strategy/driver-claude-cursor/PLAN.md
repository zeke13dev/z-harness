---
cluster_id: C4
cluster_name: driver-claude-cursor
run_id: 20260527T050549Z-harness-distribution-strategy
---

# PLAN — C4: driver-claude-cursor

## Goal

This cluster implements the two most structurally unusual host drivers in the z-harness runtime:
the Claude-self driver (which inverts the normal host/subprocess relationship because z-harness
runs INSIDE Claude Code as a plugin) and the Cursor driver (which has a three-tier programmatic
surface: CLI headless mode, TypeScript SDK, and a REST API). The goal is to produce concrete,
tested driver implementations under `runtime/drivers/claude/` and `runtime/drivers/cursor/` that
conform to C1's HostDriver interface, handle documented failure modes defensively, and give C5's
conformance harness a working surface to test against.

## Decisions

| ID | Question | Chosen | Rationale |
|---|---|---|---|
| C4-D1 | Claude-self: in-process vs subprocess? | Dual-mode: SelfHostDriver (in-process) + SubprocessClaudeDriver (spawn) | Both cases are real and not mutually exclusive; separating them keeps each class simple |
| C4-D2 | Claude-self: auto-detect vs explicit mode? | Env-detect (CLAUDECODE) with --driver override | Minimal friction for common case; escape hatch for edge cases |
| C4-D3 | Cursor: CLI+SDK in v1 or CLI-only? | CLI-only in v1; SDK stubbed (NotImplementedError) | @cursor/sdk is public beta; adding it as a dependency escalates per rubric rule (b); CLI tier is sufficient for v1 conformance |
| C4-D4 | MCPoison mitigation: how to name MCP key? | Namespaced key "z-harness" + runtime assertion | Trust anchor is key name; stable distinctive name + assertion is the only mitigation without vendor patch |

## Non-goals (v1)

- Cursor REST API Background Agents tier (v2)
- @cursor/sdk SDK tier beyond the stub (v2)
- Windows subprocess support for SubprocessClaudeDriver
- MCP server implementation (only client-side config writing)
- OAuth credential sharing between host CLIs and z-harness SDK tiers

## Approved shortcuts

None. Both drivers have documented failure modes that must be handled; no "stub and revisit"
shortcuts are appropriate for the in-scope tasks.

## Phases

### Phase A — Claude driver foundation

Implement `env_hygiene.py` (CLAUDECODE env clearing, the `--bare` flag helper, failure-mode
constant definitions). Implement `SelfHostDriver` skeleton conforming to C1 HostDriver protocol.
Implement `SubprocessClaudeDriver` skeleton with proper env override. These two tasks unblock
everything else.

### Phase B — Claude driver session + failure modes

Implement `session.py`: stream-json line parser, `is_error` detection, UUID session-ID
validation, failure-mode detection heuristics (task-state desync indicator from claude-code#59962,
ProcessTransport death indicator from claude-agent-acp#338, Windows init timeout from
claude-code#50559).

### Phase C — Cursor CLI driver

Implement `runtime/drivers/cursor/cli_driver.py`: `cursor-agent -p` invocation, `--output-format
stream-json`, CURSOR_API_KEY auth, `--mode ask|plan|agent` mapping, Cursor-specific
`session.py` with `agent_busy` (HTTP 409) retry logic.

### Phase D — Cursor MCP config writer + SDK stub

Implement `mcp_config.py`: reads/writes `~/.cursor/mcp.json` and `.cursor/mcp.json`, enforces
key name `"z-harness"` with runtime assertion, handles merge (does not clobber existing entries).
Implement `sdk_driver.py` stub: raises `NotImplementedError` with v2 milestone reference.

### Phase E — Driver selection wiring

Implement the driver-selection entry point (may be in C1's dispatcher or a thin shim here):
env-detect logic for `CLAUDECODE`, `--driver` flag override, `driver_selected` event emission.

## Risks

1. **CLAUDECODE env var name.** The research cites `CLAUDECODE=1` (from the issue) and
   `CLAUDECODE=""` (as the clearing workaround). The exact var name may change; the env_hygiene
   module should read from a constant, not a hardcoded string literal scattered across the codebase.
2. **stream-json format stability.** `--output-format stream-json` requires `--verbose` to surface
   intermediate tool events. If Anthropic or Cursor changes the schema, parsers break silently.
   Parsers should log raw lines on parse error rather than silently swallowing them.
3. **@cursor/sdk beta churn.** The SDK is public beta (2026-04-29). The stub must be isolated so
   v2 implementation can be dropped in without touching the CLI driver.
4. **SelfHostDriver tool primitive binding.** In-process delegation requires access to the host's
   tool call surface (Read, Edit, Bash, Agent). How these are exposed to the driver layer depends
   on C1's HostDriver interface. If C1 doesn't expose a tool-call injection point, SelfHostDriver
   may need to be partially rearchitected.
5. **MCPoison (CVE-2025-54136) exploit shape not fully verified.** The runtime assertion on key
   name is a best-effort mitigation. If the CVE's actual attack surface is broader (e.g., affects
   server URL, not just key name), the mitigation may be insufficient.

## DRY / KISS / SOLID applied

- **Single Responsibility:** SelfHostDriver and SubprocessClaudeDriver are separate classes, not
  a flag-gated monolith. Cursor CLI and SDK drivers are also separate.
- **Open/Closed:** env_hygiene.py is the single extension point for env manipulation; no driver
  duplicates the CLAUDECODE-clearing logic.
- **DRY:** stream-json line parsing is in each driver's `session.py` (one per host, because format
  details differ), not shared across all drivers (avoiding premature abstraction given format
  differences between Claude and Cursor stream-json).
- **KISS:** v1 ships CLI tier only for Cursor. The SDK stub is a single `raise NotImplementedError`
  — no partial implementation that could be mistaken for working code.
