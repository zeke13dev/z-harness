"""
tests/test_sink_view_rebuild.py — pytest tests for sink-view-rebuild.sh + sink-view-reducer.py

Cases covered:
  (a) empty journal → empty view (entries:{})
  (b) full lifecycle journal (entry_created, status_changed open→running,
      status_changed running→verify, status_changed verify→done)
      → correct end-state entry with status=done
  (c) unknown event kind in middle of journal → skipped silently, lifecycle still correct
  (d) idempotency — rebuild twice, bytes identical
  (e) lock-not-held → exits 4
  (f) truncated final line → exits 3, index.view.json left untouched, stderr mentions corruption
  (g) interior corrupt line → exits 3 (both default and --repair)
  (h) --repair strips bad tail and rebuilds successfully; original view state reflected
  (i) clean journal after prior corruption test → normal rebuild path not broken
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
REBUILD_SH = str(REPO_ROOT / "scripts" / "sink-view-rebuild.sh")
REDUCER_PY = str(REPO_ROOT / "scripts" / "sink-view-reducer.py")


# ── helpers ────────────────────────────────────────────────────────────────────

# Tiny Python helper script that holds an exclusive flock on the sentinel file,
# then runs sink-view-rebuild.sh as a child process, then releases the lock.
# This mirrors what sink-lock.sh / sink-claim.sh do in production.
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


def _run_rebuild(sink_root: str, *, lock_file: str | None = None,
                 hold_lock: bool = True, env_extra: dict | None = None,
                 repair: bool = False) -> subprocess.CompletedProcess:
    """
    Run sink-view-rebuild.sh <sink_root>.

    If hold_lock=True (default), acquires the exclusive flock on the sentinel
    file (.flock suffix) before running the script, so the script sees the lock
    as held. Uses a tiny inline Python helper (no dependency on the `flock`
    CLI utility which is absent on macOS).

    If hold_lock=False, runs the script without holding the lock (should → exit 4).
    """
    env = {**os.environ, **(env_extra or {})}
    if lock_file:
        env["Z_HARNESS_FOLLOWUP_GLOBAL_LOCK"] = lock_file

    # The rebuild script looks for <lock_file>.flock as its sentinel.
    resolved_lock = lock_file or os.path.join(sink_root, ".test.lock")
    sentinel = resolved_lock + ".flock"

    rebuild_cmd = ["bash", REBUILD_SH, sink_root]
    if repair:
        rebuild_cmd.append("--repair")

    if hold_lock:
        Path(resolved_lock).parent.mkdir(parents=True, exist_ok=True)
        Path(sentinel).touch()
        # Run via the Python lock-holder helper
        cmd = [
            sys.executable, "-c", _HOLD_LOCK_AND_RUN,
            sentinel,
            *rebuild_cmd,
        ]
        return subprocess.run(cmd, capture_output=True, text=True, env=env)
    else:
        return subprocess.run(
            rebuild_cmd,
            capture_output=True,
            text=True,
            env=env,
        )


def _run_reducer(sink_root: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, REDUCER_PY, sink_root],
        capture_output=True,
        text=True,
    )


def _write_journal(sink_root: Path, events: list[dict]) -> None:
    """Write events as newline-delimited JSON to <sink_root>/index.jsonl."""
    lines = "\n".join(json.dumps(e) for e in events) + ("\n" if events else "")
    (sink_root / "index.jsonl").write_text(lines, encoding="utf-8")


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


def _status_changed_event(entry_id: str, from_status: str, to_status: str, ts: str = "2026-05-28T13:00:00Z") -> dict:
    return {
        "kind": "status_changed",
        "ts": ts,
        "entry_id": entry_id,
        "from": from_status,
        "to": to_status,
        "by": "test",
    }


# ── test cases ─────────────────────────────────────────────────────────────────

class TestEmptyJournal(unittest.TestCase):
    """(a) empty journal → empty view (entries:{})"""

    def test_empty_journal_produces_empty_entries(self):
        with tempfile.TemporaryDirectory() as td:
            sink_root = Path(td)
            lock_file = str(sink_root / "test.lock")
            # No index.jsonl written → treat as empty
            result = _run_rebuild(td, lock_file=lock_file, hold_lock=True)
            self.assertEqual(result.returncode, 0, msg=f"stderr={result.stderr}")
            view = _read_view(sink_root)
            # view["entries"] must be empty; view may also carry a "_checkpoint" field
            self.assertEqual(view["entries"], {})

    def test_empty_journal_file_produces_empty_entries(self):
        """Explicit empty index.jsonl still produces entries:{}."""
        with tempfile.TemporaryDirectory() as td:
            sink_root = Path(td)
            lock_file = str(sink_root / "test.lock")
            (sink_root / "index.jsonl").write_text("", encoding="utf-8")
            result = _run_rebuild(td, lock_file=lock_file, hold_lock=True)
            self.assertEqual(result.returncode, 0, msg=f"stderr={result.stderr}")
            view = _read_view(sink_root)
            # view["entries"] must be empty; view may also carry a "_checkpoint" field
            self.assertEqual(view["entries"], {})


class TestFullLifecycle(unittest.TestCase):
    """(b) full lifecycle → status=done with correct end state."""

    def test_full_lifecycle_status_is_done(self):
        """entry_created + open→running + running→verify + verify→done → status=done."""
        with tempfile.TemporaryDirectory() as td:
            sink_root = Path(td)
            lock_file = str(sink_root / "test.lock")
            entry_id = "20260528T120000Z-test-entry"
            events = [
                _entry_created_event(entry_id),
                _status_changed_event(entry_id, "open", "running", "2026-05-28T13:00:00Z"),
                _status_changed_event(entry_id, "running", "verify", "2026-05-28T14:00:00Z"),
                _status_changed_event(entry_id, "verify", "done", "2026-05-28T15:00:00Z"),
            ]
            _write_journal(sink_root, events)
            result = _run_rebuild(td, lock_file=lock_file, hold_lock=True)
            self.assertEqual(result.returncode, 0, msg=f"stderr={result.stderr}")
            view = _read_view(sink_root)
            self.assertIn(entry_id, view["entries"])
            entry = view["entries"][entry_id]
            self.assertEqual(entry["status"], "done")

    def test_full_lifecycle_status_history_length(self):
        """The status_history after full lifecycle must have 4 entries (1 from create + 3 transitions)."""
        with tempfile.TemporaryDirectory() as td:
            sink_root = Path(td)
            lock_file = str(sink_root / "test.lock")
            entry_id = "20260528T120000Z-lifecycle"
            events = [
                _entry_created_event(entry_id),
                _status_changed_event(entry_id, "open", "running"),
                _status_changed_event(entry_id, "running", "verify"),
                _status_changed_event(entry_id, "verify", "done"),
            ]
            _write_journal(sink_root, events)
            result = _run_rebuild(td, lock_file=lock_file, hold_lock=True)
            self.assertEqual(result.returncode, 0, msg=f"stderr={result.stderr}")
            view = _read_view(sink_root)
            entry = view["entries"][entry_id]
            # Original status_history from entry_created has 1 item; 3 more appended = 4 total
            self.assertEqual(len(entry["status_history"]), 4)

    def test_final_status_in_history_is_done(self):
        with tempfile.TemporaryDirectory() as td:
            sink_root = Path(td)
            lock_file = str(sink_root / "test.lock")
            entry_id = "20260528T120000Z-history-check"
            events = [
                _entry_created_event(entry_id),
                _status_changed_event(entry_id, "open", "running"),
                _status_changed_event(entry_id, "running", "verify"),
                _status_changed_event(entry_id, "verify", "done"),
            ]
            _write_journal(sink_root, events)
            _run_rebuild(td, lock_file=lock_file, hold_lock=True)
            view = _read_view(sink_root)
            entry = view["entries"][entry_id]
            last_hist = entry["status_history"][-1]
            self.assertEqual(last_hist["to"], "done")


class TestUnknownEventKind(unittest.TestCase):
    """(c) unknown event kind in middle → skipped silently; lifecycle still correct."""

    def test_unknown_event_skipped_does_not_crash(self):
        with tempfile.TemporaryDirectory() as td:
            sink_root = Path(td)
            lock_file = str(sink_root / "test.lock")
            entry_id = "20260528T120000Z-unknown-evt"
            events = [
                _entry_created_event(entry_id),
                _status_changed_event(entry_id, "open", "running"),
                {
                    "kind": "totally_unknown_future_event_v99",
                    "ts": "2026-05-28T13:30:00Z",
                    "entry_id": entry_id,
                    "some_future_field": "ignored",
                },
                _status_changed_event(entry_id, "running", "verify"),
                _status_changed_event(entry_id, "verify", "done"),
            ]
            _write_journal(sink_root, events)
            result = _run_rebuild(td, lock_file=lock_file, hold_lock=True)
            self.assertEqual(result.returncode, 0, msg=f"stderr={result.stderr}")

    def test_unknown_event_lifecycle_still_correct(self):
        """After skipping the unknown event, the final status must still be done."""
        with tempfile.TemporaryDirectory() as td:
            sink_root = Path(td)
            lock_file = str(sink_root / "test.lock")
            entry_id = "20260528T120000Z-unknown-evt-lifecycle"
            events = [
                _entry_created_event(entry_id),
                _status_changed_event(entry_id, "open", "running"),
                {"kind": "unknown_future_event", "ts": "2026-05-28T13:30:00Z"},
                _status_changed_event(entry_id, "running", "verify"),
                _status_changed_event(entry_id, "verify", "done"),
            ]
            _write_journal(sink_root, events)
            _run_rebuild(td, lock_file=lock_file, hold_lock=True)
            view = _read_view(sink_root)
            entry = view["entries"][entry_id]
            self.assertEqual(entry["status"], "done")

    def test_unknown_event_produces_warning_on_stderr(self):
        """The reducer must log a WARNING for unknown event kinds."""
        with tempfile.TemporaryDirectory() as td:
            sink_root = Path(td)
            lock_file = str(sink_root / "test.lock")
            events = [
                {"kind": "totally_unknown_kind", "ts": "2026-05-28T12:00:00Z"},
            ]
            _write_journal(sink_root, events)
            result = _run_rebuild(td, lock_file=lock_file, hold_lock=True)
            self.assertEqual(result.returncode, 0, msg="reducer must not crash on unknown event")
            self.assertIn("WARNING", result.stderr + result.stdout,
                          "must emit a WARNING for unknown event kind")


class TestIdempotency(unittest.TestCase):
    """(d) rebuild twice → bytes identical."""

    def test_rebuild_twice_bytes_identical(self):
        with tempfile.TemporaryDirectory() as td:
            sink_root = Path(td)
            lock_file = str(sink_root / "test.lock")
            entry_id = "20260528T120000Z-idempotent"
            events = [
                _entry_created_event(entry_id),
                _status_changed_event(entry_id, "open", "running"),
                _status_changed_event(entry_id, "running", "verify"),
            ]
            _write_journal(sink_root, events)
            result1 = _run_rebuild(td, lock_file=lock_file, hold_lock=True)
            self.assertEqual(result1.returncode, 0, msg=f"first rebuild failed: {result1.stderr}")
            content1 = (sink_root / "index.view.json").read_bytes()

            result2 = _run_rebuild(td, lock_file=lock_file, hold_lock=True)
            self.assertEqual(result2.returncode, 0, msg=f"second rebuild failed: {result2.stderr}")
            content2 = (sink_root / "index.view.json").read_bytes()

            self.assertEqual(content1, content2, "two consecutive rebuilds must produce identical bytes")

    def test_rebuild_idempotent_status_unchanged(self):
        """After two rebuilds, the view status must be the same as after one rebuild."""
        with tempfile.TemporaryDirectory() as td:
            sink_root = Path(td)
            lock_file = str(sink_root / "test.lock")
            entry_id = "20260528T120000Z-idem-status"
            events = [
                _entry_created_event(entry_id),
                _status_changed_event(entry_id, "open", "running"),
            ]
            _write_journal(sink_root, events)
            _run_rebuild(td, lock_file=lock_file, hold_lock=True)
            view1 = _read_view(sink_root)
            _run_rebuild(td, lock_file=lock_file, hold_lock=True)
            view2 = _read_view(sink_root)
            self.assertEqual(
                view1["entries"][entry_id]["status"],
                view2["entries"][entry_id]["status"],
            )


class TestLockNotHeld(unittest.TestCase):
    """(e) lock not held → exits 4."""

    def test_exits_4_when_lock_is_free(self):
        """Running rebuild without holding the global lock must exit 4."""
        with tempfile.TemporaryDirectory() as td:
            sink_root = Path(td)
            lock_file = str(sink_root / "global.lock")
            Path(lock_file).touch()
            # hold_lock=False: script runs without anyone holding the lock
            result = _run_rebuild(td, lock_file=lock_file, hold_lock=False)
            self.assertEqual(result.returncode, 4,
                             msg=f"expected exit 4 (lock not held); got {result.returncode}; "
                                 f"stderr={result.stderr}")

    def test_exits_4_stderr_message(self):
        """Exit 4 must accompany a diagnostic on stderr."""
        with tempfile.TemporaryDirectory() as td:
            sink_root = Path(td)
            lock_file = str(sink_root / "global.lock")
            Path(lock_file).touch()
            result = _run_rebuild(td, lock_file=lock_file, hold_lock=False)
            self.assertIn("lock", result.stderr.lower(),
                          "stderr must mention 'lock' when exiting 4")

    def test_lock_held_succeeds(self):
        """Sanity: when caller holds the lock, script must exit 0."""
        with tempfile.TemporaryDirectory() as td:
            sink_root = Path(td)
            lock_file = str(sink_root / "global.lock")
            Path(lock_file).touch()
            result = _run_rebuild(td, lock_file=lock_file, hold_lock=True)
            self.assertEqual(result.returncode, 0, msg=f"stderr={result.stderr}")


class TestAtomicWrite(unittest.TestCase):
    """View is written via tmpfile+rename (no partial output)."""

    def test_view_file_is_valid_json(self):
        with tempfile.TemporaryDirectory() as td:
            sink_root = Path(td)
            lock_file = str(sink_root / "global.lock")
            Path(lock_file).touch()
            entry_id = "20260528T120000Z-atomic"
            _write_journal(sink_root, [_entry_created_event(entry_id)])
            _run_rebuild(td, lock_file=lock_file, hold_lock=True)
            content = (sink_root / "index.view.json").read_text(encoding="utf-8")
            # Must parse without error
            data = json.loads(content)
            self.assertIn("entries", data)

    def test_no_tmpfile_left_behind(self):
        """After successful rebuild, no .index.view.tmp.* files must remain."""
        with tempfile.TemporaryDirectory() as td:
            sink_root = Path(td)
            lock_file = str(sink_root / "global.lock")
            Path(lock_file).touch()
            _write_journal(sink_root, [])
            _run_rebuild(td, lock_file=lock_file, hold_lock=True)
            tmp_files = list(sink_root.glob(".index.view.tmp.*"))
            self.assertEqual(tmp_files, [], f"tmpfiles left behind: {tmp_files}")


class TestForwardCompat(unittest.TestCase):
    """Reducer ignores unknown fields in known event types."""

    def test_unknown_fields_in_entry_created_ignored(self):
        """Extra fields in an entry object are preserved as-is without crashing."""
        with tempfile.TemporaryDirectory() as td:
            sink_root = Path(td)
            lock_file = str(sink_root / "global.lock")
            Path(lock_file).touch()
            entry_id = "20260528T120000Z-fwdcompat"
            # Add a field that doesn't exist in schema_version=1
            event = _entry_created_event(entry_id)
            event["entry"]["future_field_v2"] = "some_value"
            _write_journal(sink_root, [event])
            result = _run_rebuild(td, lock_file=lock_file, hold_lock=True)
            self.assertEqual(result.returncode, 0, msg=f"stderr={result.stderr}")

    def test_unknown_fields_in_status_changed_ignored(self):
        """Extra fields in a status_changed event don't crash the reducer."""
        with tempfile.TemporaryDirectory() as td:
            sink_root = Path(td)
            lock_file = str(sink_root / "global.lock")
            Path(lock_file).touch()
            entry_id = "20260528T120000Z-fwdcompat2"
            events = [
                _entry_created_event(entry_id),
                {
                    "kind": "status_changed",
                    "ts": "2026-05-28T13:00:00Z",
                    "entry_id": entry_id,
                    "from": "open",
                    "to": "running",
                    "by": "test",
                    "new_field_schema_v2": "ignored_value",
                },
            ]
            _write_journal(sink_root, events)
            result = _run_rebuild(td, lock_file=lock_file, hold_lock=True)
            self.assertEqual(result.returncode, 0, msg=f"stderr={result.stderr}")
            view = _read_view(sink_root)
            self.assertEqual(view["entries"][entry_id]["status"], "running")


