from __future__ import annotations

import os
import importlib.util
import subprocess
import tarfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from runtime.drivers._export_utils import ExportResult, enumerate_sources
from z_harness_cli import release_surface
from z_harness_cli.__main__ import app
from z_harness_cli.mcp import server as mcp_server


class _FakeAdapter:
    name = "codex"

    def export_payload(self, dest: Path) -> ExportResult:
        marker = dest / "surface.txt"
        marker.write_text(os.environ.get("Z_HARNESS_RELEASE_SURFACE", "missing"), encoding="utf-8")
        return ExportResult(dest=dest, files=[marker], fidelity="flattened")


def _write_skill(root: Path, skill_id: str) -> None:
    skill_dir = root / "skills" / skill_id
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(f"---\nname: {skill_id}\n---\nbody\n", encoding="utf-8")


_HIDDEN_SURFACE_ONLY_PATHS = (
    "scripts/axiom-extract.py",
    "scripts/axiom-store.py",
    "scripts/overnight-preflight.sh",
    "personas/builtin/overnight-intern.md",
    "docs/human/attend.md",
    "docs/human/axioms.md",
    "docs/human/overnight-run.md",
    "docs/human/hermes-orchestration.md",
    "docs/human/hermes-integration-v1.md",
    "docs/human/review-hermes-implementation.md",
    "docs/human/review-hermes-integration.md",
    "docs/llm/attend.json",
    "docs/llm/axioms.json",
    "docs/llm/overnight-run.json",
    "docs/llm/hermes-orchestration.json",
    "docs/schemas/axiom.schema.json",
    "exports/pi/prompts/z-plan.md",
    ".pi/agents/doc-updater.md",
    ".omp/z-harness/manifest.yml",
    "temp/exports/omp/.omp/z-harness/manifest.yml",
)


_HIDDEN_SURFACE_PATTERN_EXAMPLES = (
    "docs/human/hermes-new-surface.md",
    "docs/human/review-hermes-new-surface.md",
    "docs/llm/axiom-new-surface.json",
    "docs/schemas/axiom-v2.schema.json",
)


_PROD_APPROVED_DOC_SCHEMA_PATHS = (
    "docs/human/INSTALL.md",
    "docs/human/z-update.md",
    "docs/llm/z-update.json",
    "docs/schemas/handoff.schema.json",
)

def test_manifest_classifies_disputed_commands_and_agents() -> None:
    assert not release_surface.is_prod_visible("skills", "z-explore", "prod")
    assert not release_surface.is_prod_visible("skills", "z-axiom-scan", "prod")
    assert not release_surface.is_prod_visible("mcp_tools", "z_explore", "prod")
    assert not release_surface.is_prod_visible("agents", "research-judge", "prod")
    assert release_surface.is_prod_visible("skills", "z-plan", "prod")
    assert release_surface.is_prod_visible("mcp_tools", "z_plan", "prod")



def test_public_release_default_helpers_include_codex() -> None:
    assert release_surface.public_release_hosts() == ("claude", "omp", "codex")
    assert release_surface.setup_target_ids("prod") == ("claude", "omp", "codex")
    assert set(release_surface.explicit_setup_target_ids()) == {"claude", "omp", "pi", "cursor", "codex"}
    assert release_surface.plugin_install_target_ids("prod") == {"claude", "codex"}
    assert release_surface.plugin_install_target_ids("dev") == {"claude", "codex"}

def test_mcp_prod_tools_are_manifest_filtered(monkeypatch) -> None:
    monkeypatch.setenv("Z_HARNESS_RELEASE_SURFACE", "prod")
    tools = set(mcp_server._active_command_tools())
    assert "z_plan" in tools
    assert "z_export" in tools
    assert tools.isdisjoint(release_surface.dev_only_mcp_tool_names())


def test_runtime_enumeration_uses_manifest_for_prod_surface(tmp_path: Path, monkeypatch) -> None:
    _write_skill(tmp_path, "z-plan")
    _write_skill(tmp_path, "z-explore")
    _write_skill(tmp_path, "z-axiom-scan")
    agents = tmp_path / "agents"
    agents.mkdir()
    (agents / "implementer.md").write_text("prod agent\n", encoding="utf-8")
    (agents / "research-judge.md").write_text("dev agent\n", encoding="utf-8")

    monkeypatch.setenv("Z_HARNESS_RELEASE_SURFACE", "prod")
    sources = enumerate_sources(tmp_path)

    assert {entry["id"] for entry in sources["skills"]} == {"z-plan"}
    assert {entry["id"] for entry in sources["agents"]} == {"implementer"}


def test_installed_default_export_surface_is_prod_and_dev_override_remains(tmp_path: Path, monkeypatch) -> None:
    runner = CliRunner()
    project_dir = tmp_path / "project"
    project_dir.mkdir()

    with patch("z_harness_cli.release_surface._module_in_source_checkout", return_value=False), patch(
        "z_harness_cli.commands.export._repo_root", return_value=project_dir
    ), patch(
        "z_harness_cli.adapters.registry.select", return_value=(_FakeAdapter(), MagicMock(installed=True))
    ):
        prod_out = project_dir / "prod-export"
        result = runner.invoke(app, ["export", "--host", "codex", "--out", str(prod_out), "--force"])
        assert result.exit_code == 0, result.output
        assert (prod_out / "surface.txt").read_text(encoding="utf-8") == "prod"

        dev_out = project_dir / "dev-export"
        result = runner.invoke(
            app,
            ["export", "--host", "codex", "--surface", "dev", "--out", str(dev_out), "--force"],
        )
        assert result.exit_code == 0, result.output
        assert (dev_out / "surface.txt").read_text(encoding="utf-8") == "dev"


