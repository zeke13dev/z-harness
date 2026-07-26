"""
Tests for T008 — [export] config section (hosts + strategy enum).

Verifies:
  (a) export.hosts and export.strategy are present in DEFAULTS + VALIDATORS.
  (b) Each valid host name is accepted; unknown host names are rejected (exit 2
      for repo/env layer; warn+fallback for global layer).
  (c) Each strategy enum value (pointer, curated, full) is accepted; unknown
      values are rejected (exit 2 for repo/env; warn+fallback for global).
      The sentinel "" is also accepted (means "defer to per-driver default").
  (d) Absent [export] section yields the configured defaults
      (hosts=["cursor","codex","agy","pi"], strategy="" sentinel).
  (e) config.py get export.hosts / export.strategy returns the set values.

  (f) 3-level model routing keys remain config-file-only and are not emitted
      by export-env while export.* lines are still present.

Invariants under test:
  - Failure class: unknown host name accepted at load time (audit m1 violation).
  - Failure class: unknown strategy enum accepted at load time.
  - Failure class: absent [export] section does not yield default host set.
  - Failure class: absent [export].strategy yields a concrete strategy instead of
    the "" sentinel, preventing per-driver defaults from taking effect.
  - Failure class: 3-level model routing keys leak into shell env export output.
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

# The closed set of valid host names as specified by T008:
# adapter names ∪ export-only driver names
_VALID_HOSTS = {
    "claude", "antigravity", "cursor", "codex", "omp",  # adapter names
    "pi", "sterling", "windsurf", "cline", "kiro", "copilot", # export-only driver names
    "agy",                                               # alias for antigravity
}

_VALID_STRATEGIES = {"pointer", "curated", "full"}
# "" is the sentinel meaning "defer to per-driver default" — also accepted by the validator.
_SENTINEL_STRATEGY = ""

# Default hosts set (the current "all" set from z-export.md line 48)
_DEFAULT_HOSTS = ["cursor", "codex", "agy", "omp", "pi"]
# The default strategy is the empty sentinel — each driver uses its own default.
_DEFAULT_STRATEGY = ""


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
    # Scrub all Z_HARNESS_* preference env vars to get clean isolation
    for key in list(env.keys()):
        if key.startswith("Z_HARNESS_"):
            del env[key]

    with tempfile.TemporaryDirectory() as td:
        td_path = Path(td)
        env["XDG_CONFIG_HOME"] = str(td_path)

        if global_toml is not None:
            global_cfg = td_path / "z-harness" / "config.toml"
            global_cfg.parent.mkdir(parents=True, exist_ok=True)
            global_cfg.write_text(global_toml)

        if repo_toml is not None:
            repo_cfg = td_path / "repo-config.toml"
            repo_cfg.write_text(repo_toml)
            env["Z_HARNESS_REPO_CONFIG"] = str(repo_cfg)
        else:
            # Point to an empty file so git-rev-parse fallback doesn't pick up
            # the dev repo's .z-harness/config.toml
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
# (a) DEFAULTS and VALIDATORS contain export.hosts and export.strategy
# ---------------------------------------------------------------------------

class TestExportSectionInDefaults(unittest.TestCase):
    """export.hosts and export.strategy must be in DEFAULTS and VALIDATORS."""

    def _import_defaults_export(self) -> dict:
        result = subprocess.run(
            [sys.executable, "-c",
             "import sys; sys.path.insert(0, 'scripts');"
             "from config import DEFAULTS; import json; print(json.dumps(DEFAULTS.get('export', {})))"],
            capture_output=True,
            text=True,
            cwd=str(_REPO_ROOT),
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        return json.loads(result.stdout)

    def _import_validators_keys(self) -> list:
        result = subprocess.run(
            [sys.executable, "-c",
             "import sys; sys.path.insert(0, 'scripts');"
             "from config import VALIDATORS; import json; print(json.dumps(list(VALIDATORS.keys())))"],
            capture_output=True,
            text=True,
            cwd=str(_REPO_ROOT),
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        return json.loads(result.stdout)

    def test_defaults_has_export_section(self):
        """DEFAULTS must have an 'export' section."""
        d = self._import_defaults_export()
        self.assertIsInstance(d, dict, "DEFAULTS['export'] must be a dict")
        self.assertNotEqual(d, {}, "DEFAULTS['export'] must not be empty")

    def test_defaults_export_has_hosts_key(self):
        """DEFAULTS['export'] must have a 'hosts' key."""
        d = self._import_defaults_export()
        self.assertIn("hosts", d, "DEFAULTS['export'] missing 'hosts' key")

    def test_defaults_export_has_strategy_key(self):
        """DEFAULTS['export'] must have a 'strategy' key."""
        d = self._import_defaults_export()
        self.assertIn("strategy", d, "DEFAULTS['export'] missing 'strategy' key")

    def test_defaults_export_has_exactly_two_keys(self):
        """DEFAULTS['export'] must have EXACTLY two keys: hosts + strategy (no filtering keys)."""
        d = self._import_defaults_export()
        self.assertEqual(sorted(d.keys()), ["hosts", "strategy"],
                         f"DEFAULTS['export'] must have exactly [hosts, strategy], got: {sorted(d.keys())!r}")

    def test_defaults_export_hosts_is_list(self):
        """DEFAULTS['export']['hosts'] must be a list."""
        d = self._import_defaults_export()
        self.assertIsInstance(d["hosts"], list, "DEFAULTS['export']['hosts'] must be a list")

    def test_defaults_export_hosts_contains_cursor_codex_agy_pi(self):
        """Default hosts must include cursor, codex, agy, pi (current 'all' set from z-export.md)."""
        d = self._import_defaults_export()
        hosts = d["hosts"]
        for expected in _DEFAULT_HOSTS:
            self.assertIn(expected, hosts,
                          f"Default hosts missing {expected!r}; got {hosts!r}")

    def test_defaults_export_strategy_is_string(self):
        """DEFAULTS['export']['strategy'] must be a string."""
        d = self._import_defaults_export()
        self.assertIsInstance(d["strategy"], str, "DEFAULTS['export']['strategy'] must be a string")

    def test_defaults_export_strategy_is_sentinel_or_valid_enum(self):
        """DEFAULTS['export']['strategy'] must be '' (sentinel) or a valid enum value.

        The sentinel '' means "defer to per-driver default"; it is the correct
        default so each driver's own default_strategy takes effect when the user
        has no [export] section in their config.toml.

        Failure class: default is a concrete strategy like "curated", which would
        override per-driver defaults (e.g. cline's "pointer") and cause all drivers
        to emit the same number of files.
        """
        d = self._import_defaults_export()
        valid_values = _VALID_STRATEGIES | {_SENTINEL_STRATEGY}
        self.assertIn(d["strategy"], valid_values,
                      f"Default strategy {d['strategy']!r} not in {valid_values!r}")

    def test_defaults_export_strategy_is_sentinel(self):
        """DEFAULTS['export']['strategy'] must be '' (the per-driver-default sentinel).

        Failure class: absent [export].strategy yields 'curated' (or any concrete
        strategy), which silently overrides per-driver defaults like cline's 'pointer'.
        """
        d = self._import_defaults_export()
        self.assertEqual(d["strategy"], _SENTINEL_STRATEGY,
                         f"Default strategy must be the sentinel '' (defer to per-driver "
                         f"default), got {d['strategy']!r}. T012-FIX: the old 'curated' "
                         "default caused cline to emit 98 files instead of 1.")

    def test_validators_has_export_hosts(self):
        """VALIDATORS must have an 'export.hosts' entry."""
        keys = self._import_validators_keys()
        self.assertIn("export.hosts", keys,
                      "VALIDATORS missing 'export.hosts' entry")

    def test_validators_has_export_strategy(self):
        """VALIDATORS must have an 'export.strategy' entry."""
        keys = self._import_validators_keys()
        self.assertIn("export.strategy", keys,
                      "VALIDATORS missing 'export.strategy' entry")


# ---------------------------------------------------------------------------
# (b) Host name validation — each valid host accepted, unknown rejected
# ---------------------------------------------------------------------------

class TestExportHostsValidation(unittest.TestCase):
    """Valid host names accepted; unknown host names rejected at load time."""

    def test_each_valid_host_accepted_in_repo_toml(self):
        """Every name in _VALID_HOSTS is accepted when set in repo TOML."""
        for host in sorted(_VALID_HOSTS):
            with self.subTest(host=host):
                toml = f'schema_version = 2\n\n[export]\nhosts = ["{host}"]\n'
                r = _run(["get", "export.hosts"], repo_toml=toml)
                self.assertEqual(r.returncode, 0,
                                 f"Valid host {host!r} rejected; stderr={r.stderr!r}")
                parsed = json.loads(r.stdout.strip())
                self.assertEqual(parsed, [host],
                                 f"get export.hosts returned {parsed!r}, expected [{host!r}]")

    def test_unknown_host_in_repo_toml_exits_2(self):
        """An unknown host name in repo TOML causes exit 2 (hard fail).

        Invariant: unknown host names must be rejected at load time (audit m1).
        Failure class: unknown host accepted silently.
        """
        toml = 'schema_version = 2\n\n[export]\nhosts = ["not_a_real_host"]\n'
        r = _run(["get", "export.hosts"], repo_toml=toml)
        self.assertEqual(r.returncode, 2,
                         f"Unknown host should have caused exit 2; got {r.returncode}; "
                         f"stdout={r.stdout!r} stderr={r.stderr!r}")

    def test_unknown_host_in_global_toml_warns_and_falls_back(self):
        """An unknown host name in global TOML warns and falls back to default (soft fail)."""
        toml = 'schema_version = 2\n\n[export]\nhosts = ["not_a_real_host"]\n'
        r = _run(["get", "export.hosts"], global_toml=toml)
        self.assertEqual(r.returncode, 0,
                         f"Global TOML invalid host should warn, not exit 2; stderr={r.stderr!r}")
        self.assertIn("WARNING", r.stderr,
                      "Global TOML invalid host must emit a WARNING to stderr")
        # Falls back to default
        parsed = json.loads(r.stdout.strip())
        self.assertEqual(sorted(parsed), sorted(_DEFAULT_HOSTS),
                         f"Expected fallback to default hosts, got {parsed!r}")

    def test_multiple_valid_hosts_accepted(self):
        """A list of multiple valid host names is accepted."""
        hosts = ["cursor", "codex", "pi"]
        toml = 'schema_version = 2\n\n[export]\nhosts = ["cursor", "codex", "pi"]\n'
        r = _run(["get", "export.hosts"], repo_toml=toml)
        self.assertEqual(r.returncode, 0,
                         f"Multiple valid hosts rejected; stderr={r.stderr!r}")
        parsed = json.loads(r.stdout.strip())
        self.assertEqual(sorted(parsed), sorted(hosts))

    def test_list_with_one_unknown_host_exits_2(self):
        """A list containing any unknown host name causes exit 2 (hard fail)."""
        toml = 'schema_version = 2\n\n[export]\nhosts = ["cursor", "unknown_host"]\n'
        r = _run(["get", "export.hosts"], repo_toml=toml)
        self.assertEqual(r.returncode, 2,
                         f"List with unknown host should exit 2; got {r.returncode}")

    def test_empty_hosts_list_exits_2(self):
        """An empty hosts list is rejected (must be non-empty)."""
        toml = 'schema_version = 2\n\n[export]\nhosts = []\n'
        r = _run(["get", "export.hosts"], repo_toml=toml)
        self.assertEqual(r.returncode, 2,
                         f"Empty hosts list should exit 2; got {r.returncode}")

    def test_env_var_valid_json_hosts_accepted(self):
        """Z_HARNESS_EXPORT_HOSTS as a valid JSON list of hosts is accepted."""
        env_val = json.dumps(["cursor", "pi"])
        r = _run(["get", "export.hosts"],
                 extra_env={"Z_HARNESS_EXPORT_HOSTS": env_val})
        self.assertEqual(r.returncode, 0,
                         f"Valid JSON hosts env rejected; stderr={r.stderr!r}")
        parsed = json.loads(r.stdout.strip())
        self.assertEqual(sorted(parsed), sorted(["cursor", "pi"]))

    def test_env_var_unknown_host_exits_2(self):
        """Z_HARNESS_EXPORT_HOSTS with an unknown host name causes exit 2.

        Invariant: unknown host names must be rejected at load time even via env (audit m1).
        Failure class: unknown host accepted via env without validation.
        """
        env_val = json.dumps(["cursor", "not_a_real_host"])
        r = _run(["get", "export.hosts"],
                 extra_env={"Z_HARNESS_EXPORT_HOSTS": env_val})
        self.assertEqual(r.returncode, 2,
                         f"Unknown host via env should exit 2; got {r.returncode}")


# ---------------------------------------------------------------------------
# (c) Strategy enum validation
# ---------------------------------------------------------------------------

class TestExportStrategyValidation(unittest.TestCase):
    """Strategy enum validation: pointer, curated, full accepted; others rejected."""

    def test_each_valid_strategy_accepted_in_repo_toml(self):
        """Every valid strategy (pointer, curated, full) is accepted in repo TOML."""
        for strategy in sorted(_VALID_STRATEGIES):
            with self.subTest(strategy=strategy):
                toml = f'schema_version = 2\n\n[export]\nstrategy = "{strategy}"\n'
                r = _run(["get", "export.strategy"], repo_toml=toml)
                self.assertEqual(r.returncode, 0,
                                 f"Valid strategy {strategy!r} rejected; stderr={r.stderr!r}")
                self.assertEqual(r.stdout.strip(), strategy,
                                 f"get export.strategy returned {r.stdout.strip()!r}, expected {strategy!r}")

    def test_unknown_strategy_in_repo_toml_exits_2(self):
        """An unknown strategy value in repo TOML causes exit 2 (hard fail).

        Failure class: unknown strategy enum accepted silently.
        """
        toml = 'schema_version = 2\n\n[export]\nstrategy = "selective"\n'
        r = _run(["get", "export.strategy"], repo_toml=toml)
        self.assertEqual(r.returncode, 2,
                         f"Unknown strategy should exit 2; got {r.returncode}")

    def test_unknown_strategy_in_global_toml_warns_and_falls_back(self):
        """An unknown strategy in global TOML warns and falls back to default (soft fail)."""
        toml = 'schema_version = 2\n\n[export]\nstrategy = "selective"\n'
        r = _run(["get", "export.strategy"], global_toml=toml)
        self.assertEqual(r.returncode, 0,
                         f"Global TOML invalid strategy should warn, not exit 2; stderr={r.stderr!r}")
        self.assertIn("WARNING", r.stderr,
                      "Global TOML invalid strategy must emit a WARNING to stderr")
        self.assertEqual(r.stdout.strip(), _DEFAULT_STRATEGY,
                         f"Expected fallback to default strategy {_DEFAULT_STRATEGY!r}")

    def test_env_var_valid_strategy_accepted(self):
        """Z_HARNESS_EXPORT_STRATEGY with a valid strategy is accepted."""
        for strategy in sorted(_VALID_STRATEGIES):
            with self.subTest(strategy=strategy):
                r = _run(["get", "export.strategy"],
                         extra_env={"Z_HARNESS_EXPORT_STRATEGY": strategy})
                self.assertEqual(r.returncode, 0,
                                 f"Valid strategy env {strategy!r} rejected; stderr={r.stderr!r}")
                self.assertEqual(r.stdout.strip(), strategy)

    def test_env_var_unknown_strategy_exits_2(self):
        """Z_HARNESS_EXPORT_STRATEGY with an unknown value causes exit 2."""
        r = _run(["get", "export.strategy"],
                 extra_env={"Z_HARNESS_EXPORT_STRATEGY": "not_a_strategy"})
        self.assertEqual(r.returncode, 2,
                         f"Unknown strategy via env should exit 2; got {r.returncode}")

    def test_sentinel_empty_string_accepted_in_repo_toml(self):
        """The sentinel '' is accepted in repo TOML and returned as-is.

        Users may explicitly write strategy = "" to force per-driver-default behaviour
        (useful for resetting an inherited global override).

        Failure class: sentinel '' is rejected as an invalid value by the validator.
        """
        toml = 'schema_version = 2\n\n[export]\nstrategy = ""\n'
        r = _run(["get", "export.strategy"], repo_toml=toml)
        self.assertEqual(r.returncode, 0,
                         f"Sentinel '' should be accepted; stderr={r.stderr!r}")
        self.assertEqual(r.stdout.strip(), "",
                         f"get export.strategy with sentinel '' should return ''; "
                         f"got {r.stdout.strip()!r}")

    def test_bogus_strategy_rejected_not_sentinel(self):
        """A non-empty unknown strategy like 'bogus' is still rejected (exit 2).

        Confirms the validator accepts '' and {pointer, curated, full} only.

        Failure class: 'bogus' accepted silently alongside the sentinel.
        """
        toml = 'schema_version = 2\n\n[export]\nstrategy = "bogus"\n'
        r = _run(["get", "export.strategy"], repo_toml=toml)
        self.assertEqual(r.returncode, 2,
                         f"Unknown strategy 'bogus' should exit 2; got {r.returncode}")


# ---------------------------------------------------------------------------
# (d) Absent [export] section yields defaults
# ---------------------------------------------------------------------------

class TestExportSectionAbsent(unittest.TestCase):
    """When [export] is absent from config, defaults are used."""

    def test_absent_section_yields_default_hosts(self):
        """Absent [export] section → hosts defaults to current 'all' set.

        Failure class: absent [export] section does not yield the default host set.
        """
        # No export section in the TOML at all
        toml = 'schema_version = 2\n\n[notify]\nlevel = "approval_only"\n'
        r = _run(["get", "export.hosts"], repo_toml=toml)
        self.assertEqual(r.returncode, 0,
                         f"get export.hosts failed for absent section; stderr={r.stderr!r}")
        parsed = json.loads(r.stdout.strip())
        self.assertEqual(sorted(parsed), sorted(_DEFAULT_HOSTS),
                         f"Expected default hosts {sorted(_DEFAULT_HOSTS)!r}, got {sorted(parsed)!r}")

    def test_absent_section_yields_default_strategy(self):
        """Absent [export] section → strategy defaults to '' (per-driver-default sentinel).

        The sentinel '' means each driver uses its own default_strategy (e.g. cline
        uses 'pointer', windsurf/kiro use 'curated').  A concrete default like
        'curated' would override cline's pointer default and cause 98-file bloat.

        Failure class: absent [export].strategy yields 'curated' instead of ''.
        """
        toml = 'schema_version = 2\n\n[notify]\nlevel = "approval_only"\n'
        r = _run(["get", "export.strategy"], repo_toml=toml)
        self.assertEqual(r.returncode, 0,
                         f"get export.strategy failed for absent section; stderr={r.stderr!r}")
        self.assertEqual(r.stdout.strip(), _DEFAULT_STRATEGY,
                         f"Expected default strategy {_DEFAULT_STRATEGY!r} (sentinel), "
                         f"got {r.stdout.strip()!r}")

    def test_no_config_at_all_yields_default_hosts(self):
        """No config files at all → export.hosts yields the default set."""
        r = _run(["get", "export.hosts"])
        self.assertEqual(r.returncode, 0,
                         f"get export.hosts failed with no config; stderr={r.stderr!r}")
        parsed = json.loads(r.stdout.strip())
        self.assertEqual(sorted(parsed), sorted(_DEFAULT_HOSTS))

    def test_no_config_at_all_yields_default_strategy(self):
        """No config files at all → export.strategy yields '' (per-driver-default sentinel)."""
        r = _run(["get", "export.strategy"])
        self.assertEqual(r.returncode, 0,
                         f"get export.strategy failed with no config; stderr={r.stderr!r}")
        self.assertEqual(r.stdout.strip(), _DEFAULT_STRATEGY)


# ---------------------------------------------------------------------------
# (e) config.py get export.hosts / export.strategy returns set values
# ---------------------------------------------------------------------------

class TestExportGetReturnsSetValues(unittest.TestCase):
    """config.py get export.hosts and export.strategy return the configured values."""

    def test_get_export_hosts_returns_json_array(self):
        """config.py get export.hosts returns a valid JSON array string."""
        r = _run(["get", "export.hosts"])
        self.assertEqual(r.returncode, 0, f"stderr={r.stderr!r}")
        output = r.stdout.strip()
        # Must be parseable JSON array
        parsed = json.loads(output)
        self.assertIsInstance(parsed, list,
                              f"get export.hosts must return a JSON array; got {output!r}")

    def test_get_export_hosts_from_toml_returns_correct_value(self):
        """config.py get export.hosts returns the value set in TOML."""
        toml = 'schema_version = 2\n\n[export]\nhosts = ["windsurf", "cline"]\n'
        r = _run(["get", "export.hosts"], repo_toml=toml)
        self.assertEqual(r.returncode, 0, f"stderr={r.stderr!r}")
        parsed = json.loads(r.stdout.strip())
        self.assertEqual(sorted(parsed), sorted(["windsurf", "cline"]))

    def test_get_export_strategy_from_toml_returns_correct_value(self):
        """config.py get export.strategy returns the value set in TOML."""
        toml = 'schema_version = 2\n\n[export]\nstrategy = "pointer"\n'
        r = _run(["get", "export.strategy"], repo_toml=toml)
        self.assertEqual(r.returncode, 0, f"stderr={r.stderr!r}")
        self.assertEqual(r.stdout.strip(), "pointer")

    def test_get_export_strategy_from_toml_full(self):
        """config.py get export.strategy returns 'full' when configured."""
        toml = 'schema_version = 2\n\n[export]\nstrategy = "full"\n'
        r = _run(["get", "export.strategy"], repo_toml=toml)
        self.assertEqual(r.returncode, 0, f"stderr={r.stderr!r}")
        self.assertEqual(r.stdout.strip(), "full")

    def test_export_section_constrained_to_two_keys(self):
        """[export] section only exposes hosts and strategy — no other keys settable.

        Verifies SPEC invariant: [export] is strategy + host-list ONLY (no filtering keys).
        Unknown keys in TOML are silently ignored (forward-compat), but they must
        not appear as resolvable config keys.
        """
        # Try to get a hypothetical filtering key — must exit 3 (unknown key)
        r = _run(["get", "export.filter_by_command"])
        self.assertEqual(r.returncode, 3,
                         f"export.filter_by_command should be unknown (exit 3); got {r.returncode}")

    def test_export_hosts_unknown_key_exits_3(self):
        """get export.hostname (typo) exits 3 (unknown key)."""
        r = _run(["get", "export.hostname"])
        self.assertEqual(r.returncode, 3,
                         f"export.hostname should be unknown (exit 3); got {r.returncode}")

    def test_repo_toml_export_hosts_wins_over_env(self):
        """TOML-wins gate: repo TOML export.hosts overrides Z_HARNESS_EXPORT_HOSTS env var."""
        toml = 'schema_version = 2\n\n[export]\nhosts = ["cursor"]\n'
        env_val = json.dumps(["codex", "pi"])
        r = _run(["get", "export.hosts"],
                 repo_toml=toml,
                 extra_env={"Z_HARNESS_EXPORT_HOSTS": env_val})
        self.assertEqual(r.returncode, 0, f"stderr={r.stderr!r}")
        parsed = json.loads(r.stdout.strip())
        self.assertEqual(parsed, ["cursor"],
                         f"TOML-wins gate: repo TOML ['cursor'] should win over env; got {parsed!r}")


# ---------------------------------------------------------------------------
# (f) 3-level model routing keys are config-file-only, not export-env output
# ---------------------------------------------------------------------------

class TestExportEnvSkipsModelRouting(unittest.TestCase):
    """export-env must skip 3-level model routing leaves while preserving export.*."""

    def test_export_env_skips_model_routing_three_level_keys(self):
        """Configured model routing leaves are readable but never emitted as env vars."""
        toml = (
            'schema_version = 2\n\n'
            '[model_classes.local_fast]\n'
            'model = "ollama/qwen3:8b"\n'
            '\n'
            '[model_routing.native_agents]\n'
            'explore = "local_fast"\n'
            '\n'
            '[export]\n'
            'strategy = "pointer"\n'
        )
        r = _run(["export-env"], repo_toml=toml)
        self.assertEqual(r.returncode, 0, f"stderr={r.stderr!r}")
        self.assertIn("Z_HARNESS_EXPORT_STRATEGY", r.stdout)
        self.assertNotIn("Z_HARNESS_MODEL_CLASSES_", r.stdout)
        self.assertNotIn("Z_HARNESS_MODEL_ROUTING_", r.stdout)


if __name__ == "__main__":
    unittest.main()
