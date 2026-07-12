"""
Tests for export_payload() delegation to runtime export().

Verifies across all three adapters (cursor, codex, antigravity):
  * export_payload() calls runtime/drivers/<t>/export.py::export() for
    commands/agents/skills — the runtime files appear in the ExportResult.
  * No duplicate paths in the files list.
  * Non-empty warnings from the runtime export are surfaced as RuntimeError
    (legacy hard-gate is preserved).
  * The runtime-owned ExportResult is the single canonical type (BLOCKER-1).
"""

from __future__ import annotations

import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

REPO_ROOT = Path(__file__).parent.parent.parent.resolve()
sys.path.insert(0, str(REPO_ROOT))

from z_harness_cli.adapters.base import ExportResult  # noqa: E402
from runtime.drivers._export_utils import ExportResult as RuntimeExportResult  # noqa: E402


# ---------------------------------------------------------------------------
# BLOCKER-1: Single canonical ExportResult type
# ---------------------------------------------------------------------------


class TestSingleCanonicalExportResult(unittest.TestCase):
    """ExportResult imported from base.py must BE the runtime-owned type."""

    def test_export_result_is_runtime_type(self):
        """base.ExportResult must be identical to runtime._export_utils.ExportResult."""
        self.assertIs(
            ExportResult,
            RuntimeExportResult,
            "base.ExportResult and runtime.drivers._export_utils.ExportResult "
            "must be the same object (single canonical type, BLOCKER-1)",
        )

    def test_export_result_from_base_is_instantiatable(self):
        """ExportResult imported from base must be constructible."""
        result = ExportResult(dest=Path("/tmp"), files=[], fidelity="flattened", warnings=[])
        self.assertEqual(result.fidelity, "flattened")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_runtime_export_result(dest: Path, files: list[Path], fidelity: str = "flattened") -> RuntimeExportResult:
    """Return a successful (no-warnings) ExportResult from the runtime layer."""
    return RuntimeExportResult(dest=dest, files=files, fidelity=fidelity, warnings=[])


def _make_runtime_export_result_with_warnings(dest: Path, warnings: list[str]) -> RuntimeExportResult:
    """Return an ExportResult with validation warnings (simulates export failure)."""
    return RuntimeExportResult(dest=dest, files=[], fidelity="flattened", warnings=warnings)


# ---------------------------------------------------------------------------
# Cursor adapter — export delegation tests
# ---------------------------------------------------------------------------


