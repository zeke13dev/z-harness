"""Tests for OmpAdapter (T002).

Covers identity, partial/degraded command tiers, PATH detection, session-scoped
injection, launch delegation, export delegation, and HostAdapter conformance.
"""

from __future__ import annotations
import importlib

from contextlib import contextmanager, ExitStack
import subprocess
import shutil
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

REPO_ROOT = Path(__file__).parent.parent.parent.resolve()
sys.path.insert(0, str(REPO_ROOT))

pi_export = importlib.import_module("runtime.drivers.pi.export")  # noqa: E402
pi_pkg = importlib.import_module("runtime.drivers.pi")  # noqa: E402
from runtime.drivers._export_utils import ExportResult as RuntimeExportResult  # noqa: E402
from z_harness_cli.adapters.base import (  # noqa: E402
    KNOWN_COMMANDS,
    HostAdapter,
    Injection,
    command_tier,
)
from z_harness_cli.adapters.omp import OmpAdapter  # noqa: E402
from z_harness_cli import inject_safety  # noqa: E402


def _git_init(path: Path) -> None:
    subprocess.run(["git", "-C", str(path), "init", "-q"], check=True)



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

class TestStaticIdentity(unittest.TestCase):
    def setUp(self) -> None:
        self.adapter = OmpAdapter()

    def test_name(self):
        self.assertEqual(self.adapter.name, "omp")

    def test_fidelity_tier_is_native_when_all_parity_evidence_present(self):
        """Adapter fidelity_tier is native when all T008 evidence resolves.

        The parity gate (omp_parity_gate) drives the tier; no hardcoded constant.
        This test will downgrade to 'partial' automatically when any T008 class
        is removed — see TestParityGate.test_removing_evidence_downgrades_tier.
        """
        from z_harness_cli.adapters.omp_parity_gate import omp_adapter_fidelity
        expected = omp_adapter_fidelity()
        self.assertEqual(self.adapter.fidelity_tier, expected)
        # With all five T008 test classes present the gate returns native.
        self.assertEqual(self.adapter.fidelity_tier, "native")

    def test_capabilities_are_ephemeral(self):
        caps = self.adapter.capabilities
        self.assertFalse(caps.supports_project_mcp)
        self.assertFalse(caps.supports_user_mcp)
        self.assertFalse(caps.needs_trust_prompt)
        self.assertFalse(caps.supports_cwd_override)
        self.assertEqual(caps.cleanup_strategy, "ephemeral")


class TestCommandCapabilityMatrix(unittest.TestCase):
    """Command tiers are driven by the parity gate, not hardcoded constants.

    These tests reflect the gate-driven tiers with all T008 evidence present.
    The parity gate (omp_parity_gate) is the authoritative source; these tests
    confirm the adapter correctly delegates to it.
    """

    # Commands that have T008 parity evidence and are promoted to native.
    _PARITY_NATIVE = {"z-execute", "z-panel", "z-consult", "z-gate"}
    # Commands with no T008 evidence — remain degraded.
    _DEGRADED = set(KNOWN_COMMANDS) - _PARITY_NATIVE

    def test_parity_proven_commands_are_native(self):
        """Commands with T008 parity evidence are promoted to native by the gate."""
        for cmd in self._PARITY_NATIVE:
            with self.subTest(cmd=cmd):
                self.assertEqual(command_tier("omp", cmd), "native")

    def test_unproven_commands_remain_degraded(self):
        """Commands without T008 evidence remain degraded (not native, not blocked)."""
        for cmd in self._DEGRADED:
            with self.subTest(cmd=cmd):
                self.assertEqual(command_tier("omp", cmd), "degraded")

    def test_gate_drives_command_tiers_not_hardcoded_constant(self):
        """Adapter delegates to omp_command_tier() for every command family."""
        from z_harness_cli.adapters.omp_parity_gate import omp_command_tier
        for cmd in KNOWN_COMMANDS:
            with self.subTest(cmd=cmd):
                expected = omp_command_tier(cmd)
                self.assertEqual(command_tier("omp", cmd), expected)


