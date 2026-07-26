"""Behavioral tests for truthful orchestration status (criteria #5/#10/#11/#13)."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "orchestration-status.py"


@pytest.fixture
def status_input() -> dict[str, object]:
    """Return a minimal status fixture with an expired admission."""

    return {
        "schema_version": 1,
        "run_id": "run-1",
        "items": [
            {
                "logical_work_id": "task-1",
                "reservation_id": "reservation-1",
                "admission_status": "reservation_expired",
                "reported_child_status": "timed_out",
            }
        ],
    }


def _run(tmp_path: Path, document: object, *args: str) -> subprocess.CompletedProcess[str]:
    """Invoke the real script against a hermetic input fixture."""

    input_path = tmp_path / "status.json"
    input_path.write_text(json.dumps(document), encoding="utf-8")
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args, str(input_path)],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )


def test_expired_reservation_never_implies_active_child_timeout(
    tmp_path: Path, status_input: dict[str, object]
) -> None:
    result = _run(tmp_path, status_input, "--json")

    assert result.returncode == 0, result.stderr
    item = json.loads(result.stdout)["items"][0]
    assert item["admission_status"] == "reservation_expired"
    assert item["child_status"] == "unknown"
    assert item["termination"] == {
        "claim_status": "unverified",
        "evidence_id": None,
        "primitive_id": None,
        "reason": "verified_active_child_termination_unavailable",
        "reported_outcome": "timed_out",
    }


@pytest.mark.parametrize("outcome", ("timed_out", "cancelled"))
def test_caller_asserted_verification_cannot_forge_terminal_child_status(
    tmp_path: Path,
    status_input: dict[str, object],
    outcome: str,
) -> None:
    status_input["items"][0].update(
        {
            "reported_child_status": outcome,
            "termination": {
                "evidence_status": "verified",
                "primitive_id": "attacker-controlled-primitive",
                "evidence_id": "attacker-controlled-proof",
            },
        }
    )

    machine = _run(tmp_path, status_input, "--json")
    human = _run(tmp_path, status_input)
    item = json.loads(machine.stdout)["items"][0]

    assert item["child_status"] == "unknown"
    assert item["termination"]["claim_status"] == "unverified"
    assert (
        item["termination"]["reason"]
        == "verified_active_child_termination_unavailable"
    )
    assert item["termination"]["primitive_id"] is None
    assert item["termination"]["evidence_id"] is None
    assert "child=unknown" in human.stdout
    assert f"reported_{outcome}=unverified" in human.stdout
    assert "attacker-controlled" not in human.stdout


def test_unavailable_broker_is_terminal_not_promotion_or_gate_waiver(
    tmp_path: Path, status_input: dict[str, object]
) -> None:
    machine = _run(tmp_path, status_input, "--json")
    human = _run(tmp_path, status_input)

    releases = {
        entry["release"]: entry
        for entry in json.loads(machine.stdout)["releases"]
    }
    assert {name: entry["status"] for name, entry in releases.items()} == {
        "A": "shipped",
        "B": "shipped",
        "C": "blocked",
    }
    assert releases["C"] == {
        "release": "C",
        "status": "blocked",
        "scope": (
            "terminal unavailable-broker outcome: no protected broker provides "
            "authoritative preemptive counters, unescapable descendant "
            "containment, and protected append-only authority; criteria "
            "#10/#11 remain unmet"
        ),
        "terminal": True,
        "terminal_outcome": "protected_broker_unavailable",
        "promotion_eligible": False,
        "unmet_criteria": [10, 11],
        "waived_criteria": [],
    }
    assert "Release A: shipped" in human.stdout
    assert "Release B: shipped" in human.stdout
    assert "Release C: blocked" in human.stdout
    assert "terminal unavailable-broker outcome" in human.stdout
    assert "authoritative preemptive counters" in human.stdout
    assert "unescapable descendant containment" in human.stdout
    assert "protected append-only authority" in human.stdout
    assert "criteria #10/#11 remain unmet" in human.stdout
    assert "child=unknown" in human.stdout
    assert "reported_timed_out=unverified" in human.stdout


def test_unknown_status_values_render_unknown_not_terminal_claims(
    tmp_path: Path, status_input: dict[str, object]
) -> None:
    status_input["items"][0]["admission_status"] = "expired_and_killed"
    status_input["items"][0]["reported_child_status"] = "probably_cancelled"

    item = json.loads(_run(tmp_path, status_input, "--json").stdout)["items"][0]

    assert item["admission_status"] == "unknown"
    assert item["child_status"] == "unknown"
    assert item["termination"]["claim_status"] == "not_applicable"


def test_malformed_input_hard_fails_without_status_claims(tmp_path: Path) -> None:
    result = _run(
        tmp_path,
        {"schema_version": 99, "run_id": "run-1", "items": []},
        "--json",
    )

    assert result.returncode == 2
    assert result.stdout == ""
    assert "requires schema_version 1" in result.stderr
