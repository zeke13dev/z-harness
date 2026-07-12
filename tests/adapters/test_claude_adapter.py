"""Unit tests for z_harness_cli/adapters/claude.py (T008).

Covers:
  - detect(): installed/not-installed/version-parse
  - export_payload(): returns an empty native ExportResult (in-place plugin)
  - inject() ephemeral: writes CLAUDE.md, sets CLAUDE_PLUGIN_ROOT, manifest
  - inject() in_place: no files written, no CLAUDE_PLUGIN_ROOT injected
  - launch(): stubs pty_launch; verifies argv + env forwarding
  - cleanup(): delegates to inject_safety.cleanup(); idempotent
  - fidelity_tier: "native"
  - command-capability matrix: all /z-* commands "native"
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

REPO_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(REPO_ROOT))

from z_harness_cli.adapters.base import (
    KNOWN_COMMANDS,
    COMMAND_CAPABILITY_MATRIX,
    DetectResult,
    ExportResult,
    Injection,
)
# Importing the module registers the command tiers as a side-effect.
import z_harness_cli.adapters.claude as _claude_mod
from z_harness_cli.adapters.claude import ClaudeAdapter
from z_harness_cli.inject_safety import MAGIC_MARKER


def _git_init(path: Path) -> None:
    subprocess.run(["git", "-C", str(path), "init", "-q"], check=True)


class _RepoCase(unittest.TestCase):
    """Base class providing a fresh git repo per test."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="zh-claude-adapter-")
        self.repo = Path(self._tmp.name).resolve()
        _git_init(self.repo)
        self.adapter = ClaudeAdapter()

    def tearDown(self) -> None:
        self._tmp.cleanup()


# ---------------------------------------------------------------------------
# Fidelity tier assertion
# ---------------------------------------------------------------------------

class TestFidelityTier(unittest.TestCase):
    """The claude adapter must declare fidelity_tier='native'."""

    def test_fidelity_tier_is_native(self):
        adapter = ClaudeAdapter()
        self.assertEqual(adapter.fidelity_tier, "native")

    def test_name_is_claude(self):
        adapter = ClaudeAdapter()
        self.assertEqual(adapter.name, "claude")


# ---------------------------------------------------------------------------
# Command-capability matrix
# ---------------------------------------------------------------------------

class TestCommandCapabilityMatrix(unittest.TestCase):
    """All /z-* commands must be declared 'native' for the claude host."""

    def test_all_known_commands_are_native(self):
        tiers = COMMAND_CAPABILITY_MATRIX.get("claude", {})
        for cmd in KNOWN_COMMANDS:
            self.assertEqual(
                tiers.get(cmd),
                "native",
                f"Expected 'native' tier for {cmd!r} on claude host, "
                f"got {tiers.get(cmd)!r}",
            )

    def test_no_degraded_or_blocked(self):
        tiers = COMMAND_CAPABILITY_MATRIX.get("claude", {})
        non_native = {cmd: t for cmd, t in tiers.items() if t != "native"}
        self.assertEqual(
            non_native,
            {},
            f"claude adapter has non-native tiers: {non_native}",
        )


# ---------------------------------------------------------------------------
# detect()
# ---------------------------------------------------------------------------

class TestDetect(unittest.TestCase):
    """detect() probes PATH for the claude binary."""

    def test_not_installed_when_binary_absent(self):
        adapter = ClaudeAdapter()
        with patch("shutil.which", return_value=None):
            result = adapter.detect()
        self.assertFalse(result.installed)
        self.assertIsNone(result.version)
        self.assertIsNone(result.binary)

    def test_installed_with_version(self):
        adapter = ClaudeAdapter()
        with patch("shutil.which", return_value="/usr/local/bin/claude"):
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(
                    returncode=0, stdout="1.2.3\n", stderr=""
                )
                result = adapter.detect()
        self.assertTrue(result.installed)
        self.assertEqual(result.version, "1.2.3")
        self.assertEqual(result.binary, "/usr/local/bin/claude")

    def test_installed_nonzero_version_exit(self):
        """Binary present but --version exits non-zero → installed=True, version=None."""
        adapter = ClaudeAdapter()
        with patch("shutil.which", return_value="/usr/local/bin/claude"):
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(
                    returncode=1, stdout="", stderr="error"
                )
                result = adapter.detect()
        self.assertTrue(result.installed)
        self.assertIsNone(result.version)

    def test_installed_timeout_returns_installed_no_version(self):
        """Timeout during --version → installed=True, version=None (no crash)."""
        adapter = ClaudeAdapter()
        with patch("shutil.which", return_value="/usr/local/bin/claude"):
            with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("claude", 10)):
                result = adapter.detect()
        self.assertTrue(result.installed)
        self.assertIsNone(result.version)

    def test_detect_result_type(self):
        """detect() always returns a DetectResult instance."""
        adapter = ClaudeAdapter()
        with patch("shutil.which", return_value=None):
            result = adapter.detect()
        self.assertIsInstance(result, DetectResult)


