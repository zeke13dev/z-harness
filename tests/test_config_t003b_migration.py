"""
Tests for T003b — parallelism/review/docs/limits preference env-var migration.

Verifies that every key migrated in T003b:
  - Is present in DEFAULTS
  - Is present in VALIDATORS
  - Can be resolved via `config.py get`
  - Accepts its legacy raw env var name on ingress (dotted→env round-trip)
  - Exports under the legacy raw name via `config.py export-env`
  - Shows up as TOML-persistent (not env-only) in inspect-all output

Also verifies that the final ENV_ONLY_KNOBS list contains ONLY the allowlisted
plumbing/unattended vars (completeness invariant).

Migration table (raw name → dotted key → section → type → default):
  Z_HARNESS_MAX_EXPLORE           → workflow.max_explore        → [workflow] → int  → 3
  Z_HARNESS_PARALLEL              → workflow.parallel           → [workflow] → int  → 3
  Z_HARNESS_MEMORY_STALE_DAYS     → workflow.memory_stale_days  → [workflow] → int  → 547
  Z_HARNESS_DOC_STALENESS_THRESHOLD → docs.staleness_threshold  → [docs]     → int  → 20
  HERMES_MAX_PARALLEL             → runtime.max_parallel        → [runtime]  → int  → 1
  Z_HARNESS_MAX_PARALLEL_PLANS    → runtime.max_parallel_plans  → [runtime]  → int  → 1
  Z_HARNESS_MAX_ATTEMPTS          → runtime.max_attempts        → [runtime]  → int  → 2
  Z_HARNESS_MAX_TASK_WALL_MS      → runtime.max_task_wall_ms    → [runtime]  → int  → 2700000
  Z_HARNESS_AXIOM_EXTRACT         → axioms.auto_extract_post_run (alias only; key already existed)

Plumbing/unattended vars that MUST stay env-only (not migrated):
  Z_HARNESS_NO_ASK, Z_HARNESS_OVERNIGHT_AUTODECIDE, Z_HARNESS_OVERNIGHT_AUTODECIDE_EFFECTIVE,
  Z_HARNESS_ASK_ALL, Z_HARNESS_REPO_PROVIDERS, Z_HARNESS_PLANS_DIR,
  Z_HARNESS_BASE_DIR, Z_HARNESS_EXTERNAL_DEFAULT, Z_HARNESS_REGISTRY_ENABLED,
  Z_HARNESS_REGISTRY_STALE_SECS, Z_HARNESS_STRICT_OVERLAP,
  Z_HARNESS_WAIT_POLL_SECS, Z_HARNESS_WAIT_TIMEOUT_SECS, Z_HARNESS_WAIT_REQUIRE_MERGE,
  Z_HARNESS_LOCAL_CARGO_CLEAN, Z_HARNESS_ERROR_POINT_MAX_NEW,
  Z_HARNESS_ERROR_POINT_PRUNE_DAYS, Z_HARNESS_ERROR_POINT_PRUNE_MAX_FREQ
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
# Migration table
# ---------------------------------------------------------------------------

# (raw_env_name, dotted_key, expected_default_str, test_value_to_set)
_T003B_EGRESS_ALIASES = [
    # raw env name                         dotted key                       default        test value
    ("Z_HARNESS_MAX_EXPLORE",              "workflow.max_explore",          "3",           "5"),
    ("Z_HARNESS_PARALLEL",                 "workflow.parallel",             "3",           "5"),
    ("Z_HARNESS_MEMORY_STALE_DAYS",        "workflow.memory_stale_days",    "547",         "365"),
    ("Z_HARNESS_DOC_STALENESS_THRESHOLD",  "docs.staleness_threshold",      "20",          "30"),
    ("HERMES_MAX_PARALLEL",                "runtime.max_parallel",          "1",           "3"),
    ("Z_HARNESS_MAX_PARALLEL_PLANS",       "runtime.max_parallel_plans",    "1",           "2"),
    ("Z_HARNESS_MAX_ATTEMPTS",             "runtime.max_attempts",          "2",           "3"),
    ("Z_HARNESS_MAX_TASK_WALL_MS",         "runtime.max_task_wall_ms",      "2700000",     "1800000"),
]

# axioms.auto_extract_post_run: Z_HARNESS_AXIOM_EXTRACT is ingress+egress alias;
# the key already existed before T003b.
_AXIOM_EXTRACT_INGRESS = ("Z_HARNESS_AXIOM_EXTRACT", "axioms.auto_extract_post_run", "true", "false")

# Plumbing/unattended: these MUST stay env-only (not in DEFAULTS, not settable via TOML).
_ENV_ONLY_ALLOWLIST = frozenset({
    "Z_HARNESS_NO_ASK",
    "Z_HARNESS_OVERNIGHT_AUTODECIDE",
    "Z_HARNESS_OVERNIGHT_AUTODECIDE_EFFECTIVE",
    "Z_HARNESS_ASK_ALL",
    "Z_HARNESS_REPO_PROVIDERS",
    "Z_HARNESS_PLANS_DIR",
    "Z_HARNESS_BASE_DIR",
    "Z_HARNESS_EXTERNAL_DEFAULT",
    "Z_HARNESS_REGISTRY_ENABLED",
    "Z_HARNESS_REGISTRY_STALE_SECS",
    "Z_HARNESS_STRICT_OVERLAP",
    "Z_HARNESS_WAIT_POLL_SECS",
    "Z_HARNESS_WAIT_TIMEOUT_SECS",
    "Z_HARNESS_WAIT_REQUIRE_MERGE",
    "Z_HARNESS_LOCAL_CARGO_CLEAN",
    "Z_HARNESS_ERROR_POINT_MAX_NEW",
    "Z_HARNESS_ERROR_POINT_PRUNE_DAYS",
    "Z_HARNESS_ERROR_POINT_PRUNE_MAX_FREQ",
})


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _import_defaults() -> dict:
    result = subprocess.run(
        [sys.executable, "-c",
         "import sys; sys.path.insert(0, 'scripts');"
         "from config import DEFAULTS; import json; print(json.dumps(DEFAULTS, default=str))"],
        capture_output=True,
        text=True,
        cwd=str(_REPO_ROOT),
    )
    if result.returncode != 0:
        raise AssertionError(f"Failed to import DEFAULTS: {result.stderr}")
    return json.loads(result.stdout)


def _import_validators_keys() -> set:
    result = subprocess.run(
        [sys.executable, "-c",
         "import sys; sys.path.insert(0, 'scripts');"
         "from config import VALIDATORS; import json; print(json.dumps(list(VALIDATORS.keys())))"],
        capture_output=True,
        text=True,
        cwd=str(_REPO_ROOT),
    )
    if result.returncode != 0:
        raise AssertionError(f"Failed to import VALIDATORS: {result.stderr}")
    return set(json.loads(result.stdout))


def _import_env_only_knobs() -> list:
    result = subprocess.run(
        [sys.executable, "-c",
         "import sys; sys.path.insert(0, 'scripts');"
         "from config import ENV_ONLY_KNOBS; import json; print(json.dumps(ENV_ONLY_KNOBS))"],
        capture_output=True,
        text=True,
        cwd=str(_REPO_ROOT),
    )
    if result.returncode != 0:
        raise AssertionError(f"Failed to import ENV_ONLY_KNOBS: {result.stderr}")
    return json.loads(result.stdout)


# ---------------------------------------------------------------------------
# Tests: DEFAULTS presence
# ---------------------------------------------------------------------------

class TestT003bDefaultsPresent(unittest.TestCase):
    """Every migrated key must be present in DEFAULTS and have the expected section."""

    def test_workflow_section_has_all_t003b_workflow_keys(self):
        defaults = _import_defaults()
        workflow = defaults.get("workflow", {})
        for raw, dotted, _default, _val in _T003B_EGRESS_ALIASES:
            section, key = dotted.split(".", 1)
            if section != "workflow":
                continue
            self.assertIn(key, workflow,
                          msg=f"DEFAULTS['workflow'] missing key {key!r} (migrated from {raw})")

    def test_docs_section_has_staleness_threshold(self):
        defaults = _import_defaults()
        docs = defaults.get("docs", {})
        self.assertIn("staleness_threshold", docs,
                      msg="DEFAULTS['docs'] missing 'staleness_threshold' (migrated from Z_HARNESS_DOC_STALENESS_THRESHOLD)")

    def test_runtime_section_has_all_t003b_runtime_keys(self):
        defaults = _import_defaults()
        runtime = defaults.get("runtime", {})
        for raw, dotted, _default, _val in _T003B_EGRESS_ALIASES:
            section, key = dotted.split(".", 1)
            if section != "runtime":
                continue
            self.assertIn(key, runtime,
                          msg=f"DEFAULTS['runtime'] missing key {key!r} (migrated from {raw})")

    def test_axioms_auto_extract_post_run_in_defaults(self):
        defaults = _import_defaults()
        axioms = defaults.get("axioms", {})
        self.assertIn("auto_extract_post_run", axioms,
                      msg="DEFAULTS['axioms'] missing 'auto_extract_post_run' "
                          "(aliased from Z_HARNESS_AXIOM_EXTRACT)")


# ---------------------------------------------------------------------------
# Tests: VALIDATORS presence
# ---------------------------------------------------------------------------

class TestT003bValidatorsPresent(unittest.TestCase):
    """Every migrated key must be present in VALIDATORS."""

    def test_all_t003b_keys_in_validators(self):
        validator_keys = _import_validators_keys()
        for raw, dotted, _default, _val in _T003B_EGRESS_ALIASES:
            self.assertIn(dotted, validator_keys,
                          msg=f"VALIDATORS missing {dotted!r} (migrated from {raw})")

    def test_axioms_auto_extract_post_run_in_validators(self):
        validator_keys = _import_validators_keys()
        self.assertIn("axioms.auto_extract_post_run", validator_keys)


# ---------------------------------------------------------------------------
# Tests: default values via config.py get
# ---------------------------------------------------------------------------

class TestT003bDefaultValues(unittest.TestCase):
    """config.py get returns the expected default for every migrated key."""

    def test_defaults_via_get(self):
        for _raw, dotted, expected, _val in _T003B_EGRESS_ALIASES:
            with self.subTest(dotted=dotted):
                r = _run(["get", dotted])
                self.assertEqual(r.returncode, 0,
                                 msg=f"get {dotted!r} exited {r.returncode}; stderr={r.stderr}")
                self.assertEqual(r.stdout.strip(), expected,
                                 msg=f"Default for {dotted!r} should be {expected!r}, "
                                     f"got {r.stdout.strip()!r}")

    def test_axioms_auto_extract_post_run_default(self):
        r = _run(["get", "axioms.auto_extract_post_run"])
        self.assertEqual(r.returncode, 0, msg=r.stderr)
        self.assertEqual(r.stdout.strip(), "true",
                         msg="axioms.auto_extract_post_run should default to 'true'")


# ---------------------------------------------------------------------------
# Tests: legacy ingress aliases
# ---------------------------------------------------------------------------

class TestT003bLegacyEnvIngress(unittest.TestCase):
    """Legacy raw env var names are accepted as ingress overrides."""

    def test_egress_alias_env_vars_read_on_ingress(self):
        """Setting the legacy raw env var overrides the config key value."""
        for raw_env, dotted, _default, test_val in _T003B_EGRESS_ALIASES:
            with self.subTest(raw_env=raw_env, dotted=dotted):
                r = _run(["get", dotted], extra_env={raw_env: test_val})
                self.assertEqual(r.returncode, 0,
                                 msg=f"get {dotted!r} with {raw_env}={test_val!r} failed; "
                                     f"stderr={r.stderr}")
                self.assertEqual(r.stdout.strip(), test_val,
                                 msg=f"Expected {test_val!r} for {dotted!r} via {raw_env}; "
                                     f"got {r.stdout.strip()!r}")

    def test_z_harness_axiom_extract_legacy_ingress_false(self):
        """Z_HARNESS_AXIOM_EXTRACT=0 is accepted and coerced to false."""
        r = _run(["get", "axioms.auto_extract_post_run"],
                 extra_env={"Z_HARNESS_AXIOM_EXTRACT": "0"})
        self.assertEqual(r.returncode, 0,
                         msg=f"get axioms.auto_extract_post_run with AXIOM_EXTRACT=0 failed; "
                             f"stderr={r.stderr}")
        self.assertEqual(r.stdout.strip(), "false",
                         msg="Z_HARNESS_AXIOM_EXTRACT=0 should resolve axioms.auto_extract_post_run to false")

    def test_z_harness_axiom_extract_legacy_ingress_true(self):
        """Z_HARNESS_AXIOM_EXTRACT=1 is accepted and coerced to true."""
        r = _run(["get", "axioms.auto_extract_post_run"],
                 extra_env={"Z_HARNESS_AXIOM_EXTRACT": "1"})
        self.assertEqual(r.returncode, 0,
                         msg=f"get axioms.auto_extract_post_run with AXIOM_EXTRACT=1 failed; "
                             f"stderr={r.stderr}")
        self.assertEqual(r.stdout.strip(), "true",
                         msg="Z_HARNESS_AXIOM_EXTRACT=1 should resolve axioms.auto_extract_post_run to true")

    def test_transliteration_takes_precedence_over_legacy(self):
        """When both transliteration and legacy var are set, transliteration wins."""
        # workflow.max_explore: transliteration = Z_HARNESS_WORKFLOW_MAX_EXPLORE, legacy = Z_HARNESS_MAX_EXPLORE
        r = _run(["get", "workflow.max_explore"], extra_env={
            "Z_HARNESS_WORKFLOW_MAX_EXPLORE": "10",
            "Z_HARNESS_MAX_EXPLORE": "5",  # legacy — should lose
        })
        self.assertEqual(r.returncode, 0, msg=r.stderr)
        self.assertEqual(r.stdout.strip(), "10",
                         msg="Transliteration env var (Z_HARNESS_WORKFLOW_MAX_EXPLORE) should take "
                             "precedence over legacy alias (Z_HARNESS_MAX_EXPLORE)")

    def test_hermes_max_parallel_ingress(self):
        """HERMES_MAX_PARALLEL (non-standard Z_HARNESS prefix) is accepted on ingress."""
        r = _run(["get", "runtime.max_parallel"], extra_env={"HERMES_MAX_PARALLEL": "4"})
        self.assertEqual(r.returncode, 0, msg=r.stderr)
        self.assertEqual(r.stdout.strip(), "4",
                         msg="HERMES_MAX_PARALLEL=4 should resolve runtime.max_parallel to 4")


# ---------------------------------------------------------------------------
# Tests: export-env emits legacy names
# ---------------------------------------------------------------------------

class TestT003bExportEnvLegacyNames(unittest.TestCase):
    """export-env emits the legacy raw names for T003b keys."""

    def _export_env_output(self) -> str:
        r = _run(["export-env"])
        self.assertEqual(r.returncode, 0, msg=r.stderr)
        return r.stdout

    def test_export_uses_legacy_names(self):
        """export-env must emit legacy raw names for all T003b egress aliases."""
        output = self._export_env_output()
        for raw_env, _dotted, _default, _val in _T003B_EGRESS_ALIASES:
            self.assertIn(raw_env, output,
                          msg=f"export-env output missing {raw_env!r}")

    def test_export_axiom_extract_uses_legacy_name(self):
        """export-env must emit Z_HARNESS_AXIOM_EXTRACT for axioms.auto_extract_post_run."""
        output = self._export_env_output()
        self.assertIn("Z_HARNESS_AXIOM_EXTRACT", output,
                      msg="export-env must emit Z_HARNESS_AXIOM_EXTRACT for axioms.auto_extract_post_run")

    def test_export_does_not_emit_mechanical_names_for_aliased_keys(self):
        """Keys with legacy aliases must NOT also emit the mechanical transliteration name."""
        output = self._export_env_output()
        # These mechanical names should NOT appear since the alias takes precedence:
        mechanical_names_that_must_not_appear = [
            "Z_HARNESS_WORKFLOW_MAX_EXPLORE=",
            "Z_HARNESS_WORKFLOW_PARALLEL=",
            "Z_HARNESS_WORKFLOW_MEMORY_STALE_DAYS=",
            "Z_HARNESS_DOCS_STALENESS_THRESHOLD=",
            "Z_HARNESS_RUNTIME_MAX_PARALLEL=",
            "Z_HARNESS_RUNTIME_MAX_PARALLEL_PLANS=",
            "Z_HARNESS_RUNTIME_MAX_ATTEMPTS=",
            "Z_HARNESS_RUNTIME_MAX_TASK_WALL_MS=",
            "Z_HARNESS_AXIOMS_AUTO_EXTRACT_POST_RUN=",
        ]
        for mech in mechanical_names_that_must_not_appear:
            self.assertNotIn(mech, output,
                             msg=f"export-env emits mechanical name {mech!r} but should emit "
                                 "the legacy alias instead")


# ---------------------------------------------------------------------------
# Tests: inspect-all shows config (not env-only)
# ---------------------------------------------------------------------------

class TestT003bInspectAllShowsConfig(unittest.TestCase):
    """inspect-all shows T003b keys as TOML-persistent, not env-only."""

    def _inspect_json(self) -> dict:
        r = _run(["inspect-all", "--json"])
        self.assertEqual(r.returncode, 0, msg=r.stderr)
        return json.loads(r.stdout)

    def test_migrated_keys_in_toml_section(self):
        data = self._inspect_json()
        toml_keys = data.get("toml_keys", {})
        for _raw, dotted, _default, _val in _T003B_EGRESS_ALIASES:
            self.assertIn(dotted, toml_keys,
                          msg=f"inspect-all toml_keys missing {dotted!r}")
        self.assertIn("axioms.auto_extract_post_run", toml_keys,
                      msg="inspect-all toml_keys missing 'axioms.auto_extract_post_run'")

    def test_migrated_raw_names_not_in_env_only_section(self):
        """Raw legacy names of migrated keys must NOT be in env_only_knobs."""
        data = self._inspect_json()
        env_only = data.get("env_only_knobs", {})
        migrated_raw_names = {raw for raw, *_ in _T003B_EGRESS_ALIASES}
        migrated_raw_names.add("Z_HARNESS_AXIOM_EXTRACT")
        for knob_name in env_only.keys():
            self.assertNotIn(knob_name, migrated_raw_names,
                             msg=f"{knob_name!r} should have been removed from ENV_ONLY_KNOBS "
                                 "(it was migrated to DEFAULTS in T003b)")


# ---------------------------------------------------------------------------
# Tests: ENV_ONLY_KNOBS completeness — ONLY allowlist members remain
# ---------------------------------------------------------------------------

class TestT003bEnvOnlyAllowlistCompleteness(unittest.TestCase):
    """
    The final ENV_ONLY_KNOBS list must contain ONLY allowlisted
    plumbing/unattended vars — no preference vars remain.

    This is the completeness invariant from the T003b acceptance criteria.
    """

    def test_env_only_knobs_are_only_allowlist_members(self):
        """Every entry in ENV_ONLY_KNOBS must be in the allowlist."""
        knobs = _import_env_only_knobs()
        rogue = [k for k in knobs if k not in _ENV_ONLY_ALLOWLIST]
        self.assertEqual(rogue, [],
                         msg=f"ENV_ONLY_KNOBS contains non-allowlist members: {rogue!r}. "
                             "These are probably preference vars that should be migrated to DEFAULTS.")

    def test_all_allowlist_members_present_in_env_only(self):
        """
        Every allowlisted plumbing/unattended var must appear in ENV_ONLY_KNOBS.

        This guards against accidentally removing documented plumbing vars from
        inspect-all visibility.
        """
        knobs = set(_import_env_only_knobs())
        missing = [k for k in _ENV_ONLY_ALLOWLIST if k not in knobs]
        self.assertEqual(missing, [],
                         msg=f"Expected plumbing/unattended vars missing from ENV_ONLY_KNOBS: "
                             f"{missing!r}")

    def test_migrated_vars_not_in_env_only_knobs(self):
        """
        The T003b-migrated vars must NOT appear in ENV_ONLY_KNOBS — they
        have been promoted to TOML-persistent.

        This test FAILS if a migrated var is erroneously left in ENV_ONLY_KNOBS,
        which is the failure class for the T003b plumbing-stays-env-only invariant
        (the inverse violation: if a migrated key were still env-only, it wouldn't
        be configurable via TOML and this test would catch it).
        """
        knobs = set(_import_env_only_knobs())
        migrated_raw_names = {raw for raw, *_ in _T003B_EGRESS_ALIASES}
        migrated_raw_names.add("Z_HARNESS_AXIOM_EXTRACT")
        erroneously_present = [k for k in migrated_raw_names if k in knobs]
        self.assertEqual(erroneously_present, [],
                         msg=f"Migrated raw names found in ENV_ONLY_KNOBS (should be removed): "
                             f"{erroneously_present!r}")

    def test_plumbing_vars_not_in_defaults(self):
        """
        Allowlisted plumbing/unattended vars must NOT have DEFAULTS entries.

        Verifies the negative side: these are NOT preference keys and must stay env-only.
        """
        defaults = _import_defaults()
        # Flatten defaults to dotted keys
        flat_keys = set()
        for section, val in defaults.items():
            if isinstance(val, dict):
                for k in val:
                    flat_keys.add(f"{section}.{k}")

        # These plumbing vars should not correspond to any DEFAULTS key.
        # We can only check "Z_HARNESS_<X>" vars with obvious transliterations.
        # For each allowlist member that follows the Z_HARNESS_<SECTION>_<KEY> pattern:
        plumbing_that_must_not_be_in_defaults = [
            "Z_HARNESS_NO_ASK",
            "Z_HARNESS_ASK_ALL",
            "Z_HARNESS_WAIT_POLL_SECS",
            "Z_HARNESS_WAIT_TIMEOUT_SECS",
            "Z_HARNESS_WAIT_REQUIRE_MERGE",
            "Z_HARNESS_LOCAL_CARGO_CLEAN",
        ]
        for raw in plumbing_that_must_not_be_in_defaults:
            # Convert Z_HARNESS_FOO_BAR → foo.bar to check DEFAULTS
            if not raw.startswith("Z_HARNESS_"):
                continue
            parts = raw[len("Z_HARNESS_"):].lower().split("_", 1)
            if len(parts) == 2:
                dotted = f"{parts[0]}.{parts[1]}"
                self.assertNotIn(dotted, flat_keys,
                                 msg=f"Plumbing var {raw!r} has a DEFAULTS entry {dotted!r}; "
                                     "it should remain env-only, not be promoted to TOML")


if __name__ == "__main__":
    unittest.main()
