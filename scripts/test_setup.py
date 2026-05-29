#!/usr/bin/env python3
"""
test_setup.py — Integration tests for scripts/setup.py.

Run with:
    python3 -m unittest scripts.test_setup -v

Each test uses a hermetic XDG_CONFIG_HOME (mkdtemp) and a hermetic
Z_HARNESS_REPO_CONFIG (empty file in mkdtemp) to avoid touching the
developer's real config or picking up the repo's .z-harness/config.toml.

Tests that require tomlkit (e.g. the TOML-write path) are guarded with
unittest.skipIf in case the package is absent, mirroring the convention
from test_config.py.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS_DIR = Path(__file__).parent
PYTHON = sys.executable
SETUP_PY = str(SCRIPTS_DIR / "setup.py")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_xdg() -> str:
    """Return a fresh temp dir for use as XDG_CONFIG_HOME."""
    return tempfile.mkdtemp(prefix="z-test-setup-xdg-")


def make_repo_cfg_dir() -> tuple[str, str]:
    """Return (tmp_dir, empty_config_path).

    config.py treats Z_HARNESS_REPO_CONFIG as non-existent→error, but an empty
    (zero-byte) file is valid TOML and resolves with no overrides.
    """
    d = tempfile.mkdtemp(prefix="z-test-setup-repo-")
    cfg = os.path.join(d, "config.toml")
    Path(cfg).touch()
    return d, cfg


def run_setup(args: list, *, xdg: str, repo_cfg: str, extra_env: dict | None = None) -> subprocess.CompletedProcess:
    """Run setup.py with hermetic XDG and repo config env vars."""
    env = os.environ.copy()
    # Clear any Z_HARNESS_* from the outer shell to avoid interference
    for k in list(env):
        if k.startswith("Z_HARNESS_"):
            del env[k]
    env["XDG_CONFIG_HOME"] = xdg
    env["Z_HARNESS_REPO_CONFIG"] = repo_cfg
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        [PYTHON, SETUP_PY] + args,
        capture_output=True,
        text=True,
        env=env,
    )


# ---------------------------------------------------------------------------
# TestInspectJson
# ---------------------------------------------------------------------------

class TestInspectJson(unittest.TestCase):
    """inspect --json returns valid JSON with expected TOML config keys."""

    def setUp(self):
        self.xdg = make_xdg()
        self.repo_dir, self.repo_cfg = make_repo_cfg_dir()

    def tearDown(self):
        shutil.rmtree(self.xdg, ignore_errors=True)
        shutil.rmtree(self.repo_dir, ignore_errors=True)

    def test_returns_valid_json(self):
        r = run_setup(["inspect", "--json"], xdg=self.xdg, repo_cfg=self.repo_cfg)
        self.assertEqual(r.returncode, 0, f"stderr={r.stderr!r}")
        try:
            data = json.loads(r.stdout)
        except json.JSONDecodeError as exc:
            self.fail(f"inspect --json returned invalid JSON: {exc}\nstdout={r.stdout!r}")
        self.assertIsInstance(data, dict)

    def test_contains_toml_config_keys(self):
        """inspect --json must contain the TOML-persistent config keys."""
        r = run_setup(["inspect", "--json"], xdg=self.xdg, repo_cfg=self.repo_cfg)
        self.assertEqual(r.returncode, 0)
        data = json.loads(r.stdout)
        expected_keys = [
            "notify.level",
            "docs.always_apply",
            "workflow.audit_to_amend",
            "workflow.slug_confirm",
        ]
        for key in expected_keys:
            self.assertIn(key, data, f"Expected TOML key {key!r} missing from inspect --json output")

    def test_contains_env_only_knobs(self):
        """inspect --json must contain env-only knob entries (Z_HARNESS_* keys)."""
        r = run_setup(["inspect", "--json"], xdg=self.xdg, repo_cfg=self.repo_cfg)
        self.assertEqual(r.returncode, 0)
        data = json.loads(r.stdout)
        env_keys = [k for k in data if k.startswith("Z_HARNESS_")]
        self.assertGreater(len(env_keys), 0, "No Z_HARNESS_* env-only knobs found in inspect --json output")

    def test_each_entry_has_required_fields(self):
        """Each entry in inspect --json must have value, source, persistence_class, strength."""
        r = run_setup(["inspect", "--json"], xdg=self.xdg, repo_cfg=self.repo_cfg)
        self.assertEqual(r.returncode, 0)
        data = json.loads(r.stdout)
        # Check a sample TOML key
        for key in ("notify.level", "docs.always_apply"):
            self.assertIn(key, data)
            entry = data[key]
            for field in ("value", "source", "persistence_class", "strength"):
                self.assertIn(field, entry, f"Field {field!r} missing from entry for {key!r}")

    def test_default_values_match_spec(self):
        """notify.level defaults to approval_only; docs.always_apply defaults to always."""
        r = run_setup(["inspect", "--json"], xdg=self.xdg, repo_cfg=self.repo_cfg)
        self.assertEqual(r.returncode, 0)
        data = json.loads(r.stdout)
        self.assertEqual(data["notify.level"]["value"], "approval_only")
        self.assertEqual(data["docs.always_apply"]["value"], "always")


# ---------------------------------------------------------------------------
# TestInspectFlat
# ---------------------------------------------------------------------------

class TestInspectFlat(unittest.TestCase):
    """inspect --flat returns parseable key=value lines with source column."""

    def setUp(self):
        self.xdg = make_xdg()
        self.repo_dir, self.repo_cfg = make_repo_cfg_dir()

    def tearDown(self):
        shutil.rmtree(self.xdg, ignore_errors=True)
        shutil.rmtree(self.repo_dir, ignore_errors=True)

    def test_returns_key_equals_value_lines(self):
        r = run_setup(["inspect", "--flat"], xdg=self.xdg, repo_cfg=self.repo_cfg)
        self.assertEqual(r.returncode, 0, f"stderr={r.stderr!r}")
        lines = [l for l in r.stdout.splitlines() if l.strip()]
        self.assertGreater(len(lines), 0, "inspect --flat produced no output lines")
        # Each non-empty line must contain '=' separating key and value
        for line in lines:
            self.assertIn("=", line, f"Line without '=' separator: {line!r}")

    def test_each_line_has_source_column(self):
        """Each flat line must end with a bracketed source label like [default] or [env ...]."""
        r = run_setup(["inspect", "--flat"], xdg=self.xdg, repo_cfg=self.repo_cfg)
        self.assertEqual(r.returncode, 0)
        lines = [l for l in r.stdout.splitlines() if l.strip()]
        for line in lines:
            self.assertRegex(line, r"\[.+\]$",
                             f"Line does not end with bracketed source label: {line!r}")

    def test_contains_notify_level(self):
        r = run_setup(["inspect", "--flat"], xdg=self.xdg, repo_cfg=self.repo_cfg)
        self.assertEqual(r.returncode, 0)
        self.assertIn("notify.level=", r.stdout)

    def test_contains_docs_always_apply(self):
        r = run_setup(["inspect", "--flat"], xdg=self.xdg, repo_cfg=self.repo_cfg)
        self.assertEqual(r.returncode, 0)
        self.assertIn("docs.always_apply=", r.stdout)


# ---------------------------------------------------------------------------
# TestInspectScopeWorkflow
# ---------------------------------------------------------------------------

class TestInspectScopeWorkflow(unittest.TestCase):
    """inspect --json --scope Workflow only returns workflow.* keys."""

    def setUp(self):
        self.xdg = make_xdg()
        self.repo_dir, self.repo_cfg = make_repo_cfg_dir()

    def tearDown(self):
        shutil.rmtree(self.xdg, ignore_errors=True)
        shutil.rmtree(self.repo_dir, ignore_errors=True)

    def test_scope_workflow_only_contains_workflow_keys(self):
        r = run_setup(["inspect", "--json", "--scope", "workflow"],
                      xdg=self.xdg, repo_cfg=self.repo_cfg)
        self.assertEqual(r.returncode, 0, f"stderr={r.stderr!r}")
        data = json.loads(r.stdout)
        for key in data:
            self.assertTrue(
                key.startswith("workflow."),
                f"Non-workflow key {key!r} present in --scope Workflow output",
            )

    def test_scope_workflow_contains_all_workflow_keys(self):
        r = run_setup(["inspect", "--json", "--scope", "workflow"],
                      xdg=self.xdg, repo_cfg=self.repo_cfg)
        self.assertEqual(r.returncode, 0)
        data = json.loads(r.stdout)
        expected_workflow_keys = [
            "workflow.audit_to_amend",
            "workflow.slug_confirm",
            "workflow.implement_all_proceed",
            "workflow.review_all_proceed",
            "workflow.plan_decisions_approval",
        ]
        for key in expected_workflow_keys:
            self.assertIn(key, data, f"workflow key {key!r} missing from --scope Workflow output")

    def test_scope_workflow_excludes_notify_and_docs_keys(self):
        r = run_setup(["inspect", "--json", "--scope", "workflow"],
                      xdg=self.xdg, repo_cfg=self.repo_cfg)
        self.assertEqual(r.returncode, 0)
        data = json.loads(r.stdout)
        self.assertNotIn("notify.level", data)
        self.assertNotIn("docs.always_apply", data)


# ---------------------------------------------------------------------------
# TestApplyDryRun
# ---------------------------------------------------------------------------

class TestApplyDryRun(unittest.TestCase):
    """apply --dry-run exits 0 and shows diff without writing anything."""

    def setUp(self):
        self.xdg = make_xdg()
        self.repo_dir, self.repo_cfg = make_repo_cfg_dir()

    def tearDown(self):
        shutil.rmtree(self.xdg, ignore_errors=True)
        shutil.rmtree(self.repo_dir, ignore_errors=True)

    def test_interactive_dry_run_exits_0(self):
        r = run_setup(["apply", "--posture", "interactive", "--dry-run"],
                      xdg=self.xdg, repo_cfg=self.repo_cfg)
        self.assertEqual(r.returncode, 0, f"stderr={r.stderr!r}")

    def test_interactive_dry_run_no_errors_on_stderr(self):
        r = run_setup(["apply", "--posture", "interactive", "--dry-run"],
                      xdg=self.xdg, repo_cfg=self.repo_cfg)
        self.assertEqual(r.returncode, 0)
        # No [setup] error lines in stderr
        self.assertNotIn("[setup] failed", r.stderr)

    def test_interactive_dry_run_does_not_write_global_config(self):
        """--dry-run must not write any files to XDG_CONFIG_HOME."""
        global_cfg = Path(self.xdg) / "z-harness" / "config.toml"
        self.assertFalse(global_cfg.exists(), "config.toml should not exist before dry-run")
        r = run_setup(["apply", "--posture", "interactive", "--dry-run"],
                      xdg=self.xdg, repo_cfg=self.repo_cfg)
        self.assertEqual(r.returncode, 0)
        self.assertFalse(global_cfg.exists(),
                         "--dry-run must not create config.toml")


# ---------------------------------------------------------------------------
# TestApplyOvernightDryRun
# ---------------------------------------------------------------------------

class TestApplyOvernightDryRun(unittest.TestCase):
    """apply --posture overnight --dry-run emits env snippet section."""

    def setUp(self):
        self.xdg = make_xdg()
        self.repo_dir, self.repo_cfg = make_repo_cfg_dir()

    def tearDown(self):
        shutil.rmtree(self.xdg, ignore_errors=True)
        shutil.rmtree(self.repo_dir, ignore_errors=True)

    def test_overnight_dry_run_exits_0(self):
        r = run_setup(["apply", "--posture", "overnight", "--dry-run"],
                      xdg=self.xdg, repo_cfg=self.repo_cfg)
        self.assertEqual(r.returncode, 0, f"stderr={r.stderr!r}")

    def test_overnight_dry_run_emits_env_snippet(self):
        """--dry-run overnight must include export Z_HARNESS_NO_ASK=halt in output."""
        r = run_setup(["apply", "--posture", "overnight", "--dry-run"],
                      xdg=self.xdg, repo_cfg=self.repo_cfg)
        self.assertEqual(r.returncode, 0)
        self.assertIn("Z_HARNESS_NO_ASK", r.stdout)
        self.assertIn("halt", r.stdout)

    def test_overnight_dry_run_env_snippet_has_autodecide(self):
        """--dry-run overnight must include Z_HARNESS_OVERNIGHT_AUTODECIDE_EFFECTIVE."""
        r = run_setup(["apply", "--posture", "overnight", "--dry-run"],
                      xdg=self.xdg, repo_cfg=self.repo_cfg)
        self.assertEqual(r.returncode, 0)
        self.assertIn("Z_HARNESS_OVERNIGHT_AUTODECIDE_EFFECTIVE", r.stdout)

    def test_overnight_dry_run_mentions_workflow_halt_keys(self):
        """--dry-run overnight diff must show workflow keys being set to halt."""
        r = run_setup(["apply", "--posture", "overnight", "--dry-run"],
                      xdg=self.xdg, repo_cfg=self.repo_cfg)
        self.assertEqual(r.returncode, 0)
        # The diff should mention at least one of the workflow.* keys being set to halt
        combined = r.stdout
        self.assertTrue(
            "halt" in combined,
            f"Expected 'halt' in overnight diff output; got: {combined!r}",
        )


# ---------------------------------------------------------------------------
# TestApplyUnknownPosture
# ---------------------------------------------------------------------------

class TestApplyUnknownPosture(unittest.TestCase):
    """apply --posture <unknown> exits 2."""

    def setUp(self):
        self.xdg = make_xdg()
        self.repo_dir, self.repo_cfg = make_repo_cfg_dir()

    def tearDown(self):
        shutil.rmtree(self.xdg, ignore_errors=True)
        shutil.rmtree(self.repo_dir, ignore_errors=True)

    def test_unknown_posture_exits_2(self):
        r = run_setup(["apply", "--posture", "unknown"],
                      xdg=self.xdg, repo_cfg=self.repo_cfg)
        self.assertEqual(r.returncode, 2,
                         f"Expected exit 2 for unknown posture; got {r.returncode}; stderr={r.stderr!r}")

    def test_unknown_posture_error_mentions_valid_choices(self):
        """Error output must mention the valid posture choices."""
        r = run_setup(["apply", "--posture", "badposture"],
                      xdg=self.xdg, repo_cfg=self.repo_cfg)
        self.assertEqual(r.returncode, 2)
        combined = r.stdout + r.stderr
        self.assertTrue(
            "interactive" in combined or "overnight" in combined or "ci-batch" in combined,
            f"Expected valid posture names in error output; got: {combined!r}",
        )


# ---------------------------------------------------------------------------
# TestApplyIdempotency
# ---------------------------------------------------------------------------

class TestApplyIdempotency(unittest.TestCase):
    """Re-run of apply --posture interactive --yes on already-configured setup is idempotent."""

    def setUp(self):
        self.xdg = make_xdg()
        self.repo_dir, self.repo_cfg = make_repo_cfg_dir()

    def tearDown(self):
        shutil.rmtree(self.xdg, ignore_errors=True)
        shutil.rmtree(self.repo_dir, ignore_errors=True)

    def test_second_apply_exits_0(self):
        """Both first and second apply --yes calls must exit 0."""
        r1 = run_setup(["apply", "--posture", "interactive", "--yes"],
                       xdg=self.xdg, repo_cfg=self.repo_cfg)
        self.assertEqual(r1.returncode, 0, f"First apply failed; stderr={r1.stderr!r}")

        r2 = run_setup(["apply", "--posture", "interactive", "--yes"],
                       xdg=self.xdg, repo_cfg=self.repo_cfg)
        self.assertEqual(r2.returncode, 0, f"Second apply failed; stderr={r2.stderr!r}")

    def test_second_apply_shows_no_changes(self):
        """After first apply --yes, second apply must show 'Already at target' for all keys."""
        run_setup(["apply", "--posture", "interactive", "--yes"],
                  xdg=self.xdg, repo_cfg=self.repo_cfg)
        r2 = run_setup(["apply", "--posture", "interactive", "--yes"],
                       xdg=self.xdg, repo_cfg=self.repo_cfg)
        self.assertEqual(r2.returncode, 0)
        # Must not show "Changes:" block — every key should be at target
        self.assertNotIn("Changes:", r2.stdout,
                         f"Second apply should have no changes; got:\n{r2.stdout}")

    def test_second_apply_shows_already_at_target(self):
        """Second apply stdout must contain 'Already at target' or equivalent phrase."""
        run_setup(["apply", "--posture", "interactive", "--yes"],
                  xdg=self.xdg, repo_cfg=self.repo_cfg)
        r2 = run_setup(["apply", "--posture", "interactive", "--yes"],
                       xdg=self.xdg, repo_cfg=self.repo_cfg)
        self.assertEqual(r2.returncode, 0)
        self.assertIn("Already at target", r2.stdout,
                      f"Expected 'Already at target' in second apply output; got:\n{r2.stdout}")


# ---------------------------------------------------------------------------
# TestWizardNotifications
# ---------------------------------------------------------------------------

class TestWizardNotifications(unittest.TestCase):
    """wizard --scope notifications with /dev/null stdin exits 0."""

    def setUp(self):
        self.xdg = make_xdg()
        self.repo_dir, self.repo_cfg = make_repo_cfg_dir()

    def tearDown(self):
        shutil.rmtree(self.xdg, ignore_errors=True)
        shutil.rmtree(self.repo_dir, ignore_errors=True)

    def _run_wizard_notifications(self, extra_env: dict | None = None) -> subprocess.CompletedProcess:
        """Run wizard --scope notifications with stdin from /dev/null."""
        env = os.environ.copy()
        for k in list(env):
            if k.startswith("Z_HARNESS_"):
                del env[k]
        env["XDG_CONFIG_HOME"] = self.xdg
        env["Z_HARNESS_REPO_CONFIG"] = self.repo_cfg
        if extra_env:
            env.update(extra_env)
        with open(os.devnull, "r") as devnull:
            return subprocess.run(
                [PYTHON, SETUP_PY, "wizard", "--scope", "notifications"],
                capture_output=True,
                text=True,
                env=env,
                stdin=devnull,
            )

    def test_wizard_notifications_exits_0(self):
        r = self._run_wizard_notifications()
        self.assertEqual(r.returncode, 0,
                         f"wizard --scope notifications exited {r.returncode}; "
                         f"stderr={r.stderr!r}")

    def test_wizard_notifications_shows_section_header(self):
        r = self._run_wizard_notifications()
        self.assertEqual(r.returncode, 0)
        self.assertIn("Notifications", r.stdout)

    def test_wizard_notifications_no_crash_on_eof(self):
        """stdin=devnull (EOF) must not crash the wizard — it should handle EOFError gracefully."""
        r = self._run_wizard_notifications()
        self.assertNotIn("Traceback", r.stderr)
        self.assertNotIn("EOFError", r.stderr)


# ---------------------------------------------------------------------------
# TestStatus
# ---------------------------------------------------------------------------

class TestStatus(unittest.TestCase):
    """status returns one line with the expected format."""

    def setUp(self):
        self.xdg = make_xdg()
        self.repo_dir, self.repo_cfg = make_repo_cfg_dir()

    def tearDown(self):
        shutil.rmtree(self.xdg, ignore_errors=True)
        shutil.rmtree(self.repo_dir, ignore_errors=True)

    def test_status_exits_0(self):
        r = run_setup(["status"], xdg=self.xdg, repo_cfg=self.repo_cfg)
        self.assertEqual(r.returncode, 0, f"stderr={r.stderr!r}")

    def test_status_returns_single_line(self):
        r = run_setup(["status"], xdg=self.xdg, repo_cfg=self.repo_cfg)
        self.assertEqual(r.returncode, 0)
        lines = [l for l in r.stdout.splitlines() if l.strip()]
        self.assertEqual(len(lines), 1,
                         f"status must return exactly one non-empty line; got {len(lines)}: {r.stdout!r}")

    def test_status_line_starts_with_z_harness(self):
        r = run_setup(["status"], xdg=self.xdg, repo_cfg=self.repo_cfg)
        self.assertEqual(r.returncode, 0)
        line = r.stdout.strip()
        self.assertTrue(line.startswith("z-harness:"),
                        f"status line must start with 'z-harness:'; got: {line!r}")

    def test_status_line_contains_expected_fields(self):
        """status line must contain posture=, providers=, docs=, prefs= fields."""
        r = run_setup(["status"], xdg=self.xdg, repo_cfg=self.repo_cfg)
        self.assertEqual(r.returncode, 0)
        line = r.stdout.strip()
        for field in ("posture=", "providers=", "docs=", "prefs="):
            self.assertIn(field, line,
                          f"status line missing field {field!r}; line={line!r}")

    def test_status_line_prefs_contains_standing(self):
        """status prefs field must include 'standing' suffix."""
        r = run_setup(["status"], xdg=self.xdg, repo_cfg=self.repo_cfg)
        self.assertEqual(r.returncode, 0)
        self.assertIn("standing", r.stdout,
                      f"status line must include 'standing'; got: {r.stdout!r}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    unittest.main()
