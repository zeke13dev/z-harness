#!/usr/bin/env python3
"""
test_config.py — End-to-end smoke tests for scripts/config.py.

Run with:
    python3 scripts/test_config.py

Each test uses a hermetic XDG_CONFIG_HOME (mkdtemp) to avoid touching
the developer's real ~/.config/z-harness/.  Tests that need "no repo config"
run subprocesses from a fresh non-git temp dir so the git-rev-parse fallback
does not pick up any .z-harness/config.toml from the z-harness repo itself.
"""
import json
import os
import subprocess
import sys
import tempfile
import shutil
import unittest
from pathlib import Path

# Allow direct import of config module for pure-function tests
SCRIPTS_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPTS_DIR))

# We import only pure functions; we do NOT call main().
from config import _dotted_to_env  # noqa: E402
from config import (  # noqa: E402
    _parse_overnight_allowlist,
    OVERNIGHT_AUTODECIDE_QIDS_DEFAULT,
    QUESTION_IDS,
    _KEY_RE,
)


PYTHON = sys.executable
CONFIG_PY = str(SCRIPTS_DIR / "config.py")

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def run(args: list, *, env=None, cwd=None) -> subprocess.CompletedProcess:
    """Run config.py subcommand; always capture stdout/stderr; never raise."""
    full_env = os.environ.copy()
    # Detach from real global config
    if "XDG_CONFIG_HOME" not in (env or {}):
        full_env.pop("XDG_CONFIG_HOME", None)
    # Detach from any real Z_HARNESS_* vars that may be set in the outer shell
    for key in list(full_env):
        if key.startswith("Z_HARNESS_"):
            del full_env[key]
    if env:
        full_env.update(env)
    return subprocess.run(
        [PYTHON, CONFIG_PY] + args,
        capture_output=True,
        text=True,
        env=full_env,
        cwd=cwd,
    )


def make_xdg() -> str:
    """Return a fresh temp dir to use as XDG_CONFIG_HOME."""
    return tempfile.mkdtemp(prefix="z-harness-test-xdg-")


def make_isolation_dir() -> str:
    """Return a fresh non-git temp dir for subprocess cwd.

    This prevents the git-rev-parse fallback in _repo_config_path() from
    walking up to the z-harness repo and picking up any .z-harness/config.toml
    that might be present there now or in the future.
    """
    return tempfile.mkdtemp(prefix="z-harness-test-cwd-")


def write_global_config(xdg: str, content: str) -> str:
    """Write content to $XDG_CONFIG_HOME/z-harness/config.toml. Returns path."""
    cfg_dir = Path(xdg) / "z-harness"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    cfg_path = cfg_dir / "config.toml"
    cfg_path.write_text(content)
    return str(cfg_path)


def write_repo_config(repo_dir: str, content: str) -> str:
    """Write content to <repo_dir>/.z-harness/config.toml. Returns path."""
    cfg_dir = Path(repo_dir) / ".z-harness"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    cfg_path = cfg_dir / "config.toml"
    cfg_path.write_text(content)
    return str(cfg_path)


# ---------------------------------------------------------------------------
# Test classes
# ---------------------------------------------------------------------------

class TestBaseline(unittest.TestCase):
    """Defaults — no config files, no env overrides."""

    def setUp(self):
        self.xdg = make_xdg()
        self.cwd = make_isolation_dir()
        self.env = {"XDG_CONFIG_HOME": self.xdg}

    def tearDown(self):
        shutil.rmtree(self.xdg, ignore_errors=True)
        shutil.rmtree(self.cwd, ignore_errors=True)

    def test_get_notify_level_default(self):
        r = run(["get", "notify.level"], env=self.env, cwd=self.cwd)
        self.assertEqual(r.returncode, 0)
        self.assertEqual(r.stdout.strip(), "approval_only")

    def test_get_docs_always_apply_default(self):
        r = run(["get", "docs.always_apply"], env=self.env, cwd=self.cwd)
        self.assertEqual(r.returncode, 0)
        self.assertEqual(r.stdout.strip(), "always")

    def test_get_schema_version_exits_3(self):
        r = run(["get", "schema_version"], env=self.env, cwd=self.cwd)
        self.assertEqual(r.returncode, 3)


class TestEnvOverride(unittest.TestCase):
    """Env-var layer (layer 4)."""

    def setUp(self):
        self.xdg = make_xdg()
        self.cwd = make_isolation_dir()

    def tearDown(self):
        shutil.rmtree(self.xdg, ignore_errors=True)
        shutil.rmtree(self.cwd, ignore_errors=True)

    def test_env_off_overrides(self):
        r = run(["get", "notify.level"], env={
            "XDG_CONFIG_HOME": self.xdg,
            "Z_HARNESS_NOTIFY_LEVEL": "off",
        }, cwd=self.cwd)
        self.assertEqual(r.returncode, 0)
        self.assertEqual(r.stdout.strip(), "off")

    def test_empty_env_treated_as_missing(self):
        r = run(["get", "notify.level"], env={
            "XDG_CONFIG_HOME": self.xdg,
            "Z_HARNESS_NOTIFY_LEVEL": "",
        }, cwd=self.cwd)
        self.assertEqual(r.returncode, 0)
        self.assertEqual(r.stdout.strip(), "approval_only")

    def test_invalid_env_value_exits_2(self):
        r = run(["get", "notify.level"], env={
            "XDG_CONFIG_HOME": self.xdg,
            "Z_HARNESS_NOTIFY_LEVEL": "loud",
        }, cwd=self.cwd)
        self.assertEqual(r.returncode, 2)


class TestRepoLocalPrecedence(unittest.TestCase):
    """Repo-local config (layer 3) overrides global + defaults."""

    def setUp(self):
        self.xdg = make_xdg()
        self.repo = tempfile.mkdtemp(prefix="z-harness-test-repo-")
        self.repo_cfg = write_repo_config(
            self.repo,
            '[notify]\nlevel = "off"\n',
        )
        self.env = {
            "XDG_CONFIG_HOME": self.xdg,
            "Z_HARNESS_REPO_CONFIG": self.repo_cfg,
        }

    def tearDown(self):
        shutil.rmtree(self.xdg, ignore_errors=True)
        shutil.rmtree(self.repo, ignore_errors=True)

    def test_get_uses_repo_value(self):
        r = run(["get", "notify.level"], env=self.env)
        self.assertEqual(r.returncode, 0)
        self.assertEqual(r.stdout.strip(), "off")

    def test_explain_shows_source_repo(self):
        """explain prints the full repo config file path as source label."""
        r = run(["explain", "notify.level"], env=self.env)
        self.assertEqual(r.returncode, 0)
        # Output format: notify.level = "off"   (source: /path/to/.z-harness/config.toml)
        self.assertIn("source: " + self.repo_cfg, r.stdout)

    def test_env_takes_precedence_over_repo(self):
        env = dict(self.env)
        env["Z_HARNESS_NOTIFY_LEVEL"] = "all"
        r = run(["get", "notify.level"], env=env)
        self.assertEqual(r.returncode, 0)
        self.assertEqual(r.stdout.strip(), "all")

    def test_explain_env_source_over_repo(self):
        """explain emits 'source: env Z_HARNESS_NOTIFY_LEVEL' when env overrides repo."""
        env = dict(self.env)
        env["Z_HARNESS_NOTIFY_LEVEL"] = "all"
        r = run(["explain", "notify.level"], env=env)
        self.assertEqual(r.returncode, 0)
        # The source label is "env Z_HARNESS_NOTIFY_LEVEL" (exact env var name included)
        self.assertIn("source: env Z_HARNESS_NOTIFY_LEVEL", r.stdout)


class TestUnknownKeys(unittest.TestCase):
    """Unknown / typo'd keys exit 3."""

    def setUp(self):
        self.xdg = make_xdg()
        self.cwd = make_isolation_dir()
        self.env = {"XDG_CONFIG_HOME": self.xdg}

    def tearDown(self):
        shutil.rmtree(self.xdg, ignore_errors=True)
        shutil.rmtree(self.cwd, ignore_errors=True)

    def test_get_typo_exits_3(self):
        r = run(["get", "notify.lvel"], env=self.env, cwd=self.cwd)
        self.assertEqual(r.returncode, 3)

    def test_explain_typo_exits_3(self):
        r = run(["explain", "notify.lvel"], env=self.env, cwd=self.cwd)
        self.assertEqual(r.returncode, 3)


class TestShouldNotify(unittest.TestCase):
    """should-notify truth table."""

    def setUp(self):
        self.xdg = make_xdg()
        self.cwd = make_isolation_dir()

    def tearDown(self):
        shutil.rmtree(self.xdg, ignore_errors=True)
        shutil.rmtree(self.cwd, ignore_errors=True)

    def _sn(self, level: str, event: str) -> str:
        env = {"XDG_CONFIG_HOME": self.xdg}
        if level != "approval_only":  # approval_only is the default
            env["Z_HARNESS_NOTIFY_LEVEL"] = level
        r = run(["should-notify", "--event", event], env=env, cwd=self.cwd)
        self.assertEqual(r.returncode, 0, f"should-notify exited {r.returncode} for level={level} event={event}")
        return r.stdout.strip()

    # off × {approval, phase_end, error}
    def test_off_approval(self):
        self.assertEqual(self._sn("off", "approval"), "no")

    def test_off_phase_end(self):
        self.assertEqual(self._sn("off", "phase_end"), "no")

    def test_off_error(self):
        self.assertEqual(self._sn("off", "error"), "no")

    # approval_only × {approval, phase_end, error}
    def test_approval_only_approval(self):
        self.assertEqual(self._sn("approval_only", "approval"), "yes")

    def test_approval_only_phase_end(self):
        self.assertEqual(self._sn("approval_only", "phase_end"), "no")

    def test_approval_only_error(self):
        self.assertEqual(self._sn("approval_only", "error"), "yes")

    # all × {approval, phase_end, error}
    def test_all_approval(self):
        self.assertEqual(self._sn("all", "approval"), "yes")

    def test_all_phase_end(self):
        self.assertEqual(self._sn("all", "phase_end"), "yes")

    def test_all_error(self):
        self.assertEqual(self._sn("all", "error"), "yes")

    def test_typo_event_exits_2_with_allowlist(self):
        xdg = make_xdg()
        cwd = make_isolation_dir()
        try:
            r = run(["should-notify", "--event", "failre"], env={"XDG_CONFIG_HOME": xdg}, cwd=cwd)
            self.assertEqual(r.returncode, 2)
            # stderr should mention the allowlist
            combined = r.stderr + r.stdout
            self.assertTrue(
                any(ev in combined for ev in ("approval", "phase_end", "error")),
                f"Expected allowlist in output, got: {combined!r}",
            )
        finally:
            shutil.rmtree(xdg, ignore_errors=True)
            shutil.rmtree(cwd, ignore_errors=True)


