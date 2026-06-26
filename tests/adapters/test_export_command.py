"""Tests for z_harness_cli/commands/export.py (T014).

Covers:
  * Per-host file landing: export_payload(dest) is called with the correct
    destination path; files are written under that path.
  * --in-place vs default destination: --in-place uses cwd; default uses
    the resolved state root.
  * --out PATH outside repo → exit 1 (within-repo guard).
  * --out PATH inside repo → accepted.
  * --out non-empty existing dir without --force → exit 1.
  * --out non-empty existing dir with --force → accepted.
  * --host and --all mutual exclusion → exit 1.
  * --out and --in-place mutual exclusion → exit 1.
  * Per-host fidelity is printed to stdout.
  * All-hosts mode iterates all registered adapters.
  * --all --in-place namespaces per host to prevent collisions.
  * Single-host export writes directly to dest (no sub-directory).
"""

from __future__ import annotations
import os
import importlib

import sys
import subprocess
import shutil
import tempfile
import unittest
from contextlib import contextmanager, ExitStack
from pathlib import Path
from unittest.mock import MagicMock, patch

# Ensure the repo root is on sys.path.
REPO_ROOT = Path(__file__).parent.parent.parent.resolve()
sys.path.insert(0, str(REPO_ROOT))

import typer
from typer.testing import CliRunner

from z_harness_cli.__main__ import app
from z_harness_cli.adapters.base import ExportResult
pi_export = importlib.import_module("runtime.drivers.pi.export")  # noqa: E402
pi_pkg = importlib.import_module("runtime.drivers.pi")  # noqa: E402
from z_harness_cli.adapters.omp import OmpAdapter  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_adapter(name: str, fidelity: str = "native") -> MagicMock:
    """Return a mock adapter whose export_payload writes no real files."""
    adapter = MagicMock()
    adapter.name = name
    adapter.fidelity_tier = fidelity

    def _fake_export(dest: Path) -> ExportResult:
        dest = Path(dest)
        dest.mkdir(parents=True, exist_ok=True)
        written = dest / f"{name}-export.txt"
        written.write_text(f"export for {name}\n", encoding="utf-8")
        return ExportResult(
            dest=dest,
            files=[Path(f"{name}-export.txt")],
            fidelity=fidelity,
            warnings=[],
        )

    adapter.export_payload.side_effect = _fake_export
    return adapter


@contextmanager
def _forbid_pi_or_consult_compatibility():
    def forbidden(*_args, **_kwargs):
        raise AssertionError("OMP export must not use pi exporter/helpers or omp-consult compatibility paths")

    original_read_text = Path.read_text
    original_read_bytes = Path.read_bytes
    original_is_dir = Path.is_dir
    original_exists = Path.exists
    original_copytree = shutil.copytree

    def assert_allowed_path(path: Path) -> None:
        rendered = path.as_posix()
        if "/scripts/pi_assets" in rendered or rendered.endswith("/scripts/omp-consult.sh"):
            raise AssertionError(f"OMP export touched forbidden compatibility path: {rendered}")

    def guarded_read_text(self: Path, *args, **kwargs):
        assert_allowed_path(self)
        return original_read_text(self, *args, **kwargs)

    def guarded_read_bytes(self: Path, *args, **kwargs):
        assert_allowed_path(self)
        return original_read_bytes(self, *args, **kwargs)

    def guarded_is_dir(self: Path):
        assert_allowed_path(self)
        return original_is_dir(self)

    def guarded_exists(self: Path):
        assert_allowed_path(self)
        return original_exists(self)

    def guarded_copytree(src, dst, *args, **kwargs):
        rendered = str(src)
        if "scripts/pi_assets" in rendered:
            raise AssertionError(f"OMP export copied forbidden pi assets path: {rendered}")
        return original_copytree(src, dst, *args, **kwargs)

    def guarded_subprocess_run(*args, **kwargs):
        cmd = args[0] if args else kwargs.get("args")
        rendered = " ".join(str(part) for part in cmd) if isinstance(cmd, (list, tuple)) else str(cmd)
        if "omp-consult.sh" in rendered:
            raise AssertionError(f"OMP export invoked forbidden consult compatibility path: {rendered}")
        raise AssertionError(f"OMP export unexpectedly spawned subprocess: {rendered}")

    with ExitStack() as stack:
        for name in (
            "export",
            "_replacement_for_line",
            "_rewrite_body",
            "_render_agent",
            "_render_prompt",
            "_render_agents_index",
        ):
            stack.enter_context(patch.object(pi_export, name, side_effect=forbidden))
        stack.enter_context(patch.object(pi_pkg, "export", side_effect=forbidden))
        stack.enter_context(patch.object(Path, "read_text", guarded_read_text))
        stack.enter_context(patch.object(Path, "read_bytes", guarded_read_bytes))
        stack.enter_context(patch.object(Path, "is_dir", guarded_is_dir))
        stack.enter_context(patch.object(Path, "exists", guarded_exists))
        stack.enter_context(patch.object(subprocess, "run", side_effect=guarded_subprocess_run))
        stack.enter_context(patch.object(shutil, "copytree", side_effect=guarded_copytree))
        yield


