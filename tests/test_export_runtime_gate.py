"""
T015: Beyond-grep export verification for z-attend RUNTIME-GATE tokens.

Tests:
1. RUNTIME-GATE category= token survival across all 4 export surfaces: a fixture
   command carrying a ``<!-- RUNTIME-GATE: ask_user; category=risk ... -->``
   comment must have the ``category=risk`` token present in every rendered output.
   Grep alone false-passes if ``z-attend`` appears elsewhere but the token was
   accidentally stripped — this test runs the actual export parser on a controlled
   fixture and asserts the token is in the rendered result.

2. Codex frontmatter load: z-attend SKILL.md's frontmatter must be parsed by the
   enumerate_sources / _parse_frontmatter pipeline and the resulting entry's
   description must be non-empty (proves the file was not silently dropped).
   The codex exporter emits skills/z-attend/SKILL.md verbatim — verified by
   checking the file contains ``category=risk``.

3. Live export z-attend presence: run the actual codex export against the real
   repo root; the emitted skills/z-attend/SKILL.md must exist AND contain
   ``category=risk`` (proving the live pipeline, not just the fixture).
   Also verifies the .codex-plugin/plugin.json manifest is generated.
"""

from __future__ import annotations
import json
import os
import subprocess

import sys
import tempfile
import textwrap
import tomllib
import unittest

from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(REPO_ROOT))

from runtime.drivers._export_utils import enumerate_sources, _parse_frontmatter  # noqa: E402


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

def _make_fixture_repo(tmp: Path) -> Path:
    """Create a minimal fixture repo with direct and included RUNTIME-GATE comments."""
    repo = tmp / "fixture_repo"
    agents_dir = repo / "agents"
    agents_dir.mkdir(parents=True)
    fragments_dir = repo / "_fragments"
    fragments_dir.mkdir(parents=True)
    (fragments_dir / "surface-mapping.md").write_text(
        textwrap.dedent("""\
        ## Surface mapping fixture fragment

        <!-- RUNTIME-GATE: subagent; non-supporting drivers must preserve this included gate comment. -->
        Included fragment body.
        """),
        encoding="utf-8",
    )

    # Fixture skill: skills/<id>/SKILL.md layout (post-migration)
    skill_dir = repo / "skills" / "z-fixture-gate"
    skill_dir.mkdir(parents=True)
    fixture_skill = skill_dir / "SKILL.md"
    fixture_skill.write_text(
        textwrap.dedent("""\
        ---
        description: Fixture skill for RUNTIME-GATE token-survival test
        ---

        ## Phase 0 — parse args

        Before re-entry, validate the HEAD SHA.
           <!-- RUNTIME-GATE: ask_user; category=risk; non-supporting drivers must surface this before any re-entry. -->
        Use AskUserQuestion to present the remediation.

        ## Phase 1 — included fragment

        <!-- include: _fragments/surface-mapping.md -->

        ## Phase 2 — main body

        The rest of the skill body here.
        """),
        encoding="utf-8",
    )

    return repo


def _render_cursor(fixture_repo: Path) -> str:
    """Run the cursor exporter on the fixture repo and return the rendered .mdc content."""
    from runtime.drivers.cursor.export import _render_mdc
    from runtime.drivers._export_utils import _parse_frontmatter, expand_includes

    skill_path = fixture_repo / "skills" / "z-fixture-gate" / "SKILL.md"
    text = skill_path.read_text(encoding="utf-8")
    fm, body = _parse_frontmatter(text)
    body = expand_includes(body, fixture_repo)
    entry = {"id": "z-fixture-gate", "frontmatter": fm, "body": body}
    return _render_mdc(entry)


def _render_codex(fixture_repo: Path) -> str:
    """Run the codex exporter renderer on the fixture skill."""
    from runtime.drivers.codex.export import _render_prompt
    from runtime.drivers._export_utils import _parse_frontmatter, expand_includes

    skill_path = fixture_repo / "skills" / "z-fixture-gate" / "SKILL.md"
    text = skill_path.read_text(encoding="utf-8")
    fm, body = _parse_frontmatter(text)
    body = expand_includes(body, fixture_repo)
    entry = {"id": "z-fixture-gate", "frontmatter": fm, "body": body}
    return _render_prompt(entry)


def _render_agy_workflow(fixture_repo: Path) -> str:
    """Run the antigravity workflow renderer on the fixture skill."""
    from runtime.drivers.antigravity.export import _render_workflow
    from runtime.drivers._export_utils import _parse_frontmatter, expand_includes

    skill_path = fixture_repo / "skills" / "z-fixture-gate" / "SKILL.md"
    text = skill_path.read_text(encoding="utf-8")
    fm, body = _parse_frontmatter(text)
    body = expand_includes(body, fixture_repo)
    entry = {"id": "z-fixture-gate", "frontmatter": fm, "body": body}
    return _render_workflow(entry)


