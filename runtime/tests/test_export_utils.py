"""
runtime/tests/test_export_utils.py

Tests for runtime/drivers/_export_utils.py.

Ports the assertions from:
  - scripts/export-common.py --self-test (all 5 cases)
  - tests/test_export_common_self_test.py (fenced_marker_preserved, path_escape_rejected)

Cases covered:
  test_run_self_test_passes           — run_self_test() returns 0 against the real repo
  test_include_inline                 — a whole-line include marker is expanded
  test_fence_skip_backtick            — marker inside ``` fence is NOT expanded
  test_fence_skip_tilde               — marker inside ~~~ fence is NOT expanded
  test_missing_fragment               — missing fragment raises FileNotFoundError
  test_path_escape                    — escaping repo root raises ValueError
  test_circular_include               — A -> B -> A raises ValueError

  test_enumerate_sources_keys         — enumerate_sources returns required keys
  test_validate_capabilities_valid    — valid CAPABILITIES.md returns no errors
  test_validate_capabilities_missing  — missing required section is reported
  test_export_result_dataclass        — ExportResult has correct fields
  test_no_z_harness_cli_imports       — _export_utils.py has zero z_harness_cli imports
  test_inline_includes_alias          — inline_includes produces same output as expand_includes
  test_output_path_for_cursor         — output_path_for returns expected cursor path
  test_output_path_for_codex          — output_path_for returns expected codex path
  test_output_path_for_unknown_target — ValueError on unknown target
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

import pytest

from runtime.drivers._export_utils import (
    ExportResult,
    expand_includes,
    inline_includes,
    enumerate_sources,
    validate_capabilities,
    output_path_for,
    run_self_test,
    _next_include_match,
    _RUN_BRIEF_FRAGMENT,
    _RUN_BRIEF_MARKER,
    _RUN_BRIEF_SENTINEL,
)

# The worktree root — used for tests that rely on real repo fixtures
# (run-brief-finalize.md, commands/_fragments/).
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent


# ---------------------------------------------------------------------------
# Self-test suite (ports scripts/export-common.py --self-test cases)
# ---------------------------------------------------------------------------

class TestRunSelfTest:
    def test_run_self_test_passes(self):
        """run_self_test() must return 0 when run against the real repo."""
        result = run_self_test(_REPO_ROOT)
        assert result == 0, "run_self_test() did not return 0 — see stderr output above"


class TestIncludeInline:
    """include-inline: a whole-line marker is replaced by the fragment body."""

    def test_include_inline(self):
        sample = f"Before marker\n{_RUN_BRIEF_MARKER}\nAfter marker\n"
        expanded = expand_includes(sample, _REPO_ROOT)
        # The marker itself must be gone
        assert _next_include_match(expanded) is None, (
            "standalone include marker still present after expansion"
        )
        # The well-known sentinel from the fragment must appear
        assert _RUN_BRIEF_SENTINEL in expanded, (
            f"expected sentinel {_RUN_BRIEF_SENTINEL!r} missing from expanded body"
        )

    def test_inline_includes_alias_matches_expand(self):
        """inline_includes(text, None, repo_root) must return the same result as
        expand_includes(text, repo_root)."""
        sample = f"Before\n{_RUN_BRIEF_MARKER}\nAfter\n"
        via_expand = expand_includes(sample, _REPO_ROOT)
        via_inline = inline_includes(sample, None, _REPO_ROOT)
        assert via_expand == via_inline


class TestFenceSkip:
    """fence-skip: markers inside fenced code blocks are preserved verbatim."""

    def test_fence_skip_backtick(self):
        fenced = f"```markdown\n{_RUN_BRIEF_MARKER}\n```\n"
        expanded = expand_includes(fenced, _REPO_ROOT)
        assert _RUN_BRIEF_MARKER in expanded, (
            "marker inside ``` fence was removed instead of preserved"
        )
        assert _RUN_BRIEF_SENTINEL not in expanded, (
            "fragment body was inlined from a fenced marker"
        )

    def test_fence_skip_tilde(self):
        fenced = f"~~~markdown\n{_RUN_BRIEF_MARKER}\n~~~\n"
        expanded = expand_includes(fenced, _REPO_ROOT)
        assert _RUN_BRIEF_MARKER in expanded, (
            "marker inside ~~~ fence was removed instead of preserved"
        )
        assert _RUN_BRIEF_SENTINEL not in expanded, (
            "fragment body was inlined from a tilde-fenced marker"
        )

    def test_fence_skip_four_backtick(self):
        """Ensure 4+ backtick fences are also detected (regression from test_export_common)."""
        marker = "<!-- include: commands/_fragments/run-brief-finalize.md -->"
        fenced = f"````\n{marker}\n````\n"
        expanded = expand_includes(fenced, _REPO_ROOT)
        assert marker in expanded
        assert _RUN_BRIEF_SENTINEL not in expanded


class TestMissingFragment:
    """missing-fragment: non-existent fragment raises FileNotFoundError."""

    def test_missing_fragment(self):
        with pytest.raises(FileNotFoundError):
            expand_includes(
                "<!-- include: commands/_fragments/does-not-exist.md -->\n",
                _REPO_ROOT,
            )


class TestPathEscape:
    """path-escape: a path that escapes repo_root raises ValueError."""

    def test_path_escape_rejected(self):
        with pytest.raises(ValueError):
            expand_includes(
                "<!-- include: ../../../etc/passwd -->\n",
                _REPO_ROOT,
            )


class TestCircularInclude:
    """circular-include: A -> B -> A raises ValueError."""

    def test_circular_include(self, tmp_path):
        # Cycle fragments must live under repo_root (path-escape guard).
        fragments_dir = _REPO_ROOT / "commands" / "_fragments"
        cycle_dir = Path(
            tempfile.mkdtemp(prefix=".test-cycle-", dir=fragments_dir)
        )
        try:
            cycle_a = cycle_dir / "a.md"
            cycle_b = cycle_dir / "b.md"
            rel_a = f"{cycle_dir.relative_to(_REPO_ROOT).as_posix()}/a.md"
            rel_b = f"{cycle_dir.relative_to(_REPO_ROOT).as_posix()}/b.md"
            cycle_a.write_text(f"<!-- include: {rel_b} -->\n", encoding="utf-8")
            cycle_b.write_text(f"<!-- include: {rel_a} -->\n", encoding="utf-8")
            with pytest.raises(ValueError, match="[Cc]ircular"):
                expand_includes(
                    f"<!-- include: {rel_a} -->\n",
                    _REPO_ROOT,
                )
        finally:
            shutil.rmtree(cycle_dir, ignore_errors=True)


# ---------------------------------------------------------------------------
# enumerate_sources
# ---------------------------------------------------------------------------

class TestEnumerateSources:
    def test_enumerate_sources_keys(self):
        """enumerate_sources must return a dict with exactly the three expected keys."""
        sources = enumerate_sources(_REPO_ROOT)
        assert set(sources.keys()) == {"commands", "agents", "skills"}

    def test_enumerate_sources_commands_non_empty(self):
        """commands list must be non-empty in this repo."""
        sources = enumerate_sources(_REPO_ROOT)
        assert len(sources["commands"]) > 0, "Expected at least one command source"

    def test_enumerate_sources_entry_shape(self):
        """Each entry must have id, source_path, frontmatter, body."""
        sources = enumerate_sources(_REPO_ROOT)
        for kind in ("commands", "agents", "skills"):
            for entry in sources[kind]:
                assert "id" in entry
                assert "source_path" in entry
                assert "frontmatter" in entry
                assert "body" in entry
                assert isinstance(entry["source_path"], Path)


# ---------------------------------------------------------------------------
# validate_capabilities
# ---------------------------------------------------------------------------

class TestValidateCapabilities:
    def test_valid_file(self, tmp_path):
        cap = tmp_path / "CAPABILITIES.md"
        cap.write_text(
            "## Supported\nfoo\n## Unsupported\nbar\n## Notes\nbaz\n",
            encoding="utf-8",
        )
        errors = validate_capabilities(cap)
        assert errors == []

    def test_missing_section(self, tmp_path):
        cap = tmp_path / "CAPABILITIES.md"
        cap.write_text("## Supported\nfoo\n## Unsupported\nbar\n", encoding="utf-8")
        errors = validate_capabilities(cap)
        assert any("Notes" in e for e in errors), (
            f"Expected a 'Notes' error, got: {errors}"
        )

    def test_file_not_found(self, tmp_path):
        errors = validate_capabilities(tmp_path / "nonexistent.md")
        assert any("not found" in e.lower() or "File not found" in e for e in errors)

    def test_all_sections_missing(self, tmp_path):
        cap = tmp_path / "CAPABILITIES.md"
        cap.write_text("# Nothing here\n", encoding="utf-8")
        errors = validate_capabilities(cap)
        assert len(errors) == 3, f"Expected 3 errors, got {errors}"


# ---------------------------------------------------------------------------
# ExportResult dataclass
# ---------------------------------------------------------------------------

class TestExportResultDataclass:
    def test_export_result_fields(self):
        r = ExportResult(dest=Path("/tmp/out"))
        assert r.dest == Path("/tmp/out")
        assert r.files == []
        assert r.fidelity == "flattened"
        assert r.warnings == []

    def test_export_result_with_values(self):
        r = ExportResult(
            dest=Path("/tmp/out"),
            files=[Path("/tmp/out/a.md")],
            fidelity="high",
            warnings=["w1"],
        )
        assert r.files == [Path("/tmp/out/a.md")]
        assert r.fidelity == "high"
        assert r.warnings == ["w1"]

    def test_export_result_is_mutable(self):
        """files and warnings must be separate mutable lists per instance."""
        r1 = ExportResult(dest=Path("/a"))
        r2 = ExportResult(dest=Path("/b"))
        r1.files.append(Path("/a/x.md"))
        assert r2.files == [], "ExportResult instances share mutable default list"


# ---------------------------------------------------------------------------
# output_path_for
# ---------------------------------------------------------------------------

class TestOutputPathFor:
    def test_cursor_command(self):
        p = output_path_for(Path("/repo"), "cursor", "commands", "z-plan")
        assert p == Path("/repo/exports/cursor/.cursor/rules/z-plan.mdc")

    def test_codex_skill(self):
        p = output_path_for(Path("/repo"), "codex", "skills", "z-debug")
        assert p == Path("/repo/exports/codex/prompts/z-debug.md")

    def test_unknown_target_raises(self):
        with pytest.raises(ValueError, match="Unknown target"):
            output_path_for(Path("/repo"), "agy", "commands", "z-plan")

    def test_unknown_kind_raises(self):
        with pytest.raises(ValueError, match="Unknown kind"):
            output_path_for(Path("/repo"), "cursor", "personas", "zeke")


# ---------------------------------------------------------------------------
# Zero z_harness_cli imports guard
# ---------------------------------------------------------------------------

class TestNoZHarnessCLIImports:
    def test_no_z_harness_cli_imports(self):
        """_export_utils.py must contain zero actual 'z_harness_cli' import statements.

        Matches only lines that are real Python import statements
        (``import z_harness_cli`` or ``from z_harness_cli``), ignoring
        docstring text that mentions the package name.
        """
        import re as _re
        src = Path(__file__).resolve().parent.parent / "drivers" / "_export_utils.py"
        text = src.read_text(encoding="utf-8")
        # Match actual Python import syntax only (not docstring prose).
        pattern = _re.compile(
            r"^\s*(?:import\s+z_harness_cli|from\s+z_harness_cli\b)"
        )
        import_lines = [
            line for line in text.splitlines()
            if pattern.match(line)
        ]
        assert import_lines == [], (
            f"_export_utils.py has forbidden z_harness_cli import(s):\n"
            + "\n".join(import_lines)
        )
