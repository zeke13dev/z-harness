# PLAN.md — z-harness MCP Server

## Goals

1. **`z-harness serve`** — a stdio MCP server exposing all `/z-*` commands as MCP tools
2. **Cross-LLM subagent dispatch** — `z_subagent_dispatch` tool that spawns subagents through pi/codex/claude CLIs
3. **Hermes bridge** — Hermes connects to this server and gets the full z-harness toolbox
4. **Zero new auth** — inherits existing z-harness provider configs
5. **HostAdapter coexistence** — supplements, doesn't replace

## Non-Goals

- SSE transport (future)
- Real-time streaming of subagent output (v1 streams progress, not token-by-token output)
- MCP server embedding in editors (sidecar only)
- Replacing the existing HostAdapter framework
- pi-mcp-server.py deprecation (coexists until migration)
- Skill-only commands (no `commands/*.md` file) — may require direct SKILL.md loading

## Decisions

| # | Decision | Call | Rationale |
|---|----------|------|-----------|
| D1 | Whole-command vs phase tools | **Whole-command tools** | Each `/z-*` is one MCP tool. Matches user mental model. Progress notifications handle the async gap. |
| D2 | Async handling | **Streaming progress** | MCP-native pattern. FastMCP supports `report_progress()`. Short commands return immediately. |
| D3 | Subagent dispatch | **Synchronous with progress** | `z_subagent_dispatch(agent, prompt)` blocks until done, streams progress. Simpler for callers. |
| D4 | Auth | **z-harness configs only** | No new auth system. Reads existing `providers.json` + `resolve-provider.py`. Editor keys not passed through. |
| D5 | IR | **Hybrid envelope** | `ToolResult { ok, status, content, artifacts, meta }`. Structured metadata + string content. |
| D6 | Transport | **stdio only (v1)** | Universal MCP transport. SSE deferred. |
| D7 | HostAdapter | **Supplement** | HostAdapter for export/inject; MCP server for runtime dispatch. Shared engine. |
| D8 | Code location | **`z_harness_cli/mcp/`** | New package alongside adapters/commands/. Proper module. |
| D9 | Naming | **snake_case from slugs** | `/z-plan` → `z_plan`. Mechanical. |
| D10 | Subagent roster | **Single `z_subagent_dispatch` tool** | agent_name parameter selects from `agents/*.md`. Full roster available. |

## Architecture

```
MCP Client (Hermes / Cursor / VS Code / Claude Desktop)
    │
    │  stdio (JSON-RPC)
    ▼
┌──────────────────────────────────┐
│  z_harness_cli/mcp/server.py     │  ← FastMCP server
│                                  │
│  Tools: z_plan, z_debug, ...    │
│         z_subagent_dispatch      │
│         z_export, z_detect       │
│                                  │
│  _dispatch_command()             │  ← core dispatch
│       │                          │
│       ▼                          │
│  runtime/dispatch/               │  ← existing dispatch engine
│  runtime/drivers/                │  ← HostDriver subprocess spawns
│       │                          │
│       ├── pi (deepseek)          │
│       ├── claude (anthropic)     │
│       ├── codex (openai)         │
│       └── cursor                 │
│                                  │
│  State: $Z_HARNESS_PLAN_DIR/     │  ← disk artifacts
│         z_harness_cli/commands/  │  ← command implementations
│         agents/*.md              │  ← agent definitions
│         scripts/config.py        │  ← config & auth resolution
└──────────────────────────────────┘
```

## Flow: MCP tool call lifecycle

```
1. Client calls tools/call { name: "z_plan", arguments: { prompt: "add rate limiter", slug: "rate-limiter" } }

2. server.z_plan() receives prompt + slug
   → ctx.report_progress(0, 3, "Starting premise check")
   → dispatches to z_harness_cli internals (runs premise check, explore, consult, write)
   → ctx.report_progress(1, 3, "Exploration complete")
   → ctx.report_progress(2, 3, "Consulting...")
   → writes SPEC.md, PLAN.md, TASKS.md to $Z_HARNESS_PLAN_DIR/rate-limiter/
   → reads artifacts from disk
   → ctx.report_progress(3, 3, "Complete")

3. Returns ToolResult {
     ok: true,
     status: "complete",
     content: "Plan 'rate-limiter' created with 8 tasks.",
     artifacts: {
       "spec": "<SPEC.md content>",
       "plan": "<PLAN.md content>",
       "tasks": "<TASKS.md content>"
     },
     meta: { tasks_count: 8, slug: "rate-limiter" }
   }
```

## Flow: Subagent dispatch

