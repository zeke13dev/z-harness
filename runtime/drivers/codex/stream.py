"""
runtime/drivers/codex/stream.py — JSONL parser for the Codex CLI driver.

Parses the ``--json`` byte stream from a ``codex exec --json -`` subprocess
line by line, yielding typed ``Frame`` objects to the caller.

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
from typing import Any, Iterator, Optional

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

EVENT_FAMILY_AGENT = "agent"
EVENT_FAMILY_SUBAGENT = "subagent"
EVENT_FAMILY_ASK_USER = "ask_user"
EVENT_FAMILY_GATE = "gate"
EVENT_FAMILY_TOOL = "tool"
EVENT_FAMILY_FINAL_RESULT = "final_result"
EVENT_FAMILY_TELEMETRY = "telemetry"
EVENT_FAMILY_ERROR = "error"
EVENT_FAMILY_MESSAGE = "message"
EVENT_FAMILY_UNKNOWN = "unknown"

_MARKER_FIELDS: tuple[str, ...] = (
    "type",
    "event",
    "kind",
    "name",
    "category",
    "role",
    "op",
    "action",
)
_CONTENT_FIELDS: tuple[str, ...] = (
    "content",
    "text",
    "message",
    "delta",
    "output",
    "result",
    "final_result",
    "final_answer",
    "summary",
    "prompt",
    "question",
)
_NESTED_CONTENT_FIELDS: tuple[str, ...] = (
    "content",
    "text",
    "message",
    "delta",
    "output",
    "result",
    "final_result",
    "final_answer",
    "summary",
    "prompt",
    "question",
)


# ---------------------------------------------------------------------------
# Public exceptions
# ---------------------------------------------------------------------------


class CodexExecutionError(Exception):
    """Raised when a Codex JSONL frame carries ``is_error: true``.

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
    """A single parsed JSONL frame from the Codex CLI.

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
    event_family : str
        Conservative semantic family derived from native Codex event fields.
        This is classification metadata only; ``raw`` remains the source of
        truth and is never rewritten.
    """

    type: str
    content: str
    is_error: bool
    raw: dict = field(default_factory=dict)
    event_family: str = EVENT_FAMILY_UNKNOWN


def classify_event_family(raw: dict) -> str:
    """Return a conservative semantic family for a native Codex event frame.

    The classifier recognizes the event families z-harness needs to preserve
    across Codex streams (agent/subagent, ask/gate prompts, tools, final
    results, and telemetry) without translating the frame into a separate
    model.  Unknown or future Codex frames remain ``"unknown"`` while their raw
    keys stay available through ``Frame.raw``.
    """
    if not isinstance(raw, dict):
        return EVENT_FAMILY_UNKNOWN

    markers, keys = _classification_context(raw)

    if bool(raw.get("is_error")) or _marker_matches(markers, ("error", "exception")):
        return EVENT_FAMILY_ERROR
    if _marker_matches(markers, ("agent_message", "assistant_message")):
        return EVENT_FAMILY_MESSAGE
    if _has_any_key(
        keys,
        ("subagent", "subagent_id", "subagent_name", "subagent_type"),
    ) or _marker_matches(markers, ("subagent", "sub_agent")):
        return EVENT_FAMILY_SUBAGENT
    if _has_any_key(
        keys,
        ("agent", "agent_id", "agent_name", "agent_type"),
    ) or _marker_matches(markers, ("agent",)):
        return EVENT_FAMILY_AGENT
    if _has_any_key(keys, ("ask_user", "prompt_user", "user_question")) or (
        "question" in keys and ("choices" in keys or "options" in keys)
    ) or _marker_matches(markers, ("ask_user", "prompt_user", "user_question")):
        return EVENT_FAMILY_ASK_USER
    if _has_any_key(keys, ("gate", "gate_id", "approval_request")) or _marker_matches(
        markers,
        ("gate", "user_gate", "approval_request", "resolve_question"),
    ):
        return EVENT_FAMILY_GATE
    if _has_any_key(
        keys,
        (
            "tool",
            "tool_call",
            "tool_call_id",
            "tool_name",
            "tool_result",
            "function_call",
            "function_call_id",
            "command_execution",
            "command_execution_id",
        ),
    ) or _marker_matches(
        markers,
        (
            "tool",
            "tool_call",
            "tool_result",
            "function_call",
            "function_call_output",
            "command_execution",
            "command_execution_output",
            "mcp_tool_call",
        ),
    ):
        return EVENT_FAMILY_TOOL
    if _has_any_key(keys, ("telemetry", "usage", "metrics", "token_usage")) or (
        ("input_tokens" in keys or "output_tokens" in keys) and "type" in keys
    ) or _marker_matches(markers, ("telemetry", "usage", "metrics", "token_usage")):
        return EVENT_FAMILY_TELEMETRY
    if _has_any_key(keys, ("final_result", "final_answer")) or _marker_matches(
        markers,
        ("final", "final_result", "final_answer", "done", "completed"),
    ):
        return EVENT_FAMILY_FINAL_RESULT
    if _marker_matches(markers, ("message", "assistant_message")):
        return EVENT_FAMILY_MESSAGE
    return EVENT_FAMILY_UNKNOWN


def extract_frame_content(raw: dict) -> str:
    """Extract human-readable content from common Codex JSONL frame fields."""
    if not isinstance(raw, dict):
        return ""

    for key in _CONTENT_FIELDS:
        text = _coerce_content(raw.get(key), depth=0)
        if text:
            return text
    item = raw.get("item")
    if isinstance(item, dict):
        text = _coerce_content(item, depth=0)
        if text:
            return text
    return ""


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
    """Parse ``codex exec --json`` JSONL from a running Popen.

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
            content=extract_frame_content(data),
            is_error=bool(data.get("is_error", False)),
            raw=data,
            event_family=classify_event_family(data),
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


def _classification_context(raw: dict) -> tuple[tuple[str, ...], set[str]]:
    """Collect conservative top-level and Codex ``item`` classification hints."""
    markers = list(_event_markers(raw))
    keys = {_normalise_marker(str(key)) for key in raw}

    item = raw.get("item")
    if isinstance(item, dict):
        markers.extend(_event_markers(item))
        keys.update(_normalise_marker(str(key)) for key in item)

    return tuple(markers), keys


def _event_markers(raw: dict) -> tuple[str, ...]:
    markers: list[str] = []
    for field_name in _MARKER_FIELDS:
        value = raw.get(field_name)
        if isinstance(value, str) and value.strip():
            markers.append(_normalise_marker(value))
    return tuple(markers)


def _normalise_marker(value: str) -> str:
    chars = [ch.lower() if ch.isalnum() else "_" for ch in value]
    return "_".join(part for part in "".join(chars).split("_") if part)


def _has_any_key(keys: set[str], candidates: tuple[str, ...]) -> bool:
    return any(candidate in keys for candidate in candidates)


def _marker_matches(markers: tuple[str, ...], candidates: tuple[str, ...]) -> bool:
    for marker in markers:
        for candidate in candidates:
            if (
                marker == candidate
                or marker.startswith(f"{candidate}_")
                or marker.endswith(f"_{candidate}")
                or f"_{candidate}_" in marker
            ):
                return True
    return False


def _coerce_content(value: Any, *, depth: int) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts = [
            part
            for item in value
            if (part := _coerce_content(item, depth=depth + 1))
        ]
        return "\n".join(parts)
    if isinstance(value, dict) and depth < 3:
        for key in _NESTED_CONTENT_FIELDS:
            text = _coerce_content(value.get(key), depth=depth + 1)
            if text:
                return text
    return ""
