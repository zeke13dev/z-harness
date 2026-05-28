"""
Tests for runtime/drivers/antigravity/driver.py.

Exercises AntigravityDriver with mocked subprocess.Popen and mocked
preflight.check() to avoid requiring agy to be installed.

Coverage:
  - dispatch() yields events from a successful subprocess run
  - dispatch() calls preflight.check() before launching subprocess
  - dispatch() raises DriverUnavailableError when preflight fails
  - dispatch() emits agy_dispatch_start and agy_dispatch_end telemetry
  - dispatch() raises DriverDispatchError on non-zero exit (with error event message)
  - dispatch() raises DriverDispatchError on non-zero exit (with raw stderr fallback)
  - dispatch() raises DriverConstraintError when stderr contains "nested session"
  - probe() returns True when at least one non-error event received
  - probe() returns False when only error events received
  - probe() writes READY marker on first successful probe
  - probe() does not write READY marker on failure
  - probe() returns False (not raises) on DriverDispatchError
"""

from __future__ import annotations

import io
import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest

# Ensure repo root is importable
_REPO_ROOT = Path(__file__).resolve().parents[5]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from runtime.drivers.antigravity.driver import (  # noqa: E402
    AntigravityDriver,
    DriverConstraintError,
    DriverDispatchError,
)
from runtime.drivers.antigravity.preflight import DriverUnavailableError  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_popen(stdout_lines: list[str], stderr: str = "", returncode: int = 0) -> MagicMock:
    """Build a mock Popen that reads from in-memory stdout/stderr."""
    proc = MagicMock(spec=subprocess.Popen)
    proc.stdout = io.StringIO("".join(line + "\n" for line in stdout_lines))
    proc.stderr = io.StringIO(stderr)
    proc.returncode = returncode

    def fake_wait():
        proc.returncode = returncode

    proc.wait.side_effect = fake_wait
    return proc


def _valid_event(event_type: str = "text", **extra) -> str:
    return json.dumps({"type": event_type, **extra})


# ---------------------------------------------------------------------------
# dispatch() — success path
# ---------------------------------------------------------------------------


def test_dispatch_yields_events_on_success():
    """dispatch() yields parsed events from agy stdout."""
    events = [
        _valid_event("text", content="hello"),
        _valid_event("done", exit_code=0),
    ]
    mock_proc = _make_popen(events, returncode=0)

    with patch("runtime.drivers.antigravity.driver.preflight_check"):
        with patch("subprocess.Popen", return_value=mock_proc):
            driver = AntigravityDriver(run_id="test", repo_root="/tmp")
            results = list(driver.dispatch("hello world"))

    assert len(results) == 2
    assert results[0]["type"] == "text"
    assert results[1]["type"] == "done"


def test_dispatch_calls_preflight_before_popen():
    """dispatch() calls preflight_check before launching subprocess."""
    events = [_valid_event("done")]
    mock_proc = _make_popen(events)

    call_order = []

    def fake_preflight(**kwargs):
        call_order.append("preflight")
        return "agy 1.0.0"

    def fake_popen(*args, **kwargs):
        call_order.append("popen")
        return mock_proc

    with patch("runtime.drivers.antigravity.driver.preflight_check", side_effect=fake_preflight):
        with patch("subprocess.Popen", side_effect=fake_popen):
            driver = AntigravityDriver(run_id="test", repo_root="/tmp")
            list(driver.dispatch("test"))

    assert call_order == ["preflight", "popen"]


def test_dispatch_popen_command_format():
    """dispatch() invokes agy with the correct argument format."""
    events = [_valid_event("done")]
    mock_proc = _make_popen(events)

    with patch("runtime.drivers.antigravity.driver.preflight_check"):
        with patch("subprocess.Popen", return_value=mock_proc) as mock_popen:
            driver = AntigravityDriver(run_id="test", repo_root="/tmp")
            list(driver.dispatch("my prompt"))

    args, kwargs = mock_popen.call_args
    cmd = args[0]
    assert cmd == ["agy", "-p", "my prompt", "--output-format", "stream-json"]
    assert kwargs["stdout"] == subprocess.PIPE
    assert kwargs["stderr"] == subprocess.PIPE
    assert kwargs["text"] is True


# ---------------------------------------------------------------------------
# dispatch() — preflight failure
# ---------------------------------------------------------------------------