# ---------------------------------------------------------------------------
# export_payload()
# ---------------------------------------------------------------------------

class TestExportPayload(unittest.TestCase):
    """export_payload() returns an empty native (in-place) ExportResult."""

    def test_export_payload_returns_empty_native_result(self):
        """Claude runs in place — export_payload writes nothing; fidelity='native'."""
        adapter = ClaudeAdapter()
        with tempfile.TemporaryDirectory() as dest_dir:
            result = adapter.export_payload(Path(dest_dir))
        self.assertIsInstance(result, ExportResult)
        self.assertEqual(result.fidelity, "native")
        self.assertEqual(list(result.files), [])
        self.assertEqual(list(result.warnings), [])

    def test_export_result_fidelity_native(self):
        """export_payload always returns fidelity='native'."""
        adapter = ClaudeAdapter()
        with tempfile.TemporaryDirectory() as dest_dir:
            with patch.object(
                _claude_mod,
                "__file__",
                "/nonexistent/z_harness_cli/adapters/claude.py",
            ):
                result = adapter.export_payload(Path(dest_dir))
        self.assertEqual(result.fidelity, "native")


# ---------------------------------------------------------------------------
# inject() — ephemeral mode
# ---------------------------------------------------------------------------

class TestInjectEphemeral(_RepoCase):
    """inject() ephemeral mode writes CLAUDE.md and sets CLAUDE_PLUGIN_ROOT."""

    def test_ephemeral_creates_claude_md(self):
        """inject(ephemeral) writes a CLAUDE.md file in the project root."""
        inj = self.adapter.inject({}, "ephemeral", self.repo)
        try:
            claude_md = self.repo / "CLAUDE.md"
            self.assertTrue(claude_md.exists(), "CLAUDE.md was not written")
        finally:
            self.adapter.cleanup(inj)

    def test_ephemeral_claude_md_carries_magic_marker(self):
        """Written CLAUDE.md must contain the z-harness magic marker."""
        inj = self.adapter.inject({}, "ephemeral", self.repo)
        try:
            content = (self.repo / "CLAUDE.md").read_text(encoding="utf-8")
            self.assertIn(MAGIC_MARKER, content)
        finally:
            self.adapter.cleanup(inj)

    def test_ephemeral_injection_sets_claude_plugin_root(self):
        """Injection env must contain CLAUDE_PLUGIN_ROOT."""
        inj = self.adapter.inject({}, "ephemeral", self.repo)
        try:
            self.assertIn("CLAUDE_PLUGIN_ROOT", inj.env)
            self.assertTrue(
                Path(inj.env["CLAUDE_PLUGIN_ROOT"]).is_absolute(),
                "CLAUDE_PLUGIN_ROOT must be an absolute path",
            )
        finally:
            self.adapter.cleanup(inj)

    def test_ephemeral_injection_lists_claude_md(self):
        """Injection.injected_files must include the written CLAUDE.md path."""
        inj = self.adapter.inject({}, "ephemeral", self.repo)
        try:
            self.assertIn(self.repo / "CLAUDE.md", inj.injected_files)
        finally:
            self.adapter.cleanup(inj)

    def test_ephemeral_mode_is_set(self):
        """Injection.mode must be 'ephemeral'."""
        inj = self.adapter.inject({}, "ephemeral", self.repo)
        try:
            self.assertEqual(inj.mode, "ephemeral")
        finally:
            self.adapter.cleanup(inj)

    def test_state_env_merged_into_injection_env(self):
        """state_env keys are present in the resulting Injection.env."""
        state_env = {"Z_HARNESS_PLAN_DIR": "/tmp/test-plan", "Z_HARNESS_TEST": "1"}
        inj = self.adapter.inject(state_env, "ephemeral", self.repo)
        try:
            self.assertEqual(inj.env["Z_HARNESS_PLAN_DIR"], "/tmp/test-plan")
            self.assertEqual(inj.env["Z_HARNESS_TEST"], "1")
        finally:
            self.adapter.cleanup(inj)

    def test_ephemeral_host_is_claude(self):
        """Injection.host must be 'claude'."""
        inj = self.adapter.inject({}, "ephemeral", self.repo)
        try:
            self.assertEqual(inj.host, "claude")
        finally:
            self.adapter.cleanup(inj)

    def test_ephemeral_gitignored(self):
        """Written CLAUDE.md must be recognised as gitignored after inject()."""
        inj = self.adapter.inject({}, "ephemeral", self.repo)
        try:
            result = subprocess.run(
                ["git", "-C", str(self.repo), "check-ignore", "-q", "CLAUDE.md"],
                capture_output=True,
                check=False,
            )
            self.assertEqual(
                result.returncode, 0,
                "CLAUDE.md is not gitignored after ephemeral inject()",
            )
        finally:
            self.adapter.cleanup(inj)


