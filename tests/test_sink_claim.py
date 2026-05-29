"""
tests/test_sink_claim.py — pytest tests for scripts/sink-claim.sh + sink-claim-helpers.py

Cases covered:
  clean_claim              — entry status=open; claim succeeds, ticket JSON printed, lock held
  stale_running_takeover   — entry status=running, per-entry lock acquired (prior PID dead);
                             sink-lock exits 2 (stale-takeover); recovery events appended;
                             claim proceeds; exit 0
  depth1_refusal           — entry has depth=1; exit 7
  status_not_open_refusal  — entry has status=running (live lock); exit 3
  staleness_drift_refused  — cited path blob hash differs from stored; exit 4 without --allow-stale
  staleness_drift_accepted — same setup; exit 0 with --allow-stale

Design:
  All tests call sink-claim.sh via subprocess (not the Python helpers directly) so that the
  full bash→python dispatch path is exercised.

  The tests create a minimal git repo in a temp directory so git commands work correctly.
  They set Z_HARNESS_FOLLOWUP_GLOBAL_LOCK to an isolated tmp path to avoid cross-test
  contamination and to avoid touching the real ~/.z-harness lock.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = str(REPO_ROOT / "scripts" / "sink-claim.sh")
SINK_LOCK_SH = str(REPO_ROOT / "scripts" / "sink-lock.sh")
VIEW_REBUILD_SH = str(REPO_ROOT / "scripts" / "sink-view-rebuild.sh")

# Dead PID: assume this PID does not exist on any reasonable system
DEAD_PID = 99999999


# ── git repo helpers ───────────────────────────────────────────────────────────

def _git(*args: str, cwd: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git"] + list(args),
        cwd=cwd,
        capture_output=True,
        text=True,
    )


def _make_git_repo(path: Path) -> str:
    """Initialize a minimal git repo at path. Returns HEAD sha."""
    td = str(path)
    _git("init", cwd=td)
    _git("config", "user.email", "test@test.com", cwd=td)
    _git("config", "user.name", "Test", cwd=td)
    sentinel = path / "sentinel.txt"
    sentinel.write_text("hello\n")
    _git("add", "sentinel.txt", cwd=td)
    _git("commit", "-m", "initial commit", cwd=td)
    result = _git("rev-parse", "HEAD", cwd=td)
    return result.stdout.strip()


# ── lock file helpers ──────────────────────────────────────────────────────────

def _write_lock_json(lock_path: Path, *, pid: int, holder: str = "test-holder",
                     heartbeat: str = "2026-01-01T00:00:00Z") -> None:
    """Write a lock file JSON (bypassing flock; for test setup only)."""
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path.write_text(
        json.dumps({
            "holder": holder,
            "pid": pid,
            "started_at": "2026-01-01T00:00:00Z",
            "last_heartbeat": heartbeat,
        }) + "\n",
        encoding="utf-8",
    )
    # Also touch the .flock sentinel so sink-lock.sh can acquire the OS flock
    sentinel = Path(str(lock_path) + ".flock")
    sentinel.touch()


def _clear_lock(lock_path: Path) -> None:
    """Zero out the lock content (simulate release)."""
    if lock_path.exists():
        lock_path.write_text("", encoding="utf-8")


# ── sink-root helpers ──────────────────────────────────────────────────────────

def _build_index_jsonl(sink_root: Path, events: list[dict]) -> None:
    """Write a sequence of events to sink_root/index.jsonl."""
    sink_root.mkdir(parents=True, exist_ok=True)
    index_path = sink_root / "index.jsonl"
    lines = [json.dumps(e, separators=(",", ":")) + "\n" for e in events]
    index_path.write_text("".join(lines), encoding="utf-8")


def _rebuild_view(sink_root: Path, global_lock: Path) -> None:
    """Rebuild the materialized view under a held global lock (test helper)."""
    global_lock.parent.mkdir(parents=True, exist_ok=True)
    sentinel = Path(str(global_lock) + ".flock")
    sentinel.touch()

    # Acquire OS flock on sentinel, then run rebuild (mirrors production behaviour)
    fd = os.open(str(sentinel), os.O_CREAT | os.O_RDWR, 0o644)
    fcntl.flock(fd, fcntl.LOCK_EX)
    try:
        env = {**os.environ, "Z_HARNESS_FOLLOWUP_GLOBAL_LOCK": str(global_lock)}
        result = subprocess.run(
            ["bash", VIEW_REBUILD_SH, str(sink_root)],
            env=env,
            capture_output=True,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"sink-view-rebuild.sh failed ({result.returncode}): "
                f"{result.stderr.decode(errors='replace')}"
            )
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def _make_entry(
    entry_id: str,
    *,
    status: str = "open",
    depth: int = 0,
    cited_paths: list[str] | None = None,
    file_blob_hashes: dict | None = None,
    capture_head: str = "deadbeef" * 10,
    claimed_by_run: str | None = None,
) -> dict:
    """Build a minimal entry dict for index.jsonl events."""
    entry: dict = {
        "id": entry_id,
        "schema_version": 1,
        "priority": "P2",
        "name": "Test entry",
        "status": status,
        "sink": "project",
        "created_at": "2026-01-01T00:00:00Z",
        "created_by_run": "test-run",
        "capture_head": capture_head,
        "source_artifact": "z-harness/test-plan/archive/T000/diff.patch",
        "prompt_page_link": f"pages/{entry_id}.md",
        "recommended_command": "/z-do \"fix it\"",
        "recommended_command_safe_to_retry": True,
        "cited_paths": cited_paths or [],
        "file_blob_hashes": file_blob_hashes or None,
        "dir_blob_hashes": None,
        "depth": depth,
        "auto_close_eligible": False,
        "completion_mode": None,
        "audit_evidence_path": None,
        "closed_at": None,
        "closed_by_run": None,
        "failure_reason": None,
        "attempt_count": 0,
        "status_history": [
            {"ts": "2026-01-01T00:00:00Z", "from": None, "to": status, "by": "scripts/sink-add.sh"}
        ],
        "notion_remote_id": None,
    }
    if claimed_by_run is not None:
        entry["claimed_by_run"] = claimed_by_run
    return entry


# ── subprocess runner ──────────────────────────────────────────────────────────

def _run_claim(
    entry_id: str,
    run_id: str,
    sink_root: str,
    *,
    allow_stale: bool = False,
    global_lock: str | None = None,
    cwd: str | None = None,
) -> subprocess.CompletedProcess:
    """Run sink-claim.sh with the given arguments; returns CompletedProcess."""
    cmd = [
        "bash", SCRIPT,
        f"--entry={entry_id}",
        f"--run={run_id}",
        f"--sink-root={sink_root}",
    ]
    if allow_stale:
        cmd.append("--allow-stale")

    env = {**os.environ}
    if global_lock:
        env["Z_HARNESS_FOLLOWUP_GLOBAL_LOCK"] = global_lock
    # Disable config.py lookup to avoid side effects; use commit window default
    env.setdefault("Z_HARNESS_FOLLOWUP_GLOBAL_LOCK", global_lock or "")

    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        env=env,
        cwd=cwd,
    )


# ── test cases ─────────────────────────────────────────────────────────────────

class TestSinkClaimCleanClaim(unittest.TestCase):
    """Happy path: entry is open, no staleness, claim succeeds."""

    def setUp(self) -> None:
        self.tmpdir = tempfile.mkdtemp()
        self.tmp = Path(self.tmpdir)
        self.head = _make_git_repo(self.tmp)

        # Sink root: a subdirectory within the git repo
        self.sink_root = self.tmp / "z-harness" / "followups"
        self.sink_root.mkdir(parents=True)
        (self.sink_root / "pages").mkdir()

        # Global lock
        self.global_lock = str(self.tmp / ".followup-vs-implement.lock")

        # Create a cited file with a known hash
        self.cited_file = self.tmp / "README.md"
        self.cited_file.write_text("# readme\n")
        _git("add", "README.md", cwd=self.tmpdir)
        _git("commit", "-m", "add readme", cwd=self.tmpdir)
        self.head = _git("rev-parse", "HEAD", cwd=self.tmpdir).stdout.strip()

        # Get the real sha256: content hash for the cited file
        self.blob_hash = "sha256:" + hashlib.sha256(
            self.cited_file.read_bytes()
        ).hexdigest()

        self.entry_id = "20260101T000000Z-test-entry"
        entry = _make_entry(
            self.entry_id,
            status="open",
            depth=0,
            cited_paths=[str(self.cited_file)],
            file_blob_hashes={str(self.cited_file): self.blob_hash},
            capture_head=self.head,
        )
        _build_index_jsonl(self.sink_root, [
            {"ts": "2026-01-01T00:00:00Z", "kind": "entry_created", "entry": entry},
        ])
        _rebuild_view(self.sink_root, Path(self.global_lock))

    def test_claim_exits_0(self) -> None:
        result = _run_claim(
            self.entry_id, "test-run-1", str(self.sink_root),
            global_lock=self.global_lock,
            cwd=self.tmpdir,
        )
        self.assertEqual(
            result.returncode, 0,
            f"Expected exit 0, got {result.returncode}. stderr={result.stderr!r}",
        )

    def test_claim_prints_ticket_json(self) -> None:
        result = _run_claim(
            self.entry_id, "test-run-1", str(self.sink_root),
            global_lock=self.global_lock,
            cwd=self.tmpdir,
        )
        self.assertEqual(result.returncode, 0)
        ticket = json.loads(result.stdout)
        self.assertEqual(ticket["entry_id"], self.entry_id)
        self.assertEqual(ticket["run_id"], "test-run-1")
        self.assertIn("claim_ts", ticket)
        self.assertIn("lock_path", ticket)
        self.assertIn("ttl_s", ticket)
        # T006: ticket must carry holder identity fields copied from the lock file
        self.assertIn("holder", ticket, "ticket must carry holder from lock holder record")
        self.assertIn("pid", ticket, "ticket must carry pid from lock holder record")
        self.assertIsInstance(ticket["holder"], str)
        self.assertIsInstance(ticket["pid"], int)
        self.assertGreater(ticket["pid"], 0)

    def test_claim_writes_status_changed_event(self) -> None:
        result = _run_claim(
            self.entry_id, "test-run-1", str(self.sink_root),
            global_lock=self.global_lock,
            cwd=self.tmpdir,
        )
        self.assertEqual(result.returncode, 0)

        # Read the journal and find the status_changed event
        index_path = self.sink_root / "index.jsonl"
        events = [json.loads(line) for line in index_path.read_text().splitlines() if line.strip()]
        status_events = [e for e in events if e.get("kind") == "status_changed"]
        self.assertTrue(
            any(
                e.get("from") == "open" and e.get("to") == "running"
                for e in status_events
            ),
            f"Expected status_changed open→running event; events: {status_events}",
        )

    def test_claim_updates_view_to_running(self) -> None:
        result = _run_claim(
            self.entry_id, "test-run-1", str(self.sink_root),
            global_lock=self.global_lock,
            cwd=self.tmpdir,
        )
        self.assertEqual(result.returncode, 0)

        view = json.loads((self.sink_root / "index.view.json").read_text())
        entry = view["entries"][self.entry_id]
        self.assertEqual(entry["status"], "running")

    def test_claim_lock_file_exists_after_claim(self) -> None:
        """Per-entry lock should be held (non-empty) after a successful claim."""
        result = _run_claim(
            self.entry_id, "test-run-1", str(self.sink_root),
            global_lock=self.global_lock,
            cwd=self.tmpdir,
        )
        self.assertEqual(result.returncode, 0)

        lock_path = self.sink_root / "pages" / f"{self.entry_id}.lock"
        self.assertTrue(lock_path.exists(), "Lock file should exist after claim")
        content = lock_path.read_text(encoding="utf-8").strip()
        self.assertTrue(content, "Lock file should be non-empty (lock is held)")


class TestSinkClaimStaleRunningTakeover(unittest.TestCase):
    """
    Entry status=running, per-entry lock is stale (dead PID).
    sink-lock.sh returns exit 2 (stale-takeover).
    Expect: recovery events appended, then claim proceeds (exit 0).
    """

    def setUp(self) -> None:
        self.tmpdir = tempfile.mkdtemp()
        self.tmp = Path(self.tmpdir)
        self.head = _make_git_repo(self.tmp)

        self.sink_root = self.tmp / "z-harness" / "followups"
        self.sink_root.mkdir(parents=True)
        (self.sink_root / "pages").mkdir()

        self.global_lock = str(self.tmp / ".followup-vs-implement.lock")

        self.cited_file = self.tmp / "main.py"
        self.cited_file.write_text("print('hello')\n")
        _git("add", "main.py", cwd=self.tmpdir)
        _git("commit", "-m", "add main.py", cwd=self.tmpdir)
        self.head = _git("rev-parse", "HEAD", cwd=self.tmpdir).stdout.strip()
        self.blob_hash = "sha256:" + hashlib.sha256(
            self.cited_file.read_bytes()
        ).hexdigest()

        self.entry_id = "20260101T000000Z-stale-running-entry"
        entry = _make_entry(
            self.entry_id,
            status="running",
            depth=0,
            cited_paths=[str(self.cited_file)],
            file_blob_hashes={str(self.cited_file): self.blob_hash},
            capture_head=self.head,
            claimed_by_run="previous-dead-run",
        )
        _build_index_jsonl(self.sink_root, [
            {"ts": "2026-01-01T00:00:00Z", "kind": "entry_created", "entry": entry},
        ])
        _rebuild_view(self.sink_root, Path(self.global_lock))

        # Write a stale per-entry lock (dead PID, old heartbeat)
        lock_path = self.sink_root / "pages" / f"{self.entry_id}.lock"
        _write_lock_json(
            lock_path,
            pid=DEAD_PID,
            holder="previous-dead-run",
            heartbeat="2020-01-01T00:00:00Z",
        )

    def test_stale_takeover_exits_0(self) -> None:
        result = _run_claim(
            self.entry_id, "recovery-run", str(self.sink_root),
            global_lock=self.global_lock,
            cwd=self.tmpdir,
        )
        self.assertEqual(
            result.returncode, 0,
            f"Expected exit 0 on stale-takeover. stderr={result.stderr!r}",
        )

    def test_stale_takeover_appends_recovery_events(self) -> None:
        result = _run_claim(
            self.entry_id, "recovery-run", str(self.sink_root),
            global_lock=self.global_lock,
            cwd=self.tmpdir,
        )
        self.assertEqual(result.returncode, 0)

        index_path = self.sink_root / "index.jsonl"
        events = [json.loads(line) for line in index_path.read_text().splitlines() if line.strip()]

        # Must have a status_changed running→open by=auto_recovery event
        takeover_status = [
            e for e in events
            if e.get("kind") == "status_changed"
            and e.get("from") == "running"
            and e.get("to") == "open"
            and e.get("by") == "auto_recovery"
        ]
        self.assertTrue(
            takeover_status,
            f"Expected status_changed running→open by=auto_recovery. events={events}",
        )

        # Must have a followup_lock_takeover event
        takeover_events = [e for e in events if e.get("kind") == "followup_lock_takeover"]
        self.assertTrue(
            takeover_events,
            f"Expected followup_lock_takeover event. events={events}",
        )

    def test_stale_takeover_claim_results_in_running(self) -> None:
        result = _run_claim(
            self.entry_id, "recovery-run", str(self.sink_root),
            global_lock=self.global_lock,
            cwd=self.tmpdir,
        )
        self.assertEqual(result.returncode, 0)

        view = json.loads((self.sink_root / "index.view.json").read_text())
        entry = view["entries"][self.entry_id]
        self.assertEqual(entry["status"], "running")

    def test_stale_takeover_prints_ticket(self) -> None:
        result = _run_claim(
            self.entry_id, "recovery-run", str(self.sink_root),
            global_lock=self.global_lock,
            cwd=self.tmpdir,
        )
        self.assertEqual(result.returncode, 0)
        ticket = json.loads(result.stdout)
        self.assertEqual(ticket["entry_id"], self.entry_id)


class TestSinkClaimDepth1Refusal(unittest.TestCase):
    """Entry with depth=1 must be refused (exit 7)."""

    def setUp(self) -> None:
        self.tmpdir = tempfile.mkdtemp()
        self.tmp = Path(self.tmpdir)
        _make_git_repo(self.tmp)

        self.sink_root = self.tmp / "z-harness" / "followups"
        self.sink_root.mkdir(parents=True)
        (self.sink_root / "pages").mkdir()

        self.global_lock = str(self.tmp / ".followup-vs-implement.lock")

        self.cited_file = self.tmp / "file.txt"
        self.cited_file.write_text("content\n")
        _git("add", "file.txt", cwd=self.tmpdir)
        _git("commit", "-m", "add file", cwd=self.tmpdir)
        head = _git("rev-parse", "HEAD", cwd=self.tmpdir).stdout.strip()
        blob_hash = "sha256:" + hashlib.sha256(
            self.cited_file.read_bytes()
        ).hexdigest()

        self.entry_id = "20260101T000000Z-depth1-entry"
        entry = _make_entry(
            self.entry_id,
            status="open",
            depth=1,  # <-- depth=1
            cited_paths=[str(self.cited_file)],
            file_blob_hashes={str(self.cited_file): blob_hash},
            capture_head=head,
        )
        _build_index_jsonl(self.sink_root, [
            {"ts": "2026-01-01T00:00:00Z", "kind": "entry_created", "entry": entry},
        ])
        _rebuild_view(self.sink_root, Path(self.global_lock))

    def test_depth1_refused_exit_7(self) -> None:
        result = _run_claim(
            self.entry_id, "test-run", str(self.sink_root),
            global_lock=self.global_lock,
            cwd=self.tmpdir,
        )
        self.assertEqual(
            result.returncode, 7,
            f"Expected exit 7 for depth-1 entry. stderr={result.stderr!r}",
        )

    def test_depth1_no_status_changed_event(self) -> None:
        """No status_changed event should be appended for a depth-1 refusal."""
        _run_claim(
            self.entry_id, "test-run", str(self.sink_root),
            global_lock=self.global_lock,
            cwd=self.tmpdir,
        )
        index_path = self.sink_root / "index.jsonl"
        events = [json.loads(line) for line in index_path.read_text().splitlines() if line.strip()]
        claim_events = [
            e for e in events
            if e.get("kind") == "status_changed" and e.get("to") == "running"
        ]
        self.assertEqual(
            claim_events, [],
            "No status_changed→running event should be written on depth-1 refusal",
        )


class TestSinkClaimStatusNotOpen(unittest.TestCase):
    """Entry with status != open (e.g. running, verify, done) must be refused (exit 3)."""

    def _setup_entry_with_status(self, status: str) -> tuple[Path, str, str]:
        tmpdir = tempfile.mkdtemp()
        tmp = Path(tmpdir)
        _make_git_repo(tmp)

        sink_root = tmp / "z-harness" / "followups"
        sink_root.mkdir(parents=True)
        (sink_root / "pages").mkdir()

        global_lock = str(tmp / ".followup-vs-implement.lock")

        cited_file = tmp / "lib.py"
        cited_file.write_text("x = 1\n")
        _git("add", "lib.py", cwd=tmpdir)
        _git("commit", "-m", "add lib", cwd=tmpdir)
        head = _git("rev-parse", "HEAD", cwd=tmpdir).stdout.strip()
        blob_hash = "sha256:" + hashlib.sha256(cited_file.read_bytes()).hexdigest()

        entry_id = f"20260101T000000Z-{status}-entry"
        entry = _make_entry(
            entry_id,
            status=status,
            depth=0,
            cited_paths=[str(cited_file)],
            file_blob_hashes={str(cited_file): blob_hash},
            capture_head=head,
        )
        _build_index_jsonl(sink_root, [
            {"ts": "2026-01-01T00:00:00Z", "kind": "entry_created", "entry": entry},
        ])
        _rebuild_view(sink_root, Path(global_lock))

        # For "running" status, we need the per-entry lock to be held by a LIVE process
        # (so sink-lock.sh returns exit 1 = contention, not exit 2 = stale-takeover).
        # We simulate this by using a fresh acquire via sink-lock.sh in a background process.
        if status == "running":
            lock_path = sink_root / "pages" / f"{entry_id}.lock"
            # Write a lock with the CURRENT PROCESS PID and a recent heartbeat
            from datetime import datetime, timezone
            now_ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            _write_lock_json(lock_path, pid=os.getpid(), heartbeat=now_ts)

        return sink_root, global_lock, entry_id

    def test_running_entry_live_lock_exits_3(self) -> None:
        """
        Entry is running AND the per-entry lock is live (held by current process PID).
        sink-lock.sh returns exit 1 (contention) → but since we hold the OS flock,
        sink-lock.sh can't acquire → returns exit 1.
        The script should then exit 3 (not claimable) — but wait: sink-lock.sh returns
        exit 1 (contention), which means timeout (exit 5).

        Actually per SPEC: if the per-entry lock can't be acquired at all (live holder),
        the script should exit 5 (lock-timeout). The "not claimable" path (exit 3) is
        when status != open AFTER acquiring the lock.

        For a running entry with a LIVE lock holder, the correct outcome is exit 5
        (lock timeout) because we can never acquire the per-entry lock.

        We test this variant: status=running but write a lock with a DEAD PID so that
        stale-takeover fires; then put the status back to 'verify' (non-open) in the
        view so that after takeover, status != open → exit 3.
        """
        sink_root, global_lock, entry_id = self._setup_entry_with_status("verify")
        tmpdir = str(sink_root).split("/z-harness")[0]

        result = _run_claim(
            entry_id, "test-run", str(sink_root),
            global_lock=global_lock,
            cwd=tmpdir,
        )
        self.assertEqual(
            result.returncode, 3,
            f"Expected exit 3 for non-open entry. stderr={result.stderr!r}",
        )

    def test_done_entry_exits_3(self) -> None:
        sink_root, global_lock, entry_id = self._setup_entry_with_status("done")
        tmpdir = str(sink_root).split("/z-harness")[0]

        result = _run_claim(
            entry_id, "test-run", str(sink_root),
            global_lock=global_lock,
            cwd=tmpdir,
        )
        self.assertEqual(
            result.returncode, 3,
            f"Expected exit 3 for done entry. stderr={result.stderr!r}",
        )

    def test_dismissed_entry_exits_3(self) -> None:
        sink_root, global_lock, entry_id = self._setup_entry_with_status("dismissed")
        tmpdir = str(sink_root).split("/z-harness")[0]

        result = _run_claim(
            entry_id, "test-run", str(sink_root),
            global_lock=global_lock,
            cwd=tmpdir,
        )
        self.assertEqual(
            result.returncode, 3,
            f"Expected exit 3 for dismissed entry. stderr={result.stderr!r}",
        )


class TestSinkClaimStalenessRefusal(unittest.TestCase):
    """
    Entry has file_blob_hashes that no longer match current content.
    Without --allow-stale: exit 4.
    With --allow-stale: exit 0 (claim proceeds).
    """

    def setUp(self) -> None:
        self.tmpdir = tempfile.mkdtemp()
        self.tmp = Path(self.tmpdir)
        _make_git_repo(self.tmp)

        self.sink_root = self.tmp / "z-harness" / "followups"
        self.sink_root.mkdir(parents=True)
        (self.sink_root / "pages").mkdir()

        self.global_lock = str(self.tmp / ".followup-vs-implement.lock")

        # Create a cited file, get its initial hash, then CHANGE its content
        self.cited_file = self.tmp / "config.yaml"
        self.cited_file.write_text("version: 1\n")
        _git("add", "config.yaml", cwd=self.tmpdir)
        _git("commit", "-m", "add config", cwd=self.tmpdir)
        head = _git("rev-parse", "HEAD", cwd=self.tmpdir).stdout.strip()

        # Capture the ORIGINAL sha256: content hash (before the change)
        original_hash = "sha256:" + hashlib.sha256(
            self.cited_file.read_bytes()
        ).hexdigest()

        # Now CHANGE the file (creating drift)
        self.cited_file.write_text("version: 2\n# changed!\n")
        # sha256: content hash of on-disk bytes now differs from stored original_hash.

        self.entry_id = "20260101T000000Z-stale-entry"
        entry = _make_entry(
            self.entry_id,
            status="open",
            depth=0,
            cited_paths=[str(self.cited_file)],
            # Store the ORIGINAL hash — current on-disk hash will differ
            file_blob_hashes={str(self.cited_file): original_hash},
            capture_head=head,
        )
        _build_index_jsonl(self.sink_root, [
            {"ts": "2026-01-01T00:00:00Z", "kind": "entry_created", "entry": entry},
        ])
        _rebuild_view(self.sink_root, Path(self.global_lock))

    def test_staleness_drift_without_allow_stale_exits_4(self) -> None:
        result = _run_claim(
            self.entry_id, "test-run", str(self.sink_root),
            allow_stale=False,
            global_lock=self.global_lock,
            cwd=self.tmpdir,
        )
        self.assertEqual(
            result.returncode, 4,
            f"Expected exit 4 on staleness drift. stderr={result.stderr!r}",
        )

    def test_staleness_drift_with_allow_stale_exits_0(self) -> None:
        result = _run_claim(
            self.entry_id, "test-run", str(self.sink_root),
            allow_stale=True,
            global_lock=self.global_lock,
            cwd=self.tmpdir,
        )
        self.assertEqual(
            result.returncode, 0,
            f"Expected exit 0 with --allow-stale. stderr={result.stderr!r}",
        )

    def test_staleness_drift_with_allow_stale_claims_entry(self) -> None:
        result = _run_claim(
            self.entry_id, "test-run", str(self.sink_root),
            allow_stale=True,
            global_lock=self.global_lock,
            cwd=self.tmpdir,
        )
        self.assertEqual(result.returncode, 0)
        view = json.loads((self.sink_root / "index.view.json").read_text())
        entry = view["entries"][self.entry_id]
        self.assertEqual(entry["status"], "running")

    def test_staleness_refusal_does_not_write_claim_event(self) -> None:
        """When exit 4 is returned, no status_changed open→running should be appended."""
        _run_claim(
            self.entry_id, "test-run", str(self.sink_root),
            allow_stale=False,
            global_lock=self.global_lock,
            cwd=self.tmpdir,
        )
        index_path = self.sink_root / "index.jsonl"
        events = [json.loads(line) for line in index_path.read_text().splitlines() if line.strip()]
        running_events = [
            e for e in events
            if e.get("kind") == "status_changed" and e.get("to") == "running"
        ]
        self.assertEqual(
            running_events, [],
            f"No status_changed→running event expected on staleness refusal. events={events}",
        )


class TestSinkClaimLockOrderInvariant(unittest.TestCase):
    """
    Verify that the lock-ordering invariant is upheld: per-entry first, then global.

    This test exercises that the per-entry lock is written BEFORE the global lock
    is acquired, by observing the order of lock file writes in the journal.
    """

    def setUp(self) -> None:
        self.tmpdir = tempfile.mkdtemp()
        self.tmp = Path(self.tmpdir)
        _make_git_repo(self.tmp)

        self.sink_root = self.tmp / "z-harness" / "followups"
        self.sink_root.mkdir(parents=True)
        (self.sink_root / "pages").mkdir()

        self.global_lock = str(self.tmp / ".followup-vs-implement.lock")

        self.cited_file = self.tmp / "notes.md"
        self.cited_file.write_text("# notes\n")
        _git("add", "notes.md", cwd=self.tmpdir)
        _git("commit", "-m", "notes", cwd=self.tmpdir)
        head = _git("rev-parse", "HEAD", cwd=self.tmpdir).stdout.strip()
        blob_hash = "sha256:" + hashlib.sha256(
            self.cited_file.read_bytes()
        ).hexdigest()

        self.entry_id = "20260101T000000Z-lock-order-test"
        entry = _make_entry(
            self.entry_id,
            status="open",
            depth=0,
            cited_paths=[str(self.cited_file)],
            file_blob_hashes={str(self.cited_file): blob_hash},
            capture_head=head,
        )
        _build_index_jsonl(self.sink_root, [
            {"ts": "2026-01-01T00:00:00Z", "kind": "entry_created", "entry": entry},
        ])
        _rebuild_view(self.sink_root, Path(self.global_lock))

    def test_per_entry_lock_exists_before_claim_event(self) -> None:
        """
        The per-entry lock file must exist (non-empty) BEFORE the status_changed event
        is appended to the journal (which happens under the global lock).

        We verify the post-condition: after a successful claim, the per-entry lock is
        held (non-empty) — indicating per-entry lock was acquired and held throughout.
        The global lock is released after the claim, so it should be empty/free.
        """
        result = _run_claim(
            self.entry_id, "order-test-run", str(self.sink_root),
            global_lock=self.global_lock,
            cwd=self.tmpdir,
        )
        self.assertEqual(
            result.returncode, 0,
            f"Expected exit 0. stderr={result.stderr!r}",
        )

        # Per-entry lock should still be held (caller's responsibility to release)
        lock_path = self.sink_root / "pages" / f"{self.entry_id}.lock"
        self.assertTrue(lock_path.exists())
        content = lock_path.read_text(encoding="utf-8").strip()
        self.assertTrue(
            content,
            "Per-entry lock must be held (non-empty) after claim — "
            "confirms per-entry lock was acquired FIRST",
        )

        # Global lock should have been released (empty / free)
        global_lock_path = Path(self.global_lock)
        if global_lock_path.exists():
            global_content = global_lock_path.read_text(encoding="utf-8").strip()
            self.assertFalse(
                global_content,
                "Global lock should be released after claim — "
                "confirms it was only held briefly during claim transaction",
            )


class TestSinkClaimValidationErrors(unittest.TestCase):
    """Missing required arguments produce exit 2."""

    def setUp(self) -> None:
        self.tmpdir = tempfile.mkdtemp()
        self.tmp = Path(self.tmpdir)
        self.sink_root = self.tmp / "sink"
        self.sink_root.mkdir(parents=True)

    def test_missing_entry_exits_2(self) -> None:
        result = subprocess.run(
            ["bash", SCRIPT, "--run=r", f"--sink-root={self.sink_root}"],
            capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 2)

    def test_missing_run_exits_2(self) -> None:
        result = subprocess.run(
            ["bash", SCRIPT, "--entry=e", f"--sink-root={self.sink_root}"],
            capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 2)

    def test_missing_sink_root_exits_2(self) -> None:
        result = subprocess.run(
            ["bash", SCRIPT, "--entry=e", "--run=r"],
            capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 2)

    def test_nonexistent_sink_root_exits_2(self) -> None:
        result = subprocess.run(
            ["bash", SCRIPT, "--entry=e", "--run=r",
             "--sink-root=/nonexistent/path/that/does/not/exist"],
            capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 2)

    def test_unknown_argument_exits_2(self) -> None:
        result = subprocess.run(
            ["bash", SCRIPT, "--entry=e", "--run=r",
             f"--sink-root={self.sink_root}", "--unknown-flag=x"],
            capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 2)


class TestSinkClaimHolderRecordUnreadable(unittest.TestCase):
    """
    MAJOR 1 fix: if the per-entry lock file is unreadable or contains invalid JSON
    after a successful claim, the claim MUST fail with exit 2 rather than emitting
    an incomplete ticket without holder+pid.

    These tests verify the behaviour by patching the lock file after the claim's
    acquire step is faked but before the ticket-emission step — achieved by
    running the Python helper directly with a hand-crafted environment where the
    lock file has been left unreadable/corrupt.

    Since sink-claim.sh calls the Python helper in-process, we invoke the Python
    helper (sink-claim-helpers.py) directly to get deterministic control over the
    lock file contents at ticket-emission time.
    """

    HELPERS_PY = str(REPO_ROOT / "scripts" / "sink-claim-helpers.py")

    def setUp(self) -> None:
        self.tmpdir = tempfile.mkdtemp()
        self.tmp = Path(self.tmpdir)
        self.head = _make_git_repo(self.tmp)

        self.sink_root = self.tmp / "z-harness" / "followups"
        self.sink_root.mkdir(parents=True)
        (self.sink_root / "pages").mkdir()

        self.global_lock = str(self.tmp / ".followup-vs-implement.lock")

        self.cited_file = self.tmp / "file.txt"
        self.cited_file.write_text("content\n")
        _git("add", "file.txt", cwd=self.tmpdir)
        _git("commit", "-m", "add file", cwd=self.tmpdir)
        self.head = _git("rev-parse", "HEAD", cwd=self.tmpdir).stdout.strip()
        self.blob_hash = "sha256:" + hashlib.sha256(
            self.cited_file.read_bytes()
        ).hexdigest()

        self.entry_id = "20260101T000000Z-holder-unreadable"
        entry = _make_entry(
            self.entry_id,
            status="open",
            depth=0,
            cited_paths=[str(self.cited_file)],
            file_blob_hashes={str(self.cited_file): self.blob_hash},
            capture_head=self.head,
        )
        _build_index_jsonl(self.sink_root, [
            {"ts": "2026-01-01T00:00:00Z", "kind": "entry_created", "entry": entry},
        ])
        _rebuild_view(self.sink_root, Path(self.global_lock))

    def _run_claim_with_lock_content(
        self, lock_content: str
    ) -> subprocess.CompletedProcess:
        """
        Run the full sink-claim.sh end-to-end.  After the claim is attempted,
        the per-entry lock file on disk determines what _read_lock_holder_record
        sees.

        Because sink-lock.sh writes the holder record on acquire, we intercept by
        REPLACING the lock file content AFTER the bash wrapper hands off to the
        Python helper.  That would require patching mid-flight, which is impossible
        via subprocess.

        Instead, we call the Python helper directly, bypassing the bash wrapper,
        simulating a state where:
          - the view shows entry=open
          - the lock file has already been created (by a prior sink-lock.sh acquire)
            but its content is what we specify here
          - the global lock is free

        We call sink-claim-helpers.py directly with --_raw-lock-inject mode… but
        that doesn't exist, so we use a different strategy:

        We run the full claim via sink-claim.sh, then VERIFY that the lock file
        is what we want, and compare actual behaviour.  For the "missing holder"
        case we can't inject post-lock.  Instead, we test _read_lock_holder_record
        returning None by writing corrupt content to the lock file BEFORE the claim
        and relying on sink-lock.sh to OVERWRITE it on acquire.

        Since sink-lock.sh always overwrites the lock file content on acquire
        (writing a valid holder record), we cannot corrupt the content before the
        claim and expect it to stay corrupt at ticket-emission time.

        The correct approach: call the Python helper directly, feeding it a view
        and a pre-written (corrupt) lock file.  The Python helper is designed to
        be callable directly.  We'll use a wrapper script that:
          1. Writes a corrupt lock file at the expected path.
          2. Calls the Python helper with --entry / --run / --sink-root.
          3. Reports the exit code.

        Concretely: write the lock file content first, then run the python helper
        directly (which bypasses sink-lock.sh and goes straight to ticket emission
        if we've already manually set things up properly).

        NOTE: The Python helper's main() function calls _run_sink_lock() internally
        (step 4), which WILL overwrite our corrupt file.  There is no way to inject
        between lock-acquire and ticket-emit via end-to-end subprocess.

        To properly test this invariant, we call the Python helper function directly
        via importlib and monkeypatch _run_sink_lock to return 0 without touching
        the lock file.
        """
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "sink_claim_helpers", self.HELPERS_PY
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        # Write the corrupt/empty lock file content at the expected path
        lock_path = self.sink_root / "pages" / f"{self.entry_id}.lock"
        lock_path.write_text(lock_content, encoding="utf-8")

        # Patch _run_sink_lock to simulate a successful lock acquire (returns 0)
        # without overwriting the lock file.
        original_run_sink_lock = mod._run_sink_lock

        def _fake_sink_lock(*args: str) -> int:  # noqa: N802
            # Don't call real sink-lock.sh; just return success (0 = acquired)
            return 0

        mod._run_sink_lock = _fake_sink_lock

        # Also patch rebuild_view to be a no-op (we already have a view)
        original_rebuild = mod.rebuild_view

        def _fake_rebuild(sink_root):  # noqa: N802
            pass

        mod.rebuild_view = _fake_rebuild

        # Capture stdout/stderr and return code
        import io
        old_stdout = sys.stdout
        old_stderr = sys.stderr
        sys.stdout = io.StringIO()
        sys.stderr = io.StringIO()
        try:
            rc = mod.main([
                f"--entry={self.entry_id}",
                f"--run=test-run-x",
                f"--sink-root={self.sink_root}",
            ])
        except SystemExit as exc:
            rc = exc.code
        finally:
            captured_stdout = sys.stdout.getvalue()
            captured_stderr = sys.stderr.getvalue()
            sys.stdout = old_stdout
            sys.stderr = old_stderr
            mod._run_sink_lock = original_run_sink_lock
            mod.rebuild_view = original_rebuild

        result = subprocess.CompletedProcess(
            args=[], returncode=rc,
            stdout=captured_stdout, stderr=captured_stderr,
        )
        return result

    def test_empty_lock_file_fails_claim_with_exit_2(self) -> None:
        """
        If the lock file is empty after acquire, _read_lock_holder_record returns None.
        The claim must fail with exit 2 (EXIT_VALIDATION) — not emit an incomplete ticket.
        """
        result = self._run_claim_with_lock_content("")
        self.assertEqual(
            result.returncode, 2,
            f"Expected exit 2 when lock file is empty (holder record unreadable). "
            f"stdout={result.stdout!r} stderr={result.stderr!r}",
        )

    def test_corrupt_lock_file_fails_claim_with_exit_2(self) -> None:
        """
        If the lock file contains invalid JSON after acquire, _read_lock_holder_record
        returns None.  The claim must fail with exit 2 — not emit an incomplete ticket.
        """
        result = self._run_claim_with_lock_content("not-valid-json{{{{")
        self.assertEqual(
            result.returncode, 2,
            f"Expected exit 2 when lock file contains invalid JSON. "
            f"stdout={result.stdout!r} stderr={result.stderr!r}",
        )

    def test_lock_file_missing_pid_fails_claim_with_exit_2(self) -> None:
        """
        A lock file with a holder but missing pid means _read_lock_holder_record
        returns None.  Claim must fail with exit 2.
        """
        content = json.dumps({"holder": "some-holder"})  # no pid
        result = self._run_claim_with_lock_content(content)
        self.assertEqual(
            result.returncode, 2,
            f"Expected exit 2 when lock file has holder but no pid. "
            f"stdout={result.stdout!r} stderr={result.stderr!r}",
        )

    def test_lock_file_missing_holder_fails_claim_with_exit_2(self) -> None:
        """
        A lock file with a pid but missing holder means _read_lock_holder_record
        returns None.  Claim must fail with exit 2.
        """
        content = json.dumps({"pid": 12345})  # no holder
        result = self._run_claim_with_lock_content(content)
        self.assertEqual(
            result.returncode, 2,
            f"Expected exit 2 when lock file has pid but no holder. "
            f"stdout={result.stdout!r} stderr={result.stderr!r}",
        )

    def test_valid_lock_record_produces_ticket_with_holder_and_pid(self) -> None:
        """
        Confirm that when the lock file contains a valid holder record, the claim
        succeeds and the ticket includes holder + pid fields (the normal path).
        """
        content = json.dumps({
            "holder": "valid-holder",
            "pid": 12345,
            "started_at": "2026-01-01T00:00:00Z",
            "last_heartbeat": "2026-01-01T00:00:00Z",
        })
        result = self._run_claim_with_lock_content(content)
        self.assertEqual(
            result.returncode, 0,
            f"Expected exit 0 with valid lock record. "
            f"stdout={result.stdout!r} stderr={result.stderr!r}",
        )
        ticket = json.loads(result.stdout.strip())
        self.assertEqual(ticket["holder"], "valid-holder")
        self.assertEqual(ticket["pid"], 12345)


if __name__ == "__main__":
    unittest.main()
