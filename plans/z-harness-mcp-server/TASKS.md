# TASKS.md — z-harness MCP Server

## T001: Create package skeleton

**Files:** `z_harness_cli/mcp/__init__.py`, `z_harness_cli/mcp/server.py`  
**Status:** [ ]  
**Depends on:** none  

- [ ] Create `z_harness_cli/mcp/` directory
- [ ] Create `__init__.py` (empty, exports nothing at package level)
- [ ] Create `server.py` with FastMCP server shell:
  - `mcp = FastMCP("z-harness")` 
  - `serve()` function that calls `mcp.run(transport="stdio")`
  - Placeholder `_dispatch_command()` stub
  - `ToolResult` dataclass stub

**Complexity:** low

---

## T002: Implement ToolResult and serialization

**Files:** `z_harness_cli/mcp/server.py`  
**Status:** [ ]  
**Depends on:** T001  

- [ ] Define `ToolResult` dataclass with fields: `ok: bool`, `status: str`, `content: str`, `artifacts: dict[str, str]`, `meta: dict[str, object]`
- [ ] Add `to_dict()` serialization method
- [ ] Add `@staticmethod` factory methods: `success(content, artifacts, meta)`, `error(content)`, `blocked(content)`, `needs_input(content, question_id)`
- [ ] Write unit test in `tests/mcp/test_server.py::test_tool_result_serialization`

**Complexity:** low

---

## T003: Implement command tool registry

**Files:** `z_harness_cli/mcp/server.py`  
**Status:** [ ]  
**Depends on:** T002  

- [ ] Define `COMMAND_TOOLS` registry: dict mapping tool_name → command metadata
- [ ] Populate from the command catalog (slash-command slugs → snake_case tool names):
  - `z_plan`, `z_implement_all`, `z_implement_next`, `z_review_all`, `z_audit`, `z_audit_plan_style`, `z_debug`, `z_do`, `z_brainstorm`, `z_research`, `z_map`, `z_plan_light`, `z_plan_split`, `z_test`, `z_amend`, `z_init_docs`, `z_maintain_docs`, `z_uplift`, `z_improve`, `z_where`, `z_stats`, `z_suggest_memory`, `z_axiom_scan`, `z_axiom_list`, `z_axiom_approve`, `z_axiom_reject`, `z_axiom_edit`, `z_personas`, `z_handoff`, `z_update`, `z_reality`, `z_overnight`, `z_evaluate`, `z_context_budget`, `z_doc_rationale`, `z_test_invariant`
- [ ] Each entry: `{ "command_id": "/z-plan", "description": "Run the rigorous planning pipeline", "is_heavy": true, "skills_path": "skills/z-plan/SKILL.md" }`
- [ ] Auto-register each as `@mcp.tool()` with signature: `async def z_plan(prompt: str, slug: str | None = None, ctx: Context | None = None) -> ToolResult`

**Complexity:** medium

---

## T004: Implement core dispatch pipeline

**Files:** `z_harness_cli/mcp/server.py`  
**Status:** [ ]  
**Depends on:** T003  

- [ ] Implement `_dispatch_command(command_id: str, args: dict, ctx: Context | None) -> ToolResult`:
  - Resolve command metadata from registry
  - Set up environment: `Z_HARNESS_PLAN_DIR`, `Z_HARNESS_SLUG`, run ID
  - Resolve auth via `scripts/resolve-provider.py <role>` and pass resolved env
  - Call `runtime/dispatch/dispatcher.dispatch(command_id, args, env)` which handles driver selection, subprocess lifecycle, event streaming, and result collection
  - Wrap in `MCPDispatcher` helper that bridges DispatchResult → ToolResult and connects progress callbacks
  - Read artifacts from disk if applicable
- [ ] Handle missing-command: return `ToolResult.error("Unknown command")`
- [ ] Handle dispatch errors: return `ToolResult.error(error_message)`

**Complexity:** high

---

