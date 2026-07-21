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

from z_harness_cli import release_surface

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

    def test_every_active_prod_tool_has_one_shared_graph_backing(self, monkeypatch) -> None:
        from z_harness_cli.mcp import server

        monkeypatch.setenv("Z_HARNESS_RELEASE_SURFACE", "prod")
        active = server._active_command_tools()
        backings = release_surface.prod_mcp_tool_backings(active)
        assert set(backings) == set(active)
        assert all(value.startswith(("skill:", "handler:")) for value in backings.values())


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

        Round 1: a dispatch that surfaces needs_input (AskUserQuestion signal).
        Round 2: a resume call with {question_id, answer} — the answer is injected
        into the prompt as a continuation block, the re-dispatch returns a clean
        narrative (no AskUserQuestion), and the server yields status="complete".

        Mechanism: re-dispatch-with-answer (not live session resume — the
        dispatcher.run session_id is telemetry-only and drivers do not support
        true subprocess continuation).
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

        # --- Resume call: re-invoke with the question_id + answer ---
        # The server injects the answer into the prompt continuation block and
        # re-dispatches.  The mocked round-2 result carries no AskUserQuestion
        # signal, so the server returns status="complete".
        fake_result_round2 = DispatchResult(
            exit_code=0,
            is_error=False,
            stdout_events=[
                {"type": "text", "content": "Plan created for slug my-feature-slug."},
            ],
            stderr="",
            wall_ms=12.0,
        )

        fake_inner_dispatcher2 = MagicMock()
        fake_inner_dispatcher2.run.return_value = fake_result_round2

        captured_caller_args: list[list[str]] = []

        def _capture_run(**kwargs: object) -> object:
            captured_caller_args.append(list(kwargs.get("caller_args", [])))  # type: ignore[arg-type]
            return fake_result_round2

        fake_inner_dispatcher2.run.side_effect = _capture_run

        with patch("subprocess.run", return_value=fake_proc), \
             patch("runtime.drivers.select_driver") as mock_select2, \
             patch("runtime.dispatch.dispatcher.Dispatcher", return_value=fake_inner_dispatcher2):
            mock_driver2 = MagicMock()
            mock_driver2.init.return_value = None
            mock_select2.return_value = mock_driver2

            dispatcher2 = MCPDispatcher(
                repo_root=Path("/fake/root"),
                tool_name="z_plan",
                args={
                    "prompt": "build a plan",
                    "resume": {"question_id": question_id, "answer": "my-feature-slug"},
                },
                progress_callback=None,
            )
            result2 = dispatcher2.dispatch()

        # Resume path: answer is threaded into caller_args as a continuation block.
        assert captured_caller_args, "dispatcher.run was never called on resume"
        resume_prompt = captured_caller_args[0][0] if captured_caller_args[0] else ""
        assert "my-feature-slug" in resume_prompt, (
            f"Answer not found in continuation prompt: {resume_prompt!r}"
        )
        assert question_id in resume_prompt, (
            f"question_id not found in continuation prompt: {resume_prompt!r}"
        )

        # No AskUserQuestion in round-2 narrative → server returns complete.
        assert result2.status == "complete", (
            f"Expected 'complete' on resume call, got '{result2.status}': {result2.content!r}"
        )


class TestSubagentDispatchIntegration:
    """Verify subagent dispatch validation and agent loading."""

    def test_agent_loading_returns_agentdef(self) -> None:
        """Loading a valid agent returns AgentDef with metadata."""
        agent = _load_agent("auditor")
        assert agent.name == "auditor"
        assert len(agent.tools) >= 3
        assert len(agent.prompt_template) > 50

    def test_subagent_dispatch_missing_agent(self) -> None:
        """Missing agent name → error result."""
        r = _handle_subagent_dispatch({}, None)
        assert r.status == "error"

    def test_subagent_dispatch_missing_prompt(self) -> None:
        """Missing prompt → error result."""
        r = _handle_subagent_dispatch({"agent": "auditor"}, None)
        assert r.status == "error"

    def test_codex_native_subagent_helper_returns_structured_tool_result(self) -> None:
        """Native Codex helper preserves ToolResult content and metadata shape."""
        import types
        from runtime.dispatch.result import DispatchResult
        from z_harness_cli.mcp.server import (
            AgentDef,
            MCPProviderResolution,
            _try_codex_native_subagent_dispatch,
        )

        provider_resolution = MCPProviderResolution(
            role="implementer",
            provider_config={
                "provider": "codex-cli",
                "args_template": ["exec", "-"],
                "model_arg_template": None,
            },
            provider_name="codex-cli",
            host="codex",
        )
        route = types.SimpleNamespace(
            effective_model="gpt-5-codex",
            source="frontmatter",
            route="haiku",
            route_kind="exact",
            thinking="",
            reasoning="",
            effort="",
        )

        class FakeNativeCodexDriver:
            def __init__(self) -> None:
                self.calls: list[dict[str, object]] = []
                self.teardown_calls = 0

            def dispatch_native_subagent(self, **kwargs: object) -> DispatchResult:
                self.calls.append(kwargs)
                return DispatchResult(
                    exit_code=0,
                    is_error=False,
                    stdout_events=[
                        {"type": "text", "content": "native result"},
                        {"type": "artifact", "name": "trace", "content": "ok"},
                    ],
                    stderr="",
                    wall_ms=4.0,
                )

            def teardown(self) -> None:
                self.teardown_calls += 1

        fake_driver = FakeNativeCodexDriver()

        with patch(
            "z_harness_cli.adapters.codex_parity_gate."
            "codex_native_subagent_dispatch_available",
            return_value=True,
        ), \
             patch("z_harness_cli.mcp.server._select_and_init_mcp_driver", return_value=fake_driver), \
             patch("runtime.dispatch.dispatcher.Dispatcher") as runtime_dispatcher:
            result = _try_codex_native_subagent_dispatch(
                repo_root=Path("/fake/root"),
                provider_resolution=provider_resolution,
                agent_def=AgentDef(
                    name="auditor",
                    description="",
                    model="haiku",
                    prompt_template="AGENT TEMPLATE",
                ),
                prompt="review the patch",
                route=route,
                progress_callback=None,
            )

        assert result is not None
        assert result.status == "complete"
        assert result.content == "native result"
        assert result.artifacts == {"trace": "ok"}
        assert result.meta["dispatch_path"] == "codex_native_subagent"
        assert result.meta["provider"] == "codex-cli"
        runtime_dispatcher.assert_not_called()
        assert fake_driver.calls[0]["agent_name"] == "auditor"
        assert fake_driver.calls[0]["prompt"] == "review the patch"
        assert fake_driver.teardown_calls == 1


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
