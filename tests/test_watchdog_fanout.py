"""Tests for runtime/watchdog/fanout.py (/z-plan-split MANIFEST fanout spawn)
and the runtime/watchdog/cli.py seed wiring.

Coverage (T013 acceptance, criterion #6):
- ``parse_manifest`` parses a real-shaped MANIFEST.md ``## Clusters`` table
  (including non-``ready`` rows, which ``spawnable_clusters`` filters out);
- a fixture MANIFEST with N clusters, with ``tmux_actuator.new_session``
  mocked via the module's dependency-injection seam, produces N
  ``zw-``-prefixed child registry records with correct ``parent_id``/
  ``children`` linkage and no two children sharing a tmux name, persisted to
  ``sessions.json`` via ``run_fanout``;
- a malformed manifest (no ``## Clusters`` heading) raises
  ``ManifestParseError``;
- ``cli.build_parser`` wires the ``fanout <root-slug>`` subcommand;
- ``run_fanout`` spawns children while holding NO registry lock, so a
  concurrent daemon persist / SIGTERM flush is never blocked by the tmux calls
  (T-REV-001, MAJOR 2 — see
  ``test_run_fanout_does_not_hold_registry_lock_during_spawn``), and its final
  short locked merge preserves a fanout child against a concurrent daemon poll
  pass that persists a stale whole-file snapshot after the child was added
  (T-REV-001, MAJOR 1, the "no session record is lost" acceptance — see
  ``test_run_fanout_child_survives_concurrent_stale_snapshot_writer``).

Tests are hermetic (STYLE.md:T-004): all filesystem effects go under pytest's
``tmp_path`` fixture; no real tmux session is ever created (``new_session`` is
always a fake recorder, never the real ``tmux_actuator.new_session``).
"""

from __future__ import annotations

import fcntl
import hashlib
import os
import shlex
from pathlib import Path
from typing import Any

import pytest

from runtime.watchdog import cli, fanout, registry


# ── fixtures ──────────────────────────────────────────────────────────────────

def _manifest_text(rows: list[tuple[str, str, str, str, str]]) -> str:
    """Build a real-shaped MANIFEST.md body from ``(id, name, path, status,
    attempts)`` rows. Mirrors the real /z-plan-split output shape (frontmatter
    + '## Clusters' table + 'Final status at' column)."""
    header = (
        "---\n"
        "artifact: manifest\n"
        "slug: demo-plan\n"
        "generated_at: 2026-07-10T20:00:00Z\n"
        "command: /z-plan-split\n"
        "status: ready\n"
        f"total_clusters: {len(rows)}\n"
        f"clusters_ready: {sum(1 for r in rows if r[3] == 'ready')}\n"
        "---\n\n"
        "# MANIFEST — demo-plan\n\n"
        "Demo fanout fixture.\n\n"
        "## Clusters\n\n"
        "| ID | Name (slug) | Scope (one line) | Path | Status | Attempts | Final status at |\n"
        "|----|-------------|------------------|------|--------|----------|-----------------|\n"
    )
    lines = [
        f"| {cid} | {name} | demo scope | {path} | {status} | {attempts} | 2026-07-10T20:00:00Z |"
        for cid, name, path, status, attempts in rows
    ]
    footer = (
        "\n\n## Run order\n\n1. all clusters (parallel).\n\n"
        "## Shared concerns\n\nNone.\n"
    )
    return header + "\n".join(lines) + footer


def _write_manifest(plan_dir: Path, rows: list[tuple[str, str, str, str, str]]) -> Path:
    plan_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = plan_dir / fanout.MANIFEST_FILENAME
    manifest_path.write_text(_manifest_text(rows), encoding="utf-8")
    return manifest_path


def _origin_record(*, now: str = "2026-07-10T20:00:00Z") -> dict:
    return registry.new_session_record(
        slug="demo-plan",
        plan_dir="/plans/demo-plan",
        host="claude",
        tmux_target="zw-demo-plan-origin01",
        transcript_path="/transcripts/origin.jsonl",
        session_id="ws-origin-0000",
        now=now,
    )


