#!/usr/bin/env python3
"""
generate-workstreams.py — Post-plan hook that generates workstreams.json
from z-harness plan artifacts.

Hermes Integration Protocol v1.2.0 (docs/human/hermes-integration-v1.md).

Two modes:
  --source=z-plan-split  → reads MANIFEST.md + SHARED-CONCERNS.md
  --source=z-plan        → reads TASKS.md, runs 5-rule DAG algorithm

Atomic output to <plan-dir>/workstreams.json via temp file + rename.
Idempotent: unchanged inputs → byte-identical output.
"""

import argparse
import json
import os
import re
import sys
from collections import defaultdict, deque
from datetime import datetime, timezone
from pathlib import Path


# ---------------------------------------------------------------------------
# Schema constants
# ---------------------------------------------------------------------------

PROTOCOL = "hermes-v1"
SLUG_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")

# Severity heuristics from z-plan-split SKILL.md Phase 4
HIGH_SEVERITY_RE = re.compile(
    r".*\.(sql|migration|schema|toml|yaml|yml|proto)$"
)
HIGH_SEVERITY_NAMES = {
    "Dockerfile", "Makefile", "package.json", "package-lock.json",
    "Cargo.lock", "pnpm-lock.yaml", "yarn.lock",
}
MEDIUM_SEVERITY_RE = re.compile(r".*\.(rs|py|ts|tsx|js|jsx)$")


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

class ValidationError(Exception):
    """Schema validation failure."""
    pass


def validate_workstreams(workstreams, file_conflicts, merge_order):
    """Raise ValidationError if any schema rule is violated."""
    ws_ids = {w["id"] for w in workstreams}

    # Rule 1: depends_on references must exist
    for w in workstreams:
        for dep in w["depends_on"]:
            if dep not in ws_ids:
                raise ValidationError(
                    f"Workstream '{w['id']}' depends_on '{dep}' "
                    f"which does not exist in workstreams[]"
                )

    # Rule 2: No dependency cycles
    _check_no_cycles(workstreams)

    # Rule 3: merge_order is a permutation of workstream IDs
    merge_set = set(merge_order)
    if merge_set != ws_ids:
        missing = ws_ids - merge_set
        extra = merge_set - ws_ids
        msg = f"merge_order is not a permutation of workstream IDs"
        if missing:
            msg += f"; missing: {sorted(missing)}"
        if extra:
            msg += f"; extra: {sorted(extra)}"
        raise ValidationError(msg)

    # Rule 4: file_conflicts workstream entries reference valid IDs
    for fc in file_conflicts:
        for ws_id in fc["workstreams"]:
            if ws_id not in ws_ids:
                raise ValidationError(
                    f"file_conflict references unknown workstream '{ws_id}'"
                )

    # Rule 5: paths are repo-relative, safe
    for w in workstreams:
        path = w["path"]
        if path.startswith("/") or path.startswith(".."):
            raise ValidationError(
                f"Workstream '{w['id']}' path '{path}' is not repo-relative"
            )
        if "//" in path:
            raise ValidationError(
                f"Workstream '{w['id']}' path '{path}' contains '//'"
            )
        if path.endswith("/"):
            raise ValidationError(
                f"Workstream '{w['id']}' path '{path}' ends with '/'"
            )

    # Rule 7: parallel_group workstreams must be mutually independent
    groups = defaultdict(list)
    for w in workstreams:
        if w["parallel_group"] is not None:
            groups[w["parallel_group"]].append(w["id"])
    for group, members in groups.items():
        for a in members:
            a_deps = _transitive_deps(a, workstreams)
            for b in members:
                if a == b:
                    continue
                if b in a_deps:
                    raise ValidationError(
                        f"Workstream '{a}' depends on '{b}' but both are "
                        f"in parallel_group '{group}'"
                    )


def _check_no_cycles(workstreams):
    """Topological sort; raise ValidationError on cycle."""
    ws_map = {w["id"]: w for w in workstreams}
    in_degree = {w["id"]: 0 for w in workstreams}
    for w in workstreams:
        for dep in w["depends_on"]:
            in_degree[w["id"]] += 1

    queue = deque([wid for wid, deg in in_degree.items() if deg == 0])
    visited = 0
    while queue:
        wid = queue.popleft()
        visited += 1
        # Find workstreams that depend on wid
        for w in workstreams:
            if wid in w["depends_on"]:
                in_degree[w["id"]] -= 1
                if in_degree[w["id"]] == 0:
                    queue.append(w["id"])

    if visited != len(workstreams):
        raise ValidationError("Dependency cycle detected in workstream depends_on")


