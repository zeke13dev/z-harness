"""
normalize.py — Nondeterminism stripper for conformance harness.

Strips timestamps, run-IDs, and numeric nondeterministic fields from JSONL
event lines before diffing against golden fixtures.
"""

from __future__ import annotations

import json
import re
from typing import Any

# ISO 8601 datetime pattern (with or without fractional seconds and timezone).
# Matches: 2026-05-27T05:05:49Z, 2026-05-27T05:05:49.123Z, 2026-05-27T05:05:49+00:00
_TIMESTAMP_RE = re.compile(
    r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})"
)

# Run-ID pattern: YYYYMMDDTHHMMSSz-<slug>, e.g. 20260527T050549Z-harness-distribution-strategy
_RUN_ID_RE = re.compile(r"\d{8}T\d{6}Z-[A-Za-z0-9_-]+")

# Bare run-ID segment pattern (used in path stripping — no trailing slug required).
_RUN_ID_SEGMENT_RE = re.compile(r"\d{8}T\d{6}Z(?:-[A-Za-z0-9_-]+)?")

# Numeric fields that are inherently nondeterministic and must be removed entirely.
_NUMERIC_FIELDS = frozenset(
    [
        "latency_ms",
        "duration_ms",
        "elapsed_s",
        "cache_hit",
        "cache_miss",
        "cached_tokens",
        "input_tokens",
        "output_tokens",
    ]
)


def _normalize_value(value: Any) -> Any:
    """Recursively replace nondeterministic string patterns in a JSON value."""
    if isinstance(value, str):
        # Replace run-IDs first (they contain a timestamp-like prefix).
        value = _RUN_ID_RE.sub("__RUN_ID__", value)
        # Replace any remaining ISO 8601 timestamps.
        value = _TIMESTAMP_RE.sub("__TIMESTAMP__", value)
        return value
    if isinstance(value, dict):
        return _normalize_dict(value)
    if isinstance(value, list):
        return [_normalize_value(item) for item in value]
    return value


def _normalize_dict(d: dict) -> dict:
    """Remove nondeterministic numeric keys and normalize remaining values."""
    result: dict = {}
    for key, value in d.items():
        if key in _NUMERIC_FIELDS:
            # Drop the key entirely — do not replace with a sentinel.
            continue
        result[key] = _normalize_value(value)
    return result


def normalize_events(jsonl_str: str) -> str:
    """Normalize a JSONL string by stripping nondeterministic fields.

    For each line:
    - If valid JSON: strip timestamps, run-IDs, and numeric nondeterministic
      fields, then re-serialize compactly.
    - If not valid JSON: pass through unchanged.

    Args:
        jsonl_str: A string containing zero or more newline-separated JSON
            objects (JSONL format).

    Returns:
        A normalized JSONL string with the same number of lines.
    """
    output_lines: list[str] = []
    for line in jsonl_str.splitlines():
        stripped = line.rstrip("\r")
        try:
            obj = json.loads(stripped)
        except (json.JSONDecodeError, ValueError):
            # Not valid JSON — pass through unchanged.
            output_lines.append(line)
            continue
        normalized = _normalize_value(obj)
        output_lines.append(json.dumps(normalized, separators=(",", ":")))
    return "\n".join(output_lines)


def normalize_artifact_list(paths: list[str]) -> list[str]:
    """Sort a list of artifact paths and strip run-ID path segments.

    Any path segment that matches the run-ID pattern (YYYYMMDDTHHMMSSz or
    YYYYMMDDTHHMMSSz-<slug>) is removed from the path, and any double slashes
    that result are collapsed.

    Args:
        paths: List of artifact file paths (absolute or relative).

    Returns:
        Sorted list of paths with run-ID segments removed.
    """
    normalized: list[str] = []
    for path in paths:
        # Split the path into segments, filter out run-ID segments, re-join.
        segments = path.split("/")
        clean_segments = [
            seg for seg in segments if not _RUN_ID_SEGMENT_RE.fullmatch(seg)
        ]
        clean_path = "/".join(clean_segments)
        # Collapse any double slashes introduced by removing a leading segment.
        while "//" in clean_path:
            clean_path = clean_path.replace("//", "/")
        normalized.append(clean_path)
    return sorted(normalized)
