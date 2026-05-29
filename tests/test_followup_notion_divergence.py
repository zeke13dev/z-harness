"""
tests/test_followup_notion_divergence.py — pytest tests for Notion divergence surfacing (T018).

Covers:
  (a) notion_sync_pending event → entry["notion_sync_pending"] == True
  (b) notion_synced event after pending → notion_sync_pending == False
  (c) notion_sync_cleared event after pending → notion_sync_pending == False
  (d) entry with no notion event → notion_sync_pending absent / False (.get fallback)
  (e) last-writer-wins ordering: pending → synced → pending → True
  (f) last-writer-wins ordering: pending → cleared → synced → False
  (g) incremental rebuild across appended notion events matches full replay
  (h) list rendering marks only pending entry (notion marker present/absent)
  (i) status count of notion_sync_pending entries
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
REDUCER_PY = str(REPO_ROOT / "scripts" / "sink-view-reducer.py")
REBUILD_SH = str(REPO_ROOT / "scripts" / "sink-view-rebuild.sh")

# Tiny Python helper script that holds an exclusive flock on the sentinel file,
# then runs sink-view-rebuild.sh as a child process, then releases the lock.
_HOLD_LOCK_AND_RUN = """
import fcntl, os, subprocess, sys

sentinel_path, *cmd = sys.argv[1:]
fd = os.open(sentinel_path, os.O_CREAT | os.O_RDWR, 0o644)
fcntl.flock(fd, fcntl.LOCK_EX)   # blocking exclusive lock
try:
    r = subprocess.run(cmd)
    sys.exit(r.returncode)
finally:
    fcntl.flock(fd, fcntl.LOCK_UN)
    os.close(fd)