def _transitive_deps(wid, workstreams):
    """Return set of all transitive dependency IDs for wid."""
    ws_map = {w["id"]: w for w in workstreams}
    result = set()
    stack = list(ws_map[wid]["depends_on"])
    while stack:
        dep = stack.pop()
        if dep in result:
            continue
        result.add(dep)
        if dep in ws_map:
            stack.extend(ws_map[dep]["depends_on"])
    return result


# ---------------------------------------------------------------------------
# 5-rule DAG algorithm (flat z-plan)
# ---------------------------------------------------------------------------

class CycleError(Exception):
    """Dependency cycle detected in TASKS.md."""
    pass


def _task_sort_key(task_id: str):
    """Sort key for task IDs: T001 < T002 < T-REV-001, etc."""
    m = re.match(r"T[-_]?(\d+)", task_id)
    if m:
        return (0, int(m.group(1)), task_id)
    return (1, 0, task_id)  # Non-standard IDs sort after T-prefixed


def parse_depends_on(tasks_text):
    """Parse **Depends on:** Txxx lines from TASKS.md.
    
    Returns dict of task_id → list of dependency task_ids.
    """
    deps = {}
    current_task = None
    
    for line in tasks_text.splitlines():
        # Detect task headers: ### Txxx or ## Txxx
        m = re.match(r"^#{2,3}\s+(T\d+)", line.strip())
        if m:
            current_task = m.group(1)
            if current_task not in deps:
                deps[current_task] = []
            continue
        
        # Detect Depends on lines
        if current_task and "**Depends on:**" in line:
            # Extract all Txxx references
            task_refs = re.findall(r"T\d+", line)
            deps[current_task].extend(task_refs)
    
    return deps


def assign_depths(deps):
    """Assign depth to each task. Raise CycleError on cycle.
    
    Returns dict of task_id → depth (int).
    """
    # Build reverse index: task → set of tasks that depend on it
    all_tasks = set(deps.keys())
    for task_deps in deps.values():
        all_tasks.update(task_deps)
    
    dependents = defaultdict(set)
    for task, task_deps in deps.items():
        for dep in task_deps:
            if dep not in all_tasks:
                # External dependency (task from another plan) — treat as satisfied
                continue
            dependents[dep].add(task)
    
    in_degree = {}
    for task in all_tasks:
        resolved_deps = [d for d in deps.get(task, []) if d in all_tasks]
        in_degree[task] = len(resolved_deps)
    
    depths = {}
    queue = deque([t for t in all_tasks if in_degree.get(t, 0) == 0])
    
    while queue:
        task = queue.popleft()
        depths[task] = max(
            (depths.get(d, -1) + 1 for d in deps.get(task, []) if d in depths),
            default=0,
        )
        for dep in dependents.get(task, []):
            in_degree[dep] -= 1
            if in_degree[dep] == 0:
                queue.append(dep)
    
    if len(depths) != len(all_tasks):
        raise CycleError(
            f"Dependency cycle detected: {len(depths)}/{len(all_tasks)} tasks assigned depth"
        )
    
    return depths


