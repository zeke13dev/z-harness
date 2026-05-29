"""
tests/test_followup_refresh_removes_staleness.py — end-to-end regression tests for the
refresh-clears-staleness path (H3 + H4 fix).

Before T003/T004:
  H3: entry_refreshed event was silently dropped by sink-view-reducer.py because
      'entry_refreshed' was not in KNOWN_EVENT_KINDS.  After a /z-followup-refresh,
      the view always retained the OLD hashes → entry stayed "stale" forever.

  H4: Blob-hash format mismatch.  create-time stored raw git hash-object SHA;
      the schema requires "sha256:<64 hex>"; the staleness checker (check_staleness)
      uses exact-equality comparison with hashlib.sha256 hashes.  Four formats
      existed across the codebase, none mutually consistent.  The fix picks ONE:
      "sha256:" + hashlib.sha256(file_bytes).hexdigest()

These tests drive the REAL sink-view-reducer.py subprocess and the Python-level
check_staleness() function to verify the full round-trip:

  create entry with sha256: hashes → modify file → recompute hashes →
  append entry_refreshed event → rebuild view → check_staleness() returns False

The staleness check is validated by calling check_staleness() directly (it is a
pure function — no subprocess needed), comparing the updated view hashes to the
current file content.
"""

from __future__ import annotations

import hashlib
import importlib.util
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

# The staleness check lives in sink-claim-helpers.py; import it directly
_CLAIM_HELPERS_PATH = REPO_ROOT / "scripts" / "sink-claim-helpers.py"


def _load_check_staleness():
    """Import check_staleness from sink-claim-helpers.py."""
    spec = importlib.util.spec_from_file_location(
        "sink_claim_helpers", str(_CLAIM_HELPERS_PATH)
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.check_staleness


def _sha256_file(path: Path) -> str:
    """Compute sha256:<hex> hash of file content — the canonical H4-fix format."""
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _run_reducer(sink_root: Path) -> subprocess.CompletedProcess:
    """Invoke sink-view-reducer.py as a real subprocess."""
    return subprocess.run(
        [sys.executable, REDUCER_PY, str(sink_root)],
        capture_output=True,
        text=True,
    )


# A tiny Python helper that holds an exclusive flock on the sentinel file before
# running the rebuild script (mirrors what the production callers do).
_HOLD_LOCK_AND_RUN = """
import fcntl, os, subprocess, sys
sentinel_path, *cmd = sys.argv[1:]
fd = os.open(sentinel_path, os.O_CREAT | os.O_RDWR, 0o644)
fcntl.flock(fd, fcntl.LOCK_EX)
try:
    r = subprocess.run(cmd)
    sys.exit(r.returncode)
finally:
    fcntl.flock(fd, fcntl.LOCK_UN)
    os.close(fd)
"""


def _run_rebuild(sink_root: Path, lock_file: Path) -> subprocess.CompletedProcess:
    """Run sink-view-rebuild.sh under a held flock (as production callers do)."""
    sentinel = str(lock_file) + ".flock"
    lock_file.parent.mkdir(parents=True, exist_ok=True)
    Path(sentinel).touch()
    cmd = [
        sys.executable, "-c", _HOLD_LOCK_AND_RUN,
        sentinel,
        "bash", REBUILD_SH, str(sink_root),
    ]
    env = {**os.environ, "Z_HARNESS_FOLLOWUP_GLOBAL_LOCK": str(lock_file)}
    return subprocess.run(cmd, capture_output=True, text=True, env=env)


def _write_journal(sink_root: Path, events: list[dict]) -> None:
    lines = "\n".join(json.dumps(e) for e in events)
    if events:
        lines += "\n"
    (sink_root / "index.jsonl").write_text(lines, encoding="utf-8")


def _append_to_journal(sink_root: Path, event: dict) -> None:
    journal = sink_root / "index.jsonl"
    with journal.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(event) + "\n")


def _read_view(sink_root: Path) -> dict:
    return json.loads((sink_root / "index.view.json").read_text(encoding="utf-8"))


def _entry_created_event(entry_id: str, file_path: str, file_hash: str) -> dict:
    """Build an entry_created event with sha256: blob hash (H4 canonical format)."""
    return {
        "kind": "entry_created",
        "ts": "2026-05-28T12:00:00Z",
        "entry": {
            "id": entry_id,
            "schema_version": 1,
            "priority": "P2",
            "name": "Test staleness entry",
            "status": "open",
            "sink": "project",
            "created_at": "2026-05-28T12:00:00Z",
            "created_by_run": "run-001",
            "recommended_command": "/z-do \"test\"",
            "capture_head": "a" * 40,
            "file_blob_hashes": {file_path: file_hash},
            "dir_blob_hashes": None,
            "auto_close_eligible": False,
            "cited_paths": [file_path],
            "status_history": [
                {"ts": "2026-05-28T12:00:00Z", "from": None, "to": "open",
                 "by": "scripts/sink-add.sh"}
            ],
        },
    }


