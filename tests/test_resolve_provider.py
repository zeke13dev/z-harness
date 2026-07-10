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
# A consult=on config.toml so these tests are insulated from the live repo's
# runtime.consult setting. Without this, a repo `.z-harness/config.toml` with
# consult=off makes resolve-provider short-circuit to "none" for consultant/
# reviewer roles, breaking the resolution assertions below.
_CONSULT_ON_CONFIG = None


def setUpModule() -> None:
    global _STUB_BIN, _CONSULT_ON_CONFIG
    _STUB_BIN = tempfile.mkdtemp(prefix="zh-stub-bin-")
    for name in ("gemini", "codex", "claude", "agy", "cursor", "omp-consult.sh", "omp"):
        p = os.path.join(_STUB_BIN, name)
        with open(p, "w") as fh:
            fh.write("#!/bin/sh\nexit 0\n")
        os.chmod(p, 0o755)
    fd, _CONSULT_ON_CONFIG = tempfile.mkstemp(prefix="zh-consult-on-", suffix=".toml")
    with os.fdopen(fd, "w") as fh:
        fh.write('schema_version = 2\n\n[runtime]\nconsult = "on"\n')


def tearDownModule() -> None:
    if _STUB_BIN:
        shutil.rmtree(_STUB_BIN, ignore_errors=True)
    if _CONSULT_ON_CONFIG and os.path.exists(_CONSULT_ON_CONFIG):
        os.remove(_CONSULT_ON_CONFIG)

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


def _make_omp_cursor_provider(model_id: str, model_label: str) -> dict:
    """T007: an omp-consult.sh entry backed by the `cursor` omp provider."""
    return {
        "kind": "cli",
        "command": "omp-consult.sh",
        "args_template": [model_id, "--fallback", "cursor-agent", "-p", "--output-format", "text"],
        "stdin": True,
        "timeout_s": 300,
        "model_label": model_label,
        "model_arg_template": None,
        "model_env_var": None,
        "default_model": None,
    }


def _write_config(path: str, providers: dict, roles: dict) -> None:
    data = {"version": 1, "providers": providers, "roles": roles}
    with open(path, "w") as fh:
        json.dump(data, fh)


def _write_config_v2(
    path: str,
    providers: dict,
    roles: dict,
    aliases: dict | None = None,
) -> None:
    data = {
        "version": 2,
        "providers": providers,
        "roles": roles,
        "aliases": aliases or {},
    }
    with open(path, "w") as fh:
        json.dump(data, fh)


def _run(role: str, config_path: str) -> subprocess.CompletedProcess:
    env = {**os.environ, "Z_HARNESS_REPO_PROVIDERS": config_path}
    if _CONSULT_ON_CONFIG:
        env["Z_HARNESS_REPO_CONFIG"] = _CONSULT_ON_CONFIG
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

    def test_omp_gemini_alias_resolves_to_antigravity_provider(self):
        """omp-gemini remains a compatibility alias for the Antigravity-backed provider."""
        providers = {
            "omp-antigravity-pro": _make_provider(
                "gemini", "Antigravity Gemini 3.1 Pro"
            ),
            "omp-codex": _make_provider("codex", "OMP Codex GPT-5.5"),
            "gemini-cli": _make_provider("gemini", "Direct Gemini CLI"),
        }
        roles = {
            "consultant_primary": "omp-gemini",
            "consultant_secondary": "omp-codex",
            "reviewer": "gemini-cli",
        }
        aliases = {"omp-gemini": "omp-antigravity-pro"}
        with tempfile.NamedTemporaryFile(suffix=".json", mode="w", delete=False) as tf:
            tf_path = tf.name
        try:
            _write_config_v2(tf_path, providers, roles, aliases)

            primary = _run("consultant_primary", tf_path)
            self.assertEqual(primary.returncode, 0, msg=primary.stderr)
            primary_out = json.loads(primary.stdout)
            self.assertEqual(primary_out["provider"], "omp-antigravity-pro")
            self.assertEqual(
                primary_out["model_label"], "Antigravity Gemini 3.1 Pro"
            )

            direct = _run("reviewer", tf_path)
            self.assertEqual(direct.returncode, 0, msg=direct.stderr)
            direct_out = json.loads(direct.stdout)
            self.assertEqual(direct_out["provider"], "gemini-cli")
            self.assertEqual(direct_out["model_label"], "Direct Gemini CLI")
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

    def test_missing_command_fails_provider_preflight_actionably(self):
        providers = {
            "missing-cli": _make_provider("definitely-not-on-path-zh", "missing-model"),
            "codex": _make_provider("codex", "codex-v1"),
        }
        roles = {
            "consultant_primary": "missing-cli",
            "consultant_secondary": "codex",
            "reviewer": "codex",
        }
        with tempfile.NamedTemporaryFile(suffix=".json", mode="w", delete=False) as tf:
            tf_path = tf.name
        try:
            _write_config(tf_path, providers, roles)
            result = _run("consultant_primary", tf_path)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("provider_preflight_failed", result.stderr)
            self.assertIn("role=consultant_primary", result.stderr)
            self.assertIn("provider=missing-cli", result.stderr)
            self.assertIn("command=definitely-not-on-path-zh not on PATH", result.stderr)
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
    extra_env: dict | None = None,
) -> subprocess.CompletedProcess:
    """Run resolve-provider.py with both a custom providers.json and config.toml."""
    env = {
        **os.environ,
        "Z_HARNESS_REPO_PROVIDERS": providers_path,
        "Z_HARNESS_REPO_CONFIG": config_toml_path,
    }
    if extra_env:
        env.update(extra_env)
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


