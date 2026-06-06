"""Acceptance integration test: per-adapter wiring of the injected-env bundle (T013).

The acceptance criterion is:

    An ephemeral inject for one host produces a launch env whose
    Z_HARNESS_PLAN_DIR byte-matches ``scripts/plan-path.sh`` output,
    and config keys match ``config.py export-env``.
    Installed (in_place) mode must leave plan/config bundle keys intact
    in Injection.env even though no session file is written.

How the wiring works:
  1. The caller (e.g. ``commands/launch.py``) calls
     ``env_bundle.resolve_env_bundle(project_root, host, "ephemeral")``.
  2. The bundle dict is passed verbatim as the ``state_env`` argument to
     ``adapter.inject(state_env, mode="ephemeral", project=...)``.
  3. Each adapter calls ``env.update(state_env)`` so every key in the
     bundle lands in ``Injection.env``.
  4. The adapter adds the host-appropriate plugin-root on top (ephemeral only
     for ClaudeAdapter; all modes for the others).

This file tests step 2-3 across all four adapters (claude, antigravity,
cursor, codex) for both ephemeral and in_place modes.

Project-root correctness check
-------------------------------
``resolve_env_bundle`` is called with ``self.project`` (the temp project root),
NOT with ``REPO_ROOT`` (the harness repo root).  A distinctive
``.z-harness/config.toml`` is planted in the temp project so that the config
subprocess runs with cwd=project and picks up the repo-local override.  If the
wrong root were passed the planted key would NOT appear in Injection.env and
the test would FAIL — this is the detection mechanism for cwd wiring bugs.

The planted key is ``notify.level = "off"`` (non-default; default is
``"approval_only"``).  It exports as ``Z_HARNESS_NOTIFY_LEVEL=off``.

Hermetic Z_HARNESS_BASE_DIR pinning
------------------------------------
All tests inherit from ``_HermeticEnvCase`` which pins ``Z_HARNESS_BASE_DIR``
to a private tmpdir for the duration of each test.  This guarantees that
``plan-path.sh z_harness_base`` returns a test-controlled path and never
touches the developer's real state directory.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Callable, Any

# ---------------------------------------------------------------------------
# Path setup: ensure the harness repo root is on sys.path so adapters can be
# imported even when pytest is invoked from outside the repo.
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).parent.parent.parent.resolve()
sys.path.insert(0, str(REPO_ROOT))

from z_harness_cli.adapters.claude import ClaudeAdapter
from z_harness_cli.adapters.antigravity import AntigravityAdapter
from z_harness_cli.adapters.cursor import CursorAdapter
from z_harness_cli.adapters.codex import CodexAdapter
from z_harness_cli.env_bundle import (
    _parse_export_env_lines,
    resolve_env_bundle,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _git_init(path: Path) -> None:
    subprocess.run(["git", "-C", str(path), "init", "-q"], check=True)


def _plant_repo_config(project: Path, *, notify_level: str = "off") -> None:
    """Write a .z-harness/config.toml in *project* with a distinctive value.

    The planted ``notify.level`` overrides the default (``"approval_only"``)
    so ``config.py export-env`` run from *project* emits
    ``Z_HARNESS_NOTIFY_LEVEL=<notify_level>``.  Any test that passes the wrong
    cwd to config.py will not see this override and the assertion will fail.
    """
    zh_dir = project / ".z-harness"
    zh_dir.mkdir(parents=True, exist_ok=True)
    config_path = zh_dir / "config.toml"
    config_path.write_text(
        f'schema_version = 1\n\n[notify]\nlevel = "{notify_level}"\n',
        encoding="utf-8",
    )


def _hermetic_base_dir() -> str:
    """Return the path to the pinned Z_HARNESS_BASE_DIR for the current test run."""
    xdg = os.environ.get("XDG_STATE_HOME", tempfile.gettempdir())
    base = os.path.join(xdg, "z-harness-test-bundle-wiring")
    os.makedirs(base, exist_ok=True)
    return base


def _scripts_available() -> bool:
    plan_sh = REPO_ROOT / "scripts" / "plan-path.sh"
    config_py = REPO_ROOT / "scripts" / "config.py"
    return plan_sh.exists() and config_py.exists()


# ---------------------------------------------------------------------------
# Base class: pins Z_HARNESS_BASE_DIR in setUp / tears it down in tearDown
# ---------------------------------------------------------------------------

class _HermeticEnvCase(unittest.TestCase):
    """Subclasses get a hermetically-pinned Z_HARNESS_BASE_DIR for the test."""

    def setUp(self) -> None:
        self._orig_base_dir = os.environ.get("Z_HARNESS_BASE_DIR")
        self._test_base_dir = _hermetic_base_dir()
        os.environ["Z_HARNESS_BASE_DIR"] = self._test_base_dir

    def tearDown(self) -> None:
        if self._orig_base_dir is None:
            os.environ.pop("Z_HARNESS_BASE_DIR", None)
        else:
            os.environ["Z_HARNESS_BASE_DIR"] = self._orig_base_dir

    def _skip_if_scripts_missing(self) -> None:
        if not _scripts_available():
            self.skipTest("scripts/plan-path.sh or scripts/config.py not present")


# ---------------------------------------------------------------------------
# Shared wiring assertions (used by all four adapter test classes)
# ---------------------------------------------------------------------------

class _AdapterWiringMixin:
    """Mixin providing the standard bundle-wiring assertion methods.

    Concrete test classes must set:
      self.adapter   — adapter instance
      self.project   — Path to a git-initialised tmp project with a planted
                       .z-harness/config.toml (notify.level = "off")
      self.host_name — string host identifier ("claude", "antigravity", ...)

    Concrete classes must also inherit from _HermeticEnvCase (which provides
    _skip_if_scripts_missing, setUp, tearDown with Z_HARNESS_BASE_DIR pinning).
    """

    adapter: Any
    project: Path
    host_name: str

    # The planted notify.level value; must differ from the default ("approval_only").
    PLANTED_NOTIFY_LEVEL: str = "off"
    PLANTED_ENV_KEY: str = "Z_HARNESS_NOTIFY_LEVEL"
    PLANTED_ENV_VALUE: str = "off"

    def _inject_ephemeral(self) -> Any:
        bundle = resolve_env_bundle(self.project, self.host_name, "ephemeral")
        return self.adapter.inject(bundle, "ephemeral", self.project)

    def _inject_in_place(self) -> Any:
        # env_bundle uses "installed" as the mode name (vs adapter.inject()'s "in_place").
        # "installed" tells resolve_env_bundle not to inject the plugin-root into the
        # bundle — the installed host plugin resolves that itself.
        bundle = resolve_env_bundle(self.project, self.host_name, "installed")
        return self.adapter.inject(bundle, "in_place", self.project)

    # ------------------------------------------------------------------
    # Ephemeral mode tests
    # ------------------------------------------------------------------

    def test_plan_dir_byte_matches_plan_path_sh(self) -> None:
        """Z_HARNESS_PLAN_DIR in Injection.env byte-matches plan-path.sh.

        Split-brain guard: if the adapter injects a different plan dir than
        the one log-event.sh would compute, telemetry from the CLI and from
        the spawned host would land in different directories.
        """
        self._skip_if_scripts_missing()

        script = REPO_ROOT / "scripts" / "plan-path.sh"
        hermetic_env = os.environ.copy()
        # Z_HARNESS_BASE_DIR is already set by _HermeticEnvCase.setUp.
        ref = subprocess.run(
            ["bash", str(script), "z_harness_base"],
            cwd=str(self.project),
            capture_output=True,
            text=True,
            env=hermetic_env,
        )
        if ref.returncode != 0:
            self.skipTest(f"plan-path.sh failed: {ref.stderr.strip()}")
        expected_plan_dir = ref.stdout.strip()
        self.assertTrue(expected_plan_dir, "plan-path.sh returned empty output")

        inj = self._inject_ephemeral()
        try:
            self.assertEqual(
                inj.env.get("Z_HARNESS_PLAN_DIR"),
                expected_plan_dir,
                "Z_HARNESS_PLAN_DIR in Injection.env does not byte-match "
                f"plan-path.sh output for host={self.host_name}",
            )
        finally:
            self.adapter.cleanup(inj)

    def test_project_local_config_key_survives_inject(self) -> None:
        """A repo-local .z-harness/config.toml override appears in Injection.env.

        This is the cwd-wiring correctness test (MAJOR 1 fix).
        resolve_env_bundle() is called with self.project so config.py runs
        with cwd=self.project and reads the planted .z-harness/config.toml.
        If the wrong root were passed the planted override would be absent
        and this test would FAIL — exposing the wiring bug.
        """
        self._skip_if_scripts_missing()

        inj = self._inject_ephemeral()
        try:
            self.assertIn(
                self.PLANTED_ENV_KEY,
                inj.env,
                f"{self.PLANTED_ENV_KEY!r} from project-local config.toml is "
                f"absent in Injection.env — cwd was probably wrong in "
                f"resolve_env_bundle() or config.py subprocess call",
            )
            self.assertEqual(
                inj.env[self.PLANTED_ENV_KEY],
                self.PLANTED_ENV_VALUE,
                f"{self.PLANTED_ENV_KEY!r} has wrong value: expected "
                f"{self.PLANTED_ENV_VALUE!r} (from planted config.toml) "
                f"but got {inj.env.get(self.PLANTED_ENV_KEY)!r}",
            )
        finally:
            self.adapter.cleanup(inj)

    def test_bundle_keys_not_overwritten_by_inject(self) -> None:
        """state_env keys survive inject() — inject() must not overwrite them."""
        self._skip_if_scripts_missing()

        bundle = resolve_env_bundle(self.project, self.host_name, "ephemeral")
        sentinel = f"/tmp/zh-wiring-sentinel-{self.host_name}"
        bundle["Z_HARNESS_PLAN_DIR"] = sentinel

        inj = self.adapter.inject(bundle, "ephemeral", self.project)
        try:
            self.assertEqual(
                inj.env.get("Z_HARNESS_PLAN_DIR"),
                sentinel,
                f"inject() must not overwrite Z_HARNESS_PLAN_DIR set in state_env "
                f"(host={self.host_name})",
            )
        finally:
            self.adapter.cleanup(inj)

    # ------------------------------------------------------------------
    # Installed (in_place) mode tests — MAJOR 2
    # ------------------------------------------------------------------

    def test_in_place_plan_dir_bundle_key_present(self) -> None:
        """Z_HARNESS_PLAN_DIR is present in Injection.env for in_place mode.

        Installed-mode must NOT lose the plan/config bundle keys even though
        no session file is written by the CLI.
        """
        self._skip_if_scripts_missing()

        inj = self._inject_in_place()
        try:
            self.assertIn(
                "Z_HARNESS_PLAN_DIR",
                inj.env,
                "Z_HARNESS_PLAN_DIR must survive into Injection.env in in_place "
                f"(installed) mode (host={self.host_name})",
            )
            # Value must be non-empty
            self.assertTrue(
                inj.env["Z_HARNESS_PLAN_DIR"],
                "Z_HARNESS_PLAN_DIR must be non-empty in in_place mode",
            )
        finally:
            self.adapter.cleanup(inj)

    def test_in_place_project_local_config_key_survives(self) -> None:
        """Project-local config key is in Injection.env for in_place mode.

        The plan/config layer of the bundle must be present regardless of
        injection mode.  A wrong-cwd call would produce the wrong config
        value and fail this assertion.
        """
        self._skip_if_scripts_missing()

        inj = self._inject_in_place()
        try:
            self.assertIn(
                self.PLANTED_ENV_KEY,
                inj.env,
                f"{self.PLANTED_ENV_KEY!r} from project-local config.toml is "
                f"absent in Injection.env (in_place mode, host={self.host_name})",
            )
            self.assertEqual(
                inj.env[self.PLANTED_ENV_KEY],
                self.PLANTED_ENV_VALUE,
                f"{self.PLANTED_ENV_KEY!r} has wrong value in in_place mode: "
                f"expected {self.PLANTED_ENV_VALUE!r} got "
                f"{inj.env.get(self.PLANTED_ENV_KEY)!r}",
            )
        finally:
            self.adapter.cleanup(inj)

    def test_in_place_bundle_keys_not_overwritten(self) -> None:
        """state_env keys survive inject() in in_place mode."""
        self._skip_if_scripts_missing()

        # env_bundle uses "installed" for the mode that corresponds to in_place injection.
        bundle = resolve_env_bundle(self.project, self.host_name, "installed")
        sentinel = f"/tmp/zh-inplace-sentinel-{self.host_name}"
        bundle["Z_HARNESS_PLAN_DIR"] = sentinel

        inj = self.adapter.inject(bundle, "in_place", self.project)
        try:
            self.assertEqual(
                inj.env.get("Z_HARNESS_PLAN_DIR"),
                sentinel,
                f"inject() must not overwrite Z_HARNESS_PLAN_DIR in in_place mode "
                f"(host={self.host_name})",
            )
        finally:
            self.adapter.cleanup(inj)


# ---------------------------------------------------------------------------
# ClaudeAdapter wiring
# ---------------------------------------------------------------------------

class TestClaudeAdapterBundleWiring(_AdapterWiringMixin, _HermeticEnvCase):
    """The full resolve_env_bundle → ClaudeAdapter.inject() wiring is correct."""

    host_name = "claude"

    def setUp(self) -> None:
        super().setUp()
        self._tmp = tempfile.TemporaryDirectory(prefix="zh-bundle-wiring-claude-")
        self.project = Path(self._tmp.name).resolve()
        _git_init(self.project)
        _plant_repo_config(self.project, notify_level=self.PLANTED_NOTIFY_LEVEL)
        self.adapter = ClaudeAdapter()

    def tearDown(self) -> None:
        self._tmp.cleanup()
        super().tearDown()

    def test_plugin_root_present_in_ephemeral_injection(self) -> None:
        """CLAUDE_PLUGIN_ROOT is set in Injection.env for ephemeral mode."""
        self._skip_if_scripts_missing()

        inj = self._inject_ephemeral()
        try:
            self.assertIn(
                "CLAUDE_PLUGIN_ROOT",
                inj.env,
                "CLAUDE_PLUGIN_ROOT must be in Injection.env for ephemeral mode (D14)",
            )
            self.assertTrue(
                Path(inj.env["CLAUDE_PLUGIN_ROOT"]).is_absolute(),
                "CLAUDE_PLUGIN_ROOT must be an absolute path",
            )
        finally:
            self.adapter.cleanup(inj)

    def test_in_place_plugin_root_not_overridden_by_cli(self) -> None:
        """ClaudeAdapter does NOT override CLAUDE_PLUGIN_ROOT in in_place mode.

        For installed mode the host's own environment provides CLAUDE_PLUGIN_ROOT.
        The CLI must not replace it with the harness root.  We verify this by
        setting a sentinel value in os.environ before calling inject() and
        confirming the sentinel is preserved.
        """
        self._skip_if_scripts_missing()

        sentinel_root = "/tmp/zh-test-installed-plugin-root-sentinel"
        saved = os.environ.get("CLAUDE_PLUGIN_ROOT")
        os.environ["CLAUDE_PLUGIN_ROOT"] = sentinel_root
        try:
            inj = self._inject_in_place()
            try:
                self.assertEqual(
                    inj.env.get("CLAUDE_PLUGIN_ROOT"),
                    sentinel_root,
                    "ClaudeAdapter.inject() must NOT replace CLAUDE_PLUGIN_ROOT "
                    "in in_place mode — the installed plugin's value must be preserved "
                    f"(expected sentinel {sentinel_root!r})",
                )
            finally:
                self.adapter.cleanup(inj)
        finally:
            if saved is None:
                os.environ.pop("CLAUDE_PLUGIN_ROOT", None)
            else:
                os.environ["CLAUDE_PLUGIN_ROOT"] = saved


# ---------------------------------------------------------------------------
# AntigravityAdapter wiring — covers the ANTIGRAVITY_PLUGIN_ROOT branch
# ---------------------------------------------------------------------------

class TestAntigravityAdapterBundleWiring(_AdapterWiringMixin, _HermeticEnvCase):
    """The ANTIGRAVITY_PLUGIN_ROOT branch of the wiring is correct."""

    host_name = "antigravity"

    def setUp(self) -> None:
        super().setUp()
        self._tmp = tempfile.TemporaryDirectory(prefix="zh-bundle-wiring-agy-")
        self.project = Path(self._tmp.name).resolve()
        _git_init(self.project)
        _plant_repo_config(self.project, notify_level=self.PLANTED_NOTIFY_LEVEL)
        self.adapter = AntigravityAdapter()

    def tearDown(self) -> None:
        self._tmp.cleanup()
        super().tearDown()

    def test_antigravity_plugin_root_injected_not_claude(self) -> None:
        """ANTIGRAVITY_PLUGIN_ROOT is set (not CLAUDE_PLUGIN_ROOT) for agy (D14)."""
        self._skip_if_scripts_missing()

        inj = self._inject_ephemeral()
        try:
            self.assertIn(
                "ANTIGRAVITY_PLUGIN_ROOT",
                inj.env,
                "ANTIGRAVITY_PLUGIN_ROOT must be set for antigravity host (D14)",
            )
        finally:
            self.adapter.cleanup(inj)

    def test_in_place_antigravity_plugin_root_present(self) -> None:
        """ANTIGRAVITY_PLUGIN_ROOT is set even for in_place mode (agy sets it unconditionally)."""
        self._skip_if_scripts_missing()

        inj = self._inject_in_place()
        try:
            self.assertIn(
                "ANTIGRAVITY_PLUGIN_ROOT",
                inj.env,
                "ANTIGRAVITY_PLUGIN_ROOT must be set in in_place mode for agy",
            )
        finally:
            self.adapter.cleanup(inj)


# ---------------------------------------------------------------------------
# CursorAdapter wiring — distinct home/.config isolation (advisory coverage)
# ---------------------------------------------------------------------------

class TestCursorAdapterBundleWiring(_AdapterWiringMixin, _HermeticEnvCase):
    """CursorAdapter wiring: .cursor/rules/.mdc injection, CLAUDE_PLUGIN_ROOT."""

    host_name = "cursor"

    def setUp(self) -> None:
        super().setUp()
        self._tmp = tempfile.TemporaryDirectory(prefix="zh-bundle-wiring-cursor-")
        self.project = Path(self._tmp.name).resolve()
        _git_init(self.project)
        _plant_repo_config(self.project, notify_level=self.PLANTED_NOTIFY_LEVEL)
        self.adapter = CursorAdapter()

    def tearDown(self) -> None:
        self._tmp.cleanup()
        super().tearDown()

    def test_claude_plugin_root_injected_for_cursor(self) -> None:
        """CLAUDE_PLUGIN_ROOT is set for cursor (D14: cursor reads this var)."""
        self._skip_if_scripts_missing()

        inj = self._inject_ephemeral()
        try:
            self.assertIn(
                "CLAUDE_PLUGIN_ROOT",
                inj.env,
                "CLAUDE_PLUGIN_ROOT must be in Injection.env for cursor ephemeral (D14)",
            )
        finally:
            self.adapter.cleanup(inj)


# ---------------------------------------------------------------------------
# CodexAdapter wiring — distinct home/.config isolation (advisory coverage)
# ---------------------------------------------------------------------------

class TestCodexAdapterBundleWiring(_AdapterWiringMixin, _HermeticEnvCase):
    """CodexAdapter wiring: AGENTS.md injection, CLAUDE_PLUGIN_ROOT."""

    host_name = "codex"

    def setUp(self) -> None:
        super().setUp()
        self._tmp = tempfile.TemporaryDirectory(prefix="zh-bundle-wiring-codex-")
        self.project = Path(self._tmp.name).resolve()
        _git_init(self.project)
        _plant_repo_config(self.project, notify_level=self.PLANTED_NOTIFY_LEVEL)
        # CodexAdapter.inject() calls codex mcp add as a best-effort side-effect.
        # We pass mcp_config_path to a non-existent path so the MCP step silently
        # skips without shelling out to the real codex binary.
        self.adapter = CodexAdapter()
        self._mcp_config_path = "/dev/null/no-mcp-config-for-test"

    def tearDown(self) -> None:
        self._tmp.cleanup()
        super().tearDown()

    def _inject_ephemeral(self) -> Any:
        bundle = resolve_env_bundle(self.project, self.host_name, "ephemeral")
        return self.adapter.inject(
            bundle, "ephemeral", self.project,
            mcp_config_path=self._mcp_config_path,
        )

    def _inject_in_place(self) -> Any:
        # env_bundle uses "installed" as the mode name for no-plugin-root injection.
        bundle = resolve_env_bundle(self.project, self.host_name, "installed")
        return self.adapter.inject(
            bundle, "in_place", self.project,
            mcp_config_path=self._mcp_config_path,
        )

    def test_claude_plugin_root_injected_for_codex(self) -> None:
        """CLAUDE_PLUGIN_ROOT is set for codex (D14)."""
        self._skip_if_scripts_missing()

        inj = self._inject_ephemeral()
        try:
            self.assertIn(
                "CLAUDE_PLUGIN_ROOT",
                inj.env,
                "CLAUDE_PLUGIN_ROOT must be in Injection.env for codex ephemeral (D14)",
            )
        finally:
            self.adapter.cleanup(inj)


if __name__ == "__main__":
    unittest.main()
