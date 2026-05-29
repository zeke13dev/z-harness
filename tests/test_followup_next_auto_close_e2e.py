"""
tests/test_followup_next_auto_close_e2e.py — end-to-end regression tests for the
auto-close ceiling path (H2 fix).

Before T002 the fix, z-followup-next Phase 8 called sink-auto-close-check.py with
non-existent flags (--entry-id=, --diff-path=, --sink-root=) — argparse exited 2
every time, so auto-close path-to-done never fired.  The fix is to use the correct
flags: --entry, --diff, --test-exit.

These tests drive the REAL subprocess invocation — not the run_check() Python function
directly — so any future regression in the CLI interface is caught immediately.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = str(REPO_ROOT / "scripts" / "sink-auto-close-check.py")


def _run(
    entry_path: str,
    diff_path: str,
    test_exit: int,
    *,
    extra_args: list[str] | None = None,
) -> subprocess.CompletedProcess:
    """Invoke sink-auto-close-check.py as a real subprocess using the correct flags."""
    cmd = [
        sys.executable,
        SCRIPT,
        f"--entry={entry_path}",
        f"--diff={diff_path}",
        f"--test-exit={test_exit}",
    ]
    if extra_args:
        cmd.extend(extra_args)
    return subprocess.run(cmd, capture_output=True, text=True)


def _write_entry(path: Path, *, auto_close_eligible: bool = True, completion_mode: str | None = None) -> None:
    """Write a minimal entry JSON to path."""
    entry: dict = {
        "id": "20260101T000000Z-test-entry",
        "schema_version": 1,
        "status": "verify",
        "auto_close_eligible": auto_close_eligible,
        "priority": "P2",
        "name": "test followup",
        "recommended_command": "/z-do \"test\"",
    }
    if completion_mode is not None:
        entry["completion_mode"] = completion_mode
    path.write_text(json.dumps(entry), encoding="utf-8")


def _write_empty_diff(path: Path) -> None:
    """Write an empty diff file (true no-op: zero stat, no touched paths)."""
    path.write_text("", encoding="utf-8")


def _write_docs_diff(path: Path, doc_path: str = "docs/design/OVERVIEW.md") -> None:
    """Write a unified diff touching only a docs/*.md path (should pass allowlist)."""
    path.write_text(
        f"diff --git a/{doc_path} b/{doc_path}\n"
        "index abc..def 100644\n"
        f"--- a/{doc_path}\n"
        f"+++ b/{doc_path}\n"
        "@@ -1,1 +1,2 @@\n"
        " unchanged line\n"
        "+added line\n",
        encoding="utf-8",
    )


def _write_code_diff(path: Path, code_path: str = "scripts/foo.py") -> None:
    """Write a unified diff touching a .py file (should fail denylist / allowlist)."""
    path.write_text(
        f"diff --git a/{code_path} b/{code_path}\n"
        "index abc..def 100644\n"
        f"--- a/{code_path}\n"
        f"+++ b/{code_path}\n"
        "@@ -1,1 +1,2 @@\n"
        " pass\n"
        "+# new comment\n",
        encoding="utf-8",
    )


class TestAutoCloseE2ECorrectFlags(unittest.TestCase):
    """Verify the real subprocess invocation accepts the correct flag names.

    Failure class (H2 regression): sink-auto-close-check.py was invoked with
    --entry-id=, --diff-path=, --sink-root= — flags that do NOT exist in argparse.
    argparse exits 2 on every call.  After the fix the flags are --entry, --diff,
    --test-exit and the script exits 0 (pass) or 1 (fail) on valid inputs.
    """

    def test_correct_flags_accepted_not_exit_2(self):
        """Invoking with the correct flags must NOT return exit 2 (argparse usage error).

        Before the H2 fix this test would fail because argparse exits 2 on unknown flags.
        Invariant: the script must reach its core logic, not die on argument parsing.
        Failure class: script exits 2 on every auto-close check due to wrong flags.
        """
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            entry_path = td_path / "entry.json"
            diff_path = td_path / "diff.txt"
            _write_entry(entry_path)
            _write_empty_diff(diff_path)

            result = _run(str(entry_path), str(diff_path), 0)
            self.assertNotEqual(
                result.returncode, 2,
                "Script must not exit 2 (argparse usage error) when called with correct flags. "
                f"H2 regression: wrong flags caused exit 2 on every call. stderr={result.stderr!r}",
            )

    def test_eligible_entry_empty_diff_passes(self):
        """An auto_close_eligible entry with empty diff and test_exit=0 must pass (exit 0).

        Invariant: eligible + no diff + passing tests → auto_closed_low_risk.
        Failure class (H2 regression): script never reached this check because argparse
        exited 2 before the core logic ran.
        """
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            entry_path = td_path / "entry.json"
            diff_path = td_path / "diff.txt"
            _write_entry(entry_path, auto_close_eligible=True)
            _write_empty_diff(diff_path)

            result = _run(str(entry_path), str(diff_path), 0)
            self.assertEqual(
                result.returncode, 0,
                f"Auto-close must PASS for eligible entry with empty diff and test_exit=0. "
                f"stdout={result.stdout!r} stderr={result.stderr!r}",
            )

    def test_eligible_entry_passing_mode_is_noop(self):
        """The result JSON must carry mode='noop' for a true empty diff."""
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            entry_path = td_path / "entry.json"
            diff_path = td_path / "diff.txt"
            _write_entry(entry_path, auto_close_eligible=True)
            _write_empty_diff(diff_path)

            result = _run(str(entry_path), str(diff_path), 0)
            self.assertEqual(result.returncode, 0, f"stderr={result.stderr!r}")
            data = json.loads(result.stdout)
            self.assertTrue(data["passed"], f"result must be passed=True; got {data}")
            self.assertEqual(data["mode"], "noop", f"mode must be 'noop'; got {data}")

    def test_failing_test_exit_rejects(self):
        """test_exit != 0 must cause the check to fail (exit 1).

        Invariant: non-zero test_exit → no auto-close regardless of diff.
        """
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            entry_path = td_path / "entry.json"
            diff_path = td_path / "diff.txt"
            _write_entry(entry_path, auto_close_eligible=True)
            _write_empty_diff(diff_path)

            result = _run(str(entry_path), str(diff_path), 1)
            self.assertEqual(
                result.returncode, 1,
                f"Failing test_exit must cause auto-close to fail. "
                f"stdout={result.stdout!r}",
            )
            data = json.loads(result.stdout)
            self.assertFalse(data["passed"])

    def test_ineligible_entry_rejects(self):
        """Entry with auto_close_eligible=false must fail even with clean diff."""
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            entry_path = td_path / "entry.json"
            diff_path = td_path / "diff.txt"
            _write_entry(entry_path, auto_close_eligible=False)
            _write_empty_diff(diff_path)

            result = _run(str(entry_path), str(diff_path), 0)
            self.assertEqual(result.returncode, 1, f"stdout={result.stdout!r}")
            data = json.loads(result.stdout)
            self.assertFalse(data["passed"])

    def test_completion_mode_set_rejects(self):
        """Entry with completion_mode already set must fail (would double-close)."""
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            entry_path = td_path / "entry.json"
            diff_path = td_path / "diff.txt"
            _write_entry(entry_path, auto_close_eligible=True, completion_mode="human_confirmed")
            _write_empty_diff(diff_path)

            result = _run(str(entry_path), str(diff_path), 0)
            self.assertEqual(result.returncode, 1, f"stdout={result.stdout!r}")
            data = json.loads(result.stdout)
            self.assertFalse(data["passed"])

    def test_old_wrong_flags_rejected_by_argparse(self):
        """Calling with the OLD (broken) flags must exit 2 — confirming they don't exist.

        This is the negative control: the H2 bug was calling the script with
        --entry-id= --diff-path= --sink-root= which do NOT exist → exit 2.
        We confirm those flags are still absent (a future patch should not add them).
        """
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            entry_path = td_path / "entry.json"
            diff_path = td_path / "diff.txt"
            _write_entry(entry_path)
            _write_empty_diff(diff_path)

            # Use the OLD wrong flags that z-followup-next used before the fix
            cmd = [
                sys.executable,
                SCRIPT,
                f"--entry-id=20260101T000000Z-test-entry",
                f"--diff-path={diff_path}",
                f"--sink-root={td}",
                f"--test-exit=0",
            ]
            result = subprocess.run(cmd, capture_output=True, text=True)
            self.assertEqual(
                result.returncode, 2,
                "Old (pre-fix) flag names must still exit 2 (argparse error) — "
                "confirming they do not exist and the H2 bug path is blocked.",
            )

    def test_stdout_is_json(self):
        """The script must always emit a parseable JSON object on stdout."""
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            entry_path = td_path / "entry.json"
            diff_path = td_path / "diff.txt"
            _write_entry(entry_path, auto_close_eligible=True)
            _write_empty_diff(diff_path)

            result = _run(str(entry_path), str(diff_path), 0)
            try:
                data = json.loads(result.stdout)
            except json.JSONDecodeError:
                self.fail(f"stdout must be valid JSON; got {result.stdout!r}")
            self.assertIn("passed", data, "JSON must have 'passed' key")
            self.assertIn("reason", data, "JSON must have 'reason' key")
            self.assertIn("mode", data, "JSON must have 'mode' key")


class TestAutoCloseE2EDocsOnlyPath(unittest.TestCase):
    """Test the docs-only (allowlist) auto-close path end-to-end."""

    def test_docs_diff_eligible_passes(self):
        """A diff touching only docs/**/*.md must pass the docs-only ceiling.

        Invariant: auto_close_eligible + test passes + only docs touched → mode=docs_only.
        """
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            entry_path = td_path / "entry.json"
            diff_path = td_path / "diff.txt"
            _write_entry(entry_path, auto_close_eligible=True)
            _write_docs_diff(diff_path, "docs/design/OVERVIEW.md")

            result = _run(str(entry_path), str(diff_path), 0)
            self.assertEqual(
                result.returncode, 0,
                f"docs-only diff with eligible entry must pass auto-close. "
                f"stdout={result.stdout!r} stderr={result.stderr!r}",
            )
            data = json.loads(result.stdout)
            self.assertTrue(data["passed"])
            self.assertEqual(data["mode"], "docs_only")

    def test_code_diff_fails(self):
        """A diff touching a Python script must fail the auto-close ceiling."""
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            entry_path = td_path / "entry.json"
            diff_path = td_path / "diff.txt"
            _write_entry(entry_path, auto_close_eligible=True)
            _write_code_diff(diff_path, "scripts/foo.py")

            result = _run(str(entry_path), str(diff_path), 0)
            self.assertEqual(
                result.returncode, 1,
                f"Code diff must fail the auto-close ceiling. stdout={result.stdout!r}",
            )
            data = json.loads(result.stdout)
            self.assertFalse(data["passed"])


if __name__ == "__main__":
    unittest.main()
