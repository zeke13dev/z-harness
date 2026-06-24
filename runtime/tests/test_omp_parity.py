"""OMP orchestration parity fixture — T008.

Asserts that the OmpHostDriver provides Claude-equivalent behavior on five
behavioral dimensions that the INTENT contract names as native-parity gates:

  (a) Subagent fan-out — OMP emits ``subagent`` events; not flattened to prose.
  (b) Consultant dispatch — native mode never routes through scripts/omp-consult.sh.
  (c) AskUser / gate blocking — ask_user events are emitted and carry payload.
  (d) Telemetry completeness — invoke + complete events with all required fields.
  (e) Multi-agent command path — a z-execute-style multi-event sequence is parsed
      correctly and yields final_result without prose-only fallback.

All tests use a stub ``omp`` binary via monkeypatched subprocess.Popen — no real
``omp`` install is required.

Parity reference
----------------
Claude's ``SubprocessClaudeDriver`` is the behavioral ground truth (INTENT key
decision, LEDGER T001).  Where this fixture references "Claude expectations" it
means the event kinds, payload fields, and gate semantics that
``SubprocessClaudeDriver`` provides and that the INTENT acceptance checklist
(criterion #4, #6, #8) requires of OMP.

Failure modes guarded
---------------------
Each test is annotated with the failure class it catches if a regression occurs.
"""

from __future__ import annotations

from io import BytesIO
from unittest.mock import MagicMock

import pytest

from runtime.drivers.omp.subprocess_driver import OmpDriverConfigError, OmpHostDriver


# ---------------------------------------------------------------------------
# Shared helpers (mirror test_omp_driver.py style)
# ---------------------------------------------------------------------------


def _proc(*, stdout: bytes = b"", stderr: bytes = b"", returncode: int = 0) -> MagicMock:
    proc = MagicMock()
    proc.stdout = BytesIO(stdout)
    proc.stderr = BytesIO(stderr)
    proc.returncode = returncode
    proc.pid = 9001

    def _wait(timeout=None):
        return returncode

    proc.wait.side_effect = _wait
    return proc


def _driver(provider_config: dict | None = None) -> OmpHostDriver:
    driver = OmpHostDriver()
    driver.init(provider_config or {})
    return driver


# ---------------------------------------------------------------------------
# (a) Subagent fan-out — OMP must emit subagent events, not flatten to prose
# ---------------------------------------------------------------------------


