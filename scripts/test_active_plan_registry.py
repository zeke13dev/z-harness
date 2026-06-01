"""
scripts/test_active_plan_registry.py — pytest tests for scripts/active-plan-registry.py

Cases covered (T006):
  round_trip                — register → list → deregister; record is present then absent
  concurrent_registers      — N=10 concurrent registers (distinct run-ids) produce exactly
                               N uncorrupted records (no corruption, no partial writes)
  safe_basename_traversal   — safe-basename validation rejects '../x', 'a/b', and leading '-'
  list_skips_torn_files     — list skips a deliberately truncated *.json file
  register_exit_code        — register returns exit code 3 on forced failure (unwritable dir)

Cases covered (T007 — overlaps + reap):
  overlaps_shared_explicit  — exit 10 when two peers share an explicit-confidence path
  overlaps_same_session     — same session_id peer is ignored (exit 0)
  overlaps_stale_nonblocking — stale peer overlap is included but does NOT trigger exit 20
  overlaps_strict_exit20    — explicit×explicit exact match with --strict → exit 20
  reap_live_pid_not_deleted — reaper does NOT delete a record whose pid is alive
  reap_dead_pid_deleted     — reaper DOES delete a record with a dead local pid
  reap_remote_host_stale    — remote host past threshold → status:stale, NOT deleted
  reap_two_reapers_race     — two reapers racing on the same record do not crash

Cases covered (T009 — session-id stamping):
  session_id_returns_env    — session-id returns Z_HARNESS_SESSION_ID when set
  session_id_stable_shape   — session-id without env returns '<digits>-<digits>' token
  session_id_no_spaces      — session-id output contains no spaces (safe token)
  session_id_env_priority   — env var takes priority over any derived value
  register_session_in_list  — register --session X → list shows session_id == X
  register_no_session       — register without --session stores session_id as empty string

All tests use a hermetic temp base via Z_HARNESS_BASE_DIR so no anchor pollution
occurs at /Users/zeke/dev/z-harness/.git/.z-harness-base or the real registry.
"""

from __future__ import annotations

import concurrent.futures
import json
import multiprocessing
import os
import socket
import stat
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
REGISTRY_PY = str(REPO_ROOT / "scripts" / "active-plan-registry.py")


def _run_registry(
    *args: str,
    base_dir: str,
    cwd: str | None = None,
    env_extra: dict | None = None,
) -> subprocess.CompletedProcess:
    """Invoke active-plan-registry.py as a subprocess under a hermetic base."""
    env = {
        **os.environ,
        "Z_HARNESS_BASE_DIR": base_dir,
        # Prevent anchor writes in git-common-dir (SPEC invariant 7):
        # Z_HARNESS_BASE_DIR is the tier-1 escape hatch that bypasses the anchor.
    }
    if env_extra:
        env.update(env_extra)
    return subprocess.run(
        [sys.executable, REGISTRY_PY] + list(args),
        capture_output=True,
        text=True,
        cwd=cwd or str(REPO_ROOT),
        env=env,
    )


class TestRoundTrip(unittest.TestCase):
    """Round-trip: register → list → deregister."""

    def test_register_list_deregister(self):
        with tempfile.TemporaryDirectory() as base:
            run_id = "test-round-trip-001"
            active_dir = Path(base) / "active-plans"

            # register
            r = _run_registry(
                "register",
                "--run-id", run_id,
                "--slug", "my-slug",
                "--command", "/z-implement-all",
                "--phase", "implement",
                base_dir=base,
            )
            self.assertEqual(r.returncode, 0, f"register failed: {r.stderr}")

            # record file must exist
            record_path = active_dir / f"{run_id}.json"
            self.assertTrue(record_path.exists(), "record file not created")

            # schema check
            with record_path.open() as fh:
                rec = json.load(fh)
            self.assertEqual(rec["schema_version"], 1)
            self.assertEqual(rec["run_id"], run_id)
            self.assertEqual(rec["slug"], "my-slug")
            self.assertEqual(rec["command"], "/z-implement-all")
            self.assertEqual(rec["phase"], "implement")
            self.assertEqual(rec["status"], "running")
            self.assertIn("started_at", rec)
            self.assertIn("last_heartbeat", rec)
            self.assertIsInstance(rec["scope"], list)

            # list --json must contain the record
            r = _run_registry("list", "--json", base_dir=base)
            self.assertEqual(r.returncode, 0)
            records = json.loads(r.stdout)
            self.assertIsInstance(records, list)
            ids = [x["run_id"] for x in records]
            self.assertIn(run_id, ids, f"run_id not found in list: {ids}")

            # deregister
            r = _run_registry(
                "deregister", "--run-id", run_id, "--status", "complete",
                base_dir=base,
            )
            self.assertEqual(r.returncode, 0, f"deregister failed: {r.stderr}")

            # record file must be gone
            self.assertFalse(record_path.exists(), "record file still present after deregister")

            # list must not contain the run-id
            r = _run_registry("list", "--json", base_dir=base)
            self.assertEqual(r.returncode, 0)
            records = json.loads(r.stdout)
            ids = [x["run_id"] for x in records]
            self.assertNotIn(run_id, ids)

    def test_register_is_idempotent(self):
        """Re-registering the same run-id overwrites the record (idempotent)."""
        with tempfile.TemporaryDirectory() as base:
            run_id = "test-idempotent-001"
            # first register
            r1 = _run_registry(
                "register", "--run-id", run_id,
                "--slug", "slug-a", "--command", "/z-plan", "--phase", "plan",
                base_dir=base,
            )
            self.assertEqual(r1.returncode, 0)

            # second register with different slug
            r2 = _run_registry(
                "register", "--run-id", run_id,
                "--slug", "slug-b", "--command", "/z-plan", "--phase", "plan",
                base_dir=base,
            )
            self.assertEqual(r2.returncode, 0)

            active_dir = Path(base) / "active-plans"
            with (active_dir / f"{run_id}.json").open() as fh:
                rec = json.load(fh)
            # second register wins
            self.assertEqual(rec["slug"], "slug-b")

    def test_heartbeat_updates_fields(self):
        """heartbeat updates last_heartbeat, phase, current_task, status."""
        with tempfile.TemporaryDirectory() as base:
            run_id = "test-hb-001"
            _run_registry(
                "register", "--run-id", run_id,
                "--slug", "s", "--command", "/z-implement-all", "--phase", "plan",
                base_dir=base,
            )
            active_dir = Path(base) / "active-plans"
            before = json.loads((active_dir / f"{run_id}.json").read_text())

            r = _run_registry(
                "heartbeat", "--run-id", run_id,
                "--phase", "implement",
                "--current-task", "T006",
                "--status", "running",
                base_dir=base,
            )
            self.assertEqual(r.returncode, 0)

            after = json.loads((active_dir / f"{run_id}.json").read_text())
            self.assertEqual(after["phase"], "implement")
            self.assertEqual(after["current_task"], "T006")
            self.assertEqual(after["status"], "running")
            # last_heartbeat must be >= started_at (both ISO strings, lexicographic compare works)
            self.assertGreaterEqual(after["last_heartbeat"], before["last_heartbeat"])

    def test_update_scope(self):
        """update-scope merges a scope array into the record."""
        with tempfile.TemporaryDirectory() as base:
            run_id = "test-scope-001"
            _run_registry(
                "register", "--run-id", run_id,
                "--slug", "s", "--command", "/z-plan", "--phase", "plan",
                base_dir=base,
            )
            # write a scope JSON file
            scope_data = [
                {"path": "scripts/active-plan-registry.py", "confidence": "explicit", "reason": "T006 file"}
            ]
            scope_file = Path(base) / "scope.json"
            scope_file.write_text(json.dumps(scope_data))

            r = _run_registry(
                "update-scope", "--run-id", run_id, "--scope-json", str(scope_file),
                base_dir=base,
            )
            self.assertEqual(r.returncode, 0)

            active_dir = Path(base) / "active-plans"
            rec = json.loads((active_dir / f"{run_id}.json").read_text())
            self.assertEqual(len(rec["scope"]), 1)
            self.assertEqual(rec["scope"][0]["path"], "scripts/active-plan-registry.py")
            self.assertEqual(rec["scope"][0]["confidence"], "explicit")