def test_dispatch_raises_driver_unavailable_on_preflight_fail():
    """dispatch() raises DriverUnavailableError when preflight fails."""
    with patch(
        "runtime.drivers.antigravity.driver.preflight_check",
        side_effect=DriverUnavailableError("agy not found"),
    ):
        driver = AntigravityDriver(run_id="test", repo_root="/tmp")
        with pytest.raises(DriverUnavailableError):
            list(driver.dispatch("test"))


def test_dispatch_does_not_call_popen_on_preflight_fail():
    """When preflight fails, Popen is never called."""
    with patch(
        "runtime.drivers.antigravity.driver.preflight_check",
        side_effect=DriverUnavailableError("not found"),
    ):
        with patch("subprocess.Popen") as mock_popen:
            driver = AntigravityDriver(run_id="test", repo_root="/tmp")
            with pytest.raises(DriverUnavailableError):
                list(driver.dispatch("test"))
    mock_popen.assert_not_called()


# ---------------------------------------------------------------------------
# dispatch() — telemetry
# ---------------------------------------------------------------------------


def test_dispatch_emits_start_and_end_telemetry():
    """dispatch() emits agy_dispatch_start and agy_dispatch_end."""
    events = [_valid_event("done")]
    mock_proc = _make_popen(events)

    emitted = []

    def fake_log_event(*, run_id, kind, payload, repo_root):
        emitted.append({"kind": kind, "payload": payload})

    with patch("runtime.drivers.antigravity.driver.preflight_check"):
        with patch("subprocess.Popen", return_value=mock_proc):
            with patch("runtime.drivers.antigravity.driver._log_event", fake_log_event):
                driver = AntigravityDriver(run_id="test", repo_root="/tmp")
                list(driver.dispatch("hello"))

    kinds = [e["kind"] for e in emitted]
    assert "agy_dispatch_start" in kinds
    assert "agy_dispatch_end" in kinds

    start = next(e for e in emitted if e["kind"] == "agy_dispatch_start")
    assert "prompt_len" in start["payload"]
    assert start["payload"]["prompt_len"] == len("hello")

    end = next(e for e in emitted if e["kind"] == "agy_dispatch_end")
    assert "exit_code" in end["payload"]
    assert "events_parsed" in end["payload"]
    assert "elapsed_ms" in end["payload"]


def test_dispatch_prompt_len_in_start_event():
    """agy_dispatch_start payload prompt_len reflects actual prompt length."""
    prompt = "a" * 42
    events = [_valid_event("done")]
    mock_proc = _make_popen(events)

    emitted = []

    def fake_log_event(*, run_id, kind, payload, repo_root):
        emitted.append({"kind": kind, "payload": payload})

    with patch("runtime.drivers.antigravity.driver.preflight_check"):
        with patch("subprocess.Popen", return_value=mock_proc):
            with patch("runtime.drivers.antigravity.driver._log_event", fake_log_event):
                driver = AntigravityDriver(run_id="test", repo_root="/tmp")
                list(driver.dispatch(prompt))

    start = next(e for e in emitted if e["kind"] == "agy_dispatch_start")
    assert start["payload"]["prompt_len"] == 42


# ---------------------------------------------------------------------------
# dispatch() — non-zero exit
# ---------------------------------------------------------------------------


def test_dispatch_raises_on_nonzero_exit_with_error_event():
    """On non-zero exit, DriverDispatchError uses error event message."""
    events = [
        _valid_event("error", message="something went wrong"),
    ]
    mock_proc = _make_popen(events, returncode=1)

    with patch("runtime.drivers.antigravity.driver.preflight_check"):
        with patch("subprocess.Popen", return_value=mock_proc):
            driver = AntigravityDriver(run_id="test", repo_root="/tmp")
            with pytest.raises(DriverDispatchError) as exc_info:
                list(driver.dispatch("test"))

    assert "something went wrong" in str(exc_info.value)


def test_dispatch_raises_on_nonzero_exit_with_stderr_fallback():
    """On non-zero exit without error event, DriverDispatchError uses stderr."""
    events = [_valid_event("text", content="partial output")]
    mock_proc = _make_popen(events, stderr="fatal internal error", returncode=2)

    with patch("runtime.drivers.antigravity.driver.preflight_check"):
        with patch("subprocess.Popen", return_value=mock_proc):
            driver = AntigravityDriver(run_id="test", repo_root="/tmp")
            with pytest.raises(DriverDispatchError) as exc_info:
                list(driver.dispatch("test"))

    assert "fatal internal error" in str(exc_info.value)