def _render_pi_prompt(fixture_repo: Path) -> str:
    """Run the pi prompt renderer on the fixture skill."""
    from runtime.drivers.pi.export import _render_prompt
    from runtime.drivers._export_utils import _parse_frontmatter, expand_includes

    skill_path = fixture_repo / "skills" / "z-fixture-gate" / "SKILL.md"
    text = skill_path.read_text(encoding="utf-8")
    fm, body = _parse_frontmatter(text)
    body = expand_includes(body, fixture_repo)
    entry = {"id": "z-fixture-gate", "frontmatter": fm, "body": body}
    # pi _render_prompt needs agent_names set; empty is fine for this fixture
    return _render_prompt(entry, agent_names=set())


# ---------------------------------------------------------------------------
# Test 1: category=risk token survives in every renderer
# ---------------------------------------------------------------------------

class TestRuntimeGateTokenSurvival(unittest.TestCase):
    """RUNTIME-GATE category= tokens must survive export rendering unchanged.

    Invariant: HTML comments (including RUNTIME-GATE comments) are NOT
    rewritten by any of the four export renderers — they are plain text
    content, not Anthropic-specific constructs. A regression that strips HTML
    comments would silently remove the gate taxonomy from exported files.
    """

    def setUp(self) -> None:
        self._tmp_ctx = tempfile.TemporaryDirectory()
        self._tmp = Path(self._tmp_ctx.name)
        self._fixture_repo = _make_fixture_repo(self._tmp)

    def tearDown(self) -> None:
        self._tmp_ctx.cleanup()

    def _assert_token_survives(self, rendered: str, surface: str) -> None:
        """Assert that 'category=risk' is present in the rendered output."""
        self.assertIn(
            "category=risk",
            rendered,
            f"[{surface}] 'category=risk' token missing from rendered output.\n"
            f"Rendered content (first 500 chars):\n{rendered[:500]}",
        )

    def test_cursor_category_token_survives(self) -> None:
        """cursor .mdc renderer must preserve RUNTIME-GATE category=risk token."""
        rendered = _render_cursor(self._fixture_repo)
        self._assert_token_survives(rendered, "cursor")

    def test_codex_category_token_survives(self) -> None:
        """codex prompt renderer must preserve RUNTIME-GATE category=risk token."""
        rendered = _render_codex(self._fixture_repo)
        self._assert_token_survives(rendered, "codex")

    def test_agy_category_token_survives(self) -> None:
        """antigravity workflow renderer must preserve RUNTIME-GATE category=risk token."""
        rendered = _render_agy_workflow(self._fixture_repo)
        self._assert_token_survives(rendered, "agy")

    def test_pi_category_token_survives(self) -> None:
        """pi prompt renderer must preserve RUNTIME-GATE category=risk token."""
        rendered = _render_pi_prompt(self._fixture_repo)
        self._assert_token_survives(rendered, "pi")

    def test_included_fragment_runtime_gate_survives_all_renderers(self) -> None:
        """RUNTIME-GATE comments from included fragments survive rendering."""
        rendered_by_surface = {
            "cursor": _render_cursor(self._fixture_repo),
            "codex": _render_codex(self._fixture_repo),
            "agy": _render_agy_workflow(self._fixture_repo),
            "pi": _render_pi_prompt(self._fixture_repo),
        }

        for surface, rendered in rendered_by_surface.items():
            with self.subTest(surface=surface):
                self.assertNotIn("<!-- include: _fragments/surface-mapping.md -->", rendered)
                self.assertIn("Surface mapping fixture fragment", rendered)
                self.assertIn("RUNTIME-GATE: subagent", rendered)
                self.assertIn("included gate comment", rendered)

    def test_runtime_gate_comment_not_rewritten_as_agent_dispatch(self) -> None:
        """RUNTIME-GATE HTML comment must NOT be treated as an Agent() call site.

        Failure class: if a future rewriter starts matching HTML comment lines
        containing 'ask_user' or replacing any line with a CAPABILITIES.md
        redirect, the token would disappear. This catches that regression.
        """
        # The cursor renderer replaces Agent(...) / Skill(...) lines.
        # A RUNTIME-GATE comment line must not match that rewriting path.
        rendered = _render_cursor(self._fixture_repo)
        # The original comment line must appear verbatim — not replaced by
        # the Anthropic-construct limitation comment.
        limitation_comment = "agent dispatch / skill invocation not supported"
        # The RUNTIME-GATE line itself should not be replaced.
        self.assertIn("RUNTIME-GATE", rendered, "RUNTIME-GATE marker lost in cursor render")
        # But also verify the limitation-comment didn't replace the gate line.
        # If it did, the rendered text would have the limitation comment but NOT category=risk.
        if limitation_comment in rendered:
            self.assertIn(
                "category=risk",
                rendered,
                "category=risk token missing — RUNTIME-GATE line may have been replaced by "
                "the Anthropic-construct limitation comment",
            )