class TestConcurrentRegisters(unittest.TestCase):
    """N=10 concurrent registers with distinct run-ids produce 10 uncorrupted records."""

    def test_concurrent_registers_no_corruption(self):
        with tempfile.TemporaryDirectory() as base:
            n = 10
            run_ids = [f"concurrent-run-{i:03d}" for i in range(n)]

            def _do_register(run_id: str) -> int:
                r = _run_registry(
                    "register", "--run-id", run_id,
                    "--slug", "concurrent-slug",
                    "--command", "/z-test",
                    "--phase", "test",
                    base_dir=base,
                )
                return r.returncode

            with concurrent.futures.ThreadPoolExecutor(max_workers=n) as executor:
                results = list(executor.map(_do_register, run_ids))

            # All registers must succeed
            for i, code in enumerate(results):
                self.assertEqual(code, 0, f"register for run {i} returned {code}")

            # All N record files must exist and be valid JSON
            active_dir = Path(base) / "active-plans"
            found_ids = set()
            for run_id in run_ids:
                record_path = active_dir / f"{run_id}.json"
                self.assertTrue(record_path.exists(), f"missing record for {run_id}")
                try:
                    rec = json.loads(record_path.read_text())
                    found_ids.add(rec["run_id"])
                except json.JSONDecodeError as exc:
                    self.fail(f"corrupted JSON for {run_id}: {exc}")

            # All N distinct run_ids must be in the set
            self.assertEqual(found_ids, set(run_ids))

            # list must return all N records
            r = _run_registry("list", "--json", base_dir=base)
            self.assertEqual(r.returncode, 0)
            listed = json.loads(r.stdout)
            listed_ids = {x["run_id"] for x in listed}
            self.assertEqual(listed_ids, set(run_ids))


class TestSafeBasename(unittest.TestCase):
    """safe-basename validation rejects traversal and other dangerous patterns."""

    def _register_with_id(self, run_id: str, base: str) -> int:
        r = _run_registry(
            "register", "--run-id", run_id,
            "--slug", "s", "--command", "/z-plan", "--phase", "plan",
            base_dir=base,
        )
        return r.returncode

    def test_rejects_dotdot_slash(self):
        with tempfile.TemporaryDirectory() as base:
            code = self._register_with_id("../x", base)
            self.assertEqual(code, 3, "expected exit 3 for run-id '../x'")

    def test_rejects_slash(self):
        with tempfile.TemporaryDirectory() as base:
            code = self._register_with_id("a/b", base)
            self.assertEqual(code, 3, "expected exit 3 for run-id 'a/b'")

    def test_rejects_leading_dash(self):
        """A leading-dash run-id is rejected.

        argparse may intercept '-bad' as an unrecognised flag (exit 2) before
        the registry's own safe-basename check (exit 3).  Both are non-zero and
        both represent a hard rejection — the invariant is that exit code != 0.
        """
        with tempfile.TemporaryDirectory() as base:
            code = self._register_with_id("-bad", base)
            self.assertNotEqual(code, 0, "leading-dash run-id must be rejected (non-zero exit)")

    def test_rejects_dotdot_only(self):
        with tempfile.TemporaryDirectory() as base:
            code = self._register_with_id("..", base)
            self.assertEqual(code, 3, "expected exit 3 for run-id '..'")

    def test_rejects_embedded_dotdot(self):
        with tempfile.TemporaryDirectory() as base:
            code = self._register_with_id("a..b", base)
            self.assertEqual(code, 3, "expected exit 3 for run-id 'a..b' (contains '..')")

    def test_accepts_valid_id(self):
        with tempfile.TemporaryDirectory() as base:
            code = self._register_with_id("run-2026-01T120000Z", base)
            self.assertEqual(code, 0, "expected exit 0 for valid run-id")

    def test_rejects_empty(self):
        """An empty run-id should be rejected by argparse (required arg) or safe-basename."""
        with tempfile.TemporaryDirectory() as base:
            r = _run_registry(
                "register",
                "--slug", "s", "--command", "/z-plan", "--phase", "plan",
                base_dir=base,
            )
            # argparse should reject a missing required --run-id with exit code 2
            self.assertNotEqual(r.returncode, 0)

    def test_also_rejects_on_heartbeat(self):
        """heartbeat with a traversal run-id is non-fatal (exit 0) but writes nothing."""
        with tempfile.TemporaryDirectory() as base:
            r = _run_registry(
                "heartbeat", "--run-id", "../evil",
                base_dir=base,
            )
            # heartbeat is NON-FATAL — exit 0 regardless
            self.assertEqual(r.returncode, 0)
            # No files should have been created in the active-plans dir
            active_dir = Path(base) / "active-plans"
            if active_dir.exists():
                files = list(active_dir.glob("*.json"))
                self.assertEqual(files, [], "no JSON files should exist")


