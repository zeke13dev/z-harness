# mcp-server

> Last updated: 2026-06-17
> Covers source: z_harness_cli/mcp/server.py, z_harness_cli/commands/serve.py, z_harness_cli/cli.py

## Overview

`z-harness serve` starts an **MCP (Model Context Protocol) server** that exposes every
`/z-*` command as a callable MCP tool over the **stdio transport**. Any MCP-capable editor
or agent host can point its MCP config at `z-harness serve` to invoke z-harness workflows
programmatically without leaving the editor.

The server is built on [FastMCP](https://github.com/jlowin/fastmcp) (`fastmcp>=3.4.2`,
`mcp>=1.20`). Each tool maps one-to-one with a z-harness command. Heavy commands (planning,
implementation, review) are dispatched through `runtime/dispatch/dispatcher.py`; fast
read-only commands (status queries) return immediately via direct in-process handlers.

## Starting the server

```bash
z-harness serve
```

Or equivalently:

```bash
python3 -m z_harness_cli serve
```

The server binds to **stdio** (default and only supported transport). It blocks until the
client disconnects. No port is opened — communication is entirely over stdin/stdout, which
is the standard MCP stdio pattern.

## MCP tool catalog

### Heavy commands (invoke z-harness pipelines)

| Tool name | z-harness command | Description |
|---|---|---|
| `z_plan` | `/z-plan` | Run the rigorous z-harness planning pipeline |
| `z_implement_all` | `/z-implement-all` | Implement ALL pending tasks from TASKS.md with per-task review |
| `z_implement_next` | `/z-implement-next` | Implement the next pending task and review |
| `z_review_all` | `/z-review-all` | Final-gate cross-LLM review of cumulative diff against SPEC.md |
| `z_audit` | `/z-audit` | Read-only audit pipeline with cross-LLM review |
| `z_audit_plan_style` | `/z-audit-plan-style` | Audit plan artifacts for code-quality issues before code is written |
| `z_debug` | `/z-debug` | Investigate a bug with repro/hypothesis/evidence/isolation phases |
| `z_do` | `/z-do` | Plan-less execution for trivial changes with harness discipline |
| `z_brainstorm` | `/z-brainstorm` | 3-vendor parallel pre-plan ideation with anti-bias check |
| `z_research` | `/z-research` | Deep research: map + brainstorm + adversarial synthesis panel |
| `z_map` | `/z-map` | Map terrain with citations and cross-LLM critique |
| `z_plan_light` | `/z-plan-light` | Lightweight planner for 1-5 file fixes with bundled cross-consult |
| `z_plan_split` | `/z-plan-split` | Pre-emptive scope splitter — fan-out into N narrow cluster-planners |
| `z_test` | `/z-test` | Dual-source semantic test-case planner (ERROR_POINTS + INVARIANTS) |
| `z_amend` | `/z-amend` | Amend an existing plan (SPEC/PLAN/TASKS) preserving completed state |
| `z_init_docs` | `/z-init-docs` | Bootstrap a two-tier docs system (human Markdown + LLM JSON) |
| `z_maintain_docs` | `/z-maintain-docs` | Refresh stale docs after source changes via per-concept updaters |
| `z_uplift` | `/z-uplift` | Bulk codebase quality uplift — decompose + per-component audit |
| `z_improve` | `/z-improve` | Post-run retrospective — analyze events.jsonl for friction signals |
| `z_subagent_dispatch` | `/z-subagent-dispatch` | Dispatch a subagent via LLM CLI |

### Fast / read-only commands (direct in-process handlers)

