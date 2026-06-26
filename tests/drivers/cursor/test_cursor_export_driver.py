"""
tests/drivers/cursor/test_cursor_export_driver.py

Unit tests for runtime/drivers/cursor/export.py.

Covers:
  - Skills are written as .cursor/skills/<id>/SKILL.md (not .mdc in rules/)
  - Skills SKILL.md files have frontmatter fences (--- ... ---)
  - Agents are still written as .cursor/rules/<id>.mdc (unchanged)
  - Exactly one generated .mdc with alwaysApply: true is written per export run
  - The single index .mdc is at .cursor/rules/z-harness-skills.mdc
  - No .mdc files appear under .cursor/rules/ for skills (only the index)
  - Skills source text is preserved verbatim (no Agent/Skill call rewriting)

No network calls; all I/O uses tmp_path fixtures.

Run:
    pytest tests/drivers/cursor/test_cursor_export_driver.py -v
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from runtime.drivers.cursor.export import export, _SKILLS_INDEX_NAME


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

def _make_skill(skills_dir: Path, skill_id: str, body: str = "") -> Path:
    """Create a minimal skills/<id>/SKILL.md under skills_dir."""
    skill_dir = skills_dir / skill_id
    skill_dir.mkdir(parents=True, exist_ok=True)
    skill_file = skill_dir / "SKILL.md"
    if not body:
        body = f"Some {skill_id} body content.\n"
    content = (
        f"---\n"
        f"name: {skill_id}\n"
        f"disable-model-invocation: true\n"
        f'description: "Test skill {skill_id}"\n'
        f"runtime: c1\n"
        f"---\n"
        f"\n"
        + body
    )
    skill_file.write_text(content, encoding="utf-8")
    return skill_file


def _make_agent(agents_dir: Path, agent_id: str) -> Path:
    """Create a minimal agents/<id>.md under agents_dir."""
    agents_dir.mkdir(parents=True, exist_ok=True)
    agent_file = agents_dir / f"{agent_id}.md"
    content = (
        f"---\n"
        f"name: {agent_id}\n"
        f'description: "Test agent {agent_id}"\n'
        f"---\n"
        f"\n"
        f"Agent body for {agent_id}.\n"
    )
    agent_file.write_text(content, encoding="utf-8")
    return agent_file


def _make_repo(tmp_path: Path, skill_ids: list[str], agent_ids: list[str]) -> Path:
    """Create a minimal repo fixture with skills and agents."""
    repo_root = tmp_path / "repo"
    repo_root.mkdir()

    skills_dir = repo_root / "skills"
    for sid in skill_ids:
        _make_skill(skills_dir, sid)

    agents_dir = repo_root / "agents"
    for aid in agent_ids:
        _make_agent(agents_dir, aid)

    return repo_root


# ---------------------------------------------------------------------------
# Core layout: skills go to .cursor/skills/<id>/SKILL.md
# ---------------------------------------------------------------------------


class TestSkillLayout:
    """Skills are exported as .cursor/skills/<id>/SKILL.md, not as .mdc."""

    def test_skill_written_as_skill_md(self, tmp_path: Path):
        repo = _make_repo(tmp_path, skill_ids=["my-skill"], agent_ids=[])
        export_root = tmp_path / "export"

        result = export(repo, export_root)

        skill_md = export_root / ".cursor" / "skills" / "my-skill" / "SKILL.md"
        assert skill_md.exists(), f"Expected {skill_md} to exist"

    def test_skill_not_written_as_mdc_in_rules(self, tmp_path: Path):
        repo = _make_repo(tmp_path, skill_ids=["my-skill"], agent_ids=[])
        export_root = tmp_path / "export"

        export(repo, export_root)

        skill_mdc = export_root / ".cursor" / "rules" / "my-skill.mdc"
        assert not skill_mdc.exists(), (
            f"Skill must NOT be emitted as {skill_mdc}"
        )

    def test_multiple_skills_each_get_own_directory(self, tmp_path: Path):
        skill_ids = ["z-plan", "z-amend", "z-attend"]
        repo = _make_repo(tmp_path, skill_ids=skill_ids, agent_ids=[])
        export_root = tmp_path / "export"

        export(repo, export_root)

        for sid in skill_ids:
            skill_md = export_root / ".cursor" / "skills" / sid / "SKILL.md"
            assert skill_md.exists(), f"Expected SKILL.md for {sid!r} at {skill_md}"

    def test_skill_md_path_in_result_files(self, tmp_path: Path):
        repo = _make_repo(tmp_path, skill_ids=["z-plan"], agent_ids=[])
        export_root = tmp_path / "export"

        result = export(repo, export_root)

        skill_paths = [f for f in result.files if "SKILL.md" in f.name]
        assert len(skill_paths) == 1
        assert skill_paths[0] == export_root / ".cursor" / "skills" / "z-plan" / "SKILL.md"


# ---------------------------------------------------------------------------
# Frontmatter: SKILL.md files must have --- fences
# ---------------------------------------------------------------------------


class TestSkillFrontmatter:
    """Exported SKILL.md files must contain frontmatter fences."""

    def test_skill_md_has_frontmatter_fences(self, tmp_path: Path):
        repo = _make_repo(tmp_path, skill_ids=["my-skill"], agent_ids=[])
        export_root = tmp_path / "export"

        export(repo, export_root)

        skill_md = export_root / ".cursor" / "skills" / "my-skill" / "SKILL.md"
        text = skill_md.read_text(encoding="utf-8")
        assert text.startswith("---\n"), "SKILL.md must start with --- frontmatter fence"
        # Check a closing fence exists
        assert "\n---\n" in text, "SKILL.md must have a closing --- frontmatter fence"

    def test_skill_md_preserves_source_frontmatter_verbatim(self, tmp_path: Path):
        """Custom frontmatter keys (runtime, driver_features_required, etc.) must be preserved."""
        skills_dir = (tmp_path / "repo" / "skills")
        skill_dir = skills_dir / "z-custom"
        skill_dir.mkdir(parents=True)
        skill_file = skill_dir / "SKILL.md"
        # Write a skill with non-standard frontmatter keys.
        custom_content = (
            "---\n"
            "name: z-custom\n"
            "disable-model-invocation: true\n"
            'description: "Custom skill"\n'
            "runtime: c1\n"
            "driver_features_required:\n"
            "  - subagent\n"
            "unsupported_driver_behavior: explicit_gate\n"
            "---\n"
            "\n"
            "Custom skill body.\n"
        )
        skill_file.write_text(custom_content, encoding="utf-8")

        export_root = tmp_path / "export"
        export(tmp_path / "repo", export_root)

        out_file = export_root / ".cursor" / "skills" / "z-custom" / "SKILL.md"
        assert out_file.exists()
        # Source preserved verbatim
        assert out_file.read_text(encoding="utf-8") == custom_content

    def test_skill_md_expands_include_markers(self, tmp_path: Path):
        """Native skills keep frontmatter but receive enumerated expanded body."""
        repo = tmp_path / "repo"
        fragment_dir = repo / "_fragments"
        fragment_dir.mkdir(parents=True)
        fragment_dir.joinpath("surface-mapping.md").write_text(
            "## Shared surface mapping contract\n\nRepo Explore facets\n",
            encoding="utf-8",
        )
        marker = "<!-- include: _fragments/surface-mapping.md -->"
        _make_skill(repo / "skills", "z-explain", body=f"Before.\n{marker}\nAfter.\n")
        _make_skill(repo / "skills", "z-learn", body=f"Before.\n{marker}\nAfter.\n")

        export_root = tmp_path / "export"
        export(repo, export_root)

        for skill_name in ("z-explain", "z-learn"):
            out_file = export_root / ".cursor" / "skills" / skill_name / "SKILL.md"
            out_text = out_file.read_text(encoding="utf-8")
            assert out_text.startswith(f"---\nname: {skill_name}\n")
            assert "Shared surface mapping contract" in out_text
            assert marker not in out_text

    def test_skill_md_not_rewritten(self, tmp_path: Path):
        """Skills must NOT have Agent/Skill calls rewritten — they are native."""
        skills_dir = tmp_path / "repo" / "skills"
        skill_dir = skills_dir / "z-agent-skill"
        skill_dir.mkdir(parents=True)
        skill_file = skill_dir / "SKILL.md"
        # This skill body references Agent() — must be preserved verbatim.
        content_with_agent = (
            "---\n"
            "name: z-agent-skill\n"
            'description: "Has Agent call"\n'
            "---\n"
            "\n"
            "Agent(subagent_type='consultant')\n"
            "Skill(id='z-plan')\n"
        )
        skill_file.write_text(content_with_agent, encoding="utf-8")

        export_root = tmp_path / "export"
        export(tmp_path / "repo", export_root)

        out_file = export_root / ".cursor" / "skills" / "z-agent-skill" / "SKILL.md"
        out_text = out_file.read_text(encoding="utf-8")
        # Agent() references must NOT be replaced with HTML comments
        assert "Agent(" in out_text, "Skills must preserve Agent() calls verbatim"
        assert "Skill(" in out_text, "Skills must preserve Skill() calls verbatim"


# ---------------------------------------------------------------------------
# Agents: still emit .cursor/rules/<id>.mdc
# ---------------------------------------------------------------------------


class TestAgentLayout:
    """Agents are still exported as .cursor/rules/<id>.mdc (unchanged)."""

    def test_agent_written_as_mdc_in_rules(self, tmp_path: Path):
        repo = _make_repo(tmp_path, skill_ids=[], agent_ids=["auditor"])
        export_root = tmp_path / "export"

        export(repo, export_root)

        agent_mdc = export_root / ".cursor" / "rules" / "auditor.mdc"
        assert agent_mdc.exists(), f"Expected agent .mdc at {agent_mdc}"

    def test_agent_not_written_to_skills_dir(self, tmp_path: Path):
        repo = _make_repo(tmp_path, skill_ids=[], agent_ids=["auditor"])
        export_root = tmp_path / "export"

        export(repo, export_root)

        agent_skill_path = export_root / ".cursor" / "skills" / "auditor" / "SKILL.md"
        assert not agent_skill_path.exists(), (
            "Agents must NOT be written to .cursor/skills/"
        )

    def test_agent_mdc_has_alwaysapply_false(self, tmp_path: Path):
        repo = _make_repo(tmp_path, skill_ids=[], agent_ids=["my-agent"])
        export_root = tmp_path / "export"

        export(repo, export_root)

        agent_mdc = export_root / ".cursor" / "rules" / "my-agent.mdc"
        text = agent_mdc.read_text(encoding="utf-8")
        assert "alwaysApply: false" in text


# ---------------------------------------------------------------------------
# Index MDC: exactly one always-apply .mdc per export run
# ---------------------------------------------------------------------------


class TestSkillsIndexMdc:
    """Exactly one generated .mdc with alwaysApply: true is written per export run."""

    def test_index_mdc_exists(self, tmp_path: Path):
        repo = _make_repo(tmp_path, skill_ids=["z-plan"], agent_ids=[])
        export_root = tmp_path / "export"

        export(repo, export_root)

        index_path = export_root / ".cursor" / "rules" / _SKILLS_INDEX_NAME
        assert index_path.exists(), f"Expected skills index .mdc at {index_path}"

    def test_index_mdc_has_alwaysapply_true(self, tmp_path: Path):
        repo = _make_repo(tmp_path, skill_ids=["z-plan"], agent_ids=[])
        export_root = tmp_path / "export"

        export(repo, export_root)

        index_path = export_root / ".cursor" / "rules" / _SKILLS_INDEX_NAME
        text = index_path.read_text(encoding="utf-8")
        assert "alwaysApply: true" in text, (
            "Skills index .mdc must have alwaysApply: true in frontmatter"
        )

    def test_exactly_one_alwaysapply_true_mdc(self, tmp_path: Path):
        """Only the index .mdc may have alwaysApply: true — agents all have false."""
        repo = _make_repo(
            tmp_path,
            skill_ids=["z-plan", "z-amend"],
            agent_ids=["auditor", "reviewer"],
        )
        export_root = tmp_path / "export"

        export(repo, export_root)

        rules_dir = export_root / ".cursor" / "rules"
        always_apply_mdc = [
            p for p in rules_dir.glob("*.mdc")
            if "alwaysApply: true" in p.read_text(encoding="utf-8")
        ]
        assert len(always_apply_mdc) == 1, (
            f"Expected exactly 1 .mdc with alwaysApply: true, "
            f"found {len(always_apply_mdc)}: {always_apply_mdc}"
        )
        assert always_apply_mdc[0].name == _SKILLS_INDEX_NAME

    def test_index_mdc_has_frontmatter_fences(self, tmp_path: Path):
        repo = _make_repo(tmp_path, skill_ids=["z-plan"], agent_ids=[])
        export_root = tmp_path / "export"

        export(repo, export_root)

        index_path = export_root / ".cursor" / "rules" / _SKILLS_INDEX_NAME
        text = index_path.read_text(encoding="utf-8")
        assert text.startswith("---\n"), "Index .mdc must start with --- frontmatter"
        assert "\n---\n" in text, "Index .mdc must have closing --- frontmatter fence"

    def test_index_mdc_references_skills_directory(self, tmp_path: Path):
        repo = _make_repo(tmp_path, skill_ids=["z-plan"], agent_ids=[])
        export_root = tmp_path / "export"

        export(repo, export_root)

        index_path = export_root / ".cursor" / "rules" / _SKILLS_INDEX_NAME
        text = index_path.read_text(encoding="utf-8")
        assert ".cursor/skills" in text, (
            "Skills index .mdc must reference the .cursor/skills directory"
        )

    def test_index_mdc_in_result_files(self, tmp_path: Path):
        repo = _make_repo(tmp_path, skill_ids=["z-plan"], agent_ids=[])
        export_root = tmp_path / "export"

        result = export(repo, export_root)

        index_path = export_root / ".cursor" / "rules" / _SKILLS_INDEX_NAME
        assert index_path in result.files, (
            "Skills index .mdc must appear in ExportResult.files"
        )


# ---------------------------------------------------------------------------
# Invariant: skill .mdc absence (failure class test)
# ---------------------------------------------------------------------------


class TestSkillMdcAbsenceInvariant:
    """If a skill is present, it must NOT produce a .mdc in .cursor/rules/."""

    def test_no_skill_mdc_when_skill_present(self, tmp_path: Path):
        """Failure class: skill emitted as .mdc → invariant violated."""
        skill_id = "z-test-skill"
        repo = _make_repo(tmp_path, skill_ids=[skill_id], agent_ids=[])
        export_root = tmp_path / "export"

        export(repo, export_root)

        rules_dir = export_root / ".cursor" / "rules"
        # All .mdc files in rules/ must not have the skill_id as their stem.
        mdc_stems = {p.stem for p in rules_dir.glob("*.mdc")}
        assert skill_id not in mdc_stems, (
            f"Skill {skill_id!r} must not appear as a .mdc in .cursor/rules/; "
            f"found: {mdc_stems}"
        )


# ---------------------------------------------------------------------------
# Mixed: agents and skills in the same export
# ---------------------------------------------------------------------------


class TestMixedExport:
    """Both agents and skills exported together produce the correct layout."""

    def test_mixed_export_produces_correct_file_tree(self, tmp_path: Path):
        repo = _make_repo(
            tmp_path,
            skill_ids=["z-plan", "z-attend"],
            agent_ids=["auditor"],
        )
        export_root = tmp_path / "export"

        result = export(repo, export_root)

        # Agent: .mdc in rules/
        assert (export_root / ".cursor" / "rules" / "auditor.mdc").exists()
        # Skills: SKILL.md under .cursor/skills/
        assert (export_root / ".cursor" / "skills" / "z-plan" / "SKILL.md").exists()
        assert (export_root / ".cursor" / "skills" / "z-attend" / "SKILL.md").exists()
        # Index: exactly one always-apply .mdc in rules/
        index = export_root / ".cursor" / "rules" / _SKILLS_INDEX_NAME
        assert index.exists()
        # No skill .mdc in rules/ except the index
        rules_mdc = set((export_root / ".cursor" / "rules").glob("*.mdc"))
        non_index_mdc = rules_mdc - {index}
        for mdc in non_index_mdc:
            assert mdc.stem == "auditor", (
                f"Only agent .mdc files should be in rules/; unexpected: {mdc}"
            )

    def test_result_files_includes_all_emitted_paths(self, tmp_path: Path):
        repo = _make_repo(
            tmp_path,
            skill_ids=["z-plan"],
            agent_ids=["auditor"],
        )
        export_root = tmp_path / "export"

        result = export(repo, export_root)

        # Expect: 1 agent .mdc + 1 skill SKILL.md + 1 index .mdc = 3 files
        assert len(result.files) == 3

    def test_no_warnings_on_clean_export(self, tmp_path: Path):
        repo = _make_repo(
            tmp_path,
            skill_ids=["z-plan"],
            agent_ids=["auditor"],
        )
        export_root = tmp_path / "export"

        result = export(repo, export_root)

        assert result.warnings == [], f"Unexpected warnings: {result.warnings}"
