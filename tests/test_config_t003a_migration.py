"""
Tests for T003a — workflow/runtime/notify preference env-var migration.

Verifies that every key migrated in T003a:
  - Is present in DEFAULTS
  - Is present in VALIDATORS
  - Can be resolved via `config.py get`
  - Accepts its legacy raw env var name on ingress (dotted→env round-trip)
  - Shows up as TOML-persistent (not env-only) in inspect-all output

Migration table (raw name → dotted key → section → type → default):
  Z_HARNESS_PRE_REVIEW          → runtime.pre_review         → [runtime] → bool  → false
  Z_HARNESS_IMPL_PRE_REVIEW     → runtime.impl_pre_review    → [runtime] → bool  → false
  Z_HARNESS_AUTO_WAIT           → runtime.auto_wait          → [runtime] → bool  → true
  Z_HARNESS_AUTO_WAIT_BUDGET_SECS → runtime.auto_wait_budget_secs → [runtime] → int → 300
  Z_HARNESS_PAUSE_AT_PCT        → runtime.pause_at_pct       → [runtime] → int   → 85
  Z_HARNESS_EXPLAIN_RESOLUTION  → runtime.explain_resolution → [runtime] → bool  → false
  Z_HARNESS_NOTIFY (ingress-only) → notify.level             → [notify]  → str   → approval_only

Already-aliased (existed before T003a; verified here for completeness):
  Z_HARNESS_CONSULT             → runtime.consult            → [runtime] → str   → on
  Z_HARNESS_NOTIFY_LEVEL        → notify.level               → [notify]  → str   → approval_only
  Z_HARNESS_DOCS_ALWAYS_APPLY   → docs.always_apply          → [docs]    → str   → always
"""

import json
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
    extra_env: dict | None = None,
) -> subprocess.CompletedProcess:
    """Run config.py with an isolated XDG_CONFIG_HOME and empty repo config."""
    env = {k: v for k, v in os.environ.items()}
    with tempfile.TemporaryDirectory() as td:
        td_path = Path(td)
        env["XDG_CONFIG_HOME"] = str(td_path)
        # Suppress repo-level config discovery so z-harness/.z-harness/config.toml
        # (which has schema_version=1) doesn't pollute these tests.
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


# ---------------------------------------------------------------------------
# Migration table: (raw_env_name, dotted_key, expected_default_str, legacy_test_value)
# ---------------------------------------------------------------------------

# Each tuple: (legacy_raw_env_name, dotted_key, expected_default_str, test_value_to_set)
_T003A_EGRESS_ALIASES = [
    # raw env name              dotted key                  expected default   test value
    ("Z_HARNESS_PRE_REVIEW",         "runtime.pre_review",          "false",    "true"),
    ("Z_HARNESS_IMPL_PRE_REVIEW",    "runtime.impl_pre_review",     "false",    "true"),
    ("Z_HARNESS_AUTO_WAIT",          "runtime.auto_wait",           "true",     "false"),
    ("Z_HARNESS_AUTO_WAIT_BUDGET_SECS", "runtime.auto_wait_budget_secs", "300", "600"),
    ("Z_HARNESS_PAUSE_AT_PCT",       "runtime.pause_at_pct",        "85",       "70"),
    ("Z_HARNESS_EXPLAIN_RESOLUTION", "runtime.explain_resolution",  "false",    "true"),
]

# notify.level: Z_HARNESS_NOTIFY is ingress-only; export uses Z_HARNESS_NOTIFY_LEVEL.
_NOTIFY_LEGACY_INGRESS = ("Z_HARNESS_NOTIFY", "notify.level", "approval_only", "all")


