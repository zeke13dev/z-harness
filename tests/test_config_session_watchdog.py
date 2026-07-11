"""
Tests for the session-watchdog daemon config knobs (T002, session-watchdog plan).

These seven knobs are ADDED alongside the pre-existing silent-failure-watchdog
watchdog.* keys (enabled, sweep_interval_secs, intervention_level,
kill_grace_secs, max_lifetime_secs, stale_secs, timeout_secs.*) — none of the
pre-existing keys are renamed or removed. See tests/test_config_watchdog.py for
the pre-existing suite, which must keep passing unmodified.

Verifies:
  (a) All seven new watchdog.* knobs are present in DEFAULTS/VALIDATORS and
      resolve to their documented default via `config.py get`.
  (b) The knobs round-trip via env (mechanical Z_HARNESS_WATCHDOG_<KEY>
      transliteration), consistent with the pre-existing flat watchdog.* keys.
  (c) Invalid (non-positive-int) values are rejected.
  (d) None of the seven new keys collide with or shadow a pre-existing
      watchdog.* key.

Invariants under test:
  - Failure class: a new knob missing from DEFAULTS/VALIDATORS → `get` exits 3
    (unknown key) instead of returning its documented default.
  - Failure class: a new knob silently coerced to the wrong type (e.g. string
    "80" instead of int 80) would misconfigure the watchdog daemon's threshold
    math without raising an error.
"""

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
    repo_toml: str | None = None,
) -> subprocess.CompletedProcess:
    """
    Run config.py with an isolated XDG_CONFIG_HOME and optional TOML content.

    Scrubs all Z_HARNESS_* / HERMES_* preference env vars from the process
    environment for isolation, then applies extra_env overrides.
    """
    env = {k: v for k, v in os.environ.items()}
    for key in list(env.keys()):
        if key.startswith("Z_HARNESS_") or key.startswith("HERMES_"):
            del env[key]

    with tempfile.TemporaryDirectory() as td:
        td_path = Path(td)
        env["XDG_CONFIG_HOME"] = str(td_path)

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


# Documented defaults (session-watchdog INTENT acceptance checklist + LEDGER.md
# poll_interval_s rationale).
_NEW_KNOB_DEFAULTS = {
    "watchdog.context_threshold_pct": "80",
    "watchdog.context_window_tokens": "200000",
    "watchdog.stuck_after_s": "600",
    "watchdog.nudge_max": "2",
    "watchdog.judge_timeout_s": "60",
    "watchdog.signals_max_mb": "50",
    "watchdog.poll_interval_s": "45",
}

# Pre-existing silent-failure-watchdog keys that must NOT be shadowed/renamed.
_PRE_EXISTING_KEYS = {
    "watchdog.enabled": "true",
    "watchdog.sweep_interval_secs": "60",
    "watchdog.intervention_level": "notify",
    "watchdog.kill_grace_secs": "10",
    "watchdog.max_lifetime_secs": "86400",
    "watchdog.stale_secs": "300",
    "watchdog.timeout_secs.bash": "600",
}


class TestSessionWatchdogNewKnobDefaults(unittest.TestCase):
    """Each of the seven new knobs resolves to its documented default."""

    def test_each_new_knob_returns_documented_default(self):
        for key, expected in _NEW_KNOB_DEFAULTS.items():
            with self.subTest(key=key):
                r = _run(["get", key])
                self.assertEqual(r.returncode, 0, msg=f"get {key!r} failed: {r.stderr}")
                self.assertEqual(
                    r.stdout.strip(), expected,
                    msg=f"get {key!r}: expected {expected!r}, got {r.stdout.strip()!r}",
                )


class TestSessionWatchdogPreExistingKeysUntouched(unittest.TestCase):
    """
    Adding the seven new knobs must not rename, remove, or shadow any
    pre-existing silent-failure-watchdog watchdog.* key.
    """

    def test_pre_existing_keys_still_resolve(self):
        for key, expected in _PRE_EXISTING_KEYS.items():
            with self.subTest(key=key):
                r = _run(["get", key])
                self.assertEqual(r.returncode, 0, msg=f"get {key!r} failed: {r.stderr}")
                self.assertEqual(
                    r.stdout.strip(), expected,
                    msg=f"pre-existing key {key!r} changed default: "
                        f"expected {expected!r}, got {r.stdout.strip()!r}",
                )