class _RecordingNewSession:
    """Fake ``tmux_actuator.new_session``-shaped callable: never touches a
    real tmux, just records every call."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str | None, float]] = []

    def __call__(self, name: str, command: str | None = None, *, timeout: float) -> None:
        self.calls.append((name, command, timeout))


# ── parse_manifest ────────────────────────────────────────────────────────────

def test_parse_manifest_parses_real_shaped_clusters_table(tmp_path: Path) -> None:
    rows = [
        ("C1", "alpha", "demo-plan/alpha/", "ready", "1"),
        ("C2", "beta", "demo-plan/beta/", "ready", "1"),
        ("C3", "gamma", "demo-plan/gamma/", "pending", "0"),
    ]
    manifest_path = _write_manifest(tmp_path / "demo-plan", rows)

    clusters = fanout.parse_manifest(manifest_path)

    assert len(clusters) == 3
    assert clusters[0]["id"] == "C1"
    assert clusters[0]["name"] == "alpha"
    assert clusters[0]["path"] == "demo-plan/alpha/"
    assert clusters[0]["status"] == "ready"
    assert clusters[0]["attempts"] == "1"
    assert clusters[0]["final_status_at"] == "2026-07-10T20:00:00Z"
    assert clusters[2]["status"] == "pending"


def test_parse_manifest_missing_clusters_heading_raises(tmp_path: Path) -> None:
    manifest_path = tmp_path / "MANIFEST.md"
    manifest_path.write_text("---\nartifact: manifest\n---\n\n# MANIFEST\n\nNo clusters here.\n")

    with pytest.raises(fanout.ManifestParseError):
        fanout.parse_manifest(manifest_path)


def test_spawnable_clusters_filters_non_ready() -> None:
    clusters = [
        {"id": "C1", "status": "ready"},
        {"id": "C2", "status": "pending"},
        {"id": "C3", "status": "ready"},
    ]
    ready = fanout.spawnable_clusters(clusters)
    assert [c["id"] for c in ready] == ["C1", "C3"]


def test_spawn_children_compatibility_path_is_removed() -> None:
    assert not hasattr(fanout, "spawn_children")


# ── spawn_children / run_fanout: N clusters -> N children ────────────────────

def test_run_fanout_spawns_n_children_with_correct_linkage(tmp_path: Path) -> None:
    rows = [
        ("C1", "alpha", "demo-plan/alpha/", "ready", "1"),
        ("C2", "beta", "demo-plan/beta/", "ready", "1"),
        ("C3", "gamma", "demo-plan/gamma/", "ready", "1"),
    ]
    plan_dir = tmp_path / "plans" / "demo-plan"
    _write_manifest(plan_dir, rows)
    registry_path = tmp_path / "state" / "sessions.json"
    origin = _origin_record()
    new_session = _RecordingNewSession()

    sessions, child_records = fanout.run_fanout(
        plan_dir, origin, registry_path, new_session=new_session, timeout=3.0
    )

    # Exactly N children were spawned.
    assert len(child_records) == 3

    # Every child is zw-prefixed and matches a distinct new_session() call.
    tmux_names = {rec["tmux_target"] for rec in child_records}
    assert len(tmux_names) == 3  # no two children share a tmux name
    for name in tmux_names:
        assert name.startswith("zw-")
    assert {call[0] for call in new_session.calls} == tmux_names
    for _, _command, timeout in new_session.calls:
        assert timeout == 3.0  # explicit timeout propagated to every call

    # Correct parent_id / children linkage.
    origin_id = origin["session_id"]
    for rec in child_records:
        assert rec["parent_id"] == origin_id
    updated_origin = sessions[origin_id]
    child_ids = {rec["session_id"] for rec in child_records}
    assert set(updated_origin["children"]) == child_ids

    # Persisted correctly: reading the registry back reflects the same state.
    persisted = registry.read_registry(registry_path)
    assert set(persisted.keys()) == {origin_id} | child_ids
    for child_id in child_ids:
        registry.validate_record(persisted[child_id])
    registry.validate_record(persisted[origin_id])


def test_run_fanout_only_spawns_ready_clusters(tmp_path: Path) -> None:
    rows = [
        ("C1", "alpha", "demo-plan/alpha/", "ready", "1"),
        ("C2", "beta", "demo-plan/beta/", "pending", "0"),
    ]
    plan_dir = tmp_path / "plans" / "demo-plan"
    _write_manifest(plan_dir, rows)
    registry_path = tmp_path / "state" / "sessions.json"
    origin = _origin_record()
    new_session = _RecordingNewSession()

    _sessions, child_records = fanout.run_fanout(
        plan_dir, origin, registry_path, new_session=new_session
    )

    assert len(child_records) == 1
    assert child_records[0]["slug"].endswith("/alpha")


def test_run_fanout_replay_reuses_deterministic_child_identity(tmp_path: Path) -> None:
    """An exact replay addresses the same child and host resource."""
    rows = [("C1", "alpha", "demo-plan/alpha/", "ready", "1")]
    plan_dir = tmp_path / "plans" / "demo-plan"
    _write_manifest(plan_dir, rows)
    registry_path = tmp_path / "state" / "sessions.json"
    origin = _origin_record()

    sessions, first_children = fanout.run_fanout(
        plan_dir, origin, registry_path, new_session=_RecordingNewSession()
    )
    origin_id = origin["session_id"]
    updated_origin = sessions[origin_id]

    replay_recorder = _RecordingNewSession()
    sessions_2, second_children = fanout.run_fanout(
        plan_dir, updated_origin, registry_path, new_session=replay_recorder
    )

    assert second_children[0]["session_id"] == first_children[0]["session_id"]
    assert second_children[0]["tmux_target"] == first_children[0]["tmux_target"]
    assert sessions_2[origin_id]["children"] == [first_children[0]["session_id"]]
    assert replay_recorder.calls == []


def test_run_fanout_persists_allocating_and_leaves_replay_for_reconciler(
    tmp_path: Path,
) -> None:
    rows = [("C1", "alpha", "demo-plan/alpha/", "ready", "1")]
    plan_dir = tmp_path / "plans" / "demo-plan"
    _write_manifest(plan_dir, rows)
    registry_path = tmp_path / "state" / "sessions.json"
    origin = _origin_record()
    observed: list[tuple[str, str, list[str]]] = []

    def _crash_during_creation(
        name: str, command: str | None = None, *, timeout: float
    ) -> None:
        sessions = registry.read_registry(registry_path)
        children = sessions[origin["session_id"]]["children"]
        child = sessions[children[0]]
        observed.append((child["state"], child["tmux_target"], children))
        raise RuntimeError("simulated host-creation crash")

    with pytest.raises(RuntimeError, match="simulated host-creation crash"):
        fanout.run_fanout(
            plan_dir, origin, registry_path, new_session=_crash_during_creation
        )

    allocating = registry.read_registry(registry_path)
    child_id = allocating[origin["session_id"]]["children"][0]
    host_identity = allocating[child_id]["tmux_target"]
    assert observed == [("allocating", host_identity, [child_id])]

    recorder = _RecordingNewSession()
    with pytest.raises(RuntimeError, match="reconciliation"):
        fanout.run_fanout(plan_dir, origin, registry_path, new_session=recorder)

    assert recorder.calls == []
    assert registry.read_registry(registry_path)[child_id]["state"] == "allocating"


def test_run_fanout_does_not_respawn_after_post_creation_promotion_crash(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = [("C1", "alpha", "demo-plan/alpha/", "ready", "1")]
    plan_dir = tmp_path / "plans" / "demo-plan"
    _write_manifest(plan_dir, rows)
    registry_path = tmp_path / "state" / "sessions.json"
    real_update = registry.locked_registry_update
    update_count = 0

    def _crash_on_promotion(path: Path | str, mutate_fn: Any) -> dict[str, dict]:
        nonlocal update_count
        update_count += 1
        if update_count == 2:
            raise OSError("simulated promotion crash")
        return real_update(path, mutate_fn)

    first_recorder = _RecordingNewSession()
    monkeypatch.setattr(registry, "locked_registry_update", _crash_on_promotion)
    with pytest.raises(OSError, match="simulated promotion crash"):
        fanout.run_fanout(
            plan_dir, _origin_record(), registry_path, new_session=first_recorder
        )
    monkeypatch.setattr(registry, "locked_registry_update", real_update)

    assert len(first_recorder.calls) == 1
    replay_recorder = _RecordingNewSession()
    with pytest.raises(RuntimeError, match="reconciliation"):
        fanout.run_fanout(
            plan_dir, _origin_record(), registry_path, new_session=replay_recorder
        )
    assert replay_recorder.calls == []


def test_run_fanout_rejects_new_manifest_child_after_group_seal(tmp_path: Path) -> None:
    """Criterion #6: a sealed epoch rejects late fanout admission before spawn."""
    plan_dir = tmp_path / "plans" / "demo-plan"
    registry_path = tmp_path / "state" / "sessions.json"
    origin = _origin_record()
    _write_manifest(plan_dir, [("C1", "alpha", "demo-plan/alpha/", "ready", "1")])
    fanout.run_fanout(
        plan_dir, origin, registry_path, new_session=_RecordingNewSession()
    )
    registry.seal_group(
        registry_path, registry.group_id_for(str(origin["session_id"]))
    )
    _write_manifest(plan_dir, [
        ("C1", "alpha", "demo-plan/alpha/", "ready", "1"),
        ("C2", "beta", "demo-plan/beta/", "ready", "1"),
    ])
    recorder = _RecordingNewSession()
    with pytest.raises(registry.GroupAdmissionError, match="sealed"):
        fanout.run_fanout(plan_dir, origin, registry_path, new_session=recorder)
    assert recorder.calls == []
    assert len(registry.read_registry(registry_path)) == 2


