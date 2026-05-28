"""
Unit tests for the per-target persona export adapters.

Covers all four targets (antigravity, cursor, codex, claude) via a shared
round-trip fixture.  Each test verifies:
- The output file is written to the expected path.
- The persona name appears in the output file.
- The persona body is preserved verbatim.
- The portability header is present and contains the expected native flag.

Run with:
    python -m pytest runtime/tests/test_persona_export.py -v
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from runtime.drivers.antigravity.persona_export import export_persona as agy_export
from runtime.drivers.cursor.persona_export import export_persona as cursor_export
from runtime.drivers.codex.persona_export import export_persona as codex_export
from runtime.drivers.claude.persona_export import export_persona as claude_export


# ---------------------------------------------------------------------------
# Sample persona fixture
# ---------------------------------------------------------------------------

SAMPLE_PERSONA_CONTENT = textwrap.dedent("""\
    ---
    name: test-persona
    description: A minimal test persona for round-trip checks.
    compatible_roles: [consultant_primary]
    contract: freeform
    ---

    You are a test persona.  Your sole purpose is to verify that export
    adapters preserve this body text exactly.

    ## Rules
    - Always say hello.
    - Never say goodbye.
""")

PERSONA_NAME = "test-persona"
PERSONA_BODY_FRAGMENT = "You are a test persona."


@pytest.fixture
def persona_file(tmp_path: Path) -> Path:
    """Write the sample persona to a temp file and return its path."""
    p = tmp_path / "test-persona.md"
    p.write_text(SAMPLE_PERSONA_CONTENT, encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# Shared assertion helpers
# ---------------------------------------------------------------------------


def _assert_portability_header(content: str, target: str, expected_native: str) -> None:
    """Assert that the portability header block is present and correct."""
    assert "<!-- persona-export: portability header -->" in content, (
        f"{target}: missing portability header comment"
    )
    assert f"<!-- target:  {target} -->" in content, (
        f"{target}: wrong or missing target line in portability header"
    )
    assert f"<!-- native:  {expected_native} -->" in content, (
        f"{target}: wrong or missing native flag in portability header"
    )


def _assert_body_preserved(content: str, target: str) -> None:
    """Assert that the persona body fragment is present in the output."""
    assert PERSONA_BODY_FRAGMENT in content, (
        f"{target}: persona body not preserved in output"
    )


def _assert_name_present(content: str, target: str) -> None:
    """Assert that the persona name appears somewhere in the output."""
    assert PERSONA_NAME in content, (
        f"{target}: persona name '{PERSONA_NAME}' missing from output"
    )


# ---------------------------------------------------------------------------
# Antigravity (agy) tests
# ---------------------------------------------------------------------------


class TestAntígravityExport:

    def test_output_path(self, persona_file: Path, tmp_path: Path) -> None:
        """agy: output lands at .agent/personas/<name>.md."""
        export_root = tmp_path / "export"
        result = agy_export(persona_file, export_root)
        expected = export_root / ".agent" / "personas" / f"{PERSONA_NAME}.md"
        assert result == expected.resolve()
        assert result.exists()

    def test_portability_header_native(self, persona_file: Path, tmp_path: Path) -> None:
        """agy: portability header declares native: yes."""
        result = agy_export(persona_file, tmp_path / "export")
        content = result.read_text(encoding="utf-8")
        _assert_portability_header(content, target="antigravity", expected_native="yes")

    def test_body_preserved(self, persona_file: Path, tmp_path: Path) -> None:
        """agy: persona body text is present verbatim in output."""
        result = agy_export(persona_file, tmp_path / "export")
        content = result.read_text(encoding="utf-8")
        _assert_body_preserved(content, target="antigravity")

    def test_name_in_output(self, persona_file: Path, tmp_path: Path) -> None:
        """agy: persona name appears in output content."""
        result = agy_export(persona_file, tmp_path / "export")
        content = result.read_text(encoding="utf-8")
        _assert_name_present(content, target="antigravity")

    def test_frontmatter_preserved(self, persona_file: Path, tmp_path: Path) -> None:
        """agy: frontmatter fields are preserved in output."""
        result = agy_export(persona_file, tmp_path / "export")
        content = result.read_text(encoding="utf-8")
        assert "compatible_roles" in content
        assert "contract: freeform" in content


# ---------------------------------------------------------------------------
# Cursor tests
# ---------------------------------------------------------------------------


class TestCursorExport:

    def test_output_path(self, persona_file: Path, tmp_path: Path) -> None:
        """cursor: output lands at .cursor/personas/<name>.mdc."""
        export_root = tmp_path / "export"
        result = cursor_export(persona_file, export_root)
        expected = export_root / ".cursor" / "personas" / f"{PERSONA_NAME}.mdc"
        assert result == expected.resolve()
        assert result.exists()

    def test_portability_header_not_native(self, persona_file: Path, tmp_path: Path) -> None:
        """cursor: portability header declares native: no."""
        result = cursor_export(persona_file, tmp_path / "export")
        content = result.read_text(encoding="utf-8")
        _assert_portability_header(content, target="cursor", expected_native="no")

    def test_body_preserved(self, persona_file: Path, tmp_path: Path) -> None:
        """cursor: persona body text is present verbatim in output."""
        result = cursor_export(persona_file, tmp_path / "export")
        content = result.read_text(encoding="utf-8")
        _assert_body_preserved(content, target="cursor")

    def test_name_in_output(self, persona_file: Path, tmp_path: Path) -> None:
        """cursor: persona name appears in output content."""
        result = cursor_export(persona_file, tmp_path / "export")
        content = result.read_text(encoding="utf-8")
        _assert_name_present(content, target="cursor")

    def test_mdc_rule_header(self, persona_file: Path, tmp_path: Path) -> None:
        """cursor: output includes a glob-based MDC rule header."""
        result = cursor_export(persona_file, tmp_path / "export")
        content = result.read_text(encoding="utf-8")
        assert 'globs:' in content
        assert '"**/*"' in content
        assert 'alwaysApply: true' in content

    def test_missing_frontmatter_raises(self, tmp_path: Path) -> None:
        """cursor: persona file without frontmatter raises ValueError."""
        bad = tmp_path / "bad.md"
        bad.write_text("No frontmatter here.\n", encoding="utf-8")
        with pytest.raises(ValueError, match="no YAML frontmatter"):
            cursor_export(bad, tmp_path / "export")


# ---------------------------------------------------------------------------
# Codex tests
# ---------------------------------------------------------------------------


class TestCodexExport:

    def test_output_path(self, persona_file: Path, tmp_path: Path) -> None:
        """codex: output lands at prompts/personas/<name>.md."""
        export_root = tmp_path / "export"
        result = codex_export(persona_file, export_root)
        expected = export_root / "prompts" / "personas" / f"{PERSONA_NAME}.md"
        assert result == expected.resolve()
        assert result.exists()

    def test_portability_header_not_native(self, persona_file: Path, tmp_path: Path) -> None:
        """codex: portability header declares native: no."""
        result = codex_export(persona_file, tmp_path / "export")
        content = result.read_text(encoding="utf-8")
        _assert_portability_header(content, target="codex", expected_native="no")

    def test_body_preserved(self, persona_file: Path, tmp_path: Path) -> None:
        """codex: persona body text is present verbatim in output."""
        result = codex_export(persona_file, tmp_path / "export")
        content = result.read_text(encoding="utf-8")
        _assert_body_preserved(content, target="codex")

    def test_flat_header(self, persona_file: Path, tmp_path: Path) -> None:
        """codex: output starts with flat '# Persona: <name>' header."""
        result = codex_export(persona_file, tmp_path / "export")
        content = result.read_text(encoding="utf-8")
        assert f"# Persona: {PERSONA_NAME}" in content

    def test_missing_name_raises(self, tmp_path: Path) -> None:
        """codex: persona file missing name: key raises ValueError."""
        bad = tmp_path / "bad.md"
        bad.write_text("---\ndescription: No name\n---\nBody here.\n", encoding="utf-8")
        with pytest.raises(ValueError, match="missing required 'name:'"):
            codex_export(bad, tmp_path / "export")


# ---------------------------------------------------------------------------
# Claude tests
# ---------------------------------------------------------------------------


class TestClaudeExport:

    def test_output_path(self, persona_file: Path, tmp_path: Path) -> None:
        """claude: output lands at personas/<name>.md."""
        export_root = tmp_path / "export"
        result = claude_export(persona_file, export_root)
        expected = export_root / "personas" / f"{PERSONA_NAME}.md"
        assert result == expected.resolve()
        assert result.exists()

    def test_portability_header_not_native(self, persona_file: Path, tmp_path: Path) -> None:
        """claude: portability header declares native: no."""
        result = claude_export(persona_file, tmp_path / "export")
        content = result.read_text(encoding="utf-8")
        _assert_portability_header(content, target="claude", expected_native="no")

    def test_body_preserved(self, persona_file: Path, tmp_path: Path) -> None:
        """claude: persona body text is present verbatim in output."""
        result = claude_export(persona_file, tmp_path / "export")
        content = result.read_text(encoding="utf-8")
        _assert_body_preserved(content, target="claude")

    def test_name_in_output(self, persona_file: Path, tmp_path: Path) -> None:
        """claude: persona name appears in output content."""
        result = claude_export(persona_file, tmp_path / "export")
        content = result.read_text(encoding="utf-8")
        _assert_name_present(content, target="claude")

    def test_frontmatter_preserved(self, persona_file: Path, tmp_path: Path) -> None:
        """claude: frontmatter fields are preserved in output."""
        result = claude_export(persona_file, tmp_path / "export")
        content = result.read_text(encoding="utf-8")
        assert "compatible_roles" in content
        assert "contract: freeform" in content


# ---------------------------------------------------------------------------
# Cross-adapter: all four output paths exist
# ---------------------------------------------------------------------------


class TestAllFourTargets:

    def test_all_four_output_paths_exist(self, persona_file: Path, tmp_path: Path) -> None:
        """All four adapters produce distinct output files under the same export root."""
        export_root = tmp_path / "export"

        agy_path = agy_export(persona_file, export_root)
        cursor_path = cursor_export(persona_file, export_root)
        codex_path = codex_export(persona_file, export_root)
        claude_path = claude_export(persona_file, export_root)

        assert agy_path.exists(), "agy output missing"
        assert cursor_path.exists(), "cursor output missing"
        assert codex_path.exists(), "codex output missing"
        assert claude_path.exists(), "claude output missing"

        # All four paths must be distinct.
        all_paths = {agy_path, cursor_path, codex_path, claude_path}
        assert len(all_paths) == 4, "Two or more adapters wrote to the same path"

    def test_all_four_paths_match_expected(self, persona_file: Path, tmp_path: Path) -> None:
        """Verify the exact expected path for each target."""
        export_root = tmp_path / "export"

        assert agy_export(persona_file, export_root) == (
            export_root / ".agent" / "personas" / f"{PERSONA_NAME}.md"
        ).resolve()
        assert cursor_export(persona_file, export_root) == (
            export_root / ".cursor" / "personas" / f"{PERSONA_NAME}.mdc"
        ).resolve()
        assert codex_export(persona_file, export_root) == (
            export_root / "prompts" / "personas" / f"{PERSONA_NAME}.md"
        ).resolve()
        assert claude_export(persona_file, export_root) == (
            export_root / "personas" / f"{PERSONA_NAME}.md"
        ).resolve()
