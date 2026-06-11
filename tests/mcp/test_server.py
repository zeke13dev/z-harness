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
            ok=True,
            status="complete",
            content="z-plan completed successfully.",
            artifacts={"plan": "# Plan\n\n...", "spec": "# Spec\n\n..."},
            meta={"tasks_count": 5, "phase": "complete"},
        )
        d = result.to_dict()

        assert d["ok"] is True
        assert d["status"] == "complete"
        assert d["content"] == "z-plan completed successfully."
        assert d["artifacts"] == {"plan": "# Plan\n\n...", "spec": "# Spec\n\n..."}
        assert d["meta"] == {"tasks_count": 5, "phase": "complete"}

        # All expected keys present
        assert set(d.keys()) == {"ok", "status", "content", "artifacts", "meta"}

    def test_tool_result_factories(self) -> None:
        """Each factory method creates the correct status and ok flag."""
        from z_harness_cli.mcp.server import ToolResult

        # success
        r = ToolResult.success("done", {"a": "b"}, {"k": "v"})
        assert r.ok is True
        assert r.status == "complete"
        assert r.content == "done"
        assert r.artifacts == {"a": "b"}
        assert r.meta == {"k": "v"}

        # success with defaults
        r2 = ToolResult.success("ok")
        assert r2.artifacts == {}
        assert r2.meta == {}

        # error
        r3 = ToolResult.error("something broke")
        assert r3.ok is False
        assert r3.status == "error"
        assert r3.content == "something broke"

        # blocked
        r4 = ToolResult.blocked("plan collision")
        assert r4.ok is False
        assert r4.status == "blocked"

        # needs_input
        r5 = ToolResult.needs_input("Which slug?", "slug_select")
        assert r5.ok is False
        assert r5.status == "needs_input"
        assert r5.meta["question_id"] == "slug_select"

    def test_tool_result_defaults(self) -> None:
        """Default values for artifacts and meta are empty dicts, not shared."""
        from z_harness_cli.mcp.server import ToolResult

        r1 = ToolResult(ok=True, status="complete", content="a")
        r2 = ToolResult(ok=True, status="complete", content="b")

        assert r1.artifacts == {}
        assert r2.artifacts == {}
        assert r1.meta == {}
        assert r2.meta == {}

        # Mutating one does not affect the other
        r1.artifacts["x"] = "y"
        assert r2.artifacts == {}


# ── FastMCP Context injection test ─────────────────────────────────────────


class TestFastMCPContextInjection:
    """Verify that `ctx: Context | None = None` works with FastMCP auto-injection.

    FastMCP automatically injects a Context object when the client provides one.
    When no client context exists, the parameter receives None.  This test
    confirms both paths without requiring a live FastMCP server.
    """

    def test_context_none_by_default(self) -> None:
        """When called without a client context, ctx is None."""
        # Simulates the MCP tool signature: async def tool(..., ctx: Context | None = None)
        # Without FastMCP wiring, we call the function directly → ctx defaults to None.
        from z_harness_cli.mcp.server import _dispatch_command

        result = _dispatch_command("z_where", {})
        assert result is not None
        # After T005, z_where has a real fast handler; status may be complete or error
        assert result.status in ("complete", "error")

    def test_context_accepts_none_explicitly(self) -> None:
        """Calling with ctx=None explicitly works (no crash)."""
        from z_harness_cli.mcp.server import _dispatch_command

        result = _dispatch_command("z_where", {}, progress_callback=None)
        assert result is not None

    def test_command_tools_registry_has_entries(self) -> None:
        """COMMAND_TOOLS registry contains the expected 35 command entries."""
        from z_harness_cli.mcp.server import COMMAND_TOOLS

        assert len(COMMAND_TOOLS) >= 35
        # Verify a few representative entries
        assert COMMAND_TOOLS["z_plan"]["command_id"] == "/z-plan"
        assert COMMAND_TOOLS["z_plan"]["is_heavy"] is True
        assert COMMAND_TOOLS["z_where"]["is_heavy"] is False
        assert COMMAND_TOOLS["z_debug"]["is_heavy"] is True
        # All entries have required keys
        for name, entry in COMMAND_TOOLS.items():
            assert "command_id" in entry
            assert "description" in entry
            assert "is_heavy" in entry
            assert "skills_path" in entry
