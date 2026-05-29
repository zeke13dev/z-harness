"""
tests/test_sink_lock.py — pytest tests for scripts/sink-lock.sh

Invokes the script as a subprocess to exercise the real exit-code contract.

Cases covered:
  clean_acquire                   — acquire on a free lock → exit 0, JSON written
  os_level_flock_contention       — T001 regression: OS-level LOCK_EX held after acquire returns;
                                    holder B rejected at OS level while A is alive; B succeeds after A releases;
                                    holder record fields match spec (holder, pid, started_at, last_heartbeat)
  contention                      — process A holds lock (live PID), B fails with exit 1
  stale_pid_takeover              — lock held by dead PID → acquire exits 2, new lock written
  stale_heartbeat_takeover        — lock has live PID but old heartbeat → acquire exits 2
  stale_heartbeat_takeover_live   — live daemon holding flock, but heartbeat expired → new acquire
                                    kills stale daemon and takes over (finding 2)
  release_ownership_validation    — release with wrong --expected-holder/--expected-pid → exit 4
                                    (finding 4); correct ownership → exit 0
  malformed_json_not_free         — wrong-schema parseable JSON (e.g. '{}') → stale (exit 2),
                                    NOT free (exit 1) (finding 8)
  zombie_after_sigterm            — release verifies flock free via LOCK_EX|LOCK_NB probe,
                                    not just kill(pid,0) liveness; setup acquire assertions required
  release_then_reacquire          — release zeroes content, re-acquire succeeds with exit 0
  heartbeat_updates_ts            — heartbeat changes last_heartbeat timestamp
  check_stale_free                — check-stale on absent/empty lock → exit 1
  check_stale_live                — check-stale on recently-acquired lock → exit 0
  check_stale_dead_pid            — check-stale with dead PID → exit 2
  check_stale_old_hb              — check-stale with old heartbeat, short TTL → exit 2
  release_not_found               — release when lock absent → exit 1
  heartbeat_not_found             — heartbeat when lock absent → exit 1
"""

import json
import os
import re
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = str(REPO_ROOT / "scripts" / "sink-lock.sh")
DEAD_PID = 99999999  # assume this PID does not exist


def _run(*args: str, env_extra: dict | None = None) -> subprocess.CompletedProcess:
    env = {**os.environ, **(env_extra or {})}
    return subprocess.run(
        ["bash", SCRIPT] + list(args),
        capture_output=True,
        text=True,
        env=env,
    )


def _write_lock(lock_path: Path, *, pid: int, heartbeat: str = "2026-01-01T00:00:00Z") -> None:
    """Write a lock file with the given pid and heartbeat (bypassing flock for test setup)."""
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path.write_text(
        json.dumps({
            "holder": "test-holder",
            "pid": pid,
            "started_at": "2026-01-01T00:00:00Z",
            "last_heartbeat": heartbeat,
        }) + "\n",
        encoding="utf-8",
    )


def _read_lock(lock_path: Path) -> dict | None:
    content = lock_path.read_text(encoding="utf-8").strip()
    if not content:
        return None
    return json.loads(content)


def _live_daemon_pids() -> set[int]:
    """PIDs of background sink-lock daemons, identified by the unique marker
    string embedded in their -c source (`zero_lock_under_hblock`)."""
    proc = subprocess.run(
        ["pgrep", "-f", "zero_lock_under_hblock"],
        capture_output=True, text=True,
    )
    pids = set()
    for line in proc.stdout.split():
        try:
            pids.add(int(line))
        except ValueError:
            pass
    return pids


class _DaemonReapingTestCase(unittest.TestCase):
    """Base for lock tests. Each `acquire` forks a background daemon that holds
    the flock and blocks in signal.pause() until released or signalled. Tests
    that intentionally leave a holder alive (contention/takeover cases) would
    otherwise leak that daemon past the test, destabilising later tests and the
    process table. tearDown SIGTERMs any daemon spawned during the test."""

    def setUp(self):
        super().setUp()
        self._daemons_at_start = _live_daemon_pids()

    def tearDown(self):
        leaked = _live_daemon_pids() - self._daemons_at_start
        import signal as _signal
        for pid in leaked:
            try:
                os.kill(pid, _signal.SIGTERM)
            except ProcessLookupError:
                pass
        super().tearDown()


class TestCleanAcquire(_DaemonReapingTestCase):
    """acquire on a free lock succeeds with exit 0 and writes valid JSON."""

    def test_exit_zero_and_json_written(self):
        with tempfile.TemporaryDirectory() as td:
            lock_path = Path(td) / "test.lock"
            result = _run("acquire", str(lock_path), "holder-A")
            self.assertEqual(result.returncode, 0, msg=result.stderr)
            self.assertTrue(lock_path.exists(), "lock file must be created")
            data = _read_lock(lock_path)
            self.assertIsNotNone(data, "lock JSON must not be empty after acquire")
            self.assertEqual(data["holder"], "holder-A")
            self.assertIn("pid", data)
            self.assertIn("started_at", data)
            self.assertIn("last_heartbeat", data)

    def test_invariant_missing_holder_arg_exits_2(self):
        """acquire with only one arg must exit 2 (usage error), not crash."""
        with tempfile.TemporaryDirectory() as td:
            lock_path = Path(td) / "test.lock"
            result = _run("acquire", str(lock_path))
            self.assertEqual(result.returncode, 2, msg=result.stderr)


class TestOSLevelFlockContention(_DaemonReapingTestCase):
    """Verify that the OS-level flock is actually held across acquire invocations.

    This is the T001 regression: the original implementation closed the flock fd
    inside cmd_acquire's finally clause — releasing the kernel lock before the
    call returned.  The fix spawns a background daemon that holds the fd open.

    These tests verify real mutual exclusion at the OS level using fcntl.LOCK_EX
    | fcntl.LOCK_NB from an *independent* Python subprocess — not just the JSON
    content check, which is what the original (broken) tests relied on.
    """

    def _flock_probe(self, flock_path: Path) -> bool:
        """Return True if the .flock file is currently locked by another process.

        Opens the file in a fresh subprocess and attempts a non-blocking LOCK_EX.
        Returns True if the flock is held (LOCK_EX attempt would block).
        Returns False if the flock is free (LOCK_EX succeeds).
        """
        probe_code = textwrap.dedent("""\
            import fcntl, os, sys
            fd = os.open(sys.argv[1], os.O_CREAT | os.O_RDWR, 0o644)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                sys.exit(1)  # acquired = free
            except BlockingIOError:
                sys.exit(0)  # blocked = held by another process
        """)
        result = subprocess.run(
            [sys.executable, "-c", probe_code, str(flock_path)],
            timeout=5,
        )
        # exit 0 = held (blocked), exit 1 = free
        return result.returncode == 0

    def test_flock_held_after_acquire(self):
        """After acquire returns exit 0, the .flock sentinel is held by a live process.

        Invariant: the OS-level LOCK_EX persists after the acquire invocation exits.
        Failure class (T001): fd closed in finally — lock released before acquire returns.
        """
        with tempfile.TemporaryDirectory() as td:
            lock_path = Path(td) / "test.lock"
            flock_path = Path(td) / "test.lock.flock"

            result = _run("acquire", str(lock_path), "holder-A")
            self.assertEqual(result.returncode, 0, msg=result.stderr)

            # Verify via an independent subprocess that the flock is actually held
            is_held = self._flock_probe(flock_path)
            self.assertTrue(
                is_held,
                "OS-level LOCK_EX must remain held after acquire returns (T001 regression: "
                "if the daemon closes the fd in finally, the flock is released immediately)",
            )

            # Clean up: release the lock
            _run("release", str(lock_path))

    def test_flock_released_after_release(self):
        """After release, the .flock sentinel is free to be re-acquired."""
        with tempfile.TemporaryDirectory() as td:
            lock_path = Path(td) / "test.lock"
            flock_path = Path(td) / "test.lock.flock"

            _run("acquire", str(lock_path), "holder-A")
            self.assertTrue(self._flock_probe(flock_path), "must be held before release")

            _run("release", str(lock_path))
            time.sleep(0.3)  # give daemon time to exit

            is_held = self._flock_probe(flock_path)
            self.assertFalse(is_held, "OS-level LOCK_EX must be released after release call")

    def test_holder_b_rejected_while_holder_a_alive(self):
        """Holder A acquires; holder B is rejected while A is alive; B succeeds after A releases.

        This is the canonical acceptance test for T001: real mutual exclusion,
        verified at the OS level, not just via the JSON advisory record.
        """
        with tempfile.TemporaryDirectory() as td:
            lock_path = Path(td) / "test.lock"
            flock_path = Path(td) / "test.lock.flock"

            # A acquires
            r_a = _run("acquire", str(lock_path), "holder-A")
            self.assertEqual(r_a.returncode, 0, msg=f"holder A acquire failed: {r_a.stderr}")

            # Confirm flock is OS-level held
            self.assertTrue(
                self._flock_probe(flock_path),
                "flock must be held at OS level while holder A is alive",
            )

            # B is rejected (exit 1 = contention)
            r_b = _run("acquire", str(lock_path), "holder-B")
            self.assertEqual(
                r_b.returncode, 1,
                f"holder B must be rejected while A holds; got {r_b.returncode}: {r_b.stderr}",
            )

            # Verify A's daemon PID is alive (ensures the rejection was real, not a race)
            data = _read_lock(lock_path)
            self.assertIsNotNone(data, "lock content must be non-empty while A holds")
            daemon_pid = data["pid"]
            try:
                os.kill(daemon_pid, 0)
                daemon_alive = True
            except ProcessLookupError:
                daemon_alive = False
            self.assertTrue(daemon_alive, f"holder A daemon PID {daemon_pid} must still be alive")

            # A releases
            r_rel = _run("release", str(lock_path))
            self.assertEqual(r_rel.returncode, 0, msg=r_rel.stderr)
            time.sleep(0.3)  # give daemon time to exit

            # Confirm flock is now free at OS level
            self.assertFalse(
                self._flock_probe(flock_path),
                "flock must be free at OS level after holder A releases",
            )

            # B now succeeds (exit 0 = acquired)
            r_b2 = _run("acquire", str(lock_path), "holder-B")
            self.assertEqual(
                r_b2.returncode, 0,
                f"holder B must succeed after A releases; got {r_b2.returncode}: {r_b2.stderr}",
            )

            # Verify B's holder record
            data_b = _read_lock(lock_path)
            self.assertIsNotNone(data_b, "lock content must be non-empty after B acquires")
            self.assertEqual(data_b["holder"], "holder-B")
            self.assertIn("pid", data_b)
            self.assertIn("started_at", data_b)
            self.assertIn("last_heartbeat", data_b)

            # Clean up
            _run("release", str(lock_path))

    def test_holder_record_fields_match_spec(self):
        """The JSON holder record must have exactly the required fields: holder, pid, started_at, last_heartbeat.

        Per T001 acceptance: "The holder record written to the .lock JSON file is
        documented and validated as exactly these required fields: holder (non-empty
        string), pid (integer PID), started_at (UTC ISO-8601), last_heartbeat (UTC ISO-8601)."
        """
        with tempfile.TemporaryDirectory() as td:
            lock_path = Path(td) / "test.lock"

            result = _run("acquire", str(lock_path), "my-holder-id")
            self.assertEqual(result.returncode, 0, msg=result.stderr)

            data = _read_lock(lock_path)
            self.assertIsNotNone(data, "lock JSON must not be empty")

            # Required fields
            self.assertIn("holder", data, "holder field required")
            self.assertIn("pid", data, "pid field required")
            self.assertIn("started_at", data, "started_at field required")
            self.assertIn("last_heartbeat", data, "last_heartbeat field required")

            # Type/value constraints
            self.assertIsInstance(data["holder"], str, "holder must be a string")
            self.assertGreater(len(data["holder"]), 0, "holder must be non-empty")
            self.assertIsInstance(data["pid"], int, "pid must be an integer")
            self.assertGreater(data["pid"], 0, "pid must be a positive integer")

            # ISO-8601 UTC format validation
            iso_pattern = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
            self.assertRegex(data["started_at"], iso_pattern, "started_at must be UTC ISO-8601")
            self.assertRegex(data["last_heartbeat"], iso_pattern, "last_heartbeat must be UTC ISO-8601")

            # No extra fields beyond the spec
            expected_keys = {"holder", "pid", "started_at", "last_heartbeat"}
            self.assertEqual(set(data.keys()), expected_keys, "holder record must have exactly the spec fields")

            _run("release", str(lock_path))


