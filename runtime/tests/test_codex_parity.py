"""Codex orchestration parity fixture - T007.

This fixture records Codex-specific orchestration evidence without assuming
that every Codex surface supports native z-harness orchestration today.

The current Codex CLI driver preserves raw JSONL frames and classifies event
families for telemetry, but it does not expose a ``dispatch_native_subagent``
hook.  MCP ``z_subagent_dispatch`` must therefore keep using the generic
dispatcher unless the primitive evidence gate is open and the selected driver
implements that explicit hook.
"""

from __future__ import annotations

import io
import json
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from runtime.dispatch.result import DispatchResult
from runtime.drivers.codex.driver import CodexDriver, _build_proc_env
from runtime.drivers.codex.stream import (
    EVENT_FAMILY_ASK_USER,
    EVENT_FAMILY_FINAL_RESULT,
    EVENT_FAMILY_GATE,
    EVENT_FAMILY_MESSAGE,
    EVENT_FAMILY_SUBAGENT,
    EVENT_FAMILY_TOOL,
    classify_event_family,
    parse_stream,
)


_CODEX_PROVIDER: dict = {
    "name": "codex-cli",
    "kind": "cli",
    "command": "codex",
    "args_template": ["exec", "-"],
    "stdin": True,
    "timeout_s": 30,
    "model_label": "gpt-5-codex",
}

_CLEAN_ENV: dict = {
    "PATH": "/usr/bin",
    "HOME": "/home/user",
}


def _proc(
    *,
    stdout_lines: list[str] | None = None,
    stderr: str = "",
    returncode: int = 0,
) -> MagicMock:
    proc = MagicMock()
    proc.returncode = returncode
    proc.stdout = io.BytesIO(
        b"".join((line + "\n").encode("utf-8") for line in (stdout_lines or []))
    )
    proc.stderr = io.BytesIO(stderr.encode("utf-8"))
    proc.stdin = MagicMock()
    proc.poll.return_value = returncode
    proc.wait.return_value = returncode
    return proc


def _patch_codex_select(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "runtime.drivers.codex.stream.select.select",
        lambda rfds, wfds, xfds, timeout: (rfds, [], []),
    )


def _driver_with_proc(
    monkeypatch: pytest.MonkeyPatch,
    proc: MagicMock,
) -> tuple[CodexDriver, MagicMock]:
    popen = MagicMock(return_value=proc)
    monkeypatch.setattr("runtime.drivers.codex.driver.subprocess.Popen", popen)
    monkeypatch.setattr(
        "runtime.drivers.codex.driver.resolve_auth",
        lambda *a, **kw: MagicMock(
            strategy="codex_api_key",
            env_additions={"CODEX_API_KEY": "ck-test"},
        ),
    )
    monkeypatch.setattr("runtime.drivers.codex.driver._fire_telemetry", MagicMock())
    driver = CodexDriver()
    driver.init(_CODEX_PROVIDER, context={"run_id": "codex-parity", "repo_root": "/repo"})
    return driver, popen


def _codex_provider_resolution() -> object:
    from z_harness_cli.mcp.server import MCPProviderResolution

    return MCPProviderResolution(
        role="implementer",
        provider_config={
            "provider": "codex-cli",
            "args_template": ["exec", "-"],
            "model_arg_template": None,
        },
        provider_name="codex-cli",
        host="codex",
    )


def _agent_def() -> object:
    from z_harness_cli.mcp.server import AgentDef

    return AgentDef(
        name="auditor",
        description="",
        model="haiku",
        prompt_template="AGENT TEMPLATE",
    )


def _route() -> types.SimpleNamespace:
    return types.SimpleNamespace(
        effective_model="gpt-5-codex",
        source="frontmatter",
        route="haiku",
        route_kind="exact",
        thinking="",
        reasoning="",
    )


