"""``/z-plan-split`` fanout logic for the session-watchdog daemon.

Purpose (T013, criterion #6): given a completed ``/z-plan-split`` root-slug's
plan directory, parse its ``MANIFEST.md`` ``## Clusters`` table and spawn one
uniquely-named ``zw-``-prefixed tmux session per ``ready`` cluster, recording
each spawned child as a new ``registry`` record with ``parent_id`` set to the
origin session's id and appended to the origin record's ``children`` list.

Real ``/z-plan-split`` MANIFEST.md shape (precheck-verified against live
examples): YAML frontmatter (``artifact``/``slug``/``status``/
``total_clusters``/``clusters_ready``) followed by a ``## Clusters`` markdown
table with columns ``ID | Name (slug) | Scope | Path | Status | Attempts |
Final status at``. Only ``status == "ready"`` rows are spawnable (a completed
split has every row ``ready``).

Design decisions:
- ``run_fanout`` takes ``origin_record`` as a caller-supplied mapping (the
  session invoking fanout) rather than resolving it itself — the daemon/CLI
  owns origin-session discovery; this module only appends children to it.
- Child records enter ``allocating`` before host creation and transition to
  ``registered`` only after creation returns successfully. Later lifecycle
  changes remain owned by daemon reconciliation (T014).
- ``transcript_path`` on a freshly spawned child is unknown at spawn time (the
  host CLI assigns its own session id / transcript file only after it boots
  inside the new tmux pane), so it is recorded as ``""`` — a later
  reconciliation pass populates it once known. This is a genuine data-not-yet-
  available gap, not a deferred-implementation shortcut.
- The spawned tmux session's command is parameterizable via
  ``command_for_cluster``; the default (``DEFAULT_HOST_CLI``) is a documented
  placeholder ("cd into the cluster dir, launch the host CLI by name") — no
  host-specific bootstrap logic beyond that default is hardcoded here.
- Every tmux call funnels through the injected ``new_session`` (default
  ``tmux_actuator.new_session``) with an explicit ``timeout`` — no new raw
  subprocess call is introduced in this module.

Concurrency (STYLE.md:P-006, T001): ``run_fanout`` first persists deterministic
``allocating`` records in one short fresh-read-under-lock mutation. It then
creates tmux resources with no lock held and promotes each successful child to
``registered`` through another minimal locked mutation. A crash during host
creation therefore leaves an adoptable/reapable identity without allowing a
slow tmux call to block daemon persistence. There is no non-persisting public
spawn path.

Non-scope (later levels own these): resolving the origin record for a given
root-slug (CLI concern, see ``cli.py``), reconciling child terminal states
(T014), and populating a spawned child's real ``transcript_path``/``host``
context once its own session boots.
"""

from __future__ import annotations

import re
import secrets
import shlex
import uuid
from pathlib import Path
from typing import Callable, Mapping, Sequence

from runtime.watchdog import registry, tmux_actuator

MANIFEST_FILENAME = "MANIFEST.md"
READY_STATUS = "ready"

DEFAULT_HOST_CLI: dict[str, str] = {
    "claude": "claude",
    "codex": "codex",
    "omp": "omp",
}
"""Placeholder host-CLI launch command per host id. INTENT: "a sensible
placeholder default like launching the host CLI in the cluster path is fine";
the real per-host bootstrap command is a caller/config concern a later level
can override via ``command_for_cluster``."""

_CLUSTERS_HEADING_RE = re.compile(r"^##\s*Clusters\s*$", re.MULTILINE)

_HEADER_PREFIXES: tuple[tuple[str, str], ...] = (
    ("id", "id"),
    ("name", "name"),
    ("scope", "scope"),
    ("path", "path"),
    ("status", "status"),
    ("attempts", "attempts"),
    ("final status", "final_status_at"),
)


class ManifestParseError(ValueError):
    """Raised when a MANIFEST.md's ``## Clusters`` table cannot be parsed.

    Hard-fail (STYLE.md:EH-001): a malformed manifest must surface, not
    silently yield an empty or partial cluster list.
    """


