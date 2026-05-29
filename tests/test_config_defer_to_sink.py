"""
Tests for scripts/config.py defer-to-sink resolver result.

Cases covered:
  result_map_contains_defer_to_sink   — RESULT_MAP maps (workflow.spec_retro_discovery,
                                        defer_to_sink_p2) -> "defer-to-sink"
  resolve_question_returns_defer      — resolve-question returns result=="defer-to-sink"
                                        when workflow.spec_retro_discovery=defer_to_sink_p2
                                        is configured
  envelope_shape_correct              — returned JSON envelope has required fields:
                                        result, default, source, rule_id, sources
  default_is_ask                      — without config override the result is "ask"
  startup_guards_pass                 — module imports without SystemExit (guards intact)
"""

import importlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = str(_REPO_ROOT / "scripts" / "config.py")


def _clean_env(extra: dict | None = None) -> dict:
    """Return os.environ with Z_HARNESS_WORKFLOW_* and Z_HARNESS_FOLLOWUP_* stripped, then extra applied."""
    e = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith("Z_HARNESS_WORKFLOW_")
        and not k.startswith("Z_HARNESS_FOLLOWUP_")
        and k not in ("Z_HARNESS_ASK_ALL", "Z_HARNESS_NO_ASK", "Z_HARNESS_OVERNIGHT_AUTODECIDE_EFFECTIVE")
    }
    if extra:
        e.update(extra)
    return e


def _run(
    args: list[str],
    env_extra: dict | None = None,
) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, SCRIPT] + args,
        env=_clean_env(env_extra),
        capture_output=True,
        text=True,
    )


def _isolated_env(xdg_dir: str) -> dict:
    """Minimal env that isolates from any repo/user config."""
    return {
        "XDG_CONFIG_HOME": xdg_dir,
        "Z_HARNESS_REPO_CONFIG": "",
    }


class TestDeferToSinkResultMapEntry(unittest.TestCase):
    """RESULT_MAP must contain a mapping that produces 'defer-to-sink'."""

    def test_result_map_via_module(self):
        """RESULT_MAP key (workflow.spec_retro_discovery, defer_to_sink_p2) maps to defer-to-sink."""
        # We verify by calling resolve-question with the env var set to defer_to_sink_p2.
        # If the mapping exists, result=="defer-to-sink"; if missing, result defaults to "ask".
        with tempfile.TemporaryDirectory() as xdg_dir:
            result = _run(
                ["resolve-question", "workflow.spec_retro_discovery"],
                env_extra={
                    **_isolated_env(xdg_dir),
                    # env-layer override: Z_HARNESS_WORKFLOW_SPEC_RETRO_DISCOVERY=defer_to_sink_p2
                    "Z_HARNESS_WORKFLOW_SPEC_RETRO_DISCOVERY": "defer_to_sink_p2",
                },
            )
        self.assertEqual(result.returncode, 0, msg=f"stderr: {result.stderr}")
        envelope = json.loads(result.stdout)
        self.assertEqual(
            envelope["result"],
            "defer-to-sink",
            msg=f"Expected defer-to-sink, got {envelope['result']!r}. Full envelope: {envelope}",
        )


class TestDeferToSinkEnvelopeShape(unittest.TestCase):
    """Envelope returned for defer-to-sink has the required fields."""

    def test_envelope_has_required_fields(self):
        required_fields = {"result", "default", "source", "rule_id", "sources"}
        with tempfile.TemporaryDirectory() as xdg_dir:
            result = _run(
                ["resolve-question", "workflow.spec_retro_discovery"],
                env_extra={
                    **_isolated_env(xdg_dir),
                    "Z_HARNESS_WORKFLOW_SPEC_RETRO_DISCOVERY": "defer_to_sink_p2",
                },
            )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        envelope = json.loads(result.stdout)
        missing = required_fields - set(envelope.keys())
        self.assertFalse(
            missing,
            msg=f"Envelope missing fields {missing}. Got keys: {sorted(envelope.keys())}",
        )

    def test_envelope_result_is_defer_to_sink(self):
        with tempfile.TemporaryDirectory() as xdg_dir:
            result = _run(
                ["resolve-question", "workflow.spec_retro_discovery"],
                env_extra={
                    **_isolated_env(xdg_dir),
                    "Z_HARNESS_WORKFLOW_SPEC_RETRO_DISCOVERY": "defer_to_sink_p2",
                },
            )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        envelope = json.loads(result.stdout)
        self.assertEqual(envelope["result"], "defer-to-sink")

    def test_envelope_sources_is_list(self):
        with tempfile.TemporaryDirectory() as xdg_dir:
            result = _run(
                ["resolve-question", "workflow.spec_retro_discovery"],
                env_extra={
                    **_isolated_env(xdg_dir),
                    "Z_HARNESS_WORKFLOW_SPEC_RETRO_DISCOVERY": "defer_to_sink_p2",
                },
            )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        envelope = json.loads(result.stdout)
        self.assertIsInstance(envelope["sources"], list)


class TestDeferToSinkDefaultIsAsk(unittest.TestCase):
    """Without config override, workflow.spec_retro_discovery resolves to ask."""

    def test_default_result_is_ask(self):
        with tempfile.TemporaryDirectory() as xdg_dir:
            result = _run(
                ["resolve-question", "workflow.spec_retro_discovery"],
                env_extra=_isolated_env(xdg_dir),
            )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        envelope = json.loads(result.stdout)
        self.assertEqual(
            envelope["result"],
            "ask",
            msg=f"Expected ask by default, got {envelope['result']!r}",
        )


class TestDeferToSinkStartupGuards(unittest.TestCase):
    """Module startup guards must pass with the new question_id registered."""

    def test_module_import_does_not_raise(self):
        """config.py list-question-ids exits 0, confirming guards passed."""
        with tempfile.TemporaryDirectory() as xdg_dir:
            result = _run(
                ["list-question-ids"],
                env_extra=_isolated_env(xdg_dir),
            )
        self.assertEqual(
            result.returncode,
            0,
            msg=f"list-question-ids exit {result.returncode}. stderr: {result.stderr}",
        )

    def test_spec_retro_discovery_in_registry(self):
        """workflow.spec_retro_discovery appears in list-question-ids output."""
        with tempfile.TemporaryDirectory() as xdg_dir:
            result = _run(
                ["list-question-ids"],
                env_extra=_isolated_env(xdg_dir),
            )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        question_ids = json.loads(result.stdout)
        self.assertIn(
            "workflow.spec_retro_discovery",
            question_ids,
            msg=f"question_id not in registry: {question_ids}",
        )

    def test_invalid_option_exits_nonzero(self):
        """Passing an unknown option value via env exits 2 (hard validation for env layer)."""
        with tempfile.TemporaryDirectory() as xdg_dir:
            result = _run(
                ["resolve-question", "workflow.spec_retro_discovery"],
                env_extra={
                    **_isolated_env(xdg_dir),
                    "Z_HARNESS_WORKFLOW_SPEC_RETRO_DISCOVERY": "totally_invalid_value",
                },
            )
        # env-layer enum violation exits 2
        self.assertEqual(
            result.returncode,
            2,
            msg=f"Expected exit 2 on invalid enum, got {result.returncode}. stderr: {result.stderr}",
        )


if __name__ == "__main__":
    unittest.main()