```
1. Client calls tools/call { name: "z_subagent_dispatch", arguments: { agent: "explore", prompt: "Find where config.py handles export-env" } }

2. server.z_subagent_dispatch("explore", prompt)
   → loads agents/explore.md → model: haiku, tools: [read, bash, grep]
   → selects driver: codex (haiku → gpt-4o-mini via codex)
   → spawns: codex exec - --output-format stream-json
   → streams agent output via progress notifications
   → waits for completion
   → parses result

3. Returns ToolResult {
     ok: true,
     status: "complete",
     content: "Found at scripts/config.py:500 — export-env prints export lines for all non-meta keys.",
     artifacts: {},
     meta: { agent: "explore", model_used: "gpt-4o-mini", wall_ms: 4200 }
   }
```

## DRY / KISS / SOLID

- **DRY:** The MCP server delegates ALL logic to existing modules. No duplicated command implementations, agent definitions, or config resolution. The only new code is the MCP protocol translation layer.
- **KISS:** One new package (`z_harness_cli/mcp/`) with two files: `__init__.py` and `server.py`. Plus a thin CLI entry point (`serve.py`). No new frameworks, no new auth, no new state.
- **SOLID:**
  - **Single Responsibility:** `server.py` translates MCP ↔ z-harness. `serve.py` handles CLI.
  - **Open/Closed:** New commands auto-register as tools (no per-command boilerplate). New agents auto-available via `z_subagent_dispatch`.
  - **Liskov:** `HostDriver` interface unchanged — MCP server is a consumer, not a subclass.
  - **Interface Segregation:** `ToolResult` is the only new type. Thin contract.
  - **Dependency Inversion:** MCP server depends on `HostDriver` ABC, not concrete drivers.

## Phased Implementation

### Phase A: Core server + command tools
1. Create `z_harness_cli/mcp/__init__.py` and `server.py`
2. Implement `ToolResult`, `_dispatch_command()`, and the command tool registry
3. Start with `z_where`, `z_stats`, `z_axiom_list` (read-only, fast commands) → validate end-to-end MCP flow
4. Add `z_plan`, `z_do`, `z_debug`, `z_implement_all` (heavy commands with progress)
5. Add remaining commands
6. Wire `z-harness serve` CLI entry point

### Phase B: Subagent dispatch
7. Implement `z_subagent_dispatch` — agent loading, driver selection, subprocess dispatch
8. Implement `z_export` and `z_detect` — call existing HostAdapter methods

### Phase C: Hermes migration
9. Update Hermes config to connect to `z-harness serve` instead of `pi-mcp-server.py`
10. Migrate Hermes workflows to use `z_plan`, `z_implement_all`, `z_subagent_dispatch` tools

### Phase D: Testing and hardening
11. Unit tests for `ToolResult`, command dispatch, agent resolution
12. Integration tests for roundtrip command execution
13. Error handling hardening: all failure modes return structured `ToolResult`

## Risks

| Risk | Mitigation |
|------|------------|
| HostDriver.dispatch() returns async DispatchHandle — bridging to sync MCP tools is tricky | Wrap in asyncio. Stream events via progress, wait for final result. FastMCP supports async tools natively. |
| z-harness commands call `AskUserQuestion` (blocking) — MCP tools can't block on user input | Detect "needs_input" state, return `{ status: "needs_input" }` with question. Client re-calls with answer. |
| Agent model pins (Haiku, Sonnet, Opus) map to different provider/model combos | Follow existing mapping from export-pi.py: Haiku→flash, Sonnet/Opus→pro. |
| pi-mcp-server.py and new server both bind stdio — conflict | New server supersedes. Hermes migrates. pi-mcp-server.py kept as fallback. |
| FastMCP API churn (1.0→1.27) | Pin `mcp>=1.20`, test with venv's installed version |
| MCP client tool count limits (~34 tools) | Test with Hermes, Cursor, VS Code. Consider progressive grouping if needed |
| Z_HARNESS_CONSULT=off returns "none" for review roles | z_subagent_dispatch detects consult-off and returns status="skipped" |
| FastMCP Context injection with optional ctx param | Verify `ctx: Context \| None = None` works with FastMCP's auto-injection. Add T018 to test this. |

---

## Amendments

- **2026-06-11:** Added 4 risks to Risks table (FastMCP API churn, MCP client tool limits, Z_HARNESS_CONSULT=off bypass, Context injection). (AUDIT Findings 4, 6, 8, 9, 10)
- **2026-06-11:** Added non-goal: skill-only commands may require direct SKILL.md loading. (AUDIT Finding 7)
