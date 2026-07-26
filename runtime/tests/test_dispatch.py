"""
Unit tests for the dispatch subsystem.

Covers:
- HostDriver ABC cannot be instantiated directly.
- SelfHostDriver-like context injection (M1).
- env.py: CLAUDECODE always set to ""; auth_env injection; input dict immutability.
- env.py missing-var (m7): missing auth_env var is omitted from result.
- env.py no ENV_STRIP_LIST (m1): sensitive-looking vars pass through unstripped.
- Secrets-not-in-payload (M3, Invariant #7): no secret value in log payloads.
- TimeoutReaper SIGTERM (existing): process reaped within 6s.
- TimeoutReaper SIGKILL escalation (M4): TERM-ignoring process killed within 11s.
- Malformed-stream interleaving (M4): parse errors recorded; valid events kept.
- DispatchResult.success returns correct values.

Run with:
    python -m pytest runtime/tests/test_dispatch.py -v
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from dataclasses import replace
from pathlib import Path

import pytest

from runtime.capability_authority import (
    AUTHORITY_VERSION,
    Capability,
    CapabilityAuthority,
    CapabilityEvidence,
    CapabilityKey,
)
from runtime.dispatch.driver import DispatchHandle, HostDriver
from runtime.dispatch.dispatcher import (
    Dispatcher,
    _compose_argv,
    _current_host_family,
    _host_family,
    load_model_routing_config,
    resolve_implementer_model,
    resolve_model_route,
    resolve_native_agent_model,
)
from runtime.dispatch.env import build_env
from runtime.dispatch.result import DispatchResult
from runtime.dispatch.timeout import DispatchTimeoutError, TimeoutReaper
from runtime.orchestration_boundary import (
    AdmissionDenied,
    AdmissionRequest,
    BoundarySources,
    OrchestrationBoundary,
    TransitionIds,
)
from runtime.orchestration_ledger import OrchestrationLedger

REPO_ROOT = Path(__file__).resolve().parents[2]
ZEXECUTE_SKILL_PATH = REPO_ROOT / "skills" / "z-execute" / "SKILL.md"


# ---------------------------------------------------------------------------
# Helpers / shared fixtures
# ---------------------------------------------------------------------------


def _make_dispatcher(tmp_path):
    """Return a Dispatcher bound to a tmp repo_root and synthetic run_id."""
    return Dispatcher(repo_root=str(tmp_path), run_id="test-run-001")


class _MinimalDriver(HostDriver):
    """Minimal concrete HostDriver that returns empty events and a fixed result."""

    def init(self, provider_config, context=None):
        self._config = provider_config
        self._context = context or {}

    def dispatch(self, command_id, args, env):
        return DispatchHandle(
            _events_fn=lambda: iter([]),
            _wait_fn=lambda: DispatchResult(exit_code=0, is_error=False),
        )


class _CountingDriver(_MinimalDriver):
    """Driver that records each costly dispatch callback."""

    def __init__(self) -> None:
        self.calls = 0

    def dispatch(self, command_id, args, env):
        self.calls += 1
        return super().dispatch(command_id, args, env)


def _admission(tmp_path: Path) -> tuple[OrchestrationBoundary, AdmissionRequest]:
    """Return a degraded boundary and exact request for dispatcher tests."""

    key = CapabilityKey("codex", "cli", "build-1", "z-execute", "degraded")
    authority = CapabilityAuthority(tmp_path / "authority.json")
    authority.persist(
        CapabilityEvidence(
            evidence_id="dispatch-evidence",
            authority_version=AUTHORITY_VERSION,
            key=key,
            capability=Capability.DEGRADED_SINGLE_AGENT,
            evidence_surface="cli",
            installed_export_fingerprint="export-1",
            issued_at=1,
            expires_at=100,
        )
    )
    boundary = OrchestrationBoundary(
        authority,
        OrchestrationLedger(tmp_path / "ledger.sqlite"),
        BoundarySources(
            supervisor_id="dispatch-supervisor",
            host=lambda: "codex",
            surface=lambda: "cli",
            runtime_build=lambda driver: "build-1",
            installed_export_fingerprint=lambda: "export-1",
            command="z-execute",
            posture="degraded",
            driver_type=_CountingDriver,
            clock=lambda: 2,
        ),
    )
    request = AdmissionRequest(
        logical_work_id="task-1",
        reservation_id="reservation-1",
        writer_id="writer-1",
        transitions=TransitionIds("r", "d", "s", "i", "z"),
    )
    return boundary, request


def test_public_run_reserves_before_driver_dispatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The dispatcher invokes its driver only after executable admission."""

    boundary, request = _admission(tmp_path)
    driver = _CountingDriver()
    driver.init({"args_template": []})
    monkeypatch.setattr(
        "runtime.dispatch.dispatcher.log_event", lambda *args, **kwargs: None
    )

    result = Dispatcher(
        repo_root=str(tmp_path),
        run_id="untrusted-run",
        orchestration_boundary=boundary,
    ).run(
        driver,
        "/z-execute",
        [],
        {"args_template": []},
        admission=request,
    )

    assert result.success is True
    assert driver.calls == 1


def test_public_run_mismatched_driver_never_calls_driver(tmp_path: Path) -> None:
    """The public entrypoint binds admission to the actual driver type."""

    boundary, request = _admission(tmp_path)
    driver = _MinimalDriver()
    driver.init({"args_template": []})

    with pytest.raises(AdmissionDenied, match="boundary_driver_mismatch"):
        Dispatcher(
            repo_root=str(tmp_path),
            run_id="untrusted-run",
            orchestration_boundary=boundary,
        ).run(
            driver,
            "/z-execute",
            [],
            {"args_template": []},
            admission=request,
        )


def test_public_run_without_boundary_fails_before_driver(tmp_path: Path) -> None:
    """Production callers cannot reach raw dispatch through ``run``."""

    driver = _CountingDriver()
    driver.init({"args_template": []})
    with pytest.raises(AdmissionDenied, match="requires executable admission"):
        _make_dispatcher(tmp_path).run(
            driver,
            "/z-execute",
            [],
            {"args_template": []},
        )
    assert driver.calls == 0


# ---------------------------------------------------------------------------
# HostDriver ABC cannot be instantiated directly
# ---------------------------------------------------------------------------


def test_host_driver_abstract_cannot_instantiate():
    """HostDriver is abstract; direct instantiation raises TypeError."""
    with pytest.raises(TypeError):
        HostDriver()  # type: ignore[abstract]


# ---------------------------------------------------------------------------
# SelfHostDriver-like context injection (M1)
# ---------------------------------------------------------------------------


class _ContextAwareDriver(HostDriver):
    """Mock driver that stores tools_registry from context."""

    def init(self, provider_config, context=None):
        ctx = context or {}
        self._tools_registry = ctx.get("tools_registry", {})

    def dispatch(self, command_id, args, env):
        return DispatchHandle(
            _events_fn=lambda: iter([]),
            _wait_fn=lambda: DispatchResult(exit_code=0, is_error=False),
        )


class _ContextIgnoringDriver(HostDriver):
    """Mock driver that silently ignores all context keys."""

    def init(self, provider_config, context=None):
        # Deliberately ignore context entirely.
        pass

    def dispatch(self, command_id, args, env):
        return DispatchHandle(
            _events_fn=lambda: iter([]),
            _wait_fn=lambda: DispatchResult(exit_code=0, is_error=False),
        )


def test_context_aware_driver_receives_tools_registry():
    """A SelfHostDriver-like subclass can receive and store tools_registry from context."""
    def fake_read(path):
        return "contents"

    ctx = {"tools_registry": {"Read": fake_read}}
    driver = _ContextAwareDriver()
    driver.init({"args_template": []}, context=ctx)

    assert "Read" in driver._tools_registry
    assert driver._tools_registry["Read"] is fake_read


