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
    # Pin the artifact base into the test's cwd. Since the Phase-D flip the
    # default base is external (XDG_STATE_HOME/...), so emitted events would
    # otherwise land outside the tmp tree the tests read from — silently, making
    # event assertions pass vacuously. Tier-1 Z_HARNESS_BASE_DIR keeps it
    # hermetic. Skipped if the caller pinned it explicitly.
    if cwd and "Z_HARNESS_BASE_DIR" not in full_env:
        full_env["Z_HARNESS_BASE_DIR"] = str(Path(cwd) / "z-harness")
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

    def test_get_intent_parallel_levels_default_on_without_repo_override(self):
        """Default-on INTENT parallelism resolves hermetically without repo config."""
        r = run(["get", "workflow.intent_parallel_levels"], env=self.env, cwd=self.cwd)
        self.assertEqual(r.returncode, 0)
        self.assertEqual(r.stdout.strip(), "true")

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

    def test_repo_false_overrides_intent_parallel_levels_default(self):
        repo_cfg = write_repo_config(
            self.repo,
            '[workflow]\nintent_parallel_levels = false\n',
        )
        env = dict(self.env)
        env["Z_HARNESS_REPO_CONFIG"] = repo_cfg
        r = run(["get", "workflow.intent_parallel_levels"], env=env)
        self.assertEqual(r.returncode, 0)
        self.assertEqual(r.stdout.strip(), "false")

    def test_explain_shows_source_repo(self):
        """explain prints the full repo config file path as source label."""
        r = run(["explain", "notify.level"], env=self.env)
        self.assertEqual(r.returncode, 0)
        # Output format: notify.level = "off"   (source: /path/to/.z-harness/config.toml)
        self.assertIn("source: " + self.repo_cfg, r.stdout)

    def test_toml_wins_over_env(self):
        """T001: TOML-wins gate — repo TOML value is NOT overridden by a preference env var."""
        env = dict(self.env)
        env["Z_HARNESS_NOTIFY_LEVEL"] = "all"
        r = run(["get", "notify.level"], env=env)
        self.assertEqual(r.returncode, 0)
        # Repo TOML set "off"; env var "all" must NOT win (TOML-wins gate).
        self.assertEqual(r.stdout.strip(), "off",
                         "T001: Z_HARNESS_NOTIFY_LEVEL=all must NOT override notify.level='off' from repo TOML")

    def test_explain_source_is_toml_not_env_when_toml_set(self):
        """T001: explain must report repo TOML as source, not the env var, when TOML set the value."""
        env = dict(self.env)
        env["Z_HARNESS_NOTIFY_LEVEL"] = "all"
        r = run(["explain", "notify.level"], env=env)
        self.assertEqual(r.returncode, 0)
        # Source must be the repo TOML file path, NOT the env var (TOML-wins gate).
        self.assertIn("source: " + self.repo_cfg, r.stdout,
                      "T001: explain must report TOML file as source, not the env var")


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

    def test_schema_version_future_repo_exits_2_with_file_name(self):
        """schema_version > current (3) in REPO config exits 2 with the file path in stderr."""
        repo_cfg = write_repo_config(self.repo, 'schema_version = 3\n[notify]\nlevel = "off"\n')
        r = run(["get", "notify.level"], env={
            "XDG_CONFIG_HOME": self.xdg,
            "Z_HARNESS_REPO_CONFIG": repo_cfg,
        })
        self.assertEqual(r.returncode, 2)
        self.assertIn(".z-harness", r.stderr)

    def test_schema_version_future_global_exits_2_with_file_path(self):
        """schema_version > current (3) in GLOBAL config exits 2 with the global file path in stderr."""
        global_cfg_path = write_global_config(
            self.xdg, 'schema_version = 3\n[notify]\nlevel = "off"\n'
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
# Tests for T007: list-question-ids returns exactly 6 registered question IDs
# ---------------------------------------------------------------------------

class TestQuestionIds(unittest.TestCase):
    """
    Verify that QUESTION_IDS contains the 6 expected registered question IDs:
    2 original (workflow.audit_to_amend, workflow.slug_confirm),
    3 from T007 (workflow.implement_all_proceed, workflow.review_all_proceed,
    workflow.plan_decisions_approval), and
    workflow.pre_run_cost_gate (pre-run token-cost gate).

    The list-question-ids subcommand must return a sorted JSON array of exactly
    these 6 IDs. If a new ID is added without updating this test, the length
    assertion will catch it; if an expected ID is missing or renamed, the
    content assertion will catch it.
    """

    EXPECTED_IDS = [
        "workflow.audit_to_amend",
        "workflow.implement_all_proceed",
        "workflow.plan_decisions_approval",
        "workflow.pre_run_cost_gate",
        "workflow.review_all_proceed",
        "workflow.slug_confirm",
    ]

    def setUp(self):
        self.xdg = make_xdg()
        self.cwd = make_isolation_dir()

    def tearDown(self):
        shutil.rmtree(self.xdg, ignore_errors=True)
        shutil.rmtree(self.cwd, ignore_errors=True)

    def test_list_question_ids_returns_six_ids(self):
        """list-question-ids must return exactly 6 IDs (2 original + 3 from T007 + pre_run_cost_gate)."""
        r = run(["list-question-ids"], env={"XDG_CONFIG_HOME": self.xdg}, cwd=self.cwd)
        self.assertEqual(r.returncode, 0, f"list-question-ids exited {r.returncode}; stderr={r.stderr!r}")
        ids = json.loads(r.stdout)
        self.assertEqual(len(ids), 6, f"Expected 6 question IDs, got {len(ids)}: {ids}")

    def test_list_question_ids_contains_all_expected_ids(self):
        """list-question-ids must contain all 6 expected question IDs."""
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

    def test_path3_removing_qid_from_env_allowlist_yields_unhandled_gate(self):
        """
        When OVERNIGHT_AUTODECIDE_EFFECTIVE is set (policy mode active), a registered
        qid not covered by the merged allowlist yields unhandled_gate (H4 fail-closed).
        OVERNIGHT_AUTODECIDE_EFFECTIVE={} merges with defaults; implement_all_proceed
        is absent from both defaults and the empty env payload → unhandled_gate.
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
        self.assertEqual(result["result"], "unhandled_gate")

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

    def test_uppercase_role_table_segment_exits_2(self):
        """Dynamic role table segments must be rejected during TOML load."""
        repo_cfg = write_repo_config(
            self.repo,
            '[roles.Z_Plan.consultant_primary]\npersona = "X"\n',
        )
        env = {
            "XDG_CONFIG_HOME": self.xdg,
            "Z_HARNESS_REPO_CONFIG": repo_cfg,
        }
        r = run(["get", "notify.level"], env=env, cwd=self.cwd)
        self.assertEqual(r.returncode, 2, f"stderr={r.stderr!r}")
        self.assertIn("non-canonical key segment", r.stderr)

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
# Tests for T002: migrate subcommand
# ---------------------------------------------------------------------------

class TestMigrate(unittest.TestCase):
    """
    Covers the `migrate` subcommand acceptance criteria:

    1. Old provider names (codex, gemini, claude) in roles.*.runtime are rewritten
       to codex-cli, gemini-cli, claude-cli in both global and project layers.
    2. Idempotent: running migrate twice produces no diff on the second run.
    3. Existing new-form names (e.g. codex-cli) are not altered.
    4. Returns exit 0 on success and on no-op (no-match).
    5. Layers that do not exist are silently skipped.
    """

    def setUp(self):
        self.xdg = make_xdg()
        self.repo = tempfile.mkdtemp(prefix="z-harness-test-migrate-repo-")
        self.cwd = make_isolation_dir()

    def tearDown(self):
        shutil.rmtree(self.xdg, ignore_errors=True)
        shutil.rmtree(self.repo, ignore_errors=True)
        shutil.rmtree(self.cwd, ignore_errors=True)

    def _global_cfg_path(self) -> Path:
        return Path(self.xdg) / "z-harness" / "config.toml"

    def _repo_cfg_path(self) -> Path:
        return Path(self.repo) / ".z-harness" / "config.toml"

    def _run_migrate(self, extra_env=None) -> subprocess.CompletedProcess:
        env = {
            "XDG_CONFIG_HOME": self.xdg,
            "Z_HARNESS_REPO_CONFIG": str(self._repo_cfg_path()),
        }
        if extra_env:
            env.update(extra_env)
        return run(["migrate"], env=env, cwd=self.repo)

    # -------------------------------------------------------------------------
    # Core rewrite: old names → new names
    # -------------------------------------------------------------------------

    def test_migrate_rewrites_codex_in_global(self):
        """migrate rewrites runtime='codex' → 'codex-cli' in global config."""
        write_global_config(
            self.xdg,
            '[roles.z_plan.consultant_primary]\nruntime = "codex"\n',
        )
        r = self._run_migrate()
        self.assertEqual(r.returncode, 0, f"stderr={r.stderr!r}")
        content = self._global_cfg_path().read_text()
        self.assertIn("codex-cli", content)
        self.assertNotIn('runtime = "codex"', content)

    def test_migrate_rewrites_gemini_in_global(self):
        """migrate rewrites runtime='gemini' → 'gemini-cli' in global config."""
        write_global_config(
            self.xdg,
            '[roles.z_plan.consultant_primary]\nruntime = "gemini"\n',
        )
        r = self._run_migrate()
        self.assertEqual(r.returncode, 0, f"stderr={r.stderr!r}")
        content = self._global_cfg_path().read_text()
        self.assertIn("gemini-cli", content)
        self.assertNotIn('runtime = "gemini"', content)

    def test_migrate_rewrites_claude_in_global(self):
        """migrate rewrites runtime='claude' → 'claude-cli' in global config."""
        write_global_config(
            self.xdg,
            '[roles.z_plan.consultant_primary]\nruntime = "claude"\n',
        )
        r = self._run_migrate()
        self.assertEqual(r.returncode, 0, f"stderr={r.stderr!r}")
        content = self._global_cfg_path().read_text()
        self.assertIn("claude-cli", content)
        self.assertNotIn('runtime = "claude"', content)

    def test_migrate_rewrites_old_names_in_project(self):
        """migrate rewrites old runtime names in project (.z-harness) config."""
        write_repo_config(
            self.repo,
            '[roles.z_plan.reviewer]\nruntime = "codex"\n',
        )
        r = self._run_migrate()
        self.assertEqual(r.returncode, 0, f"stderr={r.stderr!r}")
        content = self._repo_cfg_path().read_text()
        self.assertIn("codex-cli", content)
        self.assertNotIn('runtime = "codex"', content)

    def test_migrate_rewrites_both_layers_simultaneously(self):
        """migrate rewrites old names in both global and project configs in one run."""
        write_global_config(
            self.xdg,
            '[roles.z_plan.consultant_primary]\nruntime = "codex"\n',
        )
        write_repo_config(
            self.repo,
            '[roles.z_review.reviewer]\nruntime = "gemini"\n',
        )
        r = self._run_migrate()
        self.assertEqual(r.returncode, 0, f"stderr={r.stderr!r}")
        global_content = self._global_cfg_path().read_text()
        repo_content = self._repo_cfg_path().read_text()
        self.assertIn("codex-cli", global_content)
        self.assertIn("gemini-cli", repo_content)

    def test_migrate_mixed_old_and_new_rewrites_only_old(self):
        """migrate rewrites old names but leaves already-migrated names untouched."""
        write_global_config(
            self.xdg,
            '[roles.z_plan.consultant_primary]\nruntime = "codex"\n'
            '[roles.z_plan.consultant_secondary]\nruntime = "gemini-cli"\n',
        )
        r = self._run_migrate()
        self.assertEqual(r.returncode, 0, f"stderr={r.stderr!r}")
        content = self._global_cfg_path().read_text()
        # Old name rewritten
        self.assertIn("codex-cli", content)
        self.assertNotIn('runtime = "codex"', content)
        # Already-new name unchanged
        self.assertIn("gemini-cli", content)

    # -------------------------------------------------------------------------
    # Idempotency
    # -------------------------------------------------------------------------

    def test_migrate_idempotent_second_run_no_diff(self):
        """Running migrate twice produces byte-identical file on second run."""
        write_global_config(
            self.xdg,
            '[roles.z_plan.consultant_primary]\nruntime = "codex"\n',
        )
        r1 = self._run_migrate()
        self.assertEqual(r1.returncode, 0, f"first run stderr={r1.stderr!r}")
        bytes_after_first = self._global_cfg_path().read_bytes()

        r2 = self._run_migrate()
        self.assertEqual(r2.returncode, 0, f"second run stderr={r2.stderr!r}")
        bytes_after_second = self._global_cfg_path().read_bytes()

        self.assertEqual(
            bytes_after_first, bytes_after_second,
            "File changed on second migrate run (not idempotent)"
        )

    def test_migrate_already_migrated_exit_0(self):
        """migrate on an already-migrated config exits 0 (no-op is not an error)."""
        write_global_config(
            self.xdg,
            '[roles.z_plan.consultant_primary]\nruntime = "codex-cli"\n',
        )
        r = self._run_migrate()
        self.assertEqual(r.returncode, 0, f"stderr={r.stderr!r}")

    # -------------------------------------------------------------------------
    # No-op and missing layers
    # -------------------------------------------------------------------------

    def test_migrate_no_roles_section_exit_0(self):
        """migrate with no roles section in config exits 0 (no-op)."""
        write_global_config(
            self.xdg,
            '[notify]\nlevel = "off"\n',
        )
        r = self._run_migrate()
        self.assertEqual(r.returncode, 0, f"stderr={r.stderr!r}")

    def test_migrate_missing_both_layers_exit_0(self):
        """migrate with neither global nor project config exits 0 (skip both)."""
        # Neither layer exists
        r = self._run_migrate()
        self.assertEqual(r.returncode, 0, f"stderr={r.stderr!r}")

    def test_migrate_missing_global_only_rewrites_project(self):
        """migrate with only project config (no global) rewrites project successfully."""
        write_repo_config(
            self.repo,
            '[roles.z_plan.reviewer]\nruntime = "claude"\n',
        )
        r = self._run_migrate()
        self.assertEqual(r.returncode, 0, f"stderr={r.stderr!r}")
        content = self._repo_cfg_path().read_text()
        self.assertIn("claude-cli", content)

    # -------------------------------------------------------------------------
    # Invariant: non-runtime fields and other config keys are preserved
    # -------------------------------------------------------------------------

    def test_migrate_preserves_non_runtime_role_fields(self):
        """migrate does not alter persona or model fields in role tables."""
        write_global_config(
            self.xdg,
            '[roles.z_plan.consultant_primary]\npersona = "my-persona"\nmodel = "opus"\nruntime = "codex"\n',
        )
        r = self._run_migrate()
        self.assertEqual(r.returncode, 0, f"stderr={r.stderr!r}")
        content = self._global_cfg_path().read_text()
        self.assertIn("my-persona", content)
        self.assertIn("opus", content)
        self.assertIn("codex-cli", content)

    def test_migrate_preserves_non_roles_config_sections(self):
        """migrate does not alter notify.level or other 2-level config keys."""
        write_global_config(
            self.xdg,
            '[notify]\nlevel = "off"\n[roles.z_plan.consultant_primary]\nruntime = "codex"\n',
        )
        r = self._run_migrate()
        self.assertEqual(r.returncode, 0, f"stderr={r.stderr!r}")
        # Re-read and verify notify.level still resolves correctly (use isolation cwd, no repo config)
        env = {"XDG_CONFIG_HOME": self.xdg}
        r_get = run(["get", "notify.level"], env=env, cwd=self.cwd)
        self.assertEqual(r_get.returncode, 0, f"get stderr={r_get.stderr!r}")
        self.assertEqual(r_get.stdout.strip(), "off")


# ---------------------------------------------------------------------------
# TestTomlkitPreservesComments
# ---------------------------------------------------------------------------

class TestTomlkitPreservesComments(unittest.TestCase):
    """
    Verify that cmd_set (via _toml_write_key_preserving) preserves leading
    comments in an existing TOML config file when tomlkit is available.

    If tomlkit is not installed the test is skipped — the fallback path
    explicitly strips comments, so the invariant only applies when tomlkit
    is present.
    """

    def setUp(self):
        self.xdg = make_xdg()
        self.cwd = make_isolation_dir()

    def tearDown(self):
        shutil.rmtree(self.xdg, ignore_errors=True)
        shutil.rmtree(self.cwd, ignore_errors=True)

    def _tomlkit_available(self) -> bool:
        try:
            import importlib
            importlib.import_module("tomlkit")
            return True
        except ImportError:
            return False

    def test_comment_preserved_after_set(self):
        """
        Write a config with a leading comment, call `config.py set`, and
        verify the comment survives the round-trip.
        """
        if not self._tomlkit_available():
            self.skipTest("tomlkit not installed — comment preservation unavailable")

        # Seed a global config with a user comment
        comment_line = "# user comment: do not delete"
        initial_content = (
            f"{comment_line}\n"
            '[notify]\n'
            'level = "approval_only"\n'
        )
        cfg_path = write_global_config(self.xdg, initial_content)

        env = {"XDG_CONFIG_HOME": self.xdg}
        r = run(["set", "notify.level", "off", "--scope=global"], env=env, cwd=self.cwd)
        self.assertEqual(r.returncode, 0, f"set failed: stderr={r.stderr!r}")

        content_after = Path(cfg_path).read_text()
        self.assertIn(
            comment_line,
            content_after,
            "Leading comment was stripped by cmd_set (tomlkit should preserve it)",
        )

        # Also verify the value was actually written
        r_get = run(["get", "notify.level"], env=env, cwd=self.cwd)
        self.assertEqual(r_get.returncode, 0, f"get failed: stderr={r_get.stderr!r}")
        self.assertEqual(r_get.stdout.strip(), "off")

    def test_comment_preserved_on_new_section(self):
        """
        Write a config with a comment in one section, then set a key in a
        different section. The original comment must survive.
        """
        if not self._tomlkit_available():
            self.skipTest("tomlkit not installed — comment preservation unavailable")

        comment_line = "# hand-edited: keep this"
        initial_content = (
            '[notify]\n'
            f'{comment_line}\n'
            'level = "all"\n'
        )
        cfg_path = write_global_config(self.xdg, initial_content)

        env = {"XDG_CONFIG_HOME": self.xdg}
        r = run(["set", "docs.always_apply", "never", "--scope=global"], env=env, cwd=self.cwd)
        self.assertEqual(r.returncode, 0, f"set failed: stderr={r.stderr!r}")

        content_after = Path(cfg_path).read_text()
        self.assertIn(
            comment_line,
            content_after,
            "Inline section comment was stripped when setting a key in another section",
        )

    def test_write_to_nonexistent_file_creates_valid_toml(self):
        """
        When the global config file does not yet exist, cmd_set must create it with
        valid TOML and no spurious content.  There are no existing comments to preserve,
        so the file must contain only the key written and its section header — not
        comment artefacts, blank lines from a ghost-document, or encoding errors.
        Failure class: if _toml_write_key_preserving creates a corrupt or non-parseable
        file when the target path does not yet exist, subsequent reads will error out.
        """
        # Ensure global config does NOT exist
        cfg_path = Path(self.xdg) / "z-harness" / "config.toml"
        self.assertFalse(cfg_path.exists(), "config.toml already exists before test")

        env = {"XDG_CONFIG_HOME": self.xdg}
        r = run(["set", "notify.level", "off", "--scope=global"], env=env, cwd=self.cwd)
        self.assertEqual(r.returncode, 0, f"set to non-existent file failed: stderr={r.stderr!r}")

        self.assertTrue(cfg_path.exists(), "config.toml was not created by cmd_set")
        content = cfg_path.read_text()

        # Must be parseable — use stdlib tomllib / tomli; fall back to config get round-trip
        try:
            import tomllib  # Python 3.11+
            parsed = tomllib.loads(content)
        except ImportError:
            try:
                import tomli as tomllib  # type: ignore
                parsed = tomllib.loads(content)
            except ImportError:
                # Fall back to subprocess get to verify round-trip
                r_get = run(["get", "notify.level"], env=env, cwd=self.cwd)
                self.assertEqual(r_get.returncode, 0, "get after set-to-new-file failed")
                self.assertEqual(r_get.stdout.strip(), "off")
                return

        self.assertEqual(
            parsed.get("notify", {}).get("level"), "off",
            f"Expected notify.level='off' in newly-created file; parsed={parsed!r}",
        )
        # No ghost comment artefacts — file should not have unexpected # lines
        lines = content.splitlines()
        comment_lines = [l for l in lines if l.strip().startswith("#")]
        self.assertEqual(
            comment_lines, [],
            f"Unexpected comment lines in newly-created file: {comment_lines!r}",
        )


# ---------------------------------------------------------------------------
# TestInspectAll — tests for the inspect-all subcommand (T002)
# ---------------------------------------------------------------------------

class TestInspectAll(unittest.TestCase):
    """
    ~6 tests covering the three sections of `config.py inspect-all [--json]`:
    1. Keys-in-DEFAULTS are present in JSON output with expected persistence_class.
    2. Registered question_ids are present in JSON output.
    3. Env-only knobs are present with persistence_class="env".
    4. JSON output is a valid object with the three top-level sections.
    5. Source layer is reported correctly when a global config is present.
    6. Env-only knob value is surfaced when the env var is set.
    """

    def setUp(self):
        self.xdg = make_xdg()
        self.cwd = make_isolation_dir()
        self.env = {"XDG_CONFIG_HOME": self.xdg}

    def tearDown(self):
        shutil.rmtree(self.xdg, ignore_errors=True)
        shutil.rmtree(self.cwd, ignore_errors=True)

    def _run_inspect(self, extra_env=None, extra_args=None):
        env = dict(self.env)
        if extra_env:
            env.update(extra_env)
        args = ["inspect-all", "--json"]
        if extra_args:
            args += extra_args
        return run(args, env=env, cwd=self.cwd)

    def test_json_output_is_valid_object_with_three_sections(self):
        """--json must emit a valid JSON object with toml_keys, question_ids, env_only_knobs."""
        r = self._run_inspect()
        self.assertEqual(r.returncode, 0, f"inspect-all exited {r.returncode}; stderr={r.stderr!r}")
        data = json.loads(r.stdout)
        self.assertIsInstance(data, dict)
        for section in ("toml_keys", "question_ids", "env_only_knobs"):
            self.assertIn(section, data, f"JSON output missing section {section!r}")

    def test_toml_keys_contains_all_defaults_keys(self):
        """
        Every key in DEFAULTS (excluding meta keys) must appear in toml_keys.
        Failure class: if a new default key is added to DEFAULTS without updating
        cmd_inspect_all, this test catches the omission.
        """
        from config import DEFAULTS, META_KEYS
        r = self._run_inspect()
        self.assertEqual(r.returncode, 0, f"stderr={r.stderr!r}")
        data = json.loads(r.stdout)
        toml_keys = data["toml_keys"]
        # Build expected key set from DEFAULTS (mirroring _flatten_defaults).
        # Handles up to 3-level nesting (e.g. watchdog.timeout_secs.bash).
        expected_keys = set()
        for section, sv in DEFAULTS.items():
            if section in META_KEYS:
                continue
            if isinstance(sv, dict):
                for k, v in sv.items():
                    if isinstance(v, dict):
                        # 3-level nesting: section.k.subk
                        for subk in v:
                            expected_keys.add(f"{section}.{k}.{subk}")
                    else:
                        expected_keys.add(f"{section}.{k}")
        for key in expected_keys:
            self.assertIn(key, toml_keys, f"DEFAULTS key {key!r} missing from inspect-all toml_keys")

    def test_toml_keys_default_persistence_class_is_default(self):
        """
        Keys resolved from the built-in defaults layer must have persistence_class='default'.
        Failure class: if persistence_class is wrong for the 'defaults' source, tooling
        consuming this output will misclassify which layer owns the value.
        """
        r = self._run_inspect()
        self.assertEqual(r.returncode, 0, f"stderr={r.stderr!r}")
        data = json.loads(r.stdout)
        for key, meta in data["toml_keys"].items():
            if meta["source"] == "default":
                self.assertEqual(
                    meta["persistence_class"], "default",
                    f"{key!r}: source=default but persistence_class={meta['persistence_class']!r}",
                )

    def test_registered_question_ids_are_in_output(self):
        """
        All keys registered in QUESTION_IDS must appear in the question_ids section.
        Failure class: if a question_id is registered but not surfaced, the inspect
        view is incomplete and skips routing-preference configuration.
        """
        from config import QUESTION_IDS
        r = self._run_inspect()
        self.assertEqual(r.returncode, 0, f"stderr={r.stderr!r}")
        data = json.loads(r.stdout)
        qid_keys = data["question_ids"]
        for qid in QUESTION_IDS:
            self.assertIn(qid, qid_keys, f"question_id {qid!r} missing from inspect-all output")

    def test_env_only_knobs_have_persistence_class_env(self):
        """
        All env-only knobs must appear in env_only_knobs with persistence_class='env'.
        Failure class: if persistence_class is wrong, consumers may attempt to write
        these knobs to TOML (they are not writable; they only live in the environment).
        """
        from config import ENV_ONLY_KNOBS
        r = self._run_inspect()
        self.assertEqual(r.returncode, 0, f"stderr={r.stderr!r}")
        data = json.loads(r.stdout)
        env_knobs = data["env_only_knobs"]
        for knob in ENV_ONLY_KNOBS:
            self.assertIn(knob, env_knobs, f"env-only knob {knob!r} missing from inspect-all output")
            self.assertEqual(
                env_knobs[knob]["persistence_class"], "env",
                f"{knob!r}: expected persistence_class='env', got {env_knobs[knob]['persistence_class']!r}",
            )

    def test_global_config_source_reflected_correctly(self):
        """
        When a key is overridden in the global config file, its source must be 'global'
        and persistence_class must be 'global'.
        Failure class: if the source layer is reported as 'default' despite a global
        override, inspect-all gives a misleading lineage to the user.
        """
        write_global_config(self.xdg, '[notify]\nlevel = "off"\n')
        r = self._run_inspect()
        self.assertEqual(r.returncode, 0, f"stderr={r.stderr!r}")
        data = json.loads(r.stdout)
        notify_meta = data["toml_keys"].get("notify.level")
        self.assertIsNotNone(notify_meta, "notify.level missing from toml_keys")
        self.assertEqual(notify_meta["value"], "off")
        self.assertEqual(notify_meta["source"], "global",
                         f"Expected source='global', got {notify_meta['source']!r}")
        self.assertEqual(notify_meta["persistence_class"], "global",
                         f"Expected persistence_class='global', got {notify_meta['persistence_class']!r}")

    def test_env_only_knob_value_surfaced_when_set(self):
        """
        When an env-only knob env var is set, its value must be surfaced in the output
        and source must be 'env'.
        Failure class: if the output always shows None/none regardless of environment,
        the inspect view cannot be used to verify whether a knob is active.
        """
        r = self._run_inspect(extra_env={"Z_HARNESS_NO_ASK": "halt"})
        self.assertEqual(r.returncode, 0, f"stderr={r.stderr!r}")
        data = json.loads(r.stdout)
        knob_meta = data["env_only_knobs"].get("Z_HARNESS_NO_ASK")
        self.assertIsNotNone(knob_meta, "Z_HARNESS_NO_ASK missing from env_only_knobs")
        self.assertEqual(knob_meta["value"], "halt",
                         f"Expected value='halt', got {knob_meta['value']!r}")
        self.assertEqual(knob_meta["source"], "env",
                         f"Expected source='env', got {knob_meta['source']!r}")

    def test_sources_list_reflects_toml_wins_over_env(self):
        """
        T001: TOML-wins gate — when TOML sets a key, an env var for that key must NOT
        win. sources[] must reflect the TOML layer as the winner, not the env var.
        Failure class: if sources[] shows env as winner over TOML, the TOML-wins gate
        is absent and consumers would observe env silently overriding config.toml.
        """
        # Set notify.level in global config
        write_global_config(self.xdg, '[notify]\nlevel = "all"\n')
        # Attempt to override via env var (Z_HARNESS_NOTIFY_LEVEL) — must be ignored
        r = self._run_inspect(extra_env={"Z_HARNESS_NOTIFY_LEVEL": "off"})
        self.assertEqual(r.returncode, 0, f"stderr={r.stderr!r}")
        data = json.loads(r.stdout)
        notify_meta = data["toml_keys"].get("notify.level")
        self.assertIsNotNone(notify_meta, "notify.level missing from toml_keys")
        # TOML must win: value must be "all" from global config, NOT "off" from env
        self.assertEqual(notify_meta["value"], "all",
                         "T001: TOML value 'all' must win over env var 'off' (TOML-wins gate)")
        # Source must NOT be env when TOML set the value
        self.assertNotEqual(notify_meta["source"], "env",
                            f"T001: source must not be 'env' when TOML set the value; "
                            f"got source={notify_meta['source']!r}")


# ---------------------------------------------------------------------------
# Tests for T002: [experiment] config section (persona_rotation + control_every_n)
# ---------------------------------------------------------------------------

class TestExperimentSection(unittest.TestCase):
    """
    Covers the new [experiment] TOML section added in T002:
    - experiment.persona_rotation defaults to true.
    - experiment.control_every_n defaults to 5.
    - Invalid values for persona_rotation exit 2 on repo/env layer.
    - Invalid values for control_every_n (0 or negative or non-int) exit 2 on env layer.
    - Valid env overrides (Z_HARNESS_EXPERIMENT_PERSONA_ROTATION / Z_HARNESS_EXPERIMENT_CONTROL_EVERY_N) take effect.
    - Existing keys are unaffected by the new section.
    """

    def setUp(self):
        self.xdg = make_xdg()
        self.cwd = make_isolation_dir()
        self.env = {"XDG_CONFIG_HOME": self.xdg}

    def tearDown(self):
        shutil.rmtree(self.xdg, ignore_errors=True)
        shutil.rmtree(self.cwd, ignore_errors=True)

    # -------------------------------------------------------------------------
    # Default values
    # -------------------------------------------------------------------------

    def test_persona_rotation_default_is_true(self):
        """experiment.persona_rotation default must be true."""
        r = run(["get", "experiment.persona_rotation"], env=self.env, cwd=self.cwd)
        self.assertEqual(r.returncode, 0, f"stderr={r.stderr!r}")
        self.assertEqual(r.stdout.strip(), "true")

    def test_control_every_n_default_is_5(self):
        """experiment.control_every_n default must be 5."""
        r = run(["get", "experiment.control_every_n"], env=self.env, cwd=self.cwd)
        self.assertEqual(r.returncode, 0, f"stderr={r.stderr!r}")
        self.assertEqual(r.stdout.strip(), "5")

    # -------------------------------------------------------------------------
    # Valid env overrides
    # -------------------------------------------------------------------------

    def test_env_persona_rotation_false(self):
        """Z_HARNESS_EXPERIMENT_PERSONA_ROTATION=false overrides default true."""
        env = dict(self.env)
        env["Z_HARNESS_EXPERIMENT_PERSONA_ROTATION"] = "false"
        r = run(["get", "experiment.persona_rotation"], env=env, cwd=self.cwd)
        self.assertEqual(r.returncode, 0, f"stderr={r.stderr!r}")
        self.assertEqual(r.stdout.strip(), "false")

    def test_env_persona_rotation_true_explicit(self):
        """Z_HARNESS_EXPERIMENT_PERSONA_ROTATION=true keeps value as true."""
        env = dict(self.env)
        env["Z_HARNESS_EXPERIMENT_PERSONA_ROTATION"] = "true"
        r = run(["get", "experiment.persona_rotation"], env=env, cwd=self.cwd)
        self.assertEqual(r.returncode, 0, f"stderr={r.stderr!r}")
        self.assertEqual(r.stdout.strip(), "true")

    def test_env_control_every_n_override(self):
        """Z_HARNESS_EXPERIMENT_CONTROL_EVERY_N=10 overrides default 5."""
        env = dict(self.env)
        env["Z_HARNESS_EXPERIMENT_CONTROL_EVERY_N"] = "10"
        r = run(["get", "experiment.control_every_n"], env=env, cwd=self.cwd)
        self.assertEqual(r.returncode, 0, f"stderr={r.stderr!r}")
        self.assertEqual(r.stdout.strip(), "10")

    # -------------------------------------------------------------------------
    # Invalid env values exit 2 (repo/env layer hard-fail)
    # -------------------------------------------------------------------------

    def test_invalid_persona_rotation_env_exits_2(self):
        """Invalid Z_HARNESS_EXPERIMENT_PERSONA_ROTATION value must exit 2."""
        env = dict(self.env)
        env["Z_HARNESS_EXPERIMENT_PERSONA_ROTATION"] = "maybe"
        r = run(["get", "experiment.persona_rotation"], env=env, cwd=self.cwd)
        self.assertEqual(r.returncode, 2,
                         f"Expected exit 2 for invalid value; stderr={r.stderr!r}")

    def test_invalid_control_every_n_zero_exits_2(self):
        """Z_HARNESS_EXPERIMENT_CONTROL_EVERY_N=0 is not a positive int; must exit 2."""
        env = dict(self.env)
        env["Z_HARNESS_EXPERIMENT_CONTROL_EVERY_N"] = "0"
        r = run(["get", "experiment.control_every_n"], env=env, cwd=self.cwd)
        self.assertEqual(r.returncode, 2,
                         f"Expected exit 2 for 0; stderr={r.stderr!r}")

    def test_invalid_control_every_n_negative_exits_2(self):
        """Z_HARNESS_EXPERIMENT_CONTROL_EVERY_N=-1 is not a positive int; must exit 2."""
        env = dict(self.env)
        env["Z_HARNESS_EXPERIMENT_CONTROL_EVERY_N"] = "-1"
        r = run(["get", "experiment.control_every_n"], env=env, cwd=self.cwd)
        self.assertEqual(r.returncode, 2,
                         f"Expected exit 2 for -1; stderr={r.stderr!r}")

    def test_invalid_control_every_n_string_exits_2(self):
        """Z_HARNESS_EXPERIMENT_CONTROL_EVERY_N=abc must exit 2."""
        env = dict(self.env)
        env["Z_HARNESS_EXPERIMENT_CONTROL_EVERY_N"] = "abc"
        r = run(["get", "experiment.control_every_n"], env=env, cwd=self.cwd)
        self.assertEqual(r.returncode, 2,
                         f"Expected exit 2 for non-integer string; stderr={r.stderr!r}")

    # -------------------------------------------------------------------------
    # Invalid repo-layer values exit 2
    # -------------------------------------------------------------------------

    def test_invalid_persona_rotation_in_repo_config_exits_2(self):
        """Invalid experiment.persona_rotation in repo config must exit 2."""
        repo = tempfile.mkdtemp(prefix="z-harness-test-repo-")
        try:
            repo_cfg = write_repo_config(repo, '[experiment]\npersona_rotation = "maybe"\n')
            env = dict(self.env)
            env["Z_HARNESS_REPO_CONFIG"] = repo_cfg
            r = run(["get", "experiment.persona_rotation"], env=env, cwd=self.cwd)
            self.assertEqual(r.returncode, 2,
                             f"Expected exit 2 for repo-layer invalid value; stderr={r.stderr!r}")
        finally:
            shutil.rmtree(repo, ignore_errors=True)

    def test_invalid_control_every_n_zero_in_repo_config_exits_2(self):
        """experiment.control_every_n = 0 in repo config must exit 2 (not a positive int)."""
        repo = tempfile.mkdtemp(prefix="z-harness-test-repo-")
        try:
            repo_cfg = write_repo_config(repo, "[experiment]\ncontrol_every_n = 0\n")
            env = dict(self.env)
            env["Z_HARNESS_REPO_CONFIG"] = repo_cfg
            r = run(["get", "experiment.control_every_n"], env=env, cwd=self.cwd)
            self.assertEqual(r.returncode, 2,
                             f"Expected exit 2 for repo-layer control_every_n=0; stderr={r.stderr!r}")
        finally:
            shutil.rmtree(repo, ignore_errors=True)

    # -------------------------------------------------------------------------
    # Existing keys are unaffected
    # -------------------------------------------------------------------------

    def test_existing_notify_level_unaffected(self):
        """Adding [experiment] keys must not disturb notify.level resolution."""
        r = run(["get", "notify.level"], env=self.env, cwd=self.cwd)
        self.assertEqual(r.returncode, 0)
        self.assertEqual(r.stdout.strip(), "approval_only")

    def test_existing_axioms_enabled_unaffected(self):
        """Adding [experiment] keys must not disturb axioms.enabled resolution."""
        r = run(["get", "axioms.enabled"], env=self.env, cwd=self.cwd)
        self.assertEqual(r.returncode, 0)
        self.assertEqual(r.stdout.strip(), "true")


# ---------------------------------------------------------------------------
# Tests for T003: [personas] section knobs
# ---------------------------------------------------------------------------

class TestPersonasSection(unittest.TestCase):
    """
    Verify the [personas] DEFAULTS section:
      - critique_panel, audit, review_eval default True
      - personas.consult_eval defaults False (off)
      - personas.implementer_retry defaults "same"
      - env-export emits Z_HARNESS_PERSONAS_* names
      - bad implementer_retry value (e.g. "maybe") is rejected with exit 2
      - env override for implementer_retry (Z_HARNESS_PERSONAS_IMPLEMENTER_RETRY=new) works
    """

    def setUp(self):
        self.xdg = make_xdg()
        self.cwd = make_isolation_dir()
        self.env = {"XDG_CONFIG_HOME": self.xdg}

    def tearDown(self):
        shutil.rmtree(self.xdg, ignore_errors=True)
        shutil.rmtree(self.cwd, ignore_errors=True)

    # -------------------------------------------------------------------------
    # Default values
    # -------------------------------------------------------------------------

    def test_consult_eval_default_is_false(self):
        """personas.consult_eval must default to false (off by default)."""
        r = run(["get", "personas.consult_eval"], env=self.env, cwd=self.cwd)
        self.assertEqual(r.returncode, 0, f"stderr={r.stderr!r}")
        self.assertEqual(r.stdout.strip(), "false")

    def test_implementer_retry_default_is_same(self):
        """personas.implementer_retry must default to 'same'."""
        r = run(["get", "personas.implementer_retry"], env=self.env, cwd=self.cwd)
        self.assertEqual(r.returncode, 0, f"stderr={r.stderr!r}")
        self.assertEqual(r.stdout.strip(), "same")

    def test_critique_panel_default_is_true(self):
        """personas.critique_panel must default to true."""
        r = run(["get", "personas.critique_panel"], env=self.env, cwd=self.cwd)
        self.assertEqual(r.returncode, 0, f"stderr={r.stderr!r}")
        self.assertEqual(r.stdout.strip(), "true")

    def test_audit_default_is_true(self):
        """personas.audit must default to true."""
        r = run(["get", "personas.audit"], env=self.env, cwd=self.cwd)
        self.assertEqual(r.returncode, 0, f"stderr={r.stderr!r}")
        self.assertEqual(r.stdout.strip(), "true")

    def test_review_eval_default_is_true(self):
        """personas.review_eval must default to true."""
        r = run(["get", "personas.review_eval"], env=self.env, cwd=self.cwd)
        self.assertEqual(r.returncode, 0, f"stderr={r.stderr!r}")
        self.assertEqual(r.stdout.strip(), "true")

    # -------------------------------------------------------------------------
    # Enum validation: implementer_retry rejects bad values
    # -------------------------------------------------------------------------

    def test_bad_implementer_retry_env_exits_2(self):
        """Z_HARNESS_PERSONAS_IMPLEMENTER_RETRY=maybe must be rejected with exit 2."""
        env = dict(self.env)
        env["Z_HARNESS_PERSONAS_IMPLEMENTER_RETRY"] = "maybe"
        r = run(["get", "personas.implementer_retry"], env=env, cwd=self.cwd)
        self.assertEqual(r.returncode, 2,
                         f"Expected exit 2 for invalid implementer_retry; stderr={r.stderr!r}")

    def test_bad_implementer_retry_repo_exits_2(self):
        """personas.implementer_retry = 'always' in repo config must exit 2."""
        repo = tempfile.mkdtemp(prefix="z-harness-test-repo-")
        try:
            repo_cfg = write_repo_config(repo, '[personas]\nimplementer_retry = "always"\n')
            env = dict(self.env)
            env["Z_HARNESS_REPO_CONFIG"] = repo_cfg
            r = run(["get", "personas.implementer_retry"], env=env, cwd=self.cwd)
            self.assertEqual(r.returncode, 2,
                             f"Expected exit 2 for repo-layer bad implementer_retry; stderr={r.stderr!r}")
        finally:
            shutil.rmtree(repo, ignore_errors=True)

    def test_implementer_retry_new_accepted(self):
        """Z_HARNESS_PERSONAS_IMPLEMENTER_RETRY=new must be accepted and returned."""
        env = dict(self.env)
        env["Z_HARNESS_PERSONAS_IMPLEMENTER_RETRY"] = "new"
        r = run(["get", "personas.implementer_retry"], env=env, cwd=self.cwd)
        self.assertEqual(r.returncode, 0, f"stderr={r.stderr!r}")
        self.assertEqual(r.stdout.strip(), "new")

    def test_implementer_retry_same_accepted(self):
        """Z_HARNESS_PERSONAS_IMPLEMENTER_RETRY=same must be accepted and returned."""
        env = dict(self.env)
        env["Z_HARNESS_PERSONAS_IMPLEMENTER_RETRY"] = "same"
        r = run(["get", "personas.implementer_retry"], env=env, cwd=self.cwd)
        self.assertEqual(r.returncode, 0, f"stderr={r.stderr!r}")
        self.assertEqual(r.stdout.strip(), "same")

    # -------------------------------------------------------------------------
    # Env-var name translation (export-env)
    # -------------------------------------------------------------------------

    def test_export_env_emits_personas_consult_eval(self):
        """export-env must emit Z_HARNESS_PERSONAS_CONSULT_EVAL."""
        r = run(["export-env"], env=self.env, cwd=self.cwd)
        self.assertEqual(r.returncode, 0)
        self.assertIn("Z_HARNESS_PERSONAS_CONSULT_EVAL", r.stdout)

    def test_export_env_emits_personas_implementer_retry(self):
        """export-env must emit Z_HARNESS_PERSONAS_IMPLEMENTER_RETRY."""
        r = run(["export-env"], env=self.env, cwd=self.cwd)
        self.assertEqual(r.returncode, 0)
        self.assertIn("Z_HARNESS_PERSONAS_IMPLEMENTER_RETRY", r.stdout)

    def test_export_env_consult_eval_default_value_is_false(self):
        """export-env line for Z_HARNESS_PERSONAS_CONSULT_EVAL must carry value 'false'."""
        r = run(["export-env"], env=self.env, cwd=self.cwd)
        self.assertEqual(r.returncode, 0)
        for line in r.stdout.splitlines():
            if "Z_HARNESS_PERSONAS_CONSULT_EVAL" in line:
                self.assertIn("false", line,
                              f"Expected 'false' in export line; got: {line!r}")
                break
        else:
            self.fail("Z_HARNESS_PERSONAS_CONSULT_EVAL not found in export-env output")

    def test_export_env_implementer_retry_default_value_is_same(self):
        """export-env line for Z_HARNESS_PERSONAS_IMPLEMENTER_RETRY must carry value 'same'."""
        r = run(["export-env"], env=self.env, cwd=self.cwd)
        self.assertEqual(r.returncode, 0)
        for line in r.stdout.splitlines():
            if "Z_HARNESS_PERSONAS_IMPLEMENTER_RETRY" in line:
                self.assertIn("same", line,
                              f"Expected 'same' in export line; got: {line!r}")
                break
        else:
            self.fail("Z_HARNESS_PERSONAS_IMPLEMENTER_RETRY not found in export-env output")

    # -------------------------------------------------------------------------
    # Bool env override coercion
    # -------------------------------------------------------------------------

    def test_env_override_consult_eval_true(self):
        """Z_HARNESS_PERSONAS_CONSULT_EVAL=true must coerce to bool true and be returned."""
        env = dict(self.env)
        env["Z_HARNESS_PERSONAS_CONSULT_EVAL"] = "true"
        r = run(["get", "personas.consult_eval"], env=env, cwd=self.cwd)
        self.assertEqual(r.returncode, 0, f"stderr={r.stderr!r}")
        self.assertEqual(r.stdout.strip(), "true")

    # -------------------------------------------------------------------------
    # brainstorm.personas is unaffected
    # -------------------------------------------------------------------------

    def test_brainstorm_personas_unaffected(self):
        """brainstorm.personas must still default to true (not moved to [personas])."""
        r = run(["get", "brainstorm.personas"], env=self.env, cwd=self.cwd)
        self.assertEqual(r.returncode, 0, f"stderr={r.stderr!r}")
        self.assertEqual(r.stdout.strip(), "true")


# ---------------------------------------------------------------------------
# Tests for T002: export-env egress — cosmetic unset + deprecation events
# ---------------------------------------------------------------------------

class TestExportEnvEgress(unittest.TestCase):
    """
    T002: export-env emits `export VAR=value` for all resolved knobs, plus
    `unset OLD_VAR` (before the export) for any preference env var the user set
    in the raw env whose dotted key is NOT allowlisted.  Allowlisted vars (e.g.
    Z_HARNESS_PLAN_DIR) are never unset.

    The unset is COSMETIC single-shell cleanup only — correctness across Bash
    tool calls comes from T004's config.py get conversion, not this unset.
    """

    def setUp(self):
        self.xdg = make_xdg()
        self.cwd = make_isolation_dir()
        self.env = {"XDG_CONFIG_HOME": self.xdg}

    def tearDown(self):
        shutil.rmtree(self.xdg, ignore_errors=True)
        shutil.rmtree(self.cwd, ignore_errors=True)

    # -------------------------------------------------------------------------
    # (a) export-env emits `export ` lines for resolved knobs
    # -------------------------------------------------------------------------

    def test_export_env_emits_export_lines(self):
        """export-env must emit `export VAR=value` lines for all user knobs."""
        r = run(["export-env"], env=self.env, cwd=self.cwd)
        self.assertEqual(r.returncode, 0, f"stderr={r.stderr!r}")
        export_lines = [l for l in r.stdout.splitlines() if l.startswith("export ")]
        self.assertGreater(len(export_lines), 0, "No export lines emitted")

    def test_export_env_emits_notify_level(self):
        """export-env must include Z_HARNESS_NOTIFY_LEVEL with its resolved value."""
        r = run(["export-env"], env=self.env, cwd=self.cwd)
        self.assertEqual(r.returncode, 0)
        self.assertIn("Z_HARNESS_NOTIFY_LEVEL", r.stdout)
        # Default value is approval_only
        self.assertIn("approval_only", r.stdout)

    def test_export_env_emits_consult_alias(self):
        """runtime.consult must be exported as Z_HARNESS_CONSULT (alias, not transliteration)."""
        r = run(["export-env"], env=self.env, cwd=self.cwd)
        self.assertEqual(r.returncode, 0)
        self.assertIn("Z_HARNESS_CONSULT", r.stdout)
        # Must not export the mechanical transliteration for an aliased key
        self.assertNotIn("Z_HARNESS_RUNTIME_CONSULT", r.stdout)

    def test_export_env_does_not_emit_meta_keys(self):
        """export-env must not emit Z_HARNESS_SCHEMA_VERSION."""
        r = run(["export-env"], env=self.env, cwd=self.cwd)
        self.assertEqual(r.returncode, 0)
        self.assertNotIn("Z_HARNESS_SCHEMA_VERSION", r.stdout)

    def test_export_env_exit_zero(self):
        """export-env must exit 0 under normal conditions."""
        r = run(["export-env"], env=self.env, cwd=self.cwd)
        self.assertEqual(r.returncode, 0)

    # -------------------------------------------------------------------------
    # (b) User-set preference env var produces a preceding `unset ` line
    # -------------------------------------------------------------------------

    def test_user_set_preference_var_produces_unset_before_export(self):
        """When user sets Z_HARNESS_NOTIFY_LEVEL, export-env must emit `unset Z_HARNESS_NOTIFY_LEVEL` before the export line."""
        env = dict(self.env)
        env["Z_HARNESS_NOTIFY_LEVEL"] = "off"
        r = run(["export-env"], env=env, cwd=self.cwd)
        self.assertEqual(r.returncode, 0, f"stderr={r.stderr!r}")
        lines = r.stdout.splitlines()
        # Find unset and export indices
        unset_idx = None
        export_idx = None
        for i, line in enumerate(lines):
            if line.strip() == "unset Z_HARNESS_NOTIFY_LEVEL":
                unset_idx = i
            if line.startswith("export Z_HARNESS_NOTIFY_LEVEL="):
                export_idx = i
        self.assertIsNotNone(unset_idx, "Expected `unset Z_HARNESS_NOTIFY_LEVEL` line not found")
        self.assertIsNotNone(export_idx, "Expected `export Z_HARNESS_NOTIFY_LEVEL=...` line not found")
        self.assertLess(unset_idx, export_idx,
                        f"unset (line {unset_idx}) must appear before export (line {export_idx})")

    def test_user_set_preference_var_unset_line_format(self):
        """unset line must be exactly `unset VAR` with no quotes or extra text."""
        env = dict(self.env)
        env["Z_HARNESS_NOTIFY_LEVEL"] = "off"
        r = run(["export-env"], env=env, cwd=self.cwd)
        self.assertEqual(r.returncode, 0)
        unset_lines = [l for l in r.stdout.splitlines() if l.startswith("unset ")]
        self.assertGreater(len(unset_lines), 0, "No unset lines emitted")
        # Verify the format: "unset Z_HARNESS_NOTIFY_LEVEL" (no trailing = or quotes)
        for line in unset_lines:
            self.assertRegex(line, r'^unset [A-Z_][A-Z0-9_]*$',
                             f"unset line has unexpected format: {line!r}")

    def test_legacy_alias_var_produces_unset(self):
        """When user sets Z_HARNESS_PRE_REVIEW (legacy alias for runtime.pre_review), export-env must unset it."""
        env = dict(self.env)
        env["Z_HARNESS_PRE_REVIEW"] = "true"
        r = run(["export-env"], env=env, cwd=self.cwd)
        self.assertEqual(r.returncode, 0, f"stderr={r.stderr!r}")
        self.assertIn("unset Z_HARNESS_PRE_REVIEW", r.stdout,
                      "Expected `unset Z_HARNESS_PRE_REVIEW` for legacy alias")

    def test_unset_precedes_export_for_legacy_alias(self):
        """unset must appear before the export line for the same key (legacy alias case)."""
        env = dict(self.env)
        env["Z_HARNESS_PRE_REVIEW"] = "true"
        r = run(["export-env"], env=env, cwd=self.cwd)
        self.assertEqual(r.returncode, 0)
        lines = r.stdout.splitlines()
        unset_idx = next((i for i, l in enumerate(lines) if l.strip() == "unset Z_HARNESS_PRE_REVIEW"), None)
        # The export name for runtime.pre_review is Z_HARNESS_PRE_REVIEW (from _ENV_VAR_ALIASES)
        export_idx = next((i for i, l in enumerate(lines) if l.startswith("export Z_HARNESS_PRE_REVIEW=")), None)
        self.assertIsNotNone(unset_idx, "unset Z_HARNESS_PRE_REVIEW not found")
        self.assertIsNotNone(export_idx, "export Z_HARNESS_PRE_REVIEW= not found")
        self.assertLess(unset_idx, export_idx, "unset must precede export for legacy alias")

    def test_no_user_pref_env_no_unset_lines(self):
        """When no preference env vars are set, export-env must not emit any unset lines."""
        r = run(["export-env"], env=self.env, cwd=self.cwd)
        self.assertEqual(r.returncode, 0)
        unset_lines = [l for l in r.stdout.splitlines() if l.startswith("unset ")]
        self.assertEqual(unset_lines, [],
                         f"Expected no unset lines when no preference vars are set; got: {unset_lines}")

    # -------------------------------------------------------------------------
    # (c) Allowlisted var (e.g. Z_HARNESS_PLAN_DIR) set in env is NEVER unset
    # -------------------------------------------------------------------------

    def test_allowlisted_var_plan_dir_never_unset(self):
        """Z_HARNESS_PLAN_DIR is allowlisted and must NEVER appear in an unset line."""
        env = dict(self.env)
        env["Z_HARNESS_PLAN_DIR"] = "/tmp/some-plan-dir"
        r = run(["export-env"], env=env, cwd=self.cwd)
        self.assertEqual(r.returncode, 0, f"stderr={r.stderr!r}")
        unset_lines = [l for l in r.stdout.splitlines() if l.startswith("unset ")]
        for line in unset_lines:
            self.assertNotIn("Z_HARNESS_PLAN_DIR", line,
                             f"Z_HARNESS_PLAN_DIR must never be unset; found: {line!r}")

    def test_allowlisted_var_slug_never_unset(self):
        """Z_HARNESS_SLUG is allowlisted (plumbing) and must never appear in an unset line."""
        env = dict(self.env)
        env["Z_HARNESS_SLUG"] = "my-slug"
        r = run(["export-env"], env=env, cwd=self.cwd)
        self.assertEqual(r.returncode, 0)
        unset_lines = [l for l in r.stdout.splitlines() if l.startswith("unset ")]
        for line in unset_lines:
            self.assertNotIn("Z_HARNESS_SLUG", line,
                             f"Z_HARNESS_SLUG must never be unset; found: {line!r}")

    def test_allowlisted_prefix_claim_never_unset(self):
        """Z_HARNESS_CLAIM_* vars match LEGAL_ENV_PREFIXES and must never be unset."""
        env = dict(self.env)
        env["Z_HARNESS_CLAIM_TTL_SECS"] = "300"
        r = run(["export-env"], env=env, cwd=self.cwd)
        self.assertEqual(r.returncode, 0)
        unset_lines = [l for l in r.stdout.splitlines() if l.startswith("unset ")]
        for line in unset_lines:
            self.assertNotIn("Z_HARNESS_CLAIM_", line,
                             f"Z_HARNESS_CLAIM_* must never be unset; found: {line!r}")

    def test_allowlisted_no_ask_never_unset(self):
        """Z_HARNESS_NO_ASK is allowlisted (unattended) and must never be unset."""
        env = dict(self.env)
        env["Z_HARNESS_NO_ASK"] = "halt"
        r = run(["export-env"], env=env, cwd=self.cwd)
        self.assertEqual(r.returncode, 0)
        unset_lines = [l for l in r.stdout.splitlines() if l.startswith("unset ")]
        for line in unset_lines:
            self.assertNotIn("Z_HARNESS_NO_ASK", line,
                             f"Z_HARNESS_NO_ASK must never be unset; found: {line!r}")


# ---------------------------------------------------------------------------
# T006: [models] section tests
# ---------------------------------------------------------------------------

class TestModelsSection(unittest.TestCase):
    """[models] role overrides plus local model routing schema."""

    # All expected role keys in the [models] section.
    _EXPECTED_ROLES = (
        "consultant_primary",
        "consultant_secondary",
        "reviewer",
        "implementer",
        "pre_reviewer",
    )
    _EXPECTED_MODEL_CLASS_KEYS = (
        "model_classes.cheap.model",
        "model_classes.cheap.thinking",
        "model_classes.cheap.reasoning",
        "model_classes.standard.model",
        "model_classes.standard.thinking",
        "model_classes.standard.reasoning",
        "model_classes.deep.model",
        "model_classes.deep.thinking",
        "model_classes.deep.reasoning",
    )

    _EXPECTED_MODEL_ROUTING_DEFAULTS = {
        "model_routing.native_agents.default": "",
        "model_routing.implementer.low": "sonnet",
        "model_routing.implementer.medium": "sonnet",
        "model_routing.implementer.high": "opus",
        "model_routing.implementer.retry": "opus",
    }


    def setUp(self):
        self.xdg = make_xdg()
        self.cwd = make_isolation_dir()
        self.env = {"XDG_CONFIG_HOME": self.xdg}

    def tearDown(self):
        shutil.rmtree(self.xdg, ignore_errors=True)
        shutil.rmtree(self.cwd, ignore_errors=True)

    # (a) Completeness: all role keys present in DEFAULTS and VALIDATORS
    def test_all_role_keys_present_in_defaults(self):
        """All models.* role keys must be present in DEFAULTS['models']."""
        from config import DEFAULTS
        models_defaults = DEFAULTS.get("models", {})
        for role in self._EXPECTED_ROLES:
            self.assertIn(
                role, models_defaults,
                f"DEFAULTS['models'] is missing role key {role!r}",
            )

    def test_all_role_keys_present_in_validators(self):
        """All models.* role keys must be present in VALIDATORS."""
        from config import VALIDATORS
        for role in self._EXPECTED_ROLES:
            dotted = f"models.{role}"
            self.assertIn(
                dotted, VALIDATORS,
                f"VALIDATORS is missing key {dotted!r}",
            )

    def test_default_model_class_keys_present_in_defaults_and_validators(self):
        """Built-in model classes must be readable 3-level config leaves."""
        from config import DEFAULTS, VALIDATORS
        flat_defaults = {
            f"model_classes.{class_name}.{field}": value
            for class_name, fields in DEFAULTS.get("model_classes", {}).items()
            for field, value in fields.items()
        }
        for dotted in self._EXPECTED_MODEL_CLASS_KEYS:
            self.assertIn(dotted, flat_defaults)
            self.assertIn(dotted, VALIDATORS)

    def test_model_routing_defaults_present_in_defaults_and_validators(self):
        """Model routing defaults must reproduce current implementer labels."""
        from config import DEFAULTS, VALIDATORS
        flat_defaults = {
            f"model_routing.{group}.{field}": value
            for group, fields in DEFAULTS.get("model_routing", {}).items()
            for field, value in fields.items()
        }
        for dotted, expected in self._EXPECTED_MODEL_ROUTING_DEFAULTS.items():
            self.assertEqual(flat_defaults.get(dotted), expected)
            self.assertIn(dotted, VALIDATORS)


    # (b) Validator accepts any string (including empty and arbitrary strings)
    def test_validator_accepts_empty_string(self):
        """models.* validator must accept the empty string sentinel."""
        from config import VALIDATORS
        for role in self._EXPECTED_ROLES:
            dotted = f"models.{role}"
            validator = VALIDATORS[dotted]
            self.assertTrue(
                callable(validator),
                f"VALIDATORS[{dotted!r}] should be callable, got {validator!r}",
            )
            self.assertTrue(
                validator(""),
                f"VALIDATORS[{dotted!r}]('') must return True (empty string sentinel)",
            )

    def test_validator_accepts_arbitrary_model_string(self):
        """models.* validator must accept any non-empty model string."""
        from config import VALIDATORS
        for role in self._EXPECTED_ROLES:
            dotted = f"models.{role}"
            validator = VALIDATORS[dotted]
            for sample in ("claude-sonnet-4-5", "gpt-5-codex", "gemini-2.5-pro", "my-custom-model"):
                self.assertTrue(
                    validator(sample),
                    f"VALIDATORS[{dotted!r}]({sample!r}) must return True",
                )

    def test_validator_rejects_non_string(self):
        """models.* validator must reject non-string values (e.g. int, bool, None)."""
        from config import VALIDATORS
        for role in self._EXPECTED_ROLES:
            dotted = f"models.{role}"
            validator = VALIDATORS[dotted]
            for bad in (123, True, None, [], {}):
                self.assertFalse(
                    validator(bad),
                    f"VALIDATORS[{dotted!r}]({bad!r}) must return False (non-string)",
                )

    # (c) Absent [models] section → back-compat default resolution (empty string)
    def test_absent_models_section_yields_empty_string_default(self):
        """When [models] is absent from all config layers, defaults are empty strings."""
        for role in self._EXPECTED_ROLES:
            r = run(["get", f"models.{role}"], env=self.env, cwd=self.cwd)
            self.assertEqual(r.returncode, 0, f"get models.{role} exited {r.returncode}: {r.stderr}")
            # Empty string default prints as blank line
            self.assertEqual(
                r.stdout.strip(), "",
                f"models.{role} default must be empty string (absent sentinel), got {r.stdout.strip()!r}",
            )

    def test_default_model_classes_are_readable(self):
        """Absent config still exposes explicit cheap/standard/deep class defaults."""
        for key, expected in (
            ("model_classes.cheap.model", "haiku"),
            ("model_classes.standard.model", "sonnet"),
            ("model_classes.deep.model", "opus"),
            ("model_routing.implementer.low", "sonnet"),
            ("model_routing.implementer.medium", "sonnet"),
            ("model_routing.implementer.high", "opus"),
            ("model_routing.implementer.retry", "opus"),
        ):
            r = run(["get", key], env=self.env, cwd=self.cwd)
            self.assertEqual(r.returncode, 0, f"get {key} exited {r.returncode}: {r.stderr}")
            self.assertEqual(r.stdout.strip(), expected, f"unexpected default for {key}")

    def test_native_agent_default_route_inherits_frontmatter(self):
        """The native default route stays empty so checked-in agent model pins survive."""
        r = run(["get", "model_routing.native_agents.default"], env=self.env, cwd=self.cwd)
        self.assertEqual(r.returncode, 0, f"stderr={r.stderr!r}")
        self.assertEqual(r.stdout.strip(), "")

    def test_global_config_can_define_model_class_and_native_agent_route(self):
        """User-global config can define a custom class and route an agent to it."""
        write_global_config(
            self.xdg,
            "[model_classes.local_fast]\n"
            "model = \"ollama/qwen3:8b\"\n"
            "thinking = \"low\"\n"
            "reasoning = \"effort=low\"\n"
            "\n"
            "[model_routing.native_agents]\n"
            "explore = \"local_fast\"\n",
        )
        for key, expected in (
            ("model_classes.local_fast.model", "ollama/qwen3:8b"),
            ("model_classes.local_fast.thinking", "low"),
            ("model_classes.local_fast.reasoning", "effort=low"),
            ("model_routing.native_agents.explore", "local_fast"),
        ):
            r = run(["get", key], env=self.env, cwd=self.cwd)
            self.assertEqual(r.returncode, 0, f"get {key} exited {r.returncode}: {r.stderr}")
            self.assertEqual(r.stdout.strip(), expected)

    def test_custom_model_class_omitted_metadata_reads_empty(self):
        """Custom class thinking/reasoning metadata is optional and defaults empty."""
        write_global_config(
            self.xdg,
            "[model_classes.local_plain]\n"
            "model = \"llama-3.3-70b\"\n",
        )
        for key in (
            "model_classes.local_plain.thinking",
            "model_classes.local_plain.reasoning",
        ):
            r = run(["get", key], env=self.env, cwd=self.cwd)
            self.assertEqual(r.returncode, 0, f"get {key} exited {r.returncode}: {r.stderr}")
            self.assertEqual(r.stdout.strip(), "")

    def test_repo_config_can_override_implementer_route_with_exact_model(self):
        """Repo config can map a tier directly to an exact model override."""
        repo = tempfile.mkdtemp(prefix="z-harness-test-repo-model-routing-")
        try:
            repo_cfg = write_repo_config(
                repo,
                "[model_routing.implementer]\n"
                "high = \"claude-opus-4-1\"\n",
            )
            r = run(
                ["get", "model_routing.implementer.high"],
                env={"XDG_CONFIG_HOME": self.xdg, "Z_HARNESS_REPO_CONFIG": repo_cfg},
            )
            self.assertEqual(r.returncode, 0, f"stderr={r.stderr!r}")
            self.assertEqual(r.stdout.strip(), "claude-opus-4-1")
        finally:
            shutil.rmtree(repo, ignore_errors=True)

    def test_repo_config_rejects_empty_model_class_model(self):
        """Custom model_classes.*.model must be non-empty."""
        repo = tempfile.mkdtemp(prefix="z-harness-test-repo-model-class-invalid-")
        try:
            repo_cfg = write_repo_config(
                repo,
                "[model_classes.bad]\n"
                "model = \"\"\n",
            )
            r = run(
                ["get", "model_classes.bad.model"],
                env={"XDG_CONFIG_HOME": self.xdg, "Z_HARNESS_REPO_CONFIG": repo_cfg},
            )
            self.assertEqual(r.returncode, 2)
        finally:
            shutil.rmtree(repo, ignore_errors=True)

    def test_repo_config_rejects_nested_implementer_route_leaf(self):
        """Scalar implementer routes must not accept nested table leaves."""
        repo = tempfile.mkdtemp(prefix="z-harness-test-repo-model-routing-shape-")
        try:
            repo_cfg = write_repo_config(
                repo,
                "[model_routing.implementer.high]\n"
                "foo = \"bar\"\n",
            )
            r = run(
                ["get", "model_routing.implementer.high"],
                env={"XDG_CONFIG_HOME": self.xdg, "Z_HARNESS_REPO_CONFIG": repo_cfg},
            )
            self.assertEqual(r.returncode, 2)
            self.assertIn("unsupported nested table", r.stderr)
        finally:
            shutil.rmtree(repo, ignore_errors=True)

    def test_repo_config_rejects_nested_model_class_field(self):
        """Scalar model class fields must not accept nested table leaves."""
        repo = tempfile.mkdtemp(prefix="z-harness-test-repo-model-class-shape-")
        try:
            repo_cfg = write_repo_config(
                repo,
                "[model_classes.local_fast.model]\n"
                "foo = \"bar\"\n",
            )
            r = run(
                ["get", "model_classes.local_fast.model"],
                env={"XDG_CONFIG_HOME": self.xdg, "Z_HARNESS_REPO_CONFIG": repo_cfg},
            )
            self.assertEqual(r.returncode, 2)
            self.assertIn("unsupported nested table", r.stderr)
        finally:
            shutil.rmtree(repo, ignore_errors=True)

    def test_global_config_rejects_unsupported_model_class_leaf(self):
        """Unsupported dynamic model class leaves hard-fail at TOML load."""
        write_global_config(
            self.xdg,
            "[model_classes.local_fast]\n"
            "model = \"haiku\"\n"
            "foo = \"bar\"\n",
        )
        r = run(["get", "model_classes.local_fast.model"], env=self.env, cwd=self.cwd)
        self.assertEqual(r.returncode, 2)
        self.assertIn("unsupported model routing key", r.stderr)

    def test_repo_config_rejects_unsupported_model_class_leaf(self):
        """Unsupported dynamic model class leaves hard-fail in repo TOML."""
        repo = tempfile.mkdtemp(prefix="z-harness-test-repo-model-class-leaf-")
        try:
            repo_cfg = write_repo_config(
                repo,
                "[model_classes.local_fast]\n"
                "model = \"haiku\"\n"
                "foo = \"bar\"\n",
            )
            r = run(
                ["get", "model_classes.local_fast.model"],
                env={"XDG_CONFIG_HOME": self.xdg, "Z_HARNESS_REPO_CONFIG": repo_cfg},
            )
            self.assertEqual(r.returncode, 2)
            self.assertIn("unsupported model routing key", r.stderr)
            self.assertIn("model_classes.local_fast.foo", r.stderr)
        finally:
            shutil.rmtree(repo, ignore_errors=True)

    def test_repo_config_rejects_unsupported_model_routing_direct_leaf(self):
        """Unsupported direct leaves in dynamic sections must hard-fail in repo TOML."""
        repo = tempfile.mkdtemp(prefix="z-harness-test-repo-model-routing-leaf-")
        try:
            repo_cfg = write_repo_config(
                repo,
                "[model_routing]\n"
                "unexpected = \"cheap\"\n",
            )
            r = run(
                ["get", "model_routing.implementer.high"],
                env={"XDG_CONFIG_HOME": self.xdg, "Z_HARNESS_REPO_CONFIG": repo_cfg},
            )
            self.assertEqual(r.returncode, 2)
            self.assertIn("unsupported model routing key", r.stderr)
            self.assertIn("model_routing.unexpected", r.stderr)
        finally:
            shutil.rmtree(repo, ignore_errors=True)

    def test_repo_config_rejects_scalar_dynamic_section(self):
        """Dynamic model config sections must be TOML tables, not scalar leaves."""
        repo = tempfile.mkdtemp(prefix="z-harness-test-repo-model-section-scalar-")
        try:
            repo_cfg = write_repo_config(
                repo,
                "model_classes = \"cheap\"\n",
            )
            r = run(
                ["get", "model_classes.cheap.model"],
                env={"XDG_CONFIG_HOME": self.xdg, "Z_HARNESS_REPO_CONFIG": repo_cfg},
            )
            self.assertEqual(r.returncode, 2)
            self.assertIn("unsupported model routing key", r.stderr)
            self.assertIn("model_classes", r.stderr)
        finally:
            shutil.rmtree(repo, ignore_errors=True)

    def test_repo_config_rejects_uppercase_model_class_name(self):
        """Dynamic model class names must use canonical lowercase segments."""
        repo = tempfile.mkdtemp(prefix="z-harness-test-repo-model-class-case-")
        try:
            repo_cfg = write_repo_config(
                repo,
                "[model_classes.LocalFast]\n"
                "model = \"haiku\"\n",
            )
            r = run(
                ["get", "model_classes.LocalFast.model"],
                env={"XDG_CONFIG_HOME": self.xdg, "Z_HARNESS_REPO_CONFIG": repo_cfg},
            )
            self.assertEqual(r.returncode, 2)
            self.assertIn("non-canonical key segment", r.stderr)
        finally:
            shutil.rmtree(repo, ignore_errors=True)

    def test_repo_config_rejects_uppercase_native_agent_id(self):
        """Dynamic native-agent route ids must use canonical lowercase segments."""
        repo = tempfile.mkdtemp(prefix="z-harness-test-repo-native-agent-case-")
        try:
            repo_cfg = write_repo_config(
                repo,
                "[model_routing.native_agents]\n"
                "Explore = \"cheap\"\n",
            )
            r = run(
                ["get", "model_routing.native_agents.Explore"],
                env={"XDG_CONFIG_HOME": self.xdg, "Z_HARNESS_REPO_CONFIG": repo_cfg},
            )
            self.assertEqual(r.returncode, 2)
            self.assertIn("non-canonical key segment", r.stderr)
        finally:
            shutil.rmtree(repo, ignore_errors=True)

    def test_repo_config_rejects_uppercase_implementer_tier(self):
        """Dynamic implementer tier keys must use canonical lowercase segments."""
        repo = tempfile.mkdtemp(prefix="z-harness-test-repo-implementer-case-")
        try:
            repo_cfg = write_repo_config(
                repo,
                "[model_routing.implementer]\n"
                "High = \"deep\"\n",
            )
            r = run(
                ["get", "model_routing.implementer.High"],
                env={"XDG_CONFIG_HOME": self.xdg, "Z_HARNESS_REPO_CONFIG": repo_cfg},
            )
            self.assertEqual(r.returncode, 2)
            self.assertIn("non-canonical key segment", r.stderr)
        finally:
            shutil.rmtree(repo, ignore_errors=True)

    # (d) config.py get models.reviewer returns a set value
    def test_get_models_reviewer_returns_set_value_from_toml(self):
        """config.py get models.reviewer returns the value set in repo config."""
        repo = tempfile.mkdtemp(prefix="z-harness-test-repo-models-")
        try:
            repo_cfg = write_repo_config(
                repo,
                "[models]\nreviewer = \"claude-opus-4\"\n",
            )
            r = run(
                ["get", "models.reviewer"],
                env={"XDG_CONFIG_HOME": self.xdg, "Z_HARNESS_REPO_CONFIG": repo_cfg},
            )
            self.assertEqual(r.returncode, 0, f"get models.reviewer exited {r.returncode}: {r.stderr}")
            self.assertEqual(r.stdout.strip(), "claude-opus-4")
        finally:
            shutil.rmtree(repo, ignore_errors=True)

    def test_get_models_implementer_returns_set_value_from_env(self):
        """config.py get models.implementer returns the value set via env var."""
        r = run(
            ["get", "models.implementer"],
            env={
                "XDG_CONFIG_HOME": self.xdg,
                "Z_HARNESS_MODELS_IMPLEMENTER": "gpt-5-codex",
            },
            cwd=self.cwd,
        )
        self.assertEqual(r.returncode, 0, f"get models.implementer exited {r.returncode}: {r.stderr}")
        self.assertEqual(r.stdout.strip(), "gpt-5-codex")

    def test_unknown_models_key_exits_3(self):
        """A non-existent models.* key exits with code 3."""
        r = run(["get", "models.nonexistent_role"], env=self.env, cwd=self.cwd)
        self.assertEqual(r.returncode, 3)

    def test_toml_wins_over_env_for_models_key(self):
        """T001: TOML models value is not overridden by env var."""
        repo = tempfile.mkdtemp(prefix="z-harness-test-repo-models-tomlwins-")
        try:
            repo_cfg = write_repo_config(
                repo,
                "[models]\nreviewer = \"gemini-2.5-pro\"\n",
            )
            r = run(
                ["get", "models.reviewer"],
                env={
                    "XDG_CONFIG_HOME": self.xdg,
                    "Z_HARNESS_REPO_CONFIG": repo_cfg,
                    "Z_HARNESS_MODELS_REVIEWER": "claude-opus-4",  # must NOT win
                },
            )
            self.assertEqual(r.returncode, 0)
            self.assertEqual(
                r.stdout.strip(), "gemini-2.5-pro",
                "TOML-wins: repo models.reviewer must not be overridden by env var",
            )
        finally:
            shutil.rmtree(repo, ignore_errors=True)


# ---------------------------------------------------------------------------
# Tests for T005: Deprecation surface — runtime.env_strict
# ---------------------------------------------------------------------------

class TestEnvStrictDeprecation(unittest.TestCase):
    """
    Tests for the deprecation warning/error surface added by T005.

    When a user-set preference env var is detected (the same set that
    _collect_deprecated_env_vars finds), load_config() emits:
      - A WARNING to stderr when runtime.env_strict = false (default)
      - A hard ERROR (exit 2) when runtime.env_strict = true

    The env_strict key is a CONFIG KEY (set via config.toml [runtime]
    env_strict = true) — it is NOT itself a raw env var override.
    """

    def setUp(self):
        self.xdg = make_xdg()
        self.cwd = make_isolation_dir()

    def tearDown(self):
        shutil.rmtree(self.xdg, ignore_errors=True)
        shutil.rmtree(self.cwd, ignore_errors=True)

    # ---- Default (env_strict = false): warning-only, non-fatal ----

    def test_deprecated_pref_env_emits_warning_when_strict_false(self):
        """
        Setting a preference env var (e.g. Z_HARNESS_PRE_REVIEW) with no
        env_strict config must produce a WARNING on stderr but still exit 0.

        Failure class: if the deprecation warning is missing, users will
        silently use the old env-var path long after migration — the
        deprecation surface becomes a no-op.
        """
        r = run(
            ["get", "notify.level"],
            env={
                "XDG_CONFIG_HOME": self.xdg,
                # Z_HARNESS_PRE_REVIEW is a deprecated preference env var
                # (maps to runtime.pre_review via _INGRESS_LEGACY_ALIASES)
                "Z_HARNESS_PRE_REVIEW": "true",
            },
            cwd=self.cwd,
        )
        # Must succeed (non-fatal when env_strict=false)
        self.assertEqual(r.returncode, 0,
                         f"Expected exit 0 with env_strict=false; got {r.returncode}. stderr={r.stderr!r}")
        # Warning must appear on stderr
        self.assertIn("DEPRECATED", r.stderr,
                      "Expected DEPRECATED warning in stderr when preference env var is set")
        self.assertIn("Z_HARNESS_PRE_REVIEW", r.stderr,
                      "Warning must name the offending env var")

    def test_deprecated_transliteration_env_emits_warning(self):
        """
        The mechanical transliteration Z_HARNESS_RUNTIME_PRE_REVIEW (not the
        legacy alias) is also a deprecated preference env var and must trigger
        a warning.

        Failure class: if only legacy aliases are checked, users who set the
        mechanical transliteration would bypass the deprecation surface.
        """
        r = run(
            ["get", "runtime.pre_review"],
            env={
                "XDG_CONFIG_HOME": self.xdg,
                "Z_HARNESS_RUNTIME_PRE_REVIEW": "true",
            },
            cwd=self.cwd,
        )
        self.assertEqual(r.returncode, 0,
                         f"Expected exit 0; got {r.returncode}. stderr={r.stderr!r}")
        self.assertIn("DEPRECATED", r.stderr,
                      "Transliteration env var must also trigger DEPRECATED warning")

    def test_no_pref_env_set_no_warning(self):
        """
        When no preference env vars are set in the environment, no deprecation
        warning must appear on stderr.

        Failure class: false-positive warnings would be noise that trains users
        to ignore the deprecation surface entirely.
        """
        r = run(
            ["get", "notify.level"],
            env={"XDG_CONFIG_HOME": self.xdg},
            cwd=self.cwd,
        )
        self.assertEqual(r.returncode, 0)
        # No deprecation warning should appear (stderr may have other lines but not DEPRECATED)
        self.assertNotIn("DEPRECATED", r.stderr,
                         f"Unexpected DEPRECATED in stderr with no preference env set: {r.stderr!r}")

    # ---- env_strict = true: hard error ----

    def test_deprecated_pref_env_errors_when_strict_true(self):
        """
        With runtime.env_strict = true in config.toml, setting a preference
        env var must cause a hard ERROR (non-zero exit).

        Failure class: if this exits 0, the strict-enforcement mode is broken
        and users relying on it for CI enforcement will get silent regressions.
        """
        write_global_config(self.xdg, '[runtime]\nenv_strict = true\n')
        r = run(
            ["get", "notify.level"],
            env={
                "XDG_CONFIG_HOME": self.xdg,
                "Z_HARNESS_PRE_REVIEW": "true",
            },
            cwd=self.cwd,
        )
        # Must be a hard error (non-zero exit)
        self.assertNotEqual(r.returncode, 0,
                            "Expected non-zero exit with runtime.env_strict=true and deprecated env var")
        self.assertEqual(r.returncode, 2,
                         f"Expected exit 2 for validation error; got {r.returncode}")
        # Error message must appear on stderr
        self.assertIn("DEPRECATED", r.stderr,
                      "Hard error must include DEPRECATED marker in stderr")

    def test_env_strict_true_no_pref_env_exits_0(self):
        """
        With runtime.env_strict = true but NO preference env vars set, the
        command must still succeed (exit 0).

        Failure class: if the strict mode errors even with no deprecated vars,
        it becomes impossible to use env_strict=true in normal operation.
        """
        write_global_config(self.xdg, '[runtime]\nenv_strict = true\n')
        r = run(
            ["get", "notify.level"],
            env={"XDG_CONFIG_HOME": self.xdg},
            cwd=self.cwd,
        )
        self.assertEqual(r.returncode, 0,
                         f"env_strict=true with no deprecated vars must exit 0; got {r.returncode}. stderr={r.stderr!r}")

    def test_env_strict_is_config_key_not_raw_env(self):
        """
        runtime.env_strict must be settable via config.toml only — not via a
        raw env var Z_HARNESS_RUNTIME_ENV_STRICT, because that would create a
        bootstrap paradox (the env var would be deprecated by the very policy
        it enables).

        This test verifies that env_strict can be read via `config.py get` and
        that the TOML-layer value is respected.

        Failure class: if env_strict were itself an env override, it could be
        defeated by unsetting the env var, and the enforcement guarantee breaks.
        """
        # Without config.toml, env_strict must default to false
        r = run(
            ["get", "runtime.env_strict"],
            env={"XDG_CONFIG_HOME": self.xdg},
            cwd=self.cwd,
        )
        self.assertEqual(r.returncode, 0)
        self.assertEqual(r.stdout.strip(), "false",
                         "runtime.env_strict must default to false")

        # With config.toml setting it to true, must reflect true
        write_global_config(self.xdg, '[runtime]\nenv_strict = true\n')
        r2 = run(
            ["get", "runtime.env_strict"],
            env={"XDG_CONFIG_HOME": self.xdg},
            cwd=self.cwd,
        )
        self.assertEqual(r2.returncode, 0)
        self.assertEqual(r2.stdout.strip(), "true",
                         "runtime.env_strict = true in config.toml must be respected")

    def test_legal_plumbing_env_does_not_trigger_warning(self):
        """
        Legal plumbing/unattended env vars (Z_HARNESS_PLAN_DIR, Z_HARNESS_SLUG,
        Z_HARNESS_NO_ASK, etc.) must never trigger the deprecation warning —
        they are in LEGAL_ENV_KEYS and are allowed.

        Failure class: if legal vars trigger the warning, legitimate uses of
        plumbing env vars in CI/CD pipelines generate spurious noise that masks
        real deprecation warnings.
        """
        r = run(
            ["get", "notify.level"],
            env={
                "XDG_CONFIG_HOME": self.xdg,
                # Legal plumbing vars (from LEGAL_ENV_KEYS)
                "Z_HARNESS_NO_ASK": "halt",
                "Z_HARNESS_PLAN_DIR": "/tmp/test-plan",
                "Z_HARNESS_SLUG": "test-slug",
            },
            cwd=self.cwd,
        )
        # Should succeed (legal vars are never deprecated)
        # Note: Z_HARNESS_NO_ASK=halt may cause other effects but should not
        # produce a DEPRECATED warning for these legal vars.
        self.assertNotIn("DEPRECATED", r.stderr,
                         f"Legal plumbing vars must NOT trigger DEPRECATED warning: {r.stderr!r}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    unittest.main(verbosity=2)
