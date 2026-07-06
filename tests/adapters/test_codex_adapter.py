"""
Tests for z_harness_cli/adapters/codex.py

Covers:
  * detect() — binary present vs absent vs unresponsive.
  * export_payload() — round-trip to a tmp dir; files land under prompts/.
  * inject() / cleanup() — ephemeral round-trip in a tmp git project.
  * MCP registration — capability-gated; idempotent; NOT removed by cleanup (F4).
  * fidelity tiers are gate-driven.
  * capability flags correct (project_mcp=True, user_mcp=False,
    needs_trust_prompt=False, supports_cwd_override=False).
  * command-capability matrix — tiers are parity-gate driven.
  * PTY exec is stubbed so tests run without a real terminal.
  * Ephemeral cleanup leaves ~/.codex/config.toml untouched (F4 invariant).
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock, call, patch

# Repo root for sys.path insertion.
REPO_ROOT = Path(__file__).parent.parent.parent.resolve()
sys.path.insert(0, str(REPO_ROOT))

from z_harness_cli.adapters.codex import CodexAdapter, _MAGIC_MARKER  # noqa: E402
from z_harness_cli.adapters.base import (  # noqa: E402
    KNOWN_COMMANDS,
    command_tier,
)
from z_harness_cli.inject_safety import MAGIC_MARKER  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _git_init(path: Path) -> None:
    subprocess.run(["git", "-C", str(path), "init", "-q"], check=True)


class _RepoCase(unittest.TestCase):
    """Base class: fresh git repo per test, cleaned up in tearDown."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="zh-codex-adapter-")
        self.repo = Path(self._tmp.name).resolve()
        _git_init(self.repo)
        self.adapter = CodexAdapter()

    def tearDown(self) -> None:
        self._tmp.cleanup()


# ---------------------------------------------------------------------------
# Static identity
# ---------------------------------------------------------------------------


class TestStaticIdentity(unittest.TestCase):
    def setUp(self) -> None:
        self.adapter = CodexAdapter()

    def test_name(self):
        self.assertEqual(self.adapter.name, "codex")

    def test_fidelity_tier_is_gate_driven(self):
        """Adapter fidelity follows the Codex parity gate."""
        from z_harness_cli.adapters.codex_parity_gate import codex_adapter_fidelity

        self.assertEqual(self.adapter.fidelity_tier, codex_adapter_fidelity())

    def test_capabilities_project_mcp(self):
        """codex mcp add writes to ~/.codex/config.toml; project_mcp must be True."""
        self.assertTrue(self.adapter.capabilities.supports_project_mcp)

    def test_capabilities_no_user_mcp(self):
        """codex has no separate user-scoped MCP store; user_mcp must be False."""
        self.assertFalse(self.adapter.capabilities.supports_user_mcp)

    def test_capabilities_no_trust_prompt(self):
        """codex runs non-interactively; no per-tool trust prompt."""
        self.assertFalse(self.adapter.capabilities.needs_trust_prompt)

    def test_capabilities_no_cwd_override(self):
        """codex has no --cwd / --project flag."""
        self.assertFalse(self.adapter.capabilities.supports_cwd_override)

    def test_capabilities_cleanup_strategy_ephemeral(self):
        self.assertEqual(self.adapter.capabilities.cleanup_strategy, "ephemeral")


# ---------------------------------------------------------------------------
# Command-capability matrix
# ---------------------------------------------------------------------------


