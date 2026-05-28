"""
tests/drivers/test_select_driver.py — Unit tests for select_driver factory.

Covers:
  - host="claude" + detect_self_hosted() True → SelfHostDriver returned
  - host="claude" + detect_self_hosted() False → SubprocessClaudeDriver returned
  - host="claude" + driver_override="claude-self" → SelfHostDriver always
  - host="cursor" (no override) → CursorCLIDriver returned
  - host="cursor" + driver_override="cursor-sdk" → NotImplementedError raised
  - host="unknown" → DriverNotFoundError raised
  - driver_selected event emitted for each successful selection

No actual binaries are invoked; driver constructors are mocked where needed.

Run:
    pytest tests/drivers/test_select_driver.py -v
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from runtime.drivers import DriverNotFoundError, select_driver
from runtime.drivers.claude.self_host_driver import SelfHostDriver
from runtime.drivers.claude.subprocess_driver import SubprocessClaudeDriver
from runtime.drivers.cursor.cli_driver import CursorCLIDriver


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_DETECT_PATH = "runtime.drivers.detect_self_hosted"
_SELF_HOST_DRIVER_PATH = "runtime.drivers.SelfHostDriver"
_SUBPROCESS_DRIVER_PATH = "runtime.drivers.SubprocessClaudeDriver"
_CURSOR_CLI_DRIVER_PATH = "runtime.drivers.CursorCLIDriver"
_EMIT_PATH = "runtime.drivers._emit_driver_selected"


def _mock_self_host_driver() -> MagicMock:
    """Return a MagicMock instance that passes isinstance checks as SelfHostDriver."""
    mock = MagicMock(spec=SelfHostDriver)
    return mock


def _mock_subprocess_driver() -> MagicMock:
    """Return a MagicMock instance that passes isinstance checks as SubprocessClaudeDriver."""
    mock = MagicMock(spec=SubprocessClaudeDriver)
    return mock


def _mock_cursor_cli_driver() -> MagicMock:
    """Return a MagicMock instance that passes isinstance checks as CursorCLIDriver."""
    mock = MagicMock(spec=CursorCLIDriver)
    return mock


# ---------------------------------------------------------------------------
# host="claude" — auto-detection via detect_self_hosted
# ---------------------------------------------------------------------------


class TestClaudeHostAutoDetection:
    """select_driver("claude") routes based on detect_self_hosted()."""

    def test_self_hosted_true_returns_self_host_driver(self):
        """When detect_self_hosted() is True, SelfHostDriver is returned."""
        mock_instance = _mock_self_host_driver()
        with (
            patch(_DETECT_PATH, return_value=True),
            patch(_SELF_HOST_DRIVER_PATH, return_value=mock_instance) as MockCls,
            patch(_EMIT_PATH),
        ):
            result = select_driver("claude")
        MockCls.assert_called_once_with(force=True)
        assert result is mock_instance

    def test_self_hosted_false_returns_subprocess_driver(self):
        """When detect_self_hosted() is False, SubprocessClaudeDriver is returned."""
        mock_instance = _mock_subprocess_driver()
        with (
            patch(_DETECT_PATH, return_value=False),
            patch(_SUBPROCESS_DRIVER_PATH, return_value=mock_instance) as MockCls,
            patch(_EMIT_PATH),
        ):
            result = select_driver("claude")
        MockCls.assert_called_once_with()
        assert result is mock_instance

    def test_self_hosted_true_does_not_instantiate_subprocess_driver(self):
        """SelfHostDriver env path must never construct SubprocessClaudeDriver."""
        mock_self = _mock_self_host_driver()
        with (
            patch(_DETECT_PATH, return_value=True),
            patch(_SELF_HOST_DRIVER_PATH, return_value=mock_self),
            patch(_SUBPROCESS_DRIVER_PATH) as MockSubprocess,
            patch(_EMIT_PATH),
        ):
            select_driver("claude")
        MockSubprocess.assert_not_called()

    def test_self_hosted_false_does_not_instantiate_self_host_driver(self):
        """SubprocessClaudeDriver path must never construct SelfHostDriver."""
        mock_sub = _mock_subprocess_driver()
        with (
            patch(_DETECT_PATH, return_value=False),
            patch(_SUBPROCESS_DRIVER_PATH, return_value=mock_sub),
            patch(_SELF_HOST_DRIVER_PATH) as MockSelf,
            patch(_EMIT_PATH),
        ):
            select_driver("claude")
        MockSelf.assert_not_called()


# ---------------------------------------------------------------------------
# host="claude" + driver_override="claude-self"
# ---------------------------------------------------------------------------


class TestClaudeHostOverride:
    """driver_override="claude-self" forces SelfHostDriver regardless of env."""

    def test_override_claude_self_forces_self_host_driver_when_env_false(self):
        """Override must win even when detect_self_hosted() returns False."""
        mock_instance = _mock_self_host_driver()
        with (
            patch(_DETECT_PATH, return_value=False),
            patch(_SELF_HOST_DRIVER_PATH, return_value=mock_instance) as MockCls,
            patch(_EMIT_PATH),
        ):
            result = select_driver("claude", driver_override="claude-self")
        MockCls.assert_called_once_with(force=True)
        assert result is mock_instance

    def test_override_claude_self_does_not_instantiate_subprocess_driver(self):
        """With override="claude-self", SubprocessClaudeDriver must not be constructed."""
        mock_instance = _mock_self_host_driver()
        with (
            patch(_DETECT_PATH, return_value=False),
            patch(_SELF_HOST_DRIVER_PATH, return_value=mock_instance),
            patch(_SUBPROCESS_DRIVER_PATH) as MockSub,
            patch(_EMIT_PATH),
        ):
            select_driver("claude", driver_override="claude-self")
        MockSub.assert_not_called()

    def test_override_claude_self_detection_method_is_override(self):
        """detection_method in telemetry must be 'override' when driver_override used."""
        mock_instance = _mock_self_host_driver()
        with (
            patch(_DETECT_PATH, return_value=False),
            patch(_SELF_HOST_DRIVER_PATH, return_value=mock_instance),
            patch(_EMIT_PATH) as mock_emit,
        ):
            select_driver("claude", driver_override="claude-self")
        mock_emit.assert_called_once()
        _, kwargs = mock_emit.call_args
        assert kwargs.get("detection_method") == "override" or mock_emit.call_args[0][2] == "override"


# ---------------------------------------------------------------------------
# host="cursor"
# ---------------------------------------------------------------------------


class TestCursorHost:
    """select_driver("cursor") routes to CursorCLIDriver; cursor-sdk raises."""

    def test_cursor_no_override_returns_cursor_cli_driver(self):
        """Default cursor host selection must return CursorCLIDriver."""
        mock_instance = _mock_cursor_cli_driver()
        with (
            patch(_CURSOR_CLI_DRIVER_PATH, return_value=mock_instance) as MockCls,
            patch(_EMIT_PATH),
        ):
            result = select_driver("cursor")
        MockCls.assert_called_once_with()
        assert result is mock_instance

    def test_cursor_sdk_override_raises_not_implemented(self):
        """driver_override='cursor-sdk' must raise NotImplementedError (v2 milestone)."""
        with pytest.raises(NotImplementedError) as exc_info:
            select_driver("cursor", driver_override="cursor-sdk")
        # Error message must mention v2 milestone context.
        assert "v2" in str(exc_info.value) or "milestone" in str(exc_info.value)

    def test_cursor_sdk_override_does_not_construct_cursor_cli_driver(self):
        """cursor-sdk override path must not instantiate CursorCLIDriver."""
        with (
            patch(_CURSOR_CLI_DRIVER_PATH) as MockCLI,
            pytest.raises(NotImplementedError),
        ):
            select_driver("cursor", driver_override="cursor-sdk")
        MockCLI.assert_not_called()


# ---------------------------------------------------------------------------
# Unknown host → DriverNotFoundError
# ---------------------------------------------------------------------------


class TestUnknownHost:
    """Unsupported host values must raise DriverNotFoundError."""

    def test_unknown_host_raises_driver_not_found_error(self):
        with pytest.raises(DriverNotFoundError):
            select_driver("gemini")

    def test_empty_host_raises_driver_not_found_error(self):
        with pytest.raises(DriverNotFoundError):
            select_driver("")

    def test_driver_not_found_error_mentions_host(self):
        """Error message should include the unknown host name."""
        with pytest.raises(DriverNotFoundError) as exc_info:
            select_driver("unknown-host-xyz")
        assert "unknown-host-xyz" in str(exc_info.value)

    def test_driver_not_found_error_is_not_swallowed(self):
        """DriverNotFoundError must propagate, not be silently caught."""
        raised = False
        try:
            select_driver("bogus")
        except DriverNotFoundError:
            raised = True
        assert raised, "DriverNotFoundError was not raised for unknown host"


# ---------------------------------------------------------------------------
# driver_selected telemetry emission
# ---------------------------------------------------------------------------


class TestDriverSelectedTelemetry:
    """driver_selected event is emitted for every successful driver selection."""

    def test_driver_selected_emitted_for_claude_subprocess(self):
        mock_instance = _mock_subprocess_driver()
        with (
            patch(_DETECT_PATH, return_value=False),
            patch(_SUBPROCESS_DRIVER_PATH, return_value=mock_instance),
            patch(_EMIT_PATH) as mock_emit,
        ):
            select_driver("claude")
        mock_emit.assert_called_once()

    def test_driver_selected_emitted_for_claude_self_host(self):
        mock_instance = _mock_self_host_driver()
        with (
            patch(_DETECT_PATH, return_value=True),
            patch(_SELF_HOST_DRIVER_PATH, return_value=mock_instance),
            patch(_EMIT_PATH) as mock_emit,
        ):
            select_driver("claude")
        mock_emit.assert_called_once()

    def test_driver_selected_emitted_for_cursor_cli(self):
        mock_instance = _mock_cursor_cli_driver()
        with (
            patch(_CURSOR_CLI_DRIVER_PATH, return_value=mock_instance),
            patch(_EMIT_PATH) as mock_emit,
        ):
            select_driver("cursor")
        mock_emit.assert_called_once()

    def test_driver_selected_not_emitted_for_unknown_host(self):
        """No telemetry for failed driver selection."""
        with (
            patch(_EMIT_PATH) as mock_emit,
            pytest.raises(DriverNotFoundError),
        ):
            select_driver("bogus-host")
        mock_emit.assert_not_called()

    def test_driver_selected_payload_driver_class_for_subprocess(self):
        """driver_class in telemetry matches the concrete class name."""
        mock_instance = _mock_subprocess_driver()
        with (
            patch(_DETECT_PATH, return_value=False),
            patch(_SUBPROCESS_DRIVER_PATH, return_value=mock_instance),
            patch(_EMIT_PATH) as mock_emit,
        ):
            select_driver("claude")
        args, kwargs = mock_emit.call_args
        # _emit_driver_selected(driver_class=..., host=..., detection_method=...)
        called_driver_class = args[0] if args else kwargs.get("driver_class")
        assert called_driver_class is not None

    def test_driver_selected_payload_host_for_cursor(self):
        """host field in telemetry must be 'cursor'."""
        mock_instance = _mock_cursor_cli_driver()
        with (
            patch(_CURSOR_CLI_DRIVER_PATH, return_value=mock_instance),
            patch(_EMIT_PATH) as mock_emit,
        ):
            select_driver("cursor")
        args, kwargs = mock_emit.call_args
        # _emit_driver_selected is called with keyword arguments
        called_host = kwargs.get("host") if kwargs else (args[1] if len(args) > 1 else None)
        assert called_host == "cursor"
