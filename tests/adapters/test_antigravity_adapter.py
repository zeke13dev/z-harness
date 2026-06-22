"""
Tests for z_harness_cli/adapters/antigravity.py (T011)

Covers:
  * detect() — binary present vs absent vs unresponsive.
  * export_payload() — round-trip to a tmp dir; files land under .agent/.
  * inject() / cleanup() — ephemeral round-trip in a tmp git project.
  * fidelity tier = "high".
  * capability flags correct (project_mcp=False, user_mcp=False,
    needs_trust_prompt=False, supports_cwd_override=False).
  * command-capability matrix — multi-agent commands degraded, single-agent native.
  * PTY exec is stubbed so tests run without a real terminal.
  * ANTIGRAVITY_PLUGIN_ROOT injected for ephemeral launches (D14).
  * native skill export writes to .agent/personas/.
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# Repo root for sys.path insertion.
REPO_ROOT = Path(__file__).parent.parent.parent.resolve()
sys.path.insert(0, str(REPO_ROOT))

from z_harness_cli.adapters.antigravity import AntigravityAdapter, _MAGIC_MARKER  # noqa: E402
from z_harness_cli.adapters.base import (  # noqa: E402
    KNOWN_COMMANDS,
    command_tier,
    HostAdapter,
)
from z_harness_cli.inject_safety import MAGIC_MARKER  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _git_init(path: Path) -> None:
    subprocess.run(["git", "-C", str(path), "init", "-q"], check=True)


class _RepoCase(unittest.TestCase):
    """Base class: fresh git repo per test, cleaned up in tearDown."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="zh-agy-adapter-")
        self.repo = Path(self._tmp.name).resolve()
        _git_init(self.repo)
        self.adapter = AntigravityAdapter()

    def tearDown(self) -> None:
        self._tmp.cleanup()


# ---------------------------------------------------------------------------
# Static identity
# ---------------------------------------------------------------------------


class TestStaticIdentity(unittest.TestCase):
    def setUp(self) -> None:
        self.adapter = AntigravityAdapter()

    def test_name(self):
        self.assertEqual(self.adapter.name, "antigravity")

    def test_fidelity_tier_is_high(self):
        """Fidelity must be exactly 'high' — the core invariant for this adapter."""
        self.assertEqual(self.adapter.fidelity_tier, "high")

    def test_capabilities_no_project_mcp(self):
        """agy uses .agent/config.toml, not the MCP protocol."""
        self.assertFalse(self.adapter.capabilities.supports_project_mcp)

    def test_capabilities_no_user_mcp(self):
        """agy has no documented user-scoped MCP path."""
        self.assertFalse(self.adapter.capabilities.supports_user_mcp)

    def test_capabilities_no_trust_prompt(self):
        """agy does not present interactive trust prompts."""
        self.assertFalse(self.adapter.capabilities.needs_trust_prompt)

    def test_capabilities_no_cwd_override(self):
        """agy has no --cwd / --project flag."""
        self.assertFalse(self.adapter.capabilities.supports_cwd_override)

    def test_capabilities_cleanup_strategy_ephemeral(self):
        self.assertEqual(self.adapter.capabilities.cleanup_strategy, "ephemeral")


# ---------------------------------------------------------------------------
# Command-capability matrix
# ---------------------------------------------------------------------------


class TestCommandCapabilityMatrix(unittest.TestCase):
    """Verify the command-tier matrix is populated correctly for antigravity."""

    _MULTI_AGENT = {"z-execute", "z-panel", "z-consult", "z-gate"}

    def test_multi_agent_commands_degraded(self):
        """Multi-agent commands must be degraded (not blocked) on high-fidelity host."""
        for cmd in self._MULTI_AGENT:
            with self.subTest(cmd=cmd):
                tier = command_tier("antigravity", cmd)
                self.assertEqual(
                    tier,
                    "degraded",
                    f"{cmd} should be degraded on agy (high), got {tier!r}",
                )

    def test_single_agent_commands_native(self):
        """Non-multi-agent commands must be native on a high-fidelity host."""
        single_agent = set(KNOWN_COMMANDS) - self._MULTI_AGENT
        for cmd in single_agent:
            with self.subTest(cmd=cmd):
                tier = command_tier("antigravity", cmd)
                self.assertEqual(
                    tier,
                    "native",
                    f"{cmd} should be native on agy (high), got {tier!r}",
                )

    def test_all_known_commands_registered(self):
        """Every known command must have an explicit tier registered."""
        for cmd in KNOWN_COMMANDS:
            with self.subTest(cmd=cmd):
                tier = command_tier("antigravity", cmd)
                self.assertIn(tier, ("native", "degraded", "blocked"))

    def test_multi_agent_not_blocked(self):
        """agy is high-fidelity: multi-agent commands are degraded, never blocked."""
        for cmd in self._MULTI_AGENT:
            with self.subTest(cmd=cmd):
                tier = command_tier("antigravity", cmd)
                self.assertNotEqual(
                    tier,
                    "blocked",
                    f"{cmd} must not be blocked on agy (high fidelity)",
                )


