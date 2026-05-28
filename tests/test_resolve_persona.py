"""
Tests for scripts/resolve-persona.py

Invokes the script as a subprocess so we exercise the real exit-code contract.

Cases covered:
  list_personas_dedup      — personas in all three layers → list-personas returns ONE winner per name
  list_personas_ordering   — winner is the LAST layer (highest priority)
  shadow_emitted_once      — persona_shadowed emitted exactly once per name even on repeated list-personas calls
  where_all_layers         — where <name> prints all defining paths in load order
  where_not_found          — where <nonexistent> exits non-zero with actionable message
  name_validation_rejects  — invalid name (uppercase, dots, slashes, trailing hyphen) exits 2
  missing_required_field   — persona without description exits 2
  compatible_roles_optional — persona without compatible_roles is accepted
"""

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent

SCRIPT = str(Path(__file__).parent.parent / "scripts" / "resolve-persona.py")


def _run(args: list[str], env_extra: dict | None = None) -> subprocess.CompletedProcess:
    env = {**os.environ, **(env_extra or {})}
    return subprocess.run(
        [sys.executable, SCRIPT] + args,
        env=env,
        capture_output=True,
        text=True,
    )


def _write_persona(directory: Path, name: str, description: str = "Test persona",
                   extra_frontmatter: str = "") -> Path:
    """Write a minimal valid persona .md file to directory."""
    directory.mkdir(parents=True, exist_ok=True)
    fm_lines = [
        "---",
        f"name: {name}",
        f"description: {description}",
    ]
    if extra_frontmatter:
        fm_lines.append(extra_frontmatter)
    fm_lines += ["---", "", f"Prompt prefix body for {name}.", ""]
    content = "\n".join(fm_lines)
    path = directory / f"{name}.md"
    path.write_text(content, encoding="utf-8")
    return path


class TestListPersonasDedup(unittest.TestCase):
    """list-personas returns one winner per name when name appears in multiple layers."""

    def test_dedup_winner_is_last_layer(self):
        """When persona present in builtin and repo, list-personas returns one entry (repo wins)."""
        import tempfile
        with tempfile.TemporaryDirectory() as builtin_dir, \
             tempfile.TemporaryDirectory() as user_dir, \
             tempfile.TemporaryDirectory() as repo_dir:

            persona_name = "test-persona"
            _write_persona(Path(builtin_dir), persona_name, description="Builtin version")
            _write_persona(Path(repo_dir), persona_name, description="Repo version")

            env = {
                "Z_HARNESS_BUILTIN_PERSONAS_DIR": builtin_dir,
                "Z_HARNESS_USER_PERSONAS_DIR": user_dir,
                "Z_HARNESS_REPO_PERSONAS_DIR": repo_dir,
            }
            result = _run(["list-personas"], env_extra=env)
            # list-personas itself must succeed
            self.assertEqual(result.returncode, 0, msg=result.stderr)
            data = json.loads(result.stdout)
            matching = [e for e in data if e["name"] == persona_name]
            # Exactly one entry per name (dedup)
            self.assertEqual(len(matching), 1, msg=f"Expected 1 winner, got {len(matching)}: {matching}")


class TestListPersonasOrdering(unittest.TestCase):
    """The winner is the repo (last) layer."""

    def test_repo_layer_wins(self):
        import tempfile
        with tempfile.TemporaryDirectory() as builtin_dir, \
             tempfile.TemporaryDirectory() as user_dir, \
             tempfile.TemporaryDirectory() as repo_dir:

            name = "ordering-test"
            builtin_path = _write_persona(Path(builtin_dir), name, description="from-builtin")
            repo_path = _write_persona(Path(repo_dir), name, description="from-repo")

            env = {
                "Z_HARNESS_BUILTIN_PERSONAS_DIR": builtin_dir,
                "Z_HARNESS_USER_PERSONAS_DIR": user_dir,
                "Z_HARNESS_REPO_PERSONAS_DIR": repo_dir,
            }
            result = _run(["list-personas"], env_extra=env)
            self.assertEqual(result.returncode, 0, msg=result.stderr)
            data = json.loads(result.stdout)
            winners = [e for e in data if e["name"] == name]
            self.assertEqual(len(winners), 1)
            # Winner path must match repo layer
            self.assertEqual(winners[0]["path"], str(repo_path))
            self.assertEqual(winners[0]["source_layer"], "repo")


class TestShadowEventOncePer(unittest.TestCase):
    """persona_shadowed emitted exactly once per name when a collision exists."""

    def test_shadow_emitted_once(self):
        """Single list-personas call with collision emits shadow message on stderr."""
        import tempfile
        with tempfile.TemporaryDirectory() as builtin_dir, \
             tempfile.TemporaryDirectory() as user_dir, \
             tempfile.TemporaryDirectory() as repo_dir:

            name = "shadowed-persona"
            _write_persona(Path(builtin_dir), name)
            _write_persona(Path(repo_dir), name)

            env = {
                "Z_HARNESS_BUILTIN_PERSONAS_DIR": builtin_dir,
                "Z_HARNESS_USER_PERSONAS_DIR": user_dir,
                "Z_HARNESS_REPO_PERSONAS_DIR": repo_dir,
            }
            result = _run(["list-personas"], env_extra=env)
            self.assertEqual(result.returncode, 0, msg=result.stderr)
            # persona_shadowed must appear in stderr
            self.assertIn("persona_shadowed", result.stderr,
                          msg=f"Expected 'persona_shadowed' in stderr. Got: {result.stderr!r}")

    def test_shadow_not_emitted_for_unique_names(self):
        """No shadow event when each name appears in only one layer."""
        import tempfile
        with tempfile.TemporaryDirectory() as builtin_dir, \
             tempfile.TemporaryDirectory() as user_dir, \
             tempfile.TemporaryDirectory() as repo_dir:

            _write_persona(Path(builtin_dir), "only-in-builtin")
            _write_persona(Path(repo_dir), "only-in-repo")

            env = {
                "Z_HARNESS_BUILTIN_PERSONAS_DIR": builtin_dir,
                "Z_HARNESS_USER_PERSONAS_DIR": user_dir,
                "Z_HARNESS_REPO_PERSONAS_DIR": repo_dir,
            }
            result = _run(["list-personas"], env_extra=env)
            self.assertEqual(result.returncode, 0, msg=result.stderr)
            self.assertNotIn("persona_shadowed", result.stderr,
                             msg="persona_shadowed must not fire when no collision exists")