def test_context_ignoring_driver_does_not_error():
    """A driver that ignores context can be instantiated with arbitrary context keys."""
    driver = _ContextIgnoringDriver()
    # Must not raise regardless of what context keys are present.
    driver.init({"args_template": []}, context={"some_key": "x"})


# ---------------------------------------------------------------------------
# Future pipelined scheduler contract (T005 structural guard)
# ---------------------------------------------------------------------------


def test_future_pipelined_scheduler_requires_durable_background_handles():
    """The docs-only scheduler contract requires durable handles, not sync Agent() only."""
    text = ZEXECUTE_SKILL_PATH.read_text(encoding="utf-8")
    start = text.index("FUTURE PIPELINED TRACK CONTRACT")
    contract = text[start:start + 4500]

    assert "Background-handle expectation" in contract
    assert "durable background handle" in contract
    assert "poll/cancel/result semantics" in contract
    assert "synchronous Agent()" in contract
    assert "stores no durable handle/state does not satisfy this contract" in contract


def test_current_dispatcher_has_no_runtime_pipelined_refill_surface():
    """T005 must not ship a live pipelined refill scheduler in runtime dispatch."""
    dispatcher_text = (REPO_ROOT / "runtime" / "dispatch" / "dispatcher.py").read_text(
        encoding="utf-8"
    )

    for forbidden in (
        "pipelined_refill",
        "PipelinedTrack",
        "background_handle_id",
        "refill_cursor",
        "track_state_table",
    ):
        assert forbidden not in dispatcher_text


# ---------------------------------------------------------------------------
# env.py tests
# ---------------------------------------------------------------------------


def test_build_env_claudecode_always_set():
    """build_env always sets CLAUDECODE to empty string."""
    result = build_env({}, base_env={})
    assert result["CLAUDECODE"] == ""


def test_build_env_claudecode_overwrites_existing():
    """build_env sets CLAUDECODE="" even if base_env has a different value."""
    result = build_env({}, base_env={"CLAUDECODE": "1"})
    assert result["CLAUDECODE"] == ""


def test_build_env_auth_env_injection():
    """build_env injects the named auth var from base_env into the returned dict."""
    base = {"MY_TOKEN": "abc123", "OTHER": "val"}
    result = build_env({"auth_env": "MY_TOKEN"}, base_env=base)
    assert result["MY_TOKEN"] == "abc123"
    assert result["OTHER"] == "val"


def test_build_env_does_not_mutate_input_dict():
    """build_env never mutates the base_env dict passed by the caller."""
    base = {"SOME_VAR": "original", "OTHER": "value"}
    original_copy = dict(base)
    build_env({"auth_env": "SOME_VAR"}, base_env=base)
    assert base == original_copy, "build_env mutated the input dict"


def test_build_env_missing_auth_var_omits_key():
    """build_env omits the auth var key when it is absent from base_env (m7)."""
    # base_env explicitly does not contain MISSING_VAR.
    base = {"OTHER_KEY": "some_value"}
    result = build_env({"auth_env": "MISSING_VAR"}, base_env=base)
    assert "MISSING_VAR" not in result
    # Must not be set to empty string either.
    assert result.get("MISSING_VAR") is None


def test_build_env_no_env_strip_list(monkeypatch):
    """Sensitive-looking var names pass through unstripped (m1: no ENV_STRIP_LIST)."""
    base = {
        "MY_SECRET_TOKEN": "super_secret",
        "ANOTHER_KEY": "plain_value",
    }
    result = build_env({}, base_env=base)
    assert result["MY_SECRET_TOKEN"] == "super_secret"
    assert result["ANOTHER_KEY"] == "plain_value"


# ---------------------------------------------------------------------------
# Secrets not in payload (M3, SPEC Invariant #7)
# ---------------------------------------------------------------------------


def test_secrets_not_in_log_payloads(monkeypatch, tmp_path):
    """No log payload contains the secret value when auth_env is in provider_config."""
    captured: list[tuple[str, dict]] = []

    def mock_log_event(run_id, kind, payload, repo_root, slug=None):
        captured.append((kind, payload))

    monkeypatch.setattr("runtime.dispatch.dispatcher.log_event", mock_log_event)
    monkeypatch.setenv("FAKE_API_KEY", "SECRET_VALUE_DO_NOT_LEAK")

    driver = _MinimalDriver()
    provider_config = {
        "args_template": [],
        "auth_env": "FAKE_API_KEY",
    }
    driver.init(provider_config)

    dispatcher = _make_dispatcher(tmp_path)
    dispatcher.run(driver, "z-ask", [], provider_config)

    assert len(captured) >= 2, "Expected at least dispatch_start and dispatch_end events"
    for kind, payload in captured:
        serialized = json.dumps(payload)
        assert "SECRET_VALUE_DO_NOT_LEAK" not in serialized, (
            f"Secret leaked in '{kind}' payload: {serialized}"
        )


# ---------------------------------------------------------------------------
# TimeoutReaper: SIGTERM (existing test)
# ---------------------------------------------------------------------------


def test_timeout_reaper_sigterm_reaps_within_6s():
    """TimeoutReaper sends SIGTERM; process that accepts TERM is reaped within 6s."""
    proc = subprocess.Popen(["sleep", "999"])
    t0 = time.monotonic()

    with pytest.raises(DispatchTimeoutError):
        with TimeoutReaper(proc, timeout_s=1):
            proc.wait()

    elapsed = time.monotonic() - t0
    assert proc.poll() is not None, "Process was not reaped"
    assert elapsed < 6, f"Took too long to reap: {elapsed:.2f}s"


# ---------------------------------------------------------------------------
# TimeoutReaper: SIGKILL escalation (M4)
# ---------------------------------------------------------------------------


def test_timeout_reaper_sigkill_escalation():
    """TimeoutReaper escalates to SIGKILL for a process that traps (ignores) SIGTERM.

    Design note: TimeoutReaper's _on_timeout sends SIGTERM to unblock proc.wait().
    For processes that ignore SIGTERM, proc.wait() never unblocks, so we cannot
    call proc.wait() inside the ``with`` block. Instead, the test lets the timeout
    fire (sending SIGTERM, which gets ignored by the shell), then exits the ``with``
    block normally — triggering __exit__ which calls _reap(). _reap() sends SIGTERM,
    waits 5s, then sends SIGKILL. The total wall time (timeout_s + 5s wait + kill)
    must be under 11s.
    """
    proc = subprocess.Popen(["sh", "-c", "trap '' TERM; sleep 999"])
    t0 = time.monotonic()

    with pytest.raises(DispatchTimeoutError):
        with TimeoutReaper(proc, timeout_s=1):
            # Wait for the timer to fire (slightly longer than timeout_s) so
            # _on_timeout runs and marks _timed_out = True, then exit normally.
            # The __exit__ will see _timed_out=True and proc still alive,
            # call _reap() (SIGTERM → 5s wait → SIGKILL), then raise.
            time.sleep(1.5)

    elapsed = time.monotonic() - t0
    # Expected: 1s timer fires + 1.5s sleep exits + 5s reap wait + SIGKILL
    # Total is at most ~8s, comfortably under 11s.
    assert proc.poll() is not None, "Process was not reaped after SIGKILL"
    assert elapsed < 11, f"SIGKILL escalation took too long: {elapsed:.2f}s"


# ---------------------------------------------------------------------------
# Malformed-stream interleaving (M4)
# ---------------------------------------------------------------------------