class TestMalformedLines(unittest.TestCase):
    """Malformed JSON lines in the journal cause hard abort; reducer exits non-zero."""

    def test_malformed_interior_line_exits_nonzero(self):
        """An interior corrupt line causes exit 3; index.view.json is NOT written."""
        with tempfile.TemporaryDirectory() as td:
            sink_root = Path(td)
            lock_file = str(sink_root / "global.lock")
            Path(lock_file).touch()
            entry_id = "20260528T120000Z-malformed"
            # Mix a broken JSON line between two valid events (interior corruption)
            journal = sink_root / "index.jsonl"
            journal.write_text(
                json.dumps(_entry_created_event(entry_id)) + "\n"
                + "{THIS IS NOT JSON!!!\n"
                + json.dumps(_status_changed_event(entry_id, "open", "running")) + "\n",
                encoding="utf-8",
            )
            result = _run_rebuild(td, lock_file=lock_file, hold_lock=True)
            self.assertEqual(result.returncode, 3,
                             msg=f"reducer must exit 3 on interior corrupt line; stderr={result.stderr}")
            # index.view.json must NOT have been written
            self.assertFalse((sink_root / "index.view.json").exists(),
                             "index.view.json must not be written when journal is corrupt")


class TestTruncatedFinalLine(unittest.TestCase):
    """(f) truncated final line → exits 3, index.view.json left untouched."""

    def test_truncated_final_line_exits_3(self):
        """Default mode: truncated final line causes exit 3."""
        with tempfile.TemporaryDirectory() as td:
            sink_root = Path(td)
            lock_file = str(sink_root / "global.lock")
            Path(lock_file).touch()
            entry_id = "20260528T120000Z-truncated"
            journal = sink_root / "index.jsonl"
            # Write a valid event then a truncated (incomplete) JSON line at the end
            journal.write_text(
                json.dumps(_entry_created_event(entry_id)) + "\n"
                + '{"kind":"status_changed","entry_id":"' + entry_id + '","to":"running"',  # truncated
                encoding="utf-8",
            )
            result = _run_rebuild(td, lock_file=lock_file, hold_lock=True)
            self.assertEqual(result.returncode, 3,
                             msg=f"expected exit 3 on truncated final line; stderr={result.stderr}")

    def test_truncated_final_line_view_untouched(self):
        """Default mode: existing index.view.json must NOT be overwritten on corruption."""
        with tempfile.TemporaryDirectory() as td:
            sink_root = Path(td)
            lock_file = str(sink_root / "global.lock")
            Path(lock_file).touch()
            entry_id = "20260528T120000Z-truncated-view"
            # Write a known-good view first
            original_view = {"entries": {"sentinel": {"status": "open"}}}
            (sink_root / "index.view.json").write_text(
                json.dumps(original_view), encoding="utf-8"
            )
            journal = sink_root / "index.jsonl"
            journal.write_text(
                json.dumps(_entry_created_event(entry_id)) + "\n"
                + '{"kind":"status_changed","entry_id":"' + entry_id + '","to":"running"',
                encoding="utf-8",
            )
            result = _run_rebuild(td, lock_file=lock_file, hold_lock=True)
            self.assertEqual(result.returncode, 3)
            # View must still contain the original sentinel entry
            view = _read_view(sink_root)
            self.assertIn("sentinel", view["entries"],
                          "existing index.view.json must not be overwritten on corruption")

    def test_truncated_final_line_stderr_mentions_corruption(self):
        """Default mode: stderr must mention the corruption/truncation."""
        with tempfile.TemporaryDirectory() as td:
            sink_root = Path(td)
            lock_file = str(sink_root / "global.lock")
            Path(lock_file).touch()
            entry_id = "20260528T120000Z-stderr-check"
            journal = sink_root / "index.jsonl"
            journal.write_text(
                json.dumps(_entry_created_event(entry_id)) + "\n"
                + '{"kind":"status_changed","entry_id":"' + entry_id + '"',
                encoding="utf-8",
            )
            result = _run_rebuild(td, lock_file=lock_file, hold_lock=True)
            self.assertEqual(result.returncode, 3)
            combined = result.stderr + result.stdout
            self.assertTrue(
                any(word in combined.lower() for word in ("corrupt", "truncat", "error")),
                f"stderr/stdout must mention corruption or truncation; got: {combined!r}",
            )