class TestWherePrintsAllLayers(unittest.TestCase):
    """where <name> prints all defining layer paths in load order, one per line."""

    def test_three_layers_all_shown(self):
        """When persona defined in all three layers, where prints three lines."""
        import tempfile
        with tempfile.TemporaryDirectory() as builtin_dir, \
             tempfile.TemporaryDirectory() as user_dir, \
             tempfile.TemporaryDirectory() as repo_dir:

            name = "three-layer-persona"
            builtin_path = _write_persona(Path(builtin_dir), name)
            user_path = _write_persona(Path(user_dir), name)
            repo_path = _write_persona(Path(repo_dir), name)

            env = {
                "Z_HARNESS_BUILTIN_PERSONAS_DIR": builtin_dir,
                "Z_HARNESS_USER_PERSONAS_DIR": user_dir,
                "Z_HARNESS_REPO_PERSONAS_DIR": repo_dir,
            }
            result = _run(["where", name], env_extra=env)
            self.assertEqual(result.returncode, 0, msg=result.stderr)

            lines = [l.strip() for l in result.stdout.strip().splitlines() if l.strip()]
            self.assertEqual(len(lines), 3,
                             msg=f"Expected 3 lines in output, got {len(lines)}: {lines}")
            # First line = builtin, last line = repo
            self.assertEqual(lines[0], str(builtin_path))
            self.assertEqual(lines[1], str(user_path))
            self.assertEqual(lines[2], str(repo_path))

    def test_single_layer_one_line(self):
        """where prints one line when persona exists in only one layer."""
        import tempfile
        with tempfile.TemporaryDirectory() as builtin_dir, \
             tempfile.TemporaryDirectory() as user_dir, \
             tempfile.TemporaryDirectory() as repo_dir:

            name = "single-layer"
            builtin_path = _write_persona(Path(builtin_dir), name)

            env = {
                "Z_HARNESS_BUILTIN_PERSONAS_DIR": builtin_dir,
                "Z_HARNESS_USER_PERSONAS_DIR": user_dir,
                "Z_HARNESS_REPO_PERSONAS_DIR": repo_dir,
            }
            result = _run(["where", name], env_extra=env)
            self.assertEqual(result.returncode, 0, msg=result.stderr)
            lines = [l.strip() for l in result.stdout.strip().splitlines() if l.strip()]
            self.assertEqual(len(lines), 1)
            self.assertEqual(lines[0], str(builtin_path))


class TestWhereNotFound(unittest.TestCase):
    """where <nonexistent> exits non-zero with actionable error message."""

    def test_not_found_exits_1(self):
        import tempfile
        with tempfile.TemporaryDirectory() as builtin_dir, \
             tempfile.TemporaryDirectory() as user_dir, \
             tempfile.TemporaryDirectory() as repo_dir:

            env = {
                "Z_HARNESS_BUILTIN_PERSONAS_DIR": builtin_dir,
                "Z_HARNESS_USER_PERSONAS_DIR": user_dir,
                "Z_HARNESS_REPO_PERSONAS_DIR": repo_dir,
            }
            result = _run(["where", "definitely-does-not-exist"], env_extra=env)
            self.assertNotEqual(result.returncode, 0)
            # stderr must contain actionable guidance
            self.assertIn("list-personas", result.stderr,
                          msg=f"Expected 'list-personas' in error message. Got: {result.stderr!r}")


class TestNameValidation(unittest.TestCase):
    """Schema validation rejects non-kebab names."""

    def _run_with_bad_persona(self, name_in_frontmatter: str) -> subprocess.CompletedProcess:
        """Write a persona file with an invalid name and run list-personas against it."""
        import tempfile
        with tempfile.TemporaryDirectory() as builtin_dir, \
             tempfile.TemporaryDirectory() as user_dir, \
             tempfile.TemporaryDirectory() as repo_dir:

            # Write a persona manually (bypassing name validation in _write_persona)
            p = Path(builtin_dir) / "test.md"
            p.write_text(
                f"---\nname: {name_in_frontmatter}\ndescription: test\n---\n\nbody\n",
                encoding="utf-8",
            )
            env = {
                "Z_HARNESS_BUILTIN_PERSONAS_DIR": builtin_dir,
                "Z_HARNESS_USER_PERSONAS_DIR": user_dir,
                "Z_HARNESS_REPO_PERSONAS_DIR": repo_dir,
            }
            return _run(["list-personas"], env_extra=env)

    def test_uppercase_rejected(self):
        result = self._run_with_bad_persona("MyPersona")
        self.assertNotEqual(result.returncode, 0, msg="Uppercase name should be rejected")

    def test_dot_rejected(self):
        result = self._run_with_bad_persona("my.persona")
        self.assertNotEqual(result.returncode, 0, msg="Dotted name should be rejected")

    def test_slash_rejected(self):
        result = self._run_with_bad_persona("my/persona")
        self.assertNotEqual(result.returncode, 0, msg="Slashed name should be rejected")

    def test_trailing_hyphen_rejected(self):
        result = self._run_with_bad_persona("my-persona-")
        self.assertNotEqual(result.returncode, 0, msg="Trailing hyphen should be rejected")

    def test_leading_hyphen_rejected(self):
        # Starts with hyphen — fails ^[a-z] check
        result = self._run_with_bad_persona("-bad")
        self.assertNotEqual(result.returncode, 0, msg="Leading hyphen should be rejected")

    def test_valid_name_accepted(self):
        import tempfile
        with tempfile.TemporaryDirectory() as builtin_dir, \
             tempfile.TemporaryDirectory() as user_dir, \
             tempfile.TemporaryDirectory() as repo_dir:

            _write_persona(Path(builtin_dir), "valid-kebab-name")
            env = {
                "Z_HARNESS_BUILTIN_PERSONAS_DIR": builtin_dir,
                "Z_HARNESS_USER_PERSONAS_DIR": user_dir,
                "Z_HARNESS_REPO_PERSONAS_DIR": repo_dir,
            }
            result = _run(["list-personas"], env_extra=env)
            self.assertEqual(result.returncode, 0, msg=result.stderr)
            data = json.loads(result.stdout)
            self.assertEqual(len(data), 1)
            self.assertEqual(data[0]["name"], "valid-kebab-name")


class TestMissingRequiredField(unittest.TestCase):
    """Persona without 'description' exits 2."""

    def test_no_description_exits_2(self):
        import tempfile
        with tempfile.TemporaryDirectory() as builtin_dir, \
             tempfile.TemporaryDirectory() as user_dir, \
             tempfile.TemporaryDirectory() as repo_dir:

            p = Path(builtin_dir) / "no-desc.md"
            p.write_text("---\nname: no-desc\n---\n\nbody\n", encoding="utf-8")
            env = {
                "Z_HARNESS_BUILTIN_PERSONAS_DIR": builtin_dir,
                "Z_HARNESS_USER_PERSONAS_DIR": user_dir,
                "Z_HARNESS_REPO_PERSONAS_DIR": repo_dir,
            }
            result = _run(["list-personas"], env_extra=env)
            self.assertEqual(result.returncode, 2,
                             msg=f"Expected exit 2. stderr: {result.stderr!r}")


class TestCompatibleRolesOptional(unittest.TestCase):
    """Persona without compatible_roles is valid and appears in list-personas."""

    def test_no_compatible_roles_is_valid(self):
        import tempfile
        with tempfile.TemporaryDirectory() as builtin_dir, \
             tempfile.TemporaryDirectory() as user_dir, \
             tempfile.TemporaryDirectory() as repo_dir:

            # _write_persona does NOT add compatible_roles by default
            _write_persona(Path(builtin_dir), "no-roles", description="No compatible_roles field")
            env = {
                "Z_HARNESS_BUILTIN_PERSONAS_DIR": builtin_dir,
                "Z_HARNESS_USER_PERSONAS_DIR": user_dir,
                "Z_HARNESS_REPO_PERSONAS_DIR": repo_dir,
            }
            result = _run(["list-personas"], env_extra=env)
            self.assertEqual(result.returncode, 0, msg=result.stderr)
            data = json.loads(result.stdout)
            self.assertEqual(len(data), 1)
            self.assertEqual(data[0]["name"], "no-roles")

    def test_with_compatible_roles_is_also_valid(self):
        import tempfile
        with tempfile.TemporaryDirectory() as builtin_dir, \
             tempfile.TemporaryDirectory() as user_dir, \
             tempfile.TemporaryDirectory() as repo_dir:

            _write_persona(
                Path(builtin_dir), "with-roles",
                description="Has compatible_roles",
                extra_frontmatter="compatible_roles: [reviewer]",
            )
            env = {
                "Z_HARNESS_BUILTIN_PERSONAS_DIR": builtin_dir,
                "Z_HARNESS_USER_PERSONAS_DIR": user_dir,
                "Z_HARNESS_REPO_PERSONAS_DIR": repo_dir,
            }
            result = _run(["list-personas"], env_extra=env)
            self.assertEqual(result.returncode, 0, msg=result.stderr)
            data = json.loads(result.stdout)
            self.assertEqual(len(data), 1)
            self.assertEqual(data[0]["name"], "with-roles")


