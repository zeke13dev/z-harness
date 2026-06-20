"""Unit tests for z_harness_cli.mcp.server — ToolResult, agent loading, error handling, FastMCP Context injection."""

from __future__ import annotations

import os
import subprocess
import types
from unittest.mock import patch

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
        """Parse auditor.md — should return AgentDef with name, model, tools."""
        from z_harness_cli.mcp.server import _load_agent

        agent = _load_agent("auditor")
        assert agent.name == "auditor"
        assert agent.model == "sonnet"
        assert "Read" in agent.tools
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

        r = _handle_subagent_dispatch({"agent": "auditor"}, None)
        assert r.status == "error"
        assert "prompt" in r.content.lower()


# ── Consult-off bypass tests ───────────────────────────────────────────────


class TestConsultOffBypass:
    """Verify Z_HARNESS_CONSULT=off sentinel → status='skipped', not 'error'."""

    def _make_proc(self, stdout: str, returncode: int = 0) -> subprocess.CompletedProcess:
        """Build a fake CompletedProcess with the given stdout."""
        return subprocess.CompletedProcess(
            args=[], returncode=returncode, stdout=stdout, stderr=""
        )

    def test_skipped_factory(self) -> None:
        """ToolResult.skipped() returns ok=False, status='skipped'."""
        from z_harness_cli.mcp.server import ToolResult

        r = ToolResult.skipped("Consulting disabled")
        assert r.ok is False
        assert r.status == "skipped"
        assert "Consulting disabled" in r.content

    def test_dispatch_returns_skipped_on_none_sentinel(self) -> None:
        """When resolve-provider prints bare 'none', dispatch → status='skipped'."""
        from z_harness_cli.mcp.server import MCPDispatcher
        from pathlib import Path

        fake_proc = self._make_proc("none\n", returncode=0)

        with patch("subprocess.run", return_value=fake_proc):
            dispatcher = MCPDispatcher(
                repo_root=Path("/fake/root"),
                tool_name="z_review_all",
                args={"prompt": "review"},
                progress_callback=None,
            )
            result = dispatcher.dispatch()

        assert result.status == "skipped", (
            f"Expected 'skipped' but got '{result.status}': {result.content}"
        )
        assert result.ok is False
        assert "z_review_all" in result.content

    def test_dispatch_returns_skipped_on_none_sentinel_no_newline(self) -> None:
        """Sentinel without trailing newline also triggers skipped."""
        from z_harness_cli.mcp.server import MCPDispatcher
        from pathlib import Path

        fake_proc = self._make_proc("none", returncode=0)

        with patch("subprocess.run", return_value=fake_proc):
            dispatcher = MCPDispatcher(
                repo_root=Path("/fake/root"),
                tool_name="z_audit",
                args={"prompt": "audit"},
                progress_callback=None,
            )
            result = dispatcher.dispatch()

        assert result.status == "skipped"

    def test_dispatch_returns_error_on_genuine_failure(self) -> None:
        """A non-zero returncode from resolve-provider → status='error', not 'skipped'."""
        from z_harness_cli.mcp.server import MCPDispatcher
        from pathlib import Path

        fake_proc = self._make_proc("", returncode=1)

        with patch("subprocess.run", return_value=fake_proc):
            dispatcher = MCPDispatcher(
                repo_root=Path("/fake/root"),
                tool_name="z_review_all",
                args={"prompt": "review"},
                progress_callback=None,
            )
            result = dispatcher.dispatch()

        assert result.status == "error"
        assert result.status != "skipped"


# ── Z_HARNESS_SLUG leak prevention tests (T-REV-003) ──────────────────────


class TestSlugEnvRestore:
    """Verify Z_HARNESS_SLUG is restored after dispatch, preventing cross-call leakage."""

    def _make_skipped_proc(self) -> subprocess.CompletedProcess:
        """Build a fake CompletedProcess that returns the skipped sentinel."""
        return subprocess.CompletedProcess(
            args=[], returncode=0, stdout="none\n", stderr=""
        )

    def test_slug_restored_when_previously_unset(self) -> None:
        """After dispatch with a slug, Z_HARNESS_SLUG is unset if it was unset before."""
        from z_harness_cli.mcp.server import MCPDispatcher
        from pathlib import Path

        # Ensure Z_HARNESS_SLUG is not set before the call.
        os.environ.pop("Z_HARNESS_SLUG", None)

        with patch("subprocess.run", return_value=self._make_skipped_proc()):
            dispatcher = MCPDispatcher(
                repo_root=Path("/fake/root"),
                tool_name="z_review_all",
                args={"prompt": "review", "slug": "my-test-slug"},
                progress_callback=None,
            )
            dispatcher.dispatch()

        assert "Z_HARNESS_SLUG" not in os.environ, (
            f"Z_HARNESS_SLUG leaked after dispatch: {os.environ.get('Z_HARNESS_SLUG')!r}"
        )

    def test_slug_restored_to_prior_sentinel_value(self) -> None:
        """After dispatch with a slug, Z_HARNESS_SLUG is restored to its pre-call value."""
        from z_harness_cli.mcp.server import MCPDispatcher
        from pathlib import Path

        sentinel = "prior-sentinel-slug"
        os.environ["Z_HARNESS_SLUG"] = sentinel

        try:
            with patch("subprocess.run", return_value=self._make_skipped_proc()):
                dispatcher = MCPDispatcher(
                    repo_root=Path("/fake/root"),
                    tool_name="z_review_all",
                    args={"prompt": "review", "slug": "dispatch-slug"},
                    progress_callback=None,
                )
                dispatcher.dispatch()

            assert os.environ.get("Z_HARNESS_SLUG") == sentinel, (
                f"Expected sentinel {sentinel!r}, got {os.environ.get('Z_HARNESS_SLUG')!r}"
            )
        finally:
            os.environ.pop("Z_HARNESS_SLUG", None)

    def test_slug_restored_even_on_dispatch_error(self) -> None:
        """Z_HARNESS_SLUG is restored even when the dispatch raises an exception."""
        import unittest.mock as mock
        from z_harness_cli.mcp.server import MCPDispatcher
        from pathlib import Path

        os.environ.pop("Z_HARNESS_SLUG", None)

        # Simulate an exception during provider resolution.
        with patch("subprocess.run", side_effect=RuntimeError("simulated failure")):
            dispatcher = MCPDispatcher(
                repo_root=Path("/fake/root"),
                tool_name="z_plan",
                args={"prompt": "plan", "slug": "error-slug"},
                progress_callback=None,
            )
            result = dispatcher.dispatch()

        # Even though dispatch failed, slug must be cleaned up.
        assert "Z_HARNESS_SLUG" not in os.environ, (
            f"Z_HARNESS_SLUG leaked after failed dispatch: {os.environ.get('Z_HARNESS_SLUG')!r}"
        )
        # And the result should be an error, not a crash.
        assert result.status in ("error", "skipped")