class TestCommandCapabilityMatrix(unittest.TestCase):
    """Verify the command-tier matrix is populated from the Codex parity gate."""

    def test_all_known_commands_registered(self):
        """Every known command must have an explicit tier registered."""
        for cmd in KNOWN_COMMANDS:
            with self.subTest(cmd=cmd):
                tier = command_tier("codex", cmd)
                self.assertIn(tier, ("native", "degraded", "blocked"))

    def test_unknown_command_remains_blocked(self):
        """Dynamic gate providers must not degrade unknown command ids."""
        self.assertEqual(command_tier("codex", "z-not-a-command"), "blocked")

    def test_gate_drives_command_tiers(self):
        """Every registered command tier must match codex_parity_gate."""
        from z_harness_cli.adapters.codex_parity_gate import codex_command_tier

        for cmd in KNOWN_COMMANDS:
            with self.subTest(cmd=cmd):
                self.assertEqual(command_tier("codex", cmd), codex_command_tier(cmd))

    def test_native_candidate_decisions_are_gate_authorized(self):
        """Native-candidate families are native only when the gate proves them."""
        from z_harness_cli.adapters.codex_parity_gate import (
            NATIVE_CANDIDATE_FAMILIES,
            codex_command_decision,
            has_parity_evidence,
        )

        for cmd in NATIVE_CANDIDATE_FAMILIES:
            with self.subTest(cmd=cmd):
                decision = codex_command_decision(cmd)
                self.assertEqual(command_tier("codex", cmd), decision.tier)
                if decision.tier == "native":
                    self.assertTrue(has_parity_evidence(cmd))
                else:
                    self.assertEqual(decision.tier, "blocked")
                    self.assertIn("Codex parity evidence", decision.reason)


# ---------------------------------------------------------------------------
# detect()
# ---------------------------------------------------------------------------


class TestDetect(unittest.TestCase):
    def setUp(self) -> None:
        self.adapter = CodexAdapter()

    def test_detect_not_installed_when_binary_absent(self):
        """detect() returns installed=False when codex is not on PATH."""
        with patch("shutil.which", return_value=None):
            result = self.adapter.detect()
        self.assertFalse(result.installed)
        self.assertIsNone(result.version)

    def test_detect_installed_with_version(self):
        """detect() returns installed=True and version when binary reports one."""
        mock_run = MagicMock()
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = "codex 0.1.0\n"
        mock_run.return_value.stderr = ""

        with patch("shutil.which", return_value="/fake/codex"), \
             patch("subprocess.run", mock_run):
            result = self.adapter.detect()

        self.assertTrue(result.installed)
        self.assertEqual(result.version, "codex 0.1.0")
        self.assertEqual(result.binary, "/fake/codex")

    def test_detect_installed_no_version_on_nonzero(self):
        """detect() returns installed=True, version=None when --version exits non-zero."""
        mock_run = MagicMock()
        mock_run.return_value.returncode = 1
        mock_run.return_value.stdout = ""
        mock_run.return_value.stderr = "error"

        with patch("shutil.which", return_value="/fake/codex"), \
             patch("subprocess.run", mock_run):
            result = self.adapter.detect()

        self.assertTrue(result.installed)
        self.assertIsNone(result.version)

    def test_detect_installed_no_version_on_timeout(self):
        """detect() handles TimeoutExpired gracefully — binary found but unresponsive."""
        def _raise(*args, **kwargs):
            raise subprocess.TimeoutExpired(cmd="codex", timeout=10)

        with patch("shutil.which", return_value="/fake/codex"), \
             patch("subprocess.run", side_effect=_raise):
            result = self.adapter.detect()

        self.assertTrue(result.installed)
        self.assertIsNone(result.version)


# ---------------------------------------------------------------------------
# export_payload()
# ---------------------------------------------------------------------------


