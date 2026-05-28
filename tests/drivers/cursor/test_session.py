"""
Tests for runtime/drivers/cursor/session.py.

Covers:
  - parse_stream_line: valid JSON, invalid JSON (returns None + DEBUG log), empty string,
    non-dict JSON, whitespace-only input
  - is_error_response: is_error field, type=="error", status_code>=400, http_status>=400,
    happy-path (no error fields)
  - is_agent_busy: status_code 409, http_status 409, type containing "busy",
    error field containing "busy", non-busy dict
  - AgentBusyError is a subclass of DriverBusyError
  - handle_agent_busy: raises AgentBusyError when attempt >= max_attempts (no sleep)
  - handle_agent_busy: sleeps for backoff duration when attempt < max_attempts
  - handle_agent_busy: emits driver_busy_retry event with correct fields
  - _backoff_seconds: exponential growth capped at 8 s
"""

from __future__ import annotations

import logging
from unittest.mock import MagicMock, call, patch

import pytest

from runtime.drivers.cursor.session import (
    AgentBusyError,
    DriverBusyError,
    _backoff_seconds,
    handle_agent_busy,
    is_agent_busy,
    is_error_response,
    parse_stream_line,
)


# ---------------------------------------------------------------------------
# parse_stream_line
# ---------------------------------------------------------------------------


class TestParseStreamLine:
    def test_valid_json_returns_dict(self):
        result = parse_stream_line('{"type": "text", "content": "hello"}')
        assert result == {"type": "text", "content": "hello"}

    def test_empty_string_returns_none(self):
        assert parse_stream_line("") is None

    def test_whitespace_only_returns_none(self):
        assert parse_stream_line("   \t\n") is None

    def test_invalid_json_returns_none(self):
        assert parse_stream_line("not-json") is None

    def test_invalid_json_logs_at_debug(self, caplog):
        with caplog.at_level(logging.DEBUG, logger="runtime.drivers.cursor.session"):
            result = parse_stream_line("not-json")
        assert result is None
        assert any("invalid JSON" in record.message for record in caplog.records)

    def test_non_dict_json_returns_none(self):
        # A JSON array is not a valid stream-json frame
        assert parse_stream_line("[1, 2, 3]") is None

    def test_non_dict_json_logs_at_debug(self, caplog):
        with caplog.at_level(logging.DEBUG, logger="runtime.drivers.cursor.session"):
            result = parse_stream_line("[1, 2, 3]")
        assert result is None
        assert any("expected JSON object" in record.message for record in caplog.records)

    def test_strips_surrounding_whitespace(self):
        result = parse_stream_line('  {"k": "v"}  ')
        assert result == {"k": "v"}

    def test_nested_dict_preserved(self):
        line = '{"type": "result", "data": {"x": 1}}'
        result = parse_stream_line(line)
        assert result is not None
        assert result["data"] == {"x": 1}

    def test_parse_error_never_raises(self):
        # Malformed JSON must return None, not raise
        result = parse_stream_line("{bad json}")
        assert result is None


# ---------------------------------------------------------------------------
# is_error_response
# ---------------------------------------------------------------------------


class TestIsErrorResponse:
    def test_is_error_true_field(self):
        assert is_error_response({"is_error": True}) is True

    def test_is_error_truthy_int(self):
        assert is_error_response({"is_error": 1}) is True

    def test_is_error_false_field(self):
        assert is_error_response({"is_error": False}) is False

    def test_type_error_string(self):
        assert is_error_response({"type": "error"}) is True

    def test_type_system_error_string(self):
        assert is_error_response({"type": "system_error"}) is True

    def test_type_other_is_not_error(self):
        assert is_error_response({"type": "text"}) is False

    def test_status_code_400_is_error(self):
        assert is_error_response({"status_code": 400}) is True

    def test_status_code_409_is_error(self):
        assert is_error_response({"status_code": 409}) is True

    def test_status_code_500_is_error(self):
        assert is_error_response({"status_code": 500}) is True

    def test_http_status_400_is_error(self):
        assert is_error_response({"http_status": 400}) is True

    def test_status_code_200_is_not_error(self):
        assert is_error_response({"status_code": 200}) is False

    def test_empty_dict_is_not_error(self):
        assert is_error_response({}) is False

    def test_unrelated_fields_not_error(self):
        assert is_error_response({"type": "text", "content": "hello"}) is False


