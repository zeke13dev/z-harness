#!/usr/bin/env python3
"""Smoke test for evaluate-session.py."""

import subprocess
import sys
import tempfile
from pathlib import Path


def test_directory_not_found() -> None:
    """Nonexistent directory → 'No telemetry data'."""
    result = subprocess.run(
        [sys.executable, "scripts/evaluate-session.py", "/nonexistent/dir"],
        capture_output=True,
        text=True,
    )
    assert "No telemetry data" in result.stdout
    assert result.returncode == 0


def test_empty_archive() -> None:
    """Empty archive directory → 'No telemetry data'."""
    with tempfile.TemporaryDirectory() as tmp:
        result = subprocess.run(
            [sys.executable, "scripts/evaluate-session.py", tmp],
            capture_output=True,
            text=True,
        )
        assert "No telemetry data" in result.stdout
        assert result.returncode == 0


def test_with_events() -> None:
    """Archive with events → renders patterns section."""
    import json
    with tempfile.TemporaryDirectory() as tmp:
        events = [
            {"kind": "task_start", "id": "T001"},
            {"kind": "task_done", "id": "T001", "review_cycles": 2, "total_retries": 1},
            {"kind": "task_start", "id": "T002"},
            {"kind": "task_halt", "id": "T002", "reason": "test"},
        ]
        (Path(tmp) / "events.jsonl").write_text(
            "\n".join(json.dumps(e) for e in events)
        )
        result = subprocess.run(
            [sys.executable, "scripts/evaluate-session.py", tmp],
            capture_output=True,
            text=True,
        )
        assert "Detected Patterns" in result.stdout
        assert result.returncode == 0


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