| Tool name | z-harness command | Description |
|---|---|---|
| `z_where` | `/z-where` | List active plans, current phase, branch, age, status |
| `z_stats` | `/z-stats` | Progress + cost report for the current plan |
| `z_suggest_memory` | `/z-suggest-memory` | Author a memory entry for docs/llm/ from debug post-mortems |
| `z_axiom_scan` | `/z-axiom-scan` | Mine candidate axioms from interaction history |
| `z_axiom_list` | `/z-axiom-list` | List axiom records from the store with filtering |
| `z_axiom_approve` | `/z-axiom-approve` | Approve a candidate axiom (requires explicit confirmation) |
| `z_axiom_reject` | `/z-axiom-reject` | Reject a candidate or approved axiom |
| `z_axiom_edit` | `/z-axiom-edit` | Edit a field on a candidate or approved axiom record |
| `z_personas` | `/z-personas` | Inspect the persona registry, role bindings, and persona files |
| `z_handoff` | `/z-handoff` | Write a handoff.json artifact for session continuity |
| `z_update` | `/z-update` | Update the local z-harness install |
| `z_sharpen` | `/z-sharpen` | Conversational bounded idea-sharpener — probes, reframes, and converges a vague idea into a buildable problem statement; writes GRILL.md |
| `z_overnight` | `/z-overnight` | Overnight batch run of multiple /z-* commands |
| `z_evaluate` | `/z-evaluate` | Evaluate a completed z-harness session for patterns worth preserving |
| `z_context_budget` | `/z-context-budget` | Analyze context utilization and surface savings recommendations |
| `z_doc_rationale` | `/z-doc-rationale` | Produce ADRs, design rationale, and tradeoff explanations |
| `z_test_invariant` | `/z-test-invariant` | Legacy invariant-only test-case planner |

### Utility tools

| Tool name | z-harness command | Description |
|---|---|---|
| `z_export` | `/z-export` | Export z-harness commands/agents/skills to a host |
| `z_detect` | `/z-detect` | Detect installed hosts and versions |

### Tool arguments

Every tool accepts the same two arguments:

