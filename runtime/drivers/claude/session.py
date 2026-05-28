"""
session.py — Session state, stream-json parser, and exit-code handling for Claude drivers.

Public surface
--------------
parse_stream_line(line: str) -> dict | None
    Parse one JSONL line from a claude --bare stream.  Returns None on parse
    error (with DEBUG log of the raw line).

is_error_response(parsed: dict) -> bool
    True iff the parsed dict carries ``is_error: true``.  Does NOT rely on
    exit code alone (SPEC invariant 3).

detect_failure_mode(line: str) -> str | None
    Returns one of:
        "task_state_desync"      — claude-code#59962
        "process_transport_death" — claude-agent-acp#338
        "windows_init_timeout"   — claude-code#50559
    or None when no known failure pattern is matched.
    When a failure mode is detected an ``failure_mode_detected`` event is
    emitted via runtime.compat.log_event (with ImportError fallback).

validate_session_id(s: str) -> bool
    True iff *s* is a valid UUID (any version).

Telemetry
---------
failure_mode_detected event: fields ``failure_mode``, ``raw_indicator``
"""

from __future__ import annotations

import json
import logging
import platform
import sys
import uuid as _uuid

# ---------------------------------------------------------------------------
# Module-level logger
# ---------------------------------------------------------------------------

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Telemetry helper — ImportError-tolerant
# ---------------------------------------------------------------------------

try:
    from runtime.compat import log_event as _log_event  # type: ignore
    _HAVE_LOG_EVENT = True
except ImportError:
    _log_event = None  # type: ignore
    _HAVE_LOG_EVENT = False


def _emit_failure_mode(failure_mode: str, raw_indicator: str) -> None:
    """Emit failure_mode_detected event; silently skip when telemetry unavailable."""
    if not _HAVE_LOG_EVENT or _log_event is None:
        logger.debug(
            "telemetry unavailable; failure_mode_detected not emitted: %s",
            failure_mode,
        )
        return
    try:
        _log_event(
            run_id="unknown",
            kind="failure_mode_detected",
            payload={"failure_mode": failure_mode, "raw_indicator": raw_indicator},
            repo_root=".",
        )
    except (FileNotFoundError, RuntimeError) as exc:
        logger.debug("failure_mode_detected event failed to emit: %s", exc)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def parse_stream_line(line: str) -> dict | None:
    """Parse one JSONL line from a claude --bare stream.

    Returns the parsed dict on success.  Returns None on any JSON parse
    error and logs the raw line at DEBUG level so it is never silently
    swallowed.

    Parameters
    ----------
    line:
        A single text line from the claude --bare JSON stream.
    """
    stripped = line.strip()
    if not stripped:
        return None
    try:
        result = json.loads(stripped)
        if not isinstance(result, dict):
            logger.debug("parse_stream_line: expected JSON object, got %r", stripped)
            return None
        return result
    except json.JSONDecodeError:
        logger.debug("parse_stream_line: invalid JSON: %r", stripped)
        return None


def is_error_response(parsed: dict) -> bool:
    """Return True iff *parsed* carries ``is_error: true``.

    Does NOT rely on process exit code — per SPEC invariant 3, exit codes
    from claude are only 0 or 1, which is insufficient for error detection.

    Parameters
    ----------
    parsed:
        A dict previously returned by parse_stream_line().
    """
    return bool(parsed.get("is_error"))


# Failure-mode indicator fragments — (needle_a, needle_b) both must appear
# (case-insensitive) in the line for a match.
_FAILURE_INDICATORS: list[tuple[str, str, str]] = [
    # (failure_mode, fragment_a, fragment_b)
    ("task_state_desync", "task state", "desync"),
    ("task_state_desync", "task state", "out of sync"),
    ("process_transport_death", "transport", "closed"),
    ("process_transport_death", "transport", "epipe"),
    ("process_transport_death", "transport", "broken pipe"),
]

_WINDOWS_INIT_FRAGMENTS = ("init timeout",)


def detect_failure_mode(line: str) -> str | None:
    """Return a failure mode string or None based on heuristic string matching.

    Failure modes:
    - ``task_state_desync``       — claude-code#59962
    - ``process_transport_death`` — claude-agent-acp#338
    - ``windows_init_timeout``    — claude-code#50559

    Matching is case-insensitive substring matching.  When a failure mode is
    detected the function emits a ``failure_mode_detected`` event via
    runtime.compat.log_event (with ImportError fallback to no-op + DEBUG log).

    Parameters
    ----------
    line:
        Raw text line (may be JSON or plain text from stderr).
    """
    lower = line.lower()

    # Check two-fragment indicators first
    for failure_mode, frag_a, frag_b in _FAILURE_INDICATORS:
        if frag_a in lower and frag_b in lower:
            _emit_failure_mode(failure_mode, line)
            return failure_mode

    # windows_init_timeout: needs "init timeout" AND (win in line OR platform is win32)
    if "init timeout" in lower:
        is_windows = (
            "win" in lower
            or platform.system().lower() == "windows"
            or sys.platform == "win32"
        )
        if is_windows:
            _emit_failure_mode("windows_init_timeout", line)
            return "windows_init_timeout"

    return None


def validate_session_id(s: str) -> bool:
    """Return True iff *s* is a valid UUID (any version).

    Uses uuid.UUID(s) try/except per SPEC requirement.  Non-UUID session IDs
    silently fail when passed to ``claude -p --resume``; this validator lets
    the caller guard against that.

    Parameters
    ----------
    s:
        The session ID string to validate.
    """
    try:
        _uuid.UUID(s)
        return True
    except ValueError:
        return False