def _normalize_header(header: str) -> str:
    """Map one Clusters-table column header to a stable snake_case key.

    Matches by prefix (case-insensitive) against the documented column set
    (``ID | Name (slug) | Scope | Path | Status | Attempts | Final status
    at``); an unrecognized header falls back to a mechanical snake_case
    transliteration so an unexpected extra column never crashes the parse.
    """
    lowered = header.lower()
    for prefix, key in _HEADER_PREFIXES:
        if lowered.startswith(prefix):
            return key
    return re.sub(r"[^a-z0-9]+", "_", lowered).strip("_")


def parse_manifest(manifest_path: Path | str) -> list[dict[str, str]]:
    """Parse the ``## Clusters`` markdown table of a ``/z-plan-split`` MANIFEST.md.

    Args:
        manifest_path: Path to the ``MANIFEST.md`` file.

    Returns:
        One dict per cluster row, keyed by normalized column name (``id``,
        ``name``, ``scope``, ``path``, ``status``, ``attempts``,
        ``final_status_at``, plus any extra column normalized mechanically).
        An empty list if the table has a header but zero data rows.

    Raises:
        ManifestParseError: if no ``## Clusters`` heading is found, the table
            has no header/separator, or a data row's column count does not
            match the header's.
    """
    text = Path(manifest_path).read_text(encoding="utf-8")
    heading = _CLUSTERS_HEADING_RE.search(text)
    if heading is None:
        raise ManifestParseError(f"no '## Clusters' section found in {manifest_path}")

    table_lines: list[str] = []
    for line in text[heading.end():].splitlines():
        stripped = line.strip()
        if stripped.startswith("|"):
            table_lines.append(stripped)
        elif table_lines:
            break  # table ended at the first non-table line after it started

    if len(table_lines) < 2:  # need at least a header row + '---' separator row
        raise ManifestParseError(f"malformed or missing Clusters table in {manifest_path}")

    header_cells = [c.strip() for c in table_lines[0].strip("|").split("|")]
    keys = [_normalize_header(h) for h in header_cells]

    clusters: list[dict[str, str]] = []
    for row in table_lines[2:]:  # skip the header row and the '---' separator row
        cells = [c.strip() for c in row.strip("|").split("|")]
        if len(cells) != len(keys):
            raise ManifestParseError(
                f"row/column-count mismatch in {manifest_path}: {row!r}"
            )
        clusters.append(dict(zip(keys, cells)))
    return clusters


def spawnable_clusters(clusters: Sequence[Mapping[str, str]]) -> list[dict[str, str]]:
    """Return the subset of ``clusters`` whose ``status`` is ``"ready"``."""
    return [dict(c) for c in clusters if c.get("status") == READY_STATUS]


def _cluster_dir(plan_dir: Path, cluster: Mapping[str, str]) -> Path:
    """Resolve a cluster's directory from its MANIFEST ``path`` column.

    ``path`` is documented as relative to the plans root (``plan_dir``'s
    parent), matching real MANIFEST.md examples (e.g.
    ``parser-robustness/poly-intl-parse/`` when ``plan_dir`` is
    ``.../plans/parser-robustness``); an already-absolute ``path`` is used
    as-is.
    """
    raw = cluster.get("path", "")
    candidate = Path(raw)
    return candidate if candidate.is_absolute() else plan_dir.parent / candidate


def _default_command(host: str, cluster_dir: Path) -> str:
    """Build the default cluster-session bootstrap command: cd + launch the
    host CLI by name (see ``DEFAULT_HOST_CLI``)."""
    cli = DEFAULT_HOST_CLI.get(host, host)
    return f"cd {shlex.quote(str(cluster_dir))} && {cli}"


def _allocation_identity(origin_id: str, cluster: Mapping[str, str]) -> tuple[str, str]:
    """Return stable watchdog and host identities for one admitted cluster."""
    cluster_key = _allocation_key(cluster)
    allocation_uuid = uuid.uuid5(uuid.NAMESPACE_URL, f"z-harness:{origin_id}:{cluster_key}")
    return f"ws-{allocation_uuid}", allocation_uuid.hex[:16]


