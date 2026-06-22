"""
tests/drivers/test_antigravity_export_driver.py

End-to-end fixture-based tests for runtime/drivers/antigravity/export.py.

Acceptance criteria covered:
  - With commands/ absent (sources["commands"] returns []) and skills/*/SKILL.md
    populated, export() emits .agent/skills/<id>/SKILL.md for every skill entry.
  - No .agent/workflows/ entries are emitted (workflows block is empty).
  - ExportResult.warnings is empty on a clean run.
  - _build_manifest() emits a non-empty skills: block referencing
    skills/<id>/SKILL.md source paths (not commands/...).
  - Each emitted SKILL.md has name: and description: frontmatter keys and a
    non-empty body.

Failure classes exercised:
  - If skill emission is broken (e.g. skills loop skipped), skill_file_count != input.
  - If frontmatter rendering omits name/description, the frontmatter key assertions fail.
  - If warnings are generated for valid skills, the empty-warnings assertion fails.
  - If manifest skills: block uses wrong source path, the path assertion fails.

No network calls; all I/O uses tmp_path fixtures.

Run:
    pytest tests/drivers/test_antigravity_export_driver.py -v
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from runtime.drivers.antigravity.export import export, _build_manifest


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

_FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n", re.DOTALL)


def _make_skill(
    skills_dir: Path,
    skill_id: str,
    description: str = "",
    extra_body: str = "",
) -> Path:
    """Create a minimal skills/<id>/SKILL.md under skills_dir."""
    if not description:
        description = f"Test skill {skill_id}"
    body = extra_body or f"Invoke with /{skill_id}. Does {skill_id} things.\n"
    content = (
        f"---\n"
        f"name: {skill_id}\n"
        f"disable-model-invocation: true\n"
        f'description: "{description}"\n'
        f"runtime: c1\n"
        f"---\n"
        f"\n"
        + body
    )
    skill_dir = skills_dir / skill_id
    skill_dir.mkdir(parents=True, exist_ok=True)
    skill_file = skill_dir / "SKILL.md"
    skill_file.write_text(content, encoding="utf-8")
    return skill_file


def _make_agent(agents_dir: Path, agent_id: str) -> Path:
    """Create a minimal agents/<id>.md under agents_dir."""
    agents_dir.mkdir(parents=True, exist_ok=True)
    agent_file = agents_dir / f"{agent_id}.md"
    content = (
        f"---\n"
        f'description: "Test agent {agent_id}"\n'
        f"---\n"
        f"\n"
        f"Agent body for {agent_id}.\n"
    )
    agent_file.write_text(content, encoding="utf-8")
    return agent_file


def _make_repo(
    tmp_path: Path,
    skill_ids: list[str],
    agent_ids: list[str] | None = None,
) -> Path:
    """Create a minimal repo fixture with skills (and optionally agents).

    No commands/ directory is created — simulating the post-migration state
    where enumerate_sources() returns sources["commands"] == [].
    """
    repo_root = tmp_path / "repo"
    repo_root.mkdir(exist_ok=True)

    skills_dir = repo_root / "skills"
    for sid in skill_ids:
        _make_skill(skills_dir, sid)

    if agent_ids:
        agents_dir = repo_root / "agents"
        for aid in agent_ids:
            _make_agent(agents_dir, aid)

    return repo_root


def _parse_frontmatter(text: str) -> dict[str, str]:
    """Return {key: value} from a YAML-fenced frontmatter block."""
    m = _FRONTMATTER_RE.match(text)
    if not m:
        return {}
    result: dict[str, str] = {}
    for line in m.group(1).splitlines():
        stripped = line.strip()
        if ":" in stripped and not stripped.startswith("#"):
            key, _, value = stripped.partition(":")
            result[key.strip()] = value.strip().strip('"')
    return result


# ---------------------------------------------------------------------------
# Core: skills emit to .agent/skills/<id>/SKILL.md
# ---------------------------------------------------------------------------


class TestSkillEmission:
    """Skills are written as .agent/skills/<id>/SKILL.md."""

    # Failure class: if the skill loop is skipped or broken, file count < 3
    def test_skill_count_matches_input(self, tmp_path: Path):
        """Emitted skill file count equals the number of input skills."""
        skill_ids = ["z-plan", "z-audit", "z-fix"]
        repo = _make_repo(tmp_path, skill_ids)
        result = export(repo, tmp_path / "out")

        skill_files = [
            f for f in result.files
            if f.name == "SKILL.md" and ".agent/skills" in str(f)
        ]
        assert len(skill_files) == len(skill_ids), (
            f"Expected {len(skill_ids)} skill files, got {len(skill_files)}: {skill_files}"
        )

    def test_skill_written_at_correct_path(self, tmp_path: Path):
        """Each skill lands at .agent/skills/<id>/SKILL.md."""
        repo = _make_repo(tmp_path, ["z-plan", "z-attend", "z-brainstorm"])
        out = tmp_path / "out"
        export(repo, out)

        for skill_id in ("z-plan", "z-attend", "z-brainstorm"):
            expected = out / ".agent" / "skills" / skill_id / "SKILL.md"
            assert expected.exists(), f"Expected skill file at {expected}"

    def test_skill_in_result_files(self, tmp_path: Path):
        """Every emitted SKILL.md path appears in ExportResult.files."""
        skill_ids = ["z-plan", "z-audit", "z-sharpen"]
        repo = _make_repo(tmp_path, skill_ids)
        out = tmp_path / "out"
        result = export(repo, out)

        for sid in skill_ids:
            expected = out / ".agent" / "skills" / sid / "SKILL.md"
            assert expected in result.files, (
                f"Expected {expected} in ExportResult.files"
            )

    def test_skill_order_matches_sorted_input(self, tmp_path: Path):
        """Skills appear in alphabetically sorted order (consistent with sorted())."""
        skill_ids = ["z-plan", "z-amend", "z-audit"]
        repo = _make_repo(tmp_path, skill_ids)
        out = tmp_path / "out"
        result = export(repo, out)

        skill_files = [
            f for f in result.files
            if f.name == "SKILL.md" and ".agent/skills" in str(f)
        ]
        skill_names = [f.parent.name for f in skill_files]
        assert skill_names == sorted(skill_ids), (
            f"Expected {sorted(skill_ids)}, got {skill_names}"
        )


# ---------------------------------------------------------------------------
# Frontmatter: emitted SKILL.md must have name: and description: and body
# ---------------------------------------------------------------------------


class TestSkillFrontmatter:
    """Emitted SKILL.md files must have name: and description: keys and a body."""

    # Failure class: if _render_skill() omits name/description, these assertions fail.
    def test_skill_md_has_name_key(self, tmp_path: Path):
        """Emitted SKILL.md frontmatter must contain 'name:' key."""
        repo = _make_repo(tmp_path, ["z-plan", "z-audit", "z-fix"])
        out = tmp_path / "out"
        export(repo, out)

        for skill_id in ("z-plan", "z-audit", "z-fix"):
            skill_path = out / ".agent" / "skills" / skill_id / "SKILL.md"
            text = skill_path.read_text(encoding="utf-8")
            fm = _parse_frontmatter(text)
            assert "name" in fm, (
                f"SKILL.md for {skill_id!r} missing 'name:' in frontmatter"
            )

    def test_skill_md_has_description_key(self, tmp_path: Path):
        """Emitted SKILL.md frontmatter must contain 'description:' key."""
        repo = _make_repo(tmp_path, ["z-plan", "z-audit", "z-fix"])
        out = tmp_path / "out"
        export(repo, out)

        for skill_id in ("z-plan", "z-audit", "z-fix"):
            skill_path = out / ".agent" / "skills" / skill_id / "SKILL.md"
            text = skill_path.read_text(encoding="utf-8")
            fm = _parse_frontmatter(text)
            assert "description" in fm, (
                f"SKILL.md for {skill_id!r} missing 'description:' in frontmatter"
            )

    def test_skill_md_has_nonempty_body(self, tmp_path: Path):
        """Emitted SKILL.md must have a non-empty body after the frontmatter fence."""
        repo = _make_repo(tmp_path, ["z-plan", "z-audit", "z-fix"])
        out = tmp_path / "out"
        export(repo, out)

        for skill_id in ("z-plan", "z-audit", "z-fix"):
            skill_path = out / ".agent" / "skills" / skill_id / "SKILL.md"
            text = skill_path.read_text(encoding="utf-8")
            m = _FRONTMATTER_RE.match(text)
            assert m is not None, f"SKILL.md for {skill_id!r} has no frontmatter fences"
            body = text[m.end():]
            assert body.strip(), (
                f"SKILL.md for {skill_id!r} has an empty body after frontmatter"
            )

    def test_skill_md_name_matches_skill_id(self, tmp_path: Path):
        """The 'name:' value in the emitted SKILL.md must be the skill's directory name."""
        skill_id = "z-attend"
        repo = _make_repo(tmp_path, [skill_id, "z-audit", "z-fix"])
        out = tmp_path / "out"
        export(repo, out)

        skill_path = out / ".agent" / "skills" / skill_id / "SKILL.md"
        text = skill_path.read_text(encoding="utf-8")
        fm = _parse_frontmatter(text)
        assert fm.get("name") == skill_id, (
            f"Expected name: {skill_id!r}, got {fm.get('name')!r}"
        )

    def test_skill_md_description_preserved_from_source(self, tmp_path: Path):
        """The description in the emitted SKILL.md comes from the source frontmatter."""
        skill_id = "z-custom-desc"
        custom_desc = "Do the custom thing with extra flair"
        skills_dir = tmp_path / "repo" / "skills"
        _make_skill(skills_dir, skill_id, description=custom_desc)
        # Also need 2 more skills to satisfy ≥3 fixture requirement
        _make_skill(skills_dir, "z-extra-1")
        _make_skill(skills_dir, "z-extra-2")

        out = tmp_path / "out"
        export(tmp_path / "repo", out)

        skill_path = out / ".agent" / "skills" / skill_id / "SKILL.md"
        text = skill_path.read_text(encoding="utf-8")
        fm = _parse_frontmatter(text)
        assert custom_desc in fm.get("description", ""), (
            f"Expected description to contain {custom_desc!r}, got {fm.get('description')!r}"
        )