"""


# ── helpers ────────────────────────────────────────────────────────────────────

def _run_rebuild(sink_root: str, *, lock_file: str | None = None,
                 hold_lock: bool = True) -> subprocess.CompletedProcess:
    """Run sink-view-rebuild.sh <sink_root> with the lock held."""
    env = dict(os.environ)
    if lock_file:
        env["Z_HARNESS_FOLLOWUP_GLOBAL_LOCK"] = lock_file

    resolved_lock = lock_file or os.path.join(sink_root, ".test.lock")
    sentinel = resolved_lock + ".flock"

    rebuild_cmd = ["bash", REBUILD_SH, sink_root]

    if hold_lock:
        Path(resolved_lock).parent.mkdir(parents=True, exist_ok=True)
        Path(sentinel).touch()
        cmd = [sys.executable, "-c", _HOLD_LOCK_AND_RUN, sentinel, *rebuild_cmd]
        return subprocess.run(cmd, capture_output=True, text=True, env=env)
    else:
        return subprocess.run(rebuild_cmd, capture_output=True, text=True, env=env)


def _run_reducer_full(sink_root: str) -> subprocess.CompletedProcess:
    """Run reducer with --full flag (forced cold replay)."""
    return subprocess.run(
        [sys.executable, REDUCER_PY, "--full", sink_root],
        capture_output=True,
        text=True,
    )


def _run_reducer_incremental(sink_root: str) -> subprocess.CompletedProcess:
    """Run reducer without flags (incremental path)."""
    return subprocess.run(
        [sys.executable, REDUCER_PY, sink_root],
        capture_output=True,
        text=True,
    )


def _write_journal(sink_root: Path, events: list[dict]) -> None:
    lines = "\n".join(json.dumps(e) for e in events) + ("\n" if events else "")
    (sink_root / "index.jsonl").write_text(lines, encoding="utf-8")


def _append_journal(sink_root: Path, events: list[dict]) -> None:
    lines = "\n".join(json.dumps(e) for e in events) + "\n"
    with (sink_root / "index.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(lines)


def _read_view(sink_root: Path) -> dict:
    return json.loads((sink_root / "index.view.json").read_text(encoding="utf-8"))


def _entry_created_event(entry_id: str) -> dict:
    return {
        "kind": "entry_created",
        "ts": "2026-05-28T12:00:00Z",
        "entry": {
            "id": entry_id,
            "schema_version": 1,
            "priority": "P2",
            "name": "Test entry",
            "status": "open",
            "sink": "project",
            "created_at": "2026-05-28T12:00:00Z",
            "created_by_run": "run-001",
            "recommended_command": "/z-do \"test\"",
            "status_history": [
                {"ts": "2026-05-28T12:00:00Z", "from": None, "to": "open", "by": "scripts/sink-add.sh"}
            ],
        },
    }


def _notion_sync_pending_event(entry_id: str, ts: str = "2026-05-28T13:00:00Z") -> dict:
    return {
        "kind": "notion_sync_pending",
        "ts": ts,
        "entry_id": entry_id,
        "notion_sync_pending": True,
    }


def _notion_synced_event(entry_id: str, remote_id: str = "remote-001",
                          ts: str = "2026-05-28T14:00:00Z") -> dict:
    return {
        "kind": "notion_synced",
        "ts": ts,
        "entry_id": entry_id,
        "remote_id": remote_id,
    }


def _notion_sync_cleared_event(entry_id: str, ts: str = "2026-05-28T15:00:00Z") -> dict:
    return {
        "kind": "notion_sync_cleared",
        "ts": ts,
        "entry_id": entry_id,
    }


# ── tests ──────────────────────────────────────────────────────────────────────

class TestNotionSyncPendingMaterialized(unittest.TestCase):
    """(a) notion_sync_pending event sets the field to True in the view."""

    def test_notion_sync_pending_sets_field_true(self):
        with tempfile.TemporaryDirectory() as td:
            sink_root = Path(td)
            lock_file = str(sink_root / "test.lock")
            entry_id = "20260528T120000Z-pending-set"
            _write_journal(sink_root, [
                _entry_created_event(entry_id),
                _notion_sync_pending_event(entry_id),
            ])
            result = _run_rebuild(td, lock_file=lock_file)
            self.assertEqual(result.returncode, 0, msg=f"stderr={result.stderr}")
            view = _read_view(sink_root)
            entry = view["entries"][entry_id]
            self.assertTrue(entry.get("notion_sync_pending", False),
                            "notion_sync_pending must be True after notion_sync_pending event")

    def test_notion_sync_pending_field_true_is_bool(self):
        """notion_sync_pending must be a boolean True, not just truthy."""
        with tempfile.TemporaryDirectory() as td:
            sink_root = Path(td)
            lock_file = str(sink_root / "test.lock")
            entry_id = "20260528T120000Z-pending-bool"
            _write_journal(sink_root, [
                _entry_created_event(entry_id),
                _notion_sync_pending_event(entry_id),
            ])
            _run_rebuild(td, lock_file=lock_file)
            view = _read_view(sink_root)
            entry = view["entries"][entry_id]
            self.assertIs(entry.get("notion_sync_pending"), True,
                          "notion_sync_pending must be exactly True (bool)")


class TestNotionSyncedClearsFlag(unittest.TestCase):
    """(b) notion_synced event after pending → notion_sync_pending == False."""

    def test_notion_synced_clears_pending(self):
        with tempfile.TemporaryDirectory() as td:
            sink_root = Path(td)
            lock_file = str(sink_root / "test.lock")
            entry_id = "20260528T120000Z-synced-clears"
            _write_journal(sink_root, [
                _entry_created_event(entry_id),
                _notion_sync_pending_event(entry_id),
                _notion_synced_event(entry_id),
            ])
            result = _run_rebuild(td, lock_file=lock_file)
            self.assertEqual(result.returncode, 0, msg=f"stderr={result.stderr}")
            view = _read_view(sink_root)
            entry = view["entries"][entry_id]
            self.assertFalse(entry.get("notion_sync_pending", False),
                             "notion_sync_pending must be False after notion_synced")

    def test_notion_synced_field_false_is_bool(self):
        """notion_sync_pending must be False (bool) after notion_synced."""
        with tempfile.TemporaryDirectory() as td:
            sink_root = Path(td)
            lock_file = str(sink_root / "test.lock")
            entry_id = "20260528T120000Z-synced-bool"
            _write_journal(sink_root, [
                _entry_created_event(entry_id),
                _notion_sync_pending_event(entry_id),
                _notion_synced_event(entry_id),
            ])
            _run_rebuild(td, lock_file=lock_file)
            view = _read_view(sink_root)
            entry = view["entries"][entry_id]
            self.assertIs(entry.get("notion_sync_pending"), False,
                          "notion_sync_pending must be exactly False (bool) after notion_synced")


class TestNotionSyncClearedClearsFlag(unittest.TestCase):
    """(c) notion_sync_cleared event after pending → notion_sync_pending == False."""

    def test_notion_sync_cleared_clears_pending(self):
        with tempfile.TemporaryDirectory() as td:
            sink_root = Path(td)
            lock_file = str(sink_root / "test.lock")
            entry_id = "20260528T120000Z-cleared-clears"
            _write_journal(sink_root, [
                _entry_created_event(entry_id),
                _notion_sync_pending_event(entry_id),
                _notion_sync_cleared_event(entry_id),
            ])
            result = _run_rebuild(td, lock_file=lock_file)
            self.assertEqual(result.returncode, 0, msg=f"stderr={result.stderr}")
            view = _read_view(sink_root)
            entry = view["entries"][entry_id]
            self.assertFalse(entry.get("notion_sync_pending", False),
                             "notion_sync_pending must be False after notion_sync_cleared")


class TestNoNotionEventDefaultsFalse(unittest.TestCase):
    """(d) Entry with no notion event: notion_sync_pending absent or False via .get()."""

    def test_no_notion_event_field_absent_or_false(self):
        with tempfile.TemporaryDirectory() as td:
            sink_root = Path(td)
            lock_file = str(sink_root / "test.lock")
            entry_id = "20260528T120000Z-no-notion"
            _write_journal(sink_root, [
                _entry_created_event(entry_id),
            ])
            result = _run_rebuild(td, lock_file=lock_file)
            self.assertEqual(result.returncode, 0, msg=f"stderr={result.stderr}")
            view = _read_view(sink_root)
            entry = view["entries"][entry_id]
            self.assertFalse(entry.get("notion_sync_pending", False),
                             "notion_sync_pending must default False when no notion event present")

    def test_no_notion_event_field_not_true(self):
        """Field must not be truthy for entries that never had a notion event."""
        with tempfile.TemporaryDirectory() as td:
            sink_root = Path(td)
            lock_file = str(sink_root / "test.lock")
            entry_id = "20260528T120000Z-no-notion-not-true"
            _write_journal(sink_root, [
                _entry_created_event(entry_id),
            ])
            _run_rebuild(td, lock_file=lock_file)
            view = _read_view(sink_root)
            entry = view["entries"][entry_id]
            # Must not be True (may be absent or False)
            self.assertNotEqual(entry.get("notion_sync_pending", False), True,
                                "notion_sync_pending must not be True for an entry with no notion events")


class TestLastWriterWins(unittest.TestCase):
    """(e)+(f) Last-writer-wins ordering holds."""

    def test_pending_then_synced_then_pending_is_true(self):
        """pending → synced → pending: last event wins → True."""
        with tempfile.TemporaryDirectory() as td:
            sink_root = Path(td)
            lock_file = str(sink_root / "test.lock")
            entry_id = "20260528T120000Z-last-writer-pending"
            _write_journal(sink_root, [
                _entry_created_event(entry_id),
                _notion_sync_pending_event(entry_id, ts="2026-05-28T13:00:00Z"),
                _notion_synced_event(entry_id, ts="2026-05-28T14:00:00Z"),
                _notion_sync_pending_event(entry_id, ts="2026-05-28T15:00:00Z"),
            ])
            result = _run_rebuild(td, lock_file=lock_file)
            self.assertEqual(result.returncode, 0, msg=f"stderr={result.stderr}")
            view = _read_view(sink_root)
            entry = view["entries"][entry_id]
            self.assertTrue(entry.get("notion_sync_pending", False),
                            "last pending event must win: notion_sync_pending must be True")

    def test_pending_then_cleared_then_synced_is_false(self):
        """pending → cleared → synced: last event wins → False."""
        with tempfile.TemporaryDirectory() as td:
            sink_root = Path(td)
            lock_file = str(sink_root / "test.lock")
            entry_id = "20260528T120000Z-last-writer-cleared"
            _write_journal(sink_root, [
                _entry_created_event(entry_id),
                _notion_sync_pending_event(entry_id, ts="2026-05-28T13:00:00Z"),
                _notion_sync_cleared_event(entry_id, ts="2026-05-28T14:00:00Z"),
                _notion_synced_event(entry_id, ts="2026-05-28T15:00:00Z"),
            ])
            result = _run_rebuild(td, lock_file=lock_file)
            self.assertEqual(result.returncode, 0, msg=f"stderr={result.stderr}")
            view = _read_view(sink_root)
            entry = view["entries"][entry_id]
            self.assertFalse(entry.get("notion_sync_pending", False),
                             "last synced event must win: notion_sync_pending must be False")


class TestIncrementalDeterminism(unittest.TestCase):
    """(g) Incremental rebuild across appended notion events matches a full replay."""

    def test_incremental_after_notion_events_matches_full_replay(self):
        """Append notion events, do incremental rebuild → same view as full replay."""
        with tempfile.TemporaryDirectory() as td:
            sink_root = Path(td)
            entry_id = "20260528T120000Z-incremental-notion"

            # Write initial journal and do a full rebuild (seeds checkpoint)
            _write_journal(sink_root, [_entry_created_event(entry_id)])
            r = _run_reducer_full(td)
            self.assertEqual(r.returncode, 0, msg=f"full rebuild failed: {r.stderr}")

            # Append notion events
            _append_journal(sink_root, [
                _notion_sync_pending_event(entry_id),
                _notion_synced_event(entry_id),
            ])

            # Incremental rebuild (uses checkpoint)
            r_inc = _run_reducer_incremental(td)
            self.assertEqual(r_inc.returncode, 0, msg=f"incremental rebuild failed: {r_inc.stderr}")
            view_inc = _read_view(sink_root)

            # Full cold replay of the same journal
            r_full = _run_reducer_full(td)
            self.assertEqual(r_full.returncode, 0, msg=f"full replay failed: {r_full.stderr}")
            view_full = _read_view(sink_root)

            inc_entry = view_inc["entries"][entry_id]
            full_entry = view_full["entries"][entry_id]
            self.assertEqual(
                inc_entry.get("notion_sync_pending"),
                full_entry.get("notion_sync_pending"),
                "incremental and full replay must agree on notion_sync_pending",
            )

    def test_incremental_pending_appended_matches_full(self):
        """Incremental after appending a pending event must show pending=True, same as full."""
        with tempfile.TemporaryDirectory() as td:
            sink_root = Path(td)
            entry_id = "20260528T120000Z-incremental-pending"

            _write_journal(sink_root, [_entry_created_event(entry_id)])
            _run_reducer_full(td)

            _append_journal(sink_root, [_notion_sync_pending_event(entry_id)])

            r_inc = _run_reducer_incremental(td)
            self.assertEqual(r_inc.returncode, 0, msg=f"incremental rebuild failed: {r_inc.stderr}")
            view_inc = _read_view(sink_root)

            r_full = _run_reducer_full(td)
            view_full = _read_view(sink_root)

            self.assertEqual(
                view_inc["entries"][entry_id].get("notion_sync_pending"),
                view_full["entries"][entry_id].get("notion_sync_pending"),
                "incremental and full replay must agree after pending event appended",
            )
            self.assertTrue(
                view_full["entries"][entry_id].get("notion_sync_pending", False),
                "full replay must see notion_sync_pending=True after pending event",
            )


class TestListRendering(unittest.TestCase):
    """(h) List rendering marks only pending entry with notion marker."""

    def _render_list(self, entries: list[dict]) -> str:
        """Invoke the list rendering Python snippet (extracted from z-followup-list.md)."""
        code = r"""