def run_5rule_algorithm(task_ids, deps):
    """Run the 5-rule DAG derivation algorithm.
    
    Returns list of workstream dicts (id, name, tasks, depends_on, path prefix).
    
    Rules:
    1. Parse into DAG (already done — deps dict)
    2. Assign depths
    3. Group by depth
    4. Collapse linear chains
    5. Split at parent boundaries
    """
    depths = assign_depths(deps)

    # Rule 3: Group by depth
    by_depth = defaultdict(set)
    for task in task_ids:
        by_depth[depths.get(task, 0)].add(task)

    max_depth = max(by_depth.keys()) if by_depth else 0

    # Build workstream candidates (depth groups)
    ws_candidates = {}
    for depth in sorted(by_depth.keys()):
        ws_candidates[depth] = by_depth[depth]

    # Rule 4: Collapse linear chains
    # If depth N has exactly 1 task AND that task is the sole dependency
    # of depth N+1 (which also has exactly 1 task), merge.
    collapsed = {}  # depth → merged depth group
    merged_workstreams = []  # list of (depth, tasks)
    depth = 0
    while depth <= max_depth:
        if depth not in ws_candidates:
            depth += 1
            continue

        current_tasks = ws_candidates[depth]
        
        # Check if this is a linear chain start
        if len(current_tasks) == 1 and depth + 1 in ws_candidates:
            solo = next(iter(current_tasks))
            next_tasks = ws_candidates.get(depth + 1, set())
            
            if len(next_tasks) == 1:
                next_solo = next(iter(next_tasks))
                # Check: solo is the sole dependency of next_solo
                next_deps = deps.get(next_solo, [])
                if next_deps == [solo] or set(next_deps) == {solo}:
                    # Merge into chain — find the full chain
                    chain = [solo, next_solo]
                    chain_depth = depth + 1
                    while (chain_depth + 1) in ws_candidates:
                        next_set = ws_candidates[chain_depth + 1]
                        if len(next_set) != 1:
                            break
                        chain_tail = chain[-1]
                        next_candidate = next(iter(next_set))
                        cand_deps = deps.get(next_candidate, [])
                        if cand_deps == [chain_tail] or set(cand_deps) == {chain_tail}:
                            chain.append(next_candidate)
                            chain_depth += 1
                        else:
                            break
                    
                    merged_workstreams.append((depth, set(chain)))
                    depth = chain_depth + 1
                    continue

        merged_workstreams.append((depth, current_tasks))
        depth += 1

    # Rule 5: Split at parent boundaries
    # Tasks at the same depth whose parents ended up in different workstreams
    # after step 4 → separate workstreams.
    task_to_ws = {}  # task_id → ws index
    final_workstreams = []
    
    for depth, tasks in merged_workstreams:
        if depth == 0:
            # Depth 0 tasks have no parents → single workstream
            final_workstreams.append(tasks)
            for t in tasks:
                task_to_ws[t] = len(final_workstreams) - 1
        else:
            # Group tasks by parent workstream
            by_parent_ws = defaultdict(set)
            for task in tasks:
                parent_wss = set()
                for dep in deps.get(task, []):
                    if dep in task_to_ws:
                        parent_wss.add(task_to_ws[dep])
                # If no mapped parents, use same workstream
                key = tuple(sorted(parent_wss)) if parent_wss else (-1,)
                by_parent_ws[key].add(task)
            
            for key, subtasks in by_parent_ws.items():
                final_workstreams.append(subtasks)
                for t in subtasks:
                    task_to_ws[t] = len(final_workstreams) - 1

    # Build workstream objects
    ws_objects = []
    for i, tasks in enumerate(final_workstreams):
        ws_id = f"ws-{i + 1}"
        sorted_tasks = sorted(tasks, key=_task_sort_key)

        # Compute depends_on from task-level deps
        ws_deps = set()
        for task in sorted_tasks:
            for dep in deps.get(task, []):
                if dep in task_to_ws and task_to_ws[dep] != i:
                    dep_ws_id = f"ws-{task_to_ws[dep] + 1}"
                    ws_deps.add(dep_ws_id)
        
        ws_objects.append({
            "id": ws_id,
            "name": sorted_tasks[0] if sorted_tasks else f"Workstream {i+1}",
            "tasks": sorted_tasks,
            "depends_on": sorted(ws_deps),
        })

    # Assign parallel_group = f"level-{depth}" from workstream-level longest-path depth.
    ws_depths = assign_ws_depths(ws_objects)
    for ws in ws_objects:
        ws["parallel_group"] = f"level-{ws_depths[ws['id']]}"

    # Topological sort for merge_order
    merge_order = topological_sort_ws(ws_objects)

    return ws_objects, merge_order


def assign_ws_depths(ws_objects):
    """Compute longest-path depth for each workstream over the ws depends_on DAG.

    A root (no depends_on) is depth 0.  All others are 1 + max(depth of deps).
    The input is assumed to be a DAG (Rule 2 guarantees acyclic); a defensive
    guard skips any workstream whose predecessors have not yet been resolved
    (should not occur in valid output).

    Returns:
        dict[ws_id, int] — mapping from workstream ID to longest-path depth.
    """
    ws_map = {w["id"]: w for w in ws_objects}
    depths = {}

    # Kahn-style topological iteration to resolve depths in dependency order.
    in_degree = {w["id"]: len(w["depends_on"]) for w in ws_objects}
    queue = deque([wid for wid, deg in in_degree.items() if deg == 0])

    while queue:
        wid = queue.popleft()
        ws = ws_map[wid]
        # Depth = 1 + max depth of all direct predecessors (0 if no deps).
        if ws["depends_on"]:
            depths[wid] = 1 + max(depths.get(dep, 0) for dep in ws["depends_on"])
        else:
            depths[wid] = 0

        # Unlock successors.
        for w in ws_objects:
            if wid in w["depends_on"]:
                in_degree[w["id"]] -= 1
                if in_degree[w["id"]] == 0:
                    queue.append(w["id"])

    # Defensive fallback: assign depth 0 to any ws not reached (should not happen).
    for w in ws_objects:
        if w["id"] not in depths:
            depths[w["id"]] = 0

    return depths


