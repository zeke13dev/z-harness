"""
Tests for T001 — Legal-env allowlist + ingress preference-env ignore.

Verifies:
  1. LEGAL_ENV_KEYS and LEGAL_ENV_PREFIXES constants exist and enumerate the
     required plumbing + unattended vars.
  2. load_config() TOML-wins gate: a preference-class env var does NOT override
     a value set in TOML (global or repo layer).
  3. Plumbing env vars (Z_HARNESS_PLAN_DIR etc.) are not affected — they are not
     DEFAULTS keys and continue to be read directly from the environment by
     callers (not via load_config).
  4. Env still applies when TOML is silent (only defaults) — preserves existing
     T003a/T003b migration behaviour.

Invariant under test:
  - Failure class: preference-class env shadows TOML value (TOML-wins gate absent).
  - Passing scenario: Z_HARNESS_NOTIFY_LEVEL=all in env, notify.level="off" in TOML
    → resolved value is "off" (TOML), not "all" (env).
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = str(_REPO_ROOT / "scripts" / "config.py")


def _run(
    args: list[str],
    extra_env: dict | None = None,
    global_toml: str | None = None,
    repo_toml: str | None = None,
) -> subprocess.CompletedProcess:
    """
    Run config.py with an isolated XDG_CONFIG_HOME and optional TOML content.

    global_toml: if provided, write as the global config file.
    repo_toml: if provided, write as the repo config file.
    """
    env = {k: v for k, v in os.environ.items()}

    with tempfile.TemporaryDirectory() as td:
        td_path = Path(td)
        env["XDG_CONFIG_HOME"] = str(td_path)

        if global_toml is not None:
            global_cfg = td_path / "z-harness" / "config.toml"
            global_cfg.parent.mkdir(parents=True, exist_ok=True)
            global_cfg.write_text(global_toml)
        else:
            # No global config — use XDG_CONFIG_HOME pointing to an empty dir
            pass

        if repo_toml is not None:
            repo_cfg = td_path / "repo-config.toml"
            repo_cfg.write_text(repo_toml)
            env["Z_HARNESS_REPO_CONFIG"] = str(repo_cfg)
        else:
            # Empty repo config
            empty_repo_cfg = td_path / "empty-repo.toml"
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


def _import_constant(name: str) -> object:
    """Import a module-level constant from config.py via subprocess."""
    result = subprocess.run(
        [sys.executable, "-c",
         f"import sys; sys.path.insert(0, 'scripts');"
         f"from config import {name}; import json; print(json.dumps(list({name}) if hasattr({name}, '__iter__') and not isinstance({name}, str) else {name}))"],
        capture_output=True,
        text=True,
        cwd=str(_REPO_ROOT),
    )
    if result.returncode != 0:
        raise AssertionError(f"Failed to import {name}: {result.stderr}")
    return json.loads(result.stdout)


# ---------------------------------------------------------------------------
# Tests: LEGAL_ENV_KEYS and LEGAL_ENV_PREFIXES constants exist + enumerate
# the required vars from the acceptance criteria.
# ---------------------------------------------------------------------------

class TestLegalEnvConstants(unittest.TestCase):
    """LEGAL_ENV_KEYS and LEGAL_ENV_PREFIXES must be present and complete."""

    def _import_legal_env_keys(self) -> set:
        result = subprocess.run(
            [sys.executable, "-c",
             "import sys; sys.path.insert(0, 'scripts');"
             "from config import LEGAL_ENV_KEYS; import json; print(json.dumps(list(LEGAL_ENV_KEYS)))"],
            capture_output=True,
            text=True,
            cwd=str(_REPO_ROOT),
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        return set(json.loads(result.stdout))

    def _import_legal_env_prefixes(self) -> list:
        result = subprocess.run(
            [sys.executable, "-c",
             "import sys; sys.path.insert(0, 'scripts');"
             "from config import LEGAL_ENV_PREFIXES; import json; print(json.dumps(list(LEGAL_ENV_PREFIXES)))"],
            capture_output=True,
            text=True,
            cwd=str(_REPO_ROOT),
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        return json.loads(result.stdout)

    # Acceptance criteria: plumbing set
    _REQUIRED_PLUMBING = {
        "Z_HARNESS_PLAN_DIR",
        "Z_HARNESS_SLUG",
        "Z_HARNESS_RUN",
        "Z_HARNESS_RUN_ID",
        "Z_HARNESS_SESSION_ID",
        "Z_HARNESS_PLUGIN_ROOT",
        "Z_HARNESS_BASE_DIR",
        "Z_HARNESS_PLANS_DIR",
        "Z_HARNESS_ROOT",
        "Z_HARNESS_TASK_ID",
        "Z_HARNESS_ATTEMPT_ID",
        "Z_HARNESS_PARENT_RUN_ID",
        "Z_HARNESS_PARENT_COMMAND",
        "Z_HARNESS_REPO_CONFIG",
        "Z_HARNESS_REPO_PROVIDERS",
    }

    # Acceptance criteria: unattended set (exact keys, not prefix-matched)
    _REQUIRED_UNATTENDED_KEYS = {
        "Z_HARNESS_NO_ASK",
        "Z_HARNESS_ASK_ALL",
        "Z_HARNESS_OVERNIGHT_AUTODECIDE",
        "Z_HARNESS_OVERNIGHT_AUTODECIDE_EFFECTIVE",
        "Z_HARNESS_STRICT_OVERLAP",
    }

    # Acceptance criteria: prefix-covered sets
    _REQUIRED_PREFIXES_COVER = {
        "CLAIM_": ["Z_HARNESS_CLAIM_TTL_SECS", "Z_HARNESS_CLAIM_OVERRIDE", "Z_HARNESS_CLAIM_DISABLE"],
        "REGISTRY_": ["Z_HARNESS_REGISTRY_ENABLED", "Z_HARNESS_REGISTRY_STALE_SECS"],
    }

    def test_legal_env_keys_exists(self):
        """LEGAL_ENV_KEYS constant must exist and be importable."""
        keys = self._import_legal_env_keys()
        self.assertIsInstance(keys, set)

    def test_legal_env_prefixes_exists(self):
        """LEGAL_ENV_PREFIXES constant must exist and be importable."""
        prefixes = self._import_legal_env_prefixes()
        self.assertIsInstance(prefixes, list)

    def test_plumbing_vars_in_legal_env_keys(self):
        """All required plumbing env var names must be in LEGAL_ENV_KEYS."""
        keys = self._import_legal_env_keys()
        missing = self._REQUIRED_PLUMBING - keys
        self.assertEqual(missing, set(),
                         msg=f"LEGAL_ENV_KEYS missing required plumbing vars: {sorted(missing)}")

    def test_unattended_vars_in_legal_env_keys(self):
        """All required unattended env var names must be in LEGAL_ENV_KEYS."""
        keys = self._import_legal_env_keys()
        missing = self._REQUIRED_UNATTENDED_KEYS - keys
        self.assertEqual(missing, set(),
                         msg=f"LEGAL_ENV_KEYS missing required unattended vars: {sorted(missing)}")

    def test_claim_prefix_in_legal_env_prefixes(self):
        """LEGAL_ENV_PREFIXES must contain a prefix that covers CLAIM_* vars."""
        prefixes = self._import_legal_env_prefixes()
        # At least one prefix must cover Z_HARNESS_CLAIM_TTL_SECS
        covered = any("Z_HARNESS_CLAIM_TTL_SECS".startswith(p) for p in prefixes)
        self.assertTrue(covered,
                        msg=f"LEGAL_ENV_PREFIXES {prefixes!r} does not cover Z_HARNESS_CLAIM_TTL_SECS")

    def test_registry_prefix_in_legal_env_prefixes_or_keys(self):
        """LEGAL_ENV_PREFIXES or LEGAL_ENV_KEYS must cover REGISTRY_* vars."""
        prefixes = self._import_legal_env_prefixes()
        keys = self._import_legal_env_keys()
        # Check that Z_HARNESS_REGISTRY_ENABLED is covered by either keys or prefixes
        sample = "Z_HARNESS_REGISTRY_ENABLED"
        covered_by_key = sample in keys
        covered_by_prefix = any(sample.startswith(p) for p in prefixes)
        self.assertTrue(covered_by_key or covered_by_prefix,
                        msg=f"{sample!r} not covered by LEGAL_ENV_KEYS or LEGAL_ENV_PREFIXES")

    def test_preference_vars_not_in_legal_env_keys(self):
        """
        Preference-class env vars (transliterations of DEFAULTS keys) must NOT
        be in LEGAL_ENV_KEYS.

        This is the negative invariant: if a preference var were added to the
        allowlist, the TOML-wins gate would be bypassed, violating T001's purpose.
        """
        keys = self._import_legal_env_keys()
        # These are transliterations of DEFAULTS keys — they must never be allowlisted
        preference_transliterations = [
            "Z_HARNESS_NOTIFY_LEVEL",
            "Z_HARNESS_RUNTIME_PRE_REVIEW",
            "Z_HARNESS_RUNTIME_AUTO_WAIT",
            "Z_HARNESS_WORKFLOW_AUDIT_TO_AMEND",
            "Z_HARNESS_EXPERIMENT_PERSONA_ROTATION",
            "Z_HARNESS_AXIOMS_ENABLED",
        ]
        erroneously_allowlisted = [k for k in preference_transliterations if k in keys]
        self.assertEqual(erroneously_allowlisted, [],
                         msg=f"Preference-class transliterations found in LEGAL_ENV_KEYS: "
                             f"{erroneously_allowlisted!r} — these must NOT be allowlisted")


# ---------------------------------------------------------------------------
# Tests: TOML-wins gate — env does NOT override TOML-set preference values
# ---------------------------------------------------------------------------

class TestTomlWinsGate(unittest.TestCase):
    """
    Core T001 invariant: when TOML sets a preference key, the env var for that
    key is ignored on ingress.

    Failure class: preference-class env shadows TOML value.
    """

    def test_env_does_not_override_global_toml_notify_level(self):
        """
        Z_HARNESS_NOTIFY_LEVEL=all in env does NOT override notify.level="off"
        from the global TOML config.

        This is the primary acceptance-criterion test from the task spec.
        """
        global_cfg = 'schema_version = 2\n\n[notify]\nlevel = "off"\n'
        r = _run(
            ["get", "notify.level"],
            extra_env={"Z_HARNESS_NOTIFY_LEVEL": "all"},
            global_toml=global_cfg,
        )
        self.assertEqual(r.returncode, 0, msg=r.stderr)
        self.assertEqual(r.stdout.strip(), "off",
                         msg="Z_HARNESS_NOTIFY_LEVEL=all should NOT override notify.level='off' from TOML; "
                             f"got {r.stdout.strip()!r} (TOML-wins gate missing?)")

    def test_env_does_not_override_global_toml_via_legacy_alias(self):
        """
        Z_HARNESS_NOTIFY=all (legacy alias) does NOT override notify.level="approval_only"
        from the global TOML config.
        """
        global_cfg = 'schema_version = 2\n\n[notify]\nlevel = "approval_only"\n'
        r = _run(
            ["get", "notify.level"],
            extra_env={"Z_HARNESS_NOTIFY": "all"},
            global_toml=global_cfg,
        )
        self.assertEqual(r.returncode, 0, msg=r.stderr)
        self.assertEqual(r.stdout.strip(), "approval_only",
                         msg="Legacy Z_HARNESS_NOTIFY=all should NOT override notify.level from TOML; "
                             f"got {r.stdout.strip()!r}")

    def test_env_does_not_override_repo_toml(self):
        """
        Z_HARNESS_NOTIFY_LEVEL=all in env does NOT override notify.level="off"
        from the repo TOML config.
        """
        repo_cfg = 'schema_version = 2\n\n[notify]\nlevel = "off"\n'
        r = _run(
            ["get", "notify.level"],
            extra_env={"Z_HARNESS_NOTIFY_LEVEL": "all"},
            repo_toml=repo_cfg,
        )
        self.assertEqual(r.returncode, 0, msg=r.stderr)
        self.assertEqual(r.stdout.strip(), "off",
                         msg="Z_HARNESS_NOTIFY_LEVEL=all should NOT override notify.level='off' from repo TOML; "
                             f"got {r.stdout.strip()!r}")

    def test_env_does_not_override_toml_runtime_pre_review(self):
        """
        Z_HARNESS_PRE_REVIEW=true in env does NOT override runtime.pre_review=false
        from TOML.
        """
        repo_cfg = 'schema_version = 2\n\n[runtime]\npre_review = false\n'
        r = _run(
            ["get", "runtime.pre_review"],
            extra_env={"Z_HARNESS_PRE_REVIEW": "true"},
            repo_toml=repo_cfg,
        )
        self.assertEqual(r.returncode, 0, msg=r.stderr)
        self.assertEqual(r.stdout.strip(), "false",
                         msg="Z_HARNESS_PRE_REVIEW=true should NOT override runtime.pre_review=false from TOML; "
                             f"got {r.stdout.strip()!r}")

    def test_env_does_not_override_toml_hermes_max_parallel(self):
        """
        HERMES_MAX_PARALLEL=8 (T003b legacy alias) does NOT override
        runtime.max_parallel=1 from TOML.
        """
        repo_cfg = 'schema_version = 2\n\n[runtime]\nmax_parallel = 1\n'
        r = _run(
            ["get", "runtime.max_parallel"],
            extra_env={"HERMES_MAX_PARALLEL": "8"},
            repo_toml=repo_cfg,
        )
        self.assertEqual(r.returncode, 0, msg=r.stderr)
        self.assertEqual(r.stdout.strip(), "1",
                         msg="HERMES_MAX_PARALLEL=8 should NOT override runtime.max_parallel=1 from TOML; "
                             f"got {r.stdout.strip()!r}")

    def test_repo_toml_wins_over_global_toml_and_env(self):
        """
        Repo TOML wins over both global TOML and env for a preference key.
        """
        global_cfg = 'schema_version = 2\n\n[notify]\nlevel = "approval_only"\n'
        repo_cfg = 'schema_version = 2\n\n[notify]\nlevel = "off"\n'
        r = _run(
            ["get", "notify.level"],
            extra_env={"Z_HARNESS_NOTIFY_LEVEL": "all"},
            global_toml=global_cfg,
            repo_toml=repo_cfg,
        )
        self.assertEqual(r.returncode, 0, msg=r.stderr)
        self.assertEqual(r.stdout.strip(), "off",
                         msg="Repo TOML ('off') must win over global TOML ('approval_only') and env ('all')")

    def test_source_is_toml_path_not_env_when_toml_set(self):
        """
        config.py explain must report the TOML file as source, not the env var,
        when TOML has set the value.
        """
        repo_cfg = 'schema_version = 2\n\n[notify]\nlevel = "off"\n'
        r = _run(
            ["explain", "notify.level"],
            extra_env={"Z_HARNESS_NOTIFY_LEVEL": "all"},
            repo_toml=repo_cfg,
        )
        self.assertEqual(r.returncode, 0, msg=r.stderr)
        # Source must be the TOML file path, NOT the env var
        self.assertNotIn("env", r.stdout,
                         msg=f"explain should report TOML source, not env: {r.stdout!r}")
        self.assertIn("off", r.stdout,
                      msg=f"explain should show value 'off' from TOML: {r.stdout!r}")


# ---------------------------------------------------------------------------
# Tests: env still works when TOML is silent (DEFAULTS only)
# ---------------------------------------------------------------------------

class TestEnvAppliesWhenTomlSilent(unittest.TestCase):
    """
    When TOML is absent/silent for a key, env vars still set the value.
    This preserves backward-compat and the T003a/T003b migration behaviour.
    """

    def test_env_sets_notify_level_when_toml_silent(self):
        """
        Z_HARNESS_NOTIFY_LEVEL=all sets notify.level when no TOML config.
        """
        r = _run(
            ["get", "notify.level"],
            extra_env={"Z_HARNESS_NOTIFY_LEVEL": "all"},
        )
        self.assertEqual(r.returncode, 0, msg=r.stderr)
        self.assertEqual(r.stdout.strip(), "all",
                         msg="Z_HARNESS_NOTIFY_LEVEL=all should set notify.level when TOML is silent")

    def test_legacy_env_sets_value_when_toml_silent(self):
        """
        Z_HARNESS_PRE_REVIEW=true sets runtime.pre_review when TOML is silent.
        (This preserves T003a migration behavior.)
        """
        r = _run(
            ["get", "runtime.pre_review"],
            extra_env={"Z_HARNESS_PRE_REVIEW": "true"},
        )
        self.assertEqual(r.returncode, 0, msg=r.stderr)
        self.assertEqual(r.stdout.strip(), "true",
                         msg="Z_HARNESS_PRE_REVIEW=true should set runtime.pre_review when TOML is silent")

    def test_hermes_max_parallel_sets_value_when_toml_silent(self):
        """
        HERMES_MAX_PARALLEL=4 sets runtime.max_parallel when TOML is silent.
        """
        r = _run(
            ["get", "runtime.max_parallel"],
            extra_env={"HERMES_MAX_PARALLEL": "4"},
        )
        self.assertEqual(r.returncode, 0, msg=r.stderr)
        self.assertEqual(r.stdout.strip(), "4",
                         msg="HERMES_MAX_PARALLEL=4 should set runtime.max_parallel when TOML is silent")


# ---------------------------------------------------------------------------
# Tests: plumbing env vars are not affected by load_config (passthrough)
# ---------------------------------------------------------------------------

class TestPlumbingEnvPassthrough(unittest.TestCase):
    """
    Plumbing env vars (Z_HARNESS_PLAN_DIR etc.) are NOT DEFAULTS keys and
    are NOT processed by load_config(). They are read directly from the
    environment by callers. This test confirms:
    1. Z_HARNESS_PLAN_DIR is not a DEFAULTS key (not returned by config.py get)
    2. The constant LEGAL_ENV_KEYS includes Z_HARNESS_PLAN_DIR
    """

    def test_z_harness_plan_dir_is_not_a_config_key(self):
        """
        Z_HARNESS_PLAN_DIR is a plumbing var, not a DEFAULTS preference key.
        config.py get should return exit 3 (unknown key) for 'plumbing.plan_dir'
        and the env var does not affect any known preference key.
        """
        # confirm that there's no 'plumbing' section or similar in DEFAULTS
        r = _run(["get", "plumbing.plan_dir"], extra_env={"Z_HARNESS_PLAN_DIR": "/tmp/test"})
        self.assertEqual(r.returncode, 3,
                         msg="plumbing.plan_dir is not a known config key; get should exit 3")

    def test_z_harness_plan_dir_in_legal_env_keys(self):
        """Z_HARNESS_PLAN_DIR must be in LEGAL_ENV_KEYS."""
        result = subprocess.run(
            [sys.executable, "-c",
             "import sys; sys.path.insert(0, 'scripts');"
             "from config import LEGAL_ENV_KEYS; print('yes' if 'Z_HARNESS_PLAN_DIR' in LEGAL_ENV_KEYS else 'no')"],
            capture_output=True,
            text=True,
            cwd=str(_REPO_ROOT),
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertEqual(result.stdout.strip(), "yes",
                         msg="Z_HARNESS_PLAN_DIR must be in LEGAL_ENV_KEYS (plumbing passthrough)")

    def test_plumbing_env_does_not_interfere_with_preference_resolution(self):
        """
        Setting Z_HARNESS_PLAN_DIR does not affect preference key resolution.
        """
        r = _run(
            ["get", "notify.level"],
            extra_env={"Z_HARNESS_PLAN_DIR": "/some/plan/dir"},
        )
        self.assertEqual(r.returncode, 0, msg=r.stderr)
        self.assertEqual(r.stdout.strip(), "approval_only",
                         msg="Z_HARNESS_PLAN_DIR should not affect notify.level resolution")


# ---------------------------------------------------------------------------
# Tests: startup guards still pass after T001 changes
# ---------------------------------------------------------------------------

class TestStartupGuardsPass(unittest.TestCase):
    """config.py must import cleanly (startup guards pass) after T001 changes."""

    def test_module_imports_cleanly(self):
        """
        Importing config.py must succeed (exit 0) and startup guards must pass.
        """
        result = subprocess.run(
            [sys.executable, "-c",
             "import sys; sys.path.insert(0, 'scripts'); import config; print('ok')"],
            capture_output=True,
            text=True,
            cwd=str(_REPO_ROOT),
        )
        self.assertEqual(result.returncode, 0,
                         msg=f"config.py failed to import: {result.stderr}")
        self.assertEqual(result.stdout.strip(), "ok",
                         msg=f"config.py import produced unexpected output: {result.stdout!r}")

    def test_legal_env_keys_is_frozenset(self):
        """LEGAL_ENV_KEYS must be a frozenset (immutable)."""
        result = subprocess.run(
            [sys.executable, "-c",
             "import sys; sys.path.insert(0, 'scripts');"
             "from config import LEGAL_ENV_KEYS; print(type(LEGAL_ENV_KEYS).__name__)"],
            capture_output=True,
            text=True,
            cwd=str(_REPO_ROOT),
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertEqual(result.stdout.strip(), "frozenset",
                         msg="LEGAL_ENV_KEYS must be a frozenset")

    def test_legal_env_prefixes_is_tuple(self):
        """LEGAL_ENV_PREFIXES must be a tuple (ordered, immutable)."""
        result = subprocess.run(
            [sys.executable, "-c",
             "import sys; sys.path.insert(0, 'scripts');"
             "from config import LEGAL_ENV_PREFIXES; print(type(LEGAL_ENV_PREFIXES).__name__)"],
            capture_output=True,
            text=True,
            cwd=str(_REPO_ROOT),
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertEqual(result.stdout.strip(), "tuple",
                         msg="LEGAL_ENV_PREFIXES must be a tuple")


if __name__ == "__main__":
    unittest.main()