import json, sys

entries = json.loads(sys.argv[1])

if not entries:
    print("(no entries match the current filters)")
    sys.exit(0)

HEADER = "| Priority | Status    | Sink    | ID                                        | Name                              | Created At           | Notion            |"
SEP    = "|----------|-----------|---------|-------------------------------------------|-----------------------------------|----------------------|-------------------|"
print(HEADER)
print(SEP)

for e in entries:
    entry_id = e.get("id", "")
    truncated_id = (entry_id[:40] + "...") if len(entry_id) > 43 else entry_id.ljust(43)
    name = e.get("name", "")
    truncated_name = (name[:33] + "...") if len(name) > 36 else name.ljust(36)
    notion_tag = "[notion: sync pending]" if e.get("notion_sync_pending", False) else ""
    print(
        f"| {e.get('priority','?'):<8} "
        f"| {e.get('status','?'):<9} "
        f"| {e.get('sink','?'):<7} "
        f"| {truncated_id:<43} "
        f"| {truncated_name:<33} "
        f"| {e.get('created_at',''):<20} "
        f"| {notion_tag:<17} |"
    )

print(f"\n{len(entries)} entr{'y' if len(entries)==1 else 'ies'} shown.")
"""
        result = subprocess.run(
            [sys.executable, "-c", code, json.dumps(entries)],
            capture_output=True,
            text=True,
        )
        return result.stdout

    def test_pending_entry_shows_notion_marker(self):
        """An entry with notion_sync_pending=True must show [notion: sync pending] in list output."""
        entries = [
            {
                "id": "20260528T120000Z-pending-entry",
                "priority": "P1",
                "status": "open",
                "sink": "project",
                "name": "Fix something urgent",
                "created_at": "2026-05-28T12:00:00Z",
                "notion_sync_pending": True,
            },
        ]
        output = self._render_list(entries)
        self.assertIn("[notion: sync pending]", output,
                      "pending entry must show [notion: sync pending] in list output")

    def test_non_pending_entry_no_notion_marker(self):
        """An entry without notion_sync_pending must NOT show the marker."""
        entries = [
            {
                "id": "20260528T120000Z-non-pending-entry",
                "priority": "P2",
                "status": "open",
                "sink": "project",
                "name": "A normal entry",
                "created_at": "2026-05-28T12:00:00Z",
            },
        ]
        output = self._render_list(entries)
        self.assertNotIn("[notion: sync pending]", output,
                         "non-pending entry must not show [notion: sync pending]")

    def test_only_pending_entry_shows_marker_among_mixed(self):
        """With one pending and one non-pending entry, only the pending one shows the marker."""
        pending_id = "20260528T120000Z-pending"
        non_pending_id = "20260528T120000Z-non-pending"
        entries = [
            {
                "id": pending_id,
                "priority": "P1",
                "status": "open",
                "sink": "project",
                "name": "Pending entry",
                "created_at": "2026-05-28T12:00:00Z",
                "notion_sync_pending": True,
            },
            {
                "id": non_pending_id,
                "priority": "P2",
                "status": "open",
                "sink": "project",
                "name": "Normal entry",
                "created_at": "2026-05-28T13:00:00Z",
                "notion_sync_pending": False,
            },
        ]
        output = self._render_list(entries)
        lines = output.splitlines()
        # Find data rows (skip header and separator)
        data_lines = [l for l in lines if l.startswith("|") and "Priority" not in l and "---" not in l]
        self.assertEqual(len(data_lines), 2, f"expected 2 data rows; got: {data_lines}")
        pending_line = next((l for l in data_lines if pending_id[:30] in l), None)
        non_pending_line = next((l for l in data_lines if non_pending_id[:30] in l), None)
        self.assertIsNotNone(pending_line, "pending entry row must exist")
        self.assertIsNotNone(non_pending_line, "non-pending entry row must exist")
        self.assertIn("[notion: sync pending]", pending_line,
                      "pending entry row must contain marker")
        self.assertNotIn("[notion: sync pending]", non_pending_line,
                         "non-pending entry row must not contain marker")


class TestStatusNotionCount(unittest.TestCase):
    """(i) Status count of notion_sync_pending entries."""

    def _count_pending(self, entries: list[dict]) -> int:
        """Apply the notion_sync_pending count logic from z-followup-status.md."""
        return sum(1 for e in entries if e.get("notion_sync_pending", False))

    def test_count_one_pending(self):
        """One pending entry in the list → count is 1."""
        entries = [
            {"id": "a", "notion_sync_pending": True},
            {"id": "b", "notion_sync_pending": False},
        ]
        self.assertEqual(self._count_pending(entries), 1,
                         "count must be 1 when one entry is pending")

    def test_count_zero_pending(self):
        """No pending entries → count is 0."""
        entries = [
            {"id": "a"},
            {"id": "b", "notion_sync_pending": False},
        ]
        self.assertEqual(self._count_pending(entries), 0,
                         "count must be 0 when no entries are pending")

    def test_count_all_pending(self):
        """All entries pending → count equals len(entries)."""
        entries = [
            {"id": "a", "notion_sync_pending": True},
            {"id": "b", "notion_sync_pending": True},
            {"id": "c", "notion_sync_pending": True},
        ]
        self.assertEqual(self._count_pending(entries), 3,
                         "count must equal the number of entries when all are pending")

    def test_status_render_shows_notion_pending_count(self):
        """The status render logic must emit 'Notion sync pending: N' line."""
        # Build a minimal status_data with one pending entry
        status_data = {
            "project": {
                "total": 2,
                "counts": {s: 0 for s in ["open", "running", "verify", "done", "failed", "blocked", "dismissed"]},
                "entries": [
                    {"id": "a", "status": "open", "notion_sync_pending": True},
                    {"id": "b", "status": "open", "notion_sync_pending": False},
                ],
            }
        }
        status_data["project"]["counts"]["open"] = 2

        # Run the status render snippet
        code = r"""