# ---------------------------------------------------------------------------
# Test 2: Codex frontmatter load for z-attend.md
# ---------------------------------------------------------------------------

class TestCodexFrontmatterLoad(unittest.TestCase):
    """z-attend SKILL.md must be parsed (not silently dropped) by enumerate_sources.

    Invariant: _parse_frontmatter on skills/z-attend/SKILL.md must return a
    non-empty description. enumerate_sources must include a 'z-attend' entry in
    its 'skills' list (z-attend is now a SKILL, not a command). The codex
    exporter now emits skills/z-attend/SKILL.md verbatim (not prompts/).

    Failure class: if SKILL.md has malformed frontmatter that causes
    _parse_frontmatter to silently skip it, or if enumerate_sources drops it,
    the description would be empty and the codex output would be missing.
    """

    def test_z_attend_frontmatter_parsed_not_empty(self) -> None:
        """_parse_frontmatter on skills/z-attend/SKILL.md returns a non-empty description."""
        z_attend_path = REPO_ROOT / "skills" / "z-attend" / "SKILL.md"
        self.assertTrue(z_attend_path.exists(), f"z-attend SKILL.md not found at {z_attend_path}")

        text = z_attend_path.read_text(encoding="utf-8")
        fm, body = _parse_frontmatter(text)

        self.assertIn(
            "description",
            fm,
            "z-attend SKILL.md frontmatter has no 'description' key — frontmatter may not be parsed",
        )
        self.assertTrue(
            fm["description"],
            "z-attend SKILL.md frontmatter 'description' is empty — file may be silently dropped",
        )
        self.assertTrue(
            body.strip(),
            "z-attend SKILL.md body is empty after frontmatter — malformed file structure",
        )

    def test_enumerate_sources_includes_z_attend(self) -> None:
        """enumerate_sources must return z-attend in the skills list."""
        sources = enumerate_sources(REPO_ROOT)
        skill_ids = {entry["id"] for entry in sources["skills"]}
        self.assertIn(
            "z-attend",
            skill_ids,
            f"enumerate_sources did not include 'z-attend' in skills. "
            f"Found: {sorted(skill_ids)[:10]}... (first 10)",
        )

    def test_z_attend_entry_has_nonempty_description(self) -> None:
        """The z-attend entry returned by enumerate_sources must have a description."""
        sources = enumerate_sources(REPO_ROOT)
        attend_entries = [e for e in sources["skills"] if e["id"] == "z-attend"]
        self.assertTrue(
            attend_entries,
            "No z-attend entry found in enumerate_sources skills",
        )
        entry = attend_entries[0]
        description = entry["frontmatter"].get("description", "")
        self.assertTrue(
            description,
            "z-attend entry has empty description — frontmatter not loaded or silently dropped",
        )

    def test_codex_emits_z_attend_skill_md_verbatim(self) -> None:
        """Codex export must emit skills/z-attend/SKILL.md verbatim (frontmatter preserved).

        This verifies the full pipeline: enumerate_sources picks up z-attend in
        the skills tier, and the codex driver writes the source SKILL.md verbatim
        (no transliteration). The emitted file must start with the YAML frontmatter
        fence (---) from the source.
        """
        import tempfile

        from runtime.drivers.codex import export as codex_export

        with tempfile.TemporaryDirectory() as tmp:
            out_root = Path(tmp) / "codex_out"
            result = codex_export.export(REPO_ROOT, out_root)

            skill_path = out_root / "skills" / "z-attend" / "SKILL.md"
            self.assertTrue(
                skill_path.exists(),
                f"Codex export did not emit skills/z-attend/SKILL.md at {skill_path}",
            )
            content = skill_path.read_text(encoding="utf-8")
            first_line = content.splitlines()[0] if content.strip() else ""
            self.assertEqual(
                first_line,
                "---",
                f"skills/z-attend/SKILL.md first line must be '---' (YAML frontmatter). Got: {first_line!r}",
            )

    def test_codex_z_attend_skill_md_contains_category_risk(self) -> None:
        """Codex-emitted skills/z-attend/SKILL.md must contain 'category=risk' token.

        This is the full-pipeline BEYOND-GREP assertion: z-attend carries
        RUNTIME-GATE comments with category=risk; the codex verbatim copy must
        preserve them (no stripping or rewriting of the source SKILL.md).
        """
        import tempfile

        from runtime.drivers.codex import export as codex_export

        with tempfile.TemporaryDirectory() as tmp:
            out_root = Path(tmp) / "codex_out"
            codex_export.export(REPO_ROOT, out_root)

            skill_path = out_root / "skills" / "z-attend" / "SKILL.md"
            self.assertTrue(skill_path.exists(), "skills/z-attend/SKILL.md not emitted")
            content = skill_path.read_text(encoding="utf-8")

            self.assertIn(
                "category=risk",
                content,
                "codex skills/z-attend/SKILL.md missing 'category=risk' token — "
                "RUNTIME-GATE comments may have been stripped from the verbatim copy",
            )