def _entry_refreshed_event(entry_id: str, new_head: str, file_path: str, new_hash: str) -> dict:
    """Build an entry_refreshed event with new sha256: blob hash (H4 canonical format)."""
    return {
        "kind": "entry_refreshed",
        "ts": "2026-05-28T14:00:00Z",
        "entry_id": entry_id,
        "new_capture_head": new_head,
        "new_file_blob_hashes": {file_path: new_hash},
    }


# ── tests ──────────────────────────────────────────────────────────────────────

class TestEntryRefreshedEventAppliedByReducer(unittest.TestCase):
    """H3 regression: entry_refreshed was silently dropped by the reducer.

    Invariant: after reduce_journal processes an entry_refreshed event,
    the view's file_blob_hashes for the entry must reflect the NEW hashes.
    Failure class (H3): 'entry_refreshed' was not in KNOWN_EVENT_KINDS →
    reducer skipped it → view always retained the original stale hashes.
    """

    def test_reducer_applies_entry_refreshed_subprocess(self):
        """The REAL reducer subprocess must apply entry_refreshed and update hashes.

        This is the canonical H3 regression test: drives sink-view-reducer.py as a
        subprocess, NOT the Python function directly, to catch any CLI-level breakage.
        """
        entry_id = "20260528T120000Z-refresh-e2e"
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            sink_root = td_path

            # Create a temp file to track
            tracked_file = td_path / "tracked_file.txt"
            tracked_file.write_bytes(b"original content\n")
            original_hash = _sha256_file(tracked_file)

            # Write journal: entry_created with original hash
            _write_journal(sink_root, [
                _entry_created_event(entry_id, "tracked_file.txt", original_hash),
            ])

            # Run reducer to build initial view
            result = _run_reducer(sink_root)
            self.assertEqual(result.returncode, 0, f"initial rebuild failed: {result.stderr}")

            view = _read_view(sink_root)
            self.assertEqual(
                view["entries"][entry_id]["file_blob_hashes"]["tracked_file.txt"],
                original_hash,
                "Initial view must have the original hash",
            )

            # Modify the file (making it stale)
            tracked_file.write_bytes(b"modified content\n")
            new_hash = _sha256_file(tracked_file)
            self.assertNotEqual(new_hash, original_hash, "Modified file must have different hash")

            # Append entry_refreshed event with new hash
            new_head = "b" * 40
            _append_to_journal(sink_root, _entry_refreshed_event(
                entry_id, new_head, "tracked_file.txt", new_hash
            ))

            # Run reducer again — H3 regression: if entry_refreshed is dropped,
            # the view will still have the OLD hash after this call.
            result2 = _run_reducer(sink_root)
            self.assertEqual(result2.returncode, 0, f"refresh rebuild failed: {result2.stderr}")

            view2 = _read_view(sink_root)
            entry = view2["entries"][entry_id]

            self.assertEqual(
                entry["file_blob_hashes"]["tracked_file.txt"],
                new_hash,
                f"H3 regression: entry_refreshed must update file_blob_hashes in the view. "
                f"If still {original_hash!r}, the entry_refreshed event was dropped "
                f"(KNOWN_EVENT_KINDS missing 'entry_refreshed'). "
                f"Got: {entry.get('file_blob_hashes')}",
            )
            self.assertEqual(
                entry["capture_head"],
                new_head,
                f"capture_head must be updated to {new_head!r} by entry_refreshed",
            )

    def test_reducer_without_refresh_retains_stale_hash(self):
        """Negative control: without entry_refreshed, the stale hash persists in the view."""
        entry_id = "20260528T120000Z-no-refresh-stale"
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            sink_root = td_path

            tracked_file = td_path / "tracked_file2.txt"
            tracked_file.write_bytes(b"original content\n")
            original_hash = _sha256_file(tracked_file)

            _write_journal(sink_root, [
                _entry_created_event(entry_id, "tracked_file2.txt", original_hash),
            ])
            result = _run_reducer(sink_root)
            self.assertEqual(result.returncode, 0, f"rebuild failed: {result.stderr}")

            # Modify file but do NOT append entry_refreshed
            tracked_file.write_bytes(b"modified content\n")

            # Rebuild again — no refresh event → hash should still be the old one
            result2 = _run_reducer(sink_root)
            self.assertEqual(result2.returncode, 0, f"rebuild failed: {result2.stderr}")

            view = _read_view(sink_root)
            self.assertEqual(
                view["entries"][entry_id]["file_blob_hashes"]["tracked_file2.txt"],
                original_hash,
                "Without entry_refreshed, the view must retain the original (now stale) hash",
            )