def _allocation_key(cluster: Mapping[str, str]) -> str:
    """Return the non-empty manifest identity used for durable allocation."""
    return cluster.get("id", "").strip() or cluster.get("name", "").strip()


def _build_allocations(
    plan_dir: Path,
    origin_record: Mapping[str, object],
    *,
    host: str | None,
    now: str | None,
) -> tuple[dict, list[tuple[dict[str, str], Path, dict, str]]]:
    """Build deterministic allocating records without creating host resources.

    Args:
        plan_dir: Root plan directory containing ``MANIFEST.md``.
        origin_record: Parent watchdog session record.
        host: Optional child host override.
        now: Optional deterministic timestamp.

    Returns:
        The updated parent and cluster/path/allocation tuples.

    Raises:
        ManifestParseError: if the manifest cannot be parsed.
        ValueError: if the resolved host is unsupported.
    """
    clusters = spawnable_clusters(parse_manifest(plan_dir / MANIFEST_FILENAME))
    allocation_keys = [_allocation_key(cluster) for cluster in clusters]
    if any(not key for key in allocation_keys):
        raise ValueError("allocation key must not be empty")
    if len(set(allocation_keys)) != len(allocation_keys):
        raise ValueError("allocation key must be unique within a manifest")
    origin_host = host or str(origin_record.get("host"))
    origin_id = str(origin_record.get("session_id"))
    root_slug = str(origin_record.get("slug"))
    origin = dict(origin_record)
    children_ids = list(origin.get("children", []))
    allocations: list[tuple[dict[str, str], Path, dict, str]] = []

    for cluster in clusters:
        cluster_name = cluster.get("name") or cluster.get("id") or "cluster"
        cluster_dir = _cluster_dir(plan_dir, cluster)
        session_id, resource_suffix = _allocation_identity(origin_id, cluster)
        tmux_name = registry.deterministic_tmux_name(
            f"{root_slug}-{cluster_name}", resource_suffix
        )
        report_capability = secrets.token_urlsafe(32)
        record = registry.new_session_record(
            slug=f"{root_slug}/{cluster_name}",
            plan_dir=str(cluster_dir),
            host=origin_host,
            tmux_target=tmux_name,
            transcript_path="",
            session_id=session_id,
            parent_id=origin_id,
            report_capability=report_capability,
            now=now,
        )
        record["state"] = "allocating"
        if session_id not in children_ids:
            children_ids.append(session_id)
        allocations.append((cluster, cluster_dir, record, report_capability))

    origin["children"] = children_ids
    return origin, allocations


_ALLOCATION_IDENTITY_FIELDS = (
    "session_id",
    "slug",
    "plan_dir",
    "host",
    "tmux_target",
    "parent_id",
)


def _same_allocation(existing: Mapping[str, object], intended: Mapping[str, object]) -> bool:
    """Return whether two records identify the same durable host allocation."""
    return all(existing.get(field) == intended.get(field)
               for field in _ALLOCATION_IDENTITY_FIELDS)