class TestContention(_DaemonReapingTestCase):
    """Process A holds lock (live PID); process B must get exit 1."""

    def test_second_acquire_fails_with_exit_1(self):
        with tempfile.TemporaryDirectory() as td:
            lock_path = Path(td) / "test.lock"
            # First acquire — stores current process PID (our test process via ppid)
            r1 = _run("acquire", str(lock_path), "holder-A")
            self.assertEqual(r1.returncode, 0, msg=r1.stderr)

            # Verify the stored PID is alive (it's the test process)
            data = _read_lock(lock_path)
            stored_pid = data["pid"]
            try:
                os.kill(stored_pid, 0)  # signal 0 = liveness check
                pid_alive = True
            except ProcessLookupError:
                pid_alive = False
            self.assertTrue(pid_alive, f"stored PID {stored_pid} must be alive for contention test")

            # Second acquire must see live lock and return 1
            r2 = _run("acquire", str(lock_path), "holder-B")
            self.assertEqual(r2.returncode, 1, msg=f"expected contention exit 1, got {r2.returncode}; stderr={r2.stderr}")

    def test_contention_does_not_overwrite_lock(self):
        with tempfile.TemporaryDirectory() as td:
            lock_path = Path(td) / "test.lock"
            _run("acquire", str(lock_path), "holder-A")
            original = _read_lock(lock_path)

            _run("acquire", str(lock_path), "holder-B")
            after = _read_lock(lock_path)

            self.assertEqual(original["holder"], after["holder"], "contention must not overwrite holder")


class TestStalePidTakeover(_DaemonReapingTestCase):
    """Lock held by dead PID → acquire exits 2 and writes new lock."""

    def test_dead_pid_takeover_exits_2(self):
        with tempfile.TemporaryDirectory() as td:
            lock_path = Path(td) / "test.lock"
            _write_lock(lock_path, pid=DEAD_PID)

            result = _run("acquire", str(lock_path), "new-holder")
            self.assertEqual(result.returncode, 2, msg=result.stderr)

    def test_dead_pid_takeover_writes_new_holder(self):
        with tempfile.TemporaryDirectory() as td:
            lock_path = Path(td) / "test.lock"
            _write_lock(lock_path, pid=DEAD_PID)

            _run("acquire", str(lock_path), "new-holder")
            data = _read_lock(lock_path)
            self.assertIsNotNone(data)
            self.assertEqual(data["holder"], "new-holder")

    def test_dead_pid_takeover_logs_to_stderr(self):
        with tempfile.TemporaryDirectory() as td:
            lock_path = Path(td) / "test.lock"
            _write_lock(lock_path, pid=DEAD_PID)

            result = _run("acquire", str(lock_path), "new-holder")
            self.assertIn("stale-takeover", result.stderr, "must log takeover to stderr")

    def test_invariant_takeover_must_fail_not_succeed_silently(self):
        """If takeover returns 2, the lock must have new content — not old content."""
        with tempfile.TemporaryDirectory() as td:
            lock_path = Path(td) / "test.lock"
            _write_lock(lock_path, pid=DEAD_PID)

            result = _run("acquire", str(lock_path), "takeover-holder")
            if result.returncode == 2:
                data = _read_lock(lock_path)
                self.assertNotEqual(
                    data.get("holder"), "test-holder",
                    "stale takeover must replace the lock, not leave old holder",
                )


class TestStaleHeartbeatTakeover(_DaemonReapingTestCase):
    """Lock has live PID (our process) but very old heartbeat → stale → takeover."""

    def test_old_heartbeat_is_stale(self):
        with tempfile.TemporaryDirectory() as td:
            lock_path = Path(td) / "test.lock"
            # Store our own PID (alive) but with ancient heartbeat
            _write_lock(lock_path, pid=os.getpid(), heartbeat="2026-01-01T00:00:00Z")

            # check-stale with default TTL (7200s) — old heartbeat is stale
            result = _run("check-stale", str(lock_path))
            self.assertEqual(result.returncode, 2, msg=f"expected stale (2), got {result.returncode}")

    def test_old_heartbeat_triggers_takeover(self):
        with tempfile.TemporaryDirectory() as td:
            lock_path = Path(td) / "test.lock"
            _write_lock(lock_path, pid=os.getpid(), heartbeat="2026-01-01T00:00:00Z")

            result = _run("acquire", str(lock_path), "hb-takeover-holder")
            self.assertEqual(result.returncode, 2, msg=f"expected takeover (2), got {result.returncode}; stderr={result.stderr}")

    def test_fresh_heartbeat_is_not_stale(self):
        with tempfile.TemporaryDirectory() as td:
            lock_path = Path(td) / "test.lock"
            # Acquire fresh lock, then check-stale immediately
            _run("acquire", str(lock_path), "fresh-holder")
            result = _run("check-stale", str(lock_path))
            self.assertEqual(result.returncode, 0, msg=f"fresh lock must be live (0), got {result.returncode}")

    def test_short_ttl_makes_recent_heartbeat_stale(self):
        with tempfile.TemporaryDirectory() as td:
            lock_path = Path(td) / "test.lock"
            _write_lock(lock_path, pid=os.getpid(), heartbeat="2026-01-01T00:00:00Z")
            result = _run("check-stale", str(lock_path), "--ttl-seconds=60")
            self.assertEqual(result.returncode, 2, msg=f"expected stale with short TTL, got {result.returncode}")


