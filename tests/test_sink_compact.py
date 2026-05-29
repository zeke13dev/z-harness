"""
tests/test_sink_compact.py — pytest tests for scripts/sink-compact.sh + sink-compact-impl.py

Cases covered:
  (a) archive contains terminal entries' events; live journal retains non-terminal events
  (b) live journal no longer contains terminal entries' events
  (c) view after compaction is correct for surviving non-terminal entries
  (d) rebuild after compaction does a full replay (checkpoint was invalidated) and produces
      a valid, correct view with a fresh checkpoint
  (e) compaction requires the global lock (free-lock invocation is refused with exit 4)
  (f) no-op when there are no terminal entries
  (g) empty journal is a no-op (exits 0, no archive written)
  (h) journal corruption aborts without changing any files (exits 3)
"""

from __future__ import annotations

import fcntl
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
COMPACT_SH = str(REPO_ROOT / "scripts" / "sink-compact.sh")
REBUILD_SH = str(REPO_ROOT / "scripts" / "sink-view-rebuild.sh")

# ── test helpers (mirrored from test_sink_view_rebuild.py) ────────────────────

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


def _run_compact(
    sink_root: str,
    *,
    lock_file: str | None = None,
    hold_lock: bool = True,
    env_extra: dict | None = None,
) -> subprocess.CompletedProcess:
    """Run sink-compact.sh <sink_root>.

    If hold_lock=True (default), acquires the exclusive flock on the sentinel
    before running the script. If hold_lock=False, runs without holding the
    lock (should exit 4).
    """
    env = {**os.environ, **(env_extra or {})}
    if lock_file:
        env["Z_HARNESS_FOLLOWUP_GLOBAL_LOCK"] = lock_file

    resolved_lock = lock_file or os.path.join(sink_root, ".test.lock")
    sentinel = resolved_lock + ".flock"

    compact_cmd = ["bash", COMPACT_SH, sink_root]

    if hold_lock:
        Path(resolved_lock).parent.mkdir(parents=True, exist_ok=True)
        Path(sentinel).touch()
        cmd = [sys.executable, "-c", _HOLD_LOCK_AND_RUN, sentinel, *compact_cmd]
        return subprocess.run(cmd, capture_output=True, text=True, env=env)
    else:
        return subprocess.run(compact_cmd, capture_output=True, text=True, env=env)


def _run_rebuild(
    sink_root: str,
    *,
    lock_file: str | None = None,
    hold_lock: bool = True,
    full: bool = False,
    env_extra: dict | None = None,
) -> subprocess.CompletedProcess:
    """Run sink-view-rebuild.sh <sink_root>."""
    env = {**os.environ, **(env_extra or {})}
    if lock_file:
        env["Z_HARNESS_FOLLOWUP_GLOBAL_LOCK"] = lock_file

    resolved_lock = lock_file or os.path.join(sink_root, ".test.lock")
    sentinel = resolved_lock + ".flock"

    rebuild_cmd = ["bash", REBUILD_SH, sink_root]
    if full:
        rebuild_cmd.append("--full")

    if hold_lock:
        Path(resolved_lock).parent.mkdir(parents=True, exist_ok=True)
        Path(sentinel).touch()
        cmd = [sys.executable, "-c", _HOLD_LOCK_AND_RUN, sentinel, *rebuild_cmd]
        return subprocess.run(cmd, capture_output=True, text=True, env=env)
    else:
        return subprocess.run(rebuild_cmd, capture_output=True, text=True, env=env)


def _write_journal(sink_root: Path, events: list[dict]) -> None:
    """Write events as newline-delimited JSON to <sink_root>/index.jsonl."""
    lines = "\n".join(json.dumps(e) for e in events) + ("\n" if events else "")
    (sink_root / "index.jsonl").write_text(lines, encoding="utf-8")


def _read_view(sink_root: Path) -> dict:
    return json.loads((sink_root / "index.view.json").read_text(encoding="utf-8"))


