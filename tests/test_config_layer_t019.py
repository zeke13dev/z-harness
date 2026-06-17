"""
T019 — Config-layer test suite.

Coverage:
  (a) TOML-wins: load_config returns the TOML value when a conflicting preference
      env var is ALSO set (TOML wins over env).
  (b) Completeness: every key in VALIDATORS is also in DEFAULTS (no orphan
      validators).  Some DEFAULTS keys intentionally lack VALIDATORS entries
      (free-form strings and list types), so the bidirectional check is
      one-way: VALIDATORS ⊆ DEFAULTS.
  (c) `config.py get <pref>` returns the TOML value even when the matching
      preference env var is set in the process environment (subprocess-level
      cross-process check — load-bearing because bash tool calls are fresh
      processes).
  (d) A legacy (schema_version=1) config loads without crashing and emits the
      warn-on-legacy warning on stderr (T018 behavior).

Env isolation: strips all Z_HARNESS_* and HERMES_* from os.environ before
applying test-specific env overrides, matching the pattern established in
test_config_t001_ingress_gate.py.

Run directly:
  python3 -m unittest tests.test_config_layer_t019
"""

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = str(_REPO_ROOT / "scripts" / "config.py")

# ─── Shared isolation helper ──────────────────────────────────────────────────


def _clean_env(extra: dict | None = None) -> dict:
    """
    Return a copy of os.environ stripped of all Z_HARNESS_* and HERMES_*
    variables.  Optionally merge ``extra`` on top.

    This prevents real-machine preference env vars from leaking into tests and
    causing false failures.
    """
    env = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith("Z_HARNESS_") and not k.startswith("HERMES_")
    }
    if extra:
        env.update(extra)
    return env


def _run(
    args: list[str],
    extra_env: dict | None = None,
    global_toml: str | None = None,
    repo_toml: str | None = None,
) -> subprocess.CompletedProcess:
    """
    Run config.py with a fully isolated XDG_CONFIG_HOME.

    - All Z_HARNESS_* / HERMES_* vars are stripped before extra_env is applied.
    - global_toml: written as the global config file.
    - repo_toml: written as the repo config file (overrides auto-discovery).
    - If repo_toml is None, an empty file is written so git-root discovery
      doesn't pick up the repo's own .z-harness/config.toml.
    """
    with tempfile.TemporaryDirectory() as td:
        td_path = Path(td)
        env = _clean_env()
        env["XDG_CONFIG_HOME"] = str(td_path)

        if global_toml is not None:
            global_cfg = td_path / "z-harness" / "config.toml"
            global_cfg.parent.mkdir(parents=True, exist_ok=True)
            global_cfg.write_text(global_toml)

        if repo_toml is not None:
            repo_cfg = td_path / "repo-config.toml"
            repo_cfg.write_text(repo_toml)
        else:
            repo_cfg = td_path / "empty-repo.toml"
            repo_cfg.write_text("")
        env["Z_HARNESS_REPO_CONFIG"] = str(repo_cfg)

        if extra_env:
            env.update(extra_env)

        return subprocess.run(
            [sys.executable, SCRIPT] + args,
            env=env,
            capture_output=True,
            text=True,
        )


# ─── (a) TOML-wins tests ─────────────────────────────────────────────────────