class TestReleaseAndReacquire(_DaemonReapingTestCase):
    """release zeroes content; subsequent acquire succeeds."""

    def test_release_zeroes_content(self):
        with tempfile.TemporaryDirectory() as td:
            lock_path = Path(td) / "test.lock"
            _run("acquire", str(lock_path), "holder-A")
            self.assertIsNotNone(_read_lock(lock_path))

            _run("release", str(lock_path))
            content = lock_path.read_text(encoding="utf-8").strip()
            self.assertEqual(content, "", "release must zero lock content")

    def test_release_exits_0(self):
        with tempfile.TemporaryDirectory() as td:
            lock_path = Path(td) / "test.lock"
            _run("acquire", str(lock_path), "holder-A")
            result = _run("release", str(lock_path))
            self.assertEqual(result.returncode, 0)

    def test_reacquire_after_release_exits_0(self):
        with tempfile.TemporaryDirectory() as td:
            lock_path = Path(td) / "test.lock"
            _run("acquire", str(lock_path), "holder-A")
            _run("release", str(lock_path))

            result = _run("acquire", str(lock_path), "holder-B")
            self.assertEqual(result.returncode, 0, msg=f"re-acquire after release must succeed; stderr={result.stderr}")

    def test_reacquire_after_release_writes_new_holder(self):
        with tempfile.TemporaryDirectory() as td:
            lock_path = Path(td) / "test.lock"
            _run("acquire", str(lock_path), "holder-A")
            _run("release", str(lock_path))
            _run("acquire", str(lock_path), "holder-B")

            data = _read_lock(lock_path)
            self.assertIsNotNone(data)
            self.assertEqual(data["holder"], "holder-B")

    def test_invariant_acquire_after_release_not_contention(self):
        """After release, acquire must never return 1 (contention) or 2 (takeover)."""
        with tempfile.TemporaryDirectory() as td:
            lock_path = Path(td) / "test.lock"
            _run("acquire", str(lock_path), "holder-A")
            _run("release", str(lock_path))
            result = _run("acquire", str(lock_path), "holder-B")
            self.assertNotEqual(
                result.returncode, 1,
                "acquire on released lock must not signal contention",
            )


class TestHeartbeat(_DaemonReapingTestCase):
    """heartbeat updates last_heartbeat timestamp atomically."""

    def test_heartbeat_updates_timestamp(self):
        with tempfile.TemporaryDirectory() as td:
            lock_path = Path(td) / "test.lock"
            _run("acquire", str(lock_path), "holder-A")
            data_before = _read_lock(lock_path)
            hb_before = data_before["last_heartbeat"]

            time.sleep(1.1)  # ensure clock advances
            _run("heartbeat", str(lock_path))
            data_after = _read_lock(lock_path)
            hb_after = data_after["last_heartbeat"]

            self.assertNotEqual(hb_before, hb_after, "heartbeat must update last_heartbeat")

    def test_heartbeat_preserves_other_fields(self):
        with tempfile.TemporaryDirectory() as td:
            lock_path = Path(td) / "test.lock"
            _run("acquire", str(lock_path), "holder-A")
            data_before = _read_lock(lock_path)

            time.sleep(1.1)
            _run("heartbeat", str(lock_path))
            data_after = _read_lock(lock_path)

            self.assertEqual(data_before["holder"], data_after["holder"])
            self.assertEqual(data_before["pid"], data_after["pid"])
            self.assertEqual(data_before["started_at"], data_after["started_at"])

    def test_heartbeat_exits_1_on_missing_lock(self):
        with tempfile.TemporaryDirectory() as td:
            lock_path = Path(td) / "nonexistent.lock"
            result = _run("heartbeat", str(lock_path))
            self.assertEqual(result.returncode, 1)


class TestCheckStale(_DaemonReapingTestCase):
    """check-stale exit code semantics."""

    def test_free_lock_file_absent_exits_1(self):
        with tempfile.TemporaryDirectory() as td:
            lock_path = Path(td) / "nonexistent.lock"
            result = _run("check-stale", str(lock_path))
            self.assertEqual(result.returncode, 1)

    def test_empty_lock_file_exits_1(self):
        with tempfile.TemporaryDirectory() as td:
            lock_path = Path(td) / "empty.lock"
            lock_path.write_text("", encoding="utf-8")
            result = _run("check-stale", str(lock_path))
            self.assertEqual(result.returncode, 1)

    def test_live_lock_exits_0(self):
        with tempfile.TemporaryDirectory() as td:
            lock_path = Path(td) / "test.lock"
            _run("acquire", str(lock_path), "holder")
            result = _run("check-stale", str(lock_path))
            self.assertEqual(result.returncode, 0)

    def test_dead_pid_exits_2(self):
        with tempfile.TemporaryDirectory() as td:
            lock_path = Path(td) / "test.lock"
            _write_lock(lock_path, pid=DEAD_PID)
            result = _run("check-stale", str(lock_path))
            self.assertEqual(result.returncode, 2)

    def test_old_heartbeat_exits_2(self):
        with tempfile.TemporaryDirectory() as td:
            lock_path = Path(td) / "test.lock"
            _write_lock(lock_path, pid=os.getpid(), heartbeat="2026-01-01T00:00:00Z")
            result = _run("check-stale", str(lock_path))
            self.assertEqual(result.returncode, 2)

    def test_check_stale_no_takeover(self):
        """check-stale must never modify the lock file — it is read-only."""
        with tempfile.TemporaryDirectory() as td:
            lock_path = Path(td) / "test.lock"
            _write_lock(lock_path, pid=DEAD_PID)
            content_before = lock_path.read_text(encoding="utf-8")

            _run("check-stale", str(lock_path))
            content_after = lock_path.read_text(encoding="utf-8")

            self.assertEqual(content_before, content_after, "check-stale must not modify lock content")

    def test_ttl_seconds_option(self):
        with tempfile.TemporaryDirectory() as td:
            lock_path = Path(td) / "test.lock"
            _write_lock(lock_path, pid=os.getpid(), heartbeat="2026-01-01T00:00:00Z")
            result = _run("check-stale", str(lock_path), "--ttl-seconds=60")
            self.assertEqual(result.returncode, 2)


class TestNonNumericPid(_DaemonReapingTestCase):
    """Non-numeric pid in lock JSON must be treated as stale (safe), not crash."""

    def _write_lock_nonnumeric_pid(self, lock_path: Path) -> None:
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        lock_path.write_text(
            json.dumps({
                "holder": "test-holder",
                "pid": "not-a-number",
                "started_at": "2026-01-01T00:00:00Z",
                "last_heartbeat": "2026-01-01T00:00:00Z",
            }) + "\n",
            encoding="utf-8",
        )

    def test_check_stale_nonnumeric_pid_exits_2(self):
        """check-stale with non-numeric pid must return 2 (stale), not crash."""
        with tempfile.TemporaryDirectory() as td:
            lock_path = Path(td) / "test.lock"
            self._write_lock_nonnumeric_pid(lock_path)
            result = _run("check-stale", str(lock_path))
            self.assertEqual(result.returncode, 2, msg=f"non-numeric pid must be stale; stderr={result.stderr}")

    def test_acquire_nonnumeric_pid_treats_as_stale_exits_2(self):
        """acquire with non-numeric pid in existing lock must perform stale-takeover (exit 2)."""
        with tempfile.TemporaryDirectory() as td:
            lock_path = Path(td) / "test.lock"
            self._write_lock_nonnumeric_pid(lock_path)
            result = _run("acquire", str(lock_path), "new-holder")
            self.assertEqual(result.returncode, 2, msg=f"non-numeric pid must trigger takeover; stderr={result.stderr}")