class TestEnsureDefaults(unittest.TestCase):
    """ensure-defaults subcommand edge cases."""

    def setUp(self):
        self.xdg = make_xdg()
        self.cwd = make_isolation_dir()
        self.env = {"XDG_CONFIG_HOME": self.xdg}
        self.cfg_path = Path(self.xdg) / "z-harness" / "config.toml"

    def tearDown(self):
        shutil.rmtree(self.xdg, ignore_errors=True)
        shutil.rmtree(self.cwd, ignore_errors=True)

    def test_creates_file_on_empty_xdg(self):
        r = run(["ensure-defaults"], env=self.env, cwd=self.cwd)
        self.assertEqual(r.returncode, 0)
        self.assertIn("created", r.stdout)
        self.assertTrue(self.cfg_path.exists())

    def test_second_invocation_prints_exists_bytes_unchanged(self):
        """Second invocation must print 'exists' and leave file byte-identical."""
        r1 = run(["ensure-defaults"], env=self.env, cwd=self.cwd)
        self.assertEqual(r1.returncode, 0)
        bytes_after_first = self.cfg_path.read_bytes()
        r2 = run(["ensure-defaults"], env=self.env, cwd=self.cwd)
        self.assertEqual(r2.returncode, 0)
        self.assertIn("exists", r2.stdout)
        self.assertEqual(self.cfg_path.read_bytes(), bytes_after_first,
                         "File bytes changed on second invocation")

    def test_zero_byte_file_exits_4_not_overwritten(self):
        self.cfg_path.parent.mkdir(parents=True, exist_ok=True)
        self.cfg_path.write_text("")
        r = run(["ensure-defaults"], env=self.env, cwd=self.cwd)
        self.assertEqual(r.returncode, 4)
        # File must still be empty (not overwritten)
        self.assertEqual(self.cfg_path.stat().st_size, 0)

    def test_malformed_toml_exits_4_bytes_unchanged(self):
        """ensure-defaults must not overwrite a malformed file; byte equality check."""
        self.cfg_path.parent.mkdir(parents=True, exist_ok=True)
        bad = 'notify.level = \n'
        self.cfg_path.write_text(bad)
        original_bytes = self.cfg_path.read_bytes()
        r = run(["ensure-defaults"], env=self.env, cwd=self.cwd)
        self.assertEqual(r.returncode, 4)
        self.assertEqual(self.cfg_path.read_bytes(), original_bytes,
                         "File was modified despite malformed TOML")


class TestTomlSchemaErrors(unittest.TestCase):
    """TOML / schema validation errors."""

    def setUp(self):
        self.xdg = make_xdg()
        self.repo = tempfile.mkdtemp(prefix="z-harness-test-repo-")
        self.cwd = make_isolation_dir()

    def tearDown(self):
        shutil.rmtree(self.xdg, ignore_errors=True)
        shutil.rmtree(self.repo, ignore_errors=True)
        shutil.rmtree(self.cwd, ignore_errors=True)

    def test_repo_local_invalid_value_exits_2(self):
        repo_cfg = write_repo_config(self.repo, '[notify]\nlevel = "loud"\n')
        r = run(["get", "notify.level"], env={
            "XDG_CONFIG_HOME": self.xdg,
            "Z_HARNESS_REPO_CONFIG": repo_cfg,
        })
        self.assertEqual(r.returncode, 2)

    def test_global_invalid_value_warns_and_falls_back(self):
        write_global_config(self.xdg, '[notify]\nlevel = "loud"\n')
        r = run(["get", "notify.level"], env={"XDG_CONFIG_HOME": self.xdg},
                cwd=self.cwd)
        self.assertEqual(r.returncode, 0)
        self.assertEqual(r.stdout.strip(), "approval_only")
        self.assertIn("WARNING", r.stderr)

    def test_schema_version_2_repo_exits_2_with_file_name(self):
        """schema_version=2 in REPO config exits 2 with the file path in stderr."""
        repo_cfg = write_repo_config(self.repo, 'schema_version = 2\n[notify]\nlevel = "off"\n')
        r = run(["get", "notify.level"], env={
            "XDG_CONFIG_HOME": self.xdg,
            "Z_HARNESS_REPO_CONFIG": repo_cfg,
        })
        self.assertEqual(r.returncode, 2)
        self.assertIn(".z-harness", r.stderr)

    def test_schema_version_2_global_exits_2_with_file_path(self):
        """schema_version=2 in GLOBAL config exits 2 with the global file path in stderr."""
        global_cfg_path = write_global_config(
            self.xdg, 'schema_version = 2\n[notify]\nlevel = "off"\n'
        )
        r = run(["get", "notify.level"], env={"XDG_CONFIG_HOME": self.xdg},
                cwd=self.cwd)
        self.assertEqual(r.returncode, 2)
        self.assertIn(global_cfg_path, r.stderr,
                      f"Expected global config path {global_cfg_path!r} in stderr: {r.stderr!r}")

    def test_malformed_toml_repo_exits_2_with_line_info(self):
        repo_cfg = write_repo_config(self.repo, 'notify.level = \n')
        r = run(["get", "notify.level"], env={
            "XDG_CONFIG_HOME": self.xdg,
            "Z_HARNESS_REPO_CONFIG": repo_cfg,
        })
        self.assertEqual(r.returncode, 2)
        # tomllib errors include line/col info
        self.assertRegex(r.stderr, r"(?i)(line|col|parse|error)")

    def test_malformed_toml_global_exits_2_with_line_info(self):
        """Malformed TOML in GLOBAL config exits 2 with parser line/column info in stderr."""
        global_cfg_path = write_global_config(self.xdg, 'notify.level = \n')
        r = run(["get", "notify.level"], env={"XDG_CONFIG_HOME": self.xdg},
                cwd=self.cwd)
        self.assertEqual(r.returncode, 2)
        self.assertRegex(r.stderr, r"(?i)(line|col|parse|error)",
                         f"Expected line/col in stderr; got: {r.stderr!r}")
        # stderr should also name the global file path
        self.assertIn(global_cfg_path, r.stderr)


class TestExplicitOverridePath(unittest.TestCase):
    """Z_HARNESS_REPO_CONFIG pointing to nonexistent path."""

    def setUp(self):
        self.xdg = make_xdg()

    def tearDown(self):
        shutil.rmtree(self.xdg, ignore_errors=True)

    def test_nonexistent_path_exits_2(self):
        r = run(["get", "notify.level"], env={
            "XDG_CONFIG_HOME": self.xdg,
            "Z_HARNESS_REPO_CONFIG": "/nonexistent/path/config.toml",
        })
        self.assertEqual(r.returncode, 2)


class TestEventDedup(unittest.TestCase):
    """export-env event de-dup via Z_HARNESS_RUN.

    Tests verify both the O_EXCL stamp file AND the events.jsonl archive to
    ensure (a) first call writes exactly one config_resolved event, (b) second
    call writes zero additional events, (c) no-$Z_HARNESS_RUN writes zero events.

    The log-event.sh script requires a git repo context (git rev-parse) to
    locate the events.jsonl path, so we init a bare git repo for each test.
    """

    def setUp(self):
        self.xdg = make_xdg()
        self.run_id = f"test-run-dedup-{os.getpid()}"
        # Create a temporary git repo so log-event.sh can write events.jsonl
        self.git_repo = tempfile.mkdtemp(prefix="z-harness-test-gitrepo-")
        subprocess.run(["git", "init", "--quiet", self.git_repo], check=True)
        # Clean up any leftover stamp from prior test runs
        stamp = self._stamp_path()
        if os.path.exists(stamp):
            os.unlink(stamp)

    def tearDown(self):
        shutil.rmtree(self.xdg, ignore_errors=True)
        shutil.rmtree(self.git_repo, ignore_errors=True)
        stamp = self._stamp_path()
        if os.path.exists(stamp):
            os.unlink(stamp)

    def _stamp_path(self) -> str:
        return os.path.join(tempfile.gettempdir(), f"z-harness-config-resolved-{self.run_id}")

    def _stamp_exists(self) -> bool:
        return os.path.exists(self._stamp_path())

    def _events_jsonl_path(self) -> Path:
        return Path(self.git_repo) / "z-harness" / "archive" / self.run_id / "events.jsonl"

    def _read_config_resolved_events(self) -> list:
        """Return list of config_resolved events from the run's events.jsonl."""
        p = self._events_jsonl_path()
        if not p.exists():
            return []
        events = []
        for line in p.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            if obj.get("kind") == "config_resolved":
                events.append(obj)
        return events

    def test_first_export_env_creates_stamp(self):
        r = run(["export-env"], env={
            "XDG_CONFIG_HOME": self.xdg,
            "Z_HARNESS_RUN": self.run_id,
        }, cwd=self.git_repo)
        self.assertEqual(r.returncode, 0)
        self.assertTrue(self._stamp_exists())

    def test_first_export_env_writes_exactly_one_event(self):
        """First export-env call writes exactly one config_resolved event with values+sources."""
        r = run(["export-env"], env={
            "XDG_CONFIG_HOME": self.xdg,
            "Z_HARNESS_RUN": self.run_id,
        }, cwd=self.git_repo)
        self.assertEqual(r.returncode, 0)
        events = self._read_config_resolved_events()
        self.assertEqual(len(events), 1, f"Expected 1 config_resolved event, got {len(events)}: {events}")
        event = events[0]
        self.assertIn("values", event, "config_resolved event missing 'values' key")
        self.assertIn("sources", event, "config_resolved event missing 'sources' key")
        # Payload accuracy: defaults expected when no config files are present
        self.assertEqual(event["values"].get("notify.level"), "approval_only")
        self.assertEqual(event["sources"].get("notify.level"), "defaults")

    def test_second_export_env_same_run_blocked_by_excl(self):
        """Second export-env call with same Z_HARNESS_RUN adds zero events."""
        # First call creates the stamp and emits the event
        r1 = run(["export-env"], env={
            "XDG_CONFIG_HOME": self.xdg,
            "Z_HARNESS_RUN": self.run_id,
        }, cwd=self.git_repo)
        self.assertEqual(r1.returncode, 0)
        events_after_first = self._read_config_resolved_events()
        self.assertEqual(len(events_after_first), 1)

        # Manually write a sentinel to the stamp to detect any re-open
        Path(self._stamp_path()).write_text("SENTINEL")

        # Second call — should be blocked
        r2 = run(["export-env"], env={
            "XDG_CONFIG_HOME": self.xdg,
            "Z_HARNESS_RUN": self.run_id,
        }, cwd=self.git_repo)
        self.assertEqual(r2.returncode, 0)

        # Stamp must still contain "SENTINEL" (not re-opened)
        self.assertEqual(Path(self._stamp_path()).read_text(), "SENTINEL")
        # events.jsonl must still have exactly 1 config_resolved event (zero added)
        events_after_second = self._read_config_resolved_events()
        self.assertEqual(len(events_after_second), 1,
                         f"Second call added events; total now: {events_after_second}")

    def test_without_run_no_stamp(self):
        """Without Z_HARNESS_RUN, no stamp file is created."""
        r = run(["export-env"], env={"XDG_CONFIG_HOME": self.xdg}, cwd=self.git_repo)
        self.assertEqual(r.returncode, 0)
        self.assertFalse(self._stamp_exists())

    def test_without_run_no_event(self):
        """Without Z_HARNESS_RUN, no config_resolved event is emitted."""
        r = run(["export-env"], env={"XDG_CONFIG_HOME": self.xdg}, cwd=self.git_repo)
        self.assertEqual(r.returncode, 0)
        events = self._read_config_resolved_events()
        self.assertEqual(len(events), 0,
                         f"Expected 0 events without Z_HARNESS_RUN, got: {events}")


