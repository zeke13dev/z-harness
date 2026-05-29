"""
tests/test_followup_next_heartbeat.py — Integration test for the heartbeat loop
described in z-followup-next.md Phase 5.

Test scenario:
  1. Create a temp lock dir + lock file.
  2. Acquire the lock via sink-lock.sh acquire.
  3. Start a heartbeat-loop subprocess (1s sleep instead of 30s) that calls
     sink-lock.sh heartbeat in a shell background loop.
  4. Record capture_time immediately after the heartbeat loop starts.
  5. Wait 3 seconds.
  6. Read the lock JSON; assert last_heartbeat > capture_time + 1s.
  7. Kill heartbeat subprocess; release lock.

This verifies:
  - The heartbeat loop actually fires (last_heartbeat advances).
  - The lock JSON is updated atomically by heartbeat without corruption.
  - After kill + release, the lock file is empty (released state).
"""

import json
import os
import signal
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SINK_LOCK = str(REPO_ROOT / "scripts" / "sink-lock.sh")


def _run_lock(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", SINK_LOCK] + list(args),
        capture_output=True,
        text=True,
    )


def _read_lock_json(lock_path: Path) -> dict:
    content = lock_path.read_text(encoding="utf-8").strip()
    return json.loads(content)


def _iso_to_epoch(ts: str) -> float:
    from datetime import datetime, timezone
    dt = datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    return dt.timestamp()


class TestHeartbeatLoop(unittest.TestCase):
    """Verify the heartbeat loop advances last_heartbeat while running."""

    def test_heartbeat_advances_last_heartbeat(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            lock_path = Path(tmpdir) / "pages" / "test-entry.lock"
            lock_path.parent.mkdir(parents=True, exist_ok=True)

            # Step 1: Acquire the lock
            result = _run_lock("acquire", str(lock_path), "test-heartbeat-holder")
            self.assertIn(result.returncode, (0, 2),
                          f"acquire failed: {result.stderr}")

            # Verify the lock file was written
            self.assertTrue(lock_path.exists(), "Lock file must exist after acquire")
            lock_data = _read_lock_json(lock_path)
            self.assertIn("last_heartbeat", lock_data)

            # Step 2: Start heartbeat loop with 1s sleep (instead of 30s) for test speed.
            # This mirrors the Phase 5 bash snippet from z-followup-next.md, using a
            # 1s sleep so we can observe advancement within a 3s window.
            heartbeat_script = (
                f"while true; do "
                f"  sleep 1; "
                f"  bash '{SINK_LOCK}' heartbeat '{lock_path}' >/dev/null 2>&1 || break; "
                f"done"
            )
            heartbeat_proc = subprocess.Popen(
                ["bash", "-c", heartbeat_script],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

            # Step 3: Record capture_time just after loop starts
            capture_time = time.time()

            # Step 4: Wait 3 seconds for at least two heartbeat cycles
            time.sleep(3)

            # Step 5: Read lock JSON and check last_heartbeat advanced
            self.assertTrue(lock_path.exists(), "Lock file must still exist after 3s")
            lock_data_after = _read_lock_json(lock_path)
            self.assertIn("last_heartbeat", lock_data_after)

            last_hb_epoch = _iso_to_epoch(lock_data_after["last_heartbeat"])
            # last_heartbeat must be at least 1 second after capture_time
            self.assertGreater(
                last_hb_epoch,
                capture_time + 1.0,
                f"Expected last_heartbeat > capture_time+1s, "
                f"got last_heartbeat={lock_data_after['last_heartbeat']} "
                f"capture_time={capture_time:.3f}",
            )

            # Step 6: Kill heartbeat subprocess (mirrors Phase 9 kill $HEARTBEAT_PID)
            heartbeat_proc.terminate()
            try:
                heartbeat_proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                heartbeat_proc.kill()
                heartbeat_proc.wait()

            # Step 7: Release the lock (mirrors Phase 9 sink-lock.sh release)
            release_result = _run_lock("release", str(lock_path))
            self.assertEqual(release_result.returncode, 0,
                             f"release failed: {release_result.stderr}")

            # After release, lock file content must be empty (zeroed)
            released_content = lock_path.read_text(encoding="utf-8").strip()
            self.assertEqual(released_content, "",
                             "Lock file must be empty after release")

    def test_heartbeat_exits_when_lock_released(self):
        """Verify the heartbeat loop exits cleanly (exit 1) when the lock is released
        externally, matching the '|| break' guard in the Phase 5 snippet."""
        with tempfile.TemporaryDirectory() as tmpdir:
            lock_path = Path(tmpdir) / "pages" / "test-entry2.lock"
            lock_path.parent.mkdir(parents=True, exist_ok=True)

            # Acquire
            result = _run_lock("acquire", str(lock_path), "test-early-release")
            self.assertIn(result.returncode, (0, 2),
                          f"acquire failed: {result.stderr}")

            # Start heartbeat with 1s sleep
            heartbeat_script = (
                f"while true; do "
                f"  sleep 1; "
                f"  bash '{SINK_LOCK}' heartbeat '{lock_path}' >/dev/null 2>&1 || break; "
                f"done"
            )
            heartbeat_proc = subprocess.Popen(
                ["bash", "-c", heartbeat_script],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

            # Release lock externally (simulates stale-takeover or early teardown)
            time.sleep(0.5)
            release_result = _run_lock("release", str(lock_path))
            self.assertEqual(release_result.returncode, 0)

            # Heartbeat loop should exit on its own within ~3s (1s sleep + heartbeat call)
            try:
                heartbeat_proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                heartbeat_proc.kill()
                heartbeat_proc.wait()
                self.fail("Heartbeat loop did not exit after lock was released")

            # Process should have exited naturally (any exit code is acceptable — the
            # important thing is it terminated without being explicitly killed)
            self.assertIsNotNone(heartbeat_proc.returncode,
                                 "Heartbeat process should have a return code")


if __name__ == "__main__":
    unittest.main()