def test_dispatch_stderr_truncated_to_500_chars():
    """DriverDispatchError from stderr is truncated to 500 chars."""
    # Use a character that doesn't appear in the prefix "agy exited with code N: "
    long_stderr = "Z" * 1000
    mock_proc = _make_popen([], stderr=long_stderr, returncode=1)

    with patch("runtime.drivers.antigravity.driver.preflight_check"):
        with patch("subprocess.Popen", return_value=mock_proc):
            driver = AntigravityDriver(run_id="test", repo_root="/tmp")
            with pytest.raises(DriverDispatchError) as exc_info:
                list(driver.dispatch("test"))

    # The error message contains truncated stderr; only ≤500 of the 1000 Z's appear
    msg = str(exc_info.value)
    z_count = msg.count("Z")
    assert z_count <= 500


# ---------------------------------------------------------------------------
# dispatch() — nesting detection
# ---------------------------------------------------------------------------


def test_dispatch_raises_constraint_error_on_nested_session():
    """DriverConstraintError raised when stderr contains 'nested session'."""
    mock_proc = _make_popen([], stderr="error: nested session not allowed", returncode=1)

    with patch("runtime.drivers.antigravity.driver.preflight_check"):
        with patch("subprocess.Popen", return_value=mock_proc):
            driver = AntigravityDriver(run_id="test", repo_root="/tmp")
            with pytest.raises(DriverConstraintError):
                list(driver.dispatch("test"))


def test_dispatch_constraint_error_takes_priority_over_dispatch_error():
    """DriverConstraintError (nesting) supersedes DriverDispatchError."""
    events = [_valid_event("error", message="some other error")]
    mock_proc = _make_popen(events, stderr="nested session detected", returncode=1)

    with patch("runtime.drivers.antigravity.driver.preflight_check"):
        with patch("subprocess.Popen", return_value=mock_proc):
            driver = AntigravityDriver(run_id="test", repo_root="/tmp")
            with pytest.raises(DriverConstraintError):
                list(driver.dispatch("test"))


# ---------------------------------------------------------------------------
# probe()
# ---------------------------------------------------------------------------


def test_probe_returns_true_on_success():
    """probe() returns True when dispatch yields at least one non-error event."""
    events = [_valid_event("text", content="pong")]
    mock_proc = _make_popen(events)

    with patch("runtime.drivers.antigravity.driver.preflight_check"):
        with patch("subprocess.Popen", return_value=mock_proc):
            driver = AntigravityDriver(run_id="test", repo_root="/tmp")
            with patch.object(driver, "_write_ready"):
                result = driver.probe()

    assert result is True


def test_probe_returns_false_on_dispatch_error():
    """probe() returns False (not raises) when dispatch raises DriverDispatchError."""
    mock_proc = _make_popen([], returncode=1)

    with patch("runtime.drivers.antigravity.driver.preflight_check"):
        with patch("subprocess.Popen", return_value=mock_proc):
            driver = AntigravityDriver(run_id="test", repo_root="/tmp")
            result = driver.probe()

    assert result is False


def test_probe_returns_false_when_only_error_events():
    """probe() returns False when all received events are error-type."""
    events = [_valid_event("error", message="fail")]
    mock_proc = _make_popen(events)

    with patch("runtime.drivers.antigravity.driver.preflight_check"):
        with patch("subprocess.Popen", return_value=mock_proc):
            driver = AntigravityDriver(run_id="test", repo_root="/tmp")
            result = driver.probe()

    assert result is False


def test_probe_writes_ready_on_first_success(tmp_path):
    """probe() writes READY marker on first successful probe with correct format."""
    events = [_valid_event("text", content="pong")]
    mock_proc = _make_popen(events)

    ready_path = tmp_path / "READY"

    with patch(
        "runtime.drivers.antigravity.driver.preflight_check",
        return_value="agy 2.5.0",
    ):
        with patch("subprocess.Popen", return_value=mock_proc):
            with patch("runtime.drivers.antigravity.driver._READY_PATH", ready_path):
                driver = AntigravityDriver(run_id="test", repo_root="/tmp")
                result = driver.probe()

    assert result is True
    assert ready_path.exists()
    content = ready_path.read_text()
    assert content.startswith("agy_version=agy 2.5.0\n")
    assert "verified_at=" in content
    # verified_at must look like an ISO8601 UTC timestamp
    import re
    assert re.search(r"verified_at=\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", content)


def test_probe_does_not_write_ready_on_failure(tmp_path):
    """probe() does not write READY marker when dispatch fails."""
    mock_proc = _make_popen([], returncode=1)

    ready_path = tmp_path / "READY"

    with patch("runtime.drivers.antigravity.driver.preflight_check"):
        with patch("subprocess.Popen", return_value=mock_proc):
            with patch("runtime.drivers.antigravity.driver._READY_PATH", ready_path):
                driver = AntigravityDriver(run_id="test", repo_root="/tmp")
                driver.probe()

    assert not ready_path.exists()


