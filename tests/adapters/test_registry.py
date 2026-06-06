"""
Tests for z_harness_cli/adapters/registry.py (T012)

Covers:
  * detect_all() — returns one entry per adapter; installed flag correct.
  * detect_all() — skips no host; list always has all four adapters.
  * select(host=...) — --host override resolves to the right adapter.
  * select(host=...) — unknown host raises UnknownHostError.
  * select() (auto, interactive=False) — returns installed host when one present.
  * select() (auto, interactive=False) — first canonical when multiple installed.
  * select() — raises NoHostInstalledError when none installed.
  * Rich picker path — patched to verify it is invoked when multiple installed
    and interactive=True (integration path; actual terminal not required).
  * Adapter import triggers register_command_tiers so command_tier() works.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# Insert repo root so absolute imports work when run directly.
REPO_ROOT = Path(__file__).parent.parent.parent.resolve()
sys.path.insert(0, str(REPO_ROOT))

from z_harness_cli.adapters.registry import (  # noqa: E402
    NoHostInstalledError,
    UnknownHostError,
    _ADAPTER_BY_NAME,
    _ALL_ADAPTERS,
    detect_all,
    select,
)
from z_harness_cli.adapters.base import DetectResult, command_tier  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _installed_result(version: str = "1.0.0", binary: str = "/usr/bin/fake") -> DetectResult:
    return DetectResult(installed=True, version=version, binary=binary)


def _not_installed_result() -> DetectResult:
    return DetectResult(installed=False)


def _patch_all_detect(installed_names: set[str]):
    """Return a context manager that patches every adapter's detect() so that
    only adapters whose name is in *installed_names* report installed=True."""

    def _make_detect_patch(adapter_name: str):
        if adapter_name in installed_names:
            return MagicMock(return_value=_installed_result(binary=f"/fake/{adapter_name}"))
        return MagicMock(return_value=_not_installed_result())

    patches = []
    for adapter in _ALL_ADAPTERS:
        mock_fn = _make_detect_patch(adapter.name)
        p = patch.object(adapter, "detect", mock_fn)
        patches.append(p)

    class _CM:
        def __enter__(self):
            for p in patches:
                p.start()
            return self

        def __exit__(self, *_):
            for p in patches:
                p.stop()

    return _CM()


# ---------------------------------------------------------------------------
# detect_all()
# ---------------------------------------------------------------------------


class TestDetectAll(unittest.TestCase):
    """detect_all() must probe every adapter and return all results."""

    def test_returns_all_four_adapters(self):
        """detect_all() always returns an entry for every registered adapter."""
        with patch.object(
            _ALL_ADAPTERS[0], "detect", return_value=_not_installed_result()
        ), patch.object(
            _ALL_ADAPTERS[1], "detect", return_value=_not_installed_result()
        ), patch.object(
            _ALL_ADAPTERS[2], "detect", return_value=_not_installed_result()
        ), patch.object(
            _ALL_ADAPTERS[3], "detect", return_value=_not_installed_result()
        ):
            results = detect_all()

        self.assertEqual(len(results), 4, "detect_all() must return one entry per adapter")

    def test_each_entry_is_adapter_detect_pair(self):
        """Each entry must be a (HostAdapter, DetectResult) pair."""
        from z_harness_cli.adapters.base import HostAdapter

        with _patch_all_detect(set()):
            results = detect_all()

        for adapter, result in results:
            self.assertIsInstance(adapter, HostAdapter)
            self.assertIsInstance(result, DetectResult)

    def test_installed_flag_reflects_probe(self):
        """detect_all() must propagate installed=True from the adapter's detect()."""
        with _patch_all_detect({"claude"}):
            results = detect_all()

        installed_names = {a.name for a, r in results if r.installed}
        self.assertIn("claude", installed_names)
        self.assertNotIn("cursor", installed_names)
        self.assertNotIn("codex", installed_names)
        self.assertNotIn("antigravity", installed_names)

    def test_all_installed_when_all_present(self):
        """detect_all() reports all installed when all probes return installed=True."""
        with _patch_all_detect({"claude", "cursor", "codex", "antigravity"}):
            results = detect_all()

        for adapter, result in results:
            self.assertTrue(
                result.installed,
                f"Expected {adapter.name} to be installed; got installed=False",
            )

    def test_detect_called_once_per_adapter(self):
        """detect_all() calls detect() exactly once per adapter per invocation."""
        mocks = []
        patches = []
        for adapter in _ALL_ADAPTERS:
            m = MagicMock(return_value=_not_installed_result())
            p = patch.object(adapter, "detect", m)
            mocks.append(m)
            patches.append(p)

        for p in patches:
            p.start()
        try:
            detect_all()
        finally:
            for p in patches:
                p.stop()

        for m in mocks:
            m.assert_called_once()