# ---------------------------------------------------------------------------
# is_agent_busy
# ---------------------------------------------------------------------------


class TestIsAgentBusy:
    def test_status_code_409(self):
        assert is_agent_busy({"status_code": 409}) is True

    def test_http_status_409(self):
        assert is_agent_busy({"http_status": 409}) is True

    def test_status_code_200_not_busy(self):
        assert is_agent_busy({"status_code": 200}) is False

    def test_type_agent_busy(self):
        assert is_agent_busy({"type": "agent_busy"}) is True

    def test_type_containing_busy(self):
        assert is_agent_busy({"type": "BUSY_SIGNAL"}) is True

    def test_error_field_containing_busy(self):
        assert is_agent_busy({"error": "agent_busy: too many requests"}) is True

    def test_error_field_containing_busy_case_insensitive(self):
        assert is_agent_busy({"error": "Agent is BUSY"}) is True

    def test_empty_dict_not_busy(self):
        assert is_agent_busy({}) is False

    def test_non_busy_error_not_busy(self):
        assert is_agent_busy({"is_error": True, "type": "error"}) is False

    def test_409_detection_via_parse_stream_line(self):
        """HTTP 409 must be detected from parsed output, not raw exit code."""
        line = '{"status_code": 409, "error": "agent is busy"}'
        parsed = parse_stream_line(line)
        assert parsed is not None
        assert is_agent_busy(parsed) is True


# ---------------------------------------------------------------------------
# AgentBusyError hierarchy
# ---------------------------------------------------------------------------


class TestAgentBusyErrorHierarchy:
    def test_agent_busy_error_is_driver_busy_error(self):
        """AgentBusyError must be a subclass of DriverBusyError (C1 type contract)."""
        err = AgentBusyError("busy")
        assert isinstance(err, DriverBusyError)

    def test_driver_busy_error_is_exception(self):
        err = DriverBusyError("busy")
        assert isinstance(err, Exception)

    def test_agent_busy_error_is_not_fatal(self):
        """AgentBusyError must be catchable independently from generic Exception."""
        raised = False
        try:
            raise AgentBusyError("too many agents")
        except AgentBusyError:
            raised = True
        assert raised

    def test_agent_busy_error_caught_as_driver_busy_error(self):
        """AgentBusyError must be catchable via DriverBusyError."""
        raised = False
        try:
            raise AgentBusyError("too many agents")
        except DriverBusyError:
            raised = True
        assert raised


# ---------------------------------------------------------------------------
# _backoff_seconds
# ---------------------------------------------------------------------------


class TestBackoffSeconds:
    def test_attempt_1_returns_half_second(self):
        assert _backoff_seconds(1) == pytest.approx(0.5)

    def test_attempt_2_returns_one_second(self):
        assert _backoff_seconds(2) == pytest.approx(1.0)

    def test_attempt_3_returns_two_seconds(self):
        assert _backoff_seconds(3) == pytest.approx(2.0)

    def test_attempt_4_returns_four_seconds(self):
        assert _backoff_seconds(4) == pytest.approx(4.0)

    def test_attempt_5_returns_eight_seconds(self):
        assert _backoff_seconds(5) == pytest.approx(8.0)

    def test_capped_at_eight_seconds_for_large_attempt(self):
        # attempt=10 would be 0.5 * 2^9 = 256 s without cap
        assert _backoff_seconds(10) == pytest.approx(8.0)


# ---------------------------------------------------------------------------
# handle_agent_busy
# ---------------------------------------------------------------------------