def _malformed_stream_events():
    """Generator that yields a valid event, raises JSONDecodeError, yields another valid event."""
    yield {"valid": 1}
    raise json.JSONDecodeError("Expecting value", "bad json", 0)
    yield {"valid": 2}  # noqa: unreachable — iterator resumes after exception? No.
    # Note: once a generator raises an exception, it is exhausted. The test
    # driver wraps this to simulate three distinct "chunks" from a stream.


class _MalformedStreamDriver(HostDriver):
    """Driver whose events() yields {"valid":1}, raises JSONDecodeError, then yields {"valid":2}.

    Implementation note: ``DispatchHandle.events()`` uses ``yield from _events_fn()``,
    which terminates the generator on any non-StopIteration exception raised by the
    sub-iterator.  To test that the dispatcher's JSONDecodeError swallowing works
    across multiple valid events, we subclass ``DispatchHandle`` and override
    ``events()`` to return the stateful ``_ThreePhaseIter`` directly (not as a
    generator).  This means the dispatcher's ``iter(handle.events())`` wraps the
    iterator, and each ``next()`` call goes straight to ``_ThreePhaseIter.__next__``,
    whose state persists across raises so ``{"valid": 2}`` is reachable.
    """

    def init(self, provider_config, context=None):
        pass

    def dispatch(self, command_id, args, env):
        class _ThreePhaseIter:
            """Yields two events with a JSONDecodeError in between."""
            def __init__(self):
                self._phase = 0

            def __iter__(self):
                return self

            def __next__(self):
                if self._phase == 0:
                    self._phase = 1
                    return {"valid": 1}
                elif self._phase == 1:
                    self._phase = 2
                    raise json.JSONDecodeError("Expecting value", "bad json line", 0)
                elif self._phase == 2:
                    self._phase = 3
                    return {"valid": 2}
                else:
                    raise StopIteration

        iter_obj = _ThreePhaseIter()

        class _MalformedHandle(DispatchHandle):
            def events(self):
                # Return the stateful iterator directly (not via yield-from).
                # This ensures JSONDecodeError raised in __next__ is caught by
                # the dispatcher's loop, and the iterator can continue afterward.
                return iter_obj

        return _MalformedHandle(
            _events_fn=lambda: iter_obj,
            _wait_fn=lambda: DispatchResult(exit_code=0, is_error=False, stderr=""),
        )


def test_malformed_stream_collects_valid_events_and_records_error(monkeypatch, tmp_path):
    """Dispatcher collects both valid events and records JSONDecodeError in stderr; no crash."""

    def mock_log_event(run_id, kind, payload, repo_root, slug=None):
        pass  # suppress actual shell calls

    monkeypatch.setattr("runtime.dispatch.dispatcher.log_event", mock_log_event)

    driver = _MalformedStreamDriver()
    provider_config = {"args_template": []}
    driver.init(provider_config)

    dispatcher = _make_dispatcher(tmp_path)
    result = dispatcher.run(driver, "z-ask", [], provider_config)

    # Both valid events must be collected.
    assert {"valid": 1} in result.stdout_events, (
        f"Missing first valid event; got stdout_events={result.stdout_events}"
    )
    assert {"valid": 2} in result.stdout_events, (
        f"Missing second valid event; got stdout_events={result.stdout_events}"
    )

    # The parse error must be recorded in result.stderr.
    assert result.stderr, "Expected parse error info in result.stderr"
    assert "JSONDecodeError" in result.stderr, (
        f"Expected 'JSONDecodeError' in stderr; got: {result.stderr!r}"
    )


# ---------------------------------------------------------------------------
# T010: Dispatcher.run override kwargs
# ---------------------------------------------------------------------------


def _capture_events(monkeypatch):
    """Return a (captured list, mock_log_event fn) pair for monkeypatching."""
    captured: list[tuple[str, dict]] = []

    def mock_log_event(run_id, kind, payload, repo_root, slug=None):
        captured.append((kind, payload))

    monkeypatch.setattr("runtime.dispatch.dispatcher.log_event", mock_log_event)
    return captured


def test_run_no_kwargs_backward_compat(monkeypatch, tmp_path):
    """Existing callers (no new kwargs) compile and run unchanged."""
    captured = _capture_events(monkeypatch)

    driver = _MinimalDriver()
    provider_config = {"args_template": []}
    driver.init(provider_config)

    dispatcher = _make_dispatcher(tmp_path)
    result = dispatcher.run(driver, "z-ask", [], provider_config)

    assert result.exit_code == 0
    kinds = [k for k, _ in captured]
    assert "dispatch_start" in kinds
    assert "dispatch_end" in kinds
    assert "model_resolved" in kinds
    # No override event when no kwargs passed.
    assert "persona_override_used" not in kinds


def test_run_model_override_emits_event(monkeypatch, tmp_path):
    """Passing model='opus' emits persona_override_used with override_field='model'."""
    captured = _capture_events(monkeypatch)

    driver = _MinimalDriver()
    provider_config = {"args_template": [], "model": "sonnet"}
    driver.init(provider_config)

    dispatcher = _make_dispatcher(tmp_path)
    dispatcher.run(driver, "z-plan", [], provider_config, model="opus")

    override_events = [(k, p) for k, p in captured if k == "persona_override_used"]
    assert len(override_events) == 1, f"Expected 1 persona_override_used, got {override_events}"
    _, payload = override_events[0]
    assert payload["override_field"] == "model"
    assert payload["value"] == "opus"
    assert payload["original"] == "sonnet"


def test_run_model_and_runtime_overrides_emit_events(monkeypatch, tmp_path):
    """Passing model + runtime kwargs emits a persona_override_used event per axis."""
    captured = _capture_events(monkeypatch)

    driver = _MinimalDriver()
    provider_config = {"args_template": []}
    driver.init(provider_config)

    dispatcher = _make_dispatcher(tmp_path)
    dispatcher.run(
        driver, "z-ask", [], provider_config,
        model="M", runtime="R",
    )

    override_events = [(k, p) for k, p in captured if k == "persona_override_used"]
    fields = {p["override_field"] for _, p in override_events}
    assert fields == {"model", "runtime"}


# ---------------------------------------------------------------------------
# T101: model_env_var wired through Dispatcher.run → build_env
# ---------------------------------------------------------------------------


class _EnvCapturingDriver(HostDriver):
    """Driver that captures the env dict passed to dispatch()."""

    def init(self, provider_config, context=None):
        self._captured_env: dict | None = None

    def dispatch(self, command_id, args, env):
        self._captured_env = dict(env)
        return DispatchHandle(
            _events_fn=lambda: iter([]),
            _wait_fn=lambda: DispatchResult(exit_code=0, is_error=False),
        )


def test_dispatcher_run_passes_resolved_model_to_build_env_via_model_env_var(
    monkeypatch, tmp_path
):
    """Dispatcher.run wires effective_model into build_env when model_env_var is configured.

    Failure class: If build_env is called without effective_model (or before
    _resolved_model is computed), model_env_var will be absent from the
    subprocess env — verifiable by inspecting the env dict captured inside
    dispatch().
    """

    def mock_log_event(run_id, kind, payload, repo_root, slug=None):
        pass  # suppress shell calls

    monkeypatch.setattr("runtime.dispatch.dispatcher.log_event", mock_log_event)

    provider_config = {
        "args_template": [],
        "model": "haiku",  # base model from provider_config
        "model_env_var": "CLAUDE_MODEL",
    }

    driver = _EnvCapturingDriver()
    driver.init(provider_config)

    dispatcher = _make_dispatcher(tmp_path)
    # Pass a caller-side model override; this becomes _resolved_model="opus".
    dispatcher.run(driver, "z-ask", [], provider_config, model="opus")

    assert driver._captured_env is not None, "dispatch() was never called"
    assert "CLAUDE_MODEL" in driver._captured_env, (
        "model_env_var 'CLAUDE_MODEL' missing from subprocess env"
    )
    assert driver._captured_env["CLAUDE_MODEL"] == "opus", (
        f"Expected CLAUDE_MODEL='opus' (resolved override), "
        f"got {driver._captured_env['CLAUDE_MODEL']!r}"
    )