# ---------------------------------------------------------------------------
# Warnings: clean run must produce no warnings
# ---------------------------------------------------------------------------


class TestNoWarnings:
    """ExportResult.warnings must be empty on a clean run with valid skills."""

    # Failure class: if validation incorrectly flags valid skills, warnings != [].
    def test_warnings_empty_on_valid_skills(self, tmp_path: Path):
        """No warnings generated for valid skills with name, description, and body."""
        skill_ids = ["z-plan", "z-audit", "z-fix"]
        repo = _make_repo(tmp_path, skill_ids)
        out = tmp_path / "out"

        result = export(repo, out)

        assert result.warnings == [], (
            f"Expected no warnings, got: {result.warnings}"
        )

    def test_warnings_empty_with_agents_and_skills(self, tmp_path: Path):
        """No warnings when both agents and skills are present."""
        repo = _make_repo(
            tmp_path,
            skill_ids=["z-plan", "z-audit", "z-fix"],
            agent_ids=["implementer"],
        )
        out = tmp_path / "out"

        result = export(repo, out)

        assert result.warnings == [], (
            f"Expected no warnings, got: {result.warnings}"
        )


# ---------------------------------------------------------------------------
# Workflows: commands/ absent → .agent/workflows/ empty
# ---------------------------------------------------------------------------


