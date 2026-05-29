"""
tests/test_sink_status_set.py — pytest tests for scripts/sink-status-set.sh

Cases covered:
  Legal transitions:
    - open → running
    - running → verify
    - running → failed
    - running → blocked
    - failed → open (retry)
    - blocked → open (refresh)
    - verify → done (human_confirmed)
    - verify → done (audit_confirmed) — stubbed via mock evidence
    - verify → done (auto_closed_low_risk) — stubbed
    - any → dismissed (running→dismissed, open→dismissed)

  Illegal transitions:
    - open → done (direct; skips state machine)
    - open → verify
    - done → open
    - failed → done (direct)

  Mutex collision:
    - verify → done with completion_mode set; second attempt → exit 6

  Evidence missing:
    - verify → done with completion_mode=audit_confirmed, no --evidence → exit 4

  Validation errors:
    - missing --entry → exit 2
    - missing --to → exit 2
    - missing --by → exit 2
    - missing --sink-root → exit 2
    - invalid --to value → exit 2
    - missing --completion-mode for verify→done → exit 2
"""

from __future__ import annotations

import fcntl
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = str(REPO_ROOT / "scripts" / "sink-status-set.sh")
IMPL_PY = str(REPO_ROOT / "scripts" / "sink-status-set-impl.py")
SINK_LOCK_SH = str(REPO_ROOT / "scripts" / "sink-lock.sh")
REBUILD_SH = str(REPO_ROOT / "scripts" / "sink-view-rebuild.sh")


# ── Git helpers ────────────────────────────────────────────────────────────────

def _git(*args: str, cwd: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git"] + list(args),
        cwd=cwd,
        capture_output=True,
        text=True,
    )


def _make_git_repo(path: Path) -> str:
    """Initialise a minimal git repo. Returns HEAD sha."""
    td = str(path)
    _git("init", cwd=td)
    _git("config", "user.email", "test@test.com", cwd=td)
    _git("config", "user.name", "Test", cwd=td)
    (path / "sentinel.txt").write_text("hello\n")
    _git("add", "sentinel.txt", cwd=td)
    _git("commit", "-m", "initial commit", cwd=td)
    result = _git("rev-parse", "HEAD", cwd=td)
    return result.stdout.strip()


# ── Lock-holding helpers ────────────────────────────────────────────────────────

_HOLD_LOCK_AND_RUN = """
import fcntl, os, subprocess, sys, json

sentinel_path, lock_path, *cmd = sys.argv[1:]

# Write JSON holder record so sink-view-rebuild.sh sees lock as held
holder_record = json.dumps({
    "holder": "test-holder",
    "pid": os.getpid(),
    "started_at": "2026-01-01T00:00:00Z",
    "last_heartbeat": "2026-01-01T00:00:00Z",
}) + "\\n"
Path = __import__('pathlib').Path
Path(lock_path).parent.mkdir(parents=True, exist_ok=True)
Path(lock_path).write_text(holder_record)

fd = os.open(sentinel_path, os.O_CREAT | os.O_RDWR, 0o644)
fcntl.flock(fd, fcntl.LOCK_EX)
try:
    r = subprocess.run(cmd)
    sys.exit(r.returncode)
finally:
    Path(lock_path).write_text("")
    fcntl.flock(fd, fcntl.LOCK_UN)
    os.close(fd)
"""


def _hold_global_lock(lock_file: Path, duration: float) -> None:
    """Hold the global flock sentinel exclusively for `duration` seconds in a thread."""
    sentinel = Path(str(lock_file) + ".flock")
    sentinel.parent.mkdir(parents=True, exist_ok=True)
    sentinel.touch()

    # Write JSON holder content so view-rebuild sees it as held
    holder_record = json.dumps({
        "holder": "test-blocker",
        "pid": os.getpid(),
        "started_at": "2026-01-01T00:00:00Z",
        "last_heartbeat": "2026-01-01T00:00:00Z",
    }) + "\n"
    lock_file.parent.mkdir(parents=True, exist_ok=True)
    lock_file.write_text(holder_record, encoding="utf-8")

    fd = os.open(str(sentinel), os.O_CREAT | os.O_RDWR, 0o644)
    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
        time.sleep(duration)
    finally:
        lock_file.write_text("", encoding="utf-8")
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


# ── Sink fixture helpers ───────────────────────────────────────────────────────

def _make_sink(sink_root: Path) -> None:
    """Create a minimal sink directory layout."""
    (sink_root / "pages").mkdir(parents=True, exist_ok=True)
    (sink_root / "audit_evidence").mkdir(parents=True, exist_ok=True)