def test_dispatcher_run_model_env_var_uses_provider_config_model_when_no_override(
    monkeypatch, tmp_path
):
    """Without a model override, model_env_var is set to provider_config['model'].

    Failure class: If build_env receives effective_model=None (regression),
    the env var will not be set from provider_config['model'], causing the
    subprocess to receive no model.
    """

    def mock_log_event(run_id, kind, payload, repo_root, slug=None):
        pass

    monkeypatch.setattr("runtime.dispatch.dispatcher.log_event", mock_log_event)

    provider_config = {
        "args_template": [],
        "model": "sonnet",
        "model_env_var": "CLAUDE_MODEL",
    }

    driver = _EnvCapturingDriver()
    driver.init(provider_config)

    dispatcher = _make_dispatcher(tmp_path)
    dispatcher.run(driver, "z-ask", [], provider_config)  # no model kwarg

    assert driver._captured_env is not None
    assert driver._captured_env.get("CLAUDE_MODEL") == "sonnet", (
        f"Expected CLAUDE_MODEL='sonnet' from provider_config, "
        f"got {driver._captured_env.get('CLAUDE_MODEL')!r}"
    )


# ---------------------------------------------------------------------------
# DispatchResult.success
# ---------------------------------------------------------------------------


def test_dispatch_result_success_exit0_no_error():
    """DispatchResult.success is True when exit_code=0 and is_error=False."""
    r = DispatchResult(exit_code=0, is_error=False)
    assert r.success is True


def test_dispatch_result_success_exit1_no_error():
    """DispatchResult.success is False when exit_code=1 (non-zero exit)."""
    r = DispatchResult(exit_code=1, is_error=False)
    assert r.success is False


def test_dispatch_result_success_exit0_with_error():
    """DispatchResult.success is False when is_error=True even if exit_code=0."""
    r = DispatchResult(exit_code=0, is_error=True)
    assert r.success is False


# ---------------------------------------------------------------------------
# T003: {model} substitution in model_arg_template
# ---------------------------------------------------------------------------


class _ArgsCapturingDriver(HostDriver):
    """Driver that captures the args list passed to dispatch()."""

    def init(self, provider_config, context=None):
        self._captured_args: list[str] | None = None

    def dispatch(self, command_id, args, env):
        self._captured_args = list(args)
        return DispatchHandle(
            _events_fn=lambda: iter([]),
            _wait_fn=lambda: DispatchResult(exit_code=0, is_error=False),
        )


def test_compose_argv_model_arg_template_substituted():
    """_compose_argv renders {model} from model_arg_template when model_arg_template is set.

    Failure class: If {model} substitution is missing, the returned argv will
    contain the literal string '{model}' instead of the resolved model name,
    causing the provider CLI to receive an invalid model argument.
    """
    provider_config = {
        "args_template": ["-p", "--output-format", "text"],
        "model_arg_template": ["--model", "{model}"],
        "default_model": "auto",
    }
    argv = _compose_argv(provider_config, effective_model="grok-4.3")
    assert "--model" in argv, f"Expected '--model' in argv; got {argv}"
    assert "grok-4.3" in argv, f"Expected 'grok-4.3' in argv; got {argv}"
    assert "{model}" not in argv, f"Unreplaced '{{model}}' placeholder remains in {argv}"


def test_compose_argv_null_model_arg_template_unaffected():
    """_compose_argv with null model_arg_template returns args_template unchanged.

    Failure class: If the null-template guard is removed, providers without
    model_arg_template would attempt model resolution and may raise ValueError
    or inject unexpected args.
    """
    provider_config = {
        "args_template": ["exec", "-"],
        "model_arg_template": None,
        "default_model": None,
    }
    argv = _compose_argv(provider_config, effective_model="grok-4.3")
    assert argv == ["exec", "-"], f"Unexpected argv modification; got {argv}"


def test_compose_argv_uses_default_model_when_no_effective_model():
    """_compose_argv falls back to default_model when effective_model is None.

    Failure class: If the fallback to default_model is not implemented,
    dispatching with no explicit model override will raise ValueError even
    when the provider declares a default_model.
    """
    provider_config = {
        "args_template": ["-p"],
        "model_arg_template": ["--model", "{model}"],
        "default_model": "auto",
    }
    argv = _compose_argv(provider_config, effective_model=None)
    assert "auto" in argv, f"Expected 'auto' (default_model) in argv; got {argv}"


def test_compose_argv_raises_when_no_model_resolvable():
    """_compose_argv raises ValueError when model_arg_template is set but no model available.

    Failure class: If ValueError is not raised, the provider CLI receives
    '--model {model}' literally — a silent misconfiguration that is harder to
    debug than an explicit error.
    """
    provider_config = {
        "args_template": ["-p"],
        "model_arg_template": ["--model", "{model}"],
        "default_model": None,
    }
    with pytest.raises(ValueError, match="default_model"):
        _compose_argv(provider_config, effective_model=None)


def test_dispatcher_run_cursor_with_model_yields_model_in_argv(monkeypatch, tmp_path):
    """Dispatcher.run with cursor provider config and effective model grok-4.3 includes --model grok-4.3 in final_args.

    Failure class: If the dispatcher still uses raw args_template + caller_args
    (without model_arg_template substitution), dispatching cursor@grok-4.3 will
    silently omit the --model flag, causing the wrong model to run.
    """

    def mock_log_event(run_id, kind, payload, repo_root, slug=None):
        pass

    monkeypatch.setattr("runtime.dispatch.dispatcher.log_event", mock_log_event)

    # Cursor provider config as it appears in .z-harness/providers.json after T003.
    cursor_provider_config = {
        "args_template": ["-p", "--output-format", "text"],
        "model_arg_template": ["--model", "{model}"],
        "default_model": "auto",
    }

    driver = _ArgsCapturingDriver()
    driver.init(cursor_provider_config)

    dispatcher = _make_dispatcher(tmp_path)
    dispatcher.run(driver, "z-plan", [], cursor_provider_config, model="grok-4.3")

    assert driver._captured_args is not None, "dispatch() was never called"
    assert "--model" in driver._captured_args, (
        f"'--model' missing from final_args; got {driver._captured_args}"
    )
    assert "grok-4.3" in driver._captured_args, (
        f"'grok-4.3' missing from final_args; got {driver._captured_args}"
    )


def test_dispatcher_run_null_model_arg_template_unaffected(monkeypatch, tmp_path):
    """Dispatcher.run with a provider that has null model_arg_template does not inject model arg.

    Failure class: If the null-template guard is missing in the dispatcher,
    providers like codex-cli (which control model selection internally)
    would receive unexpected --model flags.
    """

    def mock_log_event(run_id, kind, payload, repo_root, slug=None):
        pass

    monkeypatch.setattr("runtime.dispatch.dispatcher.log_event", mock_log_event)

    codex_provider_config = {
        "args_template": ["exec", "-"],
        "model_arg_template": None,
        "default_model": None,
    }

    driver = _ArgsCapturingDriver()
    driver.init(codex_provider_config)

    dispatcher = _make_dispatcher(tmp_path)
    dispatcher.run(driver, "z-review", [], codex_provider_config, model="gpt-5-codex")

    assert driver._captured_args is not None
    # caller_args is empty; args_template unchanged; no --model injected.
    assert driver._captured_args == ["exec", "-"], (
        f"Expected unchanged argv for null model_arg_template; got {driver._captured_args}"
    )



