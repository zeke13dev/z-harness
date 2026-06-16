"""
tests/test_intent_config.py — Tests for intent/BFS config knobs, mode detection,
freeze+bootstrap helpers, and backward-compat invariants.

Covers:
  TestWorkflowKnobsFromFile     — (a) four workflow.* knobs resolve from a TOML file
  TestInvalidEnumExits2         — (a) invalid enum value exits 2
  TestBoolCoercion              — (a) bool-typed knobs coerce from string
  TestModeDetection             — (c) SPEC vs INTENT mode detection helpers
  TestFreezeBfsLevel            — (d) freeze_intent + bootstrap_ledger cycle
  TestBackwardCompatLegacyTasks — (e) done_set_hash on a legacy TASKS.md
  TestHermesGatedOff            — (f) hermes_enabled default is false; HERMES_* env ignored

Invariants:
  - workflow.planning_mode default is "intent" (not "full" / legacy SDD).
  - workflow.hermes_enabled default is False — old Hermes machinery is gated off.
  - freeze_intent is idempotent — calling it twice returns False on second call.
  - bootstrap_ledger is idempotent — calling it when file exists returns False.
  - done_set_hash on a SPEC/PLAN/TASKS legacy file must return the same hash as
    running it directly — the legacy path is untouched by the beyond-sdd changes.
  Failure class: hermes_enabled=True leaks into a default run (gate bypass).
"""

from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SCRIPTS_DIR = _REPO_ROOT / "scripts"
_CONFIG_PY = str(_SCRIPTS_DIR / "config.py")
_HELPERS_SH = str(_SCRIPTS_DIR / "session-helpers.sh")
_SCHEMA_PY = str(_SCRIPTS_DIR / "intent-schema.py")

PYTHON = sys.executable


# ---------------------------------------------------------------------------
# Module import helpers
# ---------------------------------------------------------------------------