def _read_journal_events(path: Path) -> list[dict]:
    """Read all JSON events from a JSONL file."""
    if not path.exists():
        return []
    events = []
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped:
            events.append(json.loads(stripped))
    return events


def _entry_created_event(entry_id: str, status: str = "open") -> dict:
    return {
        "kind": "entry_created",
        "ts": "2026-05-28T12:00:00Z",
        "entry": {
            "id": entry_id,
            "schema_version": 1,
            "priority": "P2",
            "name": f"Test entry {entry_id}",
            "status": status,
            "sink": "project",
            "created_at": "2026-05-28T12:00:00Z",
            "created_by_run": "run-001",
            "recommended_command": "/z-do \"test\"",
            "status_history": [
                {"ts": "2026-05-28T12:00:00Z", "from": None, "to": status, "by": "scripts/sink-add.sh"}
            ],
        },
    }


def _status_changed_event(
    entry_id: str, from_status: str, to_status: str, ts: str = "2026-05-28T13:00:00Z"
) -> dict:
    return {
        "kind": "status_changed",
        "ts": ts,
        "entry_id": entry_id,
        "from": from_status,
        "to": to_status,
        "by": "test",
    }


def _build_mixed_journal(sink_root: Path) -> tuple[str, str, str]:
    """Build a journal with terminal (done), terminal (dismissed), and non-terminal (open) entries.

    Returns (done_id, dismissed_id, open_id).
    """
    done_id = "20260528T120000Z-entry-done"
    dismissed_id = "20260528T120001Z-entry-dismissed"
    open_id = "20260528T120002Z-entry-open"
    running_id = "20260528T120003Z-entry-running"

    events = [
        # done entry: created → running → verify → done
        _entry_created_event(done_id),
        _status_changed_event(done_id, "open", "running", "2026-05-28T13:00:00Z"),
        _status_changed_event(done_id, "running", "verify", "2026-05-28T14:00:00Z"),
        _status_changed_event(done_id, "verify", "done", "2026-05-28T15:00:00Z"),
        # dismissed entry: created → dismissed
        _entry_created_event(dismissed_id),
        _status_changed_event(dismissed_id, "open", "dismissed", "2026-05-28T13:30:00Z"),
        # open entry: just created
        _entry_created_event(open_id),
        # running entry: created → running
        _entry_created_event(running_id),
        _status_changed_event(running_id, "open", "running", "2026-05-28T13:45:00Z"),
    ]
    _write_journal(sink_root, events)
    return done_id, dismissed_id, open_id


# ── test cases ─────────────────────────────────────────────────────────────────


class TestLockRequired(unittest.TestCase):
    """(e) Compaction requires the global lock; free-lock invocation exits 4."""

    def test_exits_4_when_lock_is_free(self):
        """Running sink-compact.sh without holding the global lock must exit 4."""
        with tempfile.TemporaryDirectory() as td:
            sink_root = Path(td)
            lock_file = str(sink_root / "global.lock")
            Path(lock_file).touch()
            _write_journal(sink_root, [_entry_created_event("20260528T120000Z-test")])
            result = _run_compact(td, lock_file=lock_file, hold_lock=False)
            self.assertEqual(
                result.returncode, 4,
                msg=f"expected exit 4 (lock not held); got {result.returncode}; stderr={result.stderr}",
            )

    def test_exits_4_mentions_lock_on_stderr(self):
        """Exit 4 must include a diagnostic mentioning 'lock' on stderr."""
        with tempfile.TemporaryDirectory() as td:
            sink_root = Path(td)
            lock_file = str(sink_root / "global.lock")
            Path(lock_file).touch()
            _write_journal(sink_root, [_entry_created_event("20260528T120000Z-test2")])
            result = _run_compact(td, lock_file=lock_file, hold_lock=False)
            self.assertIn(
                "lock", result.stderr.lower(),
                "stderr must mention 'lock' when exiting 4",
            )

    def test_lock_held_succeeds(self):
        """Sanity: when caller holds the lock, compact must exit 0."""
        with tempfile.TemporaryDirectory() as td:
            sink_root = Path(td)
            lock_file = str(sink_root / "global.lock")
            Path(lock_file).touch()
            # Only non-terminal entries → no-op but must exit 0
            _write_journal(sink_root, [_entry_created_event("20260528T120000Z-open-only")])
            result = _run_compact(td, lock_file=lock_file, hold_lock=True)
            self.assertEqual(result.returncode, 0, msg=f"stderr={result.stderr}")