def test_dispatcher_provider_preflight_ok_emitted(monkeypatch, tmp_path):
    captured = _capture_events(monkeypatch)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake = bin_dir / "fake-llm"
    fake.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    fake.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}:{os.environ.get('PATH', '')}")

    provider_config = {
        "provider": "codex-cli",
        "command": "fake-llm",
        "args_template": ["exec", "-"],
        "model_arg_template": None,
        "default_model": None,
    }
    driver = _MinimalDriver()
    driver.init(provider_config)

    dispatcher = _make_dispatcher(tmp_path)
    dispatcher.run(
        driver,
        "z-review",
        [],
        provider_config,
        role="reviewer",
        runtime="codex-cli",
        model="gpt-5-codex",
    )

    preflight = [p for kind, p in captured if kind == "provider_preflight_ok"]
    assert len(preflight) == 1
    payload = preflight[0]
    assert payload["role"] == "reviewer"
    assert payload["provider"] == "codex-cli"
    assert payload["attempted_model"] == "gpt-5-codex"
    assert payload["auth_backend"] == "cli-managed"
    assert payload["auth_ready"] == "not_required"


def test_dispatcher_provider_preflight_missing_command_fails(monkeypatch, tmp_path):
    captured = _capture_events(monkeypatch)
    provider_config = {
        "provider": "missing-provider",
        "command": "definitely-not-on-path-zh",
        "args_template": [],
    }
    driver = _MinimalDriver()
    driver.init(provider_config)

    dispatcher = _make_dispatcher(tmp_path)
    with pytest.raises(RuntimeError, match="provider_preflight_failed"):
        dispatcher.run(
            driver,
            "z-review",
            [],
            provider_config,
            role="reviewer",
            runtime="missing-provider",
        )

    failed = [p for kind, p in captured if kind == "provider_preflight_failed"]
    assert len(failed) == 1
    assert failed[0]["role"] == "reviewer"
    assert failed[0]["provider"] == "missing-provider"
    assert "not on PATH" in failed[0]["reason"]


@pytest.mark.parametrize("command_value", [None, ""])
def test_dispatcher_provider_preflight_empty_command_fails(
    command_value, monkeypatch, tmp_path
):
    captured = _capture_events(monkeypatch)
    provider_config = {
        "provider": "empty-command-provider",
        "args_template": [],
    }
    if command_value is not None:
        provider_config["command"] = command_value
    driver = _MinimalDriver()
    driver.init(provider_config)

    dispatcher = _make_dispatcher(tmp_path)
    with pytest.raises(RuntimeError, match="provider_preflight_failed"):
        dispatcher.run(
            driver,
            "z-review",
            [],
            provider_config,
            role="reviewer",
            runtime="empty-command-provider",
        )

    failed = [p for kind, p in captured if kind == "provider_preflight_failed"]
    assert len(failed) == 1
    assert failed[0]["role"] == "reviewer"
    assert failed[0]["provider"] == "empty-command-provider"
    assert "provider command is empty" in failed[0]["reason"]


def test_dispatcher_provider_preflight_model_composition_failure_emitted(
    monkeypatch, tmp_path
):
    captured = _capture_events(monkeypatch)
    provider_config = {
        "provider": "drifted",
        "args_template": [],
        "model_arg_template": ["--model", "{model}"],
        "default_model": None,
    }
    driver = _MinimalDriver()
    driver.init(provider_config)

    dispatcher = _make_dispatcher(tmp_path)
    with pytest.raises(ValueError, match="default_model"):
        dispatcher.run(driver, "z-review", [], provider_config, role="reviewer")

    failed = [p for kind, p in captured if kind == "provider_preflight_failed"]
    assert len(failed) == 1
    assert failed[0]["provider"] == "drifted"
    assert "argv/model composition failed" in failed[0]["reason"]


def test_dispatcher_provider_metadata_env_reaches_driver(monkeypatch, tmp_path):
    captured = _capture_events(monkeypatch)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake = bin_dir / "fake-llm"
    fake.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    fake.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}:{os.environ.get('PATH', '')}")

    provider_config = {
        "provider": "codex-cli",
        "command": "fake-llm",
        "args_template": [],
        "model_arg_template": None,
        "default_model": None,
    }
    driver = _EnvCapturingDriver()
    driver.init(provider_config)

    dispatcher = _make_dispatcher(tmp_path)
    dispatcher.run(
        driver,
        "z-review",
        [],
        provider_config,
        role="reviewer",
        runtime="codex-cli",
    )

    assert driver._captured_env is not None
    assert driver._captured_env["Z_HARNESS_RUN_ID"] == "test-run-001"
    assert driver._captured_env["Z_HARNESS_PROVIDER_ROLE"] == "reviewer"
    assert [kind for kind, _payload in captured].count("provider_preflight_ok") == 1


# ---------------------------------------------------------------------------
# T002 model routing resolver
# ---------------------------------------------------------------------------


def _routing_defaults() -> dict[str, object]:
    return {
        "model_classes.cheap.model": "haiku",
        "model_classes.cheap.thinking": "",
        "model_classes.cheap.reasoning": "",
        "model_classes.standard.model": "sonnet",
        "model_classes.standard.thinking": "",
        "model_classes.standard.reasoning": "",
        "model_classes.deep.model": "opus",
        "model_classes.deep.thinking": "max",
        "model_classes.deep.reasoning": "extended",
        "model_routing.native_agents.default": "",
        "model_routing.implementer.low": "sonnet",
        "model_routing.implementer.medium": "sonnet",
        "model_routing.implementer.high": "opus",
        "model_routing.implementer.retry": "opus",
    }


def test_model_route_class_expands_model_and_metadata():
    values = _routing_defaults()
    values["model_classes.local_deep.model"] = "claude-opus-4.5"
    values["model_classes.local_deep.thinking"] = "budget:high"
    values["model_classes.local_deep.reasoning"] = "effort:high"

    resolved = resolve_model_route("local_deep", values, source="test")

    assert resolved.effective_model == "claude-opus-4.5"
    assert resolved.route_kind == "class"
    assert resolved.thinking == "budget:high"
    assert resolved.reasoning == "effort:high"


def test_model_route_exact_model_returns_itself():
    resolved = resolve_model_route(
        "anthropic/claude-sonnet-4.5",
        _routing_defaults(),
        source="model_routing.native_agents.explore",
    )

    assert resolved.effective_model == "anthropic/claude-sonnet-4.5"
    assert resolved.route_kind == "exact"
    assert resolved.source == "model_routing.native_agents.explore"


def test_implementer_tier_defaults_preserve_current_labels():
    values = _routing_defaults()

    assert resolve_implementer_model("low", values).effective_model == "sonnet"
    assert resolve_implementer_model("medium", values).effective_model == "sonnet"
    assert resolve_implementer_model("high", values).effective_model == "opus"
    assert resolve_implementer_model("retry", values).effective_model == "opus"


def test_implementer_tier_can_route_through_class():
    values = _routing_defaults()
    values["model_routing.implementer.high"] = "deep"

    resolved = resolve_implementer_model("high", values)

    assert resolved.effective_model == "opus"
    assert resolved.source == "model_routing.implementer.high"
    assert resolved.route == "deep"
    assert resolved.route_kind == "class"