class _ExportCmdBase(unittest.TestCase):
    """Base: provides a CliRunner and a temp tree with a fake repo root."""

    def setUp(self) -> None:
        self.runner = CliRunner()
        self._tmp = tempfile.TemporaryDirectory(prefix="zh-export-cmd-")
        self.tmp_root = Path(self._tmp.name).resolve()

    def tearDown(self) -> None:
        self._tmp.cleanup()


# ---------------------------------------------------------------------------
# 1. Per-host file landing
# ---------------------------------------------------------------------------


class TestPerHostFileLanding(_ExportCmdBase):
    """export_payload is called with the correct dest."""

    def test_default_dest_export_calls_adapter(self):
        """export_payload is called for the auto-selected adapter."""
        adapter = _make_adapter("claude", "native")
        state_root = self.tmp_root / "state-root"

        with patch(
            "z_harness_cli.commands.export._resolve_default_dest",
            return_value=state_root,
        ), patch(
            "z_harness_cli.commands.export._repo_root",
            return_value=REPO_ROOT,
        ), patch(
            "z_harness_cli.adapters.registry.select",
            return_value=(adapter, MagicMock(installed=True)),
        ):
            result = self.runner.invoke(app, ["export"])

        self.assertEqual(result.exit_code, 0, result.output)
        adapter.export_payload.assert_called_once()
        # Single auto-selected host writes directly to state_root (no sub-dir).
        call_dest = adapter.export_payload.call_args[0][0]
        self.assertEqual(Path(call_dest).resolve(), state_root.resolve())

    def test_exported_file_lands_under_dest(self):
        """The file written by export_payload appears directly under state_root."""
        adapter = _make_adapter("claude", "native")
        state_root = self.tmp_root / "state-root"

        with patch(
            "z_harness_cli.commands.export._resolve_default_dest",
            return_value=state_root,
        ), patch(
            "z_harness_cli.commands.export._repo_root",
            return_value=REPO_ROOT,
        ), patch(
            "z_harness_cli.adapters.registry.select",
            return_value=(adapter, MagicMock(installed=True)),
        ):
            result = self.runner.invoke(app, ["export"])

        self.assertEqual(result.exit_code, 0, result.output)
        # Single host: no namespace — file is directly under state_root.
        expected_file = state_root / "claude-export.txt"
        self.assertTrue(expected_file.exists(), f"Expected file not found: {expected_file}")

    def test_fidelity_printed_to_stdout(self):
        """Per-host fidelity is printed after the export."""
        adapter = _make_adapter("claude", "native")
        state_root = self.tmp_root / "state-root"

        with patch(
            "z_harness_cli.commands.export._resolve_default_dest",
            return_value=state_root,
        ), patch(
            "z_harness_cli.commands.export._repo_root",
            return_value=REPO_ROOT,
        ), patch(
            "z_harness_cli.adapters.registry.select",
            return_value=(adapter, MagicMock(installed=True)),
        ):
            result = self.runner.invoke(app, ["export"])

        self.assertIn("fidelity=native", result.output)
        self.assertIn("claude", result.output)