class TestArchiveAndPruning(unittest.TestCase):
    """(a)+(b) Archive contains terminal events; live journal retains non-terminal."""

    def test_terminal_events_archived(self):
        """Events for done/dismissed entries must appear in index.archive.jsonl."""
        with tempfile.TemporaryDirectory() as td:
            sink_root = Path(td)
            lock_file = str(sink_root / "global.lock")
            Path(lock_file).touch()
            done_id, dismissed_id, open_id = _build_mixed_journal(sink_root)

            result = _run_compact(td, lock_file=lock_file, hold_lock=True)
            self.assertEqual(result.returncode, 0, msg=f"stderr={result.stderr}")

            archive_events = _read_journal_events(sink_root / "index.archive.jsonl")
            archive_entry_ids: set[str] = set()
            for ev in archive_events:
                if ev.get("kind") == "entry_created":
                    entry_obj = ev.get("entry")
                    if isinstance(entry_obj, dict):
                        archive_entry_ids.add(entry_obj["id"])
                elif "entry_id" in ev:
                    archive_entry_ids.add(ev["entry_id"])

            self.assertIn(done_id, archive_entry_ids, "done entry must be in archive")
            self.assertIn(dismissed_id, archive_entry_ids, "dismissed entry must be in archive")

    def test_non_terminal_events_not_in_archive(self):
        """Events for open/running entries must NOT appear in index.archive.jsonl."""
        with tempfile.TemporaryDirectory() as td:
            sink_root = Path(td)
            lock_file = str(sink_root / "global.lock")
            Path(lock_file).touch()
            done_id, dismissed_id, open_id = _build_mixed_journal(sink_root)

            result = _run_compact(td, lock_file=lock_file, hold_lock=True)
            self.assertEqual(result.returncode, 0, msg=f"stderr={result.stderr}")

            archive_events = _read_journal_events(sink_root / "index.archive.jsonl")
            archive_entry_ids: set[str] = set()
            for ev in archive_events:
                if ev.get("kind") == "entry_created":
                    entry_obj = ev.get("entry")
                    if isinstance(entry_obj, dict):
                        archive_entry_ids.add(entry_obj["id"])
                elif "entry_id" in ev:
                    archive_entry_ids.add(ev["entry_id"])

            self.assertNotIn(open_id, archive_entry_ids,
                             "open entry must NOT be in archive")

    def test_terminal_events_removed_from_live_journal(self):
        """After compaction, index.jsonl must not contain events for terminal entries."""
        with tempfile.TemporaryDirectory() as td:
            sink_root = Path(td)
            lock_file = str(sink_root / "global.lock")
            Path(lock_file).touch()
            done_id, dismissed_id, open_id = _build_mixed_journal(sink_root)

            result = _run_compact(td, lock_file=lock_file, hold_lock=True)
            self.assertEqual(result.returncode, 0, msg=f"stderr={result.stderr}")

            live_events = _read_journal_events(sink_root / "index.jsonl")
            live_entry_ids: set[str] = set()
            for ev in live_events:
                if ev.get("kind") == "entry_created":
                    entry_obj = ev.get("entry")
                    if isinstance(entry_obj, dict):
                        live_entry_ids.add(entry_obj["id"])
                elif "entry_id" in ev:
                    live_entry_ids.add(ev["entry_id"])

            self.assertNotIn(done_id, live_entry_ids,
                             "done entry events must be removed from live journal")
            self.assertNotIn(dismissed_id, live_entry_ids,
                             "dismissed entry events must be removed from live journal")

    def test_non_terminal_events_retained_in_live_journal(self):
        """After compaction, index.jsonl must still contain events for non-terminal entries."""
        with tempfile.TemporaryDirectory() as td:
            sink_root = Path(td)
            lock_file = str(sink_root / "global.lock")
            Path(lock_file).touch()
            done_id, dismissed_id, open_id = _build_mixed_journal(sink_root)

            result = _run_compact(td, lock_file=lock_file, hold_lock=True)
            self.assertEqual(result.returncode, 0, msg=f"stderr={result.stderr}")

            live_events = _read_journal_events(sink_root / "index.jsonl")
            live_entry_ids: set[str] = set()
            for ev in live_events:
                if ev.get("kind") == "entry_created":
                    entry_obj = ev.get("entry")
                    if isinstance(entry_obj, dict):
                        live_entry_ids.add(entry_obj["id"])
                elif "entry_id" in ev:
                    live_entry_ids.add(ev["entry_id"])

            self.assertIn(open_id, live_entry_ids,
                          "open entry events must be retained in live journal")


