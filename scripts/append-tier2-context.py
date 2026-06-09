#!/usr/bin/env python3
"""
append-tier2-context.py — Incremental context accumulation for Tier 2 narrative docs.

Appends structured data to $Z_HARNESS_PLAN_DIR/tier2-context.json across pipeline phases.
Validates JSON schema per field type. Supports upsert mode for task-level dedup.
Atomic writes via tmp file + os.replace.
"""

import argparse
import json
import os
import sys
import time

SCHEMA_SKELETON = {
    "plan": "",
    "generated_at": "",
    "finalized": False,
    "spec_summary": "",
    "plan_summary": "",
    "decisions": [],
    "consultant_findings": [],
    "tried_and_failed": [],
    "deviations": [],
    "breaking_changes": [],
    "review_patterns": [],
    "human_overrides": [],
    "gaps": [],
}

FIELD_SCHEMAS = {
    "decisions": {
        "required": ["id", "phase", "chosen", "rationale"],
        "optional": ["rejected", "consultant_consensus", "human_override", "human_reason", "adr_worthy"],
    },
    "consultant_findings": {
        "required": ["finding", "source", "severity", "disposition"],
        "optional": ["reason"],
    },
    "tried_and_failed": {
        "required": ["task", "concept", "attempts", "chose"],
        "optional": ["reviewer_validated"],
    },
    "deviations": {
        "required": ["task", "deviation", "reason"],
        "optional": ["reviewer_validated", "reviewer_note"],
    },
    "breaking_changes": {
        "required": ["api", "old", "new"],
        "optional": ["consumers", "breaking"],
    },
    "review_patterns": {
        "required": ["pattern", "source", "finding"],
        "optional": ["recommendation"],
    },
    "human_overrides": {
        "required": ["phase", "decision_id", "override"],
        "optional": ["reason", "overrides_consultant", "consultant_affected"],
    },
    "gaps": {
        "required": ["field", "status"],
        "optional": ["note"],
    },
}

VALID_PHASES = {"plan", "implement", "review"}


def validate_payload(field: str, payload: object) -> str | None:
    """Validate a single payload entry against the field schema. Returns error string or None."""
    if not isinstance(payload, dict):
        return f"payload for field '{field}' must be a JSON object, got {type(payload).__name__}"
    schema = FIELD_SCHEMAS.get(field)
    if schema is None:
        return f"unknown field '{field}'"
    for key in schema["required"]:
        if key not in payload:
            return f"payload for field '{field}' missing required key '{key}'"
    return None


def load_context(plan_dir: str) -> dict:
    """Load existing tier2-context.json or return skeleton."""
    path = os.path.join(plan_dir, "tier2-context.json")
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return dict(SCHEMA_SKELETON)


def save_context(plan_dir: str, data: dict) -> None:
    """Atomically write tier2-context.json."""
    path = os.path.join(plan_dir, "tier2-context.json")
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, path)


def upsert_entry(entries: list, payload: dict, key_fields: list[str]) -> list:
    """Replace existing entry with matching key fields, or append."""
    key_vals = {k: payload.get(k) for k in key_fields}
    for i, entry in enumerate(entries):
        if all(entry.get(k) == key_vals[k] for k in key_fields):
            entries[i] = payload
            return entries
    entries.append(payload)
    return entries


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Append to tier2-context.json for Tier 2 narrative doc accumulation"
    )
    parser.add_argument("--phase", required=True, choices=sorted(VALID_PHASES),
                        help="Pipeline phase (plan, implement, review)")
    parser.add_argument("--field", required=True, choices=sorted(FIELD_SCHEMAS.keys()),
                        help="Context field to append to")
    parser.add_argument("--json", required=True, help="JSON payload (single object or array)")
    parser.add_argument("--upsert", action="store_true",
                        help="Replace existing entry by task/id instead of always appending")
    parser.add_argument("--mark-amended", action="store_true",
                        help="Append a plan_amended marker event")
    parser.add_argument("--plan-dir", default=None,
                        help="Plan directory (default: $Z_HARNESS_PLAN_DIR)")
    args = parser.parse_args()

    plan_dir = args.plan_dir or os.environ.get("Z_HARNESS_PLAN_DIR")
    if not plan_dir:
        print("Error: --plan-dir or $Z_HARNESS_PLAN_DIR must be set", file=sys.stderr)
        sys.exit(2)

    # Parse payload
    try:
        payload_raw = json.loads(args.json)
    except json.JSONDecodeError as e:
        print(f"Error: invalid JSON payload: {e}", file=sys.stderr)
        sys.exit(2)

    # Normalize to list of entries
    if isinstance(payload_raw, list):
        entries_payload = payload_raw
    else:
        entries_payload = [payload_raw]

    # Validate each entry
    for entry in entries_payload:
        err = validate_payload(args.field, entry)
        if err:
            print(f"Error: {err}", file=sys.stderr)
            sys.exit(1)

    # Load context
    context = load_context(plan_dir)

    # Ensure skeleton fields exist
    for key, default in SCHEMA_SKELETON.items():
        if key not in context:
            context[key] = default

    # Handle plan_amended marker
    if args.mark_amended:
        context.setdefault("amend_events", [])
        context["amend_events"].append({
            "event": "plan_amended",
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        })

    # Append or upsert
    field_array = context.setdefault(args.field, [])
    if args.upsert:
        # Determine key fields for upsert
        if args.field in ("tried_and_failed", "deviations", "breaking_changes"):
            key_fields = ["task"]
        elif args.field == "decisions":
            key_fields = ["id"]
        else:
            key_fields = []
        if key_fields:
            for entry in entries_payload:
                field_array = upsert_entry(field_array, entry, key_fields)
            context[args.field] = field_array
        else:
            field_array.extend(entries_payload)
    else:
        field_array.extend(entries_payload)

    # Update generated_at
    context["generated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    # Save atomically
    save_context(plan_dir, context)
    print(f"Appended {len(entries_payload)} entry(s) to {args.field} (phase: {args.phase})")


if __name__ == "__main__":
    main()