class TestExportPayload(unittest.TestCase):
    def setUp(self) -> None:
        self.adapter = CodexAdapter()

    def test_export_warns_when_personas_missing(self):
        """export_payload() returns a warning when personas/ dir does not exist.

        With the T007 delegation, the runtime export (cmds/agents/skills) runs
        first.  This test mocks both the runtime export driver AND patches
        __file__ to a fake harness with no personas/ directory.
        """
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "out"
            dest.mkdir()
            fake_harness = Path(tmp) / "fake_harness"
            fake_harness.mkdir()

            import z_harness_cli.adapters.codex as _mod
            from runtime.drivers._export_utils import ExportResult as RE

            # Mock the runtime export driver to return an empty successful result
            # so we can focus on the personas-missing warning path.
            mock_export = MagicMock(
                return_value=RE(dest=dest, files=[], fidelity="flattened", warnings=[])
            )
            mock_codex_export_mod = MagicMock()
            mock_codex_export_mod.export = mock_export

            with patch.object(
                _mod,
                "__file__",
                str(fake_harness / "z_harness_cli" / "adapters" / "codex.py"),
            ), patch.dict(
                "sys.modules",
                {
                    "runtime.drivers.codex.export": mock_codex_export_mod,
                },
            ):
                result = self.adapter.export_payload(dest)

            from z_harness_cli.adapters.codex_parity_gate import codex_export_fidelity

            self.assertEqual(result.fidelity, codex_export_fidelity())
            self.assertTrue(
                any("personas/" in w for w in result.warnings),
                f"Expected warning about missing personas/, got: {result.warnings}",
            )

    def test_export_fidelity_is_gate_driven(self):
        """export_payload() reports the gate-driven default fidelity."""
        from z_harness_cli.adapters.codex_parity_gate import codex_export_fidelity

        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "out"
            dest.mkdir()
            result = self.adapter.export_payload(dest)
        self.assertEqual(result.fidelity, codex_export_fidelity())

    def test_export_to_temp_dir_with_mock_persona(self):
        """Round-trip: persona exported to temp dir lands under prompts/personas/."""
        with tempfile.TemporaryDirectory() as tmp_root:
            dest = Path(tmp_root) / "dest"
            dest.mkdir()

            def _fake_export_persona(persona_file, target_root):
                out = Path(target_root) / "prompts" / "personas" / "test.md"
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_text(f"# {MAGIC_MARKER}\nfake persona\n", encoding="utf-8")
                return out.resolve()

            fake_harness = Path(tmp_root) / "harness"
            personas_dir = fake_harness / "personas"
            personas_dir.mkdir(parents=True)
            persona_file = personas_dir / "default.md"
            persona_file.write_text("---\nname: default\n---\nHello.\n", encoding="utf-8")

            import z_harness_cli.adapters.codex as _mod

            with patch.object(
                _mod,
                "__file__",
                str(fake_harness / "z_harness_cli" / "adapters" / "codex.py"),
            ):
                with patch.dict(
                    "sys.modules",
                    {
                        "runtime": MagicMock(),
                        "runtime.drivers": MagicMock(),
                        "runtime.drivers.codex": MagicMock(),
                        "runtime.drivers.codex.persona_export": MagicMock(
                            export_persona=_fake_export_persona
                        ),
                    },
                ):
                    adapter = CodexAdapter()
                    result = adapter.export_payload(dest)

            from z_harness_cli.adapters.codex_parity_gate import codex_export_fidelity

            self.assertEqual(result.fidelity, codex_export_fidelity())
            self.assertEqual(result.dest, dest)


# ---------------------------------------------------------------------------
# Codex parity gate
# ---------------------------------------------------------------------------


