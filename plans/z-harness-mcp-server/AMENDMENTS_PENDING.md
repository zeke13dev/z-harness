# Pending Amendments for mcp-server (slug: mcp-server)

> Collected from AUDIT.md findings. To be applied when SPEC.md / PLAN.md / TASKS.md exist.

## Amendment 1: SPEC.md — Overview section
- **Section:** `## Overview`
- **Old:** "A thin adapter over the existing z-harness engine (commands, agents, skills, drivers, config)"
- **New:** "A thin adapter over the existing z-harness dispatch engine. Delegates ALL command execution to `runtime/dispatch/dispatcher.py` which dispatches through `HostDriver.dispatch()` → subprocess LLM CLI."

## Amendment 2: SPEC.md — Behavior section, step 4
- **Section:** `## Behavior` (line ~66-72), step 4
- **Old:** "Calls internal dispatch to run the command pipeline"
- **New:** "Calls `_dispatch_command()` which wraps `runtime/dispatch/dispatcher.py` to spawn the appropriate host driver, stream events via progress, wait for the result, and read artifacts from disk"

## Amendment 3: SPEC.md — Invariant to add
- **Add INVARIANT:** "The MCP server NEVER imports or calls command implementation code directly. All command execution goes through `runtime/dispatch/dispatcher.py` → `HostDriver.dispatch()`."

## Amendment 4: TASKS.md — T004 changes
- (Awaiting details)

## Amendment 5: PLAN.md or SPEC.md — Core dispatch pipeline rewrite
- **Old:** Step "Select driver via `runtime/drivers/select_driver()`"
- **New:** Step "Call `runtime/dispatch/dispatcher.dispatch(command_id, args, env)` which handles driver selection, subprocess lifecycle, event streaming, and result collection"

## Amendment 6: PLAN.md or SPEC.md — Remove step
- **Remove:** "Call `driver.dispatch(command_id, args, env)`" — the dispatcher handles this

## Amendment 7: PLAN.md or SPEC.md — Add step
- **Add step:** "Wrap the dispatcher with `MCPDispatcher` helper that bridges DispatchResult → ToolResult and connects progress callbacks"

## Amendment 8: SPEC.md — Auth Flow section (Finding 2 — FAIL)
- **Section:** `## Auth Flow`
- **Old line 1:** "Server reads `scripts/resolve-provider.py export-env` at startup → caches provider env"
- **New line 1:** "Server calls `scripts/config.py export-env` at startup → caches Z_HARNESS_* env vars"

## Amendment 9: SPEC.md — Auth Flow section (continued)
- **New line 2:** "Per-tool dispatch: calls `scripts/resolve-provider.py <role>` to get provider descriptor (including auth_env keys)"
- **New line 3:** "Resolves API keys from environment variables listed in provider descriptor"
- **New line 4:** "Passes resolved env to `dispatcher.dispatch()`"

## Amendment 10: SPEC.md — Expand command catalog (Finding 3 — FAIL)
- Add these 6 missing commands to the tool list in `### NEW: z_harness_cli/mcp/server.py`:
  - `z_reality` — Interactive premise refinement
  - `z_overnight` — Autonomous overnight run orchestrator
  - `z_evaluate` — Post-run evaluation for patterns
  - `z_context_budget` — Analyze context utilization
  - `z_doc_rationale` — Tier 2 narrative doc generation
  - `z_test_invariant` — Invariant-only test planner

## Amendment 11: TASKS.md — T003 changes
- Expand registry from 29 to ~34 entries, adding the 6 missing commands (z_reality, z_overnight, z_evaluate, z_context_budget, z_doc_rationale, z_test_invariant)

## Amendment 12: PLAN.md — Non-Goals section
- Add note: skill-only commands (no commands/*.md file) may require direct SKILL.md loading

## Amendment 13: Version pin and risks (Findings 4, 6, 8, 9, 10 — WARNs)
- TASKS.md T012 changes:
  - Change `mcp>=1.0.0` to `mcp>=1.20` in pyproject.toml step
- PLAN.md risks table additions:

| Risk | Mitigation |
|------|------------|
| FastMCP API churn (1.0→1.27) | Pin `mcp>=1.20`, test with venv's installed version |
| MCP client tool count limits (~34 tools) | Test with Hermes, Cursor, VS Code. Consider progressive grouping if needed |
| Z_HARNESS_CONSULT=off returns "none" for review roles | z_subagent_dispatch detects consult-off and returns status="skipped" |
| FastMCP Context injection with optional ctx param | Verify `ctx: Context \| None = None` works with FastMCP's auto-injection. Add T018 to test this. |

## Amendment 14: Task complexity reclassification (from audit)
- **PLAN.md or TASKS.md:**
  - T007: medium → high (heavy commands now dispatch through host drivers, not Python functions)
  - Add T017: MCPDispatcher wrapper (new, high — wraps dispatcher.py for MCP use)
  - Add T018: Verify FastMCP Context injection (new, low — write a test)
  - Add T019: Handle skill-only commands (new, medium — dispatch path for skills without commands/*.md)
