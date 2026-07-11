from __future__ import annotations

import os
import subprocess
import tempfile
import sys
import unittest

from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

REPO_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(REPO_ROOT))

from z_harness_cli.__main__ import app  # noqa: E402
from z_harness_cli.adapters.base import DetectResult  # noqa: E402


class SetupCommandTest(unittest.TestCase):
    def setUp(self) -> None:
        self.runner = CliRunner()

    def test_setup_dry_run_lists_selected_harnesses_without_installing(self) -> None:
        claude = MagicMock()
        claude.name = "claude"
        claude.fidelity_tier = "native"
        cursor = MagicMock()
        cursor.name = "cursor"
        cursor.fidelity_tier = "flattened"

        with patch(
            "z_harness_cli.adapters.registry.detect_all",
            return_value=[
                (claude, DetectResult(installed=True, version="1.0.0")),
                (cursor, DetectResult(installed=False)),
            ],
        ), patch("z_harness_cli.commands.setup.shutil.which", return_value=None), patch(
            "z_harness_cli.commands.setup._run_plugin_install"
        ) as install_mock:
            result = self.runner.invoke(app, ["setup", "--target", "claude,cursor", "--dry-run"])

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("z-harness setup", result.output)
        self.assertIn("* claude", result.output)
        self.assertIn("* cursor", result.output)
        self.assertIn("dry run: no changes made", result.output)
        install_mock.assert_not_called()


    def test_prod_setup_default_all_selects_claude_omp_and_codex(self) -> None:
        claude = MagicMock()
        claude.name = "claude"
        claude.fidelity_tier = "native"
        omp = MagicMock()
        omp.name = "omp"
        omp.fidelity_tier = "native"
        codex = MagicMock()
        codex.name = "codex"
        codex.fidelity_tier = "flattened"
        cursor = MagicMock()
        cursor.name = "cursor"
        cursor.fidelity_tier = "flattened"

        with patch.dict(os.environ, {"Z_HARNESS_RELEASE_SURFACE": "prod"}, clear=False), patch(
            "z_harness_cli.adapters.registry.detect_all",
            return_value=[
                (claude, DetectResult(installed=True, version="1.0.0")),
                (cursor, DetectResult(installed=True, version="2.0.0")),
                (omp, DetectResult(installed=False)),
                (codex, DetectResult(installed=True, version="0.42.0")),
            ],
        ), patch("z_harness_cli.commands.setup.shutil.which", return_value=None), patch(
            "z_harness_cli.commands.setup._run_plugin_install"
        ) as install_mock:
            result = self.runner.invoke(app, ["setup", "--dry-run"])

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("selected harnesses: claude, omp, codex", result.output)
        self.assertIn("* claude", result.output)
        self.assertIn("* omp", result.output)
        self.assertIn("* codex", result.output)
        self.assertNotIn("cursor", result.output.lower())
        install_mock.assert_not_called()

    def test_prod_setup_all_install_runs_all_direct_plugin_targets(self) -> None:
        claude = MagicMock()
        claude.name = "claude"
        claude.fidelity_tier = "native"
        omp = MagicMock()
        omp.name = "omp"
        omp.fidelity_tier = "native"
        codex = MagicMock()
        codex.name = "codex"
        codex.fidelity_tier = "flattened"

        with patch.dict(os.environ, {"Z_HARNESS_RELEASE_SURFACE": "prod"}, clear=False), patch(
            "z_harness_cli.adapters.registry.detect_all",
            return_value=[
                (claude, DetectResult(installed=True, version="1.0.0")),
                (omp, DetectResult(installed=True, version="0.1.0")),
                (codex, DetectResult(installed=True, version="0.42.0")),
            ],
        ), patch("z_harness_cli.commands.setup.shutil.which", return_value=None), patch(
            "z_harness_cli.commands.setup._run_plugin_install"
        ) as install_mock:
            result = self.runner.invoke(app, ["setup", "--target", "all", "--install"])

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("selected harnesses: claude, omp, codex", result.output)
        install_mock.assert_called_once_with("all", force=False)

    def test_prod_setup_explicit_non_core_target_is_labeled_advanced(self) -> None:
        cursor = MagicMock()
        cursor.name = "cursor"
        cursor.fidelity_tier = "flattened"

        with patch.dict(os.environ, {"Z_HARNESS_RELEASE_SURFACE": "prod"}, clear=False), patch(
            "z_harness_cli.adapters.registry.detect_all",
            return_value=[(cursor, DetectResult(installed=True, version="2.0.0"))],
        ), patch("z_harness_cli.commands.setup.shutil.which", return_value=None):
            result = self.runner.invoke(app, ["setup", "--target", "cursor", "--dry-run"])

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("* cursor", result.output)
        self.assertIn("dev/advanced", result.output)

    def test_public_help_names_claude_omp_codex_release_defaults(self) -> None:
        result = self.runner.invoke(app, ["setup", "--help"])

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("Release default/all", result.output)
        self.assertIn("claude, omp, codex", result.output)
        self.assertIn("Dev/advanced explicit", result.output)
        self.assertIn("targets: pi, cursor", result.output)

    def test_root_help_presents_claude_omp_release_surface(self) -> None:
        result = self.runner.invoke(app, ["--help"])

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("Claude Code plugin + OMP package/export + Codex plugin", result.output)
        self.assertIn("Claude Code, OMP, and Codex", result.output)
        self.assertIn("release", result.output)
        self.assertIn("surfaces", result.output)

    def test_setup_rejects_unknown_target(self) -> None:
        result = self.runner.invoke(app, ["setup", "--target", "unknown", "--dry-run"])
        self.assertEqual(result.exit_code, 2, result.output)
        self.assertIn("unknown setup target", result.output)


class InstallCommandProdScopeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.runner = CliRunner()

    def test_prod_install_all_passes_all_direct_plugin_targets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for dirname in (".git", "skills", "agents", "runtime"):
                (root / dirname).mkdir()
            script = root / "install.sh"
            script.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            script.chmod(0o755)
            completed = MagicMock(returncode=0)

            with patch.dict(os.environ, {"Z_HARNESS_RELEASE_SURFACE": "prod"}, clear=False), patch(
                "z_harness_cli.commands.install._harness_root",
                return_value=root,
            ), patch(
                "z_harness_cli.commands.install.subprocess.run",
                return_value=completed,
            ) as run_mock:
                result = self.runner.invoke(
                    app,
                    ["install", "--target", "all", "--tarball", "file:///tmp/z-harness.tgz"],
                )

        self.assertEqual(result.exit_code, 0, result.output)
        args = run_mock.call_args[0][0]
        self.assertIn("--target=all", args)
        self.assertNotIn("--target=claude", args)
        self.assertNotIn("--target=codex", args)

    def test_prod_install_accepts_codex_plugin_target(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for dirname in (".git", "skills", "agents", "runtime"):
                (root / dirname).mkdir()
            script = root / "install.sh"
            script.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            script.chmod(0o755)
            completed = MagicMock(returncode=0)

            with patch.dict(os.environ, {"Z_HARNESS_RELEASE_SURFACE": "prod"}, clear=False), patch(
                "z_harness_cli.commands.install._harness_root",
                return_value=root,
            ), patch(
                "z_harness_cli.commands.install.subprocess.run",
                return_value=completed,
            ) as run_mock:
                result = self.runner.invoke(app, ["install", "--target", "codex"])

        self.assertEqual(result.exit_code, 0, result.output)
        args = run_mock.call_args[0][0]
        self.assertIn("--target=codex", args)

    def test_prod_install_codex_does_not_short_circuit_before_script(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {"Z_HARNESS_RELEASE_SURFACE": "prod"}, clear=False), patch(
                "z_harness_cli.commands.install._harness_root",
                return_value=Path(tmp),
            ), patch(
                "z_harness_cli.commands.install.subprocess.run",
            ) as run_mock:
                result = self.runner.invoke(app, ["install", "--target", "codex"])

        self.assertEqual(result.exit_code, 1, result.output)
        self.assertIn("install.sh is missing", result.output)
        run_mock.assert_not_called()

    def test_dev_source_install_all_remains_explicitly_available(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for dirname in (".git", "skills", "agents", "runtime"):
                (root / dirname).mkdir()
            script = root / "install.sh"
            script.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            script.chmod(0o755)
            completed = MagicMock(returncode=0)

            with patch.dict(os.environ, {"Z_HARNESS_RELEASE_SURFACE": "dev"}, clear=False), patch(
                "z_harness_cli.commands.install._harness_root",
                return_value=root,
            ), patch(
                "z_harness_cli.commands.install.subprocess.run",
                return_value=completed,
            ) as run_mock:
                result = self.runner.invoke(app, ["install", "--target", "all"])

        self.assertEqual(result.exit_code, 0, result.output)
        args = run_mock.call_args[0][0]
        self.assertIn("--target=all", args)

    @unittest.skipUnless(
        (_REPO_ROOT / ".git").is_dir(),
        "install.sh is_repo_clone() requires .git to be a directory; in a git worktree "
        ".git is a file, so this test only runs on a normal clone (see LEDGER, T020)",
    )
    def test_install_sh_prod_codex_repo_mode_is_valid(self) -> None:
        with tempfile.TemporaryDirectory() as home, tempfile.TemporaryDirectory() as bin_dir:
            fake_codex = Path(bin_dir) / "codex"
            fake_codex.write_text("#!/bin/sh\nprintf '%s\\n' \"$*\" >> \"$HOME/codex-calls.log\"\n", encoding="utf-8")
            fake_codex.chmod(0o755)
            env = {
                **os.environ,
                "HOME": home,
                "PATH": f"{bin_dir}:{os.environ.get('PATH', '')}",
                "Z_HARNESS_RELEASE_SURFACE": "prod",
            }
            result = subprocess.run(
                ["bash", "install.sh", "--target=codex"],
                cwd=REPO_ROOT,
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )

        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertIn("z-harness installed for Codex", result.stdout)

    @unittest.skipUnless(
        (_REPO_ROOT / ".git").is_dir(),
        "install.sh is_repo_clone() requires .git to be a directory; in a git worktree "
        ".git is a file, so this test only runs on a normal clone (see LEDGER, T020)",
    )
    def test_install_sh_prod_all_repo_mode_installs_claude_and_codex(self) -> None:
        with tempfile.TemporaryDirectory() as home, tempfile.TemporaryDirectory() as bin_dir:
            fake_codex = Path(bin_dir) / "codex"
            fake_codex.write_text("#!/bin/sh\nprintf '%s\\n' \"$*\" >> \"$HOME/codex-calls.log\"\n", encoding="utf-8")
            fake_codex.chmod(0o755)
            env = {
                **os.environ,
                "HOME": home,
                "PATH": f"{bin_dir}:{os.environ.get('PATH', '')}",
                "Z_HARNESS_RELEASE_SURFACE": "prod",
            }
            result = subprocess.run(
                ["bash", "install.sh", "--target=all"],
                cwd=REPO_ROOT,
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )

            claude_link = Path(home) / ".claude" / "plugins" / "z-harness@zeke-tools"
            codex_link = Path(home) / "plugins" / "z-harness"
            claude_installed = claude_link.is_symlink()
            codex_installed = codex_link.is_symlink()

        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertIn("z-harness installed for Claude Code", result.stdout)
        self.assertIn("z-harness installed for Codex", result.stdout)
        self.assertTrue(claude_installed)
        self.assertTrue(codex_installed)


class ProdSurfaceExportFilterTest(unittest.TestCase):
    def test_prod_surface_hides_experimental_skills(self) -> None:
        from runtime.drivers._export_utils import enumerate_sources

        previous = os.environ.get("Z_HARNESS_RELEASE_SURFACE")
        os.environ["Z_HARNESS_RELEASE_SURFACE"] = "prod"
        try:
            sources = enumerate_sources(REPO_ROOT)
        finally:
            if previous is None:
                os.environ.pop("Z_HARNESS_RELEASE_SURFACE", None)
            else:
                os.environ["Z_HARNESS_RELEASE_SURFACE"] = previous

        skill_ids = {entry["id"] for entry in sources["skills"]}
        self.assertIn("z-brainstorm", skill_ids)
        self.assertIn("z-learn", skill_ids)
        self.assertIn("z-sharpen", skill_ids)
        self.assertIn("z-grill", skill_ids)
        self.assertNotIn("z-research", skill_ids)
        self.assertNotIn("z-map", skill_ids)
        self.assertNotIn("z-explore", skill_ids)
        self.assertNotIn("z-overnight", skill_ids)
        self.assertNotIn("z-attend", skill_ids)
        self.assertFalse(any(skill_id.startswith("z-axiom-") for skill_id in skill_ids))

    def test_dev_surface_keeps_experimental_skills(self) -> None:
        from runtime.drivers._export_utils import enumerate_sources

        previous = os.environ.get("Z_HARNESS_RELEASE_SURFACE")
        os.environ["Z_HARNESS_RELEASE_SURFACE"] = "dev"
        try:
            sources = enumerate_sources(REPO_ROOT)
        finally:
            if previous is None:
                os.environ.pop("Z_HARNESS_RELEASE_SURFACE", None)
            else:
                os.environ["Z_HARNESS_RELEASE_SURFACE"] = previous

        skill_ids = {entry["id"] for entry in sources["skills"]}
        self.assertIn("z-research", skill_ids)
        self.assertIn("z-map", skill_ids)
        self.assertIn("z-explore", skill_ids)
        self.assertIn("z-overnight", skill_ids)
        self.assertIn("z-attend", skill_ids)



class ProdSurfaceMcpFilterTest(unittest.TestCase):
    def test_prod_surface_hides_experimental_mcp_tools(self) -> None:
        import z_harness_cli.mcp.server as server

        previous = os.environ.get("Z_HARNESS_RELEASE_SURFACE")
        os.environ["Z_HARNESS_RELEASE_SURFACE"] = "prod"
        try:
            active = server._active_command_tools()
        finally:
            if previous is None:
                os.environ.pop("Z_HARNESS_RELEASE_SURFACE", None)
            else:
                os.environ["Z_HARNESS_RELEASE_SURFACE"] = previous

        self.assertIn("z_brainstorm", active)
        self.assertIn("z_sharpen", active)
        self.assertIn("z_learn", active)
        self.assertIn("z_grill", active)
        self.assertNotIn("z_research", active)
        self.assertNotIn("z_map", active)
        self.assertNotIn("z_explore", active)
        self.assertNotIn("z_overnight", active)
        self.assertNotIn("z_axiom_scan", active)

    def test_packaged_prod_surface_hides_mcp_tools_without_env(self) -> None:
        import z_harness_cli.mcp.server as server

        previous = os.environ.get("Z_HARNESS_RELEASE_SURFACE")
        if previous is not None:
            os.environ.pop("Z_HARNESS_RELEASE_SURFACE")
        try:
            with patch("z_harness_cli.release_surface._module_in_source_checkout", return_value=False):
                active = server._active_command_tools()
        finally:
            if previous is not None:
                os.environ["Z_HARNESS_RELEASE_SURFACE"] = previous

        self.assertIn("z_brainstorm", active)
        self.assertNotIn("z_research", active)
        self.assertNotIn("z_map", active)
        self.assertNotIn("z_explore", active)
        self.assertNotIn("z_overnight", active)
        self.assertNotIn("z_axiom_scan", active)

class UxSmokeScriptExistsTest(unittest.TestCase):
    def test_ux_smoke_script_exists(self) -> None:
        script = REPO_ROOT / "scripts" / "ux-setup-smoke.sh"
        self.assertTrue(script.exists())
        self.assertIn("Z_HARNESS_UX_SMOKE_HOME", script.read_text(encoding="utf-8"))