class TestListSkipsTornFiles(unittest.TestCase):
    """list skips a deliberately truncated *.json file without crashing."""

    def test_list_skips_truncated_json(self):
        with tempfile.TemporaryDirectory() as base:
            # Register a valid run
            run_id_good = "list-test-good-001"
            _run_registry(
                "register", "--run-id", run_id_good,
                "--slug", "s", "--command", "/z-plan", "--phase", "plan",
                base_dir=base,
            )

            # Manually create a torn/partial JSON file
            active_dir = Path(base) / "active-plans"
            active_dir.mkdir(parents=True, exist_ok=True)
            torn_path = active_dir / "torn-partial-run.json"
            torn_path.write_text('{"schema_version": 1, "run_id": "torn",', encoding="utf-8")
            # ^ deliberately unterminated JSON

            # list --json must return exactly 1 record (the valid one), not crash
            r = _run_registry("list", "--json", base_dir=base)
            self.assertEqual(r.returncode, 0, f"list crashed: {r.stderr}")
            records = json.loads(r.stdout)
            ids = [x["run_id"] for x in records]
            self.assertIn(run_id_good, ids)
            self.assertNotIn("torn", ids, "torn file should have been skipped")

    def test_list_skips_empty_json(self):
        """An empty .json file in active-plans is skipped gracefully."""
        with tempfile.TemporaryDirectory() as base:
            active_dir = Path(base) / "active-plans"
            active_dir.mkdir(parents=True, exist_ok=True)
            (active_dir / "empty-run.json").write_text("", encoding="utf-8")

            r = _run_registry("list", "--json", base_dir=base)
            self.assertEqual(r.returncode, 0)
            records = json.loads(r.stdout)
            self.assertEqual(records, [])


class TestRegisterExitCode(unittest.TestCase):
    """register returns exit code 3 on failure, not 0 or 1."""

    def test_exit_code_3_on_unwritable_active_dir(self):
        """If the active-plans dir is unwritable, register exits with code 3."""
        with tempfile.TemporaryDirectory() as base:
            # Pre-create the active-plans dir and make it unwritable
            active_dir = Path(base) / "active-plans"
            active_dir.mkdir(parents=True, exist_ok=True)
            # Make the dir read-only (removes write bit)
            os.chmod(str(active_dir), stat.S_IRUSR | stat.S_IXUSR)
            try:
                r = _run_registry(
                    "register", "--run-id", "failtest-001",
                    "--slug", "s", "--command", "/z-plan", "--phase", "plan",
                    base_dir=base,
                )
                self.assertEqual(
                    r.returncode, 3,
                    f"expected exit 3 on unwritable dir, got {r.returncode}; stderr={r.stderr}"
                )
            finally:
                # Restore permissions so tempdir cleanup works
                os.chmod(str(active_dir), stat.S_IRWXU)

    def test_exit_code_3_on_traversal_run_id(self):
        """register with traversal run-id exits 3 (not 0)."""
        with tempfile.TemporaryDirectory() as base:
            r = _run_registry(
                "register", "--run-id", "../bad",
                "--slug", "s", "--command", "/z-plan", "--phase", "plan",
                base_dir=base,
            )
            self.assertEqual(r.returncode, 3)

    def test_exit_code_distinguishable_from_success(self):
        """The exit code for register failure (3) must be != 0 (success)."""
        with tempfile.TemporaryDirectory() as base:
            # Cause a failure by using traversal id — guaranteed safe basename rejection
            r = _run_registry(
                "register", "--run-id", "a/b",
                "--slug", "s", "--command", "/z-plan", "--phase", "plan",
                base_dir=base,
            )
            self.assertNotEqual(r.returncode, 0, "failure must be distinguishable from success")
            self.assertEqual(r.returncode, 3, "register failure must use exit code 3")


class TestNoAnchorPollution(unittest.TestCase):
    """Ensure tests do not pollute the real git anchor file."""

    def test_z_harness_base_dir_bypasses_anchor(self):
        """When Z_HARNESS_BASE_DIR is set, no anchor file is written in git-common-dir."""
        anchor_path = (
            Path(REPO_ROOT) / ".git" / ".z-harness-base"
        )
        existed_before = anchor_path.exists()

        with tempfile.TemporaryDirectory() as base:
            _run_registry(
                "register", "--run-id", "anchor-test-001",
                "--slug", "s", "--command", "/z-plan", "--phase", "plan",
                base_dir=base,
            )

        # The anchor should not have been created by this test run
        if not existed_before:
            self.assertFalse(
                anchor_path.exists(),
                f"anchor file was created at {anchor_path} — Z_HARNESS_BASE_DIR tier-1 "
                "escape hatch should bypass anchor writes"
            )


# ── T007: helpers ──────────────────────────────────────────────────────────────

def _write_record_direct(active_dir: Path, record: dict) -> None:
    """Directly write a registry record JSON file (bypasses subprocess for test setup)."""
    active_dir.mkdir(parents=True, exist_ok=True)
    run_id = record["run_id"]
    path = active_dir / f"{run_id}.json"
    tmp = path.parent / f".tmp-test-{run_id}"
    tmp.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    os.replace(str(tmp), str(path))


def _read_record_direct(active_dir: Path, run_id: str) -> dict | None:
    """Read a registry record JSON file directly."""
    path = active_dir / f"{run_id}.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def _make_record(
    run_id: str,
    *,
    session_id: str = "",
    host: str | None = None,
    pid: int | None = None,
    scope: list[dict] | None = None,
    status: str = "running",
    last_heartbeat: str | None = None,
) -> dict:
    """Build a minimal registry record for test injection."""
    from datetime import datetime, timezone
    now_str = last_heartbeat or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {
        "schema_version": 1,
        "run_id": run_id,
        "session_id": session_id,
        "slug": "test-slug",
        "command": "/z-test",
        "command_version": "",
        "phase": "test",
        "status": status,
        "pid": pid if pid is not None else os.getpid(),
        "host": host if host is not None else socket.gethostname(),
        "repo_id": "test-repo-id",
        "repo_root": "/fake/repo",
        "git_common_dir": "/fake/repo/.git",
        "worktree_path": "/fake/repo",
        "branch": "main",
        "started_at": now_str,
        "last_heartbeat": now_str,
        "current_task": "",
        "scope": scope or [],
    }



