"""
runtime/drivers/antigravity/stream_parser.py — JSONL stream-json output parser.

Parses the JSONL output of `agy -p --output-format stream-json`.

Public surface
--------------
parse_stream(lines) -> Iterator[dict]
    Generator that yields one normalized dict per input line.
    Normalized dicts always contain at minimum:
        {"type": str, "raw": dict}

Malformed lines yield:
        {"type": "parse_error", "raw_line": str, "error": str}
    and emit an ``agy_stream_parse_error`` telemetry event; they do NOT raise.

This module does NOT import driver.py to avoid circular dependencies.
"""

from __future__ import annotations

import json
import os
from typing import Iterator

try:
    from runtime.compat import log_event
except ImportError:
    log_event = None  # type: ignore[assignment]

_TRUNCATE_LEN = 200
_RUN_ID_ENV = "Z_HARNESS_RUN_ID"


def _emit_parse_error(raw_line: str, error: str) -> None:
    """Emit agy_stream_parse_error telemetry if log_event is available."""
    if log_event is None:
        return
    run_id = os.environ.get(_RUN_ID_ENV, "stream-parser")
    repo_root = os.environ.get("Z_HARNESS_REPO_ROOT", os.getcwd())
    try:
        log_event(
            run_id,
            "agy_stream_parse_error",
            {"line": raw_line[:_TRUNCATE_LEN], "error": error},
            repo_root,
        )
    except Exception:  # noqa: BLE001 — telemetry must never crash the parser
        pass


def parse_stream(lines: "Iterable[str]") -> Iterator[dict]:
    """
    Parse an iterable of JSONL lines from an agy stream-json subprocess.

    Parameters
    ----------
    lines:
        Any iterable of strings (e.g. a file object, list of strings, or
        the stdout of a subprocess).  Each string is treated as one JSONL
        line; leading/trailing whitespace is stripped before parsing.

    Yields
    ------
    dict
        For valid lines: ``{"type": str, "raw": dict, ...}`` where ``type``
        is the event's ``type`` field and ``raw`` is the full parsed dict.
        Additional top-level keys from the parsed event are preserved.

        For malformed lines: ``{"type": "parse_error",
        "raw_line": str, "error": str}``.

    Notes
    -----
    Empty lines (blank or whitespace-only) are silently skipped.
    This generator does not raise; all errors are caught and yielded as
    ``parse_error`` events.
    """
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue

        # Attempt JSON decode
        try:
            data = json.loads(stripped)
        except json.JSONDecodeError as exc:
            raw_line = stripped[:_TRUNCATE_LEN]
            _emit_parse_error(raw_line, str(exc))
            yield {"type": "parse_error", "raw_line": raw_line, "error": str(exc)}
            continue

        # Require a dict at the top level
        if not isinstance(data, dict):
            error = f"expected JSON object, got {type(data).__name__}"
            raw_line = stripped[:_TRUNCATE_LEN]
            _emit_parse_error(raw_line, error)
            yield {"type": "parse_error", "raw_line": raw_line, "error": error}
            continue

        # Require a 'type' field
        if "type" not in data:
            error = "missing required field: 'type'"
            raw_line = stripped[:_TRUNCATE_LEN]
            _emit_parse_error(raw_line, error)
            yield {"type": "parse_error", "raw_line": raw_line, "error": error}
            continue

        # Valid event: build normalized dict, preserving all original fields
        event_type = data["type"]
        normalized: dict = {"type": event_type, "raw": data}
        # Surface additional top-level keys for caller convenience
        for key, value in data.items():
            if key not in normalized:
                normalized[key] = value

        yield normalized
