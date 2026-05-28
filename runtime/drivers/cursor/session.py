"""
runtime/drivers/cursor/session.py — Stream-JSON parser and agent_busy guard for the Cursor driver.

Public surface
--------------
parse_stream_line(line: str) -> dict | None
    Parse one JSONL line from a cursor-agent stream.  Returns None on parse
    error and logs the raw line at DEBUG level (never silently swallows).

is_error_response(parsed: dict) -> bool
    Cursor-specific is_error check.  Returns True iff the parsed dict signals
    an error via ``is_error``, ``error``, or HTTP status fields.

is_agent_busy(parsed: dict) -> bool
    Return True iff the parsed dict represents an HTTP 409 agent-busy response.
    Heuristic: checks ``status_code == 409``, ``http_status == 409``, or a
    ``type`` / ``error`` field containing "busy" or "agent_busy".

DriverBusyError (local C1 placeholder)
    Retryable busy error.  Subclassed by AgentBusyError.  Promote to C1
    runtime-core when that interface ships.

AgentBusyError
    Raised by handle_agent_busy() after max_attempts are exhausted.  It is a
    subclass of DriverBusyError — NOT a fatal error; callers must catch and
    handle.

handle_agent_busy(agent_id, attempt, max_attempts=3)
    Implements exponential backoff (base=0.5 s, capped at 8 s, attempt is
    1-indexed).  Emits ``driver_busy_retry`` telemetry event with
    ``attempt``, ``agent_id``, and ``wait_ms`` fields.  Raises
    AgentBusyError when attempt >= max_attempts.

Telemetry
---------
driver_busy_retry event: fields ``attempt``, ``agent_id``, ``wait_ms``
"""

from __future__ import annotations

import json
import logging
import time

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


def _fire_telemetry(kind: str, payload: dict) -> None:
    """Emit a telemetry event; silently skip when telemetry unavailable.

    Telemetry is fire-and-forget: a failure here must never prevent the
    driver from returning a result or raising a meaningful error to its caller.
    """
    if not _HAVE_LOG_EVENT or _log_event is None:
        logger.debug("telemetry unavailable; event not emitted: %s", kind)
        return
    try:
        _log_event(
            run_id="unknown",
            kind=kind,
            payload=payload,
            repo_root=".",
        )
    except (FileNotFoundError, RuntimeError) as exc:
        logger.debug("telemetry event '%s' failed to emit: %s", kind, exc)


# ---------------------------------------------------------------------------
# C1 DriverBusyError placeholder
# ---------------------------------------------------------------------------


class DriverBusyError(Exception):
    """Retryable busy error — C1 type not yet shipped.

    Defined locally here following the pattern of DriverConfigError /
    DriverInitError in other drivers.  Promote to runtime.dispatch.driver
    (or equivalent C1 module) when the runtime-core interface ships.
    """


class AgentBusyError(DriverBusyError):
    """Raised when cursor-agent returns HTTP 409 (agent busy) and all retry
    attempts are exhausted.

    This is NOT a fatal error.  Callers must catch AgentBusyError and decide
    whether to wait, queue, or report a capacity error to the user.
    """


# ---------------------------------------------------------------------------
# Exponential backoff constants
# ---------------------------------------------------------------------------

_BACKOFF_BASE_SECONDS: float = 0.5
_BACKOFF_CAP_SECONDS: float = 8.0


def _backoff_seconds(attempt: int) -> float:
    """Return the wait time in seconds for a 1-indexed *attempt*.

    Formula: base * 2^(attempt-1), capped at _BACKOFF_CAP_SECONDS.

    Parameters
    ----------
    attempt:
        1-indexed attempt number (first retry is attempt=1).
    """
    raw = _BACKOFF_BASE_SECONDS * (2 ** (attempt - 1))
    return min(raw, _BACKOFF_CAP_SECONDS)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def parse_stream_line(line: str) -> dict | None:
    """Parse one JSONL line from a cursor-agent stream.

    Returns the parsed dict on success.  Returns None on any JSON parse
    error and logs the raw line at DEBUG level so it is never silently
    swallowed.

    Parameters
    ----------
    line:
        A single text line from the cursor-agent JSON stream.
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
    """Return True iff *parsed* signals an error from cursor-agent.

    Cursor-specific heuristic:
    - ``is_error`` field is truthy, OR
    - ``type`` field equals ``"error"`` or ``"system_error"``, OR
    - ``status_code`` or ``http_status`` is >= 400.

    Does NOT rely on process exit code alone.

    Parameters
    ----------
    parsed:
        A dict previously returned by parse_stream_line().
    """
    if parsed.get("is_error"):
        return True
    event_type = parsed.get("type", "")
    if event_type in ("error", "system_error"):
        return True
    for key in ("status_code", "http_status"):
        status = parsed.get(key)
        if isinstance(status, int) and status >= 400:
            return True
    return False


def is_agent_busy(parsed: dict) -> bool:
    """Return True iff *parsed* represents an HTTP 409 agent-busy response.

    Detection heuristic (in priority order):
    1. ``status_code == 409`` or ``http_status == 409``
    2. ``type`` field equals ``"agent_busy"`` or contains ``"busy"``
    3. ``error`` field (string) contains ``"busy"`` or ``"agent_busy"``

    This is the authoritative check used by the cursor driver to distinguish
    HTTP 409 (retryable concurrency limit) from other errors.  It is called
    on the result of parse_stream_line, NOT on the raw exit code.

    Parameters
    ----------
    parsed:
        A dict previously returned by parse_stream_line().
    """
    for key in ("status_code", "http_status"):
        if parsed.get(key) == 409:
            return True
    event_type = str(parsed.get("type", "")).lower()
    if "busy" in event_type:
        return True
    error_field = str(parsed.get("error", "")).lower()
    if "busy" in error_field or "agent_busy" in error_field:
        return True
    return False


def handle_agent_busy(
    agent_id: str,
    attempt: int,
    max_attempts: int = 3,
) -> None:
    """Sleep for an exponential-backoff interval and emit driver_busy_retry telemetry.

    This function implements the wait side of the busy-retry loop.  The caller
    is responsible for the loop structure.  On each call:

    1. If ``attempt >= max_attempts``, raises :class:`AgentBusyError` immediately
       (no sleep, no telemetry — the caller is responsible for surfacing the
       error to the user).
    2. Otherwise, computes ``wait = base * 2^(attempt-1)`` (capped at 8 s),
       emits a ``driver_busy_retry`` telemetry event, then sleeps.

    Parameters
    ----------
    agent_id:
        Identifies the agent that returned busy (for telemetry).
    attempt:
        1-indexed attempt number.  Pass 1 on the first retry, 2 on the second,
        and so on.
    max_attempts:
        Maximum total retry attempts before giving up (default: 3).

    Raises
    ------
    AgentBusyError:
        When ``attempt >= max_attempts``, signalling that the caller must stop
        retrying.  This is NOT a fatal error; callers should catch it and handle
        gracefully (e.g. queue or report capacity error).
    """
    if attempt >= max_attempts:
        raise AgentBusyError(
            f"cursor-agent '{agent_id}' is busy after {attempt} attempt(s); "
            f"max_attempts={max_attempts} reached."
        )

    wait_seconds = _backoff_seconds(attempt)
    wait_ms = round(wait_seconds * 1000)

    _fire_telemetry(
        "driver_busy_retry",
        {
            "agent_id": agent_id,
            "attempt": attempt,
            "wait_ms": wait_ms,
        },
    )

    time.sleep(wait_seconds)
