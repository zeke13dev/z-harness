"""
tests/drivers/claude/test_self_host_driver.py — Negative / tombstone tests for SelfHostDriver.

SelfHostDriver is tombstoned: instantiation always raises NotImplementedError.
The file exists for import-compatibility only; it is not a working driver.

These tests assert:
  - SelfHostDriver() raises NotImplementedError (with or without force=True).
  - SelfHostDriver(force=True) raises NotImplementedError.
  - select_driver("claude") never returns SelfHostDriver.
  - select_driver("claude") never returns SelfHostDriver even when
    driver_override="claude-self" is requested.
  - DriverInitError is still importable (tombstone artifact).

Run:
    pytest tests/drivers/claude/test_self_host_driver.py -v
"""

from __future__ import annotations

import pytest

from runtime.drivers.claude.self_host_driver import DriverInitError, SelfHostDriver
from runtime.drivers import select_driver
from runtime.drivers.claude.subprocess_driver import SubprocessClaudeDriver


# ---------------------------------------------------------------------------
# Tombstone: instantiation always raises NotImplementedError
# ---------------------------------------------------------------------------


class TestSelfHostDriverTombstoned:
    """SelfHostDriver.__init__ must raise NotImplementedError for all call forms."""

    def test_instantiation_raises_not_implemented(self):
        """SelfHostDriver() with no args must raise NotImplementedError."""
        with pytest.raises(NotImplementedError):
            SelfHostDriver()

    def test_instantiation_with_force_true_raises_not_implemented(self):
        """SelfHostDriver(force=True) must also raise NotImplementedError (not bypass)."""
        with pytest.raises(NotImplementedError):
            SelfHostDriver(force=True)

    def test_not_implemented_error_message_has_doc_pointer(self):
        """NotImplementedError message must mention the doc pointer (tombstoned)."""
        with pytest.raises(NotImplementedError) as exc_info:
            SelfHostDriver()
        msg = str(exc_info.value)
        # Must mention the tombstone or doc pointer so callers know where to look.
        assert "tombstone" in msg.lower() or "docs/" in msg or "SubprocessClaudeDriver" in msg

    def test_driver_init_error_still_importable(self):
        """DriverInitError must still be importable (tombstone artifact; no crash on import)."""
        # If this line raises, the import compatibility is broken.
        assert DriverInitError is not None
        assert issubclass(DriverInitError, Exception)


# ---------------------------------------------------------------------------
# select_driver never returns SelfHostDriver
# ---------------------------------------------------------------------------


class TestSelectDriverNeverReturnsSelfHostDriver:
    """select_driver("claude") must always return SubprocessClaudeDriver, not SelfHostDriver."""

    def test_select_driver_claude_returns_subprocess_driver(self):
        """select_driver('claude') must return a SubprocessClaudeDriver instance."""
        from unittest.mock import patch, MagicMock
        mock_instance = MagicMock(spec=SubprocessClaudeDriver)
        with (
            patch("runtime.drivers.SubprocessClaudeDriver", return_value=mock_instance),
            patch("runtime.drivers._emit_driver_selected"),
        ):
            result = select_driver("claude")
        assert isinstance(result, type(mock_instance)) or result is mock_instance

    def test_select_driver_claude_never_returns_self_host_driver(self):
        """Result of select_driver('claude') must never be a SelfHostDriver instance."""
        from unittest.mock import patch, MagicMock
        mock_instance = MagicMock(spec=SubprocessClaudeDriver)
        with (
            patch("runtime.drivers.SubprocessClaudeDriver", return_value=mock_instance),
            patch("runtime.drivers._emit_driver_selected"),
        ):
            result = select_driver("claude")
        assert not isinstance(result, SelfHostDriver)

    def test_select_driver_claude_self_override_not_selectable(self):
        """Passing driver_override='claude-self' must not return SelfHostDriver.

        After tombstoning, the 'claude-self' override is removed; select_driver
        must route 'claude' to SubprocessClaudeDriver regardless.
        """
        from unittest.mock import patch, MagicMock
        mock_instance = MagicMock(spec=SubprocessClaudeDriver)
        with (
            patch("runtime.drivers.SubprocessClaudeDriver", return_value=mock_instance),
            patch("runtime.drivers._emit_driver_selected"),
        ):
            result = select_driver("claude", driver_override="claude-self")
        assert not isinstance(result, SelfHostDriver)
