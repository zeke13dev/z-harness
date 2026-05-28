"""
tests/drivers/claude/test_self_host_driver.py — Unit tests for SelfHostDriver.

Covers:
  - DriverInitError raised when detect_self_hosted() is False and force not set
  - force=True overrides the env guard; no DriverInitError raised
  - detection_method is "env" when detect_self_hosted() is True
  - detection_method is "explicit" when force=True is used
  - driver_selected telemetry emitted on init with correct fields
  - SelfHostDriver implements the HostDriver ABC (all abstract methods present)
  - dispatch() returns a DispatchHandle
  - handle.events() raises NotImplementedError (tool-primitive layer pending)
  - handle.wait() returns a DispatchResult
  - subprocess.Popen is NEVER called under any code path

No CLAUDECODE env var is required; all detection is mocked.

Run:
    pytest tests/drivers/claude/test_self_host_driver.py -v
"""

from __future__ import annotations

import subprocess as _subprocess
from unittest.mock import MagicMock, patch

import pytest

from runtime.drivers.claude.self_host_driver import DriverInitError, SelfHostDriver
from runtime.dispatch.driver import DispatchHandle, HostDriver
from runtime.dispatch.result import DispatchResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_PROVIDER: dict = {
    "name": "claude-self",
    "kind": "self-host",
    "host": "claude-self",
}

_CONTEXT: dict = {
    "run_id": "test-run-001",
    "repo_root": "/tmp/repo",
}

_ENV: dict = {"PATH": "/usr/bin", "HOME": "/home/user"}


def _make_driver_env(monkeypatch: pytest.MonkeyPatch) -> SelfHostDriver:
    """Create SelfHostDriver with detect_self_hosted() returning True."""
    monkeypatch.setattr(
        "runtime.drivers.claude.self_host_driver.detect_self_hosted",
        lambda: True,
    )
    return SelfHostDriver()


def _make_driver_force() -> SelfHostDriver:
    """Create SelfHostDriver with force=True (bypasses env check)."""
    return SelfHostDriver(force=True)


# ---------------------------------------------------------------------------
# HostDriver ABC conformance
# ---------------------------------------------------------------------------


class TestHostDriverConformance:
    """SelfHostDriver must implement all abstract methods of HostDriver."""

    def test_is_subclass_of_host_driver(self):
        assert issubclass(SelfHostDriver, HostDriver)

    def test_has_init_method(self):
        assert callable(getattr(SelfHostDriver, "init", None))

    def test_has_dispatch_method(self):
        assert callable(getattr(SelfHostDriver, "dispatch", None))

    def test_has_teardown_method(self):
        assert callable(getattr(SelfHostDriver, "teardown", None))


# ---------------------------------------------------------------------------
# Init guard: DriverInitError when not self-hosted
# ---------------------------------------------------------------------------


