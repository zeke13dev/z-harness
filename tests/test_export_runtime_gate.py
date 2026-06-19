"""
T015: Beyond-grep export verification for z-attend RUNTIME-GATE tokens.

Tests:
1. RUNTIME-GATE category= token survival across all 4 export surfaces: a fixture
   command carrying a ``<!-- RUNTIME-GATE: ask_user; category=risk ... -->``
   comment must have the ``category=risk`` token present in every rendered output.
   Grep alone false-passes if ``z-attend`` appears elsewhere but the token was
   accidentally stripped — this test runs the actual export parser on a controlled
   fixture and asserts the token is in the rendered result.

2. Codex frontmatter load: z-attend.md's frontmatter must be parsed by the
   enumerate_sources / _parse_frontmatter pipeline and the resulting entry's
   description must be non-empty (proves the file was not silently dropped).
   The codex exporter then includes z-attend in its prompt files — verified by
   checking the emitted file's header line starts with ``# /z-attend``.

3. Live export z-attend presence: run the actual codex export against the real
   repo root; the emitted prompts/z-attend.md must exist AND contain
   ``category=risk`` (proving the live pipeline, not just the fixture).
"""

from __future__ import annotations

import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(REPO_ROOT))

from runtime.drivers._export_utils import enumerate_sources, _parse_frontmatter  # noqa: E402


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

def _make_fixture_repo(tmp: Path) -> Path:
    """Create a minimal fixture repo with one skill carrying a RUNTIME-GATE comment."""
    repo = tmp / "fixture_repo"
    agents_dir = repo / "agents"
    agents_dir.mkdir(parents=True)

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

        ## Phase 1 — main body

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
    exporter must emit prompts/z-attend.md whose first line is '# /z-attend'.

    Failure class: if SKILL.md has malformed frontmatter that causes
    _parse_frontmatter to silently skip it, or if enumerate_sources drops it,
    the description would be empty and the codex prompt would be missing.
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

    def test_codex_emits_z_attend_prompt_with_correct_header(self) -> None:
        """Codex export must emit prompts/z-attend.md with '# /z-attend' as first line.

        This verifies the full pipeline: enumerate_sources picks up z-attend in
        the skills tier, _render_prompt runs on it, and the output starts with
        the correct header.
        """
        from runtime.drivers.codex.export import _render_prompt

        sources = enumerate_sources(REPO_ROOT)
        attend_entries = [e for e in sources["skills"] if e["id"] == "z-attend"]
        self.assertTrue(attend_entries, "z-attend not in enumerate_sources skills")

        entry = attend_entries[0]
        rendered = _render_prompt(entry)
        first_line = rendered.splitlines()[0] if rendered.strip() else ""

        self.assertEqual(
            first_line,
            "# /z-attend",
            f"codex prompt for z-attend has wrong header line. Got: {first_line!r}",
        )

    def test_codex_z_attend_prompt_contains_category_risk(self) -> None:
        """Codex-rendered z-attend prompt must contain 'category=risk' token.

        This is the full-pipeline BEYOND-GREP assertion: z-attend carries
        RUNTIME-GATE comments with category=risk; the codex renderer must not
        strip them.
        """
        from runtime.drivers.codex.export import _render_prompt

        sources = enumerate_sources(REPO_ROOT)
        attend_entries = [e for e in sources["skills"] if e["id"] == "z-attend"]
        self.assertTrue(attend_entries, "z-attend not found in enumerate_sources skills")

        entry = attend_entries[0]
        rendered = _render_prompt(entry)

        self.assertIn(
            "category=risk",
            rendered,
            "codex _render_prompt stripped 'category=risk' token from z-attend — "
            "RUNTIME-GATE comments are being incorrectly rewritten",
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
        """Codex export must produce prompts/z-attend.md with category=risk."""
        self._run_and_verify(
            "runtime.drivers.codex.export",
            ("prompts", "z-attend.md"),
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


if __name__ == "__main__":
    unittest.main()
