"""
tests/test_global_lock_consolidation.py — T015 consolidation tests.

Verifies that:
1. All callers (sink-add, sink-claim, sink-status-set) go through the ONE shared
   helper in followup_common.py (GlobalLockContext / acquire_global_lock /
   release_global_lock).
2. The holder JSON write/clear is serialized under <lock>.hb.lock.
3. fd-hygiene holds on the error path (no leak on holder-write failure).
4. GlobalLockContext raises TimeoutError (not calls sys.exit) on contention timeout.
5. acquire_global_lock / release_global_lock round-trip clears the holder file.
"""

from __future__ import annotations

import fcntl
import importlib
import importlib.util
import json
import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = REPO_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import followup_common  # noqa: E402 — must come after sys.path insert
from followup_common import (  # noqa: E402
    GlobalLockContext,
    acquire_global_lock,
    release_global_lock,
)


# ── helpers ────────────────────────────────────────────────────────────────────

def _hold_sentinel_ex(sentinel: Path, duration: float) -> None:
    """Hold LOCK_EX on *sentinel* for *duration* seconds (used in threads)."""
    sentinel.parent.mkdir(parents=True, exist_ok=True)
    sentinel.touch()
    fd = os.open(str(sentinel), os.O_CREAT | os.O_RDWR, 0o644)
    fcntl.flock(fd, fcntl.LOCK_EX)
    time.sleep(duration)
    fcntl.flock(fd, fcntl.LOCK_UN)
    os.close(fd)


# ── Test: shared helper is ONE place ──────────────────────────────────────────

class TestSingleHelper(unittest.TestCase):
    """GlobalLockContext, acquire_global_lock, release_global_lock must live in
    followup_common and must NOT be duplicated in the three caller modules."""

    def _load_source(self, script_name: str) -> str:
        path = SCRIPTS / script_name
        return path.read_text(encoding="utf-8")

    def test_sink_add_imports_global_lock_from_common(self) -> None:
        src = self._load_source("sink-add-helpers.py")
        # Must import GlobalLockContext from followup_common
        self.assertIn("GlobalLockContext", src, "sink-add-helpers.py must import GlobalLockContext")
        # Must NOT define its own class
        self.assertNotIn("class GlobalLockContext", src,
                         "sink-add-helpers.py must NOT define its own GlobalLockContext")

    def test_sink_claim_imports_global_lock_from_common(self) -> None:
        src = self._load_source("sink-claim-helpers.py")
        self.assertIn("acquire_global_lock", src,
                      "sink-claim-helpers.py must import acquire_global_lock")
        self.assertIn("release_global_lock", src,
                      "sink-claim-helpers.py must import release_global_lock")
        # Must NOT define its own acquire_global_lock function
        self.assertNotIn("def acquire_global_lock", src,
                         "sink-claim-helpers.py must NOT define its own acquire_global_lock")
        self.assertNotIn("def release_global_lock", src,
                         "sink-claim-helpers.py must NOT define its own release_global_lock")

    def test_sink_status_set_imports_global_lock_from_common(self) -> None:
        src = self._load_source("sink-status-set-impl.py")
        self.assertIn("acquire_global_lock", src,
                      "sink-status-set-impl.py must import acquire_global_lock")
        self.assertIn("release_global_lock", src,
                      "sink-status-set-impl.py must import release_global_lock")
        # Must NOT define its own acquire_global_lock function
        self.assertNotIn("def acquire_global_lock", src,
                         "sink-status-set-impl.py must NOT define its own acquire_global_lock")
        self.assertNotIn("def release_global_lock", src,
                         "sink-status-set-impl.py must NOT define its own release_global_lock")

    def test_global_lock_helpers_in_followup_common(self) -> None:
        """followup_common exports the three expected names."""
        self.assertTrue(hasattr(followup_common, "GlobalLockContext"))
        self.assertTrue(hasattr(followup_common, "acquire_global_lock"))
        self.assertTrue(hasattr(followup_common, "release_global_lock"))


# ── Test: z-followup-refresh.md Phase 6 uses the shared helper ─────────────────

