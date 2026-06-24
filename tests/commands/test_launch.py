"""Tests for z_harness_cli/commands/launch.py (T015, Model B).

Covers the postmortem-proof surface and the enumerated acceptance criteria:

  * non-git dir → exit 1 with an export-mode hint (F3 precondition).
  * --quiet suppresses the fidelity banner; default prints it.
  * clobber preflight (ClobberRefused from inject) → exit 1 without --force.
  * cleanup callback is wired into the PTY launch and runs on the launch path.
  * cleanup runs EXACTLY ONCE (no double-clean) even when the launch path and
    the post-launch safety net both fire.
  * RestoreError from cleanup propagates (is NOT swallowed) per the T021 note.
  * correct mode pairing: resolve_env_bundle is called with the SAME mode that
    is passed to adapter.inject() ("in_place"), and env_bundle accepts it as an
    alias of "installed" (the footgun reconciliation).
  * crash-interrupted restore is recovered on startup via detect_orphans+cleanup.

PTY exec is always stubbed via ``patch("z_harness_cli.pty_launch.pty_launch")``
so no real host process is spawned (adapters lazy-import pty_launch, and
launch.py wraps the module function for the single real spawn).
"""

from __future__ import annotations

import io
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import typer

# Ensure repo root on sys.path.
REPO_ROOT = Path(__file__).parent.parent.parent.resolve()
sys.path.insert(0, str(REPO_ROOT))

from z_harness_cli import inject_safety  # noqa: E402
from z_harness_cli.commands import launch as launch_mod  # noqa: E402
from z_harness_cli.adapters import registry  # noqa: E402
from z_harness_cli.adapters.base import DetectResult  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _git_init(path: Path) -> None:
    subprocess.run(["git", "-C", str(path), "init", "-q"], check=True)


def _fake_adapter(name: str = "claude", fidelity: str = "native"):
    """Build a MagicMock adapter with the attributes launch.py reads.

    ``inject`` mirrors the real adapter contract: it merges the passed env
    bundle into ``injection.env`` so a plugin-root that resolve_env_bundle put
    in the bundle (ephemeral mode, D14) actually reaches the child env handed to
    pty_launch.  The returned ``injection`` is a fixed handle so cleanup
    identity assertions still work.
    """
    adapter = MagicMock()
    adapter.name = name
    adapter.fidelity_tier = fidelity
    # inject() returns an Injection-like object carrying .env and is cleaned up
    # via adapter.cleanup(injection).
    injection = MagicMock()
    injection.env = {"PATH": "/usr/bin", "Z_HARNESS_PLAN_DIR": "/tmp/state"}

    def _inject(state_env, mode, project):
        # Real adapters merge the bundle into the child env; reflect that so a
        # plugin-root present in the ephemeral bundle propagates to injection.env.
        injection.env = {**injection.env, **dict(state_env)}
        return injection

    adapter.inject.side_effect = _inject
    # launch() blocks until the host exits and returns its exit code.  By default
    # it calls the (patched) pty_launch so the cleanup wiring is exercised.
    return adapter, injection


# ---------------------------------------------------------------------------
# F3 precondition: non-git dir
# ---------------------------------------------------------------------------