# ---------------------------------------------------------------------------
# Test 3: Live export verification — z-attend in all 4 surfaces
# ---------------------------------------------------------------------------

class TestLiveExportZAttend(unittest.TestCase):
    """End-to-end: run each exporter against the real repo and verify z-attend.

    These tests run the actual export() function against REPO_ROOT and write
    to a temp directory, then assert z-attend is present and has category=risk.
    """

    def _run_and_verify(
        self,
        exporter_module: str,
        exported_path_parts: tuple[str, ...],
        surface: str,
    ) -> None:
        """Generic helper: run export() and verify the z-attend file."""
        import importlib
        mod = importlib.import_module(exporter_module)

        with tempfile.TemporaryDirectory() as tmp:
            out_root = Path(tmp) / "export_out"
            result = mod.export(REPO_ROOT, out_root)

            # Check that a z-attend file is in the emitted files list.
            file_names = [f.name for f in result.files]
            attend_in_files = any("z-attend" in str(f) for f in result.files)
            self.assertTrue(
                attend_in_files,
                f"[{surface}] z-attend not found in export result files. "
                f"Got {len(result.files)} files. First 10: {[str(f) for f in result.files[:10]]}",
            )

            # Check the exported z-attend file for category=risk.
            attend_file = out_root / Path(*exported_path_parts)
            self.assertTrue(
                attend_file.exists(),
                f"[{surface}] expected z-attend export at {attend_file} but file not found",
            )
            content = attend_file.read_text(encoding="utf-8")
            self.assertIn(
                "category=risk",
                content,
                f"[{surface}] 'category=risk' missing from {attend_file}. "
                f"File content (first 300 chars):\n{content[:300]}",
            )
            self.assertIn(
                "z-attend",
                content,
                f"[{surface}] 'z-attend' missing from exported file {attend_file}",
            )

    def test_cursor_export_has_z_attend_with_category_token(self) -> None:
        """Cursor export must produce .cursor/skills/z-attend/SKILL.md with category=risk."""
        self._run_and_verify(
            "runtime.drivers.cursor.export",
            (".cursor", "skills", "z-attend", "SKILL.md"),
            "cursor",
        )

    def test_codex_export_has_z_attend_with_category_token(self) -> None:
        """Codex export must produce skills/z-attend/SKILL.md with category=risk."""
        self._run_and_verify(
            "runtime.drivers.codex.export",
            ("skills", "z-attend", "SKILL.md"),
            "codex",
        )

    def test_agy_export_has_z_attend_with_category_token(self) -> None:
        """Antigravity export must produce .agent/skills/z-attend/SKILL.md with category=risk."""
        self._run_and_verify(
            "runtime.drivers.antigravity.export",
            (".agent", "skills", "z-attend", "SKILL.md"),
            "agy",
        )

    def test_pi_export_has_z_attend_with_category_token(self) -> None:
        """Pi export must produce prompts/z-attend.md with category=risk."""
        self._run_and_verify(
            "runtime.drivers.pi.export",
            ("prompts", "z-attend.md"),
            "pi",
        )

    def test_codex_export_generates_plugin_manifest(self) -> None:
        """Codex export must generate .codex-plugin/plugin.json declaring skills path.

        Invariant: the manifest must parse as JSON and contain a 'skills' key
        (relative path to the skills directory). Without this manifest Codex CLI
        cannot discover the emitted SKILL.md files.
        """
        import importlib
        import json
        import tempfile

        mod = importlib.import_module("runtime.drivers.codex.export")
        with tempfile.TemporaryDirectory() as tmp:
            out_root = Path(tmp) / "export_out"
            result = mod.export(REPO_ROOT, out_root)

            manifest_path = out_root / ".codex-plugin" / "plugin.json"
            self.assertTrue(
                manifest_path.exists(),
                f"[codex] .codex-plugin/plugin.json not generated at {manifest_path}",
            )
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertIn(
                "skills",
                data,
                "[codex] .codex-plugin/plugin.json missing 'skills' key — "
                "Codex CLI will not discover the skills directory",
            )
            # Manifest must be in the emitted files list.
            manifest_in_files = any(
                ".codex-plugin" in str(f) and "plugin.json" in str(f)
                for f in result.files
            )
            self.assertTrue(
                manifest_in_files,
                "[codex] plugin.json not listed in ExportResult.files",
            )
            # No prompts/ directory should exist (old flat layout removed).
            prompts_dir = out_root / "prompts"
            self.assertFalse(
                prompts_dir.exists(),
                "[codex] prompts/ directory still present — old flat-transliteration layout not removed",
            )