def test_native_agent_exact_default_and_frontmatter_precedence():
    values = _routing_defaults()
    values["model_classes.local_fast.model"] = "ollama/qwen3:8b"
    values["model_classes.local_fast.thinking"] = ""
    values["model_classes.local_fast.reasoning"] = ""
    values["model_routing.native_agents.default"] = "cheap"
    values["model_routing.native_agents.explore"] = "local_fast"

    exact = resolve_native_agent_model("explore", "haiku", values)
    via_default = resolve_native_agent_model("reviewer", "sonnet", values)

    assert exact.effective_model == "ollama/qwen3:8b"
    assert exact.source == "model_routing.native_agents.explore"
    values["model_routing.native_agents.auditor"] = "anthropic/claude-sonnet-4.5"
    exact_model = resolve_native_agent_model("auditor", "sonnet", values)
    assert exact_model.effective_model == "anthropic/claude-sonnet-4.5"
    assert exact_model.route_kind == "exact"
    assert exact_model.source == "model_routing.native_agents.auditor"

    assert exact.route_kind == "class"
    assert via_default.effective_model == "haiku"
    assert via_default.source == "model_routing.native_agents.default"

    values["model_routing.native_agents.default"] = ""
    fallback = resolve_native_agent_model("reviewer", "sonnet", values)
    assert fallback.effective_model == "sonnet"
    assert fallback.source == "frontmatter"
    assert fallback.override_applied is False
    assert fallback.override_support == "frontmatter"
    values["model_routing.native_agents.doc_fetcher"] = "deep"
    hyphen_id = resolve_native_agent_model("doc-fetcher", "haiku", values)
    assert hyphen_id.effective_model == "opus"
    assert hyphen_id.source == "model_routing.native_agents.doc_fetcher"



# ---------------------------------------------------------------------------
# T002 host-aware class resolution
# ---------------------------------------------------------------------------


def _host_keyed_defaults() -> dict[str, object]:
    """Four-tier host-keyed matrix values (mirrors T001 config defaults)."""
    return {
        # cheap
        "model_classes.cheap.model": "haiku",  # legacy scalar fallback
        "model_classes.cheap.claude.model": "haiku",
        "model_classes.cheap.claude.effort": "",
        "model_classes.cheap.omp.model": "gpt-5.6-luna-low",
        "model_classes.cheap.omp.effort": "",
        # low
        "model_classes.low.model": "sonnet",
        "model_classes.low.claude.model": "sonnet",
        "model_classes.low.claude.effort": "medium",
        "model_classes.low.omp.model": "gpt-5.6-terra-low",
        "model_classes.low.omp.effort": "",
        # standard
        "model_classes.standard.model": "sonnet",
        "model_classes.standard.claude.model": "sonnet",
        "model_classes.standard.claude.effort": "high",
        "model_classes.standard.omp.model": "gpt-5.6-terra-medium",
        "model_classes.standard.omp.effort": "",
        # deep
        "model_classes.deep.model": "opus",
        "model_classes.deep.claude.model": "opus",
        "model_classes.deep.claude.effort": "high",
        "model_classes.deep.omp.model": "gpt-5.6-sol-medium",
        "model_classes.deep.omp.effort": "",
    }


_CLAUDE_MATRIX = {
    "cheap": ("haiku", ""),
    "low": ("sonnet", "medium"),
    "standard": ("sonnet", "high"),
    "deep": ("opus", "high"),
}

_OMP_MATRIX = {
    "cheap": ("gpt-5.6-luna-low", ""),
    "low": ("gpt-5.6-terra-low", ""),
    "standard": ("gpt-5.6-terra-medium", ""),
    "deep": ("gpt-5.6-sol-medium", ""),
}


def test_host_family_maps_claude_to_claude_and_others_to_omp():
    """Only the literal 'claude' host is the claude family; all else is omp."""
    assert _host_family("claude") == "claude"
    for other in ("pi", "codex", "cursor", "antigravity", "totally-unknown"):
        assert _host_family(other) == "omp", other


def test_current_host_family_honors_env_override(monkeypatch):
    """Z_HARNESS_HOST forces the family without invoking detect-host.sh."""
    monkeypatch.setenv("Z_HARNESS_HOST", "claude")
    assert _current_host_family() == "claude"
    monkeypatch.setenv("Z_HARNESS_HOST", "pi")
    assert _current_host_family() == "omp"


def test_detect_host_caches_subprocess_call_but_env_override_wins_every_call(monkeypatch):
    """The detect-host.sh subprocess call is cached (T-REV-004), but Z_HARNESS_HOST
    is read fresh on every call and always short-circuits the cache.

    Failure class: if ``Z_HARNESS_HOST`` were read *inside* the cached function,
    ``lru_cache`` would freeze whichever env value was seen on the first call and
    silently break every test (and caller) that forces a different host per call.
    """
    from runtime.dispatch import dispatcher as dispatcher_module

    dispatcher_module._run_detect_host_script.cache_clear()
    calls: list[list[str]] = []

    def _fake_run(argv, **kwargs):
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, stdout="codex\n", stderr="")

    monkeypatch.setattr(dispatcher_module.subprocess, "run", _fake_run)
    monkeypatch.delenv("Z_HARNESS_HOST", raising=False)

    # Two calls with no override: subprocess is only invoked once (cached).
    assert dispatcher_module._detect_host() == "codex"
    assert dispatcher_module._detect_host() == "codex"
    assert len(calls) == 1

    # Z_HARNESS_HOST overrides win outright and never touch the cached subprocess
    # result, per-call, even though the cache is already warm from above.
    monkeypatch.setenv("Z_HARNESS_HOST", "claude")
    assert dispatcher_module._detect_host() == "claude"
    monkeypatch.setenv("Z_HARNESS_HOST", "pi")
    assert dispatcher_module._detect_host() == "pi"
    assert len(calls) == 1  # still just the one cached subprocess invocation

    dispatcher_module._run_detect_host_script.cache_clear()


@pytest.mark.parametrize("class_name", ["cheap", "low", "standard", "deep"])
def test_class_resolution_claude_column(class_name, monkeypatch):
    """On a claude host each class resolves to the Claude (model, effort) pair."""
    monkeypatch.setenv("Z_HARNESS_HOST", "claude")
    resolved = resolve_model_route(class_name, _host_keyed_defaults(), source="test")

    expected_model, expected_effort = _CLAUDE_MATRIX[class_name]
    assert resolved.route_kind == "class"
    assert resolved.effective_model == expected_model
    assert resolved.effort == expected_effort


@pytest.mark.parametrize("class_name", ["cheap", "low", "standard", "deep"])
def test_class_resolution_omp_column(class_name, monkeypatch):
    """On a pi (omp-family) host each class resolves to the gpt-5.6 (model, effort) pair."""
    monkeypatch.setenv("Z_HARNESS_HOST", "pi")
    resolved = resolve_model_route(class_name, _host_keyed_defaults(), source="test")

    expected_model, expected_effort = _OMP_MATRIX[class_name]
    assert resolved.route_kind == "class"
    assert resolved.effective_model == expected_model
    assert resolved.effort == expected_effort


def test_class_effort_flows_into_telemetry(monkeypatch):
    """The resolved effort appears in ModelRouteResolution.telemetry() when non-empty."""
    monkeypatch.setenv("Z_HARNESS_HOST", "claude")
    resolved = resolve_model_route("deep", _host_keyed_defaults(), source="test")
    assert resolved.telemetry()["effort"] == "high"

    monkeypatch.setenv("Z_HARNESS_HOST", "claude")
    cheap = resolve_model_route("cheap", _host_keyed_defaults(), source="test")
    # Empty effort must be omitted from telemetry (additive-only).
    assert "effort" not in cheap.telemetry()