class TestCodexSubagentFanOutFrames:
    """Codex subagent-shaped frames are preserved when the CLI emits them."""

    def test_parser_preserves_subagent_event_family_without_flattening(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch_codex_select(monkeypatch)
        raw_frames = [
            {
                "type": "item.started",
                "item": {
                    "type": "subagent.started",
                    "subagent_type": "implementer",
                    "id": "subagent-1",
                },
                "codex_extra": {"fanout_index": 1},
            },
            {
                "type": "item.started",
                "item": {
                    "type": "subagent.started",
                    "subagent_type": "reviewer",
                    "id": "subagent-2",
                },
                "codex_extra": {"fanout_index": 2},
            },
            {
                "type": "item.completed",
                "item": {"type": "agent_message", "text": "ordinary prose"},
            },
        ]
        proc = _proc(stdout_lines=[json.dumps(frame) for frame in raw_frames])

        frames = list(parse_stream(proc))

        assert [frame.event_family for frame in frames] == [
            EVENT_FAMILY_SUBAGENT,
            EVENT_FAMILY_SUBAGENT,
            EVENT_FAMILY_MESSAGE,
        ]
        assert [frame.raw for frame in frames] == raw_frames
        assert all(frame.event_family != EVENT_FAMILY_MESSAGE for frame in frames[:2])
        assert [frame.raw["item"]["subagent_type"] for frame in frames[:2]] == [
            "implementer",
            "reviewer",
        ]

    def test_driver_yields_raw_subagent_frames_not_prose(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch_codex_select(monkeypatch)
        raw_frames = [
            {
                "type": "subagent.started",
                "subagent_type": "implementer",
                "native_unknown": "kept",
            },
            {
                "type": "subagent.completed",
                "subagent_type": "implementer",
                "result": {"content": "done"},
            },
        ]
        driver, _ = _driver_with_proc(
            monkeypatch,
            _proc(stdout_lines=[json.dumps(frame) for frame in raw_frames]),
        )

        handle = driver.dispatch("z-execute", [], dict(_CLEAN_ENV))
        events = list(handle.events())

        assert events == raw_frames
        assert [classify_event_family(event) for event in events] == [
            EVENT_FAMILY_SUBAGENT,
            EVENT_FAMILY_SUBAGENT,
        ]
        assert all(event.get("type") != "assistant_delta" for event in events)


class TestCodexConsultantDispatchIsolation:
    """Codex paths must not inherit OMP/Pi/Claude consult-shim assumptions."""

    def test_driver_invocation_has_no_omp_or_sessionless_consult_flags(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        seen: dict[str, object] = {}

        def fake_popen(argv, **kwargs):
            seen["argv"] = argv
            seen["env"] = kwargs["env"]
            return _proc(stdout_lines=[])

        monkeypatch.setattr("runtime.drivers.codex.driver.subprocess.Popen", fake_popen)
        monkeypatch.setattr(
            "runtime.drivers.codex.driver.resolve_auth",
            lambda *a, **kw: MagicMock(
                strategy="codex_api_key",
                env_additions={"CODEX_API_KEY": "ck-test"},
            ),
        )
        monkeypatch.setattr("runtime.drivers.codex.driver._fire_telemetry", MagicMock())

        driver = CodexDriver()
        driver.init(_CODEX_PROVIDER, context={"run_id": "codex-parity", "repo_root": "/repo"})
        driver.dispatch("z-consult", ["exec", "-", "review this"], dict(_CLEAN_ENV))

        argv = seen["argv"]
        assert argv == ["codex", "exec", "--json", "-"]
        flat_argv = " ".join(argv)  # type: ignore[arg-type]
        assert "omp-consult" not in flat_argv
        assert "pi_assets" not in flat_argv
        assert "claude" not in flat_argv
        assert "--no-rules" not in argv
        assert "--no-session" not in argv

    def test_codex_env_strips_cross_vendor_keys_by_default(self) -> None:
        env = _build_proc_env(
            base_env={
                **_CLEAN_ENV,
                "ANTHROPIC_API_KEY": "anthropic-secret",
                "CLAUDE_API_KEY": "claude-secret",
                "OPENAI_API_KEY": "openai-secret",
            },
            auth_additions={"CODEX_API_KEY": "codex-secret"},
            provider_config=_CODEX_PROVIDER,
        )

        assert env["CODEX_API_KEY"] == "codex-secret"
        assert env["OPENAI_API_KEY"] == "openai-secret"
        assert "ANTHROPIC_API_KEY" not in env
        assert "CLAUDE_API_KEY" not in env


class TestCodexAskUserGateFrames:
    """Codex ask/gate frames are preserved when present; support still gates evidence."""

    def test_ask_user_and_gate_frames_are_classified_without_rewriting(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch_codex_select(monkeypatch)
        raw_frames = [
            {
                "type": "ask_user",
                "question": "Continue?",
                "choices": ["continue", "abort"],
                "codex_extra": {"id": "ask-1"},
            },
            {
                "type": "user_gate",
                "gate_id": "release-review",
                "prompt": "Approve release?",
            },
        ]
        proc = _proc(stdout_lines=[json.dumps(frame) for frame in raw_frames])

        frames = list(parse_stream(proc))

        assert [frame.event_family for frame in frames] == [
            EVENT_FAMILY_ASK_USER,
            EVENT_FAMILY_GATE,
        ]
        assert [frame.raw for frame in frames] == raw_frames
        assert frames[0].content == "Continue?"
        assert frames[1].content == "Approve release?"

    def test_gate_decision_fails_closed_when_required_evidence_is_absent(self) -> None:
        import z_harness_cli.adapters.codex_parity_gate as gate_mod

        original = {
            command: list(entries)
            for command, entries in gate_mod.PARITY_EVIDENCE.items()
        }
        try:
            gate_mod.PARITY_EVIDENCE["z-gate"] = [
                ("runtime.tests.test_codex_parity", "MissingCodexAskUserEvidence")
            ]

            decision = gate_mod.codex_command_decision("z-gate")

            assert decision.tier == "blocked"
            assert "Missing required Codex parity evidence" in decision.reason
            assert "MissingCodexAskUserEvidence" in decision.reason
        finally:
            gate_mod.PARITY_EVIDENCE.clear()
            gate_mod.PARITY_EVIDENCE.update(original)


class TestCodexTelemetryFrameParity:
    """Codex driver telemetry preserves event-family counts for raw frames."""

    def test_complete_telemetry_reports_frames_by_family(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch_codex_select(monkeypatch)
        raw_frames = [
            {"type": "subagent.started", "subagent_type": "implementer"},
            {"type": "ask_user", "question": "Continue?", "choices": ["yes", "no"]},
            {"type": "tool_call", "tool_name": "apply_patch", "tool_call_id": "t1"},
            {"type": "final_result", "result": {"content": "done"}},
        ]
        proc = _proc(stdout_lines=[json.dumps(frame) for frame in raw_frames])
        popen = MagicMock(return_value=proc)
        mock_fire = MagicMock()
        monkeypatch.setattr("runtime.drivers.codex.driver.subprocess.Popen", popen)
        monkeypatch.setattr(
            "runtime.drivers.codex.driver.resolve_auth",
            lambda *a, **kw: MagicMock(
                strategy="codex_api_key",
                env_additions={"CODEX_API_KEY": "ck-test"},
            ),
        )
        monkeypatch.setattr("runtime.drivers.codex.driver._fire_telemetry", mock_fire)

        driver = CodexDriver()
        driver.init(_CODEX_PROVIDER, context={"run_id": "codex-parity", "repo_root": "/repo"})
        handle = driver.dispatch("z-execute", [], dict(_CLEAN_ENV))
        events = list(handle.events())
        result = handle.wait()

        assert result.success
        assert events == raw_frames
        complete_call = next(
            call for call in mock_fire.call_args_list
            if call.args[0] == "codex_driver_complete"
        )
        payload = complete_call.args[1]
        assert payload["frames_parsed"] == 4
        assert payload["frames_by_family"] == {
            EVENT_FAMILY_SUBAGENT: 1,
            EVENT_FAMILY_ASK_USER: 1,
            EVENT_FAMILY_TOOL: 1,
            EVENT_FAMILY_FINAL_RESULT: 1,
        }


class TestCodexMultiAgentCommandPath:
    """Representative z_subagent_dispatch branch selection for Codex."""

    def test_current_codex_driver_has_no_native_subagent_hook(self) -> None:
        from z_harness_cli.mcp.server import _codex_native_subagent_hook

        assert _codex_native_subagent_hook(CodexDriver()) is None
        assert not hasattr(CodexDriver, "dispatch_native_subagent")

    def test_z_subagent_dispatch_falls_back_when_hook_absent(
        self,
    ) -> None:
        from z_harness_cli.mcp.server import (
            MCPDispatcher,
            ToolResult,
            _handle_subagent_dispatch,
        )

        class FakeCodexDriverWithoutNativeHook:
            def __init__(self) -> None:
                self.teardown_calls = 0

            def teardown(self) -> None:
                self.teardown_calls += 1

        fake_driver = FakeCodexDriverWithoutNativeHook()

        with patch("z_harness_cli.mcp.server._get_repo_root", return_value=Path("/repo")), \
             patch("z_harness_cli.mcp.server._load_agent", return_value=_agent_def()), \
             patch("runtime.dispatch.dispatcher.load_model_routing_config", return_value={}), \
             patch("runtime.dispatch.dispatcher.resolve_native_agent_model", return_value=_route()), \
             patch("z_harness_cli.mcp.server._resolve_mcp_provider", return_value=_codex_provider_resolution()), \
             patch(
                 "z_harness_cli.adapters.codex_parity_gate."
                 "codex_native_subagent_dispatch_available",
                 return_value=True,
             ), \
             patch("z_harness_cli.mcp.server._select_and_init_mcp_driver", return_value=fake_driver), \
             patch.object(
                 MCPDispatcher,
                 "dispatch",
                 return_value=ToolResult.success("generic path"),
             ) as generic_dispatch:
            result = _handle_subagent_dispatch({"agent": "auditor", "prompt": "check it"}, None)

        assert result.status == "complete"
        assert result.content == "generic path"
        generic_dispatch.assert_called_once()
        assert fake_driver.teardown_calls == 1

    def test_z_subagent_dispatch_uses_native_branch_only_with_gate_and_hook(
        self,
    ) -> None:
        from z_harness_cli.mcp.server import _try_codex_native_subagent_dispatch

        class FakeNativeCodexDriver:
            def __init__(self) -> None:
                self.calls: list[dict[str, object]] = []
                self.teardown_calls = 0

            def dispatch_native_subagent(self, **kwargs: object) -> DispatchResult:
                self.calls.append(kwargs)
                return DispatchResult(
                    exit_code=0,
                    is_error=False,
                    stdout_events=[{"type": "text", "content": "native complete"}],
                    stderr="",
                    wall_ms=2.0,
                )

            def teardown(self) -> None:
                self.teardown_calls += 1

        fake_driver = FakeNativeCodexDriver()

        with patch(
            "z_harness_cli.adapters.codex_parity_gate."
            "codex_native_subagent_dispatch_available",
            return_value=True,
        ), \
             patch("z_harness_cli.mcp.server._select_and_init_mcp_driver", return_value=fake_driver):
            result = _try_codex_native_subagent_dispatch(
                repo_root=Path("/repo"),
                provider_resolution=_codex_provider_resolution(),
                agent_def=_agent_def(),
                prompt="check it",
                route=_route(),
                progress_callback=None,
                slug="codex-parity-slug",
            )

        assert result is not None
        assert result.status == "complete"
        assert result.content == "native complete"
        assert result.meta["dispatch_path"] == "codex_native_subagent"
        assert fake_driver.calls
        assert fake_driver.calls[0]["prompt"] == "check it"
        assert fake_driver.calls[0]["env"]["Z_HARNESS_SLUG"] == "codex-parity-slug"  # type: ignore[index]
        assert fake_driver.teardown_calls == 1


class TestUnsupportedCodexSurfaces:
    """Negative evidence for unsupported native Codex surfaces."""

    def test_current_gate_keeps_unpromoted_surfaces_conservative(self) -> None:
        from z_harness_cli.adapters.codex_parity_gate import (
            NATIVE_CANDIDATE_FAMILIES,
            codex_adapter_fidelity,
            codex_command_tier,
            codex_export_fidelity,
            codex_native_subagent_dispatch_available,
        )

        assert codex_adapter_fidelity() == "flattened"
        assert codex_export_fidelity() == "partial"
        assert codex_command_tier("z-plan") == "degraded"
        assert codex_native_subagent_dispatch_available() is False
        assert {
            command: codex_command_tier(command)
            for command in NATIVE_CANDIDATE_FAMILIES
        } == {
            command: "blocked"
            for command in NATIVE_CANDIDATE_FAMILIES
        }

    def test_primitive_native_subagent_gate_remains_closed_without_evidence(self) -> None:
        import runtime.tests.test_codex_parity as parity_module
        from z_harness_cli.adapters.codex_parity_gate import (
            codex_native_subagent_dispatch_available,
        )

        assert not hasattr(parity_module, "TestCodexNativeSubagentDispatchPrimitive")
        assert codex_native_subagent_dispatch_available() is False

    def test_native_subagent_try_path_does_not_initialize_driver_when_gate_closed(
        self,
    ) -> None:
        from z_harness_cli.mcp.server import _try_codex_native_subagent_dispatch

        with patch("z_harness_cli.mcp.server._select_and_init_mcp_driver") as select_driver:
            result = _try_codex_native_subagent_dispatch(
                repo_root=Path("/repo"),
                provider_resolution=_codex_provider_resolution(),
                agent_def=_agent_def(),
                prompt="check it",
                route=_route(),
                progress_callback=None,
            )

        assert result is None
        select_driver.assert_not_called()

    def test_unknown_codex_event_family_stays_unknown_not_promoted(self) -> None:
        assert classify_event_family({"type": "future.codex.event", "payload": {}}) == "unknown"

    def test_ask_user_detection_from_plain_text_is_mcp_needs_input_not_native_gate(
        self,
    ) -> None:
        from z_harness_cli.mcp.server import _detect_needs_input

        signal = _detect_needs_input("AskUserQuestion: pick a plan slug")

        assert signal is not None
        assert signal["question_id"] == "ask_user_needs_input"
        assert signal["content"] == "pick a plan slug"
