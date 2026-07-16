#!/usr/bin/env python3
"""Read-only validation for an INTENT-mode implementation dispatch.

The CLI deliberately has no scheduler, registry, or supervisor dependency.  It
accepts one JSON object on stdin and emits one normalized JSON result on stdout.
The local graph schema is either ``{"nodes": [{"id", "dependencies",
"status"}]}`` or ``{"dependencies": {"T001": []}, "completed_ids": []}``.
For the latter form (and a bare ``{task_id: [dependencies]}`` mapping), only an
empty dependency list is ready unless ``completed_ids`` says otherwise.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import PurePosixPath
from typing import Any


TASK_ID = re.compile(r"T\d{3}\Z")
COMPLEXITY = {"low", "medium", "high", "retry"}
CONTEXT_KEYS = (
    "frozen_intent",
    "graph",
    "ledger",
    "strategy",
    "dependency_context",
)


def error(errors: list[dict[str, str]], code: str, message: str, **details: str) -> None:
    entry = {"code": code, "message": message}
    entry.update({key: value for key, value in details.items() if value is not None})
    errors.append(entry)


def normal_path(value: Any) -> str | None:
    """Return a precise repo-relative POSIX file path, or ``None``."""
    if not isinstance(value, str) or not value or "\\" in value:
        return None
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        return None
    normalized = str(path)
    if normalized != value or any(char in value for char in "*?[]{}") or value.endswith("/"):
        return None
    return normalized


def overlaps(first: str, second: str) -> bool:
    return first == second or first.startswith(second + "/") or second.startswith(first + "/")


def parse_graph(graph: Any, errors: list[dict[str, str]]) -> tuple[dict[str, list[str]], set[str]]:
    dependencies: dict[str, list[str]] = {}
    completed: set[str] = set()
    if not isinstance(graph, dict):
        error(errors, "INVALID_GRAPH", "graph must be an object")
        return dependencies, completed

    if "nodes" in graph:
        nodes = graph["nodes"]
        if not isinstance(nodes, list):
            error(errors, "INVALID_GRAPH", "graph.nodes must be a list")
            return dependencies, completed
        for node in nodes:
            if not isinstance(node, dict):
                error(errors, "INVALID_GRAPH_NODE", "graph node must be an object")
                continue
            task_id = node.get("id")
            deps = node.get("dependencies", node.get("depends_on", []))
            if not isinstance(task_id, str) or not TASK_ID.fullmatch(task_id):
                error(errors, "INVALID_GRAPH_ID", "graph node id must match TNNN", id=str(task_id))
                continue
            if task_id in dependencies:
                error(errors, "DUPLICATE_GRAPH_ID", "graph node id appears more than once", id=task_id)
                continue
            if not isinstance(deps, list) or not all(isinstance(dep, str) for dep in deps):
                error(errors, "INVALID_DEPENDENCIES", "graph dependencies must be a list of task IDs", id=task_id)
                deps = []
            dependencies[task_id] = list(deps)
            if node.get("status") in {"complete", "completed", "done"}:
                completed.add(task_id)
        return dependencies, completed

    source = graph.get("dependencies", graph)
    if not isinstance(source, dict):
        error(errors, "INVALID_GRAPH", "graph.dependencies must be an object")
        return dependencies, completed
    for task_id, deps in source.items():
        if not isinstance(task_id, str) or not TASK_ID.fullmatch(task_id):
            error(errors, "INVALID_GRAPH_ID", "graph id must match TNNN", id=str(task_id))
            continue
        if not isinstance(deps, list) or not all(isinstance(dep, str) for dep in deps):
            error(errors, "INVALID_DEPENDENCIES", "graph dependencies must be a list of task IDs", id=task_id)
            deps = []
        dependencies[task_id] = list(deps)
    supplied_completed = graph.get("completed_ids", [])
    if (
        not isinstance(supplied_completed, list)
        or not all(isinstance(value, str) and TASK_ID.fullmatch(value) for value in supplied_completed)
    ):
        error(errors, "INVALID_COMPLETED_IDS", "graph.completed_ids must be a list of task IDs")
    else:
        completed.update(supplied_completed)
    return dependencies, completed


def validate_context(context: Any, errors: list[dict[str, str]]) -> None:
    if not isinstance(context, dict):
        error(errors, "INCOMPLETE_INTENT_CONTEXT", "intent_context must be an object")
        return
    for key in CONTEXT_KEYS:
        value = context.get(key)
        if not isinstance(value, str) or not value:
            error(errors, "INCOMPLETE_INTENT_CONTEXT", f"intent_context.{key} is required", field=key)
        elif not os.path.isfile(value) or not os.access(value, os.R_OK):
            error(errors, "UNREADABLE_INTENT_CONTEXT", f"intent_context.{key} must be a readable file", field=key)


def preflight(document: Any) -> dict[str, Any]:
    errors: list[dict[str, str]] = []
    serial_task_ids: list[str] = []
    if not isinstance(document, dict):
        return {"ok": False, "errors": [{"code": "INVALID_INPUT", "message": "input must be an object"}], "serial_only": False, "serial_task_ids": [], "deferred_followups": deferred_followups()}

    run_id = document.get("run_id")
    if not isinstance(run_id, str) or not run_id.strip():
        error(errors, "INVALID_RUN_ID", "run_id must be a non-empty string")
    tasks = document.get("tasks")
    if not isinstance(tasks, list):
        error(errors, "INVALID_TASKS", "tasks must be a list")
        tasks = []
    graph, completed = parse_graph(document.get("graph"), errors)
    validate_context(document.get("intent_context"), errors)

    fanout = document.get("fanout")
    if isinstance(fanout, bool) or not isinstance(fanout, int) or not 1 <= fanout <= 3:
        error(errors, "INVALID_FANOUT", "fanout must be an integer in 1..3")
        fanout = 0
    ready_ids = document.get("ready_ids")
    if not isinstance(ready_ids, list) or not all(isinstance(value, str) for value in ready_ids):
        error(errors, "INVALID_READY_IDS", "ready_ids must be a list of task IDs")
        ready_ids = []
    elif not ready_ids or len(ready_ids) > fanout or len(ready_ids) > 3 or len(set(ready_ids)) != len(ready_ids):
        error(errors, "INVALID_READY_FRONTIER", "ready_ids must be a non-empty unique frontier within fanout")

    task_by_id: dict[str, dict[str, Any]] = {}
    task_paths: dict[str, list[str]] = {}
    for task in tasks:
        if not isinstance(task, dict):
            error(errors, "INVALID_TASK", "each task must be an object")
            continue
        task_id = task.get("id")
        if not isinstance(task_id, str) or not TASK_ID.fullmatch(task_id):
            error(errors, "INVALID_TASK_ID", "task id must match TNNN", id=str(task_id))
            continue
        if task_id in task_by_id:
            error(errors, "DUPLICATE_TASK_ID", "task id appears more than once", id=task_id)
            continue
        task_by_id[task_id] = task
        paths = task.get("paths", task.get("files"))
        if not isinstance(paths, list) or not paths:
            error(errors, "UNUSABLE_PATHS", "task must declare non-empty paths", id=task_id)
            task_paths[task_id] = []
        else:
            normalized = [normal_path(path) for path in paths]
            if any(path is None for path in normalized) or len(set(normalized)) != len(normalized):
                error(errors, "UNUSABLE_PATHS", "declared paths must be unique precise repo-relative file paths", id=task_id)
            task_paths[task_id] = [path for path in normalized if path is not None]
        complexity = task.get("complexity")
        if not isinstance(complexity, str) or complexity not in COMPLEXITY:
            error(errors, "MISSING_COMPLEXITY", "task complexity must be low, medium, high, or retry", id=task_id)
        if len(task_paths[task_id]) > 3:
            if not isinstance(task.get("atomic_reason"), str) or not task["atomic_reason"].strip():
                error(errors, "MISSING_ATOMIC_REASON", "multi-file task requires a non-empty atomic_reason", id=task_id)

    if set(task_by_id) != set(graph):
        error(errors, "TASK_GRAPH_MISMATCH", "task and graph IDs must match exactly")
    for task_id, deps in graph.items():
        for dependency in deps:
            if not TASK_ID.fullmatch(dependency) or dependency not in graph:
                error(errors, "INVALID_DEPENDENCY", "dependency must name a graph task", id=task_id, dependency=str(dependency))

    exclusions = document.get("hard_exclusions")
    if not isinstance(exclusions, list) or not all(isinstance(value, str) and normal_path(value.rstrip("/")) for value in exclusions):
        error(errors, "INVALID_HARD_EXCLUSIONS", "hard_exclusions must be repo-relative path prefixes")
        exclusions = []
    normalized_exclusions = [value.rstrip("/") for value in exclusions]
    for task_id, paths in task_paths.items():
        for path in paths:
            if any(path == prefix or path.startswith(prefix + "/") for prefix in normalized_exclusions):
                error(errors, "HARD_EXCLUSION", "declared path is hard-excluded", id=task_id, path=path)

    held = document.get("held_paths")
    if not isinstance(held, list):
        error(errors, "INVALID_HELD_PATHS", "held_paths must be a list")
        held = []
    held_paths: set[str] = set()
    for entry in held:
        if not isinstance(entry, dict) or not isinstance(entry.get("run_id"), str) or normal_path(entry.get("path")) is None:
            error(errors, "INVALID_HELD_PATH", "held path records require run_id and a repo-relative path")
            continue
        if entry["run_id"] != run_id:
            held_paths.add(normal_path(entry["path"]) or "")
    for task_id, paths in task_paths.items():
        for path in paths:
            if path in held_paths:
                error(errors, "HELD_PATH_COLLISION", "declared path is actively held by another run", id=task_id, path=path)

    ready_set = set(ready_ids)
    for task_id in ready_ids:
        if not TASK_ID.fullmatch(task_id) or task_id not in task_by_id or task_id not in graph:
            error(errors, "INVALID_READY_TASK", "ready task must exist in tasks and graph", id=task_id)
            continue
        unresolved = [dependency for dependency in graph[task_id] if dependency not in completed]
        if unresolved:
            error(errors, "UNSATISFIED_DEPENDENCY", "ready task has unsatisfied dependencies", id=task_id, dependency=unresolved[0])
        task = task_by_id[task_id]
        if len(task_paths[task_id]) > 3 and task.get("disjointness_proven") is not True:
            serial_task_ids.append(task_id)

    for index, first_id in enumerate(ready_ids):
        for second_id in ready_ids[index + 1:]:
            for first_path in task_paths.get(first_id, []):
                for second_path in task_paths.get(second_id, []):
                    if overlaps(first_path, second_path):
                        error(errors, "UNSAFE_PATH_OVERLAP", "ready tasks must have disjoint declared paths", id=first_id, path=first_path, other_id=second_id, other_path=second_path)
    if serial_task_ids and len(ready_set) > 1:
        error(errors, "FRONTIER_REQUIRES_SERIAL", "unproven atomic multi-file task cannot share a ready frontier", id=serial_task_ids[0])

    errors.sort(key=lambda item: (item["code"], item.get("id", ""), item.get("path", ""), item["message"]))
    return {"ok": not errors, "errors": errors, "serial_only": bool(serial_task_ids), "serial_task_ids": sorted(serial_task_ids), "deferred_followups": deferred_followups()}


def deferred_followups() -> list[dict[str, str]]:
    return [{"topic": "supervisor_integration", "status": "deferred", "reason": "Supervisor lifecycle integration is intentionally outside this read-only preflight."}]


def main() -> int:
    try:
        document = json.load(sys.stdin)
    except json.JSONDecodeError as exc:
        result = {"ok": False, "errors": [{"code": "INVALID_JSON", "message": f"invalid JSON: {exc.msg}"}], "serial_only": False, "serial_task_ids": [], "deferred_followups": deferred_followups()}
    else:
        result = preflight(document)
    json.dump(result, sys.stdout, sort_keys=True, separators=(",", ":"))
    sys.stdout.write("\n")
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