class TestViewInvariant(unittest.TestCase):
    """(c)+(d) View after compaction is correct; checkpoint is invalidated and rebuilt."""

    def test_view_correct_for_non_terminal_entries(self):
        """After compaction, the view must correctly reflect non-terminal entries."""
        with tempfile.TemporaryDirectory() as td:
            sink_root = Path(td)
            lock_file = str(sink_root / "global.lock")
            Path(lock_file).touch()

            open_id = "20260528T120002Z-open-entry"
            running_id = "20260528T120003Z-running-entry"
            done_id = "20260528T120000Z-done-entry"

            events = [
                _entry_created_event(done_id),
                _status_changed_event(done_id, "open", "running"),
                _status_changed_event(done_id, "running", "done"),
                _entry_created_event(open_id),
                _entry_created_event(running_id),
                _status_changed_event(running_id, "open", "running"),
            ]
            _write_journal(sink_root, events)

            # Build the pre-compaction view
            pre_result = _run_rebuild(td, lock_file=lock_file, hold_lock=True)
            self.assertEqual(pre_result.returncode, 0, msg=f"pre-compact rebuild: {pre_result.stderr}")
            pre_view = _read_view(sink_root)

            # Run compaction
            result = _run_compact(td, lock_file=lock_file, hold_lock=True)
            self.assertEqual(result.returncode, 0, msg=f"compact: {result.stderr}")

            # Post-compaction view
            post_view = _read_view(sink_root)

            # Non-terminal entries must be in the view with correct status
            self.assertIn(open_id, post_view["entries"],
                          "open entry must be in post-compaction view")
            self.assertEqual(post_view["entries"][open_id]["status"], "open",
                             "open entry status must be correct")

            self.assertIn(running_id, post_view["entries"],
                          "running entry must be in post-compaction view")
            self.assertEqual(post_view["entries"][running_id]["status"], "running",
                             "running entry status must be correct")

    def test_non_terminal_entries_unchanged_by_compaction(self):
        """Non-terminal entries in the view must be identical before and after compaction."""
        with tempfile.TemporaryDirectory() as td:
            sink_root = Path(td)
            lock_file = str(sink_root / "global.lock")
            Path(lock_file).touch()

            open_id = "20260528T120002Z-open-unchanged"
            done_id = "20260528T120000Z-done-compacted"

            events = [
                _entry_created_event(done_id),
                _status_changed_event(done_id, "open", "done"),
                _entry_created_event(open_id),
                _status_changed_event(open_id, "open", "running"),
            ]
            _write_journal(sink_root, events)

            # Build pre-compaction view
            pre_result = _run_rebuild(td, lock_file=lock_file, hold_lock=True)
            self.assertEqual(pre_result.returncode, 0)
            pre_view = _read_view(sink_root)
            pre_open_entry = pre_view["entries"][open_id]

            # Run compaction
            result = _run_compact(td, lock_file=lock_file, hold_lock=True)
            self.assertEqual(result.returncode, 0, msg=f"compact: {result.stderr}")

            post_view = _read_view(sink_root)
            post_open_entry = post_view["entries"][open_id]

            # The non-terminal entry must be byte-identical (excluding top-level _checkpoint)
            self.assertEqual(
                pre_open_entry, post_open_entry,
                "non-terminal entry must be byte-identical before and after compaction",
            )

    def test_checkpoint_invalidated_before_rebuild(self):
        """Compaction must invalidate the T010 checkpoint; next rebuild must be a full replay."""
        with tempfile.TemporaryDirectory() as td:
            sink_root = Path(td)
            lock_file = str(sink_root / "global.lock")
            Path(lock_file).touch()

            open_id = "20260528T120002Z-open-ckpt"
            done_id = "20260528T120000Z-done-ckpt"

            events = [
                _entry_created_event(done_id),
                _status_changed_event(done_id, "open", "done"),
                _entry_created_event(open_id),
            ]
            _write_journal(sink_root, events)

            # Build pre-compaction view (establishes a checkpoint)
            pre_result = _run_rebuild(td, lock_file=lock_file, hold_lock=True)
            self.assertEqual(pre_result.returncode, 0)
            pre_view = _read_view(sink_root)
            self.assertIn("_checkpoint", pre_view,
                          "pre-compaction view must have a checkpoint")

            # Run compaction — it must invalidate the checkpoint and rebuild
            result = _run_compact(td, lock_file=lock_file, hold_lock=True)
            self.assertEqual(result.returncode, 0, msg=f"compact: {result.stderr}")

            # The post-compaction view must exist and have a valid (fresh) checkpoint
            self.assertTrue((sink_root / "index.view.json").exists(),
                            "index.view.json must be regenerated after compaction")
            post_view = _read_view(sink_root)
            self.assertIn("_checkpoint", post_view,
                          "post-compaction view must have a fresh checkpoint")

            # The fresh checkpoint must reflect the compacted journal size, not the
            # pre-compaction one (the journal is now shorter).
            pre_byte_len = pre_view["_checkpoint"]["journal_byte_length"]
            post_byte_len = post_view["_checkpoint"]["journal_byte_length"]
            self.assertLess(
                post_byte_len, pre_byte_len,
                "post-compaction checkpoint byte length must be smaller than pre-compaction "
                "(terminal events were evicted from the journal)",
            )

    def test_full_replay_after_compaction_produces_valid_view(self):
        """A subsequent full rebuild after compaction must produce a valid correct view."""
        with tempfile.TemporaryDirectory() as td:
            sink_root = Path(td)
            lock_file = str(sink_root / "global.lock")
            Path(lock_file).touch()

            open_id = "20260528T120002Z-open-rebuild"
            done_id = "20260528T120000Z-done-rebuild"

            events = [
                _entry_created_event(done_id),
                _status_changed_event(done_id, "open", "running"),
                _status_changed_event(done_id, "running", "done"),
                _entry_created_event(open_id),
            ]
            _write_journal(sink_root, events)

            # Run compaction (includes a full rebuild internally)
            result = _run_compact(td, lock_file=lock_file, hold_lock=True)
            self.assertEqual(result.returncode, 0, msg=f"compact: {result.stderr}")

            # Run another full rebuild explicitly
            rebuild_result = _run_rebuild(td, lock_file=lock_file, hold_lock=True, full=True)
            self.assertEqual(rebuild_result.returncode, 0,
                             msg=f"post-compact --full rebuild: {rebuild_result.stderr}")

            view = _read_view(sink_root)
            self.assertIn("entries", view, "view must have entries dict")
            self.assertIn(open_id, view["entries"],
                          "open entry must survive in view after full rebuild")
            self.assertEqual(view["entries"][open_id]["status"], "open",
                             "open entry must still be 'open' after full rebuild")