class TestHandleAgentBusy:
    def test_raises_agent_busy_error_at_max_attempts(self):
        """Raises AgentBusyError when attempt == max_attempts without sleeping."""
        with patch("runtime.drivers.cursor.session.time.sleep") as mock_sleep:
            with pytest.raises(AgentBusyError):
                handle_agent_busy("agent-1", attempt=3, max_attempts=3)
        mock_sleep.assert_not_called()

    def test_raises_agent_busy_error_beyond_max_attempts(self):
        """Raises AgentBusyError when attempt > max_attempts."""
        with patch("runtime.drivers.cursor.session.time.sleep") as mock_sleep:
            with pytest.raises(AgentBusyError):
                handle_agent_busy("agent-1", attempt=5, max_attempts=3)
        mock_sleep.assert_not_called()

    def test_sleeps_for_backoff_duration_on_retry(self):
        """Sleeps for _backoff_seconds(attempt) on attempt < max_attempts."""
        with patch("runtime.drivers.cursor.session.time.sleep") as mock_sleep:
            with patch("runtime.drivers.cursor.session._fire_telemetry"):
                handle_agent_busy("agent-1", attempt=1, max_attempts=3)
        mock_sleep.assert_called_once_with(pytest.approx(0.5))

    def test_sleeps_correct_duration_for_attempt_2(self):
        with patch("runtime.drivers.cursor.session.time.sleep") as mock_sleep:
            with patch("runtime.drivers.cursor.session._fire_telemetry"):
                handle_agent_busy("agent-1", attempt=2, max_attempts=3)
        mock_sleep.assert_called_once_with(pytest.approx(1.0))

    def test_emits_driver_busy_retry_event(self):
        """handle_agent_busy must emit driver_busy_retry event with correct fields."""
        with patch("runtime.drivers.cursor.session.time.sleep"):
            with patch("runtime.drivers.cursor.session._fire_telemetry") as mock_fire:
                handle_agent_busy("agent-xyz", attempt=1, max_attempts=3)

        mock_fire.assert_called_once()
        kind, payload = mock_fire.call_args.args
        assert kind == "driver_busy_retry"
        assert payload["agent_id"] == "agent-xyz"
        assert payload["attempt"] == 1
        assert "wait_ms" in payload
        assert payload["wait_ms"] == 500  # 0.5 s * 1000

    def test_event_wait_ms_matches_sleep_duration(self):
        """wait_ms in telemetry event must match actual sleep duration."""
        with patch("runtime.drivers.cursor.session.time.sleep") as mock_sleep:
            with patch("runtime.drivers.cursor.session._fire_telemetry") as mock_fire:
                handle_agent_busy("agent-1", attempt=2, max_attempts=3)

        sleep_seconds = mock_sleep.call_args.args[0]
        _, payload = mock_fire.call_args.args
        assert payload["wait_ms"] == round(sleep_seconds * 1000)

    def test_does_not_raise_when_below_max_attempts(self):
        """Must return normally (no exception) when attempt < max_attempts."""
        with patch("runtime.drivers.cursor.session.time.sleep"):
            with patch("runtime.drivers.cursor.session._fire_telemetry"):
                handle_agent_busy("agent-1", attempt=1, max_attempts=3)
                handle_agent_busy("agent-1", attempt=2, max_attempts=3)
                # No exception should be raised for attempts 1 and 2

    def test_agent_busy_error_message_includes_agent_id(self):
        with pytest.raises(AgentBusyError, match="agent-xyz"):
            handle_agent_busy("agent-xyz", attempt=3, max_attempts=3)

    def test_default_max_attempts_is_3(self):
        """Default max_attempts=3: attempt 3 raises, attempt 2 does not."""
        with patch("runtime.drivers.cursor.session.time.sleep"):
            with patch("runtime.drivers.cursor.session._fire_telemetry"):
                # attempt=2 with default max should NOT raise
                handle_agent_busy("agent-1", attempt=2)

        with pytest.raises(AgentBusyError):
            handle_agent_busy("agent-1", attempt=3)