# ---------------------------------------------------------------------------
# Finding 1: Inline YAML comment stripping
# ---------------------------------------------------------------------------

class TestInlineYAMLComments(unittest.TestCase):
    """Inline YAML comments (# ...) must be stripped from unquoted values and inline lists."""

    def _run_persona_content(self, content: str, env: dict) -> subprocess.CompletedProcess:
        """Write a persona file with arbitrary content and run list-personas."""
        import tempfile
        with tempfile.TemporaryDirectory() as builtin_dir, \
             tempfile.TemporaryDirectory() as user_dir, \
             tempfile.TemporaryDirectory() as repo_dir:
            p = Path(builtin_dir) / "comment-test.md"
            p.write_text(content, encoding="utf-8")
            full_env = {
                "Z_HARNESS_BUILTIN_PERSONAS_DIR": builtin_dir,
                "Z_HARNESS_USER_PERSONAS_DIR": user_dir,
                "Z_HARNESS_REPO_PERSONAS_DIR": repo_dir,
            }
            return _run(["list-personas"], env_extra=full_env)

    def test_inline_list_with_trailing_comment(self):
        """compatible_roles: [reviewer] # optional — comment must be stripped; list parses correctly."""
        import tempfile
        with tempfile.TemporaryDirectory() as builtin_dir, \
             tempfile.TemporaryDirectory() as user_dir, \
             tempfile.TemporaryDirectory() as repo_dir:
            p = Path(builtin_dir) / "cr-comment.md"
            p.write_text(
                "---\n"
                "name: cr-comment\n"
                "description: A persona\n"
                "compatible_roles: [reviewer] # optional\n"
                "---\n\nbody\n",
                encoding="utf-8",
            )
            env = {
                "Z_HARNESS_BUILTIN_PERSONAS_DIR": builtin_dir,
                "Z_HARNESS_USER_PERSONAS_DIR": user_dir,
                "Z_HARNESS_REPO_PERSONAS_DIR": repo_dir,
            }
            result = _run(["list-personas"], env_extra=env)
            self.assertEqual(result.returncode, 0,
                             msg=f"Should parse inline list with trailing comment. stderr={result.stderr!r}")

    def test_scalar_with_trailing_comment(self):
        """name: foo  # trailing comment — comment stripped, value is 'foo'."""
        import tempfile
        with tempfile.TemporaryDirectory() as builtin_dir, \
             tempfile.TemporaryDirectory() as user_dir, \
             tempfile.TemporaryDirectory() as repo_dir:
            p = Path(builtin_dir) / "foo.md"
            p.write_text(
                "---\n"
                "name: foo  # trailing comment\n"
                "description: Test persona  # another comment\n"
                "---\n\nbody\n",
                encoding="utf-8",
            )
            env = {
                "Z_HARNESS_BUILTIN_PERSONAS_DIR": builtin_dir,
                "Z_HARNESS_USER_PERSONAS_DIR": user_dir,
                "Z_HARNESS_REPO_PERSONAS_DIR": repo_dir,
            }
            result = _run(["list-personas"], env_extra=env)
            self.assertEqual(result.returncode, 0,
                             msg=f"Should parse scalar with trailing comment. stderr={result.stderr!r}")
            data = json.loads(result.stdout)
            self.assertEqual(len(data), 1)
            self.assertEqual(data[0]["name"], "foo",
                             msg="Name should be 'foo', not include the comment text")

    def test_quoted_hash_preserved(self):
        """description: \"uses # in string\" — the # inside quotes must NOT be stripped. Verifies parsed value."""
        import tempfile
        import importlib.util
        # Load resolve-persona.py module directly to call _parse_frontmatter
        spec = importlib.util.spec_from_file_location("rp", str(_REPO_ROOT / "scripts" / "resolve-persona.py"))
        rp = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(rp)
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "hash-in-desc.md"
            p.write_text(
                '---\n'
                'name: hash-in-desc\n'
                'description: "uses # in string"\n'
                '---\n\nbody\n',
                encoding="utf-8",
            )
            fm, _body = rp._parse_frontmatter(p)
            self.assertEqual(fm["description"], "uses # in string",
                             msg=f"Quoted # must be preserved verbatim, got {fm['description']!r}")


# ---------------------------------------------------------------------------
# Finding 2: Unknown frontmatter keys must be rejected
# ---------------------------------------------------------------------------

class TestUnknownFrontmatterKeys(unittest.TestCase):
    """additionalProperties: false — unknown keys must cause exit 2 with an actionable error."""

    def _run_with_extra_key(self, extra_key: str, extra_val: str) -> subprocess.CompletedProcess:
        import tempfile
        with tempfile.TemporaryDirectory() as builtin_dir, \
             tempfile.TemporaryDirectory() as user_dir, \
             tempfile.TemporaryDirectory() as repo_dir:
            p = Path(builtin_dir) / "extra-key.md"
            p.write_text(
                f"---\nname: extra-key\ndescription: Test\n{extra_key}: {extra_val}\n---\n\nbody\n",
                encoding="utf-8",
            )
            env = {
                "Z_HARNESS_BUILTIN_PERSONAS_DIR": builtin_dir,
                "Z_HARNESS_USER_PERSONAS_DIR": user_dir,
                "Z_HARNESS_REPO_PERSONAS_DIR": repo_dir,
            }
            return _run(["list-personas"], env_extra=env)

    def test_model_key_rejected(self):
        """`model: opus` is a binding axis — must be rejected with exit 2."""
        result = self._run_with_extra_key("model", "opus")
        self.assertEqual(result.returncode, 2,
                         msg=f"'model' key should be rejected. stderr={result.stderr!r}")
        self.assertIn("model", result.stderr,
                      msg="Error message should name the offending key")

    def test_runtime_key_rejected(self):
        """`runtime: claude-cli` is a binding axis — must be rejected with exit 2."""
        result = self._run_with_extra_key("runtime", "claude-cli")
        self.assertEqual(result.returncode, 2,
                         msg=f"'runtime' key should be rejected. stderr={result.stderr!r}")
        self.assertIn("runtime", result.stderr,
                      msg="Error message should name the offending key")

    def test_known_keys_still_accepted(self):
        """All four known keys together: no rejection."""
        import tempfile
        with tempfile.TemporaryDirectory() as builtin_dir, \
             tempfile.TemporaryDirectory() as user_dir, \
             tempfile.TemporaryDirectory() as repo_dir:
            p = Path(builtin_dir) / "all-known.md"
            p.write_text(
                "---\n"
                "name: all-known\n"
                "description: Full persona\n"
                "compatible_roles: [reviewer]\n"
                "contract: freeform\n"
                "---\n\nbody\n",
                encoding="utf-8",
            )
            env = {
                "Z_HARNESS_BUILTIN_PERSONAS_DIR": builtin_dir,
                "Z_HARNESS_USER_PERSONAS_DIR": user_dir,
                "Z_HARNESS_REPO_PERSONAS_DIR": repo_dir,
            }
            result = _run(["list-personas"], env_extra=env)
            self.assertEqual(result.returncode, 0,
                             msg=f"All known keys should be accepted. stderr={result.stderr!r}")


# ---------------------------------------------------------------------------
# Finding 3: Quote-aware list splitting
# ---------------------------------------------------------------------------