class TestNoOpCases(unittest.TestCase):
    """(f)+(g) No terminal entries → no-op; empty journal → no-op."""

    def test_no_terminal_entries_exits_0(self):
        """When there are no terminal entries, compact must exit 0."""
        with tempfile.TemporaryDirectory() as td:
            sink_root = Path(td)
            lock_file = str(sink_root / "global.lock")
            Path(lock_file).touch()
            _write_journal(sink_root, [
                _entry_created_event("20260528T120000Z-open"),
                _entry_created_event("20260528T120001Z-running"),
                _status_changed_event("20260528T120001Z-running", "open", "running"),
            ])
            result = _run_compact(td, lock_file=lock_file, hold_lock=True)
            self.assertEqual(result.returncode, 0, msg=f"stderr={result.stderr}")

    def test_no_terminal_entries_no_archive_created(self):
        """When there are no terminal entries, index.archive.jsonl must not be created."""
        with tempfile.TemporaryDirectory() as td:
            sink_root = Path(td)
            lock_file = str(sink_root / "global.lock")
            Path(lock_file).touch()
            _write_journal(sink_root, [
                _entry_created_event("20260528T120000Z-open-only"),
            ])
            _run_compact(td, lock_file=lock_file, hold_lock=True)
            self.assertFalse(
                (sink_root / "index.archive.jsonl").exists(),
                "index.archive.jsonl must not be created when there are no terminal entries",
            )

    def test_empty_journal_exits_0(self):
        """Empty journal is a no-op and exits 0."""
        with tempfile.TemporaryDirectory() as td:
            sink_root = Path(td)
            lock_file = str(sink_root / "global.lock")
            Path(lock_file).touch()
            (sink_root / "index.jsonl").write_text("", encoding="utf-8")
            result = _run_compact(td, lock_file=lock_file, hold_lock=True)
            self.assertEqual(result.returncode, 0, msg=f"stderr={result.stderr}")

    def test_absent_journal_exits_0(self):
        """Absent journal is a no-op and exits 0."""
        with tempfile.TemporaryDirectory() as td:
            sink_root = Path(td)
            lock_file = str(sink_root / "global.lock")
            Path(lock_file).touch()
            # No index.jsonl written
            result = _run_compact(td, lock_file=lock_file, hold_lock=True)
            self.assertEqual(result.returncode, 0, msg=f"stderr={result.stderr}")