class TestLiveExportZResumeRegistration(unittest.TestCase):
    """End-to-end export and packaging coverage for the /z-resume recovery surface."""

    def _exported_text(
        self,
        exporter_module: str,
        exported_path_parts: tuple[str, ...],
    ) -> str:
        import importlib

        mod = importlib.import_module(exporter_module)
        with tempfile.TemporaryDirectory() as tmp:
            out_root = Path(tmp) / "export_out"
            mod.export(REPO_ROOT, out_root)
            exported = out_root / Path(*exported_path_parts)
            self.assertTrue(exported.exists(), f"missing z-resume export at {exported}")
            return exported.read_text(encoding="utf-8")

    def _exported_file_set(self, exporter_module: str) -> set[str]:
        import importlib

        mod = importlib.import_module(exporter_module)
        with tempfile.TemporaryDirectory() as tmp:
            out_root = (Path(tmp) / "export_out").resolve()
            result = mod.export(REPO_ROOT, out_root)
            paths: set[str] = set()
            for path in result.files:
                resolved = Path(path).resolve()
                if resolved.exists():
                    paths.add(resolved.relative_to(out_root).as_posix())
            return paths


    def test_enumerate_sources_includes_z_resume_skill_with_script_reference(self) -> None:
        sources = enumerate_sources(REPO_ROOT)
        resume_entries = [entry for entry in sources["skills"] if entry["id"] == "z-resume"]
        self.assertTrue(resume_entries, "enumerate_sources did not include z-resume skill")
        entry = resume_entries[0]
        self.assertTrue(entry["frontmatter"].get("description"), "z-resume description not parsed")
        self.assertIn("scripts/resume-context.py", entry["body"])
        self.assertTrue(
            (REPO_ROOT / "scripts" / "resume-context.py").exists(),
            "deterministic resume-context.py script is missing",
        )

    def test_z_resume_skill_and_script_reference_survive_all_exports(self) -> None:
        exported_by_surface = {
            "cursor": self._exported_text(
                "runtime.drivers.cursor.export",
                (".cursor", "skills", "z-resume", "SKILL.md"),
            ),
            "codex": self._exported_text(
                "runtime.drivers.codex.export",
                ("skills", "z-resume", "SKILL.md"),
            ),
            "agy": self._exported_text(
                "runtime.drivers.antigravity.export",
                (".agent", "skills", "z-resume", "SKILL.md"),
            ),
            "pi": self._exported_text(
                "runtime.drivers.pi.export",
                ("prompts", "z-resume.md"),
            ),
            "kiro": self._exported_text(
                "runtime.drivers.kiro.export",
                (".kiro", "steering", "z-resume.md"),
            ),
            "windsurf": self._exported_text(
                "runtime.drivers.windsurf.export",
                (".windsurf", "rules", "z-resume.md"),
            ),
        }

        for surface, content in exported_by_surface.items():
            with self.subTest(surface=surface):
                self.assertIn("/z-resume", content)
                self.assertIn("scripts/resume-context.py", content)
                self.assertIn("selected_target", content)


    def test_omp_export_declares_z_resume_skill_without_agent_project_autoload(self) -> None:
        import importlib

        mod = importlib.import_module("runtime.drivers.omp.export")
        with tempfile.TemporaryDirectory() as tmp:
            out_root = Path(tmp) / "export_out"
            mod.export(REPO_ROOT, out_root)
            config = (out_root / ".omp" / "config.yml").read_text(encoding="utf-8")
            skill = (out_root / ".omp" / "z-harness" / "skills" / "z-resume" / "SKILL.md").read_text(encoding="utf-8")

        self.assertIn("enableAgentsProject: false", config)
        self.assertIn("/z-resume", skill)
        self.assertIn("scripts/resume-context.py", skill)
        self.assertIn("selected_target", skill)
        self.assertIn("Selection before story", skill)

    def test_z_resume_runtime_scripts_are_exported_for_hosts(self) -> None:
        expected = {
            "scripts/resume-context.py",
            "scripts/artifact-scout-inventory.py",
            "scripts/active-plan-registry.py",
            "scripts/plan-path.sh",
            "scripts/session-helpers.sh",
        }
        exporters = {
            "cursor": ("runtime.drivers.cursor.export", ""),
            "codex": ("runtime.drivers.codex.export", ""),
            "agy": ("runtime.drivers.antigravity.export", ""),
            "pi": ("runtime.drivers.pi.export", ""),
            "omp": ("runtime.drivers.omp.export", ".omp/z-harness/"),
            "kiro": ("runtime.drivers.kiro.export", ""),
            "windsurf": ("runtime.drivers.windsurf.export", ""),
        }

        for surface, (module, prefix) in exporters.items():
            with self.subTest(surface=surface):
                exported_files = self._exported_file_set(module)
                for rel_path in expected:
                    self.assertIn(f"{prefix}{rel_path}", exported_files)


    def test_export_only_z_resume_references_have_runtime_scripts(self) -> None:
        exporters = {
            "kiro": (
                "runtime.drivers.kiro.export",
                (".kiro", "steering", "z-resume.md"),
            ),
            "windsurf": (
                "runtime.drivers.windsurf.export",
                (".windsurf", "rules", "z-resume.md"),
            ),
        }

        for surface, (module, exported_path_parts) in exporters.items():
            with self.subTest(surface=surface):
                import importlib

                mod = importlib.import_module(module)
                with tempfile.TemporaryDirectory() as tmp:
                    out_root = (Path(tmp) / "export_out").resolve()
                    result = mod.export(REPO_ROOT, out_root)
                    exported = out_root / Path(*exported_path_parts)
                    self.assertTrue(exported.exists(), f"[{surface}] missing z-resume export")
                    content = exported.read_text(encoding="utf-8")
                    self.assertIn("scripts/resume-context.py", content)
                    runtime_script = out_root / "scripts" / "resume-context.py"
                    self.assertTrue(
                        runtime_script.exists(),
                        f"[{surface}] z-resume references scripts/resume-context.py "
                        "but the runtime script was not exported",
                    )
                    emitted = {Path(path).resolve() for path in result.files}
                    self.assertIn(runtime_script, emitted)

    def test_exported_z_resume_runtime_uses_target_repo_root_without_target_scripts(self) -> None:
        import importlib

        mod = importlib.import_module("runtime.drivers.codex.export")
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            export_root = (tmp_path / "export_out").resolve()
            target_repo = (tmp_path / "target_repo").resolve()
            target_repo.mkdir()
            (target_repo / "README.txt").write_text("target repo marker\n", encoding="utf-8")

            mod.export(REPO_ROOT, export_root)
            self.assertFalse((target_repo / "scripts").exists(), "target fixture must not carry helper scripts")

            proc = subprocess.run(
                [
                    sys.executable,
                    str(export_root / "scripts" / "resume-context.py"),
                    "--repo-root",
                    str(target_repo),
                    "--format",
                    "json",
                    "--noninteractive",
                    "--max-candidates",
                    "1",
                ],
                cwd=str(target_repo),
                env={**os.environ, "Z_HARNESS_PLAN_DIR": str(tmp_path / "state")},
                capture_output=True,
                text=True,
                timeout=30,
            )

            self.assertEqual(proc.returncode, 0, proc.stderr or proc.stdout)
            packet = json.loads(proc.stdout)
            self.assertEqual(Path(packet["repo_identity"]["repo_root"]).resolve(), target_repo)
            self.assertNotEqual(Path(packet["repo_identity"]["repo_root"]).resolve(), export_root)
            repo_records = [record for record in packet["evidence_records"] if record.get("type") == "repo_identity"]
            self.assertTrue(repo_records)
            self.assertEqual(Path(repo_records[0]["data"]["repo_root"]).resolve(), target_repo)
            inventory_records = [record for record in packet["evidence_records"] if record.get("type") == "artifact_inventory"]
            self.assertTrue(inventory_records)
            self.assertEqual(Path(inventory_records[0]["data"]["repo_root"]).resolve(), target_repo)
            self.assertFalse(
                any(record.get("type") == "provider_failure" and record.get("provider") == "artifact_inventory" for record in packet["evidence_records"]),
                "artifact inventory should load helpers from export root while probing target repo",
            )

    def test_agy_manifest_declares_z_resume_skill_and_resume_agent(self) -> None:
        manifest = (REPO_ROOT / "agy-plugin.yaml").read_text(encoding="utf-8")
        self.assertIn("id: z-resume", manifest)
        self.assertIn("source: skills/z-resume/SKILL.md", manifest)
        self.assertIn("output: .agent/skills/z-resume/SKILL.md", manifest)
        self.assertIn("id: resume-cluster", manifest)
        self.assertIn("source: agents/resume-cluster.md", manifest)

    def test_pyproject_force_includes_z_resume_runtime_roots(self) -> None:
        data = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        force_include = data["tool"]["hatch"]["build"]["targets"]["wheel"]["force-include"]
        self.assertEqual(force_include.get("skills"), "skills")
        self.assertEqual(force_include.get("scripts"), "scripts")
        self.assertEqual(force_include.get("agents"), "agents")
        self.assertTrue((REPO_ROOT / "skills" / "z-resume" / "SKILL.md").exists())
        self.assertTrue((REPO_ROOT / "scripts" / "resume-context.py").exists())



