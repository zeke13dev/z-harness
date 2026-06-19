"""
Tests for scripts/build-skill-index.py

Cases covered:
  exact_line_format           — each output line is exactly `/name` — description (no table)
  no_table_headers            — output must NOT contain markdown table separators or header row
  ordering_stable             — two calls to build_skill_index return byte-identical output
  ordering_is_alphabetical    — lines are sorted alpha (casefold) by name
  case_only_tie_total_order   — uppercase variant before lowercase when casefolded the same
  unsorted_filenames          — alpha ordering holds regardless of filesystem crawl order
  duplicate_collapse          — same-named skills collapse to one row
  command_description_wins    — when two skills share a name, the first alphabetically wins
  skills_included             — skills/*/SKILL.md entries appear in output
  skill_missing_file_skipped  — skill dir without SKILL.md is silently skipped
  empty_dirs                  — missing commands/ and skills/ dirs produce empty output (no crash)
  custom_repo_root            — --repo-root flag is respected
  real_repo_smoke             — a known skill appears with correct format in real repo
  multiline_yaml_fails_fast   — folded/literal block description raises ValueError (not garbage)
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SCRIPT = str(_REPO_ROOT / "scripts" / "build-skill-index.py")


# ---------------------------------------------------------------------------
# Import the module directly for unit-level tests
# ---------------------------------------------------------------------------

def _load_module():
    spec = importlib.util.spec_from_file_location(
        "build_skill_index", _SCRIPT
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_mod = _load_module()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_command(commands_dir: Path, stem: str, name: str, description: str) -> Path:
    """Write a minimal command .md file with frontmatter."""
    commands_dir.mkdir(parents=True, exist_ok=True)
    fm_lines = ["---", f"description: {description}"]
    if name:
        fm_lines.append(f"name: {name}")
    fm_lines += ["---", "", f"Body for {stem}.", ""]
    path = commands_dir / f"{stem}.md"
    path.write_text("\n".join(fm_lines), encoding="utf-8")
    return path


def _write_skill(skills_dir: Path, skill_name: str, description: str,
                 frontmatter_name: str | None = None) -> Path:
    """Write a minimal SKILL.md in skills/<skill_name>/SKILL.md."""
    skill_dir = skills_dir / skill_name
    skill_dir.mkdir(parents=True, exist_ok=True)
    fm_name = frontmatter_name if frontmatter_name is not None else skill_name
    fm_lines = ["---", f"name: {fm_name}", f"description: {description}"]
    fm_lines += ["---", "", f"Skill body for {skill_name}.", ""]
    path = skill_dir / "SKILL.md"
    path.write_text("\n".join(fm_lines), encoding="utf-8")
    return path


def _run_script(extra_args: list[str] | None = None) -> subprocess.CompletedProcess:
    """Run the script as a subprocess against the real repo root."""
    cmd = [sys.executable, _SCRIPT] + (extra_args or [])
    return subprocess.run(cmd, capture_output=True, text=True)


def _parse_lines(output: str) -> list[str]:
    """Return non-empty lines from output."""
    return [l for l in output.splitlines() if l.strip()]


# ---------------------------------------------------------------------------
# Tests: exact line format
# ---------------------------------------------------------------------------

class TestExactLineFormat(unittest.TestCase):
    """Each output line must be exactly: `backtick-wrapped name` — description."""

    def test_exact_format_two_entries(self):
        """Synthetic repo with two skills produces exact expected output."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_skill(root / "skills", "z-alpha", "Alpha does alpha things",
                         frontmatter_name="/z-alpha")
            _write_skill(root / "skills", "z-beta", "Beta does beta things",
                         frontmatter_name="/z-beta")

            result = _mod.build_skill_index(root)
            expected = "`/z-alpha` — Alpha does alpha things\n`/z-beta` — Beta does beta things\n"
            self.assertEqual(result, expected,
                             msg=f"Exact output mismatch.\nExpected:\n{expected!r}\nGot:\n{result!r}")

    def test_no_table_headers_or_separators(self):
        """Output must not contain markdown table headers or separator rows."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_skill(root / "skills", "z-cmd", "A command", frontmatter_name="/z-cmd")
            result = _mod.build_skill_index(root)
            self.assertNotIn("|", result, msg="Output must not contain pipe characters (no table)")
            self.assertNotIn("---", result, msg="Output must not contain table separator rows")
            self.assertNotIn("argument-hint", result,
                             msg="argument-hint must not appear in output")

    def test_backtick_wrapping_present(self):
        """Each line must start with a backtick-wrapped command name."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_skill(root / "skills", "z-thing", "Does a thing",
                         frontmatter_name="/z-thing")
            result = _mod.build_skill_index(root)
            lines = _parse_lines(result)
            self.assertEqual(len(lines), 1)
            self.assertTrue(lines[0].startswith("`/z-thing`"),
                            msg=f"Line must start with `/z-thing` wrapped in backticks: {lines[0]!r}")
            self.assertIn(" — ", lines[0],
                          msg=f"Line must contain ' — ' em-dash separator: {lines[0]!r}")

    def test_leading_slash_always_present(self):
        """Names without a leading / in frontmatter are normalized to have one."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            # Write a skill whose dir name has no leading slash — _crawl_skills
            # uses skill_dir.name as the raw_name, which _normalize_name prefixes with /
            skills_dir = root / "skills"
            skills_dir.mkdir(parents=True)
            skill_dir = skills_dir / "z-noslash"
            skill_dir.mkdir()
            (skill_dir / "SKILL.md").write_text(
                "---\ndescription: No slash in name\n---\nBody\n", encoding="utf-8"
            )
            result = _mod.build_skill_index(root)
            self.assertIn("`/z-noslash`", result,
                          msg="Name must be normalized to have a leading /")


# ---------------------------------------------------------------------------
# Tests: ordering
# ---------------------------------------------------------------------------

class TestOrderingStable(unittest.TestCase):
    """Two calls to build_skill_index must produce byte-identical output."""

    def test_two_calls_identical(self):
        result1 = _mod.build_skill_index(_REPO_ROOT)
        result2 = _mod.build_skill_index(_REPO_ROOT)
        self.assertEqual(result1, result2,
                         msg="build_skill_index must be deterministic")

    def test_subprocess_two_runs_identical(self):
        r1 = _run_script()
        r2 = _run_script()
        self.assertEqual(r1.returncode, 0, msg=r1.stderr)
        self.assertEqual(r2.returncode, 0, msg=r2.stderr)
        self.assertEqual(r1.stdout, r2.stdout,
                         msg="Two subprocess runs must produce byte-identical stdout")


class TestAlphaOrdering(unittest.TestCase):
    """Entries must be in ascending alphabetical (casefold) order by name."""

    def test_unsorted_filenames_still_sorted_output(self):
        """Skill dirs created in reverse order must produce alpha-sorted output."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            # Write in reverse alphabetical order on disk (skill dirs)
            _write_skill(root / "skills", "z-zebra", "Zebra command",
                         frontmatter_name="/z-zebra")
            _write_skill(root / "skills", "z-middle", "Middle command",
                         frontmatter_name="/z-middle")
            _write_skill(root / "skills", "a-alpha", "Alpha command",
                         frontmatter_name="/a-alpha")

            result = _mod.build_skill_index(root)
            lines = _parse_lines(result)
            self.assertEqual(len(lines), 3)
            # Extract names from backtick-wrapped portion
            names = [l.split("`")[1] for l in lines]
            self.assertEqual(names, sorted(names, key=lambda n: n.casefold()),
                             msg=f"Lines not in alpha order: {names}")

    def test_real_repo_names_sorted(self):
        """Real repo output lines must be in alphabetical (casefold) order."""
        result = _mod.build_skill_index(_REPO_ROOT)
        lines = _parse_lines(result)
        names = [l.split("`")[1] for l in lines if l.startswith("`")]
        sorted_names = sorted(names, key=lambda n: n.casefold())
        self.assertEqual(names, sorted_names,
                         msg=f"Real repo output is not alpha-sorted: {names}")


