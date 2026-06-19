"""
tests/test_lint_halt_categories.py

Python wrapper tests for scripts/lint-halt-categories.sh.
Invokes the script via subprocess and asserts exit codes and output.

Runnable under pytest. Does NOT require bats.

Cases covered:
  in_enum_category_passes         -- a valid category= token causes exit 0
  out_of_enum_category_fails      -- an invalid category= token causes exit != 0
  missing_category_warn_exit0     -- ask_user gate with no category= exits 0 (warn)
  missing_category_strict_fails   -- same gate under --strict exits != 0
  check_chain_graceful            -- --check-chain with an unknown preset exits 0
  check_chain_known_preset        -- --check-chain with a known preset lists gates
  subagent_gate_ignored           -- RUNTIME-GATE: subagent is not flagged
  empty_skills_dir                -- no SKILL.md files -> exit 0, clean output
"""

import subprocess
import tempfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = str(REPO_ROOT / "scripts" / "lint-halt-categories.sh")


def _run(args: list[str], skills_dir: str | None = None) -> subprocess.CompletedProcess:
    """Run lint-halt-categories.sh with the given extra args."""
    cmd = ["bash", SCRIPT]
    if skills_dir is not None:
        cmd += ["--skills-dir", skills_dir]
    cmd += args
    return subprocess.run(cmd, capture_output=True, text=True)


def _make_skills_dir(gates: list[str]) -> tempfile.TemporaryDirectory:
    """Return a TemporaryDirectory whose skills/test-skill/SKILL.md contains the gates."""
    tmpdir = tempfile.TemporaryDirectory()
    skill_dir = Path(tmpdir.name) / "skills" / "test-skill"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("\n".join(gates) + "\n")
    return tmpdir


# ---------------------------------------------------------------------------
# 1. In-enum category -> exit 0
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("category", [
    "decision", "risk", "shortcut", "archiving", "mechanical_proceed",
])
def test_in_enum_category_passes(category):
    gate = f"<!-- RUNTIME-GATE: ask_user; category={category} -->"
    with _make_skills_dir([gate]) as tmpdir:
        skills = str(Path(tmpdir) / "skills")
        result = _run([], skills_dir=skills)
    assert result.returncode == 0, f"Expected exit 0 for category={category}; got {result.returncode}\nstderr: {result.stderr}"


# ---------------------------------------------------------------------------
# 2. Out-of-enum category -> exit non-zero
# ---------------------------------------------------------------------------

def test_out_of_enum_category_fails_nonzero():
    gate = "<!-- RUNTIME-GATE: ask_user; category=not_a_valid_category -->"
    with _make_skills_dir([gate]) as tmpdir:
        skills = str(Path(tmpdir) / "skills")
        result = _run([], skills_dir=skills)
    assert result.returncode != 0, f"Expected non-zero exit for invalid category; got 0\nstderr: {result.stderr}"


def test_out_of_enum_category_emits_error_message():
    gate = "<!-- RUNTIME-GATE: ask_user; category=totally_bogus -->"
    with _make_skills_dir([gate]) as tmpdir:
        skills = str(Path(tmpdir) / "skills")
        result = _run([], skills_dir=skills)
    combined = result.stdout + result.stderr
    assert "ERROR" in combined
    assert "totally_bogus" in combined


# ---------------------------------------------------------------------------
# 2a. MAJOR 1 (review): partial-match bug. A token that has a VALID enum
#     member as a prefix but extra junk after a hyphen (`risk-foo`) must NOT
#     be silently accepted by capturing only the `risk` prefix. It is a
#     COMPLETE-token enum violation -> exit non-zero.
# ---------------------------------------------------------------------------

def test_valid_prefix_with_trailing_junk_is_enum_violation():
    """`category=risk-foo` must be rejected: the full token isn't an enum member."""
    gate = "<!-- RUNTIME-GATE: ask_user; category=risk-foo -->"
    with _make_skills_dir([gate]) as tmpdir:
        skills = str(Path(tmpdir) / "skills")
        result = _run([], skills_dir=skills)
    assert result.returncode != 0, (
        "category=risk-foo was accepted -- the linter captured only the 'risk' "
        "prefix instead of validating the complete token."
    )
    combined = result.stdout + result.stderr
    assert "ERROR" in combined
    # The full malformed token (not just 'risk') should surface in the message.
    assert "risk-foo" in combined


