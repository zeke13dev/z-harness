"""
runtime/drivers/antigravity/driver.py — CLI-tier driver for the agy binary.

Invokes ``agy -p <prompt> --output-format stream-json`` via subprocess.Popen,
feeds stdout through stream_parser.parse_stream(), and yields normalized dicts.

Public surface
--------------
AntigravityDriver
    dispatch(prompt: str) -> Iterator[dict]
        Calls preflight.check() then launches the subprocess.
        Yields each parsed event dict from the stdout stream.
        On non-zero exit raises DriverDispatchError.

    probe() -> bool
        Dispatches a "ping" prompt; returns True if at least one non-error
        event is received.  Writes a READY marker on first successful probe.

DriverDispatchError
    Raised when agy exits non-zero.  Message is the error event message (if
    one appears in the stream) or the raw stderr truncated to 500 chars.

DriverConstraintError
    Raised when agy stderr indicates a nested session constraint violation.

Telemetry events emitted
------------------------
- agy_dispatch_start  — before subprocess launch (prompt_len)
- agy_dispatch_end    — after subprocess exits (exit_code, events_parsed, elapsed_ms)
- agy_ready_written   — when READY marker is written (path)
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from runtime.drivers.antigravity.preflight import DriverUnavailableError, check as preflight_check
from runtime.drivers.antigravity.stream_parser import parse_stream

try:
    from runtime.compat import log_event as _log_event
except ImportError:
    _log_event = None  # type: ignore[assignment]

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Maximum characters of raw stderr included in DriverDispatchError messages.
_STDERR_TRUNCATE = 500

#: Substring in agy stderr that signals a nested-session constraint violation.
_NESTED_SESSION_MARKER = "nested session"

#: Path to the READY marker file; relative to this file's directory.
_READY_PATH: Path = Path(__file__).parent / "READY"


# ---------------------------------------------------------------------------
# Public exception types
# ---------------------------------------------------------------------------


class DriverDispatchError(Exception):
    """
    Raised when agy exits with a non-zero status code.

    The message is either:
    - The ``message`` field from an error-type event in the stream, or
    - Raw agy stderr truncated to 500 characters.
    """


class DriverConstraintError(Exception):
    """
    Raised when agy refuses to run due to a constraint violation (e.g. nesting).

    The Antigravity CLI does not support nested sessions.  If z-harness is
    invoked from within an existing agy session, this exception is raised so
    the caller can surface an actionable error rather than a generic failure.
    """


# ---------------------------------------------------------------------------
# AntigravityDriver
# ---------------------------------------------------------------------------


class AntigravityDriver:
    """CLI-tier driver that dispatches prompts to the agy binary.

    Usage
    -----
    driver = AntigravityDriver()
    for event in driver.dispatch("summarise the repo"):
        print(event)

    Notes
    -----
    - Pre-flight is called on every dispatch() call to confirm agy is available.
    - The driver is stateless between calls; no session or connection is held.
    - probe() returns True if a dispatch round-trip succeeds and writes the
      READY marker on the first successful probe.
    """

    def __init__(
        self,
        *,
        run_id: str | None = None,
        repo_root: str | None = None,
    ) -> None:
        self._run_id: str = run_id or os.environ.get("Z_HARNESS_RUN_ID", "agy-driver")
        self._repo_root: str = repo_root or os.environ.get(
            "Z_HARNESS_REPO_ROOT", os.getcwd()
        )
        self._ready_written: bool = False
        self._last_agy_version: str = ""

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def dispatch(self, prompt: str) -> Iterator[dict]:
        """Dispatch a prompt to agy and yield parsed stream-json events.

        Parameters
        ----------
        prompt : str
            The prompt text to send to agy via the ``-p`` flag.

        Yields
        ------
        dict
            Normalized event dicts from stream_parser.parse_stream().

        Raises
        ------
        DriverUnavailableError
            If pre-flight determines that agy is not available.
        DriverConstraintError
            If agy stderr indicates a nested-session constraint violation.
        DriverDispatchError
            If agy exits with a non-zero exit code.
        """
        # Pre-flight guard — capture version string for READY marker.
        self._last_agy_version = preflight_check(run_id=self._run_id, repo_root=self._repo_root)

        t_start = time.monotonic()
        prompt_len = len(prompt)

        self._emit("agy_dispatch_start", {"prompt_len": prompt_len})

        cmd = ["agy", "-p", prompt, "--output-format", "stream-json"]

        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        events_parsed = 0
        error_message: str | None = None
        collected_events: list[dict] = []

        assert proc.stdout is not None  # guaranteed by stdout=PIPE

        for event in parse_stream(proc.stdout):
            events_parsed += 1
            collected_events.append(event)
            # Track any error-type event message for use in exception raising.
            if event.get("type") == "error" and error_message is None:
                error_message = event.get("message") or event.get("error") or None
            yield event

        proc.wait()
        exit_code = proc.returncode if proc.returncode is not None else -1
        elapsed_ms = round((time.monotonic() - t_start) * 1000.0, 1)

        self._emit(
            "agy_dispatch_end",
            {
                "exit_code": exit_code,
                "events_parsed": events_parsed,
                "elapsed_ms": elapsed_ms,
            },
        )

        if exit_code != 0:
            # Read stderr for nesting detection and error messages.
            assert proc.stderr is not None
            stderr_text = proc.stderr.read()

            # Nesting constraint check takes priority.
            if _NESTED_SESSION_MARKER in stderr_text.lower():
                raise DriverConstraintError(
                    "agy does not support nested sessions; "
                    "z-harness cannot be invoked from within an active agy session."
                )

            # Use error event message if available; fall back to raw stderr.
            if error_message is not None:
                raise DriverDispatchError(error_message)

            truncated_stderr = stderr_text[:_STDERR_TRUNCATE]
            raise DriverDispatchError(
                f"agy exited with code {exit_code}: {truncated_stderr}"
                if truncated_stderr
                else f"agy exited with code {exit_code}"
            )

    def probe(self) -> bool:
        """Dispatch a minimal ping prompt; return True on success.

        Writes the READY marker on first successful probe.

        Returns
        -------
        bool
            True if at least one non-error event was received; False otherwise.

        Notes
        -----
        DriverUnavailableError raised by dispatch() propagates unchanged so
        the caller can distinguish "agy not installed" from a dispatch failure.
        """
        try:
            non_error_count = 0
            for event in self.dispatch("ping"):
                if event.get("type") != "error" and event.get("type") != "parse_error":
                    non_error_count += 1

            if non_error_count > 0:
                if not self._ready_written:
                    self._write_ready()
                return True
            return False
        except (DriverDispatchError, DriverConstraintError):
            return False

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _write_ready(self) -> None:
        """Write the READY marker file and emit agy_ready_written telemetry.

        Idempotent: if the file already exists on disk, the write is skipped and
        telemetry is not re-emitted.  The in-process ``_ready_written`` flag
        prevents redundant calls within the same driver instance lifetime.
        """
        ready_path = _READY_PATH

        # Disk-level idempotency: do not overwrite if already present.
        if ready_path.exists():
            self._ready_written = True
            return

        verified_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        content = f"agy_version={self._last_agy_version}\nverified_at={verified_at}\n"

        try:
            ready_path.write_text(content)
        except OSError as exc:
            print(
                f"[agy_driver] WARNING: could not write READY marker: {exc}",
                file=sys.stderr,
            )
            return

        self._ready_written = True
        self._emit("agy_ready_written", {"path": str(ready_path)})

    def _emit(self, kind: str, payload: dict) -> None:
        """Fire-and-forget telemetry emission; never raises."""
        if _log_event is None:
            return
        try:
            _log_event(
                run_id=self._run_id,
                kind=kind,
                payload=payload,
                repo_root=self._repo_root,
            )
        except (FileNotFoundError, RuntimeError, OSError) as exc:
            print(
                f"[agy_driver] WARNING: telemetry event '{kind}' failed: {exc}",
                file=sys.stderr,
            )
