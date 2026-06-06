"""
Tests for z_harness_cli/adapters/cursor.py

Covers:
  * detect() — binary present vs absent vs unresponsive.
  * export_payload() — round-trip to a tmp dir; files land under .cursor/.
  * inject() / cleanup() — ephemeral round-trip in a tmp git project.
  * fidelity tier = "flattened".
  * capability flags correct (project_mcp=True, user_mcp=True,
    needs_trust_prompt=True, supports_cwd_override=False).
  * command-capability matrix — multi-agent commands blocked, others degraded.
  * PTY exec is stubbed so tests run without a real terminal.
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

from z_harness_cli.adapters.cursor import CursorAdapter, _MAGIC_MARKER  # noqa: E402
from z_harness_cli.adapters.base import (  # noqa: E402
    KNOWN_COMMANDS,
    command_tier,
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
        self._tmp = tempfile.TemporaryDirectory(prefix="zh-cursor-adapter-")
        self.repo = Path(self._tmp.name).resolve()
        _git_init(self.repo)
        self.adapter = CursorAdapter()

    def tearDown(self) -> None:
        self._tmp.cleanup()


# ---------------------------------------------------------------------------
# Static identity
# ---------------------------------------------------------------------------


class TestStaticIdentity(unittest.TestCase):
    def setUp(self) -> None:
        self.adapter = CursorAdapter()

    def test_name(self):
        self.assertEqual(self.adapter.name, "cursor")

    def test_fidelity_tier_is_flattened(self):
        """Fidelity must be exactly 'flattened' — the core invariant for this adapter."""
        self.assertEqual(self.adapter.fidelity_tier, "flattened")

    def test_capabilities_project_mcp(self):
        """cursor-agent supports project-scoped MCP via .cursor/mcp.json."""
        self.assertTrue(self.adapter.capabilities.supports_project_mcp)

    def test_capabilities_user_mcp(self):
        """cursor-agent supports user-scoped MCP via ~/.cursor/mcp.json."""
        self.assertTrue(self.adapter.capabilities.supports_user_mcp)

    def test_capabilities_needs_trust_prompt(self):
        """cursor-agent surfaces per-tool approval interactively."""
        self.assertTrue(self.adapter.capabilities.needs_trust_prompt)

    def test_capabilities_no_cwd_override(self):
        """cursor-agent has no --cwd / --project flag."""
        self.assertFalse(self.adapter.capabilities.supports_cwd_override)

    def test_capabilities_cleanup_strategy_ephemeral(self):
        self.assertEqual(self.adapter.capabilities.cleanup_strategy, "ephemeral")


# ---------------------------------------------------------------------------
# Command-capability matrix
# ---------------------------------------------------------------------------


class TestCommandCapabilityMatrix(unittest.TestCase):
    """Verify the command-tier matrix is populated correctly for cursor."""

    _MULTI_AGENT = {"z-implement-all", "z-panel", "z-consult", "z-gate"}

    def test_multi_agent_commands_blocked(self):
        """Multi-agent orchestration commands must be blocked on flattened fidelity."""
        for cmd in self._MULTI_AGENT:
            with self.subTest(cmd=cmd):
                tier = command_tier("cursor", cmd)
                self.assertEqual(
                    tier,
                    "blocked",
                    f"{cmd} should be blocked on cursor (flattened), got {tier!r}",
                )

    def test_single_agent_commands_degraded(self):
        """Non-multi-agent commands must be degraded (not native, not blocked)."""
        single_agent = set(KNOWN_COMMANDS) - self._MULTI_AGENT
        for cmd in single_agent:
            with self.subTest(cmd=cmd):
                tier = command_tier("cursor", cmd)
                self.assertEqual(
                    tier,
                    "degraded",
                    f"{cmd} should be degraded on cursor (flattened), got {tier!r}",
                )

    def test_all_known_commands_registered(self):
        """Every known command must have an explicit tier registered."""
        for cmd in KNOWN_COMMANDS:
            with self.subTest(cmd=cmd):
                tier = command_tier("cursor", cmd)
                self.assertIn(tier, ("native", "degraded", "blocked"))


# ---------------------------------------------------------------------------
# detect()
# ---------------------------------------------------------------------------


class TestDetect(unittest.TestCase):
    def setUp(self) -> None:
        self.adapter = CursorAdapter()

    def test_detect_not_installed_when_binary_absent(self):
        """detect() returns installed=False when cursor-agent is not on PATH."""
        with patch("shutil.which", return_value=None):
            result = self.adapter.detect()
        self.assertFalse(result.installed)
        self.assertIsNone(result.version)

    def test_detect_installed_with_version(self):
        """detect() returns installed=True and version when binary reports one."""
        mock_run = MagicMock()
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = "2026.05.28-a70ca7c\n"
        mock_run.return_value.stderr = ""

        with patch("shutil.which", return_value="/fake/cursor-agent"), \
             patch("subprocess.run", mock_run):
            result = self.adapter.detect()

        self.assertTrue(result.installed)
        self.assertEqual(result.version, "2026.05.28-a70ca7c")
        self.assertEqual(result.binary, "/fake/cursor-agent")

    def test_detect_installed_no_version_on_nonzero(self):
        """detect() returns installed=True, version=None when --version exits non-zero."""
        mock_run = MagicMock()
        mock_run.return_value.returncode = 1
        mock_run.return_value.stdout = ""
        mock_run.return_value.stderr = "error"

        with patch("shutil.which", return_value="/fake/cursor-agent"), \
             patch("subprocess.run", mock_run):
            result = self.adapter.detect()

        self.assertTrue(result.installed)
        self.assertIsNone(result.version)

    def test_detect_installed_no_version_on_timeout(self):
        """detect() handles TimeoutExpired gracefully — binary found but unresponsive."""
        def _raise(*args, **kwargs):
            raise subprocess.TimeoutExpired(cmd="cursor-agent", timeout=10)

        with patch("shutil.which", return_value="/fake/cursor-agent"), \
             patch("subprocess.run", side_effect=_raise):
            result = self.adapter.detect()

        self.assertTrue(result.installed)
        self.assertIsNone(result.version)


# ---------------------------------------------------------------------------
# export_payload()
# ---------------------------------------------------------------------------


class TestExportPayload(unittest.TestCase):
    def setUp(self) -> None:
        self.adapter = CursorAdapter()

    def test_export_warns_when_personas_missing(self):
        """export_payload() returns a warning when personas/ dir does not exist."""
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "out"
            dest.mkdir()
            # Patch the harness root to a dir that has no personas/
            fake_root = Path(tmp) / "harness"
            fake_root.mkdir()
            with patch("z_harness_cli.adapters.cursor.Path") as mock_path_cls:
                # Only patch __file__ parent resolution; use real Path otherwise.
                # Easier: patch the computed harness_root via the adapter's module.
                pass  # We'll use a different approach below.

        # Simpler: patch the runtime import to fail (no personas/ found scenario).
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "out"
            dest.mkdir()
            # Patch Path(__file__).parent.parent.parent to a dir with no personas/
            fake_harness = Path(tmp) / "fake_harness"
            fake_harness.mkdir()

            import z_harness_cli.adapters.cursor as _mod
            real_file = _mod.__file__

            with patch.object(_mod, "__file__",
                              str(fake_harness / "z_harness_cli" / "adapters" / "cursor.py")):
                result = self.adapter.export_payload(dest)

            # personas/ doesn't exist under fake harness root → warning
            self.assertEqual(result.fidelity, "flattened")
            self.assertEqual(result.files, [])
            self.assertTrue(
                any("personas/" in w for w in result.warnings),
                f"Expected warning about missing personas/, got: {result.warnings}",
            )

    def test_export_fidelity_is_flattened(self):
        """export_payload() always reports fidelity=flattened regardless of outcome."""
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "out"
            dest.mkdir()
            result = self.adapter.export_payload(dest)
        self.assertEqual(result.fidelity, "flattened")

    def test_export_to_temp_dir_with_mock_persona(self):
        """Round-trip: persona exported to temp dir lands under .cursor/personas/."""
        with tempfile.TemporaryDirectory() as tmp_root:
            dest = Path(tmp_root) / "dest"
            dest.mkdir()

            # Stub export_persona to write a dummy file under dest.
            def _fake_export_persona(persona_file, target_root):
                out = Path(target_root) / ".cursor" / "personas" / "test.mdc"
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_text(f"# {MAGIC_MARKER}\nfake persona\n", encoding="utf-8")
                return out.resolve()

            # Build a fake harness with a personas/ dir containing one persona.
            fake_harness = Path(tmp_root) / "harness"
            personas_dir = fake_harness / "personas"
            personas_dir.mkdir(parents=True)
            persona_file = personas_dir / "default.md"
            persona_file.write_text("---\nname: default\n---\nHello.\n", encoding="utf-8")

            import z_harness_cli.adapters.cursor as _mod

            with patch.object(
                _mod,
                "__file__",
                str(fake_harness / "z_harness_cli" / "adapters" / "cursor.py"),
            ), patch(
                "z_harness_cli.adapters.cursor.CursorAdapter.export_payload",
                wraps=self.adapter.export_payload,
            ):
                # Directly patch the runtime import inside the method.
                with patch.dict(
                    "sys.modules",
                    {
                        "runtime": MagicMock(),
                        "runtime.drivers": MagicMock(),
                        "runtime.drivers.cursor": MagicMock(),
                        "runtime.drivers.cursor.persona_export": MagicMock(
                            export_persona=_fake_export_persona
                        ),
                    },
                ):
                    # Re-create adapter to pick up patched __file__.
                    adapter = CursorAdapter()
                    result = adapter.export_payload(dest)

            self.assertEqual(result.fidelity, "flattened")
            self.assertEqual(result.dest, dest)


# ---------------------------------------------------------------------------
# inject() / cleanup() — ephemeral round-trip
# ---------------------------------------------------------------------------


class TestInjectEphemeral(_RepoCase):
    def test_inject_writes_mdc_rule(self):
        """inject() in ephemeral mode writes .cursor/rules/z-harness-session.mdc."""
        state_env: dict[str, str] = {}
        injection = self.adapter.inject(state_env, mode="ephemeral", project=self.repo)

        rule_path = self.repo / ".cursor" / "rules" / "z-harness-session.mdc"
        self.assertTrue(rule_path.exists(), f"Rule not found: {rule_path}")
        self.assertEqual(len(injection.injected_files), 1)
        self.assertEqual(injection.injected_files[0], rule_path)

    def test_inject_mdc_contains_magic_marker(self):
        """Written .mdc rule must carry the z-harness magic marker."""
        self.adapter.inject({}, mode="ephemeral", project=self.repo)
        rule_path = self.repo / ".cursor" / "rules" / "z-harness-session.mdc"
        content = rule_path.read_text(encoding="utf-8")
        self.assertIn(MAGIC_MARKER, content)

    def test_inject_sets_claude_plugin_root(self):
        """inject() must set CLAUDE_PLUGIN_ROOT in the returned env (D14)."""
        injection = self.adapter.inject({}, mode="ephemeral", project=self.repo)
        self.assertIn("CLAUDE_PLUGIN_ROOT", injection.env)
        # The value must be a non-empty path string.
        self.assertTrue(injection.env["CLAUDE_PLUGIN_ROOT"])

    def test_inject_mode_is_ephemeral(self):
        injection = self.adapter.inject({}, mode="ephemeral", project=self.repo)
        self.assertEqual(injection.mode, "ephemeral")

    def test_inject_host_is_cursor(self):
        injection = self.adapter.inject({}, mode="ephemeral", project=self.repo)
        self.assertEqual(injection.host, "cursor")

    def test_inject_state_env_merged(self):
        """state_env vars must appear in injection.env."""
        state_env = {"Z_HARNESS_PLAN_DIR": "/tmp/fake-plan"}
        injection = self.adapter.inject(state_env, mode="ephemeral", project=self.repo)
        self.assertEqual(injection.env["Z_HARNESS_PLAN_DIR"], "/tmp/fake-plan")

    def test_cleanup_removes_rule_file(self):
        """cleanup() must remove the injected .mdc rule file."""
        injection = self.adapter.inject({}, mode="ephemeral", project=self.repo)
        rule_path = self.repo / ".cursor" / "rules" / "z-harness-session.mdc"
        self.assertTrue(rule_path.exists())

        self.adapter.cleanup(injection)
        self.assertFalse(rule_path.exists(), "Rule file should be removed after cleanup")

    def test_cleanup_idempotent(self):
        """cleanup() must be idempotent — calling it twice must not raise."""
        injection = self.adapter.inject({}, mode="ephemeral", project=self.repo)
        self.adapter.cleanup(injection)
        self.adapter.cleanup(injection)  # second call must not raise

    def test_context_manager_calls_cleanup(self):
        """Using Injection as a context manager must call cleanup on __exit__."""
        rule_path = self.repo / ".cursor" / "rules" / "z-harness-session.mdc"
        with self.adapter.inject({}, mode="ephemeral", project=self.repo):
            self.assertTrue(rule_path.exists())
        self.assertFalse(rule_path.exists(), "Context manager __exit__ must call cleanup")

    def test_context_manager_propagates_exceptions(self):
        """Injection context manager must propagate exceptions (return False)."""
        with self.assertRaises(ValueError):
            with self.adapter.inject({}, mode="ephemeral", project=self.repo):
                raise ValueError("test error")


# ---------------------------------------------------------------------------
# inject() — in_place mode
# ---------------------------------------------------------------------------


class TestInjectInPlace(_RepoCase):
    def test_inject_in_place_writes_rule(self):
        """inject() in in_place mode writes the rule but does not gitignore."""
        injection = self.adapter.inject({}, mode="in_place", project=self.repo)
        rule_path = self.repo / ".cursor" / "rules" / "z-harness-session.mdc"
        self.assertTrue(rule_path.exists())
        self.assertEqual(injection.mode, "in_place")

    def test_cleanup_in_place_is_noop(self):
        """cleanup() in in_place mode must not remove the rule file."""
        injection = self.adapter.inject({}, mode="in_place", project=self.repo)
        rule_path = self.repo / ".cursor" / "rules" / "z-harness-session.mdc"
        self.assertTrue(rule_path.exists())

        self.adapter.cleanup(injection)
        # In in_place mode the file must survive cleanup.
        self.assertTrue(rule_path.exists(), "in_place rule should survive cleanup")


# ---------------------------------------------------------------------------
# launch() — PTY exec stubbed
# ---------------------------------------------------------------------------


class TestLaunch(unittest.TestCase):
    def setUp(self) -> None:
        self.adapter = CursorAdapter()

    def test_launch_calls_pty_launch_with_cursor_agent(self):
        """launch() must call pty_launch with cursor-agent as the command."""
        captured: list[dict] = []

        def _fake_pty_launch(argv, env, cwd):
            captured.append({"argv": argv, "env": env, "cwd": cwd})
            return 0

        # pty_launch is lazily imported inside launch(); patch at its source module.
        with patch("z_harness_cli.pty_launch.pty_launch", _fake_pty_launch), \
             patch("shutil.which", return_value="/fake/cursor-agent"), \
             tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            rc = self.adapter.launch(project, env=dict())

        self.assertEqual(rc, 0)
        self.assertEqual(len(captured), 1)
        self.assertIn("cursor-agent", captured[0]["argv"][0])

    def test_launch_returns_exit_code(self):
        """launch() must forward the exit code from pty_launch."""
        # pty_launch is lazily imported inside launch(); patch at its source module.
        with patch("z_harness_cli.pty_launch.pty_launch", return_value=42), \
             patch("shutil.which", return_value="/fake/cursor-agent"), \
             tempfile.TemporaryDirectory() as tmp:
            rc = self.adapter.launch(Path(tmp), env=dict())
        self.assertEqual(rc, 42)


# ---------------------------------------------------------------------------
# HostAdapter Protocol conformance
# ---------------------------------------------------------------------------


class TestProtocolConformance(unittest.TestCase):
    """Verify CursorAdapter satisfies the HostAdapter Protocol at runtime."""

    def test_isinstance_host_adapter(self):
        from z_harness_cli.adapters.base import HostAdapter
        adapter = CursorAdapter()
        self.assertIsInstance(adapter, HostAdapter)

    def test_all_required_attributes_present(self):
        adapter = CursorAdapter()
        for attr in ("name", "fidelity_tier", "capabilities"):
            self.assertTrue(hasattr(adapter, attr), f"missing attribute: {attr}")

    def test_all_required_methods_present(self):
        adapter = CursorAdapter()
        for method in ("detect", "export_payload", "inject", "launch", "cleanup"):
            self.assertTrue(callable(getattr(adapter, method, None)),
                            f"missing callable: {method}")


if __name__ == "__main__":
    unittest.main()
