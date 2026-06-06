"""
tests/drivers/test_antigravity_shim.py — Unit tests for AntigravityHostDriverShim.

Covers:
  - init() stores provider config and extracts run_id/repo_root from context
  - dispatch() returns a DispatchHandle (HostDriver contract)
  - dispatch() joins args into a prompt and delegates to AntigravityDriver.dispatch()
  - events() yields dicts from the AntigravityDriver iterator
  - wait() returns DispatchResult with exit_code=0 on clean completion
  - wait() returns DispatchResult with is_error=True on DriverDispatchError
  - wait() returns DispatchResult with is_error=True when called before events exhausted
  - teardown() is a no-op
  - AntigravityHostDriverShim subclasses HostDriver (DispatchHandle contract compatibility)

No agy binary is required; AntigravityDriver.dispatch() is mocked throughout.

Run:
    pytest tests/drivers/test_antigravity_shim.py -v
"""

from __future__ import annotations

from typing import Iterator
from unittest.mock import MagicMock, patch

import pytest

from runtime.dispatch.driver import DispatchHandle, HostDriver
from runtime.dispatch.result import DispatchResult
from runtime.drivers.antigravity.driver import DriverConstraintError, DriverDispatchError
from runtime.drivers.antigravity.host_driver_shim import AntigravityHostDriverShim
from runtime.drivers.antigravity.preflight import DriverUnavailableError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_PROVIDER_CONFIG: dict = {
    "name": "antigravity",
    "kind": "cli",
    "command": "agy",
    "args_template": [],
    "timeout_s": 60,
}

_DRIVER_DISPATCH_PATH = "runtime.drivers.antigravity.host_driver_shim.AntigravityDriver"


def _make_shim(
    run_id: str = "test-run",
    repo_root: str = "/fake/root",
) -> AntigravityHostDriverShim:
    """Return an initialised shim backed by real config."""
    shim = AntigravityHostDriverShim()
    shim.init(
        _PROVIDER_CONFIG,
        context={"run_id": run_id, "repo_root": repo_root},
    )
    return shim


def _mock_agy_driver(events: list[dict], raises: Exception | None = None) -> MagicMock:
    """Return a MagicMock AntigravityDriver whose dispatch() yields events or raises."""

    def _dispatch(prompt: str) -> Iterator[dict]:
        for event in events:
            yield event
        if raises is not None:
            raise raises

    mock_driver = MagicMock()
    mock_driver.dispatch.side_effect = _dispatch
    return mock_driver


# ---------------------------------------------------------------------------
# HostDriver subclass invariant
# ---------------------------------------------------------------------------


class TestShimIsHostDriver:
    """AntigravityHostDriverShim must be a HostDriver subclass."""

    def test_subclasses_host_driver(self):
        assert issubclass(AntigravityHostDriverShim, HostDriver)

    def test_instance_is_host_driver(self):
        shim = AntigravityHostDriverShim()
        assert isinstance(shim, HostDriver)

    def test_has_init_method(self):
        assert callable(getattr(AntigravityHostDriverShim, "init", None))

    def test_has_dispatch_method(self):
        assert callable(getattr(AntigravityHostDriverShim, "dispatch", None))

    def test_has_teardown_method(self):
        assert callable(getattr(AntigravityHostDriverShim, "teardown", None))


# ---------------------------------------------------------------------------
# init() tests
# ---------------------------------------------------------------------------


class TestShimInit:
    """init() stores config and reads run_id / repo_root from context."""

    def test_stores_provider_config(self):
        shim = AntigravityHostDriverShim()
        shim.init(_PROVIDER_CONFIG)
        assert shim._provider_config == _PROVIDER_CONFIG

    def test_accepts_run_id_from_context(self):
        shim = AntigravityHostDriverShim()
        shim.init(_PROVIDER_CONFIG, context={"run_id": "run-xyz"})
        assert shim._run_id == "run-xyz"

    def test_accepts_repo_root_from_context(self):
        shim = AntigravityHostDriverShim()
        shim.init(_PROVIDER_CONFIG, context={"repo_root": "/my/repo"})
        assert shim._repo_root == "/my/repo"

    def test_ignores_unknown_context_keys(self):
        """Unknown context keys must not raise (C1-D5 Liskov substitutability)."""
        shim = AntigravityHostDriverShim()
        shim.init(_PROVIDER_CONFIG, context={"unknown_key": "value", "another": 42})
        # No exception raised — pass

    def test_default_run_id_is_set(self):
        shim = AntigravityHostDriverShim()
        shim.init(_PROVIDER_CONFIG)
        assert shim._run_id  # non-empty default