class TestLiveExportZExplainSurfacePolicy(unittest.TestCase):
    """End-to-end export coverage for the /z-explain repo surface command text."""

    def _exported_text(
        self,
        exporter_module: str,
        exported_path_parts: tuple[str, ...],
    ) -> str:
        import importlib

        mod = importlib.import_module(exporter_module)
        with tempfile.TemporaryDirectory() as tmp:
            out_root = Path(tmp) / "export_out"
            mod.export(REPO_ROOT, out_root)
            exported = out_root / Path(*exported_path_parts)
            self.assertTrue(exported.exists(), f"missing z-explain export at {exported}")
            return exported.read_text(encoding="utf-8")

    def test_z_explain_repo_surface_policy_survives_all_exports(self) -> None:
        exported_by_surface = {
            "cursor": self._exported_text(
                "runtime.drivers.cursor.export",
                (".cursor", "skills", "z-explain", "SKILL.md"),
            ),
            "codex": self._exported_text(
                "runtime.drivers.codex.export",
                ("skills", "z-explain", "SKILL.md"),
            ),
            "agy": self._exported_text(
                "runtime.drivers.antigravity.export",
                (".agent", "skills", "z-explain", "SKILL.md"),
            ),
            "pi": self._exported_text(
                "runtime.drivers.pi.export",
                ("prompts", "z-explain.md"),
            ),
        }

        for surface, content in exported_by_surface.items():
            with self.subTest(surface=surface):
                self.assertIn("/z-explain --repo orientation", content)
                self.assertIn("--surface=auto|off|force", content)
                self.assertIn("--surface=off", content)
                self.assertIn("surface-map.json", content)
                self.assertIn("One answer, one lens", content)
                self.assertIn("Shared surface mapping contract", content)
                self.assertNotIn("<!-- include: _fragments/surface-mapping.md -->", content)
                self.assertNotIn("/z-" + "grasp", content)



