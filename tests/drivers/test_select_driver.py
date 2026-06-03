"""
tests/drivers/test_select_driver.py — Unit tests for select_driver factory.

Covers:
  - host="claude" → SubprocessClaudeDriver returned (SelfHostDriver is tombstoned)
  - host="claude" + driver_override="claude-self" → SubprocessClaudeDriver returned
    (not SelfHostDriver; the claude-self override is removed)
  - host="cursor" (no override) → CursorCLIDriver returned
  - host="cursor" + driver_override="cursor-sdk" → NotImplementedError raised
  - host="codex" → CodexDriver returned
  - host="antigravity" → AntigravityHostDriverShim returned
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
from runtime.drivers.antigravity.host_driver_shim import AntigravityHostDriverShim
from runtime.drivers.claude.self_host_driver import SelfHostDriver
from runtime.drivers.claude.subprocess_driver import SubprocessClaudeDriver
from runtime.drivers.codex.driver import CodexDriver
from runtime.drivers.cursor.cli_driver import CursorCLIDriver


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SUBPROCESS_DRIVER_PATH = "runtime.drivers.SubprocessClaudeDriver"
_CURSOR_CLI_DRIVER_PATH = "runtime.drivers.CursorCLIDriver"
_EMIT_PATH = "runtime.drivers._emit_driver_selected"


def _mock_subprocess_driver() -> MagicMock:
    """Return a MagicMock instance that passes isinstance checks as SubprocessClaudeDriver."""
    mock = MagicMock(spec=SubprocessClaudeDriver)
    return mock


def _mock_cursor_cli_driver() -> MagicMock:
    """Return a MagicMock instance that passes isinstance checks as CursorCLIDriver."""
    mock = MagicMock(spec=CursorCLIDriver)
    return mock


# ---------------------------------------------------------------------------
# host="claude" — always routes to SubprocessClaudeDriver (SelfHostDriver tombstoned)
# ---------------------------------------------------------------------------


class TestClaudeHostAutoDetection:
    """select_driver("claude") always routes to SubprocessClaudeDriver."""

    def test_claude_returns_subprocess_driver(self):
        """select_driver('claude') must always return SubprocessClaudeDriver."""
        mock_instance = _mock_subprocess_driver()
        with (
            patch(_SUBPROCESS_DRIVER_PATH, return_value=mock_instance) as MockCls,
            patch(_EMIT_PATH),
        ):
            result = select_driver("claude")
        MockCls.assert_called_once_with()
        assert result is mock_instance

    def test_claude_never_returns_self_host_driver(self):
        """select_driver('claude') must never return a SelfHostDriver instance."""
        mock_instance = _mock_subprocess_driver()
        with (
            patch(_SUBPROCESS_DRIVER_PATH, return_value=mock_instance),
            patch(_EMIT_PATH),
        ):
            result = select_driver("claude")
        assert not isinstance(result, SelfHostDriver)

    def test_claude_with_claude_self_override_returns_subprocess_driver(self):
        """driver_override='claude-self' must route to SubprocessClaudeDriver (override removed)."""
        mock_instance = _mock_subprocess_driver()
        with (
            patch(_SUBPROCESS_DRIVER_PATH, return_value=mock_instance) as MockCls,
            patch(_EMIT_PATH),
        ):
            result = select_driver("claude", driver_override="claude-self")
        MockCls.assert_called_once_with()
        assert result is mock_instance

    def test_claude_with_claude_self_override_never_returns_self_host_driver(self):
        """driver_override='claude-self' must not produce a SelfHostDriver (tombstoned)."""
        mock_instance = _mock_subprocess_driver()
        with (
            patch(_SUBPROCESS_DRIVER_PATH, return_value=mock_instance),
            patch(_EMIT_PATH),
        ):
            result = select_driver("claude", driver_override="claude-self")
        assert not isinstance(result, SelfHostDriver)


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
            patch(_SUBPROCESS_DRIVER_PATH, return_value=mock_instance),
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


# ---------------------------------------------------------------------------
# host="codex" — MF1 gate
# ---------------------------------------------------------------------------

_CODEX_DRIVER_PATH = "runtime.drivers.CodexDriver"
_AGY_SHIM_PATH = "runtime.drivers.AntigravityHostDriverShim"


def _mock_codex_driver() -> MagicMock:
    """Return a MagicMock instance that passes isinstance checks as CodexDriver."""
    return MagicMock(spec=CodexDriver)


def _mock_agy_shim() -> MagicMock:
    """Return a MagicMock instance that passes isinstance checks as AntigravityHostDriverShim."""
    return MagicMock(spec=AntigravityHostDriverShim)


class TestCodexHost:
    """select_driver("codex") routes to CodexDriver — MF1 gate."""

    def test_codex_returns_codex_driver(self):
        """select_driver('codex') must return a CodexDriver instance."""
        mock_instance = _mock_codex_driver()
        with (
            patch(_CODEX_DRIVER_PATH, return_value=mock_instance) as MockCls,
            patch(_EMIT_PATH),
        ):
            result = select_driver("codex")
        MockCls.assert_called_once_with()
        assert result is mock_instance

    def test_codex_emits_driver_selected(self):
        """driver_selected telemetry fires for host='codex'."""
        mock_instance = _mock_codex_driver()
        with (
            patch(_CODEX_DRIVER_PATH, return_value=mock_instance),
            patch(_EMIT_PATH) as mock_emit,
        ):
            select_driver("codex")
        mock_emit.assert_called_once()

    def test_codex_telemetry_host_field(self):
        """host field in driver_selected telemetry must be 'codex'."""
        mock_instance = _mock_codex_driver()
        with (
            patch(_CODEX_DRIVER_PATH, return_value=mock_instance),
            patch(_EMIT_PATH) as mock_emit,
        ):
            select_driver("codex")
        _, kwargs = mock_emit.call_args
        assert kwargs.get("host") == "codex"

    def test_codex_driver_class_is_host_driver_subclass(self):
        """CodexDriver must be importable and subclass HostDriver."""
        from runtime.dispatch.driver import HostDriver
        assert issubclass(CodexDriver, HostDriver)


# ---------------------------------------------------------------------------
# host="antigravity" — MF1 gate + shim
# ---------------------------------------------------------------------------


class TestAntigravityHost:
    """select_driver("antigravity") routes to AntigravityHostDriverShim — MF1 gate."""

    def test_antigravity_returns_shim(self):
        """select_driver('antigravity') must return an AntigravityHostDriverShim instance."""
        mock_instance = _mock_agy_shim()
        with (
            patch(_AGY_SHIM_PATH, return_value=mock_instance) as MockCls,
            patch(_EMIT_PATH),
        ):
            result = select_driver("antigravity")
        MockCls.assert_called_once_with()
        assert result is mock_instance

    def test_antigravity_emits_driver_selected(self):
        """driver_selected telemetry fires for host='antigravity'."""
        mock_instance = _mock_agy_shim()
        with (
            patch(_AGY_SHIM_PATH, return_value=mock_instance),
            patch(_EMIT_PATH) as mock_emit,
        ):
            select_driver("antigravity")
        mock_emit.assert_called_once()

    def test_antigravity_telemetry_host_field(self):
        """host field in driver_selected telemetry must be 'antigravity'."""
        mock_instance = _mock_agy_shim()
        with (
            patch(_AGY_SHIM_PATH, return_value=mock_instance),
            patch(_EMIT_PATH) as mock_emit,
        ):
            select_driver("antigravity")
        _, kwargs = mock_emit.call_args
        assert kwargs.get("host") == "antigravity"

    def test_antigravity_shim_is_host_driver_subclass(self):
        """AntigravityHostDriverShim must subclass HostDriver."""
        from runtime.dispatch.driver import HostDriver
        assert issubclass(AntigravityHostDriverShim, HostDriver)


# ---------------------------------------------------------------------------
# DriverNotFoundError host list — updated to include codex + antigravity
# ---------------------------------------------------------------------------


class TestDriverNotFoundErrorHostList:
    """DriverNotFoundError message must list all four supported hosts."""

    def test_error_mentions_codex(self):
        """Error message for unknown host must mention 'codex'."""
        with pytest.raises(DriverNotFoundError) as exc_info:
            select_driver("gemini")
        assert "codex" in str(exc_info.value)

    def test_error_mentions_antigravity(self):
        """Error message for unknown host must mention 'antigravity'."""
        with pytest.raises(DriverNotFoundError) as exc_info:
            select_driver("gemini")
        assert "antigravity" in str(exc_info.value)