class TestTomlWins(unittest.TestCase):
    """
    Acceptance criterion (a): load_config returns the TOML value when a
    conflicting preference env var is also set.

    Failure class: preference-class env shadows TOML value (TOML-wins gate
    missing or bypassed).
    """

    def test_toml_wins_over_env_notify_level_global(self):
        """
        notify.level = "approval_only" in repo TOML + Z_HARNESS_NOTIFY_LEVEL=all
        in env → resolved value is "approval_only" (TOML), not "all" (env).

        This is the primary acceptance-criterion test from T019.
        """
        repo_cfg = 'schema_version = 2\n\n[notify]\nlevel = "approval_only"\n'
        r = _run(
            ["get", "notify.level"],
            extra_env={"Z_HARNESS_NOTIFY_LEVEL": "all"},
            repo_toml=repo_cfg,
        )
        self.assertEqual(r.returncode, 0, msg=r.stderr)
        self.assertEqual(
            r.stdout.strip(),
            "approval_only",
            msg=(
                "TOML-wins gate: Z_HARNESS_NOTIFY_LEVEL=all must NOT override "
                f"notify.level='approval_only' from TOML; got {r.stdout.strip()!r}"
            ),
        )

    def test_toml_wins_over_env_notify_level_off(self):
        """
        notify.level = "off" in global TOML + Z_HARNESS_NOTIFY_LEVEL=all in env
        → resolved value is "off" (TOML wins).
        """
        global_cfg = 'schema_version = 2\n\n[notify]\nlevel = "off"\n'
        r = _run(
            ["get", "notify.level"],
            extra_env={"Z_HARNESS_NOTIFY_LEVEL": "all"},
            global_toml=global_cfg,
        )
        self.assertEqual(r.returncode, 0, msg=r.stderr)
        self.assertEqual(
            r.stdout.strip(),
            "off",
            msg=(
                "TOML-wins gate: Z_HARNESS_NOTIFY_LEVEL=all must NOT override "
                f"notify.level='off' from global TOML; got {r.stdout.strip()!r}"
            ),
        )

    def test_toml_wins_over_legacy_env_notify_alias(self):
        """
        notify.level = "approval_only" in TOML + Z_HARNESS_NOTIFY=all (legacy
        ingress alias) in env → resolved value is "approval_only" (TOML wins).
        """
        repo_cfg = 'schema_version = 2\n\n[notify]\nlevel = "approval_only"\n'
        r = _run(
            ["get", "notify.level"],
            extra_env={"Z_HARNESS_NOTIFY": "all"},
            repo_toml=repo_cfg,
        )
        self.assertEqual(r.returncode, 0, msg=r.stderr)
        self.assertEqual(
            r.stdout.strip(),
            "approval_only",
            msg=(
                "TOML-wins gate: legacy Z_HARNESS_NOTIFY=all must NOT override "
                f"notify.level='approval_only' from TOML; got {r.stdout.strip()!r}"
            ),
        )

    def test_toml_wins_over_env_runtime_pre_review(self):
        """
        runtime.pre_review = false in TOML + Z_HARNESS_PRE_REVIEW=true in env
        → resolved value is "false" (TOML wins).
        """
        repo_cfg = 'schema_version = 2\n\n[runtime]\npre_review = false\n'
        r = _run(
            ["get", "runtime.pre_review"],
            extra_env={"Z_HARNESS_PRE_REVIEW": "true"},
            repo_toml=repo_cfg,
        )
        self.assertEqual(r.returncode, 0, msg=r.stderr)
        self.assertEqual(
            r.stdout.strip(),
            "false",
            msg=(
                "TOML-wins gate: Z_HARNESS_PRE_REVIEW=true must NOT override "
                f"runtime.pre_review=false from TOML; got {r.stdout.strip()!r}"
            ),
        )

    def test_toml_wins_over_hermes_max_parallel(self):
        """
        runtime.max_parallel = 1 in TOML + HERMES_MAX_PARALLEL=8 in env
        → resolved value is "1" (TOML wins).
        """
        repo_cfg = 'schema_version = 2\n\n[runtime]\nmax_parallel = 1\n'
        r = _run(
            ["get", "runtime.max_parallel"],
            extra_env={"HERMES_MAX_PARALLEL": "8"},
            repo_toml=repo_cfg,
        )
        self.assertEqual(r.returncode, 0, msg=r.stderr)
        self.assertEqual(
            r.stdout.strip(),
            "1",
            msg=(
                "TOML-wins gate: HERMES_MAX_PARALLEL=8 must NOT override "
                f"runtime.max_parallel=1 from TOML; got {r.stdout.strip()!r}"
            ),
        )

    def test_toml_wins_repo_over_global_and_env(self):
        """
        Repo TOML wins over both global TOML and env.
        """
        global_cfg = 'schema_version = 2\n\n[notify]\nlevel = "all"\n'
        repo_cfg = 'schema_version = 2\n\n[notify]\nlevel = "off"\n'
        r = _run(
            ["get", "notify.level"],
            extra_env={"Z_HARNESS_NOTIFY_LEVEL": "approval_only"},
            global_toml=global_cfg,
            repo_toml=repo_cfg,
        )
        self.assertEqual(r.returncode, 0, msg=r.stderr)
        self.assertEqual(
            r.stdout.strip(),
            "off",
            msg="Repo TOML ('off') must win over global TOML ('all') and env ('approval_only')",
        )

    def test_env_applies_when_toml_silent(self):
        """
        When no TOML sets a preference key, env vars still apply.
        This preserves the T003a/T003b migration backward-compat behaviour.
        """
        r = _run(
            ["get", "notify.level"],
            extra_env={"Z_HARNESS_NOTIFY_LEVEL": "all"},
        )
        self.assertEqual(r.returncode, 0, msg=r.stderr)
        self.assertEqual(
            r.stdout.strip(),
            "all",
            msg="Z_HARNESS_NOTIFY_LEVEL=all should set notify.level when TOML is silent",
        )


