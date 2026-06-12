"""Unit tests for z_harness_cli.mcp.server — ToolResult, agent loading, error handling, FastMCP Context injection."""

from __future__ import annotations

import pytest


# ── ToolResult tests ────────────────────────────────────────────────────────


class TestToolResult:
    """Tests for ToolResult dataclass — serialization and factory methods."""

    def test_tool_result_serialization(self) -> None:
        """Roundtrip test: ToolResult → to_dict() produces expected keys and values."""
        from z_harness_cli.mcp.server import ToolResult

        result = ToolResult(
            ok=True, status="complete",
            content="z-plan completed successfully.",
            artifacts={"plan": "# Plan\n\n...", "spec": "# Spec\n\n..."},
            meta={"tasks_count": 5, "phase": "complete"},
        )
        d = result.to_dict()

        assert d["ok"] is True
        assert d["status"] == "complete"
        assert d["artifacts"] == {"plan": "# Plan\n\n...", "spec": "# Spec\n\n..."}
        assert d["meta"] == {"tasks_count": 5, "phase": "complete"}
        assert set(d.keys()) == {"ok", "status", "content", "artifacts", "meta"}

    def test_tool_result_factories(self) -> None:
        """Each factory method creates the correct status and ok flag."""
        from z_harness_cli.mcp.server import ToolResult

        r = ToolResult.success("done", {"a": "b"}, {"k": "v"})
        assert r.ok is True and r.status == "complete"
        assert r.artifacts == {"a": "b"} and r.meta == {"k": "v"}

        r2 = ToolResult.success("ok")
        assert r2.artifacts == {} and r2.meta == {}

        r3 = ToolResult.error("something broke")
        assert r3.ok is False and r3.status == "error"

        r4 = ToolResult.blocked("plan collision")
        assert r4.ok is False and r4.status == "blocked"

        r5 = ToolResult.needs_input("Which slug?", "slug_select")
        assert r5.ok is False and r5.status == "needs_input"
        assert r5.meta["question_id"] == "slug_select"

    def test_tool_result_defaults(self) -> None:
        """Default values for artifacts and meta are empty dicts, not shared."""
        from z_harness_cli.mcp.server import ToolResult

        r1 = ToolResult(ok=True, status="complete", content="a")
        r2 = ToolResult(ok=True, status="complete", content="b")
        assert r1.artifacts == {} and r2.artifacts == {}
        r1.artifacts["x"] = "y"
        assert r2.artifacts == {}


# ── Agent loading tests ────────────────────────────────────────────────────


class TestAgentLoading:
    """Tests for _load_agent — parsing agents/*.md with YAML frontmatter."""

    def test_agent_loading_explore(self) -> None:
        """Parse explore.md — should return AgentDef with name, model, tools."""
        from z_harness_cli.mcp.server import _load_agent

        agent = _load_agent("explore")
        assert agent.name == "explore"
        assert agent.model == "deepseek-v4-flash"
        assert "read" in agent.tools
        assert len(agent.prompt_template) > 100

    def test_agent_not_found(self) -> None:
        """Loading a nonexistent agent raises AgentNotFoundError."""
        from z_harness_cli.mcp.server import _load_agent, AgentNotFoundError

        with pytest.raises(AgentNotFoundError, match="nonexistent"):
            _load_agent("nonexistent_agent_xyz")


# ── Error handling tests ───────────────────────────────────────────────────


class TestErrorHandling:
    """Verify all error categories return ToolResult (never throw)."""

    def test_unknown_command(self) -> None:
        """command_not_found → ToolResult.error."""
        from z_harness_cli.mcp.server import _dispatch_command

        r = _dispatch_command("/z-nonexistent-cmd", {})
        assert r.status == "error"
        assert "Unknown" in r.content

    def test_safe_tool_wraps_exceptions(self) -> None:
        """_safe_tool catches all exceptions → ToolResult.error."""
        from z_harness_cli.mcp.server import _safe_tool

        @_safe_tool
        def crashing_handler(x: int) -> None:
            raise RuntimeError("deliberate crash")

        r = crashing_handler(1)
        assert r.status == "error"
        assert "deliberate crash" in r.content

    def test_needs_input_detection(self) -> None:
        """_detect_needs_input identifies AskUserQuestion signals."""
        from z_harness_cli.mcp.server import _detect_needs_input

        assert _detect_needs_input("") is None
        assert _detect_needs_input("normal output") is None

        sig = _detect_needs_input("AskUserQuestion: pick a plan slug")
        assert sig is not None
        assert sig["question_id"] == "ask_user_needs_input"
        assert "pick a plan slug" in sig["content"]


# ── FastMCP Context injection test ─────────────────────────────────────────


class TestFastMCPContextInjection:
    """Verify that `ctx: Context | None = None` works with FastMCP auto-injection."""

    def test_context_none_by_default(self) -> None:
        """When called without a client context, ctx is None."""
        from z_harness_cli.mcp.server import _dispatch_command

        result = _dispatch_command("z_where", {})
        assert result is not None
        assert result.status in ("complete", "error")

    def test_context_accepts_none_explicitly(self) -> None:
        """Calling with progress_callback=None explicitly works (no crash)."""
        from z_harness_cli.mcp.server import _dispatch_command

        result = _dispatch_command("z_where", {}, progress_callback=None)
        assert result is not None

    def test_command_tools_registry_has_entries(self) -> None:
        """COMMAND_TOOLS registry contains the expected 35+ command entries."""
        from z_harness_cli.mcp.server import COMMAND_TOOLS

        assert len(COMMAND_TOOLS) >= 35
        assert COMMAND_TOOLS["z_plan"]["command_id"] == "/z-plan"
        assert COMMAND_TOOLS["z_plan"]["is_heavy"] is True
        assert COMMAND_TOOLS["z_where"]["is_heavy"] is False
        assert COMMAND_TOOLS["z_subagent_dispatch"]["is_heavy"] is True
        for name, entry in COMMAND_TOOLS.items():
            assert "command_id" in entry
            assert "description" in entry
            assert "is_heavy" in entry


# ── Progress phases test ───────────────────────────────────────────────────


class TestProgressPhases:
    """Verify progress phase definitions for heavy commands."""

    def test_progress_phases_for_heavy_commands(self) -> None:
        """Each heavy command with phases has valid definitions."""
        from z_harness_cli.mcp.server import _PROGRESS_PHASES

        assert "z_plan" in _PROGRESS_PHASES
        assert _PROGRESS_PHASES["z_plan"] == ["premise_check", "explore", "decisions", "consult", "writing", "complete"]
        assert "z_implement_all" in _PROGRESS_PHASES
        assert "z_debug" in _PROGRESS_PHASES
        assert _PROGRESS_PHASES["z_debug"] == ["repro", "hypothesis", "evidence", "isolate", "fix", "post_mortem"]


# ── Subagent dispatch test ─────────────────────────────────────────────────


class TestSubagentDispatch:
    """Verify subagent dispatch validation."""

    def test_missing_agent_name(self) -> None:
        """subagent dispatch without agent → error."""
        from z_harness_cli.mcp.server import _handle_subagent_dispatch

        r = _handle_subagent_dispatch({}, None)
        assert r.status == "error"
        assert "agent" in r.content.lower()

    def test_missing_prompt(self) -> None:
        """subagent dispatch without prompt → error."""
        from z_harness_cli.mcp.server import _handle_subagent_dispatch

        r = _handle_subagent_dispatch({"agent": "explore"}, None)
        assert r.status == "error"
        assert "prompt" in r.content.lower()