class TestHashFormatCanonical(unittest.TestCase):
    """H4 regression: blob hash format must be 'sha256:<64 hex>' everywhere.

    Invariant: hashes in entry_refreshed events use 'sha256:' prefix + 64-hex from hashlib.
    Failure class (H4): create-time used raw git hash-object SHA (no prefix, 40 chars);
    refresh used 'sha256:' prefix; comparison used endswith() prefix check.
    After the fix, the format is consistently 'sha256:<64 hex>' everywhere.
    """

    def test_sha256_format_matches_schema(self):
        """Hashes produced by _sha256_file must match the schema pattern sha256:<64 hex>.

        This validates the H4 canonical format implementation used throughout the subsystem.
        """
        with tempfile.TemporaryDirectory() as td:
            test_file = Path(td) / "test.txt"
            test_file.write_bytes(b"test content\n")
            h = _sha256_file(test_file)
            self.assertTrue(h.startswith("sha256:"),
                            f"Hash must start with 'sha256:'; got {h!r}")
            hex_part = h[len("sha256:"):]
            self.assertEqual(len(hex_part), 64,
                             f"Hex part must be 64 chars; got {len(hex_part)}")
            self.assertTrue(all(c in "0123456789abcdef" for c in hex_part),
                            f"Hex part must be lowercase hex; got {hex_part!r}")

    def test_reducer_preserves_sha256_hash_in_view(self):
        """The reducer must store the sha256: hash exactly as given in entry_refreshed."""
        entry_id = "20260528T120000Z-hash-format"
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            sink_root = td_path

            tracked_file = td_path / "script.py"
            tracked_file.write_bytes(b"# original\n")
            original_hash = _sha256_file(tracked_file)

            _write_journal(sink_root, [
                _entry_created_event(entry_id, "script.py", original_hash),
            ])
            result = _run_reducer(sink_root)
            self.assertEqual(result.returncode, 0, f"stderr={result.stderr}")

            # Modify + refresh
            tracked_file.write_bytes(b"# modified\n")
            new_hash = _sha256_file(tracked_file)
            _append_to_journal(sink_root, _entry_refreshed_event(
                entry_id, "c" * 40, "script.py", new_hash,
            ))
            result2 = _run_reducer(sink_root)
            self.assertEqual(result2.returncode, 0, f"stderr={result2.stderr}")

            view = _read_view(sink_root)
            stored_hash = view["entries"][entry_id]["file_blob_hashes"]["script.py"]
            self.assertEqual(
                stored_hash, new_hash,
                f"Reducer must preserve exact sha256: hash from entry_refreshed. "
                f"Expected {new_hash!r}, got {stored_hash!r}",
            )
            # Verify the stored hash is in canonical format
            self.assertRegex(
                stored_hash, r"^sha256:[0-9a-f]{64}$",
                f"Stored hash must be in canonical 'sha256:<64hex>' format; got {stored_hash!r}",
            )