# ---------------------------------------------------------------------------
# 2. --in-place vs default destination
# ---------------------------------------------------------------------------


class TestInPlaceVsDefaultDest(_ExportCmdBase):
    """--in-place writes into cwd; default writes under state root."""

    def test_default_dest_uses_state_root(self):
        """Without --in-place, dest is the state root."""
        adapter = _make_adapter("claude", "native")
        state_root = self.tmp_root / "state-root"

        with patch(
            "z_harness_cli.commands.export._resolve_default_dest",
            return_value=state_root,
        ), patch(
            "z_harness_cli.commands.export._repo_root",
            return_value=REPO_ROOT,
        ), patch(
            "z_harness_cli.adapters.registry.select",
            return_value=(adapter, MagicMock(installed=True)),
        ):
            result = self.runner.invoke(app, ["export"])

        self.assertEqual(result.exit_code, 0, result.output)
        call_dest = adapter.export_payload.call_args[0][0]
        # Single host: dest is state_root directly (no host sub-directory).
        self.assertEqual(Path(call_dest).resolve(), state_root.resolve())

    def test_in_place_uses_cwd(self):
        """With --in-place single host, dest is the current working directory."""
        adapter = _make_adapter("claude", "native")
        project_dir = self.tmp_root / "project"
        project_dir.mkdir()

        with patch(
            "z_harness_cli.commands.export._repo_root",
            return_value=REPO_ROOT,
        ), patch(
            "z_harness_cli.adapters.registry.select",
            return_value=(adapter, MagicMock(installed=True)),
        ), patch(
            "z_harness_cli.commands.export.Path.cwd",
            return_value=project_dir,
        ):
            result = self.runner.invoke(app, ["export", "--in-place"])

        self.assertEqual(result.exit_code, 0, result.output)
        call_dest = adapter.export_payload.call_args[0][0]
        # Single host --in-place: no namespace, write directly to cwd.
        self.assertEqual(Path(call_dest).resolve(), project_dir.resolve())

    def test_in_place_and_out_are_mutually_exclusive(self):
        """--in-place and --out together must exit 1."""
        # Use an in-repo path for --out so the guard doesn't fire first.
        out_path = str(REPO_ROOT / ".z-harness" / "test-exclusive-check")
        result = self.runner.invoke(
            app, ["export", "--in-place", "--out", out_path]
        )
        self.assertEqual(result.exit_code, 1)
        self.assertIn("mutually exclusive", result.output.lower())

    def test_host_and_all_are_mutually_exclusive(self):
        """--host and --all together must exit 1."""
        result = self.runner.invoke(app, ["export", "--host", "claude", "--all"])
        self.assertEqual(result.exit_code, 1)
        self.assertIn("mutually exclusive", result.output.lower())

    def test_surface_env_restored_on_early_validation_failure(self):
        """Early validation errors must not leak prod surface into this process."""
        previous = os.environ.get("Z_HARNESS_RELEASE_SURFACE")
        os.environ["Z_HARNESS_RELEASE_SURFACE"] = "dev"
        try:
            result = self.runner.invoke(
                app, ["export", "--surface", "prod", "--host", "claude", "--all"]
            )
            self.assertEqual(result.exit_code, 1)
            self.assertEqual(os.environ.get("Z_HARNESS_RELEASE_SURFACE"), "dev")
        finally:
            if previous is None:
                os.environ.pop("Z_HARNESS_RELEASE_SURFACE", None)
            else:
                os.environ["Z_HARNESS_RELEASE_SURFACE"] = previous

    def test_prod_surface_removes_stale_hidden_skill_paths(self):
        """Prod exports into reused destinations delete stale dev-only skills."""
        adapter = _make_adapter("codex", "flattened")
        project_dir = self.tmp_root / "project"
        out_dir = project_dir / "export"
        stale_skill = out_dir / "skills" / "z-research" / "SKILL.md"
        stale_axiom = out_dir / "skills" / "z-axiom-scan" / "SKILL.md"
        stale_prompt = out_dir / "prompts" / "z-map.md"
        stale_cursor_skill = out_dir / ".cursor" / "skills" / "z-overnight" / "SKILL.md"
        for path in (stale_skill, stale_axiom, stale_prompt, stale_cursor_skill):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("stale\n", encoding="utf-8")

        with patch(
            "z_harness_cli.commands.export._repo_root",
            return_value=project_dir,
        ), patch(
            "z_harness_cli.adapters.registry.select",
            return_value=(adapter, MagicMock(installed=True)),
        ):
            result = self.runner.invoke(
                app,
                ["export", "--host", "codex", "--surface", "prod", "--out", str(out_dir), "--force"],
            )

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertFalse((out_dir / "skills" / "z-research").exists())
        self.assertFalse((out_dir / "skills" / "z-axiom-scan").exists())
        self.assertFalse(stale_prompt.exists())
        self.assertFalse((out_dir / ".cursor" / "skills" / "z-overnight").exists())
        self.assertTrue((out_dir / "codex-export.txt").exists())