def test_probe_ready_written_only_once(tmp_path):
    """probe() writes READY only once across multiple successful calls."""
    def make_proc():
        events = [_valid_event("text", content="pong")]
        return _make_popen(events)

    ready_path = tmp_path / "READY"

    write_calls = []
    original_write_ready = AntigravityDriver._write_ready

    def patched_write_ready(self):
        write_calls.append(1)
        original_write_ready(self)

    with patch("runtime.drivers.antigravity.driver.preflight_check"):
        with patch("runtime.drivers.antigravity.driver._READY_PATH", ready_path):
            with patch.object(AntigravityDriver, "_write_ready", patched_write_ready):
                driver = AntigravityDriver(run_id="test", repo_root="/tmp")

                with patch("subprocess.Popen", return_value=make_proc()):
                    driver.probe()
                with patch("subprocess.Popen", return_value=make_proc()):
                    driver.probe()

    assert len(write_calls) == 1


def test_probe_ready_skips_write_if_file_exists(tmp_path):
    """probe() skips writing READY if the file already exists on disk (idempotency)."""
    events = [_valid_event("text", content="pong")]

    ready_path = tmp_path / "READY"
    # Pre-create the READY file with old content
    ready_path.write_text("agy_version=old\nverified_at=2020-01-01T00:00:00Z\n")
    original_mtime = ready_path.stat().st_mtime

    with patch("runtime.drivers.antigravity.driver.preflight_check", return_value="agy 3.0.0"):
        with patch("subprocess.Popen", return_value=_make_popen(events)):
            with patch("runtime.drivers.antigravity.driver._READY_PATH", ready_path):
                driver = AntigravityDriver(run_id="test", repo_root="/tmp")
                result = driver.probe()

    assert result is True
    # Content should be unchanged
    assert ready_path.read_text() == "agy_version=old\nverified_at=2020-01-01T00:00:00Z\n"
    assert ready_path.stat().st_mtime == original_mtime


def test_probe_ready_skips_telemetry_if_file_exists(tmp_path):
    """probe() does not emit agy_ready_written if READY already exists on disk."""
    events = [_valid_event("text", content="pong")]

    ready_path = tmp_path / "READY"
    ready_path.write_text("agy_version=old\nverified_at=2020-01-01T00:00:00Z\n")

    emitted = []

    def fake_log_event(*, run_id, kind, payload, repo_root):
        emitted.append(kind)

    with patch("runtime.drivers.antigravity.driver.preflight_check", return_value="agy 3.0.0"):
        with patch("subprocess.Popen", return_value=_make_popen(events)):
            with patch("runtime.drivers.antigravity.driver._READY_PATH", ready_path):
                with patch("runtime.drivers.antigravity.driver._log_event", fake_log_event):
                    driver = AntigravityDriver(run_id="test", repo_root="/tmp")
                    driver.probe()

    assert "agy_ready_written" not in emitted


def test_probe_emits_ready_written_telemetry(tmp_path):
    """probe() emits agy_ready_written telemetry when READY is first written."""
    events = [_valid_event("text", content="pong")]
    mock_proc = _make_popen(events)

    ready_path = tmp_path / "READY"
    emitted = []

    def fake_log_event(*, run_id, kind, payload, repo_root):
        emitted.append({"kind": kind, "payload": payload})

    with patch("runtime.drivers.antigravity.driver.preflight_check"):
        with patch("subprocess.Popen", return_value=mock_proc):
            with patch("runtime.drivers.antigravity.driver._READY_PATH", ready_path):
                with patch("runtime.drivers.antigravity.driver._log_event", fake_log_event):
                    driver = AntigravityDriver(run_id="test", repo_root="/tmp")
                    driver.probe()

    kinds = [e["kind"] for e in emitted]
    assert "agy_ready_written" in kinds

    ready_event = next(e for e in emitted if e["kind"] == "agy_ready_written")
    assert "path" in ready_event["payload"]


def test_probe_propagates_driver_unavailable_error():
    """probe() does not catch DriverUnavailableError — it propagates."""
    with patch(
        "runtime.drivers.antigravity.driver.preflight_check",
        side_effect=DriverUnavailableError("agy not installed"),
    ):
        driver = AntigravityDriver(run_id="test", repo_root="/tmp")
        with pytest.raises(DriverUnavailableError):
            driver.probe()