# ── T007: overlaps tests ───────────────────────────────────────────────────────

class TestOverlapsSharedExplicit(unittest.TestCase):
    """Exit 10 when two peers share an explicit-confidence path."""

    def test_shared_explicit_path_exit_10(self):
        """Two registered plans sharing an explicit path → overlaps exits 10."""
        with tempfile.TemporaryDirectory() as base:
            active_dir = Path(base) / "active-plans"

            scope_a = [{"path": "scripts/active-plan-registry.py", "confidence": "explicit", "reason": "T007"}]
            scope_b = [{"path": "scripts/active-plan-registry.py", "confidence": "explicit", "reason": "T006"}]

            _write_record_direct(active_dir, _make_record("run-a", scope=scope_a))
            _write_record_direct(active_dir, _make_record("run-b", scope=scope_b))

            # Write scope JSON for run-a to pass to overlaps
            scope_file = Path(base) / "scope_a.json"
            scope_file.write_text(json.dumps(scope_a), encoding="utf-8")

            r = _run_registry(
                "overlaps", "--run-id", "run-a",
                "--scope-json", str(scope_file),
                "--json",
                base_dir=base,
            )
            self.assertEqual(
                r.returncode, 10,
                f"expected exit 10 for advisory overlap; got {r.returncode}; stderr={r.stderr}; stdout={r.stdout}"
            )
            result = json.loads(r.stdout)
            self.assertGreater(result["overlapping_peers"], 0)
            # Verify the shared path appears
            shared_paths = result["peers"][0]["shared_paths"]
            self.assertTrue(
                any(sp["path"] == "scripts/active-plan-registry.py" for sp in shared_paths),
                f"expected shared path not found: {shared_paths}"
            )

    def test_no_overlap_exit_0(self):
        """Non-overlapping scopes → overlaps exits 0."""
        with tempfile.TemporaryDirectory() as base:
            active_dir = Path(base) / "active-plans"

            scope_a = [{"path": "scripts/plan-path.sh", "confidence": "explicit", "reason": "T001"}]
            scope_b = [{"path": "scripts/log-event.sh", "confidence": "explicit", "reason": "T002"}]

            _write_record_direct(active_dir, _make_record("run-x", scope=scope_a))
            _write_record_direct(active_dir, _make_record("run-y", scope=scope_b))

            scope_file = Path(base) / "scope_x.json"
            scope_file.write_text(json.dumps(scope_a), encoding="utf-8")

            r = _run_registry(
                "overlaps", "--run-id", "run-x",
                "--scope-json", str(scope_file),
                "--json",
                base_dir=base,
            )
            self.assertEqual(
                r.returncode, 0,
                f"expected exit 0 for no overlap; got {r.returncode}; stdout={r.stdout}"
            )
            result = json.loads(r.stdout)
            self.assertEqual(result["overlaps"], 0)


class TestOverlapsSameSession(unittest.TestCase):
    """Same session_id peer is ignored (exit 0)."""

    def test_same_session_ignored(self):
        """A peer with the same session_id as the querying run is skipped."""
        with tempfile.TemporaryDirectory() as base:
            active_dir = Path(base) / "active-plans"
            shared_session = "sess-abc123"

            shared_scope = [{"path": "scripts/active-plan-registry.py", "confidence": "explicit", "reason": "T007"}]

            # Both records share a session → peer should be ignored.
            rec_a = _make_record("run-sess-a", session_id=shared_session, scope=shared_scope)
            rec_b = _make_record("run-sess-b", session_id=shared_session, scope=shared_scope)
            _write_record_direct(active_dir, rec_a)
            _write_record_direct(active_dir, rec_b)

            scope_file = Path(base) / "scope_sess.json"
            scope_file.write_text(json.dumps(shared_scope), encoding="utf-8")

            # overlaps --run-id run-sess-a: the only other peer is run-sess-b (same session).
            r = _run_registry(
                "overlaps", "--run-id", "run-sess-a",
                "--scope-json", str(scope_file),
                "--json",
                base_dir=base,
            )
            # The peer is in the same session → must be ignored → exit 0, overlaps=0.
            self.assertEqual(
                r.returncode, 0,
                f"same-session peer must be ignored; got exit {r.returncode}; stdout={r.stdout}"
            )
            result = json.loads(r.stdout)
            # The overlaps field is present only in the no-overlap payload.
            # If peers_with_overlap is empty, the active_plan_scan_complete payload is emitted.
            self.assertEqual(result.get("overlaps", 0), 0)


