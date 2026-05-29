"""
tests/test_followup_reconcile.py — pytest tests for scripts/followup-reconcile-notion-impl.py

All subprocess calls to notion-push.py are mocked via unittest.mock.patch on
subprocess.run. No real HTTP requests are made.

Scenarios:
  T01  no pending entries → swept_count=0
  T02  one pending entry, push succeeds → notion_synced + notion_sync_cleared events; succeeded=1
  T03  one pending entry, push fails → still pending (no cleared event), failed=1
  T04  one pending entry with null notion_remote_id → --check-existing flag passed
  T05  one pending entry, push returns conflict (exit 5) → conflicts=1
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch, call

REPO_ROOT = Path(__file__).resolve().parent.parent


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


_impl_path = REPO_ROOT / "scripts" / "followup-reconcile-notion-impl.py"
impl = _load_module("followup_reconcile_notion_impl", _impl_path)


# ── Helpers ────────────────────────────────────────────────────────────────────

ENTRY_ID = "20260101T000000Z-test-entry"
REMOTE_PAGE_ID = "notion-page-xyz"


def _make_entry(
    *,
    entry_id: str = ENTRY_ID,
    notion_remote_id: str | None = None,
    status: str = "open",
) -> dict:
    return {
        "id": entry_id,
        "schema_version": 1,
        "priority": "P2",
        "name": "Test Entry",
        "status": status,
        "sink": "project",
        "notion_remote_id": notion_remote_id,
        "recommended_command": '/z-do "test"',
    }


def _write_view(sink_root: Path, entries: dict) -> None:
    """Write a minimal index.view.json."""
    view_path = sink_root / "index.view.json"
    view_path.write_text(json.dumps({"entries": entries}))


def _write_journal(sink_root: Path, events: list[dict]) -> None:
    """Write events to index.jsonl."""
    journal_path = sink_root / "index.jsonl"
    with journal_path.open("a") as fh:
        for ev in events:
            fh.write(json.dumps(ev) + "\n")


def _read_journal_events(sink_root: Path) -> list[dict]:
    journal_path = sink_root / "index.jsonl"
    if not journal_path.exists():
        return []
    return [json.loads(line) for line in journal_path.read_text().splitlines() if line.strip()]


def _make_push_result(returncode: int, stdout: dict) -> MagicMock:
    r = MagicMock()
    r.returncode = returncode
    r.stdout = json.dumps(stdout)
    r.stderr = ""
    return r


# ── Tests ──────────────────────────────────────────────────────────────────────

def _make_sweep_kwargs() -> dict:
    """Return default config kwargs for _sweep_sink (empty strings = no Notion config)."""
    return {"config_database_id": "", "config_token_path": ""}


class TestNoPendingEntries(unittest.TestCase):
    """T01: no pending entries → swept_count=0."""

    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        self.sink_root = Path(self.tmp)
        self.sink_root.mkdir(exist_ok=True)

    def test_no_journal_returns_zero_swept(self) -> None:
        """
        Invariant: when no index.jsonl exists, swept_count must be 0.

        Failure class: reconciler runs spuriously when there is nothing pending.
        """
        counters = impl._sweep_sink(self.sink_root, Path(self.tmp), **_make_sweep_kwargs())
        self.assertEqual(counters["swept_count"], 0)
        self.assertEqual(counters["succeeded"], 0)
        self.assertEqual(counters["failed"], 0)
        self.assertEqual(counters["conflicts"], 0)

    def test_no_pending_events_returns_zero_swept(self) -> None:
        """
        Invariant: when all notion events are notion_synced (not pending),
        swept_count must be 0.

        Failure class: reconciler re-sweeps already-synced entries.
        """
        entry = _make_entry()
        _write_view(self.sink_root, {ENTRY_ID: entry})
        _write_journal(self.sink_root, [
            {"kind": "entry_created", "entry_id": ENTRY_ID, "ts": "2026-01-01T00:00:00Z"},
            {"kind": "notion_sync_pending", "entry_id": ENTRY_ID, "notion_sync_pending": True, "ts": "2026-01-01T00:00:01Z"},
            {"kind": "notion_synced", "entry_id": ENTRY_ID, "remote_id": REMOTE_PAGE_ID, "ts": "2026-01-01T00:00:02Z"},
        ])

        counters = impl._sweep_sink(self.sink_root, Path(self.tmp), **_make_sweep_kwargs())
        self.assertEqual(counters["swept_count"], 0)

    def test_notion_sync_cleared_also_clears_pending(self) -> None:
        """
        notion_sync_cleared event must also mark an entry as no longer pending.
        """
        entry = _make_entry()
        _write_view(self.sink_root, {ENTRY_ID: entry})
        _write_journal(self.sink_root, [
            {"kind": "notion_sync_pending", "entry_id": ENTRY_ID, "notion_sync_pending": True, "ts": "t1"},
            {"kind": "notion_sync_cleared", "entry_id": ENTRY_ID, "ts": "t2"},
        ])

        counters = impl._sweep_sink(self.sink_root, Path(self.tmp), **_make_sweep_kwargs())
        self.assertEqual(counters["swept_count"], 0)


class TestPendingPushSucceeds(unittest.TestCase):
    """T02: one pending entry, push succeeds → notion_synced + notion_sync_cleared; succeeded=1."""

    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        self.sink_root = Path(self.tmp)
        self.proj_root = Path(self.tmp)

    def test_push_success_writes_synced_and_cleared_events(self) -> None:
        """
        Invariant: on push success, both notion_synced and notion_sync_cleared events
        must be appended to index.jsonl, and the counters show succeeded=1.

        Failure class: reconciler marks entry succeeded in memory but forgets to write
        the cleared event, leaving the entry pending on next run.
        """
        entry = _make_entry(notion_remote_id=REMOTE_PAGE_ID)
        _write_view(self.sink_root, {ENTRY_ID: entry})
        _write_journal(self.sink_root, [
            {"kind": "notion_sync_pending", "entry_id": ENTRY_ID, "notion_sync_pending": True, "ts": "t1"},
        ])

        push_result = _make_push_result(0, {"action": "updated", "remote_id": REMOTE_PAGE_ID, "attempts": 1})

        with patch("subprocess.run", return_value=push_result) as mock_run:
            counters = impl._sweep_sink(self.sink_root, self.proj_root, **_make_sweep_kwargs())

        self.assertEqual(counters["swept_count"], 1)
        self.assertEqual(counters["succeeded"], 1)
        self.assertEqual(counters["failed"], 0)
        self.assertEqual(counters["conflicts"], 0)

        events = _read_journal_events(self.sink_root)
        # Keep only new events (after the pending event we wrote above)
        new_events = [e for e in events if e.get("kind") in ("notion_synced", "notion_sync_cleared")]
        kinds = [e["kind"] for e in new_events]
        self.assertIn("notion_synced", kinds, "notion_synced event must be appended on success")
        self.assertIn("notion_sync_cleared", kinds, "notion_sync_cleared event must be appended on success")

        synced_ev = next(e for e in new_events if e["kind"] == "notion_synced")
        self.assertEqual(synced_ev["entry_id"], ENTRY_ID)
        self.assertEqual(synced_ev["remote_id"], REMOTE_PAGE_ID)

    def test_push_success_subsequent_sweep_finds_zero_pending(self) -> None:
        """
        After a successful reconcile sweep, a subsequent sweep must find 0 pending entries
        (the cleared event must make _find_pending_entry_ids return empty set).
        """
        entry = _make_entry(notion_remote_id=REMOTE_PAGE_ID)
        _write_view(self.sink_root, {ENTRY_ID: entry})
        _write_journal(self.sink_root, [
            {"kind": "notion_sync_pending", "entry_id": ENTRY_ID, "notion_sync_pending": True, "ts": "t1"},
        ])

        push_result = _make_push_result(0, {"action": "updated", "remote_id": REMOTE_PAGE_ID, "attempts": 1})

        with patch("subprocess.run", return_value=push_result):
            impl._sweep_sink(self.sink_root, self.proj_root, **_make_sweep_kwargs())

        # Second sweep — no more mocking needed; the journal now has cleared event
        # Re-read pending IDs directly from journal
        pending = impl._find_pending_entry_ids(self.sink_root)
        self.assertEqual(pending, set(), "After successful sweep, no entries should be pending")


class TestPendingPushFails(unittest.TestCase):
    """T03: one pending entry, push fails → still pending (no cleared event), failed=1."""

    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        self.sink_root = Path(self.tmp)
        self.proj_root = Path(self.tmp)

    def test_push_failure_leaves_entry_pending(self) -> None:
        """
        Invariant: on push failure (exit 4), the entry must remain pending (no
        notion_sync_cleared event written), and failed counter must be 1.

        Failure class: reconciler incorrectly clears a pending entry on push failure,
        causing the entry to be silently dropped from future reconcile attempts.
        """
        entry = _make_entry(notion_remote_id=REMOTE_PAGE_ID)
        _write_view(self.sink_root, {ENTRY_ID: entry})
        _write_journal(self.sink_root, [
            {"kind": "notion_sync_pending", "entry_id": ENTRY_ID, "notion_sync_pending": True, "ts": "t1"},
        ])

        push_result = _make_push_result(4, {"action": "failed", "attempts": 3, "error": "HTTP 500"})

        with patch("subprocess.run", return_value=push_result):
            counters = impl._sweep_sink(self.sink_root, self.proj_root, **_make_sweep_kwargs())

        self.assertEqual(counters["swept_count"], 1)
        self.assertEqual(counters["succeeded"], 0)
        self.assertEqual(counters["failed"], 1, "failed counter must be 1 on push failure")
        self.assertEqual(counters["conflicts"], 0)

        # No notion_sync_cleared event must have been written
        events = _read_journal_events(self.sink_root)
        cleared = [e for e in events if e.get("kind") == "notion_sync_cleared"]
        self.assertEqual(cleared, [], "notion_sync_cleared must NOT be written on push failure")

        # Entry must still be in pending state
        pending = impl._find_pending_entry_ids(self.sink_root)
        self.assertIn(ENTRY_ID, pending, "Entry must remain pending after push failure")

    def test_failed_does_not_prevent_exit_0(self) -> None:
        """
        Reconcile sweep must return exit 0 even when push fails (best-effort).
        """
        entry = _make_entry(notion_remote_id=REMOTE_PAGE_ID)
        _write_view(self.sink_root, {ENTRY_ID: entry})
        _write_journal(self.sink_root, [
            {"kind": "notion_sync_pending", "entry_id": ENTRY_ID, "notion_sync_pending": True, "ts": "t1"},
        ])

        push_result = _make_push_result(4, {"action": "failed", "attempts": 3, "error": "timeout"})

        with patch("subprocess.run", return_value=push_result):
            # _sweep_sink must not raise
            try:
                impl._sweep_sink(self.sink_root, self.proj_root, **_make_sweep_kwargs())
            except Exception as exc:
                self.fail(f"_sweep_sink raised on push failure: {exc}")


class TestNullRemoteIdUsesCheckExisting(unittest.TestCase):
    """T04: pending entry with null notion_remote_id → --check-existing flag passed to notion-push.py."""

    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        self.sink_root = Path(self.tmp)
        self.proj_root = Path(self.tmp)

    def test_null_remote_id_passes_check_existing_flag(self) -> None:
        """
        Invariant: when notion_remote_id is null, notion-push.py must be invoked with
        the --check-existing flag to avoid creating duplicate Notion pages.

        Failure class: reconciler calls notion-push.py without --check-existing for
        entries whose remote_id is null, causing duplicate page creation in Notion.
        """
        # Entry with null notion_remote_id (never successfully synced)
        entry = _make_entry(notion_remote_id=None)
        _write_view(self.sink_root, {ENTRY_ID: entry})
        _write_journal(self.sink_root, [
            {"kind": "notion_sync_pending", "entry_id": ENTRY_ID, "notion_sync_pending": True, "ts": "t1"},
        ])

        push_result = _make_push_result(0, {"action": "created", "remote_id": REMOTE_PAGE_ID, "attempts": 1})
        captured_cmds: list[list[str]] = []

        def _capturing_run(cmd, *args, **kwargs):
            if isinstance(cmd, list):
                captured_cmds.append(cmd)
            return push_result

        with patch("subprocess.run", side_effect=_capturing_run):
            impl._sweep_sink(self.sink_root, self.proj_root, **_make_sweep_kwargs())

        # Find the notion-push.py invocation
        notion_push_calls = [
            cmd for cmd in captured_cmds
            if any("notion-push.py" in str(a) for a in cmd)
        ]
        self.assertEqual(len(notion_push_calls), 1, "Exactly one notion-push.py call expected")
        call_args = notion_push_calls[0]
        self.assertIn("--check-existing", call_args, (
            "--check-existing must be passed when notion_remote_id is null to avoid "
            "duplicate Notion page creation"
        ))

    def test_check_existing_also_passed_for_non_null_remote_id(self) -> None:
        """
        --check-existing should also be passed even when notion_remote_id is set
        (reconciler always uses it for safety).
        """
        entry = _make_entry(notion_remote_id=REMOTE_PAGE_ID)
        _write_view(self.sink_root, {ENTRY_ID: entry})
        _write_journal(self.sink_root, [
            {"kind": "notion_sync_pending", "entry_id": ENTRY_ID, "notion_sync_pending": True, "ts": "t1"},
        ])

        push_result = _make_push_result(0, {"action": "updated", "remote_id": REMOTE_PAGE_ID, "attempts": 1})
        captured_cmds: list[list[str]] = []

        def _capturing_run(cmd, *args, **kwargs):
            if isinstance(cmd, list):
                captured_cmds.append(cmd)
            return push_result

        with patch("subprocess.run", side_effect=_capturing_run):
            impl._sweep_sink(self.sink_root, self.proj_root, **_make_sweep_kwargs())

        notion_push_calls = [
            cmd for cmd in captured_cmds
            if any("notion-push.py" in str(a) for a in cmd)
        ]
        self.assertEqual(len(notion_push_calls), 1)
        self.assertIn("--check-existing", notion_push_calls[0])


class TestConflict(unittest.TestCase):
    """T05: push returns exit 5 (idempotency conflict) → conflicts=1."""

    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        self.sink_root = Path(self.tmp)
        self.proj_root = Path(self.tmp)

    def test_conflict_increments_conflicts_counter(self) -> None:
        """
        Invariant: when notion-push.py exits 5 (z_harness_entry_id mismatch),
        the conflict counter must be incremented, and no cleared event written.

        Failure class: reconciler treats a conflict as a success, clearing a pending
        entry that has a data integrity issue requiring human review.
        """
        entry = _make_entry(notion_remote_id=REMOTE_PAGE_ID)
        _write_view(self.sink_root, {ENTRY_ID: entry})
        _write_journal(self.sink_root, [
            {"kind": "notion_sync_pending", "entry_id": ENTRY_ID, "notion_sync_pending": True, "ts": "t1"},
        ])

        push_result = _make_push_result(5, {"action": "failed", "attempts": 1, "error": "mismatch"})

        with patch("subprocess.run", return_value=push_result):
            counters = impl._sweep_sink(self.sink_root, self.proj_root, **_make_sweep_kwargs())

        self.assertEqual(counters["swept_count"], 1)
        self.assertEqual(counters["succeeded"], 0)
        self.assertEqual(counters["failed"], 0)
        self.assertEqual(counters["conflicts"], 1, "Exit 5 must increment conflicts, not failed")

        events = _read_journal_events(self.sink_root)
        cleared = [e for e in events if e.get("kind") == "notion_sync_cleared"]
        self.assertEqual(cleared, [], "No cleared event on conflict")


class TestMainOutputJson(unittest.TestCase):
    """main() must always print valid JSON with swept_count, succeeded, failed, conflicts."""

    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()

    def test_main_returns_json_summary(self) -> None:
        """
        Invariant: main() stdout must be valid JSON with all four summary keys.
        """
        import io
        import contextlib

        project_sink = Path(self.tmp) / "project"
        global_sink = Path(self.tmp) / "global"
        project_sink.mkdir()
        global_sink.mkdir()

        out_capture = io.StringIO()
        with patch.object(impl, "_find_project_root", return_value=Path(self.tmp)):
            with contextlib.redirect_stdout(out_capture):
                exit_code = impl.main([
                    f"--project-sink-root={project_sink}",
                    f"--global-sink-root={global_sink}",
                ])

        self.assertEqual(exit_code, 0, "main() must exit 0 even with no pending entries")
        output = json.loads(out_capture.getvalue())
        for key in ("swept_count", "succeeded", "failed", "conflicts"):
            self.assertIn(key, output, f"Summary JSON must contain '{key}' key")
        self.assertEqual(output["swept_count"], 0)

    def test_main_exit_0_on_partial_failure(self) -> None:
        """
        main() must exit 0 even when some pushes fail (best-effort sweep).
        """
        import io
        import contextlib

        project_sink = Path(self.tmp) / "project2"
        global_sink = Path(self.tmp) / "global2"
        project_sink.mkdir()
        global_sink.mkdir()

        # Write a pending entry
        entry = _make_entry()
        _write_view(project_sink, {ENTRY_ID: entry})
        _write_journal(project_sink, [
            {"kind": "notion_sync_pending", "entry_id": ENTRY_ID, "notion_sync_pending": True, "ts": "t1"},
        ])

        push_result = _make_push_result(4, {"action": "failed", "attempts": 3, "error": "net"})
        out_capture = io.StringIO()

        # Patch get_config_batch (imported into impl from followup_common) so that
        # main() does not fork config.py when there is no real project config.
        import sys as _sys
        followup_common_mod = _sys.modules.get("followup_common")
        with patch("subprocess.run", return_value=push_result), \
             patch.object(followup_common_mod, "get_config_batch", return_value={
                 "followup.notion_database_id": "",
                 "followup.notion_token_path": "",
             }), \
             patch.object(impl, "_find_project_root", return_value=Path(self.tmp)):
            with contextlib.redirect_stdout(out_capture):
                exit_code = impl.main([
                    f"--project-sink-root={project_sink}",
                    f"--global-sink-root={global_sink}",
                ])

        self.assertEqual(exit_code, 0, "main() must exit 0 even when pushes fail")
        output = json.loads(out_capture.getvalue())
        self.assertEqual(output["failed"], 1)


if __name__ == "__main__":
    unittest.main()
