#!/usr/bin/env python3
"""Build deterministic, task-local state for retry review findings.

The command reads one JSON object from standard input and writes one JSON object
to standard output.  Input has the following deliberately small schema::

    {
      "task_id": "T001",
      "prior_findings": [{"id": "T001-F...", "path": "scripts/example.py", "message": "..."}],
      "current_findings": [{"id": "T001-F...", "path": "scripts/example.py", "message": "reworded"}]
    }

``severity`` and ``id`` are optional.  New findings receive an identity derived
from their normalized path, message, and severity.  A later reviewer must carry
an exact ID from ``prior_findings`` to preserve identity across semantic
rewording or severity changes.  An omitted current ID always denotes a new
finding, even when its normalized content is identical to a prior finding.  IDs
not present in that supplied prior set fail closed.  The output keeps structured
state and a Markdown artifact together so callers do not need a second lossy
renderer.  It intentionally records that aggregate review remains an
independent decision; closing retry findings must never waive that gate.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from typing import Any


TASK_ID_RE = re.compile(r"(?:T\d{3}|T(?:-[A-Z][A-Z0-9]*)+-\d{3})\Z")


class InputError(ValueError):
    """Raised when the local finding-state input contract is malformed."""


def _require_string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise InputError(f"{field} must be a non-empty string")
    return value.strip()


def _normalise_finding(value: Any, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise InputError(f"{field} must be an object")
    path = _require_string(value.get("path"), f"{field}.path")
    message = _require_string(value.get("message"), f"{field}.message")
    severity_value = value.get("severity", "")
    if not isinstance(severity_value, str):
        raise InputError(f"{field}.severity must be a string when present")
    finding: dict[str, Any] = {
        "path": path,
        "message": message,
        "severity": severity_value.strip(),
        "_id_explicit": "id" in value,
    }
    if "id" in value:
        finding["id"] = _require_string(value["id"], f"{field}.id")
    return finding


def _finding_id(task_id: str, finding: dict[str, Any]) -> str:
    identity = "\x00".join((finding["path"], finding["message"], finding["severity"]))
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:16]
    return f"{task_id}-F{digest}"


def _collision_id(task_id: str, finding: dict[str, Any], reserved_ids: set[str]) -> str:
    """Return a deterministic fresh ID when a generated ID aliases prior state."""
    identity = "\x00".join((finding["path"], finding["message"], finding["severity"]))
    attempt = 1
    while True:
        digest = hashlib.sha256(
            f"{identity}\x00new-finding\x00{attempt}".encode("utf-8")
        ).hexdigest()[:16]
        candidate = f"{task_id}-F{digest}"
        if candidate not in reserved_ids:
            return candidate
        attempt += 1


def _parse_findings(
    payload: dict[str, Any], key: str, *, allowed_ids: set[str] | None = None
) -> list[dict[str, Any]]:
    values = payload.get(key)
    if not isinstance(values, list):
        raise InputError(f"{key} must be a list")
    findings = [_normalise_finding(value, f"{key}[{index}]") for index, value in enumerate(values)]
    ids: list[str] = []
    expected_prefix = f"{payload['task_id']}-F"
    for index, finding in enumerate(findings):
        finding_id = finding.get("id") or _finding_id(payload["task_id"], finding)
        if not finding_id.startswith(expected_prefix) or not re.fullmatch(
            re.escape(expected_prefix) + r"[0-9a-f]{16}", finding_id
        ):
            raise InputError(f"{key}[{index}].id is not valid for task {payload['task_id']}")
        if allowed_ids is not None and finding["_id_explicit"] and finding_id not in allowed_ids:
            raise InputError(f"{key}[{index}].id is not present in prior_findings")
        if not finding["_id_explicit"] and finding_id in ids:
            raise InputError(f"{key} contains duplicate findings")
        if not finding["_id_explicit"] and allowed_ids is not None and finding_id in allowed_ids:
            finding_id = _collision_id(
                payload["task_id"], finding, allowed_ids | set(ids)
            )
        finding["id"] = finding_id
        ids.append(finding_id)
    if len(set(ids)) != len(ids):
        raise InputError(f"{key} contains duplicate findings")
    return findings


def _entry(task_id: str, finding: dict[str, Any], disposition: str) -> dict[str, str]:
    entry = {
        "disposition": disposition,
        **{key: value for key, value in finding.items() if key != "_id_explicit"},
    }
    return entry


def _render_markdown(task_id: str, prior: list[dict[str, str]], current: list[dict[str, str]]) -> str:
    lines = [
        f"# Review finding state — {task_id}",
        "",
        "| Finding | Disposition | Path | Message |",
        "| --- | --- | --- | --- |",
    ]
    for finding in prior + [item for item in current if item["disposition"] == "new"]:
        message = finding["message"].replace("|", "\\|").replace("\n", " ")
        lines.append(f"| {finding['id']} | {finding['disposition']} | {finding['path']} | {message} |")
    lines.extend(
        [
            "",
            "Aggregate review: preserved. This retry finding state does not alter the conditional aggregate-review decision.",
        ]
    )
    return "\n".join(lines) + "\n"


def transition(payload: Any) -> dict[str, Any]:
    """Classify retry findings without suppressing fresh review findings."""
    if not isinstance(payload, dict):
        raise InputError("input must be a JSON object")
    task_id = payload.get("task_id")
    if not isinstance(task_id, str) or not TASK_ID_RE.fullmatch(task_id):
        raise InputError("task_id must match T### or a review-task ID such as T-REV-003")

    # Store the normalized task id before parsing so helper messages and IDs are stable.
    payload = {**payload, "task_id": task_id}
    prior_findings = _parse_findings(payload, "prior_findings")
    prior_ids = {finding["id"] for finding in prior_findings}
    current_findings = _parse_findings(payload, "current_findings", allowed_ids=prior_ids)
    carried_current_ids = {
        finding["id"] for finding in current_findings if finding["_id_explicit"]
    }

    prior = [
        _entry(task_id, finding, "still_open" if finding["id"] in carried_current_ids else "resolved")
        for finding in prior_findings
    ]
    current = [
        _entry(
            task_id,
            finding,
            "still_open" if finding["_id_explicit"] and finding["id"] in prior_ids else "new",
        )
        for finding in current_findings
    ]
    prior.sort(key=lambda item: item["id"])
    current.sort(key=lambda item: item["id"])
    return {
        "task_id": task_id,
        "prior_findings": prior,
        "current_findings": current,
        "aggregate_review": {
            "preserved": True,
            "decision": "unchanged",
            "reason": "retry finding closure cannot waive conditional aggregate review",
        },
        "artifact_markdown": _render_markdown(task_id, prior, current),
    }


def main() -> int:
    try:
        payload = json.load(sys.stdin)
        result = transition(payload)
    except (InputError, json.JSONDecodeError) as error:
        print(json.dumps({"ok": False, "error": str(error)}, sort_keys=True), file=sys.stderr)
        return 2
    print(json.dumps({"ok": True, **result}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