class TestInitGuard:
    """DriverInitError raised when detect_self_hosted() is False and force not set."""

    def test_raises_driver_init_error_when_not_self_hosted(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        """Invariant: instantiating outside Claude Code always raises DriverInitError."""
        monkeypatch.setattr(
            "runtime.drivers.claude.self_host_driver.detect_self_hosted",
            lambda: False,
        )
        with pytest.raises(DriverInitError):
            SelfHostDriver()

    def test_error_message_mentions_claudecode(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setattr(
            "runtime.drivers.claude.self_host_driver.detect_self_hosted",
            lambda: False,
        )
        with pytest.raises(DriverInitError) as exc_info:
            SelfHostDriver()
        assert "CLAUDECODE" in str(exc_info.value)

    def test_driver_init_error_is_raised_not_swallowed(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        """DriverInitError must propagate; it must not be silently swallowed."""
        monkeypatch.setattr(
            "runtime.drivers.claude.self_host_driver.detect_self_hosted",
            lambda: False,
        )
        raised = False
        try:
            SelfHostDriver()
        except DriverInitError:
            raised = True
        assert raised, "DriverInitError was not raised — init guard is missing or broken"

    def test_no_error_when_self_hosted(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(
            "runtime.drivers.claude.self_host_driver.detect_self_hosted",
            lambda: True,
        )
        driver = SelfHostDriver()  # must not raise
        assert driver is not None


# ---------------------------------------------------------------------------
# force=True override
# ---------------------------------------------------------------------------


class TestForceOverride:
    """force=True bypasses detect_self_hosted(); no DriverInitError raised."""

    def test_force_true_suppresses_init_error(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        """Invariant: force=True always succeeds regardless of env detection."""
        monkeypatch.setattr(
            "runtime.drivers.claude.self_host_driver.detect_self_hosted",
            lambda: False,
        )
        driver = SelfHostDriver(force=True)  # must not raise
        assert driver is not None

    def test_force_true_sets_detection_method_explicit(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setattr(
            "runtime.drivers.claude.self_host_driver.detect_self_hosted",
            lambda: False,
        )
        driver = SelfHostDriver(force=True)
        assert driver._detection_method == "explicit"

    def test_env_detection_sets_detection_method_env(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setattr(
            "runtime.drivers.claude.self_host_driver.detect_self_hosted",
            lambda: True,
        )
        driver = SelfHostDriver()
        assert driver._detection_method == "env"


# ---------------------------------------------------------------------------
# driver_selected telemetry on init
# ---------------------------------------------------------------------------


class TestDriverSelectedTelemetry:
    """driver_selected event emitted on init with required fields."""

    def test_driver_selected_emitted_on_init(self):
        mock_fire = MagicMock()
        driver = _make_driver_force()
        driver._fire_telemetry = mock_fire  # type: ignore[method-assign]
        driver.init(_PROVIDER, context=_CONTEXT)

        fired_kinds = [c.args[0] for c in mock_fire.call_args_list]
        assert "driver_selected" in fired_kinds

    def test_driver_selected_payload_driver_class(self):
        mock_fire = MagicMock()
        driver = _make_driver_force()
        driver._fire_telemetry = mock_fire  # type: ignore[method-assign]
        driver.init(_PROVIDER, context=_CONTEXT)

        call = next(
            c for c in mock_fire.call_args_list if c.args[0] == "driver_selected"
        )
        assert call.args[1]["driver_class"] == "SelfHostDriver"

    def test_driver_selected_payload_host(self):
        mock_fire = MagicMock()
        driver = _make_driver_force()
        driver._fire_telemetry = mock_fire  # type: ignore[method-assign]
        driver.init(_PROVIDER, context=_CONTEXT)

        call = next(
            c for c in mock_fire.call_args_list if c.args[0] == "driver_selected"
        )
        assert call.args[1]["host"] == "claude-self"

    def test_driver_selected_payload_detection_method_explicit(self):
        mock_fire = MagicMock()
        driver = _make_driver_force()  # force=True → detection_method="explicit"
        driver._fire_telemetry = mock_fire  # type: ignore[method-assign]
        driver.init(_PROVIDER, context=_CONTEXT)

        call = next(
            c for c in mock_fire.call_args_list if c.args[0] == "driver_selected"
        )
        assert call.args[1]["detection_method"] == "explicit"

    def test_driver_selected_payload_detection_method_env(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        mock_fire = MagicMock()
        driver = _make_driver_env(monkeypatch)  # env → detection_method="env"
        driver._fire_telemetry = mock_fire  # type: ignore[method-assign]
        driver.init(_PROVIDER, context=_CONTEXT)

        call = next(
            c for c in mock_fire.call_args_list if c.args[0] == "driver_selected"
        )
        assert call.args[1]["detection_method"] == "env"


# ---------------------------------------------------------------------------
# dispatch returns DispatchHandle
# ---------------------------------------------------------------------------


class TestDispatch:
    """dispatch() returns a DispatchHandle; no subprocess spawned."""

    def test_dispatch_returns_dispatch_handle(self):
        driver = _make_driver_force()
        driver.init(_PROVIDER, context=_CONTEXT)
        handle = driver.dispatch("z-ask", [], dict(_ENV))
        assert isinstance(handle, DispatchHandle)

    def test_handle_events_raises_not_implemented(self):
        """tool-primitive layer not yet wired; events() must raise NotImplementedError."""
        driver = _make_driver_force()
        driver.init(_PROVIDER, context=_CONTEXT)
        handle = driver.dispatch("z-ask", [], dict(_ENV))
        with pytest.raises(NotImplementedError):
            next(iter(handle.events()))

    def test_handle_wait_returns_dispatch_result(self):
        driver = _make_driver_force()
        driver.init(_PROVIDER, context=_CONTEXT)
        handle = driver.dispatch("z-ask", [], dict(_ENV))
        result = handle.wait()
        assert isinstance(result, DispatchResult)

    def test_handle_wait_result_is_error(self):
        """Placeholder result indicates not-implemented; is_error must be True."""
        driver = _make_driver_force()
        driver.init(_PROVIDER, context=_CONTEXT)
        handle = driver.dispatch("z-ask", [], dict(_ENV))
        result = handle.wait()
        assert result.is_error is True


# ---------------------------------------------------------------------------
# Invariant: subprocess.Popen NEVER called
# ---------------------------------------------------------------------------


class TestNoSubprocessSpawn:
    """subprocess.Popen must never be called by SelfHostDriver under any path."""

    def test_popen_not_called_on_init(self):
        with patch.object(_subprocess, "Popen") as mock_popen:
            driver = _make_driver_force()
            driver.init(_PROVIDER, context=_CONTEXT)
            mock_popen.assert_not_called()

    def test_popen_not_called_on_dispatch(self):
        with patch.object(_subprocess, "Popen") as mock_popen:
            driver = _make_driver_force()
            driver.init(_PROVIDER, context=_CONTEXT)
            driver.dispatch("z-ask", [], dict(_ENV))
            mock_popen.assert_not_called()

    def test_popen_not_called_on_teardown(self):
        with patch.object(_subprocess, "Popen") as mock_popen:
            driver = _make_driver_force()
            driver.init(_PROVIDER, context=_CONTEXT)
            driver.teardown()
            mock_popen.assert_not_called()

    def test_popen_not_called_end_to_end(self):
        """Full lifecycle (init → dispatch → wait → teardown) must not call Popen."""
        with patch.object(_subprocess, "Popen") as mock_popen:
            driver = _make_driver_force()
            driver.init(_PROVIDER, context=_CONTEXT)
            handle = driver.dispatch("z-ask", [], dict(_ENV))
            handle.wait()
            driver.teardown()
            mock_popen.assert_not_called()