def test_legacy_scalar_fallback_resolves_without_error(monkeypatch):
    """A class with only the legacy scalar model (no host-keyed keys) still resolves.

    Failure class: If the resolver required host-keyed keys, an old/partial config
    that predates the host axis would raise or return the route as an exact model
    label instead of expanding the class — breaking backward-compat.
    """
    monkeypatch.setenv("Z_HARNESS_HOST", "pi")  # omp family, but no host-keyed keys exist
    values = {
        "model_classes.legacy_only.model": "claude-opus-4.5",
        "model_classes.legacy_only.thinking": "budget:high",
        "model_classes.legacy_only.reasoning": "effort:high",
    }
    resolved = resolve_model_route("legacy_only", values, source="test")

    assert resolved.route_kind == "class"
    assert resolved.effective_model == "claude-opus-4.5"
    assert resolved.thinking == "budget:high"
    assert resolved.reasoning == "effort:high"
    assert resolved.effort == ""  # legacy path carries no host effort


def test_host_keyed_wins_over_legacy_scalar(monkeypatch):
    """When both host-keyed and legacy scalar are present, host-keyed wins."""
    monkeypatch.setenv("Z_HARNESS_HOST", "claude")
    resolved = resolve_model_route("deep", _host_keyed_defaults(), source="test")
    # Legacy scalar is also 'opus', so assert via the omp column to prove routing.
    monkeypatch.setenv("Z_HARNESS_HOST", "codex")
    omp_resolved = resolve_model_route("deep", _host_keyed_defaults(), source="test")
    assert resolved.effective_model == "opus"
    assert omp_resolved.effective_model == "gpt-5.6-sol-medium"


def test_host_family_param_overrides_detection():
    """An explicit host_family kwarg bypasses host detection entirely."""
    resolved = resolve_model_route(
        "standard", _host_keyed_defaults(), source="test", host_family="omp"
    )
    assert resolved.effective_model == "gpt-5.6-terra-medium"


def test_builtin_class_legacy_scalar_pin_is_shadowed_by_hostkeyed_default(monkeypatch):
    """Documents the built-in-class backward-compat gotcha (docs/human/config.md).

    Built-in classes ship host-keyed DEFAULTS alongside the legacy scalar (see
    ``scripts/config.py`` DEFAULTS), so a user who re-pins ONLY the legacy
    scalar ``model_classes.<class>.model`` for a built-in class is silently
    shadowed by the shipped host-keyed default — the host-keyed key is checked
    first and is never absent for a built-in class. This locks that behavior
    as observable so it does not regress unnoticed.
    """
    monkeypatch.setenv("Z_HARNESS_HOST", "claude")
    values = _host_keyed_defaults()  # host-keyed DEFAULTS present, as shipped
    values["model_classes.deep.model"] = "my-custom-legacy-pin"  # user's legacy-only pin
    resolved = resolve_model_route("deep", values, source="test")

    # Shadowed: the shipped host-keyed default wins, not the user's legacy pin.
    assert resolved.effective_model == "opus"
    assert resolved.effective_model != "my-custom-legacy-pin"


def test_builtin_class_hostkeyed_key_overrides_default(monkeypatch):
    """Setting the host-keyed key is the documented way to re-pin a built-in class."""
    monkeypatch.setenv("Z_HARNESS_HOST", "claude")
    values = _host_keyed_defaults()
    values["model_classes.deep.claude.model"] = "my-custom-legacy-pin"
    resolved = resolve_model_route("deep", values, source="test")

    assert resolved.effective_model == "my-custom-legacy-pin"


# ---------------------------------------------------------------------------
# T003 implementer tier -> host-keyed class routing + applied/advisory effort
# ---------------------------------------------------------------------------

# Shipped default implementer tier -> class mapping (scripts/config.py DEFAULTS).
_IMPL_TIER_CLASS = {
    "low": "low",
    "medium": "standard",
    "high": "deep",
    "retry": "deep",
}


def _impl_tier_defaults() -> dict[str, object]:
    """Host-keyed classes + the shipped implementer tier->class mapping (T003)."""
    values = _host_keyed_defaults()
    values.update(
        {
            "model_routing.implementer.low": "low",
            "model_routing.implementer.medium": "standard",
            "model_routing.implementer.high": "deep",
            "model_routing.implementer.retry": "deep",
        }
    )
    return values


def _implementer_support_axis(resolution) -> tuple[bool, str]:
    """Mirror the /z-execute implementer applied-vs-advisory rule.

    Source of truth is prose in ``skills/z-execute/SKILL.md`` (the orchestrator
    applies ``model=`` via ``Agent()`` but has no per-call effort parameter). The
    model is always applied per-call; effort is applied only when baked into the
    model name (omp family -> ``resolution.effort == ""``). When the per-task effort
    is a distinct value (Claude family) it is advisory. This helper encodes that
    rule so the invariant is guarded here even though the decision itself lives in
    prose that cannot be imported.
    """
    return True, ("advisory" if resolution.effort else "applied")


@pytest.mark.parametrize("tier", ["low", "medium", "high", "retry"])
def test_implementer_tier_routes_to_host_keyed_class_on_claude(tier, monkeypatch):
    """Each tier resolves through its class to the Claude (model, effort) pair."""
    monkeypatch.setenv("Z_HARNESS_HOST", "claude")
    resolved = resolve_implementer_model(tier, _impl_tier_defaults())

    expected_model, expected_effort = _CLAUDE_MATRIX[_IMPL_TIER_CLASS[tier]]
    assert resolved.route == _IMPL_TIER_CLASS[tier]
    assert resolved.route_kind == "class"
    assert resolved.effective_model == expected_model
    assert resolved.effort == expected_effort


@pytest.mark.parametrize("tier", ["low", "medium", "high", "retry"])
def test_implementer_tier_routes_to_host_keyed_class_on_pi(tier, monkeypatch):
    """Each tier resolves through its class to the gpt-5.6 (model, effort) pair."""
    monkeypatch.setenv("Z_HARNESS_HOST", "pi")
    resolved = resolve_implementer_model(tier, _impl_tier_defaults())

    expected_model, expected_effort = _OMP_MATRIX[_IMPL_TIER_CLASS[tier]]
    assert resolved.route == _IMPL_TIER_CLASS[tier]
    assert resolved.route_kind == "class"
    assert resolved.effective_model == expected_model
    assert resolved.effort == expected_effort  # "" - baked into the model name


@pytest.mark.parametrize("tier", ["low", "medium", "high", "retry"])
def test_implementer_effort_advisory_on_claude(tier, monkeypatch):
    """On Claude the model is applied but the per-task effort is advisory."""
    monkeypatch.setenv("Z_HARNESS_HOST", "claude")
    resolved = resolve_implementer_model(tier, _impl_tier_defaults())
    applied, support = _implementer_support_axis(resolved)

    assert resolved.effort in {"medium", "high"}  # distinct effort value present
    assert applied is True  # model applied per-call via Agent(model=...)
    assert support == "advisory"  # Agent() has no per-call effort parameter


@pytest.mark.parametrize("tier", ["low", "medium", "high", "retry"])
def test_implementer_effort_baked_applied_on_pi(tier, monkeypatch):
    """On omp the effort is baked into the model name, so it is applied."""
    monkeypatch.setenv("Z_HARNESS_HOST", "pi")
    resolved = resolve_implementer_model(tier, _impl_tier_defaults())
    applied, support = _implementer_support_axis(resolved)

    assert resolved.effort == ""  # baked into the omp catalog model name
    assert applied is True
    assert support == "applied"