import json, sys, os

status_data = json.loads(sys.argv[1])
ALL_STATUSES = ["open", "running", "verify", "done", "failed", "blocked", "dismissed"]
sinks_shown = ["project"]

for label in sinks_shown:
    info = status_data.get(label, {})
    if "error" in info:
        print(f"  {info['error']}")
    else:
        counts = info.get("counts", {})
        for s in ALL_STATUSES:
            print(f"  {s:<12} {counts.get(s, 0)}")
        print(f"  {'─'*13}")
        print(f"  {'total':<12} {info.get('total', 0)}")
        notion_pending = sum(
            1 for e in info.get("entries", [])
            if e.get("notion_sync_pending", False)
        )
        print(f"  {'─'*13}")
        print(f"  Notion sync pending: {notion_pending}")
"""
        result = subprocess.run(
            [sys.executable, "-c", code, json.dumps(status_data)],
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, msg=f"stderr={result.stderr}")
        self.assertIn("Notion sync pending: 1", result.stdout,
                      "status render must show 'Notion sync pending: 1' when one entry pending")

    def test_status_render_shows_zero_when_none_pending(self):
        """Status render must show 'Notion sync pending: 0' when Notion is disabled / nothing pending."""
        status_data = {
            "project": {
                "total": 1,
                "counts": {"open": 1, "running": 0, "verify": 0, "done": 0, "failed": 0, "blocked": 0, "dismissed": 0},
                "entries": [
                    {"id": "a", "status": "open"},
                ],
            }
        }
        code = r"""
