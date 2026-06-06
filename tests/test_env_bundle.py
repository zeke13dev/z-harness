"""
Tests for z_harness_cli/env_bundle.py

Key parity invariant: the Z_HARNESS_PLAN_DIR injected by resolve_env_bundle()
must byte-match the output of ``bash scripts/plan-path.sh z_harness_base``
when both are called with the same cwd (same repo_root).

Also tests:
  - _parse_export_env_lines parses every shlex-quoted form correctly.
  - resolve_config_env output matches ``python3 scripts/config.py export-env``
    raw output exactly.
  - resolve_plugin_root_env returns the right var for each host/mode pair.
  - resolve_providers_env picks up repo-local providers.json.
  - apply_env_bundle merges bundle onto a copy without mutating the original.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

# Repo root (where scripts/ lives)
REPO_ROOT = Path(__file__).parent.parent.resolve()

# Module under test
sys.path.insert(0, str(REPO_ROOT))
from z_harness_cli.env_bundle import (
    _parse_export_env_lines,
    apply_env_bundle,
    resolve_config_env,
    resolve_env_bundle,
    resolve_plan_dir,
    resolve_plugin_root_env,
    resolve_providers_env,
)


class TestParseExportEnvLines(unittest.TestCase):
    """Unit tests for the export-line parser (no subprocess)."""

    def test_bare_value(self):
        out = _parse_export_env_lines("export FOO=bar\n")
        self.assertEqual(out["FOO"], "bar")

    def test_single_quoted_value(self):
        out = _parse_export_env_lines("export FOO='hello world'\n")
        self.assertEqual(out["FOO"], "hello world")

    def test_double_quoted_value(self):
        out = _parse_export_env_lines('export FOO="hello world"\n')
        self.assertEqual(out["FOO"], "hello world")

    def test_non_export_lines_skipped(self):
        out = _parse_export_env_lines("# comment\nexport A=1\nunset B\n")
        self.assertIn("A", out)
        self.assertNotIn("B", out)
        self.assertNotIn("# comment", out)

    def test_empty_value(self):
        out = _parse_export_env_lines("export EMPTY=\n")
        self.assertEqual(out.get("EMPTY", "MISSING"), "")

    def test_shlex_complex_quoted(self):
        # Simulate config.py's quoting of a Python list
        line = "export Z_HARNESS_FOLLOWUP_AUDIT='[\"a\", \"b\"]'"
        out = _parse_export_env_lines(line)
        self.assertIn("Z_HARNESS_FOLLOWUP_AUDIT", out)

    def test_multiple_vars_roundtrip(self):
        lines = (
            "export Z_HARNESS_NOTIFY_LEVEL=approval_only\n"
            "export Z_HARNESS_DOCS_ALWAYS_APPLY=always\n"
            "export Z_HARNESS_AXIOMS_ENABLED=true\n"
        )
        out = _parse_export_env_lines(lines)
        self.assertEqual(out["Z_HARNESS_NOTIFY_LEVEL"], "approval_only")
        self.assertEqual(out["Z_HARNESS_DOCS_ALWAYS_APPLY"], "always")
        self.assertEqual(out["Z_HARNESS_AXIOMS_ENABLED"], "true")


def _hermetic_env() -> dict[str, str]:
    """Return an env copy with Z_HARNESS_BASE_DIR pointing at a fresh tmpdir.

    Using the tier-1 escape hatch (Z_HARNESS_BASE_DIR) bypasses the
    .z-harness-base anchor check, so tests run hermetically regardless of
    whatever anchor the developer's machine has recorded.  The conftest also
    sets XDG_STATE_HOME to a throwaway dir (tier-2), but if an anchor already
    exists it conflicts with that tier-2 path.  Tier-1 is the clean solution.
    """
    env = os.environ.copy()
    # Use the XDG_STATE_HOME temp dir already set by conftest._hermetic_external_base.
    # Build a stable sub-path under it so plan-path.sh writes artifacts there.
    xdg = env.get("XDG_STATE_HOME", tempfile.gettempdir())
    base = os.path.join(xdg, "z-harness-test-env-bundle")
    os.makedirs(base, exist_ok=True)
    env["Z_HARNESS_BASE_DIR"] = base
    return env


class TestResolvePlanDir(unittest.TestCase):
    """Parity test: resolve_plan_dir() byte-matches plan-path.sh z_harness_base."""

    def test_parity_with_plan_path_sh(self):
        """Z_HARNESS_PLAN_DIR from env_bundle == stdout of plan-path.sh z_harness_base."""
        script = REPO_ROOT / "scripts" / "plan-path.sh"
        if not script.exists():
            self.skipTest("scripts/plan-path.sh not present")

        env = _hermetic_env()

        # Reference value: what plan-path.sh itself returns.
        ref = subprocess.run(
            ["bash", str(script), "z_harness_base"],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            env=env,
        )
        if ref.returncode != 0:
            self.skipTest(
                f"plan-path.sh exited {ref.returncode}: {ref.stderr.strip()}"
            )
        expected_path = ref.stdout.strip()
        self.assertTrue(expected_path, "plan-path.sh returned empty output")

        # Value from env_bundle (inject the same hermetic env via subprocess override).
        # resolve_plan_dir calls subprocess.run internally; we patch env by
        # temporarily setting Z_HARNESS_BASE_DIR in os.environ for the call.
        orig = os.environ.get("Z_HARNESS_BASE_DIR")
        try:
            os.environ["Z_HARNESS_BASE_DIR"] = env["Z_HARNESS_BASE_DIR"]
            actual_path = resolve_plan_dir(REPO_ROOT)
        finally:
            if orig is None:
                os.environ.pop("Z_HARNESS_BASE_DIR", None)
            else:
                os.environ["Z_HARNESS_BASE_DIR"] = orig

        self.assertEqual(
            actual_path,
            expected_path,
            "resolve_plan_dir() does not byte-match plan-path.sh z_harness_base "
            "(split-brain: CLI and harness scripts would use different state roots)",
        )

    def test_nonzero_exit_raises_runtime_error(self):
        """When plan-path.sh exits non-zero, resolve_plan_dir raises RuntimeError.

        We trigger this by passing an invalid base dir (non-absolute) so the
        script hard-fails via the Z_HARNESS_BASE_DIR absolute-path guard.
        """
        script = REPO_ROOT / "scripts" / "plan-path.sh"
        if not script.exists():
            self.skipTest("scripts/plan-path.sh not present")

        orig = os.environ.get("Z_HARNESS_BASE_DIR")
        try:
            # Pass a relative (non-absolute) path to trigger the guard exit.
            os.environ["Z_HARNESS_BASE_DIR"] = "relative/path"
            with self.assertRaises(RuntimeError):
                resolve_plan_dir(REPO_ROOT)
        finally:
            if orig is None:
                os.environ.pop("Z_HARNESS_BASE_DIR", None)
            else:
                os.environ["Z_HARNESS_BASE_DIR"] = orig


class TestResolveConfigEnv(unittest.TestCase):
    """Parity test: resolve_config_env() matches config.py export-env output."""

    def test_parity_with_config_py(self):
        """Config dict from env_bundle matches raw config.py export-env output."""
        script = REPO_ROOT / "scripts" / "config.py"
        if not script.exists():
            self.skipTest("scripts/config.py not present")

        ref = subprocess.run(
            [sys.executable, str(script), "export-env"],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            env=os.environ.copy(),
        )
        if ref.returncode != 0:
            self.skipTest(
                f"config.py export-env exited {ref.returncode}: {ref.stderr.strip()}"
            )

        expected = _parse_export_env_lines(ref.stdout)
        actual = resolve_config_env(REPO_ROOT)

        self.assertEqual(
            actual,
            expected,
            "resolve_config_env() does not match config.py export-env output "
            "(config split-brain: spawned host would see different config values)",
        )

    def test_keys_are_z_harness_prefixed(self):
        """All keys from resolve_config_env start with Z_HARNESS_."""
        env = resolve_config_env(REPO_ROOT)
        bad = [k for k in env if not k.startswith("Z_HARNESS_")]
        self.assertFalse(
            bad,
            f"resolve_config_env returned non-Z_HARNESS_ keys: {bad}",
        )

    def test_nonzero_exit_raises_runtime_error(self):
        """When config.py is called in a broken state it raises RuntimeError.

        Passing an explicit invalid Z_HARNESS_REPO_CONFIG (non-existent path)
        causes config.py export-env to exit 2 — triggering our RuntimeError.
        """
        script = REPO_ROOT / "scripts" / "config.py"
        if not script.exists():
            self.skipTest("scripts/config.py not present")

        orig = os.environ.get("Z_HARNESS_REPO_CONFIG")
        try:
            os.environ["Z_HARNESS_REPO_CONFIG"] = "/nonexistent/config.toml"
            with self.assertRaises(RuntimeError):
                resolve_config_env(REPO_ROOT)
        finally:
            if orig is None:
                os.environ.pop("Z_HARNESS_REPO_CONFIG", None)
            else:
                os.environ["Z_HARNESS_REPO_CONFIG"] = orig


class TestResolvePluginRootEnv(unittest.TestCase):
    """Unit tests for plugin-root var selection."""

    def test_installed_mode_returns_empty(self):
        result = resolve_plugin_root_env("claude", "installed")
        self.assertEqual(result, {})

    def test_claude_ephemeral_sets_claude_plugin_root(self):
        result = resolve_plugin_root_env("claude", "ephemeral")
        self.assertIn("CLAUDE_PLUGIN_ROOT", result)
        self.assertNotIn("ANTIGRAVITY_PLUGIN_ROOT", result)

    def test_cursor_ephemeral_sets_claude_plugin_root(self):
        result = resolve_plugin_root_env("cursor", "ephemeral")
        self.assertIn("CLAUDE_PLUGIN_ROOT", result)

    def test_codex_ephemeral_sets_claude_plugin_root(self):
        result = resolve_plugin_root_env("codex", "ephemeral")
        self.assertIn("CLAUDE_PLUGIN_ROOT", result)

    def test_antigravity_ephemeral_sets_antigravity_plugin_root(self):
        result = resolve_plugin_root_env("antigravity", "ephemeral")
        self.assertIn("ANTIGRAVITY_PLUGIN_ROOT", result)
        self.assertNotIn("CLAUDE_PLUGIN_ROOT", result)

    def test_agy_alias_sets_antigravity_plugin_root(self):
        result = resolve_plugin_root_env("agy", "ephemeral")
        self.assertIn("ANTIGRAVITY_PLUGIN_ROOT", result)

    def test_ephemeral_plugin_root_is_absolute_path(self):
        result = resolve_plugin_root_env("claude", "ephemeral")
        path = result["CLAUDE_PLUGIN_ROOT"]
        self.assertTrue(
            os.path.isabs(path),
            f"CLAUDE_PLUGIN_ROOT should be absolute, got: {path}",
        )

    def test_custom_harness_root_override(self):
        result = resolve_plugin_root_env("claude", "ephemeral", harness_root="/custom/root")
        self.assertEqual(result["CLAUDE_PLUGIN_ROOT"], "/custom/root")


class TestResolveProvidersEnv(unittest.TestCase):
    """Tests for providers.json resolution."""

    def test_repo_local_providers_json_detected(self):
        """When .z-harness/providers.json exists, it is returned."""
        with tempfile.TemporaryDirectory() as tmp:
            zh_dir = Path(tmp) / ".z-harness"
            zh_dir.mkdir()
            pjson = zh_dir / "providers.json"
            pjson.write_text(json.dumps({"version": 2, "providers": {}}))
            result = resolve_providers_env(tmp)
            self.assertIn("Z_HARNESS_REPO_PROVIDERS", result)
            self.assertEqual(result["Z_HARNESS_REPO_PROVIDERS"], str(pjson))

    def test_no_providers_json_returns_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = resolve_providers_env(tmp)
            self.assertEqual(result, {})

    def test_explicit_env_var_passthrough(self):
        """When Z_HARNESS_REPO_PROVIDERS is already set, it is passed through."""
        orig = os.environ.get("Z_HARNESS_REPO_PROVIDERS")
        try:
            os.environ["Z_HARNESS_REPO_PROVIDERS"] = "/explicit/path/providers.json"
            result = resolve_providers_env("/some/dir")
            self.assertEqual(result["Z_HARNESS_REPO_PROVIDERS"], "/explicit/path/providers.json")
        finally:
            if orig is None:
                os.environ.pop("Z_HARNESS_REPO_PROVIDERS", None)
            else:
                os.environ["Z_HARNESS_REPO_PROVIDERS"] = orig


class TestApplyEnvBundle(unittest.TestCase):
    """Tests for apply_env_bundle()."""

    def test_bundle_merged_onto_base(self):
        base = {"A": "1", "B": "2"}
        bundle = {"B": "overridden", "C": "3"}
        result = apply_env_bundle(bundle, base)
        self.assertEqual(result["A"], "1")
        self.assertEqual(result["B"], "overridden")
        self.assertEqual(result["C"], "3")

    def test_original_base_not_mutated(self):
        base = {"A": "1"}
        bundle = {"A": "new", "B": "2"}
        _ = apply_env_bundle(bundle, base)
        self.assertEqual(base["A"], "1", "apply_env_bundle must not mutate base_environ")

    def test_none_base_uses_os_environ(self):
        bundle = {"Z_HARNESS_BUNDLE_TEST_KEY": "test_val"}
        result = apply_env_bundle(bundle, None)
        self.assertEqual(result["Z_HARNESS_BUNDLE_TEST_KEY"], "test_val")
        # os.environ itself must not be mutated
        self.assertNotIn("Z_HARNESS_BUNDLE_TEST_KEY", os.environ)


class TestResolveEnvBundle(unittest.TestCase):
    """Integration tests for the composite resolve_env_bundle()."""

    def _skip_if_scripts_missing(self) -> None:
        plan_sh = REPO_ROOT / "scripts" / "plan-path.sh"
        config_py = REPO_ROOT / "scripts" / "config.py"
        if not plan_sh.exists() or not config_py.exists():
            self.skipTest("scripts/ directory not available")

    def setUp(self):
        """Set Z_HARNESS_BASE_DIR to bypass the anchor for hermetic test runs."""
        self._orig_base_dir = os.environ.get("Z_HARNESS_BASE_DIR")
        env = _hermetic_env()
        os.environ["Z_HARNESS_BASE_DIR"] = env["Z_HARNESS_BASE_DIR"]
        self._test_base_dir = env["Z_HARNESS_BASE_DIR"]

    def tearDown(self):
        if self._orig_base_dir is None:
            os.environ.pop("Z_HARNESS_BASE_DIR", None)
        else:
            os.environ["Z_HARNESS_BASE_DIR"] = self._orig_base_dir

    def test_bundle_contains_z_harness_plan_dir(self):
        self._skip_if_scripts_missing()
        bundle = resolve_env_bundle(REPO_ROOT, "claude", "ephemeral")
        self.assertIn("Z_HARNESS_PLAN_DIR", bundle)
        self.assertTrue(bundle["Z_HARNESS_PLAN_DIR"])

    def test_plan_dir_matches_plan_path_sh(self):
        """Core parity invariant: Z_HARNESS_PLAN_DIR == plan-path.sh z_harness_base."""
        self._skip_if_scripts_missing()

        script = REPO_ROOT / "scripts" / "plan-path.sh"
        env = _hermetic_env()
        ref = subprocess.run(
            ["bash", str(script), "z_harness_base"],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            env=env,
        )
        if ref.returncode != 0:
            self.skipTest(f"plan-path.sh failed: {ref.stderr.strip()}")

        expected = ref.stdout.strip()
        # Z_HARNESS_BASE_DIR is set in os.environ by setUp; resolve_plan_dir
        # calls subprocess which inherits it.
        bundle = resolve_env_bundle(REPO_ROOT, "claude", "ephemeral")
        self.assertEqual(
            bundle["Z_HARNESS_PLAN_DIR"],
            expected,
            "Z_HARNESS_PLAN_DIR in bundle does not byte-match plan-path.sh output "
            "(split-brain: CLI and log-event.sh would resolve different state roots)",
        )

    def test_bundle_contains_config_keys(self):
        self._skip_if_scripts_missing()
        bundle = resolve_env_bundle(REPO_ROOT, "claude", "ephemeral")
        # config.py always exports at least the schema defaults
        config_keys = [k for k in bundle if k.startswith("Z_HARNESS_") and k != "Z_HARNESS_PLAN_DIR"]
        self.assertTrue(
            len(config_keys) > 0,
            "resolve_env_bundle() returned no Z_HARNESS_* config keys",
        )

    def test_ephemeral_claude_includes_plugin_root(self):
        self._skip_if_scripts_missing()
        bundle = resolve_env_bundle(REPO_ROOT, "claude", "ephemeral")
        self.assertIn("CLAUDE_PLUGIN_ROOT", bundle)

    def test_installed_mode_omits_plugin_root(self):
        self._skip_if_scripts_missing()
        bundle = resolve_env_bundle(REPO_ROOT, "claude", "installed")
        self.assertNotIn("CLAUDE_PLUGIN_ROOT", bundle)
        self.assertNotIn("ANTIGRAVITY_PLUGIN_ROOT", bundle)

    def test_antigravity_ephemeral_sets_antigravity_root(self):
        self._skip_if_scripts_missing()
        bundle = resolve_env_bundle(REPO_ROOT, "antigravity", "ephemeral")
        self.assertIn("ANTIGRAVITY_PLUGIN_ROOT", bundle)
        self.assertNotIn("CLAUDE_PLUGIN_ROOT", bundle)


if __name__ == "__main__":
    unittest.main()
