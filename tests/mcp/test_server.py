"""Unit tests for z_harness_cli.mcp.server — ToolResult, agent loading, error handling, FastMCP Context injection."""

from __future__ import annotations

import json
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
        assert COMMAND_TOOLS["z_resume"]["command_id"] == "/z-resume"
        assert COMMAND_TOOLS["z_resume"]["is_heavy"] is False
        assert COMMAND_TOOLS["z_subagent_dispatch"]["is_heavy"] is True
        for name, entry in COMMAND_TOOLS.items():
            assert "command_id" in entry
            assert "description" in entry
            assert "is_heavy" in entry

    def test_prod_discovery_and_dispatch_reject_removed_tools(self, monkeypatch) -> None:
        from z_harness_cli.mcp import server

        monkeypatch.setenv("Z_HARNESS_RELEASE_SURFACE", "prod")
        active = server._active_command_tools()
        for name in ("z_do", "z_evaluate", "z_uplift"):
            assert name not in active
            result = server._dispatch_command(name, {})
            assert result.status == "error"
            assert result.content == f"Unknown command: {name}"


    def test_z_resume_uses_fast_handler_registration(self) -> None:
        """z_resume must bypass heavy command dispatch and use the deterministic fast handler."""
        from z_harness_cli.mcp.server import _FAST_HANDLERS, _handle_z_resume

        assert _FAST_HANDLERS["z_resume"] is _handle_z_resume



# ── z-resume fast handler tests ─────────────────────────────────────────────


class TestZResumeFastHandler:
    """Verify /z-resume uses deterministic resume-context JSON, not skill dispatch."""

    def _make_proc(self, packet: dict[str, object]) -> subprocess.CompletedProcess:
        return subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout=json.dumps(packet),
            stderr="",
        )

    def test_ambiguous_prompt_returns_noninteractive_packet(self, tmp_path) -> None:
        from z_harness_cli.mcp.server import _dispatch_command

        packet = {
            "status": "needs_selection",
            "interaction_mode": "noninteractive",
            "ambiguity": {"needs_selection": True, "state": "ambiguous"},
            "selected_target": None,
            "suggested_selection_args": ["--select candidate:cand-1"],
            "safe_next_command": {"kind": "select_target"},
        }


        target_repo = tmp_path / "target-repo"
        target_repo.mkdir()
        with patch("subprocess.run", return_value=self._make_proc(packet)) as run, \
             patch("z_harness_cli.mcp.server._handle_skill_dispatch") as skill_dispatch:
            result = _dispatch_command("z_resume", {"prompt": "resume parser work", "repo_root": str(target_repo)})

        assert result.status == "complete"
        assert result.meta["needs_selection"] is True
        assert result.meta["selected_target"] is None
        assert result.meta["packet"]["status"] == "needs_selection"
        assert "resume_context" in result.artifacts
        skill_dispatch.assert_not_called()
        argv = run.call_args.args[0]
        assert argv[-3:] == ["--format", "json", "--noninteractive"]
        assert "--arguments" in argv
        assert argv[argv.index("--arguments") + 1] == "resume parser work"
        assert "--repo-root" in argv
        assert run.call_args.kwargs["cwd"] == argv[argv.index("--repo-root") + 1]
        assert argv[argv.index("--repo-root") + 1] == str(target_repo)

    def test_missing_explicit_caller_repo_root_does_not_use_process_cwd(self, tmp_path) -> None:
        from z_harness_cli.mcp.server import _dispatch_command

        helper_root = tmp_path / "helper-root"
        process_cwd = tmp_path / "process-cwd"
        helper_root.mkdir()
        process_cwd.mkdir()

        with patch.dict(
            os.environ,
            {"PWD": str(process_cwd), "Z_HARNESS_TARGET_REPO_ROOT": ""},
            clear=False,
        ), \
             patch("z_harness_cli.mcp.server._get_repo_root", return_value=helper_root), \
             patch("os.getcwd", return_value=str(process_cwd)), \
             patch("subprocess.run") as run:
            result = _dispatch_command("z_resume", {"prompt": "resume parser work"})

        assert result.status == "error"
        assert "explicit caller workspace root" in result.content
        assert "helper process cwd" in result.content
        run.assert_not_called()

    def test_exact_slug_control_selects_target(self, tmp_path) -> None:
        from z_harness_cli.mcp.server import _dispatch_command

        selected = {
            "target_type": "plan",
            "slug": "z-resume",
            "selection_token": "candidate:cand-1|slug:z-resume",
        }
        packet = {
            "status": "selected",
            "interaction_mode": "noninteractive",
            "ambiguity": {"needs_selection": False, "state": "none"},
            "selected_target": selected,
            "suggested_selection_args": [],
            "safe_next_command": {"kind": "continue_plan"},
        }

        target_repo = tmp_path / "target-repo"
        target_repo.mkdir()

        with patch("subprocess.run", return_value=self._make_proc(packet)) as run:
            result = _dispatch_command("z_resume", {"prompt": "", "slug": "z-resume", "cwd": str(target_repo)})

        assert result.status == "complete"
        assert result.meta["needs_selection"] is False
        assert result.meta["selected_target"] == selected
        argv = run.call_args.args[0]
        assert "--slug" in argv
        assert argv[argv.index("--slug") + 1] == "z-resume"
        assert "--arguments" not in argv

    def test_fast_handler_does_not_mutate_caller_args(self, tmp_path) -> None:
        from z_harness_cli.mcp.server import _dispatch_command

        packet = {
            "status": "selected",
            "interaction_mode": "noninteractive",
            "ambiguity": {"needs_selection": False, "state": "none"},
            "selected_target": {"target_type": "plan", "slug": "z-resume"},
            "suggested_selection_args": [],
            "safe_next_command": {"kind": "continue_plan"},
        }
        target_repo = tmp_path / "target-repo"
        target_repo.mkdir()
        args = {"prompt": "resume parser work", "slug": "z-resume", "repo_root": str(target_repo)}
        before = dict(args)

        with patch("subprocess.run", return_value=self._make_proc(packet)):
            result = _dispatch_command("z_resume", args)

        assert result.status == "complete"
        assert args == before