# ---------------------------------------------------------------------------
# inject() — in_place mode
# ---------------------------------------------------------------------------

class TestInjectInPlace(_RepoCase):
    """inject(in_place) does not write any files or inject CLAUDE_PLUGIN_ROOT."""

    def test_in_place_no_files_written(self):
        inj = self.adapter.inject({}, "in_place", self.repo)
        self.assertEqual(inj.injected_files, [])

    def test_in_place_mode_is_set(self):
        inj = self.adapter.inject({}, "in_place", self.repo)
        self.assertEqual(inj.mode, "in_place")

    def test_in_place_no_claude_plugin_root_injected(self):
        """in_place mode must NOT set CLAUDE_PLUGIN_ROOT (host manages it)."""
        # Remove it from environ temporarily to get a clean baseline.
        orig = os.environ.pop("CLAUDE_PLUGIN_ROOT", None)
        try:
            inj = self.adapter.inject({}, "in_place", self.repo)
            self.assertNotIn(
                "CLAUDE_PLUGIN_ROOT",
                inj.env,
                "in_place inject() must not set CLAUDE_PLUGIN_ROOT",
            )
        finally:
            if orig is not None:
                os.environ["CLAUDE_PLUGIN_ROOT"] = orig

    def test_in_place_no_claude_md_created(self):
        self.adapter.inject({}, "in_place", self.repo)
        self.assertFalse((self.repo / "CLAUDE.md").exists())


import os  # noqa: E402  (used in TestInjectInPlace above)


# ---------------------------------------------------------------------------
# launch() — stubbed PTY exec
# ---------------------------------------------------------------------------

class TestLaunch(unittest.TestCase):
    """launch() calls pty_launch with the claude binary + env + cwd."""

    def test_launch_calls_pty_launch_with_claude(self):
        """launch() passes ['claude'] (or resolved binary) to pty_launch."""
        adapter = ClaudeAdapter()
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            with patch("shutil.which", return_value="/usr/local/bin/claude"):
                with patch(
                    "z_harness_cli.pty_launch.pty_launch", return_value=0
                ) as mock_pty:
                    exit_code = adapter.launch(project, {"SOME": "env"})

        mock_pty.assert_called_once()
        call_kwargs = mock_pty.call_args
        argv = call_kwargs.kwargs.get("argv") or call_kwargs.args[0]
        self.assertEqual(argv, ["/usr/local/bin/claude"])
        self.assertEqual(exit_code, 0)

    def test_launch_passes_env_to_pty(self):
        """launch() forwards the env dict to pty_launch unchanged."""
        adapter = ClaudeAdapter()
        env = {"CLAUDE_PLUGIN_ROOT": "/some/root", "Z_HARNESS_PLAN_DIR": "/plan"}
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            with patch("shutil.which", return_value="/usr/local/bin/claude"):
                with patch(
                    "z_harness_cli.pty_launch.pty_launch", return_value=0
                ) as mock_pty:
                    adapter.launch(project, env)

        call_kwargs = mock_pty.call_args
        passed_env = call_kwargs.kwargs.get("env") or call_kwargs.args[1]
        self.assertEqual(passed_env, env)

    def test_launch_passes_cwd_to_pty(self):
        """launch() passes the resolved project path as cwd."""
        adapter = ClaudeAdapter()
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp).resolve()
            with patch("shutil.which", return_value="/usr/local/bin/claude"):
                with patch(
                    "z_harness_cli.pty_launch.pty_launch", return_value=0
                ) as mock_pty:
                    adapter.launch(project, {})

        call_kwargs = mock_pty.call_args
        cwd = call_kwargs.kwargs.get("cwd") or call_kwargs.args[2]
        self.assertEqual(cwd, project)

    def test_launch_returns_exit_code(self):
        """launch() returns whatever exit code pty_launch returns."""
        adapter = ClaudeAdapter()
        with tempfile.TemporaryDirectory() as tmp:
            with patch("shutil.which", return_value="/usr/local/bin/claude"):
                with patch(
                    "z_harness_cli.pty_launch.pty_launch", return_value=42
                ):
                    code = adapter.launch(Path(tmp), {})
        self.assertEqual(code, 42)

    def test_launch_falls_back_to_claude_without_which(self):
        """When shutil.which returns None, argv falls back to ['claude']."""
        adapter = ClaudeAdapter()
        with tempfile.TemporaryDirectory() as tmp:
            with patch("shutil.which", return_value=None):
                with patch(
                    "z_harness_cli.pty_launch.pty_launch", return_value=0
                ) as mock_pty:
                    adapter.launch(Path(tmp), {})

        call_kwargs = mock_pty.call_args
        argv = call_kwargs.kwargs.get("argv") or call_kwargs.args[0]
        self.assertEqual(argv, ["claude"])

    def test_launch_round_trip_exit_code_forwarded(self):
        """Round-trip: inject env → launch → cleanup with exit code forwarded."""
        adapter = ClaudeAdapter()
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            subprocess.run(["git", "-C", str(project), "init", "-q"], check=True)

            inj = adapter.inject({"Z_HARNESS_PLAN_DIR": "/tmp/rp"}, "ephemeral", project)
            try:
                with patch("shutil.which", return_value="/usr/local/bin/claude"):
                    with patch(
                        "z_harness_cli.pty_launch.pty_launch", return_value=0
                    ):
                        code = adapter.launch(project, inj.env)
                self.assertEqual(code, 0)
            finally:
                adapter.cleanup(inj)