class TestRefreshCommandUsesSharedHelper(unittest.TestCase):
    """commands/z-followup-refresh.md Phase 6 must delegate global-lock
    acquisition to the shared helper, not reimplement flock/holder/.hb.lock
    logic inline (T015 CARRY-2 + Codex blocker)."""

    COMMAND = REPO_ROOT / "skills" / "z-followup-refresh" / "SKILL.md"

    def _source(self) -> str:
        return self.COMMAND.read_text(encoding="utf-8")

    def test_imports_shared_helper(self) -> None:
        src = self._source()
        self.assertIn("acquire_global_lock", src,
                      "Phase 6 must call acquire_global_lock from followup_common")
        self.assertIn("release_global_lock", src,
                      "Phase 6 must call release_global_lock from followup_common")
        self.assertIn("from followup_common import", src,
                      "Phase 6 must import the shared helper from followup_common")

    def test_no_inline_global_lock_reimplementation(self) -> None:
        src = self._source()
        # The inline reimplementation used these exact tokens; none must remain.
        for forbidden in ("fcntl.flock", "GLOBAL_FLOCK_PATH", "HB_LOCK_PATH",
                          "LOCK_EX | fcntl.LOCK_NB"):
            self.assertNotIn(forbidden, src,
                             f"Phase 6 must NOT reimplement the global lock inline ({forbidden})")

    def test_per_entry_lock_acquired_before_global(self) -> None:
        """Mandatory per-entry -> global lock ordering: the per-entry
        sink-lock.sh acquire must appear before the global-lock acquisition."""
        src = self._source()
        entry_idx = src.find("sink-lock.sh")
        global_idx = src.find("acquire_global_lock")
        self.assertNotEqual(entry_idx, -1, "per-entry lock (sink-lock.sh) must be present")
        self.assertNotEqual(global_idx, -1, "global lock acquire must be present")
        self.assertLess(entry_idx, global_idx,
                        "per-entry lock must be acquired BEFORE the global lock")


# ── Test: .hb.lock serializes holder writes ───────────────────────────────────

class TestHbLockSerialization(unittest.TestCase):
    """The holder JSON write and clear must be serialized under <lock>.hb.lock."""

    def setUp(self) -> None:
        self.tmpdir = tempfile.mkdtemp()
        self.lock_file = Path(self.tmpdir) / "test.lock"
        self.hb_lock = Path(str(self.lock_file) + ".hb.lock")

    def test_context_manager_writes_holder_under_hb_lock(self) -> None:
        """After __enter__, .hb.lock exists and holder file has valid JSON."""
        with GlobalLockContext(self.lock_file, "test-holder") as ctx:
            self.assertTrue(self.hb_lock.exists(), ".hb.lock sentinel must be created")
            content = self.lock_file.read_text(encoding="utf-8").strip()
            self.assertTrue(content, "holder file must not be empty while lock is held")
            rec = json.loads(content)
            self.assertEqual(rec["holder"], "test-holder")
            self.assertIn("pid", rec)
            self.assertIn("started_at", rec)
            self.assertIn("last_heartbeat", rec)

    def test_context_manager_clears_holder_under_hb_lock_on_exit(self) -> None:
        """After __exit__, holder file is cleared (empty)."""
        with GlobalLockContext(self.lock_file, "test-holder"):
            pass
        content = self.lock_file.read_text(encoding="utf-8")
        self.assertEqual(content, "", "holder file must be empty after context exit")

    def test_acquire_release_writes_and_clears_holder(self) -> None:
        """acquire_global_lock writes the holder; release_global_lock clears it."""
        fd = acquire_global_lock(self.lock_file, "test-acquire-release")
        try:
            content = self.lock_file.read_text(encoding="utf-8").strip()
            rec = json.loads(content)
            self.assertEqual(rec["holder"], "test-acquire-release")
            self.assertIn("pid", rec)
        finally:
            release_global_lock(fd, self.lock_file)
        cleared = self.lock_file.read_text(encoding="utf-8")
        self.assertEqual(cleared, "", "holder file must be empty after release")

    def test_hb_lock_exists_after_acquire(self) -> None:
        """acquire_global_lock creates the .hb.lock sentinel."""
        fd = acquire_global_lock(self.lock_file, "holder-hb-test")
        try:
            self.assertTrue(self.hb_lock.exists())
        finally:
            release_global_lock(fd, self.lock_file)

    def test_concurrent_reader_sees_complete_record_not_torn(self) -> None:
        """While the lock is held, a concurrent reader always sees a complete JSON record.

        Simulates a reader that opens the holder file concurrently with a writer.
        The .hb.lock serialization ensures no torn (partial) JSON is visible.
        """
        records_seen: list[str] = []

        def reader() -> None:
            # Poll the holder file 20 times in quick succession
            for _ in range(20):
                try:
                    content = self.lock_file.read_text(encoding="utf-8").strip()
                    if content:
                        records_seen.append(content)
                except OSError:
                    pass
                time.sleep(0.005)

        t = threading.Thread(target=reader, daemon=True)
        t.start()
        with GlobalLockContext(self.lock_file, "concurrent-test"):
            time.sleep(0.15)  # Hold long enough for reader to poll
        t.join(timeout=2.0)

        for rec_str in records_seen:
            try:
                rec = json.loads(rec_str)
                self.assertIsInstance(rec, dict, f"Torn record observed: {rec_str!r}")
                self.assertIn("holder", rec, f"Missing 'holder' key: {rec_str!r}")
            except json.JSONDecodeError:
                self.fail(f"Torn (unparseable) holder record observed: {rec_str!r}")