# ---------------------------------------------------------------------------
# select() — --host override
# ---------------------------------------------------------------------------


class TestSelectHostOverride(unittest.TestCase):
    """select(host=...) resolves the named adapter regardless of install state."""

    def test_host_claude_resolves_claude_adapter(self):
        """select(host='claude') must return the ClaudeAdapter."""
        with _patch_all_detect({"claude"}):
            adapter, result = select(host="claude", interactive=False)
        self.assertEqual(adapter.name, "claude")

    def test_host_cursor_resolves_cursor_adapter(self):
        with _patch_all_detect({"cursor"}):
            adapter, result = select(host="cursor", interactive=False)
        self.assertEqual(adapter.name, "cursor")

    def test_host_codex_resolves_codex_adapter(self):
        with _patch_all_detect({"codex"}):
            adapter, result = select(host="codex", interactive=False)
        self.assertEqual(adapter.name, "codex")

    def test_host_antigravity_resolves_antigravity_adapter(self):
        with _patch_all_detect({"antigravity"}):
            adapter, result = select(host="antigravity", interactive=False)
        self.assertEqual(adapter.name, "antigravity")

    def test_host_override_calls_detect_on_named_adapter(self):
        """select(host=...) must call detect() to populate the DetectResult."""
        fake_result = _installed_result(version="9.9.9", binary="/custom/claude")
        with patch.object(_ADAPTER_BY_NAME["claude"], "detect", return_value=fake_result):
            adapter, result = select(host="claude", interactive=False)
        self.assertEqual(result.version, "9.9.9")
        self.assertEqual(result.binary, "/custom/claude")

    def test_unknown_host_raises_unknown_host_error(self):
        """select(host='bogus') must raise UnknownHostError."""
        with self.assertRaises(UnknownHostError) as ctx:
            select(host="bogus", interactive=False)

        # The error message must include the bad name and valid names.
        self.assertIn("bogus", str(ctx.exception))
        self.assertIn("claude", str(ctx.exception))

    def test_unknown_host_error_message_lists_valid_hosts(self):
        """UnknownHostError message must enumerate known valid hosts."""
        try:
            select(host="nonexistent", interactive=False)
        except UnknownHostError as exc:
            msg = str(exc)
            for name in _ADAPTER_BY_NAME:
                self.assertIn(name, msg, f"Valid host '{name}' missing from error: {msg}")
        else:
            self.fail("Expected UnknownHostError was not raised")


# ---------------------------------------------------------------------------
# select() — auto (no --host)
# ---------------------------------------------------------------------------


class TestSelectAuto(unittest.TestCase):
    """select() without a host arg auto-detects from installed adapters."""

    def test_single_installed_host_returned_directly(self):
        """When exactly one host is installed, select() must return it without prompting."""
        with _patch_all_detect({"cursor"}):
            adapter, result = select(interactive=False)
        self.assertEqual(adapter.name, "cursor")
        self.assertTrue(result.installed)

    def test_no_host_installed_raises_no_host_installed_error(self):
        """select() must raise NoHostInstalledError when no adapter is installed."""
        with _patch_all_detect(set()):
            with self.assertRaises(NoHostInstalledError) as ctx:
                select(interactive=False)
        # Error message must mention at least one known host name.
        msg = str(ctx.exception)
        self.assertTrue(
            any(name in msg for name in _ADAPTER_BY_NAME),
            f"Expected host names in error message, got: {msg}",
        )

    def test_multiple_installed_non_interactive_returns_first_canonical(self):
        """With interactive=False and multiple installed, returns first in canonical order."""
        # claude and codex both installed
        with _patch_all_detect({"claude", "codex"}):
            adapter, result = select(interactive=False)
        # claude is first in _ALL_ADAPTERS (native fidelity)
        self.assertEqual(adapter.name, "claude")

    def test_multiple_installed_interactive_calls_picker(self):
        """With interactive=True and multiple installed, the Rich picker is invoked."""
        # We patch _rich_picker_rich to avoid needing a real terminal, and verify it's called.
        with _patch_all_detect({"claude", "cursor"}):
            # Patch the internal picker to return the first installed entry.
            with patch(
                "z_harness_cli.adapters.registry._rich_picker",
                side_effect=lambda installed: installed[0],
            ) as mock_picker:
                adapter, result = select(interactive=True)

        mock_picker.assert_called_once()
        # The picker received the installed subset, not the full four-adapter list.
        call_args = mock_picker.call_args[0][0]
        installed_names = {a.name for a, _ in call_args}
        self.assertIn("claude", installed_names)
        self.assertIn("cursor", installed_names)
        self.assertNotIn("codex", installed_names)
        self.assertNotIn("antigravity", installed_names)

    def test_select_single_host_no_picker(self):
        """select() with interactive=True but only one installed host must skip the picker."""
        with _patch_all_detect({"antigravity"}):
            with patch(
                "z_harness_cli.adapters.registry._rich_picker",
            ) as mock_picker:
                adapter, result = select(interactive=True)

        mock_picker.assert_not_called()
        self.assertEqual(adapter.name, "antigravity")