# ---------------------------------------------------------------------------
# detect()
# ---------------------------------------------------------------------------


class TestDetect(unittest.TestCase):
    def setUp(self) -> None:
        self.adapter = AntigravityAdapter()

    def test_detect_not_installed_when_binary_absent(self):
        """detect() returns installed=False when agy is not on PATH."""
        with patch("shutil.which", return_value=None):
            result = self.adapter.detect()
        self.assertFalse(result.installed)
        self.assertIsNone(result.version)

    def test_detect_installed_with_version(self):
        """detect() returns installed=True and version when binary reports one."""
        mock_run = MagicMock()
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = "0.9.1\n"
        mock_run.return_value.stderr = ""

        with patch("shutil.which", return_value="/fake/agy"), \
             patch("subprocess.run", mock_run):
            result = self.adapter.detect()

        self.assertTrue(result.installed)
        self.assertEqual(result.version, "0.9.1")
        self.assertEqual(result.binary, "/fake/agy")

    def test_detect_installed_no_version_on_nonzero(self):
        """detect() returns installed=True, version=None when --version exits non-zero."""
        mock_run = MagicMock()
        mock_run.return_value.returncode = 1
        mock_run.return_value.stdout = ""
        mock_run.return_value.stderr = "error"

        with patch("shutil.which", return_value="/fake/agy"), \
             patch("subprocess.run", mock_run):
            result = self.adapter.detect()

        self.assertTrue(result.installed)
        self.assertIsNone(result.version)

    def test_detect_installed_no_version_on_timeout(self):
        """detect() handles TimeoutExpired gracefully — binary found but unresponsive."""
        def _raise(*args, **kwargs):
            raise subprocess.TimeoutExpired(cmd="agy", timeout=10)

        with patch("shutil.which", return_value="/fake/agy"), \
             patch("subprocess.run", side_effect=_raise):
            result = self.adapter.detect()

        self.assertTrue(result.installed)
        self.assertIsNone(result.version)

    def test_detect_installed_no_version_on_oserror(self):
        """detect() handles OSError from subprocess gracefully."""
        def _raise(*args, **kwargs):
            raise OSError("exec failed")

        with patch("shutil.which", return_value="/fake/agy"), \
             patch("subprocess.run", side_effect=_raise):
            result = self.adapter.detect()

        self.assertTrue(result.installed)
        self.assertIsNone(result.version)


# ---------------------------------------------------------------------------
# export_payload()
# ---------------------------------------------------------------------------


