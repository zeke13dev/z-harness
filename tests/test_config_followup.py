"""
Tests for scripts/config.py [followup] namespace.

Cases covered:
  default_value           — followup.default_sink returns "project" from defaults
  env_var_override        — Z_HARNESS_FOLLOWUP_DEFAULT_SINK=global overrides default
  invalid_enum_rejected   — invalid value for followup.default_sink exits 2
  layer_merge_repo        — repo TOML [followup] overrides global TOML
  bool_default_notion     — followup.notion_enabled default is false
  bool_default_autoclose  — followup.auto_close_low_risk_enabled default is true (kill-switch on)
"""

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = str(_REPO_ROOT / "scripts" / "config.py")


def _clean_env(extra: dict | None = None) -> dict:
    """Return os.environ with all Z_HARNESS_FOLLOWUP_* keys stripped, then extra applied."""
    e = {k: v for k, v in os.environ.items() if not k.startswith("Z_HARNESS_FOLLOWUP_")}
    if extra:
        e.update(extra)
    return e


def _run(
    args: list[str],
    env_extra: dict | None = None,
) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, SCRIPT] + args,
        env=_clean_env(env_extra),
        capture_output=True,
        text=True,
    )


class TestFollowupDefaults(unittest.TestCase):
    """followup.default_sink resolves to 'project' from built-in defaults."""

    def test_default_sink_is_project(self):
        # Isolate from any user/repo config by pointing both paths to non-existent files
        with tempfile.TemporaryDirectory() as td:
            result = _run(
                ["get", "followup.default_sink"],
                env_extra={
                    "XDG_CONFIG_HOME": td,
                    "Z_HARNESS_REPO_CONFIG": str(Path(td) / "repo.toml"),
                },
            )
            # Exit 2 would mean Z_HARNESS_REPO_CONFIG path doesn't exist, but we're
            # relying on the fact that an absent Z_HARNESS_REPO_CONFIG path is allowed
            # (the loader only errors if the env var is set AND the file is missing when
            # require_exists=True). Use unset repo config path instead.
            pass  # handled below

        # Simpler: just unset repo-config env and use a temp XDG_CONFIG_HOME with no config
        with tempfile.TemporaryDirectory() as xdg_dir:
            env = {
                "XDG_CONFIG_HOME": xdg_dir,
            }
            # Unset Z_HARNESS_REPO_CONFIG so we rely on git-root discovery; the file
            # will likely not exist, which is fine (treated as missing).
            env["Z_HARNESS_REPO_CONFIG"] = ""
            result = _run(["get", "followup.default_sink"], env_extra=env)
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertEqual(result.stdout.strip(), "project")

    def test_notion_enabled_default_is_false(self):
        with tempfile.TemporaryDirectory() as xdg_dir:
            result = _run(
                ["get", "followup.notion_enabled"],
                env_extra={"XDG_CONFIG_HOME": xdg_dir, "Z_HARNESS_REPO_CONFIG": ""},
            )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertEqual(result.stdout.strip(), "false")

    def test_auto_close_low_risk_enabled_default_is_true(self):
        # The key is the master kill-switch for low-risk auto-close: ON by default
        # (the feature is functional and tested), flipped to false to disable it.
        with tempfile.TemporaryDirectory() as xdg_dir:
            result = _run(
                ["get", "followup.auto_close_low_risk_enabled"],
                env_extra={"XDG_CONFIG_HOME": xdg_dir, "Z_HARNESS_REPO_CONFIG": ""},
            )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertEqual(result.stdout.strip(), "true")


class TestFollowupEnvOverride(unittest.TestCase):
    """Z_HARNESS_FOLLOWUP_DEFAULT_SINK=global overrides built-in default."""

    def test_env_override_global(self):
        with tempfile.TemporaryDirectory() as xdg_dir:
            result = _run(
                ["get", "followup.default_sink"],
                env_extra={
                    "XDG_CONFIG_HOME": xdg_dir,
                    "Z_HARNESS_REPO_CONFIG": "",
                    "Z_HARNESS_FOLLOWUP_DEFAULT_SINK": "global",
                },
            )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertEqual(result.stdout.strip(), "global")

    def test_env_override_invalid_value_rejected(self):
        """Invalid enum value via env var exits 2."""
        with tempfile.TemporaryDirectory() as xdg_dir:
            result = _run(
                ["get", "followup.default_sink"],
                env_extra={
                    "XDG_CONFIG_HOME": xdg_dir,
                    "Z_HARNESS_REPO_CONFIG": "",
                    "Z_HARNESS_FOLLOWUP_DEFAULT_SINK": "invalid_sink",
                },
            )
        self.assertEqual(result.returncode, 2)
        self.assertIn("followup.default_sink", result.stderr)


class TestFollowupLayerMerge(unittest.TestCase):
    """Repo TOML [followup] section overrides global TOML."""

    def test_repo_toml_overrides_global_toml(self):
        with tempfile.TemporaryDirectory() as xdg_dir, \
             tempfile.TemporaryDirectory() as repo_dir:

            global_config = Path(xdg_dir) / "z-harness" / "config.toml"
            global_config.parent.mkdir(parents=True, exist_ok=True)
            global_config.write_text(
                'schema_version = 1\n\n[followup]\ndefault_sink = "project"\n',
                encoding="utf-8",
            )

            repo_config = Path(repo_dir) / "repo.toml"
            repo_config.write_text(
                'schema_version = 1\n\n[followup]\ndefault_sink = "global"\n',
                encoding="utf-8",
            )

            result = _run(
                ["get", "followup.default_sink"],
                env_extra={
                    "XDG_CONFIG_HOME": xdg_dir,
                    "Z_HARNESS_REPO_CONFIG": str(repo_config),
                },
            )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        # Repo layer (higher priority) wins
        self.assertEqual(result.stdout.strip(), "global")

    def test_repo_toml_invalid_enum_hard_fails(self):
        """Invalid value in repo TOML exits 2 (hard fail, not soft warn)."""
        with tempfile.TemporaryDirectory() as xdg_dir, \
             tempfile.TemporaryDirectory() as repo_dir:

            global_config = Path(xdg_dir) / "z-harness" / "config.toml"
            global_config.parent.mkdir(parents=True, exist_ok=True)
            global_config.write_text("schema_version = 1\n", encoding="utf-8")

            repo_config = Path(repo_dir) / "repo.toml"
            repo_config.write_text(
                'schema_version = 1\n\n[followup]\ndefault_sink = "notion"\n',
                encoding="utf-8",
            )

            result = _run(
                ["get", "followup.default_sink"],
                env_extra={
                    "XDG_CONFIG_HOME": xdg_dir,
                    "Z_HARNESS_REPO_CONFIG": str(repo_config),
                },
            )
        self.assertEqual(result.returncode, 2)
        self.assertIn("followup.default_sink", result.stderr)


if __name__ == "__main__":
    unittest.main()