def topological_sort_ws(workstreams):
    """Return topologically sorted list of workstream IDs."""
    ws_map = {w["id"]: w for w in workstreams}
    in_degree = {w["id"]: 0 for w in workstreams}
    for w in workstreams:
        in_degree[w["id"]] = len(w["depends_on"])

    queue = deque([wid for wid, deg in in_degree.items() if deg == 0])
    result = []
    while queue:
        wid = queue.popleft()
        result.append(wid)
        for w in workstreams:
            if wid in w["depends_on"]:
                in_degree[w["id"]] -= 1
                if in_degree[w["id"]] == 0:
                    queue.append(w["id"])

    return result


# ---------------------------------------------------------------------------
# Per-task scope derivation from TASKS.md **Files:** lines
# ---------------------------------------------------------------------------

# Token-stripping regex: strips parenthesized annotation suffixes.
# Mirrors the scope-extractor rubric: \s*\([^)]*\) covers (new), (NEW),
# (MODIFY), (deleted), (renamed from ...), etc.
_ANNOTATION_RE = re.compile(r"\s*\([^)]*\)")


def _strip_token(raw: str) -> str:
    """Strip backticks and annotation suffixes from a single path token.

    Mirrors the scope-extractor rubric:
      - Strip parenthesized suffixes: (new), (NEW), (MODIFY), (deleted), ...
      - Strip all backtick characters (they may appear mid-token after suffix removal).
      - Strip leading/trailing whitespace.
    Returns the cleaned token (may be empty string if nothing remained).
    """
    token = raw.strip()
    # Strip annotation suffixes like (new), (NEW), (MODIFY), (deleted from ...)
    # Do this BEFORE stripping backticks so that "`path` (new)" → "`path`"
    token = _ANNOTATION_RE.sub("", token)
    # Strip all backtick characters (may appear at start/end after annotation removal)
    token = token.replace("`", "")
    return token.strip()


def parse_task_files(tasks_md_text: str) -> dict:
    """Parse TASKS.md text and return a mapping of task_id → list of path tokens.

    For each task block (## Tnnn heading), extract the **Files:** line and
    split it into comma-separated tokens, stripping backticks and annotation
    suffixes per the scope-extractor rubric.

    A task block with no parseable **Files:** line maps to an empty list.
    Never raises.

    Returns:
        dict[str, list[str]] — task_id → list of cleaned repo-relative path
        tokens (globs/brace-groups kept as-is per scope-extractor rules).
    """
    result = {}
    current_task = None

    for line in tasks_md_text.splitlines():
        # Detect task block headers: ## Tnnn or ### Tnnn
        m = re.match(r"^#{2,3}\s+(T\d+)", line.strip())
        if m:
            current_task = m.group(1)
            if current_task not in result:
                result[current_task] = []
            continue

        if current_task is None:
            continue

        # Detect **Files:** line
        files_m = re.match(r"^\*\*Files:\*\*\s*(.*)", line.strip())
        if files_m:
            raw_list = files_m.group(1)
            tokens = []
            for raw_token in raw_list.split(","):
                cleaned = _strip_token(raw_token)
                if cleaned:
                    tokens.append(cleaned)
            result[current_task] = tokens

    return result


def workstream_scope(ws_objects: list, task_files: dict) -> dict:
    """Derive per-workstream path sets from task→path mapping.

    For each workstream in ws_objects, union the path lists of all its member
    tasks (using task_files from parse_task_files). Tasks with no paths (empty
    list) contribute nothing. Tasks not found in task_files are silently
    skipped (contributes empty set).

    Returns:
        dict[str, set[str]] — ws_id → set of repo-relative path tokens.
    """
    result = {}
    for ws in ws_objects:
        ws_id = ws["id"]
        paths: set = set()
        for task_id in ws.get("tasks", []):
            paths.update(task_files.get(task_id, []))
        result[ws_id] = paths
    return result