def _import_intent_schema():
    spec = importlib.util.spec_from_file_location(
        "intent_schema", _SCRIPTS_DIR / "intent-schema.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_schema = _import_intent_schema()
freeze_intent = _schema.freeze_intent
bootstrap_ledger = _schema.bootstrap_ledger


# ---------------------------------------------------------------------------
# Subprocess helper (mirrors test_config.py idiom)
# ---------------------------------------------------------------------------

def _run_config(*args, env_extra: dict | None = None, cwd: str | None = None):
    """Run scripts/config.py with isolated env and capture output."""
    full_env = os.environ.copy()
    # Strip all Z_HARNESS_* from parent env for hermeticity.
    for k in list(full_env):
        if k.startswith("Z_HARNESS_"):
            del full_env[k]
    # Default: no XDG (so no global config file bleeds in); pin to a temp dir.
    if "XDG_CONFIG_HOME" not in (env_extra or {}):
        full_env.pop("XDG_CONFIG_HOME", None)
    if env_extra:
        full_env.update(env_extra)
    return subprocess.run(
        [PYTHON, _CONFIG_PY] + list(args),
        capture_output=True,
        text=True,
        env=full_env,
        cwd=cwd,
    )


def _write_repo_config(repo_dir: str, content: str) -> str:
    """Write content to <repo_dir>/.z-harness/config.toml. Returns path string."""
    cfg_dir = Path(repo_dir) / ".z-harness"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    cfg_path = cfg_dir / "config.toml"
    cfg_path.write_text(content)
    return str(cfg_path)


def _write_tmp(content: str, suffix: str = ".md") -> Path:
    f = tempfile.NamedTemporaryFile(
        mode="w", suffix=suffix, delete=False, encoding="utf-8"
    )
    f.write(content)
    f.flush()
    f.close()
    return Path(f.name)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_VALID_PENDING_INTENT = textwrap.dedent("""\
    ---
    artifact: intent
    slug: test-config
    level: quick
    generated_at: 2026-06-16T00:00:00Z
    frozen_at: pending
    planning_mode: intent
    ---
    ## Intent
    Tests the freeze/bootstrap cycle.
    ## Acceptance checklist
    - [ ] The freeze_intent helper stamps frozen_at with a real ISO timestamp
    - [ ] bootstrap_ledger creates LEDGER.md with correct frontmatter
""")

_LEGACY_TASKS_MD = textwrap.dedent("""\
    # Tasks

    ## T001 — Set up scaffolding `[x]`
    **Files:** scripts/setup.sh
    **Acceptance:** The setup script exits 0.

    ## T002 — Write unit tests `[ ]`
    **Files:** tests/test_setup.py
    **Acceptance:** pytest passes.
""")


# ---------------------------------------------------------------------------
# (a) TestWorkflowKnobsFromFile
# ---------------------------------------------------------------------------

class TestWorkflowKnobsFromFile(unittest.TestCase):
    """Four workflow.* knobs resolve correctly from a .z-harness/config.toml file.

    Invariant: file-layer values override defaults.
    Failure class: knob silently returns default even when file overrides it.
    """

    def setUp(self):
        self.repo_dir = tempfile.mkdtemp(prefix="z-harness-test-repo-")
        self.xdg = tempfile.mkdtemp(prefix="z-harness-test-xdg-")

    def tearDown(self):
        shutil.rmtree(self.repo_dir, ignore_errors=True)
        shutil.rmtree(self.xdg, ignore_errors=True)

    def _run(self, key: str, cfg_content: str):
        repo_cfg = _write_repo_config(self.repo_dir, cfg_content)
        return _run_config(
            "get", key,
            env_extra={
                "XDG_CONFIG_HOME": self.xdg,
                "Z_HARNESS_REPO_CONFIG": repo_cfg,
            },
        )

    def test_planning_mode_resolved_from_file(self):
        """workflow.planning_mode can be set to 'full' via TOML file."""
        r = self._run("workflow.planning_mode", '[workflow]\nplanning_mode = "full"\n')
        self.assertEqual(r.returncode, 0, msg=r.stderr)
        self.assertEqual(r.stdout.strip(), "full")

    def test_intent_level_resolved_from_file(self):
        """workflow.intent_level can be set to 'standard' via TOML file."""
        r = self._run("workflow.intent_level", '[workflow]\nintent_level = "standard"\n')
        self.assertEqual(r.returncode, 0, msg=r.stderr)
        self.assertEqual(r.stdout.strip(), "standard")

    def test_intent_parallel_levels_resolved_from_file(self):
        """workflow.intent_parallel_levels can be set to true via TOML file."""
        r = self._run(
            "workflow.intent_parallel_levels",
            '[workflow]\nintent_parallel_levels = true\n',
        )
        self.assertEqual(r.returncode, 0, msg=r.stderr)
        self.assertEqual(r.stdout.strip(), "true")

    def test_hermes_enabled_resolved_from_file(self):
        """workflow.hermes_enabled can be set to true via TOML file."""
        r = self._run("workflow.hermes_enabled", '[workflow]\nhermes_enabled = true\n')
        self.assertEqual(r.returncode, 0, msg=r.stderr)
        self.assertEqual(r.stdout.strip(), "true")

    def test_all_four_knobs_have_expected_defaults(self):
        """Without any config file, all four knobs return their spec-defined defaults."""
        repo_cfg = _write_repo_config(self.repo_dir, "")  # empty, no overrides
        for key, expected in [
            ("workflow.planning_mode", "intent"),
            ("workflow.intent_level", "auto"),
            ("workflow.intent_parallel_levels", "false"),
            ("workflow.hermes_enabled", "false"),
        ]:
            with self.subTest(key=key):
                r = _run_config(
                    "get", key,
                    env_extra={
                        "XDG_CONFIG_HOME": self.xdg,
                        "Z_HARNESS_REPO_CONFIG": repo_cfg,
                    },
                )
                self.assertEqual(r.returncode, 0, msg=f"key={key}: {r.stderr}")
                self.assertEqual(r.stdout.strip(), expected,
                                 f"key={key}: expected {expected!r}, got {r.stdout.strip()!r}")


# ---------------------------------------------------------------------------
# (a) TestInvalidEnumExits2
# ---------------------------------------------------------------------------

class TestInvalidEnumExits2(unittest.TestCase):
    """Invalid enum value in repo config must cause exit 2 (hard fail on repo layer).

    Invariant: bad enum in repo config exits 2, not silently falls back to default.
    Failure class: bad enum silently passes validation → wrong planning_mode used.
    """

    def setUp(self):
        self.repo_dir = tempfile.mkdtemp(prefix="z-harness-test-repo-")
        self.xdg = tempfile.mkdtemp(prefix="z-harness-test-xdg-")

    def tearDown(self):
        shutil.rmtree(self.repo_dir, ignore_errors=True)
        shutil.rmtree(self.xdg, ignore_errors=True)

    def _run(self, key: str, cfg_content: str):
        repo_cfg = _write_repo_config(self.repo_dir, cfg_content)
        return _run_config(
            "get", key,
            env_extra={
                "XDG_CONFIG_HOME": self.xdg,
                "Z_HARNESS_REPO_CONFIG": repo_cfg,
            },
        )

    def test_invalid_planning_mode_exits_2(self):
        """planning_mode='magic' is not in allowed set → exit 2."""
        r = self._run("workflow.planning_mode", '[workflow]\nplanning_mode = "magic"\n')
        self.assertEqual(r.returncode, 2,
                         f"Expected exit 2 for invalid planning_mode, got {r.returncode}. "
                         f"stdout: {r.stdout} stderr: {r.stderr}")

    def test_invalid_intent_level_exits_2(self):
        """intent_level='mega' is not in {auto,quick,standard,deep} → exit 2."""
        r = self._run("workflow.intent_level", '[workflow]\nintent_level = "mega"\n')
        self.assertEqual(r.returncode, 2,
                         f"Expected exit 2 for invalid intent_level, got {r.returncode}")


# ---------------------------------------------------------------------------
# (a) TestBoolCoercion
# ---------------------------------------------------------------------------

class TestBoolCoercion(unittest.TestCase):
    """Bool-typed knobs coerce correctly from string values and TOML booleans.

    Invariant: hermes_enabled = true (TOML) → prints 'true'; 'false' → 'false'.
    Failure class: coercion fails → hermes_enabled silently stays false when overridden.
    """

    def setUp(self):
        self.repo_dir = tempfile.mkdtemp(prefix="z-harness-test-repo-")
        self.xdg = tempfile.mkdtemp(prefix="z-harness-test-xdg-")

    def tearDown(self):
        shutil.rmtree(self.repo_dir, ignore_errors=True)
        shutil.rmtree(self.xdg, ignore_errors=True)

    def _run_key(self, key: str, toml_content: str) -> str:
        repo_cfg = _write_repo_config(self.repo_dir, toml_content)
        r = _run_config(
            "get", key,
            env_extra={
                "XDG_CONFIG_HOME": self.xdg,
                "Z_HARNESS_REPO_CONFIG": repo_cfg,
            },
        )
        self.assertEqual(r.returncode, 0, msg=f"Exit {r.returncode}: {r.stderr}")
        return r.stdout.strip()

    def test_hermes_enabled_toml_true_prints_true(self):
        val = self._run_key("workflow.hermes_enabled", "[workflow]\nhermes_enabled = true\n")
        self.assertEqual(val, "true")

    def test_hermes_enabled_toml_false_prints_false(self):
        val = self._run_key("workflow.hermes_enabled", "[workflow]\nhermes_enabled = false\n")
        self.assertEqual(val, "false")

    def test_intent_parallel_levels_toml_true_prints_true(self):
        val = self._run_key(
            "workflow.intent_parallel_levels",
            "[workflow]\nintent_parallel_levels = true\n",
        )
        self.assertEqual(val, "true")

    def test_env_var_true_coerces_hermes_enabled(self):
        """Z_HARNESS_WORKFLOW_HERMES_ENABLED=true in env → 'true'."""
        repo_cfg = _write_repo_config(self.repo_dir, "")
        r = _run_config(
            "get", "workflow.hermes_enabled",
            env_extra={
                "XDG_CONFIG_HOME": self.xdg,
                "Z_HARNESS_REPO_CONFIG": repo_cfg,
                "Z_HARNESS_WORKFLOW_HERMES_ENABLED": "true",
            },
        )
        self.assertEqual(r.returncode, 0, msg=r.stderr)
        self.assertEqual(r.stdout.strip(), "true")

    def test_env_var_false_coerces_hermes_enabled(self):
        """Z_HARNESS_WORKFLOW_HERMES_ENABLED=false in env → 'false'."""
        repo_cfg = _write_repo_config(self.repo_dir, "")
        r = _run_config(
            "get", "workflow.hermes_enabled",
            env_extra={
                "XDG_CONFIG_HOME": self.xdg,
                "Z_HARNESS_REPO_CONFIG": repo_cfg,
                "Z_HARNESS_WORKFLOW_HERMES_ENABLED": "false",
            },
        )
        self.assertEqual(r.returncode, 0, msg=r.stderr)
        self.assertEqual(r.stdout.strip(), "false")


# ---------------------------------------------------------------------------
# (c) TestModeDetection
# ---------------------------------------------------------------------------

class TestModeDetection(unittest.TestCase):
    """SPEC vs INTENT mode detection.

    The z-plan/z-implement-all commands branch on presence of INTENT.md vs
    SPEC.md. We cannot unit-test the bash command logic directly, but we CAN:
      1. Assert that config.py get workflow.planning_mode returns the
         expected value from a file (intent or full).
      2. Assert that validate_intent correctly distinguishes an INTENT.md
         from an ordinary file (so the mode-detection helper is reliable).
      3. Assert that a fixture with only SPEC.md (no INTENT.md) would trigger
         the legacy path — represented by validate_intent returning invalid
         for a SPEC-formatted file.

    Invariant: INTENT.md detection is based on artifact: intent in frontmatter.
    A SPEC.md file lacks this field → validate_intent rejects it → mode=full.
    Failure class: validate_intent accepts a SPEC.md → mode detection is wrong.
    """

    _SPEC_CONTENT = textwrap.dedent("""\
        # SPEC

        This is a SDD-style spec, not an INTENT.md.

        ## Goals
        - Build something useful

        ## Acceptance criteria
        - The command exits 0
    """)

    def test_validate_intent_accepts_valid_intent_md(self):
        """A proper INTENT.md (artifact: intent frontmatter) passes validate_intent."""
        p = _write_tmp(_VALID_PENDING_INTENT)
        try:
            result = _schema.validate_intent(p)
            self.assertTrue(result.valid, msg=result.errors)
        finally:
            p.unlink(missing_ok=True)

    def test_validate_intent_rejects_spec_md(self):
        """A SPEC.md file (no frontmatter) is rejected by validate_intent.

        This is the key mode-detection invariant: the SPEC/PLAN legacy path is
        only active when INTENT.md is absent or fails validate_intent.
        """
        p = _write_tmp(self._SPEC_CONTENT)
        try:
            result = _schema.validate_intent(p)
            self.assertFalse(result.valid,
                             "SPEC.md should NOT pass validate_intent (mode detection would break)")
        finally:
            p.unlink(missing_ok=True)

    def test_planning_mode_default_is_intent_not_full(self):
        """Default planning_mode is 'intent' — the BFS path, not the legacy SDD path."""
        repo_dir = tempfile.mkdtemp(prefix="z-harness-modedetect-")
        xdg = tempfile.mkdtemp(prefix="z-harness-modedetect-xdg-")
        try:
            repo_cfg = _write_repo_config(repo_dir, "")
            r = _run_config(
                "get", "workflow.planning_mode",
                env_extra={
                    "XDG_CONFIG_HOME": xdg,
                    "Z_HARNESS_REPO_CONFIG": repo_cfg,
                },
            )
            self.assertEqual(r.returncode, 0, msg=r.stderr)
            self.assertEqual(r.stdout.strip(), "intent",
                             "Default planning_mode must be 'intent' (not 'full'). "
                             "Changing this to 'full' would silently run the legacy SDD path.")
        finally:
            shutil.rmtree(repo_dir, ignore_errors=True)
            shutil.rmtree(xdg, ignore_errors=True)

    def test_planning_mode_full_is_accepted(self):
        """planning_mode = 'full' is a valid enum value (legacy SDD path opt-in)."""
        repo_dir = tempfile.mkdtemp(prefix="z-harness-modedetect-")
        xdg = tempfile.mkdtemp(prefix="z-harness-modedetect-xdg-")
        try:
            repo_cfg = _write_repo_config(repo_dir, '[workflow]\nplanning_mode = "full"\n')
            r = _run_config(
                "get", "workflow.planning_mode",
                env_extra={
                    "XDG_CONFIG_HOME": xdg,
                    "Z_HARNESS_REPO_CONFIG": repo_cfg,
                },
            )
            self.assertEqual(r.returncode, 0, msg=r.stderr)
            self.assertEqual(r.stdout.strip(), "full")
        finally:
            shutil.rmtree(repo_dir, ignore_errors=True)
            shutil.rmtree(xdg, ignore_errors=True)


# ---------------------------------------------------------------------------
# (d) TestFreezeBfsLevel
# ---------------------------------------------------------------------------

class TestFreezeBfsLevel(unittest.TestCase):
    """freeze_intent + bootstrap_ledger — one BFS level freeze cycle.

    Invariant:
      1. freeze_intent stamps frozen_at with an ISO timestamp (pending → real).
      2. bootstrap_ledger creates LEDGER.md with the correct frontmatter.
      3. Both helpers are idempotent (second call is a no-op).
      4. After freeze + bootstrap, validate_ledger passes on the bootstrapped file.
    Failure class: freeze not idempotent → double-freeze corrupts frozen_at.
    Failure class: bootstrap creates file with wrong frontmatter → ledger validation fails.
    """

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp(prefix="z-harness-bfs-")

    def tearDown(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def _write_intent(self, content: str) -> Path:
        p = Path(self.tmp_dir) / "INTENT.md"
        p.write_text(content, encoding="utf-8")
        return p

    def test_freeze_intent_stamps_frozen_at(self):
        """freeze_intent changes frozen_at from 'pending' to a real ISO timestamp."""
        intent_path = self._write_intent(_VALID_PENDING_INTENT)
        was_frozen, frozen_at = freeze_intent(intent_path)
        self.assertTrue(was_frozen, "Should have frozen (was pending)")
        self.assertNotEqual(frozen_at, "pending",
                            "frozen_at must not remain 'pending' after freeze")
        # Must be a non-empty ISO-ish string
        self.assertRegex(frozen_at, r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$",
                         f"frozen_at {frozen_at!r} is not a valid ISO timestamp")

    def test_freeze_intent_idempotent(self):
        """Calling freeze_intent twice returns was_frozen=False on second call."""
        intent_path = self._write_intent(_VALID_PENDING_INTENT)
        was_frozen_1, frozen_at_1 = freeze_intent(intent_path)
        self.assertTrue(was_frozen_1)
        # Second call — must be idempotent
        was_frozen_2, frozen_at_2 = freeze_intent(intent_path)
        self.assertFalse(was_frozen_2,
                         "Second freeze_intent call must return was_frozen=False (idempotent)")
        self.assertEqual(frozen_at_1, frozen_at_2,
                         "frozen_at must not change on second call")

    def test_frozen_intent_passes_validate_intent(self):
        """After freeze, the INTENT.md still passes validate_intent."""
        intent_path = self._write_intent(_VALID_PENDING_INTENT)
        freeze_intent(intent_path)
        result = _schema.validate_intent(intent_path)
        self.assertTrue(result.valid, msg=result.errors)

    def test_bootstrap_ledger_creates_file(self):
        """bootstrap_ledger creates LEDGER.md with correct frontmatter on first call."""
        intent_path = self._write_intent(_VALID_PENDING_INTENT)
        _was_frozen, frozen_at = freeze_intent(intent_path)

        ledger_path = Path(self.tmp_dir) / "LEDGER.md"
        self.assertFalse(ledger_path.exists(), "Ledger must not exist before bootstrap")

        created = bootstrap_ledger(ledger_path, frozen_at, slug="test-config")
        self.assertTrue(created, "bootstrap_ledger must return True on first call")
        self.assertTrue(ledger_path.exists(), "LEDGER.md must be created")

    def test_bootstrap_ledger_frontmatter_is_valid(self):
        """The bootstrapped LEDGER.md passes validate_ledger."""
        intent_path = self._write_intent(_VALID_PENDING_INTENT)
        _was_frozen, frozen_at = freeze_intent(intent_path)

        ledger_path = Path(self.tmp_dir) / "LEDGER.md"
        bootstrap_ledger(ledger_path, frozen_at, slug="test-config")

        result = _schema.validate_ledger(ledger_path)
        self.assertTrue(result.valid, msg=result.errors)

    def test_bootstrap_ledger_idempotent(self):
        """Calling bootstrap_ledger twice returns False on second call, file unchanged."""
        intent_path = self._write_intent(_VALID_PENDING_INTENT)
        _was_frozen, frozen_at = freeze_intent(intent_path)

        ledger_path = Path(self.tmp_dir) / "LEDGER.md"
        created_1 = bootstrap_ledger(ledger_path, frozen_at, slug="test-config")
        self.assertTrue(created_1)
        content_1 = ledger_path.read_text(encoding="utf-8")

        created_2 = bootstrap_ledger(ledger_path, frozen_at, slug="test-config")
        self.assertFalse(created_2,
                         "Second bootstrap_ledger call must return False (idempotent)")
        content_2 = ledger_path.read_text(encoding="utf-8")
        self.assertEqual(content_1, content_2,
                         "File content must not change on second bootstrap call")

    def test_bootstrap_ledger_contains_intent_frozen_at(self):
        """Bootstrapped LEDGER.md frontmatter contains the intent_frozen_at value."""
        intent_path = self._write_intent(_VALID_PENDING_INTENT)
        _was_frozen, frozen_at = freeze_intent(intent_path)

        ledger_path = Path(self.tmp_dir) / "LEDGER.md"
        bootstrap_ledger(ledger_path, frozen_at, slug="test-config")

        content = ledger_path.read_text(encoding="utf-8")
        self.assertIn(frozen_at, content,
                      f"LEDGER.md must contain intent_frozen_at={frozen_at!r}")

    def test_bootstrap_ledger_contains_slug(self):
        """Bootstrapped LEDGER.md frontmatter contains the slug value."""
        intent_path = self._write_intent(_VALID_PENDING_INTENT)
        _was_frozen, frozen_at = freeze_intent(intent_path)

        ledger_path = Path(self.tmp_dir) / "LEDGER.md"
        bootstrap_ledger(ledger_path, frozen_at, slug="my-test-slug")

        content = ledger_path.read_text(encoding="utf-8")
        self.assertIn("my-test-slug", content,
                      "LEDGER.md must contain the slug value")


# ---------------------------------------------------------------------------
# (e) TestBackwardCompatLegacyTasks
# ---------------------------------------------------------------------------

class TestBackwardCompatLegacyTasks(unittest.TestCase):
    """Legacy SPEC/PLAN/TASKS fixtures still work on the unchanged legacy path.

    Invariant: done_set_hash on a TASKS.md with [x] tasks produces a stable,
    non-empty hash. A TASKS.md with zero [x] tasks must produce the sha256
    of an empty string (deterministic). The beyond-sdd changes must not alter
    the done_set_hash output for legacy files.
    Failure class: done_set_hash breaks on legacy TASKS.md format → orchestrator
    cannot track task completion → silent regression in all existing plans.
    """

    def _run_done_set_hash(self, tasks_content: str) -> str:
        """Write tasks to a temp file, call done_set_hash via session-helpers.sh, return output."""
        p = _write_tmp(tasks_content, suffix=".md")
        try:
            result = subprocess.run(
                ["bash", _HELPERS_SH, "done_set_hash", str(p)],
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0,
                             f"done_set_hash failed: {result.stderr}")
            return result.stdout.strip()
        finally:
            p.unlink(missing_ok=True)

    def test_done_set_hash_with_one_done_task(self):
        """TASKS.md with one [x] task returns a non-empty hash."""
        h = self._run_done_set_hash(_LEGACY_TASKS_MD)
        self.assertNotEqual(h, "",
                            "done_set_hash must return a non-empty hash when [x] tasks exist")
        # Must look like a hex sha256 (64 hex chars)
        self.assertRegex(h, r"^[0-9a-f]{64}$",
                         f"Expected 64-char hex hash, got: {h!r}")

    def test_done_set_hash_empty_tasks_returns_stable_hash(self):
        """TASKS.md with no [x] tasks returns the sha256 of empty string (deterministic)."""
        all_pending = textwrap.dedent("""\
            # Tasks

            ## T001 — Do something `[ ]`
            **Files:** foo.py

            ## T002 — Do something else `[ ]`
            **Files:** bar.py
        """)
        h = self._run_done_set_hash(all_pending)
        # sha256("") = e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
        self.assertEqual(h, "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
                         "Hash of zero done tasks must be sha256 of empty string")

    def test_done_set_hash_deterministic_same_input(self):
        """Same TASKS.md content always returns the same hash."""
        h1 = self._run_done_set_hash(_LEGACY_TASKS_MD)
        h2 = self._run_done_set_hash(_LEGACY_TASKS_MD)
        self.assertEqual(h1, h2, "done_set_hash must be deterministic for the same input")

    def test_done_set_hash_differs_when_task_completed(self):
        """Completing a task changes the hash (hash tracks state)."""
        before = textwrap.dedent("""\
            ## T001 — Task A `[ ]`
            ## T002 — Task B `[ ]`
        """)
        after = textwrap.dedent("""\
            ## T001 — Task A `[x]`
            ## T002 — Task B `[ ]`
        """)
        h_before = self._run_done_set_hash(before)
        h_after = self._run_done_set_hash(after)
        self.assertNotEqual(h_before, h_after,
                            "done_set_hash must change when a task is marked done")

    def test_legacy_config_defaults_unchanged(self):
        """The default config knobs that existed before beyond-sdd still return their defaults.

        This guards against the beyond-sdd changes accidentally altering existing
        config defaults (e.g. notify.level, docs.always_apply).
        Failure class: beyond-sdd changes DEFAULTS dict → existing config callers break.
        """
        repo_dir = tempfile.mkdtemp(prefix="z-harness-legacy-")
        xdg = tempfile.mkdtemp(prefix="z-harness-legacy-xdg-")
        try:
            repo_cfg = _write_repo_config(repo_dir, "")
            for key, expected in [
                ("notify.level", "approval_only"),
                ("docs.always_apply", "always"),
                ("workflow.audit_to_amend", "ask"),
                ("workflow.slug_confirm", "ask"),
            ]:
                with self.subTest(key=key):
                    r = _run_config(
                        "get", key,
                        env_extra={
                            "XDG_CONFIG_HOME": xdg,
                            "Z_HARNESS_REPO_CONFIG": repo_cfg,
                        },
                    )
                    self.assertEqual(r.returncode, 0, msg=f"{key}: {r.stderr}")
                    self.assertEqual(r.stdout.strip(), expected,
                                     f"Legacy default for {key!r} must be {expected!r}; "
                                     f"got {r.stdout.strip()!r}")
        finally:
            shutil.rmtree(repo_dir, ignore_errors=True)
            shutil.rmtree(xdg, ignore_errors=True)


# ---------------------------------------------------------------------------
# (f) TestHermesGatedOff
# ---------------------------------------------------------------------------

class TestHermesGatedOff(unittest.TestCase):
    """workflow.hermes_enabled is false by default; HERMES_* env vars don't affect it.

    Invariant: hermes_enabled defaults to False — old Hermes machinery is gated off
    unless a user explicitly opts in via config file (not env).
    Failure class: hermes_enabled defaults to True → old Hermes machinery fires on
    every run, breaking plans that were designed for the new BFS path.
    """

    def setUp(self):
        self.repo_dir = tempfile.mkdtemp(prefix="z-harness-hermes-")
        self.xdg = tempfile.mkdtemp(prefix="z-harness-hermes-xdg-")

    def tearDown(self):
        shutil.rmtree(self.repo_dir, ignore_errors=True)
        shutil.rmtree(self.xdg, ignore_errors=True)

    def _get_hermes_enabled(self, extra_env: dict | None = None) -> str:
        repo_cfg = _write_repo_config(self.repo_dir, "")
        env = {"XDG_CONFIG_HOME": self.xdg, "Z_HARNESS_REPO_CONFIG": repo_cfg}
        if extra_env:
            env.update(extra_env)
        r = _run_config("get", "workflow.hermes_enabled", env_extra=env)
        self.assertEqual(r.returncode, 0, msg=r.stderr)
        return r.stdout.strip()

    def test_hermes_enabled_default_is_false(self):
        """Default workflow.hermes_enabled must be 'false' (Hermes gated off)."""
        val = self._get_hermes_enabled()
        self.assertEqual(val, "false",
                         "HARD INVARIANT: hermes_enabled must default to false. "
                         "If true, the old Hermes machinery fires on every run.")

    def test_hermes_env_var_does_not_activate_hermes_enabled(self):
        """HERMES_MAX_PARALLEL env var has no effect on workflow.hermes_enabled.

        The hermes_enabled knob is NOT an HERMES_* env var — it's
        Z_HARNESS_WORKFLOW_HERMES_ENABLED. HERMES_* vars govern hermes/config.py
        (concurrency), not the workflow gate.
        """
        val = self._get_hermes_enabled(extra_env={"HERMES_MAX_PARALLEL": "4"})
        self.assertEqual(val, "false",
                         "HERMES_MAX_PARALLEL must not affect workflow.hermes_enabled")

    def test_hermes_enabled_can_be_set_true_via_file(self):
        """Explicit opt-in via file sets hermes_enabled to true."""
        repo_cfg = _write_repo_config(self.repo_dir, "[workflow]\nhermes_enabled = true\n")
        r = _run_config(
            "get", "workflow.hermes_enabled",
            env_extra={
                "XDG_CONFIG_HOME": self.xdg,
                "Z_HARNESS_REPO_CONFIG": repo_cfg,
            },
        )
        self.assertEqual(r.returncode, 0, msg=r.stderr)
        self.assertEqual(r.stdout.strip(), "true")

    def test_hermes_enabled_cannot_be_set_via_hermes_env_vars(self):
        """HERMES_ENABLED (not a z-harness var) has no effect on workflow.hermes_enabled."""
        val = self._get_hermes_enabled(extra_env={"HERMES_ENABLED": "1"})
        self.assertEqual(val, "false",
                         "HERMES_ENABLED env var must not activate workflow.hermes_enabled")


if __name__ == "__main__":
    unittest.main()
