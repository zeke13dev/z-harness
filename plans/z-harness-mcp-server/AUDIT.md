The audit is written to `~/.local/state/z-harness/z-harness-ded77383/plans/mcp-server/AUDIT.md`.

## Key findings at a glance

**3 FAILs, 8 WARNs, 12 PASSes**

### FAIL — blocks implementation as written:

1. **Command execution model is wrong** (Finding 1). The plan assumes `/z-*` commands are Python modules in `z_harness_cli/commands/` that can be imported in-process. Reality: they're 53 markdown files in `commands/z-*.md` orchestrated by LLM hosts. `z_harness_cli/commands/` contains only 5 packaging CLI modules (`launch`, `export`, `doctor`, `update`, `init`). The MCP server must use `runtime/dispatch/dispatcher.py` → `HostDriver.dispatch()` — subprocess-based dispatch, not Python imports. **This invalidates the internals of T004 and T007.**

2. **`resolve-provider.py` has no `export-env` subcommand** (Finding 2). The SPEC says "reads `scripts/resolve-provider.py export-env`" — but that script takes a single `<role>` arg. `export-env` lives on `config.py`.

3. **Command catalog is incomplete** (Finding 3). The plan lists 30 command tools, but there are 53 `commands/z-*.md` files and 36 `skills/` directories. Missing: `z-context-budget`, `z-doc-rationale`, `z-evaluate`, `z-overnight`, `z-reality`, `z-test-invariant`.

### Key WARNs:
- `mcp>=1.0.0` is too loose — current PyPI is 1.27.2, API has churned
- `select_driver()` return type is `object`, not `HostDriver` (minor type-gap)
- No risk documented for `Z_HARNESS_CONSULT=off` bypass in subagent dispatch
- Task complexity: T007 should be **high**, not medium (see Finding 1)