# ---------------------------------------------------------------------------
# Mode: z-plan-split (MANIFEST.md + SHARED-CONCERNS.md)
# ---------------------------------------------------------------------------

def parse_manifest(manifest_path):
    """Parse MANIFEST.md YAML frontmatter and clusters table.
    
    Returns (metadata, clusters) where clusters is list of dicts:
        {id, name, scope, path, status}
    """
    text = Path(manifest_path).read_text()
    
    # Parse YAML frontmatter
    fm = {}
    if text.startswith("---"):
        _, fm_text, body = text.split("---", 2)
        for line in fm_text.strip().splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                fm[k.strip()] = v.strip()
    
    # Parse clusters table
    clusters = []
    in_table = False
    for line in text.splitlines():
        if line.startswith("| ID |"):
            in_table = True
            continue
        if in_table and line.startswith("|---"):
            continue
        if in_table and line.startswith("| C") and "|" in line[2:]:
            cells = [c.strip() for c in line.split("|")[1:-1]]
            if len(cells) >= 5:
                path = cells[3].rstrip("/") if len(cells) > 3 else ""
                clusters.append({
                    "id": cells[0],           # C1, C2, ...
                    "name": cells[1],          # cluster slug
                    "scope": cells[2] if len(cells) > 2 else "",
                    "path": path,
                    "status": cells[4] if len(cells) > 4 else "ready",
                })
        elif in_table and not line.startswith("|"):
            in_table = False
    
    return fm, clusters


def parse_shared_concerns(sc_path):
    """Parse SHARED-CONCERNS.md overlap blocks.
    
    Returns list of {file, workstreams, severity} dicts.
    """
    text = Path(sc_path).read_text()
    
    # Parse YAML frontmatter for overlap_count
    overlap_count = 0
    if text.startswith("---"):
        _, fm_text, body = text.split("---", 2)
        for line in fm_text.strip().splitlines():
            if line.startswith("overlap_count:"):
                try:
                    overlap_count = int(line.split(":")[1].strip())
                except ValueError:
                    pass
    
    if overlap_count == 0:
        return []
    
    overlaps = []
    current_overlap = None
    
    for line in text.splitlines():
        # Detect overlap headers: ## Overlap: `path`
        m = re.match(r"^##\s+Overlap:\s+`([^`]+)`", line)
        if m:
            if current_overlap:
                overlaps.append(current_overlap)
            current_overlap = {
                "file": m.group(1),
                "workstreams": [],
                "severity": "low",
            }
            continue
        
        # Detect "Touched by" entries
        if current_overlap and line.strip().startswith("-"):
            # Extract cluster name: "- C1 <name> (<tasks>)"
            m = re.match(r"-\s+(C\d+)", line.strip())
            if m:
                current_overlap["workstreams"].append(m.group(1))
        
        # Detect severity
        if current_overlap and "severity:" in line.lower():
            sev = line.split(":")[-1].strip().lower()
            if sev in ("high", "medium", "low"):
                current_overlap["severity"] = sev
    
    if current_overlap:
        overlaps.append(current_overlap)
    
    return overlaps


def derive_severity(file_path, workstream_count):
    """Derive severity from file path and workstream count."""
    basename = os.path.basename(file_path)
    
    if HIGH_SEVERITY_RE.match(file_path) or basename in HIGH_SEVERITY_NAMES:
        return "high"
    if MEDIUM_SEVERITY_RE.match(file_path) and workstream_count >= 3:
        return "medium"
    return "low"