class TestWorkflowsEmpty:
    """With commands/ absent, no .agent/workflows/ entries are emitted."""

    # Failure class: if commands loop runs on stale data, workflow files appear.
    def test_no_workflow_files_emitted(self, tmp_path: Path):
        """No .md files under .agent/workflows/ when commands/ is absent."""
        repo = _make_repo(tmp_path, ["z-plan", "z-audit", "z-fix"])
        out = tmp_path / "out"

        export(repo, out)

        workflows_dir = out / ".agent" / "workflows"
        workflow_files = list(workflows_dir.iterdir()) if workflows_dir.exists() else []
        assert workflow_files == [], (
            f"Expected no workflow files, got: {workflow_files}"
        )

    def test_workflow_files_absent_from_result_files(self, tmp_path: Path):
        """No workflow paths appear in ExportResult.files."""
        repo = _make_repo(tmp_path, ["z-plan", "z-audit", "z-fix"])
        out = tmp_path / "out"

        result = export(repo, out)

        workflow_files = [
            f for f in result.files
            if ".agent/workflows" in str(f)
        ]
        assert workflow_files == [], (
            f"Expected no workflow files in result.files, got: {workflow_files}"
        )


# ---------------------------------------------------------------------------
# Manifest: _build_manifest() → skills: block with skills/<id>/SKILL.md paths
# ---------------------------------------------------------------------------