# ---------------------------------------------------------------------------
# 3. --out PATH within-repo guard
# ---------------------------------------------------------------------------


class TestOutPathRepoEscapeGuard(_ExportCmdBase):
    """--out outside repo → exit 1 (within-repo guard)."""

    def test_out_path_outside_repo_exits_1(self):
        """--out at any path outside the repo root must exit 1."""
        outside_dest = self.tmp_root / "external-export"

        with patch(
            "z_harness_cli.commands.export._repo_root",
            return_value=REPO_ROOT,
        ):
            result = self.runner.invoke(
                app, ["export", "--out", str(outside_dest)]
            )

        self.assertEqual(
            result.exit_code,
            1,
            f"Expected exit 1 for out-of-repo path; "
            f"got {result.exit_code}. Output:\n{result.output}",
        )
        self.assertIn("escapes the repo root", result.output.lower())

    def test_out_path_outside_repo_with_existing_parent_is_rejected(self):
        """--out outside the repo is rejected even when the parent dir exists."""
        # self.tmp_root is an existing directory outside the repo.
        outside_dest = self.tmp_root / "external-export"

        with patch(
            "z_harness_cli.commands.export._repo_root",
            return_value=REPO_ROOT,
        ):
            result = self.runner.invoke(
                app, ["export", "--out", str(outside_dest)]
            )

        self.assertEqual(
            result.exit_code,
            1,
            f"Expected exit 1 even when parent exists outside repo; "
            f"got {result.exit_code}. Output:\n{result.output}",
        )

    def test_out_path_inside_repo_is_accepted(self):
        """--out at a path inside the repo root is always accepted."""
        inside_dest = REPO_ROOT / ".z-harness" / "test-export-dest"

        adapter = _make_adapter("claude", "native")

        with patch(
            "z_harness_cli.commands.export._repo_root",
            return_value=REPO_ROOT,
        ), patch(
            "z_harness_cli.adapters.registry.select",
            return_value=(adapter, MagicMock(installed=True)),
        ):
            result = self.runner.invoke(
                app, ["export", "--out", str(inside_dest)]
            )

        # Clean up any created directories.
        if inside_dest.exists():
            import shutil
            shutil.rmtree(inside_dest, ignore_errors=True)

        self.assertEqual(
            result.exit_code,
            0,
            f"Expected exit 0 for in-repo path; "
            f"got {result.exit_code}. Output:\n{result.output}",
        )


# ---------------------------------------------------------------------------
# 4. --out non-empty existing dir without/with --force
# ---------------------------------------------------------------------------


