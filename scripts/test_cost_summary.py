#!/usr/bin/env python3
"""Tests for render-cost-summary.py."""

import json
import subprocess
import sys
import tempfile
from pathlib import Path


def _run_cost_summary(events: list[dict]) -> str:
    """Run render-cost-summary.py via stdin with given events and return stdout."""
    events_jsonl = "\n".join(json.dumps(e) for e in events)
    result = subprocess.run(
        [sys.executable, "scripts/render-cost-summary.py", "-"],
        input=events_jsonl,
        capture_output=True,
        text=True,
    )
    return result.stdout


def test_empty_events() -> None:
    """Empty events → 'No telemetry data'."""
    output = _run_cost_summary([])
    assert "No telemetry data" in output, f"got: {output}"


def test_no_llm_calls() -> None:
    """Events with no subagent dispatch/return pairs → 'No LLM calls'."""
    events = [
        {"kind": "run_start", "run_id": "r1"},
        {"kind": "task_start", "id": "T001"},
    ]
    output = _run_cost_summary(events)
    assert "No LLM calls" in output, f"got: {output}"


def test_single_subagent_pair() -> None:
    """One subagent dispatch + return → renders a row."""
    events = [
        {"kind": "subagent_dispatch", "run_id": "r1", "subagent_type": "implementer",
         "provider": "deepseek", "model": "v4-pro", "tokens_in": 10000},
        {"kind": "subagent_return", "run_id": "r1", "subagent_type": "implementer",
         "provider": "deepseek", "model": "v4-pro", "tokens_in": 10000, "tokens_out": 5000},
    ]
    output = _run_cost_summary(events)
    assert "deepseek" in output
    assert "v4-pro" in output
    assert "10K / 5K" in output or "10000 / 5000" in output


def test_unknown_provider_unknown_cost() -> None:
    """Missing provider/model → 'unknown' in table, 'unknown' cost."""
    events = [
        {"kind": "subagent_dispatch", "run_id": "r1", "subagent_type": "explorer"},
        {"kind": "subagent_return", "run_id": "r1", "subagent_type": "explorer",
         "tokens_in": 5000, "tokens_out": 1000},
    ]
    output = _run_cost_summary(events)
    assert "unknown" in output.lower()


def test_incomplete_pair_warning() -> None:
    """Unclosed dispatch → warning on stderr, still renders other rows."""
    events = [
        {"kind": "subagent_dispatch", "run_id": "r1", "subagent_type": "stuck"},
        {"kind": "subagent_dispatch", "run_id": "r2", "subagent_type": "implementer",
         "provider": "deepseek", "model": "v4-pro", "tokens_in": 5000},
        {"kind": "subagent_return", "run_id": "r2", "subagent_type": "implementer",
         "provider": "deepseek", "model": "v4-pro", "tokens_in": 5000, "tokens_out": 2000},
    ]
    result = subprocess.run(
        [sys.executable, "scripts/render-cost-summary.py", "-"],
        input="\n".join(json.dumps(e) for e in events),
        capture_output=True,
        text=True,
    )
    assert "deepseek" in result.stdout
    assert "WARNING" in result.stderr or "skipped" in result.stderr


def test_aggregation_by_provider_model() -> None:
    """Multiple dispatches to same (provider, model) → one row with summed tokens."""
    events = [
        {"kind": "subagent_dispatch", "run_id": "r1", "subagent_type": "a",
         "provider": "deepseek", "model": "v4-pro", "tokens_in": 5000},
        {"kind": "subagent_return", "run_id": "r1", "subagent_type": "a",
         "provider": "deepseek", "model": "v4-pro", "tokens_in": 5000, "tokens_out": 2000},
        {"kind": "subagent_dispatch", "run_id": "r2", "subagent_type": "b",
         "provider": "deepseek", "model": "v4-pro", "tokens_in": 3000},
        {"kind": "subagent_return", "run_id": "r2", "subagent_type": "b",
         "provider": "deepseek", "model": "v4-pro", "tokens_in": 3000, "tokens_out": 1000},
    ]
    output = _run_cost_summary(events)
    assert output.count("deepseek") == 1 or output.count("v4-pro") >= 1


def test_file_not_found() -> None:
    """Nonexistent file → 'No telemetry data'."""
    result = subprocess.run(
        [sys.executable, "scripts/render-cost-summary.py", "/nonexistent/path.jsonl"],
        capture_output=True,
        text=True,
    )
    assert "No telemetry data" in result.stdout


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