class TestDottedToEnvPureFunction(unittest.TestCase):
    """Direct unit tests for _dotted_to_env."""

    def test_notify_level(self):
        self.assertEqual(_dotted_to_env("notify.level"), "Z_HARNESS_NOTIFY_LEVEL")

    def test_docs_always_apply(self):
        self.assertEqual(_dotted_to_env("docs.always_apply"), "Z_HARNESS_DOCS_ALWAYS_APPLY")

    def test_hyphen_raises(self):
        with self.assertRaises(SystemExit) as cm:
            _dotted_to_env("notify-level")
        self.assertEqual(cm.exception.code, 2)

    def test_three_levels_raises(self):
        # a.b.c has a dot in the second segment → doesn't match the regex
        with self.assertRaises(SystemExit) as cm:
            _dotted_to_env("a.b.c")
        self.assertEqual(cm.exception.code, 2)

    def test_no_dot_raises(self):
        with self.assertRaises(SystemExit) as cm:
            _dotted_to_env("notify")
        self.assertEqual(cm.exception.code, 2)


class TestEvalCleanliness(unittest.TestCase):
    """eval export-env sets expected vars but not schema_version."""

    def setUp(self):
        self.xdg = make_xdg()
        self.cwd = make_isolation_dir()

    def tearDown(self):
        shutil.rmtree(self.xdg, ignore_errors=True)
        shutil.rmtree(self.cwd, ignore_errors=True)

    def test_eval_sets_notify_and_docs_not_schema(self):
        # Run export-env and capture the output
        r = run(["export-env"], env={"XDG_CONFIG_HOME": self.xdg}, cwd=self.cwd)
        self.assertEqual(r.returncode, 0)
        output = r.stdout
        self.assertIn("Z_HARNESS_NOTIFY_LEVEL", output)
        self.assertIn("Z_HARNESS_DOCS_ALWAYS_APPLY", output)
        self.assertNotIn("Z_HARNESS_SCHEMA_VERSION", output)

    def test_eval_under_set_e_succeeds(self):
        script = (
            "set -e\n"
            f"eval \"$({PYTHON} {CONFIG_PY} export-env)\"\n"
            "echo NOTIFY=$Z_HARNESS_NOTIFY_LEVEL\n"
            "echo DOCS=$Z_HARNESS_DOCS_ALWAYS_APPLY\n"
        )
        env = os.environ.copy()
        for k in list(env):
            if k.startswith("Z_HARNESS_"):
                del env[k]
        env["XDG_CONFIG_HOME"] = self.xdg
        r = subprocess.run(
            ["bash", "-c", script],
            capture_output=True,
            text=True,
            env=env,
            cwd=self.cwd,
        )
        self.assertEqual(r.returncode, 0, f"bash exited {r.returncode}; stderr={r.stderr!r}")
        self.assertIn("NOTIFY=approval_only", r.stdout)
        self.assertIn("DOCS=always", r.stdout)


# ---------------------------------------------------------------------------
# Regression tests for cmd_resolve_question (T004 refactor)
# Verifies that the build-envelope-then-emit pattern produces byte-identical
# output to the pre-refactor scatter-print-exit pattern, across all resolution
# branches: no-pref, config-only, ASK_ALL override, unknown-id, and conflict.
# ---------------------------------------------------------------------------

class TestResolveQuestion(unittest.TestCase):
    """Regression tests for resolve-question subcommand."""

    KNOWN_QID = "workflow.slug_confirm"
    KNOWN_QID2 = "workflow.audit_to_amend"
    UNKNOWN_QID = "workflow.does_not_exist"

    def setUp(self):
        self.xdg = make_xdg()
        self.cwd = make_isolation_dir()

    def tearDown(self):
        shutil.rmtree(self.xdg, ignore_errors=True)
        shutil.rmtree(self.cwd, ignore_errors=True)

    def _run_resolve(self, question_id, extra_env=None):
        env = {"XDG_CONFIG_HOME": self.xdg, "Z_HARNESS_PROJECT_ROOT": self.cwd}
        if extra_env:
            env.update(extra_env)
        return run(["resolve-question", question_id], env=env, cwd=self.cwd)

    # --- Branch: no config preference, no memory → result=ask, source=none ---

    def test_no_pref_no_memory_result_is_ask(self):
        r = self._run_resolve(self.KNOWN_QID)
        self.assertEqual(r.returncode, 0, f"stderr={r.stderr!r}")
        envelope = json.loads(r.stdout)
        self.assertEqual(envelope["result"], "ask")
        self.assertEqual(envelope["source"], "none")
        self.assertEqual(envelope["strength"], "none")
        self.assertIn("sources", envelope)
        self.assertEqual(envelope["sources"], [])

    def test_no_pref_envelope_shape_has_required_keys(self):
        """Envelope must always contain result, default, source, rule_id, strength, reason, sources."""
        r = self._run_resolve(self.KNOWN_QID)
        self.assertEqual(r.returncode, 0)
        envelope = json.loads(r.stdout)
        for key in ("result", "default", "source", "rule_id", "strength", "reason", "sources"):
            self.assertIn(key, envelope, f"missing key {key!r} in envelope")

    def test_no_pref_stdout_is_single_json_line(self):
        """stdout must be exactly one JSON line (no trailing newlines after strip)."""
        r = self._run_resolve(self.KNOWN_QID)
        self.assertEqual(r.returncode, 0)
        lines = [l for l in r.stdout.splitlines() if l.strip()]
        self.assertEqual(len(lines), 1, f"expected 1 JSON line, got: {r.stdout!r}")

    # --- Branch: config sets a non-default value, no memory → result from RESULT_MAP ---

    def test_config_auto_accept_resolves_to_skip(self):
        write_global_config(self.xdg, '[workflow]\nslug_confirm = "auto_accept"\n')
        r = self._run_resolve(self.KNOWN_QID)
        self.assertEqual(r.returncode, 0, f"stderr={r.stderr!r}")
        envelope = json.loads(r.stdout)
        self.assertEqual(envelope["result"], "skip")
        self.assertEqual(envelope["source"], "config")
        self.assertEqual(envelope["strength"], "hard")

    def test_config_recommend_derived_resolves_to_prefill(self):
        write_global_config(self.xdg, '[workflow]\nslug_confirm = "recommend_derived"\n')
        r = self._run_resolve(self.KNOWN_QID)
        self.assertEqual(r.returncode, 0, f"stderr={r.stderr!r}")
        envelope = json.loads(r.stdout)
        self.assertEqual(envelope["result"], "prefill")
        self.assertEqual(envelope["source"], "config")

    def test_config_amend_resolves_to_skip_for_audit_to_amend(self):
        write_global_config(self.xdg, '[workflow]\naudit_to_amend = "amend"\n')
        r = self._run_resolve(self.KNOWN_QID2)
        self.assertEqual(r.returncode, 0, f"stderr={r.stderr!r}")
        envelope = json.loads(r.stdout)
        self.assertEqual(envelope["result"], "skip")
        self.assertEqual(envelope["source"], "config")

    # --- Branch: Z_HARNESS_ASK_ALL=1 short-circuit ---

    def test_ask_all_override_forces_ask(self):
        # Even with a config value set, ASK_ALL overrides to ask
        write_global_config(self.xdg, '[workflow]\nslug_confirm = "auto_accept"\n')
        r = self._run_resolve(self.KNOWN_QID, extra_env={"Z_HARNESS_ASK_ALL": "1"})
        self.assertEqual(r.returncode, 0, f"stderr={r.stderr!r}")
        envelope = json.loads(r.stdout)
        self.assertEqual(envelope["result"], "ask")
        self.assertEqual(envelope["source"], "override")
        self.assertEqual(envelope["rule_id"], "Z_HARNESS_ASK_ALL")

    def test_ask_all_no_config_also_returns_ask(self):
        r = self._run_resolve(self.KNOWN_QID, extra_env={"Z_HARNESS_ASK_ALL": "1"})
        self.assertEqual(r.returncode, 0, f"stderr={r.stderr!r}")
        envelope = json.loads(r.stdout)
        self.assertEqual(envelope["result"], "ask")
        self.assertEqual(envelope["source"], "override")

    # --- Branch: unknown question_id → exit 3 with error envelope ---

    def test_unknown_question_id_exits_3(self):
        r = self._run_resolve(self.UNKNOWN_QID)
        self.assertEqual(r.returncode, 3)
        envelope = json.loads(r.stdout)
        self.assertEqual(envelope["error"], "unknown_question_id")
        self.assertIn("known", envelope)
        self.assertIn(self.KNOWN_QID, envelope["known"])

    def test_unknown_question_id_emits_json_not_plain_text(self):
        """Even on error, stdout must be valid JSON — not a plain-text message."""
        r = self._run_resolve(self.UNKNOWN_QID)
        # Must parse without raising
        parsed = json.loads(r.stdout)
        self.assertIsInstance(parsed, dict)

    # --- Behavioral invariant: diagnostics go to stderr, not stdout ---

    def test_no_pref_stderr_is_empty_by_default(self):
        """Without --explain, stderr should be empty on a clean resolution."""
        r = self._run_resolve(self.KNOWN_QID)
        self.assertEqual(r.returncode, 0)
        self.assertEqual(r.stderr.strip(), "",
                         f"unexpected stderr content: {r.stderr!r}")

    def test_explain_flag_writes_to_stderr_not_stdout(self):
        """--explain must write trace to stderr only; stdout must remain a single JSON line."""
        env = {"XDG_CONFIG_HOME": self.xdg, "Z_HARNESS_PROJECT_ROOT": self.cwd}
        r = run(["resolve-question", self.KNOWN_QID, "--explain"], env=env, cwd=self.cwd)
        self.assertEqual(r.returncode, 0)
        # stdout is still exactly one JSON line
        lines = [l for l in r.stdout.splitlines() if l.strip()]
        self.assertEqual(len(lines), 1)
        # stderr contains the explain trace
        self.assertIn("[explain]", r.stderr)

    # --- Invariant: missing required argument exits 2 ---

    def test_missing_question_id_exits_2(self):
        env = {"XDG_CONFIG_HOME": self.xdg}
        r = run(["resolve-question"], env=env, cwd=self.cwd)
        self.assertEqual(r.returncode, 2)

    def test_unknown_flag_exits_2(self):
        env = {"XDG_CONFIG_HOME": self.xdg}
        r = run(["resolve-question", self.KNOWN_QID, "--no-such-flag"], env=env, cwd=self.cwd)
        self.assertEqual(r.returncode, 2)


# ---------------------------------------------------------------------------
# Tests for T005: _apply_overnight_overrides + halt-from-ask integration
# ---------------------------------------------------------------------------