@pytest.mark.parametrize(
    "rows",
    [
        [
            ("C1", "alpha", "demo-plan/alpha/", "ready", "1"),
            ("C1", "beta", "demo-plan/beta/", "ready", "1"),
        ],
        [("", "", "demo-plan/alpha/", "ready", "1")],
        [("   ", "   ", "demo-plan/alpha/", "ready", "1")],
    ],
)
def test_run_fanout_rejects_duplicate_or_empty_allocation_keys_before_persist(
    tmp_path: Path,
    rows: list[tuple[str, str, str, str, str]],
) -> None:
    plan_dir = tmp_path / "plans" / "demo-plan"
    _write_manifest(plan_dir, rows)
    registry_path = tmp_path / "state" / "sessions.json"
    recorder = _RecordingNewSession()

    with pytest.raises(ValueError, match="allocation key"):
        fanout.run_fanout(
            plan_dir, _origin_record(), registry_path, new_session=recorder
        )

    assert recorder.calls == []
    assert not registry_path.exists()


# ── run_fanout: concurrency discipline (T-REV-001) ───────────────────────────

def test_run_fanout_does_not_hold_registry_lock_during_spawn(tmp_path: Path) -> None:
    """The slow tmux ``new_session`` spawning runs with NO registry lock held
    (T-REV-001, reviewer MAJOR 2): a 15s-timeout tmux call per cluster must
    never block the daemon's registry persistence or its SIGTERM flush.

    Proof: from inside the injected ``new_session`` (i.e. while ``run_fanout``
    is mid-spawn), a NON-BLOCKING acquire of the registry's sidecar lock must
    succeed. If ``run_fanout`` still wrapped spawning in the lock (the v1
    behavior), this ``LOCK_NB`` acquire would raise ``BlockingIOError``.
    """
    rows = [("C1", "alpha", "demo-plan/alpha/", "ready", "1")]
    plan_dir = tmp_path / "plans" / "demo-plan"
    _write_manifest(plan_dir, rows)
    registry_path = tmp_path / "state" / "sessions.json"
    origin = _origin_record()
    registry.write_registry(registry_path, {origin["session_id"]: origin})

    lock_free_during_spawn: list[bool] = []

    def _new_session_probes_lock(
        name: str, command: str | None = None, *, timeout: float
    ) -> None:
        lock_file = Path(str(registry_path) + ".lock")
        lock_file.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(str(lock_file), os.O_CREAT | os.O_RDWR, 0o644)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)  # must NOT block
            lock_free_during_spawn.append(True)
            fcntl.flock(fd, fcntl.LOCK_UN)
        except BlockingIOError:
            lock_free_during_spawn.append(False)
        finally:
            os.close(fd)

    fanout.run_fanout(
        plan_dir, origin, registry_path, new_session=_new_session_probes_lock
    )

    assert lock_free_during_spawn == [True], (
        "run_fanout held the registry lock during spawn — the tmux calls can "
        "block a concurrent daemon persist / SIGTERM flush"
    )