## T005: Implement read-only command tools

**Files:** `z_harness_cli/mcp/server.py`  
**Status:** [ ]  
**Depends on:** T004  

- [ ] Implement fast, read-only command tools that don't need subagent dispatch:
  - `z_where` — reads $Z_HARNESS_PLAN_DIR, lists active plans
  - `z_stats` — reads metrics.jsonl + TASKS.md, returns progress summary
  - `z_axiom_list` — reads axiom store, returns filtered list
  - `z_axiom_approve` — approves a candidate axiom (requires confirmation handled via `needs_input`)
  - `z_axiom_reject` — rejects an axiom
  - `z_axiom_edit` — edits an axiom field
  - `z_personas` — reads persona registry
  - `z_handoff` — produces handoff.json artifact
- [ ] Each returns immediately (no progress streaming, no subagent dispatch)
- [ ] Write integration test: `test_z_where_returns_plan_list`

**Complexity:** medium

---

## T006: Implement progress reporting for heavy commands

**Files:** `z_harness_cli/mcp/server.py`  
**Status:** [ ]  
**Depends on:** T004  

- [ ] Define progress phases per command type:
  - `z_plan`: premise_check → explore → decisions → consult → writing → complete
  - `z_implement_all`: task_N_start → task_N_complete (per task) → review → complete
  - `z_debug`: repro → hypothesis → evidence → isolate → fix → post_mortem
  - `z_brainstorm`: dispatch → anti_bias → synthesize → complete
  - `z_research`: map → brainstorm → adversarial_panel → synthesize → complete
- [ ] Implement `_report_phase(ctx, phase, total, current, message)` helper
- [ ] Integrate into `_dispatch_command()`: emit progress at each phase boundary
- [ ] Ensure fast commands skip progress entirely (no progress token)

**Complexity:** high

---

## T007: Implement heavy command tools

**Files:** `z_harness_cli/mcp/server.py`  
**Status:** [ ]  
**Depends on:** T006  

- [ ] Implement heavy commands that dispatch subagents + cross-consult:
  - `z_plan` — full planning pipeline
  - `z_do` — plan-less execution
  - `z_debug` — investigation + fix pipeline
  - `z_implement_all` — orchestrate all tasks
  - `z_implement_next` — next pending task
  - `z_brainstorm` — 3-vendor parallel ideation
  - `z_research` — map + brainstorm + synthesis
  - `z_map` — terrain mapping
  - `z_audit` — read-only audit pipeline
  - `z_review_all` — final-gate cross-LLM review
  - `z_test` — test case planner
  - `z_amend` — amend existing plan
  - `z_uplift` — bulk codebase audit
  - `z_improve` — post-run retro
  - `z_plan_light` — lightweight planner
  - `z_plan_split` — scope splitter
  - `z_init_docs` — bootstrap docs
  - `z_maintain_docs` — refresh stale docs
  - `z_suggest_memory` — write memory
  - `z_axiom_scan` — mine candidate axioms
  - `z_update` — update z-harness install
- [ ] Each calls `_dispatch_command()` with progress reporting

**Complexity:** high

---

## T008: Implement needs_input handling

**Files:** `z_harness_cli/mcp/server.py`  
**Status:** [ ]  
**Depends on:** T004  

- [ ] Detect when a command blocks on `AskUserQuestion`:
  - Command output contains structured question signal
  - `DispatchResult.is_error == false` but output incomplete
- [ ] Return `ToolResult.needs_input(content, question_id)` with the question text
- [ ] Support resume: client re-calls tool with `resume: { question_id, answer }` parameter
- [ ] Handle timeout: if client doesn't resume within configurable window, cancel

**Complexity:** high

---

## T009: Implement agent definition loader

**Files:** `z_harness_cli/mcp/server.py`  
**Status:** [ ]  
**Depends on:** T001  