class TestApplyOvernightOverrides(unittest.TestCase):
    """
    Regression tests for _apply_overnight_overrides() and the halt-from-ask
    integration in cmd_resolve_question.

    Four branches:
    (A) no-op pass-through: Z_HARNESS_NO_ASK not set (or != halt)
    (B) allowlist hit: Z_HARNESS_NO_ASK=halt + qid in allowlist → overnight_decision
    (C) halt: Z_HARNESS_NO_ASK=halt + qid not in allowlist → halt envelope
    (D) conflict: Z_HARNESS_ASK_ALL=1 + Z_HARNESS_NO_ASK=halt → exit 5
    """

    KNOWN_QID = "workflow.slug_confirm"
    KNOWN_QID2 = "workflow.audit_to_amend"

    def setUp(self):
        self.xdg = make_xdg()
        self.cwd = make_isolation_dir()

    def tearDown(self):
        shutil.rmtree(self.xdg, ignore_errors=True)
        shutil.rmtree(self.cwd, ignore_errors=True)

    def _run_resolve(self, question_id, extra_env=None):
        env = {"XDG_CONFIG_HOME": self.xdg, "Z_HARNESS_PROJECT_ROOT": self.cwd}
        if extra_env:
            env.update(extra_env)
        return run(["resolve-question", question_id], env=env, cwd=self.cwd)

    # (A) No-op pass-through: Z_HARNESS_NO_ASK not set

    def test_no_ask_unset_result_is_ask(self):
        """Without Z_HARNESS_NO_ASK, envelope passes through unchanged (result=ask)."""
        r = self._run_resolve(self.KNOWN_QID)
        self.assertEqual(r.returncode, 0, f"stderr={r.stderr!r}")
        envelope = json.loads(r.stdout)
        self.assertEqual(envelope["result"], "ask")

    def test_no_ask_wrong_value_does_not_halt(self):
        """Z_HARNESS_NO_ASK=something-else is ignored (not halt); envelope unchanged."""
        r = self._run_resolve(self.KNOWN_QID, extra_env={"Z_HARNESS_NO_ASK": "ignore"})
        self.assertEqual(r.returncode, 0, f"stderr={r.stderr!r}")
        envelope = json.loads(r.stdout)
        self.assertEqual(envelope["result"], "ask")

    def test_no_ask_halt_with_skip_result_is_passthrough(self):
        """When result is already skip (config=auto_accept), NO_ASK=halt is a no-op."""
        write_global_config(self.xdg, '[workflow]\nslug_confirm = "auto_accept"\n')
        r = self._run_resolve(
            self.KNOWN_QID,
            extra_env={"Z_HARNESS_NO_ASK": "halt"},
        )
        self.assertEqual(r.returncode, 0, f"stderr={r.stderr!r}")
        envelope = json.loads(r.stdout)
        # result was already skip — override should NOT fire
        self.assertEqual(envelope["result"], "skip")
        self.assertEqual(envelope["source"], "config")

    # (B) Allowlist hit: Z_HARNESS_NO_ASK=halt + qid in default allowlist

    def test_no_ask_halt_allowlist_hit_returns_overnight_decision(self):
        """slug_confirm is in the default allowlist → overnight_decision envelope."""
        r = self._run_resolve(
            self.KNOWN_QID,
            extra_env={"Z_HARNESS_NO_ASK": "halt"},
        )
        self.assertEqual(r.returncode, 0, f"stderr={r.stderr!r}")
        envelope = json.loads(r.stdout)
        self.assertEqual(envelope["source"], "overnight_allowlist")
        self.assertIn("chosen", envelope)
        self.assertEqual(envelope["chosen"], "recommend_derived")

    def test_no_ask_halt_allowlist_hit_result_mapped_from_result_map(self):
        """slug_confirm=recommend_derived maps to result=prefill via RESULT_MAP."""
        r = self._run_resolve(
            self.KNOWN_QID,
            extra_env={"Z_HARNESS_NO_ASK": "halt"},
        )
        self.assertEqual(r.returncode, 0)
        envelope = json.loads(r.stdout)
        # recommend_derived → prefill in RESULT_MAP
        self.assertEqual(envelope["result"], "prefill")

    def test_no_ask_halt_allowlist_hit_audit_to_amend(self):
        """audit_to_amend is in the default allowlist → amend chosen → result=skip."""
        r = self._run_resolve(
            self.KNOWN_QID2,
            extra_env={"Z_HARNESS_NO_ASK": "halt"},
        )
        self.assertEqual(r.returncode, 0, f"stderr={r.stderr!r}")
        envelope = json.loads(r.stdout)
        self.assertEqual(envelope["source"], "overnight_allowlist")
        self.assertEqual(envelope["chosen"], "amend")
        # amend → skip
        self.assertEqual(envelope["result"], "skip")

    def test_no_ask_halt_env_allowlist_override_wins(self):
        """Z_HARNESS_OVERNIGHT_AUTODECIDE_EFFECTIVE env entry overrides default for a qid."""
        import json as _json
        env_allowlist = _json.dumps({"workflow.slug_confirm": "auto_accept"})
        r = self._run_resolve(
            self.KNOWN_QID,
            extra_env={
                "Z_HARNESS_NO_ASK": "halt",
                "Z_HARNESS_OVERNIGHT_AUTODECIDE_EFFECTIVE": env_allowlist,
            },
        )
        self.assertEqual(r.returncode, 0, f"stderr={r.stderr!r}")
        envelope = json.loads(r.stdout)
        self.assertEqual(envelope["chosen"], "auto_accept")
        # auto_accept → skip
        self.assertEqual(envelope["result"], "skip")

    def test_no_ask_halt_allowlist_hit_envelope_has_required_keys(self):
        """overnight_decision envelope has result, default, source, rule_id, strength, reason, sources."""
        r = self._run_resolve(
            self.KNOWN_QID,
            extra_env={"Z_HARNESS_NO_ASK": "halt"},
        )
        self.assertEqual(r.returncode, 0)
        envelope = json.loads(r.stdout)
        for key in ("result", "default", "source", "rule_id", "strength", "reason", "sources"):
            self.assertIn(key, envelope, f"overnight_decision envelope missing key {key!r}")

    # (C) Halt: Z_HARNESS_NO_ASK=halt + qid NOT in allowlist

    def test_no_ask_halt_not_in_allowlist_returns_halt(self):
        """workflow.implement_all_proceed is not in the default allowlist → halt envelope."""
        r = self._run_resolve(
            "workflow.implement_all_proceed",
            extra_env={"Z_HARNESS_NO_ASK": "halt"},
        )
        self.assertEqual(r.returncode, 0, f"stderr={r.stderr!r}")
        envelope = json.loads(r.stdout)
        self.assertEqual(envelope["result"], "halt")
        self.assertEqual(envelope["halt_reason"], "no_ask_blocked")
        self.assertEqual(envelope["question_id"], "workflow.implement_all_proceed")

    def test_no_ask_halt_envelope_has_would_have_asked(self):
        """Halt envelope includes would_have_asked with exactly {default, choices}."""
        r = self._run_resolve(
            "workflow.implement_all_proceed",
            extra_env={"Z_HARNESS_NO_ASK": "halt"},
        )
        self.assertEqual(r.returncode, 0)
        envelope = json.loads(r.stdout)
        self.assertIn("would_have_asked", envelope)
        wha = envelope["would_have_asked"]
        self.assertIn("default", wha)
        self.assertIn("choices", wha)
        # Per D4: ONLY default and choices — no question/header/description
        self.assertNotIn("question", wha)
        self.assertNotIn("header", wha)
        self.assertNotIn("description", wha)

    def test_no_ask_halt_envelope_would_have_asked_choices_correct(self):
        """would_have_asked.choices matches the registered choices for the qid."""
        r = self._run_resolve(
            "workflow.implement_all_proceed",
            extra_env={"Z_HARNESS_NO_ASK": "halt"},
        )
        self.assertEqual(r.returncode, 0)
        envelope = json.loads(r.stdout)
        wha = envelope["would_have_asked"]
        self.assertEqual(sorted(wha["choices"]), ["ask", "auto_resume", "halt"])

    def test_no_ask_halt_envelope_has_source_no_ask_halt(self):
        """Halt envelope source field is 'no_ask_halt'."""
        r = self._run_resolve(
            "workflow.implement_all_proceed",
            extra_env={"Z_HARNESS_NO_ASK": "halt"},
        )
        self.assertEqual(r.returncode, 0)
        envelope = json.loads(r.stdout)
        self.assertEqual(envelope["source"], "no_ask_halt")
        self.assertEqual(envelope["rule_id"], "no_ask_halt")

    def test_no_ask_halt_stdout_is_single_json_line(self):
        """Halt envelope stdout is exactly one JSON line."""
        r = self._run_resolve(
            "workflow.implement_all_proceed",
            extra_env={"Z_HARNESS_NO_ASK": "halt"},
        )
        self.assertEqual(r.returncode, 0)
        lines = [l for l in r.stdout.splitlines() if l.strip()]
        self.assertEqual(len(lines), 1, f"expected 1 JSON line, got: {r.stdout!r}")

    def test_no_ask_halt_removes_qid_from_allowlist_via_empty_env(self):
        """Empty Z_HARNESS_OVERNIGHT_AUTODECIDE_EFFECTIVE falls back to default allowlist."""
        r = self._run_resolve(
            self.KNOWN_QID,
            extra_env={
                "Z_HARNESS_NO_ASK": "halt",
                "Z_HARNESS_OVERNIGHT_AUTODECIDE_EFFECTIVE": "",
            },
        )
        self.assertEqual(r.returncode, 0)
        envelope = json.loads(r.stdout)
        # slug_confirm is in the default allowlist → still overnight_decision
        self.assertEqual(envelope["source"], "overnight_allowlist")

    # (D) Conflict: Z_HARNESS_ASK_ALL=1 AND Z_HARNESS_NO_ASK=halt

    def test_ask_all_and_no_ask_conflict_exits_5(self):
        """Z_HARNESS_ASK_ALL=1 + Z_HARNESS_NO_ASK=halt must exit with code 5."""
        r = self._run_resolve(
            self.KNOWN_QID,
            extra_env={
                "Z_HARNESS_ASK_ALL": "1",
                "Z_HARNESS_NO_ASK": "halt",
            },
        )
        self.assertEqual(r.returncode, 5, f"expected exit 5; stderr={r.stderr!r}")

    def test_ask_all_and_no_ask_conflict_stdout_is_json(self):
        """Conflict exit still produces a JSON envelope on stdout."""
        r = self._run_resolve(
            self.KNOWN_QID,
            extra_env={
                "Z_HARNESS_ASK_ALL": "1",
                "Z_HARNESS_NO_ASK": "halt",
            },
        )
        self.assertEqual(r.returncode, 5)
        # Must be parseable JSON
        parsed = json.loads(r.stdout)
        self.assertIsInstance(parsed, dict)
        self.assertIn("error", parsed)
        self.assertEqual(parsed["error"], "config_conflict")

    def test_ask_all_and_no_ask_conflict_stderr_mentions_conflict(self):
        """Conflict must emit a diagnostic to stderr."""
        r = self._run_resolve(
            self.KNOWN_QID,
            extra_env={
                "Z_HARNESS_ASK_ALL": "1",
                "Z_HARNESS_NO_ASK": "halt",
            },
        )
        self.assertEqual(r.returncode, 5)
        combined = r.stderr + r.stdout
        self.assertIn("config_conflict", combined)

    def test_ask_all_without_no_ask_still_works(self):
        """Z_HARNESS_ASK_ALL=1 alone (no NO_ASK) must not exit 5."""
        r = self._run_resolve(
            self.KNOWN_QID,
            extra_env={"Z_HARNESS_ASK_ALL": "1"},
        )
        self.assertEqual(r.returncode, 0, f"stderr={r.stderr!r}")
        envelope = json.loads(r.stdout)
        self.assertEqual(envelope["result"], "ask")
        self.assertEqual(envelope["source"], "override")

    def test_no_ask_halt_without_ask_all_does_not_conflict(self):
        """Z_HARNESS_NO_ASK=halt alone (no ASK_ALL) must not exit 5."""
        r = self._run_resolve(
            "workflow.implement_all_proceed",
            extra_env={"Z_HARNESS_NO_ASK": "halt"},
        )
        # Should be 0, not 5
        self.assertNotEqual(r.returncode, 5, f"unexpected conflict exit; stderr={r.stderr!r}")
        self.assertEqual(r.returncode, 0)