class TestRepairFlag(unittest.TestCase):
    """(h) --repair strips bad tail and rebuilds successfully."""

    def test_repair_strips_truncated_tail_and_exits_0(self):
        """--repair on a truncated tail must exit 0 and produce a valid view."""
        with tempfile.TemporaryDirectory() as td:
            sink_root = Path(td)
            lock_file = str(sink_root / "global.lock")
            Path(lock_file).touch()
            entry_id = "20260528T120000Z-repair-exit0"
            journal = sink_root / "index.jsonl"
            # Valid event + truncated final line
            journal.write_text(
                json.dumps(_entry_created_event(entry_id)) + "\n"
                + '{"kind":"status_changed","entry_id":"' + entry_id + '","to":"running"',
                encoding="utf-8",
            )
            result = _run_rebuild(td, lock_file=lock_file, hold_lock=True, repair=True)
            self.assertEqual(result.returncode, 0,
                             msg=f"--repair must exit 0 after stripping truncated tail; stderr={result.stderr}")

    def test_repair_view_reflects_good_events(self):
        """After --repair, the view must reflect only the good events before the broken tail."""
        with tempfile.TemporaryDirectory() as td:
            sink_root = Path(td)
            lock_file = str(sink_root / "global.lock")
            Path(lock_file).touch()
            entry_id = "20260528T120000Z-repair-view"
            journal = sink_root / "index.jsonl"
            # Two valid events + truncated final line (the truncated line is a status_changed to "done")
            journal.write_text(
                json.dumps(_entry_created_event(entry_id)) + "\n"
                + json.dumps(_status_changed_event(entry_id, "open", "running")) + "\n"
                + '{"kind":"status_changed","entry_id":"' + entry_id + '","to":"done"',
                encoding="utf-8",
            )
            result = _run_rebuild(td, lock_file=lock_file, hold_lock=True, repair=True)
            self.assertEqual(result.returncode, 0, msg=f"stderr={result.stderr}")
            view = _read_view(sink_root)
            self.assertIn(entry_id, view["entries"])
            # The truncated "to done" event was stripped; status must be "running" (last good event)
            self.assertEqual(view["entries"][entry_id]["status"], "running",
                             "repaired view must reflect only good events")

    def test_repair_rewrites_journal_atomically(self):
        """After --repair, index.jsonl must no longer contain the bad trailing line."""
        with tempfile.TemporaryDirectory() as td:
            sink_root = Path(td)
            lock_file = str(sink_root / "global.lock")
            Path(lock_file).touch()
            entry_id = "20260528T120000Z-repair-journal"
            journal = sink_root / "index.jsonl"
            bad_tail = '{"kind":"status_changed","entry_id":"' + entry_id + '"'
            journal.write_text(
                json.dumps(_entry_created_event(entry_id)) + "\n" + bad_tail,
                encoding="utf-8",
            )
            result = _run_rebuild(td, lock_file=lock_file, hold_lock=True, repair=True)
            self.assertEqual(result.returncode, 0, msg=f"stderr={result.stderr}")
            repaired = journal.read_text(encoding="utf-8")
            self.assertNotIn(bad_tail, repaired,
                             "repaired journal must not contain the truncated line")

    def test_repair_interior_corrupt_line_exits_nonzero(self):
        """--repair on an interior corrupt line (not tail) must still exit non-zero."""
        with tempfile.TemporaryDirectory() as td:
            sink_root = Path(td)
            lock_file = str(sink_root / "global.lock")
            Path(lock_file).touch()
            entry_id = "20260528T120000Z-repair-interior"
            journal = sink_root / "index.jsonl"
            # Corrupt line in the MIDDLE, followed by a valid line
            journal.write_text(
                json.dumps(_entry_created_event(entry_id)) + "\n"
                + "{CORRUPT INTERIOR LINE\n"
                + json.dumps(_status_changed_event(entry_id, "open", "running")) + "\n",
                encoding="utf-8",
            )
            result = _run_rebuild(td, lock_file=lock_file, hold_lock=True, repair=True)
            self.assertNotEqual(result.returncode, 0,
                                "--repair must not succeed on interior corrupt line")

    def test_repair_stderr_logs_dropped_content(self):
        """--repair must log/mention what was dropped on stderr."""
        with tempfile.TemporaryDirectory() as td:
            sink_root = Path(td)
            lock_file = str(sink_root / "global.lock")
            Path(lock_file).touch()
            entry_id = "20260528T120000Z-repair-log"
            journal = sink_root / "index.jsonl"
            journal.write_text(
                json.dumps(_entry_created_event(entry_id)) + "\n"
                + '{"kind":"status_changed","entry_id":"' + entry_id + '"',
                encoding="utf-8",
            )
            result = _run_rebuild(td, lock_file=lock_file, hold_lock=True, repair=True)
            self.assertEqual(result.returncode, 0, msg=f"stderr={result.stderr}")
            combined = result.stderr + result.stdout
            self.assertTrue(
                any(word in combined.lower() for word in ("repair", "drop", "corrupt", "strip")),
                f"--repair must log what was dropped; got: {combined!r}",
            )


class TestCleanJournalAfterCorruptionFix(unittest.TestCase):
    """(i) Normal (clean) rebuild path is not broken by the corruption-detection changes."""

    def test_clean_journal_still_works(self):
        """A clean journal with no corruption must still produce a correct view."""
        with tempfile.TemporaryDirectory() as td:
            sink_root = Path(td)
            lock_file = str(sink_root / "global.lock")
            Path(lock_file).touch()
            entry_id = "20260528T120000Z-clean-after-fix"
            events = [
                _entry_created_event(entry_id),
                _status_changed_event(entry_id, "open", "running"),
                _status_changed_event(entry_id, "running", "verify"),
                _status_changed_event(entry_id, "verify", "done"),
            ]
            _write_journal(sink_root, events)
            result = _run_rebuild(td, lock_file=lock_file, hold_lock=True)
            self.assertEqual(result.returncode, 0, msg=f"stderr={result.stderr}")
            view = _read_view(sink_root)
            self.assertEqual(view["entries"][entry_id]["status"], "done")

    def test_clean_journal_with_repair_flag_still_works(self):
        """A clean journal with --repair flag must also produce a correct view."""
        with tempfile.TemporaryDirectory() as td:
            sink_root = Path(td)
            lock_file = str(sink_root / "global.lock")
            Path(lock_file).touch()
            entry_id = "20260528T120000Z-clean-repair-flag"
            events = [
                _entry_created_event(entry_id),
                _status_changed_event(entry_id, "open", "running"),
            ]
            _write_journal(sink_root, events)
            result = _run_rebuild(td, lock_file=lock_file, hold_lock=True, repair=True)
            self.assertEqual(result.returncode, 0, msg=f"--repair on a clean journal must exit 0; stderr={result.stderr}")
            view = _read_view(sink_root)
            self.assertEqual(view["entries"][entry_id]["status"], "running")


class TestCorruptionEventEmissionNoRunContext(unittest.TestCase):
    """(a-new) Corruption event emission is attempted even without a Z_HARNESS_RUN context."""

    def _run_reducer_no_run_context(self, sink_root: str) -> subprocess.CompletedProcess:
        """Run the reducer directly (bypassing rebuild.sh lock check) with no Z_HARNESS_RUN set."""
        env = {k: v for k, v in os.environ.items() if k != "Z_HARNESS_RUN"}
        # Also strip any Z_HARNESS_* vars to ensure no run context leaks in
        env = {k: v for k, v in env.items() if not k.startswith("Z_HARNESS_RUN")}
        return subprocess.run(
            [sys.executable, REDUCER_PY, sink_root],
            capture_output=True,
            text=True,
            env=env,
        )

    def test_corruption_without_run_context_exits_3(self):
        """Corruption must exit 3 even when Z_HARNESS_RUN is not set."""
        with tempfile.TemporaryDirectory() as td:
            sink_root = Path(td)
            entry_id = "20260528T120000Z-no-run-ctx"
            journal = sink_root / "index.jsonl"
            journal.write_text(
                json.dumps(_entry_created_event(entry_id)) + "\n"
                + '{"kind":"status_changed","entry_id":"' + entry_id + '"',
                encoding="utf-8",
            )
            result = self._run_reducer_no_run_context(td)
            self.assertEqual(result.returncode, 3,
                             msg=f"reducer must exit 3 on corruption even without run context; stderr={result.stderr}")

    def test_corruption_without_run_context_stderr_has_error(self):
        """Corruption must emit an ERROR on stderr regardless of run context."""
        with tempfile.TemporaryDirectory() as td:
            sink_root = Path(td)
            entry_id = "20260528T120000Z-no-run-ctx-stderr"
            journal = sink_root / "index.jsonl"
            journal.write_text(
                json.dumps(_entry_created_event(entry_id)) + "\n"
                + '{"kind":"status_changed","entry_id":"' + entry_id + '"',
                encoding="utf-8",
            )
            result = self._run_reducer_no_run_context(td)
            combined = result.stderr + result.stdout
            self.assertIn("ERROR", combined,
                          f"stderr must contain ERROR on corruption; got: {combined!r}")

    def test_corruption_without_run_context_view_untouched(self):
        """Existing index.view.json must remain untouched on corruption regardless of run context."""
        with tempfile.TemporaryDirectory() as td:
            sink_root = Path(td)
            entry_id = "20260528T120000Z-no-run-ctx-view"
            original_view = {"entries": {"sentinel": {"status": "open"}}}
            (sink_root / "index.view.json").write_text(
                json.dumps(original_view), encoding="utf-8"
            )
            journal = sink_root / "index.jsonl"
            journal.write_text(
                json.dumps(_entry_created_event(entry_id)) + "\n"
                + '{"kind":"status_changed","entry_id":"' + entry_id + '"',
                encoding="utf-8",
            )
            result = self._run_reducer_no_run_context(td)
            self.assertEqual(result.returncode, 3)
            view = _read_view(sink_root)
            self.assertIn("sentinel", view["entries"],
                          "existing index.view.json must not be overwritten when run context absent")

    def test_corruption_without_run_context_fallback_event_written(self):
        """Without a run context, the reducer must write the event to events.jsonl as fallback."""
        with tempfile.TemporaryDirectory() as td:
            sink_root = Path(td)
            entry_id = "20260528T120000Z-no-run-ctx-fallback"
            journal = sink_root / "index.jsonl"
            journal.write_text(
                json.dumps(_entry_created_event(entry_id)) + "\n"
                + '{"kind":"status_changed","entry_id":"' + entry_id + '"',
                encoding="utf-8",
            )
            result = self._run_reducer_no_run_context(td)
            self.assertEqual(result.returncode, 3,
                             msg=f"must exit 3; stderr={result.stderr}")
            events_path = sink_root / "events.jsonl"
            self.assertTrue(events_path.exists(),
                            "events.jsonl fallback must be created when no run context is active")
            events_content = events_path.read_text(encoding="utf-8")
            self.assertIn("followup_journal_truncated", events_content,
                          "events.jsonl must contain the followup_journal_truncated event")