# ── Progress phases test ───────────────────────────────────────────────────


class TestProgressPhases:
    """Verify progress phase definitions for heavy commands."""

    def test_progress_phases_for_heavy_commands(self) -> None:
        """Each heavy command with phases has valid definitions."""
        from z_harness_cli.mcp.server import _PROGRESS_PHASES

        assert "z_plan" in _PROGRESS_PHASES
        assert _PROGRESS_PHASES["z_plan"] == ["premise_check", "explore", "decisions", "consult", "writing", "complete"]
        assert "z_execute" in _PROGRESS_PHASES
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

    def test_provider_resolution_preserves_role_and_reviewer_fallback(self) -> None:
        """Reusable provider resolution keeps command role mapping and reviewer fallback."""
        from pathlib import Path
        from z_harness_cli.mcp.server import MCPProviderResolution, _resolve_mcp_provider

        failing_proc = subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="")
        provider = {
            "provider": "codex-cli",
            "args_template": ["exec", "-"],
            "model_arg_template": None,
        }
        success_proc = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout=json.dumps(provider),
            stderr="",
        )

        with patch("subprocess.run", side_effect=[failing_proc, success_proc]) as run:
            result = _resolve_mcp_provider(Path("/fake/root"), "z_plan")

        assert isinstance(result, MCPProviderResolution)
        assert result.role == "implementer"
        assert result.provider_name == "codex-cli"
        assert result.host == "codex"
        assert run.call_args_list[0].args[0][-1] == "implementer"
        assert run.call_args_list[1].args[0][-1] == "reviewer"

    def test_provider_resolution_skips_provider_none_payload(self) -> None:
        """provider='none' JSON keeps consult-off behavior as skipped, not error."""
        from pathlib import Path
        from z_harness_cli.mcp.server import ToolResult, _resolve_mcp_provider

        fake_proc = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout=json.dumps({"provider": "none"}),
            stderr="",
        )

        with patch("subprocess.run", return_value=fake_proc):
            result = _resolve_mcp_provider(Path("/fake/root"), "z_review_all")

        assert isinstance(result, ToolResult)
        assert result.status == "skipped"

    def test_subagent_dispatch_falls_back_when_codex_native_gate_is_closed(self) -> None:
        """Codex provider without primitive evidence uses the generic MCP dispatcher."""
        from pathlib import Path
        from z_harness_cli.mcp.server import (
            AgentDef,
            MCPDispatcher,
            MCPProviderResolution,
            ToolResult,
            _handle_subagent_dispatch,
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

        with patch("z_harness_cli.mcp.server._get_repo_root", return_value=Path("/fake/root")), \
             patch(
                 "z_harness_cli.mcp.server._load_agent",
                 return_value=AgentDef(
                     name="auditor",
                     description="",
                     model="haiku",
                     prompt_template="AGENT TEMPLATE",
                 ),
             ), \
             patch("runtime.dispatch.dispatcher.load_model_routing_config", return_value={}), \
             patch("runtime.dispatch.dispatcher.resolve_native_agent_model", return_value=route), \
             patch("z_harness_cli.mcp.server._resolve_mcp_provider", return_value=provider_resolution), \
             patch(
                 "z_harness_cli.adapters.codex_parity_gate."
                 "codex_native_subagent_dispatch_available",
                 return_value=False,
             ), \
             patch.object(
                 MCPDispatcher,
                 "dispatch",
                 return_value=ToolResult.success("generic path"),
             ) as generic_dispatch:
            result = _handle_subagent_dispatch({"agent": "auditor", "prompt": "check it"}, None)

        assert result.status == "complete"
        generic_dispatch.assert_called_once()
        assert generic_dispatch.call_args.kwargs["provider_resolution"] is provider_resolution

    def test_subagent_dispatch_uses_codex_native_branch_when_proven(self) -> None:
        """Primitive evidence plus a driver hook dispatches via Codex-native branch."""
        from pathlib import Path
        from runtime.dispatch.result import DispatchResult
        from z_harness_cli.mcp.server import (
            AgentDef,
            MCPDispatcher,
            MCPProviderResolution,
            _handle_subagent_dispatch,
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
        fake_result = DispatchResult(
            exit_code=0,
            is_error=False,
            stdout_events=[{"type": "text", "content": "native complete"}],
            stderr="",
            wall_ms=7.0,
        )

        class FakeNativeCodexDriver:
            def __init__(self) -> None:
                self.calls: list[dict[str, object]] = []
                self.teardown_calls = 0

            def dispatch_native_subagent(self, **kwargs: object) -> DispatchResult:
                self.calls.append(kwargs)
                return fake_result

            def teardown(self) -> None:
                self.teardown_calls += 1

        fake_driver = FakeNativeCodexDriver()
        prior_slug = "prior-native-slug"
        os.environ["Z_HARNESS_SLUG"] = prior_slug

        restored_slug = None
        try:
            with patch("z_harness_cli.mcp.server._get_repo_root", return_value=Path("/fake/root")), \
                 patch(
                     "z_harness_cli.mcp.server._load_agent",
                     return_value=AgentDef(
                         name="auditor",
                         description="",
                         model="haiku",
                         prompt_template="AGENT TEMPLATE",
                     ),
                 ), \
                 patch("runtime.dispatch.dispatcher.load_model_routing_config", return_value={}), \
                 patch("runtime.dispatch.dispatcher.resolve_native_agent_model", return_value=route), \
                 patch("z_harness_cli.mcp.server._resolve_mcp_provider", return_value=provider_resolution), \
                 patch(
                     "z_harness_cli.adapters.codex_parity_gate."
                     "codex_native_subagent_dispatch_available",
                     return_value=True,
                 ), \
                 patch("z_harness_cli.mcp.server._select_and_init_mcp_driver", return_value=fake_driver), \
                 patch("runtime.dispatch.dispatcher.Dispatcher") as runtime_dispatcher, \
                 patch.object(MCPDispatcher, "dispatch") as generic_dispatch:
                result = _handle_subagent_dispatch(
                    {"agent": "auditor", "prompt": "check it", "slug": "native-call-slug"},
                    None,
                )
        finally:
            restored_slug = os.environ.get("Z_HARNESS_SLUG")
            os.environ.pop("Z_HARNESS_SLUG", None)

        assert restored_slug == prior_slug
        assert result.status == "complete"
        assert result.content == "native complete"
        assert result.meta["dispatch_path"] == "codex_native_subagent"
        assert result.meta["agent"] == "auditor"
        generic_dispatch.assert_not_called()
        runtime_dispatcher.assert_not_called()
        assert fake_driver.calls
        native_call = fake_driver.calls[0]
        assert native_call["agent_name"] == "auditor"
        assert native_call["prompt"] == "check it"
        assert "AGENT TEMPLATE" not in str(native_call["prompt"])
        assert native_call["model"] == "gpt-5-codex"
        assert native_call["env"]["Z_HARNESS_SLUG"] == "native-call-slug"  # type: ignore[index]
        assert fake_driver.teardown_calls == 1

    def test_subagent_dispatch_falls_back_when_gate_open_but_driver_has_no_hook(self) -> None:
        """Primitive evidence alone does not turn prompt-only Codex exec into native."""
        from pathlib import Path
        from z_harness_cli.mcp.server import (
            AgentDef,
            MCPDispatcher,
            MCPProviderResolution,
            ToolResult,
            _handle_subagent_dispatch,
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

        class FakeCodexDriverWithoutNativeHook:
            def __init__(self) -> None:
                self.teardown_calls = 0

            def teardown(self) -> None:
                self.teardown_calls += 1

        fake_driver = FakeCodexDriverWithoutNativeHook()

        with patch("z_harness_cli.mcp.server._get_repo_root", return_value=Path("/fake/root")), \
             patch(
                 "z_harness_cli.mcp.server._load_agent",
                 return_value=AgentDef(
                     name="auditor",
                     description="",
                     model="haiku",
                     prompt_template="AGENT TEMPLATE",
                 ),
             ), \
             patch("runtime.dispatch.dispatcher.load_model_routing_config", return_value={}), \
             patch("runtime.dispatch.dispatcher.resolve_native_agent_model", return_value=route), \
             patch("z_harness_cli.mcp.server._resolve_mcp_provider", return_value=provider_resolution), \
             patch(
                 "z_harness_cli.adapters.codex_parity_gate."
                 "codex_native_subagent_dispatch_available",
                 return_value=True,
             ), \
             patch(
                 "z_harness_cli.mcp.server._select_and_init_mcp_driver",
                 return_value=fake_driver,
             ), \
             patch("runtime.dispatch.dispatcher.Dispatcher") as runtime_dispatcher, \
             patch.object(
                 MCPDispatcher,
                 "dispatch",
                 return_value=ToolResult.success("generic path"),
             ) as generic_dispatch:
            result = _handle_subagent_dispatch({"agent": "auditor", "prompt": "check it"}, None)

        assert result.status == "complete"
        assert result.content == "generic path"
        generic_dispatch.assert_called_once()
        runtime_dispatcher.assert_not_called()
        assert fake_driver.teardown_calls == 1

    def test_codex_native_hook_clears_stale_slug_when_slug_not_supplied(self) -> None:
        """Native hook calls without a slug do not inherit stale process state."""
        from pathlib import Path
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
                self.seen_env: dict[str, str] | None = None
                self.seen_process_slug: str | None = None
                self.teardown_calls = 0

            def dispatch_native_subagent(self, **kwargs: object) -> DispatchResult:
                self.seen_env = kwargs["env"]  # type: ignore[assignment]
                self.seen_process_slug = os.environ.get("Z_HARNESS_SLUG")
                return DispatchResult(
                    exit_code=0,
                    is_error=False,
                    stdout_events=[{"type": "text", "content": "native complete"}],
                    stderr="",
                    wall_ms=1.0,
                )

            def teardown(self) -> None:
                self.teardown_calls += 1

        fake_driver = FakeNativeCodexDriver()
        os.environ["Z_HARNESS_SLUG"] = "stale-slug"
        try:
            with patch(
                "z_harness_cli.adapters.codex_parity_gate."
                "codex_native_subagent_dispatch_available",
                return_value=True,
            ), \
                 patch("z_harness_cli.mcp.server._select_and_init_mcp_driver", return_value=fake_driver):
                result = _try_codex_native_subagent_dispatch(
                    repo_root=Path("/fake/root"),
                    provider_resolution=provider_resolution,
                    agent_def=AgentDef(
                        name="auditor",
                        description="",
                        model="haiku",
                        prompt_template="AGENT TEMPLATE",
                    ),
                    prompt="check it",
                    route=route,
                    progress_callback=None,
                    slug=None,
                )

            assert os.environ.get("Z_HARNESS_SLUG") == "stale-slug"
        finally:
            os.environ.pop("Z_HARNESS_SLUG", None)

        assert result is not None
        assert result.status == "complete"
        assert fake_driver.seen_env is not None
        assert "Z_HARNESS_SLUG" not in fake_driver.seen_env
        assert fake_driver.seen_process_slug is None
        assert fake_driver.teardown_calls == 1

    def test_codex_native_hook_tears_down_when_hook_raises(self) -> None:
        """Native hook dispatch failures still run driver teardown once."""
        from pathlib import Path
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

        class FakeFailingNativeCodexDriver:
            def __init__(self) -> None:
                self.teardown_calls = 0

            def dispatch_native_subagent(self, **kwargs: object) -> object:
                raise RuntimeError("native boom")

            def teardown(self) -> None:
                self.teardown_calls += 1

        fake_driver = FakeFailingNativeCodexDriver()

        with patch(
            "z_harness_cli.adapters.codex_parity_gate."
            "codex_native_subagent_dispatch_available",
            return_value=True,
        ), \
             patch("z_harness_cli.mcp.server._select_and_init_mcp_driver", return_value=fake_driver):
            result = _try_codex_native_subagent_dispatch(
                repo_root=Path("/fake/root"),
                provider_resolution=provider_resolution,
                agent_def=AgentDef(
                    name="auditor",
                    description="",
                    model="haiku",
                    prompt_template="AGENT TEMPLATE",
                ),
                prompt="check it",
                route=route,
                progress_callback=None,
            )

        assert result is not None
        assert result.status == "error"
        assert "native boom" in result.content
        assert fake_driver.teardown_calls == 1

    def test_subagent_dispatch_does_not_check_native_gate_for_non_codex_provider(self) -> None:
        """Native gate is considered only after provider resolution yields Codex host."""
        from pathlib import Path
        from z_harness_cli.mcp.server import (
            AgentDef,
            MCPDispatcher,
            MCPProviderResolution,
            ToolResult,
            _handle_subagent_dispatch,
        )

        provider_resolution = MCPProviderResolution(
            role="implementer",
            provider_config={"provider": "claude", "args_template": ["--print"]},
            provider_name="claude",
            host="claude",
        )
        route = types.SimpleNamespace(
            effective_model="sonnet",
            source="frontmatter",
            route="sonnet",
            route_kind="exact",
            thinking="",
            reasoning="",
            effort="",
        )

        with patch("z_harness_cli.mcp.server._get_repo_root", return_value=Path("/fake/root")), \
             patch(
                 "z_harness_cli.mcp.server._load_agent",
                 return_value=AgentDef(
                     name="auditor",
                     description="",
                     model="sonnet",
                     prompt_template="AGENT TEMPLATE",
                 ),
             ), \
             patch("runtime.dispatch.dispatcher.load_model_routing_config", return_value={}), \
             patch("runtime.dispatch.dispatcher.resolve_native_agent_model", return_value=route), \
             patch("z_harness_cli.mcp.server._resolve_mcp_provider", return_value=provider_resolution), \
             patch(
                 "z_harness_cli.adapters.codex_parity_gate."
                 "codex_native_subagent_dispatch_available",
                 return_value=True,
             ) as native_gate, \
             patch.object(
                 MCPDispatcher,
                 "dispatch",
                 return_value=ToolResult.success("generic path"),
             ):
            result = _handle_subagent_dispatch({"agent": "auditor", "prompt": "check it"}, None)

        assert result.status == "complete"
        native_gate.assert_not_called()


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