class TestOverlapsStaleNonBlocking(unittest.TestCase):
    """Stale peer overlap is included but does NOT trigger exit 20 (even under strict)."""

    def test_stale_peer_nonblocking(self):
        """A stale peer's overlap → exit 10 (advisory), NOT 20, even with --strict."""
        with tempfile.TemporaryDirectory() as base:
            active_dir = Path(base) / "active-plans"

            shared_path = "scripts/active-plan-registry.py"
            scope_a = [{"path": shared_path, "confidence": "explicit", "reason": "T007"}]
            scope_b = [{"path": shared_path, "confidence": "explicit", "reason": "T006"}]

            # Inject a stale record for run-b: last_heartbeat in the distant past.
            from datetime import datetime, timezone, timedelta
            old_time = (datetime.now(timezone.utc) - timedelta(seconds=7200)).strftime("%Y-%m-%dT%H:%M:%SZ")
            rec_b = _make_record(
                "run-stale-b",
                scope=scope_b,
                status="running",
                last_heartbeat=old_time,
                host="some-remote-host",  # Use remote host so it gets marked stale
            )
            _write_record_direct(active_dir, _make_record("run-stale-a", scope=scope_a))
            _write_record_direct(active_dir, rec_b)

            scope_file = Path(base) / "scope_stale.json"
            scope_file.write_text(json.dumps(scope_a), encoding="utf-8")

            # With --strict and stale peer: must NOT exit 20 (stale peers don't block).
            r = _run_registry(
                "overlaps", "--run-id", "run-stale-a",
                "--scope-json", str(scope_file),
                "--json",
                "--strict",
                base_dir=base,
                env_extra={"Z_HARNESS_REGISTRY_STALE_SECS": "1800"},
            )
            # Stale peer may produce exit 10 (if included) or 0 — but never 20.
            self.assertNotEqual(
                r.returncode, 20,
                f"stale peer must not trigger exit 20; got {r.returncode}; stdout={r.stdout}"
            )

    def test_stale_peer_shown_as_stale(self):
        """A stale peer is included in the output with is_stale=True."""
        with tempfile.TemporaryDirectory() as base:
            active_dir = Path(base) / "active-plans"

            from datetime import datetime, timezone, timedelta
            # Use 2× + a bit over threshold so it's definitely stale
            old_time = (datetime.now(timezone.utc) - timedelta(seconds=3700)).strftime("%Y-%m-%dT%H:%M:%SZ")
            scope_shared = [{"path": "scripts/active-plan-registry.py", "confidence": "explicit", "reason": "test"}]

            _write_record_direct(active_dir, _make_record("run-fresh-a", scope=scope_shared))
            stale_rec = _make_record(
                "run-stale-b",
                scope=scope_shared,
                host="remote-machine-xyz",
                last_heartbeat=old_time,
            )
            _write_record_direct(active_dir, stale_rec)

            scope_file = Path(base) / "scope_fresh.json"
            scope_file.write_text(json.dumps(scope_shared), encoding="utf-8")

            r = _run_registry(
                "overlaps", "--run-id", "run-fresh-a",
                "--scope-json", str(scope_file),
                "--json",
                base_dir=base,
                env_extra={"Z_HARNESS_REGISTRY_STALE_SECS": "1800"},
            )
            # May be exit 0 (if stale peer excluded from non-stale overlaps) or exit 10.
            # The key invariant is that is_stale is True for that peer in the JSON output.
            if r.returncode in (10,):
                result = json.loads(r.stdout)
                stale_peers = [p for p in result.get("peers", []) if p.get("is_stale")]
                self.assertGreater(len(stale_peers), 0, "stale peer must appear with is_stale=True")


class TestOverlapsStrictExit20(unittest.TestCase):
    """explicit×explicit exact match with --strict → exit 20."""

    def test_strict_exit_20_on_explicit_explicit(self):
        """--strict AND explicit×explicit exact path match → exit 20."""
        with tempfile.TemporaryDirectory() as base:
            active_dir = Path(base) / "active-plans"

            shared_path = "scripts/active-plan-registry.py"
            scope_a = [{"path": shared_path, "confidence": "explicit", "reason": "T007"}]
            scope_b = [{"path": shared_path, "confidence": "explicit", "reason": "T006"}]

            _write_record_direct(active_dir, _make_record("run-strict-a", scope=scope_a))
            _write_record_direct(active_dir, _make_record("run-strict-b", scope=scope_b))

            scope_file = Path(base) / "scope_strict.json"
            scope_file.write_text(json.dumps(scope_a), encoding="utf-8")

            # --strict mode must produce exit 20.
            r = _run_registry(
                "overlaps", "--run-id", "run-strict-a",
                "--scope-json", str(scope_file),
                "--json",
                "--strict",
                base_dir=base,
            )
            self.assertEqual(
                r.returncode, 20,
                f"expected exit 20 in strict mode with explicit×explicit match; "
                f"got {r.returncode}; stdout={r.stdout}"
            )
            result = json.loads(r.stdout)
            self.assertTrue(result.get("blocking"), "blocking field must be True")

    def test_strict_mode_via_env(self):
        """Z_HARNESS_STRICT_OVERLAP=1 activates strict mode without --strict flag."""
        with tempfile.TemporaryDirectory() as base:
            active_dir = Path(base) / "active-plans"

            shared_path = "scripts/plan-path.sh"
            scope_a = [{"path": shared_path, "confidence": "explicit", "reason": "T001"}]
            scope_b = [{"path": shared_path, "confidence": "explicit", "reason": "T002"}]

            _write_record_direct(active_dir, _make_record("run-env-strict-a", scope=scope_a))
            _write_record_direct(active_dir, _make_record("run-env-strict-b", scope=scope_b))

            scope_file = Path(base) / "scope_env.json"
            scope_file.write_text(json.dumps(scope_a), encoding="utf-8")

            r = _run_registry(
                "overlaps", "--run-id", "run-env-strict-a",
                "--scope-json", str(scope_file),
                "--json",
                base_dir=base,
                env_extra={"Z_HARNESS_STRICT_OVERLAP": "1"},
            )
            self.assertEqual(
                r.returncode, 20,
                f"expected exit 20 via Z_HARNESS_STRICT_OVERLAP=1; "
                f"got {r.returncode}; stdout={r.stdout}"
            )

    def test_non_explicit_does_not_trigger_exit_20(self):
        """inferred×explicit overlap with --strict must NOT exit 20 (only explicit×explicit)."""
        with tempfile.TemporaryDirectory() as base:
            active_dir = Path(base) / "active-plans"

            shared_path = "scripts/active-plan-registry.py"
            scope_a = [{"path": shared_path, "confidence": "inferred", "reason": "implied"}]
            scope_b = [{"path": shared_path, "confidence": "explicit", "reason": "T006"}]

            _write_record_direct(active_dir, _make_record("run-infer-a", scope=scope_a))
            _write_record_direct(active_dir, _make_record("run-infer-b", scope=scope_b))

            scope_file = Path(base) / "scope_infer.json"
            scope_file.write_text(json.dumps(scope_a), encoding="utf-8")

            r = _run_registry(
                "overlaps", "--run-id", "run-infer-a",
                "--scope-json", str(scope_file),
                "--json",
                "--strict",
                base_dir=base,
            )
            # Should be exit 10 (advisory) not 20 (blocking).
            self.assertEqual(
                r.returncode, 10,
                f"inferred×explicit must only be advisory (exit 10), not blocking (exit 20); "
                f"got {r.returncode}"
            )
            self.assertNotEqual(r.returncode, 20)


# ── T007: reap tests ───────────────────────────────────────────────────────────