def test_run_fanout_child_survives_concurrent_stale_snapshot_writer(
    tmp_path: Path,
) -> None:
    """A concurrent daemon poll pass persisting a stale whole-file snapshot
    cannot clobber a fanout child (T-REV-001, reviewer MAJOR 1 — the core
    acceptance: "no session record is lost").

    Real interleaving modeled: the poll pass reads its sessions snapshot
    UNLOCKED and early (before fanout runs), mutates the record it is polling,
    then persists AFTER fanout has already added its child. Because the poll's
    persist goes through ``registry.locked_registry_update`` (re-read fresh,
    merge only the records it changed), the fanout child that landed after the
    poll's stale read survives, and so does the poll's own transition — nothing
    is lost. A naive whole-file ``write_registry(stale_snapshot)`` here would
    drop the child; this test would fail in that case.
    """
    rows = [("C1", "alpha", "demo-plan/alpha/", "ready", "1")]
    plan_dir = tmp_path / "plans" / "demo-plan"
    _write_manifest(plan_dir, rows)
    registry_path = tmp_path / "state" / "sessions.json"

    origin = _origin_record()
    # A separate watched session the poll pass is transitioning this cycle.
    watched = registry.new_session_record(
        slug="watched-plan",
        plan_dir="/plans/watched-plan",
        host="claude",
        tmux_target="zw-watched-00000001",
        transcript_path="/transcripts/watched.jsonl",
        session_id="ws-watched-0000",
    )
    registry.write_registry(
        registry_path,
        {origin["session_id"]: origin, watched["session_id"]: watched},
    )

    # 1. The poll pass reads its snapshot UNLOCKED and early.
    poll_snapshot = registry.read_registry(registry_path)

    # 2. Fanout runs concurrently and adds its child + origin linkage.
    _sessions, child_records = fanout.run_fanout(
        plan_dir, origin, registry_path, new_session=_RecordingNewSession()
    )
    child_id = child_records[0]["session_id"]

    # 3. The poll pass now persists its own transition (watched -> needs_input)
    #    using the SAME locked-fresh-merge discipline poll.py uses: merge ONLY
    #    the record it changed onto a fresh locked re-read.
    changed_watched = registry.transition(
        poll_snapshot[watched["session_id"]], "needs_input",
        now="2026-07-10T20:05:00Z",
    )

    def _apply(fresh: dict) -> None:
        fresh[watched["session_id"]] = changed_watched

    registry.locked_registry_update(registry_path, _apply)

    persisted = registry.read_registry(registry_path)
    # The fanout child survives the poll's post-fanout persist (no record lost).
    assert child_id in persisted
    registry.validate_record(persisted[child_id])
    # The origin's freshly-added children linkage survives too.
    assert child_id in persisted[origin["session_id"]]["children"]
    # And the poll's own transition landed.
    assert persisted[watched["session_id"]]["state"] == "needs_input"


