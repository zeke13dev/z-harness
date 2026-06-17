"""
Tests for axioms.* config keys in scripts/config.py

Covers:
  defaults        — all four axioms keys return correct default values
  env_override    — Z_HARNESS_AXIOMS_* env vars override defaults
  toml_override   — project/global toml overrides resolve correctly in 4-layer precedence
  bad_type        — invalid types are rejected (exit 2)
"""

import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = str(_REPO_ROOT / "scripts" / "config.py")


def _run(args: list[str], env_extra: dict | None = None) -> subprocess.CompletedProcess:
    env = {**os.environ, **(env_extra or {})}
    return subprocess.run(
        [sys.executable, SCRIPT] + args,
        env=env,
        capture_output=True,
        text=True,
    )


def _run_get(key: str, env_extra: dict | None = None) -> subprocess.CompletedProcess:
    return _run(["get", key], env_extra=env_extra)


class TestAxiomsDefaults(unittest.TestCase):
    """All four axioms keys return the correct default value from DEFAULTS."""

    def test_enabled_default(self):
        result = _run_get("axioms.enabled")
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertEqual(result.stdout.strip(), "true")

    def test_kernel_budget_chars_default(self):
        result = _run_get("axioms.kernel_budget_chars")
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertEqual(result.stdout.strip(), "6000")

    def test_extract_min_recurrence_default(self):
        result = _run_get("axioms.extract_min_recurrence")
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertEqual(result.stdout.strip(), "3")

    def test_auto_extract_post_run_default(self):
        result = _run_get("axioms.auto_extract_post_run")
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertEqual(result.stdout.strip(), "true")