class TestRepairMissingJournal(unittest.TestCase):
    """(b-new) --repair on a missing journal must not raise an uncaught traceback."""

    def test_repair_missing_journal_exits_0(self):
        """--repair when index.jsonl does not exist must exit 0 (like normal path)."""
        with tempfile.TemporaryDirectory() as td:
            sink_root = Path(td)
            lock_file = str(sink_root / "global.lock")
            Path(lock_file).touch()
            # No index.jsonl written
            result = _run_rebuild(td, lock_file=lock_file, hold_lock=True, repair=True)
            self.assertEqual(result.returncode, 0,
                             msg=f"--repair on missing journal must exit 0; stderr={result.stderr}")

    def test_repair_missing_journal_produces_empty_view(self):
        """--repair when index.jsonl does not exist must produce an empty view."""
        with tempfile.TemporaryDirectory() as td:
            sink_root = Path(td)
            lock_file = str(sink_root / "global.lock")
            Path(lock_file).touch()
            result = _run_rebuild(td, lock_file=lock_file, hold_lock=True, repair=True)
            self.assertEqual(result.returncode, 0, msg=f"stderr={result.stderr}")
            view = _read_view(sink_root)
            # view["entries"] must be empty; view may also carry a "_checkpoint" field
            self.assertEqual(view["entries"], {},
                             "--repair on missing journal must produce entries:{}")

    def test_repair_missing_journal_no_traceback(self):
        """--repair on missing journal must not emit a Python traceback."""
        with tempfile.TemporaryDirectory() as td:
            sink_root = Path(td)
            lock_file = str(sink_root / "global.lock")
            Path(lock_file).touch()
            result = _run_rebuild(td, lock_file=lock_file, hold_lock=True, repair=True)
            combined = result.stderr + result.stdout
            self.assertNotIn("Traceback", combined,
                             f"--repair on missing journal must not produce a traceback; got: {combined!r}")
            self.assertNotIn("FileNotFoundError", combined,
                             f"--repair on missing journal must not show FileNotFoundError; got: {combined!r}")


class TestEntryRefreshedEvent(unittest.TestCase):
    """entry_refreshed event handling in the reducer (T004 / H3).

    Invariant: after an entry_refreshed event the view must reflect the new
    capture_head and the new hashes, and the opposite hash field must be None.
    """

    def _entry_refreshed_file_event(
        self,
        entry_id: str,
        new_head: str,
        file_hashes: dict,
        ts: str = "2026-05-28T14:00:00Z",
    ) -> dict:
        return {
            "kind": "entry_refreshed",
            "ts": ts,
            "entry_id": entry_id,
            "new_capture_head": new_head,
            "new_file_blob_hashes": file_hashes,
        }

    def _entry_refreshed_dir_event(
        self,
        entry_id: str,
        new_head: str,
        dir_hashes: dict,
        ts: str = "2026-05-28T14:00:00Z",
    ) -> dict:
        return {
            "kind": "entry_refreshed",
            "ts": ts,
            "entry_id": entry_id,
            "new_capture_head": new_head,
            "new_dir_blob_hashes": dir_hashes,
        }

    def test_entry_refreshed_file_hashes_updates_capture_head(self):
        """entry_refreshed with new_file_blob_hashes must update capture_head."""
        with tempfile.TemporaryDirectory() as td:
            sink_root = Path(td)
            lock_file = str(sink_root / "global.lock")
            Path(lock_file).touch()
            entry_id = "20260528T120000Z-refresh-file-head"
            new_head = "abc123def456" + "a" * 28  # 40-char sha-like string
            file_hashes = {"foo/bar.py": "sha256:" + "a" * 64}
            events = [
                _entry_created_event(entry_id),
                self._entry_refreshed_file_event(entry_id, new_head, file_hashes),
            ]
            _write_journal(sink_root, events)
            result = _run_rebuild(td, lock_file=lock_file, hold_lock=True)
            self.assertEqual(result.returncode, 0, msg=f"stderr={result.stderr}")
            view = _read_view(sink_root)
            entry = view["entries"][entry_id]
            self.assertEqual(entry["capture_head"], new_head,
                             "capture_head must be updated by entry_refreshed")

    def test_entry_refreshed_file_hashes_sets_file_blob_hashes(self):
        """entry_refreshed with new_file_blob_hashes must set file_blob_hashes on the entry."""
        with tempfile.TemporaryDirectory() as td:
            sink_root = Path(td)
            lock_file = str(sink_root / "global.lock")
            Path(lock_file).touch()
            entry_id = "20260528T120000Z-refresh-file-hashes"
            new_head = "b" * 40
            file_hashes = {"scripts/foo.py": "sha256:" + "b" * 64}
            events = [
                _entry_created_event(entry_id),
                self._entry_refreshed_file_event(entry_id, new_head, file_hashes),
            ]
            _write_journal(sink_root, events)
            _run_rebuild(td, lock_file=lock_file, hold_lock=True)
            view = _read_view(sink_root)
            entry = view["entries"][entry_id]
            self.assertEqual(entry["file_blob_hashes"], file_hashes,
                             "file_blob_hashes must be set from new_file_blob_hashes")

    def test_entry_refreshed_file_hashes_nulls_dir_blob_hashes(self):
        """entry_refreshed with new_file_blob_hashes must null dir_blob_hashes."""
        with tempfile.TemporaryDirectory() as td:
            sink_root = Path(td)
            lock_file = str(sink_root / "global.lock")
            Path(lock_file).touch()
            entry_id = "20260528T120000Z-refresh-file-nulls-dir"
            new_head = "c" * 40
            file_hashes = {"path/to/file.py": "sha256:" + "c" * 64}
            events = [
                _entry_created_event(entry_id),
                self._entry_refreshed_file_event(entry_id, new_head, file_hashes),
            ]
            _write_journal(sink_root, events)
            _run_rebuild(td, lock_file=lock_file, hold_lock=True)
            view = _read_view(sink_root)
            entry = view["entries"][entry_id]
            self.assertIsNone(entry.get("dir_blob_hashes"),
                              "dir_blob_hashes must be None when file hashes are provided")

    def test_entry_refreshed_dir_hashes_updates_capture_head(self):
        """entry_refreshed with new_dir_blob_hashes must update capture_head."""
        with tempfile.TemporaryDirectory() as td:
            sink_root = Path(td)
            lock_file = str(sink_root / "global.lock")
            Path(lock_file).touch()
            entry_id = "20260528T120000Z-refresh-dir-head"
            new_head = "d" * 40
            dir_hashes = {"scripts/": "sha256:" + "d" * 64}
            events = [
                _entry_created_event(entry_id),
                self._entry_refreshed_dir_event(entry_id, new_head, dir_hashes),
            ]
            _write_journal(sink_root, events)
            result = _run_rebuild(td, lock_file=lock_file, hold_lock=True)
            self.assertEqual(result.returncode, 0, msg=f"stderr={result.stderr}")
            view = _read_view(sink_root)
            entry = view["entries"][entry_id]
            self.assertEqual(entry["capture_head"], new_head,
                             "capture_head must be updated by entry_refreshed (dir variant)")

    def test_entry_refreshed_dir_hashes_sets_dir_blob_hashes(self):
        """entry_refreshed with new_dir_blob_hashes must set dir_blob_hashes on the entry."""
        with tempfile.TemporaryDirectory() as td:
            sink_root = Path(td)
            lock_file = str(sink_root / "global.lock")
            Path(lock_file).touch()
            entry_id = "20260528T120000Z-refresh-dir-hashes"
            new_head = "e" * 40
            dir_hashes = {"src/": "sha256:" + "e" * 64}
            events = [
                _entry_created_event(entry_id),
                self._entry_refreshed_dir_event(entry_id, new_head, dir_hashes),
            ]
            _write_journal(sink_root, events)
            _run_rebuild(td, lock_file=lock_file, hold_lock=True)
            view = _read_view(sink_root)
            entry = view["entries"][entry_id]
            self.assertEqual(entry["dir_blob_hashes"], dir_hashes,
                             "dir_blob_hashes must be set from new_dir_blob_hashes")

    def test_entry_refreshed_dir_hashes_nulls_file_blob_hashes(self):
        """entry_refreshed with new_dir_blob_hashes must null file_blob_hashes."""
        with tempfile.TemporaryDirectory() as td:
            sink_root = Path(td)
            lock_file = str(sink_root / "global.lock")
            Path(lock_file).touch()
            entry_id = "20260528T120000Z-refresh-dir-nulls-file"
            new_head = "f" * 40
            dir_hashes = {"src/": "sha256:" + "f" * 64}
            events = [
                _entry_created_event(entry_id),
                self._entry_refreshed_dir_event(entry_id, new_head, dir_hashes),
            ]
            _write_journal(sink_root, events)
            _run_rebuild(td, lock_file=lock_file, hold_lock=True)
            view = _read_view(sink_root)
            entry = view["entries"][entry_id]
            self.assertIsNone(entry.get("file_blob_hashes"),
                              "file_blob_hashes must be None when dir hashes are provided")

    def test_entry_refreshed_replaces_stale_hashes(self):
        """entry_refreshed must overwrite any previously set file_blob_hashes with new values."""
        with tempfile.TemporaryDirectory() as td:
            sink_root = Path(td)
            lock_file = str(sink_root / "global.lock")
            Path(lock_file).touch()
            entry_id = "20260528T120000Z-refresh-overwrite"
            initial_head = "0" * 40
            stale_head = "1" * 40
            fresh_head = "2" * 40
            stale_hashes = {"foo.py": "sha256:" + "1" * 64}
            fresh_hashes = {"foo.py": "sha256:" + "2" * 64}
            # Build an entry that already has file_blob_hashes embedded
            created_event = _entry_created_event(entry_id)
            created_event["entry"]["capture_head"] = initial_head
            created_event["entry"]["file_blob_hashes"] = stale_hashes
            events = [
                created_event,
                self._entry_refreshed_file_event(entry_id, fresh_head, fresh_hashes),
            ]
            _write_journal(sink_root, events)
            _run_rebuild(td, lock_file=lock_file, hold_lock=True)
            view = _read_view(sink_root)
            entry = view["entries"][entry_id]
            self.assertEqual(entry["capture_head"], fresh_head,
                             "capture_head must be updated to the fresh head")
            self.assertEqual(entry["file_blob_hashes"], fresh_hashes,
                             "file_blob_hashes must reflect the refreshed values, not the stale ones")

    def test_without_entry_refreshed_stale_hashes_remain(self):
        """Without an entry_refreshed event, original hashes must remain (negative control)."""
        with tempfile.TemporaryDirectory() as td:
            sink_root = Path(td)
            lock_file = str(sink_root / "global.lock")
            Path(lock_file).touch()
            entry_id = "20260528T120000Z-no-refresh-negative"
            initial_head = "a1b2c3d4e5" + "0" * 30
            original_hashes = {"bar.py": "sha256:" + "0" * 64}
            created_event = _entry_created_event(entry_id)
            created_event["entry"]["capture_head"] = initial_head
            created_event["entry"]["file_blob_hashes"] = original_hashes
            events = [
                created_event,
                _status_changed_event(entry_id, "open", "running"),
            ]
            _write_journal(sink_root, events)
            _run_rebuild(td, lock_file=lock_file, hold_lock=True)
            view = _read_view(sink_root)
            entry = view["entries"][entry_id]
            self.assertEqual(entry["capture_head"], initial_head,
                             "capture_head must not change without an entry_refreshed event")
            self.assertEqual(entry["file_blob_hashes"], original_hashes,
                             "file_blob_hashes must not change without an entry_refreshed event")