def test_default_command_uses_host_cli_and_cluster_dir(tmp_path: Path) -> None:
    rows = [("C1", "alpha", "demo-plan/alpha/", "ready", "1")]
    plan_dir = tmp_path / "plans" / "demo-plan"
    _write_manifest(plan_dir, rows)
    registry_path = tmp_path / "state" / "sessions.json"
    origin = _origin_record()
    new_session = _RecordingNewSession()

    fanout.run_fanout(plan_dir, origin, registry_path, new_session=new_session)

    _name, command, _timeout = new_session.calls[0]
    expected_dir = plan_dir.parent / "demo-plan" / "alpha"
    assert str(expected_dir) in command
    assert "claude" in command  # origin host is "claude"


def test_command_for_cluster_override_is_used(tmp_path: Path) -> None:
    rows = [("C1", "alpha", "demo-plan/alpha/", "ready", "1")]
    plan_dir = tmp_path / "plans" / "demo-plan"
    _write_manifest(plan_dir, rows)
    registry_path = tmp_path / "state" / "sessions.json"
    origin = _origin_record()
    new_session = _RecordingNewSession()
    calls: list[tuple[Any, Any]] = []

    def _custom(cluster: dict, cluster_dir: Path) -> str:
        calls.append((cluster["id"], cluster_dir))
        return "custom-command"

    fanout.run_fanout(
        plan_dir,
        origin,
        registry_path,
        new_session=new_session,
        command_for_cluster=_custom,
    )

    assert calls == [("C1", plan_dir.parent / "demo-plan" / "alpha")]
    assert new_session.calls[0][1].endswith(" custom-command")


