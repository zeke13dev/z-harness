"""Integration tests for z_harness_cli.mcp.server.

These tests verify the MCP server end-to-end: tool registration, command dispatch
shape, z_where/z_stats against test fixtures, subagent dispatch result shape,
needs_input flow, and progress streaming.

Note: Some tests require a live server process (test_server_starts,
test_progress_streaming) and are marked with @pytest.mark.integration.
"""

from __future__ import annotations

import pytest

from z_harness_cli.mcp.server import (
    COMMAND_TOOLS,
    _FAST_HANDLERS,
    _detect_needs_input,
    _dispatch_command,
    _handle_subagent_dispatch,
    _handle_z_detect,
    _handle_z_export,
    _handle_z_where,
    _load_agent,
    _safe_tool,
)


class TestServerRegistration:
    """Verify all tools are registered and discoverable."""

    def test_all_heavy_commands_registered(self) -> None:
        """Every command in _PROGRESS_PHASES is also in COMMAND_TOOLS."""
        from z_harness_cli.mcp.server import _PROGRESS_PHASES
        for name in _PROGRESS_PHASES:
            assert name in COMMAND_TOOLS, f"{name} missing from COMMAND_TOOLS"
            assert COMMAND_TOOLS[name]["is_heavy"], f"{name} should be heavy"

    def test_all_fast_handlers_registered(self) -> None:
        """Every handler in _FAST_HANDLERS is also in COMMAND_TOOLS."""
        for name in _FAST_HANDLERS:
            assert name in COMMAND_TOOLS, f"{name} missing from COMMAND_TOOLS"

    def test_subagent_dispatch_registered(self) -> None:
        """z_subagent_dispatch is in COMMAND_TOOLS and marked heavy."""
        assert "z_subagent_dispatch" in COMMAND_TOOLS
        assert COMMAND_TOOLS["z_subagent_dispatch"]["is_heavy"]


class TestZWhere:
    """Test z_where returns plan list format."""

    def test_z_where_returns_result(self) -> None:
        """z_where returns a ToolResult with expected shape."""
        r = _handle_z_where({})
        assert r.status in ("complete", "error")
        assert isinstance(r.to_dict(), dict)

    def test_z_where_meta_has_plans_dir(self) -> None:
        """z_where meta includes plans_dir."""
        r = _handle_z_where({})
        assert "plans_dir" in r.meta


class TestZDetect:
    """Test z_detect returns host detection format."""

    def test_z_detect_returns_result(self) -> None:
        """z_detect returns a ToolResult with hosts list in meta (or graceful error)."""
        r = _handle_z_detect({})
        assert r.status in ("complete", "error")
        if r.status == "complete":
            assert "hosts" in r.meta


class TestNeedsInputFlow:
    """Verify needs_input detection and tool behavior."""

    def test_needs_input_returns_structured_result(self) -> None:
        """ToolResult.needs_input produces the correct status and question_id."""
        from z_harness_cli.mcp.server import ToolResult

        r = ToolResult.needs_input("Which plan?", "slug_picker")
        d = r.to_dict()
        assert d["status"] == "needs_input"
        assert d["meta"]["question_id"] == "slug_picker"

    def test_ask_user_question_detected(self) -> None:
        """AskUserQuestion: marker in output triggers needs_input."""
        sig = _detect_needs_input("AskUserQuestion: choose a slug please")
        assert sig is not None
        assert "choose a slug" in sig["content"]
        assert sig["question_id"] == "ask_user_needs_input"

    def test_normal_output_not_misidentified(self) -> None:
        """Normal output without AskUserQuestion is not misidentified."""
        assert _detect_needs_input("Task completed successfully.") is None
        assert _detect_needs_input("Error: file not found") is None


class TestSubagentDispatchIntegration:
    """Verify subagent dispatch validation and agent loading."""

    def test_agent_loading_returns_agentdef(self) -> None:
        """Loading a valid agent returns AgentDef with metadata."""
        agent = _load_agent("explore")
        assert agent.name == "explore"
        assert len(agent.tools) >= 3
        assert len(agent.prompt_template) > 50

    def test_subagent_dispatch_missing_agent(self) -> None:
        """Missing agent name → error result."""
        r = _handle_subagent_dispatch({}, None)
        assert r.status == "error"

    def test_subagent_dispatch_missing_prompt(self) -> None:
        """Missing prompt → error result."""
        r = _handle_subagent_dispatch({"agent": "explore"}, None)
        assert r.status == "error"


class TestSafeToolWrapper:
    """Verify _safe_tool catches exceptions on all handler types."""

    def test_safe_tool_on_fast_handler(self) -> None:
        """_safe_tool wraps a function that returns ToolResult correctly."""
        wrapped = _safe_tool(_handle_z_where)
        r = wrapped({})
        assert r.status in ("complete", "error")

    def test_safe_tool_prevents_crash(self) -> None:
        """A function that raises returns ToolResult.error, never throws."""

        @_safe_tool
        def bad_handler(args: dict) -> None:
            raise ValueError("test explosion")

        r = bad_handler({})
        assert r.status == "error"
        assert "test explosion" in r.content