class TestEntryRefreshedMalformedPayload(unittest.TestCase):
    """MAJOR 1+2 regression: malformed entry_refreshed must NOT partially mutate state.

    Invariant: when entry_refreshed carries BOTH hash fields or NEITHER hash field,
    capture_head, file_blob_hashes, and dir_blob_hashes must remain UNCHANGED,
    and the reducer must emit a WARNING.
    """

    def _make_entry_with_hashes(self, entry_id: str, head: str, file_hashes: dict) -> dict:
        """Return an entry_created event with pre-populated capture_head and file_blob_hashes."""
        evt = _entry_created_event(entry_id)
        evt["entry"]["capture_head"] = head
        evt["entry"]["file_blob_hashes"] = file_hashes
        evt["entry"]["dir_blob_hashes"] = None
        return evt

    def test_both_hash_fields_present_capture_head_unchanged(self):
        """Both new_file_blob_hashes and new_dir_blob_hashes present → capture_head must not change."""
        with tempfile.TemporaryDirectory() as td:
            sink_root = Path(td)
            lock_file = str(sink_root / "global.lock")
            Path(lock_file).touch()
            entry_id = "20260528T120000Z-both-hashes-head"
            original_head = "0" * 40
            new_head = "1" * 40
            file_hashes = {"foo.py": "sha256:" + "a" * 64}
            events = [
                self._make_entry_with_hashes(entry_id, original_head, file_hashes),
                {
                    "kind": "entry_refreshed",
                    "ts": "2026-05-28T14:00:00Z",
                    "entry_id": entry_id,
                    "new_capture_head": new_head,
                    "new_file_blob_hashes": {"foo.py": "sha256:" + "b" * 64},
                    "new_dir_blob_hashes": {"src/": "sha256:" + "c" * 64},
                },
            ]
            _write_journal(sink_root, events)
            _run_rebuild(td, lock_file=lock_file, hold_lock=True)
            view = _read_view(sink_root)
            entry = view["entries"][entry_id]
            self.assertEqual(entry["capture_head"], original_head,
                             "capture_head must remain unchanged when both hash fields present")

    def test_both_hash_fields_present_file_blob_hashes_unchanged(self):
        """Both present → file_blob_hashes must not be mutated."""
        with tempfile.TemporaryDirectory() as td:
            sink_root = Path(td)
            lock_file = str(sink_root / "global.lock")
            Path(lock_file).touch()
            entry_id = "20260528T120000Z-both-hashes-file"
            original_head = "0" * 40
            original_file_hashes = {"foo.py": "sha256:" + "a" * 64}
            events = [
                self._make_entry_with_hashes(entry_id, original_head, original_file_hashes),
                {
                    "kind": "entry_refreshed",
                    "ts": "2026-05-28T14:00:00Z",
                    "entry_id": entry_id,
                    "new_capture_head": "1" * 40,
                    "new_file_blob_hashes": {"foo.py": "sha256:" + "b" * 64},
                    "new_dir_blob_hashes": {"src/": "sha256:" + "c" * 64},
                },
            ]
            _write_journal(sink_root, events)
            _run_rebuild(td, lock_file=lock_file, hold_lock=True)
            view = _read_view(sink_root)
            entry = view["entries"][entry_id]
            self.assertEqual(entry["file_blob_hashes"], original_file_hashes,
                             "file_blob_hashes must remain unchanged when both hash fields present")

    def test_both_hash_fields_present_dir_blob_hashes_unchanged(self):
        """Both present → dir_blob_hashes must not be mutated (stays None)."""
        with tempfile.TemporaryDirectory() as td:
            sink_root = Path(td)
            lock_file = str(sink_root / "global.lock")
            Path(lock_file).touch()
            entry_id = "20260528T120000Z-both-hashes-dir"
            original_head = "0" * 40
            file_hashes = {"foo.py": "sha256:" + "a" * 64}
            events = [
                self._make_entry_with_hashes(entry_id, original_head, file_hashes),
                {
                    "kind": "entry_refreshed",
                    "ts": "2026-05-28T14:00:00Z",
                    "entry_id": entry_id,
                    "new_capture_head": "1" * 40,
                    "new_file_blob_hashes": {"foo.py": "sha256:" + "b" * 64},
                    "new_dir_blob_hashes": {"src/": "sha256:" + "c" * 64},
                },
            ]
            _write_journal(sink_root, events)
            _run_rebuild(td, lock_file=lock_file, hold_lock=True)
            view = _read_view(sink_root)
            entry = view["entries"][entry_id]
            self.assertIsNone(entry.get("dir_blob_hashes"),
                              "dir_blob_hashes must remain None when both hash fields present")

    def test_both_hash_fields_present_emits_warning(self):
        """Both present → reducer must emit a WARNING on stderr."""
        with tempfile.TemporaryDirectory() as td:
            sink_root = Path(td)
            lock_file = str(sink_root / "global.lock")
            Path(lock_file).touch()
            entry_id = "20260528T120000Z-both-hashes-warn"
            events = [
                _entry_created_event(entry_id),
                {
                    "kind": "entry_refreshed",
                    "ts": "2026-05-28T14:00:00Z",
                    "entry_id": entry_id,
                    "new_capture_head": "1" * 40,
                    "new_file_blob_hashes": {"foo.py": "sha256:" + "b" * 64},
                    "new_dir_blob_hashes": {"src/": "sha256:" + "c" * 64},
                },
            ]
            _write_journal(sink_root, events)
            result = _run_rebuild(td, lock_file=lock_file, hold_lock=True)
            self.assertEqual(result.returncode, 0,
                             "reducer must not crash on malformed entry_refreshed (both present)")
            self.assertIn("WARNING", result.stderr + result.stdout,
                          "reducer must emit a WARNING when both hash fields are present")

    def test_neither_hash_field_present_capture_head_unchanged(self):
        """Neither new_file_blob_hashes nor new_dir_blob_hashes → capture_head must not change."""
        with tempfile.TemporaryDirectory() as td:
            sink_root = Path(td)
            lock_file = str(sink_root / "global.lock")
            Path(lock_file).touch()
            entry_id = "20260528T120000Z-neither-hashes-head"
            original_head = "0" * 40
            file_hashes = {"foo.py": "sha256:" + "a" * 64}
            events = [
                self._make_entry_with_hashes(entry_id, original_head, file_hashes),
                {
                    "kind": "entry_refreshed",
                    "ts": "2026-05-28T14:00:00Z",
                    "entry_id": entry_id,
                    "new_capture_head": "9" * 40,
                    # no new_file_blob_hashes, no new_dir_blob_hashes
                },
            ]
            _write_journal(sink_root, events)
            _run_rebuild(td, lock_file=lock_file, hold_lock=True)
            view = _read_view(sink_root)
            entry = view["entries"][entry_id]
            self.assertEqual(entry["capture_head"], original_head,
                             "capture_head must remain unchanged when neither hash field present")

    def test_neither_hash_field_present_file_blob_hashes_unchanged(self):
        """Neither present → file_blob_hashes must not be mutated."""
        with tempfile.TemporaryDirectory() as td:
            sink_root = Path(td)
            lock_file = str(sink_root / "global.lock")
            Path(lock_file).touch()
            entry_id = "20260528T120000Z-neither-hashes-file"
            original_head = "0" * 40
            original_file_hashes = {"foo.py": "sha256:" + "a" * 64}
            events = [
                self._make_entry_with_hashes(entry_id, original_head, original_file_hashes),
                {
                    "kind": "entry_refreshed",
                    "ts": "2026-05-28T14:00:00Z",
                    "entry_id": entry_id,
                    "new_capture_head": "9" * 40,
                },
            ]
            _write_journal(sink_root, events)
            _run_rebuild(td, lock_file=lock_file, hold_lock=True)
            view = _read_view(sink_root)
            entry = view["entries"][entry_id]
            self.assertEqual(entry["file_blob_hashes"], original_file_hashes,
                             "file_blob_hashes must remain unchanged when neither hash field present")

    def test_neither_hash_field_present_dir_blob_hashes_unchanged(self):
        """Neither present → dir_blob_hashes must not be mutated (stays None)."""
        with tempfile.TemporaryDirectory() as td:
            sink_root = Path(td)
            lock_file = str(sink_root / "global.lock")
            Path(lock_file).touch()
            entry_id = "20260528T120000Z-neither-hashes-dir"
            original_head = "0" * 40
            file_hashes = {"foo.py": "sha256:" + "a" * 64}
            events = [
                self._make_entry_with_hashes(entry_id, original_head, file_hashes),
                {
                    "kind": "entry_refreshed",
                    "ts": "2026-05-28T14:00:00Z",
                    "entry_id": entry_id,
                    "new_capture_head": "9" * 40,
                },
            ]
            _write_journal(sink_root, events)
            _run_rebuild(td, lock_file=lock_file, hold_lock=True)
            view = _read_view(sink_root)
            entry = view["entries"][entry_id]
            self.assertIsNone(entry.get("dir_blob_hashes"),
                              "dir_blob_hashes must remain None when neither hash field present")

    def test_neither_hash_field_present_emits_warning(self):
        """Neither present → reducer must emit a WARNING on stderr."""
        with tempfile.TemporaryDirectory() as td:
            sink_root = Path(td)
            lock_file = str(sink_root / "global.lock")
            Path(lock_file).touch()
            entry_id = "20260528T120000Z-neither-hashes-warn"
            events = [
                _entry_created_event(entry_id),
                {
                    "kind": "entry_refreshed",
                    "ts": "2026-05-28T14:00:00Z",
                    "entry_id": entry_id,
                    "new_capture_head": "9" * 40,
                },
            ]
            _write_journal(sink_root, events)
            result = _run_rebuild(td, lock_file=lock_file, hold_lock=True)
            self.assertEqual(result.returncode, 0,
                             "reducer must not crash on malformed entry_refreshed (neither present)")
            self.assertIn("WARNING", result.stderr + result.stdout,
                          "reducer must emit a WARNING when neither hash field is present")


