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
import subprocess
import time

import pytest

from runtime.dispatch.driver import DispatchHandle, HostDriver
from runtime.dispatch.dispatcher import Dispatcher
from runtime.dispatch.env import build_env
from runtime.dispatch.result import DispatchResult
from runtime.dispatch.timeout import DispatchTimeoutError, TimeoutReaper


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
    """Existing callers (no new kwargs) compile and run unchanged; persona_bound emitted."""
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
    assert "persona_bound" in kinds
    assert "model_resolved" in kinds
    # No override event when no kwargs passed.
    assert "persona_override_used" not in kinds


def test_run_persona_override_emits_event(monkeypatch, tmp_path):
    """Passing persona='X' emits persona_override_used with override_field='persona'."""
    captured = _capture_events(monkeypatch)

    driver = _MinimalDriver()
    provider_config = {"args_template": [], "persona": "original-persona"}
    driver.init(provider_config)

    dispatcher = _make_dispatcher(tmp_path)
    dispatcher.run(driver, "z-ask", [], provider_config, persona="custom-persona")

    override_events = [(k, p) for k, p in captured if k == "persona_override_used"]
    assert len(override_events) == 1, f"Expected 1 persona_override_used, got {override_events}"
    _, payload = override_events[0]
    assert payload["override_field"] == "persona"
    assert payload["value"] == "custom-persona"
    assert payload["original"] == "original-persona"
    assert payload["command"] == "z-ask"


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


def test_run_persona_bound_payload_reflects_resolved_triple(monkeypatch, tmp_path):
    """persona_bound payload contains all three resolved fields after overrides."""
    captured = _capture_events(monkeypatch)

    driver = _MinimalDriver()
    provider_config = {
        "args_template": [],
        "persona": "old-persona",
        "model": "haiku",
        "runtime": "codex-cli",
    }
    driver.init(provider_config)

    dispatcher = _make_dispatcher(tmp_path)
    dispatcher.run(
        driver, "z-implement", [], provider_config,
        persona="new-persona",
        model="opus",
    )

    bound_events = [(k, p) for k, p in captured if k == "persona_bound"]
    assert len(bound_events) == 1, f"Expected 1 persona_bound, got {bound_events}"
    _, payload = bound_events[0]

    # Override wins for persona and model.
    assert payload["persona"] == "new-persona"
    assert payload["model"] == "opus"
    # runtime was not overridden — falls back to provider_config.
    assert payload["runtime"] == "codex-cli"
    assert payload["command"] == "z-implement"
    # Source per axis.
    assert payload["source"]["persona"] == "override"
    assert payload["source"]["model"] == "override"
    assert payload["source"]["runtime"] == "provider_config"


def test_run_persona_bound_no_override_source_is_provider_config(monkeypatch, tmp_path):
    """When no kwargs passed, persona_bound source reflects provider_config for set axes."""
    captured = _capture_events(monkeypatch)

    driver = _MinimalDriver()
    provider_config = {"args_template": [], "persona": "base-persona", "model": "haiku"}
    driver.init(provider_config)

    dispatcher = _make_dispatcher(tmp_path)
    dispatcher.run(driver, "z-review", [], provider_config)

    bound_events = [(k, p) for k, p in captured if k == "persona_bound"]
    assert len(bound_events) == 1
    _, payload = bound_events[0]
    assert payload["source"]["persona"] == "provider_config"
    assert payload["source"]["model"] == "provider_config"
    assert payload["source"]["runtime"] == "none"


def test_run_role_kwarg_appears_in_persona_bound_payload(monkeypatch, tmp_path):
    """Passing role='reviewer' includes role in the persona_bound payload.

    Failure class: If the role kwarg is ignored or not forwarded into the
    persona_bound event, payload['role'] will be absent — this test catches
    that regression.
    """
    captured = _capture_events(monkeypatch)

    driver = _MinimalDriver()
    provider_config = {"args_template": [], "persona": "base-persona", "model": "haiku"}
    driver.init(provider_config)

    dispatcher = _make_dispatcher(tmp_path)
    dispatcher.run(driver, "z-review", [], provider_config, role="reviewer")

    bound_events = [(k, p) for k, p in captured if k == "persona_bound"]
    assert len(bound_events) == 1, f"Expected 1 persona_bound, got {bound_events}"
    _, payload = bound_events[0]
    assert "role" in payload, f"Expected 'role' key in persona_bound payload; got {payload}"
    assert payload["role"] == "reviewer", (
        f"Expected role='reviewer', got {payload['role']!r}"
    )
    assert payload["command"] == "z-review"


def test_run_role_kwarg_absent_when_not_passed(monkeypatch, tmp_path):
    """persona_bound payload omits 'role' key when role kwarg is not passed.

    Failure class: If role is always included (e.g. as None), the SPEC
    requirement that 'role is omitted when caller did not supply it' is violated.
    """
    captured = _capture_events(monkeypatch)

    driver = _MinimalDriver()
    provider_config = {"args_template": []}
    driver.init(provider_config)

    dispatcher = _make_dispatcher(tmp_path)
    dispatcher.run(driver, "z-ask", [], provider_config)  # no role kwarg

    bound_events = [(k, p) for k, p in captured if k == "persona_bound"]
    assert len(bound_events) == 1
    _, payload = bound_events[0]
    assert "role" not in payload, (
        f"Expected 'role' to be absent from persona_bound when not passed; got {payload}"
    )


def test_run_all_three_overrides(monkeypatch, tmp_path):
    """Passing all three kwargs emits three persona_override_used events."""
    captured = _capture_events(monkeypatch)

    driver = _MinimalDriver()
    provider_config = {"args_template": []}
    driver.init(provider_config)

    dispatcher = _make_dispatcher(tmp_path)
    dispatcher.run(
        driver, "z-ask", [], provider_config,
        persona="P", model="M", runtime="R",
    )

    override_events = [(k, p) for k, p in captured if k == "persona_override_used"]
    fields = {p["override_field"] for _, p in override_events}
    assert fields == {"persona", "model", "runtime"}


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