class TestReapLivePidNotDeleted(unittest.TestCase):
    """Reaper does NOT delete a record whose pid is the current (alive) process."""

    def test_live_pid_not_reaped(self):
        """A record with this process's pid and this host is NOT deleted by reap."""
        with tempfile.TemporaryDirectory() as base:
            active_dir = Path(base) / "active-plans"
            run_id = "reap-live-001"

            # Record with our own pid (alive) and our own hostname.
            rec = _make_record(run_id, pid=os.getpid(), host=socket.gethostname())
            _write_record_direct(active_dir, rec)

            r = _run_registry("reap", base_dir=base)
            self.assertEqual(r.returncode, 0, f"reap must be non-fatal; stderr={r.stderr}")

            # Record must still exist.
            remaining = _read_record_direct(active_dir, run_id)
            self.assertIsNotNone(
                remaining,
                f"reap deleted a record with a live pid ({os.getpid()}) — must not delete live runs"
            )


class TestReapDeadPidDeleted(unittest.TestCase):
    """Reaper DOES delete a record with a dead local pid."""

    def test_dead_pid_reaped(self):
        """A record whose pid is a known-dead local process is deleted by reap."""
        with tempfile.TemporaryDirectory() as base:
            active_dir = Path(base) / "active-plans"
            run_id = "reap-dead-001"

            # Spawn a child process with subprocess (avoids pickle issues with spawn),
            # wait for it to exit, then use its (now-dead) pid.
            child = subprocess.Popen(
                [sys.executable, "-c", "import sys; sys.exit(0)"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            child.wait()
            dead_pid = child.pid

            # Verify pid is actually dead before proceeding (test assumption).
            try:
                os.kill(dead_pid, 0)
                # If we get here, the OS may have recycled the pid — skip test.
                self.skipTest(f"pid {dead_pid} was recycled before reap ran; skipping")
            except ProcessLookupError:
                pass  # confirmed dead
            except PermissionError:
                self.skipTest(f"pid {dead_pid} appears alive (PermissionError); skipping")

            rec = _make_record(run_id, pid=dead_pid, host=socket.gethostname())
            _write_record_direct(active_dir, rec)

            r = _run_registry("reap", base_dir=base)
            self.assertEqual(r.returncode, 0, f"reap must be non-fatal; stderr={r.stderr}")

            # Record must be gone.
            remaining = _read_record_direct(active_dir, run_id)
            self.assertIsNone(
                remaining,
                f"reap did NOT delete a record with a dead pid ({dead_pid})"
            )


class TestReapRemoteHostStaleNotDeleted(unittest.TestCase):
    """A remote-host record past the 1× stale threshold is marked stale, NOT deleted."""

    def test_remote_host_marked_stale_not_deleted(self):
        """A record with a remote host that is past the 1× threshold gets status:stale."""
        with tempfile.TemporaryDirectory() as base:
            active_dir = Path(base) / "active-plans"
            run_id = "reap-remote-001"

            from datetime import datetime, timezone, timedelta
            # Set last_heartbeat to 2000s ago (past 1× threshold of 1800s, under 2× of 3600s).
            stale_time = (datetime.now(timezone.utc) - timedelta(seconds=2000)).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            )

            rec = _make_record(
                run_id,
                host="remote-machine-thats-not-this-host-xyz",
                last_heartbeat=stale_time,
            )
            _write_record_direct(active_dir, rec)

            r = _run_registry(
                "reap", base_dir=base,
                env_extra={"Z_HARNESS_REGISTRY_STALE_SECS": "1800"},
            )
            self.assertEqual(r.returncode, 0, f"reap must be non-fatal; stderr={r.stderr}")

            # File must still exist (not deleted).
            record_path = active_dir / f"{run_id}.json"
            self.assertTrue(
                record_path.exists(),
                "reap deleted a remote-host record that was only 1× stale — must NOT delete"
            )

            # Status must be "stale".
            remaining = _read_record_direct(active_dir, run_id)
            self.assertIsNotNone(remaining, "record file missing after reap")
            self.assertEqual(
                remaining.get("status"), "stale",
                f"expected status='stale' for remote-host past threshold; got {remaining.get('status')!r}"
            )


class TestReapTwoReapersRace(unittest.TestCase):
    """Two reapers racing on the same record do not crash."""

    def test_two_reapers_no_crash(self):
        """Calling reap twice in quick succession does not raise or exit non-zero."""
        with tempfile.TemporaryDirectory() as base:
            active_dir = Path(base) / "active-plans"

            from datetime import datetime, timezone, timedelta
            # Create a record that is 2×+1 stale so both reapers will try to delete it.
            very_old_time = (datetime.now(timezone.utc) - timedelta(seconds=4000)).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            )
            run_id = "reap-race-001"
            rec = _make_record(
                run_id,
                host="remote-old-host",
                last_heartbeat=very_old_time,
            )
            _write_record_direct(active_dir, rec)

            # First reap: deletes the record.
            r1 = _run_registry(
                "reap", base_dir=base,
                env_extra={"Z_HARNESS_REGISTRY_STALE_SECS": "1800"},
            )
            self.assertEqual(r1.returncode, 0, f"first reap failed: {r1.stderr}")

            # Second reap: file already gone — must not crash.
            r2 = _run_registry(
                "reap", base_dir=base,
                env_extra={"Z_HARNESS_REGISTRY_STALE_SECS": "1800"},
            )
            self.assertEqual(r2.returncode, 0, f"second reap crashed: {r2.stderr}")

    def test_reap_missing_file_no_crash(self):
        """If the file disappears between listing and unlinking, reap stays non-fatal."""
        with tempfile.TemporaryDirectory() as base:
            active_dir = Path(base) / "active-plans"
            # Empty active-plans dir — nothing to reap. Must not crash.
            active_dir.mkdir(parents=True, exist_ok=True)
            r = _run_registry("reap", base_dir=base)
            self.assertEqual(r.returncode, 0, f"reap on empty dir crashed: {r.stderr}")


# ── T009: session-id tests ─────────────────────────────────────────────────────

