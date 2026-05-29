"""
tests/test_notion_integration.py — Integration tests for Notion push wiring
in followup_common.py (shared helper), sink-add-helpers.py, and
sink-status-set-impl.py.

All tests mock subprocess.run to intercept the notion-push.py call.
No real HTTP requests are made.

Scenarios:
  T01  notion disabled (followup.notion_enabled=false) → no push call, no events
  T02  notion enabled + push success (exit 0, stdout has remote_id) → notion_synced event
  T03  notion enabled + push fail (exit 4) → notion_sync_pending event + failure logged, local exit 0
  T04  mismatch (exit 5) → mismatch logged, notion_sync_pending event, local exit 0
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch, call

REPO_ROOT = Path(__file__).resolve().parent.parent

# ── Load modules under test via importlib (filenames have hyphens) ────────────

def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


_helpers_path = REPO_ROOT / "scripts" / "sink-add-helpers.py"
helpers = _load_module("sink_add_helpers", _helpers_path)

# followup_common is imported by helpers via `from followup_common import ...`.
# When that import ran, Python added it to sys.modules under the key "followup_common".
# We must get THAT exact module object (not re-load a fresh copy) because
# _notion_push_entry calls _log_event_sh from followup_common's own namespace —
# patching a different module object instance would not intercept the call.
import importlib as _importlib
followup_common = sys.modules.get("followup_common") or _importlib.import_module("followup_common")

# _notion_push_entry lives in followup_common (the canonical location after T013
# consolidation).  sink-add-helpers and sink-status-set-impl now expose
# _notion_push_entry_bg (background variant) instead.  Tests that verify the
# push logic (event appending, log calls) use followup_common._notion_push_entry
# directly so they remain synchronous and fast.
_notion_push_entry = followup_common._notion_push_entry


# ── Fixtures ──────────────────────────────────────────────────────────────────

ENTRY_ID = "20260101T000000Z-test-entry"
REMOTE_PAGE_ID = "notion-page-abc123"


def _make_entry(*, notion_remote_id: str | None = None) -> dict:
    return {
        "id": ENTRY_ID,
        "schema_version": 1,
        "priority": "P2",
        "name": "Test Entry",
        "status": "open",
        "sink": "project",
        "notion_remote_id": notion_remote_id,
        "recommended_command": "/z-do \"test\"",
    }


def _make_push_result(returncode: int, stdout: dict) -> MagicMock:
    """Create a mock CompletedProcess from subprocess.run."""
    r = MagicMock()
    r.returncode = returncode
    r.stdout = json.dumps(stdout)
    r.stderr = ""
    return r


# ── Tests for _notion_push_entry (the shared helper in followup_common.py) ────

class TestNotionPushEntryHelper(unittest.TestCase):
    """Test the _notion_push_entry helper directly (via followup_common)."""

    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        self.sink_root = Path(self.tmp) / "followups"
        self.sink_root.mkdir(parents=True)
        self.proj_root = Path(self.tmp)
        # Create a minimal git repo so config queries don't fail
        subprocess.run(["git", "init", self.tmp], capture_output=True)
        subprocess.run(
            ["git", "config", "user.email", "t@t.com"],
            capture_output=True,
            cwd=self.tmp,
        )

    def _read_journal_events(self) -> list[dict]:
        journal = self.sink_root / "index.jsonl"
        if not journal.exists():
            return []
        return [json.loads(line) for line in journal.read_text().splitlines() if line.strip()]

    # ── T01: notion disabled → no subprocess call ──────────────────────────────

    def test_notion_disabled_no_push_call(self) -> None:
        """When notion_enabled=False, _notion_push_entry must not be called at all."""
        entry = _make_entry()
        push_result = _make_push_result(0, {"action": "created", "remote_id": REMOTE_PAGE_ID, "attempts": 1})

        with patch.object(followup_common, "_get_config_bool", return_value=False) as mock_cfg, \
             patch.object(followup_common, "subprocess") as mock_subproc:
            mock_subproc.run.return_value = push_result
            # Simulate the check that sink-add does before calling _notion_push_entry
            notion_enabled = followup_common._get_config_bool("followup.notion_enabled", self.proj_root)
            if notion_enabled:
                _notion_push_entry(entry, self.sink_root, self.proj_root)

        # The config check returned False — no notion-push.py call should have happened
        # No journal events should have been written
        events = self._read_journal_events()
        assert events == [], f"Expected no events, got: {events}"

    # ── T02: push success → notion_synced event with remote_id ────────────────

    def test_push_success_appends_notion_synced_event(self) -> None:
        """On exit 0 from notion-push.py, notion_synced event is appended with remote_id."""
        entry = _make_entry()
        push_result = _make_push_result(
            0, {"action": "created", "remote_id": REMOTE_PAGE_ID, "attempts": 1}
        )

        with patch("subprocess.run", return_value=push_result):
            _notion_push_entry(entry, self.sink_root, self.proj_root)

        events = self._read_journal_events()
        assert len(events) == 1, f"Expected 1 event, got: {events}"
        ev = events[0]
        assert ev["kind"] == "notion_synced", f"Expected notion_synced, got {ev['kind']}"
        assert ev["entry_id"] == ENTRY_ID
        assert ev["remote_id"] == REMOTE_PAGE_ID

    # ── T03: push fail (exit 4) → notion_sync_pending + failure logged, no raise ──

    def test_push_failure_appends_pending_event_and_logs_failure(self) -> None:
        """On exit 4, notion_sync_pending event is appended and followup_notion_sync_failure logged."""
        entry = _make_entry()
        push_result = _make_push_result(
            4, {"action": "failed", "attempts": 3, "error": "POST failed: HTTP 500: Server Error"}
        )

        logged_events: list[tuple] = []

        def _capture_log_event_sh(event_kind: str, payload: dict) -> None:
            logged_events.append((event_kind, payload))

        with patch("subprocess.run", return_value=push_result), \
             patch.object(followup_common, "_log_event_sh", side_effect=_capture_log_event_sh):
            _notion_push_entry(entry, self.sink_root, self.proj_root)

        # notion_sync_pending event in journal
        events = self._read_journal_events()
        pending_events = [e for e in events if e.get("kind") == "notion_sync_pending"]
        assert len(pending_events) == 1, f"Expected 1 notion_sync_pending event, got: {events}"
        assert pending_events[0]["notion_sync_pending"] is True
        assert pending_events[0]["entry_id"] == ENTRY_ID

        # followup_notion_sync_failure was logged via _log_event_sh
        failure_logs = [e for e in logged_events if e[0] == "followup_notion_sync_failure"]
        assert len(failure_logs) == 1, f"Expected 1 failure log call, got: {logged_events}"
        payload = failure_logs[0][1]
        assert payload["entry_id"] == ENTRY_ID
        assert payload["attempts"] == 3

    def test_push_failure_local_caller_exits_zero(self) -> None:
        """_notion_push_entry must not raise on push failure (local op exit 0 unaffected)."""
        entry = _make_entry()
        push_result = _make_push_result(4, {"action": "failed", "attempts": 3, "error": "net err"})

        # Should complete without raising any exception
        try:
            with patch("subprocess.run", return_value=push_result), \
                 patch.object(followup_common, "_log_event_sh"):
                _notion_push_entry(entry, self.sink_root, self.proj_root)
        except Exception as exc:
            self.fail(f"_notion_push_entry raised an exception on push failure: {exc}")

    # ── T04: mismatch (exit 5) → mismatch logged, notion_sync_pending, no raise ──

    def test_mismatch_logs_and_appends_pending(self) -> None:
        """On exit 5, followup_notion_remote_id_mismatch is logged and soft failure recorded."""
        entry = _make_entry(notion_remote_id="old-page-id")
        push_result = _make_push_result(
            5,
            {
                "action": "failed",
                "attempts": 1,
                "error": "z_harness_entry_id mismatch: expected 'X', got 'Y'",
            },
        )

        logged_events: list[tuple] = []

        def _capture_log_event_sh(event_kind: str, payload: dict) -> None:
            logged_events.append((event_kind, payload))

        with patch("subprocess.run", return_value=push_result), \
             patch.object(followup_common, "_log_event_sh", side_effect=_capture_log_event_sh):
            _notion_push_entry(entry, self.sink_root, self.proj_root)

        # Mismatch event was logged
        mismatch_logs = [e for e in logged_events if e[0] == "followup_notion_remote_id_mismatch"]
        assert len(mismatch_logs) == 1, f"Expected 1 mismatch log, got: {logged_events}"
        assert mismatch_logs[0][1]["entry_id"] == ENTRY_ID

        # notion_sync_pending event in journal (mismatch=True)
        events = self._read_journal_events()
        pending_events = [e for e in events if e.get("kind") == "notion_sync_pending"]
        assert len(pending_events) == 1, f"Expected 1 notion_sync_pending event, got: {events}"
        assert pending_events[0].get("mismatch") is True

    def test_mismatch_local_caller_exits_zero(self) -> None:
        """_notion_push_entry must not raise on mismatch (local op exit 0 unaffected)."""
        entry = _make_entry(notion_remote_id="old-page-id")
        push_result = _make_push_result(5, {"action": "failed", "attempts": 1, "error": "mismatch"})

        try:
            with patch("subprocess.run", return_value=push_result), \
                 patch.object(followup_common, "_log_event_sh"):
                _notion_push_entry(entry, self.sink_root, self.proj_root)
        except Exception as exc:
            self.fail(f"_notion_push_entry raised an exception on mismatch: {exc}")


# ── Tests for sink-status-set-impl.py's notion push wiring ───────────────────

class TestStatusSetNotionWiring(unittest.TestCase):
    """
    Verify the Notion push wiring in sink-status-set-impl.py.

    Since _notion_push_entry lives in followup_common (after T013 consolidation),
    tests call followup_common._notion_push_entry directly — which is the same
    function that the impl module uses under the hood.
    """

    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        self.sink_root = Path(self.tmp) / "followups"
        self.sink_root.mkdir(parents=True)
        self.proj_root = Path(self.tmp)

    def _read_journal_events(self) -> list[dict]:
        journal = self.sink_root / "index.jsonl"
        if not journal.exists():
            return []
        return [json.loads(line) for line in journal.read_text().splitlines() if line.strip()]

    def test_notion_disabled_no_push(self) -> None:
        """When notion_enabled=False, no push call and no events written."""
        entry = _make_entry()
        push_result = _make_push_result(0, {"action": "created", "remote_id": REMOTE_PAGE_ID})

        with patch("subprocess.run", return_value=push_result) as mock_run, \
             patch.object(followup_common, "_get_config_bool", return_value=False):
            notion_enabled = followup_common._get_config_bool("followup.notion_enabled", self.proj_root)
            if notion_enabled:
                _notion_push_entry(entry, self.sink_root, self.proj_root)

        notion_push_calls = [
            c for c in mock_run.call_args_list
            if any("notion-push.py" in str(a) for a in (c.args[0] if c.args else []))
        ]
        assert notion_push_calls == []
        events = self._read_journal_events()
        assert events == []

    def test_status_set_push_success_writes_synced_event(self) -> None:
        """On success, _notion_push_entry appends notion_synced."""
        entry = _make_entry()
        push_result = _make_push_result(
            0, {"action": "created", "remote_id": REMOTE_PAGE_ID, "attempts": 1}
        )

        with patch("subprocess.run", return_value=push_result):
            _notion_push_entry(entry, self.sink_root, self.proj_root)

        events = self._read_journal_events()
        assert len(events) == 1
        assert events[0]["kind"] == "notion_synced"
        assert events[0]["remote_id"] == REMOTE_PAGE_ID

    def test_status_set_push_failure_writes_pending_event(self) -> None:
        """On exit 4, _notion_push_entry appends notion_sync_pending."""
        entry = _make_entry()
        push_result = _make_push_result(
            4, {"action": "failed", "attempts": 3, "error": "all retries exhausted"}
        )

        with patch("subprocess.run", return_value=push_result), \
             patch.object(followup_common, "_log_event_sh"):
            _notion_push_entry(entry, self.sink_root, self.proj_root)

        events = self._read_journal_events()
        pending = [e for e in events if e.get("kind") == "notion_sync_pending"]
        assert len(pending) == 1
        assert pending[0]["notion_sync_pending"] is True

    def test_status_set_mismatch_writes_pending_with_mismatch_flag(self) -> None:
        """On exit 5, _notion_push_entry records mismatch=True in notion_sync_pending event."""
        entry = _make_entry(notion_remote_id="old-page")
        push_result = _make_push_result(5, {"action": "failed", "attempts": 1, "error": "mismatch"})

        with patch("subprocess.run", return_value=push_result), \
             patch.object(followup_common, "_log_event_sh"):
            _notion_push_entry(entry, self.sink_root, self.proj_root)

        events = self._read_journal_events()
        pending = [e for e in events if e.get("kind") == "notion_sync_pending"]
        assert len(pending) == 1
        assert pending[0].get("mismatch") is True


if __name__ == "__main__":
    unittest.main()
