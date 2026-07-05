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
from pathlib import Path

import pytest

from runtime.dispatch.driver import DispatchHandle, HostDriver
from runtime.dispatch.dispatcher import (
    Dispatcher,
    _compose_argv,
    resolve_implementer_model,
    resolve_model_route,
    resolve_native_agent_model,
)
from runtime.dispatch.env import build_env
from runtime.dispatch.result import DispatchResult
from runtime.dispatch.timeout import DispatchTimeoutError, TimeoutReaper

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
# T007: persona_bound attribution tuple extension
# ---------------------------------------------------------------------------


def test_persona_bound_run_id_always_present(monkeypatch, tmp_path):
    """persona_bound always contains run_id from the Dispatcher constructor.

    Failure class: If run_id is absent from persona_bound (e.g. because it was
    accidentally gated behind an 'if' condition), downstream join queries on
    run_id will silently drop all rows for this dispatch.
    """
    captured = _capture_events(monkeypatch)

    driver = _MinimalDriver()
    provider_config = {"args_template": []}
    driver.init(provider_config)

    dispatcher = Dispatcher(repo_root=str(tmp_path), run_id="run-abc-123")
    dispatcher.run(driver, "z-ask", [], provider_config)

    bound_events = [(k, p) for k, p in captured if k == "persona_bound"]
    assert len(bound_events) == 1
    _, payload = bound_events[0]
    assert "run_id" in payload, f"Expected 'run_id' in persona_bound payload; got {payload}"
    assert payload["run_id"] == "run-abc-123", (
        f"Expected run_id='run-abc-123', got {payload['run_id']!r}"
    )


def test_persona_bound_attribution_tuple_all_fields(monkeypatch, tmp_path):
    """persona_bound carries the full attribution tuple when all new kwargs are supplied.

    Failure class: If any of task_id/attempt_id/persona_id/selection_source/draw_id/
    reviewer_participant are omitted from the payload, the join query in
    persona-stats.py will fail to correlate draw and outcome events.
    """
    captured = _capture_events(monkeypatch)

    driver = _MinimalDriver()
    provider_config = {"args_template": [], "persona": "terse-pragmatist", "model": "haiku"}
    driver.init(provider_config)

    dispatcher = _make_dispatcher(tmp_path)
    dispatcher.run(
        driver, "z-implement", [], provider_config,
        role="implementer",
        task_id="T007",
        attempt_id="T007-v1",
        persona_id="terse-pragmatist",
        selection_source="random_role_pool",
        draw_id="T007-impl-T007-v1-abc",
    )

    bound_events = [(k, p) for k, p in captured if k == "persona_bound"]
    assert len(bound_events) == 1
    _, payload = bound_events[0]

    assert payload["task_id"] == "T007", f"task_id missing or wrong: {payload}"
    assert payload["attempt_id"] == "T007-v1", f"attempt_id missing or wrong: {payload}"
    assert payload["persona_id"] == "terse-pragmatist", f"persona_id missing or wrong: {payload}"
    assert payload["selection_source"] == "random_role_pool", (
        f"selection_source missing or wrong: {payload}"
    )
    assert payload["draw_id"] == "T007-impl-T007-v1-abc", (
        f"draw_id missing or wrong: {payload}"
    )
    assert payload["role"] == "implementer", f"role missing or wrong: {payload}"
    assert payload["run_id"] == "test-run-001", f"run_id missing or wrong: {payload}"


def test_persona_bound_reviewer_participant_included(monkeypatch, tmp_path):
    """persona_bound includes reviewer_participant when passed for reviewer dispatches.

    Failure class: If reviewer_participant is not forwarded into the payload,
    the analysis layer cannot segment reviewer rows by arm (base_codex vs
    random_arm), defeating the dual-reviewer attribution scheme.
    """
    captured = _capture_events(monkeypatch)

    driver = _MinimalDriver()
    provider_config = {"args_template": [], "persona": "codex-default-reviewer"}
    driver.init(provider_config)

    dispatcher = _make_dispatcher(tmp_path)
    dispatcher.run(
        driver, "z-review", [], provider_config,
        role="reviewer",
        task_id="T007",
        attempt_id="T007-v1",
        draw_id="T007-reviewer-base-d4e5f6",
        reviewer_participant="base_codex",
    )

    bound_events = [(k, p) for k, p in captured if k == "persona_bound"]
    assert len(bound_events) == 1
    _, payload = bound_events[0]
    assert payload.get("reviewer_participant") == "base_codex", (
        f"Expected reviewer_participant='base_codex'; got {payload}"
    )