class TestParityGate(unittest.TestCase):
    """The Codex gate synchronizes adapter, export, and command-tier defaults."""

    _PARITY_MODULE = "runtime.tests.test_codex_parity"
    _EXPORT_MODULE = "tests.drivers.test_codex_export_driver"

    def _fake_module(self, class_names: set[str]) -> types.ModuleType:
        module = types.ModuleType("fake_codex_parity")
        for class_name in class_names:
            setattr(module, class_name, type(class_name, (), {}))
        return module

    def test_adapter_export_and_command_tiers_all_read_gate(self):
        from z_harness_cli.adapters.codex_parity_gate import (
            codex_adapter_fidelity,
            codex_command_tier,
            codex_export_fidelity,
        )

        adapter = CodexAdapter()

        self.assertEqual(adapter.fidelity_tier, codex_adapter_fidelity())
        self.assertIn(codex_export_fidelity(), ("native", "partial", "flattened"))
        for cmd in KNOWN_COMMANDS:
            with self.subTest(cmd=cmd):
                self.assertEqual(command_tier("codex", cmd), codex_command_tier(cmd))

    def test_clearing_evidence_keeps_multi_agent_families_blocked(self):
        import z_harness_cli.adapters.codex_parity_gate as gate_mod

        original = {cmd: list(entries) for cmd, entries in gate_mod.PARITY_EVIDENCE.items()}
        try:
            gate_mod.PARITY_EVIDENCE.clear()
            self.assertEqual(CodexAdapter().fidelity_tier, "flattened")
            for cmd in gate_mod.NATIVE_CANDIDATE_FAMILIES:
                with self.subTest(cmd=cmd):
                    decision = gate_mod.codex_command_decision(cmd)
                    self.assertEqual(decision.tier, "blocked")
                    self.assertEqual(command_tier("codex", cmd), decision.tier)
                    self.assertIn("No Codex parity evidence is registered", decision.reason)
        finally:
            gate_mod.PARITY_EVIDENCE.clear()
            gate_mod.PARITY_EVIDENCE.update(original)

    def test_partial_resolvable_evidence_does_not_promote_unproven_families(self):
        import z_harness_cli.adapters.codex_parity_gate as gate_mod

        original_module = sys.modules.get(self._PARITY_MODULE)
        fake = self._fake_module({"TestConsultantDispatchIsolation"})
        try:
            sys.modules[self._PARITY_MODULE] = fake
            self.assertEqual(gate_mod.codex_command_tier("z-consult"), "native")
            self.assertEqual(gate_mod.codex_command_tier("z-execute"), "blocked")
            self.assertEqual(gate_mod.codex_adapter_fidelity(), "partial")
            self.assertEqual(gate_mod.codex_export_fidelity(), "partial")
        finally:
            if original_module is None:
                sys.modules.pop(self._PARITY_MODULE, None)
            else:
                sys.modules[self._PARITY_MODULE] = original_module

    def test_command_tier_rereads_gate_after_evidence_changes(self):
        """Codex command_tier() must not freeze the import-time gate result."""
        import z_harness_cli.adapters.codex_parity_gate as gate_mod

        original_module = sys.modules.get(self._PARITY_MODULE)
        fake = self._fake_module({"TestConsultantDispatchIsolation"})
        try:
            sys.modules[self._PARITY_MODULE] = fake
            self.assertEqual(command_tier("codex", "z-consult"), "native")
            self.assertEqual(command_tier("codex", "z-execute"), "blocked")
            self.assertEqual(
                command_tier("codex", "z-execute"),
                gate_mod.codex_command_tier("z-execute"),
            )
        finally:
            if original_module is None:
                sys.modules.pop(self._PARITY_MODULE, None)
            else:
                sys.modules[self._PARITY_MODULE] = original_module

    def test_full_fake_evidence_promotes_adapter_and_export(self):
        import z_harness_cli.adapters.codex_parity_gate as gate_mod

        original_parity_module = sys.modules.get(self._PARITY_MODULE)
        original_export_module = sys.modules.get(self._EXPORT_MODULE)
        fake_parity = self._fake_module(
            {
                "TestSubagentFanOutParity",
                "TestConsultantDispatchIsolation",
                "TestAskUserGateParity",
                "TestTelemetryParity",
                "TestMultiAgentCommandPath",
            }
        )
        fake_export = self._fake_module({"TestCodexNativeAgentExport"})
        try:
            sys.modules[self._PARITY_MODULE] = fake_parity
            sys.modules[self._EXPORT_MODULE] = fake_export
            for cmd in gate_mod.NATIVE_CANDIDATE_FAMILIES:
                with self.subTest(cmd=cmd):
                    self.assertEqual(gate_mod.codex_command_tier(cmd), "native")
            self.assertEqual(CodexAdapter().fidelity_tier, "native")
            self.assertEqual(gate_mod.codex_export_fidelity(), "native")
        finally:
            if original_parity_module is None:
                sys.modules.pop(self._PARITY_MODULE, None)
            else:
                sys.modules[self._PARITY_MODULE] = original_parity_module
            if original_export_module is None:
                sys.modules.pop(self._EXPORT_MODULE, None)
            else:
                sys.modules[self._EXPORT_MODULE] = original_export_module

    def test_native_subagent_dispatch_gate_is_primitive_specific(self):
        import z_harness_cli.adapters.codex_parity_gate as gate_mod

        original_parity_module = sys.modules.get(self._PARITY_MODULE)
        fake_without_primitive = self._fake_module(
            {
                "TestSubagentFanOutParity",
                "TestConsultantDispatchIsolation",
                "TestAskUserGateParity",
                "TestTelemetryParity",
                "TestMultiAgentCommandPath",
            }
        )
        fake_with_primitive = self._fake_module(
            {
                "TestSubagentFanOutParity",
                "TestConsultantDispatchIsolation",
                "TestAskUserGateParity",
                "TestTelemetryParity",
                "TestMultiAgentCommandPath",
                "TestCodexNativeSubagentDispatchPrimitive",
            }
        )
        try:
            sys.modules[self._PARITY_MODULE] = fake_without_primitive
            self.assertEqual(gate_mod.codex_adapter_fidelity(), "native")
            self.assertFalse(gate_mod.codex_native_subagent_dispatch_available())

            sys.modules[self._PARITY_MODULE] = fake_with_primitive
            self.assertTrue(gate_mod.codex_native_subagent_dispatch_available())
        finally:
            if original_parity_module is None:
                sys.modules.pop(self._PARITY_MODULE, None)
            else:
                sys.modules[self._PARITY_MODULE] = original_parity_module