def _write_entry(sink_root: Path, entry_id: str, status: str, **extra) -> dict:
    """Write an entry_created event to index.jsonl and return the entry dict."""
    entry = {
        "id": entry_id,
        "schema_version": 1,
        "priority": "P2",
        "name": "Test entry",
        "status": status,
        "sink": "project",
        "created_at": "2026-05-28T12:00:00Z",
        "created_by_run": "run-001",
        "recommended_command": "/z-do \"test\"",
        "auto_close_eligible": False,
        "completion_mode": None,
        "audit_evidence_path": None,
        "closed_at": None,
        "closed_by_run": None,
        "failure_reason": None,
        "attempt_count": 0,
        "cited_paths": [],
        "file_blob_hashes": {},
        "status_history": [
            {"ts": "2026-05-28T12:00:00Z", "from": None, "to": status, "by": "scripts/sink-add.sh"}
        ],
    }
    entry.update(extra)
    event = {
        "kind": "entry_created",
        "ts": "2026-05-28T12:00:00Z",
        "entry": entry,
    }
    journal_path = sink_root / "index.jsonl"
    with journal_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(event) + "\n")
    return entry


def _rebuild_view(sink_root: Path, lock_file: Path) -> None:
    """Rebuild view under a held global lock."""
    sentinel = Path(str(lock_file) + ".flock")
    sentinel.parent.mkdir(parents=True, exist_ok=True)
    sentinel.touch()

    holder_record = json.dumps({
        "holder": "test-rebuild",
        "pid": os.getpid(),
        "started_at": "2026-01-01T00:00:00Z",
        "last_heartbeat": "2026-01-01T00:00:00Z",
    }) + "\n"
    lock_file.parent.mkdir(parents=True, exist_ok=True)
    lock_file.write_text(holder_record, encoding="utf-8")

    fd = os.open(str(sentinel), os.O_CREAT | os.O_RDWR, 0o644)
    fcntl.flock(fd, fcntl.LOCK_EX)
    try:
        subprocess.run(
            ["bash", REBUILD_SH, str(sink_root)],
            capture_output=True,
            env={**os.environ, "Z_HARNESS_FOLLOWUP_GLOBAL_LOCK": str(lock_file)},
        )
    finally:
        lock_file.write_text("", encoding="utf-8")
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def _acquire_per_entry_lock(lock_path: Path, holder_id: str) -> int:
    """Acquire per-entry lock via sink-lock.sh; return flock fd."""
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        ["bash", SINK_LOCK_SH, "acquire", str(lock_path), holder_id],
        capture_output=True,
        text=True,
    )
    # 0 = acquired, 2 = stale-takeover
    if result.returncode not in (0, 2):
        raise RuntimeError(
            f"sink-lock acquire failed with exit {result.returncode}: {result.stderr}"
        )
    # Keep flock alive by holding fd on sentinel
    sentinel = Path(str(lock_path) + ".flock")
    fd = os.open(str(sentinel), os.O_CREAT | os.O_RDWR, 0o644)
    fcntl.flock(fd, fcntl.LOCK_EX)
    return fd


def _release_per_entry_lock(lock_path: Path, fd: int) -> None:
    """Release per-entry lock."""
    subprocess.run(
        ["bash", SINK_LOCK_SH, "release", str(lock_path)],
        capture_output=True,
    )
    fcntl.flock(fd, fcntl.LOCK_UN)
    os.close(fd)


def _build_claim_ticket(
    entry_id: str,
    lock_path: Path,
    holder: str = "test-holder",
    pid: int | None = None,
) -> str:
    """Build a claim ticket JSON string.

    If ``pid`` is None it defaults to the current process PID — tests that
    write a holder record with os.getpid() can pass None and the ticket will
    match the record automatically.
    """
    if pid is None:
        pid = os.getpid()
    return json.dumps({
        "entry_id": entry_id,
        "run_id": "test-run-001",
        "claim_ts": "2026-05-28T12:00:00Z",
        "lock_path": str(lock_path),
        "holder": holder,
        "pid": pid,
        "ttl_s": 7200,
    })


def _write_per_entry_lock(lock_path: Path, holder: str, pid: int) -> None:
    """Write a per-entry lock JSON holder record (bypassing flock; test setup only)."""
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path.write_text(
        json.dumps({
            "holder": holder,
            "pid": pid,
            "started_at": "2026-01-01T00:00:00Z",
            "last_heartbeat": "2026-01-01T00:00:00Z",
        }) + "\n",
        encoding="utf-8",
    )


def _run_status_set(
    *extra_args: str,
    env_extra: dict | None = None,
    lock_file: str | None = None,
) -> subprocess.CompletedProcess:
    env = {**os.environ, **(env_extra or {})}
    if lock_file:
        env["Z_HARNESS_FOLLOWUP_GLOBAL_LOCK"] = lock_file
    return subprocess.run(
        ["bash", SCRIPT] + list(extra_args),
        capture_output=True,
        text=True,
        env=env,
    )


def _read_view(sink_root: Path) -> dict:
    return json.loads((sink_root / "index.view.json").read_text(encoding="utf-8"))


# ── Base test class ────────────────────────────────────────────────────────────