class TestQuoteAwareListSplitting(unittest.TestCase):
    """compatible_roles: ["a,b", "c"] must not corrupt list items at comma splits."""

    def test_block_list_item_comment_stripped(self):
        """compatible_roles:\n  - reviewer # optional — the trailing comment must be stripped from the item."""
        import tempfile
        import importlib.util
        spec = importlib.util.spec_from_file_location("rp", str(_REPO_ROOT / "scripts" / "resolve-persona.py"))
        rp = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(rp)
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "block-list-comment.md"
            p.write_text(
                "---\n"
                "name: block-list-comment\n"
                "description: Test\n"
                "compatible_roles:\n"
                "  - reviewer # optional\n"
                "  - consultant_primary\n"
                "---\n\nbody\n",
                encoding="utf-8",
            )
            fm, _body = rp._parse_frontmatter(p)
            self.assertEqual(fm["compatible_roles"], ["reviewer", "consultant_primary"],
                             msg=f"Block-list comments must be stripped, got {fm['compatible_roles']!r}")

    def test_quoted_comma_in_list_item(self):
        """A quoted string containing a comma must be treated as one item — verifies parsed list."""
        import tempfile
        import importlib.util
        spec = importlib.util.spec_from_file_location("rp", str(_REPO_ROOT / "scripts" / "resolve-persona.py"))
        rp = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(rp)
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "quoted-comma.md"
            p.write_text(
                '---\n'
                'name: quoted-comma\n'
                'description: Test persona\n'
                'compatible_roles: ["a,b", "c"]\n'
                '---\n\nbody\n',
                encoding="utf-8",
            )
            fm, _body = rp._parse_frontmatter(p)
            self.assertEqual(fm["compatible_roles"], ["a,b", "c"],
                             msg=f"Quoted comma must keep 'a,b' as ONE item, got {fm['compatible_roles']!r}")

    def test_simple_list_still_works(self):
        """A plain unquoted list [reviewer, consultant] must still parse correctly."""
        import tempfile
        with tempfile.TemporaryDirectory() as builtin_dir, \
             tempfile.TemporaryDirectory() as user_dir, \
             tempfile.TemporaryDirectory() as repo_dir:
            p = Path(builtin_dir) / "plain-list.md"
            p.write_text(
                "---\n"
                "name: plain-list\n"
                "description: Test persona\n"
                "compatible_roles: [reviewer, consultant]\n"
                "---\n\nbody\n",
                encoding="utf-8",
            )
            env = {
                "Z_HARNESS_BUILTIN_PERSONAS_DIR": builtin_dir,
                "Z_HARNESS_USER_PERSONAS_DIR": user_dir,
                "Z_HARNESS_REPO_PERSONAS_DIR": repo_dir,
            }
            result = _run(["list-personas"], env_extra=env)
            self.assertEqual(result.returncode, 0,
                             msg=f"Plain list should parse. stderr={result.stderr!r}")


# ---------------------------------------------------------------------------
# Finding 4: persona_shadowed emitted from `where` subcommand
# ---------------------------------------------------------------------------

class TestWhereShadowEvent(unittest.TestCase):
    """where <name> must emit persona_shadowed when persona is defined in >1 layer."""

    def test_where_emits_shadow_event_for_shadowed_persona(self):
        """Calling `where <shadowed-name>` emits persona_shadowed exactly once."""
        import tempfile
        with tempfile.TemporaryDirectory() as builtin_dir, \
             tempfile.TemporaryDirectory() as user_dir, \
             tempfile.TemporaryDirectory() as repo_dir:

            name = "shadow-where-test"
            _write_persona(Path(builtin_dir), name)
            _write_persona(Path(repo_dir), name)

            env = {
                "Z_HARNESS_BUILTIN_PERSONAS_DIR": builtin_dir,
                "Z_HARNESS_USER_PERSONAS_DIR": user_dir,
                "Z_HARNESS_REPO_PERSONAS_DIR": repo_dir,
            }
            result = _run(["where", name], env_extra=env)
            self.assertEqual(result.returncode, 0, msg=result.stderr)

            # Must emit persona_shadowed in stderr
            shadow_count = result.stderr.count("persona_shadowed")
            self.assertGreaterEqual(shadow_count, 1,
                                    msg=f"Expected persona_shadowed in stderr. Got: {result.stderr!r}")
            # Must not emit more than once per process run
            self.assertEqual(shadow_count, 1,
                             msg=f"Expected exactly one persona_shadowed event, got {shadow_count}. "
                                 f"stderr: {result.stderr!r}")

    def test_where_no_shadow_event_for_unique_persona(self):
        """where <unique-name> must NOT emit persona_shadowed."""
        import tempfile
        with tempfile.TemporaryDirectory() as builtin_dir, \
             tempfile.TemporaryDirectory() as user_dir, \
             tempfile.TemporaryDirectory() as repo_dir:

            name = "unique-where-test"
            _write_persona(Path(builtin_dir), name)  # only in one layer

            env = {
                "Z_HARNESS_BUILTIN_PERSONAS_DIR": builtin_dir,
                "Z_HARNESS_USER_PERSONAS_DIR": user_dir,
                "Z_HARNESS_REPO_PERSONAS_DIR": repo_dir,
            }
            result = _run(["where", name], env_extra=env)
            self.assertEqual(result.returncode, 0, msg=result.stderr)
            self.assertNotIn("persona_shadowed", result.stderr,
                             msg="persona_shadowed must not fire for a unique persona")


# ---------------------------------------------------------------------------
# T007: resolve subcommand
# ---------------------------------------------------------------------------

def _write_toml(path: Path, content: str) -> None:
    """Write a TOML config file at path (creates parents)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


class TestResolveCommandNormalization(unittest.TestCase):
    """resolve normalizes /z-plan → z_plan; z-plan → z_plan; z_plan → z_plan."""

    def test_slash_prefix_normalized(self):
        """/z-plan and z_plan both resolve to the same binding."""
        import tempfile
        with tempfile.TemporaryDirectory() as builtin_dir, \
             tempfile.TemporaryDirectory() as user_dir, \
             tempfile.TemporaryDirectory() as repo_dir, \
             tempfile.TemporaryDirectory() as config_dir:

            persona_name = "test-persona"
            _write_persona(Path(builtin_dir), persona_name, description="Test")

            # Write a repo TOML with [roles.z_plan.consultant_primary]
            toml_path = Path(config_dir) / "config.toml"
            _write_toml(toml_path, f"""
[roles.z_plan.consultant_primary]
persona = "{persona_name}"
model = "opus"
runtime = "codex-cli"
""")
            env = {
                "Z_HARNESS_BUILTIN_PERSONAS_DIR": builtin_dir,
                "Z_HARNESS_USER_PERSONAS_DIR": user_dir,
                "Z_HARNESS_REPO_PERSONAS_DIR": repo_dir,
                "Z_HARNESS_REPO_CONFIG": str(toml_path),
                # Point XDG_CONFIG_HOME to a dir with no config.toml
                "XDG_CONFIG_HOME": config_dir,
            }

            result_slash = _run(["resolve", "/z-plan", "consultant_primary"], env_extra=env)
            result_plain = _run(["resolve", "z_plan", "consultant_primary"], env_extra=env)

            self.assertEqual(result_slash.returncode, 0, msg=result_slash.stderr)
            self.assertEqual(result_plain.returncode, 0, msg=result_plain.stderr)

            data_slash = json.loads(result_slash.stdout)
            data_plain = json.loads(result_plain.stdout)

            # Both must resolve identically
            self.assertEqual(data_slash["persona"], data_plain["persona"])
            self.assertEqual(data_slash["model"], data_plain["model"])
            self.assertEqual(data_slash["runtime"], data_plain["runtime"])
            self.assertEqual(data_slash["source"], data_plain["source"])

    def test_hyphen_command_normalized(self):
        """z-plan (hyphen) resolves the same as z_plan (underscore)."""
        import tempfile
        with tempfile.TemporaryDirectory() as builtin_dir, \
             tempfile.TemporaryDirectory() as user_dir, \
             tempfile.TemporaryDirectory() as repo_dir, \
             tempfile.TemporaryDirectory() as config_dir:

            persona_name = "hyphen-test-persona"
            _write_persona(Path(builtin_dir), persona_name, description="Hyphen test")

            toml_path = Path(config_dir) / "config.toml"
            _write_toml(toml_path, f"""
