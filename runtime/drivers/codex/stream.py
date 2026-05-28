"""
runtime/drivers/codex/stream.py — stream-json JSONL parser for the Codex CLI driver.

Parses the ``--output-format stream-json`` byte stream from a ``codex exec -``
subprocess line by line, yielding typed ``Frame`` objects to the caller.

FORMAT-PAIRING PITFALL
----------------------
``--output-format stream-json`` MUST NOT be combined with ``--json-schema``.
When both flags are present, the Codex CLI silently omits the ``structured_output``
field from emitted frames — the schema is parsed and accepted but the response
never includes a ``structured_output`` key.  If you need structured output, use
``--output-format json`` (non-streaming) instead.

Exception taxonomy (stream-level; distinct from driver.py wait-level kinds)
---------------------------------------------------------------------------
- ``CodexExecutionError``  — raised when a frame carries ``is_error: true``
  (error_kind: "execution_error")
- ``CodexTimeoutError``    — raised when stdout hangs for longer than
  ``stream_timeout_s`` seconds (error_kind: "stream_timeout")
- ``CodexCrashError``      — raised when the process exits with a non-zero code
  during streaming (error_kind: "subprocess_crash")

Malformed JSONL lines (error_kind: "malformed_jsonl") are logged as warnings and
skipped; they do not raise.  This matches the permissive parsing stance described
in SPEC §Invariants-3.

Telemetry
---------
``codex_driver_error`` is emitted on every abnormal path via the standard
z-harness log_event mechanism.  Import failures are handled with an ImportError
fallback identical to the pattern in auth.py so the parser remains usable
outside a full z-harness installation.
"""

from __future__ import annotations

import json
import select
import subprocess
import sys
import time
import warnings
from dataclasses import dataclass, field
from typing import Iterator, Optional

try:
    from runtime.compat import log_event as _log_event
except ImportError:
    _log_event = None  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Default per-line read timeout in seconds.  parse_stream() raises
#: CodexTimeoutError if no new byte is available within this window.
_DEFAULT_STREAM_TIMEOUT_S: int = 30


# ---------------------------------------------------------------------------
# Public exceptions
# ---------------------------------------------------------------------------


class CodexExecutionError(Exception):
    """Raised when a stream-json frame carries ``is_error: true``.

    Attributes
    ----------
    frame : Frame
        The offending frame (already fully parsed, raw dict preserved).
    """

    def __init__(self, message: str, frame: "Frame") -> None:
        super().__init__(message)
        self.frame = frame


class CodexTimeoutError(Exception):
    """Raised when stdout produces no data for ``stream_timeout_s`` seconds.

    Attributes
    ----------
    stream_timeout_s : int
        The timeout value that was exceeded.
    """

    def __init__(self, message: str, stream_timeout_s: int) -> None:
        super().__init__(message)
        self.stream_timeout_s = stream_timeout_s


class CodexCrashError(Exception):
    """Raised when the codex subprocess exits with a non-zero code mid-stream.

    Attributes
    ----------
    exit_code : int
        The process exit code (always != 0 when this exception is raised).
    """

    def __init__(self, message: str, exit_code: int) -> None:
        super().__init__(message)
        self.exit_code = exit_code


# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------