| Argument | Type | Description |
|---|---|---|
| `prompt` | `str` (optional) | The task or goal for the command (same as the free-text argument you'd pass on the CLI) |
| `slug` | `str` (optional) | Plan slug to target (sets `Z_HARNESS_SLUG`); fast commands like `z_stats` require it |

### Tool result envelope

Every tool returns a JSON object:

```json
{
  "ok": true,
  "status": "complete",
  "content": "<human-readable output>",
  "artifacts": {},
  "meta": {}
}
```

`status` is one of `"complete"`, `"error"`, `"blocked"`, `"needs_input"`, or `"skipped"`. When `status`
is `"needs_input"`, `meta.question_id` carries a correlation ID and `content` is the
question for the user.

**Resume after `needs_input`.** A client answers a `needs_input` result by re-calling the
same tool with a `resume` argument of shape `{"question_id": "...", "answer": "..."}`.
`MCPDispatcher` appends the answer as a delimited continuation block to the dispatch prompt
and re-runs the command so it proceeds past the question. This is a re-dispatch-with-answer,
**not** a live session resume — the dispatcher's `session_id` is telemetry-only and no driver
implements true subprocess continuation.

**`skipped` status (consulting disabled).** When `Z_HARNESS_CONSULT=off`,
`scripts/resolve-provider.py <role>` returns the bare sentinel `none` for consult/reviewer-bound
roles. `MCPDispatcher` detects this sentinel (bare `none` on stdout, or a JSON payload whose
`provider == "none"`) and returns `status="skipped"` — distinct from a genuine provider-resolution
failure, which returns `status="error"`. (Addresses the consult-off bypass from the MCP-server
plan's AUDIT Finding 10.)

**Content & artifact sourcing.** `content` (the human-readable narrative) is reconstructed from
the dispatcher's `type == "text"` stream events — **not** from the subprocess `stderr` (which
carries only raw CLI diagnostics). `artifacts` is populated from each `type == "artifact"` stream
event as `{ name → content }`; a command that writes files without emitting an `artifact` event
will not surface those files, so drivers are responsible for emitting one `artifact` event per
durable write. The event stream is the wire mechanism; it is expected to mirror what the command
wrote under `$Z_HARNESS_PLAN_DIR/<slug>/`.

## Editor MCP config snippets

### Cursor

Add to `.cursor/mcp.json` (project) or `~/.cursor/mcp.json` (global):

```json
{
  "mcpServers": {
    "z-harness": {
      "command": "z-harness",
      "args": ["serve"],
      "env": {}
    }
  }
}
```

If `z-harness` is not on `PATH`, replace `"command": "z-harness"` with the full path
(e.g. `"command": "/usr/local/bin/z-harness"`) or use `python3 -m z_harness_cli` and
`"args": ["serve"]`.

### VS Code (via Copilot MCP)

Add to `.vscode/mcp.json` (workspace) or the user `settings.json` under
`"github.copilot.mcp.servers"`:

```json
{
  "servers": {
    "z-harness": {
      "type": "stdio",
      "command": "z-harness",
      "args": ["serve"]
    }
  }
}
```

### Claude Desktop

Add to `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS) or the
platform equivalent:

```json
{
  "mcpServers": {
    "z-harness": {
      "command": "z-harness",
      "args": ["serve"]
    }
  }
}
```

After saving, restart Claude Desktop. The z-harness tools will appear in the tool picker.

### Hermes

Hermes connects to `z-harness serve` via stdio. Set the MCP server path in
`~/.config/hermes/config.toml` (or your Hermes config location):

```toml
[mcp_servers.z-harness]
command = "z-harness"
args    = ["serve"]
```

Or set it via `Z_HERMES_MCP_COMMAND`:

```bash
export Z_HERMES_MCP_COMMAND="z-harness serve"
```

Hermes calls `z_plan`, `z_implement_all`, `z_implement_next`, and the fast read handlers
(`z_where`, `z_stats`) as its primary integration points.

## Key entry points

- `z_harness_cli/__main__.py:184` — `serve_cmd` — Typer CLI wrapper; help text: "Start the z-harness MCP server (stdio)"; delegates to `z_harness_cli/commands/serve.py`.
- `z_harness_cli/commands/serve.py:11` — `run` — Thin command implementation; calls `z_harness_cli.mcp.server.serve(transport=transport)`.
- `z_harness_cli/mcp/server.py:32` — `mcp` — `FastMCP("z-harness")` singleton; all tools are registered against it at import time via `_register_tools()`.
- `z_harness_cli/mcp/server.py:360` — `COMMAND_TOOLS` — Registry mapping tool name → `{command_id, description, is_heavy, skills_path}`. 39 entries.
- `z_harness_cli/mcp/server.py:208` — `MCPDispatcher` — Routes heavy commands through `runtime/dispatch/dispatcher.py`; bridges `DispatchResult` to `ToolResult`.
- `z_harness_cli/mcp/server.py:675` — `_FAST_HANDLERS` — Dict of direct in-process handlers for read-only tools (`z_where`, `z_stats`, `z_handoff`, `z_personas`, `z_update`, `z_export`, `z_detect`).
- `z_harness_cli/mcp/server.py:707` — `serve` — `mcp.run(transport=transport)` — public entry point called by the CLI.

## How it interacts with others

- `runtime/dispatch/dispatcher.py` — Heavy commands are routed through the dispatcher, which selects the provider and driver, then runs the command subprocess.
- `scripts/resolve-provider.py` — Provider resolution for each heavy tool call; falls back to `reviewer` role if the primary role has no configured provider.
- `runtime/drivers` — The dispatcher selects a driver (`claude`, `cursor`, `codex`, `antigravity`) based on provider config.
- `z_harness_cli/commands/export.py` — `z_export` fast handler imports `export.run` directly.
- `z_harness_cli/adapters/registry.py` — `z_detect` fast handler calls `detect_all()`.

## Edge cases / gotchas

- The server requires `fastmcp>=3.4.2` and `mcp>=1.20`. If FastMCP is not installed, `serve()` raises `RuntimeError: FastMCP is not installed. Install with: pip install fastmcp`.
- **stdio only** — No HTTP/SSE transport is currently wired. The `transport` parameter accepts any string FastMCP supports but `"stdio"` is the only tested and documented transport.
- Heavy tools require a configured provider (via `providers.json` or env). If no provider is configured, the tool returns `status: "error"` with a message about provider resolution failure — it does not crash the server.
- `z_stats` requires a `slug` argument; it returns `status: "needs_input"` with `question_id: "slug_select"` when the slug is absent.
- Tool registration happens at import time (`_register_tools()` is called at module bottom). The server module is safe to import without FastMCP; tools simply are not registered if `mcp is None`.
- `needs_input` signals are detected by scanning dispatcher stderr for `AskUserQuestion:`, `[INPUT_REQUIRED]`, or structured `question_id:` lines. The editor/host is responsible for presenting the question to the user and re-calling the tool with the answer as `prompt`.