class TestCorruptionAbort(unittest.TestCase):
    """(h) Journal corruption aborts without changing any files (exits 3)."""

    def test_corruption_exits_3_and_leaves_journal_unchanged(self):
        """Corruption in journal must exit 3 without modifying index.jsonl."""
        with tempfile.TemporaryDirectory() as td:
            sink_root = Path(td)
            lock_file = str(sink_root / "global.lock")
            Path(lock_file).touch()

            entry_id = "20260528T120000Z-corrupt"
            journal = sink_root / "index.jsonl"
            journal_content = (
                json.dumps(_entry_created_event(entry_id)) + "\n"
                + "{CORRUPT LINE\n"
                + json.dumps(_status_changed_event(entry_id, "open", "running")) + "\n"
            )
            journal.write_text(journal_content, encoding="utf-8")

            result = _run_compact(td, lock_file=lock_file, hold_lock=True)
            self.assertEqual(result.returncode, 3,
                             msg=f"expected exit 3 on corruption; got {result.returncode}; "
                                 f"stderr={result.stderr}")

            # index.jsonl must be unchanged
            self.assertEqual(
                journal.read_text(encoding="utf-8"), journal_content,
                "index.jsonl must be unchanged after compaction aborts on corruption",
            )

    def test_corruption_does_not_create_archive(self):
        """Corruption abort must not create or modify index.archive.jsonl."""
        with tempfile.TemporaryDirectory() as td:
            sink_root = Path(td)
            lock_file = str(sink_root / "global.lock")
            Path(lock_file).touch()

            entry_id = "20260528T120000Z-corrupt2"
            journal = sink_root / "index.jsonl"
            journal.write_text(
                json.dumps(_entry_created_event(entry_id)) + "\n"
                + "{CORRUPT LINE\n",
                encoding="utf-8",
            )

            _run_compact(td, lock_file=lock_file, hold_lock=True)
            self.assertFalse(
                (sink_root / "index.archive.jsonl").exists(),
                "index.archive.jsonl must not be created on corruption abort",
            )