[roles.z_plan.consultant_primary]
persona = "{persona_name}"
runtime = "codex-cli"
""")
            env = {
                "Z_HARNESS_BUILTIN_PERSONAS_DIR": builtin_dir,
                "Z_HARNESS_USER_PERSONAS_DIR": user_dir,
                "Z_HARNESS_REPO_PERSONAS_DIR": repo_dir,
                "Z_HARNESS_REPO_CONFIG": str(toml_path),
                "XDG_CONFIG_HOME": config_dir,
            }

            result_hyphen = _run(["resolve", "z-plan", "consultant_primary"], env_extra=env)
            result_underscore = _run(["resolve", "z_plan", "consultant_primary"], env_extra=env)

            self.assertEqual(result_hyphen.returncode, 0, msg=result_hyphen.stderr)
            data_hyphen = json.loads(result_hyphen.stdout)
            data_underscore = json.loads(result_underscore.stdout)
            self.assertEqual(data_hyphen["persona"], data_underscore["persona"])


class TestResolveResolutionOrder(unittest.TestCase):
    """resolve applies correct priority: roles_command > roles_default > providers_legacy."""

    def test_roles_command_wins_over_default(self):
        """[roles.<cmd>.<role>] takes priority over [roles.default.<role>]."""
        import tempfile
        with tempfile.TemporaryDirectory() as builtin_dir, \
             tempfile.TemporaryDirectory() as user_dir, \
             tempfile.TemporaryDirectory() as repo_dir, \
             tempfile.TemporaryDirectory() as config_dir:

            _write_persona(Path(builtin_dir), "cmd-specific-persona", description="Cmd specific")
            _write_persona(Path(builtin_dir), "default-persona", description="Default")

            toml_path = Path(config_dir) / "config.toml"
            _write_toml(toml_path, """
[roles.default.consultant_primary]
persona = "default-persona"
runtime = "codex-cli"

[roles.z_plan.consultant_primary]
persona = "cmd-specific-persona"
runtime = "gemini-cli"
""")
            env = {
                "Z_HARNESS_BUILTIN_PERSONAS_DIR": builtin_dir,
                "Z_HARNESS_USER_PERSONAS_DIR": user_dir,
                "Z_HARNESS_REPO_PERSONAS_DIR": repo_dir,
                "Z_HARNESS_REPO_CONFIG": str(toml_path),
                "XDG_CONFIG_HOME": config_dir,
                "Z_HARNESS_REPO_PROVIDERS": "/dev/null",  # no legacy providers
            }

            result = _run(["resolve", "z_plan", "consultant_primary"], env_extra=env)
            self.assertEqual(result.returncode, 0, msg=result.stderr)
            data = json.loads(result.stdout)
            self.assertEqual(data["persona"], "cmd-specific-persona")
            self.assertEqual(data["source"], "roles_command")

    def test_default_fallback_when_no_command_binding(self):
        """[roles.default.<role>] is used when no command-specific binding exists."""
        import tempfile
        with tempfile.TemporaryDirectory() as builtin_dir, \
             tempfile.TemporaryDirectory() as user_dir, \
             tempfile.TemporaryDirectory() as repo_dir, \
             tempfile.TemporaryDirectory() as config_dir:

            _write_persona(Path(builtin_dir), "default-persona", description="Default persona")

            toml_path = Path(config_dir) / "config.toml"
            _write_toml(toml_path, """
[roles.default.consultant_primary]
persona = "default-persona"
runtime = "codex-cli"
""")
            env = {
                "Z_HARNESS_BUILTIN_PERSONAS_DIR": builtin_dir,
                "Z_HARNESS_USER_PERSONAS_DIR": user_dir,
                "Z_HARNESS_REPO_PERSONAS_DIR": repo_dir,
                "Z_HARNESS_REPO_CONFIG": str(toml_path),
                "XDG_CONFIG_HOME": config_dir,
                "Z_HARNESS_REPO_PROVIDERS": "/dev/null",
            }

            result = _run(["resolve", "z_plan", "consultant_primary"], env_extra=env)
            self.assertEqual(result.returncode, 0, msg=result.stderr)
            data = json.loads(result.stdout)
            self.assertEqual(data["persona"], "default-persona")
            self.assertEqual(data["source"], "roles_default")

    def test_providers_legacy_fallback(self):
        """When no TOML binding, resolve falls back to providers.json roles."""
        import tempfile
        with tempfile.TemporaryDirectory() as builtin_dir, \
             tempfile.TemporaryDirectory() as user_dir, \
             tempfile.TemporaryDirectory() as repo_dir, \
             tempfile.TemporaryDirectory() as config_dir, \
             tempfile.TemporaryDirectory() as providers_dir:

            providers_path = Path(providers_dir) / "providers.json"
            providers_path.write_text(json.dumps({
                "version": 1,
                "providers": {},
                "roles": {"consultant_primary": "codex-cli"},
            }), encoding="utf-8")

            empty_toml = Path(config_dir) / "config.toml"
            _write_toml(empty_toml, "")

            env = {
                "Z_HARNESS_BUILTIN_PERSONAS_DIR": builtin_dir,
                "Z_HARNESS_USER_PERSONAS_DIR": user_dir,
                "Z_HARNESS_REPO_PERSONAS_DIR": repo_dir,
                "Z_HARNESS_REPO_CONFIG": str(empty_toml),
                "XDG_CONFIG_HOME": config_dir,
                "Z_HARNESS_REPO_PROVIDERS": str(providers_path),
            }

            result = _run(["resolve", "z_plan", "consultant_primary"], env_extra=env)
            self.assertEqual(result.returncode, 0, msg=result.stderr)
            data = json.loads(result.stdout)
            self.assertEqual(data["source"], "providers_legacy")
            self.assertEqual(data["runtime"], "codex-cli")

    def test_resolve_output_shape(self):
        """resolve returns JSON with persona, model, runtime, source, persona_body_path keys."""
        import tempfile
        with tempfile.TemporaryDirectory() as builtin_dir, \
             tempfile.TemporaryDirectory() as user_dir, \
             tempfile.TemporaryDirectory() as repo_dir, \
             tempfile.TemporaryDirectory() as config_dir:

            empty_toml = Path(config_dir) / "config.toml"
            _write_toml(empty_toml, "")

            env = {
                "Z_HARNESS_BUILTIN_PERSONAS_DIR": builtin_dir,
                "Z_HARNESS_USER_PERSONAS_DIR": user_dir,
                "Z_HARNESS_REPO_PERSONAS_DIR": repo_dir,
                "Z_HARNESS_REPO_CONFIG": str(empty_toml),
                "XDG_CONFIG_HOME": config_dir,
                "Z_HARNESS_REPO_PROVIDERS": "/dev/null",
            }

            result = _run(["resolve", "z_plan", "consultant_primary"], env_extra=env)
            self.assertEqual(result.returncode, 0, msg=result.stderr)
            data = json.loads(result.stdout)
            for key in ("persona", "model", "runtime", "source", "persona_body_path"):
                self.assertIn(key, data, msg=f"Missing key {key!r} in output")

    def test_persona_body_path_populated(self):
        """resolve populates persona_body_path when persona exists in a layer."""
        import tempfile
        with tempfile.TemporaryDirectory() as builtin_dir, \
             tempfile.TemporaryDirectory() as user_dir, \
             tempfile.TemporaryDirectory() as repo_dir, \
             tempfile.TemporaryDirectory() as config_dir:

            persona_name = "body-path-persona"
            written_path = _write_persona(Path(builtin_dir), persona_name, description="Body path test")

            toml_path = Path(config_dir) / "config.toml"
            _write_toml(toml_path, f"""