# ---------------------------------------------------------------------------
# 2b. MAJOR 2 (review): case-sensitivity downgrade. A present-but-wrong-case
#     token (`category=Risk`) must be a hard enum violation (exit non-zero),
#     NOT a missing-category WARN. Presence is detected case-insensitively;
#     validity requires the exact lowercase enum member.
# ---------------------------------------------------------------------------

def test_wrong_case_category_is_enum_violation_not_warning():
    gate = "<!-- RUNTIME-GATE: ask_user; category=Risk -->"
    with _make_skills_dir([gate]) as tmpdir:
        skills = str(Path(tmpdir) / "skills")
        result = _run([], skills_dir=skills)
    assert result.returncode != 0, (
        "category=Risk was treated as missing-category (warn) instead of an "
        "enum violation -- the presence check must be case-insensitive while "
        "validity stays lowercase-exact."
    )
    combined = result.stdout + result.stderr
    assert "ERROR" in combined
    # It must NOT be downgraded to the missing-category warning.
    assert "no category= token" not in combined


# ---------------------------------------------------------------------------
# 2c. MAJOR 3 (review): single-line-comment expectation. The scanner inspects
#     one physical line at a time; a category= token on a SECOND physical line
#     is (by documented design) reported as missing-category. This test pins
#     that documented behavior so the constraint stays explicit.
# ---------------------------------------------------------------------------

def test_category_on_second_physical_line_is_missing_by_design():
    """Documented single-line requirement: a wrapped category= is 'missing'."""
    gates = [
        "<!-- RUNTIME-GATE: ask_user; gate text wraps here",
        "     category=decision -->",
    ]
    with _make_skills_dir(gates) as tmpdir:
        skills = str(Path(tmpdir) / "skills")
        # Default mode: missing-category is a warning (exit 0).
        result = _run([], skills_dir=skills)
    assert result.returncode == 0, (
        "Multi-line gate unexpectedly hard-failed in default mode; the "
        "documented behavior is a missing-category WARN."
    )
    combined = result.stdout + result.stderr
    assert "WARN" in combined, (
        "A category= token wrapped onto a second physical line should be "
        "reported as missing-category per the documented single-line rule."
    )


# ---------------------------------------------------------------------------
# 3. Missing category -> warn (exit 0) by default; fail under --strict
# ---------------------------------------------------------------------------

def test_missing_category_warn_exit0():
    gate = "<!-- RUNTIME-GATE: ask_user; non-supporting drivers must surface this -->"
    with _make_skills_dir([gate]) as tmpdir:
        skills = str(Path(tmpdir) / "skills")
        result = _run([], skills_dir=skills)
    assert result.returncode == 0, (
        f"Expected exit 0 for missing category (default/warn mode); got {result.returncode}\nstderr: {result.stderr}"
    )
    combined = result.stdout + result.stderr
    assert "WARN" in combined


def test_missing_category_strict_fails_nonzero():
    gate = "<!-- RUNTIME-GATE: ask_user; no category token present -->"
    with _make_skills_dir([gate]) as tmpdir:
        skills = str(Path(tmpdir) / "skills")
        result = _run(["--strict"], skills_dir=skills)
    assert result.returncode != 0, (
        f"Expected non-zero exit under --strict for missing category; got 0\nstderr: {result.stderr}"
    )


def test_missing_category_strict_emits_error_not_warn():
    gate = "<!-- RUNTIME-GATE: ask_user; no category token present -->"
    with _make_skills_dir([gate]) as tmpdir:
        skills = str(Path(tmpdir) / "skills")
        result = _run(["--strict"], skills_dir=skills)
    combined = result.stdout + result.stderr
    assert "ERROR" in combined


