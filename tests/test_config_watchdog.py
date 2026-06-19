"""
Tests for the watchdog config section added in the silent-failure-watchdog plan.

Verifies:
  (a) watchdog.* keys present in DEFAULTS + VALIDATORS.
  (b) Flat watchdog.* keys (enabled, sweep_interval_secs, etc.) round-trip
      via export-env / ingress (env → get works; bools via _validate_bool,
      ints via _validate_positive_int).
  (c) watchdog.timeout_secs.* keys are config-file-only: NOT exported by
      export-env; readable via `config.py get watchdog.timeout_secs.<type>`.
  (d) `config.py get watchdog.timeout_secs.<unknown>` exits 3 (unknown key),
      never exits 0 with an empty value.
  (e) `should-notify --event watchdog_stall` returns "yes" under the DEFAULT
      notify.level=approval_only, "yes" under "all", and "no" under "off".
  (f) `should-notify --event watchdog_timeout` same behavior as watchdog_stall.
  (g) A typo'd Z_HARNESS_WATCHDOG_TIMEOUT_SECS env var is silently ignored
      (timeout_secs keys are not env-imported).

Invariants under test:
  - Failure class: watchdog_stall/watchdog_timeout not in _NOTIFY_EVENTS → exit 2.
  - Failure class: approval_only fire-set missing watchdog kinds → "no" returned
    instead of "yes" (alert layer silently inert under default config).
  - Failure class: watchdog.timeout_secs.* exported as env var (None→'' poisoning risk).
  - Failure class: watchdog.timeout_secs.<unknown> returns exit 0 instead of exit 3.
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

    Scrubs all Z_HARNESS_* preference env vars from the process environment for
    isolation, then applies extra_env overrides.
    """
    env = {k: v for k, v in os.environ.items()}
    # Scrub all Z_HARNESS_* and HERMES_* preference env vars for clean isolation
    for key in list(env.keys()):
        if key.startswith("Z_HARNESS_") or key.startswith("HERMES_"):
            del env[key]

    with tempfile.TemporaryDirectory() as td:
        td_path = Path(td)
        env["XDG_CONFIG_HOME"] = str(td_path)

        if global_toml is not None:
            global_cfg = td_path / "z-harness" / "config.toml"
            global_cfg.parent.mkdir(parents=True, exist_ok=True)
            global_cfg.write_text(global_toml)

        # Always point Z_HARNESS_REPO_CONFIG at an empty file so the dev repo's
        # own .z-harness/config.toml is not loaded.
        if repo_toml is not None:
            repo_cfg = td_path / "repo-config.toml"
            repo_cfg.write_text(repo_toml)
            env["Z_HARNESS_REPO_CONFIG"] = str(repo_cfg)
        else:
            empty = td_path / "empty-repo.toml"
            empty.write_text("")
            env["Z_HARNESS_REPO_CONFIG"] = str(empty)

        if extra_env:
            env.update(extra_env)

        return subprocess.run(
            [sys.executable, SCRIPT] + args,
            env=env,
            capture_output=True,
            text=True,
        )


# ---------------------------------------------------------------------------
# (a) DEFAULTS + VALIDATORS coverage
# ---------------------------------------------------------------------------

