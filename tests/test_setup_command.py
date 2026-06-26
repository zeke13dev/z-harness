from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
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

    def test_setup_rejects_unknown_target(self) -> None:
        result = self.runner.invoke(app, ["setup", "--target", "unknown", "--dry-run"])
        self.assertEqual(result.exit_code, 2, result.output)
        self.assertIn("unknown setup target", result.output)


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
        self.assertNotIn("z_overnight", active)
        self.assertNotIn("z_axiom_scan", active)

    def test_packaged_prod_surface_hides_mcp_tools_without_env(self) -> None:
        import z_harness_cli.mcp.server as server

        previous = os.environ.get("Z_HARNESS_RELEASE_SURFACE")
        if previous is not None:
            os.environ.pop("Z_HARNESS_RELEASE_SURFACE")
        try:
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                for skill_id in ("z-plan", "z-brainstorm", "z-learn"):
                    skill_dir = root / "skills" / skill_id
                    skill_dir.mkdir(parents=True)
                    (skill_dir / "SKILL.md").write_text("---\nname: test\n---\n", encoding="utf-8")
                with patch.object(server, "_candidate_repo_roots", return_value=[root]):
                    active = server._active_command_tools()
        finally:
            if previous is not None:
                os.environ["Z_HARNESS_RELEASE_SURFACE"] = previous

        self.assertIn("z_brainstorm", active)
        self.assertNotIn("z_research", active)
        self.assertNotIn("z_map", active)
        self.assertNotIn("z_overnight", active)
        self.assertNotIn("z_axiom_scan", active)

class UxSmokeScriptExistsTest(unittest.TestCase):
    def test_ux_smoke_script_exists(self) -> None:
        script = REPO_ROOT / "scripts" / "ux-setup-smoke.sh"
        self.assertTrue(script.exists())
        self.assertIn("Z_HARNESS_UX_SMOKE_HOME", script.read_text(encoding="utf-8"))
