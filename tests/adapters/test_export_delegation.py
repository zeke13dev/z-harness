"""
T007: Tests for export_payload() delegation to runtime export() + persona loop.

Verifies across all three adapters (cursor, codex, antigravity):
  * export_payload() calls runtime/drivers/<t>/export.py::export() for
    commands/agents/skills AND runs the persona loop — files from both
    stages appear in the merged ExportResult.
  * No duplicate paths in the merged files list.
  * Non-empty warnings from the runtime export are surfaced as RuntimeError
    (legacy hard-gate is preserved).
  * Collision assert: persona names that overlap command/agent/skill ids
    raise RuntimeError with a clear message.
  * The runtime-owned ExportResult is the single canonical type (BLOCKER-1).
"""

from __future__ import annotations

import sys
import tempfile
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
    """CursorAdapter.export_payload() delegates to runtime export() then persona loop."""

    def setUp(self) -> None:
        from z_harness_cli.adapters.cursor import CursorAdapter
        self.adapter = CursorAdapter()

    def _run_export_with_mocks(
        self,
        dest: Path,
        harness_root: Path,
        runtime_files: list[Path],
        persona_files: list[Path],
        runtime_warnings: list[str] | None = None,
    ):
        """Helper: run export_payload with mocked runtime export + persona modules."""
        import z_harness_cli.adapters.cursor as _mod

        personas_dir = harness_root / "personas" / "builtin"
        personas_dir.mkdir(parents=True, exist_ok=True)
        for pf in persona_files:
            pf.write_text("---\nname: test\n---\nHello.\n", encoding="utf-8")

        rt_result = RuntimeExportResult(
            dest=dest,
            files=runtime_files,
            fidelity="flattened",
            warnings=runtime_warnings or [],
        )
        mock_export_fn = MagicMock(return_value=rt_result)
        mock_cursor_export = MagicMock()
        mock_cursor_export.export = mock_export_fn

        exported_persona_paths: list[Path] = []

        def _fake_export_persona(persona_file, target_root):
            out = Path(target_root) / ".cursor" / "personas" / (persona_file.stem + ".mdc")
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text("fake persona content", encoding="utf-8")
            exported_persona_paths.append(out.resolve())
            return out.resolve()

        mock_pe = MagicMock()
        mock_pe.export_persona = _fake_export_persona

        with patch.object(
            _mod,
            "__file__",
            str(harness_root / "z_harness_cli" / "adapters" / "cursor.py"),
        ), patch.dict(
            "sys.modules",
            {
                "runtime.drivers.cursor.export": mock_cursor_export,
                "runtime.drivers.cursor.persona_export": mock_pe,
            },
        ):
            result = self.adapter.export_payload(dest)

        return result, exported_persona_paths

    def test_files_contains_both_runtime_and_persona_files(self):
        """export_payload() must include BOTH runtime-export files AND persona files."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp).resolve()
            dest = tmp_path / "dest"
            dest.mkdir()
            harness_root = tmp_path / "harness"

            # Simulate runtime export producing 2 .mdc files.
            runtime_file_1 = dest / ".cursor" / "rules" / "z-plan.mdc"
            runtime_file_2 = dest / ".cursor" / "rules" / "z-implement.mdc"
            persona_source = harness_root / "personas" / "builtin" / "assistant.md"

            result, _ = self._run_export_with_mocks(
                dest=dest,
                harness_root=harness_root,
                runtime_files=[runtime_file_1, runtime_file_2],
                persona_files=[persona_source],
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
        # Persona file must also be in the result.
        self.assertTrue(
            any("personas" in s and "assistant.mdc" in s for s in file_strs),
            f"persona file assistant.mdc missing from files: {result.files}",
        )

    def test_no_duplicate_paths(self):
        """No file path must appear more than once in ExportResult.files."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp).resolve()
            dest = tmp_path / "dest"
            dest.mkdir()
            harness_root = tmp_path / "harness"

            runtime_files = [dest / ".cursor" / "rules" / "z-plan.mdc"]
            persona_source = harness_root / "personas" / "builtin" / "helper.md"

            result, _ = self._run_export_with_mocks(
                dest=dest,
                harness_root=harness_root,
                runtime_files=runtime_files,
                persona_files=[persona_source],
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
                    persona_files=[],
                    runtime_warnings=["validation error: missing frontmatter in z-plan.mdc"],
                )

        self.assertIn("validation error", str(ctx.exception).lower())

    def test_persona_collision_raises_runtime_error(self):
        """Persona name that collides with a command/agent/skill id must raise RuntimeError."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp).resolve()
            dest = tmp_path / "dest"
            dest.mkdir()
            harness_root = tmp_path / "harness"
            personas_dir = harness_root / "personas" / "builtin"
            personas_dir.mkdir(parents=True, exist_ok=True)

            # Persona file named "z-plan" — same as a runtime command id.
            collision_persona = personas_dir / "z-plan.md"
            collision_persona.write_text("---\nname: z-plan\n---\nPersona.\n", encoding="utf-8")

            import z_harness_cli.adapters.cursor as _mod

            # Runtime export emits z-plan.mdc (stem = "z-plan").
            runtime_file = dest / ".cursor" / "rules" / "z-plan.mdc"
            rt_result = RuntimeExportResult(
                dest=dest,
                files=[runtime_file],
                fidelity="flattened",
                warnings=[],
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
            ), self.assertRaises(RuntimeError) as ctx:
                self.adapter.export_payload(dest)

        self.assertIn("collision", str(ctx.exception).lower())
        self.assertIn("z-plan", str(ctx.exception))


# ---------------------------------------------------------------------------
# Codex adapter — export delegation tests
# ---------------------------------------------------------------------------


class TestCodexExportDelegation(unittest.TestCase):
    """CodexAdapter.export_payload() delegates to runtime export() then persona loop."""

    def setUp(self) -> None:
        from z_harness_cli.adapters.codex import CodexAdapter
        self.adapter = CodexAdapter()

    def _run_export_with_mocks(
        self,
        dest: Path,
        harness_root: Path,
        runtime_files: list[Path],
        persona_files: list[Path],
        runtime_warnings: list[str] | None = None,
    ):
        """Helper: run export_payload with mocked runtime export + persona modules."""
        import z_harness_cli.adapters.codex as _mod

        personas_dir = harness_root / "personas" / "builtin"
        personas_dir.mkdir(parents=True, exist_ok=True)
        for pf in persona_files:
            pf.write_text("---\nname: test\n---\nHello.\n", encoding="utf-8")

        rt_result = RuntimeExportResult(
            dest=dest,
            files=runtime_files,
            fidelity="flattened",
            warnings=runtime_warnings or [],
        )
        mock_export_fn = MagicMock(return_value=rt_result)
        mock_codex_export = MagicMock()
        mock_codex_export.export = mock_export_fn

        def _fake_export_persona(persona_file, target_root):
            out = Path(target_root) / "prompts" / "personas" / (persona_file.stem + ".md")
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text("fake persona content", encoding="utf-8")
            return out.resolve()

        mock_pe = MagicMock()
        mock_pe.export_persona = _fake_export_persona

        with patch.object(
            _mod,
            "__file__",
            str(harness_root / "z_harness_cli" / "adapters" / "codex.py"),
        ), patch.dict(
            "sys.modules",
            {
                "runtime.drivers.codex.export": mock_codex_export,
                "runtime.drivers.codex.persona_export": mock_pe,
            },
        ):
            result = self.adapter.export_payload(dest)

        return result

    def test_files_contains_both_runtime_and_persona_files(self):
        """export_payload() must include BOTH runtime-export files AND persona files."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp).resolve()
            dest = tmp_path / "dest"
            dest.mkdir()
            harness_root = tmp_path / "harness"

            runtime_file_1 = dest / "prompts" / "z-plan.md"
            runtime_file_2 = dest / "AGENTS.md"
            persona_source = harness_root / "personas" / "builtin" / "architect.md"

            result = self._run_export_with_mocks(
                dest=dest,
                harness_root=harness_root,
                runtime_files=[runtime_file_1, runtime_file_2],
                persona_files=[persona_source],
            )

        self.assertEqual(result.fidelity, "flattened")
        file_strs = [str(f) for f in result.files]
        self.assertTrue(
            any("z-plan.md" in s for s in file_strs),
            f"runtime file z-plan.md missing from files: {result.files}",
        )
        self.assertTrue(
            any("AGENTS.md" in s for s in file_strs),
            f"AGENTS.md missing from files: {result.files}",
        )
        self.assertTrue(
            any("personas" in s and "architect.md" in s for s in file_strs),
            f"persona file architect.md missing from files: {result.files}",
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
                    persona_files=[],
                    runtime_warnings=["validation error: bad prompt header"],
                )

        self.assertIn("validation error", str(ctx.exception).lower())

    def test_persona_collision_in_prompts_namespace_raises(self):
        """Persona name that collides with a prompt file id must raise RuntimeError.

        Codex flat prompts/ is the real collision risk (MINOR-6).
        """
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp).resolve()
            dest = tmp_path / "dest"
            dest.mkdir()
            harness_root = tmp_path / "harness"
            personas_dir = harness_root / "personas" / "builtin"
            personas_dir.mkdir(parents=True, exist_ok=True)

            # Persona named "z-implement" — same stem as a runtime command file.
            collision_persona = personas_dir / "z-implement.md"
            collision_persona.write_text("---\nname: z-implement\n---\nPersona.\n", encoding="utf-8")

            import z_harness_cli.adapters.codex as _mod

            runtime_file = dest / "prompts" / "z-implement.md"
            rt_result = RuntimeExportResult(
                dest=dest,
                files=[runtime_file],
                fidelity="flattened",
                warnings=[],
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
            ), self.assertRaises(RuntimeError) as ctx:
                self.adapter.export_payload(dest)

        self.assertIn("collision", str(ctx.exception).lower())
        self.assertIn("z-implement", str(ctx.exception))


