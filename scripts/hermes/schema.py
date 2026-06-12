"""
schema.py — Hermes orchestrator schema definitions.

Implements workstreams.json and session-status.json schemas
per docs/human/hermes-integration-v1.md v1.3.0.

Used by all clusters for type-safe schema access.
"""

from dataclasses import dataclass, field, asdict
from typing import Optional
import json
from pathlib import Path


# ---------------------------------------------------------------------------
# workstreams.json schema
# ---------------------------------------------------------------------------

@dataclass
class Workstream:
    """A single workstream in the execution plan."""
    id: str                              # "ws-1", "ws-2", ...
    status: str                          # "ready" | "failed"
    name: str                            # Human-readable description
    path: str                            # Repo-relative path (no trailing /)
    tasks: list[str] = field(default_factory=list)  # Ordered task IDs
    depends_on: list[str] = field(default_factory=list)  # Workstream IDs
    parallel_group: Optional[str] = None  # Derived label "level-{depth}" from ws DAG longest-path depth; None for legacy manifests


@dataclass
class FileConflict:
    """Cross-workstream file overlap."""
    file: str                            # Repo-relative path
    workstreams: list[str]               # ≥2 workstream IDs
    severity: str                        # "high" | "medium" | "low"


@dataclass
class WorkstreamsManifest:
    """Top-level workstreams.json schema."""
    protocol: str                        # "hermes-v1"
    slug: str                            # Plan identifier
    source: str                          # "/z-plan-split" | "/z-plan" | "/z-plan-light"
    generated_at: str                    # ISO 8601 UTC
    partial_tree: bool                   # True if any workstream has status "failed"
    scope_unknown: bool = False          # True when ≥1 task block had no parseable **Files:** line
    workstreams: list[Workstream] = field(default_factory=list)
    file_conflicts: list[FileConflict] = field(default_factory=list)
    merge_order: list[str] = field(default_factory=list)


def parse_workstreams_json(path: str) -> WorkstreamsManifest:
    """Parse workstreams.json into typed dataclass."""
    with open(path) as f:
        data = json.load(f)
    
    return WorkstreamsManifest(
        protocol=data["protocol"],
        slug=data["slug"],
        source=data["source"],
        generated_at=data["generated_at"],
        partial_tree=data.get("partial_tree", False),
        scope_unknown=data.get("scope_unknown", False),
        workstreams=[
            Workstream(
                id=w["id"],
                status=w["status"],
                name=w["name"],
                path=w["path"].rstrip("/"),
                tasks=w.get("tasks", []),
                depends_on=w.get("depends_on", []),
                parallel_group=w.get("parallel_group"),
            )
            for w in data.get("workstreams", [])
        ],
        file_conflicts=[
            FileConflict(
                file=fc["file"],
                workstreams=fc["workstreams"],
                severity=fc["severity"],
            )
            for fc in data.get("file_conflicts", [])
        ],
        merge_order=data.get("merge_order", []),
    )


# ---------------------------------------------------------------------------
# session-status.json schema
# ---------------------------------------------------------------------------

@dataclass
class SessionStatus:
    """Per-workstream session liveness signal."""
    status: str                          # "running" | "done" | "halted" | "paused"
    halt_reason: Optional[str] = None    # "decision_needed" | "spec_problem" | "needs_clarification"
    halt_description: Optional[str] = None  # Free-text (untrusted — sanitize before UI)
    tasks_done: int = 0
    tasks_total: int = 0
    current_task: Optional[str] = None
    updated_at: Optional[str] = None     # ISO 8601 UTC
    slug: Optional[str] = None           # Plan identifier — lets a scan confirm which plan this file belongs to


def parse_session_status(path: str) -> Optional[SessionStatus]:
    """Parse session-status.json. Returns None if file missing or unparseable."""
    try:
        with open(path) as f:
            data = json.load(f)
        return SessionStatus(
            status=data["status"],
            halt_reason=data.get("halt_reason"),
            halt_description=data.get("halt_description"),
            tasks_done=data.get("tasks_done", 0),
            tasks_total=data.get("tasks_total", 0),
            current_task=data.get("current_task"),
            updated_at=data.get("updated_at"),
            slug=data.get("slug"),
        )
    except (FileNotFoundError, json.JSONDecodeError, KeyError):
        return None