class TestWatchdogDefaults(unittest.TestCase):
    """watchdog.* keys must be present in DEFAULTS and resolvable via cmd_get."""

    _FLAT_KEYS = {
        "watchdog.enabled": "true",
        "watchdog.sweep_interval_secs": "60",
        "watchdog.intervention_level": "notify",
        "watchdog.kill_grace_secs": "10",
        "watchdog.max_lifetime_secs": "86400",
        "watchdog.stale_secs": "300",
    }
    _TIMEOUT_KEYS = {
        "watchdog.timeout_secs.bash": "600",
        "watchdog.timeout_secs.ssh": "600",
        "watchdog.timeout_secs.rsync": "660",
        "watchdog.timeout_secs.cargo": "1800",
        "watchdog.timeout_secs.reviewer": "300",
    }

    def test_flat_keys_return_defaults(self):
        """Flat watchdog.* keys return expected defaults when no TOML/env override."""
        for key, expected in self._FLAT_KEYS.items():
            with self.subTest(key=key):
                r = _run(["get", key])
                self.assertEqual(r.returncode, 0, msg=f"get {key!r} failed: {r.stderr}")
                self.assertEqual(r.stdout.strip(), expected,
                                 msg=f"get {key!r}: expected {expected!r}, got {r.stdout.strip()!r}")

    def test_timeout_secs_keys_return_defaults(self):
        """watchdog.timeout_secs.* keys return expected defaults."""
        for key, expected in self._TIMEOUT_KEYS.items():
            with self.subTest(key=key):
                r = _run(["get", key])
                self.assertEqual(r.returncode, 0, msg=f"get {key!r} failed: {r.stderr}")
                self.assertEqual(r.stdout.strip(), expected,
                                 msg=f"get {key!r}: expected {expected!r}, got {r.stdout.strip()!r}")

    def test_watchdog_enabled_in_valid_keys(self):
        """watchdog.* keys appear in the valid-keys list on an unknown-key error."""
        r = _run(["get", "watchdog.nonexistent"])
        self.assertEqual(r.returncode, 3, msg="unknown watchdog key should exit 3")
        self.assertIn("watchdog.enabled", r.stderr,
                      msg="valid keys in error message should include watchdog.enabled")

    def test_timeout_secs_keys_in_valid_keys(self):
        """watchdog.timeout_secs.* appear in the valid-keys list."""
        r = _run(["get", "watchdog.timeout_secs.nonexistent"])
        self.assertEqual(r.returncode, 3, msg="unknown timeout_secs key should exit 3")
        self.assertIn("watchdog.timeout_secs.bash", r.stderr,
                      msg="valid keys should include watchdog.timeout_secs.bash")


# ---------------------------------------------------------------------------
# (b) Flat watchdog.* keys round-trip via env
# ---------------------------------------------------------------------------

class TestWatchdogEnvRoundTrip(unittest.TestCase):
    """
    Flat watchdog.* keys accept env vars and produce the expected value from get.

    Failure class: env var ignored → wrong value returned (alert layer misconfigured).
    """

    def test_enabled_false_via_env(self):
        """Z_HARNESS_WATCHDOG_ENABLED=false → watchdog.enabled = false."""
        r = _run(["get", "watchdog.enabled"],
                 extra_env={"Z_HARNESS_WATCHDOG_ENABLED": "false"})
        self.assertEqual(r.returncode, 0, msg=r.stderr)
        self.assertEqual(r.stdout.strip(), "false",
                         msg="Z_HARNESS_WATCHDOG_ENABLED=false should yield false")

    def test_enabled_true_via_env(self):
        """Z_HARNESS_WATCHDOG_ENABLED=true → watchdog.enabled = true."""
        r = _run(["get", "watchdog.enabled"],
                 extra_env={"Z_HARNESS_WATCHDOG_ENABLED": "true"})
        self.assertEqual(r.returncode, 0, msg=r.stderr)
        self.assertEqual(r.stdout.strip(), "true",
                         msg="Z_HARNESS_WATCHDOG_ENABLED=true should yield true")

    def test_sweep_interval_via_env(self):
        """Z_HARNESS_WATCHDOG_SWEEP_INTERVAL_SECS=30 → watchdog.sweep_interval_secs = 30."""
        r = _run(["get", "watchdog.sweep_interval_secs"],
                 extra_env={"Z_HARNESS_WATCHDOG_SWEEP_INTERVAL_SECS": "30"})
        self.assertEqual(r.returncode, 0, msg=r.stderr)
        self.assertEqual(r.stdout.strip(), "30",
                         msg="sweep_interval_secs should round-trip via env")

    def test_intervention_level_observe_via_env(self):
        """Z_HARNESS_WATCHDOG_INTERVENTION_LEVEL=observe → intervention_level = observe."""
        r = _run(["get", "watchdog.intervention_level"],
                 extra_env={"Z_HARNESS_WATCHDOG_INTERVENTION_LEVEL": "observe"})
        self.assertEqual(r.returncode, 0, msg=r.stderr)
        self.assertEqual(r.stdout.strip(), "observe",
                         msg="intervention_level should accept 'observe' via env")

    def test_kill_grace_secs_via_env(self):
        """Z_HARNESS_WATCHDOG_KILL_GRACE_SECS=5 → kill_grace_secs = 5."""
        r = _run(["get", "watchdog.kill_grace_secs"],
                 extra_env={"Z_HARNESS_WATCHDOG_KILL_GRACE_SECS": "5"})
        self.assertEqual(r.returncode, 0, msg=r.stderr)
        self.assertEqual(r.stdout.strip(), "5")

    def test_stale_secs_via_env(self):
        """Z_HARNESS_WATCHDOG_STALE_SECS=120 → stale_secs = 120."""
        r = _run(["get", "watchdog.stale_secs"],
                 extra_env={"Z_HARNESS_WATCHDOG_STALE_SECS": "120"})
        self.assertEqual(r.returncode, 0, msg=r.stderr)
        self.assertEqual(r.stdout.strip(), "120")

    def test_export_env_includes_flat_watchdog_keys(self):
        """export-env must include Z_HARNESS_WATCHDOG_ENABLED and other flat keys."""
        r = _run(["export-env"])
        self.assertEqual(r.returncode, 0, msg=r.stderr)
        self.assertIn("Z_HARNESS_WATCHDOG_ENABLED", r.stdout,
                      msg="export-env should export Z_HARNESS_WATCHDOG_ENABLED")
        self.assertIn("Z_HARNESS_WATCHDOG_SWEEP_INTERVAL_SECS", r.stdout,
                      msg="export-env should export Z_HARNESS_WATCHDOG_SWEEP_INTERVAL_SECS")
        self.assertIn("Z_HARNESS_WATCHDOG_INTERVENTION_LEVEL", r.stdout,
                      msg="export-env should export Z_HARNESS_WATCHDOG_INTERVENTION_LEVEL")

    def test_toml_wins_over_env_for_flat_keys(self):
        """TOML-set watchdog.enabled=false wins over Z_HARNESS_WATCHDOG_ENABLED=true."""
        repo_cfg = 'schema_version = 2\n\n[watchdog]\nenabled = false\n'
        r = _run(
            ["get", "watchdog.enabled"],
            extra_env={"Z_HARNESS_WATCHDOG_ENABLED": "true"},
            repo_toml=repo_cfg,
        )
        self.assertEqual(r.returncode, 0, msg=r.stderr)
        self.assertEqual(r.stdout.strip(), "false",
                         msg="TOML must win over env for watchdog.enabled "
                             "(got true → TOML-wins gate missing for watchdog keys)")