class TestT003aDefaultsPresent(unittest.TestCase):
    """Every migrated key must be present in DEFAULTS and have the expected default."""

    def _import_defaults(self) -> dict:
        result = subprocess.run(
            [sys.executable, "-c",
             "import sys; sys.path.insert(0, 'scripts');"
             "from config import DEFAULTS; import json; print(json.dumps(DEFAULTS, default=str))"],
            capture_output=True,
            text=True,
            cwd=str(_REPO_ROOT),
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        return json.loads(result.stdout)

    def test_runtime_section_has_all_t003a_keys(self):
        defaults = self._import_defaults()
        runtime = defaults.get("runtime", {})
        for _raw, dotted, _default, _val in _T003A_EGRESS_ALIASES:
            section, key = dotted.split(".", 1)
            self.assertEqual(section, "runtime")
            self.assertIn(key, runtime,
                          msg=f"DEFAULTS['runtime'] missing key {key!r} (migrated from {_raw})")

    def test_notify_level_in_defaults(self):
        defaults = self._import_defaults()
        self.assertIn("level", defaults.get("notify", {}),
                      msg="DEFAULTS['notify'] missing 'level'")


class TestT003aValidatorsPresent(unittest.TestCase):
    """Every migrated key must be present in VALIDATORS."""

    def _import_validators_keys(self) -> set:
        result = subprocess.run(
            [sys.executable, "-c",
             "import sys; sys.path.insert(0, 'scripts');"
             "from config import VALIDATORS; import json; print(json.dumps(list(VALIDATORS.keys())))"],
            capture_output=True,
            text=True,
            cwd=str(_REPO_ROOT),
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        return set(json.loads(result.stdout))

    def test_all_t003a_keys_in_validators(self):
        validator_keys = self._import_validators_keys()
        for _raw, dotted, _default, _val in _T003A_EGRESS_ALIASES:
            self.assertIn(dotted, validator_keys,
                          msg=f"VALIDATORS missing {dotted!r} (migrated from {_raw})")

    def test_notify_level_in_validators(self):
        validator_keys = self._import_validators_keys()
        self.assertIn("notify.level", validator_keys)

    # Already-aliased keys
    def test_already_aliased_in_validators(self):
        validator_keys = self._import_validators_keys()
        for key in ("runtime.consult", "notify.level", "docs.always_apply"):
            self.assertIn(key, validator_keys,
                          msg=f"VALIDATORS missing pre-existing key {key!r}")


class TestT003aDefaultValues(unittest.TestCase):
    """config.py get returns the expected default for every migrated key."""

    def test_defaults_via_get(self):
        for _raw, dotted, expected, _val in _T003A_EGRESS_ALIASES:
            with self.subTest(dotted=dotted):
                r = _run(["get", dotted])
                self.assertEqual(r.returncode, 0,
                                 msg=f"get {dotted!r} exited {r.returncode}; stderr={r.stderr}")
                self.assertEqual(r.stdout.strip(), expected,
                                 msg=f"Default for {dotted!r} should be {expected!r}")

    def test_notify_level_default(self):
        r = _run(["get", "notify.level"])
        self.assertEqual(r.returncode, 0, msg=r.stderr)
        self.assertEqual(r.stdout.strip(), "approval_only")


class TestT003aLegacyEnvIngress(unittest.TestCase):
    """Legacy raw env var names are accepted as ingress overrides."""

    def test_egress_alias_env_vars_read_on_ingress(self):
        """Setting the legacy raw env var overrides the config key value."""
        for raw_env, dotted, _default, test_val in _T003A_EGRESS_ALIASES:
            with self.subTest(raw_env=raw_env, dotted=dotted):
                r = _run(["get", dotted], extra_env={raw_env: test_val})
                self.assertEqual(r.returncode, 0,
                                 msg=f"get {dotted!r} with {raw_env}={test_val!r} failed; "
                                     f"stderr={r.stderr}")
                self.assertEqual(r.stdout.strip(), test_val,
                                 msg=f"Expected {test_val!r} for {dotted!r} via {raw_env}; "
                                     f"got {r.stdout.strip()!r}")

    def test_z_harness_notify_legacy_ingress(self):
        """Z_HARNESS_NOTIFY (legacy name for notify.level) is read on ingress."""
        raw_env, dotted, _default, test_val = _NOTIFY_LEGACY_INGRESS
        r = _run(["get", dotted], extra_env={raw_env: test_val})
        self.assertEqual(r.returncode, 0,
                         msg=f"get notify.level with {raw_env}={test_val!r} failed; "
                             f"stderr={r.stderr}")
        self.assertEqual(r.stdout.strip(), test_val,
                         msg=f"Expected {test_val!r} for notify.level via {raw_env}; "
                             f"got {r.stdout.strip()!r}")

    def test_transliteration_env_var_takes_precedence_over_legacy(self):
        """When both transliteration and legacy var are set, transliteration wins."""
        # runtime.pre_review: transliteration = Z_HARNESS_RUNTIME_PRE_REVIEW, legacy = Z_HARNESS_PRE_REVIEW
        r = _run(["get", "runtime.pre_review"], extra_env={
            "Z_HARNESS_RUNTIME_PRE_REVIEW": "false",
            "Z_HARNESS_PRE_REVIEW": "true",  # legacy — should lose
        })
        self.assertEqual(r.returncode, 0, msg=r.stderr)
        self.assertEqual(r.stdout.strip(), "false",
                         msg="Transliteration env var should take precedence over legacy alias")


class TestT003aExportEnvLegacyNames(unittest.TestCase):
    """export-env emits the legacy raw names for T003a keys."""

    def _export_env_output(self) -> str:
        r = _run(["export-env"])
        self.assertEqual(r.returncode, 0, msg=r.stderr)
        return r.stdout

    def test_export_uses_legacy_names(self):
        """export-env must emit Z_HARNESS_PRE_REVIEW, Z_HARNESS_AUTO_WAIT, etc."""
        output = self._export_env_output()
        for raw_env, _dotted, _default, _val in _T003A_EGRESS_ALIASES:
            self.assertIn(raw_env, output,
                          msg=f"export-env output missing {raw_env!r}")

    def test_export_notify_level_uses_transliteration(self):
        """notify.level exports as Z_HARNESS_NOTIFY_LEVEL (not Z_HARNESS_NOTIFY)."""
        output = self._export_env_output()
        self.assertIn("Z_HARNESS_NOTIFY_LEVEL", output,
                      msg="export-env must export Z_HARNESS_NOTIFY_LEVEL for notify.level")
        # Z_HARNESS_NOTIFY should NOT appear as an export target (it's ingress-only legacy)
        # (note: Z_HARNESS_NOTIFY_DISCORD_WEBHOOK_URL is fine — different key)
        lines = output.splitlines()
        notify_lines = [l for l in lines if "Z_HARNESS_NOTIFY=" in l]
        self.assertEqual(notify_lines, [],
                         msg="export-env must NOT emit Z_HARNESS_NOTIFY= (use Z_HARNESS_NOTIFY_LEVEL)")


class TestT003aInspectAllShowsConfig(unittest.TestCase):
    """inspect-all shows T003a keys as TOML-persistent, not env-only."""

    def _inspect_json(self) -> dict:
        r = _run(["inspect-all", "--json"])
        self.assertEqual(r.returncode, 0, msg=r.stderr)
        return json.loads(r.stdout)

    def test_migrated_keys_in_toml_section(self):
        data = self._inspect_json()
        toml_keys = data.get("toml_keys", {})
        for _raw, dotted, _default, _val in _T003A_EGRESS_ALIASES:
            self.assertIn(dotted, toml_keys,
                          msg=f"inspect-all toml_keys missing {dotted!r}")

    def test_migrated_keys_not_in_env_only_section(self):
        data = self._inspect_json()
        env_only = data.get("env_only_knobs", {})
        migrated_raw_names = {raw for raw, *_ in _T003A_EGRESS_ALIASES}
        migrated_raw_names.add("Z_HARNESS_NOTIFY")
        for knob_name in env_only.keys():
            self.assertNotIn(knob_name, migrated_raw_names,
                             msg=f"{knob_name!r} should have been removed from ENV_ONLY_KNOBS "
                                 "(it was migrated to DEFAULTS in T003a)")


class TestT003aAlreadyAliasedKeys(unittest.TestCase):
    """Pre-existing already-aliased keys (CONSULT, NOTIFY_LEVEL, DOCS_ALWAYS_APPLY)
    still work correctly after T003a changes."""

    def test_consult_default(self):
        r = _run(["get", "runtime.consult"])
        self.assertEqual(r.returncode, 0, msg=r.stderr)
        self.assertEqual(r.stdout.strip(), "on")

    def test_notify_level_default(self):
        r = _run(["get", "notify.level"])
        self.assertEqual(r.returncode, 0, msg=r.stderr)
        self.assertEqual(r.stdout.strip(), "approval_only")

    def test_docs_always_apply_default(self):
        r = _run(["get", "docs.always_apply"])
        self.assertEqual(r.returncode, 0, msg=r.stderr)
        self.assertEqual(r.stdout.strip(), "always")

    def test_z_harness_consult_ingress(self):
        """Z_HARNESS_CONSULT (legacy) is still honoured on ingress."""
        r = _run(["get", "runtime.consult"], extra_env={"Z_HARNESS_CONSULT": "off"})
        self.assertEqual(r.returncode, 0, msg=r.stderr)
        self.assertEqual(r.stdout.strip(), "off")

    def test_z_harness_notify_level_ingress(self):
        """Z_HARNESS_NOTIFY_LEVEL (transliteration) still overrides notify.level."""
        r = _run(["get", "notify.level"], extra_env={"Z_HARNESS_NOTIFY_LEVEL": "all"})
        self.assertEqual(r.returncode, 0, msg=r.stderr)
        self.assertEqual(r.stdout.strip(), "all")


if __name__ == "__main__":
    unittest.main()