# ---------------------------------------------------------------------------
# _ADAPTER_BY_NAME — registry completeness
# ---------------------------------------------------------------------------


class TestRegistryCompleteness(unittest.TestCase):
    """Sanity checks on the registry contents."""

    def test_all_four_hosts_registered(self):
        """The registry must contain entries for all four supported hosts."""
        for name in ("claude", "cursor", "codex", "antigravity"):
            self.assertIn(name, _ADAPTER_BY_NAME, f"Host '{name}' missing from registry")

    def test_no_duplicate_names(self):
        """No two adapters in _ALL_ADAPTERS may share a name."""
        names = [a.name for a in _ALL_ADAPTERS]
        self.assertEqual(len(names), len(set(names)), "Duplicate adapter names detected")

    def test_adapter_by_name_matches_all_adapters(self):
        """_ADAPTER_BY_NAME must contain exactly the same adapters as _ALL_ADAPTERS."""
        self.assertEqual(set(_ADAPTER_BY_NAME.keys()), {a.name for a in _ALL_ADAPTERS})

    def test_importing_registry_registers_command_tiers(self):
        """Importing the registry must register command tiers for all four hosts.

        This verifies the import-time side-effect: each adapter module calls
        register_command_tiers() at import time, which is required before
        command_tier() can return meaningful results.

        Failure class: if an adapter module is NOT imported, command_tier()
        returns 'blocked' for all commands — the registry is incomplete.
        """
        from z_harness_cli.adapters.base import COMMAND_CAPABILITY_MATRIX, KNOWN_COMMANDS

        for host in ("claude", "cursor", "codex", "antigravity"):
            self.assertIn(
                host,
                COMMAND_CAPABILITY_MATRIX,
                f"Host '{host}' not in COMMAND_CAPABILITY_MATRIX after importing registry; "
                "registry must import all adapter modules to trigger register_command_tiers()",
            )
            for cmd in KNOWN_COMMANDS:
                tier = command_tier(host, cmd)
                self.assertIn(
                    tier,
                    ("native", "degraded", "blocked"),
                    f"command_tier('{host}', '{cmd}') returned unexpected value {tier!r}",
                )

    def test_cursor_command_tiers_populated_after_registry_import(self):
        """cursor command tiers must be queryable after importing the registry.

        This specifically guards the T009/T012 note: CursorAdapter's
        register_command_tiers('cursor', ...) runs at import time; the registry
        must import cursor.py so the matrix is populated before any caller
        queries it.
        """
        # cursor module is imported via registry; multi-agent commands are blocked.
        multi_agent = {"z-implement-all", "z-panel", "z-consult", "z-gate"}
        for cmd in multi_agent:
            tier = command_tier("cursor", cmd)
            self.assertEqual(
                tier,
                "blocked",
                f"cursor/{cmd} should be blocked after registry import, got {tier!r}",
            )


# ---------------------------------------------------------------------------
# Error type checks
# ---------------------------------------------------------------------------


class TestErrorTypes(unittest.TestCase):
    """Verify exception hierarchy is correct."""

    def test_unknown_host_error_is_value_error(self):
        self.assertTrue(issubclass(UnknownHostError, ValueError))

    def test_no_host_installed_error_is_runtime_error(self):
        self.assertTrue(issubclass(NoHostInstalledError, RuntimeError))


if __name__ == "__main__":
    unittest.main()