# ─── (b) Completeness tests ───────────────────────────────────────────────────


class TestCompleteness(unittest.TestCase):
    """
    Acceptance criterion (b): every key in VALIDATORS is also in DEFAULTS
    (no orphan validators that reference a non-existent default).

    The inverse (every DEFAULTS key in VALIDATORS) is intentionally NOT
    asserted because some DEFAULTS keys are free-form strings or lists that
    have no meaningful closed-set validator (e.g. followup.notion_database_id,
    notify.discord_webhook_url, followup.*_allowlist).

    Failure class: a VALIDATORS entry references a key that was removed from
    DEFAULTS, leaving a validator that can never fire.
    """

    @classmethod
    def _import_structures(cls) -> tuple[dict, dict, set]:
        """Import DEFAULTS, VALIDATORS, META_KEYS from config.py via subprocess."""
        code = (
            "import sys, json; sys.path.insert(0, 'scripts');"
            "from config import DEFAULTS, VALIDATORS, META_KEYS;"
            # Flatten DEFAULTS into dotted keys (exclude meta)
            "flat = {};"
            "[(flat.update({f'{sec}.{k}': v for k, v in val.items()}))"
            "    if isinstance(val, dict) else None"
            "    for sec, val in DEFAULTS.items() if sec not in META_KEYS];"
            "print(json.dumps({'flat_defaults': list(flat.keys()), "
            "'validators': list(VALIDATORS.keys()), "
            "'meta_keys': list(META_KEYS)}))"
        )
        result = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
            cwd=str(_REPO_ROOT),
        )
        if result.returncode != 0:
            raise AssertionError(
                f"Failed to import config structures: {result.stderr}"
            )
        import json
        data = json.loads(result.stdout)
        return (
            set(data["flat_defaults"]),
            set(data["validators"]),
            set(data["meta_keys"]),
        )

    def test_every_validators_key_is_in_defaults(self):
        """
        VALIDATORS must not contain orphan keys absent from DEFAULTS.

        An orphan validator can never fire because load_config only resolves
        keys that have a DEFAULTS entry.
        """
        flat_defaults, validators, _ = self._import_structures()
        orphan_validators = validators - flat_defaults
        self.assertEqual(
            orphan_validators,
            set(),
            msg=(
                f"VALIDATORS contains keys not in DEFAULTS (orphan validators): "
                f"{sorted(orphan_validators)}"
            ),
        )

    def test_core_migrated_keys_have_validators(self):
        """
        The keys migrated in T003a/T003b must have VALIDATORS entries.

        These are the primary risk surface: if a migrated key silently loses
        its validator, bad values can be written to config.toml without error.
        """
        flat_defaults, validators, _ = self._import_structures()
        # Keys migrated in T003a (workflow/runtime/notify group)
        t003a_keys = {
            "notify.level",
            "workflow.audit_to_amend",
            "workflow.slug_confirm",
            "workflow.implement_all_proceed",
            "workflow.review_all_proceed",
            "workflow.plan_decisions_approval",
            "workflow.spec_retro_discovery",
            "workflow.pre_run_cost_gate",
            "runtime.consult",
            "runtime.pre_review",
            "runtime.impl_pre_review",
            "runtime.auto_wait",
            "runtime.auto_wait_budget_secs",
            "runtime.pause_at_pct",
            "runtime.explain_resolution",
        }
        # Keys migrated in T003b (parallelism/review/docs/limits group)
        t003b_keys = {
            "docs.staleness_threshold",
            "workflow.max_explore",
            "workflow.parallel",
            "workflow.memory_stale_days",
            "runtime.max_parallel",
            "runtime.max_parallel_plans",
            "runtime.max_attempts",
            "runtime.max_task_wall_ms",
        }
        migrated = t003a_keys | t003b_keys

        missing_from_defaults = migrated - flat_defaults
        self.assertEqual(
            missing_from_defaults,
            set(),
            msg=(
                f"Migrated preference keys absent from DEFAULTS: "
                f"{sorted(missing_from_defaults)}"
            ),
        )

        missing_from_validators = migrated - validators
        self.assertEqual(
            missing_from_validators,
            set(),
            msg=(
                f"Migrated preference keys absent from VALIDATORS: "
                f"{sorted(missing_from_validators)}"
            ),
        )