# ---------------------------------------------------------------------------
# (c) + (d) watchdog.timeout_secs.* is config-file-only
# ---------------------------------------------------------------------------

class TestWatchdogTimeoutSecsConfigFileOnly(unittest.TestCase):
    """
    watchdog.timeout_secs.* must NOT appear in export-env output.
    They are readable via config.py get only.

    Failure class: env export of nested table causes None→'' poisoning on ingress.
    """

    def test_timeout_secs_not_in_export_env(self):
        """
        export-env must NOT include any Z_HARNESS_WATCHDOG_TIMEOUT_SECS_* lines.

        This is the critical invariant: if timeout_secs were exported, a None or
        empty ingress round-trip would silently break all subsequent config reads.
        """
        r = _run(["export-env"])
        self.assertEqual(r.returncode, 0, msg=r.stderr)
        for key in ["TIMEOUT_SECS_BASH", "TIMEOUT_SECS_SSH", "TIMEOUT_SECS_RSYNC",
                    "TIMEOUT_SECS_CARGO", "TIMEOUT_SECS_REVIEWER"]:
            self.assertNotIn(key, r.stdout,
                             msg=f"export-env must NOT export Z_HARNESS_WATCHDOG_{key} "
                                 "(config-file-only — env export risks None→'' poisoning)")

    def test_typo_env_var_is_ignored(self):
        """
        Z_HARNESS_WATCHDOG_TIMEOUT_SECS (typo'd generic name) is silently ignored.
        watchdog.timeout_secs.bash should still return the default (600).
        """
        r = _run(
            ["get", "watchdog.timeout_secs.bash"],
            extra_env={"Z_HARNESS_WATCHDOG_TIMEOUT_SECS": "9999"},
        )
        self.assertEqual(r.returncode, 0, msg=r.stderr)
        self.assertEqual(r.stdout.strip(), "600",
                         msg="Z_HARNESS_WATCHDOG_TIMEOUT_SECS should be silently ignored; "
                             "watchdog.timeout_secs.bash should return default 600")

    def test_unknown_timeout_type_exits_3(self):
        """
        config.py get watchdog.timeout_secs.<unknown> must exit 3 (unknown key).

        Failure class: exit 0 with empty output would silently misconfigure callers.
        """
        r = _run(["get", "watchdog.timeout_secs.unknown_type"])
        self.assertEqual(r.returncode, 3,
                         msg="get watchdog.timeout_secs.<unknown> should exit 3, "
                             "not exit 0 with an empty value "
                             f"(got exit {r.returncode}, stdout={r.stdout!r})")

    def test_timeout_secs_from_toml(self):
        """watchdog.timeout_secs overridden in TOML is readable via get."""
        repo_cfg = (
            'schema_version = 2\n\n'
            '[watchdog.timeout_secs]\n'
            'cargo = 3600\n'
        )
        r = _run(["get", "watchdog.timeout_secs.cargo"], repo_toml=repo_cfg)
        self.assertEqual(r.returncode, 0, msg=r.stderr)
        self.assertEqual(r.stdout.strip(), "3600",
                         msg="watchdog.timeout_secs.cargo from TOML should be readable via get")


