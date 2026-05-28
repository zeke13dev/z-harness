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