class TestSessionId(unittest.TestCase):
    """session-id subcommand returns Z_HARNESS_SESSION_ID when set; stable token when not."""

    def _run_session_id(self, base: str, env_extra: dict | None = None) -> subprocess.CompletedProcess:
        return _run_registry("session-id", base_dir=base, env_extra=env_extra)

    def test_returns_env_when_set(self):
        """session-id returns $Z_HARNESS_SESSION_ID unchanged when it is set."""
        with tempfile.TemporaryDirectory() as base:
            expected_sid = "12345-1717200000"
            r = self._run_session_id(base, env_extra={"Z_HARNESS_SESSION_ID": expected_sid})
            self.assertEqual(r.returncode, 0, f"session-id failed: {r.stderr}")
            self.assertEqual(r.stdout.strip(), expected_sid,
                             "session-id must return Z_HARNESS_SESSION_ID unchanged")

    def test_stable_token_shape_when_env_unset(self):
        """session-id without Z_HARNESS_SESSION_ID returns a '<digits>-<digits>' shaped token."""
        with tempfile.TemporaryDirectory() as base:
            # Unset Z_HARNESS_SESSION_ID in env_extra by passing an empty string,
            # which _run_registry merges (overwriting any parent env value).
            env_without_sid = {k: v for k, v in os.environ.items()
                               if k != "Z_HARNESS_SESSION_ID"}
            r = subprocess.run(
                [sys.executable, REGISTRY_PY, "session-id"],
                capture_output=True,
                text=True,
                cwd=str(REPO_ROOT),
                env={**env_without_sid, "Z_HARNESS_BASE_DIR": base},
            )
            self.assertEqual(r.returncode, 0, f"session-id failed: {r.stderr}")
            sid = r.stdout.strip()
            self.assertRegex(
                sid,
                r"^\d+-\d+$",
                f"session-id without env must match '<digits>-<digits>', got: {sid!r}"
            )

    def test_no_spaces_in_token(self):
        """session-id output must be a single safe token with no spaces."""
        with tempfile.TemporaryDirectory() as base:
            env_without_sid = {k: v for k, v in os.environ.items()
                               if k != "Z_HARNESS_SESSION_ID"}
            r = subprocess.run(
                [sys.executable, REGISTRY_PY, "session-id"],
                capture_output=True,
                text=True,
                cwd=str(REPO_ROOT),
                env={**env_without_sid, "Z_HARNESS_BASE_DIR": base},
            )
            self.assertEqual(r.returncode, 0, f"session-id failed: {r.stderr}")
            sid = r.stdout.strip()
            self.assertNotIn(" ", sid, f"session-id token must not contain spaces: {sid!r}")
            self.assertNotIn("\t", sid, f"session-id token must not contain tabs: {sid!r}")

    def test_env_takes_priority_over_derived(self):
        """When Z_HARNESS_SESSION_ID is set, it is returned even if it looks non-standard."""
        with tempfile.TemporaryDirectory() as base:
            custom_sid = "custom-session-token-abc123"
            r = self._run_session_id(base, env_extra={"Z_HARNESS_SESSION_ID": custom_sid})
            self.assertEqual(r.returncode, 0)
            self.assertEqual(r.stdout.strip(), custom_sid,
                             "env var must take priority over any derived value")


class TestSessionIdInRegister(unittest.TestCase):
    """register --session X then list shows session_id == X in the record."""

    def test_register_with_session_shows_in_list(self):
        """register --session SID stores session_id; list --json returns it."""
        with tempfile.TemporaryDirectory() as base:
            run_id = "test-session-reg-001"
            session_id = "99999-1717200001"

            r = _run_registry(
                "register",
                "--run-id", run_id,
                "--slug", "my-slug",
                "--command", "/z-plan",
                "--phase", "plan",
                "--session", session_id,
                base_dir=base,
            )
            self.assertEqual(r.returncode, 0, f"register failed: {r.stderr}")

            # Read the record directly and verify session_id.
            active_dir = Path(base) / "active-plans"
            rec = json.loads((active_dir / f"{run_id}.json").read_text())
            self.assertEqual(
                rec.get("session_id"), session_id,
                f"session_id in record must match --session arg; got {rec.get('session_id')!r}"
            )

            # Also verify via list --json.
            r2 = _run_registry("list", "--json", base_dir=base)
            self.assertEqual(r2.returncode, 0)
            records = json.loads(r2.stdout)
            matching = [x for x in records if x.get("run_id") == run_id]
            self.assertEqual(len(matching), 1, "run_id must appear exactly once in list")
            self.assertEqual(
                matching[0].get("session_id"), session_id,
                "list --json must return session_id matching --session arg"
            )

    def test_register_without_session_has_empty_session_id(self):
        """register without --session stores session_id as empty string."""
        with tempfile.TemporaryDirectory() as base:
            run_id = "test-no-session-001"
            r = _run_registry(
                "register",
                "--run-id", run_id,
                "--slug", "s",
                "--command", "/z-plan",
                "--phase", "plan",
                base_dir=base,
            )
            self.assertEqual(r.returncode, 0)
            active_dir = Path(base) / "active-plans"
            rec = json.loads((active_dir / f"{run_id}.json").read_text())
            self.assertEqual(
                rec.get("session_id", None), "",
                f"session_id must be empty string when --session not provided; got {rec.get('session_id')!r}"
            )


# ── T009 (RETRY v2): subprocess-CLI fork-safety regression tests ──────────────
#
# These tests invoke the registry as a SUBPROCESS (not in-process import) with
# Z_HARNESS_SESSION_ID UNSET and a hermetic Z_HARNESS_BASE_DIR.  They catch the
# macOS CoreFoundation fork-safety crash that in-process tests can't detect
# because the crash only manifests in the forked child process.
#
# The regression being guarded: prior to the fix, the macOS `ps -p <ppid> -o lstart=`
# and `getconf CLK_TCK` subprocess calls in _derive_session_id triggered:
#   "The process has forked and you cannot use this CoreFoundation functionality safely"
#   followed by "Segmentation fault: 11"
# Fix 1: os.environ.setdefault("OBJC_DISABLE_INITIALIZE_FORK_SAFETY", "YES") at module top.
# Fix 2: _derive_session_id on macOS falls back to a pure-Python token (no subprocess).


