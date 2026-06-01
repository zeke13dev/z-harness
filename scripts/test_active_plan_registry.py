"""
scripts/test_active_plan_registry.py — pytest tests for scripts/active-plan-registry.py

Cases covered:
  round_trip                — register → list → deregister; record is present then absent
  concurrent_registers      — N=10 concurrent registers (distinct run-ids) produce exactly
                               N uncorrupted records (no corruption, no partial writes)
  safe_basename_traversal   — safe-basename validation rejects '../x', 'a/b', and leading '-'
  list_skips_torn_files     — list skips a deliberately truncated *.json file
  register_exit_code        — register returns exit code 3 on forced failure (unwritable dir)

All tests use a hermetic temp base via Z_HARNESS_BASE_DIR so no anchor pollution
occurs at /Users/zeke/dev/z-harness/.git/.z-harness-base or the real registry.
"""

from __future__ import annotations

import concurrent.futures
import json
import os
import stat
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
REGISTRY_PY = str(REPO_ROOT / "scripts" / "active-plan-registry.py")


def _run_registry(
    *args: str,
    base_dir: str,
    cwd: str | None = None,
) -> subprocess.CompletedProcess:
    """Invoke active-plan-registry.py as a subprocess under a hermetic base."""
    env = {
        **os.environ,
        "Z_HARNESS_BASE_DIR": base_dir,
        # Prevent anchor writes in git-common-dir (SPEC invariant 7):
        # Z_HARNESS_BASE_DIR is the tier-1 escape hatch that bypasses the anchor.
    }
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


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