def _write_raw_config_toml(path: str, content: str) -> None:
    with open(path, "w") as fh:
        fh.write(content)


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
        self.assertIn("provider_preflight_failed", result.stderr)
        self.assertIn("gemini-drifted", result.stderr)
        self.assertIn("argv/model composition failed", result.stderr)
        self.assertIn("default_model", result.stderr)

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

    def test_role_runtime_override_precedes_models_selector(self):
        """Provider role routing uses [roles.default.<role>].runtime before legacy [models]."""
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
        _write_raw_config_toml(
            self._config_path(),
            (
                'schema_version = 2\n\n'
                '[models]\n'
                'reviewer = "gemini"\n\n'
                '[roles.default.reviewer]\n'
                'runtime = "codex"\n'
            ),
        )

        result = _run_with_config_override("reviewer", self._providers_path(), self._config_path())
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        out = json.loads(result.stdout)
        self.assertEqual(out["provider"], "codex")

    def test_runtime_consult_toml_on_wins_over_env_off(self):
        """config.py owns runtime.consult precedence: explicit TOML on beats stale env off."""
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
        _write_raw_config_toml(
            self._config_path(),
            'schema_version = 2\n\n[runtime]\nconsult = "on"\n',
        )

        result = _run_with_config_override(
            "reviewer",
            self._providers_path(),
            self._config_path(),
            extra_env={"Z_HARNESS_CONSULT": "off"},
        )

        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertNotEqual(result.stdout.strip(), "none")
        out = json.loads(result.stdout)
        self.assertEqual(out["provider"], "gemini")

    def test_command_role_runtime_override_precedes_default_runtime(self):
        """Command-specific role runtime wins over [roles.default.<role>].runtime."""
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
        _write_raw_config_toml(
            self._config_path(),
            (
                'schema_version = 2\n\n'
                '[roles.default.reviewer]\n'
                'runtime = "gemini"\n\n'
                '[roles.z_execute.reviewer]\n'
                'runtime = "codex"\n'
            ),
        )

        result = _run_with_config_override(
            "reviewer",
            self._providers_path(),
            self._config_path(),
            {"Z_HARNESS_PROVIDER_COMMAND": "/z-execute"},
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        out = json.loads(result.stdout)
        self.assertEqual(out["provider"], "codex")

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


class TestCursorRoleReconfiguration(unittest.TestCase):
    """T007: reviewer/consultant_secondary reconfigured to cursor-backed gpt-5.6 providers."""

    def test_reviewer_resolves_cursor_terra_provider(self):
        providers = {
            "omp-cursor-terra": _make_omp_cursor_provider(
                "cursor/gpt-5.6-terra-medium", "GPT-5.6 Terra medium (omp/cursor OAuth)"
            ),
            "omp-cursor-sol": _make_omp_cursor_provider(
                "cursor/gpt-5.6-sol-medium", "GPT-5.6 Sol medium (omp/cursor OAuth)"
            ),
            "omp-antigravity-pro": _make_omp_cursor_provider(
                "google-antigravity/gemini-3.1-pro", "Antigravity Gemini 3.1 Pro"
            ),
        }
        roles = {
            "consultant_primary": "omp-antigravity-pro",
            "consultant_secondary": "omp-cursor-sol",
            "reviewer": "omp-cursor-terra",
        }
        with tempfile.NamedTemporaryFile(suffix=".json", mode="w", delete=False) as tf:
            tf_path = tf.name
        try:
            _write_config_v2(tf_path, providers, roles)
            result = _run("reviewer", tf_path)
            self.assertEqual(result.returncode, 0, msg=result.stderr)
            out = json.loads(result.stdout)
            self.assertEqual(out["provider"], "omp-cursor-terra")
            self.assertEqual(out["args_template"][0], "cursor/gpt-5.6-terra-medium")
            self.assertEqual(out["auth_backend"], "OMP OAuth / Cursor")
            self.assertEqual(out["auth_provider"], "cursor")
        finally:
            os.unlink(tf_path)

    def test_consultant_secondary_resolves_cursor_sol_provider(self):
        providers = {
            "omp-cursor-terra": _make_omp_cursor_provider(
                "cursor/gpt-5.6-terra-medium", "GPT-5.6 Terra medium (omp/cursor OAuth)"
            ),
            "omp-cursor-sol": _make_omp_cursor_provider(
                "cursor/gpt-5.6-sol-medium", "GPT-5.6 Sol medium (omp/cursor OAuth)"
            ),
            "omp-antigravity-pro": _make_omp_cursor_provider(
                "google-antigravity/gemini-3.1-pro", "Antigravity Gemini 3.1 Pro"
            ),
        }
        roles = {
            "consultant_primary": "omp-antigravity-pro",
            "consultant_secondary": "omp-cursor-sol",
            "reviewer": "omp-cursor-terra",
        }
        with tempfile.NamedTemporaryFile(suffix=".json", mode="w", delete=False) as tf:
            tf_path = tf.name
        try:
            _write_config_v2(tf_path, providers, roles)
            result = _run("consultant_secondary", tf_path)
            self.assertEqual(result.returncode, 0, msg=result.stderr)
            out = json.loads(result.stdout)
            self.assertEqual(out["provider"], "omp-cursor-sol")
            self.assertEqual(out["args_template"][0], "cursor/gpt-5.6-sol-medium")
            self.assertEqual(out["auth_backend"], "OMP OAuth / Cursor")
            self.assertEqual(out["auth_provider"], "cursor")

            primary = _run("consultant_primary", tf_path)
            self.assertEqual(primary.returncode, 0, msg=primary.stderr)
            primary_out = json.loads(primary.stdout)
            # consultant_primary stays gemini-3.1-pro and remains a distinct provider.
            self.assertEqual(primary_out["provider"], "omp-antigravity-pro")
            self.assertEqual(
                primary_out["args_template"][0], "google-antigravity/gemini-3.1-pro"
            )
            self.assertNotEqual(primary_out["provider"], out["provider"])
        finally:
            os.unlink(tf_path)

    def test_cursor_auth_backend_classification_unit(self):
        """_auth_backend_for classifies the cursor omp provider analogous to
        Antigravity/Codex, given only the argv (no live auth check)."""
        import importlib.util

        spec = importlib.util.spec_from_file_location("resolve_provider_mod", SCRIPT)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        entry = {"command": "omp-consult.sh"}
        argv = [
            "cursor/gpt-5.6-terra-medium",
            "--fallback",
            "cursor-agent",
            "-p",
            "--output-format",
            "text",
        ]
        backend, provider = mod._auth_backend_for(entry, argv)
        self.assertEqual(backend, "OMP OAuth / Cursor")
        self.assertEqual(provider, "cursor")


if __name__ == "__main__":
    unittest.main()