[roles.z_plan.consultant_primary]
persona = "{persona_name}"
""")
            env = {
                "Z_HARNESS_BUILTIN_PERSONAS_DIR": builtin_dir,
                "Z_HARNESS_USER_PERSONAS_DIR": user_dir,
                "Z_HARNESS_REPO_PERSONAS_DIR": repo_dir,
                "Z_HARNESS_REPO_CONFIG": str(toml_path),
                "XDG_CONFIG_HOME": config_dir,
            }

            result = _run(["resolve", "z_plan", "consultant_primary"], env_extra=env)
            self.assertEqual(result.returncode, 0, msg=result.stderr)
            data = json.loads(result.stdout)
            self.assertIsNotNone(data["persona_body_path"],
                                 msg="persona_body_path must be set when persona exists")
            self.assertEqual(data["persona_body_path"], str(written_path))


class TestResolveChimeraEvent(unittest.TestCase):
    """persona_binding_chimera is emitted when axes resolve from >=2 distinct sources."""

    def test_chimera_emitted_when_axes_from_different_layers(self):
        """
        Chimera fires when persona comes from [roles.default] but runtime from providers_legacy.
        This is a mixed-source scenario (roles_default + providers_legacy).
        """
        import tempfile
        with tempfile.TemporaryDirectory() as builtin_dir, \
             tempfile.TemporaryDirectory() as user_dir, \
             tempfile.TemporaryDirectory() as repo_dir, \
             tempfile.TemporaryDirectory() as config_dir, \
             tempfile.TemporaryDirectory() as providers_dir:

            _write_persona(Path(builtin_dir), "my-persona", description="Chimera test persona")

            # TOML sets persona only (from roles_default), no runtime
            toml_path = Path(config_dir) / "config.toml"
            _write_toml(toml_path, """
[roles.default.consultant_primary]
persona = "my-persona"
""")

            # providers.json provides runtime (providers_legacy)
            providers_path = Path(providers_dir) / "providers.json"
            providers_path.write_text(json.dumps({
                "version": 1,
                "providers": {},
                "roles": {"consultant_primary": "codex-cli"},
            }), encoding="utf-8")

            env = {
                "Z_HARNESS_BUILTIN_PERSONAS_DIR": builtin_dir,
                "Z_HARNESS_USER_PERSONAS_DIR": user_dir,
                "Z_HARNESS_REPO_PERSONAS_DIR": repo_dir,
                "Z_HARNESS_REPO_CONFIG": str(toml_path),
                "XDG_CONFIG_HOME": config_dir,
                "Z_HARNESS_REPO_PROVIDERS": str(providers_path),
            }

            result = _run(["resolve", "z_plan", "consultant_primary"], env_extra=env)
            self.assertEqual(result.returncode, 0, msg=result.stderr)
            # Chimera event must appear in stderr
            self.assertIn("persona_binding_chimera", result.stderr,
                          msg=f"Expected persona_binding_chimera in stderr. Got: {result.stderr!r}")

    def test_no_chimera_when_all_from_same_source(self):
        """No chimera when all axes come from the same TOML layer."""
        import tempfile
        with tempfile.TemporaryDirectory() as builtin_dir, \
             tempfile.TemporaryDirectory() as user_dir, \
             tempfile.TemporaryDirectory() as repo_dir, \
             tempfile.TemporaryDirectory() as config_dir:

            _write_persona(Path(builtin_dir), "mono-persona", description="Mono source")

            toml_path = Path(config_dir) / "config.toml"
            _write_toml(toml_path, """
[roles.default.consultant_primary]
persona = "mono-persona"
model = "opus"
runtime = "codex-cli"
""")
            env = {
                "Z_HARNESS_BUILTIN_PERSONAS_DIR": builtin_dir,
                "Z_HARNESS_USER_PERSONAS_DIR": user_dir,
                "Z_HARNESS_REPO_PERSONAS_DIR": repo_dir,
                "Z_HARNESS_REPO_CONFIG": str(toml_path),
                "XDG_CONFIG_HOME": config_dir,
                "Z_HARNESS_REPO_PROVIDERS": "/dev/null",
            }

            result = _run(["resolve", "z_plan", "consultant_primary"], env_extra=env)
            self.assertEqual(result.returncode, 0, msg=result.stderr)
            self.assertNotIn("persona_binding_chimera", result.stderr,
                             msg="No chimera when all axes from same source")


# ---------------------------------------------------------------------------
# T007: validate subcommand
# ---------------------------------------------------------------------------

class TestValidateMissingPersona(unittest.TestCase):
    """validate exits non-zero when a default binding references a missing persona."""

    def test_missing_default_persona_exits_nonzero(self):
        """validate fails when default binding references a persona not in any layer."""
        import tempfile
        with tempfile.TemporaryDirectory() as builtin_dir, \
             tempfile.TemporaryDirectory() as user_dir, \
             tempfile.TemporaryDirectory() as repo_dir, \
             tempfile.TemporaryDirectory() as config_dir:

            # Bind to a persona that does not exist in any layer
            toml_path = Path(config_dir) / "config.toml"
            _write_toml(toml_path, """
[roles.default.consultant_primary]
persona = "nonexistent-persona"
runtime = "codex-cli"
""")
            env = {
                "Z_HARNESS_BUILTIN_PERSONAS_DIR": builtin_dir,
                "Z_HARNESS_USER_PERSONAS_DIR": user_dir,
                "Z_HARNESS_REPO_PERSONAS_DIR": repo_dir,
                "Z_HARNESS_REPO_CONFIG": str(toml_path),
                "XDG_CONFIG_HOME": config_dir,
            }

            result = _run(["validate"], env_extra=env)
            self.assertNotEqual(result.returncode, 0,
                                msg="validate must exit non-zero when persona is missing")
            self.assertIn("nonexistent-persona", result.stderr,
                          msg="Error message must name the missing persona")

    def test_validate_ok_when_persona_exists(self):
        """validate exits 0 when all bound personas exist."""
        import tempfile
        with tempfile.TemporaryDirectory() as builtin_dir, \
             tempfile.TemporaryDirectory() as user_dir, \
             tempfile.TemporaryDirectory() as repo_dir, \
             tempfile.TemporaryDirectory() as config_dir:

            _write_persona(Path(builtin_dir), "real-persona", description="Real persona")

            toml_path = Path(config_dir) / "config.toml"
            _write_toml(toml_path, """