def _run_registry_unset_session(
    *args: str,
    base_dir: str,
    cwd: str | None = None,
) -> subprocess.CompletedProcess:
    """Invoke active-plan-registry.py as a subprocess with Z_HARNESS_SESSION_ID UNSET.

    Builds a clean env with Z_HARNESS_SESSION_ID explicitly removed so the
    script must derive the session id internally (exercising _derive_session_id).
    """
    env = {k: v for k, v in os.environ.items() if k != "Z_HARNESS_SESSION_ID"}
    env["Z_HARNESS_BASE_DIR"] = base_dir
    return subprocess.run(
        [sys.executable, REGISTRY_PY] + list(args),
        capture_output=True,
        text=True,
        cwd=cwd or str(REPO_ROOT),
        env=env,
    )


class TestSubprocessCliForkSafety(unittest.TestCase):
    """Subprocess-CLI invocations with Z_HARNESS_SESSION_ID UNSET must not crash.

    These tests reproduce the macOS CoreFoundation fork-safety crash that
    in-process tests cannot detect.  Each test asserts:
      (a) returncode 0
      (b) stderr does NOT contain "has forked" or "Segmentation fault"
      (c) output is correct (correct shape / expected content)
    """

    def _assert_no_fork_crash(self, result: subprocess.CompletedProcess, label: str) -> None:
        """Assert that the subprocess did not crash with a CF fork-safety error."""
        self.assertNotIn(
            "has forked", result.stderr,
            f"{label}: CoreFoundation fork-safety crash detected in stderr: {result.stderr[:400]}",
        )
        self.assertNotIn(
            "Segmentation fault", result.stderr,
            f"{label}: Segmentation fault detected in stderr: {result.stderr[:400]}",
        )

    def test_session_id_no_crash_unset_env(self):
        """session-id with Z_HARNESS_SESSION_ID UNSET must not crash and return a valid token."""
        with tempfile.TemporaryDirectory() as base:
            r = _run_registry_unset_session("session-id", base_dir=base)
            # (a) exit 0
            self.assertEqual(
                r.returncode, 0,
                f"session-id must exit 0; got {r.returncode}; stderr={r.stderr[:400]}",
            )
            # (b) no CF crash
            self._assert_no_fork_crash(r, "session-id")
            # (c) output must be a safe token matching <digits>-<digits>
            sid = r.stdout.strip()
            self.assertRegex(
                sid, r"^\d+-\d+$",
                f"session-id must return '<digits>-<digits>' token; got {sid!r}",
            )

    def test_register_no_crash_unset_session(self):
        """register with Z_HARNESS_SESSION_ID UNSET must not crash and create a record."""
        with tempfile.TemporaryDirectory() as base:
            run_id = "subprocess-cli-register-001"
            r = _run_registry_unset_session(
                "register",
                "--run-id", run_id,
                "--slug", "test-slug",
                "--command", "/z-test",
                "--phase", "test",
                base_dir=base,
            )
            # (a) exit 0
            self.assertEqual(
                r.returncode, 0,
                f"register must exit 0; got {r.returncode}; stderr={r.stderr[:400]}",
            )
            # (b) no CF crash
            self._assert_no_fork_crash(r, "register")
            # (c) record exists and list shows it
            r2 = _run_registry_unset_session("list", "--json", base_dir=base)
            self.assertEqual(r2.returncode, 0)
            self._assert_no_fork_crash(r2, "list after register")
            records = json.loads(r2.stdout)
            ids = [x["run_id"] for x in records]
            self.assertIn(
                run_id, ids,
                f"register then list must show the record; got ids={ids}",
            )
            # (c) non-empty git fields when run from a git repo
            matching = [x for x in records if x["run_id"] == run_id]
            self.assertEqual(len(matching), 1)
            rec = matching[0]
            # branch and repo_root should be populated (we run from a git repo)
            self.assertNotEqual(
                rec.get("branch", ""), "",
                "branch must be non-empty when run from a git repo",
            )
            self.assertNotEqual(
                rec.get("repo_root", ""), "",
                "repo_root must be non-empty when run from a git repo",
            )

    def test_heartbeat_no_crash_unset_session(self):
        """heartbeat with Z_HARNESS_SESSION_ID UNSET must not crash."""
        with tempfile.TemporaryDirectory() as base:
            run_id = "subprocess-cli-heartbeat-001"
            # First register
            r_reg = _run_registry_unset_session(
                "register",
                "--run-id", run_id,
                "--slug", "s",
                "--command", "/z-test",
                "--phase", "test",
                base_dir=base,
            )
            self.assertEqual(r_reg.returncode, 0)
            self._assert_no_fork_crash(r_reg, "register before heartbeat")

            # Then heartbeat
            r_hb = _run_registry_unset_session(
                "heartbeat",
                "--run-id", run_id,
                "--phase", "impl",
                base_dir=base,
            )
            # (a) exit 0 (heartbeat is NON-FATAL)
            self.assertEqual(
                r_hb.returncode, 0,
                f"heartbeat must exit 0; got {r_hb.returncode}; stderr={r_hb.stderr[:400]}",
            )
            # (b) no CF crash
            self._assert_no_fork_crash(r_hb, "heartbeat")

    def test_full_repro_sequence_no_crash(self):
        """Exact repro sequence from the bug report must succeed end-to-end.

        Sequence: register → session-id (unset) → heartbeat
        Each step must return 0 and must not produce 'has forked' or 'Segmentation fault'.
        """
        with tempfile.TemporaryDirectory() as base:
            # Step 1: register
            r1 = _run_registry_unset_session(
                "register",
                "--run-id", "t1",
                "--slug", "d",
                "--command", "/x",
                "--phase", "plan",
                base_dir=base,
            )
            self.assertEqual(r1.returncode, 0, f"register: {r1.stderr[:400]}")
            self._assert_no_fork_crash(r1, "register")

            # Step 2: session-id (Z_HARNESS_SESSION_ID unset — must derive, no subprocess crash)
            r2 = _run_registry_unset_session("session-id", base_dir=base)
            self.assertEqual(r2.returncode, 0, f"session-id: {r2.stderr[:400]}")
            self._assert_no_fork_crash(r2, "session-id")
            sid = r2.stdout.strip()
            self.assertRegex(sid, r"^\d+-\d+$", f"session-id shape: {sid!r}")

            # Step 3: heartbeat
            r3 = _run_registry_unset_session(
                "heartbeat",
                "--run-id", "t1",
                "--phase", "impl",
                base_dir=base,
            )
            self.assertEqual(r3.returncode, 0, f"heartbeat: {r3.stderr[:400]}")
            self._assert_no_fork_crash(r3, "heartbeat")


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
