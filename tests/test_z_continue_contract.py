"""Structural safety checks for the foreground continuation skill."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "z-continue" / "SKILL.md"


def test_skill_uses_existing_handoff_resume_and_reconcile_authorities() -> None:
    text = SKILL.read_text(encoding="utf-8")
    assert "continuation-approval.py" in text
    assert "/z-handoff" in text
    assert "/z-resume --select" in text
    assert "/z-reconcile --archive-plans" in text
    assert "/z-reconcile --clean-locks" in text
    assert "/z-reconcile --prune-worktrees" in text


def test_skill_prohibits_lifecycle_and_external_delivery() -> None:
    text = SKILL.read_text(encoding="utf-8").lower()
    assert "no daemon" in text
    assert "external notification channel" in text
    assert "do not send the nudge to another task" in text
    assert "never\nwrap, batch, pre-answer, or bypass" in text
    assert "do not persist a deduplication record" in text


def test_release_surface_and_mcp_registry_expose_skill() -> None:
    release = (ROOT / "runtime" / "release_surface.py").read_text(encoding="utf-8")
    server = (ROOT / "z_harness_cli" / "mcp" / "server.py").read_text(encoding="utf-8")
    assert '"z-continue"' in release
    assert '"z_continue"' in server