class TestExportPayload(unittest.TestCase):
    def setUp(self) -> None:
        self.adapter = AntigravityAdapter()

    def test_export_fidelity_is_high(self):
        """export_payload() always reports fidelity=high regardless of outcome."""
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "out"
            dest.mkdir()
            result = self.adapter.export_payload(dest)
        self.assertEqual(result.fidelity, "high")

    def test_export_warns_when_personas_missing(self):
        """export_payload() returns a warning when personas/ dir does not exist.

        With the T007 delegation, the runtime export (cmds/agents/skills) runs
        first.  This test mocks both the runtime export driver AND patches
        __file__ to a fake harness with no personas/ directory.
        """
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "out"
            dest.mkdir()
            fake_harness = Path(tmp) / "fake_harness"
            fake_harness.mkdir()

            import z_harness_cli.adapters.antigravity as _mod
            from runtime.drivers._export_utils import ExportResult as RE

            # Mock the runtime export driver to return an empty successful result
            # so we can focus on the personas-missing warning path.
            mock_export = MagicMock(
                return_value=RE(dest=dest, files=[], fidelity="high", warnings=[])
            )
            mock_agy_export_mod = MagicMock()
            mock_agy_export_mod.export = mock_export

            with patch.object(
                _mod,
                "__file__",
                str(fake_harness / "z_harness_cli" / "adapters" / "antigravity.py"),
            ), patch.dict(
                "sys.modules",
                {
                    "runtime.drivers.antigravity.export": mock_agy_export_mod,
                },
            ):
                result = self.adapter.export_payload(dest)

            self.assertEqual(result.fidelity, "high")
            self.assertTrue(
                any("personas/" in w for w in result.warnings),
                f"Expected warning about missing personas/, got: {result.warnings}",
            )

    def test_export_native_skill_layout(self):
        """Round-trip: persona exported to temp dir lands under .agent/personas/.

        With the T007 delegation, both the runtime export driver (mocked to
        return an empty result) and the persona exporter are called.  Files
        from both stages are combined in the returned ExportResult.
        """
        with tempfile.TemporaryDirectory() as tmp_root:
            # Resolve to avoid macOS /private/tmp vs /tmp symlink issues.
            tmp_path = Path(tmp_root).resolve()
            dest = tmp_path / "dest"
            dest.mkdir()

            def _fake_export_persona(persona_file, target_root):
                out = Path(target_root).resolve() / ".agent" / "personas" / "test.md"
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_text(f"# {MAGIC_MARKER}\nfake persona\n", encoding="utf-8")
                return out.resolve()

            fake_harness = tmp_path / "harness"
            personas_dir = fake_harness / "personas" / "builtin"
            personas_dir.mkdir(parents=True)
            persona_file = personas_dir / "default.md"
            persona_file.write_text("---\nname: default\n---\nHello.\n", encoding="utf-8")

            import z_harness_cli.adapters.antigravity as _mod
            from runtime.drivers._export_utils import ExportResult as RE

            # Mock runtime export driver (cmds/agents/skills) to return empty result.
            mock_export = MagicMock(
                return_value=RE(dest=dest, files=[], fidelity="high", warnings=[])
            )
            mock_agy_export_mod = MagicMock()
            mock_agy_export_mod.export = mock_export

            mock_pe = MagicMock()
            mock_pe.export_persona = _fake_export_persona

            with patch.object(
                _mod,
                "__file__",
                str(fake_harness / "z_harness_cli" / "adapters" / "antigravity.py"),
            ), patch.dict(
                "sys.modules",
                {
                    "runtime.drivers.antigravity.export": mock_agy_export_mod,
                    "runtime.drivers.antigravity.persona_export": mock_pe,
                },
            ):
                adapter = AntigravityAdapter()
                result = adapter.export_payload(dest)

            self.assertEqual(result.fidelity, "high")
            self.assertEqual(result.dest, dest)
            # The exported persona file must land under .agent/personas/
            persona_files = [
                f for f in result.files
                if ".agent" in str(f) and "personas" in str(f)
            ]
            self.assertEqual(len(persona_files), 1, f"Expected 1 persona file, got: {result.files}")
            self.assertIn(".agent", str(persona_files[0]))
            self.assertIn("personas", str(persona_files[0]))


# ---------------------------------------------------------------------------
# inject() / cleanup() — ephemeral round-trip
# ---------------------------------------------------------------------------


class TestInjectEphemeral(_RepoCase):
    def test_inject_writes_session_file(self):
        """inject() in ephemeral mode writes .agent/z-harness-session.md."""
        state_env: dict[str, str] = {}
        injection = self.adapter.inject(state_env, mode="ephemeral", project=self.repo)

        session_path = self.repo / ".agent" / "z-harness-session.md"
        self.assertTrue(session_path.exists(), f"Session file not found: {session_path}")
        self.assertEqual(len(injection.injected_files), 1)
        self.assertEqual(injection.injected_files[0], session_path)

    def test_inject_session_file_contains_magic_marker(self):
        """Written session file must carry the z-harness magic marker."""
        self.adapter.inject({}, mode="ephemeral", project=self.repo)
        session_path = self.repo / ".agent" / "z-harness-session.md"
        content = session_path.read_text(encoding="utf-8")
        self.assertIn(MAGIC_MARKER, content)

    def test_inject_sets_antigravity_plugin_root(self):
        """inject() must set ANTIGRAVITY_PLUGIN_ROOT in the returned env (D14)."""
        injection = self.adapter.inject({}, mode="ephemeral", project=self.repo)
        self.assertIn("ANTIGRAVITY_PLUGIN_ROOT", injection.env)
        self.assertTrue(injection.env["ANTIGRAVITY_PLUGIN_ROOT"])

    def test_inject_mode_is_ephemeral(self):
        injection = self.adapter.inject({}, mode="ephemeral", project=self.repo)
        self.assertEqual(injection.mode, "ephemeral")

    def test_inject_host_is_antigravity(self):
        injection = self.adapter.inject({}, mode="ephemeral", project=self.repo)
        self.assertEqual(injection.host, "antigravity")

    def test_inject_state_env_merged(self):
        """state_env vars must appear in injection.env."""
        state_env = {"Z_HARNESS_PLAN_DIR": "/tmp/fake-plan"}
        injection = self.adapter.inject(state_env, mode="ephemeral", project=self.repo)
        self.assertEqual(injection.env["Z_HARNESS_PLAN_DIR"], "/tmp/fake-plan")

    def test_cleanup_removes_session_file(self):
        """cleanup() must remove the injected session file."""
        injection = self.adapter.inject({}, mode="ephemeral", project=self.repo)
        session_path = self.repo / ".agent" / "z-harness-session.md"
        self.assertTrue(session_path.exists())

        self.adapter.cleanup(injection)
        self.assertFalse(session_path.exists(), "Session file should be removed after cleanup")

    def test_cleanup_idempotent(self):
        """cleanup() must be idempotent — calling it twice must not raise."""
        injection = self.adapter.inject({}, mode="ephemeral", project=self.repo)
        self.adapter.cleanup(injection)
        self.adapter.cleanup(injection)  # second call must not raise

    def test_context_manager_calls_cleanup(self):
        """Using Injection as a context manager must call cleanup on __exit__."""
        session_path = self.repo / ".agent" / "z-harness-session.md"
        with self.adapter.inject({}, mode="ephemeral", project=self.repo):
            self.assertTrue(session_path.exists())
        self.assertFalse(session_path.exists(), "Context manager __exit__ must call cleanup")

    def test_context_manager_propagates_exceptions(self):
        """Injection context manager must propagate exceptions (return False)."""
        with self.assertRaises(ValueError):
            with self.adapter.inject({}, mode="ephemeral", project=self.repo):
                raise ValueError("test error")