class TestSubagentFanOutParity:
    """Failure class: OMP flattens Agent() subagent fan-out into prose.

    Claude's SubprocessClaudeDriver emits structured subagent events when the
    model spawns a sub-agent.  If OMP serialises the same span as plain text,
    the harness loses the agent identity and cannot track fan-out.  These tests
    assert that the OmpHostDriver correctly maps OMP's ``subagent`` frame to the
    canonical ``subagent`` event kind with an ``agent`` payload field.
    """

    def test_subagent_event_kind_present_in_events(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """OMP subagent frame is normalised to kind='subagent', not assistant_delta.

        Regression: if _map_kind removes 'subagent' or maps it to 'assistant_delta',
        every subagent span becomes opaque prose and fan-out tracking breaks.
        """
        stdout = (
            b'{"type":"subagent","agent":"explore","status":"started"}\n'
            b'{"type":"subagent","agent":"explore","status":"completed"}\n'
            b'{"type":"final_result","result":"done"}\n'
        )
        monkeypatch.setattr(
            "runtime.drivers.omp.subprocess_driver.subprocess.Popen",
            MagicMock(return_value=_proc(stdout=stdout)),
        )
        monkeypatch.setattr("runtime.drivers.omp.subprocess_driver._fire_telemetry", MagicMock())

        handle = _driver({"model": "m"}).dispatch("z-execute", ["run it"], {})
        events = list(handle.events())
        handle.wait()

        subagent_events = [e for e in events if e["kind"] == "subagent"]
        assert len(subagent_events) == 2, (
            f"Expected 2 subagent events; got kinds={[e['kind'] for e in events]}"
        )
        # Verify no subagent frame was silently converted to prose.
        prose_events = [e for e in events if e["kind"] == "assistant_delta"]
        assert prose_events == [], (
            f"Subagent frames were flattened into prose: {prose_events}"
        )

    def test_subagent_event_carries_agent_field(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Subagent payload carries 'agent' field identifying the spawned agent.

        Regression: if _normalise_frame drops the 'agent' key, the harness
        cannot identify which sub-agent ran and fan-out attribution is lost.
        """
        stdout = b'{"type":"subagent","agent":"doc-fetcher","status":"started"}\n{"type":"final_result","result":"ok"}\n'
        monkeypatch.setattr(
            "runtime.drivers.omp.subprocess_driver.subprocess.Popen",
            MagicMock(return_value=_proc(stdout=stdout)),
        )
        monkeypatch.setattr("runtime.drivers.omp.subprocess_driver._fire_telemetry", MagicMock())

        handle = _driver({"model": "m"}).dispatch("z-execute", ["prompt"], {})
        events = list(handle.events())
        handle.wait()

        subagent_events = [e for e in events if e["kind"] == "subagent"]
        assert subagent_events, "No subagent event emitted"
        assert subagent_events[0]["payload"].get("agent") == "doc-fetcher", (
            f"Expected agent='doc-fetcher'; got payload={subagent_events[0]['payload']}"
        )

    def test_multiple_concurrent_subagents_all_preserved(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """All subagent frames in a fan-out sequence are preserved, not collapsed.

        Regression: if the driver deduplicates or skips repeated subagent events
        only the first agent would appear, masking parallel-agent behaviour.
        """
        stdout = b"".join([
            b'{"type":"subagent","agent":"implementer-1","status":"started"}\n',
            b'{"type":"subagent","agent":"implementer-2","status":"started"}\n',
            b'{"type":"subagent","agent":"implementer-1","status":"completed"}\n',
            b'{"type":"subagent","agent":"implementer-2","status":"completed"}\n',
            b'{"type":"final_result","result":"all done"}\n',
        ])
        monkeypatch.setattr(
            "runtime.drivers.omp.subprocess_driver.subprocess.Popen",
            MagicMock(return_value=_proc(stdout=stdout)),
        )
        monkeypatch.setattr("runtime.drivers.omp.subprocess_driver._fire_telemetry", MagicMock())

        handle = _driver({"model": "m"}).dispatch("z-execute", ["fan out"], {})
        events = list(handle.events())
        handle.wait()

        subagent_events = [e for e in events if e["kind"] == "subagent"]
        agents_seen = [e["payload"].get("agent") for e in subagent_events]
        assert len(subagent_events) == 4, (
            f"Expected 4 subagent events; got {len(subagent_events)}: {agents_seen}"
        )
        assert "implementer-1" in agents_seen and "implementer-2" in agents_seen, (
            f"Not all subagent identities preserved: {agents_seen}"
        )


# ---------------------------------------------------------------------------
# (b) Consultant dispatch — native mode must NOT route through omp-consult.sh
# ---------------------------------------------------------------------------


class TestConsultantDispatchIsolation:
    """Failure class: native OMP dispatch routes through scripts/omp-consult.sh.

    Claude's native dispatch never uses compatibility shim paths.  OMP native
    mode must be equally clean.  These tests assert the forbidden-compat guard
    fires and that native dispatch args never contain --no-rules or --no-session
    (consult-mode-only flags).
    """

    def test_consult_sh_in_provider_command_raises_at_init(self) -> None:
        """OmpDriverConfigError raised at init() when command= names omp-consult.sh.

        Regression: if the forbidden-compat guard is removed, a mis-configured
        provider could silently route native z-execute through the consult shim,
        losing session/rules semantics and masking the regression.
        """
        with pytest.raises(OmpDriverConfigError, match="omp-consult"):
            _driver({"command": "scripts/omp-consult.sh"})

    def test_consult_sh_in_args_raises_before_spawn(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """OmpDriverConfigError raised at dispatch() when args contain omp-consult.sh.

        Regression: if _contains_forbidden_compat is removed, a caller that
        passes the consult shim path in args would silently execute in consult
        mode instead of native mode.
        """
        popen = MagicMock()
        monkeypatch.setattr("runtime.drivers.omp.subprocess_driver.subprocess.Popen", popen)

        driver = _driver()
        with pytest.raises(OmpDriverConfigError, match="omp-consult"):
            driver.dispatch("z-consult", ["--fallback", "scripts/omp-consult.sh", "prompt"], {})

        popen.assert_not_called()

    def test_native_dispatch_argv_contains_no_consult_mode_flags(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Native OMP dispatch never adds --no-rules or --no-session to argv.

        Regression: if consult-mode flag injection is added to native dispatch,
        OMP would execute without session context or rules, silently degrading
        native-mode behaviour to consult-mode behaviour.
        """
        seen: dict = {}

        def fake_popen(argv, *, stdout, stderr, env):
            seen["argv"] = argv
            return _proc(stdout=b"ok\n")

        monkeypatch.setattr("runtime.drivers.omp.subprocess_driver.subprocess.Popen", fake_popen)
        monkeypatch.setattr("runtime.drivers.omp.subprocess_driver._fire_telemetry", MagicMock())

        _driver({"model": "m", "profile": "z-harness"}).dispatch(
            "z-execute", ["implement T008"], {}
        )

        argv = seen["argv"]
        assert "--no-rules" not in argv, f"Consult-mode flag --no-rules present in native argv: {argv}"
        assert "--no-session" not in argv, f"Consult-mode flag --no-session present in native argv: {argv}"

    def test_native_dispatch_argv_has_no_omp_consult_string(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The string 'omp-consult' must not appear anywhere in native dispatch argv.

        Regression: if a future refactor injects a fallback path, any invocation
        of the consult shim would be detectable here before reaching the guard.
        """
        seen: dict = {}

        def fake_popen(argv, *, stdout, stderr, env):
            seen["argv"] = argv
            return _proc(stdout=b"ok\n")

        monkeypatch.setattr("runtime.drivers.omp.subprocess_driver.subprocess.Popen", fake_popen)
        monkeypatch.setattr("runtime.drivers.omp.subprocess_driver._fire_telemetry", MagicMock())

        _driver({"model": "m"}).dispatch("z-review", ["review this"], {})

        flat_argv = " ".join(seen["argv"])
        assert "omp-consult" not in flat_argv, (
            f"'omp-consult' unexpectedly appeared in native dispatch argv: {seen['argv']}"
        )


# ---------------------------------------------------------------------------
# (c) AskUser / gate blocking — ask_user events must be emitted with payload
# ---------------------------------------------------------------------------


class TestAskUserGateParity:
    """Failure class: native OMP skips or drops AskUser / user-gate events.

    Claude's native mode surfaces AskUser frames as blocking gate events that
    the harness can inspect or relay to the user.  If OMP silently drops or
    merges these into prose, automated flows that depend on gate detection
    (e.g. /z-gate in z-execute) would silently proceed past user checkpoints.
    """

    def test_ask_user_event_is_emitted_not_dropped(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """AskUserQuestion OMP frame becomes kind='ask_user', not prose or dropped.

        Regression: if _map_kind maps AskUserQuestion to assistant_delta or omits
        it entirely, the gate event is lost and the harness proceeds past the
        user checkpoint without surfacing the question.
        """
        stdout = (
            b'{"type":"AskUserQuestion","question":"Confirm destructive action?"}\n'
            b'{"type":"final_result","result":"user confirmed"}\n'
        )
        monkeypatch.setattr(
            "runtime.drivers.omp.subprocess_driver.subprocess.Popen",
            MagicMock(return_value=_proc(stdout=stdout)),
        )
        monkeypatch.setattr("runtime.drivers.omp.subprocess_driver._fire_telemetry", MagicMock())

        handle = _driver({"model": "m"}).dispatch("z-gate", ["check gate"], {})
        events = list(handle.events())
        handle.wait()

        ask_events = [e for e in events if e["kind"] == "ask_user"]
        assert len(ask_events) == 1, (
            f"Expected 1 ask_user event; got kinds={[e['kind'] for e in events]}"
        )
        # Verify the gate was not silently converted to prose.
        prose_with_question = [
            e for e in events
            if e["kind"] == "assistant_delta"
            and "Confirm" in str(e.get("payload", {}).get("text", ""))
        ]
        assert prose_with_question == [], (
            f"AskUser question appeared as prose instead of gate event: {prose_with_question}"
        )

    def test_ask_user_payload_carries_question_field(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """ask_user event payload always contains a 'question' field.

        Regression: if _normalise_frame drops the question key, callers that
        relay the question to the user receive an empty gate with no context.
        """
        stdout = (
            b'{"type":"ask_user","question":"Should I overwrite existing file?"}\n'
            b'{"type":"final_result","result":"skipped"}\n'
        )
        monkeypatch.setattr(
            "runtime.drivers.omp.subprocess_driver.subprocess.Popen",
            MagicMock(return_value=_proc(stdout=stdout)),
        )
        monkeypatch.setattr("runtime.drivers.omp.subprocess_driver._fire_telemetry", MagicMock())

        handle = _driver({"model": "m"}).dispatch("z-gate", ["overwrite?"], {})
        events = list(handle.events())
        handle.wait()

        ask_events = [e for e in events if e["kind"] == "ask_user"]
        assert ask_events, "No ask_user event emitted"
        question = ask_events[0]["payload"].get("question")
        assert question == "Should I overwrite existing file?", (
            f"Expected question payload; got payload={ask_events[0]['payload']}"
        )

    def test_ask_user_appears_in_event_sequence_not_at_end_only(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """ask_user event preserves its position in the event stream (not deferred).

        Regression: if ask_user events are buffered and replayed at the end of
        the stream, a gate in the middle of a long task would appear after the
        final result — making it undetectable as a blocking checkpoint.
        """
        stdout = b"".join([
            b'{"type":"assistant_delta","text":"working"}\n',
            b'{"type":"AskUserQuestion","question":"Continue?"}\n',
            b'{"type":"assistant_delta","text":"continuing"}\n',
            b'{"type":"final_result","result":"done"}\n',
        ])
        monkeypatch.setattr(
            "runtime.drivers.omp.subprocess_driver.subprocess.Popen",
            MagicMock(return_value=_proc(stdout=stdout)),
        )
        monkeypatch.setattr("runtime.drivers.omp.subprocess_driver._fire_telemetry", MagicMock())

        handle = _driver({"model": "m"}).dispatch("z-gate", ["go"], {})
        events = list(handle.events())
        handle.wait()

        kinds = [e["kind"] for e in events]
        # ask_user must appear before final_result (not after or missing).
        assert "ask_user" in kinds, f"ask_user missing from stream: {kinds}"
        ask_idx = kinds.index("ask_user")
        final_idx = kinds.index("final_result")
        assert ask_idx < final_idx, (
            f"ask_user at index {ask_idx} appeared after final_result at {final_idx}: {kinds}"
        )

    def test_multiple_ask_user_gates_all_surface(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Multiple AskUser frames in one run are all surfaced as separate events.

        Regression: if the driver only emits the first ask_user event (e.g. by
        tracking a 'gate_seen' flag), subsequent gates in a multi-step task
        would be silently dropped.
        """
        stdout = b"".join([
            b'{"type":"AskUserQuestion","question":"First gate?"}\n',
            b'{"type":"AskUserQuestion","question":"Second gate?"}\n',
            b'{"type":"final_result","result":"completed"}\n',
        ])
        monkeypatch.setattr(
            "runtime.drivers.omp.subprocess_driver.subprocess.Popen",
            MagicMock(return_value=_proc(stdout=stdout)),
        )
        monkeypatch.setattr("runtime.drivers.omp.subprocess_driver._fire_telemetry", MagicMock())

        handle = _driver({"model": "m"}).dispatch("z-gate", ["multi-gate"], {})
        events = list(handle.events())
        handle.wait()

        ask_events = [e for e in events if e["kind"] == "ask_user"]
        assert len(ask_events) == 2, (
            f"Expected 2 ask_user events; got {len(ask_events)}: "
            f"{[e['payload'] for e in ask_events]}"
        )


# ---------------------------------------------------------------------------
# (d) Telemetry completeness — invoke + complete with all required fields
# ---------------------------------------------------------------------------


class TestTelemetryParity:
    """Failure class: OMP driver drops telemetry fields required for analysis.

    Claude's SubprocessClaudeDriver emits subprocess_spawn and subprocess_exit
    events with pid, args_redacted, exit_code, is_error, and wall_ms.  OMP's
    equivalent events (omp_driver_invoke / omp_driver_complete) must carry the
    same analysis-relevant fields so metrics.jsonl rows remain joinable.
    """

    def test_invoke_event_has_required_fields(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """omp_driver_invoke payload has command, args_redacted, pid, has_model/profile/session.

        Regression: if any of these fields is removed, the telemetry analysis
        pipeline cannot identify which omp binary ran or correlate with model/
        session configuration.
        """
        calls: list[tuple[str, dict]] = []

        def capture_telemetry(kind, payload, *, run_id, repo_root):
            calls.append((kind, payload))

        monkeypatch.setattr(
            "runtime.drivers.omp.subprocess_driver.subprocess.Popen",
            MagicMock(return_value=_proc(stdout=b"ok\n")),
        )
        monkeypatch.setattr(
            "runtime.drivers.omp.subprocess_driver._fire_telemetry",
            capture_telemetry,
        )

        driver = _driver({"model": "gpt-5.5", "profile": "z-harness", "session_id": "s1"})
        handle = driver.dispatch("z-execute", ["do the thing"], {})
        list(handle.events())
        handle.wait()

        invoke_calls = [(k, p) for k, p in calls if k == "omp_driver_invoke"]
        assert len(invoke_calls) == 1, f"Expected 1 omp_driver_invoke; got {[k for k, _ in calls]}"
        _, payload = invoke_calls[0]

        assert "command" in payload, f"'command' missing from omp_driver_invoke: {payload}"
        assert "args_redacted" in payload, f"'args_redacted' missing: {payload}"
        assert "pid" in payload, f"'pid' missing: {payload}"
        assert payload.get("has_model") is True, f"has_model not True: {payload}"
        assert payload.get("has_profile") is True, f"has_profile not True: {payload}"
        assert payload.get("has_session") is True, f"has_session not True: {payload}"

    def test_completion_event_has_required_fields(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """omp_driver_complete payload has exit_code, is_error, wall_ms, events_parsed.

        Regression: if wall_ms or events_parsed is removed, the metrics pipeline
        cannot compute per-invocation latency or correlate event count with cost.
        """
        calls: list[tuple[str, dict]] = []

        def capture_telemetry(kind, payload, *, run_id, repo_root):
            calls.append((kind, payload))

        monkeypatch.setattr(
            "runtime.drivers.omp.subprocess_driver.subprocess.Popen",
            MagicMock(return_value=_proc(stdout=b"ok\n")),
        )
        monkeypatch.setattr(
            "runtime.drivers.omp.subprocess_driver._fire_telemetry",
            capture_telemetry,
        )

        handle = _driver({"model": "m"}).dispatch("z-execute", ["prompt"], {})
        list(handle.events())
        handle.wait()

        complete_calls = [(k, p) for k, p in calls if k in ("omp_driver_complete", "omp_driver_error")]
        assert len(complete_calls) == 1, (
            f"Expected 1 completion event; got {[k for k, _ in calls]}"
        )
        _, payload = complete_calls[0]

        assert "exit_code" in payload, f"'exit_code' missing from completion event: {payload}"
        assert "is_error" in payload, f"'is_error' missing: {payload}"
        assert "wall_ms" in payload, f"'wall_ms' missing: {payload}"
        assert "events_parsed" in payload, f"'events_parsed' missing: {payload}"

    def test_invoke_args_redacted_masks_model_profile_session(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Sensitive flag values (model, profile, session) are redacted in telemetry.

        Regression: if _redact_args is removed, actual model names and session IDs
        would appear verbatim in telemetry — violating the no-secrets-in-payloads
        invariant (INVARIANTS.json #7 / dispatch test_secrets_not_in_log_payloads).
        """
        calls: list[tuple[str, dict]] = []

        def capture_telemetry(kind, payload, *, run_id, repo_root):
            calls.append((kind, payload))

        monkeypatch.setattr(
            "runtime.drivers.omp.subprocess_driver.subprocess.Popen",
            MagicMock(return_value=_proc(stdout=b"done\n")),
        )
        monkeypatch.setattr(
            "runtime.drivers.omp.subprocess_driver._fire_telemetry",
            capture_telemetry,
        )

        sensitive_model = "anthropic/claude-opus-4.5-top-secret"
        sensitive_session = "secret-session-id-abc"
        sensitive_profile = "confidential-profile"

        _driver({
            "model": sensitive_model,
            "profile": sensitive_profile,
            "session_id": sensitive_session,
        }).dispatch("z-execute", ["prompt"], {})

        invoke_payloads = [p for k, p in calls if k == "omp_driver_invoke"]
        assert invoke_payloads, "No omp_driver_invoke event"
        redacted_str = str(invoke_payloads[0].get("args_redacted", []))

        assert sensitive_model not in redacted_str, (
            f"Sensitive model name leaked in args_redacted: {redacted_str}"
        )
        assert sensitive_session not in redacted_str, (
            f"Sensitive session ID leaked in args_redacted: {redacted_str}"
        )
        assert sensitive_profile not in redacted_str, (
            f"Sensitive profile name leaked in args_redacted: {redacted_str}"
        )
        # Placeholder must appear in its place.
        assert "<redacted>" in redacted_str, (
            f"Expected '<redacted>' placeholder in args_redacted: {redacted_str}"
        )

    def test_error_result_emits_omp_driver_error_not_complete(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Non-zero exit emits omp_driver_error telemetry event, not omp_driver_complete.

        Regression: if the error-path telemetry is unified with the success path,
        the analysis layer cannot distinguish failed runs without inspecting
        exit_code — making error-rate queries ambiguous.
        """
        calls: list[tuple[str, dict]] = []

        def capture_telemetry(kind, payload, *, run_id, repo_root):
            calls.append((kind, payload))

        monkeypatch.setattr(
            "runtime.drivers.omp.subprocess_driver.subprocess.Popen",
            MagicMock(return_value=_proc(stdout=b"fail\n", returncode=2)),
        )
        monkeypatch.setattr(
            "runtime.drivers.omp.subprocess_driver._fire_telemetry",
            capture_telemetry,
        )

        handle = _driver({"model": "m"}).dispatch("z-execute", ["prompt"], {})
        list(handle.events())
        handle.wait()

        kind_names = [k for k, _ in calls]
        assert "omp_driver_error" in kind_names, (
            f"Expected omp_driver_error for non-zero exit; got telemetry kinds: {kind_names}"
        )
        assert "omp_driver_complete" not in kind_names, (
            f"omp_driver_complete must not fire on error; got: {kind_names}"
        )


# ---------------------------------------------------------------------------
# (e) Multi-agent command path — z-execute-style multi-event sequence
# ---------------------------------------------------------------------------


class TestMultiAgentCommandPath:
    """Failure class: OMP cannot execute the multi-agent command path.

    Claude's native mode handles a z-execute run that includes subagent fan-out,
    tool calls, user gates, and a final_result in one streaming session.  These
    tests exercise the full event sequence that a multi-agent /z-* command
    produces and assert that all event kinds are preserved in sequence.
    """

    def test_full_z_execute_sequence_all_event_kinds_preserved(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """All event kinds in a z-execute multi-agent sequence are preserved in order.

        Regression: if any parsing branch drops a frame type (subagent, tool_call,
        ask_user, assistant_delta), the dispatcher receives an incomplete event
        stream and cannot reconstruct the execution trace.
        """
        stdout = b"".join([
            b'{"type":"assistant_delta","text":"Starting implementation"}\n',
            b'{"type":"subagent","agent":"implementer","status":"started"}\n',
            b'{"type":"tool","name":"Read","input":{"path":"TASKS.md"}}\n',
            b'{"type":"AskUserQuestion","question":"Confirm approach?"}\n',
            b'{"type":"subagent","agent":"implementer","status":"completed"}\n',
            b'{"type":"final_result","result":"T008 implemented"}\n',
        ])
        monkeypatch.setattr(
            "runtime.drivers.omp.subprocess_driver.subprocess.Popen",
            MagicMock(return_value=_proc(stdout=stdout)),
        )
        monkeypatch.setattr("runtime.drivers.omp.subprocess_driver._fire_telemetry", MagicMock())

        handle = _driver({"model": "m"}).dispatch("z-execute", ["implement T008"], {})
        events = list(handle.events())
        result = handle.wait()

        kinds = [e["kind"] for e in events]
        assert "prompt_submitted" in kinds, f"prompt_submitted missing: {kinds}"
        assert "assistant_delta" in kinds, f"assistant_delta missing: {kinds}"
        assert "subagent" in kinds, f"subagent missing: {kinds}"
        assert "tool_call" in kinds, f"tool_call missing: {kinds}"
        assert "ask_user" in kinds, f"ask_user missing: {kinds}"
        assert "final_result" in kinds, f"final_result missing: {kinds}"

        # Verify sequence is 1-based and contiguous.
        sequences = [e["sequence"] for e in events]
        assert sequences == list(range(1, len(events) + 1)), (
            f"Event sequence not 1-based contiguous: {sequences}"
        )
        # Verify driver tag on every event.
        assert all(e["driver"] == "omp" for e in events), (
            f"Not all events tagged driver='omp': {[(e['kind'], e.get('driver')) for e in events]}"
        )
        # Verify final result is correct.
        assert result.stdout == "T008 implemented", f"Unexpected final result: {result.stdout!r}"
        assert result.is_error is False

    def test_z_execute_final_result_not_flattened_to_prose(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """final_result from OMP's explicit frame is used, not synthesised from prose chunks.

        Regression: if the driver ignores the explicit final_result JSON frame and
        synthesises result.stdout by joining assistant_delta chunks, the result
        text may differ from what OMP intended (e.g. contains incremental text
        instead of the resolved answer).
        """
        stdout = b"".join([
            b'{"type":"assistant_delta","text":"thinking step 1"}\n',
            b'{"type":"assistant_delta","text":"thinking step 2"}\n',
            b'{"type":"final_result","result":"ACTUAL ANSWER"}\n',
        ])
        monkeypatch.setattr(
            "runtime.drivers.omp.subprocess_driver.subprocess.Popen",
            MagicMock(return_value=_proc(stdout=stdout)),
        )
        monkeypatch.setattr("runtime.drivers.omp.subprocess_driver._fire_telemetry", MagicMock())

        handle = _driver({"model": "m"}).dispatch("z-execute", ["what is the answer?"], {})
        list(handle.events())
        result = handle.wait()

        assert result.stdout == "ACTUAL ANSWER", (
            f"Final result was not taken from explicit final_result frame; got: {result.stdout!r}"
        )
        assert "thinking step 1" not in result.stdout, (
            f"Prose chunks leaked into final result: {result.stdout!r}"
        )

    def test_event_envelope_fields_match_claude_expectations(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Every OMP event envelope has driver, command_id, session_id, sequence, kind, payload.

        Regression: if any envelope field is dropped, consumers that expect the
        same schema as SubprocessClaudeDriver events will KeyError or silently
        mis-attribute events.
        """
        stdout = b'{"type":"final_result","result":"parity check"}\n'
        monkeypatch.setattr(
            "runtime.drivers.omp.subprocess_driver.subprocess.Popen",
            MagicMock(return_value=_proc(stdout=stdout)),
        )
        monkeypatch.setattr("runtime.drivers.omp.subprocess_driver._fire_telemetry", MagicMock())

        handle = _driver({"model": "m", "session_id": "ses-abc"}).dispatch(
            "z-execute", ["--session", "ses-abc", "parity check"], {}
        )
        events = list(handle.events())
        handle.wait()

        required_envelope_fields = {"driver", "command_id", "session_id", "sequence", "kind", "payload"}
        for event in events:
            missing = required_envelope_fields - set(event.keys())
            assert not missing, (
                f"Event missing envelope fields {missing}: {event}"
            )
            assert event["driver"] == "omp", f"driver field wrong: {event}"
            assert event["command_id"] == "z-execute", f"command_id wrong: {event}"
            assert isinstance(event["sequence"], int), f"sequence not int: {event}"
            assert event["sequence"] >= 1, f"sequence < 1: {event}"
            assert isinstance(event["payload"], dict), f"payload not dict: {event}"

    def test_result_stdout_events_matches_collected_events(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """result.stdout_events is exactly the same list as events() yielded.

        Regression: if wait() returns a different collection than events() yields,
        post-dispatch analysis on result.stdout_events will miss or duplicate
        events relative to the live stream — making retry logic unreliable.
        """
        stdout = b"".join([
            b'{"type":"subagent","agent":"explore","status":"done"}\n',
            b'{"type":"final_result","result":"ok"}\n',
        ])
        monkeypatch.setattr(
            "runtime.drivers.omp.subprocess_driver.subprocess.Popen",
            MagicMock(return_value=_proc(stdout=stdout)),
        )
        monkeypatch.setattr("runtime.drivers.omp.subprocess_driver._fire_telemetry", MagicMock())

        handle = _driver({"model": "m"}).dispatch("z-execute", ["go"], {})
        streamed_events = list(handle.events())
        result = handle.wait()

        assert result.stdout_events == streamed_events, (
            f"result.stdout_events differs from streamed events:\n"
            f"  streamed: {[e['kind'] for e in streamed_events]}\n"
            f"  result:   {[e['kind'] for e in result.stdout_events]}"
        )
