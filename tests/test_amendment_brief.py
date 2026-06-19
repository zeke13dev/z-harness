"""
tests/test_amendment_brief.py — Golden + unit tests for scripts/amendment-brief.py.

Cases:
  both_sections        — corrections + approach_concerns → two-section brief
  corrections_only     — approach_concerns empty → no "Worth your eyes" section
  approach_only        — corrections empty → "Patched automatically (0): none." + "Worth your eyes"
  both_empty           — both empty → "Patched automatically (0): none." only, no second section
  affected_absent      — approach_concern with no "affected" → "rework this, or proceed?"
  stdin_input          — reads from stdin when no file arg given
  missing_file_exits1  — missing file path → exit 1
  invalid_json_exits1  — non-JSON input → exit 1

All four primary cases pin byte-exact output against inline golden strings.
"""

from __future__ import annotations

import importlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SCRIPT = _REPO_ROOT / "scripts" / "amendment-brief.py"

# ---------------------------------------------------------------------------
# Import the module so we can unit-test render_brief() directly.
# amendment-brief.py uses a hyphen, so importlib.util is required.
# ---------------------------------------------------------------------------
import importlib.util as _ilu

_spec = _ilu.spec_from_file_location("amendment_brief", _SCRIPT)
assert _spec is not None and _spec.loader is not None
_mod = _ilu.module_from_spec(_spec)
_spec.loader.exec_module(_mod)  # type: ignore[union-attr]
render_brief = _mod.render_brief


# ---------------------------------------------------------------------------
# Golden strings — byte-exact expected outputs.
# ---------------------------------------------------------------------------

_GOLDEN_BOTH_SECTIONS = (
    "Patched automatically (2 corrections):\n"
    "- Fix task count — plan said 5 tasks but only 4 listed [TASKS.md]\n"
    "- Correct dep reference — T002 listed T005 as dep but T005 was renamed T006 [TASKS.md]\n"
    "\n"
    "Worth your eyes (2):\n"
    "The batching strategy may deadlock under high load."
    " Consider a queue-based approach. rework scripts/merger.py, or proceed?\n"
    "Using sqlite for ephemeral state adds a hard dep."
    " A flat JSON file would suffice. rework this, or proceed?\n"
)

_GOLDEN_CORRECTIONS_ONLY = (
    "Patched automatically (1 corrections):\n"
    "- Fix task count — plan said 5 tasks but only 4 listed [TASKS.md]\n"
)

_GOLDEN_APPROACH_ONLY = (
    "Patched automatically (0 corrections): none.\n"
    "\n"
    "Worth your eyes (1):\n"
    "The chosen algorithm has O(n^2) complexity. rework scripts/solver.py, or proceed?\n"
)

_GOLDEN_BOTH_EMPTY = "Patched automatically (0 corrections): none.\n"

# ---------------------------------------------------------------------------
# Input payloads matching the golden outputs above.
# ---------------------------------------------------------------------------

_INPUT_BOTH_SECTIONS: dict = {
    "corrections": [
        {
            "title": "Fix task count",
            "why": "plan said 5 tasks but only 4 listed",
            "target": "TASKS.md",
        },
        {
            "title": "Correct dep reference",
            "why": "T002 listed T005 as dep but T005 was renamed T006",
            "target": "TASKS.md",
        },
    ],
    "approach_concerns": [
        {
            "concern": "The batching strategy may deadlock under high load.",
            "affected": "scripts/merger.py",
            "suggestion": "Consider a queue-based approach.",
        },
        {
            "concern": "Using sqlite for ephemeral state adds a hard dep.",
            "suggestion": "A flat JSON file would suffice.",
        },
    ],
}

_INPUT_CORRECTIONS_ONLY: dict = {
    "corrections": [
        {
            "title": "Fix task count",
            "why": "plan said 5 tasks but only 4 listed",
            "target": "TASKS.md",
        }
    ],
    "approach_concerns": [],
}