def test_dispatcher_model_resolved_telemetry_source_and_applied(monkeypatch, tmp_path):
    captured = _capture_events(monkeypatch)
    provider_config = {
        "args_template": [],
        "model_arg_template": ["--model", "{model}"],
        "default_model": "sonnet",
    }
    driver = _MinimalDriver()
    driver.init(provider_config)

    dispatcher = _make_dispatcher(tmp_path)
    dispatcher.run(
        driver,
        "z-subagent-dispatch",
        [],
        provider_config,
        model="claude-opus-4.5",
        model_source="model_routing.native_agents.implementer",
        model_route="deep",
        model_route_kind="class",
        model_override_applied=True,
        model_override_support="applied",
    )

    model_events = [payload for kind, payload in captured if kind == "model_resolved"]
    assert len(model_events) == 1
    payload = model_events[0]
    assert payload["effective_model"] == "claude-opus-4.5"
    assert payload["source"] == "model_routing.native_agents.implementer"
    assert payload["route"] == "deep"
    assert payload["route_kind"] == "class"
    assert payload["override_applied"] is True
    assert payload["override_support"] == "applied"


def test_dispatcher_model_resolved_telemetry_advisory_when_host_cannot_apply(
    monkeypatch, tmp_path
):
    captured = _capture_events(monkeypatch)
    provider_config = {
        "args_template": [],
        "model_arg_template": None,
        "default_model": None,
    }
    driver = _MinimalDriver()
    driver.init(provider_config)

    dispatcher = _make_dispatcher(tmp_path)
    dispatcher.run(
        driver,
        "z-subagent-dispatch",
        [],
        provider_config,
        model="claude-opus-4.5",
        model_source="model_routing.implementer.retry",
    )

    payload = [p for kind, p in captured if kind == "model_resolved"][0]
    assert payload["source"] == "model_routing.implementer.retry"
    assert payload["override_applied"] is False
    assert payload["override_support"] == "advisory"


def test_routed_model_source_does_not_emit_legacy_override_event(monkeypatch, tmp_path):
    captured = _capture_events(monkeypatch)
    provider_config = {"args_template": []}
    driver = _MinimalDriver()
    driver.init(provider_config)

    dispatcher = _make_dispatcher(tmp_path)
    dispatcher.run(
        driver,
        "z-subagent-dispatch",
        [],
        provider_config,
        model="sonnet",
        model_source="frontmatter",
    )

    assert "persona_override_used" not in [kind for kind, _payload in captured]
    model_payload = [p for kind, p in captured if kind == "model_resolved"][0]
    assert model_payload["source"] == "frontmatter"


def test_dispatcher_model_resolved_telemetry_includes_effort_when_present(monkeypatch, tmp_path):
    """``model_effort`` reaches ``model_resolved`` telemetry when non-empty (T-REV-004)."""
    captured = _capture_events(monkeypatch)
    provider_config = {
        "args_template": [],
        "model_arg_template": ["--model", "{model}"],
        "default_model": "sonnet",
    }
    driver = _MinimalDriver()
    driver.init(provider_config)

    dispatcher = _make_dispatcher(tmp_path)
    dispatcher.run(
        driver,
        "z-subagent-dispatch",
        [],
        provider_config,
        model="gpt-5.6-sol-medium",
        model_source="model_routing.native_agents.explore",
        model_route="deep",
        model_route_kind="class",
        model_effort="medium",
        model_override_applied=True,
        model_override_support="applied",
    )

    payload = [p for kind, p in captured if kind == "model_resolved"][0]
    assert payload["effort"] == "medium"


def test_dispatcher_model_resolved_telemetry_omits_effort_when_empty(monkeypatch, tmp_path):
    """An empty/absent ``model_effort`` is never emitted (additive-only, like thinking/reasoning)."""
    captured = _capture_events(monkeypatch)
    provider_config = {"args_template": []}
    driver = _MinimalDriver()
    driver.init(provider_config)

    dispatcher = _make_dispatcher(tmp_path)
    dispatcher.run(
        driver,
        "z-subagent-dispatch",
        [],
        provider_config,
        model="haiku",
        model_source="model_routing.native_agents.doc_fetcher",
    )

    payload = [p for kind, p in captured if kind == "model_resolved"][0]
    assert "effort" not in payload


# ---------------------------------------------------------------------------
# T004 fleet native-agent host-aware routing (against the real config DEFAULTS)
# ---------------------------------------------------------------------------

# Representative fleet agents per class, exercising the shipped
# model_routing.native_agents DEFAULTS mapping in scripts/config.py.  Frontmatter
# fallbacks are passed but MUST be ignored because each agent is class-mapped.
_FLEET_REPRESENTATIVES = {
    "cheap": ("doc_fetcher", "haiku"),      # haiku frontmatter → cheap class
    "standard": ("auditor", "sonnet"),      # sonnet frontmatter → standard class
    "deep": ("research_judge", "opus"),     # opus frontmatter → deep class
}

# (model, effort) each representative must resolve to per host family.
_FLEET_CLAUDE_EXPECT = {
    "cheap": ("haiku", ""),
    "standard": ("sonnet", "high"),
    "deep": ("opus", "high"),
}
_FLEET_PI_EXPECT = {
    "cheap": ("gpt-5.6-luna-low", ""),
    "standard": ("gpt-5.6-terra-medium", ""),
    "deep": ("gpt-5.6-sol-medium", ""),
}


@pytest.mark.parametrize("class_name", ["cheap", "standard", "deep"])
def test_fleet_native_agent_resolves_claude_host(class_name, monkeypatch):
    """Representative fleet agents route through their config class on claude."""
    monkeypatch.setenv("Z_HARNESS_HOST", "claude")
    values = load_model_routing_config(REPO_ROOT)
    agent_id, frontmatter = _FLEET_REPRESENTATIVES[class_name]

    resolved = resolve_native_agent_model(agent_id, frontmatter, values)

    expected_model, expected_effort = _FLEET_CLAUDE_EXPECT[class_name]
    assert resolved.route_kind == "class"
    assert resolved.route == class_name
    assert resolved.source == f"model_routing.native_agents.{agent_id}"
    assert resolved.effective_model == expected_model
    assert resolved.effort == expected_effort


@pytest.mark.parametrize("class_name", ["cheap", "standard", "deep"])
def test_fleet_native_agent_resolves_pi_host(class_name, monkeypatch):
    """The same fleet agents resolve to the gpt-5.6 family on a non-claude host."""
    monkeypatch.setenv("Z_HARNESS_HOST", "pi")
    values = load_model_routing_config(REPO_ROOT)
    agent_id, frontmatter = _FLEET_REPRESENTATIVES[class_name]

    resolved = resolve_native_agent_model(agent_id, frontmatter, values)

    expected_model, expected_effort = _FLEET_PI_EXPECT[class_name]
    assert resolved.route_kind == "class"
    assert resolved.source == f"model_routing.native_agents.{agent_id}"
    assert resolved.effective_model == expected_model
    assert resolved.effort == expected_effort


def test_fleet_native_agent_telemetry_carries_effort(monkeypatch):
    """A class-routed fleet agent surfaces effort in its telemetry payload."""
    monkeypatch.setenv("Z_HARNESS_HOST", "claude")
    values = load_model_routing_config(REPO_ROOT)

    resolved = resolve_native_agent_model("auditor", "sonnet", values)
    telemetry = resolved.telemetry()

    assert telemetry["route"] == "standard"
    assert telemetry["route_kind"] == "class"
    assert telemetry["effort"] == "high"


def test_unmapped_fleet_agent_falls_back_to_frontmatter(monkeypatch):
    """An agent id absent from native_agents defaults resolves via frontmatter."""
    monkeypatch.setenv("Z_HARNESS_HOST", "claude")
    values = load_model_routing_config(REPO_ROOT)

    resolved = resolve_native_agent_model("not_a_real_agent", "haiku", values)

    assert resolved.source == "frontmatter"
    assert resolved.effective_model == "haiku"
    assert resolved.route_kind == "exact"
