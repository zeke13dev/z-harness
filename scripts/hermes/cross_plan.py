"""
cross_plan.py — Cross-plan scope analysis, conflict-graph builder, and locking helpers.

Public API:
    plan_scope(slug, *, registry_records=None, plan_dir=None)
        -> tuple[set[str], bool]
    build_plan_conflict_graph(slugs, *, registry_records=None)
        -> dict[str, set[str]]
    acquire_plan_locks(slugs, *, session_id, run_id, acquire_fn=None)
        -> tuple[bool, list[str]]
    release_plan_locks(slugs, *, session_id, run_id, release_fn=None)
        -> None
    schedule_batches(slugs, graph)
        -> list[list[str]]

No side effects at import. Pure Python, no asyncio.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Callable, Optional


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_LOW_CONFIDENCE = {"broad", "unknown"}


def _fetch_registry_records() -> list[dict]:
    """Call active-plan-registry.py list --json; return parsed records.

    On any failure returns [] so callers treat all plans as fail-safe.
    """
    try:
        r = subprocess.run(
            ["python3", "scripts/active-plan-registry.py", "list", "--json"],
            capture_output=True,
            text=True,
            check=True,
        )
        return json.loads(r.stdout)
    except (subprocess.CalledProcessError, json.JSONDecodeError, OSError):
        return []


def _resolve_plan_dir(slug: str) -> Optional[str]:
    """Resolve a plan dir via scripts/plan-path.sh, mirroring hermes-execute.py."""
    try:
        r = subprocess.run(
            ["bash", "scripts/plan-path.sh", "resolve_plan_path", slug],
            capture_output=True,
            text=True,
            check=True,
        )
        path = r.stdout.strip()
        if path:
            return path
    except (subprocess.CalledProcessError, OSError):
        pass
    legacy = Path("z-harness") / slug
    if legacy.exists():
        return str(legacy)
    return None


def _read_workstreams_scope(plan_dir: str) -> tuple[set[str], bool]:
    """Read file_conflicts paths and scope_unknown from workstreams.json.

    Returns (paths_set, scope_unknown).  On missing/invalid file, returns
    (empty set, False) — caller combines with the registry-record check to
    determine overall fail-safe status.
    """
    ws_path = os.path.join(plan_dir, "workstreams.json")
    try:
        with open(ws_path) as f:
            data = json.load(f)
        scope_unknown: bool = bool(data.get("scope_unknown", False))
        paths: set[str] = set()
        for fc in data.get("file_conflicts", []):
            raw = fc.get("file", "")
            if raw:
                paths.add(os.path.normpath(raw))
        return paths, scope_unknown
    except (OSError, json.JSONDecodeError, KeyError):
        return set(), False


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def plan_scope(
    slug: str,
    *,
    registry_records: Optional[list[dict]] = None,
    plan_dir: Optional[str] = None,
) -> tuple[set[str], bool]:
    """Return (paths, fail_safe_flag) for a plan.

    paths:         union of registry scope paths and workstreams.json
                   file_conflicts paths (both normalized via os.path.normpath).
    fail_safe_flag (True => treat as conflicting with everything):
      - no registry record for the slug AND no workstreams.json scope, OR
      - workstreams.json has scope_unknown == true, OR
      - registry scope contains a low-confidence entry (broad/unknown).
    """
    if registry_records is None:
        registry_records = _fetch_registry_records()

    # Find this slug's registry record (if any).
    record: Optional[dict] = None
    for rec in registry_records:
        if rec.get("slug") == slug:
            record = rec
            break

    # Registry scope paths.
    reg_paths: set[str] = set()
    has_low_confidence = False
    if record is not None:
        for entry in record.get("scope", []):
            raw = entry.get("path", "")
            if raw:
                reg_paths.add(os.path.normpath(raw))
            conf = entry.get("confidence", "unknown")
            if conf in _LOW_CONFIDENCE:
                has_low_confidence = True

    # Workstreams.json scope.
    resolved_dir = plan_dir or _resolve_plan_dir(slug)
    if resolved_dir is not None:
        ws_paths, ws_scope_unknown = _read_workstreams_scope(resolved_dir)
    else:
        ws_paths, ws_scope_unknown = set(), False

    # Combined path set.
    all_paths = reg_paths | ws_paths

    # Fail-safe flag computation.
    no_registry = record is None
    no_ws_scope = len(ws_paths) == 0
    fail_safe = (
        (no_registry and no_ws_scope)
        or ws_scope_unknown
        or has_low_confidence
    )

    return all_paths, fail_safe


def build_plan_conflict_graph(
    slugs: list[str],
    *,
    registry_records: Optional[list[dict]] = None,
) -> dict[str, set[str]]:
    """Return an adjacency map slug -> set(conflicting slugs).

    Two plans A and B conflict iff:
      - their scope path sets intersect, OR
      - either A or B has the fail-safe flag (scope_unknown / low-confidence /
        missing registry record with no workstreams scope).

    No self-edges. Result is symmetric.
    """
    if registry_records is None:
        registry_records = _fetch_registry_records()

    # Compute scope for every slug once.
    scopes: dict[str, tuple[set[str], bool]] = {}
    for slug in slugs:
        scopes[slug] = plan_scope(slug, registry_records=registry_records)

    # Build adjacency map.
    graph: dict[str, set[str]] = {slug: set() for slug in slugs}

    for i, a in enumerate(slugs):
        for b in slugs[i + 1:]:
            paths_a, fail_a = scopes[a]
            paths_b, fail_b = scopes[b]

            conflict = (
                fail_a
                or fail_b
                or bool(paths_a & paths_b)
            )
            if conflict:
                graph[a].add(b)
                graph[b].add(a)

    return graph


# ---------------------------------------------------------------------------
# Locking helpers
# ---------------------------------------------------------------------------

def _default_acquire_fn(slug: str, *, session_id: str, run_id: str) -> bool:
    """Default acquire: call plan-claim.sh acquire for the given slug."""
    try:
        result = subprocess.run(
            [
                "bash", "scripts/plan-claim.sh", "acquire",
                "--slug", slug,
                "--run-id", run_id,
                "--session", session_id,
                "--command", "/hermes-execute",
            ],
            capture_output=True,
            text=True,
        )
        return result.returncode == 0
    except (subprocess.SubprocessError, OSError):
        return False


def _default_release_fn(slug: str, *, session_id: str, run_id: str) -> None:
    """Default release: call plan-claim.sh release for the given slug."""
    try:
        subprocess.run(
            [
                "bash", "scripts/plan-claim.sh", "release",
                "--slug", slug,
                "--run-id", run_id,
                "--session", session_id,
                "--command", "/hermes-execute",
            ],
            capture_output=True,
            text=True,
        )
    except (subprocess.SubprocessError, OSError):
        pass


def acquire_plan_locks(
    slugs: list[str],
    *,
    session_id: str,
    run_id: str,
    acquire_fn: Optional[Callable[[str], bool]] = None,
    release_fn: Optional[Callable[[str], None]] = None,
) -> tuple[bool, list[str]]:
    """Acquire plan-claim.sh locks for slugs in SORTED ascending order.

    Acquiring in sorted order is the deadlock-safety property: two orchestrators
    acquiring {a,b} both go a-then-b, so no AB/BA deadlock is possible.

    Returns (all_acquired, acquired_slugs).  On ANY failure, releases everything
    already acquired (in reverse sorted order) and returns (False, []).

    acquire_fn(slug) -> bool: defaults to subprocess call to plan-claim.sh acquire.
    release_fn(slug) -> None: defaults to subprocess call to plan-claim.sh release.
      Pass these to inject test doubles without real locks or subprocesses.
    """
    if acquire_fn is None:
        def acquire_fn(slug: str) -> bool:
            return _default_acquire_fn(slug, session_id=session_id, run_id=run_id)

    if release_fn is None:
        def release_fn(slug: str) -> None:
            _default_release_fn(slug, session_id=session_id, run_id=run_id)

    # Acquire in sorted ascending order — the deadlock-safety invariant.
    ordered = sorted(slugs)
    acquired: list[str] = []

    for slug in ordered:
        ok = acquire_fn(slug)
        if ok:
            acquired.append(slug)
        else:
            # Failure: release all already-acquired locks in reverse sorted order.
            for held in reversed(acquired):
                try:
                    release_fn(held)
                except Exception:
                    pass
            return False, []

    return True, acquired


def release_plan_locks(
    slugs: list[str],
    *,
    session_id: str,
    run_id: str,
    release_fn: Optional[Callable[[str], None]] = None,
) -> None:
    """Release locks for the given slugs (best-effort, never raises).

    release_fn(slug) -> None: defaults to subprocess call to plan-claim.sh release.
    """
    if release_fn is None:
        def release_fn(slug: str) -> None:
            _default_release_fn(slug, session_id=session_id, run_id=run_id)

    for slug in slugs:
        try:
            release_fn(slug)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Batch scheduling helper
# ---------------------------------------------------------------------------

def schedule_batches(
    slugs: list[str],
    graph: dict[str, set[str]],
) -> list[list[str]]:
    """Partition slugs into conflict-free batches via greedy graph-coloring.

    Iterates slugs in sorted order (determinism guarantee). Each slug is placed
    in the first batch that contains no conflicting peer (per graph). If no
    such batch exists a new batch is started.

    Returns a list of batches; plans within a batch are mutually conflict-free
    (safe to run concurrently), batches run in order (serial between batches).
    This mirrors the within-plan partition_level approach from hermes-execute.py.

    Invariant: no two slugs in the same batch are connected by an edge in graph.
    """
    batches: list[list[str]] = []

    for slug in sorted(slugs):
        placed = False
        for batch in batches:
            # Check if this slug conflicts with any member of the batch.
            has_conflict = any(
                member in graph.get(slug, set())
                for member in batch
            )
            if not has_conflict:
                batch.append(slug)
                placed = True
                break
        if not placed:
            batches.append([slug])

    return batches