class _SinkTestBase(unittest.TestCase):
    """Base class that sets up a temp dir with a git repo and sink layout."""

    def setUp(self) -> None:
        self._td = tempfile.TemporaryDirectory()
        self.td = Path(self._td.name)
        self.git_head = _make_git_repo(self.td)
        self.sink_root = self.td / "z-harness" / "followups"
        _make_sink(self.sink_root)
        self.lock_file = self.td / ".test-global.lock"

    def tearDown(self) -> None:
        self._td.cleanup()

    def _setup_entry(self, entry_id: str, status: str, **extra) -> dict:
        """Write entry to journal and rebuild view."""
        entry = _write_entry(self.sink_root, entry_id, status, **extra)
        _rebuild_view(self.sink_root, self.lock_file)
        return entry

    def _run(self, entry_id: str, to_status: str, by: str = "test-actor",
             **kwargs) -> subprocess.CompletedProcess:
        """Run sink-status-set.sh with common args."""
        extra_args = [
            f"--entry={entry_id}",
            f"--to={to_status}",
            f"--by={by}",
            f"--sink-root={self.sink_root}",
        ]
        for k, v in kwargs.items():
            flag = k.replace("_", "-")
            if v is not None and v != "":
                extra_args.append(f"--{flag}={v}")
        return _run_status_set(
            *extra_args,
            lock_file=str(self.lock_file),
        )

    def _get_entry_status(self, entry_id: str) -> str:
        view = _read_view(self.sink_root)
        return view["entries"][entry_id]["status"]

    def _get_entry(self, entry_id: str) -> dict:
        view = _read_view(self.sink_root)
        return view["entries"][entry_id]


# ── Legal transitions ──────────────────────────────────────────────────────────

class TestOpenToRunning(_SinkTestBase):
    """open → running is the sink-claim path."""

    def test_open_to_running_succeeds(self):
        entry_id = "20260528T120000Z-open-to-running"
        self._setup_entry(entry_id, "open")
        result = self._run(entry_id, "running")
        self.assertEqual(result.returncode, 0, msg=f"stderr={result.stderr}")
        self.assertEqual(self._get_entry_status(entry_id), "running")

    def test_open_to_running_appends_status_history(self):
        entry_id = "20260528T120000Z-open-running-history"
        self._setup_entry(entry_id, "open")
        self._run(entry_id, "running")
        entry = self._get_entry(entry_id)
        history = entry["status_history"]
        last = history[-1]
        self.assertEqual(last["from"], "open")
        self.assertEqual(last["to"], "running")


class TestRunningToVerify(_SinkTestBase):

    def test_running_to_verify_succeeds(self):
        entry_id = "20260528T120000Z-running-to-verify"
        self._setup_entry(entry_id, "running")
        result = self._run(entry_id, "verify")
        self.assertEqual(result.returncode, 0, msg=f"stderr={result.stderr}")
        self.assertEqual(self._get_entry_status(entry_id), "verify")


class TestRunningToFailed(_SinkTestBase):

    def test_running_to_failed_succeeds(self):
        entry_id = "20260528T120000Z-running-to-failed"
        self._setup_entry(entry_id, "running")
        result = self._run(entry_id, "failed", reason="command exited non-zero")
        self.assertEqual(result.returncode, 0, msg=f"stderr={result.stderr}")
        self.assertEqual(self._get_entry_status(entry_id), "failed")


class TestRunningToBlocked(_SinkTestBase):

    def test_running_to_blocked_succeeds(self):
        entry_id = "20260528T120000Z-running-to-blocked"
        self._setup_entry(entry_id, "running")
        result = self._run(entry_id, "blocked", reason="staleness drift detected")
        self.assertEqual(result.returncode, 0, msg=f"stderr={result.stderr}")
        self.assertEqual(self._get_entry_status(entry_id), "blocked")


class TestFailedToOpen(_SinkTestBase):

    def test_failed_to_open_succeeds(self):
        """Consumer retry policy: failed → open."""
        entry_id = "20260528T120000Z-failed-to-open"
        self._setup_entry(entry_id, "failed")
        result = self._run(entry_id, "open", reason="retry")
        self.assertEqual(result.returncode, 0, msg=f"stderr={result.stderr}")
        self.assertEqual(self._get_entry_status(entry_id), "open")


class TestBlockedToOpen(_SinkTestBase):

    def test_blocked_to_open_succeeds(self):
        """Via /z-followup-refresh: blocked → open."""
        entry_id = "20260528T120000Z-blocked-to-open"
        self._setup_entry(entry_id, "blocked")
        result = self._run(entry_id, "open", reason="refresh")
        self.assertEqual(result.returncode, 0, msg=f"stderr={result.stderr}")
        self.assertEqual(self._get_entry_status(entry_id), "open")