class TestAxiomsEnvOverride(unittest.TestCase):
    """Env vars override defaults for all four axioms keys."""

    def test_enabled_false_via_env(self):
        result = _run_get("axioms.enabled", env_extra={"Z_HARNESS_AXIOMS_ENABLED": "false"})
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertEqual(result.stdout.strip(), "false")

    def test_enabled_true_via_env(self):
        result = _run_get("axioms.enabled", env_extra={"Z_HARNESS_AXIOMS_ENABLED": "true"})
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertEqual(result.stdout.strip(), "true")

    def test_kernel_budget_chars_via_env(self):
        result = _run_get(
            "axioms.kernel_budget_chars",
            env_extra={"Z_HARNESS_AXIOMS_KERNEL_BUDGET_CHARS": "9000"},
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertEqual(result.stdout.strip(), "9000")

    def test_extract_min_recurrence_via_env(self):
        result = _run_get(
            "axioms.extract_min_recurrence",
            env_extra={"Z_HARNESS_AXIOMS_EXTRACT_MIN_RECURRENCE": "5"},
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertEqual(result.stdout.strip(), "5")

    def test_auto_extract_post_run_false_via_env(self):
        result = _run_get(
            "axioms.auto_extract_post_run",
            env_extra={"Z_HARNESS_AXIOMS_AUTO_EXTRACT_POST_RUN": "false"},
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertEqual(result.stdout.strip(), "false")


class TestAxiomsTomlOverride(unittest.TestCase):
    """TOML repo-local config overrides defaults; env beats toml (4-layer precedence)."""

    def _write_toml(self, directory: Path, content: str) -> Path:
        config_dir = directory / ".z-harness"
        config_dir.mkdir(parents=True, exist_ok=True)
        config_file = config_dir / "config.toml"
        config_file.write_text(textwrap.dedent(content), encoding="utf-8")
        return config_file

    def test_toml_overrides_default(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config_file = self._write_toml(
                Path(tmpdir),
                """
                [axioms]
                enabled = false
                kernel_budget_chars = 1234
                """,
            )
            env = {"Z_HARNESS_REPO_CONFIG": str(config_file)}

            result_enabled = _run_get("axioms.enabled", env_extra=env)
            self.assertEqual(result_enabled.returncode, 0, msg=result_enabled.stderr)
            self.assertEqual(result_enabled.stdout.strip(), "false")

            result_budget = _run_get("axioms.kernel_budget_chars", env_extra=env)
            self.assertEqual(result_budget.returncode, 0, msg=result_budget.stderr)
            self.assertEqual(result_budget.stdout.strip(), "1234")

    def test_toml_beats_env(self):
        """TOML wins over env (T001 ingress-gate): preference env is ignored when TOML sets the key."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_file = self._write_toml(
                Path(tmpdir),
                """
                [axioms]
                enabled = false
                """,
            )
            env = {
                "Z_HARNESS_REPO_CONFIG": str(config_file),
                "Z_HARNESS_AXIOMS_ENABLED": "true",
            }
            result = _run_get("axioms.enabled", env_extra=env)
            self.assertEqual(result.returncode, 0, msg=result.stderr)
            # TOML wins: env var Z_HARNESS_AXIOMS_ENABLED=true is ignored because TOML explicitly set enabled=false.
            # This is the T001 ingress-gate behaviour: preference-class env does NOT shadow TOML.
            self.assertEqual(result.stdout.strip(), "false")


class TestAxiomsValidationRejectsBadType(unittest.TestCase):
    """Validation rejects bad types — exits non-zero on invalid values."""

    def test_bad_bool_via_env_exits_nonzero(self):
        """Invalid bool string 'notabool' causes non-zero exit."""
        result = _run_get(
            "axioms.enabled",
            env_extra={"Z_HARNESS_AXIOMS_ENABLED": "notabool"},
        )
        self.assertNotEqual(result.returncode, 0)

    def test_bad_int_via_env_exits_nonzero(self):
        """Non-numeric string for int key causes non-zero exit."""
        result = _run_get(
            "axioms.kernel_budget_chars",
            env_extra={"Z_HARNESS_AXIOMS_KERNEL_BUDGET_CHARS": "notanint"},
        )
        self.assertNotEqual(result.returncode, 0)

    def test_zero_int_via_env_exits_nonzero(self):
        """Zero is not a positive int — should be rejected."""
        result = _run_get(
            "axioms.extract_min_recurrence",
            env_extra={"Z_HARNESS_AXIOMS_EXTRACT_MIN_RECURRENCE": "0"},
        )
        self.assertNotEqual(result.returncode, 0)

    def test_negative_int_via_env_exits_nonzero(self):
        """Negative int is not a positive int — should be rejected."""
        result = _run_get(
            "axioms.kernel_budget_chars",
            env_extra={"Z_HARNESS_AXIOMS_KERNEL_BUDGET_CHARS": "-1"},
        )
        self.assertNotEqual(result.returncode, 0)

    def test_bad_bool_in_toml_exits_nonzero(self):
        """Non-bool value for bool key in repo toml causes non-zero exit."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir) / ".z-harness"
            config_dir.mkdir(parents=True, exist_ok=True)
            config_file = config_dir / "config.toml"
            # Write raw TOML with a string value where bool is expected.
            # TOML parsers will give us a Python string if we quote it.
            config_file.write_text(
                '[axioms]\nenabled = "notabool"\n',
                encoding="utf-8",
            )
            result = _run_get(
                "axioms.enabled",
                env_extra={"Z_HARNESS_REPO_CONFIG": str(config_file)},
            )
            self.assertNotEqual(result.returncode, 0)


class TestAxiomsSetCmd(unittest.TestCase):
    """Tests for the ``config.py set`` path with axioms.* keys.

    Each test uses a temporary directory with a writable repo config file so
    that writes do not touch the real user config.  The set subcommand writes
    to the project-scope file (default scope) when Z_HARNESS_REPO_CONFIG is
    given; we then read back with ``get`` using the same env to verify.
    """

    def _env_with_tmpconfig(self, tmpdir: str) -> tuple[Path, dict]:
        """Return (config_path, env_dict) pointing set/get at a temp TOML file."""
        config_path = Path(tmpdir) / ".z-harness" / "config.toml"
        config_path.parent.mkdir(parents=True, exist_ok=True)
        env = {**os.environ, "Z_HARNESS_REPO_CONFIG": str(config_path)}
        return config_path, env

    def _run_set(self, key: str, value: str, env: dict) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, SCRIPT, "set", key, value],
            env=env,
            capture_output=True,
            text=True,
        )

    def _run_get_with_env(self, key: str, env: dict) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, SCRIPT, "get", key],
            env=env,
            capture_output=True,
            text=True,
        )

    def test_set_int_key_writes_unquoted_int_and_get_returns_int(self):
        """set axioms.kernel_budget_chars 7000 → TOML int (unquoted), get → '7000'."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path, env = self._env_with_tmpconfig(tmpdir)

            result_set = self._run_set("axioms.kernel_budget_chars", "7000", env)
            self.assertEqual(result_set.returncode, 0, msg=result_set.stderr)

            # Check the raw TOML — must be an unquoted integer (no quotes around 7000)
            toml_text = config_path.read_text(encoding="utf-8")
            self.assertIn("kernel_budget_chars", toml_text)
            # An unquoted int means the line does NOT contain '"7000"' or "'7000'"
            self.assertNotIn('"7000"', toml_text, msg=f"TOML wrote a quoted string: {toml_text!r}")
            self.assertNotIn("'7000'", toml_text, msg=f"TOML wrote a quoted string: {toml_text!r}")
            # And it does contain the bare integer
            self.assertRegex(toml_text, r"kernel_budget_chars\s*=\s*7000")

            # get must return the integer value
            result_get = self._run_get_with_env("axioms.kernel_budget_chars", env)
            self.assertEqual(result_get.returncode, 0, msg=result_get.stderr)
            self.assertEqual(result_get.stdout.strip(), "7000")

    def test_set_bool_key_false_writes_toml_bool_and_get_returns_false(self):
        """set axioms.enabled false → TOML bool (unquoted false), get → 'false'."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path, env = self._env_with_tmpconfig(tmpdir)

            result_set = self._run_set("axioms.enabled", "false", env)
            self.assertEqual(result_set.returncode, 0, msg=result_set.stderr)

            # Check the raw TOML — must be an unquoted bool (not '"false"')
            toml_text = config_path.read_text(encoding="utf-8")
            self.assertIn("enabled", toml_text)
            self.assertNotIn('"false"', toml_text, msg=f"TOML wrote a quoted string: {toml_text!r}")
            self.assertNotIn("'false'", toml_text, msg=f"TOML wrote a quoted string: {toml_text!r}")
            self.assertRegex(toml_text, r"enabled\s*=\s*false")

            # get must return the bool value
            result_get = self._run_get_with_env("axioms.enabled", env)
            self.assertEqual(result_get.returncode, 0, msg=result_get.stderr)
            self.assertEqual(result_get.stdout.strip(), "false")

    def test_set_invalid_bool_exits_nonzero_without_traceback(self):
        """set axioms.enabled bogus → exits non-zero with a clean error, no TypeError traceback."""
        with tempfile.TemporaryDirectory() as tmpdir:
            _, env = self._env_with_tmpconfig(tmpdir)

            result = self._run_set("axioms.enabled", "bogus", env)

            self.assertNotEqual(result.returncode, 0, msg="Expected non-zero exit for invalid bool")
            # Must NOT contain a Python traceback (TypeError from sorted(callable))
            self.assertNotIn("TypeError", result.stderr, msg=f"Got traceback: {result.stderr}")
            self.assertNotIn("Traceback", result.stderr, msg=f"Got traceback: {result.stderr}")
            # Must print a meaningful error message
            self.assertIn("[config]", result.stderr, msg=f"Expected [config] error message: {result.stderr}")

    def test_set_invalid_int_exits_nonzero_with_clean_error(self):
        """set axioms.kernel_budget_chars notanumber → exits non-zero with clean error."""
        with tempfile.TemporaryDirectory() as tmpdir:
            _, env = self._env_with_tmpconfig(tmpdir)

            result = self._run_set("axioms.kernel_budget_chars", "notanumber", env)

            self.assertNotEqual(result.returncode, 0, msg="Expected non-zero exit for invalid int")
            self.assertNotIn("TypeError", result.stderr, msg=f"Got traceback: {result.stderr}")
            self.assertNotIn("Traceback", result.stderr, msg=f"Got traceback: {result.stderr}")
            self.assertIn("[config]", result.stderr, msg=f"Expected [config] error message: {result.stderr}")


if __name__ == "__main__":
    unittest.main()
