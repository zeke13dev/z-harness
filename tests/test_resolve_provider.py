"""
Tests for scripts/resolve-provider.py

Invokes the script as a subprocess so we exercise the real exit-code contract.
Three cases (original):
  1. happy_path       — valid config, two providers, 3 roles → correct JSON output
  2. collision        — consultant_primary == consultant_secondary → nonzero exit
  3. malformed_args   — args_template is a string, not list[str] → nonzero + message

T007 cases — [models] override resolution:
  4. models_hit       — models.reviewer set to valid provider → resolves to it
  5. models_miss      — models.reviewer set to absent provider → fail-loud + nonzero
  6. models_drift     — models.reviewer set to provider whose compose_argv precondition
                        fails (model_arg_template set, default_model None) → fail-loud
  7. models_silent    — models.reviewer empty → falls back to default role resolution
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = str(Path(__file__).parent.parent / "scripts" / "resolve-provider.py")

# resolve-provider.py validates that a provider's `command` is on PATH
# (shutil.which) before returning it. The real provider CLIs (gemini, codex,
# claude, ...) are not installed in CI, so we stage no-op stub executables on a
# temp PATH for the duration of the module. This replicates a dev box where the
# CLIs are present, exercising the resolution logic without the real binaries.
_STUB_BIN = None


def setUpModule() -> None:
    global _STUB_BIN
    _STUB_BIN = tempfile.mkdtemp(prefix="zh-stub-bin-")
    for name in ("gemini", "codex", "claude", "agy", "cursor"):
        p = os.path.join(_STUB_BIN, name)
        with open(p, "w") as fh:
            fh.write("#!/bin/sh\nexit 0\n")
        os.chmod(p, 0o755)


def tearDownModule() -> None:
    if _STUB_BIN:
        shutil.rmtree(_STUB_BIN, ignore_errors=True)

# A minimal valid provider entry shape.
def _make_provider(command: str, model_label: str) -> dict:
    return {
        "kind": "cli",
        "command": command,
        "args_template": ["--model", model_label],
        "stdin": True,
        "timeout_s": 60,
        "model_label": model_label,
    }


def _write_config(path: str, providers: dict, roles: dict) -> None:
    data = {"version": 1, "providers": providers, "roles": roles}
    with open(path, "w") as fh:
        json.dump(data, fh)


def _run(role: str, config_path: str) -> subprocess.CompletedProcess:
    env = {**os.environ, "Z_HARNESS_REPO_PROVIDERS": config_path}
    if _STUB_BIN:
        env["PATH"] = _STUB_BIN + os.pathsep + env.get("PATH", "")
    return subprocess.run(
        [sys.executable, SCRIPT, role],
        env=env,
        capture_output=True,
        text=True,
    )


class TestResolveProvider(unittest.TestCase):

    def test_happy_path(self):
        """Valid config with two providers + 3 distinct roles returns correct JSON."""
        providers = {
            "gemini": _make_provider("gemini", "gemini-2.5-pro"),
            "codex": _make_provider("codex", "codex-v1"),
        }
        roles = {
            "consultant_primary": "gemini",
            "consultant_secondary": "codex",
            "reviewer": "gemini",
        }
        with tempfile.NamedTemporaryFile(suffix=".json", mode="w", delete=False) as tf:
            tf_path = tf.name
        try:
            _write_config(tf_path, providers, roles)

            for role, expected_provider in [
                ("consultant_primary", "gemini"),
                ("consultant_secondary", "codex"),
                ("reviewer", "gemini"),
            ]:
                with self.subTest(role=role):
                    result = _run(role, tf_path)
                    self.assertEqual(result.returncode, 0, msg=result.stderr)
                    out = json.loads(result.stdout)
                    self.assertEqual(out["role"], role)
                    self.assertEqual(out["provider"], expected_provider)
                    self.assertEqual(out["model_label"], providers[expected_provider]["model_label"])
                    self.assertEqual(out["args_template"], providers[expected_provider]["args_template"])
                    self.assertIsInstance(out["stdin"], bool)
                    self.assertIsInstance(out["timeout_s"], int)
                    self.assertGreater(out["timeout_s"], 0)
        finally:
            os.unlink(tf_path)

    def test_collision_primary_equals_secondary(self):
        """consultant_primary == consultant_secondary must exit nonzero."""
        providers = {
            "gemini": _make_provider("gemini", "gemini-2.5-pro"),
        }
        roles = {
            "consultant_primary": "gemini",
            "consultant_secondary": "gemini",
            "reviewer": "gemini",
        }
        with tempfile.NamedTemporaryFile(suffix=".json", mode="w", delete=False) as tf:
            tf_path = tf.name
        try:
            _write_config(tf_path, providers, roles)
            result = _run("consultant_primary", tf_path)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("DISTINCT", result.stderr)
        finally:
            os.unlink(tf_path)

    def test_malformed_args_template(self):
        """args_template that is a string (not list[str]) must exit nonzero with message."""
        providers = {
            "gemini": {
                "kind": "cli",
                "command": "gemini",
                "args_template": "not-a-list",   # <-- malformed
                "stdin": True,
                "timeout_s": 60,
                "model_label": "gemini-2.5-pro",
            },
        }
        roles = {
            "consultant_primary": "gemini",
            "consultant_secondary": "codex-placeholder",
            "reviewer": "gemini",
        }
        with tempfile.NamedTemporaryFile(suffix=".json", mode="w", delete=False) as tf:
            tf_path = tf.name
        try:
            _write_config(tf_path, providers, roles)
            result = _run("consultant_primary", tf_path)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("invalid args_template", result.stderr)
            self.assertIn("gemini", result.stderr)
        finally:
            os.unlink(tf_path)


def _run_with_config_override(
    role: str,
    providers_path: str,
    config_toml_path: str,
) -> subprocess.CompletedProcess:
    """Run resolve-provider.py with both a custom providers.json and config.toml."""
    env = {
        **os.environ,
        "Z_HARNESS_REPO_PROVIDERS": providers_path,
        "Z_HARNESS_REPO_CONFIG": config_toml_path,
    }
    if _STUB_BIN:
        env["PATH"] = _STUB_BIN + os.pathsep + env.get("PATH", "")
    return subprocess.run(
        [sys.executable, SCRIPT, role],
        env=env,
        capture_output=True,
        text=True,
    )


def _write_config_toml(path: str, models_section: dict) -> None:
    """Write a minimal config.toml with a [models] table for testing."""
    lines = ["[models]\n"]
    for k, v in models_section.items():
        lines.append(f'{k} = "{v}"\n')
    with open(path, "w") as fh:
        fh.writelines(lines)


class TestModelsOverride(unittest.TestCase):
    """T007: [models] config override — HIT / MISS / DRIFT / SILENT."""

    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="zh-models-test-")

    def tearDown(self):
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _providers_path(self) -> str:
        return os.path.join(self._tmp, "providers.json")

    def _config_path(self) -> str:
        return os.path.join(self._tmp, "config.toml")

    def _write_providers(self, providers: dict, roles: dict) -> None:
        _write_config(self._providers_path(), providers, roles)

    def test_models_hit(self):
        """HIT: models.reviewer set to a valid providers.json entry → resolves to it."""
        providers = {
            "gemini": _make_provider("gemini", "gemini-2.5-pro"),
            "codex": _make_provider("codex", "codex-v1"),
        }
        roles = {
            "consultant_primary": "gemini",
            "consultant_secondary": "codex",
            "reviewer": "gemini",
        }
        self._write_providers(providers, roles)
        # Override reviewer → codex (different from the roles mapping)
        _write_config_toml(self._config_path(), {"reviewer": "codex"})

        result = _run_with_config_override("reviewer", self._providers_path(), self._config_path())
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        out = json.loads(result.stdout)
        self.assertEqual(out["role"], "reviewer")
        self.assertEqual(out["provider"], "codex")
        self.assertEqual(out["model_label"], "codex-v1")

    def test_models_miss(self):
        """MISS: models.reviewer set to a name absent from providers.json → fail-loud."""
        providers = {
            "gemini": _make_provider("gemini", "gemini-2.5-pro"),
        }
        roles = {
            "consultant_primary": "gemini",
            "consultant_secondary": "gemini",
            "reviewer": "gemini",
        }
        self._write_providers(providers, roles)
        _write_config_toml(self._config_path(), {"reviewer": "nonexistent-provider"})

        result = _run_with_config_override("reviewer", self._providers_path(), self._config_path())
        self.assertNotEqual(result.returncode, 0)
        # Must contain the standardised fail-loud message.
        self.assertIn("nonexistent-provider", result.stderr)
        self.assertIn("not found in providers.json", result.stderr)
        self.assertIn("/z-providers-discover", result.stderr)

    def test_models_drift(self):
        """DRIFT: provider present but compose_argv precondition fails → fail-loud.

        compose_argv raises ValueError when model_arg_template is non-null but
        default_model is null.  This is the schema-signature-mismatch case.
        """
        # Provider has model_arg_template set but no default_model → drift.
        drifted_provider = {
            "kind": "cli",
            "command": "gemini",
            "args_template": [],
            "stdin": True,
            "timeout_s": 60,
            "model_label": "gemini-x",
            "model_arg_template": ["--model", "{model}"],
            "model_env_var": None,
            "default_model": None,  # <-- missing: compose_argv precondition fails
        }
        providers = {"gemini-drifted": drifted_provider}
        roles = {
            "consultant_primary": "gemini-drifted",
            "consultant_secondary": "gemini-drifted",
            "reviewer": "gemini-drifted",
        }
        data = {"version": 2, "providers": providers, "roles": roles}
        with open(self._providers_path(), "w") as fh:
            json.dump(data, fh)

        _write_config_toml(self._config_path(), {"reviewer": "gemini-drifted"})

        result = _run_with_config_override("reviewer", self._providers_path(), self._config_path())
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("gemini-drifted", result.stderr)
        self.assertIn("not found in providers.json", result.stderr)
        self.assertIn("/z-providers-discover", result.stderr)

    def test_models_silent(self):
        """SILENT: models.reviewer empty → falls back to default role resolution unchanged."""
        providers = {
            "gemini": _make_provider("gemini", "gemini-2.5-pro"),
            "codex": _make_provider("codex", "codex-v1"),
        }
        roles = {
            "consultant_primary": "gemini",
            "consultant_secondary": "codex",
            "reviewer": "gemini",
        }
        self._write_providers(providers, roles)
        # Empty string = absent sentinel → default resolution should apply.
        _write_config_toml(self._config_path(), {"reviewer": ""})

        result = _run_with_config_override("reviewer", self._providers_path(), self._config_path())
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        out = json.loads(result.stdout)
        # Default resolution: roles.reviewer = gemini
        self.assertEqual(out["provider"], "gemini")

    def test_models_consultant_collision_both_overridden(self):
        """REGRESSION: both consultant roles overridden to same provider → nonzero + DISTINCT."""
        providers = {
            "gemini": _make_provider("gemini", "gemini-2.5-pro"),
            "codex": _make_provider("codex", "codex-v1"),
        }
        roles = {
            "consultant_primary": "gemini",
            "consultant_secondary": "codex",
            "reviewer": "gemini",
        }
        self._write_providers(providers, roles)
        # Override BOTH consultant roles to the same provider via [models].
        _write_config_toml(
            self._config_path(),
            {"consultant_primary": "codex", "consultant_secondary": "codex"},
        )

        result = _run_with_config_override(
            "consultant_primary", self._providers_path(), self._config_path()
        )
        self.assertNotEqual(result.returncode, 0, msg=result.stdout)
        self.assertIn("DISTINCT", result.stderr)

    def test_models_consultant_collision_one_overridden_collides_with_default(self):
        """REGRESSION: one consultant role overridden to match the other's legacy default → nonzero."""
        providers = {
            "gemini": _make_provider("gemini", "gemini-2.5-pro"),
            "codex": _make_provider("codex", "codex-v1"),
        }
        # Legacy default: consultant_secondary = gemini.
        roles = {
            "consultant_primary": "codex",
            "consultant_secondary": "gemini",
            "reviewer": "gemini",
        }
        self._write_providers(providers, roles)
        # Override consultant_primary → gemini (collides with legacy secondary).
        _write_config_toml(self._config_path(), {"consultant_primary": "gemini"})

        result = _run_with_config_override(
            "consultant_primary", self._providers_path(), self._config_path()
        )
        self.assertNotEqual(result.returncode, 0, msg=result.stdout)
        self.assertIn("DISTINCT", result.stderr)

    def test_models_pre_reviewer_hyphen_normalization(self):
        """pre-reviewer role (hyphenated) must map to models.pre_reviewer config key."""
        providers = {
            "gemini": _make_provider("gemini", "gemini-2.5-pro"),
            "codex": _make_provider("codex", "codex-v1"),
        }
        roles = {
            "consultant_primary": "gemini",
            "consultant_secondary": "codex",
            "reviewer": "gemini",
            "pre-reviewer": "gemini",
        }
        self._write_providers(providers, roles)
        # Set models.pre_reviewer (underscore) — role is passed as "pre-reviewer".
        _write_config_toml(self._config_path(), {"pre_reviewer": "codex"})

        result = _run_with_config_override("pre-reviewer", self._providers_path(), self._config_path())
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        out = json.loads(result.stdout)
        self.assertEqual(out["provider"], "codex")


if __name__ == "__main__":
    unittest.main()
