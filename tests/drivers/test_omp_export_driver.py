"""Regression tests for runtime/drivers/omp/export.py."""

from __future__ import annotations
import importlib

from pathlib import Path
import subprocess
import shutil

import pytest

pi_export = importlib.import_module("runtime.drivers.pi.export")
pi_pkg = importlib.import_module("runtime.drivers.pi")
from runtime import release_surface
from runtime.drivers.omp.export import export


def _make_skill(repo_root: Path, skill_id: str = "z-plan") -> None:
    skill_dir = repo_root / "skills" / skill_id
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(
        "---\n"
        f"name: {skill_id}\n"
        "description: Test skill\n"
        "---\n\n"
        "Skill body.\n",
        encoding="utf-8",
    )


def _make_persona(repo_root: Path, filename: str, name: str) -> None:
    personas_dir = repo_root / "personas" / "builtin"
    personas_dir.mkdir(parents=True, exist_ok=True)
    (personas_dir / filename).write_text(
        "---\n"
        f"name: {name}\n"
        "description: Test persona\n"
        "---\n\n"
        "Persona body.\n",
        encoding="utf-8",
    )


def _make_repo(tmp_path: Path) -> Path:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    _make_skill(repo_root)
    return repo_root


def _forbid_pi_or_consult_compatibility(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("OMP export must not use pi exporter/helpers or omp-consult compatibility paths")

    for name in (
        "export",
        "_replacement_for_line",
        "_rewrite_body",
        "_render_agent",
        "_render_prompt",
        "_render_agents_index",
    ):
        monkeypatch.setattr(pi_export, name, forbidden)
    monkeypatch.setattr(pi_pkg, "export", forbidden)

    original_read_text = Path.read_text
    original_read_bytes = Path.read_bytes
    original_is_dir = Path.is_dir
    original_exists = Path.exists
    original_copytree = shutil.copytree

    def assert_allowed_path(path: Path) -> None:
        rendered = path.as_posix()
        if "/scripts/pi_assets" in rendered or rendered.endswith("/scripts/omp-consult.sh"):
            raise AssertionError(f"OMP export touched forbidden compatibility path: {rendered}")

    def guarded_read_text(self: Path, *args: object, **kwargs: object) -> str:
        assert_allowed_path(self)
        return original_read_text(self, *args, **kwargs)

    def guarded_read_bytes(self: Path, *args: object, **kwargs: object) -> bytes:
        assert_allowed_path(self)
        return original_read_bytes(self, *args, **kwargs)

    def guarded_is_dir(self: Path) -> bool:
        assert_allowed_path(self)
        return original_is_dir(self)

    def guarded_exists(self: Path) -> bool:
        assert_allowed_path(self)
        return original_exists(self)

    def guarded_copytree(src: object, dst: object, *args: object, **kwargs: object) -> object:
        rendered = str(src)
        if "scripts/pi_assets" in rendered:
            raise AssertionError(f"OMP export copied forbidden pi assets path: {rendered}")
        return original_copytree(src, dst, *args, **kwargs)

    def guarded_subprocess_run(*args: object, **kwargs: object) -> object:
        cmd = args[0] if args else kwargs.get("args")
        rendered = " ".join(str(part) for part in cmd) if isinstance(cmd, (list, tuple)) else str(cmd)
        if "omp-consult.sh" in rendered:
            raise AssertionError(f"OMP export invoked forbidden consult compatibility path: {rendered}")
        raise AssertionError(f"OMP export unexpectedly spawned subprocess: {rendered}")

    monkeypatch.setattr(Path, "read_text", guarded_read_text)
    monkeypatch.setattr(Path, "read_bytes", guarded_read_bytes)
    monkeypatch.setattr(Path, "is_dir", guarded_is_dir)
    monkeypatch.setattr(Path, "exists", guarded_exists)
    monkeypatch.setattr(subprocess, "run", guarded_subprocess_run)
    monkeypatch.setattr(shutil, "copytree", guarded_copytree)


def test_export_does_not_touch_pi_or_consult_compatibility_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo_root = _make_repo(tmp_path)
    _make_persona(repo_root, "safe.md", "safe-profile")
    export_root = tmp_path / "exports"
    pi_sentinel = export_root / "pi" / "keep.txt"
    pi_sentinel.parent.mkdir(parents=True)
    pi_sentinel.write_text("preexisting pi export\n", encoding="utf-8")
    _forbid_pi_or_consult_compatibility(monkeypatch)

    result = export(repo_root, export_root / "omp")

    from z_harness_cli.adapters.omp_parity_gate import omp_export_fidelity
    assert result.fidelity == omp_export_fidelity()
    assert pi_sentinel.read_text(encoding="utf-8") == "preexisting pi export\n"
    assert (export_root / "omp" / ".omp" / "z-harness" / "manifest.yml").is_file()


def test_repeated_export_reconciles_owned_package_without_touching_siblings(tmp_path: Path) -> None:
    repo_root = _make_repo(tmp_path)
    export_root = tmp_path / "exports" / "omp"
    package_root = export_root / ".omp" / "z-harness"
    omp_sibling = export_root / ".omp" / "user-owned.yml"

    export(repo_root, export_root)
    stale_skill = package_root / "skills" / "z-plan" / "SKILL.md"
    stale_prompt = package_root / "prompts" / "z-plan.md"
    assert stale_skill.is_file()
    assert stale_prompt.is_file()

    shutil.rmtree(repo_root / "skills" / "z-plan")
    _make_skill(repo_root, "z-new")
    omp_sibling.write_text("user-owned omp sibling\n", encoding="utf-8")

    export(repo_root, export_root)

    assert not stale_skill.exists()
    assert not stale_prompt.exists()
    assert (package_root / "skills" / "z-new" / "SKILL.md").is_file()
    assert (package_root / "prompts" / "z-new.md").is_file()
    assert omp_sibling.read_text(encoding="utf-8") == "user-owned omp sibling\n"
    config_text = (export_root / ".omp" / "config.yml").read_text(encoding="utf-8")
    assert "enableAgentsProject: false" in config_text

def test_prod_export_rejects_extra_hidden_resources_before_emission(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo_root = _make_repo(tmp_path)
    _make_skill(repo_root, "z-research")
    _make_skill(repo_root, "z-explore")
    _make_skill(repo_root, "z-axiom-scan")
    agents_dir = repo_root / "agents"
    agents_dir.mkdir(parents=True)
    (agents_dir / "axiom-extractor.md").write_text("---\nname: axiom-extractor\n---\n\nhidden\n", encoding="utf-8")
    (agents_dir / "implementer.md").write_text("---\nname: implementer\n---\n\nimplement\n", encoding="utf-8")
    out = tmp_path / "out"

    monkeypatch.setenv("Z_HARNESS_RELEASE_SURFACE", "prod")
    with pytest.raises(ValueError, match="agents/axiom-extractor.md"):
        export(repo_root, out)

    assert not (out / ".omp" / "z-harness" / "manifest.yml").exists()


def test_prod_export_consumes_the_canonical_skill_agent_graph(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo_root = _make_repo(tmp_path)
    agents_dir = repo_root / "agents"
    agents_dir.mkdir()
    (agents_dir / "implementer.md").write_text(
        "---\nname: implementer\ndescription: Implement\n---\n\nDo the task.\n",
        encoding="utf-8",
    )
    _make_skill(repo_root, "z-research")
    (agents_dir / "axiom-extractor.md").write_text(
        "---\nname: axiom-extractor\n---\n\ndev only\n",
        encoding="utf-8",
    )
    (repo_root / ".git").mkdir()
    contract = {
        "prod_inventory": {
            "skills": ["z-plan"],
            "agents": ["implementer"],
            "mcp_tools": [],
            "export_targets": ["omp"],
            "scripts_backends": [],
            "schemas": [],
            "public_documents": [],
            "generated_requirements": [],
        }
    }
    monkeypatch.setattr(release_surface, "release_contract", lambda: contract)
    monkeypatch.setattr(release_surface, "reviewed_dynamic_dependencies", lambda: ())
    monkeypatch.setenv("Z_HARNESS_RELEASE_SURFACE", "prod")

    result = export(repo_root, tmp_path / "out")

    package_root = result.dest
    assert {path.parent.name for path in (package_root / "skills").glob("*/SKILL.md")} == {
        "z-plan"
    }
    assert {path.stem for path in (package_root / "agents").glob("*.md")} == {
        "implementer"
    }