_INPUT_APPROACH_ONLY: dict = {
    "corrections": [],
    "approach_concerns": [
        {
            "concern": "The chosen algorithm has O(n^2) complexity.",
            "affected": "scripts/solver.py",
        }
    ],
}

_INPUT_BOTH_EMPTY: dict = {"corrections": [], "approach_concerns": []}


# ---------------------------------------------------------------------------
# Unit tests — render_brief() directly (no subprocess overhead).
# ---------------------------------------------------------------------------


class TestRenderBriefGolden:
    """Byte-exact golden comparison against render_brief()."""

    def test_both_sections(self) -> None:
        assert render_brief(_INPUT_BOTH_SECTIONS) == _GOLDEN_BOTH_SECTIONS

    def test_corrections_only(self) -> None:
        assert render_brief(_INPUT_CORRECTIONS_ONLY) == _GOLDEN_CORRECTIONS_ONLY

    def test_approach_only(self) -> None:
        assert render_brief(_INPUT_APPROACH_ONLY) == _GOLDEN_APPROACH_ONLY

    def test_both_empty(self) -> None:
        assert render_brief(_INPUT_BOTH_EMPTY) == _GOLDEN_BOTH_EMPTY

    def test_affected_absent_fallback(self) -> None:
        """approach_concern without 'affected' → 'rework this, or proceed?'"""
        data = {
            "corrections": [],
            "approach_concerns": [
                {"concern": "Plan-level viability is unclear."},
            ],
        }
        result = render_brief(data)
        assert "rework this, or proceed?" in result
        assert "rework None" not in result

    def test_affected_present_uses_value(self) -> None:
        """approach_concern with 'affected' → 'rework <affected>, or proceed?'"""
        data = {
            "corrections": [],
            "approach_concerns": [
                {"concern": "Slow path detected.", "affected": "scripts/hot.py"},
            ],
        }
        result = render_brief(data)
        assert "rework scripts/hot.py, or proceed?" in result

    def test_no_worth_your_eyes_when_approach_empty(self) -> None:
        """When approach_concerns is empty, 'Worth your eyes' must not appear."""
        result = render_brief(_INPUT_CORRECTIONS_ONLY)
        assert "Worth your eyes" not in result

    def test_no_worth_your_eyes_when_both_empty(self) -> None:
        result = render_brief(_INPUT_BOTH_EMPTY)
        assert "Worth your eyes" not in result

    def test_output_ends_with_newline(self) -> None:
        for data in (
            _INPUT_BOTH_SECTIONS,
            _INPUT_CORRECTIONS_ONLY,
            _INPUT_APPROACH_ONLY,
            _INPUT_BOTH_EMPTY,
        ):
            assert render_brief(data).endswith("\n"), f"No trailing newline for {data}"


# ---------------------------------------------------------------------------
# Subprocess / CLI tests — exercise the script's argument handling.
# ---------------------------------------------------------------------------


def _run_script(
    args: list[str],
    *,
    stdin: str | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(_SCRIPT), *args],
        input=stdin,
        capture_output=True,
        text=True,
    )


class TestCLI:
    def test_file_arg_both_sections(self, tmp_path: Path) -> None:
        f = tmp_path / "input.json"
        f.write_text(json.dumps(_INPUT_BOTH_SECTIONS), encoding="utf-8")
        result = _run_script([str(f)])
        assert result.returncode == 0
        assert result.stdout == _GOLDEN_BOTH_SECTIONS

    def test_stdin_input(self) -> None:
        result = _run_script([], stdin=json.dumps(_INPUT_BOTH_EMPTY))
        assert result.returncode == 0
        assert result.stdout == _GOLDEN_BOTH_EMPTY

    def test_missing_file_exits_1(self) -> None:
        result = _run_script(["/nonexistent/path/that/does/not/exist.json"])
        assert result.returncode == 1
        assert "cannot read" in result.stderr

    def test_invalid_json_exits_1(self) -> None:
        result = _run_script([], stdin="not valid json{{{")
        assert result.returncode == 1
        assert "invalid JSON" in result.stderr