class TestCursorExportDelegation(unittest.TestCase):
    """CursorAdapter.export_payload() delegates to the runtime export()."""

    def setUp(self) -> None:
        from z_harness_cli.adapters.cursor import CursorAdapter
        self.adapter = CursorAdapter()

    def _run_export_with_mocks(
        self,
        dest: Path,
        harness_root: Path,
        runtime_files: list[Path],
        runtime_warnings: list[str] | None = None,
    ):
        """Helper: run export_payload with a mocked runtime export module."""
        import z_harness_cli.adapters.cursor as _mod

        rt_result = RuntimeExportResult(
            dest=dest,
            files=runtime_files,
            fidelity="flattened",
            warnings=runtime_warnings or [],
        )
        mock_export_fn = MagicMock(return_value=rt_result)
        mock_cursor_export = MagicMock()
        mock_cursor_export.export = mock_export_fn

        with patch.object(
            _mod,
            "__file__",
            str(harness_root / "z_harness_cli" / "adapters" / "cursor.py"),
        ), patch.dict(
            "sys.modules",
            {
                "runtime.drivers.cursor.export": mock_cursor_export,
            },
        ):
            result = self.adapter.export_payload(dest)

        return result

    def test_files_contains_runtime_files(self):
        """export_payload() must include the runtime-export files."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp).resolve()
            dest = tmp_path / "dest"
            dest.mkdir()
            harness_root = tmp_path / "harness"

            # Simulate runtime export producing 2 .mdc files.
            runtime_file_1 = dest / ".cursor" / "rules" / "z-plan.mdc"
            runtime_file_2 = dest / ".cursor" / "rules" / "z-implement.mdc"

            result = self._run_export_with_mocks(
                dest=dest,
                harness_root=harness_root,
                runtime_files=[runtime_file_1, runtime_file_2],
            )

        self.assertEqual(result.fidelity, "flattened")
        # Runtime files must be in the result.
        file_strs = [str(f) for f in result.files]
        self.assertTrue(
            any("z-plan.mdc" in s for s in file_strs),
            f"runtime file z-plan.mdc missing from files: {result.files}",
        )
        self.assertTrue(
            any("z-implement.mdc" in s for s in file_strs),
            f"runtime file z-implement.mdc missing from files: {result.files}",
        )

    def test_no_duplicate_paths(self):
        """No file path must appear more than once in ExportResult.files."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp).resolve()
            dest = tmp_path / "dest"
            dest.mkdir()
            harness_root = tmp_path / "harness"

            runtime_files = [dest / ".cursor" / "rules" / "z-plan.mdc"]

            result = self._run_export_with_mocks(
                dest=dest,
                harness_root=harness_root,
                runtime_files=runtime_files,
            )

        # All paths must be unique.
        seen = set()
        for f in result.files:
            key = str(Path(f).resolve())
            self.assertNotIn(key, seen, f"Duplicate path in ExportResult.files: {key}")
            seen.add(key)

    def test_runtime_warnings_raise_runtime_error(self):
        """Non-empty runtime export warnings must raise RuntimeError (legacy hard-gate)."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp).resolve()
            dest = tmp_path / "dest"
            dest.mkdir()
            harness_root = tmp_path / "harness"

            with self.assertRaises(RuntimeError) as ctx:
                self._run_export_with_mocks(
                    dest=dest,
                    harness_root=harness_root,
                    runtime_files=[],
                    runtime_warnings=["validation error: missing frontmatter in z-plan.mdc"],
                )

        self.assertIn("validation error", str(ctx.exception).lower())


# ---------------------------------------------------------------------------
# Codex adapter — export delegation tests
# ---------------------------------------------------------------------------


class TestCodexExportDelegation(unittest.TestCase):
    """CodexAdapter.export_payload() delegates to the runtime export()."""

    def setUp(self) -> None:
        from z_harness_cli.adapters.codex import CodexAdapter
        self.adapter = CodexAdapter()

    def _run_export_with_mocks(
        self,
        dest: Path,
        harness_root: Path,
        runtime_files: list[Path],
        runtime_warnings: list[str] | None = None,
    ):
        """Helper: run export_payload with a mocked runtime export module."""
        import z_harness_cli.adapters.codex as _mod

        rt_result = RuntimeExportResult(
            dest=dest,
            files=runtime_files,
            fidelity="flattened",
            warnings=runtime_warnings or [],
        )
        mock_export_fn = MagicMock(return_value=rt_result)
        mock_codex_export = MagicMock()
        mock_codex_export.export = mock_export_fn

        with patch.object(
            _mod,
            "__file__",
            str(harness_root / "z_harness_cli" / "adapters" / "codex.py"),
        ), patch.dict(
            "sys.modules",
            {
                "runtime.drivers.codex.export": mock_codex_export,
            },
        ):
            result = self.adapter.export_payload(dest)

        return result

    def test_files_contains_runtime_files(self):
        """export_payload() must include the runtime-export files."""
        from z_harness_cli.adapters.codex_parity_gate import codex_export_fidelity

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp).resolve()
            dest = tmp_path / "dest"
            dest.mkdir()
            harness_root = tmp_path / "harness"

            runtime_file_1 = dest / "prompts" / "z-plan.md"
            runtime_file_2 = dest / "AGENTS.md"

            result = self._run_export_with_mocks(
                dest=dest,
                harness_root=harness_root,
                runtime_files=[runtime_file_1, runtime_file_2],
            )

        self.assertEqual(result.fidelity, codex_export_fidelity())
        file_strs = [str(f) for f in result.files]
        self.assertTrue(
            any("z-plan.md" in s for s in file_strs),
            f"runtime file z-plan.md missing from files: {result.files}",
        )
        self.assertTrue(
            any("AGENTS.md" in s for s in file_strs),
            f"AGENTS.md missing from files: {result.files}",
        )

    def test_runtime_warnings_raise_runtime_error(self):
        """Non-empty runtime export warnings must raise RuntimeError (legacy hard-gate)."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp).resolve()
            dest = tmp_path / "dest"
            dest.mkdir()
            harness_root = tmp_path / "harness"

            with self.assertRaises(RuntimeError) as ctx:
                self._run_export_with_mocks(
                    dest=dest,
                    harness_root=harness_root,
                    runtime_files=[],
                    runtime_warnings=["validation error: bad prompt header"],
                )

        self.assertIn("validation error", str(ctx.exception).lower())

    def test_runtime_export_uses_gate_fidelity(self):
        """runtime.drivers.codex.export reads fidelity from codex_parity_gate."""
        from runtime.drivers.codex.export import export as codex_runtime_export
        from z_harness_cli.adapters.codex_parity_gate import codex_export_fidelity

        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp).resolve()
            result = codex_runtime_export(REPO_ROOT, dest)

        self.assertEqual(result.fidelity, codex_export_fidelity())


