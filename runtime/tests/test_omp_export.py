from __future__ import annotations

import hashlib
from pathlib import Path
from contextlib import ExitStack
from unittest.mock import patch

import pytest

from runtime.drivers.omp.export import export


def _write_minimal_harness(root: Path, *, persona_name: str = "quiet") -> None:
    skill = root / "skills" / "z-plan" / "SKILL.md"
    skill.parent.mkdir(parents=True, exist_ok=True)
    skill.write_text(
        "---\nname: z-plan\ndescription: Plan things.\n---\nSkill body.\n",
        encoding="utf-8",
    )

    agent = root / "agents" / "implementer.md"
    agent.parent.mkdir(parents=True, exist_ok=True)
    agent.write_text(
        "---\nname: implementer\ndescription: Implement things.\n---\nAgent body.\n",
        encoding="utf-8",
    )

    persona = root / "personas" / "builtin" / f"{persona_name}.md"
    persona.parent.mkdir(parents=True, exist_ok=True)
    persona.write_text(
        f"---\nname: {persona_name}\ndescription: Quiet profile.\n---\nProfile body.\n",
        encoding="utf-8",
    )


def _digest_tree(root: Path) -> dict[str, str]:
    if not root.exists():
        return {}
    result: dict[str, str] = {}
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        rel = path.relative_to(root).as_posix()
        result[rel] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def test_omp_export_writes_native_package_layout(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    dest = tmp_path / "out"
    _write_minimal_harness(repo)

    result = export(repo, dest)
    package = dest / ".omp" / "z-harness"

    from z_harness_cli.adapters.omp_parity_gate import omp_export_fidelity
    assert result.dest == package.resolve()
    assert result.fidelity == omp_export_fidelity()
    assert result.warnings == []
    assert (package / "manifest.yml").is_file()
    assert (package / "skills" / "z-plan" / "SKILL.md").read_text(encoding="utf-8").startswith("---\nname: z-plan")
    assert (package / "rules" / "z-plan.md").is_file()
    assert (package / "prompts" / "z-plan.md").is_file()
    assert (package / "agents" / "implementer.md").is_file()
    assert (package / "profiles" / "quiet.yml").is_file()
    assert "enableAgentsProject: false" in (dest / ".omp" / "config.yml").read_text(encoding="utf-8")
    assert "OMP_PLUGIN_ROOT" in (dest / ".omp" / "config.yml").read_text(encoding="utf-8")


def test_omp_export_preserves_profile_source_collision_check(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _write_minimal_harness(repo, persona_name="z-plan")

    with pytest.raises(RuntimeError, match="collision.*z-plan"):
        export(repo, tmp_path / "out")


def test_omp_export_does_not_invoke_pi_prompt_or_line_rewrite_helpers(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _write_minimal_harness(repo)

    import importlib

    pi_export = importlib.import_module("runtime.drivers.pi.export")

    with ExitStack() as stack:
        for name in ("_replacement_for_line", "_render_prompt", "_render_agent"):
            stack.enter_context(patch.object(pi_export, name, side_effect=AssertionError("pi helper used")))
        result = export(repo, tmp_path / "out")

    from z_harness_cli.adapters.omp_parity_gate import omp_export_fidelity
    assert result.fidelity == omp_export_fidelity()


def test_omp_export_does_not_mutate_exports_pi(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _write_minimal_harness(repo)
    pi_tree = repo / "exports" / "pi"
    pi_tree.mkdir(parents=True)
    sentinel = pi_tree / "sentinel.txt"
    sentinel.write_text("legacy pi export stays untouched\n", encoding="utf-8")
    before = _digest_tree(pi_tree)

    export(repo, repo / "exports" / "omp")

    assert _digest_tree(pi_tree) == before
    assert sentinel.read_text(encoding="utf-8") == "legacy pi export stays untouched\n"


def test_omp_export_fidelity_matches_parity_gate(tmp_path: Path) -> None:
    """Export fidelity is driven by the parity gate, not a hardcoded constant.

    With all T008 evidence present the gate returns 'native'. Removing any T008
    class from PARITY_EVIDENCE would drop this to 'partial'. The runtime exporter
    must use the gate value; it must not hardcode 'partial' or 'native'.
    """
    from z_harness_cli.adapters.omp_parity_gate import omp_export_fidelity
    repo = tmp_path / "repo"
    _write_minimal_harness(repo)

    result = export(repo, tmp_path / "out")

    assert result.fidelity == omp_export_fidelity()