class NonGitPreconditionTest(unittest.TestCase):
    def test_non_git_dir_exits_1_with_export_hint(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(typer.Exit) as ctx_exit:
                launch_mod.run(
                    ctx=MagicMock(),
                    host="claude",
                    project=tmp,
                    quiet=True,
                )
            self.assertEqual(ctx_exit.exception.exit_code, 1)

    def test_non_git_dir_message_mentions_export(self):
        # Capture stderr to verify the export-mode hint is surfaced (never silent).
        with tempfile.TemporaryDirectory() as tmp:
            from io import StringIO

            buf = StringIO()
            with patch("typer.echo", side_effect=lambda msg, **kw: buf.write(str(msg))):
                with self.assertRaises(typer.Exit):
                    launch_mod.run(
                        ctx=MagicMock(), host="claude", project=tmp, quiet=True
                    )
            self.assertIn("export", buf.getvalue().lower())
            self.assertIn("git", buf.getvalue().lower())


# ---------------------------------------------------------------------------
# Happy-path + cleanup wiring (git repo, stubbed pty_launch)
# ---------------------------------------------------------------------------


class GitRepoLaunchCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.project = Path(self._tmp.name).resolve()
        _git_init(self.project)

    def tearDown(self):
        self._tmp.cleanup()

    def _patch_pty(self, exit_code: int = 0):
        """Patch pty_launch so the captured cleanup callback runs once (as the
        real pty_launch does in its finally block) and record the child env that
        reached the spawn (so plugin-root injection can be asserted)."""

        def _fake_pty_launch(argv, env, cwd, cleanup=None):
            self.captured_env = dict(env)
            if cleanup is not None:
                cleanup()
            return exit_code

        return patch("z_harness_cli.pty_launch.pty_launch", side_effect=_fake_pty_launch)

    def _ephemeral_bundle(self, host: str) -> dict:
        """A realistic ephemeral env bundle: includes the host plugin-root (D14)."""
        from z_harness_cli.env_bundle import resolve_plugin_root_env

        bundle = {"Z_HARNESS_PLAN_DIR": "/tmp/state"}
        bundle.update(resolve_plugin_root_env(host, "ephemeral", harness_root="/x"))
        return bundle

    def _run_with(self, adapter, *, quiet=True, exit_code=0):
        """Wire registry.select + env_bundle + adapter.launch and run()."""
        self.captured_env = None
        # adapter.launch must delegate to the (patched) module pty_launch so the
        # cleanup wiring in launch.py is exercised.
        def _adapter_launch(project, env):
            from z_harness_cli import pty_launch as _pty

            return _pty.pty_launch([adapter.name], env, project)

        adapter.launch.side_effect = _adapter_launch

        with patch.object(
            registry, "select", return_value=(adapter, DetectResult(installed=True))
        ), patch(
            "z_harness_cli.env_bundle.resolve_env_bundle",
            return_value=self._ephemeral_bundle(adapter.name),
        ) as mock_bundle, self._patch_pty(exit_code=exit_code) as mock_pty:
            rc = launch_mod.run(
                ctx=MagicMock(),
                host=adapter.name,
                project=str(self.project),
                quiet=quiet,
            )
        return rc, mock_bundle, mock_pty

    # -- cleanup runs on the launch path -----------------------------------

    def test_cleanup_invoked_on_launch_path(self):
        adapter, injection = _fake_adapter()
        rc, _, _ = self._run_with(adapter)
        self.assertEqual(rc, 0)
        adapter.cleanup.assert_called()
        # The cleanup was called with the injection produced by inject().
        adapter.cleanup.assert_called_with(injection)

    def test_cleanup_runs_exactly_once(self):
        # pty_launch fires cleanup AND the post-launch safety net fires it again;
        # the one-shot guard must collapse those into a single real cleanup.
        adapter, injection = _fake_adapter()
        rc, _, _ = self._run_with(adapter)
        self.assertEqual(rc, 0)
        self.assertEqual(
            adapter.cleanup.call_count,
            1,
            "cleanup must run exactly once (no double-clean)",
        )

    # -- mode pairing -------------------------------------------------------

    def test_resolve_bundle_and_inject_share_ephemeral_mode(self):
        # launch is ALWAYS the gitignored/ephemeral path (SPEC.md:115-116); there
        # is no --in-place flag here.  Both resolve_env_bundle AND adapter.inject
        # must receive "ephemeral" so the gitignored config is written and (D14,
        # SPEC.md:151-155) the host plugin-root env var is injected.
        adapter, _ = _fake_adapter()
        _, mock_bundle, _ = self._run_with(adapter)
        # resolve_env_bundle(project, host, mode) — mode is the 3rd positional.
        bundle_mode = mock_bundle.call_args.args[2]
        # inject(state_env, mode, project) — mode is the 2nd positional.
        inject_mode = adapter.inject.call_args.args[1]
        self.assertEqual(bundle_mode, "ephemeral")
        self.assertEqual(inject_mode, "ephemeral")
        self.assertEqual(bundle_mode, inject_mode)

    def test_ephemeral_launch_injects_plugin_root_into_child_env(self):
        # D14 (SPEC.md:151-155): an ephemeral launch MUST inject the
        # host-appropriate plugin-root env var, or /z-* commands fail after the
        # PTY hands over.  Assert a plugin-root var actually reaches the child env
        # handed to pty_launch (not just the bundle).
        for host, expected_var in (
            ("claude", "CLAUDE_PLUGIN_ROOT"),
            ("antigravity", "ANTIGRAVITY_PLUGIN_ROOT"),
            ("omp", "OMP_PLUGIN_ROOT"),
        ):
            with self.subTest(host=host):
                adapter, _ = _fake_adapter(name=host)
                self._run_with(adapter)
                self.assertIsNotNone(
                    self.captured_env,
                    "pty_launch was never called; child env not captured",
                )
                self.assertIn(
                    expected_var,
                    self.captured_env,
                    f"{expected_var} must be injected for an ephemeral {host} launch",
                )

    def test_real_omp_launch_gets_scoped_runtime_env_and_cleans_session_file(self):
        from z_harness_cli.adapters.omp import OmpAdapter

        adapter = OmpAdapter()
        bundle = {"Z_HARNESS_PLAN_DIR": "/tmp/state", "OMP_PLUGIN_ROOT": "/bundle/root"}
        expected_plugin_root = str(self.project / ".omp" / "z-harness")
        with patch.object(
            registry, "select", return_value=(adapter, DetectResult(installed=True))
        ), patch(
            "z_harness_cli.env_bundle.resolve_env_bundle",
            return_value=bundle,
        ) as mock_bundle, patch.dict(
            "os.environ",
            {
                "PATH": "/usr/bin",
                "CLAUDE_PLUGIN_ROOT": "/wrong/claude",
                "ANTIGRAVITY_PLUGIN_ROOT": "/wrong/agy",
            },
            clear=True,
        ), self._patch_pty() as mock_pty:
            rc = launch_mod.run(
                ctx=MagicMock(),
                host="omp",
                project=str(self.project),
                quiet=True,
            )

        self.assertEqual(rc, 0)
        mock_bundle.assert_called_once_with(self.project, "omp", "ephemeral")
        self.assertIsNotNone(self.captured_env)
        self.assertEqual(self.captured_env["OMP_PLUGIN_ROOT"], expected_plugin_root)
        self.assertEqual(self.captured_env["Z_HARNESS_PLAN_DIR"], "/tmp/state")
        self.assertNotIn("CLAUDE_PLUGIN_ROOT", self.captured_env)
        self.assertNotIn("ANTIGRAVITY_PLUGIN_ROOT", self.captured_env)
        self.assertFalse((self.project / ".omp" / "z-harness" / "session.yml").exists())
        self.assertFalse((self.project / ".omp" / "z-harness").exists())
        self.assertEqual(mock_pty.call_args.args[2], self.project)

    def test_omp_launch_output_does_not_expose_runtime_env_or_secret_values(self):
        from z_harness_cli.adapters.omp import OmpAdapter

        adapter = OmpAdapter()
        secret_bundle = {
            "Z_HARNESS_PLAN_DIR": "/tmp/state",
            "OMP_PLUGIN_ROOT": "/secret/plugin-root",
            "Z_HARNESS_OAUTH_TOKEN": "oauth-secret-value",
            "Z_HARNESS_MODEL": "model-secret-value",
            "Z_HARNESS_PROFILE": "profile-secret-value",
        }
        stderr = io.StringIO()
        stdout = io.StringIO()
        with patch.object(
            registry, "select", return_value=(adapter, DetectResult(installed=True))
        ), patch(
            "z_harness_cli.env_bundle.resolve_env_bundle",
            return_value=secret_bundle,
        ), patch.dict(
            "os.environ",
            {"PATH": "/usr/bin"},
            clear=True,
        ), self._patch_pty(), patch(
            "sys.stderr", stderr
        ), patch(
            "sys.stdout", stdout
        ):
            rc = launch_mod.run(
                ctx=MagicMock(),
                host="omp",
                project=str(self.project),
                quiet=False,
            )

        self.assertEqual(rc, 0)
        output = stdout.getvalue() + stderr.getvalue()
        for forbidden in (
            "/secret/plugin-root",
            "oauth-secret-value",
            "model-secret-value",
            "profile-secret-value",
            "Z_HARNESS_OAUTH_TOKEN",
            "Z_HARNESS_MODEL",
            "Z_HARNESS_PROFILE",
        ):
            self.assertNotIn(forbidden, output)

    # -- exit code passthrough ---------------------------------------------

    def test_host_exit_code_propagates(self):
        adapter, _ = _fake_adapter()
        rc, _, _ = self._run_with(adapter, exit_code=7)
        self.assertEqual(rc, 7)

    # -- --quiet suppresses banner -----------------------------------------

    def test_quiet_suppresses_banner(self):
        adapter, _ = _fake_adapter()
        with patch.object(launch_mod, "_print_fidelity_banner") as banner:
            self._run_with(adapter, quiet=True)
            banner.assert_not_called()

    def test_default_prints_banner(self):
        adapter, _ = _fake_adapter()
        with patch.object(launch_mod, "_print_fidelity_banner") as banner:
            self._run_with(adapter, quiet=False)
            banner.assert_called_once()

    # -- clobber preflight --------------------------------------------------

    def test_clobber_refused_exits_1(self):
        adapter, _ = _fake_adapter()
        adapter.inject.side_effect = inject_safety.ClobberRefused(
            [self.project / "CLAUDE.md"]
        )
        with patch.object(
            registry, "select", return_value=(adapter, DetectResult(installed=True))
        ), patch(
            "z_harness_cli.env_bundle.resolve_env_bundle",
            return_value={"Z_HARNESS_PLAN_DIR": "/tmp/state"},
        ), self._patch_pty():
            with self.assertRaises(typer.Exit) as ctx_exit:
                launch_mod.run(
                    ctx=MagicMock(),
                    host="claude",
                    project=str(self.project),
                    quiet=True,
                )
            self.assertEqual(ctx_exit.exception.exit_code, 1)

    # -- RestoreError propagates (not swallowed) ---------------------------

    def test_restore_error_propagates(self):
        adapter, _ = _fake_adapter()

        # adapter.cleanup raises RestoreError (a failed/unrecoverable restore).
        adapter.cleanup.side_effect = inject_safety.RestoreError("backup missing")

        def _adapter_launch(project, env):
            from z_harness_cli import pty_launch as _pty

            return _pty.pty_launch([adapter.name], env, project)

        adapter.launch.side_effect = _adapter_launch

        with patch.object(
            registry, "select", return_value=(adapter, DetectResult(installed=True))
        ), patch(
            "z_harness_cli.env_bundle.resolve_env_bundle",
            return_value={"Z_HARNESS_PLAN_DIR": "/tmp/state"},
        ), self._patch_pty():
            with self.assertRaises(inject_safety.RestoreError):
                launch_mod.run(
                    ctx=MagicMock(),
                    host="claude",
                    project=str(self.project),
                    quiet=True,
                )

    # -- no installed host --------------------------------------------------

    def test_no_host_installed_exits_1(self):
        with patch.object(
            registry,
            "select",
            side_effect=registry.NoHostInstalledError("none installed"),
        ):
            with self.assertRaises(typer.Exit) as ctx_exit:
                launch_mod.run(
                    ctx=MagicMock(),
                    host=None,
                    project=str(self.project),
                    quiet=True,
                )
            self.assertEqual(ctx_exit.exception.exit_code, 1)

    def test_selected_host_not_installed_exits_1(self):
        adapter, _ = _fake_adapter()
        with patch.object(
            registry, "select", return_value=(adapter, DetectResult(installed=False))
        ):
            with self.assertRaises(typer.Exit) as ctx_exit:
                launch_mod.run(
                    ctx=MagicMock(),
                    host="claude",
                    project=str(self.project),
                    quiet=True,
                )
            self.assertEqual(ctx_exit.exception.exit_code, 1)

    # -- crash-interrupted restore recovery on startup ---------------------

    def test_orphan_recovery_runs_before_inject(self):
        adapter, _ = _fake_adapter()
        order: list[str] = []

        def _detect(project):
            order.append("detect")
            return [self.project / "CLAUDE.md"]

        def _cleanup(project):
            order.append("recover_cleanup")

        def _inject(state_env, mode, project):
            order.append("inject")
            inj = MagicMock()
            inj.env = {}
            return inj

        adapter.inject.side_effect = _inject

        def _adapter_launch(project, env):
            from z_harness_cli import pty_launch as _pty

            return _pty.pty_launch([adapter.name], env, project)

        adapter.launch.side_effect = _adapter_launch

        with patch.object(
            registry, "select", return_value=(adapter, DetectResult(installed=True))
        ), patch(
            "z_harness_cli.env_bundle.resolve_env_bundle",
            return_value={},
        ), patch.object(
            inject_safety, "detect_orphans", side_effect=_detect
        ), patch.object(
            inject_safety, "cleanup", side_effect=_cleanup
        ), self._patch_pty():
            launch_mod.run(
                ctx=MagicMock(),
                host="claude",
                project=str(self.project),
                quiet=True,
            )

        # Orphan recovery must finish before we inject anew.
        self.assertIn("recover_cleanup", order)
        self.assertLess(order.index("recover_cleanup"), order.index("inject"))

    def test_omp_orphan_recovery_removes_prior_session_file(self):
        from z_harness_cli.adapters.omp import OmpAdapter

        adapter = OmpAdapter()
        with patch.dict("os.environ", {"PATH": "/usr/bin"}, clear=True):
            injection = adapter.inject(
                {"OMP_PLUGIN_ROOT": "/bundle/root"},
                "ephemeral",
                self.project,
            )

        target = self.project / ".omp" / "z-harness" / "session.yml"
        self.assertEqual(injection.injected_files, [target])
        self.assertTrue(target.exists())
        self.assertEqual(inject_safety.detect_orphans(self.project), [target])

        launch_mod._recover_orphans(self.project)

        self.assertFalse(target.exists())
        self.assertEqual(inject_safety.detect_orphans(self.project), [])

    def test_omp_launch_argv_env_cwd_and_once_cleanup(self):
        from z_harness_cli.adapters.omp import OmpAdapter

        adapter = OmpAdapter()
        session_file = self.project / ".omp" / "z-harness" / "session.yml"
        seen = {}

        def _fake_pty_launch(argv, env, cwd, cleanup=None):
            seen["argv"] = argv
            seen["env"] = dict(env)
            seen["cwd"] = cwd
            seen["cleanup_attached"] = cleanup is not None
            seen["session_exists_before_cleanup"] = session_file.exists()
            if cleanup is not None:
                cleanup()
                cleanup()
            return 23

        with patch.object(
            registry,
            "select",
            return_value=(adapter, DetectResult(installed=True, binary="/fake/omp")),
        ), patch(
            "z_harness_cli.env_bundle.resolve_env_bundle",
            return_value={
                "OMP_PLUGIN_ROOT": "/bundle/root",
                "Z_HARNESS_PLAN_DIR": "/tmp/state",
            },
        ), patch(
            "shutil.which",
            return_value="/fake/omp",
        ), patch.object(
            adapter,
            "cleanup",
            wraps=adapter.cleanup,
        ) as mock_cleanup, patch(
            "z_harness_cli.pty_launch.pty_launch",
            side_effect=_fake_pty_launch,
        ):
            rc = launch_mod.run(
                ctx=MagicMock(),
                host="omp",
                project=str(self.project),
                quiet=True,
            )

        self.assertEqual(rc, 23)
        self.assertEqual(seen["argv"], ["/fake/omp"])
        self.assertEqual(seen["cwd"], self.project)
        self.assertEqual(seen["env"]["OMP_PLUGIN_ROOT"], str(session_file.parent))
        self.assertEqual(seen["env"]["Z_HARNESS_PLAN_DIR"], "/tmp/state")
        self.assertNotIn("CLAUDE_PLUGIN_ROOT", seen["env"])
        self.assertNotIn("ANTIGRAVITY_PLUGIN_ROOT", seen["env"])
        self.assertTrue(seen["cleanup_attached"])
        self.assertTrue(seen["session_exists_before_cleanup"])
        self.assertFalse(session_file.exists())
        self.assertFalse(session_file.parent.exists())
        self.assertEqual(inject_safety.detect_orphans(self.project), [])
        self.assertEqual(mock_cleanup.call_count, 1)


# ---------------------------------------------------------------------------
# env_bundle footgun reconciliation: "in_place" is an alias of "installed"
# ---------------------------------------------------------------------------


class EnvBundleModeAliasTest(unittest.TestCase):
    def test_in_place_aliases_installed_for_plugin_root(self):
        from z_harness_cli.env_bundle import resolve_plugin_root_env

        # "installed" historically meant "do not inject plugin-root".
        installed = resolve_plugin_root_env("claude", "installed")
        in_place = resolve_plugin_root_env("claude", "in_place")
        self.assertEqual(installed, {})
        self.assertEqual(in_place, {})
        # ephemeral still injects.
        ephemeral = resolve_plugin_root_env("claude", "ephemeral", harness_root="/x")
        self.assertEqual(ephemeral, {"CLAUDE_PLUGIN_ROOT": "/x"})
        omp_ephemeral = resolve_plugin_root_env("omp", "ephemeral", harness_root="/x")
        self.assertEqual(omp_ephemeral, {"OMP_PLUGIN_ROOT": "/x"})

    def test_unknown_mode_raises(self):
        from z_harness_cli.env_bundle import resolve_plugin_root_env

        with self.assertRaises(ValueError):
            resolve_plugin_root_env("claude", "bogus")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# BLOCKER-2 regression: cleanup wiring reaches the REAL adapter pty_launch
# bindings, not just a fake adapter that reads the module attribute.
#
# launch.py attaches its signal-trapped cleanup by wrapping the MODULE function
# z_harness_cli.pty_launch.pty_launch.  That wrapper is only visible to adapters
# that LAZY-import pty_launch inside launch().  A top-level
# `from z_harness_cli.pty_launch import pty_launch` would bind the name at import
# time, making the wrapper invisible and silently skipping cleanup on Ctrl+C /
# crash.  These tests exercise the real adapter.launch bindings so a regression
# (re-adding a top-level import) is caught.
# ---------------------------------------------------------------------------


class RealAdapterCleanupWiringTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.project = Path(self._tmp.name).resolve()
        _git_init(self.project)

    def tearDown(self):
        self._tmp.cleanup()

    def _run_real_adapter(self, adapter, name):
        """Drive a REAL adapter instance through launch.py's cleanup wrapper.

        Patches the module-level pty_launch to a recorder.  If the adapter's
        launch() lazy-imports pty_launch (correct), the recorder sees the
        cleanup callback launch.py injected and fires it.  If the adapter bound
        pty_launch at import time (the bug), the recorder never sees it and the
        cleanup callback is never invoked.
        """
        seen = {"got_callback": False}

        def _recorder(argv, env, cwd, cleanup=None):
            # launch.py's wrapper forces its own cleanup_cb here.
            seen["got_callback"] = cleanup is not None
            if cleanup is not None:
                cleanup()
            return 0

        # Use the REAL one-shot guard so we measure the underlying restore count:
        # the recorder fires cleanup, the _launch_with_cleanup finally fires the
        # safety net, and the guard must collapse them into ONE adapter.cleanup.
        cleanup_target = MagicMock()
        injection = MagicMock()
        once = launch_mod._OnceCleanup(cleanup_target, injection)

        import z_harness_cli.pty_launch as _pty_mod

        with patch("z_harness_cli.pty_launch.pty_launch", side_effect=_recorder):
            rc = launch_mod._launch_with_cleanup(
                _pty_mod,
                adapter,
                self.project,
                {"PATH": "/usr/bin"},
                once,
            )
        return rc, seen, cleanup_target.cleanup.call_count

    def test_claude_adapter_routes_through_wrapped_pty_launch(self):
        # The real regression target: claude.py used to bind pty_launch at the
        # module top level, so launch.py's wrapper was invisible on this path.
        from z_harness_cli.adapters.claude import ClaudeAdapter

        rc, seen, cleanup_count = self._run_real_adapter(ClaudeAdapter(), "claude")
        self.assertEqual(rc, 0)
        self.assertTrue(
            seen["got_callback"],
            "claude adapter did not route through launch.py's wrapped pty_launch "
            "— cleanup callback was not attached (top-level import regression?)",
        )
        # The recorder fires cleanup AND the finally safety net fires it again;
        # the one-shot guard must collapse those into a single real restore.
        self.assertEqual(
            cleanup_count, 1, "the underlying cleanup must run exactly once"
        )

    def test_all_four_adapters_route_through_wrapped_pty_launch(self):
        from z_harness_cli.adapters.claude import ClaudeAdapter
        from z_harness_cli.adapters.cursor import CursorAdapter
        from z_harness_cli.adapters.codex import CodexAdapter
        from z_harness_cli.adapters.antigravity import AntigravityAdapter
        from z_harness_cli.adapters.omp import OmpAdapter

        for adapter, name in (
            (ClaudeAdapter(), "claude"),
            (CursorAdapter(), "cursor"),
            (CodexAdapter(), "codex"),
            (AntigravityAdapter(), "antigravity"),
            (OmpAdapter(), "omp"),
        ):
            with self.subTest(host=name):
                rc, seen, cleanup_count = self._run_real_adapter(adapter, name)
                self.assertTrue(
                    seen["got_callback"],
                    f"{name} adapter must route through the wrapped pty_launch",
                )
                self.assertEqual(
                    cleanup_count, 1, f"{name}: cleanup must run exactly once"
                )


# ---------------------------------------------------------------------------
# MAJOR-3 regression: nonzero host exit code propagates through the CLI.
# ---------------------------------------------------------------------------


class CliExitCodePropagationTest(unittest.TestCase):
    def test_nonzero_host_exit_propagates_through_cli(self):
        # __main__.launch_cmd must raise typer.Exit(code=rc) when run() returns a
        # nonzero host exit code (else the CLI reports success for a crashed host).
        # launch_cmd imports z_harness_cli.commands.launch as _launch_mod and
        # calls _launch_mod.run(...), so patching launch_mod.run intercepts it.
        from z_harness_cli import __main__ as main_mod

        with patch.object(launch_mod, "run", return_value=7) as mock_run:
            with self.assertRaises(typer.Exit) as ctx_exit:
                main_mod.launch_cmd(
                    ctx=MagicMock(), host="claude", quiet=True, project=None
                )
        self.assertEqual(ctx_exit.exception.exit_code, 7)
        mock_run.assert_called_once()

    def test_zero_host_exit_does_not_raise(self):
        from z_harness_cli import __main__ as main_mod

        # A clean (0) exit must NOT raise — typer treats no-raise as exit 0.
        with patch.object(launch_mod, "run", return_value=0):
            main_mod.launch_cmd(
                ctx=MagicMock(), host="claude", quiet=True, project=None
            )


if __name__ == "__main__":
    unittest.main()
