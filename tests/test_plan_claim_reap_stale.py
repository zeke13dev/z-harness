"""
tests/test_plan_claim_reap_stale.py — pytest tests for plan-claim.sh reap-stale subcommand.

Cases covered:
  held    — lock is live (acquired by a live process) → stdout "held", exit 0
  free    — no lock file for the slug → stdout "free", exit 1
  stale   — lock held by a dead PID → stdout "stale", exit 2
  corrupt — lock file contains non-JSON garbage → stdout "corrupt", exit 3

Design:
  All tests call plan-claim.sh via subprocess so the full bash→sink-lock dispatch
  path is exercised.  Z_HARNESS_BASE_DIR is pointed at an isolated temp directory
  so lockpath() resolves there and tests are self-contained.

  For the "held" case: we use plan-claim.sh acquire (with --slug/--run-id/--session/
  --command) to establish a live lock, then call reap-stale and assert "held"/exit 0,
  then release via plan-claim.sh release.  We rely on the lock being acquired by
  the current process's PID (via sink-lock's daemon), which is live for the duration
  of the test.

  For "stale": we bypass plan-claim.sh and write a lock JSON directly with a dead PID
  (99999999) and an old heartbeat so sink-lock check-stale reports stale.

  For "corrupt": we write raw non-JSON bytes to the expected lock file path.

  Lock file path (mirroring lockpath() in plan-claim.sh):
    <Z_HARNESS_BASE_DIR>/active-plans/claims/<slug>.lock
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PLAN_CLAIM_SH = str(REPO_ROOT / "scripts" / "plan-claim.sh")
SINK_LOCK_SH = str(REPO_ROOT / "scripts" / "sink-lock.sh")

# A PID that is assumed to never exist on any reasonable system.
DEAD_PID = 99999999


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _claims_dir(base: Path) -> Path:
    """Return the claims directory under the given base (mirrors plan-path.sh)."""
    return base / "active-plans" / "claims"


def _lock_path(base: Path, slug: str) -> Path:
    return _claims_dir(base) / f"{slug}.lock"


def _write_lock_json(
    lock_path: Path,
    *,
    pid: int,
    holder: str = "test-holder",
    heartbeat: str = "2020-01-01T00:00:00Z",
) -> None:
    """Write a lock file JSON directly (bypassing flock; for test setup only)."""
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path.write_text(
        json.dumps({
            "holder": holder,
            "pid": pid,
            "started_at": "2020-01-01T00:00:00Z",
            "last_heartbeat": heartbeat,
        }) + "\n",
        encoding="utf-8",
    )
    # Touch the .flock sentinel so sink-lock can acquire the OS flock on it.
    sentinel = Path(str(lock_path) + ".flock")
    sentinel.touch()


def _base_env(base: Path) -> dict:
    """Return an env dict with Z_HARNESS_BASE_DIR pointing at the temp base."""
    return {
        **os.environ,
        "Z_HARNESS_BASE_DIR": str(base),
        # Disable claim-disable flag so tests hit real code paths.
        "Z_HARNESS_CLAIM_DISABLE": "",
    }


def _run_reap_stale(slug: str, base: Path, ttl: int | None = None) -> subprocess.CompletedProcess:
    """Run plan-claim.sh reap-stale --slug <slug> [--ttl N] with the given base."""
    cmd = ["bash", PLAN_CLAIM_SH, "reap-stale", f"--slug={slug}"]
    if ttl is not None:
        cmd.append(f"--ttl={ttl}")
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        env=_base_env(base),
    )


def _run_acquire(slug: str, base: Path, run_id: str = "run-test",
                 session: str = "sess-test", command: str = "z-test") -> subprocess.CompletedProcess:
    return subprocess.run(
        [
            "bash", PLAN_CLAIM_SH, "acquire",
            f"--slug={slug}",
            f"--run-id={run_id}",
            f"--session={session}",
            f"--command={command}",
        ],
        capture_output=True,
        text=True,
        env=_base_env(base),
    )


def _run_release(slug: str, base: Path, run_id: str = "run-test",
                 session: str = "sess-test", command: str = "z-test") -> subprocess.CompletedProcess:
    return subprocess.run(
        [
            "bash", PLAN_CLAIM_SH, "release",
            f"--slug={slug}",
            f"--run-id={run_id}",
            f"--session={session}",
            f"--command={command}",
        ],
        capture_output=True,
        text=True,
        env=_base_env(base),
    )


# ---------------------------------------------------------------------------
# test cases
# ---------------------------------------------------------------------------

class TestReapStaleHeld(unittest.TestCase):
    """Lock is live (acquired by the current test process) → "held", exit 0."""

    def setUp(self) -> None:
        self.tmpdir = tempfile.mkdtemp()
        self.base = Path(self.tmpdir)
        self.slug = "test-slug-held"

    def tearDown(self) -> None:
        # Best-effort release so the daemon subprocess doesn't linger.
        _run_release(self.slug, self.base)

    def test_held_exits_0(self) -> None:
        acq = _run_acquire(self.slug, self.base)
        self.assertIn(
            acq.returncode, (0, 2),
            f"acquire must succeed (0 or 2=stale-takeover). stderr={acq.stderr!r}",
        )

        result = _run_reap_stale(self.slug, self.base)
        self.assertEqual(
            result.returncode, 0,
            f"Expected exit 0 (held). stdout={result.stdout!r} stderr={result.stderr!r}",
        )

    def test_held_prints_held(self) -> None:
        acq = _run_acquire(self.slug, self.base)
        self.assertIn(acq.returncode, (0, 2))

        result = _run_reap_stale(self.slug, self.base)
        self.assertEqual(result.stdout.strip(), "held",
                         f"Expected stdout 'held'. got={result.stdout!r}")

    def test_held_is_readonly(self) -> None:
        """reap-stale must not release the lock; the lock file must still be held after."""
        acq = _run_acquire(self.slug, self.base)
        self.assertIn(acq.returncode, (0, 2))

        lp = _lock_path(self.base, self.slug)
        content_before = lp.read_text(encoding="utf-8") if lp.exists() else ""

        _run_reap_stale(self.slug, self.base)

        content_after = lp.read_text(encoding="utf-8") if lp.exists() else ""
        self.assertEqual(
            content_before, content_after,
            "reap-stale must not mutate the lock file",
        )


class TestReapStaleFree(unittest.TestCase):
    """No lock file exists for the slug → "free", exit 1."""

    def setUp(self) -> None:
        self.tmpdir = tempfile.mkdtemp()
        self.base = Path(self.tmpdir)
        self.slug = "test-slug-free"

    def test_free_exits_1(self) -> None:
        # No lock file at all for this slug.
        result = _run_reap_stale(self.slug, self.base)
        self.assertEqual(
            result.returncode, 1,
            f"Expected exit 1 (free). stdout={result.stdout!r} stderr={result.stderr!r}",
        )

    def test_free_prints_free(self) -> None:
        result = _run_reap_stale(self.slug, self.base)
        self.assertEqual(result.stdout.strip(), "free",
                         f"Expected stdout 'free'. got={result.stdout!r}")

    def test_empty_lock_file_is_free(self) -> None:
        """An empty (zeroed) lock file should be treated as free."""
        lp = _lock_path(self.base, self.slug)
        lp.parent.mkdir(parents=True, exist_ok=True)
        lp.write_text("", encoding="utf-8")
        sentinel = Path(str(lp) + ".flock")
        sentinel.touch()

        result = _run_reap_stale(self.slug, self.base)
        self.assertEqual(
            result.returncode, 1,
            f"Expected exit 1 (free) for empty lock. stdout={result.stdout!r}",
        )
        self.assertEqual(result.stdout.strip(), "free")


class TestReapStaleStale(unittest.TestCase):
    """Lock held by a dead PID → "stale", exit 2."""

    def setUp(self) -> None:
        self.tmpdir = tempfile.mkdtemp()
        self.base = Path(self.tmpdir)
        self.slug = "test-slug-stale"

    def test_stale_dead_pid_exits_2(self) -> None:
        lp = _lock_path(self.base, self.slug)
        _write_lock_json(lp, pid=DEAD_PID, heartbeat="2020-01-01T00:00:00Z")

        result = _run_reap_stale(self.slug, self.base)
        self.assertEqual(
            result.returncode, 2,
            f"Expected exit 2 (stale) for dead-PID lock. stdout={result.stdout!r} stderr={result.stderr!r}",
        )

    def test_stale_dead_pid_prints_stale(self) -> None:
        lp = _lock_path(self.base, self.slug)
        _write_lock_json(lp, pid=DEAD_PID, heartbeat="2020-01-01T00:00:00Z")

        result = _run_reap_stale(self.slug, self.base)
        self.assertEqual(result.stdout.strip(), "stale",
                         f"Expected stdout 'stale'. got={result.stdout!r}")

    def test_stale_expired_heartbeat_exits_2(self) -> None:
        """A live-ish PID (current process) with an old heartbeat and short TTL → stale."""
        lp = _lock_path(self.base, self.slug)
        # Use current process PID but a heartbeat far in the past
        _write_lock_json(lp, pid=os.getpid(), heartbeat="2020-01-01T00:00:00Z")

        # TTL of 1 second; the heartbeat is years old → stale
        result = _run_reap_stale(self.slug, self.base, ttl=1)
        self.assertEqual(
            result.returncode, 2,
            f"Expected exit 2 (stale) for expired heartbeat. stdout={result.stdout!r} stderr={result.stderr!r}",
        )
        self.assertEqual(result.stdout.strip(), "stale")

    def test_stale_is_readonly(self) -> None:
        """reap-stale must not modify the lock file when reporting stale."""
        lp = _lock_path(self.base, self.slug)
        _write_lock_json(lp, pid=DEAD_PID, heartbeat="2020-01-01T00:00:00Z")
        content_before = lp.read_text(encoding="utf-8")

        _run_reap_stale(self.slug, self.base)

        content_after = lp.read_text(encoding="utf-8")
        self.assertEqual(
            content_before, content_after,
            "reap-stale must not mutate the lock file even when stale",
        )


class TestReapStaleCorrupt(unittest.TestCase):
    """Lock file contains non-JSON garbage → "corrupt", exit 3."""

    def setUp(self) -> None:
        self.tmpdir = tempfile.mkdtemp()
        self.base = Path(self.tmpdir)
        self.slug = "test-slug-corrupt"

    def _write_corrupt(self, content: str = "NOT VALID JSON {{{") -> None:
        lp = _lock_path(self.base, self.slug)
        lp.parent.mkdir(parents=True, exist_ok=True)
        lp.write_text(content, encoding="utf-8")
        sentinel = Path(str(lp) + ".flock")
        sentinel.touch()

    def test_corrupt_exits_3(self) -> None:
        self._write_corrupt()
        result = _run_reap_stale(self.slug, self.base)
        self.assertEqual(
            result.returncode, 3,
            f"Expected exit 3 (corrupt). stdout={result.stdout!r} stderr={result.stderr!r}",
        )

    def test_corrupt_prints_corrupt(self) -> None:
        self._write_corrupt()
        result = _run_reap_stale(self.slug, self.base)
        self.assertEqual(result.stdout.strip(), "corrupt",
                         f"Expected stdout 'corrupt'. got={result.stdout!r}")

    def test_corrupt_partial_json_exits_3(self) -> None:
        """Truncated JSON (non-empty but JSON-unparseable) must produce 'corrupt'/exit 3."""
        lp = _lock_path(self.base, self.slug)
        lp.parent.mkdir(parents=True, exist_ok=True)
        # Truncated at the opening brace — valid UTF-8, non-empty, but unparseable JSON.
        lp.write_text('{"holder": "x", "pid": 123, "star', encoding="utf-8")
        sentinel = Path(str(lp) + ".flock")
        sentinel.touch()

        result = _run_reap_stale(self.slug, self.base)
        self.assertEqual(
            result.returncode, 3,
            f"Expected exit 3 (corrupt) for truncated JSON. stdout={result.stdout!r}",
        )
        self.assertEqual(result.stdout.strip(), "corrupt")


class TestReapStaleArgValidation(unittest.TestCase):
    """Missing or invalid arguments should exit with code 2."""

    def setUp(self) -> None:
        self.tmpdir = tempfile.mkdtemp()
        self.base = Path(self.tmpdir)

    def test_missing_slug_exits_2(self) -> None:
        result = subprocess.run(
            ["bash", PLAN_CLAIM_SH, "reap-stale"],
            capture_output=True,
            text=True,
            env=_base_env(self.base),
        )
        self.assertEqual(result.returncode, 2,
                         f"Expected exit 2 (missing --slug). stderr={result.stderr!r}")

    def test_slash_in_slug_exits_2(self) -> None:
        result = subprocess.run(
            ["bash", PLAN_CLAIM_SH, "reap-stale", "--slug=../../etc/passwd"],
            capture_output=True,
            text=True,
            env=_base_env(self.base),
        )
        self.assertEqual(result.returncode, 2,
                         f"Expected exit 2 (invalid slug with /). stderr={result.stderr!r}")


if __name__ == "__main__":
    unittest.main()
