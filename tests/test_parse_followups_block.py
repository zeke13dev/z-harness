"""
tests/test_parse_followups_block.py — pytest tests for scripts/parse-followups-block.py

Cases covered:
  valid_block              — 2 valid entries → 2 structured dicts returned
  malformed_json           — invalid JSON in fence → logged + returns []
  missing_block            — no **FOLLOWUPS:** header → returns []
  partial_entry_validation — 1 valid + 1 invalid entry → 1 returned, 1 skipped
  invalid_priority         — priority not in {P0,P1,P2,P3} → entry skipped
  invalid_command          — command does not start with /z- → entry skipped
  command_control_chars    — control char in command → entry skipped
  command_too_long         — command > 2048 chars → entry skipped
  cited_paths_cap          — > 16 cited_paths → entry skipped
  no_followups_section     — plain review text without **FOLLOWUPS:** → []
"""

from __future__ import annotations

import importlib.util
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parent.parent

# Import parse-followups-block as a module (hyphen in name requires importlib)
_spec = importlib.util.spec_from_file_location(
    "parse_followups_block",
    str(REPO_ROOT / "scripts" / "parse-followups-block.py"),
)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

parse_followups = _mod.parse_followups
_find_followups_block = _mod._find_followups_block
_validate_entry = _mod._validate_entry


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

VALID_ENTRY_1 = {
    "priority": "P3",
    "name": "Fix stale README badge",
    "recommended_command": '/z-do "update README badge URL"',
    "cited_paths": ["README.md"],
    "recommended_command_safe_to_retry": True,
    "auto_close_eligible": False,
}

VALID_ENTRY_2 = {
    "priority": "P2",
    "name": "Update CI config",
    "recommended_command": "/z-execute",
    "cited_paths": [".github/workflows/ci.yml", "Makefile"],
    "recommended_command_safe_to_retry": False,
    "auto_close_eligible": True,
}

INVALID_ENTRY_NO_NAME = {
    "priority": "P1",
    # missing "name"
    "recommended_command": "/z-do \"fix something\"",
    "cited_paths": ["scripts/foo.sh"],
}

INVALID_ENTRY_BAD_PRIORITY = {
    "priority": "P9",  # invalid
    "name": "Some followup",
    "recommended_command": "/z-do \"something\"",
    "cited_paths": [],
}


def _make_review_text(entries_json: str, preamble: str = "") -> str:
    """Wrap entries_json in a **FOLLOWUPS:** block like the reviewer would emit."""
    return f"""{preamble}
## Reviewer review: task T001

### Blockers
No blockers found.

### Major
No majors found.

**FOLLOWUPS:**
```json
{entries_json}
```
"""


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestFindFollowupsBlock(unittest.TestCase):
    """Unit tests for _find_followups_block (structural extraction)."""

    def test_finds_block_after_header(self):
        text = _make_review_text('[{"a": 1}]')
        raw = _find_followups_block(text)
        self.assertIsNotNone(raw)
        self.assertIn('"a"', raw)

    def test_returns_none_if_no_header(self):
        text = "Some review text without the magic header."
        self.assertIsNone(_find_followups_block(text))

    def test_returns_none_if_header_but_no_fence(self):
        text = "**FOLLOWUPS:**\nsome plain text no fence"
        self.assertIsNone(_find_followups_block(text))