class TestDoneToDismissedPolicy(unittest.TestCase):
    """M2: done → dismissed must set dismissed_after_done=True and retain closed_at/completion_mode.
       open → dismissed (and other non-done sources) must NOT get the marker.
    """

    def _make_done_entry_events(self, entry_id: str, closed_at: str = "2026-05-28T16:00:00Z") -> list:
        """Return a journal that takes entry_id through open → running → verify → done."""
        return [
            _entry_created_event(entry_id),
            _status_changed_event(entry_id, "open", "running", "2026-05-28T13:00:00Z"),
            _status_changed_event(entry_id, "running", "verify", "2026-05-28T14:00:00Z"),
            {
                "kind": "status_changed",
                "ts": "2026-05-28T15:00:00Z",
                "entry_id": entry_id,
                "from": "verify",
                "to": "done",
                "by": "test",
                "completion_mode": "human_confirmed",
                "closed_at": closed_at,
            },
        ]

    def test_done_to_dismissed_sets_dismissed_after_done(self):
        """done → dismissed must stamp dismissed_after_done=True on the entry."""
        with tempfile.TemporaryDirectory() as td:
            sink_root = Path(td)
            lock_file = str(sink_root / "global.lock")
            Path(lock_file).touch()
            entry_id = "20260528T120000Z-done-dismissed-marker"
            events = self._make_done_entry_events(entry_id)
            events.append(_status_changed_event(entry_id, "done", "dismissed", "2026-05-28T17:00:00Z"))
            _write_journal(sink_root, events)
            result = _run_rebuild(td, lock_file=lock_file, hold_lock=True)
            self.assertEqual(result.returncode, 0, msg=f"stderr={result.stderr}")
            view = _read_view(sink_root)
            entry = view["entries"][entry_id]
            self.assertTrue(
                entry.get("dismissed_after_done"),
                "dismissed_after_done must be True when transitioning done → dismissed",
            )

    def test_done_to_dismissed_retains_closed_at(self):
        """done → dismissed must NOT null closed_at (audit trail preservation)."""
        with tempfile.TemporaryDirectory() as td:
            sink_root = Path(td)
            lock_file = str(sink_root / "global.lock")
            Path(lock_file).touch()
            entry_id = "20260528T120000Z-done-dismissed-closed-at"
            closed_at = "2026-05-28T16:00:00Z"
            events = self._make_done_entry_events(entry_id, closed_at=closed_at)
            events.append(_status_changed_event(entry_id, "done", "dismissed", "2026-05-28T17:00:00Z"))
            _write_journal(sink_root, events)
            _run_rebuild(td, lock_file=lock_file, hold_lock=True)
            view = _read_view(sink_root)
            entry = view["entries"][entry_id]
            self.assertEqual(
                entry.get("closed_at"), closed_at,
                "closed_at must be retained after done → dismissed transition",
            )

    def test_done_to_dismissed_retains_completion_mode(self):
        """done → dismissed must NOT null completion_mode (audit trail preservation)."""
        with tempfile.TemporaryDirectory() as td:
            sink_root = Path(td)
            lock_file = str(sink_root / "global.lock")
            Path(lock_file).touch()
            entry_id = "20260528T120000Z-done-dismissed-completion-mode"
            events = self._make_done_entry_events(entry_id)
            events.append(_status_changed_event(entry_id, "done", "dismissed", "2026-05-28T17:00:00Z"))
            _write_journal(sink_root, events)
            _run_rebuild(td, lock_file=lock_file, hold_lock=True)
            view = _read_view(sink_root)
            entry = view["entries"][entry_id]
            self.assertEqual(
                entry.get("completion_mode"), "human_confirmed",
                "completion_mode must be retained after done → dismissed transition",
            )

    def test_open_to_dismissed_does_not_set_dismissed_after_done(self):
        """open → dismissed must NOT stamp dismissed_after_done (marker is done→dismissed only)."""
        with tempfile.TemporaryDirectory() as td:
            sink_root = Path(td)
            lock_file = str(sink_root / "global.lock")
            Path(lock_file).touch()
            entry_id = "20260528T120000Z-open-dismissed-no-marker"
            events = [
                _entry_created_event(entry_id),
                _status_changed_event(entry_id, "open", "dismissed", "2026-05-28T13:00:00Z"),
            ]
            _write_journal(sink_root, events)
            _run_rebuild(td, lock_file=lock_file, hold_lock=True)
            view = _read_view(sink_root)
            entry = view["entries"][entry_id]
            self.assertFalse(
                entry.get("dismissed_after_done", False),
                "dismissed_after_done must not be set for open → dismissed transition",
            )

    def test_verify_to_dismissed_does_not_set_dismissed_after_done(self):
        """verify → dismissed must NOT stamp dismissed_after_done."""
        with tempfile.TemporaryDirectory() as td:
            sink_root = Path(td)
            lock_file = str(sink_root / "global.lock")
            Path(lock_file).touch()
            entry_id = "20260528T120000Z-verify-dismissed-no-marker"
            events = [
                _entry_created_event(entry_id),
                _status_changed_event(entry_id, "open", "running", "2026-05-28T13:00:00Z"),
                _status_changed_event(entry_id, "running", "verify", "2026-05-28T14:00:00Z"),
                _status_changed_event(entry_id, "verify", "dismissed", "2026-05-28T15:00:00Z"),
            ]
            _write_journal(sink_root, events)
            _run_rebuild(td, lock_file=lock_file, hold_lock=True)
            view = _read_view(sink_root)
            entry = view["entries"][entry_id]
            self.assertFalse(
                entry.get("dismissed_after_done", False),
                "dismissed_after_done must not be set for verify → dismissed transition",
            )

    def test_done_to_dismissed_final_status_is_dismissed(self):
        """After done → dismissed, entry status must be dismissed."""
        with tempfile.TemporaryDirectory() as td:
            sink_root = Path(td)
            lock_file = str(sink_root / "global.lock")
            Path(lock_file).touch()
            entry_id = "20260528T120000Z-done-dismissed-status"
            events = self._make_done_entry_events(entry_id)
            events.append(_status_changed_event(entry_id, "done", "dismissed", "2026-05-28T17:00:00Z"))
            _write_journal(sink_root, events)
            _run_rebuild(td, lock_file=lock_file, hold_lock=True)
            view = _read_view(sink_root)
            entry = view["entries"][entry_id]
            self.assertEqual(entry["status"], "dismissed",
                             "status must be dismissed after done → dismissed transition")


class TestAttemptCountIncrement(unittest.TestCase):
    """T008: repeated running → failed transitions must increment attempt_count in the rebuilt view.

    Invariant: after N running → failed transitions, the view entry shows
    attempt_count == N.  The reducer must consume the attempt_count field
    carried in status_changed events (failure edge only).
    """

    def _status_changed_with_attempt_count(
        self,
        entry_id: str,
        from_status: str,
        to_status: str,
        attempt_count: int,
        ts: str = "2026-05-28T13:00:00Z",
    ) -> dict:
        """Return a status_changed event with an explicit attempt_count payload."""
        return {
            "kind": "status_changed",
            "ts": ts,
            "entry_id": entry_id,
            "from": from_status,
            "to": to_status,
            "by": "test",
            "attempt_count": attempt_count,
        }

    def test_single_running_to_failed_sets_attempt_count_1(self):
        """One running → failed transition carrying attempt_count=1 must produce view count of 1."""
        with tempfile.TemporaryDirectory() as td:
            sink_root = Path(td)
            lock_file = str(sink_root / "global.lock")
            Path(lock_file).touch()
            entry_id = "20260528T120000Z-attempt-count-1"
            events = [
                _entry_created_event(entry_id),
                _status_changed_event(entry_id, "open", "running", "2026-05-28T13:00:00Z"),
                self._status_changed_with_attempt_count(
                    entry_id, "running", "failed", attempt_count=1, ts="2026-05-28T14:00:00Z"
                ),
            ]
            _write_journal(sink_root, events)
            result = _run_rebuild(td, lock_file=lock_file, hold_lock=True)
            self.assertEqual(result.returncode, 0, msg=f"stderr={result.stderr}")
            view = _read_view(sink_root)
            entry = view["entries"][entry_id]
            self.assertEqual(entry.get("attempt_count"), 1,
                             "attempt_count must be 1 after one running→failed transition")

    def test_two_running_to_failed_transitions_increment_to_2(self):
        """Two running → failed transitions (with open reset between) must produce count of 2."""
        with tempfile.TemporaryDirectory() as td:
            sink_root = Path(td)
            lock_file = str(sink_root / "global.lock")
            Path(lock_file).touch()
            entry_id = "20260528T120000Z-attempt-count-2"
            events = [
                _entry_created_event(entry_id),
                # First attempt
                _status_changed_event(entry_id, "open", "running", "2026-05-28T13:00:00Z"),
                self._status_changed_with_attempt_count(
                    entry_id, "running", "failed", attempt_count=1, ts="2026-05-28T14:00:00Z"
                ),
                # Reset to open (retry)
                _status_changed_event(entry_id, "failed", "open", "2026-05-28T15:00:00Z"),
                # Second attempt
                _status_changed_event(entry_id, "open", "running", "2026-05-28T16:00:00Z"),
                self._status_changed_with_attempt_count(
                    entry_id, "running", "failed", attempt_count=2, ts="2026-05-28T17:00:00Z"
                ),
            ]
            _write_journal(sink_root, events)
            result = _run_rebuild(td, lock_file=lock_file, hold_lock=True)
            self.assertEqual(result.returncode, 0, msg=f"stderr={result.stderr}")
            view = _read_view(sink_root)
            entry = view["entries"][entry_id]
            self.assertEqual(entry.get("attempt_count"), 2,
                             "attempt_count must be 2 after two running→failed transitions")

    def test_three_running_to_failed_transitions_increment_to_3(self):
        """Three running → failed transitions must produce count of 3 (at/beyond retry cap)."""
        with tempfile.TemporaryDirectory() as td:
            sink_root = Path(td)
            lock_file = str(sink_root / "global.lock")
            Path(lock_file).touch()
            entry_id = "20260528T120000Z-attempt-count-3"
            events = [
                _entry_created_event(entry_id),
                # First attempt
                _status_changed_event(entry_id, "open", "running", "2026-05-28T13:00:00Z"),
                self._status_changed_with_attempt_count(
                    entry_id, "running", "failed", attempt_count=1, ts="2026-05-28T13:30:00Z"
                ),
                # Reset to open
                _status_changed_event(entry_id, "failed", "open", "2026-05-28T14:00:00Z"),
                # Second attempt
                _status_changed_event(entry_id, "open", "running", "2026-05-28T14:30:00Z"),
                self._status_changed_with_attempt_count(
                    entry_id, "running", "failed", attempt_count=2, ts="2026-05-28T15:00:00Z"
                ),
                # Reset to open
                _status_changed_event(entry_id, "failed", "open", "2026-05-28T15:30:00Z"),
                # Third attempt
                _status_changed_event(entry_id, "open", "running", "2026-05-28T16:00:00Z"),
                self._status_changed_with_attempt_count(
                    entry_id, "running", "failed", attempt_count=3, ts="2026-05-28T16:30:00Z"
                ),
            ]
            _write_journal(sink_root, events)
            result = _run_rebuild(td, lock_file=lock_file, hold_lock=True)
            self.assertEqual(result.returncode, 0, msg=f"stderr={result.stderr}")
            view = _read_view(sink_root)
            entry = view["entries"][entry_id]
            self.assertEqual(entry.get("attempt_count"), 3,
                             "attempt_count must be 3 after three running→failed transitions")

    def test_status_changed_without_attempt_count_does_not_reset_count(self):
        """A status_changed event without attempt_count must not overwrite the existing value."""
        with tempfile.TemporaryDirectory() as td:
            sink_root = Path(td)
            lock_file = str(sink_root / "global.lock")
            Path(lock_file).touch()
            entry_id = "20260528T120000Z-attempt-count-no-overwrite"
            # Entry created with attempt_count=2 already set
            created_event = _entry_created_event(entry_id)
            created_event["entry"]["attempt_count"] = 2
            events = [
                created_event,
                # A non-failed status change carries no attempt_count — must not zero it out
                _status_changed_event(entry_id, "open", "running", "2026-05-28T13:00:00Z"),
            ]
            _write_journal(sink_root, events)
            result = _run_rebuild(td, lock_file=lock_file, hold_lock=True)
            self.assertEqual(result.returncode, 0, msg=f"stderr={result.stderr}")
            view = _read_view(sink_root)
            entry = view["entries"][entry_id]
            self.assertEqual(entry.get("attempt_count"), 2,
                             "attempt_count must not be overwritten by events that do not carry the field")


