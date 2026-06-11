# SPEC.md — z-harness MCP Server

## Planning Inputs

| Artifact | Path | generated_at |
|----------|------|--------------|
| BRAINSTORM.md | plans/mcp-server/BRAINSTORM.md | 2026-06-11T16:48:26Z |

---

## Overview

`z-harness serve` — a Python MCP server that exposes every `/z-*` command as an MCP tool and enables cross-LLM subagent dispatch. A thin adapter over the existing z-harness dispatch engine. Delegates ALL command execution to `runtime/dispatch/dispatcher.py` which dispatches through `HostDriver.dispatch()` → subprocess LLM CLI. Stateless; plan artifacts on disk are the source of truth. Transport: stdio. Auth: existing z-harness provider configs.

## Files

### NEW: `z_harness_cli/mcp/__init__.py`
Empty package init. Exports nothing at package level.

### NEW: `z_harness_cli/mcp/server.py` (~800 lines)
The core MCP server. FastMCP-based. stdio transport.

**Exports:**
- `serve()` — entry point, creates FastMCP server, registers all tools, runs
- Tool functions (registered via `@mcp.tool()`):
  - Command tools: `z_plan`, `z_implement_all`, `z_implement_next`, `z_review_all`, `z_audit`, `z_audit_plan_style`, `z_debug`, `z_do`, `z_brainstorm`, `z_research`, `z_map`, `z_plan_light`, `z_plan_split`, `z_test`, `z_amend`, `z_init_docs`, `z_maintain_docs`, `z_uplift`, `z_improve`, `z_where`, `z_stats`, `z_suggest_memory`, `z_axiom_scan`, `z_axiom_list`, `z_axiom_approve`, `z_axiom_reject`, `z_axiom_edit`, `z_personas`, `z_update`, `z_reality`, `z_overnight`, `z_evaluate`, `z_context_budget`, `z_doc_rationale`, `z_test_invariant`
  - Utility tools: `z_subagent_dispatch`, `z_export`, `z_detect`
  - Status tools: `z_status`
- `_dispatch_command(command_id, args, progress_callback) -> ToolResult` — core dispatch logic
- `ToolResult` dataclass — `{ ok, status, content, artifacts, meta }`

**Tool signature pattern (every command tool):**
```python
@mcp.tool()
async def z_plan(
    prompt: str,                    # natural language task description
    slug: str | None = None,        # optional plan slug
    ctx: Context | None = None,     # MCP context for progress reporting
) -> ToolResult:
    """Run the /z-plan planning pipeline."""
```

**Tool signature pattern (z_subagent_dispatch):**
```python
@mcp.tool()
async def z_subagent_dispatch(
    agent: str,          # agent name from agents/*.md
    prompt: str,         # task for the subagent
    model: str | None = None,  # optional model override
    ctx: Context | None = None,
) -> ToolResult:
    """Dispatch a subagent using the appropriate LLM CLI."""
```

**ToolResult schema:**
```python
@dataclass
class ToolResult:
    ok: bool                       # did the command complete without error?
    status: str                    # "complete" | "error" | "blocked" | "needs_input"
    content: str                   # narrative output (markdown or NL)
    artifacts: dict[str, str]      # artifact_name -> content (e.g. {"plan": "<md>", "spec": "<md>"})
    meta: dict[str, object]        # structured metadata (e.g. {"tasks_count": 5, "phase": "complete"})
```

**Behavior:**
- Each command tool:
  1. Parses `prompt` into structured args for the command
  2. Resolves `slug` if applicable (derive or use provided)
  3. Sets up `progress_callback` for MCP progress notifications
  4. Calls `_dispatch_command()` which wraps `runtime/dispatch/dispatcher.py` to spawn the appropriate host driver, stream events via progress, wait for the result, and read artifacts from disk
  5. Returns `ToolResult` with artifacts populated from written disk files

- `z_subagent_dispatch`:
  1. Loads agent definition from `agents/<agent>.md` (YAML frontmatter → model pin, prompt, tools)
  2. Calls `runtime/dispatch/dispatcher.dispatch(command_id, args, env)` which handles driver selection, subprocess lifecycle, event streaming, and result collection
  3. Wraps the dispatcher with `MCPDispatcher` helper that bridges DispatchResult → ToolResult and connects progress callbacks

- `z_export`:
  1. Calls `z_harness_cli/commands/export.py::run()` with structured args
  2. Returns file list and fidelity

- `z_detect`:
  1. Calls `z_harness_cli/adapters/registry.py::detect_all()`
  2. Returns installed hosts with versions

- `z_status`:
  1. Reads `$Z_HARNESS_PLAN_DIR` for active plans
  2. Returns plan status (slug, phase, task progress, age)

**INVARIANT:** The MCP server never implements z-harness logic — only translates MCP calls to internal dispatch.

**INVARIANT:** `ToolResult.content` holds EXACTLY the command's natural language output. No reformatting.