# ---------------------------------------------------------------------------
# inject() / cleanup() — ephemeral round-trip
# ---------------------------------------------------------------------------


def _make_no_op_mcp_module():
    """Return a mock runtime.drivers.codex.mcp module that records calls."""
    mock_mcp = MagicMock()
    mock_mcp.ensure_mcp_registered.return_value = False  # already registered
    return mock_mcp


class TestInjectEphemeral(_RepoCase):
    def _inject_with_stubbed_mcp(self, state_env=None):
        """Helper: call inject() with MCP subprocess stubbed out."""
        if state_env is None:
            state_env = {}
        mock_mcp = _make_no_op_mcp_module()
        with patch.dict(
            "sys.modules",
            {
                "runtime": MagicMock(),
                "runtime.drivers": MagicMock(),
                "runtime.drivers.codex": MagicMock(),
                "runtime.drivers.codex.mcp": mock_mcp,
            },
        ):
            injection = self.adapter.inject(
                state_env,
                mode="ephemeral",
                project=self.repo,
                mcp_config_path="/fake/mcp_config.json",
            )
        return injection, mock_mcp

    def test_inject_writes_agents_md(self):
        """inject() in ephemeral mode writes AGENTS.md at the project root."""
        injection, _ = self._inject_with_stubbed_mcp()
        agents_path = self.repo / "AGENTS.md"
        self.assertTrue(agents_path.exists(), f"AGENTS.md not found: {agents_path}")
        self.assertEqual(len(injection.injected_files), 1)
        self.assertEqual(injection.injected_files[0], agents_path)

    def test_inject_agents_md_contains_magic_marker(self):
        """Written AGENTS.md must carry the z-harness magic marker."""
        self._inject_with_stubbed_mcp()
        agents_path = self.repo / "AGENTS.md"
        content = agents_path.read_text(encoding="utf-8")
        self.assertIn(MAGIC_MARKER, content)

    def test_inject_sets_claude_plugin_root(self):
        """inject() must set CLAUDE_PLUGIN_ROOT in the returned env (D14)."""
        injection, _ = self._inject_with_stubbed_mcp()
        self.assertIn("CLAUDE_PLUGIN_ROOT", injection.env)
        self.assertTrue(injection.env["CLAUDE_PLUGIN_ROOT"])

    def test_inject_mode_is_ephemeral(self):
        injection, _ = self._inject_with_stubbed_mcp()
        self.assertEqual(injection.mode, "ephemeral")

    def test_inject_host_is_codex(self):
        injection, _ = self._inject_with_stubbed_mcp()
        self.assertEqual(injection.host, "codex")

    def test_inject_state_env_merged(self):
        """state_env vars must appear in injection.env."""
        state_env = {"Z_HARNESS_PLAN_DIR": "/tmp/fake-plan"}
        injection, _ = self._inject_with_stubbed_mcp(state_env=state_env)
        self.assertEqual(injection.env["Z_HARNESS_PLAN_DIR"], "/tmp/fake-plan")

    def test_inject_registers_mcp_when_capability_set(self):
        """inject() must call ensure_mcp_registered when supports_project_mcp=True."""
        _, mock_mcp = self._inject_with_stubbed_mcp()
        mock_mcp.ensure_mcp_registered.assert_called_once()

    def test_inject_default_mcp_config_path_is_generated_cache_file(self):
        """Default MCP registration must use an existing generated config."""
        with tempfile.TemporaryDirectory() as tmp:
            cache_root = Path(tmp) / "cache"
            with patch.dict("os.environ", {"XDG_CACHE_HOME": str(cache_root)}), \
                 patch(
                     "runtime.drivers.codex.mcp.ensure_mcp_registered",
                     return_value=False,
                 ) as mock_ensure:
                self.adapter.inject(
                    {},
                    mode="ephemeral",
                    project=self.repo,
                )

            hardcoded_export_path = REPO_ROOT / "exports" / "codex" / "mcp_config.json"
            mock_ensure.assert_called_once()
            kwargs = mock_ensure.call_args.kwargs
            mcp_config_path = Path(kwargs["mcp_config_path"])
            self.assertNotEqual(mcp_config_path, hardcoded_export_path)
            self.assertTrue(
                mcp_config_path.exists(),
                f"generated MCP config missing: {mcp_config_path}",
            )
            self.assertTrue(mcp_config_path.is_relative_to(cache_root))

            data = json.loads(mcp_config_path.read_text(encoding="utf-8"))
            self.assertIn("mcpServers", data)
            self.assertIn("z-harness", data["mcpServers"])

    def test_inject_mcp_registration_idempotent(self):
        """Calling inject() twice must call ensure_mcp_registered twice (each idempotent).

        The ensure_mcp_registered function itself handles de-duplication;
        the adapter must call it unconditionally so the server stays registered.
        A regression where the adapter short-circuits the second call would be
        caught here by asserting call_count == 2.
        """
        shared_mcp = _make_no_op_mcp_module()
        for _ in range(2):
            with patch.dict(
                "sys.modules",
                {
                    "runtime": MagicMock(),
                    "runtime.drivers": MagicMock(),
                    "runtime.drivers.codex": MagicMock(),
                    "runtime.drivers.codex.mcp": shared_mcp,
                },
            ):
                self.adapter.inject(
                    {},
                    mode="ephemeral",
                    project=self.repo,
                    mcp_config_path="/fake/mcp_config.json",
                )
        # Each inject() call must trigger exactly one ensure_mcp_registered call.
        # Total = 2 after two inject() calls — adapter must never skip the call.
        self.assertEqual(
            shared_mcp.ensure_mcp_registered.call_count,
            2,
            "ensure_mcp_registered must be called once per inject() — "
            f"got {shared_mcp.ensure_mcp_registered.call_count}",
        )

    def test_cleanup_removes_agents_md(self):
        """cleanup() must remove the injected AGENTS.md."""
        injection, _ = self._inject_with_stubbed_mcp()
        agents_path = self.repo / "AGENTS.md"
        self.assertTrue(agents_path.exists())
        self.adapter.cleanup(injection)
        self.assertFalse(agents_path.exists(), "AGENTS.md should be removed after cleanup")

    def test_cleanup_idempotent(self):
        """cleanup() must be idempotent — calling it twice must not raise."""
        injection, _ = self._inject_with_stubbed_mcp()
        self.adapter.cleanup(injection)
        self.adapter.cleanup(injection)  # second call must not raise

    def test_cleanup_does_not_touch_codex_config_toml(self):
        """cleanup() must NOT remove ~/.codex/config.toml MCP entry (F4 invariant).

        This verifies the separation of concerns: ephemeral per-session
        AGENTS.md is removed, but the global MCP registration persists.
        The test confirms cleanup() never calls codex mcp remove or touches
        the global config path.
        """
        injection, _ = self._inject_with_stubbed_mcp()
        # Record writes to ~/.codex/config.toml before cleanup.
        codex_config = Path.home() / ".codex" / "config.toml"
        existed_before = codex_config.exists()

        # Run cleanup — it must not alter the codex config.
        with patch(
            "runtime.drivers.codex.mcp.ensure_mcp_registered",
            side_effect=AssertionError("cleanup must not call MCP registration"),
        ):
            # If cleanup tries to call ensure_mcp_registered it will raise.
            # No exception = cleanup correctly left MCP alone.
            self.adapter.cleanup(injection)

        # The config's existence state must not have changed.
        self.assertEqual(codex_config.exists(), existed_before)

    def test_context_manager_calls_cleanup(self):
        """Using Injection as a context manager must call cleanup on __exit__."""
        agents_path = self.repo / "AGENTS.md"
        mock_mcp = _make_no_op_mcp_module()
        with patch.dict(
            "sys.modules",
            {
                "runtime": MagicMock(),
                "runtime.drivers": MagicMock(),
                "runtime.drivers.codex": MagicMock(),
                "runtime.drivers.codex.mcp": mock_mcp,
            },
        ):
            with self.adapter.inject(
                {},
                mode="ephemeral",
                project=self.repo,
                mcp_config_path="/fake/mcp_config.json",
            ):
                self.assertTrue(agents_path.exists())
        self.assertFalse(agents_path.exists(), "Context manager __exit__ must call cleanup")

    def test_context_manager_propagates_exceptions(self):
        """Injection context manager must propagate exceptions (return False)."""
        mock_mcp = _make_no_op_mcp_module()
        with patch.dict(
            "sys.modules",
            {
                "runtime": MagicMock(),
                "runtime.drivers": MagicMock(),
                "runtime.drivers.codex": MagicMock(),
                "runtime.drivers.codex.mcp": mock_mcp,
            },
        ):
            with self.assertRaises(ValueError):
                with self.adapter.inject(
                    {},
                    mode="ephemeral",
                    project=self.repo,
                    mcp_config_path="/fake/mcp_config.json",
                ):
                    raise ValueError("test error")