@dataclass
class Frame:
    """A single parsed stream-json frame from the Codex CLI.

    Required fields (always present after parsing)
    -----------------------------------------------
    type : str
        Frame type identifier (e.g. ``"message"``, ``"done"``,
        ``"function_call"``, etc.).  Empty string when the key is absent.
    content : str
        Human-readable frame content.  Empty string when absent.
    is_error : bool
        ``True`` when the frame signals an error condition.

    Optional fields
    ---------------
    raw : dict
        The full deserialized JSON dict from the original JSONL line.
        Unknown keys from the Codex CLI are preserved here so callers can
        forward-compatibly access fields not yet modelled by this dataclass.
    """

    type: str
    content: str
    is_error: bool
    raw: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def parse_stream(
    proc: subprocess.Popen,
    *,
    stream_timeout_s: int = _DEFAULT_STREAM_TIMEOUT_S,
    run_id: str = "codex-stream",
    repo_root: str = "",
) -> Iterator[Frame]:
    """Parse ``--output-format stream-json`` JSONL from a running Popen.

    Reads ``proc.stdout`` line by line.  Each well-formed JSON line is decoded
    into a ``Frame``; unknown JSON keys are preserved in ``Frame.raw``.

    Parameters
    ----------
    proc : subprocess.Popen
        A running Popen whose ``stdout`` was opened with ``subprocess.PIPE``.
    stream_timeout_s : int
        Maximum seconds to wait for the next byte from stdout before raising
        ``CodexTimeoutError``.  Defaults to ``_DEFAULT_STREAM_TIMEOUT_S`` (30 s).
    run_id : str
        z-harness run identifier forwarded to telemetry.
    repo_root : str
        Repository root forwarded to telemetry.

    Yields
    ------
    Frame
        One Frame per well-formed JSONL line.

    Raises
    ------
    CodexExecutionError
        When a frame carries ``is_error: true``.
    CodexTimeoutError
        When no data arrives from stdout within ``stream_timeout_s`` seconds.
    CodexCrashError
        When the subprocess has exited with a non-zero code and stdout is
        exhausted (detected after EOF on stdout).
    """
    assert proc.stdout is not None, "proc.stdout must be subprocess.PIPE"

    stdout = proc.stdout

    while True:
        # ------------------------------------------------------------------
        # Timeout guard: use select() to wait for readability with a deadline.
        # ------------------------------------------------------------------
        ready, _, _ = select.select([stdout], [], [], stream_timeout_s)
        if not ready:
            # No data within the timeout window.
            _emit_error_telemetry(
                "stream_timeout",
                exit_code=-1,
                run_id=run_id,
                repo_root=repo_root,
            )
            raise CodexTimeoutError(
                f"Codex stdout produced no data for {stream_timeout_s} seconds.",
                stream_timeout_s=stream_timeout_s,
            )

        raw_line = stdout.readline()

        # readline() returns b"" on EOF.
        if not raw_line:
            break

        line = raw_line.decode("utf-8", errors="replace").rstrip("\n")
        if not line:
            continue

        # ------------------------------------------------------------------
        # Parse JSON; log + skip on malformed input.
        # ------------------------------------------------------------------
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            print(
                f"[codex_stream] WARNING: malformed JSONL line: {line!r}",
                file=sys.stderr,
            )
            _emit_error_telemetry(
                "malformed_jsonl",
                exit_code=-1,
                run_id=run_id,
                repo_root=repo_root,
            )
            continue

        # ------------------------------------------------------------------
        # Build Frame — unknown keys preserved in raw.
        # ------------------------------------------------------------------
        frame = Frame(
            type=data.get("type", ""),
            content=data.get("content", ""),
            is_error=bool(data.get("is_error", False)),
            raw=data,
        )

        # ------------------------------------------------------------------
        # Error frame check.
        # ------------------------------------------------------------------
        if frame.is_error:
            _emit_error_telemetry(
                "execution_error",
                exit_code=-1,
                run_id=run_id,
                repo_root=repo_root,
            )
            raise CodexExecutionError(
                f"Codex frame signalled is_error=true: {data!r}",
                frame=frame,
            )

        yield frame

    # ------------------------------------------------------------------
    # stdout exhausted (EOF).  Check for non-zero exit.
    # ------------------------------------------------------------------
    exit_code = proc.poll()
    if exit_code is None:
        # Process still running after stdout EOF is unusual but non-fatal;
        # wait briefly for it to finish.
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass
        exit_code = proc.returncode

    if exit_code is not None and exit_code != 0:
        _emit_error_telemetry(
            "subprocess_crash",
            exit_code=exit_code,
            run_id=run_id,
            repo_root=repo_root,
        )
        raise CodexCrashError(
            f"Codex subprocess exited with non-zero code {exit_code} after EOF.",
            exit_code=exit_code,
        )


# ---------------------------------------------------------------------------
# Telemetry helper
# ---------------------------------------------------------------------------


def _emit_error_telemetry(
    error_kind: str,
    exit_code: int,
    *,
    run_id: str,
    repo_root: str,
) -> None:
    """Emit ``codex_driver_error`` telemetry.

    Fire-and-forget: any failure here is silently swallowed so that telemetry
    never prevents the parser from raising its primary exception.
    """
    if _log_event is None:
        return

    try:
        _log_event(
            run_id=run_id,
            kind="codex_driver_error",
            payload={
                "error_kind": error_kind,
                "exit_code": exit_code,
            },
            repo_root=repo_root,
        )
    except (FileNotFoundError, RuntimeError):
        # log-event.sh is unavailable outside z-harness; ignore silently.
        pass