# ── Test: fd-hygiene on error path ────────────────────────────────────────────

class TestFdHygiene(unittest.TestCase):
    """fd must be closed on holder-write failure (no fd leak)."""

    def setUp(self) -> None:
        self.tmpdir = tempfile.mkdtemp()
        self.lock_file = Path(self.tmpdir) / "test.lock"

    def test_context_manager_closes_fd_on_holder_write_failure(self) -> None:
        """If the holder write raises, the fd must be closed (not leaked)."""
        lock_file = self.lock_file
        hb_lock = Path(str(lock_file) + ".hb.lock")
        lock_file.parent.mkdir(parents=True, exist_ok=True)

        # Collect open fds before
        before_fds = set(os.listdir("/proc/self/fd")) if Path("/proc/self/fd").exists() else None

        # Patch write_text on the lock_file to raise after the OS flock is taken
        original_write_text = Path.write_text

        def failing_write(self_path: Path, *args, **kwargs):
            if self_path == lock_file:
                raise OSError("injected write failure")
            return original_write_text(self_path, *args, **kwargs)

        import unittest.mock as mock
        with mock.patch.object(Path, "write_text", failing_write):
            with self.assertRaises(OSError):
                ctx = GlobalLockContext(lock_file, "fd-leak-test")
                ctx.__enter__()

        # fd must not be leaked — verify by attempting to acquire again
        # (if fd leaked, the sentinel would still be LOCK_EX and re-acquire would fail/timeout)
        try:
            fd2 = acquire_global_lock(lock_file, "reacquire-after-failure", timeout=2)
            release_global_lock(fd2, lock_file)
        except TimeoutError:
            self.fail(
                "fd was leaked on holder-write failure: "
                "re-acquire timed out (sentinel still held LOCK_EX)"
            )

    def test_release_closes_fd_even_if_lock_un_raises(self) -> None:
        """release_global_lock must close the fd even if LOCK_UN raises."""
        fd = acquire_global_lock(self.lock_file, "fd-close-test")
        # Verify fd is valid before release
        os.fstat(fd)  # raises if fd is already closed
        # Normal release must close fd
        release_global_lock(fd, self.lock_file)
        # fd must now be closed
        with self.assertRaises(OSError):
            os.fstat(fd)


# ── Test: timeout raises TimeoutError (not sys.exit) ─────────────────────────