class TestCaseOnlyTieTotalOrder(unittest.TestCase):
    """When two names differ only by case, total order must be stable and deterministic."""

    def test_case_only_tie_order(self):
        """Skills whose casefolded names are equal must have a stable secondary order."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            # Two skills whose names differ only by case — casefold ties
            skills_dir = root / "skills"
            _write_skill(skills_dir, "z-cmd-lower", "Lower variant", frontmatter_name="z-cmd")
            _write_skill(skills_dir, "z-cmd-upper", "Upper variant", frontmatter_name="Z-cmd")

            result1 = _mod.build_skill_index(root)
            result2 = _mod.build_skill_index(root)
            # Must be identical on two calls (stability, not just ordering)
            self.assertEqual(result1, result2,
                             msg="Case-only tie ordering must be stable across calls")

            lines = _parse_lines(result1)
            self.assertEqual(len(lines), 2, msg=f"Expected 2 lines, got: {lines}")
            # Both lines must be present
            names = [l.split("`")[1] for l in lines]
            self.assertIn("/z-cmd", names)
            self.assertIn("/Z-cmd", names)
            # Secondary sort key is original name string; ord('Z')=90 < ord('z')=122
            # so /Z-cmd sorts before /z-cmd in ASCII order
            self.assertEqual(names[0], "/Z-cmd",
                             msg=f"Expected /Z-cmd before /z-cmd (uppercase ASCII < lowercase); got {names}")


# ---------------------------------------------------------------------------
# Tests: duplicate collapse
# ---------------------------------------------------------------------------

class TestDuplicateCollapse(unittest.TestCase):
    """Two skill dirs sharing the same frontmatter name collapse to one row."""

    def test_command_and_skill_same_name_one_row(self):
        """Two skill dirs with the same frontmatter name produce one row."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_skill(root / "skills", "z-plan-a", "First description wins",
                         frontmatter_name="/z-plan")
            _write_skill(root / "skills", "z-plan-b", "Second description loses",
                         frontmatter_name="/z-plan")

            result = _mod.build_skill_index(root)
            lines = _parse_lines(result)
            self.assertEqual(len(lines), 1,
                             msg=f"Duplicate /z-plan must collapse to one row; got {lines}")

    def test_command_description_wins_over_skill(self):
        """When two skill dirs share a name, the first encountered (alphabetically) wins."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            # z-dup-a sorts before z-dup-b so its description is first-seen
            _write_skill(root / "skills", "z-dup-a", "First description",
                         frontmatter_name="/z-dup")
            _write_skill(root / "skills", "z-dup-b", "Second description",
                         frontmatter_name="/z-dup")

            result = _mod.build_skill_index(root)
            self.assertIn("First description", result,
                          msg="First-encountered (alphabetically) description must win")
            self.assertNotIn("Second description", result,
                             msg="Duplicate description must be suppressed")

    def test_skill_description_used_when_command_empty(self):
        """When the first-seen skill has no description, the second's description fills in."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            # z-nodesc-a sorts first; its SKILL.md has an empty description
            skill_dir_a = root / "skills" / "z-nodesc-a"
            skill_dir_a.mkdir(parents=True)
            (skill_dir_a / "SKILL.md").write_text(
                "---\nname: /z-nodesc\ndescription: \n---\nBody\n", encoding="utf-8"
            )
            _write_skill(root / "skills", "z-nodesc-b", "Skill fills in",
                         frontmatter_name="/z-nodesc")

            result = _mod.build_skill_index(root)
            self.assertIn("Skill fills in", result,
                          msg="Fallback description must be used when first-seen description is empty")

    def test_no_duplicates_in_real_repo(self):
        """Real repo output must contain no duplicate command names."""
        result = _mod.build_skill_index(_REPO_ROOT)
        lines = _parse_lines(result)
        names = [l.split("`")[1] for l in lines if l.startswith("`")]
        self.assertEqual(len(names), len(set(names)),
                         msg=f"Duplicate names found: {[n for n in names if names.count(n) > 1]}")


