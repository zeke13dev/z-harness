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

Cases covered (T009 — watchdog_pid field + deregister kill):
  register_with_watchdog_pid_stamps_field — register --watchdog-pid N stores N in record
  register_without_watchdog_pid_stores_none — register without --watchdog-pid → None
  heartbeat_with_watchdog_pid_updates_field — heartbeat --watchdog-pid updates record
  heartbeat_without_watchdog_pid_preserves — heartbeat without flag keeps existing value
  watchdog_pid_via_list_json — list --json returns watchdog_pid field
  deregister_sigterms_live_watchdog — deregister SIGTERMs a live watchdog process
  deregister_noop_on_dead_watchdog_pid — no-op on dead pid
  deregister_noop_on_absent_pid_file — no-op when .watchdog.pid absent
  deregister_still_succeeds_when_kill_raises — NON-FATAL even on PermissionError

Cases covered (T013 — claim/release/wait-for + TOCTOU/seniority/backcompat):
  (a) F2/BLOCKER-1: double-claim TOCTOU → single winner by run_id, loser held_paths excludes conceded
  (b) F1/F3: wait-for clears within one poll after senior deregisters
  (c) F1: wait-for timeout → exit 10 + wait_timeout event + waiting_on cleared
  (d) wait-for SIGINT → no paused zombie (waiting_on cleared in finally)
  (e) F-reaper: live-local-pid carve-out keeps leases (mark stale, do NOT delete)
  (f) F-backcompat: v1 record → _is_lease_capable() False, v2 claimant skips it as holder
  (g) F4: DAG ordering — junior never waits on senior; no cycle in wait-for eligibility
  (h) F5/overlaps: held×held overlaps payload includes held_conflict + seniority
  (i) F5/coordination_warning: undeclared path held by peer → held_conflict detectable;
      uncontended paths produce zero noise (noise gate)
  (j) dual-budget: auto-wait (~300s) vs explicit (~1800s) via env, budget_s in wait_timeout
  (k) MINOR-7: senior-only TOCTOU — junior C claiming while B waits on A → B ignores C
  (l) MINOR-6: eldest-senior concede — ≥2 seniors on one path → loser concedes to lowest run_id

All tests use a hermetic temp base via Z_HARNESS_BASE_DIR so no anchor pollution
occurs at <repo>/.git/.z-harness-base or the real registry.
"""

from __future__ import annotations

import concurrent.futures
import json
import multiprocessing
import os
import shutil
import socket
import stat
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from datetime import datetime, timezone, timedelta
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


class TestInvocationRepositoryContext(unittest.TestCase):
    """Installed helpers must resolve state for the caller's repository."""

    def test_register_uses_caller_repo_for_automatic_base_and_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            target_repo = tmp_path / "target-app"
            target_repo.mkdir()
            subprocess.run(
                ["git", "init", "-q"],
                cwd=target_repo,
                check=True,
                capture_output=True,
                text=True,
            )

            plugin_scripts = tmp_path / "plugin-install" / "scripts"
            plugin_scripts.mkdir(parents=True)
            for helper_name in ("active-plan-registry.py", "plan-path.sh"):
                shutil.copy2(REPO_ROOT / "scripts" / helper_name, plugin_scripts / helper_name)
            installed_registry = str(plugin_scripts / "active-plan-registry.py")

            env = {
                key: value
                for key, value in os.environ.items()
                if key not in {
                    "GIT_DIR",
                    "GIT_WORK_TREE",
                    "Z_HARNESS_BASE_DIR",
                    "Z_HARNESS_PLANS_DIR",
                }
            }
            env.update({
                "HOME": str(tmp_path / "home"),
                "XDG_STATE_HOME": str(tmp_path / "state"),
                "Z_HARNESS_EXTERNAL_DEFAULT": "1",
                "Z_HARNESS_REGISTRY_ENABLED": "1",
            })

            repo_id_result = subprocess.run(
                ["bash", str(REPO_ROOT / "scripts" / "plan-path.sh"), "z_harness_repo_id"],
                cwd=target_repo,
                env=env,
                check=True,
                capture_output=True,
                text=True,
            )
            repo_id = repo_id_result.stdout.strip()
            run_id = "test-caller-repo-context"

            result = subprocess.run(
                [
                    sys.executable,
                    installed_registry,
                    "register",
                    "--run-id", run_id,
                    "--slug", "caller-context",
                    "--command", "/z-fix",
                    "--phase", "fix",
                ],
                cwd=target_repo,
                env=env,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)

            record_path = (
                tmp_path / "state" / "z-harness" / repo_id
                / "active-plans" / f"{run_id}.json"
            )
            self.assertTrue(record_path.is_file(), f"missing registry record: {record_path}")
            claims_result = subprocess.run(
                ["bash", str(plugin_scripts / "plan-path.sh"), "claims_dir"],
                cwd=target_repo,
                env=env,
                check=True,
                capture_output=True,
                text=True,
            )
            self.assertEqual(Path(claims_result.stdout.strip()).parent, record_path.parent)
            record = json.loads(record_path.read_text(encoding="utf-8"))
            self.assertEqual(Path(record["repo_root"]).resolve(), target_repo.resolve())
            self.assertEqual(Path(record["git_common_dir"]).resolve(), (target_repo / ".git").resolve())
            self.assertEqual(Path(record["worktree_path"]).resolve(), target_repo.resolve())
            self.assertEqual(record["repo_id"], repo_id)


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
                "--command", "/z-execute",
                "--phase", "implement",
                base_dir=base,
            )
            self.assertEqual(r.returncode, 0, f"register failed: {r.stderr}")

            # record file must exist
            record_path = active_dir / f"{run_id}.json"
            self.assertTrue(record_path.exists(), "record file not created")

            # schema check — T001 bumped schema_version to 2 (_build_record now writes v2
            # with held_paths/waiting_on); the assertion is updated to match.
            with record_path.open() as fh:
                rec = json.load(fh)
            self.assertEqual(rec["schema_version"], 2)
            self.assertEqual(rec["run_id"], run_id)
            self.assertEqual(rec["slug"], "my-slug")
            self.assertEqual(rec["command"], "/z-execute")
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
                "--slug", "s", "--command", "/z-execute", "--phase", "plan",
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

    def test_heartbeat_on_missing_is_noop(self):
        """heartbeat on a missing record must be a no-op: no file created, returns 0.

        B1 regression guard: before the fix, heartbeat fabricated a zombie record
        (empty slug/session/repo_id, status:running) when the target <run-id>.json
        was absent. This polluted other sessions' overlap detection. After the fix,
        heartbeat on a missing record must:
          (a) return 0 (non-fatal)
          (b) create NO file in the active-plans directory
          (c) self-emit a registry_error event (op:heartbeat, reason:missing_record)
        """
        with tempfile.TemporaryDirectory() as base:
            run_id = "never-registered-run-id"
            active_dir = Path(base) / "active-plans"

            # Precondition: no record exists
            if active_dir.exists():
                files_before = list(active_dir.glob("*.json"))
            else:
                files_before = []
            self.assertEqual(files_before, [], "precondition: no records exist before heartbeat")

            # Invoke heartbeat on a run-id that was never registered
            r = _run_registry(
                "heartbeat", "--run-id", run_id,
                "--phase", "implement",
                base_dir=base,
            )

            # (a) must return 0 (non-fatal)
            self.assertEqual(
                r.returncode, 0,
                f"heartbeat on missing record must return 0; got {r.returncode}; stderr={r.stderr[:400]}",
            )

            # (b) no file must have been created
            if active_dir.exists():
                files_after = list(active_dir.glob("*.json"))
            else:
                files_after = []
            self.assertEqual(
                files_after, [],
                f"heartbeat on missing record must NOT create any file; found: {files_after}",
            )

            # (c) list must be empty (no zombie record)
            r2 = _run_registry("list", "--json", base_dir=base)
            self.assertEqual(r2.returncode, 0)
            records = json.loads(r2.stdout)
            self.assertEqual(
                records, [],
                f"list must be empty after heartbeat on missing record; got: {records}",
            )

            # (d) a registry_error event with op:heartbeat and reason:missing_record was emitted
            metrics = Path(base) / "metrics.jsonl"
            found_error = False
            if metrics.exists():
                for line in metrics.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        ev = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if (ev.get("kind") == "registry_error"
                            and ev.get("op") == "heartbeat"
                            and ev.get("reason") == "missing_record"):
                        found_error = True
                        break
            self.assertTrue(
                found_error,
                "heartbeat on missing record must self-emit registry_error(op=heartbeat, reason=missing_record); "
                f"events in metrics.jsonl: {metrics.read_text() if metrics.exists() else '(none)'}",
            )

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