class TestLiveExportZLearnSurfacePolicy(unittest.TestCase):
    """End-to-end export coverage for the /z-learn repo surface grounding text."""

    def _exported_text(
        self,
        exporter_module: str,
        exported_path_parts: tuple[str, ...],
    ) -> str:
        import importlib

        mod = importlib.import_module(exporter_module)
        with tempfile.TemporaryDirectory() as tmp:
            out_root = Path(tmp) / "export_out"
            mod.export(REPO_ROOT, out_root)
            exported = out_root / Path(*exported_path_parts)
            self.assertTrue(exported.exists(), f"missing z-learn export at {exported}")
            return exported.read_text(encoding="utf-8")

    def test_z_learn_repo_surface_policy_survives_all_exports(self) -> None:
        exported_by_surface = {
            "cursor": self._exported_text(
                "runtime.drivers.cursor.export",
                (".cursor", "skills", "z-learn", "SKILL.md"),
            ),
            "codex": self._exported_text(
                "runtime.drivers.codex.export",
                ("skills", "z-learn", "SKILL.md"),
            ),
            "agy": self._exported_text(
                "runtime.drivers.antigravity.export",
                (".agent", "skills", "z-learn", "SKILL.md"),
            ),
            "pi": self._exported_text(
                "runtime.drivers.pi.export",
                ("prompts", "z-learn.md"),
            ),
        }

        for surface, content in exported_by_surface.items():
            with self.subTest(surface=surface):
                self.assertIn("/z-learn --repo", content)
                self.assertIn("--surface=auto|off|force", content)
                self.assertIn("--surface=off", content)
                self.assertIn("surface-map.json", content)
                self.assertIn("## Grounding", content)
                self.assertIn("Raw maps stay archived", content)
                self.assertIn("Do not paste raw maps", content)
                self.assertIn("First repo turn", content)
                self.assertIn("One teaching chunk per turn", content)
                self.assertIn("Target-changing pivots rerun Phase 2", content)
                self.assertIn("Orientation map", content)
                self.assertIn("Shared surface mapping contract", content)
                self.assertNotIn("<!-- include: _fragments/surface-mapping.md -->", content)
                self.assertNotIn("/z-" + "grasp", content)