# ---------------------------------------------------------------------------
# dispatch() → DispatchHandle contract
# ---------------------------------------------------------------------------


class TestShimDispatchReturnsHandle:
    """dispatch() returns a DispatchHandle with events() and wait() methods."""

    def test_returns_dispatch_handle(self):
        shim = _make_shim()
        with patch(_DRIVER_DISPATCH_PATH, return_value=_mock_agy_driver([])):
            handle = shim.dispatch("z-ask", ["hello"], {})
        assert isinstance(handle, DispatchHandle)

    def test_handle_has_events_method(self):
        shim = _make_shim()
        with patch(_DRIVER_DISPATCH_PATH, return_value=_mock_agy_driver([])):
            handle = shim.dispatch("z-ask", ["hi"], {})
        assert callable(handle.events)

    def test_handle_has_wait_method(self):
        shim = _make_shim()
        with patch(_DRIVER_DISPATCH_PATH, return_value=_mock_agy_driver([])):
            handle = shim.dispatch("z-ask", ["hi"], {})
        assert callable(handle.wait)


# ---------------------------------------------------------------------------
# Prompt construction: args joined with space
# ---------------------------------------------------------------------------


class TestShimPromptConstruction:
    """args list is joined with a single space to form the agy prompt."""

    def test_args_joined_into_prompt(self):
        shim = _make_shim()
        captured_prompts: list[str] = []

        def _fake_dispatch(prompt: str) -> Iterator[dict]:
            captured_prompts.append(prompt)
            return iter([])

        mock_driver = MagicMock()
        mock_driver.dispatch.side_effect = _fake_dispatch

        with patch(_DRIVER_DISPATCH_PATH, return_value=mock_driver):
            handle = shim.dispatch("z-ask", ["do", "the", "thing"], {})
            list(handle.events())

        assert captured_prompts == ["do the thing"]

    def test_single_arg_no_extra_spaces(self):
        shim = _make_shim()
        captured_prompts: list[str] = []

        def _fake_dispatch(prompt: str) -> Iterator[dict]:
            captured_prompts.append(prompt)
            return iter([])

        mock_driver = MagicMock()
        mock_driver.dispatch.side_effect = _fake_dispatch

        with patch(_DRIVER_DISPATCH_PATH, return_value=mock_driver):
            handle = shim.dispatch("z-ask", ["summarise"], {})
            list(handle.events())

        assert captured_prompts == ["summarise"]

    def test_empty_args_produces_empty_prompt(self):
        shim = _make_shim()
        captured_prompts: list[str] = []

        def _fake_dispatch(prompt: str) -> Iterator[dict]:
            captured_prompts.append(prompt)
            return iter([])

        mock_driver = MagicMock()
        mock_driver.dispatch.side_effect = _fake_dispatch

        with patch(_DRIVER_DISPATCH_PATH, return_value=mock_driver):
            handle = shim.dispatch("z-ask", [], {})
            list(handle.events())

        assert captured_prompts == [""]


# ---------------------------------------------------------------------------
# events() iteration
# ---------------------------------------------------------------------------


class TestShimEvents:
    """events() yields dicts from AntigravityDriver.dispatch() in order."""

    def test_events_yields_all_dicts(self):
        shim = _make_shim()
        fake_events = [
            {"type": "message", "content": "hello"},
            {"type": "done"},
        ]
        with patch(_DRIVER_DISPATCH_PATH, return_value=_mock_agy_driver(fake_events)):
            handle = shim.dispatch("z-ask", ["hi"], {})
            result = list(handle.events())

        assert result == fake_events

    def test_events_empty_on_no_output(self):
        shim = _make_shim()
        with patch(_DRIVER_DISPATCH_PATH, return_value=_mock_agy_driver([])):
            handle = shim.dispatch("z-ask", ["hi"], {})
            result = list(handle.events())

        assert result == []

    def test_events_propagates_driver_dispatch_error(self):
        """DriverDispatchError from agy subprocess must propagate unchanged."""
        shim = _make_shim()
        err = DriverDispatchError("agy exited with code 1")
        with patch(_DRIVER_DISPATCH_PATH, return_value=_mock_agy_driver([], raises=err)):
            handle = shim.dispatch("z-ask", ["hi"], {})
            with pytest.raises(DriverDispatchError):
                list(handle.events())

    def test_events_propagates_driver_unavailable_error(self):
        """DriverUnavailableError (agy not installed) must propagate unchanged."""
        shim = _make_shim()

        def _dispatch_unavailable(prompt: str) -> Iterator[dict]:
            raise DriverUnavailableError("agy not found")
            yield  # make it a generator

        mock_driver = MagicMock()
        mock_driver.dispatch.side_effect = _dispatch_unavailable

        with patch(_DRIVER_DISPATCH_PATH, return_value=mock_driver):
            handle = shim.dispatch("z-ask", ["hi"], {})
            with pytest.raises(DriverUnavailableError):
                list(handle.events())

    def test_events_propagates_driver_constraint_error(self):
        """DriverConstraintError (nested session) must propagate unchanged."""
        shim = _make_shim()
        err = DriverConstraintError("nested session not supported")
        with patch(_DRIVER_DISPATCH_PATH, return_value=_mock_agy_driver([], raises=err)):
            handle = shim.dispatch("z-ask", ["hi"], {})
            with pytest.raises(DriverConstraintError):
                list(handle.events())