# ---------------------------------------------------------------------------
# Tests for T007: list-question-ids returns exactly 5 registered question IDs
# ---------------------------------------------------------------------------

class TestQuestionIds(unittest.TestCase):
    """
    Verify that QUESTION_IDS contains the 5 expected registered question IDs:
    2 original (workflow.audit_to_amend, workflow.slug_confirm) and
    3 new from T007 (workflow.implement_all_proceed, workflow.review_all_proceed,
    workflow.plan_decisions_approval).

    The list-question-ids subcommand must return a sorted JSON array of exactly
    these 5 IDs. If a new ID is added without updating this test, the length
    assertion will catch it; if an expected ID is missing or renamed, the
    content assertion will catch it.
    """

    EXPECTED_IDS = [
        "workflow.audit_to_amend",
        "workflow.implement_all_proceed",
        "workflow.plan_decisions_approval",
        "workflow.review_all_proceed",
        "workflow.slug_confirm",
    ]

    def setUp(self):
        self.xdg = make_xdg()
        self.cwd = make_isolation_dir()

    def tearDown(self):
        shutil.rmtree(self.xdg, ignore_errors=True)
        shutil.rmtree(self.cwd, ignore_errors=True)

    def test_list_question_ids_returns_five_ids(self):
        """list-question-ids must return exactly 5 IDs (2 original + 3 from T007)."""
        r = run(["list-question-ids"], env={"XDG_CONFIG_HOME": self.xdg}, cwd=self.cwd)
        self.assertEqual(r.returncode, 0, f"list-question-ids exited {r.returncode}; stderr={r.stderr!r}")
        ids = json.loads(r.stdout)
        self.assertEqual(len(ids), 5, f"Expected 5 question IDs, got {len(ids)}: {ids}")

    def test_list_question_ids_contains_all_expected_ids(self):
        """list-question-ids must contain all 5 expected question IDs."""
        r = run(["list-question-ids"], env={"XDG_CONFIG_HOME": self.xdg}, cwd=self.cwd)
        self.assertEqual(r.returncode, 0)
        ids = json.loads(r.stdout)
        self.assertEqual(sorted(ids), self.EXPECTED_IDS,
                         f"Mismatch: got {sorted(ids)!r}, expected {self.EXPECTED_IDS!r}")

    def test_list_question_ids_output_is_sorted_json_array(self):
        """list-question-ids must return a sorted JSON array (not object or other type)."""
        r = run(["list-question-ids"], env={"XDG_CONFIG_HOME": self.xdg}, cwd=self.cwd)
        self.assertEqual(r.returncode, 0)
        ids = json.loads(r.stdout)
        self.assertIsInstance(ids, list, f"Expected list, got {type(ids)}")
        self.assertEqual(ids, sorted(ids), f"List is not sorted: {ids!r}")

    def test_list_question_ids_includes_three_new_t007_ids(self):
        """The 3 new T007 question IDs must be present; failing means T007 registration is incomplete."""
        r = run(["list-question-ids"], env={"XDG_CONFIG_HOME": self.xdg}, cwd=self.cwd)
        self.assertEqual(r.returncode, 0)
        ids = set(json.loads(r.stdout))
        new_ids = {
            "workflow.implement_all_proceed",
            "workflow.review_all_proceed",
            "workflow.plan_decisions_approval",
        }
        missing = new_ids - ids
        self.assertEqual(missing, set(),
                         f"T007 question IDs missing from registry: {missing!r}")


# ---------------------------------------------------------------------------
# Tests for T006: check-no-ask subcommand — 5 paths
# ---------------------------------------------------------------------------

class TestCheckNoAsk(unittest.TestCase):
    """
    Covers all 5 behavioral paths of `check-no-ask --question-id <id>`:

    Path 1: Z_HARNESS_NO_ASK != halt → proceed, rule_id=no_overnight_active
    Path 2: NO_ASK=halt, qid registered, in allowlist → proceed (overnight_decision)
    Path 3: NO_ASK=halt, qid registered, NOT in allowlist → halt
    Path 4: NO_ASK=halt, qid NOT registered → halt + unknown_ask_blocked
    Path 5: Bad invocation (missing --question-id, wrong flag) → exit 2
    """

    # A qid that IS in the default allowlist (OVERNIGHT_AUTODECIDE_QIDS_DEFAULT)
    QID_IN_ALLOWLIST = "workflow.slug_confirm"
    # A qid that IS registered but NOT in the default allowlist
    QID_NOT_IN_ALLOWLIST = "workflow.implement_all_proceed"
    # A qid that is NOT registered at all
    QID_UNREGISTERED = "workflow.does_not_exist"

    def setUp(self):
        self.xdg = make_xdg()
        self.cwd = make_isolation_dir()

    def tearDown(self):
        shutil.rmtree(self.xdg, ignore_errors=True)
        shutil.rmtree(self.cwd, ignore_errors=True)

    def _run_check(self, question_id, extra_env=None):
        env = {"XDG_CONFIG_HOME": self.xdg, "Z_HARNESS_PROJECT_ROOT": self.cwd}
        if extra_env:
            env.update(extra_env)
        return run(["check-no-ask", "--question-id", question_id], env=env, cwd=self.cwd)

    # -------------------------------------------------------------------------
    # Path 1: Z_HARNESS_NO_ASK not set (or != halt) → proceed
    # -------------------------------------------------------------------------

    def test_path1_no_ask_unset_returns_proceed(self):
        """Without Z_HARNESS_NO_ASK, any question_id returns proceed."""
        r = self._run_check(self.QID_IN_ALLOWLIST)
        self.assertEqual(r.returncode, 0, f"stderr={r.stderr!r}")
        result = json.loads(r.stdout)
        self.assertEqual(result["result"], "proceed")

    def test_path1_no_ask_unset_rule_id_is_no_overnight_active(self):
        """proceed result must carry rule_id=no_overnight_active."""
        r = self._run_check(self.QID_IN_ALLOWLIST)
        self.assertEqual(r.returncode, 0)
        result = json.loads(r.stdout)
        self.assertEqual(result["rule_id"], "no_overnight_active")

    def test_path1_no_ask_wrong_value_returns_proceed(self):
        """Z_HARNESS_NO_ASK=something-else (not halt) → proceed, no_overnight_active."""
        r = self._run_check(
            self.QID_IN_ALLOWLIST,
            extra_env={"Z_HARNESS_NO_ASK": "pause"},
        )
        self.assertEqual(r.returncode, 0)
        result = json.loads(r.stdout)
        self.assertEqual(result["result"], "proceed")
        self.assertEqual(result["rule_id"], "no_overnight_active")

    def test_path1_unregistered_qid_no_ask_unset_still_proceeds(self):
        """Even for unregistered qids, if NO_ASK != halt → proceed (not blocked)."""
        r = self._run_check(self.QID_UNREGISTERED)
        self.assertEqual(r.returncode, 0)
        result = json.loads(r.stdout)
        self.assertEqual(result["result"], "proceed")
        self.assertEqual(result["rule_id"], "no_overnight_active")

    def test_path1_output_contains_question_id(self):
        """Output JSON must contain the question_id field."""
        r = self._run_check(self.QID_IN_ALLOWLIST)
        self.assertEqual(r.returncode, 0)
        result = json.loads(r.stdout)
        self.assertIn("question_id", result)
        self.assertEqual(result["question_id"], self.QID_IN_ALLOWLIST)

    # -------------------------------------------------------------------------
    # Path 2: NO_ASK=halt, qid registered, in allowlist → proceed
    # -------------------------------------------------------------------------

    def test_path2_allowlist_hit_returns_proceed(self):
        """workflow.slug_confirm is in the default allowlist → proceed."""
        r = self._run_check(
            self.QID_IN_ALLOWLIST,
            extra_env={"Z_HARNESS_NO_ASK": "halt"},
        )
        self.assertEqual(r.returncode, 0, f"stderr={r.stderr!r}")
        result = json.loads(r.stdout)
        self.assertEqual(result["result"], "proceed")

    def test_path2_allowlist_hit_rule_id_not_no_ask_halt(self):
        """Allowlist-resolved proceed must not carry rule_id=no_ask_halt."""
        r = self._run_check(
            self.QID_IN_ALLOWLIST,
            extra_env={"Z_HARNESS_NO_ASK": "halt"},
        )
        self.assertEqual(r.returncode, 0)
        result = json.loads(r.stdout)
        self.assertNotEqual(result.get("rule_id"), "no_ask_halt",
                            "rule_id should not be no_ask_halt when allowlist matched")

    def test_path2_env_allowlist_override_proceeds(self):
        """A qid added to Z_HARNESS_OVERNIGHT_AUTODECIDE_EFFECTIVE env is resolved as proceed."""
        env_allowlist = json.dumps({"workflow.implement_all_proceed": "auto_resume"})
        r = self._run_check(
            self.QID_NOT_IN_ALLOWLIST,
            extra_env={
                "Z_HARNESS_NO_ASK": "halt",
                "Z_HARNESS_OVERNIGHT_AUTODECIDE_EFFECTIVE": env_allowlist,
            },
        )
        self.assertEqual(r.returncode, 0, f"stderr={r.stderr!r}")
        result = json.loads(r.stdout)
        self.assertEqual(result["result"], "proceed")

    def test_path2_output_is_valid_json_with_required_keys(self):
        """check-no-ask output must be valid JSON with result, question_id, rule_id."""
        r = self._run_check(
            self.QID_IN_ALLOWLIST,
            extra_env={"Z_HARNESS_NO_ASK": "halt"},
        )
        self.assertEqual(r.returncode, 0)
        result = json.loads(r.stdout)
        for key in ("result", "question_id", "rule_id"):
            self.assertIn(key, result, f"missing key {key!r}")

    # -------------------------------------------------------------------------
    # Path 3: NO_ASK=halt, qid registered, NOT in allowlist → halt
    # -------------------------------------------------------------------------

    def test_path3_not_in_allowlist_returns_halt(self):
        """workflow.implement_all_proceed is not in the default allowlist → halt."""
        r = self._run_check(
            self.QID_NOT_IN_ALLOWLIST,
            extra_env={"Z_HARNESS_NO_ASK": "halt"},
        )
        self.assertEqual(r.returncode, 0, f"stderr={r.stderr!r}")
        result = json.loads(r.stdout)
        self.assertEqual(result["result"], "halt")

    def test_path3_halt_rule_id_is_no_ask_halt(self):
        """Halt result from an unallisted registered qid must carry rule_id=no_ask_halt."""
        r = self._run_check(
            self.QID_NOT_IN_ALLOWLIST,
            extra_env={"Z_HARNESS_NO_ASK": "halt"},
        )
        self.assertEqual(r.returncode, 0)
        result = json.loads(r.stdout)
        self.assertEqual(result["rule_id"], "no_ask_halt")

    def test_path3_halt_exit_code_is_0(self):
        """Halt is a valid outcome, not an error — exit code must be 0."""
        r = self._run_check(
            self.QID_NOT_IN_ALLOWLIST,
            extra_env={"Z_HARNESS_NO_ASK": "halt"},
        )
        # Exit 0 means "I successfully determined the answer is halt"
        self.assertEqual(r.returncode, 0)

    def test_path3_removing_qid_from_env_allowlist_halts(self):
        """
        Providing an empty env allowlist falls back to defaults; a qid not in
        defaults (implement_all_proceed) still halts.
        """
        r = self._run_check(
            self.QID_NOT_IN_ALLOWLIST,
            extra_env={
                "Z_HARNESS_NO_ASK": "halt",
                "Z_HARNESS_OVERNIGHT_AUTODECIDE_EFFECTIVE": "{}",
            },
        )
        self.assertEqual(r.returncode, 0)
        result = json.loads(r.stdout)
        self.assertEqual(result["result"], "halt")

    # -------------------------------------------------------------------------
    # Path 4: NO_ASK=halt, qid NOT registered → halt + unknown_ask_blocked event
    # -------------------------------------------------------------------------

    def test_path4_unregistered_returns_halt(self):
        """Unregistered question_id with NO_ASK=halt → halt, rule_id=unknown_ask_blocked."""
        r = self._run_check(
            self.QID_UNREGISTERED,
            extra_env={"Z_HARNESS_NO_ASK": "halt"},
        )
        self.assertEqual(r.returncode, 0, f"stderr={r.stderr!r}")
        result = json.loads(r.stdout)
        self.assertEqual(result["result"], "halt")

    def test_path4_unregistered_rule_id_is_unknown_ask_blocked(self):
        """rule_id must be unknown_ask_blocked for unregistered qids."""
        r = self._run_check(
            self.QID_UNREGISTERED,
            extra_env={"Z_HARNESS_NO_ASK": "halt"},
        )
        self.assertEqual(r.returncode, 0)
        result = json.loads(r.stdout)
        self.assertEqual(result["rule_id"], "unknown_ask_blocked")

    def test_path4_unregistered_exit_code_is_0(self):
        """unknown_ask_blocked is a valid outcome — exit 0, not exit 2 or 3."""
        r = self._run_check(
            self.QID_UNREGISTERED,
            extra_env={"Z_HARNESS_NO_ASK": "halt"},
        )
        self.assertEqual(r.returncode, 0)

    def test_path4_registered_qid_with_no_ask_halt_does_not_emit_unknown_ask_blocked(self):
        """
        A REGISTERED qid must not produce rule_id=unknown_ask_blocked even when halting.
        This ensures path 3 and path 4 are distinct.
        """
        r = self._run_check(
            self.QID_NOT_IN_ALLOWLIST,
            extra_env={"Z_HARNESS_NO_ASK": "halt"},
        )
        self.assertEqual(r.returncode, 0)
        result = json.loads(r.stdout)
        self.assertNotEqual(result.get("rule_id"), "unknown_ask_blocked",
                            "Registered qid must not produce unknown_ask_blocked rule_id")

    # -------------------------------------------------------------------------
    # Path 5: Bad invocation → exit 2
    # -------------------------------------------------------------------------

    def test_path5_missing_question_id_flag_exits_2(self):
        """check-no-ask with no --question-id must exit 2."""
        env = {"XDG_CONFIG_HOME": self.xdg}
        r = run(["check-no-ask"], env=env, cwd=self.cwd)
        self.assertEqual(r.returncode, 2)

    def test_path5_unknown_flag_exits_2(self):
        """check-no-ask with an unrecognized flag must exit 2."""
        env = {"XDG_CONFIG_HOME": self.xdg}
        r = run(["check-no-ask", "--unknown-flag", "value"], env=env, cwd=self.cwd)
        self.assertEqual(r.returncode, 2)

    def test_path5_missing_flag_value_exits_2(self):
        """check-no-ask --question-id with no value must exit 2."""
        env = {"XDG_CONFIG_HOME": self.xdg}
        r = run(["check-no-ask", "--question-id"], env=env, cwd=self.cwd)
        self.assertEqual(r.returncode, 2)

    def test_path5_positional_arg_without_flag_exits_2(self):
        """check-no-ask <qid> (positional, no flag) must exit 2."""
        env = {"XDG_CONFIG_HOME": self.xdg}
        r = run(["check-no-ask", "workflow.slug_confirm"], env=env, cwd=self.cwd)
        self.assertEqual(r.returncode, 2)

    def test_path5_stderr_contains_usage(self):
        """On bad invocation, stderr must contain usage hint."""
        env = {"XDG_CONFIG_HOME": self.xdg}
        r = run(["check-no-ask"], env=env, cwd=self.cwd)
        self.assertEqual(r.returncode, 2)
        self.assertIn("--question-id", r.stderr)

    def test_path5_stdout_is_empty_on_exit_2(self):
        """On argparse error (exit 2), stdout must be empty — no partial JSON."""
        env = {"XDG_CONFIG_HOME": self.xdg}
        r = run(["check-no-ask"], env=env, cwd=self.cwd)
        self.assertEqual(r.returncode, 2)
        self.assertEqual(r.stdout.strip(), "", f"unexpected stdout: {r.stdout!r}")


