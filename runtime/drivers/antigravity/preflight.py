"""
runtime/drivers/antigravity/preflight.py — agy availability pre-flight check.

Runs ``agy --version`` (subprocess, timeout 10s) to confirm that the agy
binary is installed and reachable.

On success:
  - Emits ``agy_preflight_pass`` telemetry with ``agy_version`` field.
  - Returns the version string.

On failure (binary not found, non-zero exit, timeout):
  - Emits ``agy_preflight_fail`` telemetry with ``reason`` and
    ``recommendation: "defer_c3"`` fields.
  - Raises ``DriverUnavailableError`` with a message stating that agy is not
    publicly available.

No file writes or config changes are made on failure.
"""

from __future__ import annotations

import os
import subprocess
from typing import Optional

try:
    from runtime.compat import log_event
except ImportError:
    log_event = None  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------


class DriverUnavailableError(Exception):
    """
    Raised when the agy binary is not reachable or returns a non-zero exit.

    The message describes the specific failure so the caller can produce an
    actionable error without re-running the pre-flight check.
    """


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def check(
    *,
    run_id: Optional[str] = None,
    repo_root: Optional[str] = None,
) -> str:
    """
    Confirm that the agy binary is available by running ``agy --version``.

    Parameters
    ----------
    run_id : str or None
        z-harness run identifier for telemetry.  Defaults to
        ``"agy-preflight"`` when not supplied.
    repo_root : str or None
        Absolute path to the repository root.  Defaults to ``os.getcwd()``
        when not supplied.

    Returns
    -------
    str
        The version string captured from ``agy --version`` stdout.

    Raises
    ------
    DriverUnavailableError
        If the agy binary is not found, returns a non-zero exit code, or
        the subprocess times out.
    """
    effective_run_id = run_id if run_id is not None else "agy-preflight"
    effective_repo_root = repo_root if repo_root is not None else os.getcwd()

    try:
        result = subprocess.run(
            ["agy", "--version"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except FileNotFoundError:
        reason = "agy binary not found on PATH"
        _emit_fail(reason, run_id=effective_run_id, repo_root=effective_repo_root)
        raise DriverUnavailableError(
            "agy is not publicly available; consider deferring C3 until distribution is confirmed"
        ) from None
    except subprocess.TimeoutExpired:
        reason = "agy --version timed out after 10s"
        _emit_fail(reason, run_id=effective_run_id, repo_root=effective_repo_root)
        raise DriverUnavailableError(
            "agy is not publicly available; consider deferring C3 until distribution is confirmed"
        ) from None

    if result.returncode != 0:
        reason = (
            f"agy --version exited with code {result.returncode}"
            + (f": {result.stderr.strip()}" if result.stderr.strip() else "")
        )
        _emit_fail(reason, run_id=effective_run_id, repo_root=effective_repo_root)
        raise DriverUnavailableError(
            "agy is not publicly available; consider deferring C3 until distribution is confirmed"
        )

    version = result.stdout.strip()
    _emit_pass(version, run_id=effective_run_id, repo_root=effective_repo_root)
    return version


# ---------------------------------------------------------------------------
# Private telemetry helpers
# ---------------------------------------------------------------------------


def _emit_pass(version: str, *, run_id: str, repo_root: str) -> None:
    """Emit ``agy_preflight_pass`` telemetry event."""
    if log_event is None:
        return
    try:
        log_event(
            run_id=run_id,
            kind="agy_preflight_pass",
            payload={"agy_version": version},
            repo_root=repo_root,
        )
    except (FileNotFoundError, RuntimeError):
        pass


def _emit_fail(reason: str, *, run_id: str, repo_root: str) -> None:
    """Emit ``agy_preflight_fail`` telemetry event."""
    if log_event is None:
        return
    try:
        log_event(
            run_id=run_id,
            kind="agy_preflight_fail",
            payload={"reason": reason, "recommendation": "defer_c3"},
            repo_root=repo_root,
        )
    except (FileNotFoundError, RuntimeError):
        pass


# ---------------------------------------------------------------------------
# Standalone entry point
# ---------------------------------------------------------------------------


if __name__ == "__main__":
    try:
        version = check()
        print(f"agy is available: {version}")
    except DriverUnavailableError as exc:
        print(f"agy is unavailable: {exc}")