# ---------------------------------------------------------------------------
# Antigravity adapter — export delegation tests
# ---------------------------------------------------------------------------


class TestAntigravityExportDelegation(unittest.TestCase):
    """AntigravityAdapter.export_payload() delegates to the runtime export()."""

    def setUp(self) -> None:
        from z_harness_cli.adapters.antigravity import AntigravityAdapter
        self.adapter = AntigravityAdapter()

    def _run_export_with_mocks(
        self,
        dest: Path,
        harness_root: Path,
        runtime_files: list[Path],
        runtime_warnings: list[str] | None = None,
    ):
        """Helper: run export_payload with a mocked runtime export module."""
        import z_harness_cli.adapters.antigravity as _mod

        rt_result = RuntimeExportResult(
            dest=dest,
            files=runtime_files,
            fidelity="high",
            warnings=runtime_warnings or [],
        )
        mock_export_fn = MagicMock(return_value=rt_result)
        mock_agy_export = MagicMock()
        mock_agy_export.export = mock_export_fn

        with patch.object(
            _mod,
            "__file__",
            str(harness_root / "z_harness_cli" / "adapters" / "antigravity.py"),
        ), patch.dict(
            "sys.modules",
            {
                "runtime.drivers.antigravity.export": mock_agy_export,
            },
        ):
            result = self.adapter.export_payload(dest)

        return result

    def test_files_contains_runtime_files(self):
        """export_payload() must include the runtime-export files."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp).resolve()
            dest = tmp_path / "dest"
            dest.mkdir()
            harness_root = tmp_path / "harness"

            runtime_wf = dest / ".agent" / "workflows" / "z-plan.md"
            runtime_rule = dest / ".agent" / "rules" / "z-harness-reviewer.md"

            result = self._run_export_with_mocks(
                dest=dest,
                harness_root=harness_root,
                runtime_files=[runtime_wf, runtime_rule],
            )

        self.assertEqual(result.fidelity, "high")
        file_strs = [str(f) for f in result.files]
        self.assertTrue(
            any("z-plan.md" in s and "workflows" in s for s in file_strs),
            f"runtime workflow file missing from files: {result.files}",
        )
        self.assertTrue(
            any("z-harness-reviewer.md" in s for s in file_strs),
            f"runtime rule file missing from files: {result.files}",
        )

    def test_no_duplicate_paths(self):
        """No file path must appear more than once in ExportResult.files."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp).resolve()
            dest = tmp_path / "dest"
            dest.mkdir()
            harness_root = tmp_path / "harness"

            runtime_files = [dest / ".agent" / "workflows" / "z-plan.md"]

            result = self._run_export_with_mocks(
                dest=dest,
                harness_root=harness_root,
                runtime_files=runtime_files,
            )

        seen = set()
        for f in result.files:
            key = str(Path(f).resolve())
            self.assertNotIn(key, seen, f"Duplicate path in ExportResult.files: {key}")
            seen.add(key)

    def test_runtime_warnings_raise_runtime_error(self):
        """Non-empty runtime export warnings must raise RuntimeError (legacy hard-gate)."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp).resolve()
            dest = tmp_path / "dest"
            dest.mkdir()
            harness_root = tmp_path / "harness"

            with self.assertRaises(RuntimeError) as ctx:
                self._run_export_with_mocks(
                    dest=dest,
                    harness_root=harness_root,
                    runtime_files=[],
                    runtime_warnings=["body is empty: .agent/workflows/z-plan.md"],
                )

        self.assertIn("body is empty", str(ctx.exception))



# ---------------------------------------------------------------------------
# OMP adapter — export delegation tests
# ---------------------------------------------------------------------------


class TestOmpExportDelegation(unittest.TestCase):
    """OmpAdapter.export_payload() delegates to the runtime OMP exporter."""

    def setUp(self) -> None:
        from z_harness_cli.adapters.omp import OmpAdapter

        self.adapter = OmpAdapter()

    def test_delegates_to_runtime_export_and_uses_gate_fidelity(self):
        """OMP export delegates to the runtime exporter; fidelity is gate-driven.

        The adapter must use omp_export_fidelity() from the parity gate, NOT
        the fidelity returned by the runtime exporter.  This prevents the
        runtime exporter from claiming a higher fidelity than the gate allows.
        """
        import z_harness_cli.adapters.omp as _mod
        from z_harness_cli.adapters.omp_parity_gate import omp_export_fidelity
        expected_fidelity = omp_export_fidelity()

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp).resolve()
            dest = tmp_path / "dest"
            dest.mkdir()
            harness_root = tmp_path / "harness"
            runtime_file = dest / ".omp" / "z-harness" / "manifest.yml"
            rt_result = RuntimeExportResult(
                dest=dest,
                files=[runtime_file],
                fidelity="native",
                warnings=[],
            )
            mock_omp_export = MagicMock()
            mock_omp_export.export = MagicMock(return_value=rt_result)
            mock_omp_pkg = types.ModuleType("runtime.drivers.omp")
            mock_omp_pkg.__path__ = []  # type: ignore[attr-defined]

            with patch.object(
                _mod,
                "__file__",
                str(harness_root / "z_harness_cli" / "adapters" / "omp.py"),
            ), patch.dict(
                "sys.modules",
                {
                    "runtime.drivers.omp": mock_omp_pkg,
                    "runtime.drivers.omp.export": mock_omp_export,
                },
            ):
                result = self.adapter.export_payload(dest)

        mock_omp_export.export.assert_called_once_with(harness_root, dest)
        self.assertEqual(result.files, [runtime_file])
        # Fidelity must match the gate (not the runtime exporter's claimed value).
        self.assertEqual(result.fidelity, expected_fidelity)
        self.assertEqual(result.warnings, [])

    def test_runtime_warnings_preserve_hard_failure_gate(self):
        import z_harness_cli.adapters.omp as _mod

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp).resolve()
            dest = tmp_path / "dest"
            dest.mkdir()
            harness_root = tmp_path / "harness"
            rt_result = RuntimeExportResult(
                dest=dest,
                files=[],
                fidelity="partial",
                warnings=["collision: profile z-plan"],
            )
            mock_omp_export = MagicMock()
            mock_omp_export.export = MagicMock(return_value=rt_result)
            mock_omp_pkg = types.ModuleType("runtime.drivers.omp")
            mock_omp_pkg.__path__ = []  # type: ignore[attr-defined]

            with patch.object(
                _mod,
                "__file__",
                str(harness_root / "z_harness_cli" / "adapters" / "omp.py"),
            ), patch.dict(
                "sys.modules",
                {
                    "runtime.drivers.omp": mock_omp_pkg,
                    "runtime.drivers.omp.export": mock_omp_export,
                },
            ), self.assertRaises(RuntimeError) as ctx:
                self.adapter.export_payload(dest)

        self.assertIn("collision", str(ctx.exception).lower())


# ---------------------------------------------------------------------------
# Integration: verify ExportResult.fidelity is preserved per host
# ---------------------------------------------------------------------------


class TestFidelityPreserved(unittest.TestCase):
    """Fidelity tier must be correct per host regardless of merged content."""

    def _minimal_export(self, adapter, host: str, fidelity: str) -> RuntimeExportResult:
        """Run export_payload with fully mocked drivers."""
        import importlib
        import sys
        mod = importlib.import_module(f"z_harness_cli.adapters.{host}")
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp).resolve()
            dest = tmp_path / "dest"
            dest.mkdir()
            harness_root = tmp_path / "harness"
            harness_root.mkdir(parents=True, exist_ok=True)

            rt_result = RuntimeExportResult(
                dest=dest, files=[], fidelity=fidelity, warnings=[]
            )
            mock_export_mod = MagicMock()
            mock_export_mod.export = MagicMock(return_value=rt_result)
            host_key = "antigravity" if host == "antigravity" else host
            modules = {f"runtime.drivers.{host_key}.export": mock_export_mod}
            if host_key == "omp":
                mock_omp_pkg = types.ModuleType("runtime.drivers.omp")
                mock_omp_pkg.__path__ = []  # type: ignore[attr-defined]
                modules["runtime.drivers.omp"] = mock_omp_pkg

            with patch.object(
                mod,
                "__file__",
                str(harness_root / "z_harness_cli" / "adapters" / f"{host}.py"),
            ), patch.dict(
                "sys.modules",
                modules,
            ):
                return adapter.export_payload(dest)

    def test_cursor_fidelity_is_flattened(self):
        from z_harness_cli.adapters.cursor import CursorAdapter
        result = self._minimal_export(CursorAdapter(), "cursor", "flattened")
        self.assertEqual(result.fidelity, "flattened")

    def test_codex_fidelity_matches_parity_gate(self):
        from z_harness_cli.adapters.codex import CodexAdapter
        from z_harness_cli.adapters.codex_parity_gate import codex_export_fidelity

        result = self._minimal_export(CodexAdapter(), "codex", "native")
        self.assertEqual(result.fidelity, codex_export_fidelity())

    def test_antigravity_fidelity_is_high(self):
        from z_harness_cli.adapters.antigravity import AntigravityAdapter
        result = self._minimal_export(AntigravityAdapter(), "antigravity", "high")
        self.assertEqual(result.fidelity, "high")

    def test_omp_fidelity_matches_parity_gate(self):
        """OMP export fidelity matches the gate — not the runtime exporter's returned value.

        The gate is the single source of truth. With all T008 evidence present the
        gate returns 'native'. Removing evidence would return 'partial'. The adapter
        must use the gate's value regardless of what the runtime exporter claims.
        """
        from z_harness_cli.adapters.omp import OmpAdapter
        from z_harness_cli.adapters.omp_parity_gate import omp_export_fidelity
        expected = omp_export_fidelity()
        result = self._minimal_export(OmpAdapter(), "omp", "native")  # exporter claims native
        self.assertEqual(result.fidelity, expected)  # adapter uses gate value


if __name__ == "__main__":
    unittest.main()