class TestOutNonEmptyDirGuard(_ExportCmdBase):
    """Non-empty existing --out dir → exit 1; with --force → accepted."""

    def _in_repo_nonempty_dir(self) -> Path:
        """Create a non-empty dir inside the repo root and return its path."""
        nonempty_dir = REPO_ROOT / ".z-harness" / "test-nonempty-guard"
        nonempty_dir.mkdir(parents=True, exist_ok=True)
        (nonempty_dir / "existing_file.txt").write_text("content", encoding="utf-8")
        return nonempty_dir

    def _cleanup_in_repo_dir(self, path: Path) -> None:
        import shutil
        shutil.rmtree(path, ignore_errors=True)

    def test_nonempty_out_dir_without_force_exits_1(self):
        """Non-empty existing --out dir without --force must exit 1."""
        nonempty_dir = self._in_repo_nonempty_dir()
        try:
            with patch(
                "z_harness_cli.commands.export._repo_root",
                return_value=REPO_ROOT,
            ):
                result = self.runner.invoke(
                    app, ["export", "--out", str(nonempty_dir)]
                )

            self.assertEqual(
                result.exit_code,
                1,
                f"Expected exit 1 for non-empty --out dir without --force; "
                f"got {result.exit_code}. Output:\n{result.output}",
            )
            self.assertIn("non-empty", result.output.lower())
        finally:
            self._cleanup_in_repo_dir(nonempty_dir)

    def test_nonempty_out_dir_with_force_is_accepted(self):
        """Non-empty existing --out dir with --force must succeed."""
        nonempty_dir = self._in_repo_nonempty_dir()
        adapter = _make_adapter("claude", "native")
        try:
            with patch(
                "z_harness_cli.commands.export._repo_root",
                return_value=REPO_ROOT,
            ), patch(
                "z_harness_cli.adapters.registry.select",
                return_value=(adapter, MagicMock(installed=True)),
            ):
                result = self.runner.invoke(
                    app, ["export", "--out", str(nonempty_dir), "--force"]
                )

            self.assertEqual(
                result.exit_code,
                0,
                f"Expected exit 0 with --force on non-empty dir; "
                f"got {result.exit_code}. Output:\n{result.output}",
            )
        finally:
            self._cleanup_in_repo_dir(nonempty_dir)

    def test_force_reconciles_omp_owned_subtree_and_preserves_sibling_export(self):
        """Real OMP --force refresh removes stale OMP files without deleting exports/pi."""
        export_root = self.tmp_root / "repo" / "exports"
        sibling = export_root / "pi" / "keep.txt"
        stale_owned = export_root / ".omp" / "z-harness" / "prompts" / "stale.md"
        sibling.parent.mkdir(parents=True)
        stale_owned.parent.mkdir(parents=True)
        sibling.write_text("pi export\n", encoding="utf-8")
        stale_owned.write_text("stale prompt\n", encoding="utf-8")
        adapter = OmpAdapter()

        with _forbid_pi_or_consult_compatibility(), patch(
            "z_harness_cli.commands.export._repo_root",
            return_value=export_root.parent.resolve(),
        ), patch(
            "z_harness_cli.adapters.registry.select",
            return_value=(adapter, MagicMock(installed=True)),
        ):
            result = self.runner.invoke(
                app, ["export", "--host", "omp", "--out", str(export_root), "--force"]
            )

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(sibling.read_text(encoding="utf-8"), "pi export\n")
        self.assertFalse(stale_owned.exists())
        self.assertTrue((export_root / ".omp" / "z-harness" / "manifest.yml").exists())
        self.assertIn(
            "enableAgentsProject: false",
            (export_root / ".omp" / "config.yml").read_text(encoding="utf-8"),
        )
        from z_harness_cli.adapters.omp_parity_gate import omp_export_fidelity
        self.assertIn(f"[omp] fidelity={omp_export_fidelity()}", result.output)

    def test_force_out_repo_root_preserves_existing_files(self):
        """--out <repo-root> --force must not delete the repo contents."""
        repo_root = self.tmp_root / "repo-root"
        repo_root.mkdir()
        sentinel = repo_root / "pyproject.toml"
        sentinel.write_text("[project]\nname = 'sentinel'\n", encoding="utf-8")
        adapter = _make_adapter("claude", "native")

        with patch(
            "z_harness_cli.commands.export._repo_root",
            return_value=repo_root.resolve(),
        ), patch(
            "z_harness_cli.adapters.registry.select",
            return_value=(adapter, MagicMock(installed=True)),
        ):
            result = self.runner.invoke(
                app, ["export", "--out", str(repo_root), "--force"]
            )

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(sentinel.read_text(encoding="utf-8"), "[project]\nname = 'sentinel'\n")
        self.assertTrue((repo_root / "claude-export.txt").exists())

    def test_empty_existing_out_dir_is_always_accepted(self):
        """An empty --out dir is accepted even without --force."""
        empty_dir = REPO_ROOT / ".z-harness" / "test-empty-dest"
        empty_dir.mkdir(parents=True, exist_ok=True)
        adapter = _make_adapter("claude", "native")
        try:
            with patch(
                "z_harness_cli.commands.export._repo_root",
                return_value=REPO_ROOT,
            ), patch(
                "z_harness_cli.adapters.registry.select",
                return_value=(adapter, MagicMock(installed=True)),
            ):
                result = self.runner.invoke(
                    app, ["export", "--out", str(empty_dir)]
                )

            self.assertEqual(
                result.exit_code,
                0,
                f"Expected exit 0 for empty --out dir; "
                f"got {result.exit_code}. Output:\n{result.output}",
            )
        finally:
            import shutil
            shutil.rmtree(empty_dir, ignore_errors=True)


