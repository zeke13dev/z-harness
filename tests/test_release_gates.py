from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from z_harness_cli import mcp_prod_tool_list_smoke as mcp_smoke

REPO_ROOT = Path(__file__).parent.parent.resolve()
OMP_SMOKE_PATH = REPO_ROOT / "scripts" / "omp-prod-export-smoke.py"


def _load_smoke_module():
    spec = importlib.util.spec_from_file_location("omp_prod_export_smoke", OMP_SMOKE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_minimal_valid_export(root: Path) -> Path:
    from z_harness_cli.adapters.omp_parity_gate import omp_export_fidelity

    package_root = root / ".omp" / "z-harness"
    package_root.mkdir(parents=True)
    (root / ".omp" / "config.yml").write_text(
        "skills:\n  enableAgentsProject: false\n",
        encoding="utf-8",
    )
    (package_root / "manifest.yml").write_text(
        "name: z-harness\nhost: omp\n"
        f"fidelity: {omp_export_fidelity()}\n",
        encoding="utf-8",
    )
    return package_root


def test_omp_smoke_accepts_minimal_valid_prod_export(tmp_path: Path) -> None:
    smoke = _load_smoke_module()
    _write_minimal_valid_export(tmp_path)

    smoke.validate_omp_export(tmp_path)


def test_omp_smoke_rejects_missing_manifest(tmp_path: Path) -> None:
    smoke = _load_smoke_module()
    package_root = _write_minimal_valid_export(tmp_path)
    (package_root / "manifest.yml").unlink()

    with pytest.raises(AssertionError, match="missing OMP manifest"):
        smoke.validate_omp_export(tmp_path)


def test_omp_smoke_rejects_config_suppression_mutation(tmp_path: Path) -> None:
    smoke = _load_smoke_module()
    _write_minimal_valid_export(tmp_path)
    (tmp_path / ".omp" / "config.yml").write_text(
        "skills:\n  enableAgentsProject: true\n",
        encoding="utf-8",
    )

    with pytest.raises(AssertionError, match="enableAgentsProject"):
        smoke.validate_omp_export(tmp_path)


def test_omp_smoke_rejects_hidden_skill_axiom_and_agent_resources(tmp_path: Path) -> None:
    smoke = _load_smoke_module()
    package_root = _write_minimal_valid_export(tmp_path)
    hidden_skill = package_root / "skills" / "z-explore" / "SKILL.md"
    hidden_skill.parent.mkdir(parents=True)
    hidden_skill.write_text("hidden\n", encoding="utf-8")

    with pytest.raises(AssertionError, match="prod-hidden OMP skill resource leaked"):
        smoke.validate_omp_export(tmp_path)

    hidden_skill.unlink()
    hidden_skill.parent.rmdir()
    hidden_axiom_prompt = package_root / "prompts" / "z-axiom-scan.md"
    hidden_axiom_prompt.parent.mkdir(parents=True, exist_ok=True)
    hidden_axiom_prompt.write_text("hidden\n", encoding="utf-8")

    with pytest.raises(AssertionError, match="prod-hidden OMP axiom resource leaked"):
        smoke.validate_omp_export(tmp_path)

    hidden_axiom_prompt.unlink()
    hidden_agent = package_root / "agents" / "axiom-extractor.md"
    hidden_agent.parent.mkdir(parents=True)
    hidden_agent.write_text("hidden\n", encoding="utf-8")

    with pytest.raises(AssertionError, match="prod-hidden OMP agent leaked"):
        smoke.validate_omp_export(tmp_path)


def test_omp_smoke_rejects_parity_fidelity_mismatch(tmp_path: Path) -> None:
    smoke = _load_smoke_module()
    package_root = _write_minimal_valid_export(tmp_path)
    (package_root / "manifest.yml").write_text(
        "name: z-harness\nhost: omp\nfidelity: partial\n",
        encoding="utf-8",
    )

    from z_harness_cli.adapters.omp_parity_gate import omp_export_fidelity

    if omp_export_fidelity() == "partial":
        pytest.skip("gate currently resolves to partial; mismatch fixture would be valid")
    with pytest.raises(AssertionError, match="parity gate"):
        smoke.validate_omp_export(tmp_path)


def test_mcp_prod_smoke_rejects_repo_root_import_source(tmp_path: Path) -> None:
    smoke = mcp_smoke
    repo_root = tmp_path / "checkout"
    repo_root.mkdir()
    module_file = repo_root / "z_harness_cli" / "__init__.py"
    module_file.parent.mkdir()
    module_file.write_text("", encoding="utf-8")
    venv_prefix = tmp_path / "venv"
    venv_prefix.mkdir()

    with pytest.raises(AssertionError, match="checkout instead of installed wheel"):
        smoke.assert_installed_import_source(module_file, repo_root, venv_prefix)


def test_mcp_prod_smoke_accepts_venv_site_package_import(tmp_path: Path) -> None:
    smoke = mcp_smoke
    repo_root = tmp_path / "checkout"
    repo_root.mkdir()
    venv_prefix = tmp_path / "venv"
    module_file = (
        venv_prefix / "lib" / "python3.11" / "site-packages" / "z_harness_cli" / "__init__.py"
    )
    module_file.parent.mkdir(parents=True)
    module_file.write_text("", encoding="utf-8")

    smoke.assert_installed_import_source(module_file, repo_root, venv_prefix)


def test_mcp_prod_smoke_rejects_repo_root_cwd(tmp_path: Path) -> None:
    smoke = mcp_smoke
    repo_root = tmp_path / "checkout"
    nested_cwd = repo_root / "subdir"
    nested_cwd.mkdir(parents=True)

    with pytest.raises(AssertionError, match="must run outside the checkout"):
        smoke.assert_non_repo_cwd(repo_root, nested_cwd)


def test_release_workflow_runs_full_gate_set_before_publication() -> None:
    workflow = (REPO_ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    release_index = workflow.index("Create GitHub Release")
    before_release = workflow[:release_index]

    required_tokens = [
        "make release-verify",
        "scripts/stage-release-surface.py --repo-root \"$GITHUB_WORKSPACE\" --out /tmp/z-harness-release-stage --keep-git",
        "working-directory: /tmp/z-harness-release-stage",
        "python3 -m venv /tmp/z-harness-wheel-smoke",
        "scripts/omp-prod-export-smoke.py",
        "Z_HARNESS_RELEASE_SURFACE=prod /tmp/z-harness-wheel-smoke/bin/python",
        "bash scripts/audit-tarball.sh",
        "-m z_harness_cli.mcp_prod_tool_list_smoke",
        "--repo-root \"$GITHUB_WORKSPACE\"",
    ]
    for token in required_tokens:
        assert token in before_release

    assert "from z_harness_cli.mcp.server import" not in before_release
    assert "action-gh-release" in workflow[release_index:]


def test_make_release_verify_and_dry_run_include_required_gates() -> None:
    makefile = (REPO_ROOT / "Makefile").read_text(encoding="utf-8")
    dry_run = (REPO_ROOT / "scripts" / "release-dry-run.sh").read_text(encoding="utf-8")

    assert "release-verify: test test-sh" in makefile
    assert "tests/test_install_sh_integrity.py" in makefile
    assert "bash scripts/release-dry-run.sh" in makefile
    assert "stage-release-surface.py --repo-root \"$REPO_ROOT\" --out \"$STAGE_DIR\" --keep-git" in dry_run
    assert "building staged prod wheel" in dry_run
    assert "cd \"$STAGE_DIR\"" in dry_run
    assert "scripts/audit-tarball.sh" in dry_run
    assert "scripts/omp-prod-export-smoke.py" in dry_run
    assert "running MCP prod tool-list smoke" in dry_run
    assert "-m z_harness_cli.mcp_prod_tool_list_smoke" in dry_run
    assert "--repo-root \"$REPO_ROOT\"" in dry_run
    assert "cd \"$WORK_DIR\"" in dry_run
    assert "from z_harness_cli.mcp.server import" not in dry_run
    assert "python\" - <<'PY'" not in dry_run
    assert "degraded Codex export-only smoke" in dry_run
    smoke = (REPO_ROOT / "scripts" / "omp-prod-export-smoke.py").read_text(encoding="utf-8")
    assert "z-explore" in smoke
    assert "z-axiom-scan.md" in smoke