class TestValidEntry(unittest.TestCase):
    """Unit tests for _validate_entry."""

    def test_valid_entry_accepted(self):
        result = _validate_entry(VALID_ENTRY_1.copy(), 0)
        self.assertIsNotNone(result)
        self.assertEqual(result["priority"], "P3")
        self.assertEqual(result["name"], "Fix stale README badge")
        self.assertTrue(result["recommended_command_safe_to_retry"])
        self.assertFalse(result["auto_close_eligible"])

    def test_defaults_for_optional_fields(self):
        entry = {
            "priority": "P2",
            "name": "Minimal entry",
            "recommended_command": "/z-execute",
            "cited_paths": [],
        }
        result = _validate_entry(entry, 0)
        self.assertIsNotNone(result)
        self.assertFalse(result["recommended_command_safe_to_retry"])
        self.assertFalse(result["auto_close_eligible"])

    def test_invalid_priority_returns_none(self):
        entry = VALID_ENTRY_1.copy()
        entry["priority"] = "P9"
        result = _validate_entry(entry, 0)
        self.assertIsNone(result)

    def test_missing_required_field_returns_none(self):
        entry = VALID_ENTRY_1.copy()
        del entry["name"]
        result = _validate_entry(entry, 0)
        self.assertIsNone(result)

    def test_command_must_start_with_z_dash(self):
        entry = VALID_ENTRY_1.copy()
        entry["recommended_command"] = "bash -c 'rm -rf /'"
        result = _validate_entry(entry, 0)
        self.assertIsNone(result)

    def test_command_control_char_rejected(self):
        entry = VALID_ENTRY_1.copy()
        entry["recommended_command"] = "/z-do \"something\x01hidden\""
        result = _validate_entry(entry, 0)
        self.assertIsNone(result)

    def test_command_too_long_rejected(self):
        entry = VALID_ENTRY_1.copy()
        entry["recommended_command"] = "/z-do \"" + "x" * 2050 + "\""
        result = _validate_entry(entry, 0)
        self.assertIsNone(result)

    def test_cited_paths_cap_exceeded(self):
        entry = VALID_ENTRY_1.copy()
        entry["cited_paths"] = [f"file{i}.txt" for i in range(17)]
        result = _validate_entry(entry, 0)
        self.assertIsNone(result)

    def test_cited_paths_at_cap_accepted(self):
        entry = VALID_ENTRY_1.copy()
        entry["cited_paths"] = [f"file{i}.txt" for i in range(16)]
        result = _validate_entry(entry, 0)
        self.assertIsNotNone(result)

    def test_not_a_dict_returns_none(self):
        result = _validate_entry("not a dict", 0)
        self.assertIsNone(result)

    def test_cited_paths_not_array_returns_none(self):
        entry = VALID_ENTRY_1.copy()
        entry["cited_paths"] = "README.md"  # should be list
        result = _validate_entry(entry, 0)
        self.assertIsNone(result)


