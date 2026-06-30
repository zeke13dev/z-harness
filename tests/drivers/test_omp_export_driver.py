"""Regression tests for runtime/drivers/omp/export.py."""

from __future__ import annotations
import importlib

from pathlib import Path
import subprocess
import shutil

import pytest

pi_export = importlib.import_module("runtime.drivers.pi.export")
pi_pkg = importlib.import_module("runtime.drivers.pi")
from runtime.drivers.omp.export import export


def _make_skill(repo_root: Path, skill_id: str = "z-safe") -> None:
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
    stale_skill = package_root / "skills" / "z-safe" / "SKILL.md"
    stale_prompt = package_root / "prompts" / "z-safe.md"
    assert stale_skill.is_file()
    assert stale_prompt.is_file()

    shutil.rmtree(repo_root / "skills" / "z-safe")
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

def test_prod_export_filters_hidden_resources_and_records_gate_claims(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo_root = _make_repo(tmp_path)
    _make_skill(repo_root, "z-research")
    _make_skill(repo_root, "z-explore")
    _make_skill(repo_root, "z-axiom-scan")
    agents_dir = repo_root / "agents"
    agents_dir.mkdir(parents=True)
    (agents_dir / "axiom-extractor.md").write_text("---\nname: axiom-extractor\n---\n\nhidden\n", encoding="utf-8")
    (agents_dir / "safe-agent.md").write_text("---\nname: safe-agent\n---\n\nsafe\n", encoding="utf-8")
    out = tmp_path / "out"

    monkeypatch.setenv("Z_HARNESS_RELEASE_SURFACE", "prod")
    result = export(repo_root, out)

    from z_harness_cli.adapters.omp_parity_gate import omp_export_fidelity

    package_root = out / ".omp" / "z-harness"
    assert (out / ".omp" / "config.yml").read_text(encoding="utf-8") == (
        "# z-harness OMP export discovery guidance.\n"
        "# Point OMP_PLUGIN_ROOT at the sibling .omp/z-harness package root.\n"
        "# Keep project AGENTS.md autoload disabled so OMP does not ingest unrelated root context.\n"
        "skills:\n"
        "  enableAgentsProject: false\n"
    )
    assert (package_root / "manifest.yml").is_file()
    assert f"fidelity: {omp_export_fidelity()}" in (package_root / "manifest.yml").read_text(encoding="utf-8")
    assert result.fidelity == omp_export_fidelity()
    assert (package_root / "skills" / "z-safe" / "SKILL.md").is_file()
    assert (package_root / "agents" / "safe-agent.md").is_file()
    assert not (package_root / "skills" / "z-research").exists()
    assert not (package_root / "skills" / "z-explore").exists()
    assert not (package_root / "skills" / "z-axiom-scan").exists()
    assert not (package_root / "agents" / "axiom-extractor.md").exists()


def test_valid_profile_path_stays_under_omp_profiles(tmp_path: Path) -> None:
    repo_root = _make_repo(tmp_path)
    _make_persona(repo_root, "safe.md", "safe-profile")

    out = tmp_path / "out"
    result = export(repo_root, out)

    expected = out / ".omp" / "z-harness" / "profiles" / "safe-profile.yml"
    assert expected.resolve() in {Path(path).resolve() for path in result.files}
    assert expected.is_file()
    assert expected.resolve().relative_to((out / ".omp" / "z-harness" / "profiles").resolve())


def test_profile_symlink_escape_is_neutralized_by_owned_package_replacement(tmp_path: Path) -> None:
    repo_root = _make_repo(tmp_path)
    _make_persona(repo_root, "safe.md", "safe-profile")
    out = tmp_path / "out"
    profiles_dir = out / ".omp" / "z-harness" / "profiles"
    profiles_dir.parent.mkdir(parents=True)
    outside = tmp_path / "outside-profiles"
    outside.mkdir()
    profiles_dir.symlink_to(outside, target_is_directory=True)

    export(repo_root, out)

    assert not (outside / "safe-profile.yml").exists()
    assert not profiles_dir.is_symlink()
    assert (profiles_dir / "safe-profile.yml").is_file()


def test_profile_path_traversal_name_is_rejected(tmp_path: Path) -> None:
    repo_root = _make_repo(tmp_path)
    _make_persona(repo_root, "escape.md", "../escape")

    out = tmp_path / "out"
    with pytest.raises(RuntimeError, match="invalid profile name"):
        export(repo_root, out)

    assert not (out / ".omp" / "z-harness" / "escape.yml").exists()


def test_duplicate_profile_names_are_rejected(tmp_path: Path) -> None:
    repo_root = _make_repo(tmp_path)
    _make_persona(repo_root, "one.md", "same-profile")
    _make_persona(repo_root, "two.md", "same-profile")

    with pytest.raises(RuntimeError, match="duplicate profile name"):
        export(repo_root, tmp_path / "out")