class TestDetect(unittest.TestCase):
    def setUp(self) -> None:
        self.adapter = OmpAdapter()

    def test_detect_not_installed_when_binary_absent(self):
        with patch("shutil.which", return_value=None):
            result = self.adapter.detect()
        self.assertFalse(result.installed)
        self.assertIsNone(result.version)

    def test_detect_installed_with_version(self):
        mock_run = MagicMock()
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = "omp 0.3.0\n"
        mock_run.return_value.stderr = ""

        with patch("shutil.which", return_value="/fake/omp"), patch("subprocess.run", mock_run):
            result = self.adapter.detect()

        self.assertTrue(result.installed)
        self.assertEqual(result.version, "omp 0.3.0")
        self.assertEqual(result.binary, "/fake/omp")
        mock_run.assert_called_once()
        self.assertEqual(mock_run.call_args.args[0], ["/fake/omp", "--version"])

    def test_detect_installed_no_version_on_nonzero(self):
        mock_run = MagicMock()
        mock_run.return_value.returncode = 1
        mock_run.return_value.stdout = ""
        mock_run.return_value.stderr = "error"

        with patch("shutil.which", return_value="/fake/omp"), patch("subprocess.run", mock_run):
            result = self.adapter.detect()

        self.assertTrue(result.installed)
        self.assertIsNone(result.version)

    def test_detect_installed_no_version_on_timeout(self):
        def _raise(*args, **kwargs):
            raise subprocess.TimeoutExpired(cmd="omp", timeout=10)

        with patch("shutil.which", return_value="/fake/omp"), patch("subprocess.run", side_effect=_raise):
            result = self.adapter.detect()

        self.assertTrue(result.installed)
        self.assertIsNone(result.version)


class TestExportPayload(unittest.TestCase):
    def setUp(self) -> None:
        self.adapter = OmpAdapter()

    def test_real_runtime_exporter_writes_gate_driven_fidelity_omp_package(self):
        """Export fidelity is gate-driven (native when T008 evidence present).

        The adapter reads fidelity from omp_export_fidelity(), not a hardcoded
        constant. With all T008 evidence resolvable this returns 'native'.
        Removing any T008 class would drop this back to 'partial'.
        """
        from z_harness_cli.adapters.omp_parity_gate import omp_export_fidelity
        expected_fidelity = omp_export_fidelity()

        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp)
            with _forbid_pi_or_consult_compatibility():
                result = self.adapter.export_payload(dest)

        self.assertEqual(result.fidelity, expected_fidelity)
        self.assertEqual(result.warnings, [])
        self.assertTrue(any(Path(f).match("*/.omp/z-harness/manifest.yml") for f in result.files))

    def test_delegates_to_runtime_export_when_available(self):
        import z_harness_cli.adapters.omp as _mod

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
            mock_export_mod = MagicMock()
            mock_export_mod.export = MagicMock(return_value=rt_result)
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
                    "runtime.drivers.omp.export": mock_export_mod,
                },
            ):
                result = self.adapter.export_payload(dest)

        from z_harness_cli.adapters.omp_parity_gate import omp_export_fidelity
        mock_export_mod.export.assert_called_once_with(harness_root, dest)
        self.assertEqual(result.files, [runtime_file])
        # Adapter uses gate-driven fidelity, not the runtime exporter's returned value.
        self.assertEqual(result.fidelity, omp_export_fidelity())
        self.assertEqual(result.warnings, [])

    def test_runtime_warnings_raise_runtime_error(self):
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
                warnings=["missing manifest"],
            )
            mock_export_mod = MagicMock()
            mock_export_mod.export = MagicMock(return_value=rt_result)
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
                    "runtime.drivers.omp.export": mock_export_mod,
                },
            ):
                with self.assertRaises(RuntimeError) as ctx:
                    self.adapter.export_payload(dest)

        self.assertIn("missing manifest", str(ctx.exception))