class TestStalenessClears(unittest.TestCase):
    """End-to-end: create entry → modify file → refresh → staleness clears.

    This is the full H3+H4 regression: after a refresh appends entry_refreshed,
    the reducer applies it, and check_staleness() must return (False, "") because
    the stored hashes now match the current file content.
    """

    def _make_sink_with_entry(
        self,
        sink_root: Path,
        entry_id: str,
        tracked_file: Path,
        rel_path: str,
        current_hash: str,
    ) -> None:
        """Write journal with entry_created event, rebuild view."""
        _write_journal(sink_root, [
            _entry_created_event(entry_id, rel_path, current_hash),
        ])
        result = _run_reducer(sink_root)
        assert result.returncode == 0, f"Initial reducer failed: {result.stderr}"

    def test_staleness_detected_before_refresh(self):
        """Before refresh, a modified file is detected as stale by check_staleness().

        Invariant: changing the file content after entry creation makes it stale.
        This is the pre-condition for the refresh test.
        """
        check_staleness = _load_check_staleness()

        entry_id = "20260528T120000Z-stale-before-refresh"
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            sink_root = td_path

            tracked_file = td_path / "file.txt"
            tracked_file.write_bytes(b"original\n")
            original_hash = _sha256_file(tracked_file)

            self._make_sink_with_entry(sink_root, entry_id, tracked_file, "file.txt", original_hash)

            # Modify file → should be stale
            tracked_file.write_bytes(b"modified\n")

            view = _read_view(sink_root)
            entry = view["entries"][entry_id]

            # check_staleness needs absolute paths; adjust entry to use abs path for the test
            # The staleness checker uses paths from file_blob_hashes as-is.
            # To test with a real file, we need to use the absolute path.
            entry_with_abs = dict(entry)
            entry_with_abs["file_blob_hashes"] = {str(tracked_file): original_hash}

            is_stale, reason = check_staleness(entry_with_abs, staleness_commit_window=9999)
            self.assertTrue(
                is_stale,
                f"Entry must be stale after modifying the tracked file. "
                f"check_staleness returned is_stale={is_stale}, reason={reason!r}",
            )

    def test_staleness_clears_after_refresh_event_applied(self):
        """After entry_refreshed is applied by the reducer, check_staleness() clears.

        This is the core H3+H4 regression test:
        1. Create entry with sha256: hash of original file
        2. Modify the file (now stale)
        3. Compute new sha256: hash
        4. Append entry_refreshed with new hash
        5. Run real reducer subprocess (the H3-fixed path)
        6. Extract entry from view
        7. check_staleness() must return (False, "")

        Failure class (H3): if entry_refreshed is dropped, the view still has the
        OLD hash → check_staleness() still returns True → entry never leaves stale.
        Failure class (H4): if hash format mismatches, the comparison fails even
        after the update.
        """
        check_staleness = _load_check_staleness()

        entry_id = "20260528T120000Z-staleness-clears-e2e"
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            sink_root = td_path

            tracked_file = td_path / "important.py"
            tracked_file.write_bytes(b"# original code\n")
            original_hash = _sha256_file(tracked_file)

            self._make_sink_with_entry(
                sink_root, entry_id, tracked_file, str(tracked_file), original_hash
            )

            # Modify file → stale
            tracked_file.write_bytes(b"# updated code\n")
            new_hash = _sha256_file(tracked_file)
            self.assertNotEqual(new_hash, original_hash)

            # Append entry_refreshed with new hash (the H3+H4 fix)
            new_head = "d" * 40
            _append_to_journal(sink_root, _entry_refreshed_event(
                entry_id, new_head, str(tracked_file), new_hash
            ))

            # Run the real reducer subprocess (H3 fix: entry_refreshed is now in KNOWN_EVENT_KINDS)
            result = _run_reducer(sink_root)
            self.assertEqual(
                result.returncode, 0,
                f"Reducer must succeed after appending entry_refreshed. "
                f"stderr={result.stderr!r}",
            )

            # Extract updated entry from view
            view = _read_view(sink_root)
            entry = view["entries"][entry_id]

            # Verify the new hash is in the view (H3 check)
            stored_hash = entry.get("file_blob_hashes", {}).get(str(tracked_file))
            self.assertEqual(
                stored_hash, new_hash,
                f"H3 regression: entry_refreshed must update file_blob_hashes. "
                f"Got {stored_hash!r}, expected {new_hash!r}",
            )

            # Now check_staleness must return (False, "") — staleness cleared
            is_stale, reason = check_staleness(entry, staleness_commit_window=9999)
            self.assertFalse(
                is_stale,
                f"H3+H4 regression: after entry_refreshed is applied and hashes updated, "
                f"check_staleness() must return False. "
                f"Got is_stale=True, reason={reason!r}. "
                f"stored_hash={stored_hash!r}, current_hash={_sha256_file(tracked_file)!r}",
            )

    def test_old_git_hash_format_causes_staleness(self):
        """Negative control: an entry with a raw git SHA (no 'sha256:' prefix) is always stale.

        Before the H4 fix, create-time stored a raw 40-char git hash-object SHA.
        check_staleness() now uses exact equality with sha256: hashes.
        A raw SHA will never match → entry appears permanently stale.
        This test documents the H4 failure mode.
        """
        check_staleness = _load_check_staleness()

        entry_id = "20260528T120000Z-old-git-hash-format"
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            sink_root = td_path

            tracked_file = td_path / "legacy.txt"
            tracked_file.write_bytes(b"legacy content\n")

            # Simulate pre-H4 format: raw 40-char hex (no 'sha256:' prefix)
            old_format_hash = "a" * 40  # git hash-object SHA format (40 hex chars, no prefix)

            _write_journal(sink_root, [
                _entry_created_event(entry_id, str(tracked_file), old_format_hash),
            ])
            result = _run_reducer(sink_root)
            self.assertEqual(result.returncode, 0, f"stderr={result.stderr}")

            view = _read_view(sink_root)
            entry = view["entries"][entry_id]

            # An entry with old-format hash (no sha256: prefix) will appear stale
            # because file_content_hash() returns 'sha256:...', not 'a'*40.
            # is_stale should be True since old_format_hash != current sha256: hash.
            is_stale, reason = check_staleness(entry, staleness_commit_window=9999)
            self.assertTrue(
                is_stale,
                f"An entry with old-format (raw git SHA, no sha256: prefix) hash must be "
                f"considered stale — it can never match the canonical sha256: format. "
                f"This documents the H4 failure mode. is_stale={is_stale}, reason={reason!r}",
            )


if __name__ == "__main__":
    unittest.main()
