#!/usr/bin/env python3
"""Render truthful orchestration and release status from bounded evidence.

Reservation expiry is an admission-control fact, not evidence that an active
child stopped.  This host has no protected receipt verifier, so a reported
``timed_out`` or ``cancelled`` child outcome is retained only as unverified
audit data and the public child status remains ``unknown`` (INTENT acceptance
criterion #5). Machine and human output are projections of the same normalized
document. Releases A/B are shipped while Release C is terminally blocked,
without promotion or waiver of criteria #10/#11, because the required protected
broker is unavailable (criterion #13).

Input is a JSON object with ``schema_version``, ``run_id``, and ``items``.
Each item names ``logical_work_id``, ``reservation_id``, ``admission_status``,
and ``reported_child_status``. Any caller-supplied ``termination`` fields are
untrusted audit input and cannot verify an active-child outcome on this host.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


SCHEMA_VERSION = 1
_ADMISSION_STATUSES = frozenset(
    {"admitted", "reservation_expired", "rejected", "settled", "unknown"}
)
_CHILD_STATUSES = frozenset(
    {"not_started", "active", "completed", "timed_out", "cancelled", "unknown"}
)
_TERMINAL_CLAIMS = frozenset({"timed_out", "cancelled"})
_UNKNOWN_IDENTITIES = frozenset({"", "unknown", "unavailable", "none"})
_RELEASES = (
    {
        "release": "A",
        "status": "shipped",
        "scope": (
            "direct Codex App /z-execute admission block and canonical "
            "privacy-safe telemetry"
        ),
    },
    {
        "release": "B",
        "status": "shipped",
        "scope": (
            "transactional admission/reservation enforcement and the tested "
            "degraded single-unit boundary"
        ),
    },
    {
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
    },
)


def _build_status(document: object) -> dict[str, object]:
    """Normalize untrusted status evidence into the fail-closed public shape.

    Args:
        document: Parsed input JSON.

    Returns:
        One document consumed by both JSON and human renderers.

    Raises:
        ValueError: If the top-level status document or item identities are
            malformed. Unknown evidence values are not errors; they yield an
            unverified child status instead.
    """

    if (
        not isinstance(document, dict)
        or document.get("schema_version") != SCHEMA_VERSION
    ):
        raise ValueError(f"status input requires schema_version {SCHEMA_VERSION}")
    run_id = _required_identity(document.get("run_id"), "run_id")
    raw_items = document.get("items")
    if not isinstance(raw_items, list):
        raise ValueError("status input requires an items list")

    return {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "releases": [dict(release) for release in _RELEASES],
        "items": [_normalize_item(item) for item in raw_items],
    }


def _render_human(status: dict[str, object]) -> str:
    """Render the normalized machine document without changing its claims.

    Args:
        status: Result from :func:`_build_status`.

    Returns:
        Line-oriented human-readable status.
    """

    lines = ["Releases:"]
    for release in status["releases"]:
        lines.append(
            f"  Release {release['release']}: {release['status']} - {release['scope']}"
        )
    lines.append(f"Run {status['run_id']}:")
    for item in status["items"]:
        line = (
            f"  {item['logical_work_id']} (reservation {item['reservation_id']}): "
            f"admission={item['admission_status']}; child={item['child_status']}"
        )
        termination = item["termination"]
        if termination["reported_outcome"] in _TERMINAL_CLAIMS:
            line += (
                f"; reported_{termination['reported_outcome']}=unverified"
                f" ({termination['reason']})"
            )
        lines.append(line)
    return "\n".join(lines)


def _normalize_item(raw: object) -> dict[str, object]:
    """Normalize one item while preserving admission/termination separation."""

    if not isinstance(raw, dict):
        raise ValueError("every status item must be an object")
    logical_work_id = _required_identity(raw.get("logical_work_id"), "logical_work_id")
    reservation_id = _required_identity(raw.get("reservation_id"), "reservation_id")
    admission_status = raw.get("admission_status")
    if admission_status not in _ADMISSION_STATUSES:
        admission_status = "unknown"
    reported_child_status = raw.get("reported_child_status")
    if reported_child_status not in _CHILD_STATUSES:
        reported_child_status = "unknown"

    child_status = reported_child_status
    termination = {
        "reported_outcome": reported_child_status,
        "claim_status": "not_applicable",
        "primitive_id": None,
        "evidence_id": None,
        "reason": None,
    }
    if reported_child_status in _TERMINAL_CLAIMS:
        child_status = "unknown"
        termination.update(
            {
                "claim_status": "unverified",
                "reason": "verified_active_child_termination_unavailable",
            }
        )

    return {
        "logical_work_id": logical_work_id,
        "reservation_id": reservation_id,
        "admission_status": admission_status,
        "child_status": child_status,
        "termination": termination,
    }

def _usable_identity(value: object) -> str | None:
    """Return a non-sentinel evidence identity, else ``None``."""

    if not isinstance(value, str) or value.strip().lower() in _UNKNOWN_IDENTITIES:
        return None
    return value.strip()


def _required_identity(value: object, field: str) -> str:
    """Validate a required item identity. Hard-fail on malformed input."""

    identity = _usable_identity(value)
    if identity is None:
        raise ValueError(f"{field} must be a non-empty, known string")
    return identity


def _parse_args(argv: list[str]) -> argparse.Namespace:
    """Parse the small standalone status CLI."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="status evidence JSON")
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Read evidence and print normalized machine or human status.

    Args:
        argv: Optional command-line arguments.

    Returns:
        Zero on success; two for malformed or unreadable input.
    """

    args = _parse_args(sys.argv[1:] if argv is None else argv)
    try:
        document = json.loads(args.input.read_text(encoding="utf-8"))
        status = _build_status(document)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        print(f"orchestration-status: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(status, indent=2, sort_keys=True))
    else:
        print(_render_human(status))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
