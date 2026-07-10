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
- ``spawn_children`` takes ``origin_record`` as a caller-supplied mapping (the
  session invoking fanout) rather than resolving it itself — the daemon/CLI
  owns origin-session discovery; this module only appends children to it.
- Child records are left in their freshly-minted ``registered`` state
  (``registry.new_session_record``'s initial value) — fanout does not invent
  lifecycle transitions; the daemon/reconcile owns child-state changes (T014).
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

Non-scope (later levels own these): resolving the origin record for a given
root-slug (CLI concern, see ``cli.py``), reconciling child terminal states
(T014), and populating a spawned child's real ``transcript_path``/``host``
context once its own session boots.
"""

from __future__ import annotations

import re
import shlex
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


def spawn_children(
    plan_dir: Path | str,
    origin_record: Mapping[str, object],
    *,
    host: str | None = None,
    command_for_cluster: Callable[[Mapping[str, str], Path], str] | None = None,
    new_session: Callable[..., None] = tmux_actuator.new_session,
    timeout: float = tmux_actuator.DEFAULT_TIMEOUT_S,
    now: str | None = None,
) -> tuple[dict, list[dict]]:
    """Spawn one tmux session + registry record per ready MANIFEST cluster.

    Reads ``<plan_dir>/MANIFEST.md``, spawns a ``zw-``-prefixed tmux session
    per ``ready`` cluster via ``new_session`` (explicit ``timeout``), and
    builds a fresh ``registry`` record per child with ``parent_id`` set to
    ``origin_record``'s ``session_id``. Does NOT persist anything — callers
    write the result via ``registry.write_registry`` (see ``run_fanout``).

    Args:
        plan_dir: The completed ``/z-plan-split`` root-slug's directory.
        origin_record: The session record invoking fanout (not mutated).
        host: Host to register children under; defaults to
            ``origin_record["host"]``.
        command_for_cluster: Optional ``(cluster, cluster_dir) -> command``
            override for the tmux bootstrap command; defaults to
            ``_default_command``.
        new_session: Injected ``tmux_actuator.new_session``-shaped callable.
        timeout: Explicit subprocess timeout passed to every ``new_session``
            call.
        now: ISO timestamp override (deterministic tests).

    Returns:
        A ``(updated_origin_record, child_records)`` pair: a copy of
        ``origin_record`` with each new child's id appended to ``children``,
        and the list of freshly-minted child records (each schema-valid per
        ``registry.validate_record``).

    Raises:
        ManifestParseError: if the MANIFEST.md's Clusters table is malformed.
        tmux_actuator.TmuxTimeoutError / TmuxActuationError: propagated from
            a failed ``new_session`` call.
    """
    plan_dir = Path(plan_dir)
    clusters = spawnable_clusters(parse_manifest(plan_dir / MANIFEST_FILENAME))

    origin_host = host or str(origin_record.get("host"))
    origin_id = origin_record.get("session_id")
    root_slug = str(origin_record.get("slug"))

    origin = dict(origin_record)
    children_ids = list(origin.get("children", []))
    child_records: list[dict] = []
    seen_tmux_names: set[str] = set()

    for cluster in clusters:
        cluster_name = cluster.get("name") or cluster.get("id") or "cluster"
        cluster_dir = _cluster_dir(plan_dir, cluster)

        tmux_name = registry.new_tmux_name(f"{root_slug}-{cluster_name}")
        while tmux_name in seen_tmux_names:  # pragma: no cover — uuid4 collision is
            # astronomically unlikely; guard kept cheap and correct regardless.
            tmux_name = registry.new_tmux_name(f"{root_slug}-{cluster_name}")
        seen_tmux_names.add(tmux_name)

        command = (
            command_for_cluster(cluster, cluster_dir)
            if command_for_cluster is not None
            else _default_command(origin_host, cluster_dir)
        )
        new_session(tmux_name, command, timeout=timeout)

        record = registry.new_session_record(
            slug=f"{root_slug}/{cluster_name}",
            plan_dir=str(cluster_dir),
            host=origin_host,
            tmux_target=tmux_name,
            transcript_path="",
            parent_id=origin_id,
            now=now,
        )
        children_ids.append(record["session_id"])
        child_records.append(record)

    origin["children"] = children_ids
    return origin, child_records


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
    """Spawn fanout children and persist the updated registry. Hard-fail.

    Reads the existing registry at ``registry_path`` (``registry.read_registry``,
    best-effort — an absent registry reads as ``{}``), calls ``spawn_children``,
    merges the updated origin record and every new child record into the
    sessions mapping, then persists via ``registry.write_registry`` (schema
    validation + atomic write).

    Args:
        plan_dir: The completed ``/z-plan-split`` root-slug's directory.
        origin_record: The session record invoking fanout.
        registry_path: Path to ``sessions.json``.
        host, command_for_cluster, new_session, timeout, now: see
            ``spawn_children``.

    Returns:
        A ``(sessions, child_records)`` pair: the full post-write sessions
        mapping (``session_id`` -> record) and the list of newly spawned
        child records.

    Raises:
        ManifestParseError: see ``spawn_children``.
        ValueError: if a resulting record fails ``registry.validate_record``.
        OSError: on a registry write failure.
    """
    sessions = registry.read_registry(registry_path)
    updated_origin, child_records = spawn_children(
        plan_dir,
        origin_record,
        host=host,
        command_for_cluster=command_for_cluster,
        new_session=new_session,
        timeout=timeout,
        now=now,
    )
    sessions[str(updated_origin["session_id"])] = updated_origin
    for child in child_records:
        sessions[str(child["session_id"])] = child
    registry.write_registry(registry_path, sessions)
    return sessions, child_records
