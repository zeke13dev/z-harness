from __future__ import annotations

import re
from pathlib import Path

from z_harness_cli import release_surface

REPO_ROOT = Path(__file__).resolve().parent.parent


def _active_docs_and_wrappers() -> list[Path]:
    paths = [
        REPO_ROOT / "AGENTS.md",
        REPO_ROOT / "README.md",
        REPO_ROOT / "Makefile",
        REPO_ROOT / "skills" / "z-export" / "SKILL.md",
    ]
    paths.extend((REPO_ROOT / "docs" / "human").glob("*.md"))
    paths.extend((REPO_ROOT / "scripts" / "pi_assets").rglob("*.md"))
    return sorted(paths)


def test_active_docs_do_not_point_at_removed_command_source_tier() -> None:
    forbidden = [
        re.compile(r"commands/(?:z-[A-Za-z0-9-]+|_fragments)[^`\s)]*\.md"),
        re.compile(r"commands/\*\.md"),
        re.compile(r"commands/ frontmatter", re.IGNORECASE),
        re.compile(r"skills/ dir(?:ectory)? (?:was )?removed|only commands/|only crawls commands/", re.IGNORECASE),
    ]

    violations: list[str] = []
    for path in _active_docs_and_wrappers():
        text = path.read_text(encoding="utf-8")
        for pattern in forbidden:
            if pattern.search(text):
                violations.append(f"{path.relative_to(REPO_ROOT)}: {pattern.pattern}")

    assert not violations


def test_generated_export_mirrors_are_documented_as_scratch_not_release_source() -> None:
    forbidden = [
        re.compile(r"LEGACY-ALLOWLIST|REMOVE-AT: v<next-minor>"),
        re.compile(r"--commands-dir commands"),
        re.compile(r"committed `exports/|--out exports/|Path\('exports"),
    ]

    violations: list[str] = []
    for path in _active_docs_and_wrappers() + [REPO_ROOT / "scripts" / "audit-tarball.sh"]:
        text = path.read_text(encoding="utf-8")
        for pattern in forbidden:
            if pattern.search(text):
                violations.append(f"{path.relative_to(REPO_ROOT)}: {pattern.pattern}")

    gitignore = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "/exports/" in gitignore
    assert "/temp/exports/" in gitignore
    assert "/.pi/" in gitignore
    assert "/.omp/z-harness/" in gitignore
    assert release_surface.path_excluded_from_prod("exports/pi/prompts/z-plan.md")
    assert release_surface.path_excluded_from_prod(".pi/agents/doc-updater.md")
    assert release_surface.path_excluded_from_prod("temp/exports/omp/.omp/z-harness/manifest.yml")
    assert not violations


def test_z_do_wrapper_is_deleted() -> None:
    # /z-do was a deprecated pass-through wrapper; it is now fully removed.
    assert not (REPO_ROOT / "skills" / "z-do" / "SKILL.md").exists()
