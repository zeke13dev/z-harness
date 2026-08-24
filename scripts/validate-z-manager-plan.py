#!/usr/bin/env python3
"""Fail-closed validator for a sealed z-manager execution plan."""

from __future__ import annotations

import json
import sys
from pathlib import PurePosixPath
from typing import Any

UNSAFE_COMMAND_TERMS = (
    " deploy",
    " release",
    " publish",
    "git merge",
    "git push",
    "git rebase",
    "git reset",
    "rm -rf",
    "drop database",
    "drop schema",
    "drop table",
    "delete from",
    "truncate table",
)


def _paths(value: Any, field: str) -> list[str]:
    if not isinstance(value, list) or not value:
        raise ValueError(f"{field} must be a non-empty array")
    paths: list[str] = []
    for raw in value:
        if not isinstance(raw, str) or not raw.strip():
            raise ValueError(f"{field} contains an empty path")
        path = PurePosixPath(raw.strip())
        if path.is_absolute() or ".." in path.parts:
            raise ValueError(f"{field} contains an unscoped path: {raw}")
        paths.append(path.as_posix())
    return paths


def validate(plan: Any) -> dict[str, Any]:
    if not isinstance(plan, dict):
        raise ValueError("plan must be an object")
    for field in ("goals", "invariants"):
        values = plan.get(field)
        if (
            not isinstance(values, list)
            or not values
            or any(not isinstance(value, str) or not value.strip() for value in values)
        ):
            raise ValueError(f"{field} must be a non-empty array of strings")
    allowed = _paths(plan.get("allowed_paths"), "allowed_paths")
    nodes = plan.get("nodes")
    if not isinstance(nodes, list) or not 1 <= len(nodes) <= 12:
        raise ValueError("nodes must contain between 1 and 12 entries")
    ids: list[str] = []
    for node in nodes:
        if not isinstance(node, dict):
            raise ValueError("every node must be an object")
        node_id = node.get("id")
        if not isinstance(node_id, str) or not node_id.strip() or node_id in ids:
            raise ValueError("node ids must be non-empty and unique")
        if not isinstance(node.get("goal"), str) or not node["goal"].strip():
            raise ValueError(f"node {node_id} goal must be non-empty")
        ids.append(node_id)
        scoped = _paths(node.get("allowed_paths"), f"node {node_id} allowed_paths")
        for path in scoped:
            if not any(path == root or path.startswith(root.rstrip("/") + "/") for root in allowed):
                raise ValueError(f"node {node_id} path is outside plan scope: {path}")
        acceptance = node.get("acceptance")
        if (
            not isinstance(acceptance, list)
            or not acceptance
            or any(
                not isinstance(command, str) or not command.strip()
                for command in acceptance
            )
        ):
            raise ValueError(f"node {node_id} acceptance must be non-empty")
    id_set = set(ids)
    incoming: dict[str, set[str]] = {}
    for node in nodes:
        deps = node.get("dependencies")
        if not isinstance(deps, list) or any(not isinstance(dep, str) for dep in deps):
            raise ValueError(f"node {node['id']} dependencies must be strings")
        dep_set = set(deps)
        if node["id"] in dep_set or not dep_set <= id_set:
            raise ValueError(f"node {node['id']} has an invalid dependency")
        incoming[node["id"]] = dep_set
    ready = sorted(node_id for node_id, deps in incoming.items() if not deps)
    visited: list[str] = []
    while ready:
        current = ready.pop(0)
        visited.append(current)
        for node_id in sorted(incoming):
            if current in incoming[node_id]:
                incoming[node_id].remove(current)
                if not incoming[node_id] and node_id not in visited and node_id not in ready:
                    ready.append(node_id)
                    ready.sort()
    if len(visited) != len(nodes):
        raise ValueError("plan dependency graph is cyclic")
    commands = plan.get("acceptance_commands")
    if not isinstance(commands, list) or not commands:
        raise ValueError("acceptance_commands must be non-empty")
    for command in commands:
        if not isinstance(command, str) or not command.strip():
            raise ValueError("acceptance command must be a non-empty string")
        lowered = " " + command.strip().lower()
        if any(term in lowered for term in UNSAFE_COMMAND_TERMS):
            raise ValueError(f"acceptance command crosses a safety boundary: {command}")
    return {"valid": True, "topological_order": visited, "node_count": len(nodes)}


def main() -> int:
    try:
        result = validate(json.load(sys.stdin))
    except (ValueError, json.JSONDecodeError) as error:
        print(json.dumps({"valid": False, "error": str(error)}, sort_keys=True))
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