# ---------------------------------------------------------------------------
# Tests: skills included / skipped
# ---------------------------------------------------------------------------

class TestSkillsIncluded(unittest.TestCase):
    """skills/*/SKILL.md entries must appear in the output."""

    def test_skill_appears_in_output(self):
        """A synthetic skill appears in the output."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_skill(root / "skills", "my-skill", "Does something useful")
            result = _mod.build_skill_index(root)
            self.assertIn("/my-skill", result, msg="Skill name must appear in index")
            self.assertIn("Does something useful", result,
                          msg="Skill description must appear in index")

    def test_skill_missing_skill_file_skipped(self):
        """A skill directory without SKILL.md is silently skipped."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            skills_dir = root / "skills"
            (skills_dir / "no-skill-file").mkdir(parents=True)
            _write_skill(skills_dir, "valid-skill", "A valid skill")
            result = _mod.build_skill_index(root)
            self.assertIn("valid-skill", result)
            self.assertNotIn("no-skill-file", result,
                             msg="Directory without SKILL.md must not appear")


# ---------------------------------------------------------------------------
# Tests: edge cases
# ---------------------------------------------------------------------------

class TestEmptyDirectories(unittest.TestCase):
    """Missing commands/ and skills/ dirs must not crash — emit empty output."""

    def test_missing_dirs_emits_empty(self):
        """No commands/ or skills/ yields empty string output (no header, no crash)."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = _mod.build_skill_index(root)
            self.assertEqual(result, "",
                             msg=f"Empty repo must produce empty output, got: {result!r}")


class TestCustomRepoRoot(unittest.TestCase):
    """--repo-root flag must be respected in subprocess invocation."""

    def test_repo_root_flag_respected(self):
        """Script invoked with --repo-root <tmp> crawls that root, not CWD."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_skill(root / "skills", "z-custom-cmd", "Custom command description",
                         frontmatter_name="/z-custom-cmd")
            r = subprocess.run(
                [sys.executable, _SCRIPT, "--repo-root", str(root)],
                capture_output=True, text=True,
            )
            self.assertEqual(r.returncode, 0, msg=r.stderr)
            self.assertIn("`/z-custom-cmd`", r.stdout,
                          msg="Custom skill must appear when --repo-root is set to tmp")
            self.assertIn("Custom command description", r.stdout)