def run_fanout(
    plan_dir: Path | str,
    origin_record: Mapping[str, object],
    registry_path: Path | str,
    *,
    host: str | None = None,
    command_for_cluster: Callable[[Mapping[str, str], Path], str] | None = None,
    new_session: Callable[..., None] = tmux_actuator.new_session,
    timeout: float = tmux_actuator.DEFAULT_TIMEOUT_S,
    now: str | None = None,
) -> tuple[dict[str, dict], list[dict]]:
    """Durably allocate, spawn, and register fanout children. Hard-fail.

    Persists every deterministic child allocation before the first tmux call,
    then creates resources without the registry lock and promotes successful
    allocations to ``registered`` one at a time.

    Concurrency: every persistence step uses a fresh locked merge, so unrelated
    lifecycle sections and concurrent session transitions survive. Host calls
    remain outside the lock.

    Args:
        plan_dir: The completed ``/z-plan-split`` root-slug's directory.
        origin_record: The session record invoking fanout.
        registry_path: Path to ``sessions.json``.
        host: Child host override; defaults to the origin host.
        command_for_cluster: Optional cluster bootstrap command builder.
        new_session: Host creation callable compatible with tmux actuation.
        timeout: Explicit timeout passed to each host creation call.
        now: Timestamp override for deterministic tests.

    Returns:
        A ``(sessions, child_records)`` pair: the full post-write sessions
        mapping (``session_id`` -> record) and the addressed child records.

    Raises:
        ManifestParseError: if the manifest cannot be parsed.
        ValueError: if a resulting record fails ``registry.validate_record``.
        RuntimeError: if an existing allocation requires later reconciliation.
        tmux_actuator.TmuxTimeoutError / TmuxActuationError: propagated from
            host creation.
        OSError: on a registry write failure.
    """
    plan_dir = Path(plan_dir)
    updated_origin, allocations = _build_allocations(
        plan_dir, origin_record, host=host, now=now
    )
    origin_key = str(updated_origin["session_id"])
    allocating_records = [allocation[2] for allocation in allocations]
    new_child_ids = [str(child["session_id"]) for child in allocating_records]
    replay_ids: set[str] = set()

    def _merge(fresh: dict[str, dict]) -> None:
        pending_ids: list[str] = []
        for child in allocating_records:
            child_id = str(child["session_id"])
            existing = fresh.get(child_id)
            if existing is None:
                continue
            if not _same_allocation(existing, child):
                raise ValueError(f"conflicting allocation replay for {child_id}")
            if existing["state"] == "allocating":
                pending_ids.append(child_id)
            else:
                replay_ids.add(child_id)
        if pending_ids:
            raise RuntimeError(
                "allocation awaiting host reconciliation: " + ", ".join(pending_ids)
            )

        # Append the new children onto whatever origin record the fresh locked
        # re-read holds (preserving a concurrent poll's transition of the
        # origin) rather than overwriting it with the pre-spawn copy; fall back
        # to the spawned ``updated_origin`` only when the origin is not yet
        # persisted (first fanout).
        if origin_key in fresh:
            base = dict(fresh[origin_key])
            children = list(base.get("children", []))
            for cid in new_child_ids:
                if cid not in children:
                    children.append(cid)
            base["children"] = children
            fresh[origin_key] = base
        else:
            fresh[origin_key] = updated_origin
        for child in allocating_records:
            fresh.setdefault(str(child["session_id"]), child)

    # Allocation intent and deterministic tmux identity become authoritative
    # before the first host side effect. A crash from this point onward leaves
    # enough state for the later host-specific reconciler to adopt or reap.
    sessions = registry.locked_registry_update(registry_path, _merge)
    child_records: list[dict] = []
    origin_host = host or str(origin_record.get("host"))
    for cluster, cluster_dir, allocating, report_capability in allocations:
        child_id = str(allocating["session_id"])
        if child_id in replay_ids:
            child_records.append(sessions[child_id])
            continue
        command = (
            command_for_cluster(cluster, cluster_dir)
            if command_for_cluster is not None
            else _default_command(origin_host, cluster_dir)
        )
        bootstrap = " ".join((
            "env",
            f"Z_HARNESS_WATCHDOG_CHILD_ID={shlex.quote(child_id)}",
            "Z_HARNESS_WATCHDOG_CHILD_GENERATION="
            f"{shlex.quote(registry.child_generation(allocating))}",
            "Z_HARNESS_WATCHDOG_REPORT_CAPABILITY="
            f"{shlex.quote(report_capability)}",
            command,
        ))
        new_session(allocating["tmux_target"], bootstrap, timeout=timeout)

        def _mark_registered(fresh: dict[str, dict], session_id: str = child_id) -> None:
            current = fresh[session_id]
            if current["state"] == "allocating":
                fresh[session_id] = registry.transition(current, "registered", now=now)

        sessions = registry.locked_registry_update(registry_path, _mark_registered)
        child_records.append(sessions[child_id])
    return sessions, child_records
