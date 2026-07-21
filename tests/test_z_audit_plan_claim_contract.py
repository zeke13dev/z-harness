"""Lifecycle contract checks for the executable snippets in /z-audit-plan."""

from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "z-audit-plan" / "SKILL.md"
_BASH_FENCE_RE = re.compile(
    r"^[ \t]*```bash[ \t]*\n(.*?)^[ \t]*```[ \t]*$",
    flags=re.DOTALL | re.MULTILINE,
)
_EXECUTABLE_EXIT_RE = re.compile(r"^[ \t]*exit(?:[ \t]+[^#\n]+)?[ \t]*$", re.MULTILINE)


def _text() -> str:
    return SKILL.read_text(encoding="utf-8")


def _bash_blocks(text: str) -> list[str]:
    return [match.group(1) for match in _BASH_FENCE_RE.finditer(text)]


def _bash_fences(text: str) -> list[tuple[int, str]]:
    return [(match.start(), match.group(1)) for match in _BASH_FENCE_RE.finditer(text)]


def _one_line(block: str) -> str:
    return " ".join(block.replace("\\\n", " ").split())


def test_post_registration_paths_have_one_teardown_owner() -> None:
    text = _text()
    blocks = _bash_blocks(text)
    teardown_blocks = [block for block in blocks if "scripts/z-teardown.sh" in block]

    assert len(teardown_blocks) == 9
    assert 'active-plan-registry.py" deregister' not in text

    exact_identity = (
        'bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/z-teardown.sh" '
        '--run "$RUN" --slug "$Z_HARNESS_SLUG" --command /z-audit-plan '
        '--session "$Z_HARNESS_SESSION_ID" --status '
    )
    for block in teardown_blocks:
        normalized = _one_line(block)
        assert exact_identity in normalized
        assert "TEARDOWN_RC=0" in block
        assert "|| TEARDOWN_RC=$?" in block
        assert "if [[ $TEARDOWN_RC -ne 0 ]]" in block
        assert 'exit "$TEARDOWN_RC"' in block
        assert re.search(r"--status (?:complete|aborted)(?:\s|$)", normalized)


def test_every_executable_exit_is_covered_at_its_registration_stage() -> None:
    text = _text()
    registration_boundary = text.index(
        "**FINALIZE_STATUS / teardown rule (single source of truth"
    )
    exit_fences = [
        (start, block, list(_EXECUTABLE_EXIT_RE.finditer(block)))
        for start, block in _bash_fences(text)
        if _EXECUTABLE_EXIT_RE.search(block)
    ]

    # Three no-registry exits occur before the successful-registration boundary;
    # nine run-ending fences occur after it. Markdown prose mentioning `exit`
    # is intentionally excluded because only executable Bash fences are parsed.
    assert len(exit_fences) == 12
    assert sum(start < registration_boundary for start, _, _ in exit_fences) == 3
    assert sum(start > registration_boundary for start, _, _ in exit_fences) == 9

    for start, block, exits in exit_fences:
        if start < registration_boundary:
            assert "NO-REGISTRY RELEASE" in block
            assert "|| RELEASE_RC=$?" in block
            release_at = block.index('scripts/plan-claim.sh" release')
            assert all(release_at < exit_match.start() for exit_match in exits)
            continue

        assert "scripts/z-teardown.sh" in block
        assert "|| TEARDOWN_RC=$?" in block
        teardown_at = block.index("scripts/z-teardown.sh")
        assert all(teardown_at < exit_match.start() for exit_match in exits)


def test_direct_release_is_limited_to_no_registry_aborts_and_rc_checked() -> None:
    text = _text()
    release_blocks = [
        block
        for block in _bash_blocks(text)
        if 'scripts/plan-claim.sh" release' in block
    ]

    assert len(release_blocks) == 3
    for block in release_blocks:
        assert "NO-REGISTRY RELEASE" in block
        assert "RELEASE_RC=0" in block
        assert "|| RELEASE_RC=$?" in block
        assert "if [[ $RELEASE_RC -ne 0 ]]" in block
        assert 'exit "$RELEASE_RC"' in block
        assert "|| true" not in block
        assert 'active-plan-registry.py" deregister' not in block


def test_single_source_of_truth_documents_fail_closed_retry_contract() -> None:
    text = _text()
    contract = next(
        line
        for line in text.splitlines()
        if "FINALIZE_STATUS / teardown rule (single source of truth" in line
    )

    assert "scripts/z-teardown.sh" in contract
    assert "Every call captures its exit code" in contract
    assert "never independently deregister" in contract
    assert "retains the registry record" in contract
    assert "no-registry abort" in contract
    assert "fail rather than use `|| true`" in contract