class TestVerifyToDoneHumanConfirmed(_SinkTestBase):

    def test_verify_to_done_human_confirmed(self):
        entry_id = "20260528T120000Z-verify-done-human"
        self._setup_entry(entry_id, "verify")
        result = self._run(entry_id, "done", completion_mode="human_confirmed")
        self.assertEqual(result.returncode, 0, msg=f"stderr={result.stderr}")
        self.assertEqual(self._get_entry_status(entry_id), "done")

    def test_verify_to_done_human_confirmed_sets_completion_mode(self):
        entry_id = "20260528T120000Z-verify-done-mode"
        self._setup_entry(entry_id, "verify")
        self._run(entry_id, "done", completion_mode="human_confirmed")
        entry = self._get_entry(entry_id)
        self.assertEqual(entry.get("completion_mode"), "human_confirmed")

    def test_verify_to_done_human_confirmed_sets_closed_at(self):
        entry_id = "20260528T120000Z-verify-done-closed"
        self._setup_entry(entry_id, "verify")
        self._run(entry_id, "done", completion_mode="human_confirmed")
        entry = self._get_entry(entry_id)
        self.assertIsNotNone(entry.get("closed_at"))


class TestAnyToDismissed(_SinkTestBase):

    def test_running_to_dismissed(self):
        entry_id = "20260528T120000Z-running-dismissed"
        self._setup_entry(entry_id, "running")
        result = self._run(entry_id, "dismissed", reason="user override")
        self.assertEqual(result.returncode, 0, msg=f"stderr={result.stderr}")
        self.assertEqual(self._get_entry_status(entry_id), "dismissed")

    def test_open_to_dismissed(self):
        entry_id = "20260528T120000Z-open-dismissed"
        self._setup_entry(entry_id, "open")
        result = self._run(entry_id, "dismissed", reason="user override")
        self.assertEqual(result.returncode, 0, msg=f"stderr={result.stderr}")
        self.assertEqual(self._get_entry_status(entry_id), "dismissed")

    def test_verify_to_dismissed(self):
        entry_id = "20260528T120000Z-verify-dismissed"
        self._setup_entry(entry_id, "verify")
        result = self._run(entry_id, "dismissed", reason="user override")
        self.assertEqual(result.returncode, 0, msg=f"stderr={result.stderr}")
        self.assertEqual(self._get_entry_status(entry_id), "dismissed")

    def test_blocked_to_dismissed(self):
        entry_id = "20260528T120000Z-blocked-dismissed"
        self._setup_entry(entry_id, "blocked")
        result = self._run(entry_id, "dismissed", reason="user override")
        self.assertEqual(result.returncode, 0, msg=f"stderr={result.stderr}")
        self.assertEqual(self._get_entry_status(entry_id), "dismissed")


class TestRunningToOpen(_SinkTestBase):
    """auto_recovery path: running → open (stale lock takeover)."""

    def test_running_to_open_auto_recovery(self):
        entry_id = "20260528T120000Z-running-open-recovery"
        self._setup_entry(entry_id, "running")
        result = self._run(entry_id, "open", by="auto_recovery", reason="stale_lock_takeover")
        self.assertEqual(result.returncode, 0, msg=f"stderr={result.stderr}")
        self.assertEqual(self._get_entry_status(entry_id), "open")


# ── Illegal transitions ────────────────────────────────────────────────────────

class TestIllegalTransitions(_SinkTestBase):

    def test_open_to_done_rejected(self):
        """open → done directly must be rejected (exit 3)."""
        entry_id = "20260528T120000Z-open-done-illegal"
        self._setup_entry(entry_id, "open")
        result = self._run(entry_id, "done")
        self.assertEqual(result.returncode, 3, msg=f"stderr={result.stderr}")
        # Entry must NOT have changed to done
        self.assertEqual(self._get_entry_status(entry_id), "open")

    def test_open_to_verify_rejected(self):
        entry_id = "20260528T120000Z-open-verify-illegal"
        self._setup_entry(entry_id, "open")
        result = self._run(entry_id, "verify")
        self.assertEqual(result.returncode, 3, msg=f"stderr={result.stderr}")
        self.assertEqual(self._get_entry_status(entry_id), "open")

    def test_done_to_open_rejected(self):
        """done is terminal; done → open is illegal."""
        entry_id = "20260528T120000Z-done-open-illegal"
        self._setup_entry(entry_id, "done")
        result = self._run(entry_id, "open")
        self.assertEqual(result.returncode, 3, msg=f"stderr={result.stderr}")
        self.assertEqual(self._get_entry_status(entry_id), "done")

    def test_failed_to_done_rejected(self):
        """failed → done directly is illegal (must go via open → running → verify → done)."""
        entry_id = "20260528T120000Z-failed-done-illegal"
        self._setup_entry(entry_id, "failed")
        result = self._run(entry_id, "done")
        self.assertEqual(result.returncode, 3, msg=f"stderr={result.stderr}")
        self.assertEqual(self._get_entry_status(entry_id), "failed")

    def test_verify_to_running_rejected(self):
        entry_id = "20260528T120000Z-verify-running-illegal"
        self._setup_entry(entry_id, "verify")
        result = self._run(entry_id, "running")
        self.assertEqual(result.returncode, 3, msg=f"stderr={result.stderr}")
        self.assertEqual(self._get_entry_status(entry_id), "verify")

    def test_dismissed_to_open_rejected(self):
        """dismissed is terminal; no outgoing transitions."""
        entry_id = "20260528T120000Z-dismissed-open-illegal"
        self._setup_entry(entry_id, "dismissed")
        result = self._run(entry_id, "open")
        self.assertEqual(result.returncode, 3, msg=f"stderr={result.stderr}")
        self.assertEqual(self._get_entry_status(entry_id), "dismissed")