# ---------------------------------------------------------------------------
# cleanup() — idempotency + delegation
# ---------------------------------------------------------------------------

class TestCleanup(_RepoCase):
    """cleanup() removes injected files and is idempotent."""

    def test_cleanup_removes_claude_md(self):
        """After cleanup, the ephemeral CLAUDE.md is gone."""
        inj = self.adapter.inject({}, "ephemeral", self.repo)
        claude_md = self.repo / "CLAUDE.md"
        self.assertTrue(claude_md.exists())

        self.adapter.cleanup(inj)
        self.assertFalse(claude_md.exists())

    def test_cleanup_is_idempotent(self):
        """Calling cleanup() twice does not raise."""
        inj = self.adapter.inject({}, "ephemeral", self.repo)
        self.adapter.cleanup(inj)
        # Second call must not raise.
        self.adapter.cleanup(inj)

    def test_cleanup_via_context_manager(self):
        """Using Injection as a context manager calls cleanup automatically."""
        claude_md = self.repo / "CLAUDE.md"
        with self.adapter.inject({}, "ephemeral", self.repo):
            self.assertTrue(claude_md.exists())
        # CLAUDE.md must be gone after the with-block exits.
        self.assertFalse(claude_md.exists())

    def test_cleanup_noop_for_in_place(self):
        """cleanup() on an in_place injection is a no-op (nothing to remove)."""
        inj = self.adapter.inject({}, "in_place", self.repo)
        # Must not raise, not write anything, not fail.
        self.adapter.cleanup(inj)
        self.adapter.cleanup(inj)  # idempotent

    def test_cleanup_noop_when_file_already_gone(self):
        """cleanup() does not crash if the CLAUDE.md was already removed."""
        inj = self.adapter.inject({}, "ephemeral", self.repo)
        # Manually remove the file before cleanup runs.
        (self.repo / "CLAUDE.md").unlink()
        # cleanup() must not raise.
        self.adapter.cleanup(inj)


# ---------------------------------------------------------------------------
# Round-trip integration test
# ---------------------------------------------------------------------------

class TestRoundTrip(_RepoCase):
    """Full detect/inject/launch/cleanup round-trip in a temp project."""

    def test_inject_launch_cleanup_roundtrip(self):
        """Ephemeral inject + stubbed launch + cleanup round-trip succeeds.

        This is the acceptance-criteria integration test: inject creates
        the CLAUDE.md, launch (stubbed) receives the injected env, and
        cleanup removes the CLAUDE.md — all without errors.
        """
        state_env = {"Z_HARNESS_PLAN_DIR": "/tmp/roundtrip-plan"}

        # 1. inject
        inj = self.adapter.inject(state_env, "ephemeral", self.repo)

        # 2. assert injection state
        self.assertEqual(inj.fidelity_tier if hasattr(inj, "fidelity_tier") else "native", "native")
        self.assertTrue((self.repo / "CLAUDE.md").exists())
        self.assertIn("CLAUDE_PLUGIN_ROOT", inj.env)
        self.assertIn("Z_HARNESS_PLAN_DIR", inj.env)
        self.assertEqual(inj.host, "claude")
        self.assertEqual(inj.mode, "ephemeral")

        # 3. launch (stubbed — no real PTY)
        with patch("shutil.which", return_value="/usr/local/bin/claude"):
            with patch("z_harness_cli.pty_launch.pty_launch", return_value=0) as mock_pty:
                exit_code = self.adapter.launch(self.repo, inj.env)

        self.assertEqual(exit_code, 0)
        mock_pty.assert_called_once()

        # 4. cleanup
        self.adapter.cleanup(inj)
        self.assertFalse((self.repo / "CLAUDE.md").exists())

    def test_fidelity_is_native_on_adapter(self):
        """Adapter fidelity_tier attribute == 'native'."""
        self.assertEqual(self.adapter.fidelity_tier, "native")


if __name__ == "__main__":
    unittest.main()