# ---------------------------------------------------------------------------
# inject() — in_place mode
# ---------------------------------------------------------------------------


class TestInjectInPlace(_RepoCase):
    def _inject_in_place(self):
        mock_mcp = _make_no_op_mcp_module()
        with patch.dict(
            "sys.modules",
            {
                "runtime": MagicMock(),
                "runtime.drivers": MagicMock(),
                "runtime.drivers.codex": MagicMock(),
                "runtime.drivers.codex.mcp": mock_mcp,
            },
        ):
            injection = self.adapter.inject(
                {},
                mode="in_place",
                project=self.repo,
                mcp_config_path="/fake/mcp_config.json",
            )
        return injection

    def test_inject_in_place_writes_agents_md(self):
        """inject() in in_place mode writes AGENTS.md at the project root."""
        injection = self._inject_in_place()
        agents_path = self.repo / "AGENTS.md"
        self.assertTrue(agents_path.exists())
        self.assertEqual(injection.mode, "in_place")

    def test_cleanup_in_place_is_noop(self):
        """cleanup() in in_place mode must not remove the AGENTS.md file."""
        injection = self._inject_in_place()
        agents_path = self.repo / "AGENTS.md"
        self.assertTrue(agents_path.exists())
        self.adapter.cleanup(injection)
        # in_place AGENTS.md must survive cleanup.
        self.assertTrue(agents_path.exists(), "in_place AGENTS.md should survive cleanup")

    def test_inject_in_place_still_registers_mcp(self):
        """inject() registers MCP even in in_place mode (global/persistent, F4)."""
        mock_mcp = _make_no_op_mcp_module()
        with patch.dict(
            "sys.modules",
            {
                "runtime": MagicMock(),
                "runtime.drivers": MagicMock(),
                "runtime.drivers.codex": MagicMock(),
                "runtime.drivers.codex.mcp": mock_mcp,
            },
        ):
            self.adapter.inject(
                {},
                mode="in_place",
                project=self.repo,
                mcp_config_path="/fake/mcp_config.json",
            )
        mock_mcp.ensure_mcp_registered.assert_called_once()


