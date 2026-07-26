#!/usr/bin/env python3
"""Smoke test for context-budget.py."""

import importlib.util
import json
import subprocess
import sys
import tempfile
from pathlib import Path

_SCRIPT = Path(__file__).with_name("context-budget.py")
_SPEC = importlib.util.spec_from_file_location("context_budget", _SCRIPT)
assert _SPEC is not None and _SPEC.loader is not None
context_budget = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(context_budget)


def _write_native_usage(path: Path) -> None:
    rows = [
        {"event": "usage", "session_id": "root", "timestamp": 10_000_000_000, "input_tokens": 80, "cached_input_tokens": 10, "output_tokens": 20, "reasoning_output_tokens": 5, "total_tokens": 100},
        {"event": "turn_start", "session_id": "root", "timestamp": 10_000_000_000, "turn_id": "root-turn"},
        {"event": "tool_start", "session_id": "root", "timestamp": 10_000_000_200, "tool_call_id": "root-tool"},
        {"event": "tool_end", "session_id": "root", "timestamp": 10_000_000_600, "tool_call_id": "root-tool"},
        {"event": "usage", "session_id": "root", "timestamp": 10_000_001_000, "input_tokens": 120, "cached_input_tokens": 10, "output_tokens": 30, "reasoning_output_tokens": 5, "total_tokens": 150},
        {"event": "turn_end", "session_id": "root", "timestamp": 10_000_001_000, "turn_id": "root-turn"},
        {"event": "usage", "session_id": "child", "parent_session_id": "root", "timestamp": 10_000_000_100, "input_tokens": 80, "cached_input_tokens": 10, "output_tokens": 20, "reasoning_output_tokens": 5, "total_tokens": 100},
        {"event": "turn_start", "session_id": "child", "parent_session_id": "root", "timestamp": 10_000_000_100, "turn_id": "child-turn"},
        {"event": "tool_start", "session_id": "child", "parent_session_id": "root", "timestamp": 10_000_000_400, "tool_call_id": "child-tool"},
        {"event": "tool_end", "session_id": "child", "parent_session_id": "root", "timestamp": 10_000_000_600, "tool_call_id": "child-tool"},
        {"event": "usage", "session_id": "child", "parent_session_id": "root", "timestamp": 10_000_000_700, "input_tokens": 100, "cached_input_tokens": 10, "output_tokens": 25, "reasoning_output_tokens": 5, "total_tokens": 125},
        {"event": "turn_end", "session_id": "child", "parent_session_id": "root", "timestamp": 10_000_000_900, "turn_id": "child-turn"},
    ]
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")


def test_directory_not_found() -> None:
    """Nonexistent directory → graceful output."""
    result = subprocess.run(
        [sys.executable, "scripts/context-budget.py", "/nonexistent/dir"],
        capture_output=True,
        text=True,
    )
    assert "No telemetry data" in result.stdout or "not found" in result.stderr
    assert result.returncode == 0


def test_empty_archive() -> None:
    """Empty archive directory → healthy session output."""
    with tempfile.TemporaryDirectory() as tmp:
        result = subprocess.run(
            [sys.executable, "scripts/context-budget.py", tmp],
            capture_output=True,
            text=True,
        )
        assert "healthy" in result.stdout.lower() or "no actionable" in result.stdout.lower()
        assert result.returncode == 0


def test_with_minimal_events() -> None:
    """Archive with a few events → renders table."""
    import json
    with tempfile.TemporaryDirectory() as tmp:
        events = [
            {"kind": "task_start", "id": "T001"},
            {"kind": "task_done", "id": "T001"},
        ]
        (Path(tmp) / "events.jsonl").write_text(
            "\n".join(json.dumps(e) for e in events)
        )
        result = subprocess.run(
            [sys.executable, "scripts/context-budget.py", tmp],
            capture_output=True,
            text=True,
        )
        assert "Event count" in result.stdout
        assert result.returncode == 0


def test_context_pressure_uses_canonical_native_usage(tmp_path: Path) -> None:
    """INTENT criteria #8/#9: pressure uses marginal totals and exposes quality."""
    _write_native_usage(tmp_path / "native-usage.jsonl")
    pressure = context_budget.estimate_context_pressure(
        tmp_path,
        env={},
        fallback_window_tokens=1000,
    )
    native = pressure["components"]["native_usage"]
    sessions = {item["canonical_usage"]["completeness"]: item for item in native["sessions"]}
    assert pressure["estimated_tokens"] == 175
    assert sessions["complete"]["canonical_usage"]["known_subtotal_tokens"] == 150
    assert sessions["partial"]["canonical_usage"]["known_subtotal_tokens"] == 25
    assert sessions["partial"]["canonical_usage"]["unknown_segment_count"] == 1
    assert sessions["partial"]["canonical_usage"]["unknown_reasons"] == ["ambiguous_inheritance"]
    assert sessions["complete"]["canonical_timing"]["run_elapsed_ms"] == 1000
    assert sessions["complete"]["canonical_timing"]["clock_provenance"] == ["provider"]
    assert sessions["complete"]["canonical_timing"]["derived_idle_ms"] == 0


def test_partial_native_usage_keeps_conservative_telemetry_estimate(tmp_path: Path) -> None:
    """INTENT criterion #8: unknown native segments cannot reduce pressure."""
    _write_native_usage(tmp_path / "native-usage.jsonl")
    (tmp_path / "events.jsonl").write_text(
        json.dumps({"provider_total_tokens": 500}) + "\n",
        encoding="utf-8",
    )
    pressure = context_budget.estimate_context_pressure(
        tmp_path,
        env={},
        fallback_window_tokens=1000,
    )
    components = pressure["components"]
    assert components["telemetry_tokens"] == 500
    assert components["native_usage"] is not None
    assert pressure["estimated_tokens"] == 500


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
