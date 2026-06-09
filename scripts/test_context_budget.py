#!/usr/bin/env python3
"""Smoke test for context-budget.py."""

import subprocess
import sys
import tempfile
from pathlib import Path


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


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