# ---------------------------------------------------------------------------
# 5. --all mode iterates all adapters
# ---------------------------------------------------------------------------


class TestAllHostsMode(_ExportCmdBase):
    """--all calls export_payload for every registered adapter."""

    def test_all_hosts_calls_each_adapter(self):
        """--all iterates all adapters returned by detect_all()."""
        adapters = [
            _make_adapter("claude", "native"),
            _make_adapter("antigravity", "high"),
            _make_adapter("cursor", "flattened"),
            _make_adapter("codex", "flattened"),
        ]
        state_root = self.tmp_root / "state-root"

        with patch(
            "z_harness_cli.commands.export._resolve_default_dest",
            return_value=state_root,
        ), patch(
            "z_harness_cli.commands.export._repo_root",
            return_value=REPO_ROOT,
        ), patch(
            "z_harness_cli.adapters.registry.detect_all",
            return_value=[(a, MagicMock(installed=True)) for a in adapters],
        ):
            result = self.runner.invoke(app, ["export", "--all"])

        self.assertEqual(result.exit_code, 0, result.output)
        for adapter in adapters:
            adapter.export_payload.assert_called_once()

    def test_all_hosts_prints_fidelity_for_each(self):
        """--all prints fidelity for every adapter."""
        adapters = [
            _make_adapter("claude", "native"),
            _make_adapter("codex", "flattened"),
        ]
        state_root = self.tmp_root / "state-root"

        with patch(
            "z_harness_cli.commands.export._resolve_default_dest",
            return_value=state_root,
        ), patch(
            "z_harness_cli.commands.export._repo_root",
            return_value=REPO_ROOT,
        ), patch(
            "z_harness_cli.adapters.registry.detect_all",
            return_value=[(a, MagicMock(installed=True)) for a in adapters],
        ):
            result = self.runner.invoke(app, ["export", "--all"])

        self.assertIn("fidelity=native", result.output)
        self.assertIn("fidelity=flattened", result.output)

    def test_all_hosts_namespaces_per_host(self):
        """--all writes each adapter under dest/<host_name>/ to prevent collisions."""
        adapters = [
            _make_adapter("claude", "native"),
            _make_adapter("codex", "flattened"),
        ]
        state_root = self.tmp_root / "state-root"

        with patch(
            "z_harness_cli.commands.export._resolve_default_dest",
            return_value=state_root,
        ), patch(
            "z_harness_cli.commands.export._repo_root",
            return_value=REPO_ROOT,
        ), patch(
            "z_harness_cli.adapters.registry.detect_all",
            return_value=[(a, MagicMock(installed=True)) for a in adapters],
        ):
            result = self.runner.invoke(app, ["export", "--all"])

        self.assertEqual(result.exit_code, 0, result.output)
        # Each host is written to its own sub-directory.
        for adapter in adapters:
            call_dest = adapter.export_payload.call_args[0][0]
            self.assertEqual(
                Path(call_dest).name,
                adapter.name,
                f"Expected {adapter.name} dest to be namespaced as "
                f"state_root/{adapter.name}, got {call_dest}",
            )

    def test_all_in_place_namespaces_per_host_to_prevent_collision(self):
        """--all --in-place namespaces per host so multiple hosts don't collide."""
        adapters = [
            _make_adapter("claude", "native"),
            _make_adapter("codex", "flattened"),
        ]
        project_dir = self.tmp_root / "project"
        project_dir.mkdir()

        with patch(
            "z_harness_cli.commands.export._repo_root",
            return_value=REPO_ROOT,
        ), patch(
            "z_harness_cli.adapters.registry.detect_all",
            return_value=[(a, MagicMock(installed=True)) for a in adapters],
        ), patch(
            "z_harness_cli.commands.export.Path.cwd",
            return_value=project_dir,
        ):
            result = self.runner.invoke(app, ["export", "--all", "--in-place"])

        self.assertEqual(result.exit_code, 0, result.output)
        # With --all, each host must write to its own sub-directory.
        for adapter in adapters:
            call_dest = adapter.export_payload.call_args[0][0]
            self.assertEqual(
                Path(call_dest).name,
                adapter.name,
                f"Expected {adapter.name} to be namespaced under project_dir, "
                f"but got dest: {call_dest}",
            )
            # Verify files don't collide — each host has its own directory.
            self.assertEqual(
                Path(call_dest).parent.resolve(),
                project_dir.resolve(),
            )