class TestInjectLaunchCleanup(unittest.TestCase):
    def setUp(self) -> None:
        self.adapter = OmpAdapter()
        self._tmp = tempfile.TemporaryDirectory()
        self.project = Path(self._tmp.name).resolve()
        _git_init(self.project)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _session_file(self) -> Path:
        return self.project / ".omp" / "z-harness" / "session.yml"

    def test_ephemeral_inject_sets_only_omp_plugin_root_and_session_file(self):
        config = self.project / ".omp" / "config.yml"
        config.parent.mkdir(parents=True, exist_ok=True)
        config.write_text("skills:\n  enableAgentsProject: false\n", encoding="utf-8")

        with patch.dict(
            "os.environ",
            {
                "PATH": "/usr/bin",
                "CLAUDE_PLUGIN_ROOT": "/wrong/claude",
                "ANTIGRAVITY_PLUGIN_ROOT": "/wrong/agy",
            },
            clear=True,
        ):
            injection = self.adapter.inject({"STATE": "ok"}, "ephemeral", self.project)

        target = self._session_file()
        expected_plugin_root = str(target.parent)
        self.assertEqual(injection.env["STATE"], "ok")
        self.assertEqual(injection.env["OMP_PLUGIN_ROOT"], expected_plugin_root)
        self.assertNotIn("CLAUDE_PLUGIN_ROOT", injection.env)
        self.assertNotIn("ANTIGRAVITY_PLUGIN_ROOT", injection.env)
        self.assertEqual(injection.injected_files, [target])
        self.assertEqual(injection.host, "omp")
        self.assertEqual(injection.mode, "ephemeral")
        self.assertTrue(target.exists())
        self.assertIn("z-harness:injected", target.read_text(encoding="utf-8"))
        self.assertIn("OMP_PLUGIN_ROOT=", target.read_text(encoding="utf-8"))
        self.assertEqual(
            config.read_text(encoding="utf-8"),
            "skills:\n  enableAgentsProject: false\n",
        )
        self.assertIn(
            ".omp/z-harness/session.yml",
            (self.project / ".gitignore").read_text(encoding="utf-8"),
        )

    def test_ephemeral_inject_overrides_bundle_omp_plugin_root_with_session_root(self):
        with patch.dict("os.environ", {"PATH": "/usr/bin"}, clear=True):
            injection = self.adapter.inject(
                {"OMP_PLUGIN_ROOT": "/bundle/root"},
                "ephemeral",
                self.project,
            )

        expected_plugin_root = str(self._session_file().parent)
        session_body = self._session_file().read_text(encoding="utf-8")
        self.assertEqual(injection.env["OMP_PLUGIN_ROOT"], expected_plugin_root)
        self.assertIn(expected_plugin_root, session_body)
        self.assertNotIn("/bundle/root", session_body)

    def test_ephemeral_inject_refuses_foreign_session_file(self):
        target = self._session_file()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("user-owned omp state\n", encoding="utf-8")

        with patch.dict("os.environ", {"PATH": "/usr/bin"}, clear=True):
            with self.assertRaises(inject_safety.ClobberRefused):
                self.adapter.inject({"OMP_PLUGIN_ROOT": "/bundle/root"}, "ephemeral", self.project)

        self.assertEqual(target.read_text(encoding="utf-8"), "user-owned omp state\n")

    def test_in_place_preserves_bundle_without_adding_omp_plugin_root(self):
        with patch.dict("os.environ", {"PATH": "/usr/bin"}, clear=True):
            injection = self.adapter.inject({"STATE": "ok"}, "in_place", self.project)

        self.assertEqual(injection.env["STATE"], "ok")
        self.assertNotIn("OMP_PLUGIN_ROOT", injection.env)
        self.assertEqual(injection.injected_files, [])
        self.assertFalse(self._session_file().exists())

    def test_cleanup_is_idempotent_and_removes_session_file(self):
        with patch.dict("os.environ", {"PATH": "/usr/bin"}, clear=True):
            injection = self.adapter.inject({"OMP_PLUGIN_ROOT": "/bundle/root"}, "ephemeral", self.project)

        self.assertTrue(self._session_file().exists())
        self.adapter.cleanup(injection)
        self.adapter.cleanup(injection)

        self.assertFalse(self._session_file().exists())
        self.assertFalse(self._session_file().parent.exists())
        self.assertEqual(inject_safety.detect_orphans(self.project), [])

    def test_cleanup_noops_without_injected_files(self):
        injection = Injection(env={}, host="omp")
        self.adapter.cleanup(injection)

    def test_launch_routes_omp_through_wrapped_pty_with_supplied_env(self):
        seen = {}

        def _fake_pty_launch(argv, env, cwd, cleanup=None):
            seen["argv"] = argv
            seen["env"] = env
            seen["cwd"] = cwd
            seen["cleanup"] = cleanup
            return 17

        with patch("shutil.which", return_value="/usr/local/bin/omp"), patch(
            "z_harness_cli.pty_launch.pty_launch",
            side_effect=_fake_pty_launch,
        ):
            supplied_env = {"OMP_PLUGIN_ROOT": "/plugin", "Z_HARNESS_PLAN_DIR": "/plan"}
            rc = self.adapter.launch(self.project, supplied_env)

        self.assertEqual(rc, 17)
        self.assertEqual(seen["argv"], ["/usr/local/bin/omp"])
        self.assertIs(seen["env"], supplied_env)
        self.assertEqual(seen["cwd"], self.project)
        self.assertIsNone(seen["cleanup"])