class TestManifestSkillsBlock:
    """_build_manifest() emits a correct skills: block with skills/<id>/SKILL.md."""

    # Failure class: if source_rel path uses commands/... instead of skills/..., assertion fails.
    def test_manifest_has_nonempty_skills_block(self, tmp_path: Path):
        """The manifest skills: block is non-empty when skills are present."""
        skill_ids = ["z-plan", "z-audit", "z-fix"]
        repo = _make_repo(tmp_path, skill_ids)
        out = tmp_path / "out"

        export(repo, out)

        manifest = (out / "agy-plugin.yaml").read_text(encoding="utf-8")
        # Should have a skills: block with entries (not just "skills: []")
        assert re.search(r"^skills:\s*\n\s+-", manifest, re.MULTILINE), (
            "Manifest skills: block must be non-empty with skill entries"
        )

    def test_manifest_skills_use_skills_tier_source_paths(self, tmp_path: Path):
        """All source: entries in the skills: block must use 'skills/<id>/SKILL.md'."""
        skill_ids = ["z-plan", "z-audit", "z-fix"]
        repo = _make_repo(tmp_path, skill_ids)
        out = tmp_path / "out"

        export(repo, out)

        manifest = (out / "agy-plugin.yaml").read_text(encoding="utf-8")
        # Extract all 'source:' lines from the skills block
        source_lines = re.findall(r"^\s+source:\s+(.+)$", manifest, re.MULTILINE)
        # All skills source lines must start with 'skills/'
        for line in source_lines:
            assert line.startswith("skills/"), (
                f"Manifest source path {line!r} must start with 'skills/', not 'commands/'"
            )

    def test_manifest_skills_source_path_format(self, tmp_path: Path):
        """Each skill entry's source: is 'skills/<id>/SKILL.md'."""
        skill_ids = ["z-plan", "z-audit", "z-fix"]
        repo = _make_repo(tmp_path, skill_ids)
        out = tmp_path / "out"

        export(repo, out)

        manifest = (out / "agy-plugin.yaml").read_text(encoding="utf-8")
        for sid in skill_ids:
            expected_source = f"source: skills/{sid}/SKILL.md"
            assert expected_source in manifest, (
                f"Expected '{expected_source}' in manifest, not found"
            )

    def test_manifest_workflows_block_is_empty(self, tmp_path: Path):
        """The manifest workflows: block has no entries when commands/ is absent."""
        repo = _make_repo(tmp_path, ["z-plan", "z-audit", "z-fix"])
        out = tmp_path / "out"

        export(repo, out)

        manifest = (out / "agy-plugin.yaml").read_text(encoding="utf-8")
        # workflows: key must exist but must not be followed by any entries
        # (YAML: bare 'workflows:' with nothing under it = null/empty)
        # No '  - id:' lines should appear before the next top-level key
        workflows_section = re.search(
            r"^workflows:\s*\n((?:  .*\n)*)",
            manifest,
            re.MULTILINE,
        )
        if workflows_section:
            workflow_entries = workflows_section.group(1)
            assert "- id:" not in workflow_entries, (
                "workflows: block must have no entries when commands/ is absent"
            )

    def test_manifest_skills_output_path_format(self, tmp_path: Path):
        """Each skill entry's output: is '.agent/skills/<id>/SKILL.md'."""
        skill_ids = ["z-plan", "z-audit", "z-fix"]
        repo = _make_repo(tmp_path, skill_ids)
        out = tmp_path / "out"

        export(repo, out)

        manifest = (out / "agy-plugin.yaml").read_text(encoding="utf-8")
        for sid in skill_ids:
            expected_output = f"output: .agent/skills/{sid}/SKILL.md"
            assert expected_output in manifest, (
                f"Expected '{expected_output}' in manifest, not found"
            )


