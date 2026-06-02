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

# Ensure the repo root is on sys.path so the runtime package is importable.
# Walk up to the dir that holds both runtime/ and scripts/ rather than counting
# path levels — robust to non-standard checkout depths (e.g. a git worktree).
_REPO_ROOT = next(
    p for p in Path(__file__).resolve().parents
    if (p / "runtime").is_dir() and (p / "scripts").is_dir()
)
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
    stream_parser.py must not import driver.py (the circular-dep invariant from
    the spec: driver imports stream_parser, so stream_parser must not import back).

    Verified by source/AST inspection rather than a sys.modules probe. Importing
    the submodule `runtime.drivers.antigravity.stream_parser` necessarily runs the
    package __init__, which eagerly imports driver to expose AntigravityDriver as
    the public API — so sys.modules is not a valid probe for this invariant. The
    real, spec-level invariant is that stream_parser's own code never imports driver.
    """
    import ast
    from pathlib import Path

    src = Path(__file__).resolve().parent.parent / "stream_parser.py"
    tree = ast.parse(src.read_text(encoding="utf-8"))

    def _is_driver_module(name: str | None) -> bool:
        return bool(name) and (name == "driver" or name.endswith(".driver"))

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            # from .driver import X  /  from runtime.drivers.antigravity.driver import X
            assert not _is_driver_module(node.module), (
                f"stream_parser must not import from driver (found: from {node.module} import ...)"
            )
            # from . import driver
            for alias in node.names:
                assert alias.name != "driver", (
                    "stream_parser must not import the driver module (found: from . import driver)"
                )
        elif isinstance(node, ast.Import):
            for alias in node.names:
                assert not _is_driver_module(alias.name), (
                    f"stream_parser must not import driver (found: import {alias.name})"
                )