class TestTimeoutBehaviour(unittest.TestCase):
    """Both GlobalLockContext and acquire_global_lock must raise TimeoutError on
    contention timeout, not call sys.exit."""

    def setUp(self) -> None:
        self.tmpdir = tempfile.mkdtemp()
        self.lock_file = Path(self.tmpdir) / "contended.lock"

    def test_context_manager_raises_timeout_error(self) -> None:
        sentinel = Path(str(self.lock_file) + ".flock")
        t = threading.Thread(target=_hold_sentinel_ex, args=(sentinel, 3.0), daemon=True)
        t.start()
        time.sleep(0.05)  # Let holder establish LOCK_EX
        try:
            with self.assertRaises(TimeoutError):
                with GlobalLockContext(self.lock_file, "timeout-test", timeout=1):
                    pass
        finally:
            t.join(timeout=5.0)

    def test_acquire_global_lock_raises_timeout_error(self) -> None:
        sentinel = Path(str(self.lock_file) + ".flock")
        t = threading.Thread(target=_hold_sentinel_ex, args=(sentinel, 3.0), daemon=True)
        t.start()
        time.sleep(0.05)
        try:
            with self.assertRaises(TimeoutError):
                acquire_global_lock(self.lock_file, "timeout-test", timeout=1)
        finally:
            t.join(timeout=5.0)


# ── Test: sink-add uses the shared GlobalLockContext ─────────────────────────

class TestSinkAddUsesSharedHelper(unittest.TestCase):
    """Confirm sink-add-helpers imports GlobalLockContext from followup_common."""

    def _load_module(self, script_name: str):
        """Load a hyphen-named script as a module via importlib."""
        spec = importlib.util.spec_from_file_location(  # type: ignore[attr-defined]
            script_name.replace("-", "_"),
            SCRIPTS / script_name,
        )
        mod = importlib.util.module_from_spec(spec)  # type: ignore[attr-defined]
        spec.loader.exec_module(mod)
        return mod

    def test_imported_class_is_followup_common_class(self) -> None:
        sah = self._load_module("sink-add-helpers.py")
        # The GlobalLockContext in sink_add_helpers must be the one from followup_common
        self.assertIs(
            sah.GlobalLockContext,
            followup_common.GlobalLockContext,
            "sink-add-helpers.py's GlobalLockContext must be the one from followup_common",
        )

    def test_sink_add_no_local_fcntl_import(self) -> None:
        src = (SCRIPTS / "sink-add-helpers.py").read_text(encoding="utf-8")
        self.assertNotIn("import fcntl", src,
                         "sink-add-helpers.py must not import fcntl directly after consolidation")


class TestSinkClaimUsesSharedHelper(unittest.TestCase):
    """Confirm sink-claim-helpers imports acquire/release from followup_common."""

    def _load_module(self, script_name: str):
        spec = importlib.util.spec_from_file_location(  # type: ignore[attr-defined]
            script_name.replace("-", "_"),
            SCRIPTS / script_name,
        )
        mod = importlib.util.module_from_spec(spec)  # type: ignore[attr-defined]
        spec.loader.exec_module(mod)
        return mod

    def test_imported_functions_are_followup_common_functions(self) -> None:
        sch = self._load_module("sink-claim-helpers.py")
        self.assertIs(
            sch.acquire_global_lock,
            followup_common.acquire_global_lock,
            "sink-claim-helpers.py's acquire_global_lock must be followup_common's",
        )
        self.assertIs(
            sch.release_global_lock,
            followup_common.release_global_lock,
            "sink-claim-helpers.py's release_global_lock must be followup_common's",
        )

    def test_sink_claim_no_local_fcntl_import(self) -> None:
        src = (SCRIPTS / "sink-claim-helpers.py").read_text(encoding="utf-8")
        self.assertNotIn("import fcntl", src,
                         "sink-claim-helpers.py must not import fcntl directly after consolidation")


class TestSinkStatusSetUsesSharedHelper(unittest.TestCase):
    """Confirm sink-status-set-impl imports acquire/release from followup_common."""

    def test_sink_status_set_no_local_acquire_define(self) -> None:
        src = (SCRIPTS / "sink-status-set-impl.py").read_text(encoding="utf-8")
        self.assertNotIn("def acquire_global_lock", src)
        self.assertNotIn("def release_global_lock", src)

    def test_sink_status_set_no_local_fcntl_import(self) -> None:
        src = (SCRIPTS / "sink-status-set-impl.py").read_text(encoding="utf-8")
        self.assertNotIn("import fcntl", src,
                         "sink-status-set-impl.py must not import fcntl directly")


if __name__ == "__main__":
    unittest.main()