# ─── (c) Subprocess-level TOML-wins test ─────────────────────────────────────


class TestSubprocessTomlWins(unittest.TestCase):
    """
    Acceptance criterion (c): `config.py get <pref>` returns the TOML value
    with the matching preference env var set in the process environment.

    This is the cross-process load-bearing check — it exercises the full
    subprocess execution path, not just the Python import path. This matters
    because each bash tool call is a fresh process that re-inherits the parent
    env; the TOML-wins gate must hold in this subprocess-per-call model.

    Failure class: TOML-wins gate bypassed at the `config.py get` CLI layer.
    """

    def test_get_returns_toml_value_not_env_value_notify_level(self):
        """
        config.py get notify.level returns "approval_only" (TOML) even when
        Z_HARNESS_NOTIFY_LEVEL=all is set in the calling process environment.
        """
        repo_cfg = 'schema_version = 2\n\n[notify]\nlevel = "approval_only"\n'
        r = _run(
            ["get", "notify.level"],
            extra_env={"Z_HARNESS_NOTIFY_LEVEL": "all"},
            repo_toml=repo_cfg,
        )
        self.assertEqual(r.returncode, 0, msg=r.stderr)
        self.assertEqual(
            r.stdout.strip(),
            "approval_only",
            msg=(
                "config.py get must return TOML value ('approval_only'), not "
                f"env value ('all'); got {r.stdout.strip()!r}"
            ),
        )

    def test_get_returns_toml_value_not_env_value_workflow_planning_mode(self):
        """
        config.py get workflow.planning_mode returns "full" (TOML) even when
        Z_HARNESS_WORKFLOW_PLANNING_MODE=intent is set in env.
        """
        repo_cfg = 'schema_version = 2\n\n[workflow]\nplanning_mode = "full"\n'
        r = _run(
            ["get", "workflow.planning_mode"],
            extra_env={"Z_HARNESS_WORKFLOW_PLANNING_MODE": "intent"},
            repo_toml=repo_cfg,
        )
        self.assertEqual(r.returncode, 0, msg=r.stderr)
        self.assertEqual(
            r.stdout.strip(),
            "full",
            msg=(
                "config.py get must return TOML value ('full'), not env value "
                f"('intent'); got {r.stdout.strip()!r}"
            ),
        )

    def test_get_returns_toml_value_not_env_value_runtime_max_attempts(self):
        """
        config.py get runtime.max_attempts returns "3" (TOML) even when
        Z_HARNESS_MAX_ATTEMPTS=10 (legacy alias) is set in env.
        """
        repo_cfg = 'schema_version = 2\n\n[runtime]\nmax_attempts = 3\n'
        r = _run(
            ["get", "runtime.max_attempts"],
            extra_env={"Z_HARNESS_MAX_ATTEMPTS": "10"},
            repo_toml=repo_cfg,
        )
        self.assertEqual(r.returncode, 0, msg=r.stderr)
        self.assertEqual(
            r.stdout.strip(),
            "3",
            msg=(
                "config.py get must return TOML value ('3'), not legacy env "
                f"value ('10'); got {r.stdout.strip()!r}"
            ),
        )

    def test_get_returns_env_value_when_toml_absent(self):
        """
        config.py get notify.level returns env value when TOML is absent.
        This preserves backward-compat (env still works for unconfigured keys).
        """
        r = _run(
            ["get", "notify.level"],
            extra_env={"Z_HARNESS_NOTIFY_LEVEL": "all"},
        )
        self.assertEqual(r.returncode, 0, msg=r.stderr)
        self.assertEqual(
            r.stdout.strip(),
            "all",
            msg=(
                "config.py get must return env value ('all') when TOML is "
                f"absent for the key; got {r.stdout.strip()!r}"
            ),
        )