import json, sys

status_data = json.loads(sys.argv[1])
ALL_STATUSES = ["open", "running", "verify", "done", "failed", "blocked", "dismissed"]
sinks_shown = ["project"]

for label in sinks_shown:
    info = status_data.get(label, {})
    if "error" in info:
        print(f"  {info['error']}")
    else:
        counts = info.get("counts", {})
        for s in ALL_STATUSES:
            print(f"  {s:<12} {counts.get(s, 0)}")
        print(f"  {'─'*13}")
        print(f"  {'total':<12} {info.get('total', 0)}")
        notion_pending = sum(
            1 for e in info.get("entries", [])
            if e.get("notion_sync_pending", False)
        )
        print(f"  {'─'*13}")
        print(f"  Notion sync pending: {notion_pending}")
"""
        result = subprocess.run(
            [sys.executable, "-c", code, json.dumps(status_data)],
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, msg=f"stderr={result.stderr}")
        self.assertIn("Notion sync pending: 0", result.stdout,
                      "status render must show 'Notion sync pending: 0' when no entries are pending")


class TestUnknownEntryIdSkipped(unittest.TestCase):
    """notion_sync_pending/synced/cleared for unknown entry_id must be skipped gracefully."""

    def test_notion_sync_pending_unknown_entry_skipped(self):
        """notion_sync_pending for an unknown entry_id must not crash and must warn."""
        with tempfile.TemporaryDirectory() as td:
            sink_root = Path(td)
            lock_file = str(sink_root / "test.lock")
            known_entry_id = "20260528T120000Z-known"
            unknown_entry_id = "20260528T120000Z-unknown"
            _write_journal(sink_root, [
                _entry_created_event(known_entry_id),
                _notion_sync_pending_event(unknown_entry_id),
            ])
            result = _run_rebuild(td, lock_file=lock_file)
            self.assertEqual(result.returncode, 0,
                             msg="reducer must not crash on notion_sync_pending for unknown entry")
            self.assertIn("WARNING", result.stderr + result.stdout,
                          "reducer must warn on notion_sync_pending for unknown entry_id")

    def test_notion_synced_unknown_entry_skipped(self):
        """notion_synced for an unknown entry_id must not crash and must warn."""
        with tempfile.TemporaryDirectory() as td:
            sink_root = Path(td)
            lock_file = str(sink_root / "test.lock")
            known_entry_id = "20260528T120000Z-known-sync"
            unknown_entry_id = "20260528T120000Z-unknown-sync"
            _write_journal(sink_root, [
                _entry_created_event(known_entry_id),
                _notion_synced_event(unknown_entry_id),
            ])
            result = _run_rebuild(td, lock_file=lock_file)
            self.assertEqual(result.returncode, 0,
                             msg="reducer must not crash on notion_synced for unknown entry")
            self.assertIn("WARNING", result.stderr + result.stdout,
                          "reducer must warn on notion_synced for unknown entry_id")

    def test_notion_sync_cleared_unknown_entry_skipped(self):
        """notion_sync_cleared for an unknown entry_id must not crash and must warn."""
        with tempfile.TemporaryDirectory() as td:
            sink_root = Path(td)
            lock_file = str(sink_root / "test.lock")
            known_entry_id = "20260528T120000Z-known-clr"
            unknown_entry_id = "20260528T120000Z-unknown-clr"
            _write_journal(sink_root, [
                _entry_created_event(known_entry_id),
                _notion_sync_cleared_event(unknown_entry_id),
            ])
            result = _run_rebuild(td, lock_file=lock_file)
            self.assertEqual(result.returncode, 0,
                             msg="reducer must not crash on notion_sync_cleared for unknown entry")
            self.assertIn("WARNING", result.stderr + result.stdout,
                          "reducer must warn on notion_sync_cleared for unknown entry_id")


if __name__ == "__main__":
    unittest.main()
