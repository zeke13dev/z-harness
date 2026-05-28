"""
Tests for runtime/drivers/antigravity/stream_parser.py

Fixtures cover:
  - valid multi-event stream
  - single malformed line in an otherwise valid stream
  - empty stream
"""

import json
import sys
from pathlib import Path

import pytest

# Ensure the repo root is on sys.path so the runtime package is importable
_REPO_ROOT = Path(__file__).resolve().parents[5]  # …/z-harness
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from runtime.drivers.antigravity.stream_parser import parse_stream  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

VALID_EVENT_1 = {"type": "text", "content": "hello", "id": "ev1"}
VALID_EVENT_2 = {"type": "done", "exit_code": 0}
MALFORMED_JSON = "this is not json {"
MISSING_TYPE = json.dumps({"content": "no type field here"})


# ---------------------------------------------------------------------------
# Test: valid multi-event stream
# ---------------------------------------------------------------------------


def test_valid_multi_event_stream():
    """
    All valid JSONL lines are parsed; each yield has 'type' and 'raw' keys;
    'type' matches the source event's type field.
    """
    lines = [
        json.dumps(VALID_EVENT_1),
        json.dumps(VALID_EVENT_2),
    ]
    results = list(parse_stream(lines))

    assert len(results) == 2

    assert results[0]["type"] == "text"
    assert results[0]["raw"] == VALID_EVENT_1

    assert results[1]["type"] == "done"
    assert results[1]["raw"] == VALID_EVENT_2


def test_normalized_dict_has_required_keys():
    """
    Every non-error event must expose at minimum {"type": str, "raw": dict}.
    """
    lines = [json.dumps({"type": "progress", "pct": 42})]
    results = list(parse_stream(lines))

    assert len(results) == 1
    ev = results[0]
    assert isinstance(ev["type"], str)
    assert isinstance(ev["raw"], dict)


# ---------------------------------------------------------------------------
# Test: single malformed line in otherwise valid stream
# ---------------------------------------------------------------------------


def test_malformed_line_yields_parse_error_not_raise():
    """
    A malformed JSON line must NOT raise; it must yield a parse_error dict.
    Valid lines before and after the malformed line must still be yielded.
    """
    lines = [
        json.dumps(VALID_EVENT_1),   # valid
        MALFORMED_JSON,               # malformed
        json.dumps(VALID_EVENT_2),   # valid
    ]
    results = list(parse_stream(lines))

    assert len(results) == 3

    # First: valid
    assert results[0]["type"] == "text"

    # Second: parse_error
    err = results[1]
    assert err["type"] == "parse_error"
    assert "raw_line" in err
    assert "error" in err
    assert isinstance(err["error"], str)
    # raw_line must be truncated to ≤200 chars
    assert len(err["raw_line"]) <= 200

    # Third: valid
    assert results[2]["type"] == "done"


def test_missing_type_field_yields_parse_error():
    """
    A valid JSON object that lacks a 'type' field is treated as malformed.
    """
    lines = [MISSING_TYPE]
    results = list(parse_stream(lines))

    assert len(results) == 1
    assert results[0]["type"] == "parse_error"
    assert "type" in results[0]["error"].lower() or "missing" in results[0]["error"].lower()


def test_raw_line_truncated_to_200_chars():
    """
    raw_line in a parse_error event must be ≤200 characters even for very
    long malformed input.
    """
    long_line = "x" * 500
    results = list(parse_stream([long_line]))

    assert results[0]["type"] == "parse_error"
    assert len(results[0]["raw_line"]) == 200


# ---------------------------------------------------------------------------
# Test: empty stream
# ---------------------------------------------------------------------------


def test_empty_stream_yields_nothing():
    """
    An empty iterable produces no output at all.
    """
    results = list(parse_stream([]))
    assert results == []


def test_whitespace_only_lines_skipped():
    """
    Lines that are blank or contain only whitespace are silently skipped.
    """
    lines = ["", "   ", "\t\n", json.dumps(VALID_EVENT_1)]
    results = list(parse_stream(lines))

    assert len(results) == 1
    assert results[0]["type"] == "text"


# ---------------------------------------------------------------------------
# Test: no import of driver.py (no circular dependency)
# ---------------------------------------------------------------------------


def test_stream_parser_does_not_import_driver():
    """
    Importing stream_parser must NOT cause driver to appear in sys.modules.
    This guards against the circular-dep invariant stated in the spec.
    """
    import importlib
    import sys

    # Remove any cached import so we get a fresh load
    mods_to_purge = [k for k in sys.modules if "antigravity" in k]
    for mod in mods_to_purge:
        sys.modules.pop(mod, None)

    import runtime.drivers.antigravity.stream_parser  # noqa: F401

    assert "runtime.drivers.antigravity.driver" not in sys.modules