- [ ] Implement `_load_agent(name: str) -> AgentDef`:
  - Read `agents/<name>.md`
  - Parse YAML frontmatter: `model`, `tools`, `prompt`, `description`
  - Return `AgentDef(model, tools, prompt_template, description)` dataclass
- [ ] Handle missing agent: raise `AgentNotFoundError`
- [ ] Handle malformed frontmatter: raise `AgentDefinitionError`
- [ ] Write unit test: `test_agent_resolve` — parses explore.md, doc-fetcher.md, reviewer.md

**Complexity:** medium

---

## T010: Implement z_subagent_dispatch tool

**Files:** `z_harness_cli/mcp/server.py`  
**Status:** [ ]  
**Depends on:** T009, T004  

- [ ] Implement `z_subagent_dispatch(agent: str, prompt: str, model: str | None = None, ctx: Context | None = None) -> ToolResult`:
  - Load agent definition via `_load_agent(agent)`
  - Resolve driver for agent's model: model → provider → driver
  - Apply model override if provided
  - Construct dispatch prompt: agent prompt template + user's task
  - Spawn subprocess via `driver.dispatch()`
  - Stream events via progress notifications: `agent_start`, `agent_progress`, `agent_complete`
  - Wait for result, parse into ToolResult
- [ ] Handle: agent not found, driver not found, subprocess timeout, parse error
- [ ] Write integration test: `test_z_subagent_dispatch_explore`

**Complexity:** high

---

## T011: Implement z_export and z_detect tools

**Files:** `z_harness_cli/mcp/server.py`  
**Status:** [ ]  
**Depends on:** T004  

- [ ] Implement `z_export(host: str | None = None, all_hosts: bool = False, out: str | None = None) -> ToolResult`:
  - Call `z_harness_cli.commands.export.run()` with structured args
  - Return `ToolResult` with file list and fidelity in meta
- [ ] Implement `z_detect() -> ToolResult`:
  - Call `z_harness_cli.adapters.registry.detect_all()`
  - Return `ToolResult` with installed hosts + versions in meta