# ---------------------------------------------------------------------------
# Tests for T017: _parse_overnight_allowlist validator
# ---------------------------------------------------------------------------

class TestParseOvernightAllowlist(unittest.TestCase):
    """
    Unit tests for the _parse_overnight_allowlist() pure function.

    Acceptance criteria (T017):
    - Valid JSON object with qid→value pairs → validated dict returned.
    - Malformed JSON → returns defaults + logs to stderr.
    - Unregistered qid → entry dropped + routing_preference_malformed emitted.
    - Invalid value for registered qid → entry dropped + event emitted.
    - Empty / whitespace string → empty dict (no-op merge; only defaults returned).
    - Non-JSON-object (e.g. list, string) → falls back to defaults.
    - Non-string key or value → entry dropped + event emitted.
    - Nested (non-string) value → entry dropped + event emitted.
    """

    # Known valid qid and its valid choices
    VALID_QID = "workflow.slug_confirm"
    VALID_QID_CHOICES = {"ask", "auto_accept", "recommend_derived"}

    # A qid in the default allowlist
    DEFAULT_ALLOWLIST_QID = "workflow.audit_to_amend"
    DEFAULT_ALLOWLIST_VALUE = "amend"

    # An unregistered qid
    UNKNOWN_QID = "workflow.does_not_exist"

    def _parse(self, s: str) -> dict:
        """Thin wrapper so tests stay readable."""
        return _parse_overnight_allowlist(s)

    # -------------------------------------------------------------------------
    # Empty / unset → defaults only
    # -------------------------------------------------------------------------

    def test_empty_string_returns_defaults(self):
        """Empty string returns the default allowlist unchanged."""
        result = self._parse("")
        self.assertEqual(result, dict(OVERNIGHT_AUTODECIDE_QIDS_DEFAULT))

    def test_whitespace_only_returns_defaults(self):
        """Whitespace-only string is treated as empty; defaults returned."""
        result = self._parse("   \t\n  ")
        self.assertEqual(result, dict(OVERNIGHT_AUTODECIDE_QIDS_DEFAULT))

    def test_defaults_are_present_in_empty_result(self):
        """Even when the env string is empty, default qids are present in the result."""
        result = self._parse("")
        for qid, val in OVERNIGHT_AUTODECIDE_QIDS_DEFAULT.items():
            self.assertIn(qid, result)
            self.assertEqual(result[qid], val)

    # -------------------------------------------------------------------------
    # Valid JSON object → accepted entries merged over defaults
    # -------------------------------------------------------------------------

    def test_valid_json_object_accepted_entry_merged(self):
        """A valid qid=value pair from JSON is accepted and present in result."""
        payload = json.dumps({"workflow.slug_confirm": "auto_accept"})
        result = self._parse(payload)
        self.assertEqual(result["workflow.slug_confirm"], "auto_accept")

    def test_valid_json_env_overrides_default(self):
        """Env entry overrides a default-allowlist entry on key collision."""
        # Default has slug_confirm = recommend_derived; override to auto_accept
        payload = json.dumps({"workflow.slug_confirm": "auto_accept"})
        result = self._parse(payload)
        # Override must win
        self.assertEqual(result["workflow.slug_confirm"], "auto_accept")
        # Other default entries still present
        self.assertEqual(result["workflow.audit_to_amend"], "amend")

    def test_valid_json_multiple_entries_all_accepted(self):
        """Multiple valid entries are all accepted and merged."""
        payload = json.dumps({
            "workflow.slug_confirm": "auto_accept",
            "workflow.implement_all_proceed": "auto_resume",
        })
        result = self._parse(payload)
        self.assertEqual(result["workflow.slug_confirm"], "auto_accept")
        self.assertEqual(result["workflow.implement_all_proceed"], "auto_resume")

    def test_valid_json_result_is_superset_of_defaults(self):
        """When env adds new valid entries, result is a superset of defaults."""
        payload = json.dumps({"workflow.implement_all_proceed": "auto_resume"})
        result = self._parse(payload)
        # All defaults still present
        for qid, val in OVERNIGHT_AUTODECIDE_QIDS_DEFAULT.items():
            self.assertIn(qid, result)
            self.assertEqual(result[qid], val)
        # New entry also present
        self.assertIn("workflow.implement_all_proceed", result)

    def test_all_valid_choices_for_slug_confirm_accepted(self):
        """Every valid choice for workflow.slug_confirm is accepted."""
        for choice in self.VALID_QID_CHOICES:
            payload = json.dumps({self.VALID_QID: choice})
            result = self._parse(payload)
            self.assertEqual(result[self.VALID_QID], choice,
                             f"Expected choice {choice!r} to be accepted")

    # -------------------------------------------------------------------------
    # Malformed JSON → falls back to defaults, logs to stderr
    # -------------------------------------------------------------------------

    def test_malformed_json_returns_defaults(self):
        """Malformed JSON string falls back to default allowlist."""
        result = self._parse("{not valid json}")
        self.assertEqual(result, dict(OVERNIGHT_AUTODECIDE_QIDS_DEFAULT))

    def test_malformed_json_logs_to_stderr(self, capsys=None):
        """Malformed JSON emits a warning to stderr (routing_preference_malformed or parse error)."""
        import io
        from contextlib import redirect_stderr
        buf = io.StringIO()
        with redirect_stderr(buf):
            _parse_overnight_allowlist("{not valid json}")
        stderr_output = buf.getvalue()
        self.assertIn("Z_HARNESS_OVERNIGHT_AUTODECIDE_EFFECTIVE", stderr_output,
                      f"Expected location name in stderr; got: {stderr_output!r}")

    def test_truncated_json_returns_defaults(self):
        """Truncated/incomplete JSON falls back to defaults."""
        result = self._parse('{"workflow.slug_confirm": "auto')
        self.assertEqual(result, dict(OVERNIGHT_AUTODECIDE_QIDS_DEFAULT))

    def test_empty_json_object_returns_defaults_only(self):
        """Empty JSON object '{}' → only defaults, no new entries."""
        result = self._parse("{}")
        self.assertEqual(result, dict(OVERNIGHT_AUTODECIDE_QIDS_DEFAULT))

    # -------------------------------------------------------------------------
    # Non-object JSON → falls back to defaults
    # -------------------------------------------------------------------------

    def test_json_array_falls_back_to_defaults(self):
        """JSON array (not object) causes fallback to defaults."""
        result = self._parse('[{"key": "value"}]')
        self.assertEqual(result, dict(OVERNIGHT_AUTODECIDE_QIDS_DEFAULT))

    def test_json_string_falls_back_to_defaults(self):
        """JSON string (not object) causes fallback to defaults."""
        result = self._parse('"just a string"')
        self.assertEqual(result, dict(OVERNIGHT_AUTODECIDE_QIDS_DEFAULT))

    def test_json_number_falls_back_to_defaults(self):
        """JSON number causes fallback to defaults."""
        result = self._parse("42")
        self.assertEqual(result, dict(OVERNIGHT_AUTODECIDE_QIDS_DEFAULT))

    # -------------------------------------------------------------------------
    # Unregistered qid → dropped, routing_preference_malformed event emitted
    # -------------------------------------------------------------------------

    def test_unregistered_qid_is_dropped(self):
        """An unregistered qid is dropped from the result."""
        payload = json.dumps({self.UNKNOWN_QID: "some_value"})
        result = self._parse(payload)
        self.assertNotIn(self.UNKNOWN_QID, result,
                         "Unregistered qid must be dropped from result")

    def test_unregistered_qid_does_not_pollute_defaults(self):
        """Dropping an unregistered qid leaves default entries intact."""
        payload = json.dumps({self.UNKNOWN_QID: "some_value"})
        result = self._parse(payload)
        for qid, val in OVERNIGHT_AUTODECIDE_QIDS_DEFAULT.items():
            self.assertIn(qid, result)
            self.assertEqual(result[qid], val)

    def test_unregistered_qid_logs_routing_preference_malformed(self):
        """Unregistered qid emits routing_preference_malformed to stderr."""
        import io
        from contextlib import redirect_stderr
        payload = json.dumps({self.UNKNOWN_QID: "some_value"})
        buf = io.StringIO()
        with redirect_stderr(buf):
            _parse_overnight_allowlist(payload)
        stderr_output = buf.getvalue()
        self.assertIn("routing_preference_malformed", stderr_output,
                      f"Expected routing_preference_malformed in stderr; got: {stderr_output!r}")

    def test_unregistered_qid_with_valid_entry_keeps_valid(self):
        """If one entry is unregistered and another is valid, the valid entry is kept."""
        payload = json.dumps({
            self.UNKNOWN_QID: "some_value",
            "workflow.slug_confirm": "auto_accept",
        })
        result = self._parse(payload)
        self.assertNotIn(self.UNKNOWN_QID, result)
        self.assertEqual(result["workflow.slug_confirm"], "auto_accept")

    # -------------------------------------------------------------------------
    # Invalid value for registered qid → dropped, routing_preference_malformed
    # -------------------------------------------------------------------------

    def test_invalid_value_for_registered_qid_is_dropped(self):
        """Invalid value for a registered qid is dropped from the result."""
        payload = json.dumps({"workflow.slug_confirm": "not_a_real_choice"})
        result = self._parse(payload)
        # The default value should be present (from OVERNIGHT_AUTODECIDE_QIDS_DEFAULT)
        self.assertEqual(result["workflow.slug_confirm"], "recommend_derived",
                         "Invalid value must be dropped; default allowlist value should remain")

    def test_invalid_value_logs_routing_preference_malformed(self):
        """Invalid value emits routing_preference_malformed to stderr."""
        import io
        from contextlib import redirect_stderr
        payload = json.dumps({"workflow.slug_confirm": "not_a_real_choice"})
        buf = io.StringIO()
        with redirect_stderr(buf):
            _parse_overnight_allowlist(payload)
        stderr_output = buf.getvalue()
        self.assertIn("routing_preference_malformed", stderr_output,
                      f"Expected routing_preference_malformed in stderr; got: {stderr_output!r}")

    def test_invalid_value_does_not_override_default(self):
        """An invalid value does NOT overwrite the default entry for that qid."""
        # slug_confirm default is recommend_derived; invalid override must be dropped
        payload = json.dumps({"workflow.slug_confirm": "invalid_choice"})
        result = self._parse(payload)
        self.assertEqual(result["workflow.slug_confirm"], "recommend_derived")

    def test_invalid_value_for_qid_not_in_defaults_leaves_qid_absent(self):
        """Invalid value for a qid not in defaults means that qid stays absent."""
        # implement_all_proceed is not in OVERNIGHT_AUTODECIDE_QIDS_DEFAULT
        payload = json.dumps({"workflow.implement_all_proceed": "bad_choice"})
        result = self._parse(payload)
        self.assertNotIn("workflow.implement_all_proceed", result)

    # -------------------------------------------------------------------------
    # Non-string key or value → dropped, routing_preference_malformed
    # -------------------------------------------------------------------------

    def test_non_string_value_is_dropped(self):
        """A non-string value (e.g. integer) is dropped with routing_preference_malformed."""
        # JSON parsed from: {"workflow.slug_confirm": 42}
        # json.dumps produces a valid JSON object with a non-string value
        payload = '{"workflow.slug_confirm": 42}'
        result = self._parse(payload)
        # Invalid value type → default remains
        self.assertEqual(result["workflow.slug_confirm"], "recommend_derived")

    def test_non_string_value_logs_routing_preference_malformed(self):
        """Non-string value emits routing_preference_malformed to stderr."""
        import io
        from contextlib import redirect_stderr
        payload = '{"workflow.slug_confirm": 42}'
        buf = io.StringIO()
        with redirect_stderr(buf):
            _parse_overnight_allowlist(payload)
        stderr_output = buf.getvalue()
        self.assertIn("routing_preference_malformed", stderr_output)

    def test_nested_object_value_is_dropped(self):
        """Nested dict value (non-string) is dropped with routing_preference_malformed."""
        payload = '{"workflow.slug_confirm": {"nested": "value"}}'
        result = self._parse(payload)
        self.assertEqual(result["workflow.slug_confirm"], "recommend_derived")

    def test_null_value_is_dropped(self):
        """JSON null value (non-string) is dropped."""
        payload = '{"workflow.slug_confirm": null}'
        result = self._parse(payload)
        self.assertEqual(result["workflow.slug_confirm"], "recommend_derived")

    def test_boolean_value_is_dropped(self):
        """JSON boolean value (non-string) is dropped."""
        payload = '{"workflow.slug_confirm": true}'
        result = self._parse(payload)
        self.assertEqual(result["workflow.slug_confirm"], "recommend_derived")

    # -------------------------------------------------------------------------
    # Return type invariants
    # -------------------------------------------------------------------------

    def test_return_type_is_dict(self):
        """Return type is always dict[str, str]."""
        for s in ("", "{}", '{"workflow.slug_confirm": "auto_accept"}', "not json"):
            result = self._parse(s)
            self.assertIsInstance(result, dict, f"Expected dict for input {s!r}, got {type(result)}")

    def test_all_values_in_result_are_strings(self):
        """All values in the returned dict are strings."""
        payload = json.dumps({
            "workflow.slug_confirm": "auto_accept",
            "workflow.implement_all_proceed": "auto_resume",
        })
        result = self._parse(payload)
        for k, v in result.items():
            self.assertIsInstance(v, str,
                                  f"Value for {k!r} should be str, got {type(v)}: {v!r}")

    def test_all_keys_in_result_are_registered_qids(self):
        """All keys in the returned dict are registered question_ids."""
        payload = json.dumps({
            "workflow.slug_confirm": "auto_accept",
            self.UNKNOWN_QID: "some_value",
        })
        result = self._parse(payload)
        for k in result:
            self.assertIn(k, QUESTION_IDS,
                          f"Key {k!r} in result is not a registered question_id")


