"""Safety contract tests for the one-shot continuation approval helper."""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
from typing import Any, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "continuation-approval.py"
SPEC = importlib.util.spec_from_file_location("continuation_approval", MODULE_PATH)
assert SPEC and SPEC.loader
continuation_approval = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(continuation_approval)


def _packet(token: str = "candidate:one|slug:demo", *, unsafe: str | None = None) -> dict[str, Any]:
    flags = {unsafe: True} if unsafe else {}
    return {
        "selected_target": {
            "selection_token": token,
            "current_state": {"flags": flags},
        },
        "ambiguity": {"state": "none", "needs_selection": False},
    }


def _builder(packet: Mapping[str, Any]):
    def build(argv: Sequence[str], environ: Mapping[str, str] | None) -> dict[str, Any]:
        assert "--noninteractive" in argv
        return dict(packet)

    return build


def _handoff(tmp_path: Path, *, next_step: str = "Continue demo: implement T001") -> Path:
    (tmp_path / "TASKS.md").write_text("## T001 — helper `[ ]`\n", encoding="utf-8")
    path = tmp_path / "handoff.json"
    path.write_text(
        json.dumps(
            {
                "protocol_version": "1.0",
                "timestamp": "2026-07-26T00:00:00Z",
                "agent": "codex",
                "slug": "demo",
                "status": "clean_break",
                "next_step": next_step,
                "context_files": [{"path": "TASKS.md", "role": "tasks"}],
            }
        ),
        encoding="utf-8",
    )
    return path


def test_inspect_is_read_only_and_reports_current_digest(tmp_path: Path) -> None:
    handoff = _handoff(tmp_path)
    before = {path.name: path.read_bytes() for path in tmp_path.iterdir()}

    result = continuation_approval.inspect(
        handoff, tmp_path, "T001", resume_builder=_builder(_packet())
    )

    assert result["ok"] is True
    assert result["handoff_sha256"] == hashlib.sha256(before["handoff.json"]).hexdigest()
    assert {path.name: path.read_bytes() for path in tmp_path.iterdir()} == before


def test_resume_builder_loads_the_real_dataclass_based_helper() -> None:
    assert callable(continuation_approval._load_resume_builder())


def test_authorize_returns_only_exact_read_only_resume_command(tmp_path: Path) -> None:
    handoff = _handoff(tmp_path)
    digest = hashlib.sha256(handoff.read_bytes()).hexdigest()
    token = "candidate:one|slug:demo"

    result = continuation_approval.authorize(
        handoff, tmp_path, "T001", digest, token, resume_builder=_builder(_packet(token))
    )

    assert result["ok"] is True
    assert result["command"] == ["/z-resume", "--select", token]
    assert "subprocess" not in MODULE_PATH.read_text(encoding="utf-8")


def test_authorize_refuses_changed_handoff_bytes(tmp_path: Path) -> None:
    handoff = _handoff(tmp_path)
    result = continuation_approval.authorize(
        handoff, tmp_path, "T001", "0" * 64, "candidate:one|slug:demo", resume_builder=_builder(_packet())
    )
    assert result == {"ok": False, "reason": "handoff SHA-256 does not match the approved handoff"}


def test_authorize_refuses_missing_or_mismatched_task(tmp_path: Path) -> None:
    handoff = _handoff(tmp_path, next_step="Continue demo: implement T002")
    digest = hashlib.sha256(handoff.read_bytes()).hexdigest()
    result = continuation_approval.authorize(
        handoff, tmp_path, "T001", digest, "candidate:one|slug:demo", resume_builder=_builder(_packet())
    )
    assert result["ok"] is False
    assert "does not reference" in result["reason"]


def test_authorize_refuses_ambiguous_or_degraded_evidence(tmp_path: Path) -> None:
    handoff = _handoff(tmp_path)
    digest = hashlib.sha256(handoff.read_bytes()).hexdigest()
    degraded = continuation_approval.authorize(
        handoff, tmp_path, "T001", digest, "candidate:one|slug:demo",
        resume_builder=_builder(_packet(unsafe="degraded_sources")),
    )
    ambiguous_packet = _packet()
    ambiguous_packet["ambiguity"] = {"state": "needs_selection", "needs_selection": True}
    ambiguous = continuation_approval.authorize(
        handoff, tmp_path, "T001", digest, "candidate:one|slug:demo",
        resume_builder=_builder(ambiguous_packet),
    )
    assert degraded["ok"] is False and "degraded" in degraded["reason"]
    assert ambiguous == {"ok": False, "reason": "resume evidence is ambiguous"}


def test_authorize_refuses_unapproved_selection_token(tmp_path: Path) -> None:
    handoff = _handoff(tmp_path)
    digest = hashlib.sha256(handoff.read_bytes()).hexdigest()
    result = continuation_approval.authorize(
        handoff, tmp_path, "T001", digest, "candidate:other|slug:demo", resume_builder=_builder(_packet())
    )
    assert result == {"ok": False, "reason": "selection token does not match the approved token"}