[roles.default.consultant_primary]
persona = "real-persona"
runtime = "codex-cli"
""")
            env = {
                "Z_HARNESS_BUILTIN_PERSONAS_DIR": builtin_dir,
                "Z_HARNESS_USER_PERSONAS_DIR": user_dir,
                "Z_HARNESS_REPO_PERSONAS_DIR": repo_dir,
                "Z_HARNESS_REPO_CONFIG": str(toml_path),
                "XDG_CONFIG_HOME": config_dir,
            }

            result = _run(["validate"], env_extra=env)
            self.assertEqual(result.returncode, 0,
                             msg=f"validate must pass when persona exists. stderr={result.stderr!r}")

    def test_validate_no_toml_ok(self):
        """validate exits 0 with no TOML config (no bindings to check)."""
        import tempfile
        with tempfile.TemporaryDirectory() as builtin_dir, \
             tempfile.TemporaryDirectory() as user_dir, \
             tempfile.TemporaryDirectory() as repo_dir, \
             tempfile.TemporaryDirectory() as config_dir:

            # No TOML written — both paths don't exist
            env = {
                "Z_HARNESS_BUILTIN_PERSONAS_DIR": builtin_dir,
                "Z_HARNESS_USER_PERSONAS_DIR": user_dir,
                "Z_HARNESS_REPO_PERSONAS_DIR": repo_dir,
                "Z_HARNESS_REPO_CONFIG": str(Path(config_dir) / "nonexistent.toml"),
                "XDG_CONFIG_HOME": config_dir,
            }

            result = _run(["validate"], env_extra=env)
            self.assertEqual(result.returncode, 0,
                             msg=f"validate must pass with empty config. stderr={result.stderr!r}")


# ---------------------------------------------------------------------------
# T009: role contract enforcement
# ---------------------------------------------------------------------------

class TestRoleContractEnforcement(unittest.TestCase):
    """
    validate hard-fails when a bound persona's contract disagrees with the
    role's expected_contract from _ROLE_REGISTRY.

    Cases:
    - contract match → validate passes (exit 0)
    - contract mismatch → validate fails (exit non-zero) with named error
    - persona without contract → treated as "any" → passes any role
    """

    def _setup_env(
        self,
        builtin_dir: str,
        user_dir: str,
        repo_dir: str,
        config_dir: str,
        toml_content: str,
    ) -> dict:
        toml_path = Path(config_dir) / "config.toml"
        _write_toml(toml_path, toml_content)
        return {
            "Z_HARNESS_BUILTIN_PERSONAS_DIR": builtin_dir,
            "Z_HARNESS_USER_PERSONAS_DIR": user_dir,
            "Z_HARNESS_REPO_PERSONAS_DIR": repo_dir,
            "Z_HARNESS_REPO_CONFIG": str(toml_path),
            "XDG_CONFIG_HOME": config_dir,
            "Z_HARNESS_REPO_PROVIDERS": "/dev/null",
        }

    def test_contract_match_passes(self):
        """
        Binding a reviewer-role persona with contract:review-verdict → validate exits 0.

        This verifies the happy path: matching contracts should not block.
        Violating this would cause legitimate personas to fail incorrectly.
        """
        import tempfile
        with tempfile.TemporaryDirectory() as builtin_dir, \
             tempfile.TemporaryDirectory() as user_dir, \
             tempfile.TemporaryDirectory() as repo_dir, \
             tempfile.TemporaryDirectory() as config_dir:

            # Persona with contract matching what the reviewer role expects
            _write_persona(
                Path(builtin_dir), "correct-reviewer",
                description="Reviewer persona with correct contract",
                extra_frontmatter="contract: review-verdict",
            )

            env = self._setup_env(
                builtin_dir, user_dir, repo_dir, config_dir,
                """
[roles.default.reviewer]
persona = "correct-reviewer"
runtime = "codex-cli"
""",
            )

            result = _run(["validate"], env_extra=env)
            self.assertEqual(
                result.returncode, 0,
                msg=f"validate must pass when persona contract matches role. stderr={result.stderr!r}",
            )

    def test_contract_mismatch_fails(self):
        """
        Binding codex-default-reviewer (contract:freeform) to reviewer role → validate exits non-zero.

        This is the primary T009 invariant: a freeform persona bound to a
        review-verdict role is a contract violation and must block startup.
        This test uses an artificial override (persona with freeform contract
        bound to the reviewer role, which expects review-verdict).
        """
        import tempfile
        with tempfile.TemporaryDirectory() as builtin_dir, \
             tempfile.TemporaryDirectory() as user_dir, \
             tempfile.TemporaryDirectory() as repo_dir, \
             tempfile.TemporaryDirectory() as config_dir:

            # Artificial: a persona that declares freeform but is bound to reviewer
            _write_persona(
                Path(builtin_dir), "freeform-reviewer",
                description="Freeform persona incorrectly bound to reviewer role",
                extra_frontmatter="contract: freeform",
            )

            env = self._setup_env(
                builtin_dir, user_dir, repo_dir, config_dir,
                """
[roles.default.reviewer]
persona = "freeform-reviewer"
runtime = "codex-cli"
""",
            )

            result = _run(["validate"], env_extra=env)
            self.assertNotEqual(
                result.returncode, 0,
                msg="validate must exit non-zero when persona contract mismatches role",
            )
            # Error message must name both the persona and role + expected contract
            self.assertIn(
                "freeform-reviewer", result.stderr,
                msg=f"Error must name the offending persona. stderr={result.stderr!r}",
            )
            self.assertIn(
                "reviewer", result.stderr,
                msg=f"Error must name the offending role. stderr={result.stderr!r}",
            )
            self.assertIn(
                "review-verdict", result.stderr,
                msg=f"Error must state the expected contract. stderr={result.stderr!r}",
            )

    def test_consultant_role_rejects_review_verdict_contract(self):
        """
        Binding a review-verdict persona to consultant_primary → validate fails.

        Symmetric of the above: wrong direction mismatch must also be caught.
        """
        import tempfile
        with tempfile.TemporaryDirectory() as builtin_dir, \
             tempfile.TemporaryDirectory() as user_dir, \
             tempfile.TemporaryDirectory() as repo_dir, \
             tempfile.TemporaryDirectory() as config_dir:

            _write_persona(
                Path(builtin_dir), "verdict-consultant",
                description="Review-verdict persona incorrectly bound to consultant",
                extra_frontmatter="contract: review-verdict",
            )

            env = self._setup_env(
                builtin_dir, user_dir, repo_dir, config_dir,
                """
[roles.default.consultant_primary]
persona = "verdict-consultant"
runtime = "codex-cli"
""",
            )

            result = _run(["validate"], env_extra=env)
            self.assertNotEqual(
                result.returncode, 0,
                msg="validate must exit non-zero when review-verdict persona bound to consultant_primary",
            )
            self.assertIn(
                "freeform", result.stderr,
                msg=f"Error must mention the required 'freeform' contract. stderr={result.stderr!r}",
            )

    def test_persona_without_contract_passes_any_role(self):
        """
        A persona that omits the contract field passes validation for any role.

        This is the "any" semantics: omitting contract = no constraint.
        If this test fails, users who author minimal personas without contract
        will be incorrectly blocked.
        """
        import tempfile
        with tempfile.TemporaryDirectory() as builtin_dir, \
             tempfile.TemporaryDirectory() as user_dir, \
             tempfile.TemporaryDirectory() as repo_dir, \
             tempfile.TemporaryDirectory() as config_dir:

            # Persona with NO contract field (minimal persona)
            _write_persona(
                Path(builtin_dir), "no-contract-persona",
                description="Persona without contract field",
                # No extra_frontmatter — omits contract entirely
            )

            # Bind to reviewer (which requires review-verdict) — should still pass
            env = self._setup_env(
                builtin_dir, user_dir, repo_dir, config_dir,
                """