# ---------------------------------------------------------------------------
# End-to-end: full three-skill run
# ---------------------------------------------------------------------------


class TestEndToEnd:
    """End-to-end run with ≥3 skills, no commands/, verifies all invariants together."""

    def test_full_run_three_skills_no_commands(self, tmp_path: Path):
        """
        Full run: 3 skills, no commands/, 1 agent.
        Asserts all T009 acceptance criteria simultaneously.
        """
        skill_ids = ["z-plan", "z-attend", "z-brainstorm"]
        repo = _make_repo(tmp_path, skill_ids, agent_ids=["implementer"])
        out = tmp_path / "out"

        result = export(repo, out)

        # 1. No warnings
        assert result.warnings == [], f"Unexpected warnings: {result.warnings}"

        # 2. Skill file count matches input
        skill_files = [
            f for f in result.files
            if f.name == "SKILL.md" and ".agent/skills" in str(f)
        ]
        assert len(skill_files) == len(skill_ids)

        # 3. Each SKILL.md has name: and description: and non-empty body
        for sid in skill_ids:
            skill_path = out / ".agent" / "skills" / sid / "SKILL.md"
            assert skill_path.exists(), f"Missing skill file for {sid!r}"
            text = skill_path.read_text(encoding="utf-8")
            fm = _parse_frontmatter(text)
            assert "name" in fm, f"SKILL.md for {sid!r} missing 'name:'"
            assert "description" in fm, f"SKILL.md for {sid!r} missing 'description:'"
            m = _FRONTMATTER_RE.match(text)
            assert m and text[m.end():].strip(), f"SKILL.md for {sid!r} has empty body"

        # 4. No workflow files
        workflows_dir = out / ".agent" / "workflows"
        workflow_files = list(workflows_dir.iterdir()) if workflows_dir.exists() else []
        assert workflow_files == [], f"Unexpected workflow files: {workflow_files}"

        # 5. Manifest skills: block uses skills/<id>/SKILL.md source paths
        manifest = (out / "agy-plugin.yaml").read_text(encoding="utf-8")
        for sid in skill_ids:
            assert f"source: skills/{sid}/SKILL.md" in manifest, (
                f"Manifest must reference skills/{sid}/SKILL.md"
            )
            assert "source: commands/" not in manifest, (
                "Manifest must not reference commands/ paths"
            )

    def test_result_fidelity_is_high(self, tmp_path: Path):
        """antigravity driver reports fidelity='high'."""
        repo = _make_repo(tmp_path, ["z-plan", "z-audit", "z-fix"])
        out = tmp_path / "out"

        result = export(repo, out)

        assert result.fidelity == "high"

    def test_result_dest_is_export_root(self, tmp_path: Path):
        """ExportResult.dest equals the resolved export_root."""
        repo = _make_repo(tmp_path, ["z-plan", "z-audit", "z-fix"])
        out = tmp_path / "out"

        result = export(repo, out)

        assert result.dest == out.resolve()