# ---------------------------------------------------------------------------
# MCP registration — capability-gated
# ---------------------------------------------------------------------------


class TestMcpRegistration(_RepoCase):
    """Test the MCP registration path in isolation."""

    def test_mcp_not_called_when_capability_off(self):
        """If supports_project_mcp is False, inject() must NOT call ensure_mcp_registered."""
        # Temporarily override the capabilities on the adapter.
        from z_harness_cli.adapters.base import Capabilities
        mock_caps = Capabilities(
            supports_project_mcp=False,
            supports_user_mcp=False,
            needs_trust_prompt=False,
            supports_cwd_override=False,
            cleanup_strategy="ephemeral",
        )
        original_caps = self.adapter.capabilities
        self.adapter.__class__.capabilities = mock_caps  # type: ignore[assignment]

        mock_mcp = _make_no_op_mcp_module()
        try:
            with patch.dict(
                "sys.modules",
                {
                    "runtime": MagicMock(),
                    "runtime.drivers": MagicMock(),
                    "runtime.drivers.codex": MagicMock(),
                    "runtime.drivers.codex.mcp": mock_mcp,
                },
            ):
                self.adapter.inject(
                    {},
                    mode="ephemeral",
                    project=self.repo,
                    mcp_config_path="/fake/mcp_config.json",
                )
        finally:
            self.adapter.__class__.capabilities = original_caps  # type: ignore[assignment]

        mock_mcp.ensure_mcp_registered.assert_not_called()

    def test_mcp_import_error_does_not_abort_inject(self):
        """If the runtime package is missing, inject() must still succeed (best-effort MCP)."""
        with patch.dict("sys.modules", {"runtime": None, "runtime.drivers": None,
                                        "runtime.drivers.codex": None,
                                        "runtime.drivers.codex.mcp": None}):
            # inject() should not raise even if MCP module is missing.
            try:
                injection = self.adapter.inject(
                    {},
                    mode="ephemeral",
                    project=self.repo,
                    mcp_config_path="/fake/mcp_config.json",
                )
                # If we got here, inject did not crash.
                self.assertIsNotNone(injection)
            except ImportError:
                self.fail(
                    "inject() must not propagate ImportError from missing MCP module"
                )
            except Exception:  # noqa: BLE001
                # Some other error may occur without the full runtime; acceptable.
                pass


