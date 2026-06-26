"""Focused tests for runtime/drivers/codex/export.py."""

from __future__ import annotations

from pathlib import Path

from runtime.drivers.codex.export import export

_SURFACE_MARKER = "<!-- include: _fragments/surface-mapping.md -->"
_SURFACE_SENTINEL = "Shared surface mapping contract"


def _make_repo_with_included_skill(tmp_path: Path, skill_name: str) -> Path:
    repo_root = tmp_path / "repo"
    skill_dir = repo_root / "skills" / skill_name
    fragment_dir = repo_root / "_fragments"
    skill_dir.mkdir(parents=True)
    fragment_dir.mkdir(parents=True)

    (fragment_dir / "surface-mapping.md").write_text(
        "## Shared surface mapping contract\n\nRepo Explore facets\n",
        encoding="utf-8",
    )
    (skill_dir / "SKILL.md").write_text(
        "---\n"
        f"name: {skill_name}\n"
        'description: "Explain code"\n'
        "runtime: c1\n"
        "---\n"
        "\n"
        "Before fragment.\n"
        f"{_SURFACE_MARKER}\n"
        "After fragment.\n",
        encoding="utf-8",
    )
    return repo_root


def test_codex_native_skill_export_expands_z_explain_surface_fragment(tmp_path: Path) -> None:
    repo_root = _make_repo_with_included_skill(tmp_path, "z-explain")
    export_root = tmp_path / "export"

    export(repo_root, export_root)

    exported = export_root / "skills" / "z-explain" / "SKILL.md"
    text = exported.read_text(encoding="utf-8")
    assert text.startswith("---\nname: z-explain\n")
    assert _SURFACE_SENTINEL in text
    assert _SURFACE_MARKER not in text


def test_codex_native_skill_export_expands_z_learn_surface_fragment(tmp_path: Path) -> None:
    repo_root = _make_repo_with_included_skill(tmp_path, "z-learn")
    export_root = tmp_path / "export"

    export(repo_root, export_root)

    exported = export_root / "skills" / "z-learn" / "SKILL.md"
    text = exported.read_text(encoding="utf-8")
    assert text.startswith("---\nname: z-learn\n")
    assert _SURFACE_SENTINEL in text
    assert _SURFACE_MARKER not in text