# ─── (d) Legacy schema_version=1 backward-compat ─────────────────────────────


class TestLegacySchemaVersion1(unittest.TestCase):
    """
    Acceptance criterion (d): a legacy schema_version=1 config loads without
    crashing and emits the warn-on-legacy warning (T018 behavior).

    Failure class: legacy config causes a hard exit (breaks in-flight CI that
    hasn't yet run `config.py ensure-defaults` to upgrade to schema_version=2).
    """

    _V1_GLOBAL = 'schema_version = 1\n\n[notify]\nlevel = "off"\n'
    _V1_REPO = 'schema_version = 1\n\n[notify]\nlevel = "approval_only"\n'

    def test_v1_global_loads_without_crash(self):
        """A global config with schema_version=1 must exit 0 (non-fatal)."""
        r = _run(["get", "notify.level"], global_toml=self._V1_GLOBAL)
        self.assertEqual(
            r.returncode,
            0,
            msg=(
                f"schema_version=1 global config must not crash (exit 0); "
                f"got exit {r.returncode}; stderr: {r.stderr}"
            ),
        )

    def test_v1_global_emits_warning_on_stderr(self):
        """A global config with schema_version=1 must emit a deprecation warning."""
        r = _run(["get", "notify.level"], global_toml=self._V1_GLOBAL)
        self.assertIn(
            "schema_version",
            r.stderr,
            msg="Expected 'schema_version' deprecation warning in stderr",
        )
        # The warning should not be a hard error message
        self.assertIn(
            "WARNING",
            r.stderr,
            msg="Expected 'WARNING' prefix in the legacy-schema deprecation message",
        )

    def test_v1_global_value_is_readable(self):
        """Values from a schema_version=1 global config resolve correctly."""
        r = _run(["get", "notify.level"], global_toml=self._V1_GLOBAL)
        self.assertEqual(r.returncode, 0, msg=r.stderr)
        self.assertEqual(
            r.stdout.strip(),
            "off",
            msg=f"Expected 'off' from v1 global config; got {r.stdout.strip()!r}",
        )

    def test_v1_repo_loads_without_crash(self):
        """A repo config with schema_version=1 must exit 0 (non-fatal)."""
        r = _run(["get", "notify.level"], repo_toml=self._V1_REPO)
        self.assertEqual(
            r.returncode,
            0,
            msg=(
                f"schema_version=1 repo config must not crash (exit 0); "
                f"got exit {r.returncode}; stderr: {r.stderr}"
            ),
        )

    def test_v1_repo_emits_warning_on_stderr(self):
        """A repo config with schema_version=1 must emit a deprecation warning."""
        r = _run(["get", "notify.level"], repo_toml=self._V1_REPO)
        self.assertIn(
            "schema_version",
            r.stderr,
            msg="Expected 'schema_version' deprecation warning for repo v1 config",
        )

    def test_v1_repo_value_is_readable(self):
        """Values from a schema_version=1 repo config resolve correctly."""
        r = _run(["get", "notify.level"], repo_toml=self._V1_REPO)
        self.assertEqual(r.returncode, 0, msg=r.stderr)
        self.assertEqual(
            r.stdout.strip(),
            "approval_only",
            msg=f"Expected 'approval_only' from v1 repo config; got {r.stdout.strip()!r}",
        )

    def test_v1_does_not_block_toml_wins_gate(self):
        """
        Even with schema_version=1, the TOML-wins gate holds: env var must NOT
        override a value set in the v1 TOML config.
        """
        r = _run(
            ["get", "notify.level"],
            extra_env={"Z_HARNESS_NOTIFY_LEVEL": "all"},
            repo_toml=self._V1_REPO,
        )
        self.assertEqual(r.returncode, 0, msg=r.stderr)
        self.assertEqual(
            r.stdout.strip(),
            "approval_only",
            msg=(
                "TOML-wins gate must hold for schema_version=1 configs: "
                "Z_HARNESS_NOTIFY_LEVEL=all must NOT override notify.level='approval_only'"
            ),
        )


if __name__ == "__main__":
    unittest.main()
