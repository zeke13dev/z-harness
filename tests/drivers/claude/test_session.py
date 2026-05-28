"""
tests/drivers/claude/test_session.py — Unit tests for session.py.

Covers T010 acceptance criteria:
  - parse_stream_line returns parsed dict for valid JSON object lines
  - parse_stream_line returns None for invalid JSON and logs at DEBUG level
  - detect_failure_mode returns "task_state_desync" for matching indicator lines
  - validate_session_id returns True for valid UUID strings
  - validate_session_id returns False for non-UUID strings

Run:
    pytest tests/drivers/claude/test_session.py -v
"""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock, patch

import pytest

from runtime.drivers.claude.session import (
    detect_failure_mode,
    parse_stream_line,
    validate_session_id,
)


# ---------------------------------------------------------------------------
# parse_stream_line
# ---------------------------------------------------------------------------


def test_parse_stream_line_valid_json() -> None:
    """parse_stream_line returns the parsed dict for a valid JSON object line."""
    line = '{"type": "assistant", "content": "hello"}'
    result = parse_stream_line(line)
    assert result == {"type": "assistant", "content": "hello"}


def test_parse_stream_line_invalid_json(monkeypatch: pytest.MonkeyPatch) -> None:
    """parse_stream_line returns None for invalid JSON and calls logger.debug."""
    mock_logger = MagicMock()
    monkeypatch.setattr("runtime.drivers.claude.session.logger", mock_logger)

    result = parse_stream_line("not valid json {{{")

    assert result is None
    mock_logger.debug.assert_called_once()
    # Confirm the raw invalid line was passed to debug, not swallowed silently
    call_args = mock_logger.debug.call_args
    assert "not valid json {{{" in str(call_args)


# ---------------------------------------------------------------------------
# detect_failure_mode — task_state_desync
# ---------------------------------------------------------------------------


def test_detect_failure_mode_task_state_desync() -> None:
    """detect_failure_mode returns 'task_state_desync' for lines matching the indicator."""
    # "task state" + "desync" both present (case-insensitive per _FAILURE_INDICATORS)
    line = "Error: task state desync detected in session"
    result = detect_failure_mode(line)
    assert result == "task_state_desync"


def test_detect_failure_mode_task_state_desync_out_of_sync() -> None:
    """detect_failure_mode returns 'task_state_desync' for the 'out of sync' variant."""
    line = "claude internal: task state is out of sync with agent"
    result = detect_failure_mode(line)
    assert result == "task_state_desync"


def test_detect_failure_mode_none_for_unmatched() -> None:
    """detect_failure_mode returns None when no known pattern matches."""
    result = detect_failure_mode("everything looks fine here")
    assert result is None


# ---------------------------------------------------------------------------
# validate_session_id
# ---------------------------------------------------------------------------


def test_validate_session_id_valid_uuid() -> None:
    """validate_session_id returns True for a valid UUID string."""
    valid_uuid = str(uuid.uuid4())
    assert validate_session_id(valid_uuid) is True


def test_validate_session_id_invalid() -> None:
    """validate_session_id returns False for a non-UUID string."""
    assert validate_session_id("not-a-uuid") is False
    assert validate_session_id("") is False
    assert validate_session_id("12345") is False