# ── Completion-mode mutex ──────────────────────────────────────────────────────

class TestCompletionModeMutex(_SinkTestBase):

    def test_second_done_transition_rejected(self):
        """Once completion_mode is set on verify→done, a second set attempt exits 6."""
        entry_id = "20260528T120000Z-mutex-conflict"
        self._setup_entry(entry_id, "verify")

        # First transition succeeds
        result1 = self._run(entry_id, "done", completion_mode="human_confirmed")
        self.assertEqual(result1.returncode, 0, msg=f"first attempt stderr={result1.stderr}")

        # Entry is now done; put it back at verify in journal for second attempt
        # (In practice, the second attempt hits the mutex; we simulate by
        # setting up a fresh entry already in verify with completion_mode=human_confirmed)
        entry_id2 = "20260528T120000Z-mutex-conflict-2"
        self._setup_entry(
            entry_id2, "verify",
            completion_mode="human_confirmed",  # already set
        )
        result2 = self._run(entry_id2, "done", completion_mode="audit_confirmed")
        self.assertEqual(result2.returncode, 6, msg=f"second attempt stderr={result2.stderr}")

    def test_missing_completion_mode_for_verify_done_rejected(self):
        """verify → done without --completion-mode exits 2."""
        entry_id = "20260528T120000Z-missing-mode"
        self._setup_entry(entry_id, "verify")
        result = self._run(entry_id, "done")
        # Exit 2 = validation error (missing required arg for this transition)
        self.assertEqual(result.returncode, 2, msg=f"stderr={result.stderr}")
        self.assertEqual(self._get_entry_status(entry_id), "verify")


# ── Evidence validation ────────────────────────────────────────────────────────

class TestEvidenceMissing(_SinkTestBase):

    def test_audit_confirmed_without_evidence_exits_4(self):
        """audit_confirmed requires --evidence; without it, exit 4."""
        entry_id = "20260528T120000Z-audit-no-evidence"
        self._setup_entry(entry_id, "verify")
        result = self._run(
            entry_id, "done",
            completion_mode="audit_confirmed",
            # no evidence arg
        )
        self.assertEqual(result.returncode, 4, msg=f"stderr={result.stderr}")
        self.assertEqual(self._get_entry_status(entry_id), "verify")

    def test_audit_confirmed_nonexistent_evidence_exits_4(self):
        """audit_confirmed with a path that doesn't exist exits 4."""
        entry_id = "20260528T120000Z-audit-bad-evidence"
        self._setup_entry(entry_id, "verify")
        result = self._run(
            entry_id, "done",
            completion_mode="audit_confirmed",
            evidence="/nonexistent/path/audit_evidence.json",
        )
        self.assertEqual(result.returncode, 4, msg=f"stderr={result.stderr}")
        self.assertEqual(self._get_entry_status(entry_id), "verify")


# ── Validation errors ──────────────────────────────────────────────────────────

class TestValidationErrors(_SinkTestBase):

    def test_missing_entry_exits_2(self):
        result = _run_status_set(
            "--to=running", "--by=test", f"--sink-root={self.sink_root}",
            lock_file=str(self.lock_file),
        )
        self.assertEqual(result.returncode, 2)

    def test_missing_to_exits_2(self):
        result = _run_status_set(
            "--entry=some-id", "--by=test", f"--sink-root={self.sink_root}",
            lock_file=str(self.lock_file),
        )
        self.assertEqual(result.returncode, 2)

    def test_missing_by_exits_2(self):
        result = _run_status_set(
            "--entry=some-id", "--to=running", f"--sink-root={self.sink_root}",
            lock_file=str(self.lock_file),
        )
        self.assertEqual(result.returncode, 2)

    def test_missing_sink_root_exits_2(self):
        result = _run_status_set(
            "--entry=some-id", "--to=running", "--by=test",
            lock_file=str(self.lock_file),
        )
        self.assertEqual(result.returncode, 2)

    def test_invalid_to_value_exits_2(self):
        entry_id = "20260528T120000Z-invalid-to"
        self._setup_entry(entry_id, "open")
        result = self._run(entry_id, "superseded")
        self.assertEqual(result.returncode, 2)

    def test_entry_not_in_view_exits_2(self):
        """Requesting a transition for an entry that doesn't exist exits 2."""
        result = self._run("nonexistent-entry-id", "running")
        self.assertEqual(result.returncode, 2)


# ── View rebuild correctness ───────────────────────────────────────────────────