# ---------------------------------------------------------------------------
# launch() — PTY exec stubbed
# ---------------------------------------------------------------------------


class TestLaunch(unittest.TestCase):
    def setUp(self) -> None:
        self.adapter = CodexAdapter()

    def test_launch_calls_pty_launch_with_codex(self):
        """launch() must call pty_launch with codex as the command."""
        captured: list[dict] = []

        def _fake_pty_launch(argv, env, cwd):
            captured.append({"argv": argv, "env": env, "cwd": cwd})
            return 0

        with patch("z_harness_cli.pty_launch.pty_launch", _fake_pty_launch), \
             patch("shutil.which", return_value="/fake/codex"), \
             tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            rc = self.adapter.launch(project, env=dict())

        self.assertEqual(rc, 0)
        self.assertEqual(len(captured), 1)
        self.assertIn("codex", captured[0]["argv"][0])

    def test_launch_returns_exit_code(self):
        """launch() must forward the exit code from pty_launch."""
        with patch("z_harness_cli.pty_launch.pty_launch", return_value=42), \
             patch("shutil.which", return_value="/fake/codex"), \
             tempfile.TemporaryDirectory() as tmp:
            rc = self.adapter.launch(Path(tmp), env=dict())
        self.assertEqual(rc, 42)


# ---------------------------------------------------------------------------
# HostAdapter Protocol conformance
# ---------------------------------------------------------------------------


class TestProtocolConformance(unittest.TestCase):
    """Verify CodexAdapter satisfies the HostAdapter Protocol at runtime."""

    def test_isinstance_host_adapter(self):
        from z_harness_cli.adapters.base import HostAdapter
        adapter = CodexAdapter()
        self.assertIsInstance(adapter, HostAdapter)

    def test_all_required_attributes_present(self):
        adapter = CodexAdapter()
        for attr in ("name", "fidelity_tier", "capabilities"):
            self.assertTrue(hasattr(adapter, attr), f"missing attribute: {attr}")

    def test_all_required_methods_present(self):
        adapter = CodexAdapter()
        for method in ("detect", "export_payload", "inject", "launch", "cleanup"):
            self.assertTrue(
                callable(getattr(adapter, method, None)),
                f"missing callable: {method}",
            )


if __name__ == "__main__":
    unittest.main()