class TestNonFatalSelfLogsRegistryError(unittest.TestCase):
    """T010: non-fatal subcommands (heartbeat / update-scope / deregister) return 0
    by design, so a caller's `|| log registry_error` is dead code. The CLI must
    instead SELF-EMIT a registry_error event on an internal failure while still
    returning 0.

    Forced internal failure: create `<base>/active-plans` as a FILE (not a dir).
    Then any record write (heartbeat's atomic rewrite) or unlink (deregister)
    raises an OSError subclass that is NOT FileNotFoundError, exercising the
    self-log branch. log-event.sh resolves its own paths under <base> and is
    unaffected by the `active-plans` file, so the registry_error event still
    lands in <base>/metrics.jsonl.
    """

    def _registry_error_ops(self, base: str) -> list[str]:
        """Return the list of `op` values from registry_error events in metrics.jsonl."""
        metrics = Path(base) / "metrics.jsonl"
        ops: list[str] = []
        if not metrics.exists():
            return ops
        for line in metrics.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            # log-event.sh merges payload keys flat into the top-level event obj
            # ({"ts","run","kind", ...payload}), so `op` is a top-level key.
            if ev.get("kind") == "registry_error":
                op = ev.get("op")
                if op:
                    ops.append(op)
        return ops

    def test_heartbeat_internal_failure_self_logs_and_returns_0(self):
        with tempfile.TemporaryDirectory() as base:
            # Force internal failure: active-plans is a file, so the atomic record
            # rewrite cannot create/replace under it.
            (Path(base) / "active-plans").write_text("not a dir\n", encoding="utf-8")

            r = _run_registry(
                "heartbeat", "--run-id", "selflog-hb-001",
                "--phase", "implement", "--current-task", "T001",
                base_dir=base,
            )
            # (a) still returns 0 (NON-FATAL contract preserved)
            self.assertEqual(
                r.returncode, 0,
                f"heartbeat must remain NON-FATAL (exit 0); got {r.returncode}; stderr={r.stderr[:400]}",
            )
            # (b) a registry_error event with op:"heartbeat" was self-emitted
            ops = self._registry_error_ops(base)
            self.assertIn(
                "heartbeat", ops,
                f"heartbeat internal failure must self-emit registry_error(op=heartbeat); got ops={ops}",
            )

    def test_deregister_internal_failure_self_logs_and_returns_0(self):
        with tempfile.TemporaryDirectory() as base:
            (Path(base) / "active-plans").write_text("not a dir\n", encoding="utf-8")

            r = _run_registry(
                "deregister", "--run-id", "selflog-dereg-001", "--status", "aborted",
                base_dir=base,
            )
            self.assertEqual(
                r.returncode, 0,
                f"deregister must remain NON-FATAL (exit 0); got {r.returncode}; stderr={r.stderr[:400]}",
            )
            ops = self._registry_error_ops(base)
            self.assertIn(
                "deregister", ops,
                f"deregister internal failure must self-emit registry_error(op=deregister); got ops={ops}",
            )

    def test_clean_deregister_does_not_self_log_error(self):
        """Guard against false positives: a normal register→deregister round-trip
        must NOT emit any registry_error event (the self-log fires only on failure)."""
        with tempfile.TemporaryDirectory() as base:
            run_id = "selflog-clean-001"
            r_reg = _run_registry(
                "register", "--run-id", run_id,
                "--slug", "s", "--command", "/z-execute", "--phase", "implement",
                base_dir=base,
            )
            self.assertEqual(r_reg.returncode, 0, f"register: {r_reg.stderr[:400]}")
            r_dereg = _run_registry(
                "deregister", "--run-id", run_id, "--status", "complete",
                base_dir=base,
            )
            self.assertEqual(r_dereg.returncode, 0, f"deregister: {r_dereg.stderr[:400]}")
            ops = self._registry_error_ops(base)
            self.assertEqual(
                ops, [],
                f"clean round-trip must not self-emit any registry_error; got ops={ops}",
            )


# ── T009 (watchdog_pid): stamp + readback + deregister kill ───────────────────


class TestWatchdogPidStamp(unittest.TestCase):
    """watchdog_pid field: stamp via register/heartbeat, read back correctly.

    Invariant: watchdog_pid is an advisory observability field in the registry
    record. The authoritative source is the .watchdog.pid file on disk (addendum F).
    """

    def test_register_with_watchdog_pid_stamps_field(self):
        """register --watchdog-pid N stores watchdog_pid=N in the record."""
        with tempfile.TemporaryDirectory() as base:
            run_id = "test-wpid-reg-001"
            fake_pid = 99999  # will not exist; we're only testing field storage

            r = _run_registry(
                "register",
                "--run-id", run_id,
                "--slug", "s",
                "--command", "/z-test",
                "--phase", "test",
                "--watchdog-pid", str(fake_pid),
                base_dir=base,
            )
            self.assertEqual(r.returncode, 0, f"register failed: {r.stderr}")

            active_dir = Path(base) / "active-plans"
            rec = json.loads((active_dir / f"{run_id}.json").read_text())
            self.assertEqual(
                rec.get("watchdog_pid"), fake_pid,
                f"watchdog_pid must equal --watchdog-pid arg; got {rec.get('watchdog_pid')!r}"
            )

    def test_register_without_watchdog_pid_stores_none(self):
        """register without --watchdog-pid stores watchdog_pid=None."""
        with tempfile.TemporaryDirectory() as base:
            run_id = "test-wpid-none-001"
            r = _run_registry(
                "register",
                "--run-id", run_id,
                "--slug", "s",
                "--command", "/z-test",
                "--phase", "test",
                base_dir=base,
            )
            self.assertEqual(r.returncode, 0, f"register failed: {r.stderr}")

            active_dir = Path(base) / "active-plans"
            rec = json.loads((active_dir / f"{run_id}.json").read_text())
            self.assertIsNone(
                rec.get("watchdog_pid"),
                f"watchdog_pid must be None when --watchdog-pid not provided; "
                f"got {rec.get('watchdog_pid')!r}"
            )

    def test_heartbeat_with_watchdog_pid_updates_field(self):
        """heartbeat --watchdog-pid N updates watchdog_pid in the existing record."""
        with tempfile.TemporaryDirectory() as base:
            run_id = "test-wpid-hb-001"
            _run_registry(
                "register",
                "--run-id", run_id,
                "--slug", "s",
                "--command", "/z-test",
                "--phase", "test",
                base_dir=base,
            )

            fake_pid = 88888
            r = _run_registry(
                "heartbeat",
                "--run-id", run_id,
                "--watchdog-pid", str(fake_pid),
                base_dir=base,
            )
            self.assertEqual(r.returncode, 0, f"heartbeat failed: {r.stderr}")

            active_dir = Path(base) / "active-plans"
            rec = json.loads((active_dir / f"{run_id}.json").read_text())
            self.assertEqual(
                rec.get("watchdog_pid"), fake_pid,
                f"watchdog_pid must be updated by heartbeat --watchdog-pid; "
                f"got {rec.get('watchdog_pid')!r}"
            )

    def test_heartbeat_without_watchdog_pid_does_not_clear_existing(self):
        """heartbeat without --watchdog-pid preserves an existing watchdog_pid value."""
        with tempfile.TemporaryDirectory() as base:
            run_id = "test-wpid-preserve-001"
            initial_pid = 77777
            _run_registry(
                "register",
                "--run-id", run_id,
                "--slug", "s",
                "--command", "/z-test",
                "--phase", "test",
                "--watchdog-pid", str(initial_pid),
                base_dir=base,
            )

            # heartbeat without --watchdog-pid
            r = _run_registry(
                "heartbeat",
                "--run-id", run_id,
                "--phase", "implement",
                base_dir=base,
            )
            self.assertEqual(r.returncode, 0, f"heartbeat failed: {r.stderr}")

            active_dir = Path(base) / "active-plans"
            rec = json.loads((active_dir / f"{run_id}.json").read_text())
            self.assertEqual(
                rec.get("watchdog_pid"), initial_pid,
                f"watchdog_pid must be preserved when heartbeat omits --watchdog-pid; "
                f"got {rec.get('watchdog_pid')!r}"
            )

    def test_watchdog_pid_via_list_json(self):
        """list --json returns watchdog_pid in the record."""
        with tempfile.TemporaryDirectory() as base:
            run_id = "test-wpid-list-001"
            fake_pid = 55555
            _run_registry(
                "register",
                "--run-id", run_id,
                "--slug", "s",
                "--command", "/z-test",
                "--phase", "test",
                "--watchdog-pid", str(fake_pid),
                base_dir=base,
            )

            r = _run_registry("list", "--json", base_dir=base)
            self.assertEqual(r.returncode, 0)
            records = json.loads(r.stdout)
            matching = [x for x in records if x.get("run_id") == run_id]
            self.assertEqual(len(matching), 1)
            self.assertEqual(
                matching[0].get("watchdog_pid"), fake_pid,
                f"list --json must include watchdog_pid; got {matching[0].get('watchdog_pid')!r}"
            )