class TestMultiLineYamlFailsFast(unittest.TestCase):
    """Folded or literal YAML block descriptions must raise ValueError, not silently emit garbage."""

    def test_folded_block_raises_valueerror(self):
        """A frontmatter description: > in a SKILL.md triggers a ValueError naming the file."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            skill_dir = root / "skills" / "z-bad"
            skill_dir.mkdir(parents=True)
            bad_file = skill_dir / "SKILL.md"
            bad_file.write_text(
                "---\nname: /z-bad\ndescription: >\n  This is a folded block.\n---\nBody\n",
                encoding="utf-8"
            )
            with self.assertRaises(ValueError) as ctx:
                _mod.build_skill_index(root)
            self.assertIn("SKILL.md", str(ctx.exception),
                          msg="ValueError must name the offending file")

    def test_literal_block_raises_valueerror(self):
        """A frontmatter description: | in a SKILL.md triggers a ValueError naming the file."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            skill_dir = root / "skills" / "z-literal"
            skill_dir.mkdir(parents=True)
            bad_file = skill_dir / "SKILL.md"
            bad_file.write_text(
                "---\nname: /z-literal\ndescription: |\n  This is a literal block.\n---\nBody\n",
                encoding="utf-8"
            )
            with self.assertRaises(ValueError) as ctx:
                _mod.build_skill_index(root)
            self.assertIn("SKILL.md", str(ctx.exception),
                          msg="ValueError must name the offending file")


# ---------------------------------------------------------------------------
# Tests: real repo smoke test
# ---------------------------------------------------------------------------

class TestRealRepoSmoke(unittest.TestCase):
    """Real repo smoke test: known skill appears correctly formatted."""

    def test_z_export_correct_format(self):
        """z-export appears as `/z-export` — <description> with correct format."""
        result = _mod.build_skill_index(_REPO_ROOT)
        lines = _parse_lines(result)
        z_export_lines = [l for l in lines if "/z-export`" in l]
        self.assertEqual(len(z_export_lines), 1,
                         msg=f"Expected exactly one /z-export line; got {z_export_lines}")
        line = z_export_lines[0]
        # Must match exact format: `/z-export` — <description>
        self.assertTrue(line.startswith("`/z-export`"),
                        msg=f"Line must start with backtick-wrapped /z-export: {line!r}")
        self.assertIn(" — ", line,
                      msg=f"Line must contain ' — ' separator: {line!r}")
        # Description must be non-empty
        parts = line.split(" — ", 1)
        self.assertGreater(len(parts[1].strip()), 0,
                           msg="Description must be non-empty for z-export")

    def test_no_pipe_in_output(self):
        """Real repo output must not contain any pipe characters (no table)."""
        result = _mod.build_skill_index(_REPO_ROOT)
        self.assertNotIn("|", result,
                         msg="Real repo output must not contain table pipes")

    def test_no_argument_hint_in_output(self):
        """argument-hint must NOT appear in the rendered output even if crawled."""
        result = _mod.build_skill_index(_REPO_ROOT)
        self.assertNotIn("argument-hint", result,
                         msg="argument-hint must not appear in stdout output")


if __name__ == "__main__":
    unittest.main()