class TestLiveExportZReportSurfacePolicy(unittest.TestCase):
    """End-to-end export coverage for /z-report surface aliases and context contract."""

    def _exported_text(
        self,
        exporter_module: str,
        exported_path_parts: tuple[str, ...],
    ) -> str:
        import importlib

        mod = importlib.import_module(exporter_module)
        with tempfile.TemporaryDirectory() as tmp:
            out_root = Path(tmp) / "export_out"
            mod.export(REPO_ROOT, out_root)
            exported = out_root / Path(*exported_path_parts)
            self.assertTrue(exported.exists(), f"missing z-report export at {exported}")
            return exported.read_text(encoding="utf-8")

    def test_z_report_surface_aliases_survive_all_exports(self) -> None:
        exported_by_surface = {
            "cursor": self._exported_text(
                "runtime.drivers.cursor.export",
                (".cursor", "skills", "z-report", "SKILL.md"),
            ),
            "codex": self._exported_text(
                "runtime.drivers.codex.export",
                ("skills", "z-report", "SKILL.md"),
            ),
            "agy": self._exported_text(
                "runtime.drivers.antigravity.export",
                (".agent", "skills", "z-report", "SKILL.md"),
            ),
            "pi": self._exported_text(
                "runtime.drivers.pi.export",
                ("prompts", "z-report.md"),
            ),
        }

        for surface, content in exported_by_surface.items():
            with self.subTest(surface=surface):
                self.assertIn("/z-report current", content)
                self.assertIn("/z-report since <ref>", content)
                self.assertIn("--surface=auto|off|existing|refresh", content)
                self.assertIn("--surface=off", content)
                self.assertIn("context.json", content)
                self.assertIn("surface_map_*", content)
                self.assertIn("## Surface Map", content)
                self.assertIn("report-time current repo state", content)
                self.assertIn("Never read `surface_map_path`", content)
                self.assertNotIn("/z-" + "grasp", content)

class TestUnsupportedCallBlockRewrites(unittest.TestCase):
    """Regression coverage for multi-line unsupported runtime call export rewrites."""

    def _rendered(self, exporter_module: str, exported_path_parts: tuple[str, ...]) -> str:
        import importlib

        mod = importlib.import_module(exporter_module)
        with tempfile.TemporaryDirectory() as tmp:
            out_root = Path(tmp) / "export_out"
            mod.export(REPO_ROOT, out_root)
            rendered = out_root / Path(*exported_path_parts)
            self.assertTrue(rendered.exists(), f"missing rendered file: {rendered}")
            return rendered.read_text(encoding="utf-8")

    @unittest.skipUnless(
        (REPO_ROOT / ".git").is_dir(),
        "install.sh is_repo_clone() requires .git to be a directory; in a git worktree "
        ".git is a file, so this test only runs on a normal clone (see LEDGER, T020)",
    )
    def test_antigravity_preserves_gate_comments_without_orphaned_agent_args(self) -> None:
        content = self._rendered(
            "runtime.drivers.antigravity.export",
            (".agent", "skills", "z-audit-plan-style", "SKILL.md"),
        )
        self.assertIn("RUNTIME-GATE: subagent", content)
        self.assertNotIn("subagent_type=", content)
        self.assertNotIn("model=", content)
        self.assertNotIn("description=", content)

    def test_pi_agent_rewrite_skips_empty_prose_but_rewrites_real_calls(self) -> None:
        from runtime.drivers.pi.export import _rewrite_body

        body = textwrap.dedent("""\
        <!-- RUNTIME-GATE: subagent; non-supporting drivers must surface this
             requirement to the user and skip the Agent() call. -->
        | `subagent` | yes | Phase 3 reviewer Agent() calls |
        - Agent(subagent_type="doc-fetcher", description="Doc context", prompt="...")
        CURATOR_RETURN="$(Agent(
          subagent_type="context-curator",
          description="Context curation",
          prompt="..."
        ))"
        """)

        rewritten = _rewrite_body(body, {"doc-fetcher", "context-curator"})

        self.assertIn("skip the Agent() call", rewritten)
        self.assertIn("Phase 3 reviewer Agent() calls", rewritten)
        self.assertIn('> [pi] Use the subagent tool: { "agent": "doc-fetcher"', rewritten)
        self.assertIn("> [pi] Dispatch a subagent here via the subagent tool", rewritten)
        self.assertNotIn('CURATOR_RETURN="$(Agent(', rewritten)

    @unittest.skipUnless(
        (REPO_ROOT / ".git").is_dir(),
        "install.sh is_repo_clone() requires .git to be a directory; in a git worktree "
        ".git is a file, so this test only runs on a normal clone (see LEDGER, T020)",
    )
    def test_pi_preserves_gate_comments_with_legacy_line_based_agent_args(self) -> None:
        content = self._rendered(
            "runtime.drivers.pi.export",
            ("prompts", "z-audit-plan-style.md"),
        )
        self.assertIn("RUNTIME-GATE: subagent", content)
        self.assertIn("requirement to the user and skip the Agent() call.", content)
        self.assertIn("> [pi] Dispatch a subagent here via the subagent tool", content)
        self.assertIn('subagent_type="plan-style-reviewer"', content)
        self.assertIn('model="sonnet"', content)
        self.assertIn('description="Plan-style review for <Z_HARNESS_SLUG>"', content)

if __name__ == "__main__":
    unittest.main()