# ---------------------------------------------------------------------------
# (e) + (f) should-notify gate for watchdog events
# ---------------------------------------------------------------------------

class TestShouldNotifyWatchdogEvents(unittest.TestCase):
    """
    Core acceptance criterion: watchdog_stall and watchdog_timeout fire under
    the default notify.level=approval_only.

    Failure class: should-notify returns "no" → notify-watchdog.sh exits silently
    → entire alert layer is inert out of the box.
    """

    def test_watchdog_stall_yes_under_approval_only(self):
        """
        should-notify --event watchdog_stall returns "yes" under approval_only (the default).

        This is the PRIMARY acceptance criterion for this task.
        """
        # approval_only is the default; no TOML override needed
        r = _run(["should-notify", "--event", "watchdog_stall"])
        self.assertEqual(r.returncode, 0, msg=r.stderr)
        self.assertEqual(r.stdout.strip(), "yes",
                         msg="watchdog_stall must return 'yes' under default notify.level=approval_only; "
                             "got 'no' — approval_only fire-set is missing watchdog_stall")

    def test_watchdog_timeout_yes_under_approval_only(self):
        """should-notify --event watchdog_timeout returns "yes" under approval_only."""
        r = _run(["should-notify", "--event", "watchdog_timeout"])
        self.assertEqual(r.returncode, 0, msg=r.stderr)
        self.assertEqual(r.stdout.strip(), "yes",
                         msg="watchdog_timeout must return 'yes' under default notify.level=approval_only; "
                             "got 'no' — approval_only fire-set is missing watchdog_timeout")

    def test_watchdog_stall_yes_under_all(self):
        """should-notify --event watchdog_stall returns "yes" when notify.level=all."""
        r = _run(
            ["should-notify", "--event", "watchdog_stall"],
            extra_env={"Z_HARNESS_NOTIFY_LEVEL": "all"},
        )
        self.assertEqual(r.returncode, 0, msg=r.stderr)
        self.assertEqual(r.stdout.strip(), "yes",
                         msg="watchdog_stall should return 'yes' when notify.level=all")

    def test_watchdog_stall_no_under_off(self):
        """should-notify --event watchdog_stall returns "no" when notify.level=off."""
        r = _run(
            ["should-notify", "--event", "watchdog_stall"],
            extra_env={"Z_HARNESS_NOTIFY_LEVEL": "off"},
        )
        self.assertEqual(r.returncode, 0, msg=r.stderr)
        self.assertEqual(r.stdout.strip(), "no",
                         msg="watchdog_stall should return 'no' when notify.level=off")

    def test_watchdog_timeout_no_under_off(self):
        """should-notify --event watchdog_timeout returns "no" when notify.level=off."""
        r = _run(
            ["should-notify", "--event", "watchdog_timeout"],
            extra_env={"Z_HARNESS_NOTIFY_LEVEL": "off"},
        )
        self.assertEqual(r.returncode, 0, msg=r.stderr)
        self.assertEqual(r.stdout.strip(), "no",
                         msg="watchdog_timeout should return 'no' when notify.level=off")

    def test_watchdog_stall_yes_under_approval_only_via_toml(self):
        """
        should-notify returns "yes" for watchdog_stall when approval_only is set in TOML.
        (Belt-and-suspenders: confirm it's not gated by the TOML-wins path.)
        """
        repo_cfg = 'schema_version = 2\n\n[notify]\nlevel = "approval_only"\n'
        r = _run(["should-notify", "--event", "watchdog_stall"], repo_toml=repo_cfg)
        self.assertEqual(r.returncode, 0, msg=r.stderr)
        self.assertEqual(r.stdout.strip(), "yes",
                         msg="watchdog_stall should return 'yes' when approval_only in TOML")

    def test_watchdog_stall_in_notify_events(self):
        """
        watchdog_stall is a valid event kind (in _NOTIFY_EVENTS).
        Failure class: exit 2 instead of 0 → should-notify errors out.
        """
        r = _run(["should-notify", "--event", "watchdog_stall"])
        self.assertNotEqual(r.returncode, 2,
                            msg="watchdog_stall must be a valid event kind (not exit 2); "
                                f"stderr: {r.stderr!r}")

    def test_watchdog_timeout_in_notify_events(self):
        """watchdog_timeout is a valid event kind (in _NOTIFY_EVENTS)."""
        r = _run(["should-notify", "--event", "watchdog_timeout"])
        self.assertNotEqual(r.returncode, 2,
                            msg="watchdog_timeout must be a valid event kind (not exit 2)")

    def test_phase_end_still_no_under_approval_only(self):
        """
        phase_end still returns "no" under approval_only (no regression).
        Only watchdog_stall/watchdog_timeout are added to the fire-set.
        """
        r = _run(["should-notify", "--event", "phase_end"])
        self.assertEqual(r.returncode, 0, msg=r.stderr)
        self.assertEqual(r.stdout.strip(), "no",
                         msg="phase_end should still return 'no' under approval_only (no regression)")

    def test_approval_still_yes_under_approval_only(self):
        """approval event still returns 'yes' under approval_only (regression check)."""
        r = _run(["should-notify", "--event", "approval"])
        self.assertEqual(r.returncode, 0, msg=r.stderr)
        self.assertEqual(r.stdout.strip(), "yes",
                         msg="approval should still return 'yes' under approval_only")

    def test_error_still_yes_under_approval_only(self):
        """error event still returns 'yes' under approval_only (regression check)."""
        r = _run(["should-notify", "--event", "error"])
        self.assertEqual(r.returncode, 0, msg=r.stderr)
        self.assertEqual(r.stdout.strip(), "yes",
                         msg="error should still return 'yes' under approval_only")