def test_persona_bound_attribution_fields_absent_when_not_passed(monkeypatch, tmp_path):
    """New attribution fields are absent from persona_bound when not passed (additive-only).

    Failure class: If any attribution field defaults to a non-None sentinel value
    instead of being omitted, existing parsers that treat key-presence as a signal
    (e.g. 'does this event have draw_id?') would misinterpret legacy events.
    """
    captured = _capture_events(monkeypatch)

    driver = _MinimalDriver()
    provider_config = {"args_template": []}
    driver.init(provider_config)

    dispatcher = _make_dispatcher(tmp_path)
    # Call with no new attribution kwargs — simulates an existing caller.
    dispatcher.run(driver, "z-ask", [], provider_config)

    bound_events = [(k, p) for k, p in captured if k == "persona_bound"]
    assert len(bound_events) == 1
    _, payload = bound_events[0]

    for field in ("task_id", "attempt_id", "selection_source", "draw_id", "reviewer_participant"):
        assert field not in payload, (
            f"Field '{field}' should be absent when not passed; found in payload: {payload}"
        )


def test_persona_bound_persona_id_falls_back_to_resolved_persona(monkeypatch, tmp_path):
    """persona_id in persona_bound falls back to the resolved persona name when not explicitly passed.

    Failure class: If persona_id is always omitted when the kwarg is not passed
    (instead of falling back to _resolved_persona), the persona_id field would
    be absent on all legacy callers, making it impossible to join on persona_id
    without also checking the 'persona' field.
    """
    captured = _capture_events(monkeypatch)

    driver = _MinimalDriver()
    provider_config = {"args_template": [], "persona": "boring-anchor"}
    driver.init(provider_config)

    dispatcher = _make_dispatcher(tmp_path)
    # No persona_id kwarg; persona resolves from provider_config.
    dispatcher.run(driver, "z-implement", [], provider_config)

    bound_events = [(k, p) for k, p in captured if k == "persona_bound"]
    assert len(bound_events) == 1
    _, payload = bound_events[0]
    assert payload.get("persona_id") == "boring-anchor", (
        f"Expected persona_id='boring-anchor' (fallback from _resolved_persona); got {payload}"
    )


def test_persona_bound_persona_id_always_present_as_null(monkeypatch, tmp_path):
    """persona_id is always present in persona_bound — emits null when neither kwarg nor resolved persona exists.

    Failure class: If persona_id is omitted when both the kwarg and the resolved
    persona are None, downstream join queries on persona_id will silently drop
    all rows for dispatches that have no persona configured.
    """
    captured = _capture_events(monkeypatch)

    driver = _MinimalDriver()
    # provider_config has no 'persona' key, and no persona_id kwarg is passed.
    provider_config = {"args_template": []}
    driver.init(provider_config)

    dispatcher = _make_dispatcher(tmp_path)
    dispatcher.run(driver, "z-ask", [], provider_config)

    bound_events = [(k, p) for k, p in captured if k == "persona_bound"]
    assert len(bound_events) == 1
    _, payload = bound_events[0]
    assert "persona_id" in payload, (
        f"Expected 'persona_id' key always present in persona_bound; got keys: {list(payload)}"
    )
    assert payload["persona_id"] is None, (
        f"Expected persona_id=None when no persona is configured; got {payload['persona_id']!r}"
    )


def test_reviewer_participant_invalid_value_raises(monkeypatch, tmp_path):
    """reviewer_participant with an invalid value raises ValueError before emitting.

    Failure class: If the enum guard is absent, a typo like 'base_codex_arm'
    would be silently emitted into telemetry, making arm-segmentation queries
    return nonsense results that are hard to diagnose post-hoc.
    """
    monkeypatch.setattr(
        "runtime.dispatch.dispatcher.log_event",
        lambda run_id, kind, payload, repo_root, slug=None: None,
    )

    driver = _MinimalDriver()
    provider_config = {"args_template": []}
    driver.init(provider_config)

    dispatcher = _make_dispatcher(tmp_path)
    with pytest.raises(ValueError, match="reviewer_participant"):
        dispatcher.run(
            driver, "z-review", [], provider_config,
            reviewer_participant="base_codex_arm",  # typo / invalid value
        )


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