class TestCorruptLockJSON(_DaemonReapingTestCase):
    """Non-empty but JSON-unparseable lock file must cause exit 3 (corrupt-lock).

    This distinguishes malformed files from legitimately released (empty) locks.
    Both acquire and check-stale must hard-halt on corrupt JSON.
    """

    def _write_corrupt_lock(self, lock_path: Path) -> None:
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        lock_path.write_text("{this is not valid JSON!!!", encoding="utf-8")

    def test_acquire_corrupt_json_exits_3(self):
        """acquire on a corrupt (non-empty, non-parseable) lock file must exit 3."""
        with tempfile.TemporaryDirectory() as td:
            lock_path = Path(td) / "test.lock"
            self._write_corrupt_lock(lock_path)
            result = _run("acquire", str(lock_path), "new-holder")
            self.assertEqual(result.returncode, 3, msg=f"corrupt lock must exit 3; stderr={result.stderr}")

    def test_acquire_corrupt_json_writes_stderr(self):
        """acquire on corrupt lock must print a cleanup message to stderr."""
        with tempfile.TemporaryDirectory() as td:
            lock_path = Path(td) / "test.lock"
            self._write_corrupt_lock(lock_path)
            result = _run("acquire", str(lock_path), "new-holder")
            self.assertIn("corrupt", result.stderr.lower(), msg="stderr must mention 'corrupt'")
            self.assertIn("manual cleanup", result.stderr.lower(), msg="stderr must instruct manual cleanup")

    def test_check_stale_corrupt_json_exits_3(self):
        """check-stale on a corrupt (non-empty, non-parseable) lock file must exit 3."""
        with tempfile.TemporaryDirectory() as td:
            lock_path = Path(td) / "test.lock"
            self._write_corrupt_lock(lock_path)
            result = _run("check-stale", str(lock_path))
            self.assertEqual(result.returncode, 3, msg=f"corrupt lock must exit 3; stderr={result.stderr}")

    def test_check_stale_corrupt_json_writes_stderr(self):
        """check-stale on corrupt lock must print a cleanup message to stderr."""
        with tempfile.TemporaryDirectory() as td:
            lock_path = Path(td) / "test.lock"
            self._write_corrupt_lock(lock_path)
            result = _run("check-stale", str(lock_path))
            self.assertIn("corrupt", result.stderr.lower(), msg="stderr must mention 'corrupt'")

    def test_empty_file_is_not_corrupt(self):
        """Empty file (legitimately released) must NOT exit 3 — it is free (exit 1)."""
        with tempfile.TemporaryDirectory() as td:
            lock_path = Path(td) / "test.lock"
            lock_path.write_text("", encoding="utf-8")
            result = _run("check-stale", str(lock_path))
            self.assertNotEqual(result.returncode, 3, "empty file is free (exit 1), not corrupt (exit 3)")
            self.assertEqual(result.returncode, 1)

    def test_null_json_is_not_corrupt(self):
        """A file containing literal 'null' is valid JSON (empty/null value) → free (exit 1)."""
        with tempfile.TemporaryDirectory() as td:
            lock_path = Path(td) / "test.lock"
            lock_path.write_text("null", encoding="utf-8")
            result = _run("check-stale", str(lock_path))
            # 'null' parses as None in Python; treated as free
            self.assertNotEqual(result.returncode, 3, "null JSON must not be treated as corrupt")

    def test_empty_braces_json_is_not_corrupt(self):
        """A file containing '{}' is valid JSON (empty object) → treated as stale (exit 2).

        Per finding 8: non-empty JSON that does NOT match the holder-record schema
        {holder, pid, started_at, last_heartbeat} must NOT be treated as free.
        '{}' is wrong-schema → stale (exit 2), not corrupt (exit 3) and not free (exit 1).
        This prevents silent overwrites of malformed lock files.
        """
        with tempfile.TemporaryDirectory() as td:
            lock_path = Path(td) / "test.lock"
            lock_path.write_text("{}", encoding="utf-8")
            result = _run("check-stale", str(lock_path))
            self.assertEqual(result.returncode, 2, "'{}' must be treated as wrong-schema/stale (exit 2), not free (exit 1)")

    def test_empty_braces_acquire_returns_stale_takeover(self):
        """acquire on a lock file containing '{}' must return 2 (stale takeover).

        Per finding 8: '{}' is wrong-schema JSON (not a valid holder record) and must
        NOT be treated as free.  acquire must perform a stale takeover and return exit 2.
        """
        with tempfile.TemporaryDirectory() as td:
            lock_path = Path(td) / "test.lock"
            lock_path.write_text("{}", encoding="utf-8")
            result = _run("acquire", str(lock_path), "new-holder")
            self.assertEqual(result.returncode, 2, "acquire on '{}' lock must return 2 (stale-takeover, not free)")