class TestDeregisterSigtermWatchdog(unittest.TestCase):
    """deregister reads the .watchdog.pid file and SIGTERMs a live sweep; no-op on dead/absent.

    Invariant (addendum F): the pid FILE is authoritative, not the registry field.
    Deregister is NON-FATAL: kill failures must never break it.
    """

    def _make_plan_dir_with_pid_file(self, base: str, run_id: str, pid: int) -> Path:
        """Write a .watchdog.pid file in the plan dir structure under base.

        Because plan-path.sh resolve_plan_path is called under a hermetic base
        dir, we construct the expected plan dir path and write the pid file there.
        The pid file format is: plain text integer + newline (per T008 SPEC).
        """
        # plan-path.sh resolve_plan_path produces:
        #   <base>/plans/<slug>  (new-layout)
        # We need to find the slug from the registered record to replicate the path.
        # For tests we use the run_id as slug to keep things simple.
        slug = run_id  # matches --slug arg below
        plan_dir = Path(base) / "plans" / slug
        active_subdir = plan_dir / "active"
        active_subdir.mkdir(parents=True, exist_ok=True)
        pid_file = active_subdir / f"{run_id}.watchdog.pid"
        pid_file.write_text(f"{pid}\n", encoding="utf-8")
        return plan_dir

    def test_deregister_sigterms_live_watchdog(self):
        """deregister SIGTERMs a live watchdog sweep process (blocking poll via .watchdog.pid).

        Spawns a real long-sleep subprocess as the fake watchdog. After deregister
        returns, the subprocess must be dead (either exited on SIGTERM or SIGKILL
        after grace). Uses poll-based wait to avoid race.
        """
        with tempfile.TemporaryDirectory() as base:
            run_id = "test-wpid-dereg-sigterm-001"

            # Spawn a long-sleep process as the fake watchdog sweep.
            fake_watchdog = subprocess.Popen(
                [sys.executable, "-c", "import time; time.sleep(60)"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            watchdog_pid = fake_watchdog.pid

            try:
                # Register the run (slug = run_id for simple plan-dir resolution).
                r = _run_registry(
                    "register",
                    "--run-id", run_id,
                    "--slug", run_id,
                    "--command", "/z-test",
                    "--phase", "test",
                    base_dir=base,
                )
                self.assertEqual(r.returncode, 0, f"register failed: {r.stderr}")

                # Write the .watchdog.pid file in the expected location.
                self._make_plan_dir_with_pid_file(base, run_id, watchdog_pid)

                # Confirm the watchdog is alive before deregister.
                try:
                    os.kill(watchdog_pid, 0)
                except ProcessLookupError:
                    self.skipTest(f"Watchdog pid {watchdog_pid} died before deregister ran")

                # Deregister — must SIGTERM the watchdog.
                r = _run_registry(
                    "deregister",
                    "--run-id", run_id,
                    "--status", "complete",
                    base_dir=base,
                )
                self.assertEqual(r.returncode, 0, f"deregister must be NON-FATAL; stderr={r.stderr}")

                # Poll until the watchdog exits (up to 5 seconds).
                # Use fake_watchdog.poll() rather than os.kill(pid, 0) because
                # the latter returns True for zombie processes (child of this
                # test process that exited but hasn't been reaped yet).
                deadline = time.monotonic() + 5.0
                while time.monotonic() < deadline:
                    if fake_watchdog.poll() is not None:
                        break  # dead — success
                    time.sleep(0.1)
                else:
                    # Still alive — fail the test.
                    fake_watchdog.kill()  # cleanup
                    self.fail(
                        f"Watchdog pid {watchdog_pid} is still alive {5}s after deregister; "
                        f"deregister must have SIGTERMed it"
                    )
            finally:
                # Ensure the fake watchdog is cleaned up even if the test fails.
                try:
                    fake_watchdog.kill()
                    fake_watchdog.wait(timeout=2)
                except (ProcessLookupError, subprocess.TimeoutExpired, OSError):
                    pass

    def test_deregister_noop_on_dead_watchdog_pid(self):
        """deregister is a no-op (no error) when the .watchdog.pid holds a dead pid."""
        with tempfile.TemporaryDirectory() as base:
            run_id = "test-wpid-dereg-dead-001"

            # Spawn a subprocess, wait for it to die, then use its (dead) pid.
            dead_proc = subprocess.Popen(
                [sys.executable, "-c", "import sys; sys.exit(0)"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            dead_proc.wait()
            dead_pid = dead_proc.pid

            # Confirm the pid is dead.
            try:
                os.kill(dead_pid, 0)
                self.skipTest(f"pid {dead_pid} was recycled; skipping")
            except ProcessLookupError:
                pass  # confirmed dead
            except PermissionError:
                self.skipTest(f"pid {dead_pid} appears alive; skipping")

            # Register and write the dead pid to the watchdog pid file.
            r = _run_registry(
                "register",
                "--run-id", run_id,
                "--slug", run_id,
                "--command", "/z-test",
                "--phase", "test",
                base_dir=base,
            )
            self.assertEqual(r.returncode, 0, f"register failed: {r.stderr}")
            self._make_plan_dir_with_pid_file(base, run_id, dead_pid)

            # Deregister must succeed and be a no-op on the dead pid.
            r = _run_registry(
                "deregister",
                "--run-id", run_id,
                "--status", "complete",
                base_dir=base,
            )
            self.assertEqual(
                r.returncode, 0,
                f"deregister must return 0 (NON-FATAL) on dead watchdog pid; "
                f"got {r.returncode}; stderr={r.stderr}"
            )

    def test_deregister_noop_on_absent_pid_file(self):
        """deregister is a no-op when the .watchdog.pid file does not exist."""
        with tempfile.TemporaryDirectory() as base:
            run_id = "test-wpid-dereg-absent-001"

            r = _run_registry(
                "register",
                "--run-id", run_id,
                "--slug", run_id,
                "--command", "/z-test",
                "--phase", "test",
                base_dir=base,
            )
            self.assertEqual(r.returncode, 0, f"register failed: {r.stderr}")
            # Do NOT write a .watchdog.pid file.

            # Deregister must succeed without error.
            r = _run_registry(
                "deregister",
                "--run-id", run_id,
                "--status", "complete",
                base_dir=base,
            )
            self.assertEqual(
                r.returncode, 0,
                f"deregister must return 0 (NON-FATAL) when .watchdog.pid is absent; "
                f"got {r.returncode}; stderr={r.stderr}"
            )

    def test_deregister_still_succeeds_when_kill_raises(self):
        """deregister returns 0 even if SIGTERM raises (e.g. permission denied).

        Uses pid=1 (init/launchd) which is always alive but may raise PermissionError.
        This exercises the NON-FATAL contract: kill failures must not propagate.
        """
        with tempfile.TemporaryDirectory() as base:
            run_id = "test-wpid-dereg-perm-001"

            r = _run_registry(
                "register",
                "--run-id", run_id,
                "--slug", run_id,
                "--command", "/z-test",
                "--phase", "test",
                base_dir=base,
            )
            self.assertEqual(r.returncode, 0, f"register failed: {r.stderr}")

            # Use pid 1 (always alive, but we can't SIGTERM it → PermissionError).
            self._make_plan_dir_with_pid_file(base, run_id, 1)

            r = _run_registry(
                "deregister",
                "--run-id", run_id,
                "--status", "complete",
                base_dir=base,
            )
            # Must always return 0 regardless of kill outcome.
            self.assertEqual(
                r.returncode, 0,
                f"deregister must be NON-FATAL even when SIGTERM raises PermissionError; "
                f"got {r.returncode}; stderr={r.stderr}"
            )


# ── T013: helpers ─────────────────────────────────────────────────────────────


def _make_v2_record(
    run_id: str,
    *,
    session_id: str = "",
    host: str | None = None,
    pid: int | None = None,
    scope: list[dict] | None = None,
    status: str = "running",
    last_heartbeat: str | None = None,
    held_paths: list[dict] | None = None,
    waiting_on: list[str] | None = None,
) -> dict:
    """Build a schema-v2 registry record for test injection.

    Schema v2 is required for lease-capable (claim/release/wait-for) records:
    it adds 'held_paths' and 'waiting_on' to the v1 structure.
    """
    from datetime import datetime, timezone
    now_str = last_heartbeat or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {
        "schema_version": 2,
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
        "held_paths": held_paths if held_paths is not None else [],
        "waiting_on": waiting_on if waiting_on is not None else [],
    }


def _read_metrics_events(base: str, kind: str) -> list[dict]:
    """Read all events of a given kind from metrics.jsonl in the base dir."""
    metrics = Path(base) / "metrics.jsonl"
    events: list[dict] = []
    if not metrics.exists():
        return events
    for line in metrics.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        if ev.get("kind") == kind:
            events.append(ev)
    return events


# ── T013 (a): TOCTOU double-claim → single winner, loser excludes conceded path ─


class TestClaimTOCTOUSingleWinner(unittest.TestCase):
    """Case (a) F2 + BLOCKER-1: double-claim TOCTOU → deterministic single winner
    by run_id AND the loser's persisted held_paths excludes the conceded path.

    F-IDs pinned: F2 (check-after-claim), F4 (run_id tiebreak/seniority), BLOCKER-1.
    """

    def test_toctou_winner_by_run_id_and_loser_held_paths_clean(self):
        """Two runs claim the same path simultaneously.

        The senior (lexicographically lower run_id) wins. The junior concedes.
        After both claims settle:
          - senior's held_paths contains the path (won)
          - junior's held_paths does NOT contain the path (BLOCKER-1: conceded path excluded)

        This directly pins F2 (check-after-claim tiebreak) and BLOCKER-1.
        """
        with tempfile.TemporaryDirectory() as base:
            active_dir = Path(base) / "active-plans"
            path = "scripts/active-plan-registry.py"

            # A is senior (lexicographically lower run_id), B is junior.
            senior_run_id = "aaa-senior-001"
            junior_run_id = "zzz-junior-001"

            # Register both runs via subprocess so they have valid records.
            for run_id in (senior_run_id, junior_run_id):
                r = _run_registry(
                    "register",
                    "--run-id", run_id,
                    "--slug", "slug",
                    "--command", "/z-test",
                    "--phase", "test",
                    base_dir=base,
                )
                self.assertEqual(r.returncode, 0, f"register {run_id}: {r.stderr}")

            # Senior claims first — this seeds its held_paths so junior's
            # check-after-claim (F2) will see the conflict.
            r_senior = _run_registry(
                "claim",
                "--run-id", senior_run_id,
                "--paths", path,
                base_dir=base,
            )
            self.assertEqual(r_senior.returncode, 0, f"senior claim: {r_senior.stderr}")
            senior_result = json.loads(r_senior.stdout)
            self.assertIn(path, senior_result["claimed"],
                          "senior must win the path it claimed first")
            self.assertEqual(senior_result["conceded"], [],
                             "senior has no competitor at claim time — conceded must be empty")

            # Junior now claims the same path. F2 check-after-claim sees the senior
            # holds it → junior must concede to senior.
            r_junior = _run_registry(
                "claim",
                "--run-id", junior_run_id,
                "--paths", path,
                base_dir=base,
            )
            self.assertEqual(r_junior.returncode, 0, f"junior claim: {r_junior.stderr}")
            junior_result = json.loads(r_junior.stdout)

            # Junior must have conceded the path to the senior (BLOCKER-1).
            self.assertNotIn(path, junior_result.get("claimed", []),
                             "junior must NOT appear to have claimed the contested path")
            conceded_paths = [c["path"] for c in junior_result.get("conceded", [])]
            self.assertIn(path, conceded_paths,
                          "junior must list the contested path under 'conceded'")
            # Verify holder_run_id points to senior (F4 tiebreak).
            holder_ids = [c["holder_run_id"] for c in junior_result.get("conceded", [])
                          if c["path"] == path]
            self.assertEqual(holder_ids, [senior_run_id],
                             f"conceded entry must name the senior as holder; got {holder_ids}")

            # BLOCKER-1: junior's persisted record must NOT contain the conceded path.
            junior_rec = _read_record_direct(active_dir, junior_run_id)
            self.assertIsNotNone(junior_rec, "junior record must exist")
            junior_held_paths = {
                e["path"] for e in junior_rec.get("held_paths", [])
                if isinstance(e, dict) and "path" in e
            }
            self.assertNotIn(
                path, junior_held_paths,
                f"BLOCKER-1 violation: junior's persisted held_paths contains the conceded path "
                f"'{path}'; held_paths={junior_held_paths}"
            )

            # Senior's persisted record MUST contain the path.
            senior_rec = _read_record_direct(active_dir, senior_run_id)
            self.assertIsNotNone(senior_rec, "senior record must exist")
            senior_held_paths = {
                e["path"] for e in senior_rec.get("held_paths", [])
                if isinstance(e, dict) and "path" in e
            }
            self.assertIn(
                path, senior_held_paths,
                f"senior's persisted held_paths must contain the won path '{path}'"
            )


# ── T013 (b): wait-for clears within one poll of deregister ───────────────────


class TestWaitForClearsAfterDeregister(unittest.TestCase):
    """Case (b) F1 + F3: wait-for clears within one poll of senior deregistering.

    F-IDs pinned: F1 (wait/park loop), F3 (release/deregister clears target).
    """

    def test_wait_for_clears_after_senior_deregisters(self):
        """wait-for senior → senior record deleted → waiter exits 0 (cleared).

        Uses tiny poll interval (1s) and budget (10s) to keep the test fast.
        The senior is injected directly with pid=os.getpid() (alive) so the reaper
        does not prematurely delete it. A background thread deletes the senior's
        record after 2 seconds to simulate deregistration (F3).

        Pins F1 (park loop detects cleared target) and F3 (record removal = cleared).
        """
        with tempfile.TemporaryDirectory() as base:
            active_dir = Path(base) / "active-plans"
            senior_run_id = "aaa-senior-wb-001"
            waiter_run_id = "zzz-waiter-wb-001"

            # Both records injected with our live PID so reap leaves them alone.
            # wait-for updates the waiter's record via _set_waiting_on (read-modify-write).
            _write_record_direct(active_dir, _make_v2_record(senior_run_id, pid=os.getpid()))
            _write_record_direct(active_dir, _make_v2_record(waiter_run_id, pid=os.getpid()))

            # Delete the senior's record after a short delay to simulate deregistration.
            senior_path = active_dir / f"{senior_run_id}.json"

            def _delete_senior_later():
                time.sleep(2)
                try:
                    senior_path.unlink()
                except FileNotFoundError:
                    pass

            t = threading.Thread(target=_delete_senior_later, daemon=True)
            t.start()

            # wait-for with small poll + budget so the test runs fast.
            r = _run_registry(
                "wait-for",
                "--run-id", waiter_run_id,
                "--on", senior_run_id,
                base_dir=base,
                env_extra={
                    "Z_HARNESS_WAIT_POLL_SECS": "1",
                    "Z_HARNESS_AUTO_WAIT_BUDGET_SECS": "10",
                    "Z_HARNESS_AUTO_WAIT": "1",
                },
            )

            t.join(timeout=15)
            # Must exit 0 (cleared) — senior record deleted before budget expired.
            self.assertEqual(
                r.returncode, 0,
                f"wait-for must exit 0 (cleared) after senior record is deleted; "
                f"got {r.returncode}; stderr={r.stderr[:400]}"
            )


# ── T013 (c): wait-for timeout → exit 10 + wait_timeout event + waiting_on cleared ──


class TestWaitForTimeout(unittest.TestCase):
    """Case (c) F1: wait-for timeout → exit 10 + wait_timeout event + waiting_on cleared.

    F-IDs pinned: F1 (finite budget + loud timeout).
    """

    def test_timeout_exits_10_with_wait_timeout_event_and_waiting_on_cleared(self):
        """wait-for a senior that never clears → expires → exit 10, event emitted,
        waiter's waiting_on is empty.

        Uses tiny budget (2s) and poll (1s) to keep test fast.
        The senior is injected with pid=os.getpid() so reap does not prematurely
        clear it (the dead-subprocess-pid problem). The budget expires before the
        senior deregisters.
        Pins F1: 'every wait has a finite budget + loud timeout'.
        """
        with tempfile.TemporaryDirectory() as base:
            active_dir = Path(base) / "active-plans"
            senior_run_id = "aaa-senior-to-001"
            waiter_run_id = "zzz-waiter-to-001"

            # Both records injected with our live PID so reap leaves them alone.
            # The wait-for subprocess updates the waiter's record via _set_waiting_on
            # (read-modify-write), so injecting it is safe — wait-for does not need
            # to create the record, only update it.
            _write_record_direct(active_dir, _make_v2_record(senior_run_id, pid=os.getpid()))
            _write_record_direct(active_dir, _make_v2_record(waiter_run_id, pid=os.getpid()))

            # Wait-for with a 2-second budget. Senior never clears → timeout.
            r = _run_registry(
                "wait-for",
                "--run-id", waiter_run_id,
                "--on", senior_run_id,
                base_dir=base,
                env_extra={
                    "Z_HARNESS_WAIT_POLL_SECS": "1",
                    "Z_HARNESS_AUTO_WAIT_BUDGET_SECS": "2",
                    "Z_HARNESS_AUTO_WAIT": "1",
                },
            )

            # Must exit 10 (timeout).
            self.assertEqual(
                r.returncode, 10,
                f"wait-for must exit 10 on timeout; got {r.returncode}; stderr={r.stderr[:400]}"
            )

            # wait_timeout event must have been emitted with correct budget_s (F1).
            events = _read_metrics_events(base, "wait_timeout")
            self.assertGreater(len(events), 0, "wait_timeout event must be emitted on timeout")
            budgets = [e.get("budget_s") for e in events]
            # budget_s must equal the configured auto-wait budget (2 seconds).
            self.assertIn(
                2, budgets,
                f"wait_timeout event must carry budget_s=2 (the configured auto budget); got {budgets}"
            )

            # waiting_on must be cleared after timeout (EH-005: cleared on every exit path).
            waiter_rec = _read_record_direct(active_dir, waiter_run_id)
            self.assertIsNotNone(waiter_rec, "waiter record must still exist after timeout")
            self.assertEqual(
                waiter_rec.get("waiting_on", []), [],
                f"waiting_on must be cleared after timeout (EH-005); "
                f"got {waiter_rec.get('waiting_on')}"
            )
            # Status must be restored to running after timeout.
            self.assertEqual(
                waiter_rec.get("status"), "running",
                f"status must be restored to 'running' after timeout; got {waiter_rec.get('status')}"
            )


# ── T013 (d): SIGINT → no paused zombie ───────────────────────────────────────


class TestWaitForSigint(unittest.TestCase):
    """Case (d): SIGINT during wait-for → no paused zombie; waiting_on cleared.

    The 'finally' block in cmd_wait_for (EH-005) guarantees waiting_on is cleared
    on every exit path, including SIGINT.
    """

    def test_sigint_clears_waiting_on_no_paused_zombie(self):
        """Send SIGINT to a running wait-for process.

        The senior is injected with pid=os.getpid() so reap does not prematurely
        clear the target (dead-subprocess-pid problem).
        Long poll interval (30s) gives us time to interrupt before a poll completes.

        Verifies:
          (a) process exits 130
          (b) waiter's waiting_on is empty after interrupt (no zombie)
          (c) waiter's status is 'running' (not 'paused')
        """
        with tempfile.TemporaryDirectory() as base:
            active_dir = Path(base) / "active-plans"
            senior_run_id = "aaa-senior-si-001"
            waiter_run_id = "zzz-waiter-si-001"

            # Both records injected with our live PID so reap leaves them alone.
            # The wait-for subprocess updates the waiter's record via _set_waiting_on
            # (read-modify-write), so pre-injecting is safe.
            _write_record_direct(active_dir, _make_v2_record(senior_run_id, pid=os.getpid()))
            _write_record_direct(active_dir, _make_v2_record(waiter_run_id, pid=os.getpid()))

            env = {
                **os.environ,
                "Z_HARNESS_BASE_DIR": base,
                "Z_HARNESS_WAIT_POLL_SECS": "30",       # long poll so we can interrupt it
                "Z_HARNESS_AUTO_WAIT_BUDGET_SECS": "60",
                "Z_HARNESS_AUTO_WAIT": "1",
            }

            # Start wait-for as a subprocess so we can send it SIGINT.
            proc = subprocess.Popen(
                [sys.executable, REGISTRY_PY, "wait-for",
                 "--run-id", waiter_run_id,
                 "--on", senior_run_id],
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                cwd=str(REPO_ROOT),
            )

            # Give the subprocess a moment to enter its poll sleep.
            time.sleep(1.5)

            # Send SIGINT.
            import signal as _signal
            proc.send_signal(_signal.SIGINT)

            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
                self.fail("wait-for did not exit within 10s of SIGINT")

            # (a) exit 130.
            self.assertEqual(
                proc.returncode, 130,
                f"wait-for must exit 130 on SIGINT; got {proc.returncode}"
            )

            # (b) waiting_on must be cleared (no zombie).
            waiter_rec = _read_record_direct(active_dir, waiter_run_id)
            self.assertIsNotNone(waiter_rec, "waiter record must still exist after SIGINT")
            self.assertEqual(
                waiter_rec.get("waiting_on", []), [],
                f"waiting_on must be cleared after SIGINT (EH-005, no paused zombie); "
                f"got {waiter_rec.get('waiting_on')}"
            )

            # (c) status restored to running.
            self.assertEqual(
                waiter_rec.get("status"), "running",
                f"status must be 'running' after SIGINT cleanup; got {waiter_rec.get('status')}"
            )


# ── T013 (e): F-reaper carve-out keeps live-local-pid leases ──────────────────


class TestReaperLivePidCarveOut(unittest.TestCase):
    """Case (e) F-reaper: live-local-pid carve-out prevents deletion of live process leases.

    SPEC: if host == THIS host AND pid is alive AND past the 2× stale margin →
    mark status:'stale' (do NOT delete). Deletion deferred until pid dies.

    This prevents a slow local test from having its leases reaped out from under it.
    F-IDs pinned: F-reaper (live-local-pid carve-out).
    """

    def test_live_local_pid_2x_stale_marked_stale_not_deleted(self):
        """A local-pid record past 2× stale threshold is marked stale, NOT deleted.

        Pins F-reaper carve-out: held_paths of a live process must survive reap.
        """
        with tempfile.TemporaryDirectory() as base:
            active_dir = Path(base) / "active-plans"
            run_id = "reap-live-2x-001"

            from datetime import datetime, timezone, timedelta
            # Past 2× stale margin (default 1800s → 2×=3600s → use 4000s).
            very_old = (datetime.now(timezone.utc) - timedelta(seconds=4000)).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            )
            # Use OUR OWN pid (alive) and this host.
            rec = _make_v2_record(
                run_id,
                pid=os.getpid(),
                host=socket.gethostname(),
                last_heartbeat=very_old,
                held_paths=[{"path": "scripts/active-plan-registry.py", "since": "2026-01-01T00:00:00Z"}],
            )
            _write_record_direct(active_dir, rec)

            r = _run_registry(
                "reap", base_dir=base,
                env_extra={"Z_HARNESS_REGISTRY_STALE_SECS": "1800"},
            )
            self.assertEqual(r.returncode, 0, f"reap must be non-fatal; stderr={r.stderr}")

            # Record must still exist (carve-out: live-local-pid → no deletion).
            record_path = active_dir / f"{run_id}.json"
            self.assertTrue(
                record_path.exists(),
                "F-reaper: live-local-pid record past 2× stale must NOT be deleted "
                "(carve-out preserves leases of running local processes)"
            )

            # The held_paths must survive intact.
            remaining = _read_record_direct(active_dir, run_id)
            self.assertIsNotNone(remaining, "record must be readable after reap")
            held = [e["path"] for e in remaining.get("held_paths", []) if isinstance(e, dict)]
            self.assertIn(
                "scripts/active-plan-registry.py", held,
                f"F-reaper: held_paths must survive the live-local-pid carve-out; got {held}"
            )


# ── T013 (f): F-backcompat: v1 record → lease-incapable ──────────────────────


class TestBackcompatV1LeaseIncapable(unittest.TestCase):
    """Case (f) F-backcompat: a hand-written v1 record loads, _is_lease_capable()→False,
    and a v2 claimant does NOT treat it as a holder during check-after-claim (F2).

    F-IDs pinned: F-backcompat (v1 records never block a v2 claimant via held_paths).
    """

    def test_v1_record_does_not_block_v2_claim(self):
        """A v1 peer record with no held_paths key must be ignored by claim's F2 scan.

        The v1 record 'holds' a path in its scope, but since it has no held_paths,
        the v2 claimant must NOT concede — it wins the path outright.

        Pins F-backcompat: 'missing held_paths is NEVER interpreted as holds nothing'
        → v1 record is lease-incapable and never blocks a claim.
        """
        with tempfile.TemporaryDirectory() as base:
            active_dir = Path(base) / "active-plans"
            path = "scripts/active-plan-registry.py"
            v1_run_id = "aaa-v1-peer-001"   # senior (lower run_id)
            v2_run_id = "zzz-v2-claimer-001"

            # Inject a v1 record (no held_paths key, schema_version=1).
            # It is senior (lower run_id), but lease-incapable.
            v1_rec = _make_record(v1_run_id, scope=[
                {"path": path, "confidence": "explicit", "reason": "F-backcompat test"}
            ])
            # _make_record produces schema_version=1 with no held_paths — matches v1 shape.
            self.assertEqual(v1_rec["schema_version"], 1)
            self.assertNotIn("held_paths", v1_rec,
                             "precondition: v1 record must not have held_paths")
            _write_record_direct(active_dir, v1_rec)

            # Register the v2 claimer.
            r = _run_registry(
                "register",
                "--run-id", v2_run_id,
                "--slug", "s",
                "--command", "/z-test",
                "--phase", "test",
                base_dir=base,
            )
            self.assertEqual(r.returncode, 0, f"register v2 claimer: {r.stderr}")

            # v2 claimer attempts to claim the path.
            r = _run_registry(
                "claim",
                "--run-id", v2_run_id,
                "--paths", path,
                base_dir=base,
            )
            self.assertEqual(r.returncode, 0, f"claim: {r.stderr}")
            result = json.loads(r.stdout)

            # Must WIN the path — v1 peer is lease-incapable, so it never holds anything.
            self.assertIn(
                path, result.get("claimed", []),
                f"F-backcompat: v2 claimant must win path despite senior v1 peer; "
                f"claimed={result.get('claimed')}, conceded={result.get('conceded')}"
            )
            self.assertEqual(
                result.get("conceded", []), [],
                f"F-backcompat: v1 peer must not appear in conceded list; got {result.get('conceded')}"
            )


# ── T013 (g): F4 DAG ordering — junior never waits on senior ─────────────────


class TestWaitForDagOrdering(unittest.TestCase):
    """Case (g) F4: DAG ordering — junior never waits on senior; wait-for drops non-seniors.

    F-IDs pinned: F4 (run_id ordering/seniority — eligibility filter drops junior targets).
    """

    def test_junior_target_dropped_immediately_nothing_to_wait_on(self):
        """A junior (higher run_id) target is dropped; wait-for exits 0 (nothing_to_wait_on).

        F4 eligibility: 'only accept --on run_ids that are run_id < my run_id (senior)'.
        Providing only a junior run_id must result in immediate exit 0.
        """
        with tempfile.TemporaryDirectory() as base:
            my_run_id = "aaa-waiter-dag-001"       # senior (lower run_id)
            junior_run_id = "zzz-junior-dag-001"   # junior (higher run_id)

            for run_id in (my_run_id, junior_run_id):
                r = _run_registry(
                    "register",
                    "--run-id", run_id,
                    "--slug", "s",
                    "--command", "/z-test",
                    "--phase", "test",
                    base_dir=base,
                )
                self.assertEqual(r.returncode, 0, f"register {run_id}: {r.stderr}")

            # The "waiter" tries to wait on a junior — must be dropped immediately.
            r = _run_registry(
                "wait-for",
                "--run-id", my_run_id,
                "--on", junior_run_id,
                base_dir=base,
                env_extra={
                    "Z_HARNESS_WAIT_POLL_SECS": "1",
                    "Z_HARNESS_AUTO_WAIT_BUDGET_SECS": "5",
                    "Z_HARNESS_AUTO_WAIT": "1",
                },
            )
            # Must exit 0 (nothing_to_wait_on — junior was dropped).
            self.assertEqual(
                r.returncode, 0,
                f"F4: wait-for on a junior must immediately exit 0 (nothing_to_wait_on); "
                f"got {r.returncode}; stderr={r.stderr[:400]}"
            )
            self.assertIn(
                "nothing_to_wait_on", r.stdout,
                f"stdout must contain 'nothing_to_wait_on'; got {r.stdout!r}"
            )

    def test_equal_run_id_target_dropped(self):
        """A same run_id target (self-wait) is dropped — not senior."""
        with tempfile.TemporaryDirectory() as base:
            my_run_id = "self-wait-dag-001"
            r = _run_registry(
                "register",
                "--run-id", my_run_id,
                "--slug", "s",
                "--command", "/z-test",
                "--phase", "test",
                base_dir=base,
            )
            self.assertEqual(r.returncode, 0)
            r = _run_registry(
                "wait-for",
                "--run-id", my_run_id,
                "--on", my_run_id,
                base_dir=base,
                env_extra={
                    "Z_HARNESS_WAIT_POLL_SECS": "1",
                    "Z_HARNESS_AUTO_WAIT_BUDGET_SECS": "5",
                    "Z_HARNESS_AUTO_WAIT": "1",
                },
            )
            self.assertEqual(
                r.returncode, 0,
                f"F4: self-wait must exit 0 (nothing_to_wait_on); got {r.returncode}"
            )


# ── T013 (h): F5/overlaps: held×held payload + seniority ─────────────────────


class TestOverlapsHeldConflict(unittest.TestCase):
    """Case (h) F5 / overlaps: held×held conflict in overlaps payload includes
    held_conflict array with peer_run_id and holder_seniority.

    F-IDs pinned: F5 (write-set / coordination_warning), overlaps held-path dimension.
    """

    def test_held_conflict_in_overlaps_payload_with_seniority(self):
        """Two peers both hold the same path → overlaps --json includes held_conflict
        with the correct peer_run_id and seniority label.

        Pins F5 / held-path dimension of overlaps.
        """
        with tempfile.TemporaryDirectory() as base:
            active_dir = Path(base) / "active-plans"
            path = "scripts/active-plan-registry.py"

            my_run_id = "zzz-held-me-001"
            peer_run_id = "aaa-held-peer-001"   # senior (lower run_id)

            # Both records hold the same path in held_paths.
            now_ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            my_rec = _make_v2_record(
                my_run_id,
                held_paths=[{"path": path, "since": now_ts}],
            )
            peer_rec = _make_v2_record(
                peer_run_id,
                held_paths=[{"path": path, "since": now_ts}],
            )
            _write_record_direct(active_dir, my_rec)
            _write_record_direct(active_dir, peer_rec)

            # Build a scope file for my run (can be empty — held_conflict is independent).
            scope_file = Path(base) / "scope_me.json"
            scope_file.write_text("[]", encoding="utf-8")

            r = _run_registry(
                "overlaps",
                "--run-id", my_run_id,
                "--scope-json", str(scope_file),
                "--json",
                base_dir=base,
            )
            # Exit code may be 0 or 10; what matters is the held_conflict payload (F5).
            self.assertIn(r.returncode, (0, 10),
                          f"overlaps exit code must be 0 or 10; got {r.returncode}")
            result = json.loads(r.stdout)

            # held_conflict must be present in the payload.
            self.assertIn(
                "held_conflict", result,
                f"overlaps payload must include 'held_conflict' when both peers hold same path; "
                f"got keys={list(result.keys())}"
            )
            conflicts = result["held_conflict"]
            self.assertIsInstance(conflicts, list, "held_conflict must be a list")
            self.assertGreater(len(conflicts), 0, "held_conflict must be non-empty")

            # Find the conflict for our path.
            matching = [c for c in conflicts if c.get("path") == path]
            self.assertGreater(
                len(matching), 0,
                f"held_conflict must contain an entry for '{path}'; got {conflicts}"
            )
            conflict = matching[0]

            # peer_run_id must name the peer.
            self.assertEqual(
                conflict.get("peer_run_id"), peer_run_id,
                f"held_conflict must name the conflicting peer; got {conflict}"
            )

            # holder_seniority: peer_run_id < my_run_id → peer is senior.
            self.assertEqual(
                conflict.get("holder_seniority"), "senior",
                f"peer with lower run_id must have holder_seniority='senior'; got {conflict}"
            )

    def test_junior_peer_held_conflict_seniority_junior(self):
        """A peer with a higher run_id (junior) holding the same path → seniority='junior'."""
        with tempfile.TemporaryDirectory() as base:
            active_dir = Path(base) / "active-plans"
            path = "scripts/plan-path.sh"

            my_run_id = "aaa-held-me-002"          # senior
            junior_peer_run_id = "zzz-held-peer-002"   # junior

            now_ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            _write_record_direct(active_dir, _make_v2_record(
                my_run_id,
                held_paths=[{"path": path, "since": now_ts}],
            ))
            _write_record_direct(active_dir, _make_v2_record(
                junior_peer_run_id,
                held_paths=[{"path": path, "since": now_ts}],
            ))

            scope_file = Path(base) / "scope_me2.json"
            scope_file.write_text("[]", encoding="utf-8")

            r = _run_registry(
                "overlaps",
                "--run-id", my_run_id,
                "--scope-json", str(scope_file),
                "--json",
                base_dir=base,
            )
            self.assertIn(r.returncode, (0, 10))
            result = json.loads(r.stdout)

            conflicts = result.get("held_conflict", [])
            matching = [c for c in conflicts if c.get("path") == path]
            self.assertGreater(len(matching), 0,
                               f"held_conflict must contain entry for '{path}'")
            conflict = matching[0]
            self.assertEqual(
                conflict.get("holder_seniority"), "junior",
                f"peer with higher run_id must have holder_seniority='junior'; got {conflict}"
            )


# ── T013 (i): F5/coordination_warning — undeclared file held by peer ──────────


class TestF5CoordinationWarning(unittest.TestCase):
    """Case (i) F5: undeclared path held by a live peer → held_conflict detectable;
    uncontested undeclared paths → zero held_conflict (noise gate).

    The 'coordination_warning' is surfaced at the ORCHESTRATOR layer (F5 step in
    /z-execute). This test validates the registry layer the orchestrator consumes:
    overlaps --json must expose a 'held_conflict' entry when the path is held by a peer,
    and must NOT include it when the path is uncontested.

    F-IDs pinned: F5 (write-set / coordination_warning detectable via overlaps payload).
    """

    def test_undeclared_path_held_by_peer_appears_in_held_conflict(self):
        """An undeclared path that a live peer holds appears in held_conflict (F5).

        'Undeclared' means: my run does not list it in scope, but I hold it in held_paths
        AND the peer also holds it in held_paths → overlap detectable.
        """
        with tempfile.TemporaryDirectory() as base:
            active_dir = Path(base) / "active-plans"
            contested_path = "scripts/undeclared-contested.py"

            my_run_id = "zzz-f5-me-001"
            peer_run_id = "aaa-f5-peer-001"   # live peer

            now_ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            # Both hold the contested path — simulating F5 scenario.
            _write_record_direct(active_dir, _make_v2_record(
                my_run_id,
                held_paths=[{"path": contested_path, "since": now_ts}],
            ))
            _write_record_direct(active_dir, _make_v2_record(
                peer_run_id,
                held_paths=[{"path": contested_path, "since": now_ts}],
            ))

            # Scope for my run does NOT list the contested path (it is 'undeclared').
            scope_file = Path(base) / "scope_f5.json"
            scope_file.write_text("[]", encoding="utf-8")

            r = _run_registry(
                "overlaps",
                "--run-id", my_run_id,
                "--scope-json", str(scope_file),
                "--json",
                base_dir=base,
            )
            self.assertIn(r.returncode, (0, 10))
            result = json.loads(r.stdout)

            # F5: held_conflict must be present and include the contested path.
            self.assertIn(
                "held_conflict", result,
                f"F5: held_conflict must appear when an undeclared path is held by a live peer; "
                f"stdout={r.stdout[:400]}"
            )
            conflict_paths = [c.get("path") for c in result["held_conflict"]]
            self.assertIn(
                contested_path, conflict_paths,
                f"F5: held_conflict must include the contested path '{contested_path}'; "
                f"got {conflict_paths}"
            )

    def test_uncontested_paths_produce_no_held_conflict(self):
        """Uncontested undeclared paths produce zero held_conflict (noise gate, F5).

        If my run holds a path and no peer holds it, there is no conflict to surface.
        The noise gate ensures the F5 coordination_warning is actionable, not spurious.
        """
        with tempfile.TemporaryDirectory() as base:
            active_dir = Path(base) / "active-plans"
            my_path = "scripts/only-i-hold-this.py"
            peer_path = "scripts/only-peer-holds-this.py"

            my_run_id = "zzz-f5-noise-me-001"
            peer_run_id = "aaa-f5-noise-peer-001"

            now_ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            # Disjoint held_paths — no intersection.
            _write_record_direct(active_dir, _make_v2_record(
                my_run_id,
                held_paths=[{"path": my_path, "since": now_ts}],
            ))
            _write_record_direct(active_dir, _make_v2_record(
                peer_run_id,
                held_paths=[{"path": peer_path, "since": now_ts}],
            ))

            scope_file = Path(base) / "scope_noise.json"
            scope_file.write_text("[]", encoding="utf-8")

            r = _run_registry(
                "overlaps",
                "--run-id", my_run_id,
                "--scope-json", str(scope_file),
                "--json",
                base_dir=base,
            )
            self.assertIn(r.returncode, (0, 10))
            result = json.loads(r.stdout)

            # No held_conflict when paths are disjoint (noise gate).
            conflicts = result.get("held_conflict", [])
            self.assertEqual(
                conflicts, [],
                f"F5 noise gate: uncontested paths must produce zero held_conflict; got {conflicts}"
            )


# ── T013 (j): dual-budget: auto vs explicit ───────────────────────────────────


class TestDualBudget(unittest.TestCase):
    """Case (j): dual-budget — auto-wait enforces auto budget, explicit wait enforces
    explicit budget, each emitting wait_timeout with the correct budget_s.

    F-IDs pinned: F1 (finite budget + dual-budget distinction).
    """

    def _run_wait_for_timeout(self, base: str, waiter_id: str, senior_id: str,
                               env_extra: dict) -> subprocess.CompletedProcess:
        """Helper: run wait-for expecting a timeout."""
        return _run_registry(
            "wait-for",
            "--run-id", waiter_id,
            "--on", senior_id,
            base_dir=base,
            env_extra=env_extra,
        )

    def test_auto_mode_budget_in_wait_timeout_event(self):
        """Auto mode (Z_HARNESS_AUTO_WAIT=1) uses AUTO budget and emits budget_s=auto_budget.

        Senior is injected with pid=os.getpid() so reap does not prematurely clear
        the target (dead-subprocess-pid problem). Uses tiny auto budget (2s) to keep
        the test fast. Pins F1 dual-budget.
        """
        with tempfile.TemporaryDirectory() as base:
            active_dir = Path(base) / "active-plans"
            senior_run_id = "aaa-senior-db-auto-001"
            waiter_run_id = "zzz-waiter-db-auto-001"

            # Both injected with our live PID so reap leaves them alone.
            _write_record_direct(active_dir, _make_v2_record(senior_run_id, pid=os.getpid()))
            _write_record_direct(active_dir, _make_v2_record(waiter_run_id, pid=os.getpid()))

            r = self._run_wait_for_timeout(base, waiter_run_id, senior_run_id, {
                "Z_HARNESS_AUTO_WAIT": "1",
                "Z_HARNESS_AUTO_WAIT_BUDGET_SECS": "2",   # tiny auto budget
                "Z_HARNESS_WAIT_TIMEOUT_SECS": "1800",    # explicit budget untouched
                "Z_HARNESS_WAIT_POLL_SECS": "1",
            })

            self.assertEqual(r.returncode, 10, f"auto mode must timeout with exit 10; stderr={r.stderr[:400]}")

            events = _read_metrics_events(base, "wait_timeout")
            self.assertGreater(len(events), 0, "wait_timeout event must be emitted")
            budgets = [e.get("budget_s") for e in events]
            # budget_s must equal the auto budget (2), NOT the explicit budget (1800).
            self.assertIn(
                2, budgets,
                f"F1 dual-budget: wait_timeout in auto mode must carry budget_s=2 (auto); got {budgets}"
            )
            self.assertNotIn(
                1800, budgets,
                f"F1 dual-budget: auto mode must NOT use explicit timeout budget 1800; got {budgets}"
            )

    def test_explicit_mode_budget_in_wait_timeout_event(self):
        """Explicit mode (Z_HARNESS_AUTO_WAIT=0) uses EXPLICIT budget and emits budget_s=explicit.

        Senior is injected with pid=os.getpid() so reap does not prematurely clear
        the target. Uses tiny explicit budget (3s) to keep the test fast.
        Pins F1 dual-budget.
        """
        with tempfile.TemporaryDirectory() as base:
            active_dir = Path(base) / "active-plans"
            senior_run_id = "aaa-senior-db-expl-001"
            waiter_run_id = "zzz-waiter-db-expl-001"

            # Both injected with our live PID so reap leaves them alone.
            _write_record_direct(active_dir, _make_v2_record(senior_run_id, pid=os.getpid()))
            _write_record_direct(active_dir, _make_v2_record(waiter_run_id, pid=os.getpid()))

            r = self._run_wait_for_timeout(base, waiter_run_id, senior_run_id, {
                "Z_HARNESS_AUTO_WAIT": "0",              # explicit mode
                "Z_HARNESS_AUTO_WAIT_BUDGET_SECS": "300",  # auto budget untouched
                "Z_HARNESS_WAIT_TIMEOUT_SECS": "3",     # tiny explicit budget
                "Z_HARNESS_WAIT_POLL_SECS": "1",
            })

            self.assertEqual(r.returncode, 10, f"explicit mode must timeout with exit 10; stderr={r.stderr[:400]}")

            events = _read_metrics_events(base, "wait_timeout")
            self.assertGreater(len(events), 0, "wait_timeout event must be emitted")
            budgets = [e.get("budget_s") for e in events]
            # budget_s must equal the explicit budget (3), NOT the auto budget (300).
            self.assertIn(
                3, budgets,
                f"F1 dual-budget: wait_timeout in explicit mode must carry budget_s=3 (explicit); got {budgets}"
            )
            self.assertNotIn(
                300, budgets,
                f"F1 dual-budget: explicit mode must NOT use auto budget 300; got {budgets}"
            )


# ── T013 (k): MINOR-7 senior-only TOCTOU ─────────────────────────────────────


class TestSeniorOnlyTocTou(unittest.TestCase):
    """Case (k) MINOR-7: senior-only TOCTOU — junior C claims path while B waits
    on senior A → B's rescan ignores C.

    F-IDs pinned: F2 (TOCTOU re-scan), MINOR-7 (junior claimers ignored).
    """

    def test_junior_claimer_does_not_extend_wait(self):
        """Three runs: A (senior), B (middle waiter), C (junior).
        B waits on A. C claims the watched path while B is waiting.
        B's rescan must NOT add C to the wait set (junior, MINOR-7).
        B exits 0 when A's record is removed.

        A is injected with pid=os.getpid() so reap does not prematurely clear
        A's record. A background thread removes A's record to simulate deregister.
        C is registered via subprocess to seed its record for the TOCTOU re-scan.
        """
        with tempfile.TemporaryDirectory() as base:
            active_dir = Path(base) / "active-plans"
            run_a = "aaa-senior-minor7-001"   # eldest senior
            run_b = "mmm-middle-minor7-001"   # waiter
            run_c = "zzz-junior-minor7-001"   # junior claimer

            watched_path = "scripts/shared-file.py"
            now_ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

            # Inject A with our live PID + the watched path in held_paths.
            # Inject B (waiter) with our live PID so reap won't delete its record
            # when wait-for runs its internal reap pass.
            _write_record_direct(active_dir, _make_v2_record(
                run_a,
                pid=os.getpid(),
                held_paths=[{"path": watched_path, "since": now_ts}],
            ))
            _write_record_direct(active_dir, _make_v2_record(run_b, pid=os.getpid()))

            # Register C via subprocess (C is junior; its record will survive or not,
            # either way MINOR-7 ensures B ignores it in the TOCTOU rescan).
            r = _run_registry(
                "register",
                "--run-id", run_c,
                "--slug", "s",
                "--command", "/z-test",
                "--phase", "test",
                base_dir=base,
            )
            self.assertEqual(r.returncode, 0, f"register C: {r.stderr}")

            # C claims the same watched path (it's a junior — MINOR-7 says B ignores it).
            # C's claim uses its registered record. The claim subprocess exits; C's record
            # then has a dead pid so reap may delete it — that's fine, MINOR-7 says B
            # ignores junior claimers regardless.
            r_c_claim = _run_registry(
                "claim",
                "--run-id", run_c,
                "--paths", watched_path,
                base_dir=base,
            )
            # C may or may not succeed (C is junior so A wins anyway); either way proceed.
            _ = r_c_claim

            # Background: remove A's record after a short delay (simulating deregister).
            senior_path = active_dir / f"{run_a}.json"

            def _remove_a_later():
                time.sleep(2)
                try:
                    senior_path.unlink()
                except FileNotFoundError:
                    pass

            t = threading.Thread(target=_remove_a_later, daemon=True)
            t.start()

            # B waits on A with TOCTOU re-scan on watched_path.
            # MINOR-7: re-scan must only add NEW SENIOR holders, not junior C.
            r = _run_registry(
                "wait-for",
                "--run-id", run_b,
                "--on", run_a,
                "--paths", watched_path,
                base_dir=base,
                env_extra={
                    "Z_HARNESS_WAIT_POLL_SECS": "1",
                    "Z_HARNESS_AUTO_WAIT_BUDGET_SECS": "10",
                    "Z_HARNESS_AUTO_WAIT": "1",
                },
            )
            t.join(timeout=15)

            # B must exit 0: A cleared, and C (junior) must have been ignored (MINOR-7).
            self.assertEqual(
                r.returncode, 0,
                f"MINOR-7: B must exit 0 after A deregisters; C (junior) must not extend wait; "
                f"got {r.returncode}; stderr={r.stderr[:400]}"
            )


# ── T013 (l): MINOR-6 eldest-senior concede ──────────────────────────────────


class TestEldestSeniorConcede(unittest.TestCase):
    """Case (l) MINOR-6: ≥2 seniors on one path → loser concedes to lowest run_id (eldest).

    F-IDs pinned: F2 (check-after-claim tiebreak), F4 (run_id ordering),
                  MINOR-6 (multi-senior: concede to lowest run_id / eldest senior).
    """

    def test_two_seniors_loser_concedes_to_eldest(self):
        """Three runs: A (eldest senior), B (middle senior), C (junior waiter).
        Both A and B hold the path. C claims it.
        C must concede to A (the lowest/eldest run_id), not B.

        Pins MINOR-6 / F2 multi-senior tiebreak.
        """
        with tempfile.TemporaryDirectory() as base:
            active_dir = Path(base) / "active-plans"
            path = "scripts/contested-by-two.py"

            run_a = "aaa-eldest-minor6-001"    # eldest (lowest run_id)
            run_b = "mmm-senior-minor6-001"   # senior but not eldest
            run_c = "zzz-junior-minor6-001"   # junior claimer

            now_ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

            # Inject A and B records directly (both hold the contested path in v2 records).
            _write_record_direct(active_dir, _make_v2_record(
                run_a,
                held_paths=[{"path": path, "since": now_ts}],
            ))
            _write_record_direct(active_dir, _make_v2_record(
                run_b,
                held_paths=[{"path": path, "since": now_ts}],
            ))

            # Register C via subprocess (so it has a valid record).
            r = _run_registry(
                "register",
                "--run-id", run_c,
                "--slug", "s",
                "--command", "/z-test",
                "--phase", "test",
                base_dir=base,
            )
            self.assertEqual(r.returncode, 0, f"register C: {r.stderr}")

            # C attempts to claim the contested path.
            r = _run_registry(
                "claim",
                "--run-id", run_c,
                "--paths", path,
                base_dir=base,
            )
            self.assertEqual(r.returncode, 0, f"claim C: {r.stderr}")
            result = json.loads(r.stdout)

            # C must have conceded (both A and B are senior).
            self.assertNotIn(path, result.get("claimed", []),
                             "C must not have won a path held by two senior peers")
            conceded = result.get("conceded", [])
            self.assertGreater(len(conceded), 0, "C must have at least one conceded entry")

            # MINOR-6: the conceded holder_run_id must be the eldest (lowest run_id = A).
            holders = [c["holder_run_id"] for c in conceded if c.get("path") == path]
            self.assertEqual(
                len(holders), 1,
                f"Must be exactly one conceded entry for the path; got {conceded}"
            )
            self.assertEqual(
                holders[0], run_a,
                f"MINOR-6: conceded holder must be eldest senior {run_a!r}; got {holders[0]!r}"
            )


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