- [ ] Integration test for z_detect (doesn't require actual editor installs)

**Complexity:** medium

---

## T012: Wire CLI entry point

**Files:** `z_harness_cli/commands/serve.py`, `z_harness_cli/commands/launch.py`, `pyproject.toml`  
**Status:** [ ]  
**Depends on:** T001  

- [ ] Create `z_harness_cli/commands/serve.py`:
  ```python
  def run(ctx, *, transport: str = "stdio"):
      """Start the z-harness MCP server."""
      from z_harness_cli.mcp.server import serve
      serve(transport=transport)
  ```
- [ ] Register in `z_harness_cli/commands/__init__.py` command table
- [ ] Wire `z-harness serve` subcommand in `launch.py` (or other CLI entry)
- [ ] Add `mcp>=1.20` to `pyproject.toml` dependencies
- [ ] Add `serve` entry point to `pyproject.toml` if applicable

**Complexity:** low

---

## T017: Implement MCPDispatcher wrapper

**Files:** `z_harness_cli/mcp/server.py`  
**Status:** [ ]  
**Depends on:** T004  

- [ ] Write `MCPDispatcher` helper class that wraps `runtime/dispatch/dispatcher.py`:
  - Accepts MCP-tool parameters and translates to `dispatcher.dispatch()` args
  - Bridges `DispatchResult` → `ToolResult`
  - Connects progress callbacks for MCP progress notifications
  - Handles the `Z_HARNESS_CONSULT=off` bypass (returns status="skipped")

**Complexity:** high

---

## T018: Verify FastMCP Context injection

**Files:** `tests/mcp/test_server.py`  
**Status:** [ ]  
**Depends on:** T002  

- [ ] Write a test that confirms `ctx: Context | None = None` works with FastMCP's auto-injection
- [ ] Verify before wiring it into 34+ tool functions
- [ ] Test both cases: ctx provided by client, ctx absent

**Complexity:** low

---

## T019: Handle skill-only commands

**Files:** `z_harness_cli/mcp/server.py`  
**Status:** [ ]  
**Depends on:** T004  

- [ ] Implement dispatch path for skills without `commands/z-*.md` files
- [ ] Load `skills/<name>/SKILL.md` directly and execute as subagent dispatch
- [ ] Affected commands: `z_doc_rationale` and any future skill-only tools

**Complexity:** medium

---

## T013: Error handling hardening

**Files:** `z_harness_cli/mcp/server.py`  
**Status:** [ ]  
**Depends on:** T004, T010  

- [ ] Ensure ALL tool functions return `ToolResult` — never throw unhandled exceptions
- [ ] Wrap every tool in try/except, catch broad `Exception`, return `ToolResult.error()`
- [ ] Error categories:
  - `command_not_found` — tool name doesn't match any command
  - `driver_not_found` — no HostDriver for required host
  - `auth_failure` — no API key for provider
  - `timeout` — subprocess exceeded timeout
  - `binary_missing` — pi/claude/codex not on PATH
  - `plan_collision` — slug already active with another session
  - `parse_error` — subprocess output couldn't be parsed
  - `internal_error` — unexpected exception
- [ ] Write unit test for each error category: `test_error_handling`

**Complexity:** medium

---

## T014: Unit tests

**Files:** `tests/mcp/test_server.py`  
**Status:** [ ]  
**Depends on:** T002, T009  

- [ ] `test_tool_result_serialization` — roundtrip to_dict/from_dict
- [ ] `test_tool_result_factories` — success(), error(), blocked(), needs_input()
- [ ] `test_agent_loading` — parse explore.md, doc-fetcher.md, reviewer.md
- [ ] `test_agent_not_found` — raises AgentNotFoundError
- [ ] `test_command_dispatch_mock` — mock driver, verify dispatch parameters
- [ ] `test_error_handling` — all error categories return ToolResult

**Complexity:** low

---

## T015: Integration tests

**Files:** `tests/mcp/test_integration.py`  
**Status:** [ ]  
**Depends on:** T005, T010  

- [ ] `test_server_starts` — server boots and accepts connections
- [ ] `test_z_where` — returns plan list (runs against test fixture)
- [ ] `test_z_stats` — returns progress data
- [ ] `test_z_subagent_dispatch` — dispatches explore agent, verifies result shape
- [ ] `test_z_detect` — returns installed hosts (mock)
- [ ] `test_needs_input_flow` — command returns needs_input, resume works
- [ ] `test_progress_streaming` — heavy command emits progress notifications

**Complexity:** medium

---

## T016: pyproject.toml and docs

**Files:** `pyproject.toml`, `README.md` (or relevant docs)  
**Status:** [ ]  
**Depends on:** T012  

- [ ] Add `mcp>=1.20` to `pyproject.toml` dependencies
- [ ] Add `serve` to CLI help text
- [ ] Document `z-harness serve` in user-facing docs
- [ ] Document MCP tool catalog (tool name → command mapping)
- [ ] Document editor MCP config snippets (Cursor, VS Code, Claude Desktop, Hermes)

**Complexity:** low

---

## Amendments

- **2026-06-11:** Expanded T003 registry from 29 to 35 entries (added 6 missing commands). (AUDIT Finding 3)
- **2026-06-11:** Rewrote T004 dispatch pipeline to use `runtime/dispatch/dispatcher.py` instead of manual driver selection. (AUDIT Finding 1)
- **2026-06-11:** Reclassified T007 complexity from medium to high (heavy commands now dispatch through host drivers). (AUDIT Finding 1)
- **2026-06-11:** Pinned `mcp>=1.20` in T012 and T016 (was `>=1.0.0`). (AUDIT Finding 4)
- **2026-06-11:** Added T017 (MCPDispatcher wrapper), T018 (FastMCP Context injection test), T019 (skill-only command dispatch). (AUDIT Findings 1, 7, 11)