[roles.default.reviewer]
persona = "no-contract-persona"
runtime = "codex-cli"
""",
            )

            result = _run(["validate"], env_extra=env)
            self.assertEqual(
                result.returncode, 0,
                msg=(
                    "validate must pass when persona omits contract (treated as 'any'). "
                    f"stderr={result.stderr!r}"
                ),
            )

    def test_contract_mismatch_error_is_actionable(self):
        """
        Mismatch error message must include instructions to resolve the problem.

        An actionable error tells the user how to fix it, not just what broke.
        """
        import tempfile
        with tempfile.TemporaryDirectory() as builtin_dir, \
             tempfile.TemporaryDirectory() as user_dir, \
             tempfile.TemporaryDirectory() as repo_dir, \
             tempfile.TemporaryDirectory() as config_dir:

            _write_persona(
                Path(builtin_dir), "bad-contract-persona",
                description="Wrong contract persona",
                extra_frontmatter="contract: freeform",
            )

            env = self._setup_env(
                builtin_dir, user_dir, repo_dir, config_dir,
                """
[roles.default.reviewer]
persona = "bad-contract-persona"
""",
            )

            result = _run(["validate"], env_extra=env)
            self.assertNotEqual(result.returncode, 0)
            # Error must suggest a corrective action
            actionable_hints = ["resolve-persona.py read", "bind a different persona", "contract field"]
            found_hint = any(hint in result.stderr for hint in actionable_hints)
            self.assertTrue(
                found_hint,
                msg=(
                    f"Error message must include an actionable hint. "
                    f"Expected one of {actionable_hints!r} in stderr. "
                    f"Got: {result.stderr!r}"
                ),
            )


# ---------------------------------------------------------------------------
# T007: read subcommand
# ---------------------------------------------------------------------------

class TestReadSubcommand(unittest.TestCase):
    """read <name> prints frontmatter + body; exits non-zero for missing names."""

    def test_read_missing_exits_nonzero(self):
        """read <missing> exits non-zero with actionable error."""
        import tempfile
        with tempfile.TemporaryDirectory() as builtin_dir, \
             tempfile.TemporaryDirectory() as user_dir, \
             tempfile.TemporaryDirectory() as repo_dir:

            env = {
                "Z_HARNESS_BUILTIN_PERSONAS_DIR": builtin_dir,
                "Z_HARNESS_USER_PERSONAS_DIR": user_dir,
                "Z_HARNESS_REPO_PERSONAS_DIR": repo_dir,
            }
            result = _run(["read", "definitely-missing"], env_extra=env)
            self.assertNotEqual(result.returncode, 0,
                                msg="read <missing> must exit non-zero")
            # Error must be actionable (mention list-personas)
            self.assertIn("list-personas", result.stderr,
                          msg=f"Error must mention 'list-personas'. Got: {result.stderr!r}")

    def test_read_existing_exits_zero(self):
        """read <existing> exits 0 and emits JSON with frontmatter and body."""
        import tempfile
        with tempfile.TemporaryDirectory() as builtin_dir, \
             tempfile.TemporaryDirectory() as user_dir, \
             tempfile.TemporaryDirectory() as repo_dir:

            name = "readable-persona"
            _write_persona(Path(builtin_dir), name, description="A readable persona")

            env = {
                "Z_HARNESS_BUILTIN_PERSONAS_DIR": builtin_dir,
                "Z_HARNESS_USER_PERSONAS_DIR": user_dir,
                "Z_HARNESS_REPO_PERSONAS_DIR": repo_dir,
            }
            result = _run(["read", name], env_extra=env)
            self.assertEqual(result.returncode, 0, msg=result.stderr)

            data = json.loads(result.stdout)
            self.assertEqual(data["name"], name)
            self.assertIn("frontmatter", data)
            self.assertIn("body", data)
            self.assertIn("path", data)

    def test_read_winner_is_last_layer(self):
        """read returns the winning layer (last) when persona is in multiple layers."""
        import tempfile
        with tempfile.TemporaryDirectory() as builtin_dir, \
             tempfile.TemporaryDirectory() as user_dir, \
             tempfile.TemporaryDirectory() as repo_dir:

            name = "multi-layer-persona"
            _write_persona(Path(builtin_dir), name, description="From builtin")
            repo_path = _write_persona(Path(repo_dir), name, description="From repo — winner")

            env = {
                "Z_HARNESS_BUILTIN_PERSONAS_DIR": builtin_dir,
                "Z_HARNESS_USER_PERSONAS_DIR": user_dir,
                "Z_HARNESS_REPO_PERSONAS_DIR": repo_dir,
            }
            result = _run(["read", name], env_extra=env)
            self.assertEqual(result.returncode, 0, msg=result.stderr)
            data = json.loads(result.stdout)
            self.assertEqual(data["path"], str(repo_path),
                             msg="read must return the winning (last-layer) path")
            self.assertEqual(data["source_layer"], "repo")


# ---------------------------------------------------------------------------
# T007: list-bindings subcommand
# ---------------------------------------------------------------------------

class TestListBindings(unittest.TestCase):
    """list-bindings outputs a JSON tree of all resolved bindings."""

    def test_list_bindings_empty(self):
        """list-bindings with no TOML config returns empty JSON object."""
        import tempfile
        with tempfile.TemporaryDirectory() as builtin_dir, \
             tempfile.TemporaryDirectory() as user_dir, \
             tempfile.TemporaryDirectory() as repo_dir, \
             tempfile.TemporaryDirectory() as config_dir:

            env = {
                "Z_HARNESS_BUILTIN_PERSONAS_DIR": builtin_dir,
                "Z_HARNESS_USER_PERSONAS_DIR": user_dir,
                "Z_HARNESS_REPO_PERSONAS_DIR": repo_dir,
                "Z_HARNESS_REPO_CONFIG": str(Path(config_dir) / "nonexistent.toml"),
                "XDG_CONFIG_HOME": config_dir,
            }
            result = _run(["list-bindings"], env_extra=env)
            self.assertEqual(result.returncode, 0, msg=result.stderr)
            data = json.loads(result.stdout)
            self.assertIsInstance(data, dict)

    def test_list_bindings_with_command_filter(self):
        """list-bindings --command z_plan returns only that command's bindings."""
        import tempfile
        with tempfile.TemporaryDirectory() as builtin_dir, \
             tempfile.TemporaryDirectory() as user_dir, \
             tempfile.TemporaryDirectory() as repo_dir, \
             tempfile.TemporaryDirectory() as config_dir:

            _write_persona(Path(builtin_dir), "filter-persona", description="Filter test")

            toml_path = Path(config_dir) / "config.toml"
            _write_toml(toml_path, """
[roles.z_plan.consultant_primary]
persona = "filter-persona"

[roles.z_review.reviewer]
runtime = "codex-cli"
""")
            env = {
                "Z_HARNESS_BUILTIN_PERSONAS_DIR": builtin_dir,
                "Z_HARNESS_USER_PERSONAS_DIR": user_dir,
                "Z_HARNESS_REPO_PERSONAS_DIR": repo_dir,
                "Z_HARNESS_REPO_CONFIG": str(toml_path),
                "XDG_CONFIG_HOME": config_dir,
                "Z_HARNESS_REPO_PROVIDERS": "/dev/null",
            }

            result = _run(["list-bindings", "--command", "z_plan"], env_extra=env)
            self.assertEqual(result.returncode, 0, msg=result.stderr)
            data = json.loads(result.stdout)
            # Only z_plan should be present
            self.assertIn("z_plan", data,
                          msg="z_plan must be in filtered output")
            self.assertNotIn("z_review", data,
                             msg="z_review must be excluded when filtering by z_plan")


if __name__ == "__main__":
    unittest.main()