**INVARIANT:** Artifacts in `ToolResult.artifacts` mirror the on-disk state at `$Z_HARNESS_PLAN_DIR/<slug>/`.

**INVARIANT:** The server is stateless between calls. All state lives on disk under `$Z_HARNESS_PLAN_DIR/`.

**INVARIANT:** The MCP server NEVER imports or calls command implementation code directly. All command execution goes through `runtime/dispatch/dispatcher.py` → `HostDriver.dispatch()`.

### NEW: `z_harness_cli/commands/serve.py` (~50 lines)
CLI entry point for `z-harness serve`.

**Signature:**
```python
def run(ctx, *, transport: str = "stdio"):
    """Start the z-harness MCP server."""
    from z_harness_cli.mcp.server import serve
    serve(transport=transport)
```

**INVARIANT:** Registered in `z_harness_cli/commands/__init__.py` and wired as `z-harness serve` subcommand.

### MODIFIED: `z_harness_cli/commands/launch.py`
Add `serve` subcommand that imports and calls `serve.py::run()`.

**Behavior:** Same as other launch subcommands — `z-harness serve [--transport stdio]`.

### MODIFIED: `pyproject.toml`
Add `mcp` dependency: `mcp>=1.20` (FastMCP). Add `serve` entry point.

### NEW: `tests/mcp/test_server.py` (~300 lines)
Unit tests for the MCP server:
- `test_tool_result_serialization` — ToolResult → dict roundtrip
- `test_command_dispatch_mock` — mock driver, verify dispatch parameters
- `test_subagent_resolve` — agent definition parsing from markdown
- `test_error_handling` — missing command, timeout, subprocess failure
- `test_artifact_reading` — reads artifacts from disk correctly

### NEW: `tests/mcp/test_integration.py` (~150 lines)
Integration tests (require z-harness installed):
- `test_z_where_returns_plan_list` — roundtrip command execution
- `test_z_subagent_dispatch_explore` — dispatch explore agent via codex

## Auth Flow

1. Server calls `scripts/config.py export-env` at startup → caches Z_HARNESS_* env vars
2. Per-tool dispatch: calls `scripts/resolve-provider.py <role>` to get provider descriptor (including `auth_env` keys)
3. Resolves API keys from environment variables listed in provider descriptor
4. Passes resolved env to `dispatcher.dispatch()`
5. No auth data passed in MCP tool parameters — all from z-harness config

**INVARIANT:** No API keys in MCP tool parameters. Auth is server-side only.

## Progress Reporting

1. Long-running commands (z_plan, z_implement_all, z_debug, z_research, z_brainstorm):
   - Report phase transitions: `phase: premise_check`, `phase: explore`, `phase: consult`, `phase: writing`
   - Report at phase boundaries using `ctx.report_progress(progress, total, message)`
2. Short commands (z_where, z_stats, z_axiom_list): return immediately, no progress.
3. Subagent dispatch: report `agent_start`, `agent_progress`, `agent_complete`.

**INVARIANT:** Progress tokens are mandatory for commands that take >5s. Fast commands may skip.

## Error Handling

| Error | ToolResult |
|-------|------------|
| Command not found | `{ ok: false, status: "error", content: "Unknown command: ..." }` |
| Subprocess timeout | `{ ok: false, status: "error", content: "Timed out after Ns" }` |
| Binary not installed | `{ ok: false, status: "error", content: "claude/codex/pi not found on PATH" }` |
| Auth failure | `{ ok: false, status: "error", content: "No API key for provider X" }` |
| Plan collision | `{ ok: false, status: "blocked", content: "Plan slug 'X' already active" }` |
| Needs user input | `{ ok: true, status: "needs_input", content: "<question text>", meta: { question_id: "..." } }` |

**INVARIANT:** All errors return structured ToolResult — never throw unhandled exceptions over MCP.

## HostAdapter Coexistence

- `z_export` MCP tool calls `z_harness_cli/commands/export.py::run()` 
- `z_detect` MCP tool calls `z_harness_cli/adapters/registry.py::detect_all()`
- Existing `z-harness export --host X` path remains unchanged
- HostAdapters remain the canonical mechanism for editor configuration

---

## Amendments

- **2026-06-11:** Rewrote dispatch model — all command execution now uses `runtime/dispatch/dispatcher.py` (subprocess host drivers), not in-process Python imports. Added INVARIANT to enforce this. (AUDIT Finding 1)
- **2026-06-11:** Fixed auth flow — `config.py export-env` for env setup, `resolve-provider.py <role>` for per-dispatch provider resolution. (AUDIT Finding 2)
- **2026-06-11:** Added 6 missing commands to tool catalog: `z_reality`, `z_overnight`, `z_evaluate`, `z_context_budget`, `z_doc_rationale`, `z_test_invariant`. (AUDIT Finding 3)