# ---------------------------------------------------------------------------
# hermes-resolve.json schema
# ---------------------------------------------------------------------------

@dataclass
class ResolveAnswer:
    """Answer to a halted-session question."""
    decision_id: str
    chosen: str
    rationale: str = ""


def write_resolve_json(path: str, answer: ResolveAnswer) -> None:
    """Write hermes-resolve.json atomically."""
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(asdict(answer), f, indent=2)
        f.write("\n")
    Path(tmp).rename(path)


def read_resolve_json(path: str) -> Optional[ResolveAnswer]:
    """Read hermes-resolve.json. Returns None if file missing."""
    try:
        with open(path) as f:
            data = json.load(f)
        return ResolveAnswer(
            decision_id=data["decision_id"],
            chosen=data["chosen"],
            rationale=data.get("rationale", ""),
        )
    except (FileNotFoundError, json.JSONDecodeError, KeyError):
        return None


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

import re

SLUG_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


def validate_manifest(manifest: WorkstreamsManifest) -> list[str]:
    """Validate workstreams.json against all 7 schema rules.
    
    Returns list of error messages (empty = valid).
    """
    errors = []
    ws_ids = {w.id for w in manifest.workstreams}

    # scope_unknown must be a boolean
    if not isinstance(manifest.scope_unknown, bool):
        errors.append(
            f"scope_unknown must be a bool, got {type(manifest.scope_unknown).__name__}"
        )

    # Rule 1: depends_on references must exist
    for w in manifest.workstreams:
        for dep in w.depends_on:
            if dep not in ws_ids:
                errors.append(f"ws '{w.id}' depends_on '{dep}' which doesn't exist")
    
    # Rule 2: No dependency cycles (topological sort)
    in_degree = {w.id: len(w.depends_on) for w in manifest.workstreams}
    from collections import deque
    queue = deque([wid for wid, deg in in_degree.items() if deg == 0])
    visited = 0
    while queue:
        wid = queue.popleft()
        visited += 1
        for w in manifest.workstreams:
            if wid in w.depends_on:
                in_degree[w.id] -= 1
                if in_degree[w.id] == 0:
                    queue.append(w.id)
    if visited != len(manifest.workstreams):
        errors.append("Dependency cycle detected in depends_on")
    
    # Rule 3: merge_order is a permutation
    merge_set = set(manifest.merge_order)
    if merge_set != ws_ids:
        errors.append(f"merge_order is not a permutation of workstream IDs")
    
    # Rule 4: file_conflicts workstreams must exist
    for fc in manifest.file_conflicts:
        for ws_id in fc.workstreams:
            if ws_id not in ws_ids:
                errors.append(f"file_conflict references unknown ws '{ws_id}'")
    
    # Rule 5: paths are repo-relative, safe
    for w in manifest.workstreams:
        p = w.path
        if p.startswith("/") or p.startswith(".."):
            errors.append(f"ws '{w.id}' path '{p}' is not repo-relative")
        if "//" in p:
            errors.append(f"ws '{w.id}' path '{p}' contains '//'")
        if p.endswith("/"):
            errors.append(f"ws '{w.id}' path '{p}' ends with '/'")
    
    # Rule 7: parallel_group members must be mutually independent
    from collections import defaultdict
    groups = defaultdict(list)
    for w in manifest.workstreams:
        if w.parallel_group is not None:
            groups[w.parallel_group].append(w.id)
    
    def transitive_deps(wid):
        result = set()
        stack = list(next(w for w in manifest.workstreams if w.id == wid).depends_on)
        while stack:
            dep = stack.pop()
            if dep in result:
                continue
            result.add(dep)
            for w in manifest.workstreams:
                if w.id == dep:
                    stack.extend(w.depends_on)
        return result
    
    for group, members in groups.items():
        for a in members:
            a_deps = transitive_deps(a)
            for b in members:
                if a != b and b in a_deps:
                    errors.append(
                        f"ws '{a}' depends on '{b}' but both in parallel_group '{group}'"
                    )
    
    return errors


def validate_slug(slug: str) -> bool:
    """Validate slug for git branch safety."""
    return bool(SLUG_RE.match(slug))
