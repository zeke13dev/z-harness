"""
tests/test_amend_gate_decision.py — Unit tests for scripts/amend-gate-decision.py

Covers all four canonical rows from the INTENT acceptance checklist (#2 / #5):
  Row 1 — source=="none"       → auto_split  (fresh user, no stored preference)
  Row 2 — explicit-preference-ask (source=config/memory + result=ask) → force_ask
  Row 3 — result=="skip"       → auto_split  (user set auto-amend preference)
  Row 4 — result=="halt"       → halt        (user set stop preference)

Also covers edge cases:
  - result=="prefill" + source=="memory" → force_ask (second explicit-ask variant)
  - unlisted combination → auto_split (safe default fallback)
  - halt takes precedence over explicit source (Rule 1 first)
"""

import json
import subprocess
import sys
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = str(_REPO_ROOT / "scripts" / "amend-gate-decision.py")


def _run(resolver: dict) -> str:
    """Invoke the script with the given resolver dict and return the stdout token."""
    raw = json.dumps(resolver)
    result = subprocess.run(
        [sys.executable, SCRIPT, raw],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"script exited {result.returncode}; stderr={result.stderr!r}"
    )
    return result.stdout.strip()


class TestAmendGateDecisionCanonicalRows(unittest.TestCase):
    """The four rows mandated by the acceptance checklist."""

    def test_row1_source_none_yields_auto_split(self):
        """Row 1: source=="none" → auto_split (new default for fresh users)."""
        token = _run({"result": "ask", "source": "none", "default": "amend"})
        self.assertEqual(token, "auto_split")

    def test_row2_explicit_preference_ask_config_yields_force_ask(self):
        """Row 2a: source=="config" + result=="ask" → force_ask."""
        token = _run({"result": "ask", "source": "config", "default": "amend"})
        self.assertEqual(token, "force_ask")

    def test_row2_explicit_preference_ask_memory_yields_force_ask(self):
        """Row 2b: source=="memory" + result=="ask" → force_ask."""
        token = _run({"result": "ask", "source": "memory", "default": "amend"})
        self.assertEqual(token, "force_ask")

    def test_row3_result_skip_yields_auto_split(self):
        """Row 3: result=="skip" → auto_split (user configured auto-amend)."""
        token = _run({"result": "skip", "source": "config", "default": "amend"})
        self.assertEqual(token, "auto_split")

    def test_row4_result_halt_yields_halt(self):
        """Row 4: result=="halt" → halt (user configured stop)."""
        token = _run({"result": "halt", "source": "config", "default": "amend"})
        self.assertEqual(token, "halt")


class TestAmendGateDecisionEdgeCases(unittest.TestCase):
    """Additional invariant-enforcement cases."""

    def test_halt_takes_precedence_over_source_none(self):
        """Rule 1 (halt) fires before Rule 3 (source==none)."""
        # Even if source=="none", a halt result must still halt.
        token = _run({"result": "halt", "source": "none", "default": "amend"})
        self.assertEqual(token, "halt")

    def test_prefill_plus_memory_yields_force_ask(self):
        """result=="prefill" + source=="memory" is a second explicit-ask variant → force_ask."""
        token = _run({"result": "prefill", "source": "memory", "default": "amend"})
        self.assertEqual(token, "force_ask")

    def test_prefill_plus_config_yields_force_ask(self):
        """result=="prefill" + source=="config" → force_ask."""
        token = _run({"result": "prefill", "source": "config", "default": "amend"})
        self.assertEqual(token, "force_ask")

    def test_skip_with_source_none_yields_auto_split(self):
        """result=="skip" fires before source=="none" check — still auto_split."""
        token = _run({"result": "skip", "source": "none", "default": "amend"})
        self.assertEqual(token, "auto_split")

    def test_unlisted_combination_yields_auto_split(self):
        """Unlisted combination (Rule 5 fallback) → auto_split, not an error."""
        token = _run({"result": "proceed", "source": "override", "default": "amend"})
        self.assertEqual(token, "auto_split")

    def test_extra_fields_ignored(self):
        """Resolver envelopes have many extra fields; only result/source matter."""
        resolver = {
            "result": "ask",
            "source": "none",
            "default": "amend",
            "rule_id": "workflow.audit_to_amend",
            "strength": "none",
            "reason": "No config preference set",
            "sources": [],
        }
        token = _run(resolver)
        self.assertEqual(token, "auto_split")


class TestAmendGateDecisionInvalidInput(unittest.TestCase):
    """Error handling: bad input must exit non-zero, not silently return wrong token."""

    def test_missing_result_field_exits_nonzero(self):
        raw = json.dumps({"source": "none", "default": "amend"})
        result = subprocess.run(
            [sys.executable, SCRIPT, raw],
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(result.returncode, 0)

    def test_missing_source_field_exits_nonzero(self):
        raw = json.dumps({"result": "ask", "default": "amend"})
        result = subprocess.run(
            [sys.executable, SCRIPT, raw],
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(result.returncode, 0)

    def test_invalid_json_exits_nonzero(self):
        result = subprocess.run(
            [sys.executable, SCRIPT, "not-valid-json"],
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main()
