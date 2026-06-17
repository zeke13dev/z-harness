"""
Tests for scripts/run-memory-review.sh — AXIOM_READY emission.

Cases covered:
  axiom_ready_emitted_when_extract_on  — emits AXIOM_READY <path> when Z_HARNESS_AXIOM_EXTRACT is unset
  axiom_ready_emitted_when_extract_1   — emits AXIOM_READY <path> when Z_HARNESS_AXIOM_EXTRACT=1
  axiom_ready_not_emitted_when_0       — does NOT emit AXIOM_READY when Z_HARNESS_AXIOM_EXTRACT=0
  axiom_ready_emitted_when_false       — DOES emit AXIOM_READY when Z_HARNESS_AXIOM_EXTRACT=false (only "0" is off)
  axiom_ready_path_matches_diff_path   — the path on the AXIOM_READY line matches the cumulative.diff path
  status_ready_unaffected              — STATUS: ready is always emitted (AXIOM_READY gating doesn't suppress it)

HERMETICITY: each test creates a fresh tmpdir with a git repo and an archive run dir.
The real repo's artifacts are never touched.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SCRIPT = str(_REPO_ROOT / "scripts" / "run-memory-review.sh")


def _git_init_with_commit(tmp_path: Path) -> None:
    """Initialise a git repo with one commit so diff comparisons have a ref."""
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=str(tmp_path), check=True, capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=str(tmp_path), check=True, capture_output=True,
    )
    # Create a base commit so HEAD exists and diff is non-empty
    readme = tmp_path / "README.md"
    readme.write_text("initial\n")
    subprocess.run(["git", "add", "README.md"], cwd=str(tmp_path), check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "initial"],
        cwd=str(tmp_path), check=True, capture_output=True,
    )
    # Make a second commit so HEAD differs from origin/main-equivalent (no remote,
    # the script falls back to HEAD~5/empty-tree; this gives us a non-empty diff)
    change = tmp_path / "change.txt"
    change.write_text("some change\n")
    subprocess.run(["git", "add", "change.txt"], cwd=str(tmp_path), check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "add change"],
        cwd=str(tmp_path), check=True, capture_output=True,
    )


def _setup_plan_dir(tmp_path: Path, run_id: str = "run-test-001") -> Path:
    """Create a minimal plan dir structure the script expects."""
    plan_dir = tmp_path / "z-harness" / "test-plan"
    plan_dir.mkdir(parents=True, exist_ok=True)
    # Create TASKS.md with a completed task so implement-all doesn't skip
    (plan_dir / "TASKS.md").write_text("- [x] T001 — test task\n")
    # Create TAGS.txt in the expected location (docs/llm/TAGS.txt relative to repo root)
    tags_dir = tmp_path / "docs" / "llm"
    tags_dir.mkdir(parents=True, exist_ok=True)
    (tags_dir / "TAGS.txt").write_text("test-tag\n")
    # Create archive/<run_id> dir
    run_dir = plan_dir / "archive" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    return plan_dir


def _run_script(
    tmp_path: Path,
    plan_dir: Path,
    run_id: str = "run-test-001",
    parent_command: str = "implement-all",
    env_extra: dict[str, str] | None = None,
) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    # Remove any inherited AXIOM_EXTRACT so tests are clean by default
    env.pop("Z_HARNESS_AXIOM_EXTRACT", None)
    env["Z_HARNESS_PLAN_DIR"] = str(plan_dir)
    env["Z_HARNESS_SLUG"] = "test-plan"
    # Point PLUGIN_ROOT somewhere that won't try to log events
    env["ANTIGRAVITY_PLUGIN_ROOT"] = "/nonexistent"
    env["CLAUDE_PLUGIN_ROOT"] = "/nonexistent"
    if env_extra:
        env.update(env_extra)
    return subprocess.run(
        ["bash", _SCRIPT, run_id, parent_command],
        cwd=str(tmp_path),
        env=env,
        capture_output=True,
        text=True,
    )


class TestRunMemoryReviewAxiomReady(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="test_rmr_")
        self._tmp_path = Path(self._tmp)
        _git_init_with_commit(self._tmp_path)
        self._plan_dir = _setup_plan_dir(self._tmp_path)

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _get_axiom_ready_lines(self, stdout: str) -> list[str]:
        return [line for line in stdout.splitlines() if line.startswith("AXIOM_READY ")]

    # ------------------------------------------------------------------
    # axiom_ready_emitted_when_extract_on (unset)
    # ------------------------------------------------------------------

    def test_axiom_ready_emitted_when_unset(self):
        """AXIOM_READY is emitted when Z_HARNESS_AXIOM_EXTRACT is unset (default on)."""
        result = _run_script(self._tmp_path, self._plan_dir)
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("STATUS: ready", result.stdout.splitlines()[0])
        axiom_lines = self._get_axiom_ready_lines(result.stdout)
        self.assertEqual(len(axiom_lines), 1, msg=f"Expected 1 AXIOM_READY line, got: {axiom_lines!r}\nstdout={result.stdout!r}")

    # ------------------------------------------------------------------
    # axiom_ready_emitted_when_extract_1
    # ------------------------------------------------------------------

    def test_axiom_ready_emitted_when_extract_1(self):
        """AXIOM_READY is emitted when Z_HARNESS_AXIOM_EXTRACT=1 (any non-off value)."""
        result = _run_script(
            self._tmp_path, self._plan_dir,
            env_extra={"Z_HARNESS_AXIOM_EXTRACT": "1"},
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        axiom_lines = self._get_axiom_ready_lines(result.stdout)
        self.assertEqual(len(axiom_lines), 1, msg=f"Expected 1 AXIOM_READY line, stdout={result.stdout!r}")

    # ------------------------------------------------------------------
    # axiom_ready_not_emitted_when_0
    # ------------------------------------------------------------------

    def test_axiom_ready_not_emitted_when_toml_disabled(self):
        """AXIOM_READY is NOT emitted when axioms.auto_extract_post_run = false in config.toml.

        T001 made the raw env var Z_HARNESS_AXIOM_EXTRACT no longer shadow TOML.
        The correct disable path is config.toml, not a raw env var.  This test
        verifies that the config.toml disable path works end-to-end through
        run-memory-review.sh → config.py get → the AXIOM_READY gate.

        The TOML-wins ingress gate means: when TOML sets auto_extract_post_run=false,
        even a raw env var Z_HARNESS_AXIOM_EXTRACT=1 is ignored.  This test asserts
        both the disable path (TOML=false) and the TOML-wins invariant (env ignored).
        """
        # Write a repo-local config.toml with auto_extract_post_run = false.
        zh_dir = self._tmp_path / ".z-harness"
        zh_dir.mkdir(parents=True, exist_ok=True)
        config_toml = zh_dir / "config.toml"
        config_toml.write_text(
            "[axioms]\nauto_extract_post_run = false\n", encoding="utf-8"
        )
        result = _run_script(
            self._tmp_path, self._plan_dir,
            env_extra={
                # Point config.py at the temp config so it reads auto_extract_post_run=false from TOML.
                "Z_HARNESS_REPO_CONFIG": str(config_toml),
                # Use the real repo as PLUGIN_ROOT so config.py is reachable.
                "CLAUDE_PLUGIN_ROOT": str(_REPO_ROOT),
                "ANTIGRAVITY_PLUGIN_ROOT": str(_REPO_ROOT),
                # Also set the legacy raw env var to 1 (=enable); TOML=false must win (T001 ingress gate).
                "Z_HARNESS_AXIOM_EXTRACT": "1",
            },
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("STATUS: ready", result.stdout.splitlines()[0])
        axiom_lines = self._get_axiom_ready_lines(result.stdout)
        self.assertEqual(
            len(axiom_lines), 0,
            msg=(
                "Expected no AXIOM_READY: config.toml sets auto_extract_post_run=false and "
                "TOML must win over Z_HARNESS_AXIOM_EXTRACT=1 (T001 ingress-gate); "
                f"stdout={result.stdout!r}"
            ),
        )

    # ------------------------------------------------------------------
    # axiom_ready_emitted_when_false
    # ------------------------------------------------------------------

    def test_axiom_ready_emitted_when_false(self):
        """AXIOM_READY IS emitted when Z_HARNESS_AXIOM_EXTRACT=false (only "0" suppresses)."""
        result = _run_script(
            self._tmp_path, self._plan_dir,
            env_extra={"Z_HARNESS_AXIOM_EXTRACT": "false"},
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("STATUS: ready", result.stdout.splitlines()[0])
        axiom_lines = self._get_axiom_ready_lines(result.stdout)
        self.assertEqual(len(axiom_lines), 1, msg=f"Expected 1 AXIOM_READY line (false is not off), stdout={result.stdout!r}")

    # ------------------------------------------------------------------
    # axiom_ready_path_matches_diff_path
    # ------------------------------------------------------------------

    def test_axiom_ready_path_matches_diff_path(self):
        """The path on the AXIOM_READY line matches the cumulative.diff path (line 2)."""
        result = _run_script(self._tmp_path, self._plan_dir)
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        lines = result.stdout.splitlines()
        self.assertEqual(lines[0], "STATUS: ready")
        diff_path = lines[1]  # line 2 is cumulative.diff path
        axiom_lines = self._get_axiom_ready_lines(result.stdout)
        self.assertEqual(len(axiom_lines), 1)
        axiom_path = axiom_lines[0][len("AXIOM_READY "):]
        self.assertEqual(axiom_path, diff_path, msg="AXIOM_READY path must match cumulative.diff path")

    # ------------------------------------------------------------------
    # status_ready_unaffected
    # ------------------------------------------------------------------

    def test_status_ready_always_present_regardless_of_axiom_gate(self):
        """STATUS: ready is always the first line even when AXIOM_READY is suppressed (only "0" suppresses)."""
        result = _run_script(
            self._tmp_path, self._plan_dir,
            env_extra={"Z_HARNESS_AXIOM_EXTRACT": "0"},
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        first_line = result.stdout.splitlines()[0]
        self.assertEqual(first_line, "STATUS: ready", msg=f"Expected STATUS: ready as first line, stdout={result.stdout!r}")


if __name__ == "__main__":
    unittest.main()