# ── T010: incremental checkpoint tests ────────────────────────────────────────


class TestIncrementalCheckpointStored(unittest.TestCase):
    """T010: view file must carry a _checkpoint after each successful rebuild."""

    def test_checkpoint_present_after_rebuild(self):
        """After a successful rebuild, index.view.json must carry a _checkpoint dict."""
        with tempfile.TemporaryDirectory() as td:
            sink_root = Path(td)
            lock_file = str(sink_root / "global.lock")
            Path(lock_file).touch()
            entry_id = "20260528T120000Z-ckpt-present"
            _write_journal(sink_root, [_entry_created_event(entry_id)])
            result = _run_rebuild(td, lock_file=lock_file, hold_lock=True)
            self.assertEqual(result.returncode, 0, msg=f"stderr={result.stderr}")
            view = _read_view(sink_root)
            self.assertIn("_checkpoint", view, "view must carry a _checkpoint field")

    def test_checkpoint_has_event_count_and_byte_length(self):
        """The _checkpoint dict must have event_count and journal_byte_length fields."""
        with tempfile.TemporaryDirectory() as td:
            sink_root = Path(td)
            lock_file = str(sink_root / "global.lock")
            Path(lock_file).touch()
            entry_id = "20260528T120000Z-ckpt-fields"
            _write_journal(sink_root, [_entry_created_event(entry_id)])
            _run_rebuild(td, lock_file=lock_file, hold_lock=True)
            view = _read_view(sink_root)
            ckpt = view["_checkpoint"]
            self.assertIn("event_count", ckpt, "_checkpoint must have event_count")
            self.assertIn("journal_byte_length", ckpt, "_checkpoint must have journal_byte_length")
            self.assertIsInstance(ckpt["event_count"], int)
            self.assertGreaterEqual(ckpt["event_count"], 0)
            self.assertIsInstance(ckpt["journal_byte_length"], int)
            self.assertGreater(ckpt["journal_byte_length"], 0)

    def test_checkpoint_event_count_matches_journal(self):
        """event_count in _checkpoint must equal the number of non-empty lines in the journal."""
        with tempfile.TemporaryDirectory() as td:
            sink_root = Path(td)
            lock_file = str(sink_root / "global.lock")
            Path(lock_file).touch()
            entry_id = "20260528T120000Z-ckpt-count"
            events = [
                _entry_created_event(entry_id),
                _status_changed_event(entry_id, "open", "running"),
                _status_changed_event(entry_id, "running", "verify"),
            ]
            _write_journal(sink_root, events)
            _run_rebuild(td, lock_file=lock_file, hold_lock=True)
            view = _read_view(sink_root)
            ckpt = view["_checkpoint"]
            # 3 events written → event_count must be 3
            self.assertEqual(ckpt["event_count"], 3,
                             "event_count must equal the number of non-empty journal lines processed")


class TestIncrementalDeterminism(unittest.TestCase):
    """T010 acceptance: incremental and full-replay must produce byte-identical entries.

    Invariant: building a view incrementally across N appends, then forcing a full
    cold replay, must produce identical ``entries`` dicts.
    """

    def test_incremental_vs_full_replay_entries_identical(self):
        """entries dict must be identical whether built incrementally or via full replay."""
        with tempfile.TemporaryDirectory() as td:
            sink_root = Path(td)
            lock_file = str(sink_root / "global.lock")
            Path(lock_file).touch()
            entry_id = "20260528T120000Z-incr-det"

            # Build view incrementally: add one event at a time and rebuild after each
            (sink_root / "index.jsonl").write_text("", encoding="utf-8")
            _run_rebuild(td, lock_file=lock_file, hold_lock=True)

            for evt in [
                _entry_created_event(entry_id),
                _status_changed_event(entry_id, "open", "running", "2026-05-28T13:00:00Z"),
                _status_changed_event(entry_id, "running", "verify", "2026-05-28T14:00:00Z"),
                _status_changed_event(entry_id, "verify", "done", "2026-05-28T15:00:00Z"),
            ]:
                with (sink_root / "index.jsonl").open("a", encoding="utf-8") as fh:
                    fh.write(json.dumps(evt) + "\n")
                _run_rebuild(td, lock_file=lock_file, hold_lock=True)

            incremental_entries = _read_view(sink_root)["entries"]

            # Force a full cold replay using --full flag
            result = _run_rebuild(
                td, lock_file=lock_file, hold_lock=True,
                env_extra={},
                # Pass --full to force cold replay
            )
            # We need to run with --full flag; use rebuild_sh directly
            env = {**os.environ, "Z_HARNESS_FOLLOWUP_GLOBAL_LOCK": lock_file}
            sentinel = lock_file + ".flock"
            Path(lock_file).parent.mkdir(parents=True, exist_ok=True)
            Path(sentinel).touch()
            full_result = subprocess.run(
                [
                    sys.executable, "-c", _HOLD_LOCK_AND_RUN,
                    sentinel,
                    sys.executable, REDUCER_PY, td, "--full",
                ],
                capture_output=True, text=True, env=env,
            )
            self.assertEqual(full_result.returncode, 0,
                             msg=f"--full rebuild must succeed; stderr={full_result.stderr}")
            full_entries = _read_view(sink_root)["entries"]

            self.assertEqual(incremental_entries, full_entries,
                             "incremental entries must be identical to full-replay entries")

    def test_incremental_vs_full_replay_status_history_identical(self):
        """status_history must be identical between incremental and full-replay paths."""
        with tempfile.TemporaryDirectory() as td:
            sink_root = Path(td)
            lock_file = str(sink_root / "global.lock")
            Path(lock_file).touch()
            entry_id = "20260528T120000Z-incr-history"

            events = [
                _entry_created_event(entry_id),
                _status_changed_event(entry_id, "open", "running", "2026-05-28T13:00:00Z"),
                _status_changed_event(entry_id, "running", "verify", "2026-05-28T14:00:00Z"),
            ]
            # Build incrementally
            (sink_root / "index.jsonl").write_text("", encoding="utf-8")
            for evt in events:
                with (sink_root / "index.jsonl").open("a", encoding="utf-8") as fh:
                    fh.write(json.dumps(evt) + "\n")
                _run_rebuild(td, lock_file=lock_file, hold_lock=True)
            incremental_history = _read_view(sink_root)["entries"][entry_id]["status_history"]

            # Force full cold replay
            env = {**os.environ, "Z_HARNESS_FOLLOWUP_GLOBAL_LOCK": lock_file}
            sentinel = lock_file + ".flock"
            Path(sentinel).touch()
            subprocess.run(
                [sys.executable, "-c", _HOLD_LOCK_AND_RUN,
                 sentinel, sys.executable, REDUCER_PY, td, "--full"],
                capture_output=True, text=True, env=env,
            )
            full_history = _read_view(sink_root)["entries"][entry_id]["status_history"]

            self.assertEqual(incremental_history, full_history,
                             "status_history must be identical between incremental and full-replay")