class TestParseFollowupsIntegration(unittest.TestCase):
    """Integration tests for parse_followups (full text parsing pipeline)."""

    # Suppress event logging side-effects
    def setUp(self):
        self._patch = patch.object(_mod, "_log_event", return_value=None)
        self._patch.start()

    def tearDown(self):
        self._patch.stop()

    def test_valid_block_two_entries(self):
        """Valid block with 2 entries → 2 dicts returned."""
        entries = [VALID_ENTRY_1, VALID_ENTRY_2]
        text = _make_review_text(json.dumps(entries))
        result = parse_followups(text)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["name"], "Fix stale README badge")
        self.assertEqual(result[1]["name"], "Update CI config")

    def test_malformed_json_returns_empty_list(self):
        """Malformed JSON inside fence → returns [] (never crashes)."""
        text = _make_review_text("{not valid json at all}")
        result = parse_followups(text)
        self.assertEqual(result, [])

    def test_missing_block_returns_empty_list(self):
        """No **FOLLOWUPS:** header anywhere → returns []."""
        text = """## Reviewer review: task T001

### Blockers
None.

### Major
None.

No follow-ups section here.
"""
        result = parse_followups(text)
        self.assertEqual(result, [])

    def test_partial_entry_validation_failure_skips_bad_keeps_good(self):
        """1 valid + 1 invalid entry → 1 returned, 1 skipped (never aborts)."""
        entries = [VALID_ENTRY_1, INVALID_ENTRY_NO_NAME]
        text = _make_review_text(json.dumps(entries))
        result = parse_followups(text)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["name"], "Fix stale README badge")

    def test_all_invalid_entries_returns_empty(self):
        """All entries invalid → [] (not a crash)."""
        entries = [INVALID_ENTRY_BAD_PRIORITY, INVALID_ENTRY_NO_NAME]
        text = _make_review_text(json.dumps(entries))
        result = parse_followups(text)
        self.assertEqual(result, [])

    def test_empty_array_returns_empty_list(self):
        """Empty JSON array → []."""
        text = _make_review_text("[]")
        result = parse_followups(text)
        self.assertEqual(result, [])

    def test_not_array_at_top_level_returns_empty(self):
        """Top-level JSON object (not array) → logs failure + returns []."""
        text = _make_review_text('{"single": "object"}')
        result = parse_followups(text)
        self.assertEqual(result, [])

    def test_invalid_priority_entry_skipped(self):
        """Entry with invalid priority is skipped; valid sibling survives."""
        entries = [INVALID_ENTRY_BAD_PRIORITY, VALID_ENTRY_2]
        text = _make_review_text(json.dumps(entries))
        result = parse_followups(text)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["name"], "Update CI config")

    def test_command_not_starting_with_z_skipped(self):
        """Entry whose recommended_command doesn't start with /z- is skipped."""
        bad_cmd_entry = VALID_ENTRY_1.copy()
        bad_cmd_entry["recommended_command"] = "bash -c 'something'"
        text = _make_review_text(json.dumps([bad_cmd_entry]))
        result = parse_followups(text)
        self.assertEqual(result, [])

    def test_malformed_json_event_logged(self):
        """Malformed JSON triggers a _log_event call with followup_block_parse_failed."""
        logged_events = []

        def capture_event(kind, payload):
            logged_events.append((kind, payload))

        with patch.object(_mod, "_log_event", side_effect=capture_event):
            text = _make_review_text("{broken json")
            parse_followups(text)

        self.assertTrue(
            any(k == "followup_block_parse_failed" for k, _ in logged_events),
            f"Expected followup_block_parse_failed event, got: {logged_events}",
        )

    def test_validation_error_event_logged(self):
        """Per-entry validation error triggers a _log_event call."""
        logged_events = []

        def capture_event(kind, payload):
            logged_events.append((kind, payload))

        with patch.object(_mod, "_log_event", side_effect=capture_event):
            text = _make_review_text(json.dumps([INVALID_ENTRY_NO_NAME]))
            parse_followups(text)

        self.assertTrue(
            any(k == "followup_entry_validation_error" for k, _ in logged_events),
            f"Expected followup_entry_validation_error event, got: {logged_events}",
        )

    def test_valid_block_with_preamble(self):
        """**FOLLOWUPS:** block works even when deep in a longer document."""
        preamble = """## Reviewer review: task T002

### Blockers
- Something broken at line 42. Fix the null-check.

### Major
- Missing error handling in foo.py. Add try/except ValueError.

"""
        entries = [VALID_ENTRY_1]
        text = _make_review_text(json.dumps(entries), preamble=preamble)
        result = parse_followups(text)
        self.assertEqual(len(result), 1)

    def test_two_valid_one_invalid_returns_two_and_logs_skip(self):
        """Integration: 2 valid + 1 invalid entry → 2 returned, 1 logged-skipped event."""
        logged_events = []

        def capture_event(kind, payload):
            logged_events.append((kind, payload))

        entries = [VALID_ENTRY_1, INVALID_ENTRY_NO_NAME, VALID_ENTRY_2]
        text = _make_review_text(json.dumps(entries))

        with patch.object(_mod, "_log_event", side_effect=capture_event):
            result = parse_followups(text)

        # Two valid entries returned
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["name"], "Fix stale README badge")
        self.assertEqual(result[1]["name"], "Update CI config")

        # One logged-skipped event for the invalid entry
        skip_events = [e for e in logged_events if e[0] == "followup_entry_validation_error"]
        self.assertEqual(len(skip_events), 1, f"Expected 1 skip event, got: {skip_events}")


if __name__ == "__main__":
    unittest.main()
