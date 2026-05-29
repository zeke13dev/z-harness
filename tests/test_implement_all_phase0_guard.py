"""
tests/test_implement_all_phase0_guard.py — Tests for Phase 0 lock-check Python snippet
used in /z-implement-next and /z-implement-all.

The snippet is duplicated in both command markdown files and cannot be imported
directly (it lives in markdown, not a .py module). This test file copies the
logic into a helper function `_count_running` and exercises it directly.

Invariant tested: the Phase 0 guard must correctly count entries whose status
is "running" when index.view.json uses the canonical dict-keyed format:
    {"entries": {"<id>": {"id": ..., "status": "running", ...}, ...}, "schema_version": 1}

Failure class: if `entries` is iterated as a dict (iterating over keys rather
than values), `e.get('status')` would raise AttributeError on a string key and
the guard would fall back to 0 — silently allowing implementation to proceed
while a consumer is still running.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path


# ── helper extracted from Phase 0 snippet ─────────────────────────────────────

def _count_running(view_dict: dict) -> int:
    """
    Mirror of the Phase 0 Python snippet in z-implement-next.md and
    z-implement-all.md.  Returns the number of entries whose status == 'running'.

    Raises nothing — matches the try/except guard in the bash snippet.
    """
    try:
        entries_obj = view_dict.get('entries', {})
        entries = list(entries_obj.values())
        running = [e for e in entries if e.get('status') == 'running']
        return len(running)
    except (json.JSONDecodeError, OSError, KeyError, AttributeError):
        return 0


# ── tests ──────────────────────────────────────────────────────────────────────

class TestCountRunning:

    def test_single_running_entry_dict_form(self):
        """
        Canonical case from the task acceptance criteria:
        one entry keyed by id with status='running' → RUNNING_COUNT == 1.
        """
        view = {
            "schema_version": 1,
            "entries": {
                "abc123": {"id": "abc123", "status": "running", "name": "do thing"}
            }
        }
        assert _count_running(view) == 1

    def test_zero_running_when_all_done(self):
        """No running entries → 0."""
        view = {
            "schema_version": 1,
            "entries": {
                "abc123": {"id": "abc123", "status": "done", "name": "do thing"},
                "def456": {"id": "def456", "status": "open", "name": "other"},
            }
        }
        assert _count_running(view) == 0

    def test_multiple_running_entries(self):
        """Two running entries → 2."""
        view = {
            "schema_version": 1,
            "entries": {
                "a": {"id": "a", "status": "running"},
                "b": {"id": "b", "status": "running"},
                "c": {"id": "c", "status": "done"},
            }
        }
        assert _count_running(view) == 2

    def test_empty_entries_dict(self):
        """Empty dict under 'entries' → 0."""
        view = {"schema_version": 1, "entries": {}}
        assert _count_running(view) == 0

    def test_missing_entries_key(self):
        """'entries' key absent → 0 (not an error)."""
        view = {"schema_version": 1}
        assert _count_running(view) == 0

    def test_dict_iteration_bug_would_fail(self):
        """
        Regression: the old buggy code did `entries = data.get('entries', [])`,
        which returns the dict itself when the key exists.  Iterating a dict
        yields keys (strings), and `"abc123".get('status')` raises AttributeError.
        The old except-Exception swallow would then return 0 incorrectly.

        This test proves that iterating over VALUES (not keys) gives the correct
        count, and that iterating over keys would give the wrong result.
        """
        view = {
            "schema_version": 1,
            "entries": {
                "abc123": {"id": "abc123", "status": "running", "name": "task"}
            }
        }
        entries_obj = view.get('entries', {})

        # Correct path: iterate values
        values = list(entries_obj.values())
        running_via_values = [e for e in values if e.get('status') == 'running']
        assert len(running_via_values) == 1, "values path must find 1 running entry"

        # Buggy path: iterate keys (strings) — should fail to find any
        keys = list(entries_obj.keys())
        running_via_keys = []
        for k in keys:
            try:
                if k.get('status') == 'running':  # type: ignore[attr-defined]
                    running_via_keys.append(k)
            except AttributeError:
                pass  # strings don't have .get(); old except-Exception swallowed this
        assert len(running_via_keys) == 0, (
            "key-iteration path silently returns 0 — proving the old bug was real"
        )

    def test_view_loaded_from_file(self, tmp_path: Path):
        """
        End-to-end: write a temp index.view.json, load it, count running.
        Mirrors the bash snippet's `json.load(open(sys.argv[1]))` path.
        """
        view_file = tmp_path / "index.view.json"
        view_data = {
            "schema_version": 1,
            "entries": {
                "entry-1": {"id": "entry-1", "status": "running", "name": "x"},
                "entry-2": {"id": "entry-2", "status": "done", "name": "y"},
            }
        }
        view_file.write_text(json.dumps(view_data))

        loaded = json.loads(view_file.read_text())
        count = _count_running(loaded)
        assert count == 1
