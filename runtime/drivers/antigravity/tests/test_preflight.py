"""
Tests for runtime/drivers/antigravity/preflight.py.

Uses mocked subprocess to exercise:
  - Successful agy --version → returns version string, emits agy_preflight_pass
  - Binary not found (FileNotFoundError) → raises DriverUnavailableError, emits agy_preflight_fail
  - Non-zero exit code → raises DriverUnavailableError, emits agy_preflight_fail
  - Timeout → raises DriverUnavailableError, emits agy_preflight_fail
"""

from __future__ import annotations

import subprocess
from unittest.mock import MagicMock, patch

import pytest

from runtime.drivers.antigravity.preflight import DriverUnavailableError, check


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_completed_process(returncode: int, stdout: str = "", stderr: str = "") -> MagicMock:
    cp = MagicMock(spec=subprocess.CompletedProcess)
    cp.returncode = returncode
    cp.stdout = stdout
    cp.stderr = stderr
    return cp


# ---------------------------------------------------------------------------
# Success path
# ---------------------------------------------------------------------------


def test_check_returns_version_on_success():
    """On zero exit, check() returns the stripped stdout version string."""
    mock_result = _make_completed_process(returncode=0, stdout="agy 1.2.3\n")
    with patch("subprocess.run", return_value=mock_result) as mock_run:
        version = check(run_id="test", repo_root="/tmp")
    assert version == "agy 1.2.3"
    mock_run.assert_called_once_with(
        ["agy", "--version"],
        capture_output=True,
        text=True,
        timeout=10,
    )


def test_check_emits_preflight_pass_on_success():
    """On success, agy_preflight_pass telemetry is emitted with agy_version."""
    mock_result = _make_completed_process(returncode=0, stdout="agy 0.9.0")
    with patch("subprocess.run", return_value=mock_result):
        with patch("runtime.drivers.antigravity.preflight.log_event") as mock_log:
            check(run_id="run-1", repo_root="/tmp")
    mock_log.assert_called_once()
    call_kwargs = mock_log.call_args
    assert call_kwargs.kwargs["kind"] == "agy_preflight_pass"
    assert call_kwargs.kwargs["payload"]["agy_version"] == "agy 0.9.0"


# ---------------------------------------------------------------------------
# Failure: binary not found
# ---------------------------------------------------------------------------


def test_check_raises_on_file_not_found():
    """When agy binary is absent, DriverUnavailableError is raised."""
    with patch("subprocess.run", side_effect=FileNotFoundError("not found")):
        with pytest.raises(DriverUnavailableError) as exc_info:
            check(run_id="test", repo_root="/tmp")
    assert "agy is not publicly available" in str(exc_info.value)
    assert "deferring C3" in str(exc_info.value)


def test_check_emits_preflight_fail_on_file_not_found():
    """Binary-not-found emits agy_preflight_fail with recommendation=defer_c3."""
    with patch("subprocess.run", side_effect=FileNotFoundError("not found")):
        with patch("runtime.drivers.antigravity.preflight.log_event") as mock_log:
            with pytest.raises(DriverUnavailableError):
                check(run_id="run-1", repo_root="/tmp")
    mock_log.assert_called_once()
    call_kwargs = mock_log.call_args
    assert call_kwargs.kwargs["kind"] == "agy_preflight_fail"
    assert call_kwargs.kwargs["payload"]["recommendation"] == "defer_c3"
    assert "not found" in call_kwargs.kwargs["payload"]["reason"]


# ---------------------------------------------------------------------------
# Failure: non-zero exit code
# ---------------------------------------------------------------------------


def test_check_raises_on_nonzero_exit():
    """Non-zero exit code from agy --version raises DriverUnavailableError."""
    mock_result = _make_completed_process(returncode=1, stderr="some error")
    with patch("subprocess.run", return_value=mock_result):
        with pytest.raises(DriverUnavailableError) as exc_info:
            check(run_id="test", repo_root="/tmp")
    assert "agy is not publicly available" in str(exc_info.value)


def test_check_emits_preflight_fail_on_nonzero_exit():
    """Non-zero exit emits agy_preflight_fail with reason containing exit code."""
    mock_result = _make_completed_process(returncode=2, stderr="permission denied")
    with patch("subprocess.run", return_value=mock_result):
        with patch("runtime.drivers.antigravity.preflight.log_event") as mock_log:
            with pytest.raises(DriverUnavailableError):
                check(run_id="run-1", repo_root="/tmp")
    mock_log.assert_called_once()
    call_kwargs = mock_log.call_args
    assert call_kwargs.kwargs["kind"] == "agy_preflight_fail"
    assert call_kwargs.kwargs["payload"]["recommendation"] == "defer_c3"
    reason = call_kwargs.kwargs["payload"]["reason"]
    assert "2" in reason  # exit code embedded in reason


def test_check_no_file_written_on_nonzero_exit(tmp_path):
    """No files are written when agy --version returns non-zero."""
    mock_result = _make_completed_process(returncode=1)
    with patch("subprocess.run", return_value=mock_result):
        with pytest.raises(DriverUnavailableError):
            check(run_id="test", repo_root=str(tmp_path))
    # No new files should have been created by preflight itself
    created = list(tmp_path.iterdir())
    assert created == [], f"Unexpected files created on failure: {created}"


# ---------------------------------------------------------------------------
# Failure: timeout
# ---------------------------------------------------------------------------


def test_check_raises_on_timeout():
    """TimeoutExpired from subprocess raises DriverUnavailableError."""
    with patch(
        "subprocess.run",
        side_effect=subprocess.TimeoutExpired(cmd=["agy", "--version"], timeout=10),
    ):
        with pytest.raises(DriverUnavailableError) as exc_info:
            check(run_id="test", repo_root="/tmp")
    assert "agy is not publicly available" in str(exc_info.value)


def test_check_emits_preflight_fail_on_timeout():
    """Timeout emits agy_preflight_fail with reason mentioning timeout."""
    with patch(
        "subprocess.run",
        side_effect=subprocess.TimeoutExpired(cmd=["agy", "--version"], timeout=10),
    ):
        with patch("runtime.drivers.antigravity.preflight.log_event") as mock_log:
            with pytest.raises(DriverUnavailableError):
                check(run_id="run-1", repo_root="/tmp")
    mock_log.assert_called_once()
    call_kwargs = mock_log.call_args
    assert call_kwargs.kwargs["kind"] == "agy_preflight_fail"
    assert "timed out" in call_kwargs.kwargs["payload"]["reason"]
    assert call_kwargs.kwargs["payload"]["recommendation"] == "defer_c3"


# ---------------------------------------------------------------------------
# Telemetry unavailable — no crash
# ---------------------------------------------------------------------------


def test_check_succeeds_when_log_event_unavailable():
    """When log_event is None (import failed), check() still returns version."""
    mock_result = _make_completed_process(returncode=0, stdout="agy 2.0.0")
    with patch("subprocess.run", return_value=mock_result):
        with patch("runtime.drivers.antigravity.preflight.log_event", None):
            version = check(run_id="test", repo_root="/tmp")
    assert version == "agy 2.0.0"


def test_check_raises_when_log_event_unavailable_and_binary_missing():
    """DriverUnavailableError still raised even when log_event is None."""
    with patch("subprocess.run", side_effect=FileNotFoundError):
        with patch("runtime.drivers.antigravity.preflight.log_event", None):
            with pytest.raises(DriverUnavailableError):
                check(run_id="test", repo_root="/tmp")