# ---------------------------------------------------------------------------
# Real-tree smoke: run against the actual worktree skills/ + _fragments/
# ---------------------------------------------------------------------------

# The worktree root — tests that rely on real repo fixtures live here.
_WORKTREE_ROOT = Path(__file__).resolve().parent.parent.parent


class TestRealTreeSmoke:
    """Run export() against the REAL worktree to catch nested-include crashes.

    The fixture-based tests above only exercise simple skill bodies with no
    include markers.  The real skills can include fragments which themselves
    include other fragments (e.g. halt-finalize → run-brief-finalize).
    A broken nested include path causes FileNotFoundError at export time.
    These tests fail if the real export crashes or produces unexpected warnings.

    Failure class: if any skill body triggers an unresolved nested fragment
    include, export() raises FileNotFoundError instead of returning cleanly.
    """

    def test_real_tree_export_completes_without_raising(self, tmp_path: Path):
        """export() against the real worktree must not raise any exception."""
        # This test fails if _fragments/ contains active <!-- include: commands/... -->
        # markers that no longer resolve after the commands/ → skills/ migration.
        result = export(_WORKTREE_ROOT, tmp_path / "out")
        # If we reach here the export completed without raising.
        assert result is not None

    def test_real_tree_export_emits_all_58_skills(self, tmp_path: Path):
        """Real-tree export must emit a SKILL.md for all 58 skills in skills/."""
        result = export(_WORKTREE_ROOT, tmp_path / "out")

        out = tmp_path / "out"
        emitted_skill_ids = {
            p.parent.name
            for p in out.glob(".agent/skills/*/SKILL.md")
        }
        skills_dir = _WORKTREE_ROOT / "skills"
        source_skill_ids = {
            d.name
            for d in skills_dir.iterdir()
            if d.is_dir() and (d / "SKILL.md").exists()
        }

        assert emitted_skill_ids == source_skill_ids, (
            f"Skill count mismatch — emitted {len(emitted_skill_ids)}, "
            f"source has {len(source_skill_ids)}.\n"
            f"Missing: {source_skill_ids - emitted_skill_ids}\n"
            f"Extra:   {emitted_skill_ids - source_skill_ids}"
        )

    def test_real_tree_export_has_empty_warnings(self, tmp_path: Path):
        """Real-tree export must produce no validation warnings."""
        result = export(_WORKTREE_ROOT, tmp_path / "out")

        assert result.warnings == [], (
            f"Expected no warnings on real-tree export, got {len(result.warnings)} warning(s):\n"
            + "\n".join(f"  - {w}" for w in result.warnings)
        )

    def test_real_tree_nested_fragment_expansion(self, tmp_path: Path):
        """Skills that use halt-finalize fragments (with nested includes) must expand correctly.

        The halt-finalize fragments include run-brief-finalize.md.  If their
        include markers still point to commands/_fragments/ (the old location),
        expand_includes() raises FileNotFoundError.  This test verifies the
        chain resolves to completion with no unresolved markers remaining.
        """
        from runtime.drivers._export_utils import expand_includes, _next_include_match

        # Directly exercise nested expansion: outer fragment → inner fragment.
        halt_fragment = _WORKTREE_ROOT / "_fragments" / "run-brief-halt-finalize-execute.md"
        body = halt_fragment.read_text(encoding="utf-8")

        # This must not raise.  Before the fix it raised FileNotFoundError
        # because the inner include still pointed to commands/_fragments/.
        expanded = expand_includes(body, _WORKTREE_ROOT)

        # All include markers must have been resolved.
        remaining = _next_include_match(expanded)
        assert remaining is None, (
            f"Unresolved include marker after expansion: {remaining.group(0)!r}"
        )

        # The run-brief-finalize sentinel must appear (confirms the inner fragment
        # was actually inlined, not silently skipped).
        sentinel = "## Run Brief finalize (shared fragment)"
        assert sentinel in expanded, (
            f"Expected sentinel {sentinel!r} in expanded halt-finalize fragment — "
            "nested include may not have resolved"
        )