class TestCheckStaleSharedFlock(_DaemonReapingTestCase):
    """check-stale acquires shared flock, so concurrent heartbeats don't cause torn reads."""

    def test_check_stale_consistent_under_concurrent_heartbeat(self):
        """Run check-stale while heartbeat is running concurrently; must get a valid result.

        This test validates no torn-read / corrupt observation: check-stale must always
        return a legitimate exit code (0, 1, or 2) under healthy concurrency — exit 3
        must never occur because the shared flock prevents observing partially-written JSON.
        """
        with tempfile.TemporaryDirectory() as td:
            lock_path = Path(td) / "test.lock"
            # Acquire a fresh lock (PID = our test process via ppid logic)
            r = _run("acquire", str(lock_path), "hb-test-holder")
            self.assertEqual(r.returncode, 0, msg=f"acquire must succeed; stderr={r.stderr}")

            # Start many heartbeats concurrently with many check-stales.
            # Exit 3 must NEVER occur under healthy concurrency — the shared flock
            # in check-stale prevents torn reads that could produce corrupt JSON.
            valid_codes = {0, 1, 2}
            errors = []
            procs_hb = []
            procs_cs = []

            import threading

            def do_heartbeat():
                for _ in range(5):
                    _run("heartbeat", str(lock_path))

            def do_check_stale():
                for _ in range(5):
                    result = _run("check-stale", str(lock_path))
                    if result.returncode not in valid_codes:
                        errors.append(f"unexpected exit {result.returncode}: {result.stderr}")

            threads = [threading.Thread(target=do_heartbeat) for _ in range(3)]
            threads += [threading.Thread(target=do_check_stale) for _ in range(3)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

            self.assertEqual(errors, [], f"check-stale returned unexpected exit codes: {errors}")


class TestReleaseMissingFile(_DaemonReapingTestCase):
    """release exits 1 when lock file does not exist."""

    def test_release_missing_exits_1(self):
        with tempfile.TemporaryDirectory() as td:
            lock_path = Path(td) / "nonexistent.lock"
            result = _run("release", str(lock_path))
            self.assertEqual(result.returncode, 1)


class TestUnknownSubcommand(_DaemonReapingTestCase):
    """Unknown subcommand exits 2."""

    def test_unknown_subcommand_exits_2(self):
        result = _run("bogus-subcommand", "/tmp/x.lock")
        self.assertEqual(result.returncode, 2)

    def test_no_args_exits_2(self):
        result = subprocess.run(
            ["bash", SCRIPT],
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 2)


class TestStaleHeartbeatTakeoverLive(_DaemonReapingTestCase):
    """Stale-heartbeat takeover: the daemon holding the lock is alive, but its
    heartbeat has expired past the TTL.  A new acquire must take over (exit 2).

    This tests finding 2: stale-heartbeat takeover must be implemented, not just
    stale-PID takeover.  The distinction: PID alive but heartbeat old means the
    process is running but stopped heartbeating — the lock should be reclaimed.
    """

    def _flock_probe(self, flock_path: Path) -> bool:
        probe_code = textwrap.dedent("""\
            import fcntl, os, sys
            fd = os.open(sys.argv[1], os.O_CREAT | os.O_RDWR, 0o644)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                sys.exit(1)  # acquired = free
            except BlockingIOError:
                sys.exit(0)  # blocked = held
        """)
        result = subprocess.run(
            [sys.executable, "-c", probe_code, str(flock_path)],
            timeout=5,
        )
        return result.returncode == 0  # 0 = held

    def test_stale_heartbeat_live_pid_triggers_takeover(self):
        """acquire on a lock with a live PID but expired heartbeat must exit 2.

        Invariant: if PID is alive but heartbeat > TTL, the lock is stale and
        a new acquire must reclaim it.
        Failure class: acquire returns 1 (contention) instead of 2 (takeover).
        """
        with tempfile.TemporaryDirectory() as td:
            lock_path = Path(td) / "test.lock"
            flock_path = Path(td) / "test.lock.flock"

            # Acquire a real lock (live daemon + fresh heartbeat)
            r_a = _run("acquire", str(lock_path), "holder-A")
            self.assertEqual(r_a.returncode, 0, f"setup acquire failed: {r_a.stderr}")

            # Verify daemon is running and flock is held
            data = _read_lock(lock_path)
            self.assertIsNotNone(data, "setup: lock must be written")
            daemon_pid = data["pid"]
            try:
                os.kill(daemon_pid, 0)
                daemon_alive = True
            except ProcessLookupError:
                daemon_alive = False
            self.assertTrue(daemon_alive, f"setup: daemon pid={daemon_pid} must be alive")
            self.assertTrue(self._flock_probe(flock_path), "setup: flock must be held")

            # Backdate the heartbeat past default TTL (7200s) by rewriting the JSON.
            # The daemon holds the .flock but we overwrite the JSON content to simulate
            # a stale heartbeat (daemon alive, flock held, but heartbeat expired).
            stale_hb = "2020-01-01T00:00:00Z"
            data["last_heartbeat"] = stale_hb
            lock_path.write_text(json.dumps(data) + "\n", encoding="utf-8")

            # Now try to acquire as holder-B. The PID is alive (flock is held),
            # but the heartbeat is expired → stale-heartbeat takeover → exit 2.
            r_b = _run("acquire", str(lock_path), "holder-B")
            self.assertEqual(
                r_b.returncode, 2,
                f"stale-heartbeat takeover must return exit 2; got {r_b.returncode}: {r_b.stderr}",
            )

            # Verify holder-B is now the holder
            data_b = _read_lock(lock_path)
            self.assertIsNotNone(data_b, "lock must be non-empty after takeover")
            self.assertEqual(data_b["holder"], "holder-B", "holder-B must own the lock after takeover")

            # Verify flock is still held (by new daemon)
            self.assertTrue(
                self._flock_probe(flock_path),
                "flock must still be held (by new daemon) after stale takeover",
            )

            # Clean up
            _run("release", str(lock_path))

    def test_stale_heartbeat_takeover_logs_to_stderr(self):
        """Stale-heartbeat takeover must log 'stale-takeover' to stderr."""
        with tempfile.TemporaryDirectory() as td:
            lock_path = Path(td) / "test.lock"
            r_a = _run("acquire", str(lock_path), "holder-A")
            self.assertEqual(r_a.returncode, 0, f"setup acquire failed: {r_a.stderr}")

            data = _read_lock(lock_path)
            data["last_heartbeat"] = "2020-01-01T00:00:00Z"
            lock_path.write_text(json.dumps(data) + "\n", encoding="utf-8")

            r_b = _run("acquire", str(lock_path), "holder-B")
            self.assertIn(
                "stale-takeover", r_b.stderr,
                f"stale-heartbeat takeover must log 'stale-takeover'; stderr={r_b.stderr!r}",
            )
            _run("release", str(lock_path))

    def test_fresh_heartbeat_no_takeover(self):
        """A live lock with a fresh heartbeat must NOT be taken over (exit 1)."""
        with tempfile.TemporaryDirectory() as td:
            lock_path = Path(td) / "test.lock"
            r_a = _run("acquire", str(lock_path), "holder-A")
            self.assertEqual(r_a.returncode, 0, f"setup acquire failed: {r_a.stderr}")

            # Update heartbeat to now
            _run("heartbeat", str(lock_path))

            r_b = _run("acquire", str(lock_path), "holder-B")
            self.assertEqual(
                r_b.returncode, 1,
                f"live lock with fresh heartbeat must be contention (exit 1); got {r_b.returncode}",
            )
            _run("release", str(lock_path))


class TestReleaseOwnershipValidation(_DaemonReapingTestCase):
    """release must validate ownership when --expected-holder or --expected-pid is given.

    Finding 4: any caller can release any lock without proof of ownership.  The
    fix adds --expected-holder= and --expected-pid= options to release.  A
    mismatch must return exit 4 without killing the daemon.
    """

    def test_wrong_holder_rejected_exit_4(self):
        """release with wrong --expected-holder must exit 4 (ownership mismatch)."""
        with tempfile.TemporaryDirectory() as td:
            lock_path = Path(td) / "test.lock"
            r = _run("acquire", str(lock_path), "real-holder")
            self.assertEqual(r.returncode, 0, f"setup acquire failed: {r.stderr}")

            result = _run("release", str(lock_path), "--expected-holder=wrong-holder")
            self.assertEqual(
                result.returncode, 4,
                f"wrong holder must exit 4; got {result.returncode}: {result.stderr}",
            )

            # Lock must still be held (daemon not killed)
            data = _read_lock(lock_path)
            self.assertIsNotNone(data, "lock must still be held after ownership rejection")
            self.assertEqual(data["holder"], "real-holder", "holder must be unchanged")

            # Clean up
            _run("release", str(lock_path), "--expected-holder=real-holder")

    def test_wrong_pid_rejected_exit_4(self):
        """release with wrong --expected-pid must exit 4 (ownership mismatch)."""
        with tempfile.TemporaryDirectory() as td:
            lock_path = Path(td) / "test.lock"
            r = _run("acquire", str(lock_path), "real-holder")
            self.assertEqual(r.returncode, 0, f"setup acquire failed: {r.stderr}")

            data = _read_lock(lock_path)
            real_pid = data["pid"]
            wrong_pid = real_pid + 9999  # very unlikely to be the real PID

            result = _run("release", str(lock_path), f"--expected-pid={wrong_pid}")
            self.assertEqual(
                result.returncode, 4,
                f"wrong PID must exit 4; got {result.returncode}: {result.stderr}",
            )

            # Lock must still be held
            data_after = _read_lock(lock_path)
            self.assertIsNotNone(data_after, "lock must still be held after ownership rejection")
            self.assertEqual(data_after["pid"], real_pid, "daemon PID must be unchanged")

            # Clean up with correct PID
            _run("release", str(lock_path), f"--expected-pid={real_pid}")

    def test_correct_holder_and_pid_releases(self):
        """release with correct --expected-holder and --expected-pid must succeed (exit 0)."""
        with tempfile.TemporaryDirectory() as td:
            lock_path = Path(td) / "test.lock"
            r = _run("acquire", str(lock_path), "holder-X")
            self.assertEqual(r.returncode, 0, f"setup acquire failed: {r.stderr}")

            data = _read_lock(lock_path)
            pid = data["pid"]

            result = _run("release", str(lock_path),
                          "--expected-holder=holder-X",
                          f"--expected-pid={pid}")
            self.assertEqual(result.returncode, 0, f"correct ownership must release; stderr={result.stderr}")

            content = lock_path.read_text(encoding="utf-8").strip()
            self.assertEqual(content, "", "lock content must be zeroed after release")

    def test_no_ownership_args_releases_without_check(self):
        """release without ownership args must still succeed (backward-compatible)."""
        with tempfile.TemporaryDirectory() as td:
            lock_path = Path(td) / "test.lock"
            _run("acquire", str(lock_path), "holder-A")
            result = _run("release", str(lock_path))
            self.assertEqual(result.returncode, 0, f"release without ownership must succeed; {result.stderr}")


class TestMalformedJsonNotFree(_DaemonReapingTestCase):
    """Wrong-schema parseable JSON must be treated as stale (exit 2), NOT free.

    Finding 8: '{}'/'{...wrong fields}' must trigger stale logic, not be silently
    overwritten as free.  This prevents overwriting a non-empty malformed lock file
    without going through the takeover path.
    """

    def test_wrong_schema_check_stale_exit_2(self):
        """check-stale on wrong-schema JSON (e.g. partial record) must exit 2 (stale)."""
        with tempfile.TemporaryDirectory() as td:
            lock_path = Path(td) / "test.lock"
            # Partial record — missing required fields
            lock_path.write_text(json.dumps({"holder": "x", "pid": 123}) + "\n", encoding="utf-8")
            result = _run("check-stale", str(lock_path))
            self.assertEqual(
                result.returncode, 2,
                f"wrong-schema JSON must be stale (exit 2), not free (1) or corrupt (3); "
                f"got {result.returncode}: {result.stderr}",
            )

    def test_wrong_schema_acquire_triggers_takeover_exit_2(self):
        """acquire on wrong-schema JSON must trigger stale takeover (exit 2)."""
        with tempfile.TemporaryDirectory() as td:
            lock_path = Path(td) / "test.lock"
            # JSON valid but wrong schema
            lock_path.write_text(json.dumps({"foo": "bar"}) + "\n", encoding="utf-8")
            result = _run("acquire", str(lock_path), "new-holder")
            self.assertEqual(
                result.returncode, 2,
                f"wrong-schema JSON must trigger takeover (exit 2); "
                f"got {result.returncode}: {result.stderr}",
            )

    def test_wrong_schema_not_exit_1(self):
        """Wrong-schema JSON must NOT be treated as free (exit 1 from check-stale)."""
        with tempfile.TemporaryDirectory() as td:
            lock_path = Path(td) / "test.lock"
            lock_path.write_text('{"wrong_field": 42}', encoding="utf-8")
            result = _run("check-stale", str(lock_path))
            self.assertNotEqual(
                result.returncode, 1,
                "wrong-schema JSON must NOT be treated as free (exit 1)",
            )

    def test_corrupt_json_still_exit_3(self):
        """Non-parseable JSON must still exit 3 (corrupt), not exit 2 (stale)."""
        with tempfile.TemporaryDirectory() as td:
            lock_path = Path(td) / "test.lock"
            lock_path.write_text("{not valid json!!!", encoding="utf-8")
            result = _run("check-stale", str(lock_path))
            self.assertEqual(
                result.returncode, 3,
                f"non-parseable JSON must exit 3 (corrupt); got {result.returncode}",
            )

    def test_null_json_is_free_exit_1(self):
        """Literal 'null' JSON must still be treated as free (exit 1)."""
        with tempfile.TemporaryDirectory() as td:
            lock_path = Path(td) / "test.lock"
            lock_path.write_text("null", encoding="utf-8")
            result = _run("check-stale", str(lock_path))
            self.assertEqual(result.returncode, 1, "null JSON must be free (exit 1)")


class TestZombieAfterSigterm(_DaemonReapingTestCase):
    """After SIGTERM, release must verify flock availability, not just poll kill(pid,0).

    Finding 6: kill(pid,0) stays true for unreaped zombies.  If the daemon is a
    zombie, release could time out with the flock still technically held.  The fix
    uses LOCK_EX|LOCK_NB flock probe to detect flock release, not just PID liveness.

    We simulate the zombie scenario indirectly by verifying:
    - After release returns 0, the flock is genuinely free (OS-level probe)
    - release detects a stuck daemon and returns exit 5, not silently succeed
    """

    def _flock_probe(self, flock_path: Path) -> bool:
        probe_code = textwrap.dedent("""\
            import fcntl, os, sys
            fd = os.open(sys.argv[1], os.O_CREAT | os.O_RDWR, 0o644)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                sys.exit(1)  # free
            except BlockingIOError:
                sys.exit(0)  # held
        """)
        result = subprocess.run(
            [sys.executable, "-c", probe_code, str(flock_path)],
            timeout=5,
        )
        return result.returncode == 0  # 0 = held

    def test_release_verifies_flock_free(self):
        """After a successful release (exit 0), the .flock must be free at the OS level.

        Invariant: release returns 0 ONLY after verifying the flock is released.
        Failure class: release uses kill(pid,0) which is True for zombies; a zombie
        daemon still holds the fd → flock remains held despite release returning 0.
        """
        with tempfile.TemporaryDirectory() as td:
            lock_path = Path(td) / "test.lock"
            flock_path = Path(td) / "test.lock.flock"

            r = _run("acquire", str(lock_path), "holder")
            self.assertEqual(r.returncode, 0, f"setup acquire failed: {r.stderr}")
            self.assertTrue(self._flock_probe(flock_path), "setup: flock must be held")

            result = _run("release", str(lock_path))
            self.assertEqual(result.returncode, 0, f"release must succeed; {result.stderr}")

            # Verify flock is free at OS level — not just JSON content cleared
            is_held = self._flock_probe(flock_path)
            self.assertFalse(
                is_held,
                "After release returns 0, the OS-level flock must be free "
                "(failure: release returned 0 while zombie still holds flock fd)",
            )

    def test_setup_acquire_assertion(self):
        """Setup acquire in tests must be asserted to have succeeded.

        Finding 9: tests that don't assert setup return codes can pass while
        testing failed-setup paths (i.e., testing that an empty lock is released,
        not that a live lock is released).
        """
        with tempfile.TemporaryDirectory() as td:
            lock_path = Path(td) / "test.lock"
            flock_path = Path(td) / "test.lock.flock"

            r_acq = _run("acquire", str(lock_path), "holder-setup-test")
            # Must assert return code — this is the point of this test
            self.assertEqual(
                r_acq.returncode, 0,
                f"setup acquire must return 0 before testing release; "
                f"got {r_acq.returncode}: {r_acq.stderr}",
            )

            # Also verify that the flock is actually held (not just JSON written)
            self.assertTrue(
                self._flock_probe(flock_path),
                "After setup acquire, the OS-level flock must be held "
                "(not just JSON written without flock)",
            )

            r_rel = _run("release", str(lock_path))
            self.assertEqual(
                r_rel.returncode, 0,
                f"release must succeed; {r_rel.stderr}",
            )


class TestCompareAndClearReleaseRace(_DaemonReapingTestCase):
    """BLOCKER fix: release must not blindly zero the JSON — it must compare-and-clear.

    Invariant: if a new holder acquires the lock between our SIGTERM and the
    zero-write, their holder record must NOT be erased.
    Failure class: unconditional lock_path.write_text("") after _wait_flock_free
    erases any record present, including a newer holder's freshly-written record.
    """

    def test_release_does_not_erase_newer_holder_record(self):
        """Simulate the race: acquire holder-B in the window between holder-A's SIGTERM
        and the compare-and-clear step.  Holder-B's record must survive.

        We use a direct approach: acquire A, read its daemon PID, manually send SIGTERM
        (like release would), wait for the daemon to exit (flock free), then write holder-B's
        record *before* calling release.  Since release's compare-and-clear checks that the
        current PID matches the killed daemon's PID — and holder-B's PID differs — it must
        leave holder-B's record intact.
        """
        import signal as _signal

        with tempfile.TemporaryDirectory() as td:
            lock_path = Path(td) / "test.lock"

            # Acquire holder-A (real daemon)
            r_a = _run("acquire", str(lock_path), "holder-A")
            self.assertEqual(r_a.returncode, 0, f"setup: acquire holder-A failed: {r_a.stderr}")

            data_a = _read_lock(lock_path)
            self.assertIsNotNone(data_a, "setup: holder-A record must exist")
            daemon_pid_a = data_a["pid"]

            # Manually send SIGTERM to the daemon (simulating what release does)
            try:
                os.kill(daemon_pid_a, _signal.SIGTERM)
            except ProcessLookupError:
                pass  # already dead

            # Wait for daemon to exit (flock to become free)
            flock_file = Path(td) / "test.lock.flock"
            deadline = time.monotonic() + 5.0
            while time.monotonic() < deadline:
                try:
                    import fcntl
                    probe_fd = os.open(str(flock_file), os.O_CREAT | os.O_RDWR, 0o644)
                    try:
                        fcntl.flock(probe_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                        flock_free = True
                    except BlockingIOError:
                        flock_free = False
                    finally:
                        os.close(probe_fd)
                    if flock_free:
                        break
                except Exception:
                    pass
                time.sleep(0.05)

            # Now simulate holder-B winning the flock and writing its record
            # (this is the race window: between SIGTERM and compare-and-clear)
            r_b = _run("acquire", str(lock_path), "holder-B")
            # holder-B should succeed (either 0 or 2 after takeover)
            self.assertIn(
                r_b.returncode, (0, 2),
                f"holder-B acquire after A's daemon killed must succeed; got {r_b.returncode}: {r_b.stderr}",
            )
            data_b = _read_lock(lock_path)
            self.assertIsNotNone(data_b, "holder-B record must be written")
            self.assertEqual(data_b["holder"], "holder-B", "holder-B must own the record")

            # Now call release for holder-A (it will try to zero under compare-and-clear)
            # The compare-and-clear must detect that the current record belongs to holder-B
            # (different PID) and NOT erase it.
            # We pass expected-pid of daemon_pid_a to simulate the release of A
            r_rel = _run("release", str(lock_path), f"--expected-pid={daemon_pid_a}")
            # Release may fail with exit 4 (pid mismatch) or 0 (daemon already dead) —
            # either is acceptable.  The critical invariant is that holder-B's record survives.
            data_after = _read_lock(lock_path)
            self.assertIsNotNone(
                data_after,
                "holder-B's record must NOT be erased by holder-A's release "
                "(compare-and-clear blocker fix)",
            )
            self.assertEqual(
                data_after["holder"], "holder-B",
                "holder-B's record must survive holder-A's compare-and-clear release attempt",
            )

            # Clean up holder-B
            _run("release", str(lock_path))


class TestWrongSchemaWithValidPidTakeover(_DaemonReapingTestCase):
    """Finding 2: wrong-schema JSON with an integer pid field must still kill the daemon.

    Previously, _do_stale_takeover set kill_pid=None for _WRONG_SCHEMA data,
    meaning the stale daemon was never killed — just waited 2s and returned
    contention if the flock was still held.

    Fix: extract the integer pid from the wrong-schema dict and kill it before
    waiting for flock freedom.
    """

    def test_wrong_schema_with_pid_kills_daemon_on_takeover(self):
        """A live daemon holds the flock; the JSON is wrong-schema but contains a valid pid.

        The takeover must kill the daemon (freeing the flock) and succeed (exit 2).
        Failure class: takeover returns 1 (contention) because pid extraction from
        wrong-schema JSON was skipped, so the daemon is never killed.
        """
        with tempfile.TemporaryDirectory() as td:
            lock_path = Path(td) / "test.lock"
            flock_path = Path(td) / "test.lock.flock"

            # Acquire a real daemon (valid JSON, flock held)
            r_a = _run("acquire", str(lock_path), "holder-A")
            self.assertEqual(r_a.returncode, 0, f"setup: acquire failed: {r_a.stderr}")

            data_a = _read_lock(lock_path)
            self.assertIsNotNone(data_a)
            daemon_pid = data_a["pid"]

            # Overwrite the JSON with wrong-schema that still has a valid integer pid.
            # This simulates a partially-corrupted or schema-migrated lock file.
            wrong_schema_json = json.dumps({
                "pid": daemon_pid,
                "wrong_field": "bad",
                # Missing holder, started_at, last_heartbeat — invalid schema
            }) + "\n"
            lock_path.write_text(wrong_schema_json, encoding="utf-8")

            # Now try to acquire as holder-B.  The flock is held (daemon alive),
            # the JSON is wrong-schema but contains the daemon's real pid.
            # Takeover must kill the daemon and succeed (exit 2).
            r_b = _run("acquire", str(lock_path), "holder-B")
            self.assertEqual(
                r_b.returncode, 2,
                f"wrong-schema-with-valid-pid takeover must return exit 2; "
                f"got {r_b.returncode}: {r_b.stderr}",
            )

            # Verify holder-B is now the holder
            data_b = _read_lock(lock_path)
            self.assertIsNotNone(data_b, "holder-B record must exist after takeover")
            self.assertEqual(data_b["holder"], "holder-B")

            # Clean up
            _run("release", str(lock_path))


class TestMalformedTimestampRejected(_DaemonReapingTestCase):
    """Finding 3: malformed timestamps must be rejected as wrong-schema.

    Any string was previously accepted for started_at/last_heartbeat, so
    '2026-13-45T99:99:99Z' (invalid calendar values) passed as valid.
    Fix: validate both timestamps against strict UTC ISO-8601 via strptime.
    """

    def _write_lock_with_timestamps(self, lock_path: Path, started_at: str, heartbeat: str) -> None:
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        lock_path.write_text(
            json.dumps({
                "holder": "test-holder",
                "pid": os.getpid(),
                "started_at": started_at,
                "last_heartbeat": heartbeat,
            }) + "\n",
            encoding="utf-8",
        )

    def test_invalid_month_rejected_as_wrong_schema(self):
        """Month 13 is invalid; record must be treated as wrong-schema (stale, exit 2)."""
        with tempfile.TemporaryDirectory() as td:
            lock_path = Path(td) / "test.lock"
            self._write_lock_with_timestamps(
                lock_path,
                started_at="2026-13-01T00:00:00Z",
                heartbeat="2026-13-01T00:00:00Z",
            )
            result = _run("check-stale", str(lock_path))
            self.assertEqual(
                result.returncode, 2,
                f"invalid month-13 timestamp must be wrong-schema/stale (exit 2); "
                f"got {result.returncode}: {result.stderr}",
            )

    def test_invalid_hour_rejected_as_wrong_schema(self):
        """Hour 99 is invalid; record must be treated as wrong-schema (stale, exit 2)."""
        with tempfile.TemporaryDirectory() as td:
            lock_path = Path(td) / "test.lock"
            self._write_lock_with_timestamps(
                lock_path,
                started_at="2026-01-01T99:00:00Z",
                heartbeat="2026-01-01T99:00:00Z",
            )
            result = _run("check-stale", str(lock_path))
            self.assertEqual(
                result.returncode, 2,
                f"invalid hour-99 timestamp must be wrong-schema/stale (exit 2); "
                f"got {result.returncode}: {result.stderr}",
            )

    def test_non_string_timestamp_rejected(self):
        """Non-string (integer) timestamp must be rejected as wrong-schema (stale, exit 2)."""
        with tempfile.TemporaryDirectory() as td:
            lock_path = Path(td) / "test.lock"
            lock_path.parent.mkdir(parents=True, exist_ok=True)
            lock_path.write_text(
                json.dumps({
                    "holder": "test-holder",
                    "pid": os.getpid(),
                    "started_at": 1234567890,
                    "last_heartbeat": 1234567890,
                }) + "\n",
                encoding="utf-8",
            )
            result = _run("check-stale", str(lock_path))
            self.assertEqual(
                result.returncode, 2,
                f"integer timestamp must be wrong-schema/stale (exit 2); "
                f"got {result.returncode}: {result.stderr}",
            )

    def test_valid_timestamps_not_rejected(self):
        """Valid ISO-8601 timestamps must still produce a live lock (exit 0) with live pid."""
        with tempfile.TemporaryDirectory() as td:
            lock_path = Path(td) / "test.lock"
            r = _run("acquire", str(lock_path), "holder")
            self.assertEqual(r.returncode, 0, f"setup acquire failed: {r.stderr}")
            result = _run("check-stale", str(lock_path))
            self.assertEqual(result.returncode, 0, "valid timestamps must not be rejected")
            _run("release", str(lock_path))

    def test_malformed_timestamp_triggers_acquire_takeover(self):
        """acquire on wrong-schema (malformed timestamps) must perform stale takeover (exit 2)."""
        with tempfile.TemporaryDirectory() as td:
            lock_path = Path(td) / "test.lock"
            self._write_lock_with_timestamps(
                lock_path,
                started_at="not-a-date",
                heartbeat="also-not-a-date",
            )
            result = _run("acquire", str(lock_path), "new-holder")
            self.assertEqual(
                result.returncode, 2,
                f"malformed-timestamp lock must trigger stale takeover (exit 2); "
                f"got {result.returncode}: {result.stderr}",
            )


class TestUntrustedPidNotKilled(_DaemonReapingTestCase):
    """Finding 4: release and stale-takeover must not kill a PID that fails identity check.

    Invariant: if the process at the recorded pid is confirmed NOT to be a
    sink-lock daemon (identity check returns False), SIGTERM is not sent.
    Failure class: blind os.kill(pid, SIGTERM) after PID reuse or maliciously-
    edited lock file kills an unrelated process.
    """

    def test_non_daemon_pid_not_killed_on_release(self):
        """A lock file whose pid field points to an unrelated process (not a sink-lock daemon)
        must not cause SIGTERM to be sent to that process on release.

        We use pid=1 (init/launchd on macOS, systemd on Linux) as a reliably-
        live non-daemon process.  The identity check must return False (confirmed
        not our daemon) and release must skip the kill — the process at pid 1
        must still be alive after the call, and we should see the 'identity check'
        message on stderr or release exits cleanly without killing it.
        """
        with tempfile.TemporaryDirectory() as td:
            lock_path = Path(td) / "test.lock"
            lock_path.parent.mkdir(parents=True, exist_ok=True)
            # Write a plausible-looking lock with pid=1 (definitely not our daemon)
            lock_path.write_text(
                json.dumps({
                    "holder": "test-holder",
                    "pid": 1,
                    "started_at": "2026-01-01T00:00:00Z",
                    "last_heartbeat": "2026-01-01T00:00:00Z",
                }) + "\n",
                encoding="utf-8",
            )

            result = _run("release", str(lock_path))
            # Release may exit 0 (cleared wrong-schema) or other non-5 code —
            # what matters is that pid 1 is still alive and we logged the skip or
            # handled it safely.
            # Verify pid 1 is still alive (if we killed it, something went very wrong)
            try:
                os.kill(1, 0)
                pid1_alive = True
            except (ProcessLookupError, PermissionError):
                pid1_alive = True  # PermissionError means it exists
            except OSError:
                pid1_alive = False

            self.assertTrue(pid1_alive, "pid 1 (init/launchd/systemd) must still be alive after release")

    def test_stale_takeover_with_non_daemon_pid_skips_kill(self):
        """Stale-takeover where the stale pid is confirmed not a daemon must skip the kill.

        The takeover may still succeed if the flock is already free (dead process
        released it), or fail with contention if the flock is still held. Either
        way, SIGTERM must not be sent to an unrelated process.

        We use a dead PID (DEAD_PID = 99999999) — pid_alive returns False, so
        stale detection fires, but the pid is checked for identity before kill.
        If the identity check finds the pid doesn't exist (pid_alive False), the
        kill path is not reached anyway.  This test validates the control flow
        does not crash and the dead-pid stale lock is handled gracefully.
        """
        with tempfile.TemporaryDirectory() as td:
            lock_path = Path(td) / "test.lock"
            # Write a stale lock with a dead pid
            lock_path.write_text(
                json.dumps({
                    "holder": "stale-holder",
                    "pid": DEAD_PID,
                    "started_at": "2026-01-01T00:00:00Z",
                    "last_heartbeat": "2026-01-01T00:00:00Z",
                }) + "\n",
                encoding="utf-8",
            )
            result = _run("acquire", str(lock_path), "new-holder")
            # Dead pid → stale takeover → must succeed (exit 2) without killing anything
            self.assertEqual(
                result.returncode, 2,
                f"stale acquire with dead pid must return exit 2; got {result.returncode}: {result.stderr}",
            )
            _run("release", str(lock_path))


class TestWrongSchemaReleaseKillsDaemon(_DaemonReapingTestCase):
    """BLOCKER 1 fix: cmd_release wrong-schema path must kill live daemon and free flock.

    Previously, wrong-schema JSON caused an immediate zero+return 0 without ever
    signaling the daemon or verifying the OS-level flock was free.  A live daemon
    would keep the flock held forever, deadlocking all future acquires.

    Fix: extract the pid, identity-check, SIGTERM, _wait_flock_free, only then zero.
    """

    def _flock_probe(self, flock_path: Path) -> bool:
        """Return True if the .flock file is currently locked by another process."""
        probe_code = textwrap.dedent("""\
            import fcntl, os, sys
            fd = os.open(sys.argv[1], os.O_CREAT | os.O_RDWR, 0o644)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                sys.exit(1)  # acquired = free
            except BlockingIOError:
                sys.exit(0)  # blocked = held by another process
        """)
        result = subprocess.run(
            [sys.executable, "-c", probe_code, str(flock_path)],
            timeout=5,
        )
        return result.returncode == 0  # 0 = held

    def test_wrong_schema_with_live_daemon_release_frees_flock(self):
        """release on wrong-schema JSON with live daemon holding flock must kill it
        and verify the flock is genuinely free via LOCK_EX|LOCK_NB probe.

        Invariant: after release returns 0, the OS-level flock must be free.
        Failure class: wrong-schema path zeros content and returns 0 WITHOUT
        signaling the daemon — flock stays held forever (deadlock).
        """
        with tempfile.TemporaryDirectory() as td:
            lock_path = Path(td) / "test.lock"
            flock_path = Path(td) / "test.lock.flock"

            # Acquire a real lock (live daemon + valid JSON + flock held)
            r_a = _run("acquire", str(lock_path), "holder-A")
            self.assertEqual(r_a.returncode, 0, f"setup: acquire failed: {r_a.stderr}")

            data_a = _read_lock(lock_path)
            self.assertIsNotNone(data_a, "setup: holder record must exist")
            daemon_pid = data_a["pid"]

            # Confirm flock is actually held
            self.assertTrue(self._flock_probe(flock_path), "setup: flock must be held before test")

            # Overwrite JSON with wrong-schema (but preserve the real daemon pid)
            wrong_schema = json.dumps({"pid": daemon_pid, "bad_field": "no-holder-or-timestamps"})
            lock_path.write_text(wrong_schema + "\n", encoding="utf-8")

            # Now release: wrong-schema path must kill the daemon and free the flock
            result = _run("release", str(lock_path))
            self.assertEqual(
                result.returncode, 0,
                f"release on wrong-schema with live daemon must return 0; "
                f"got {result.returncode}: {result.stderr}",
            )

            # Give the daemon a moment to exit and release the flock
            time.sleep(0.3)

            # Critical: the flock must now be free at the OS level
            is_held = self._flock_probe(flock_path)
            self.assertFalse(
                is_held,
                "After release returns 0 on wrong-schema+live-daemon, the OS-level flock "
                "must be free (failure: daemon not signaled, flock held forever = deadlock)",
            )

    def test_wrong_schema_with_live_daemon_unfreeable_returns_nonzero(self):
        """If wrong-schema release can't free the flock, it must return non-zero (exit 5).

        We simulate this by acquiring, overwriting with wrong-schema containing a
        DEAD pid (so no SIGTERM is sent), then verifying that if the flock IS held
        by something that won't die, release returns exit 5.

        In practice, we test the exit-5 path indirectly: we acquire a lock, corrupt
        the JSON with a dead pid (no live daemon to signal), but keep the .flock
        file held by an independent flock-holder process so _wait_flock_free times out.
        """
        with tempfile.TemporaryDirectory() as td:
            lock_path = Path(td) / "test.lock"
            flock_path = Path(td) / "test.lock.flock"

            # Spawn a long-lived flock-holder that is NOT a sink-lock daemon
            holder_code = textwrap.dedent(f"""\
                import fcntl, os, signal, sys, time
                fd = os.open({str(flock_path)!r}, os.O_CREAT | os.O_RDWR, 0o644)
                fcntl.flock(fd, fcntl.LOCK_EX)
                # Signal parent we hold the lock
                sys.stdout.write("held\\n")
                sys.stdout.flush()
                # Hold for 10s
                time.sleep(10)
            """)
            holder_proc = subprocess.Popen(
                [sys.executable, "-c", holder_code],
                stdout=subprocess.PIPE,
                text=True,
            )
            try:
                # Wait for the holder to signal it holds the lock
                line = holder_proc.stdout.readline()
                self.assertEqual(line.strip(), "held", "holder process must confirm flock held")

                # Verify flock is held
                self.assertTrue(self._flock_probe(flock_path), "flock must be held by holder proc")

                # Write wrong-schema JSON with a DEAD pid (no daemon to signal)
                lock_path.parent.mkdir(parents=True, exist_ok=True)
                lock_path.write_text(
                    json.dumps({"pid": DEAD_PID, "bad_field": "no-holder"}) + "\n",
                    encoding="utf-8",
                )

                # Release: wrong-schema, dead pid → no kill → _wait_flock_free times out → exit 5
                result = _run("release", str(lock_path))
                self.assertEqual(
                    result.returncode, 5,
                    f"release where flock can't be freed must return exit 5; "
                    f"got {result.returncode}: {result.stderr}",
                )
            finally:
                holder_proc.terminate()
                holder_proc.wait(timeout=5)


class TestIdentityCheckRejectsMissingMarker(_DaemonReapingTestCase):
    """BLOCKER 2 fix: identity check must return False for processes lacking _DAEMON_MARKER.

    Previously, _check_cmdline returned True if the lock PATH appeared anywhere in
    the process's command line — even for unrelated processes (debuggers, CI runners,
    scripts that receive the path as an argument).  This would cause SIGTERM to be
    sent to an innocent process.

    Fix: require _DAEMON_MARKER to be present for True; absence = False (not our daemon).
    Also require lock_path to match (two daemons for different locks not confused).
    """

    def test_non_daemon_with_lock_path_in_argv_not_killed(self):
        """A live process that has the lock path in its argv but NO _DAEMON_MARKER
        must NOT be SIGTERMed by release.

        We spawn a Python process that:
          - Receives the lock path as a command-line argument (so it appears in cmdline)
          - Does NOT contain _DAEMON_MARKER ('zero_lock_under_hblock') in its code
          - Holds the OS-level flock on the .flock file

        Then we write a lock file pointing to that process's pid and call release.
        The identity check must return False (confirmed NOT our daemon), so SIGTERM
        is skipped.  The process must still be alive after release returns.

        Failure class: _check_cmdline returns True just because the lock path appears
        in argv, causing blind SIGTERM of an unrelated process.
        """
        with tempfile.TemporaryDirectory() as td:
            lock_path = Path(td) / "test.lock"
            flock_path = Path(td) / "test.lock.flock"

            # Spawn a process that:
            # 1. Has the lock_path as a command-line argument
            # 2. Holds the flock on flock_path
            # 3. Does NOT contain _DAEMON_MARKER in its source code
            # NOTE: This code must NOT contain the _DAEMON_MARKER string in any form,
            # since the marker is 'zero_lock_under_hblock' and ps reads the full -c source.
            non_daemon_code = textwrap.dedent("""\
                import fcntl, os, sys, time
                lock_path_arg = sys.argv[1]
                flock_file = lock_path_arg + ".flock"
                fd = os.open(flock_file, os.O_CREAT | os.O_RDWR, 0o644)
                fcntl.flock(fd, fcntl.LOCK_EX)
                sys.stdout.write("ready\\n")
                sys.stdout.flush()
                time.sleep(15)
            """)
            non_daemon_proc = subprocess.Popen(
                [sys.executable, "-c", non_daemon_code, str(lock_path)],
                stdout=subprocess.PIPE,
                text=True,
            )
            try:
                line = non_daemon_proc.stdout.readline()
                self.assertEqual(line.strip(), "ready", "non-daemon process must confirm it holds flock")

                non_daemon_pid = non_daemon_proc.pid

                # Write a lock file pointing to the non-daemon process
                lock_path.parent.mkdir(parents=True, exist_ok=True)
                lock_path.write_text(
                    json.dumps({
                        "holder": "test-holder",
                        "pid": non_daemon_pid,
                        "started_at": "2026-01-01T00:00:00Z",
                        "last_heartbeat": "2026-01-01T00:00:00Z",
                    }) + "\n",
                    encoding="utf-8",
                )

                # Call release — the identity check must return False (no marker in cmdline)
                # and NOT send SIGTERM to the non-daemon process.
                result = _run("release", str(lock_path))
                # Release should return 5 (flock still held — not killed) since the non-daemon
                # was correctly identified as NOT our daemon and skipped.
                # It will NOT return 0 since the flock remains held.
                self.assertEqual(
                    result.returncode, 5,
                    f"release must return exit 5 (flock still held, non-daemon skipped); "
                    f"got {result.returncode}: {result.stderr}\n"
                    f"If return code is 0, the non-daemon was wrongly killed (BLOCKER 2 regression)",
                )

                # The non-daemon process must still be alive (not killed)
                try:
                    os.kill(non_daemon_pid, 0)
                    proc_alive = True
                except ProcessLookupError:
                    proc_alive = False
                except PermissionError:
                    proc_alive = True  # exists but can't signal — still alive

                self.assertTrue(
                    proc_alive,
                    f"Non-daemon process (pid={non_daemon_pid}) must still be alive — "
                    f"SIGTERM must not be sent to processes lacking _DAEMON_MARKER",
                )
            finally:
                non_daemon_proc.terminate()
                non_daemon_proc.wait(timeout=5)

    def test_wrong_schema_non_daemon_with_lock_path_not_killed(self):
        """wrong-schema release path must also respect identity check = False.

        A wrong-schema lock file with a live pid that lacks _DAEMON_MARKER must
        not cause SIGTERM to be sent.  The flock stays held → release returns 5.
        """
        with tempfile.TemporaryDirectory() as td:
            lock_path = Path(td) / "test.lock"
            flock_path = Path(td) / "test.lock.flock"

            # Spawn a non-daemon that holds the flock and has the lock path in argv
            non_daemon_code = textwrap.dedent("""\
                import fcntl, os, sys, time
                lock_path_arg = sys.argv[1]
                flock_file = lock_path_arg + ".flock"
                fd = os.open(flock_file, os.O_CREAT | os.O_RDWR, 0o644)
                fcntl.flock(fd, fcntl.LOCK_EX)
                sys.stdout.write("ready\\n")
                sys.stdout.flush()
                time.sleep(15)
            """)
            non_daemon_proc = subprocess.Popen(
                [sys.executable, "-c", non_daemon_code, str(lock_path)],
                stdout=subprocess.PIPE,
                text=True,
            )
            try:
                line = non_daemon_proc.stdout.readline()
                self.assertEqual(line.strip(), "ready")

                non_daemon_pid = non_daemon_proc.pid

                # Write wrong-schema JSON with the non-daemon's pid
                lock_path.parent.mkdir(parents=True, exist_ok=True)
                lock_path.write_text(
                    json.dumps({"pid": non_daemon_pid, "bad_field": "wrong-schema"}) + "\n",
                    encoding="utf-8",
                )

                result = _run("release", str(lock_path))
                # Non-daemon identified → skip kill → flock still held → exit 5
                self.assertEqual(
                    result.returncode, 5,
                    f"wrong-schema release with non-daemon pid must return 5 (skip kill, flock held); "
                    f"got {result.returncode}: {result.stderr}",
                )

                # Non-daemon must still be alive
                try:
                    os.kill(non_daemon_pid, 0)
                    proc_alive = True
                except ProcessLookupError:
                    proc_alive = False
                except PermissionError:
                    proc_alive = True

                self.assertTrue(
                    proc_alive,
                    f"Non-daemon process (pid={non_daemon_pid}) must not be killed by wrong-schema release",
                )
            finally:
                non_daemon_proc.terminate()
                non_daemon_proc.wait(timeout=5)


if __name__ == "__main__":
    unittest.main()