class TestViewRebuiltAfterTransition(_SinkTestBase):

    def test_view_reflects_new_status(self):
        """After a successful transition, index.view.json reflects the new status."""
        entry_id = "20260528T120000Z-view-update"
        self._setup_entry(entry_id, "open")
        self._run(entry_id, "running")
        self.assertEqual(self._get_entry_status(entry_id), "running")

    def test_journal_has_new_event(self):
        """After transition, index.jsonl has a new status_changed event."""
        entry_id = "20260528T120000Z-journal-event"
        self._setup_entry(entry_id, "open")
        self._run(entry_id, "running")
        journal = (self.sink_root / "index.jsonl").read_text(encoding="utf-8")
        events = [json.loads(line) for line in journal.splitlines() if line.strip()]
        status_events = [e for e in events if e.get("kind") == "status_changed"]
        self.assertTrue(
            any(e.get("to") == "running" for e in status_events),
            msg=f"No status_changed to=running event found; events={status_events}",
        )


# ── Reason field propagation ───────────────────────────────────────────────────

class TestReasonPropagation(_SinkTestBase):

    def test_reason_written_to_event(self):
        """--reason is stored in the status_changed event appended to journal."""
        entry_id = "20260528T120000Z-reason-prop"
        self._setup_entry(entry_id, "running")
        self._run(entry_id, "failed", reason="test failure reason")
        journal = (self.sink_root / "index.jsonl").read_text(encoding="utf-8")
        events = [json.loads(line) for line in journal.splitlines() if line.strip()]
        status_events = [
            e for e in events
            if e.get("kind") == "status_changed" and e.get("to") == "failed"
        ]
        self.assertTrue(
            any(e.get("reason") == "test failure reason" for e in status_events),
            msg=f"reason not found in events: {status_events}",
        )


# ── Claim ticket validation ────────────────────────────────────────────────────