class TestSessionWatchdogNewKnobEnvRoundTrip(unittest.TestCase):
    """New flat watchdog.* knobs round-trip via mechanical env transliteration."""

    def test_context_threshold_pct_via_env(self):
        r = _run(["get", "watchdog.context_threshold_pct"],
                 extra_env={"Z_HARNESS_WATCHDOG_CONTEXT_THRESHOLD_PCT": "90"})
        self.assertEqual(r.returncode, 0, msg=r.stderr)
        self.assertEqual(r.stdout.strip(), "90")

    def test_stuck_after_s_via_env(self):
        r = _run(["get", "watchdog.stuck_after_s"],
                 extra_env={"Z_HARNESS_WATCHDOG_STUCK_AFTER_S": "900"})
        self.assertEqual(r.returncode, 0, msg=r.stderr)
        self.assertEqual(r.stdout.strip(), "900")

    def test_nudge_max_via_env(self):
        r = _run(["get", "watchdog.nudge_max"],
                 extra_env={"Z_HARNESS_WATCHDOG_NUDGE_MAX": "3"})
        self.assertEqual(r.returncode, 0, msg=r.stderr)
        self.assertEqual(r.stdout.strip(), "3")

    def test_judge_timeout_s_via_env(self):
        r = _run(["get", "watchdog.judge_timeout_s"],
                 extra_env={"Z_HARNESS_WATCHDOG_JUDGE_TIMEOUT_S": "30"})
        self.assertEqual(r.returncode, 0, msg=r.stderr)
        self.assertEqual(r.stdout.strip(), "30")

    def test_signals_max_mb_via_env(self):
        r = _run(["get", "watchdog.signals_max_mb"],
                 extra_env={"Z_HARNESS_WATCHDOG_SIGNALS_MAX_MB": "100"})
        self.assertEqual(r.returncode, 0, msg=r.stderr)
        self.assertEqual(r.stdout.strip(), "100")

    def test_poll_interval_s_via_env(self):
        r = _run(["get", "watchdog.poll_interval_s"],
                 extra_env={"Z_HARNESS_WATCHDOG_POLL_INTERVAL_S": "30"})
        self.assertEqual(r.returncode, 0, msg=r.stderr)
        self.assertEqual(r.stdout.strip(), "30")

    def test_context_window_tokens_via_env(self):
        r = _run(["get", "watchdog.context_window_tokens"],
                 extra_env={"Z_HARNESS_WATCHDOG_CONTEXT_WINDOW_TOKENS": "150000"})
        self.assertEqual(r.returncode, 0, msg=r.stderr)
        self.assertEqual(r.stdout.strip(), "150000")

    def test_toml_wins_over_env(self):
        """TOML-set watchdog.poll_interval_s wins over env, matching pre-existing
        flat watchdog.* keys' TOML-wins gate."""
        repo_cfg = 'schema_version = 2\n\n[watchdog]\npoll_interval_s = 55\n'
        r = _run(
            ["get", "watchdog.poll_interval_s"],
            extra_env={"Z_HARNESS_WATCHDOG_POLL_INTERVAL_S": "30"},
            repo_toml=repo_cfg,
        )
        self.assertEqual(r.returncode, 0, msg=r.stderr)
        self.assertEqual(r.stdout.strip(), "55",
                         msg="TOML must win over env for watchdog.poll_interval_s")


class TestSessionWatchdogNewKnobValidators(unittest.TestCase):
    """Invalid (non-positive-int) values for the new knobs are rejected."""

    def test_zero_nudge_max_rejected_via_env(self):
        r = _run(
            ["get", "watchdog.nudge_max"],
            extra_env={"Z_HARNESS_WATCHDOG_NUDGE_MAX": "0"},
        )
        if r.returncode == 0:
            self.assertNotEqual(r.stdout.strip(), "0",
                                msg="zero nudge_max must not be accepted")

    def test_negative_poll_interval_rejected_via_env(self):
        r = _run(
            ["get", "watchdog.poll_interval_s"],
            extra_env={"Z_HARNESS_WATCHDOG_POLL_INTERVAL_S": "-5"},
        )
        if r.returncode == 0:
            self.assertNotEqual(r.stdout.strip(), "-5",
                                msg="negative poll_interval_s must not be accepted")

    def test_non_numeric_signals_max_mb_rejected_via_toml(self):
        repo_cfg = 'schema_version = 2\n\n[watchdog]\nsignals_max_mb = "not-a-number"\n'
        r = _run(["get", "watchdog.signals_max_mb"], repo_toml=repo_cfg)
        self.assertEqual(r.returncode, 2,
                         msg="non-numeric signals_max_mb should be rejected (exit 2)")


if __name__ == "__main__":
    unittest.main()