# ---------------------------------------------------------------------------
# Antigravity adapter — export delegation tests
# ---------------------------------------------------------------------------


class TestAntigravityExportDelegation(unittest.TestCase):
    """AntigravityAdapter.export_payload() delegates to runtime export() then persona loop."""

    def setUp(self) -> None:
        from z_harness_cli.adapters.antigravity import AntigravityAdapter
        self.adapter = AntigravityAdapter()

    def _run_export_with_mocks(
        self,
        dest: Path,
        harness_root: Path,
        runtime_files: list[Path],
        persona_files: list[Path],
        runtime_warnings: list[str] | None = None,
    ):
        """Helper: run export_payload with mocked runtime export + persona modules."""
        import z_harness_cli.adapters.antigravity as _mod

        personas_dir = harness_root / "personas" / "builtin"
        personas_dir.mkdir(parents=True, exist_ok=True)
        for pf in persona_files:
            pf.write_text("---\nname: test\n---\nHello.\n", encoding="utf-8")

        rt_result = RuntimeExportResult(
            dest=dest,
            files=runtime_files,
            fidelity="high",
            warnings=runtime_warnings or [],
        )
        mock_export_fn = MagicMock(return_value=rt_result)
        mock_agy_export = MagicMock()
        mock_agy_export.export = mock_export_fn

        def _fake_export_persona(persona_file, target_root):
            out = Path(target_root) / ".agent" / "personas" / (persona_file.stem + ".md")
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text("fake persona content", encoding="utf-8")
            return out.resolve()

        mock_pe = MagicMock()
        mock_pe.export_persona = _fake_export_persona

        with patch.object(
            _mod,
            "__file__",
            str(harness_root / "z_harness_cli" / "adapters" / "antigravity.py"),
        ), patch.dict(
            "sys.modules",
            {
                "runtime.drivers.antigravity.export": mock_agy_export,
                "runtime.drivers.antigravity.persona_export": mock_pe,
            },
        ):
            result = self.adapter.export_payload(dest)

        return result

    def test_files_contains_both_runtime_and_persona_files(self):
        """export_payload() must include BOTH runtime-export files AND persona files."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp).resolve()
            dest = tmp_path / "dest"
            dest.mkdir()
            harness_root = tmp_path / "harness"

            runtime_wf = dest / ".agent" / "workflows" / "z-plan.md"
            runtime_rule = dest / ".agent" / "rules" / "z-harness-reviewer.md"
            persona_source = harness_root / "personas" / "builtin" / "researcher.md"

            result = self._run_export_with_mocks(
                dest=dest,
                harness_root=harness_root,
                runtime_files=[runtime_wf, runtime_rule],
                persona_files=[persona_source],
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
        self.assertTrue(
            any("personas" in s and "researcher.md" in s for s in file_strs),
            f"persona file researcher.md missing from files: {result.files}",
        )

    def test_no_duplicate_paths(self):
        """No file path must appear more than once in ExportResult.files."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp).resolve()
            dest = tmp_path / "dest"
            dest.mkdir()
            harness_root = tmp_path / "harness"

            runtime_files = [dest / ".agent" / "workflows" / "z-plan.md"]
            persona_source = harness_root / "personas" / "builtin" / "helper.md"

            result = self._run_export_with_mocks(
                dest=dest,
                harness_root=harness_root,
                runtime_files=runtime_files,
                persona_files=[persona_source],
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
                    persona_files=[],
                    runtime_warnings=["body is empty: .agent/workflows/z-plan.md"],
                )

        self.assertIn("body is empty", str(ctx.exception))

    def test_persona_collision_raises_runtime_error(self):
        """Persona name that collides with a command/agent/skill id must raise RuntimeError."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp).resolve()
            dest = tmp_path / "dest"
            dest.mkdir()
            harness_root = tmp_path / "harness"
            personas_dir = harness_root / "personas" / "builtin"
            personas_dir.mkdir(parents=True, exist_ok=True)

            # Persona named "z-plan" — same as a workflow command id.
            collision_persona = personas_dir / "z-plan.md"
            collision_persona.write_text("---\nname: z-plan\n---\nPersona.\n", encoding="utf-8")

            import z_harness_cli.adapters.antigravity as _mod

            # Runtime emits a workflow file with stem "z-plan".
            runtime_file = dest / ".agent" / "workflows" / "z-plan.md"
            rt_result = RuntimeExportResult(
                dest=dest,
                files=[runtime_file],
                fidelity="high",
                warnings=[],
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
            ), self.assertRaises(RuntimeError) as ctx:
                self.adapter.export_payload(dest)

        self.assertIn("collision", str(ctx.exception).lower())
        self.assertIn("z-plan", str(ctx.exception))


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
            (harness_root / "personas" / "builtin").mkdir(parents=True, exist_ok=True)

            rt_result = RuntimeExportResult(
                dest=dest, files=[], fidelity=fidelity, warnings=[]
            )
            mock_export_mod = MagicMock()
            mock_export_mod.export = MagicMock(return_value=rt_result)

            host_key = "antigravity" if host == "antigravity" else host
            with patch.object(
                mod,
                "__file__",
                str(harness_root / "z_harness_cli" / "adapters" / f"{host}.py"),
            ), patch.dict(
                "sys.modules",
                {f"runtime.drivers.{host_key}.export": mock_export_mod},
            ):
                return adapter.export_payload(dest)

    def test_cursor_fidelity_is_flattened(self):
        from z_harness_cli.adapters.cursor import CursorAdapter
        result = self._minimal_export(CursorAdapter(), "cursor", "flattened")
        self.assertEqual(result.fidelity, "flattened")

    def test_codex_fidelity_is_flattened(self):
        from z_harness_cli.adapters.codex import CodexAdapter
        result = self._minimal_export(CodexAdapter(), "codex", "flattened")
        self.assertEqual(result.fidelity, "flattened")

    def test_antigravity_fidelity_is_high(self):
        from z_harness_cli.adapters.antigravity import AntigravityAdapter
        result = self._minimal_export(AntigravityAdapter(), "antigravity", "high")
        self.assertEqual(result.fidelity, "high")


class TestRealPersonaExportRegression(unittest.TestCase):
    """Regression for the personas/builtin/ glob bug.

    The CLI adapters globbed ``personas/*.md`` (non-recursive) while persona
    sources live in ``personas/builtin/*.md`` (moved there by the
    personas-and-roles reorg). Fresh exports therefore emitted ZERO personas,
    silently — the committed exports/ retained stale pre-reorg personas, masking
    it until a regen. The other delegation tests mock ``export_persona`` and so
    never exercised the real glob against the real personas/ tree; this one runs
    each real adapter end-to-end and asserts every builtin persona is exported.
    """

    def _expected_builtin_count(self) -> int:
        repo_root = Path(__file__).resolve().parents[2]
        builtin = repo_root / "personas" / "builtin"
        n = len(list(builtin.glob("*.md")))
        self.assertGreater(n, 0, "no personas/builtin/*.md sources found in repo")
        return n

    @staticmethod
    def _count_persona_outputs(dest: Path) -> int:
        return sum(
            1 for p in dest.rglob("*") if p.is_file() and "personas" in p.parts
        )

    def test_antigravity_exports_all_builtin_personas(self):
        from z_harness_cli.adapters.antigravity import AntigravityAdapter

        expected = self._expected_builtin_count()
        with tempfile.TemporaryDirectory() as td:
            dest = Path(td)
            AntigravityAdapter().export_payload(dest)
            self.assertGreaterEqual(self._count_persona_outputs(dest), expected)

    def test_cursor_exports_all_builtin_personas(self):
        from z_harness_cli.adapters.cursor import CursorAdapter

        expected = self._expected_builtin_count()
        with tempfile.TemporaryDirectory() as td:
            dest = Path(td)
            CursorAdapter().export_payload(dest)
            self.assertGreaterEqual(self._count_persona_outputs(dest), expected)

    def test_codex_exports_all_builtin_personas(self):
        from z_harness_cli.adapters.codex import CodexAdapter

        expected = self._expected_builtin_count()
        with tempfile.TemporaryDirectory() as td:
            dest = Path(td)
            CodexAdapter().export_payload(dest)
            self.assertGreaterEqual(self._count_persona_outputs(dest), expected)

    def test_claude_exports_all_builtin_personas(self):
        from z_harness_cli.adapters.claude import ClaudeAdapter

        expected = self._expected_builtin_count()
        with tempfile.TemporaryDirectory() as td:
            dest = Path(td)
            ClaudeAdapter().export_payload(dest)
            self.assertGreaterEqual(self._count_persona_outputs(dest), expected)


if __name__ == "__main__":
    unittest.main()
