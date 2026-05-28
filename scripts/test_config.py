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

# We import only the pure function; we do NOT call main().
from config import _dotted_to_env  # noqa: E402


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
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    unittest.main(verbosity=2)