# ---------------------------------------------------------------------------
# wait() → DispatchResult contract
# ---------------------------------------------------------------------------


class TestShimWait:
    """wait() returns a DispatchResult that reflects the dispatch outcome."""

    def test_wait_returns_dispatch_result(self):
        shim = _make_shim()
        with patch(_DRIVER_DISPATCH_PATH, return_value=_mock_agy_driver([])):
            handle = shim.dispatch("z-ask", ["hi"], {})
            list(handle.events())  # exhaust iterator
            result = handle.wait()
        assert isinstance(result, DispatchResult)

    def test_wait_exit_code_zero_on_clean_completion(self):
        """Clean dispatch (no exception) → exit_code=0, is_error=False."""
        shim = _make_shim()
        fake_events = [{"type": "done"}]
        with patch(_DRIVER_DISPATCH_PATH, return_value=_mock_agy_driver(fake_events)):
            handle = shim.dispatch("z-ask", ["hi"], {})
            list(handle.events())
            result = handle.wait()

        assert result.exit_code == 0
        assert result.is_error is False

    def test_wait_is_error_true_on_driver_dispatch_error(self):
        """DriverDispatchError during events() → is_error=True, exit_code=1."""
        shim = _make_shim()
        err = DriverDispatchError("agy failed")
        with patch(_DRIVER_DISPATCH_PATH, return_value=_mock_agy_driver([], raises=err)):
            handle = shim.dispatch("z-ask", ["hi"], {})
            with pytest.raises(DriverDispatchError):
                list(handle.events())
            result = handle.wait()

        assert result.is_error is True
        assert result.exit_code != 0

    def test_wait_stderr_contains_error_message_on_failure(self):
        """wait() result.stderr must contain the exception message on failure."""
        shim = _make_shim()
        err = DriverDispatchError("agy exited with code 42")
        with patch(_DRIVER_DISPATCH_PATH, return_value=_mock_agy_driver([], raises=err)):
            handle = shim.dispatch("z-ask", ["hi"], {})
            with pytest.raises(DriverDispatchError):
                list(handle.events())
            result = handle.wait()

        assert "agy exited with code 42" in result.stderr

    def test_wait_before_events_exhausted_returns_error(self):
        """Calling wait() without exhausting events() yields is_error=True."""
        shim = _make_shim()
        fake_events = [{"type": "message", "content": "line1"}]
        with patch(_DRIVER_DISPATCH_PATH, return_value=_mock_agy_driver(fake_events)):
            handle = shim.dispatch("z-ask", ["hi"], {})
            # Deliberately do NOT call list(handle.events()) first.
            result = handle.wait()

        assert result.is_error is True

    def test_wait_wall_ms_is_positive(self):
        """wall_ms in DispatchResult must be a non-negative float."""
        shim = _make_shim()
        with patch(_DRIVER_DISPATCH_PATH, return_value=_mock_agy_driver([])):
            handle = shim.dispatch("z-ask", ["hi"], {})
            list(handle.events())
            result = handle.wait()

        assert isinstance(result.wall_ms, float)
        assert result.wall_ms >= 0.0


# ---------------------------------------------------------------------------
# teardown() is a no-op
# ---------------------------------------------------------------------------


class TestShimTeardown:
    """teardown() must not raise under any circumstances."""

    def test_teardown_does_not_raise(self):
        shim = _make_shim()
        shim.teardown()  # must not raise

    def test_teardown_callable_multiple_times(self):
        shim = _make_shim()
        shim.teardown()
        shim.teardown()  # idempotent