# ---------------------------------------------------------------------------
# Validator rejection tests
# ---------------------------------------------------------------------------

class TestWatchdogValidators(unittest.TestCase):
    """Invalid values for watchdog.* keys must be rejected."""

    def test_invalid_intervention_level_rejected(self):
        """intervention_level = 'kill' (unknown) must be rejected (exit 2)."""
        repo_cfg = (
            'schema_version = 2\n\n'
            '[watchdog]\n'
            'intervention_level = "kill"\n'
        )
        r = _run(["get", "watchdog.intervention_level"], repo_toml=repo_cfg)
        self.assertEqual(r.returncode, 2,
                         msg="intervention_level='kill' should be rejected (exit 2)")

    def test_negative_sweep_interval_rejected_via_env(self):
        """
        Z_HARNESS_WATCHDOG_SWEEP_INTERVAL_SECS=-1 is rejected by positive-int validator.
        """
        r = _run(
            ["get", "watchdog.sweep_interval_secs"],
            extra_env={"Z_HARNESS_WATCHDOG_SWEEP_INTERVAL_SECS": "-1"},
        )
        # Should exit non-zero (validation error) or fall back to default.
        # Either way, must NOT return "-1".
        if r.returncode == 0:
            self.assertNotEqual(r.stdout.strip(), "-1",
                                msg="negative sweep_interval_secs must not be accepted")

    def test_zero_kill_grace_rejected_via_env(self):
        """Z_HARNESS_WATCHDOG_KILL_GRACE_SECS=0 is rejected (must be int>0)."""
        r = _run(
            ["get", "watchdog.kill_grace_secs"],
            extra_env={"Z_HARNESS_WATCHDOG_KILL_GRACE_SECS": "0"},
        )
        if r.returncode == 0:
            self.assertNotEqual(r.stdout.strip(), "0",
                                msg="zero kill_grace_secs must not be accepted")


if __name__ == "__main__":
    unittest.main()