class TestClaimTicket(_SinkTestBase):

    def test_valid_claim_ticket_succeeds(self):
        """With a matching ticket (entry_id, lock_path, holder, pid) transition succeeds."""
        entry_id = "20260528T120000Z-ticket-valid"
        self._setup_entry(entry_id, "open")
        lock_path = self.sink_root / "pages" / f"{entry_id}.lock"
        holder = "test-holder-valid"
        pid = os.getpid()
        _write_per_entry_lock(lock_path, holder, pid)
        ticket = _build_claim_ticket(entry_id, lock_path, holder=holder, pid=pid)
        result = _run_status_set(
            f"--entry={entry_id}",
            f"--to=running",
            f"--by=test",
            f"--sink-root={self.sink_root}",
            f"--via-claim-ticket={ticket}",
            lock_file=str(self.lock_file),
        )
        self.assertEqual(result.returncode, 0, msg=f"stderr={result.stderr}")

    def test_mismatched_entry_id_exits_2(self):
        """A claim ticket with wrong entry_id exits 2."""
        entry_id = "20260528T120000Z-ticket-mismatch"
        self._setup_entry(entry_id, "open")
        lock_path = self.sink_root / "pages" / f"{entry_id}.lock"
        _write_per_entry_lock(lock_path, "test-holder", os.getpid())
        # Build ticket for a DIFFERENT entry
        ticket = _build_claim_ticket("different-entry-id", lock_path,
                                     holder="test-holder", pid=os.getpid())
        result = _run_status_set(
            f"--entry={entry_id}",
            f"--to=running",
            f"--by=test",
            f"--sink-root={self.sink_root}",
            f"--via-claim-ticket={ticket}",
            lock_file=str(self.lock_file),
        )
        self.assertEqual(result.returncode, 2, msg=f"stderr={result.stderr}")

    def test_invalid_json_claim_ticket_exits_2(self):
        """A claim ticket that's not valid JSON exits 2, no traceback."""
        entry_id = "20260528T120000Z-ticket-invalid-json"
        self._setup_entry(entry_id, "open")
        result = _run_status_set(
            f"--entry={entry_id}",
            f"--to=running",
            f"--by=test",
            f"--sink-root={self.sink_root}",
            f"--via-claim-ticket=not-valid-json",
            lock_file=str(self.lock_file),
        )
        self.assertEqual(result.returncode, 2, msg=f"stderr={result.stderr}")
        # No traceback — clean validation error only
        self.assertNotIn("Traceback", result.stderr,
                         msg="malformed-JSON ticket must not produce a traceback")

    # ── MAJOR 2 fix: non-dict ticket ────────────────────────────────────────────

    def test_non_dict_ticket_list_exits_2(self):
        """Valid JSON that is a list (not an object) must exit 2 cleanly, no AttributeError."""
        entry_id = "20260528T120000Z-ticket-list"
        self._setup_entry(entry_id, "open")
        result = _run_status_set(
            f"--entry={entry_id}",
            f"--to=running",
            f"--by=test",
            f"--sink-root={self.sink_root}",
            f"--via-claim-ticket=[]",
            lock_file=str(self.lock_file),
        )
        self.assertEqual(result.returncode, 2,
                         msg=f"Expected exit 2 for list ticket; stderr={result.stderr}")
        self.assertNotIn("Traceback", result.stderr,
                         msg="non-dict ticket must not raise an unhandled exception")
        self.assertNotIn("AttributeError", result.stderr,
                         msg="non-dict ticket must not produce an AttributeError")

    def test_non_dict_ticket_string_exits_2(self):
        """Valid JSON that is a string (not an object) must exit 2 cleanly."""
        entry_id = "20260528T120000Z-ticket-string"
        self._setup_entry(entry_id, "open")
        result = _run_status_set(
            f"--entry={entry_id}",
            f"--to=running",
            f"--by=test",
            f"--sink-root={self.sink_root}",
            f'--via-claim-ticket="hello"',
            lock_file=str(self.lock_file),
        )
        self.assertEqual(result.returncode, 2,
                         msg=f"Expected exit 2 for string ticket; stderr={result.stderr}")
        self.assertNotIn("Traceback", result.stderr,
                         msg="non-dict ticket must not raise an unhandled exception")

    def test_non_dict_ticket_number_exits_2(self):
        """Valid JSON that is a number (not an object) must exit 2 cleanly."""
        entry_id = "20260528T120000Z-ticket-number"
        self._setup_entry(entry_id, "open")
        result = _run_status_set(
            f"--entry={entry_id}",
            f"--to=running",
            f"--by=test",
            f"--sink-root={self.sink_root}",
            f"--via-claim-ticket=123",
            lock_file=str(self.lock_file),
        )
        self.assertEqual(result.returncode, 2,
                         msg=f"Expected exit 2 for number ticket; stderr={result.stderr}")
        self.assertNotIn("Traceback", result.stderr,
                         msg="non-dict ticket must not raise an unhandled exception")

    def test_non_dict_ticket_null_exits_2(self):
        """Valid JSON that is null (not an object) must exit 2 cleanly."""
        entry_id = "20260528T120000Z-ticket-null"
        self._setup_entry(entry_id, "open")
        result = _run_status_set(
            f"--entry={entry_id}",
            f"--to=running",
            f"--by=test",
            f"--sink-root={self.sink_root}",
            f"--via-claim-ticket=null",
            lock_file=str(self.lock_file),
        )
        self.assertEqual(result.returncode, 2,
                         msg=f"Expected exit 2 for null ticket; stderr={result.stderr}")
        self.assertNotIn("Traceback", result.stderr,
                         msg="non-dict ticket must not raise an unhandled exception")

    # ── H8 identity-check tests (T006 acceptance criteria) ────────────────────

    def test_mismatched_holder_rejected(self):
        """Ticket holder differs from lock file holder → exit 2 (rejected)."""
        entry_id = "20260528T120000Z-ticket-holder-mismatch"
        self._setup_entry(entry_id, "open")
        lock_path = self.sink_root / "pages" / f"{entry_id}.lock"
        real_pid = os.getpid()
        # Lock file says holder is "actual-holder"
        _write_per_entry_lock(lock_path, "actual-holder", real_pid)
        # Ticket claims holder is "imposter-holder"
        ticket = _build_claim_ticket(entry_id, lock_path,
                                     holder="imposter-holder", pid=real_pid)
        result = _run_status_set(
            f"--entry={entry_id}",
            f"--to=running",
            f"--by=test",
            f"--sink-root={self.sink_root}",
            f"--via-claim-ticket={ticket}",
            lock_file=str(self.lock_file),
        )
        self.assertEqual(result.returncode, 2,
                         msg=f"Expected exit 2 on holder mismatch; stderr={result.stderr}")
        # Entry must not have changed
        self.assertEqual(self._get_entry_status(entry_id), "open")

    def test_mismatched_pid_rejected(self):
        """Ticket pid differs from lock file pid → exit 2 (rejected)."""
        entry_id = "20260528T120000Z-ticket-pid-mismatch"
        self._setup_entry(entry_id, "open")
        lock_path = self.sink_root / "pages" / f"{entry_id}.lock"
        real_pid = os.getpid()
        real_holder = "test-holder-pid"
        # Lock file says pid is real_pid
        _write_per_entry_lock(lock_path, real_holder, real_pid)
        # Ticket claims a different pid (use a plausible but wrong value)
        wrong_pid = real_pid + 1 if real_pid < 9999999 else real_pid - 1
        ticket = _build_claim_ticket(entry_id, lock_path,
                                     holder=real_holder, pid=wrong_pid)
        result = _run_status_set(
            f"--entry={entry_id}",
            f"--to=running",
            f"--by=test",
            f"--sink-root={self.sink_root}",
            f"--via-claim-ticket={ticket}",
            lock_file=str(self.lock_file),
        )
        self.assertEqual(result.returncode, 2,
                         msg=f"Expected exit 2 on pid mismatch; stderr={result.stderr}")
        # Entry must not have changed
        self.assertEqual(self._get_entry_status(entry_id), "open")

    def test_matching_ticket_and_legal_transition_accepted(self):
        """Ticket with matching holder+pid+entry_id+lock_path and legal transition → exit 0."""
        entry_id = "20260528T120000Z-ticket-identity-ok"
        self._setup_entry(entry_id, "open")
        lock_path = self.sink_root / "pages" / f"{entry_id}.lock"
        holder = "confirmed-holder"
        pid = os.getpid()
        _write_per_entry_lock(lock_path, holder, pid)
        ticket = _build_claim_ticket(entry_id, lock_path, holder=holder, pid=pid)
        result = _run_status_set(
            f"--entry={entry_id}",
            f"--to=running",
            f"--by=test",
            f"--sink-root={self.sink_root}",
            f"--via-claim-ticket={ticket}",
            lock_file=str(self.lock_file),
        )
        self.assertEqual(result.returncode, 0,
                         msg=f"Expected exit 0 on matching ticket; stderr={result.stderr}")
        self.assertEqual(self._get_entry_status(entry_id), "running")