def test_fanout_privately_provisions_capability_without_registry_disclosure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = [("C1", "alpha", "demo-plan/alpha/", "ready", "1")]
    plan_dir = tmp_path / "plans" / "demo-plan"
    _write_manifest(plan_dir, rows)
    registry_path = tmp_path / "state" / "sessions.json"
    new_session = _RecordingNewSession()
    secret = "capability with ' quote and $(command)"
    monkeypatch.setattr(fanout.secrets, "token_urlsafe", lambda _size: secret)

    _sessions, children = fanout.run_fanout(
        plan_dir, _origin_record(), registry_path, new_session=new_session
    )

    child = children[0]
    argv = shlex.split(new_session.calls[0][1])
    provisioned = dict(part.split("=", 1) for part in argv[1:4])
    capability = provisioned["Z_HARNESS_WATCHDOG_REPORT_CAPABILITY"]
    assert capability == secret
    assert provisioned["Z_HARNESS_WATCHDOG_CHILD_ID"] == child["session_id"]
    assert provisioned["Z_HARNESS_WATCHDOG_CHILD_GENERATION"] == registry.child_generation(child)
    assert child["supervision"] == {
        "schema_version": registry.CHILD_SUPERVISION_SCHEMA_VERSION,
        "report_capability_sha256": hashlib.sha256(capability.encode()).hexdigest(),
        "lease_timeout_s": registry.DEFAULT_CHILD_LEASE_TIMEOUT_S,
        "grace_s": registry.DEFAULT_CHILD_GRACE_S,
        "resolution_window_s": registry.DEFAULT_CHILD_RESOLUTION_WINDOW_S,
    }
    assert capability not in registry_path.read_text(encoding="utf-8")
    with pytest.raises(registry.UnauthorizedChildReporterError):
        registry.report_child_outcome(
            registry_path,
            child_id=child["session_id"],
            generation=registry.child_generation(child),
            reporter_id=child["session_id"],
            report_capability=child["supervision"]["report_capability_sha256"],
            state="done",
            evidence={"artifact": "RESULT.json"},
        )


# ── cli.py seed wiring ────────────────────────────────────────────────────────

def test_cli_build_parser_wires_fanout_subcommand() -> None:
    parser = cli.build_parser()
    args = parser.parse_args(["fanout", "demo-plan"])
    assert args.root_slug == "demo-plan"
    assert args.func is cli.cmd_fanout
    assert args.registry_path == str(cli.DEFAULT_REGISTRY_PATH)


def test_cli_find_origin_record_matches_root_and_no_parent() -> None:
    origin = _origin_record()
    child = registry.new_session_record(
        slug="demo-plan/alpha",
        plan_dir="/plans/demo-plan/alpha",
        host="claude",
        tmux_target="zw-demo-plan-alpha-abcd1234",
        transcript_path="",
        parent_id=origin["session_id"],
    )
    sessions = {origin["session_id"]: origin, child["session_id"]: child}

    found = cli.find_origin_record(sessions, "demo-plan")
    assert found["session_id"] == origin["session_id"]


def test_cli_find_origin_record_raises_when_absent() -> None:
    with pytest.raises(cli.CliError):
        cli.find_origin_record({}, "no-such-slug")


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