# ---------------------------------------------------------------------------
# 4. subagent RUNTIME-GATE is ignored
# ---------------------------------------------------------------------------

def test_subagent_gate_ignored():
    gate = "<!-- RUNTIME-GATE: subagent; non-supporting drivers skip this -->"
    with _make_skills_dir([gate]) as tmpdir:
        skills = str(Path(tmpdir) / "skills")
        result = _run([], skills_dir=skills)
    assert result.returncode == 0
    combined = result.stdout + result.stderr
    assert "WARN" not in combined
    assert "ERROR" not in combined


# ---------------------------------------------------------------------------
# 5. Empty skills dir -> clean exit 0
# ---------------------------------------------------------------------------

def test_empty_skills_dir():
    with tempfile.TemporaryDirectory() as tmpdir:
        skills = Path(tmpdir) / "skills"
        skills.mkdir()
        result = _run([], skills_dir=str(skills))
    assert result.returncode == 0


# ---------------------------------------------------------------------------
# 6. --check-chain with unknown preset degrades gracefully (exit 0)
# ---------------------------------------------------------------------------

def test_check_chain_unknown_preset_graceful():
    with tempfile.TemporaryDirectory() as tmpdir:
        skills = Path(tmpdir) / "skills"
        skills.mkdir()
        result = _run(["--check-chain", "totally_unknown_xyz_preset"], skills_dir=str(skills))
    assert result.returncode == 0, (
        f"Expected graceful exit 0 for unknown chain preset; got {result.returncode}"
    )


# ---------------------------------------------------------------------------
# 7. --check-chain with a known preset lists uncategorized gates
# ---------------------------------------------------------------------------

def test_check_chain_known_preset_lists_gates():
    """--check-chain attend-full should list uncategorized ask_user gates in z-plan/SKILL.md."""
    with tempfile.TemporaryDirectory() as tmpdir:
        skills = Path(tmpdir) / "skills"
        # attend-full chain includes 'plan' step, which maps to z-plan/SKILL.md
        skill_dir = skills / "z-plan"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(
            "<!-- RUNTIME-GATE: ask_user; non-supporting drivers must surface -->\n"
        )
        result = _run(["--check-chain", "attend-full"], skills_dir=str(skills))
    assert result.returncode == 0
    combined = result.stdout + result.stderr
    assert "z-plan" in combined


# ---------------------------------------------------------------------------
# 8. Mixed: bad + missing in same file
# ---------------------------------------------------------------------------

def test_bad_and_missing_in_same_file():
    gates = [
        "<!-- RUNTIME-GATE: ask_user; category=bad_enum -->",
        "<!-- RUNTIME-GATE: ask_user; no category token -->",
        "<!-- RUNTIME-GATE: ask_user; category=risk -->",
    ]
    with _make_skills_dir(gates) as tmpdir:
        skills = str(Path(tmpdir) / "skills")
        result = _run([], skills_dir=skills)
    assert result.returncode != 0
    combined = result.stdout + result.stderr
    assert "ERROR" in combined
    assert "WARN" in combined


# ---------------------------------------------------------------------------
# 9. Violation of invariant: wrong category actually triggers failure
#    (regression guard: a test that compiles but doesn't fail on violation
#     is a trivial test -- this one verifies the mechanism)
# ---------------------------------------------------------------------------

def test_violation_of_invariant_triggers_failure():
    """If lint stops rejecting out-of-enum values, this test fails.

    Deliberately uses a value that looks plausible ('escalate') to prevent
    naive string matching from masking the failure.
    """
    gate = "<!-- RUNTIME-GATE: ask_user; category=escalate -->"
    with _make_skills_dir([gate]) as tmpdir:
        skills = str(Path(tmpdir) / "skills")
        result = _run([], skills_dir=skills)
    # If the linter were broken and accepted everything, this would be 0 -- that's the bug.
    assert result.returncode != 0, (
        "lint-halt-categories.sh accepted 'escalate' as a valid category -- "
        "the enum check is broken."
    )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