# ---------------------------------------------------------------------------
# Tests for T001: 3-level TOML nesting (roles.<command>.<role> bindings)
# ---------------------------------------------------------------------------

class TestThreeLevelNesting(unittest.TestCase):
    """
    Covers all T001 acceptance criteria for 3-level TOML key support:

    1. _KEY_RE accepts 4-segment keys (roles.z_plan.consultant_primary.persona)
       and rejects invalid forms (empty segment, 5-segment, uppercase, hyphens).
    2. Round-trip parse: [roles.z_plan.consultant_primary] persona = "X" via load_config().
    3. cmd_export_env outputs no Z_HARNESS_ROLES_* lines.
    4. cmd_explain traverses 3-level paths and shows value + source.
    5. Per-field merge: global defines persona="A", repo defines model="opus";
       merged effective binding has both.
    6. Existing 2-level keys (notify.level, workflow.audit_to_amend) still resolve unchanged.
    """

    def setUp(self):
        self.xdg = make_xdg()
        self.repo = tempfile.mkdtemp(prefix="z-harness-test-repo-")
        self.cwd = make_isolation_dir()

    def tearDown(self):
        shutil.rmtree(self.xdg, ignore_errors=True)
        shutil.rmtree(self.repo, ignore_errors=True)
        shutil.rmtree(self.cwd, ignore_errors=True)

    # -------------------------------------------------------------------------
    # Criterion 1: _KEY_RE accepts and rejects correctly
    # -------------------------------------------------------------------------

    def test_key_re_accepts_four_segment_roles_key(self):
        """_KEY_RE must accept roles.z_plan.consultant_primary.persona (4 segments)."""
        self.assertTrue(
            bool(_KEY_RE.match("roles.z_plan.consultant_primary.persona")),
            "_KEY_RE must accept 4-segment roles key"
        )

    def test_key_re_accepts_two_segment_key(self):
        """_KEY_RE must still accept 2-segment keys (backward compat)."""
        self.assertTrue(bool(_KEY_RE.match("notify.level")))
        self.assertTrue(bool(_KEY_RE.match("workflow.audit_to_amend")))

    def test_key_re_accepts_three_segment_key(self):
        """_KEY_RE must accept 3-segment keys (roles table header form)."""
        self.assertTrue(bool(_KEY_RE.match("roles.z_plan.consultant_primary")))

    def test_key_re_rejects_empty_segment(self):
        """_KEY_RE must reject roles..foo (empty middle segment)."""
        self.assertFalse(bool(_KEY_RE.match("roles..foo")))

    def test_key_re_rejects_five_segment_key(self):
        """_KEY_RE must reject roles.z_plan.role.field.extra (5 segments)."""
        self.assertFalse(bool(_KEY_RE.match("roles.z_plan.role.field.extra")))

    def test_key_re_rejects_uppercase(self):
        """_KEY_RE must reject keys with uppercase letters."""
        self.assertFalse(bool(_KEY_RE.match("roles.Z_Plan.consultant_primary.persona")))
        self.assertFalse(bool(_KEY_RE.match("Roles.z_plan.consultant_primary.persona")))

    def test_key_re_rejects_hyphens(self):
        """_KEY_RE must reject keys with hyphens."""
        self.assertFalse(bool(_KEY_RE.match("roles.z-plan.consultant_primary.persona")))
        self.assertFalse(bool(_KEY_RE.match("roles.z_plan.consultant-primary.persona")))

    # -------------------------------------------------------------------------
    # Criterion 2: Round-trip parse via load_config()
    # -------------------------------------------------------------------------

    def test_roundtrip_three_level_parses_correctly(self):
        """[roles.z_plan.consultant_primary] persona = 'X' parses via load_config()."""
        repo_cfg = write_repo_config(
            self.repo,
            '[roles.z_plan.consultant_primary]\npersona = "X"\n',
        )
        env = {
            "XDG_CONFIG_HOME": self.xdg,
            "Z_HARNESS_REPO_CONFIG": repo_cfg,
        }
        r = run(["get", "roles.z_plan.consultant_primary.persona"], env=env)
        self.assertEqual(r.returncode, 0, f"stderr={r.stderr!r}")
        self.assertEqual(r.stdout.strip(), "X")

    def test_roundtrip_multiple_keys_in_same_role_table(self):
        """Multiple keys in [roles.z_plan.consultant_primary] are each loadable."""
        repo_cfg = write_repo_config(
            self.repo,
            '[roles.z_plan.consultant_primary]\npersona = "myp"\nmodel = "opus"\nruntime = "codex-cli"\n',
        )
        env = {
            "XDG_CONFIG_HOME": self.xdg,
            "Z_HARNESS_REPO_CONFIG": repo_cfg,
        }
        for key, expected in [
            ("roles.z_plan.consultant_primary.persona", "myp"),
            ("roles.z_plan.consultant_primary.model", "opus"),
            ("roles.z_plan.consultant_primary.runtime", "codex-cli"),
        ]:
            r = run(["get", key], env=env)
            self.assertEqual(r.returncode, 0, f"key={key!r} stderr={r.stderr!r}")
            self.assertEqual(r.stdout.strip(), expected, f"key={key!r}")

    # -------------------------------------------------------------------------
    # Criterion 3: cmd_export_env outputs no Z_HARNESS_ROLES_* lines
    # -------------------------------------------------------------------------

    def test_export_env_no_roles_lines(self):
        """export-env must output no Z_HARNESS_ROLES_* lines even when roles are configured."""
        repo_cfg = write_repo_config(
            self.repo,
            '[roles.z_plan.consultant_primary]\npersona = "X"\nmodel = "opus"\n',
        )
        env = {
            "XDG_CONFIG_HOME": self.xdg,
            "Z_HARNESS_REPO_CONFIG": repo_cfg,
        }
        r = run(["export-env"], env=env)
        self.assertEqual(r.returncode, 0, f"stderr={r.stderr!r}")
        lines = [l for l in r.stdout.splitlines() if l.strip()]
        for line in lines:
            self.assertNotIn(
                "Z_HARNESS_ROLES_", line,
                f"export-env must not output roles lines; got: {line!r}"
            )

    def test_export_env_no_roles_lines_defaults_still_present(self):
        """export-env still outputs standard 2-level keys when roles are configured."""
        repo_cfg = write_repo_config(
            self.repo,
            '[roles.z_plan.consultant_primary]\npersona = "X"\n',
        )
        env = {
            "XDG_CONFIG_HOME": self.xdg,
            "Z_HARNESS_REPO_CONFIG": repo_cfg,
        }
        r = run(["export-env"], env=env)
        self.assertEqual(r.returncode, 0, f"stderr={r.stderr!r}")
        self.assertIn("Z_HARNESS_NOTIFY_LEVEL", r.stdout)
        self.assertIn("Z_HARNESS_DOCS_ALWAYS_APPLY", r.stdout)

    # -------------------------------------------------------------------------
    # Criterion 4: cmd_explain traverses 3-level paths
    # -------------------------------------------------------------------------

    def test_explain_shows_value_and_source_for_role_key(self):
        """cmd_explain roles.z_plan.consultant_primary.persona shows value + source."""
        repo_cfg = write_repo_config(
            self.repo,
            '[roles.z_plan.consultant_primary]\npersona = "test-persona"\n',
        )
        env = {
            "XDG_CONFIG_HOME": self.xdg,
            "Z_HARNESS_REPO_CONFIG": repo_cfg,
        }
        r = run(["explain", "roles.z_plan.consultant_primary.persona"], env=env)
        self.assertEqual(r.returncode, 0, f"stderr={r.stderr!r}")
        self.assertIn("test-persona", r.stdout)
        self.assertIn("source:", r.stdout)

    def test_explain_source_shows_repo_path_for_role_key(self):
        """cmd_explain shows the repo config file path as source for a roles key."""
        repo_cfg = write_repo_config(
            self.repo,
            '[roles.z_plan.consultant_primary]\npersona = "test-persona"\n',
        )
        env = {
            "XDG_CONFIG_HOME": self.xdg,
            "Z_HARNESS_REPO_CONFIG": repo_cfg,
        }
        r = run(["explain", "roles.z_plan.consultant_primary.persona"], env=env)
        self.assertEqual(r.returncode, 0, f"stderr={r.stderr!r}")
        self.assertIn(repo_cfg, r.stdout)

    def test_explain_unset_role_key_exits_3(self):
        """cmd_explain for a roles key not in any config exits 3 (unknown key)."""
        env = {
            "XDG_CONFIG_HOME": self.xdg,
            "Z_HARNESS_REPO_CONFIG": write_repo_config(self.repo, ""),
        }
        r = run(["explain", "roles.z_plan.consultant_primary.persona"], env=env, cwd=self.cwd)
        self.assertEqual(r.returncode, 3, f"stderr={r.stderr!r}")

    # -------------------------------------------------------------------------
    # Criterion 5: Per-field merge across global + repo layers
    # -------------------------------------------------------------------------

    def test_per_field_merge_global_persona_repo_model(self):
        """Global defines persona='A'; repo defines model='opus'; merged has both."""
        write_global_config(
            self.xdg,
            '[roles.z_plan.consultant_primary]\npersona = "A"\n',
        )
        repo_cfg = write_repo_config(
            self.repo,
            '[roles.z_plan.consultant_primary]\nmodel = "opus"\n',
        )
        env = {
            "XDG_CONFIG_HOME": self.xdg,
            "Z_HARNESS_REPO_CONFIG": repo_cfg,
        }
        # persona comes from global
        r_persona = run(["get", "roles.z_plan.consultant_primary.persona"], env=env)
        self.assertEqual(r_persona.returncode, 0, f"persona stderr={r_persona.stderr!r}")
        self.assertEqual(r_persona.stdout.strip(), "A")
        # model comes from repo
        r_model = run(["get", "roles.z_plan.consultant_primary.model"], env=env)
        self.assertEqual(r_model.returncode, 0, f"model stderr={r_model.stderr!r}")
        self.assertEqual(r_model.stdout.strip(), "opus")

    def test_per_field_merge_repo_overwrites_global_field(self):
        """When both global and repo define the same subkey, repo wins (higher priority)."""
        write_global_config(
            self.xdg,
            '[roles.z_plan.consultant_primary]\npersona = "global-persona"\nmodel = "global-model"\n',
        )
        repo_cfg = write_repo_config(
            self.repo,
            '[roles.z_plan.consultant_primary]\npersona = "repo-persona"\n',
        )
        env = {
            "XDG_CONFIG_HOME": self.xdg,
            "Z_HARNESS_REPO_CONFIG": repo_cfg,
        }
        # persona: repo overrides global
        r_persona = run(["get", "roles.z_plan.consultant_primary.persona"], env=env)
        self.assertEqual(r_persona.returncode, 0)
        self.assertEqual(r_persona.stdout.strip(), "repo-persona")
        # model: global value preserved (repo doesn't define it)
        r_model = run(["get", "roles.z_plan.consultant_primary.model"], env=env)
        self.assertEqual(r_model.returncode, 0)
        self.assertEqual(r_model.stdout.strip(), "global-model")

    # -------------------------------------------------------------------------
    # Criterion 6: Existing 2-level keys still resolve unchanged
    # -------------------------------------------------------------------------

    def test_two_level_notify_level_unaffected(self):
        """notify.level still resolves correctly when roles config is also present."""
        repo_cfg = write_repo_config(
            self.repo,
            '[notify]\nlevel = "off"\n[roles.z_plan.consultant_primary]\npersona = "X"\n',
        )
        env = {
            "XDG_CONFIG_HOME": self.xdg,
            "Z_HARNESS_REPO_CONFIG": repo_cfg,
        }
        r = run(["get", "notify.level"], env=env)
        self.assertEqual(r.returncode, 0, f"stderr={r.stderr!r}")
        self.assertEqual(r.stdout.strip(), "off")

    def test_two_level_workflow_audit_to_amend_unaffected(self):
        """workflow.audit_to_amend still resolves correctly when roles config is present."""
        repo_cfg = write_repo_config(
            self.repo,
            '[workflow]\naudit_to_amend = "amend"\n[roles.z_plan.consultant_primary]\npersona = "X"\n',
        )
        env = {
            "XDG_CONFIG_HOME": self.xdg,
            "Z_HARNESS_REPO_CONFIG": repo_cfg,
        }
        r = run(["get", "workflow.audit_to_amend"], env=env)
        self.assertEqual(r.returncode, 0, f"stderr={r.stderr!r}")
        self.assertEqual(r.stdout.strip(), "amend")

    # -------------------------------------------------------------------------
    # Validation: hyphenated sub-keys in 3-level tables are rejected
    # -------------------------------------------------------------------------

    def test_hyphenated_leaf_key_in_role_table_exits_2(self):
        """A hyphenated key under [roles.*.*] must be rejected with exit 2."""
        repo_cfg = write_repo_config(
            self.repo,
            '[roles.z_plan.consultant_primary]\npersona-name = "X"\n',
        )
        env = {
            "XDG_CONFIG_HOME": self.xdg,
            "Z_HARNESS_REPO_CONFIG": repo_cfg,
        }
        r = run(["get", "notify.level"], env=env, cwd=self.cwd)
        self.assertEqual(r.returncode, 2, f"stderr={r.stderr!r}")
        self.assertIn("hyphenated", r.stderr)

    def test_four_level_nesting_in_toml_exits_2(self):
        """4-level TOML table nesting (>3 levels) must be rejected with exit 2."""
        repo_cfg = write_repo_config(
            self.repo,
            '[roles.z_plan.consultant_primary.extra]\npersona = "X"\n',
        )
        env = {
            "XDG_CONFIG_HOME": self.xdg,
            "Z_HARNESS_REPO_CONFIG": repo_cfg,
        }
        r = run(["get", "notify.level"], env=env, cwd=self.cwd)
        self.assertEqual(r.returncode, 2, f"stderr={r.stderr!r}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    unittest.main(verbosity=2)
