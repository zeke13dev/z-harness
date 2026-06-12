"""
Tests for halt_category fields on QUESTION_IDS and the resolve-halt-category subcommand.

Cases covered:
  seven_entries_mapping       — each of the 7 QUESTION_IDS entries returns the expected tag
  unknown_qid_failsafe        — unknown question_id returns "ask" (fail-safe default)
  untagged_is_failsafe        — a qid with no halt_category (simulated) returns "ask"
  startup_guard_fires         — _run_startup_guards raises SystemExit when a halt_category
                                is missing or invalid on a QUESTION_IDS entry
  enum_is_module_constant     — HALT_CATEGORY_ENUM is a module-level frozenset constant
                                and is NOT a settable VALIDATORS key
  no_args_exits_2             — resolve-halt-category with no args exits 2
"""

import importlib
import sys
import subprocess
import types
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = str(_REPO_ROOT / "scripts" / "config.py")


def _run(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, SCRIPT] + args,
        capture_output=True,
        text=True,
    )


class TestHaltCategoryMapping(unittest.TestCase):
    """The 7 QUESTION_IDS entries map to their specified halt_category tags."""

    EXPECTED = {
        "workflow.implement_all_proceed": "mechanical_proceed",
        "workflow.review_all_proceed":    "mechanical_proceed",
        "workflow.slug_confirm":          "mechanical_proceed",
        "workflow.plan_decisions_approval": "decision",
        "workflow.spec_retro_discovery":  "decision",
        "workflow.audit_to_amend":        "risk",
        "workflow.pre_run_cost_gate":     "risk",
    }

    def test_all_seven_entries(self):
        for qid, expected_cat in self.EXPECTED.items():
            with self.subTest(qid=qid):
                result = _run(["resolve-halt-category", qid])
                self.assertEqual(result.returncode, 0, msg=result.stderr)
                self.assertEqual(result.stdout.strip(), expected_cat)

    def test_coverage_is_exactly_seven(self):
        """Exactly 7 QUESTION_IDS exist — if new ones are added without halt_category,
        the startup guard (not this test) catches them."""
        # Import the module in-process to read QUESTION_IDS length.
        sys.path.insert(0, str(_REPO_ROOT / "scripts"))
        import config as cfg
        self.assertEqual(len(cfg.QUESTION_IDS), 7)


class TestFailsafeDefault(unittest.TestCase):
    """Unknown or untagged question_id yields the literal "ask" fail-safe."""

    def test_unknown_qid_returns_ask(self):
        result = _run(["resolve-halt-category", "workflow.totally_unknown"])
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertEqual(result.stdout.strip(), "ask")

    def test_completely_arbitrary_string_returns_ask(self):
        result = _run(["resolve-halt-category", "not_a_real_qid"])
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertEqual(result.stdout.strip(), "ask")

    def test_no_args_exits_2(self):
        result = _run(["resolve-halt-category"])
        self.assertEqual(result.returncode, 2)

    def test_untagged_qid_returns_ask(self):
        """cmd_resolve_halt_category returns 'ask' when halt_category is absent from meta."""
        sys.path.insert(0, str(_REPO_ROOT / "scripts"))
        import config as cfg
        import io
        from contextlib import redirect_stdout

        # Temporarily inject a fake qid without halt_category into QUESTION_IDS.
        fake_qid = "_test_untagged_qid"
        cfg.QUESTION_IDS[fake_qid] = {
            "config_key": fake_qid,
            "choices": {"ask"},
            "skill_default": "ask",
            # halt_category intentionally absent
        }
        try:
            buf = io.StringIO()
            with redirect_stdout(buf):
                cfg.cmd_resolve_halt_category([fake_qid])
            self.assertEqual(buf.getvalue().strip(), "ask")
        finally:
            del cfg.QUESTION_IDS[fake_qid]