def build_from_split(plan_dir):
    """Build workstreams.json from z-plan-split artifacts."""
    manifest_path = os.path.join(plan_dir, "MANIFEST.md")
    sc_path = os.path.join(plan_dir, "SHARED-CONCERNS.md")
    
    if not os.path.exists(manifest_path):
        raise FileNotFoundError(f"MANIFEST.md not found at {manifest_path}")
    
    fm, clusters = parse_manifest(manifest_path)
    sc_overlaps = parse_shared_concerns(sc_path) if os.path.exists(sc_path) else []
    
    # Build workstreams from clusters
    workstreams = []
    for i, cluster in enumerate(clusters):
        ws_id = f"ws-{i + 1}"
        workstreams.append({
            "id": ws_id,
            "status": "ready" if cluster["status"] == "ready" else "failed",
            "name": cluster.get("name", f"Cluster {cluster['id']}"),
            "path": cluster.get("path", ""),
            "tasks": [],  # To be filled from cluster TASKS.md
            "depends_on": [],   # V1: z-plan-split is sequential
            "parallel_group": None,  # Populated below via assign_ws_depths
        })
    
    # Build file_conflicts from SHARED-CONCERNS.md
    file_conflicts = []
    for overlap in sc_overlaps:
        ws_ids = []
        for cid in overlap["workstreams"]:
            # Map C1→ws-1, C2→ws-2
            try:
                idx = int(cid[1:]) - 1
                if 0 <= idx < len(workstreams):
                    ws_ids.append(workstreams[idx]["id"])
            except ValueError:
                pass
        
        if len(ws_ids) >= 2:
            file_conflicts.append({
                "file": overlap["file"],
                "workstreams": ws_ids,
                "severity": overlap.get(
                    "severity",
                    derive_severity(overlap["file"], len(ws_ids)),
                ),
            })
    
    # Build merge_order from MANIFEST run order
    merge_order = []
    in_run_order = False
    for line in Path(manifest_path).read_text().splitlines():
        if line.strip() == "## Run order":
            in_run_order = True
            continue
        if in_run_order and re.match(r"^\d+\.\s", line):
            # Parse: "1. C1 → C2 → C3 → shared"
            parts = re.findall(r"ws-\d+|C\d+", line)
            for part in parts:
                # Map cluster ID to workstream ID
                try:
                    if part.startswith("C"):
                        idx = int(part[1:]) - 1
                        if 0 <= idx < len(workstreams):
                            merge_order.append(workstreams[idx]["id"])
                    else:
                        merge_order.append(part)
                except ValueError:
                    pass
        elif in_run_order and not re.match(r"^\d+\.\s", line) and line.strip():
            in_run_order = False
    
    # Fallback: sequential by workstream ID
    if not merge_order:
        merge_order = [w["id"] for w in workstreams]
    
    partial_tree = fm.get("status") == "partial"

    # Assign parallel_group = f"level-{depth}" from workstream-level DAG depth.
    ws_depths = assign_ws_depths(workstreams)
    for ws in workstreams:
        ws["parallel_group"] = f"level-{ws_depths[ws['id']]}"

    return workstreams, file_conflicts, merge_order, partial_tree, False


# ---------------------------------------------------------------------------
# Mode: z-plan (flat TASKS.md)
# ---------------------------------------------------------------------------

def parse_tasks_md(tasks_path):
    """Parse TASKS.md to extract task IDs and Depends-on lines."""
    text = Path(tasks_path).read_text()
    
    task_ids = []
    deps = {}
    current_task = None
    
    for line in text.splitlines():
        m = re.match(r"^#{2,3}\s+(T\d+)", line.strip())
        if m:
            current_task = m.group(1)
            task_ids.append(current_task)
            if current_task not in deps:
                deps[current_task] = []
            continue
        
        if current_task and "**Depends on:**" in line:
            task_refs = re.findall(r"T\d+", line)
            deps[current_task].extend(task_refs)
    
    return task_ids, deps