# ── Narrative extraction tests (T-REV-002) ─────────────────────────────────


class TestExtractNarrative:
    """Verify _extract_narrative reads from type=='text' stdout_events, not stderr."""

    def test_extracts_text_events(self) -> None:
        """Content from type=='text' events is joined and returned."""
        from z_harness_cli.mcp.server import _extract_narrative

        events = [
            {"type": "text", "content": "First paragraph."},
            {"type": "artifact", "name": "plan", "content": "# Plan"},
            {"type": "text", "content": "Second paragraph."},
        ]
        result = _extract_narrative(events)
        assert result == "First paragraph.\nSecond paragraph."

    def test_empty_on_no_text_events(self) -> None:
        """Returns empty string when no type=='text' events are present."""
        from z_harness_cli.mcp.server import _extract_narrative

        events = [
            {"type": "artifact", "name": "plan", "content": "# Plan"},
            {"type": "done", "exit_code": 0},
        ]
        assert _extract_narrative(events) == ""

    def test_empty_on_empty_events(self) -> None:
        """Returns empty string for an empty event list."""
        from z_harness_cli.mcp.server import _extract_narrative

        assert _extract_narrative([]) == ""

    def test_skips_empty_content(self) -> None:
        """Text events with empty or missing content field are skipped."""
        from z_harness_cli.mcp.server import _extract_narrative

        events = [
            {"type": "text", "content": ""},
            {"type": "text"},
            {"type": "text", "content": "Real content."},
        ]
        assert _extract_narrative(events) == "Real content."

    def test_mcp_dispatcher_content_comes_from_stdout_events_not_stderr(self) -> None:
        """ToolResult.content is sourced from type=='text' stdout_events, not stderr.

        Invariant (SPEC §93): ToolResult.content holds the command's natural-language
        output. This test asserts that when stdout_events carry type=='text' events,
        their content populates ToolResult.content — and that stderr text (OS-level
        diagnostic messages) is NOT used as content when narrative is available.

        A violation means the MCP tool surface exposes CLI warnings to the caller
        instead of the command's actual output.
        """
        from z_harness_cli.mcp.server import MCPDispatcher
        from pathlib import Path
        from unittest.mock import patch, MagicMock
        from runtime.dispatch.result import DispatchResult

        # Build a DispatchResult where:
        # - stdout_events has a type=='text' event (the real narrative)
        # - stderr has a CLI diagnostic message (must NOT become content)
        fake_result = DispatchResult(
            exit_code=0,
            is_error=False,
            stdout_events=[
                {"type": "text", "content": "Plan generated successfully."},
                {"type": "artifact", "name": "PLAN", "content": "# Plan\n..."},
            ],
            stderr="WARNING: some internal CLI diagnostic",
            wall_ms=42.0,
        )

        fake_provider_json = '{"provider": "codex-cli", "args_template": ["codex"]}'
        fake_proc = type("FakeProc", (), {
            "returncode": 0, "stdout": fake_provider_json, "stderr": ""
        })()

        fake_dispatcher = MagicMock()
        fake_dispatcher.run.return_value = fake_result

        with patch("subprocess.run", return_value=fake_proc), \
             patch("runtime.drivers.select_driver") as mock_select, \
             patch("runtime.dispatch.dispatcher.Dispatcher", return_value=fake_dispatcher):
            mock_driver = MagicMock()
            mock_driver.init.return_value = None
            mock_select.return_value = mock_driver

            dispatcher = MCPDispatcher(
                repo_root=Path("/fake/root"),
                tool_name="z_plan",
                args={"prompt": "build a plan"},
                progress_callback=None,
            )
            result = dispatcher.dispatch()

        assert result.status == "complete", f"Expected complete, got {result.status}: {result.content}"
        # The narrative from type=='text' event must be the content
        assert "Plan generated successfully." in result.content, (
            f"Expected narrative from stdout_events in content, got: {result.content!r}"
        )
        # The CLI diagnostic from stderr must NOT be the content source
        assert "WARNING: some internal CLI diagnostic" not in result.content, (
            f"stderr diagnostic leaked into content: {result.content!r}"
        )
        # Artifacts must still be extracted from stdout_events
        assert "PLAN" in result.artifacts, f"Artifact not extracted: {result.artifacts}"