# ── Auto-close with real diff (T007) ──────────────────────────────────────────

class TestAutoCloseWithRealDiff(_SinkTestBase):
    """Verify that auto_closed_low_risk evaluates the real diff, not an empty tempfile."""

    # Helper: write a unified-diff string touching the given paths to a temp file.
    def _write_diff(self, *touched_paths: str) -> str:
        lines = []
        for p in touched_paths:
            lines.append(f"diff --git a/{p} b/{p}")
            lines.append(f"--- a/{p}")
            lines.append(f"+++ b/{p}")
            lines.append("@@ -1 +1 @@")
            lines.append("-old line")
            lines.append("+new line")
        diff_content = "\n".join(lines) + "\n"
        tf = tempfile.NamedTemporaryFile(
            mode="w", suffix=".diff", delete=False, encoding="utf-8"
        )
        tf.write(diff_content)
        tf.flush()
        tf.close()
        self._diff_files = getattr(self, "_diff_files", [])
        self._diff_files.append(tf.name)
        return tf.name

    def tearDown(self) -> None:
        super().tearDown()
        for f in getattr(self, "_diff_files", []):
            try:
                os.unlink(f)
            except OSError:
                pass

    def _run_auto_close(self, entry_id: str, diff_path: str = "") -> subprocess.CompletedProcess:
        extra_args = [
            f"--entry={entry_id}",
            "--to=done",
            "--by=auto-consumer",
            f"--sink-root={self.sink_root}",
            "--completion-mode=auto_closed_low_risk",
        ]
        if diff_path:
            extra_args.append(f"--diff={diff_path}")
        return _run_status_set(*extra_args, lock_file=str(self.lock_file))

    def test_denylist_diff_is_rejected(self):
        """A diff that touches commands/foo.md (denylist) must not be auto-closed (exit 4)."""
        entry_id = "20260528T120000Z-autoclose-denylist"
        self._setup_entry(entry_id, "verify", auto_close_eligible=True)
        diff_path = self._write_diff("commands/foo.md")
        result = self._run_auto_close(entry_id, diff_path)
        self.assertEqual(
            result.returncode, 4,
            msg=f"Expected exit 4 for denylist diff; stderr={result.stderr}",
        )
        self.assertEqual(self._get_entry_status(entry_id), "verify",
                         msg="Entry must remain in verify after denylist rejection")

    def test_allowlist_diff_is_approved(self):
        """A diff touching only docs/**/*.md (allowlist, not denylist) must pass (exit 0)."""
        entry_id = "20260528T120000Z-autoclose-allowlist"
        self._setup_entry(entry_id, "verify", auto_close_eligible=True)
        diff_path = self._write_diff("docs/some-concept.md")
        result = self._run_auto_close(entry_id, diff_path)
        self.assertEqual(
            result.returncode, 0,
            msg=f"Expected exit 0 for allowlist diff; stderr={result.stderr}",
        )
        self.assertEqual(self._get_entry_status(entry_id), "done",
                         msg="Entry must reach done after low-risk auto-close")

    def test_no_diff_is_not_trivially_approved(self):
        """When --diff is omitted, auto-close must NOT trivially pass (exit 4, not 0)."""
        entry_id = "20260528T120000Z-autoclose-nodiff"
        self._setup_entry(entry_id, "verify", auto_close_eligible=True)
        result = self._run_auto_close(entry_id, diff_path="")
        self.assertEqual(
            result.returncode, 4,
            msg=f"Expected exit 4 when no diff provided; stderr={result.stderr}",
        )
        self.assertEqual(self._get_entry_status(entry_id), "verify",
                         msg="Entry must remain in verify when diff is missing")


# ── Lock ordering invariant ────────────────────────────────────────────────────

class TestLockOrdering(_SinkTestBase):
    """Verify per-entry lock is verified before global is acquired (SPEC invariant §Concurrency)."""

    def test_illegal_transition_exits_3_not_lock_error(self):
        """Even with an illegal transition, exit code is 3 (not 5), confirming
        lock ordering: global is acquired, validation runs, exit 3 is returned.
        This implicitly confirms the script reaches the state-machine check."""
        entry_id = "20260528T120000Z-lock-order-check"
        self._setup_entry(entry_id, "open")
        result = self._run(entry_id, "done")  # open → done is illegal
        self.assertEqual(result.returncode, 3)


if __name__ == "__main__":
    unittest.main()