# ---------------------------------------------------------------------------
# 6. --host selects a specific adapter
# ---------------------------------------------------------------------------


class TestHostFlag(_ExportCmdBase):
    """--host H selects only the named adapter."""

    def test_host_flag_calls_specific_adapter(self):
        """--host claude calls only the claude adapter."""
        adapter = _make_adapter("claude", "native")
        state_root = self.tmp_root / "state-root"

        with patch(
            "z_harness_cli.commands.export._resolve_default_dest",
            return_value=state_root,
        ), patch(
            "z_harness_cli.commands.export._repo_root",
            return_value=REPO_ROOT,
        ), patch(
            "z_harness_cli.adapters.registry.select",
            return_value=(adapter, MagicMock(installed=True)),
        ):
            result = self.runner.invoke(app, ["export", "--host", "claude"])

        self.assertEqual(result.exit_code, 0, result.output)
        adapter.export_payload.assert_called_once()

    def test_host_flag_writes_directly_to_dest_no_namespace(self):
        """--host X writes directly to dest (no host sub-directory)."""
        adapter = _make_adapter("claude", "native")
        state_root = self.tmp_root / "state-root"

        with patch(
            "z_harness_cli.commands.export._resolve_default_dest",
            return_value=state_root,
        ), patch(
            "z_harness_cli.commands.export._repo_root",
            return_value=REPO_ROOT,
        ), patch(
            "z_harness_cli.adapters.registry.select",
            return_value=(adapter, MagicMock(installed=True)),
        ):
            result = self.runner.invoke(app, ["export", "--host", "claude"])

        self.assertEqual(result.exit_code, 0, result.output)
        call_dest = adapter.export_payload.call_args[0][0]
        # Single explicit host: must NOT add a sub-directory.
        self.assertEqual(
            Path(call_dest).resolve(),
            state_root.resolve(),
            f"--host should write directly to dest, not {call_dest}",
        )

    def test_unknown_host_exits_1(self):
        """--host with an unrecognized name must exit 1."""
        from z_harness_cli.adapters.registry import UnknownHostError

        with patch(
            "z_harness_cli.commands.export._repo_root",
            return_value=REPO_ROOT,
        ), patch(
            "z_harness_cli.adapters.registry.select",
            side_effect=UnknownHostError("Unknown host 'bogus'. Valid hosts: [...]"),
        ):
            result = self.runner.invoke(app, ["export", "--host", "bogus"])

        self.assertEqual(
            result.exit_code,
            1,
            f"Expected exit 1 for unknown host; got {result.exit_code}. "
            f"Output:\n{result.output}",
        )


if __name__ == "__main__":
    unittest.main()
