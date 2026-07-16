#!/usr/bin/env python3
"""Validate and normalize privacy-safe /z-execute efficiency events.

The command accepts an event kind and a JSON object, then writes one normalized
JSON payload for ``log-event.sh``.  It deliberately rejects unknown event kinds,
fields, enum values, identifiers, booleans-as-counts, and negative counts.  It
does not accept free text or paths, so caller payloads cannot accidentally copy
prompts, reviewer prose, tool data, secrets, or filesystem paths into telemetry.
"""

from __future__ import annotations

import json
import re
import sys
from typing import Any


TASK_ID = re.compile(r"(?:T\d{3}|T(?:-[A-Z][A-Z0-9]*)+-\d{3})\Z")
FINDING_ID = re.compile(
    r"(?:T\d{3}|T(?:-[A-Z][A-Z0-9]*)+-\d{3})-F[0-9a-f]{16}\Z"
)

EVENT_SCHEMAS = {
    "surgical_eligibility": {
        "required": {"task_id", "outcome", "reason", "finding_count", "path_count"},
        "enums": {
            "outcome": {"eligible", "ineligible"},
            "reason": {
                "eligible",
                "too_many_findings",
                "too_many_paths",
                "undeclared_path",
                "change_class",
                "decision_needed",
                "malformed_review",
                "already_attempted",
                "artifact_exists",
            },
        },
        "counts": {"finding_count", "path_count"},
        "identifiers": {"task_id": TASK_ID},
    },
    "surgical_result": {
        "required": {"task_id", "outcome", "reason", "attempt_count"},
        "enums": {
            "outcome": {"success", "fallback"},
            "reason": {
                "none",
                "ineligible",
                "malformed_result",
                "failed",
                "undeclared_path",
                "unknown_finding_id",
                "retry_allowance_claimed",
                "artifact_exists",
                "post_review_failed",
            },
        },
        "counts": {"attempt_count"},
        "identifiers": {"task_id": TASK_ID},
    },
    "finding_transition": {
        "required": {"task_id", "finding_id", "outcome", "count"},
        "enums": {"outcome": {"resolved", "still_open", "new"}},
        "counts": {"count"},
        "identifiers": {"task_id": TASK_ID, "finding_id": FINDING_ID},
    },
    "preflight_rejection": {
        "required": {"outcome", "reason", "count"},
        "optional": {"task_id"},
        "enums": {
            "outcome": {"rejected"},
            "reason": {
                "duplicate_artifact_id",
                "duplicate_graph_id",
                "duplicate_task_id",
                "frontier_requires_serial",
                "hard_exclusion",
                "held_path_collision",
                "incomplete_intent_context",
                "invalid_artifact_entry",
                "invalid_artifact_id",
                "invalid_completed_ids",
                "invalid_dependencies",
                "invalid_dependency",
                "invalid_fanout",
                "invalid_graph",
                "invalid_graph_id",
                "invalid_graph_node",
                "invalid_graph_nodes",
                "invalid_hard_exclusions",
                "invalid_held_path",
                "invalid_held_paths",
                "invalid_input",
                "invalid_json",
                "invalid_ready_frontier",
                "invalid_ready_ids",
                "invalid_ready_task",
                "invalid_run_id",
                "invalid_task",
                "invalid_tasks",
                "invalid_task_id",
                "missing_atomic_reason",
                "missing_complexity",
                "task_graph_mismatch",
                "unreadable_intent_context",
                "unsafe_path_overlap",
                "unsatisfied_dependency",
                "unusable_paths",
            },
        },
        "counts": {"count"},
        "identifiers": {"task_id": TASK_ID},
    },
    "subagent_dispatch": {
        "required": {"role", "count"},
        "optional": {"task_id"},
        "enums": {
            "role": {
                "axiom_extractor",
                "complexity_classifier",
                "context_curator",
                "spec_precheck",
                "implementer",
                "pre_reviewer",
                "remote_runner",
                "review_agent",
                "reviewer",
                "scope_extractor",
                "self_reviewer",
                "surgical_fixer",
                "task_tree_generator",
                "tier1_doc_updater",
            }
        },
        "counts": {"count"},
        "identifiers": {"task_id": TASK_ID},
    },
}


class InputError(ValueError):
    """Raised when an event is outside the normalized telemetry contract."""


def normalize(event_kind: Any, payload: Any) -> dict[str, Any]:
    """Return an allowlisted event payload or fail closed."""
    if not isinstance(event_kind, str) or event_kind not in EVENT_SCHEMAS:
        raise InputError("event kind is not allowlisted")
    if not isinstance(payload, dict):
        raise InputError("payload must be a JSON object")

    schema = EVENT_SCHEMAS[event_kind]
    required = schema["required"]
    optional = schema.get("optional", set())
    supplied = set(payload)
    if supplied != required | (supplied & optional):
        raise InputError("payload fields do not match the allowlisted schema")

    for field, values in schema.get("enums", {}).items():
        if payload[field] not in values:
            raise InputError(f"{field} is not an allowlisted enum value")
    for field in schema.get("counts", set()):
        value = payload[field]
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise InputError(f"{field} must be a non-negative integer")
    for field, pattern in schema.get("identifiers", {}).items():
        if field in payload and (
            not isinstance(payload[field], str) or not pattern.fullmatch(payload[field])
        ):
            raise InputError(f"{field} is not a valid opaque identifier")

    return {"event_kind": event_kind, **{key: payload[key] for key in sorted(payload)}}


def main() -> int:
    if len(sys.argv) != 3:
        print("usage: log-execute-efficiency-event.py <event-kind> <json-payload>", file=sys.stderr)
        return 2
    try:
        payload = json.loads(sys.argv[2])
        result = normalize(sys.argv[1], payload)
    except (InputError, json.JSONDecodeError) as error:
        print(json.dumps({"ok": False, "error": str(error)}, sort_keys=True), file=sys.stderr)
        return 2
    print(json.dumps(result, separators=(",", ":"), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