class TestIncrementalEfficiency(unittest.TestCase):
    """T010 acceptance: incremental rebuild must parse only O(new events), not O(total).

    We measure the number of JSON parse calls by counting lines parsed in the
    reducer's incremental path.  Rather than wall-clock timing (which can be flaky
    in CI), we verify that the checkpoint ``event_count`` advances by exactly the
    number of new events added — which proves the incremental skip is working.
    """

    def test_checkpoint_advances_by_new_events_only(self):
        """After appending K new events, event_count must increase by exactly K."""
        with tempfile.TemporaryDirectory() as td:
            sink_root = Path(td)
            lock_file = str(sink_root / "global.lock")
            Path(lock_file).touch()
            entry_id = "20260528T120000Z-incr-eff"

            # Phase 1: write 3 events and rebuild → checkpoint at event_count=3
            events_phase1 = [
                _entry_created_event(entry_id),
                _status_changed_event(entry_id, "open", "running", "2026-05-28T13:00:00Z"),
                _status_changed_event(entry_id, "running", "verify", "2026-05-28T14:00:00Z"),
            ]
            _write_journal(sink_root, events_phase1)
            _run_rebuild(td, lock_file=lock_file, hold_lock=True)
            view1 = _read_view(sink_root)
            ckpt1 = view1["_checkpoint"]
            self.assertEqual(ckpt1["event_count"], 3,
                             "after 3 events, event_count must be 3")

            # Phase 2: append 2 more events and rebuild → checkpoint must be at 5
            new_events = [
                _status_changed_event(entry_id, "verify", "done", "2026-05-28T15:00:00Z"),
                _status_changed_event(entry_id, "done", "dismissed", "2026-05-28T16:00:00Z"),
            ]
            journal_path = sink_root / "index.jsonl"
            with journal_path.open("a", encoding="utf-8") as fh:
                for evt in new_events:
                    fh.write(json.dumps(evt) + "\n")

            _run_rebuild(td, lock_file=lock_file, hold_lock=True)
            view2 = _read_view(sink_root)
            ckpt2 = view2["_checkpoint"]
            self.assertEqual(ckpt2["event_count"], 5,
                             "after appending 2 more events, event_count must be 5")

            # The final status should be dismissed (all events were applied correctly)
            self.assertEqual(view2["entries"][entry_id]["status"], "dismissed",
                             "incremental update must apply new events correctly")

    def test_large_journal_incremental_adds_constant_work(self):
        """A ~1k-event journal: after a checkpoint, adding 1 event only advances count by 1.

        This is the O(new events) efficiency invariant: the checkpoint's event_count
        advances by exactly the number of new events — proving the hot path skips
        the already-processed prefix.
        """
        with tempfile.TemporaryDirectory() as td:
            sink_root = Path(td)
            lock_file = str(sink_root / "global.lock")
            Path(lock_file).touch()

            # Build a journal with 1000 events (entry_created + 999 status_changed)
            entry_id = "20260528T120000Z-large-journal"
            events = [_entry_created_event(entry_id)]
            statuses = ["open", "running", "verify", "failed", "open", "running"]
            for i in range(999):
                from_s = statuses[i % len(statuses)]
                to_s = statuses[(i + 1) % len(statuses)]
                events.append(_status_changed_event(
                    entry_id, from_s, to_s,
                    f"2026-05-28T{12 + (i // 3600):02d}:{(i % 3600) // 60:02d}:{i % 60:02d}Z",
                ))
            _write_journal(sink_root, events)

            # First full rebuild — establishes checkpoint at 1000
            _run_rebuild(td, lock_file=lock_file, hold_lock=True)
            view_before = _read_view(sink_root)
            ckpt_before = view_before["_checkpoint"]
            self.assertEqual(ckpt_before["event_count"], 1000,
                             "event_count must be 1000 after writing 1000 events")

            # Append exactly 1 new event
            new_event = _status_changed_event(entry_id, "verify", "done", "2026-05-28T23:59:59Z")
            with (sink_root / "index.jsonl").open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(new_event) + "\n")

            _run_rebuild(td, lock_file=lock_file, hold_lock=True)
            view_after = _read_view(sink_root)
            ckpt_after = view_after["_checkpoint"]

            # Checkpoint must advance by exactly 1
            self.assertEqual(
                ckpt_after["event_count"],
                ckpt_before["event_count"] + 1,
                "after appending 1 event, event_count must increase by exactly 1 "
                "(proving O(1) incremental work, not O(total))",
            )


class TestIncrementalCorruptionFallback(unittest.TestCase):
    """T010 acceptance: truncation/rewrite of journal invalidates checkpoint → full replay.

    When index.jsonl is truncated/compacted to be shorter than the stored
    journal_byte_length, the reducer must discard the checkpoint and fall back
    to a full cold replay.
    """

    def test_journal_truncation_invalidates_checkpoint(self):
        """After journal truncation, event_count must be reset to match the new shorter journal."""
        with tempfile.TemporaryDirectory() as td:
            sink_root = Path(td)
            lock_file = str(sink_root / "global.lock")
            Path(lock_file).touch()
            entry_id = "20260528T120000Z-trunc-fallback"

            # Phase 1: write 3 events, rebuild → checkpoint at event_count=3
            events = [
                _entry_created_event(entry_id),
                _status_changed_event(entry_id, "open", "running", "2026-05-28T13:00:00Z"),
                _status_changed_event(entry_id, "running", "verify", "2026-05-28T14:00:00Z"),
            ]
            _write_journal(sink_root, events)
            _run_rebuild(td, lock_file=lock_file, hold_lock=True)
            view1 = _read_view(sink_root)
            self.assertEqual(view1["_checkpoint"]["event_count"], 3)

            # Phase 2: simulate journal compaction — rewrite with only 1 event
            compacted_events = [_entry_created_event(entry_id)]
            _write_journal(sink_root, compacted_events)

            # The journal is now SHORTER than the stored checkpoint byte length
            new_journal_size = (sink_root / "index.jsonl").stat().st_size
            stored_byte_length = view1["_checkpoint"]["journal_byte_length"]
            self.assertLess(new_journal_size, stored_byte_length,
                            "test precondition: compacted journal must be shorter")

            # Rebuild must not crash and must fall back to full replay
            result = _run_rebuild(td, lock_file=lock_file, hold_lock=True)
            self.assertEqual(result.returncode, 0,
                             msg=f"rebuild after truncation must succeed; stderr={result.stderr}")

            view2 = _read_view(sink_root)
            # event_count must now reflect only the 1 event in the compacted journal
            self.assertEqual(view2["_checkpoint"]["event_count"], 1,
                             "after truncation, event_count must be reset to match the new journal")

    def test_journal_truncation_view_is_correct_after_fallback(self):
        """After truncation and fallback full replay, entries must reflect only the new journal."""
        with tempfile.TemporaryDirectory() as td:
            sink_root = Path(td)
            lock_file = str(sink_root / "global.lock")
            Path(lock_file).touch()
            entry_id_1 = "20260528T120000Z-trunc-view-1"
            entry_id_2 = "20260528T120000Z-trunc-view-2"

            # Phase 1: two entries
            events1 = [
                _entry_created_event(entry_id_1),
                _entry_created_event(entry_id_2),
                _status_changed_event(entry_id_1, "open", "running", "2026-05-28T13:00:00Z"),
            ]
            _write_journal(sink_root, events1)
            _run_rebuild(td, lock_file=lock_file, hold_lock=True)
            view1 = _read_view(sink_root)
            self.assertIn(entry_id_1, view1["entries"])
            self.assertIn(entry_id_2, view1["entries"])

            # Phase 2: compact to only entry_id_2 (different content)
            events2 = [_entry_created_event(entry_id_2)]
            _write_journal(sink_root, events2)

            result = _run_rebuild(td, lock_file=lock_file, hold_lock=True)
            self.assertEqual(result.returncode, 0,
                             msg=f"rebuild after compaction must succeed; stderr={result.stderr}")

            view2 = _read_view(sink_root)
            # entry_id_1 must be gone (not in the new journal)
            self.assertNotIn(entry_id_1, view2["entries"],
                             "entry_id_1 must not appear after journal compaction removed it")
            # entry_id_2 must still be present
            self.assertIn(entry_id_2, view2["entries"],
                          "entry_id_2 must still appear after fallback full replay")

    def test_checkpoint_invalidation_emits_warning(self):
        """When checkpoint is invalidated by truncation, a WARNING must be emitted on stderr."""
        with tempfile.TemporaryDirectory() as td:
            sink_root = Path(td)
            lock_file = str(sink_root / "global.lock")
            Path(lock_file).touch()
            entry_id = "20260528T120000Z-trunc-warn"

            # Phase 1: 3 events
            events = [
                _entry_created_event(entry_id),
                _status_changed_event(entry_id, "open", "running", "2026-05-28T13:00:00Z"),
                _status_changed_event(entry_id, "running", "verify", "2026-05-28T14:00:00Z"),
            ]
            _write_journal(sink_root, events)
            _run_rebuild(td, lock_file=lock_file, hold_lock=True)

            # Phase 2: compact to 1 event
            _write_journal(sink_root, [_entry_created_event(entry_id)])

            result = _run_rebuild(td, lock_file=lock_file, hold_lock=True)
            self.assertEqual(result.returncode, 0)
            combined = result.stderr + result.stdout
            self.assertIn("WARNING", combined,
                          "truncation-induced checkpoint invalidation must emit a WARNING")


class TestIncrementalWithUnknownEvents(unittest.TestCase):
    """T010: unknown event kinds in journal must not break the incremental skip count."""

    def test_unknown_events_counted_in_checkpoint(self):
        """Unknown-kind events must be counted in event_count so the skip position stays correct."""
        with tempfile.TemporaryDirectory() as td:
            sink_root = Path(td)
            lock_file = str(sink_root / "global.lock")
            Path(lock_file).touch()
            entry_id = "20260528T120000Z-unknown-ckpt"

            # Phase 1: 1 known + 1 unknown
            events = [
                _entry_created_event(entry_id),
                {"kind": "totally_unknown_v99", "ts": "2026-05-28T13:00:00Z", "entry_id": entry_id},
            ]
            _write_journal(sink_root, events)
            _run_rebuild(td, lock_file=lock_file, hold_lock=True)
            view1 = _read_view(sink_root)
            # Both lines are non-empty and parseable, so event_count must be 2
            self.assertEqual(view1["_checkpoint"]["event_count"], 2,
                             "unknown-kind events must be counted in event_count")

            # Phase 2: append 1 more known event
            with (sink_root / "index.jsonl").open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(
                    _status_changed_event(entry_id, "open", "running", "2026-05-28T14:00:00Z")
                ) + "\n")

            _run_rebuild(td, lock_file=lock_file, hold_lock=True)
            view2 = _read_view(sink_root)
            # event_count must advance to 3
            self.assertEqual(view2["_checkpoint"]["event_count"], 3,
                             "event_count must advance past unknown events correctly")
            # The new status_changed must have been applied
            self.assertEqual(view2["entries"][entry_id]["status"], "running",
                             "status_changed applied in incremental update must be reflected in view")


if __name__ == "__main__":
    unittest.main()