class TestProtocolConformance(unittest.TestCase):
    def test_omp_adapter_satisfies_host_adapter_protocol(self):
        adapter = OmpAdapter()
        self.assertIsInstance(adapter, HostAdapter)
        for method in ("detect", "export_payload", "inject", "launch", "cleanup"):
            self.assertTrue(callable(getattr(adapter, method, None)), method)


# ---------------------------------------------------------------------------
# T009: Parity gate synchronization tests
#
# These tests prove the acceptance criteria for T009:
#   1. Adapter fidelity, export fidelity, and command tiers cannot diverge.
#   2. Removing any required parity test prevents native promotion.
#   3. Only proven command families are promoted to native.
# ---------------------------------------------------------------------------


class TestParityGate(unittest.TestCase):
    """The single parity gate synchronizes all three OMP fidelity surfaces."""

    def test_adapter_fidelity_export_fidelity_and_command_tiers_all_agree(self):
        """All three surfaces report the same gate state — they cannot diverge.

        Adapter fidelity_tier, export fidelity from export_payload(), and the
        per-command tiers in COMMAND_CAPABILITY_MATRIX are all driven by the
        same omp_parity_gate module.  No surface may claim a stronger tier than
        what the gate authorizes.
        """
        from z_harness_cli.adapters.omp_parity_gate import (
            omp_adapter_fidelity,
            omp_export_fidelity,
            omp_command_tier,
        )
        adapter = OmpAdapter()

        gate_adapter = omp_adapter_fidelity()
        gate_export = omp_export_fidelity()

        # All three gate functions must agree.
        self.assertEqual(gate_adapter, gate_export,
                         "Adapter fidelity and export fidelity diverged at the gate")

        # Adapter.fidelity_tier must match the gate.
        self.assertEqual(adapter.fidelity_tier, gate_adapter,
                         "OmpAdapter.fidelity_tier diverged from omp_adapter_fidelity()")

        # Every command tier must match what the gate says.
        for cmd in KNOWN_COMMANDS:
            with self.subTest(cmd=cmd):
                self.assertEqual(
                    command_tier("omp", cmd),
                    omp_command_tier(cmd),
                    f"COMMAND_CAPABILITY_MATRIX['omp']['{cmd}'] diverged from gate",
                )

    def test_removing_parity_evidence_downgrades_adapter_fidelity_to_partial(self):
        """Removing any T008 evidence entry drops adapter fidelity back to partial.

        The gate keys promotion off the existence of PARITY_EVIDENCE entries.
        With an empty registry no command family has proof, so the adapter must
        report 'partial' — never 'native' through speculation.
        """
        import z_harness_cli.adapters.omp_parity_gate as gate_mod
        original = dict(gate_mod.PARITY_EVIDENCE)
        try:
            gate_mod.PARITY_EVIDENCE.clear()
            adapter = OmpAdapter()
            self.assertEqual(adapter.fidelity_tier, "partial",
                             "Adapter claimed native fidelity with no parity evidence")
        finally:
            gate_mod.PARITY_EVIDENCE.update(original)

    def test_removing_parity_evidence_downgrades_export_fidelity_to_partial(self):
        """Removing T008 evidence drops export fidelity to partial.

        The export path (omp_export_fidelity()) reads the same gate as the
        adapter, so removing evidence degrades both surfaces atomically.
        """
        import z_harness_cli.adapters.omp_parity_gate as gate_mod
        original = dict(gate_mod.PARITY_EVIDENCE)
        try:
            gate_mod.PARITY_EVIDENCE.clear()
            from z_harness_cli.adapters.omp_parity_gate import omp_export_fidelity
            self.assertEqual(omp_export_fidelity(), "partial",
                             "Export claimed native fidelity with no parity evidence")
        finally:
            gate_mod.PARITY_EVIDENCE.update(original)

    def test_removing_parity_evidence_downgrades_command_tiers(self):
        """Removing T008 evidence for a family downgrades it from native to degraded.

        The command-capability matrix is populated at module load time from the
        gate; but the adapter re-reads omp_command_tier() dynamically.  With
        evidence cleared a formerly-native family must not claim native.
        """
        import z_harness_cli.adapters.omp_parity_gate as gate_mod
        original = dict(gate_mod.PARITY_EVIDENCE)
        try:
            gate_mod.PARITY_EVIDENCE.clear()
            # Direct gate call — reflects cleared state.
            for cmd in KNOWN_COMMANDS:
                with self.subTest(cmd=cmd):
                    tier = gate_mod.omp_command_tier(cmd)
                    self.assertNotEqual(tier, "native",
                        f"Command {cmd!r} claimed native tier with no parity evidence")
        finally:
            gate_mod.PARITY_EVIDENCE.update(original)

    def test_removing_single_evidence_entry_blocks_that_family(self):
        """Removing parity evidence for one command blocks (not degrades) that family.

        When a family's evidence slot exists in PARITY_EVIDENCE but all its
        test classes are unresolvable (e.g. renamed), the gate returns 'blocked'
        rather than 'degraded' — the broken evidence is a stricter signal than
        'no evidence at all'.
        """
        import z_harness_cli.adapters.omp_parity_gate as gate_mod
        original = dict(gate_mod.PARITY_EVIDENCE)
        try:
            # Inject an entry with a class that doesn't exist.
            gate_mod.PARITY_EVIDENCE["z-execute"] = [
                ("runtime.tests.test_omp_parity", "NonExistentParityClass"),
            ]
            tier = gate_mod.omp_command_tier("z-execute")
            self.assertEqual(tier, "blocked",
                "Broken evidence entry should block the command, not degrade it")
        finally:
            gate_mod.PARITY_EVIDENCE.clear()
            gate_mod.PARITY_EVIDENCE.update(original)

    def test_parity_evidence_entries_are_all_resolvable(self):
        """Every entry in PARITY_EVIDENCE resolves to a real T008 test class.

        This test fails immediately if a T008 class is renamed or moved without
        updating PARITY_EVIDENCE — keeping the registry honest.
        """
        import importlib
        import z_harness_cli.adapters.omp_parity_gate as gate_mod
        for cmd, entries in gate_mod.PARITY_EVIDENCE.items():
            for module_path, class_name in entries:
                with self.subTest(cmd=cmd, cls=class_name):
                    try:
                        mod = importlib.import_module(module_path)
                    except ImportError as exc:
                        self.fail(
                            f"PARITY_EVIDENCE[{cmd!r}] references unimportable module "
                            f"{module_path!r}: {exc}"
                        )
                    self.assertTrue(
                        hasattr(mod, class_name),
                        f"PARITY_EVIDENCE[{cmd!r}] references non-existent class "
                        f"{class_name!r} in {module_path!r}",
                    )

    def test_native_promotion_only_for_families_with_mapped_parity_evidence(self):
        """Only command families in PARITY_EVIDENCE may be promoted to native.

        Every 'native' tier in the command matrix must have a corresponding
        entry in PARITY_EVIDENCE.  A family that is native but has no evidence
        entry is an overclaim — this test catches it.
        """
        import z_harness_cli.adapters.omp_parity_gate as gate_mod
        for cmd in KNOWN_COMMANDS:
            with self.subTest(cmd=cmd):
                tier = command_tier("omp", cmd)
                if tier == "native":
                    self.assertIn(
                        cmd,
                        gate_mod.PARITY_EVIDENCE,
                        f"Command {cmd!r} is promoted to native but has no "
                        "PARITY_EVIDENCE entry — this is an overclaim",
                    )


if __name__ == "__main__":
    unittest.main()
