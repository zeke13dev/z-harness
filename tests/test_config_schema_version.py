"""
Tests for schema_version handling in scripts/config.py.

Cases covered:
  default_is_2            — DEFAULTS["schema_version"] == 2
  v1_warns_on_stderr      — loading a global config with schema_version=1 emits a
                            deprecation warning to stderr (non-fatal)
  v1_still_loads          — config resolves successfully after the v1 warning (exit 0)
  v2_no_warning           — loading a config with schema_version=2 emits no WARNING
  v3_hard_exits           — loading a config with schema_version=3 (future) exits 2
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


def _run(
    args: list[str],
    global_config: str | None = None,
    extra_env: dict | None = None,
) -> subprocess.CompletedProcess:
    """
    Run config.py with optional global TOML content written to a temp XDG dir.

    Sets XDG_CONFIG_HOME to isolate from real user config.
    Writes an empty repo config to a temp file so auto-discovery of the actual
    z-harness repo's .z-harness/config.toml is suppressed (it has schema_version=1
    and would pollute tests for the repo layer).
    """
    env = {k: v for k, v in os.environ.items()}

    with tempfile.TemporaryDirectory() as td:
        td_path = Path(td)

        if global_config is not None:
            global_dir = td_path / "z-harness"
            global_dir.mkdir(parents=True)
            (global_dir / "config.toml").write_text(textwrap.dedent(global_config))

        env["XDG_CONFIG_HOME"] = str(td_path)

        # Write an empty repo config so git-root auto-discovery is bypassed.
        # A non-existent path would cause exit 2; an existing empty file is fine.
        empty_repo_cfg = td_path / "empty-repo-config.toml"
        empty_repo_cfg.write_text("")
        env["Z_HARNESS_REPO_CONFIG"] = str(empty_repo_cfg)

        if extra_env:
            env.update(extra_env)

        return subprocess.run(
            [sys.executable, SCRIPT] + args,
            env=env,
            capture_output=True,
            text=True,
        )


class TestSchemaVersionDefault(unittest.TestCase):
    """DEFAULTS["schema_version"] == 2."""

    def test_default_schema_version_is_2(self):
        """Import DEFAULTS from config.py and check schema_version == 2."""
        result = subprocess.run(
            [
                sys.executable, "-c",
                (
                    "import sys; sys.path.insert(0, '.');"
                    "from scripts.config import DEFAULTS;"  # noqa: E501
                    "print(DEFAULTS['schema_version'])"
                ),
            ],
            capture_output=True,
            text=True,
            cwd=str(_REPO_ROOT),
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertEqual(result.stdout.strip(), "2")


class TestSchemaVersionV1Legacy(unittest.TestCase):
    """Loading a global config with schema_version=1 warns but does not exit."""

    _V1_CONFIG = """\
        schema_version = 1

        [notify]
        level = "off"
    """

    def test_v1_emits_warning_to_stderr(self):
        """A v1 global config must produce a warning on stderr."""
        result = _run(["get", "notify.level"], global_config=self._V1_CONFIG)
        self.assertIn("schema_version", result.stderr,
                      msg="Expected schema_version deprecation warning on stderr")
        self.assertIn("ensure-defaults", result.stderr,
                      msg="Warning must point user at config.py ensure-defaults")

    def test_v1_still_loads_exit_0(self):
        """A v1 global config must not cause a non-zero exit (warning is non-fatal)."""
        result = _run(["get", "notify.level"], global_config=self._V1_CONFIG)
        self.assertEqual(result.returncode, 0,
                         msg=f"Expected exit 0 but got {result.returncode}; stderr: {result.stderr}")

    def test_v1_value_from_config_is_readable(self):
        """Values from a v1 config are resolved correctly despite the warning."""
        result = _run(["get", "notify.level"], global_config=self._V1_CONFIG)
        self.assertEqual(result.returncode, 0,
                         msg=f"Unexpected exit {result.returncode}; stderr: {result.stderr}")
        self.assertEqual(result.stdout.strip(), "off")


class TestSchemaVersionV2Clean(unittest.TestCase):
    """Loading a global config with schema_version=2 emits no deprecation warning."""

    _V2_CONFIG = """\
        schema_version = 2

        [notify]
        level = "all"
    """

    def test_v2_no_warning(self):
        result = _run(["get", "notify.level"], global_config=self._V2_CONFIG)
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertNotIn("WARNING", result.stderr,
                         msg="No WARNING should appear for a current schema_version=2 config")

    def test_v2_value_resolves(self):
        result = _run(["get", "notify.level"], global_config=self._V2_CONFIG)
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertEqual(result.stdout.strip(), "all")


class TestSchemaVersionFuture(unittest.TestCase):
    """Loading a global config with schema_version > 2 is a hard error (exit 2)."""

    _V3_CONFIG = """\
        schema_version = 3

        [notify]
        level = "off"
    """

    def test_v3_exits_2(self):
        result = _run(["get", "notify.level"], global_config=self._V3_CONFIG)
        self.assertEqual(result.returncode, 2,
                         msg=f"Expected exit 2 for future schema_version; stderr: {result.stderr}")

    def test_v3_mentions_schema_version_on_stderr(self):
        result = _run(["get", "notify.level"], global_config=self._V3_CONFIG)
        self.assertIn("schema_version", result.stderr)


class TestEnsureDefaultsWritesV2(unittest.TestCase):
    """ensure-defaults must write schema_version = 2 in the generated config."""

    def test_ensure_defaults_writes_schema_version_2(self):
        """Running ensure-defaults on a clean XDG dir must produce schema_version = 2."""
        env = {k: v for k, v in os.environ.items()}
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            env["XDG_CONFIG_HOME"] = str(td_path)
            # No pre-existing global config — ensure-defaults should create one.
            empty_repo_cfg = td_path / "empty-repo-config.toml"
            empty_repo_cfg.write_text("")
            env["Z_HARNESS_REPO_CONFIG"] = str(empty_repo_cfg)

            result = subprocess.run(
                [sys.executable, SCRIPT, "ensure-defaults"],
                env=env,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0,
                             msg=f"ensure-defaults failed; stderr: {result.stderr}")

            written = (td_path / "z-harness" / "config.toml").read_text()
            self.assertIn("schema_version = 2", written,
                          msg="ensure-defaults must write schema_version = 2, not 1")
            self.assertNotIn("schema_version = 1", written,
                             msg="ensure-defaults must not write the legacy schema_version = 1")


if __name__ == "__main__":
    unittest.main()