class TestArchiveAppend(unittest.TestCase):
    """Compaction appends to index.archive.jsonl (doesn't truncate existing archive)."""

    def test_archive_is_appended_not_truncated(self):
        """Running compaction twice must append to the archive, not truncate it."""
        with tempfile.TemporaryDirectory() as td:
            sink_root = Path(td)
            lock_file = str(sink_root / "global.lock")
            Path(lock_file).touch()

            done_id_1 = "20260528T120000Z-done-first"
            done_id_2 = "20260528T120001Z-done-second"

            # First compaction: one terminal entry
            events_1 = [
                _entry_created_event(done_id_1),
                _status_changed_event(done_id_1, "open", "done"),
            ]
            _write_journal(sink_root, events_1)
            result1 = _run_compact(td, lock_file=lock_file, hold_lock=True)
            self.assertEqual(result1.returncode, 0, msg=f"first compact: {result1.stderr}")

            archive_after_first = (sink_root / "index.archive.jsonl").read_text(encoding="utf-8")
            self.assertTrue(archive_after_first.strip(), "archive must have content after first compact")

            # Second compaction: a new terminal entry
            events_2 = [
                _entry_created_event(done_id_2),
                _status_changed_event(done_id_2, "open", "done"),
            ]
            _write_journal(sink_root, events_2)
            result2 = _run_compact(td, lock_file=lock_file, hold_lock=True)
            self.assertEqual(result2.returncode, 0, msg=f"second compact: {result2.stderr}")

            archive_after_second = (sink_root / "index.archive.jsonl").read_text(encoding="utf-8")
            self.assertGreater(
                len(archive_after_second), len(archive_after_first),
                "second compaction must append to archive, making it larger",
            )
            # Both archived entries must be in the final archive
            self.assertIn(done_id_1, archive_after_second,
                          "first archived entry must still be present after second compaction")
            self.assertIn(done_id_2, archive_after_second,
                          "second archived entry must be present after second compaction")


class TestAtomicRewrite(unittest.TestCase):
    """index.jsonl rewrite is atomic (no .compact.tmp.* files left behind)."""

    def test_no_tmpfile_left_behind(self):
        """After successful compaction, no .index.jsonl.compact.tmp.* files must remain."""
        with tempfile.TemporaryDirectory() as td:
            sink_root = Path(td)
            lock_file = str(sink_root / "global.lock")
            Path(lock_file).touch()
            done_id = "20260528T120000Z-done-atomic"
            events = [
                _entry_created_event(done_id),
                _status_changed_event(done_id, "open", "done"),
                _entry_created_event("20260528T120001Z-open"),
            ]
            _write_journal(sink_root, events)
            result = _run_compact(td, lock_file=lock_file, hold_lock=True)
            self.assertEqual(result.returncode, 0, msg=f"stderr={result.stderr}")
            tmp_files = list(sink_root.glob(".index.jsonl.compact.tmp.*"))
            self.assertEqual(tmp_files, [], f"tmp files left behind: {tmp_files}")
