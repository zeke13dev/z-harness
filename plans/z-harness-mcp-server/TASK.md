# z-harness MCP Server — Universal Adapter

## Problem

z-harness has adapters for 4 editors (Claude Code, Codex, Cursor, Antigravity) plus pi, but every integration is a one-way file export — write prompt files to the editor's config directory. There's no live bidirectional protocol. This means:

- No editor can invoke z-harness commands dynamically
- No cross-editor subagent dispatch (pi subagents can't call Claude Code subagents)
- Hermes can only bridge to pi (via pi-mcp-server.py), not to Claude Code or Codex CLI
- Each new editor requires 12-24h of adapter development

## Goal

Build an **MCP server** for z-harness (`z-harness serve`) that:

1. **Exposes every `/z-*` command as an MCP tool** — `z_plan`, `z_implement_all`, `z_review`, `z_audit`, `z_debug`, `z_do`, `z_research`, `z_storm`, `z_explain`, etc. Tool names snake_cased from command slugs.

2. **Subagent dispatch over MCP** — the MCP server can spawn subagents through different LLM CLIs (pi, codex, claude) as sub-calls, returning structured results. This makes cross-editor subagent dispatch work natively — pi can call a codex subagent which can call a claude subagent.

3. **Hermes can connect to it** — just like the existing pi-mcp-server.py, Hermes loads the z-harness MCP server and gets all z-commands as tools. Then Hermes can dispatch work to pi, codex, or claude through z-harness.

4. **Any MCP-capable editor can use it** — Cursor, Windsurf, VS Code extensions, Claude Desktop, Cline, Continue, Cody, etc. Just point their MCP config at `z-harness serve`.

## Design constraints

- Written in **Python** (matches z-harness's existing Python runtime)
- Uses the existing command/agent/skill engine — doesn't reimplement, delegates
- Each MCP tool call maps to one phase of a z-harness command pipeline
- State management: plan artifacts on disk ARE the state (no additional server-side state)
- Auth: inherit from z-harness's existing provider configs
- Subagent dispatch: MCP server can make sub-calls to LLM CLIs (pi/claude/codex) and aggregate results
- The server is a subprocess (sidecar), not embedded in the editor

## Existing building blocks

- **z_harness_cli/commands/** — all command implementations exist as Python modules
- **agents/*.md** — agent definitions with tools, model pins, prompts
- **skills/*/SKILL.md** — operational playbooks
- **scripts/config.py** — config resolver, providers registry, persona system
- **pi-mcp-server.py** — reference implementation of an MCP server in Hermes's z-harness integration
- **runtime/drivers/** — existing persona/command runtime drivers

## Key questions to resolve in the plan

1. How to map async z-harness commands (which can take minutes, dispatch subagents) to MCP tool calls (which expect seconds)?
2. Should subagent dispatch over MCP be synchronous (block until subagent returns) or fire-and-forget with a status endpoint?
3. How to handle auth — pass through the calling editor's API keys, or use z-harness's own provider config?
4. How to handle the "no universal IR" problem — the MCP server needs structured I/O, not line-rewritten markdown
5. What's the MCP transport? stdio (simplest, works with all editors) or SSE (needed for remote?)
6. How does this relate to the existing HostAdapter framework — replace it, supplement it, or coexist?

/go z-plan