# ---------------------------------------------------------------------------
# inject() — in_place mode
# ---------------------------------------------------------------------------


class TestInjectInPlace(_RepoCase):
    def test_inject_in_place_writes_session_file(self):
        """inject() in in_place mode writes the session file but does not gitignore."""
        injection = self.adapter.inject({}, mode="in_place", project=self.repo)
        session_path = self.repo / ".agent" / "z-harness-session.md"
        self.assertTrue(session_path.exists())
        self.assertEqual(injection.mode, "in_place")

    def test_cleanup_in_place_is_noop(self):
        """cleanup() in in_place mode must not remove the session file."""
        injection = self.adapter.inject({}, mode="in_place", project=self.repo)
        session_path = self.repo / ".agent" / "z-harness-session.md"
        self.assertTrue(session_path.exists())

        self.adapter.cleanup(injection)
        # In in_place mode the file must survive cleanup.
        self.assertTrue(session_path.exists(), "in_place session file should survive cleanup")


# ---------------------------------------------------------------------------
# launch() — PTY exec stubbed
# ---------------------------------------------------------------------------


class TestLaunch(unittest.TestCase):
    def setUp(self) -> None:
        self.adapter = AntigravityAdapter()

    def test_launch_calls_pty_launch_with_agy(self):
        """launch() must call pty_launch with agy as the command."""
        captured: list[dict] = []

        def _fake_pty_launch(argv, env, cwd):
            captured.append({"argv": argv, "env": env, "cwd": cwd})
            return 0

        with patch("z_harness_cli.pty_launch.pty_launch", _fake_pty_launch), \
             patch("shutil.which", return_value="/fake/agy"), \
             tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            rc = self.adapter.launch(project, env=dict())

        self.assertEqual(rc, 0)
        self.assertEqual(len(captured), 1)
        self.assertIn("agy", captured[0]["argv"][0])

    def test_launch_returns_exit_code(self):
        """launch() must forward the exit code from pty_launch."""
        with patch("z_harness_cli.pty_launch.pty_launch", return_value=42), \
             patch("shutil.which", return_value="/fake/agy"), \
             tempfile.TemporaryDirectory() as tmp:
            rc = self.adapter.launch(Path(tmp), env=dict())
        self.assertEqual(rc, 42)


# ---------------------------------------------------------------------------
# HostAdapter Protocol conformance
# ---------------------------------------------------------------------------


class TestProtocolConformance(unittest.TestCase):
    """Verify AntigravityAdapter satisfies the HostAdapter Protocol at runtime."""

    def test_isinstance_host_adapter(self):
        adapter = AntigravityAdapter()
        self.assertIsInstance(adapter, HostAdapter)

    def test_all_required_attributes_present(self):
        adapter = AntigravityAdapter()
        for attr in ("name", "fidelity_tier", "capabilities"):
            self.assertTrue(hasattr(adapter, attr), f"missing attribute: {attr}")

    def test_all_required_methods_present(self):
        adapter = AntigravityAdapter()
        for method in ("detect", "export_payload", "inject", "launch", "cleanup"):
            self.assertTrue(callable(getattr(adapter, method, None)),
                            f"missing callable: {method}")


if __name__ == "__main__":
    unittest.main()