def build_from_flat(plan_dir, slug):
    """Build workstreams.json from flat TASKS.md."""
    tasks_path = os.path.join(plan_dir, "TASKS.md")

    if not os.path.exists(tasks_path):
        raise FileNotFoundError(f"TASKS.md not found at {tasks_path}")

    tasks_md_text = Path(tasks_path).read_text()
    task_ids, deps = parse_tasks_md(tasks_path)

    try:
        ws_objects, merge_order = run_5rule_algorithm(task_ids, deps)
    except CycleError as e:
        # Emit minimal workstreams.json with partial_tree
        print(f"Cycle detected: {e}", file=sys.stderr)
        return [], [], [], True, False

    # Add path and status to each workstream.
    # parallel_group is already set by run_5rule_algorithm via assign_ws_depths.
    workstreams = []
    for ws in ws_objects:
        ws["status"] = "ready"
        # No trailing slash: schema (Workstream.path) and validate_workstreams() both
        # reject a trailing '/'. Emitting one here made build_workstreams_json() self-reject,
        # so --source z-plan always exited 2 (the unit tests call build_from_flat() directly,
        # below the validation layer, and never caught it).
        ws["path"] = f"z-harness/{slug}/{ws['id']}"
        workstreams.append(ws)

    # Derive file_conflicts from per-task **Files:** lines in TASKS.md.
    # INV-4 (fail-safe): if any task block has no parseable **Files:** line,
    # overlap detection would be blind — emit empty file_conflicts and set
    # scope_unknown=True rather than silently treating "no data" as "no conflicts".
    task_files = parse_task_files(tasks_md_text)
    scope_unknown = any(
        len(task_files.get(tid, [])) == 0
        for tid in task_ids
    )

    if scope_unknown:
        file_conflicts = []
    else:
        ws_scope = workstream_scope(ws_objects, task_files)
        # For each path touched by ≥2 workstreams, emit a conflict entry.
        path_to_ws: dict = defaultdict(list)
        for ws_id in sorted(ws_scope.keys()):
            for path in ws_scope[ws_id]:
                path_to_ws[path].append(ws_id)

        file_conflicts = []
        for path in sorted(path_to_ws.keys()):
            ws_ids = path_to_ws[path]
            if len(ws_ids) >= 2:
                file_conflicts.append({
                    "file": path,
                    "workstreams": sorted(ws_ids),
                    "severity": derive_severity(path, len(ws_ids)),
                })

    partial_tree = False

    return workstreams, file_conflicts, merge_order, partial_tree, scope_unknown


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def build_workstreams_json(slug, source, plan_dir):
    """Main entry point. Returns the full workstreams.json dict."""

    if not SLUG_RE.match(slug):
        raise ValidationError(
            f"Invalid slug '{slug}': must match ^[a-z0-9]+(-[a-z0-9]+)*$"
        )

    if source == "z-plan-split":
        workstreams, file_conflicts, merge_order, partial_tree, scope_unknown = (
            build_from_split(plan_dir)
        )
    elif source == "z-plan":
        workstreams, file_conflicts, merge_order, partial_tree, scope_unknown = (
            build_from_flat(plan_dir, slug)
        )
    else:
        raise ValueError(
            f"Unknown source '{source}'. Expected: z-plan-split or z-plan"
        )

    result = {
        "protocol": PROTOCOL,
        "slug": slug,
        "source": f"/{source}",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "partial_tree": partial_tree,
        "scope_unknown": scope_unknown,
        "workstreams": workstreams,
        "file_conflicts": file_conflicts,
        "merge_order": merge_order,
    }

    # Validate before writing
    validate_workstreams(workstreams, file_conflicts, merge_order)

    return result


def main():
    parser = argparse.ArgumentParser(
        description="Generate workstreams.json from z-harness plan artifacts"
    )
    parser.add_argument(
        "--slug", required=True,
        help="Plan slug (kebab-case)"
    )
    parser.add_argument(
        "--source", required=True,
        choices=["z-plan-split", "z-plan"],
        help="Plan type that produced the artifacts"
    )
    parser.add_argument(
        "--plan-dir",
        help="Plan directory (default: resolve from slug)"
    )
    args = parser.parse_args()
    
    if args.plan_dir:
        plan_dir = args.plan_dir
    else:
        # Resolve plan dir via plan-path.sh
        import subprocess
        try:
            result = subprocess.run(
                ["bash", "scripts/plan-path.sh", "resolve_plan_path", args.slug],
                capture_output=True, text=True, check=True,
            )
            plan_dir = result.stdout.strip()
        except Exception:
            plan_dir = os.path.join("z-harness", args.slug)
    
    if not os.path.isdir(plan_dir):
        print(f"Plan directory not found: {plan_dir}", file=sys.stderr)
        sys.exit(2)
    
    try:
        data = build_workstreams_json(args.slug, args.source, plan_dir)
    except ValidationError as e:
        print(f"Validation error: {e}", file=sys.stderr)
        sys.exit(2)
    except FileNotFoundError as e:
        print(f"Input not found: {e}", file=sys.stderr)
        sys.exit(2)
    except CycleError as e:
        print(f"Cycle detected: {e}", file=sys.stderr)
        sys.exit(2)
    
    # Atomic write
    output_path = os.path.join(plan_dir, "workstreams.json")
    tmp_path = output_path + ".tmp"
    
    with open(tmp_path, "w") as f:
        json.dump(data, f, indent=2)
        f.write("\n")
    
    os.rename(tmp_path, output_path)
    
    print(f"workstreams.json written to {output_path}")
    sys.exit(0)


if __name__ == "__main__":
    main()