def test_prod_artifact_audit_rejects_manifest_excluded_local_paths() -> None:
    listing = [
        "./skills/z-plan/SKILL.md",
        "./scripts/hermes/so_mcp.py",
        "./scripts/notify-discord.sh",
        "./exports/pi/prompts/z-plan.md",
    ]
    assert release_surface.first_prod_artifact_violation(listing) == "scripts/hermes/so_mcp.py"
    assert release_surface.path_excluded_from_prod("scripts/notify-discord.sh")
    assert release_surface.path_excluded_from_prod("exports/pi/prompts/z-plan.md")
    assert release_surface.path_excluded_from_prod("hermes-so-watchdog/handoff.json")
    for path in _HIDDEN_SURFACE_ONLY_PATHS:
        assert release_surface.path_excluded_from_prod(path), path
        assert release_surface.first_prod_artifact_violation([f"./{path}"]) == path
    for path in _HIDDEN_SURFACE_PATTERN_EXAMPLES:
        assert release_surface.path_excluded_from_prod(path), path
        assert release_surface.first_prod_artifact_violation([f"./{path}"]) == path
    for path in _PROD_APPROVED_DOC_SCHEMA_PATHS:
        assert not release_surface.path_excluded_from_prod(path), path
        assert release_surface.first_prod_artifact_violation([f"./{path}"]) is None


def test_prod_manifest_exclusions_cover_tar_audit_and_stage_patterns() -> None:
    tar_args = set(release_surface.tar_exclude_args("prod"))
    for pattern in release_surface.prod_excluded_paths():
        assert f"--exclude=./{pattern.removeprefix('./').rstrip('/')}" in tar_args

    assert release_surface.path_excluded_from_prod("scripts/__pycache__/axiom-store.cpython-311.pyc")
    assert release_surface.path_excluded_from_prod("scripts/__pycache__/hermes-execute.cpython-311.pyc")
    assert "--exclude=./*/__pycache__" in tar_args


def test_prod_tarball_audit_requires_codex_manifest(tmp_path: Path) -> None:
    payload = tmp_path / "payload"
    (payload / "skills" / "z-plan").mkdir(parents=True)
    (payload / "skills" / "z-plan" / "SKILL.md").write_text("name: z-plan\n", encoding="utf-8")
    tarball = tmp_path / "payload.tar.gz"
    with tarfile.open(tarball, "w:gz") as archive:
        archive.add(payload / "skills", arcname="skills")

    result = subprocess.run(
        ["bash", str(Path(__file__).parent.parent / "scripts" / "audit-tarball.sh"), str(tarball)],
        env={**os.environ, "Z_HARNESS_RELEASE_SURFACE": "prod"},
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 1
    assert ".codex-plugin/plugin.json" in result.stdout


def test_stage_release_surface_prunes_without_deleting_source(tmp_path: Path) -> None:
    spec = importlib.util.spec_from_file_location("stage_release_surface", Path(__file__).parent.parent / "scripts" / "stage-release-surface.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    stage_release_surface = module.stage_release_surface

    repo = tmp_path / "repo"
    stage = tmp_path / "stage"
    _write_skill(repo, "z-plan")
    _write_skill(repo, "z-explore")
    hermes = repo / "scripts" / "hermes"
    hermes.mkdir(parents=True)
    (hermes / "so_mcp.py").write_text("dev\n", encoding="utf-8")
    for hidden_path in _HIDDEN_SURFACE_ONLY_PATHS:
        target = repo / hidden_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("hidden\n", encoding="utf-8")
    pycache = repo / "scripts" / "__pycache__"
    pycache.mkdir(parents=True)
    (pycache / "axiom-store.cpython-311.pyc").write_bytes(b"cache")
    (pycache / "hermes-execute.cpython-311.pyc").write_bytes(b"cache")
    (repo / "README.md").write_text("readme\n", encoding="utf-8")
    for approved_path in _PROD_APPROVED_DOC_SCHEMA_PATHS:
        target = repo / approved_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("prod\n", encoding="utf-8")

    stage_release_surface(repo, stage)

    assert (repo / "skills" / "z-explore" / "SKILL.md").exists()
    assert (stage / "skills" / "z-plan" / "SKILL.md").exists()
    assert not (stage / "skills" / "z-explore").exists()
    assert not (stage / "scripts" / "hermes").exists()
    assert not (stage / "scripts" / "__pycache__").exists()
    for hidden_path in _HIDDEN_SURFACE_ONLY_PATHS:
        assert (repo / hidden_path).exists(), hidden_path
        assert not (stage / hidden_path).exists(), hidden_path
    for approved_path in _PROD_APPROVED_DOC_SCHEMA_PATHS:
        assert (stage / approved_path).exists(), approved_path