The plan's high-level architecture — decisions, ToolResult schema, invariants, error coverage — is sound. The gap is in the realization that commands aren't Python functions you import; they're workflows dispatched through subprocess LLM hosts.
e.wait()` → `DispatchResult`. This is the *only* path to execute a `/z-*` command.

  **What the plan assumes:**
  - T004: `_dispatch_command()` calls a Python function (`z_harness_cli.commands.plan.run()`) and reads artifacts from disk.
  - T003: Auto-registers each command as `@mcp.tool()` with direct Python function bodies.

  **Reality:** Every `/z-*` command must be dispatched through a host driver (pi/codex/claude). The MCP server cannot `import z_harness_cli.commands.plan` — it must:
  1. Resolve a provider (via `resolve-provider.py <role>`)
  2. Select a driver (via `runtime/drivers/select_driver(host)`)
  3. Call `driver.dispatch(command_id, args, env)` to spawn the host subprocess
  4. Stream events via progress, wait for `DispatchResult`
  5. Read artifacts from `$Z_HARNESS_PLAN_DIR/<slug>/` after the host exits

- **Recommendation:** Rewrite T004 and T007 to use `runtime/dispatch/dispatcher.py` (the existing dispatcher) rather than assuming in-process Python imports. The `_dispatch_command()` signature is correct, but its internals must compose a `HostDriver.dispatch()` call, not a Python import. Reclassify T004 and T007 from "medium"/"high" complexity to "high" (this is more complex than the current design assumes). Consider adding a new task to wrap the dispatcher for MCP use.

---

## Finding 2: `resolve-provider.py` has no `export-env` subcommand

- **Verdict:** **FAIL**
- **Artifact:** SPEC.md "Auth Flow" line 1: "Server reads `scripts/resolve-provider.py export-env` at startup"
- **Codebase evidence:**
  - `scripts/resolve-provider.py` accepts exactly one argument: `<role>` (a provider role name). It prints a JSON provider descriptor to stdout. See `main()` at line ~503: `if len(sys.argv) != 2: print("usage: resolve-provider.py <role>")`.
  - The `export-env` subcommand belongs to `scripts/config.py`, not `resolve-provider.py`. `config.py export-env` prints `export Z_HARNESS_*=...` lines for all non-meta config keys.

  **What the plan intended vs what exists:**
  - For auth: the server should call `resolve-provider.py <role>` to get a provider descriptor (including `auth_env` keys), then resolve API keys from the environment.
  - For config: the server should call `config.py export-env` to set `Z_HARNESS_*` env vars for the subprocess.

- **Recommendation:** Fix SPEC.md "Auth Flow" to either:
  - (a) Reference `config.py export-env` for config/env setup and `resolve-provider.py <role>` for per-dispatch provider resolution; or
  - (b) State that the server calls `scripts/resolve-provider.py <role>` at dispatch time (not startup), obtaining the `auth_env` list from the returned JSON descriptor.

---

## Finding 3: Command catalog is incomplete — 6 commands missing, 7 extra commands not listed

- **Verdict:** **FAIL** (materially different surface area affects risk, testing, and complexity estimates)
- **Artifact:** SPEC.md tool list (29+3 tools), TASKS.md T003 registry (29 entries), T005/T007 command grouping
- **Codebase evidence:**

  **Commands in `commands/*.md` (53 total):**
  The plan lists 30 command tools. The actual `commands/` directory has 53 markdown command files. Missing from the plan:

  | Missing command | Description |
  |---|---|
  | `z-context-budget` | Analyze context utilization (listed as skill, not registered as tool) |
  | `z-doc-rationale` | Tier 2 narrative doc generation (listed as skill, no command tool) |
  | `z-evaluate` | Post-run evaluation for patterns (listed as skill, no command tool) |
  | `z-overnight` | Autonomous overnight run orchestrator (has `commands/z-overnight.md`) |
  | `z-reality` | Interactive premise refinement (has `commands/z-reality.md`) |
  | `z-test-invariant` | Archived invariant-only test planner (has `commands/z-test-invariant.md`) |

  **Commands in the plan but NOT in `commands/*.md`:**
  - `z_audit` → the actual command file is `z-audit.md` (but `z-audit-plan.md` and `z-audit-plan-style.md` are separate)
  - `z_subagent_dispatch`, `z_export`, `z_detect`, `z_status` — these are MCP-internal tools, not `/z-*` commands; reasonable to have them

  **Skills in `skills/z-*` (36 total):**
  All 36 skills have corresponding `skills/z-*/SKILL.md` files. The plan lists 29 commands covering most skills, but the mapping command↔skill is not 1:1 (some commands invoke multiple skills; some skills have no standalone command).

- **Recommendation:** 
  1. Add the 6 missing commands to the registry (T003). 
  2. Re-count all command registrations — the plan claims "29 commands" but should be ~30 from skills + 4 utility tools = 34 total tools.
  3. Reassess T007 complexity: more commands means more tool functions to implement and test.

---

## Finding 4: `mcp` dependency not in `pyproject.toml`; version pin needs scrutiny

- **Verdict:** **WARN**
- **Artifact:** PLAN.md Phase D, TASKS.md T012, T016
- **Codebase evidence:**
  - `pyproject.toml` dependencies: `["typer>=0.9", "rich>=13"]`. No `mcp` or FastMCP entry.
  - `scripts/pi-mcp-server.py` imports `from mcp.server.fastmcp import FastMCP` — note the import path is `mcp.server.fastmcp`, not `mcp`.
  - Latest `mcp` on PyPI: **1.27.2** (the library has evolved rapidly from 1.0.0 to 1.27.2).
  - Python target: `>=3.11` — adequate for async/FastMCP support.

- **Recommendation:**
  1. Pin `mcp>=1.20` (not `>=1.0.0`) to avoid API drift from the 1.0 era. FastMCP's API surface has seen breaking changes across minor versions.
  2. Verify the import path: `from mcp.server.fastmcp import FastMCP` (not just `from mcp import FastMCP`).
  3. Test with the hermes agent venv's Python to confirm no version conflicts with the existing `mcp` install there.

---

## Finding 5: `select_driver()` return type is `object`, not `HostDriver`

- **Verdict:** **WARN**
- **Artifact:** PLAN.md "SOLID" — "MCP server depends on HostDriver ABC"
- **Codebase evidence:**
  - `runtime/drivers/__init__.py` line: `def select_driver(host: str, driver_override: str | None = None) -> object:`
  - The function returns concrete `HostDriver` instances (`SubprocessClaudeDriver`, `CodexDriver`, `CursorCLIDriver`, `AntigravityHostDriverShim`) but its return type annotation is `object`.
  - `HostDriver.dispatch()` takes `command_id` as a string (not `args` as the first positional), matching the plan's call signature `driver.dispatch(command_id, args, env)`. ✅

- **Recommendation:** The MCP server should type-narrow the return value with `isinstance(handle, HostDriver)` or cast. Not a blocker — all concrete drivers implement the `HostDriver` ABC — but the `object` return type is a papercut. Consider filing an upstream fix to annotate `select_driver() -> HostDriver`.

---

## Finding 6: `pi-mcp-server.py` import location differs from what `pyproject.toml` would install

- **Verdict:** **WARN**
- **Artifact:** N/A (cross-reference for design patterns)
- **Codebase evidence:**
  - `scripts/pi-mcp-server.py` is a standalone script in `scripts/`, NOT a package module. It uses `from mcp.server.fastmcp import FastMCP` at module level.
  - The new MCP server is proposed as `z_harness_cli/mcp/server.py` (a proper package module). This is architecturally cleaner.

  **Patterns to inherit:**
  - `mcp.run(transport="stdio")` — confirmed working pattern ✅
  - `@mcp.tool()` decorator usage — standard ✅
  - `_needs_user_input()` heuristic for detecting when the LLM is asking a question — relevant for T008 needs_input handling
  - `_extract_text_and_usage()` NDJSON parsing pattern — shows how to consume subprocess output

  **Patterns to avoid:**
  - `pi-mcp-server.py` manually spawns `subprocess.Popen` with `subprocess.communicate()`. The z-harness MCP server should use the existing `runtime/dispatch/dispatcher.py` instead — it already handles subprocess lifecycle, timeout reaping, event streaming, and result collection.

- **Recommendation:** Document in PLAN.md that the MCP server delegates subprocess management to `runtime/dispatch/dispatcher.py`, NOT manual subprocess spawning. This is stated in the invariants but should be explicit in the design.

---

## Finding 7: Command/skill mapping is not 1:1 — several skills have no command file

- **Verdict:** **WARN**
- **Artifact:** SPEC.md tool list, TASKS.md T003 registry
- **Codebase evidence:**
  - 36 skills under `skills/z-*/` but only 30 of them have corresponding `commands/z-*.md` files.
  - Skills without standalone command files:
    | Skill | Has `commands/z-*.md`? |
    |---|---|
    | `z-audit-plan` | Yes (`z-audit-plan.md`) |
    | `z-audit-plan-style` | Yes (`z-audit-plan-style.md`) |
    | `z-context-budget` | Yes (`z-context-budget.md`) |
    | `z-doc-rationale` | **No** — skill only, no command file |
    | `z-evaluate` | Yes (`z-evaluate.md`) |
    | `z-test-invariant` | Yes (`z-test-invariant.md`) |
    | `z-overnight` | Yes (`z-overnight.md`) |
    | `z-reality` | Yes (`z-reality.md`) |

  After checking all 36 skills, some skills are "sub-orchestrator" skills invoked by other commands (not directly by users). The MCP server should expose all skills as tools (matching user expectation), but dispatch paths differ for skills without a `commands/*.md` entry.

- **Recommendation:** For skills without `commands/*.md`, the MCP tool should load and execute `skills/<name>/SKILL.md` directly as a subagent dispatch. Add a task for handling "skill-only" commands differently from "command-file" commands.

---

## Finding 8: Missing risk — FastMCP API churn across versions

- **Verdict:** **WARN**
- **Artifact:** PLAN.md "Risks" table
- **Codebase evidence:**
  - `mcp` PyPI package has 27+ releases from 1.0.0 to 1.27.2.
  - `scripts/pi-mcp-server.py` works with the currently installed `mcp` (in hermes venv), but the plan pins `mcp>=1.0.0` — a 1.0-series API may not match the 1.27 API.
  - FastMCP API surface: `FastMCP(name)`, `@mcp.tool()`, `mcp.run(transport="stdio")`, `ctx.report_progress()` — these have been stable since ~1.10 but `Context` type import path may vary.

- **Recommendation:** Add to PLAN.md Risks: "FastMCP API stability — rapid version evolution (1.0→1.27). Pin to `>=1.20` and test with the version installed in the hermes venv."

---

## Finding 9: Missing risk — MCP tool parameter limits

- **Verdict:** **WARN**
- **Artifact:** PLAN.md "Risks" table
- **Codebase evidence:**
  - The plan registers ~34 tools, many with optional parameters (`slug`, `model`, `timeout`, `resume`, `ctx`). 
  - Some MCP client implementations (VS Code, early Cursor builds) have limits on tool count, parameter count, or tool description length.
  - Large tools like `z_plan(prompt, slug, ctx)` with rich parameter schemas must stay within MCP JSON-RPC message size limits.

- **Recommendation:** Add risk: "MCP client compatibility — some clients limit tool count or parameter count. Test with Hermes, Cursor, and VS Code MCP clients. Consider progressive disclosure (group tools by namespace) if tool count exceeds client limits."

---

## Finding 10: Missing risk — `Z_HARNESS_CONSULT=off` bypass for subagent dispatch

- **Verdict:** **WARN**
- **Artifact:** PLAN.md "Risks" table, SPEC.md "z_subagent_dispatch"
- **Codebase evidence:**
  - `resolve-provider.py` main(): when `Z_HARNESS_CONSULT=off`, consultant/reviewer roles return the sentinel string `"none"`. 
  - The MCP server's `z_subagent_dispatch` tool must handle this: if the agent's model resolves to a consult role and consult is off, the tool must report the skip, not silently succeed with no output.

- **Recommendation:** Add to PLAN.md Risks: "Consult-off mode — when Z_HARNESS_CONSULT=off, resolve-provider returns 'none' for review/consult roles. z_subagent_dispatch must detect this and return ToolResult with status='skipped' rather than silently succeeding or crashing."

---

## Finding 11: `ctx` parameter in tool signatures may conflict with FastMCP `Context` injection

- **Verdict:** **WARN**
- **Artifact:** SPEC.md "Tool signature pattern"
- **Codebase evidence:**
  - SPEC shows: `async def z_plan(prompt: str, slug: str | None = None, ctx: Context | None = None) -> ToolResult:`
  - FastMCP auto-injects `Context` when a parameter is typed `Context` and the MCP client provides it. But the plan makes `ctx` an explicit optional parameter at the end of the signature — this should work with FastMCP's injection, but needs verification.
  - `pi-mcp-server.py` does not use `Context` at all (no progress reporting).

- **Recommendation:** Verify that FastMCP's `Context` injection works with `ctx: Context | None = None` optional parameters. If not, use `ctx = None` with explicit `isinstance` checks inside the function body.

---

## PASS findings (confirmed correct)

### P1: `HostDriver.dispatch()` returns `DispatchHandle` with `.wait()` → `DispatchResult` ✅
- `runtime/dispatch/driver.py` lines 150-250: `HostDriver.dispatch(command_id, args, env) -> DispatchHandle`
- `DispatchHandle.wait() -> DispatchResult` (line 122-134)
- `DispatchResult` has `exit_code`, `is_error`, `stdout_events`, `stderr`, `wall_ms`, `session_id`

### P2: `select_driver()` exists ✅
- `runtime/drivers/__init__.py`: `select_driver(host, driver_override=None) -> object`
- Supports: claude, cursor, codex, antigravity
- Raises `DriverNotFoundError` for unknown hosts

### P3: `agents/*.md` YAML frontmatter pattern ✅
- 28 agent files in `/Users/zeke/dev/z-harness/agents/*.md`
- Plan describes YAML frontmatter with `model`, `tools`, `prompt`, `description` — confirmed pattern matches

### P4: `z_harness_cli/adapters/registry.py` exists with `detect_all()` ✅
- `adapters/registry.py` exports `select()`, `detect_all()`, `UnknownHostError`, `NoHostInstalledError`
- `adapters/base.py` hosts `HostAdapter` ABC and `KNOWN_COMMANDS`

### P5: `z_harness_cli/commands/export.py` exists with `run()` ✅
- `export.py::run()` accepts `host`, `all_hosts`, `in_place`, `out`, `force`

### P6: `scripts/config.py` subcommands match described behavior ✅
- `config.py export-env` prints export lines for all non-meta keys
- `config.py get <key>`, `config.py explain <key>`, `config.py list-question-ids`, etc. all present

### P7: `runtime/dispatch/dispatcher.py` provides the full dispatch lifecycle ✅
- Event iteration, timeout reaping, `dispatch_end` events, result collection
- The MCP server should wrap this, not reimplement it

### P8: Architecture diagram matches codebase ✅
- The layered diagram in PLAN.md correctly shows MCP Client → MCP Server → dispatch engine → drivers → subprocess

### P9: Decisions D1-D10 are sound ✅
- Whole-command tools (D1), streaming progress (D2), synchronous subagent dispatch (D3), z-harness auth only (D4), hybrid envelope (D5), stdio-only (D6), supplement HostAdapter (D7), package location (D8), snake_case naming (D9), single subagent tool (D10) — all reasonable

### P10: ToolResult schema is well-designed ✅
- `{ok, status, content, artifacts, meta}` — clean, extensible, maps well to MCP tool result format

### P11: Error handling coverage is thorough ✅
- SPEC.md error table covers command_not_found, timeout, binary_missing, auth_failure, plan_collision, needs_input

### P12: INVARIANT statements are correct ✅
- "Never implements z-harness logic — only translates MCP calls" — correct principle
- "Stateless between calls" — achievable with disk-state model
- "ToolResult.content holds EXACTLY the command's output" — good contract

---

## Task complexity reclassification

| Task | Current | Recommended | Reason |
|------|---------|-------------|--------|
| T004 | high | **high** (stays) | Still complex, but now involves wrapping `dispatcher.py`, not importing Python modules |
| T007 | medium | **high** | Heavy commands must now dispatch through host drivers, not call Python functions. Each command tool needs driver selection, env preparation, progress streaming, artifact reading |
| T005 | medium | **medium** (stays) | Read-only commands don't need subprocess spawns, but reading disk state correctly is non-trivial |
| T008 | high | **high** (stays) | `needs_input` handling is fundamentally hard across async subprocess boundaries |
| T010 | high | **high** (stays) | Subagent dispatch complexity unchanged |
| T003 | medium | **medium** (stays) | Registry population grows from 29 to ~34 tools, but complexity unchanged |
| T013 | medium | **medium** (stays) | Error hardening is mechanical |

---

## Missing tasks

1. **T017: Wrap dispatcher for MCP** — Write a thin `MCPDispatcher` wrapper around `runtime/dispatch/dispatcher.py` that:
   - Accepts MCP-tool parameters and translates to `dispatcher.dispatch()` args
   - Bridges `DispatchResult` to `ToolResult`
   - Provides the progress callback integration point
   - Handles the `Z_HARNESS_CONSULT=off` bypass

2. **T018: Verify FastMCP Context injection** — Write a test that confirms `ctx: Context | None = None` works with FastMCP's auto-injection before wiring it into 30+ tools.

3. **T019: Handle skill-only commands** — For skills without `commands/z-*.md` files (e.g., `z-doc-rationale`), implement a dispatch path that loads `skills/<name>/SKILL.md` directly.

---

## Summary and recommended amendments

The plan needs three material revisions before implementation:

1. **Rewrite T004/T007 dispatch model** (Finding 1) — switch from in-process Python imports to `runtime/dispatch/dispatcher.py`-based host driver dispatch. This is the single largest architecture correction.

2. **Fix auth flow reference** (Finding 2) — correct `resolve-provider.py export-env` to the actual API (`resolve-provider.py <role>` for providers, `config.py export-env` for config).

3. **Expand command catalog** (Finding 3) — add the 6 missing skill commands, reconcile the 53 markdown command count vs 36 skill count, and update T003/T005/T007 accordingly.

Without these fixes, T004 and T007 cannot be implemented as written. The plan's high-level architecture (decisions D1-D10, ToolResult schema, error handling, invariants) is correct and should be preserved.
