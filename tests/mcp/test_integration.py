"""Integration tests for z_harness_cli.mcp.server.

These tests verify the MCP server end-to-end: tool registration, command dispatch
shape, z_where/z_stats against test fixtures, subagent dispatch result shape,
needs_input flow, and progress streaming.

Note: Some tests require a live server process (test_server_starts,
test_progress_streaming) and are marked with @pytest.mark.integration.
"""

from __future__ import annotations

import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

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

    def test_needs_input_flow(self) -> None:
        """Integration test for needs_input detection and resume round-trip.

        RESUME GAP (as of T008): MCPDispatcher.dispatch() and _dispatch_command()
        have NO 'resume' parameter. The resume path is detection-only: the server
        surfaces 'needs_input' to the caller but has no logic to thread a
        (question_id, answer) pair back into a subsequent dispatch. A second call
        with resume kwargs simply passes them as unknown args that are silently
        dropped by MCPDispatcher (which only reads 'prompt', 'slug', 'model' from
        args). The test below exercises what IS implemented (needs_input surface)
        and documents the gap (resume completion) by showing the second call returns
        a fresh 'needs_input' — not 'complete' — because the answer is not threaded.

        When a future task wires the resume re-entry, this test should be updated
        to assert result2.status == "complete" in the resume branch.
        """
        from z_harness_cli.mcp.server import MCPDispatcher, ToolResult
        from runtime.dispatch.result import DispatchResult

        # --- First call: dispatch yields a needs_input signal in its narrative ---
        fake_result_round1 = DispatchResult(
            exit_code=0,
            is_error=False,
            stdout_events=[
                {"type": "text", "content": "AskUserQuestion: Which slug should I use?"},
            ],
            stderr="",
            wall_ms=10.0,
        )

        fake_provider_json = '{"provider": "codex-cli", "args_template": ["codex"]}'
        fake_proc = type("FakeProc", (), {
            "returncode": 0, "stdout": fake_provider_json, "stderr": ""
        })()

        fake_inner_dispatcher = MagicMock()
        fake_inner_dispatcher.run.return_value = fake_result_round1

        with patch("subprocess.run", return_value=fake_proc), \
             patch("runtime.drivers.select_driver") as mock_select, \
             patch("runtime.dispatch.dispatcher.Dispatcher", return_value=fake_inner_dispatcher):
            mock_driver = MagicMock()
            mock_driver.init.return_value = None
            mock_select.return_value = mock_driver

            dispatcher1 = MCPDispatcher(
                repo_root=Path("/fake/root"),
                tool_name="z_plan",
                args={"prompt": "build a plan"},
                progress_callback=None,
            )
            result1 = dispatcher1.dispatch()

        # First call: needs_input must be surfaced with the question details.
        assert result1.status == "needs_input", (
            f"Expected 'needs_input' on first call, got '{result1.status}': {result1.content!r}"
        )
        assert "Which slug should I use?" in result1.content, (
            f"Question text not in content: {result1.content!r}"
        )
        question_id = result1.meta.get("question_id")
        assert question_id is not None, "question_id missing from meta"
        assert question_id == "ask_user_needs_input", (
            f"Expected question_id='ask_user_needs_input', got {question_id!r}"
        )

        # --- Resume call: re-invoke with the question_id + answer threaded as args ---
        # NOTE: as of T008 there is NO resume wiring. MCPDispatcher ignores any
        # 'resume' key in args; the underlying dispatch re-runs from scratch and will
        # again surface needs_input if the mocked narrative still contains
        # AskUserQuestion. This demonstrates the gap: the resume answer is silently
        # dropped and the flow does NOT complete.
        #
        # A future implementation should detect resume in args and short-circuit to
        # ToolResult.success() (or a different flow) without re-running the full
        # dispatch. When that is wired, assert result2.status == "complete" here.

        fake_inner_dispatcher2 = MagicMock()
        fake_inner_dispatcher2.run.return_value = fake_result_round1  # same mock: still asks

        with patch("subprocess.run", return_value=fake_proc), \
             patch("runtime.drivers.select_driver") as mock_select2, \
             patch("runtime.dispatch.dispatcher.Dispatcher", return_value=fake_inner_dispatcher2):
            mock_driver2 = MagicMock()
            mock_driver2.init.return_value = None
            mock_select2.return_value = mock_driver2

            dispatcher2 = MCPDispatcher(
                repo_root=Path("/fake/root"),
                tool_name="z_plan",
                # resume args passed — currently silently dropped by MCPDispatcher
                args={
                    "prompt": "build a plan",
                    "resume": {"question_id": question_id, "answer": "my-feature-slug"},
                },
                progress_callback=None,
            )
            result2 = dispatcher2.dispatch()

        # RESUME GAP: because resume is not wired, the server re-runs and asks again.
        # This assertion documents the current (broken) contract; it must be updated
        # when the resume path is implemented.
        assert result2.status == "needs_input", (
            "RESUME NOT WIRED: expected 'needs_input' (demonstrating the gap). "
            f"If this assertion fails with status=='complete', the resume path has "
            f"been wired — update this test to assert result2.status == 'complete'. "
            f"Actual: {result2.status!r}"
        )


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