class TestStartupGuard(unittest.TestCase):
    """_run_startup_guards raises SystemExit when halt_category is missing or invalid."""

    def _patched_guards(self, qid: str, meta_override: dict) -> None:
        """Run _run_startup_guards with one QUESTION_IDS entry patched."""
        sys.path.insert(0, str(_REPO_ROOT / "scripts"))
        import config as cfg

        original = cfg.QUESTION_IDS.get(qid)
        cfg.QUESTION_IDS[qid] = meta_override
        try:
            cfg._run_startup_guards()
        finally:
            if original is not None:
                cfg.QUESTION_IDS[qid] = original
            else:
                cfg.QUESTION_IDS.pop(qid, None)

    def test_missing_halt_category_raises(self):
        sys.path.insert(0, str(_REPO_ROOT / "scripts"))
        import config as cfg

        # Build a meta dict that passes all other guards but lacks halt_category.
        fake_meta = {
            "config_key": "workflow.audit_to_amend",
            "choices": cfg.QUESTION_IDS["workflow.audit_to_amend"]["choices"],
            "skill_default": "amend",
            # halt_category absent → None → not in HALT_CATEGORY_ENUM
        }
        with self.assertRaises(SystemExit) as cm:
            self._patched_guards("workflow.audit_to_amend", fake_meta)
        # The guard uses raise SystemExit(message_string); code is a non-empty string (truthy).
        self.assertNotEqual(cm.exception.code, 0)

    def test_invalid_halt_category_raises(self):
        sys.path.insert(0, str(_REPO_ROOT / "scripts"))
        import config as cfg

        fake_meta = {
            "config_key": "workflow.audit_to_amend",
            "choices": cfg.QUESTION_IDS["workflow.audit_to_amend"]["choices"],
            "skill_default": "amend",
            "halt_category": "not_a_valid_category",
        }
        with self.assertRaises(SystemExit) as cm:
            self._patched_guards("workflow.audit_to_amend", fake_meta)
        self.assertNotEqual(cm.exception.code, 0)

    def test_valid_halt_category_passes(self):
        """Sanity check: valid entry does NOT raise."""
        sys.path.insert(0, str(_REPO_ROOT / "scripts"))
        import config as cfg

        # Full, valid meta — guard should not raise.
        valid_meta = cfg.QUESTION_IDS["workflow.audit_to_amend"].copy()
        try:
            self._patched_guards("workflow.audit_to_amend", valid_meta)
        except SystemExit:
            self.fail("_run_startup_guards raised for a valid QUESTION_IDS entry")


class TestEnumIsModuleConstant(unittest.TestCase):
    """HALT_CATEGORY_ENUM is a plain module-level constant, NOT a settable VALIDATORS key.

    halt_category is per-question-id metadata, not user-settable config. If it leaked
    into VALIDATORS, `config.py set workflow.halt_category <x>` would pass validation and
    write a key that load_config() silently drops (no DEFAULTS entry) — a write-only ghost.
    """

    def test_enum_is_module_level_frozenset(self):
        sys.path.insert(0, str(_REPO_ROOT / "scripts"))
        import config as cfg

        self.assertIsInstance(cfg.HALT_CATEGORY_ENUM, frozenset)

    def test_halt_category_not_in_validators(self):
        sys.path.insert(0, str(_REPO_ROOT / "scripts"))
        import config as cfg

        self.assertNotIn("workflow.halt_category", cfg.VALIDATORS)

    def test_set_halt_category_is_rejected(self):
        """`config.py set workflow.halt_category decision` must be rejected (unknown key)."""
        result = _run(["set", "workflow.halt_category", "decision"])
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("unknown key", result.stderr)

    def test_enum_contains_all_five_values(self):
        sys.path.insert(0, str(_REPO_ROOT / "scripts"))
        import config as cfg

        expected = {"decision", "risk", "shortcut", "archiving", "mechanical_proceed"}
        self.assertEqual(cfg.HALT_CATEGORY_ENUM, frozenset(expected))


if __name__ == "__main__":
    unittest.main()
