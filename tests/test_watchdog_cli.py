"""Tests for runtime/watchdog/cli.py's ``status`` and ``run [--once]`` verbs
(T019, criterion #1).

Coverage:
- ``build_parser`` wires both new subcommands with the documented flags and
  path defaults;
- ``select_adapter`` maps each ``VALID_HOSTS`` value to the correct
  ``HostAdapter`` subclass, and hard-fails (``CliError``) on an unknown host;
- ``cmd_status`` prints one line per registered session plus a heartbeat-age
  line, rendering ``"unknown"`` when the heartbeat file is absent and a
  numeric age when present;
- ``cmd_run`` with ``--once``: acquires+releases the single-instance lock,
  dispatches the injected ``poll_session`` exactly once per non-terminal
  registered session with the record's host-matched adapter and captured
  pane, does not publish standing readiness, exits 0, and never loops;
- ``cmd_run`` skips a terminal-state session (no capture/dispatch) and
  survives one session's pane-capture failure without blocking its sibling;
- a live single-instance lock makes ``cmd_run`` exit 1 with an error message
  rather than raising or hanging.

Tests inject every collaborator explicitly (``has_session``/``alert_fn``/
``get_config_int``/``capture_pane``/``poll_session``) via ``cmd_run``'s own
keyword-only DI seam — mirroring every composed module's DI-seam discipline
(STYLE.md:T-002) — so no test touches a real tmux pane, provider CLI,
webhook, or ``scripts/config.py`` subprocess. Tests are hermetic
(STYLE.md:T-004): all filesystem effects go under pytest's ``tmp_path``
fixture.
"""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from runtime.watchdog import cli, daemon, notify, planning_ingress, registry, tmux_actuator
from runtime.watchdog.adapters import ClaudeAdapter, CodexAdapter, OmpAdapter


def _outcome_child(registry_path: Path) -> dict:
    report_capability = "test-child-report-capability"
    parent = registry.new_session_record(
        "parent", "/plans/parent", "claude", "zw-parent", "/tmp/parent.jsonl",
        session_id="ws-parent", now="2026-07-14T10:00:00Z",
    )
    child = registry.new_session_record(
        "child", "/plans/child", "claude", "zw-child", "/tmp/child.jsonl",
        session_id="ws-child", parent_id=parent["session_id"],
        report_capability=report_capability,
        now="2026-07-14T10:00:00Z",
    )
    parent["children"] = [child["session_id"]]
    registry.write_registry(registry_path, {"ws-parent": parent, "ws-child": child})
    child["_report_capability"] = report_capability
    return child


def test_report_outcome_cli_is_versioned_and_notifies_after_commit(
    tmp_path: Path, capsys,
) -> None:
    registry_path = tmp_path / "sessions.json"
    child = _outcome_child(registry_path)
    seen = []

    def deliver(event):
        persisted = registry.read_registry_document(registry_path)
        assert persisted["sessions"][child["session_id"]]["state"] == "cancelled"
        seen.append(event)
        return notify.DeliveryResult(
            "failed", event.event_id, event.delivery_class
        )

    args = argparse.Namespace(
        schema_version=1, child_id=child["session_id"],
        generation=registry.child_generation(child), reporter_id=child["session_id"],
        report_capability=child["_report_capability"],
        state="cancelled", evidence_json='{"reason":"user_request"}',
        registry_path=str(registry_path),
    )
    assert cli.cmd_report_outcome(args, lifecycle_notify=deliver) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema_version"] == cli.CLI_SCHEMA_VERSION
    assert payload["result"]["state"] == "cancelled"
    assert payload["result"]["notification"]["status"] == "failed"
    assert len(seen) == 1

    assert cli.cmd_report_outcome(args, lifecycle_notify=deliver) == 0
    replay = json.loads(capsys.readouterr().out)
    assert replay["result"]["replayed"] is True
    assert replay["result"]["notification"]["status"] == "failed"
    assert len(seen) == 2
    assert seen[0].event_id == seen[1].event_id
    outcome = next(iter(registry.read_registry_document(registry_path)["outcomes"].values()))
    assert outcome["notification_status"] == "failed"
    assert outcome["notification_attempts"] == 2


def test_report_outcome_replay_recovers_commit_before_delivery_crash(
    tmp_path: Path, capsys,
) -> None:
    registry_path = tmp_path / "sessions.json"
    child = _outcome_child(registry_path)
    outcome, _ = registry.report_child_outcome(
        registry_path,
        child_id=child["session_id"],
        generation=registry.child_generation(child),
        reporter_id=child["session_id"],
        report_capability=child["_report_capability"],
        state="done",
        evidence={"artifact": "RESULT.json"},
    )
    committed = registry.read_registry_document(registry_path)["outcomes"][outcome["outcome_id"]]
    assert committed["notification_status"] == "pending"
    assert committed["notification_attempts"] == 0
    seen = []

    def deliver(event):
        seen.append(event)
        return notify.DeliveryResult("delivered", event.event_id, event.delivery_class)

    args = argparse.Namespace(
        schema_version=1,
        child_id=child["session_id"],
        generation=registry.child_generation(child),
        reporter_id=child["session_id"],
        report_capability=child["_report_capability"],
        state="done",
        evidence_json='{"artifact":"RESULT.json"}',
        registry_path=str(registry_path),
    )
    assert cli.cmd_report_outcome(args, lifecycle_notify=deliver) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["result"]["replayed"] is True
    assert payload["result"]["notification"]["status"] == "delivered"
    assert seen[0].event_id == notify.child_outcome_notification(outcome).event_id
    finished = registry.read_registry_document(registry_path)["outcomes"][outcome["outcome_id"]]
    assert finished["notification_status"] == "delivered"
    assert finished["notification_attempts"] == 1


def test_report_outcome_replay_recovers_crash_after_notification_claim(
    tmp_path: Path, capsys,
) -> None:
    registry_path = tmp_path / "sessions.json"
    child = _outcome_child(registry_path)
    outcome, _ = registry.report_child_outcome(
        registry_path,
        child_id=child["session_id"],
        generation=registry.child_generation(child),
        reporter_id=child["session_id"],
        report_capability=child["_report_capability"],
        state="failed",
        evidence={"exit_code": 1},
    )
    first_claim = registry.claim_child_outcome_notification(
        registry_path, str(outcome["outcome_id"])
    )
    assert first_claim is not None
    event_ids = []

    def deliver(event):
        event_ids.append(event.event_id)
        return notify.DeliveryResult("delivered", event.event_id, event.delivery_class)

    args = argparse.Namespace(
        schema_version=1,
        child_id=child["session_id"],
        generation=registry.child_generation(child),
        reporter_id=child["session_id"],
        report_capability=child["_report_capability"],
        state="failed",
        evidence_json='{"exit_code":1}',
        registry_path=str(registry_path),
    )
    assert cli.cmd_report_outcome(args, lifecycle_notify=deliver) == 0
    json.loads(capsys.readouterr().out)
    assert event_ids == [notify.child_outcome_notification(outcome).event_id]
    finished = registry.read_registry_document(registry_path)["outcomes"][outcome["outcome_id"]]
    assert finished["notification_status"] == "delivered"
    assert finished["notification_attempts"] == 2


def test_report_outcome_cli_rejects_stale_generation_without_mutation(
    tmp_path: Path, capsys,
) -> None:
    registry_path = tmp_path / "sessions.json"
    child = _outcome_child(registry_path)
    before = registry.read_registry_document(registry_path)

    exit_code = cli.main([
        "report-outcome", "--schema-version", "1",
        "--child-id", child["session_id"], "--generation", "stale",
        "--reporter-id", child["session_id"], "--state", "done",
        "--report-capability", child["_report_capability"],
        "--evidence-json", '{"artifact":"RESULT.json"}',
        "--registry-path", str(registry_path),
    ])

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 3
    assert payload["error"]["code"] == "stale_generation"
    assert registry.read_registry_document(registry_path) == before


def test_seal_and_ack_join_cli_return_versioned_generation_fenced_results(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Criterion #6 lifecycle verbs expose seal and exactly-once ack state."""
    registry_path = tmp_path / "sessions.json"
    child = _outcome_child(registry_path)

    def _arm(sessions: dict[str, dict]) -> None:
        parent_id = child["parent_id"]
        sessions[parent_id] = registry.transition(
            sessions[parent_id], "awaiting_children", now="2026-07-14T12:00:00Z"
        )

    registry.locked_registry_update(registry_path, _arm)
    group_id = registry.group_id_for(str(child["parent_id"]))
    assert cli.main([
        "seal-group", "--group-id", group_id, "--epoch", "1",
        "--registry-path", str(registry_path),
    ]) == 0
    sealed = json.loads(capsys.readouterr().out)
    assert sealed["schema_version"] == 1
    assert sealed["result"]["state"] == "sealed"

    registry.report_child_outcome(
        registry_path, child_id=child["session_id"],
        generation=registry.child_generation(child), reporter_id=child["session_id"],
        report_capability=child["_report_capability"], state="done",
        evidence={"artifact": "RESULT.json"},
    )
    outbox = next(iter(registry.read_registry_document(registry_path)["outbox"].values()))
    argv = [
        "ack-join", "--outbox-id", outbox["outbox_id"],
        "--coordinator-generation", outbox["coordinator_generation"],
        "--registry-path", str(registry_path),
    ]
    assert cli.main(argv) == 0
    first = json.loads(capsys.readouterr().out)
    assert cli.main(argv) == 0
    replay = json.loads(capsys.readouterr().out)
    assert first["result"]["replayed"] is False
    assert replay["result"]["replayed"] is True


def test_report_outcome_cli_rejects_spoofed_child_identity_without_capability(
    tmp_path: Path, capsys,
) -> None:
    registry_path = tmp_path / "sessions.json"
    child = _outcome_child(registry_path)
    before = registry.read_registry_document(registry_path)

    exit_code = cli.main([
        "report-outcome", "--schema-version", "1",
        "--child-id", child["session_id"],
        "--generation", registry.child_generation(child),
        "--reporter-id", child["session_id"],
        "--report-capability", "caller-supplied-spoof",
        "--state", "done", "--evidence-json", '{"artifact":"RESULT.json"}',
        "--registry-path", str(registry_path),
    ])

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 3
    assert payload["error"]["code"] == "unauthorized_reporter"
    assert registry.read_registry_document(registry_path) == before


# ── build_parser wiring ──────────────────────────────────────────────────────

def test_build_parser_wires_status_subcommand() -> None:
    parser = cli.build_parser()
    args = parser.parse_args(
        ["status", "--registry-path", "/r.json", "--heartbeat-path", "/hb"]
    )
    assert args.func is cli.cmd_status
    assert args.registry_path == "/r.json"
    assert args.heartbeat_path == "/hb"


def test_build_parser_status_uses_documented_defaults() -> None:
    parser = cli.build_parser()
    args = parser.parse_args(["status"])
    assert args.registry_path == str(cli.DEFAULT_REGISTRY_PATH)
    assert args.heartbeat_path == str(cli.DEFAULT_HEARTBEAT_PATH)


def test_build_parser_wires_run_subcommand_with_once_flag() -> None:
    parser = cli.build_parser()
    args = parser.parse_args(
        [
            "run", "--once",
            "--registry-path", "/r.json",
            "--lock-path", "/l.lock",
            "--heartbeat-path", "/hb",
            "--signals-path", "/s.jsonl",
        ]
    )
    assert args.func is cli.cmd_run
    assert args.once is True
    assert args.registry_path == "/r.json"
    assert args.lock_path == "/l.lock"
    assert args.heartbeat_path == "/hb"
    assert args.signals_path == "/s.jsonl"


def test_build_parser_run_once_defaults_to_false() -> None:
    parser = cli.build_parser()
    args = parser.parse_args(["run"])
    assert args.once is False
    assert args.lock_path == str(cli.DEFAULT_LOCK_PATH)
    assert args.signals_path == str(cli.DEFAULT_SIGNALS_PATH)


def test_build_parser_rejects_spoofable_managed_start_flag() -> None:
    parser = cli.build_parser()
    with pytest.raises(SystemExit) as exc_info:
        parser.parse_args(["run", "--managed-start"])
    assert exc_info.value.code == 2


# ── select_adapter ───────────────────────────────────────────────────────────

def test_select_adapter_maps_each_valid_host() -> None:
    assert isinstance(cli.select_adapter("claude"), ClaudeAdapter)
    assert isinstance(cli.select_adapter("codex"), CodexAdapter)
    assert isinstance(cli.select_adapter("omp"), OmpAdapter)


def test_select_adapter_raises_cli_error_for_unknown_host() -> None:
    with pytest.raises(cli.CliError):
        cli.select_adapter("not-a-real-host")


# ── cmd_status ───────────────────────────────────────────────────────────────

def _status_fixture_registry(registry_path: Path) -> dict[str, dict]:
    running = registry.new_session_record(
        slug="alpha", plan_dir="/p", host="claude",
        tmux_target="zw-alpha-1", transcript_path="/t-alpha.jsonl",
    )
    running = registry.transition(running, "running")
    sessions = {running["session_id"]: running}
    registry.write_registry(registry_path, sessions)
    return sessions


def test_cmd_status_prints_sessions_and_unknown_heartbeat(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    registry_path = tmp_path / "sessions.json"
    heartbeat_path = tmp_path / "heartbeat-absent"
    fixture = _status_fixture_registry(registry_path)

    args = argparse.Namespace(
        registry_path=str(registry_path), heartbeat_path=str(heartbeat_path)
    )
    rc = cli.cmd_status(args)

    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema_version"] == cli.CLI_SCHEMA_VERSION
    assert payload["ok"] is True
    assert payload["result"]["daemon"]["heartbeat_age_s"] is None
    session_id = next(iter(fixture))
    assert payload["result"]["sessions"] == [{
        "session_id": session_id,
        "slug": "alpha",
        "host": "claude",
        "state": "running",
        "tmux_target": "zw-alpha-1",
    }]


def test_cmd_status_prints_numeric_heartbeat_age_when_present(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    registry_path = tmp_path / "sessions.json"
    registry.write_registry(registry_path, {})
    heartbeat_path = tmp_path / "heartbeat"
    heartbeat_path.write_text("", encoding="utf-8")

    args = argparse.Namespace(
        registry_path=str(registry_path), heartbeat_path=str(heartbeat_path)
    )
    rc = cli.cmd_status(args)

    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["result"]["daemon"]["heartbeat_age_s"] >= 0


# ── cmd_run --once ───────────────────────────────────────────────────────────

class _RecordingCall:
    """Records every invocation and returns a canned value / calls a
    side-effect callable, mirroring poll's own test-stub shape."""

    def __init__(self, ret=None, side_effect=None) -> None:
        self.calls: list[tuple[tuple, dict]] = []
        self._ret = ret
        self._side_effect = side_effect

    def __call__(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        if self._side_effect is not None:
            return self._side_effect(*args, **kwargs)
        return self._ret


def _fake_poll_session(record, sessions, **kwargs):
    updated = dict(sessions)
    updated[record["session_id"]] = record
    return {"sessions": updated}


def _run_fixture(tmp_path: Path) -> tuple[argparse.Namespace, dict, dict]:
    registry_path = tmp_path / "sessions.json"
    lock_path = tmp_path / "daemon.lock"
    heartbeat_path = tmp_path / "heartbeat"
    signals_path = tmp_path / "signals.jsonl"

    claude_rec = registry.new_session_record(
        slug="alpha", plan_dir="/p", host="claude",
        tmux_target="zw-alpha-1", transcript_path="/t-alpha.jsonl",
    )
    claude_rec = registry.transition(claude_rec, "running")
    codex_rec = registry.new_session_record(
        slug="beta", plan_dir="/p", host="codex",
        tmux_target="zw-beta-1", transcript_path="/t-beta.jsonl",
    )
    codex_rec = registry.transition(codex_rec, "running")
    sessions = {claude_rec["session_id"]: claude_rec, codex_rec["session_id"]: codex_rec}
    registry.write_registry(registry_path, sessions)

    args = argparse.Namespace(
        registry_path=str(registry_path),
        lock_path=str(lock_path),
        heartbeat_path=str(heartbeat_path),
        signals_path=str(signals_path),
        once=True,
    )
    return args, claude_rec, codex_rec


def _run_once_kwargs(*, capture_pane=None, poll_session=None, get_config_int=None):
    return dict(
        has_session=lambda target, *, timeout: True,
        alert_fn=lambda title, body: True,
        get_config_int=get_config_int or (lambda key: 1),
        capture_pane=capture_pane or (lambda target, **kwargs: "pane text"),
        poll_session=poll_session or _fake_poll_session,
    )


def test_cmd_run_once_dispatches_poll_session_exactly_once_per_session(
    tmp_path: Path,
) -> None:
    args, claude_rec, codex_rec = _run_fixture(tmp_path)
    poll_session = _RecordingCall(side_effect=_fake_poll_session)

    rc = cli.cmd_run(args, **_run_once_kwargs(poll_session=poll_session))

    assert rc == 0
    assert len(poll_session.calls) == 2
    dispatched_ids = {call[0][0]["session_id"] for call in poll_session.calls}
    assert dispatched_ids == {claude_rec["session_id"], codex_rec["session_id"]}


def test_cmd_run_once_selects_correct_host_adapter_per_session(tmp_path: Path) -> None:
    args, claude_rec, codex_rec = _run_fixture(tmp_path)
    seen_adapters: dict[str, type] = {}

    def recording_poll_session(record, sessions, *, adapter, **kwargs):
        seen_adapters[record["session_id"]] = type(adapter)
        return _fake_poll_session(record, sessions, adapter=adapter, **kwargs)

    rc = cli.cmd_run(args, **_run_once_kwargs(poll_session=recording_poll_session))

    assert rc == 0
    assert seen_adapters[claude_rec["session_id"]] is ClaudeAdapter
    assert seen_adapters[codex_rec["session_id"]] is CodexAdapter


def test_cmd_run_once_never_loops_a_second_pass(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``--once`` must exit after exactly one pass — never sleep/repeat."""
    args, _claude_rec, _codex_rec = _run_fixture(tmp_path)
    poll_session = _RecordingCall(side_effect=_fake_poll_session)

    def _boom_sleep(seconds: float) -> None:
        raise AssertionError("run --once must never sleep/loop a second pass")

    monkeypatch.setattr(cli.time, "sleep", _boom_sleep)

    rc = cli.cmd_run(args, **_run_once_kwargs(poll_session=poll_session))

    assert rc == 0
    assert len(poll_session.calls) == 2  # exactly one dispatch per session, no repeat


def test_cmd_run_once_does_not_publish_readiness_and_releases_lock(tmp_path: Path) -> None:
    args, _claude_rec, _codex_rec = _run_fixture(tmp_path)

    rc = cli.cmd_run(args, **_run_once_kwargs())

    assert rc == 0
    assert not Path(args.heartbeat_path).exists()
    # Lock released: a fresh acquire attempt succeeds without raising.
    from runtime.watchdog import daemon

    with daemon.run_lifecycle(Path(args.lock_path)):
        pass


def test_cmd_run_once_skips_terminal_state_session(tmp_path: Path) -> None:
    args, claude_rec, codex_rec = _run_fixture(tmp_path)
    registry_path = Path(args.registry_path)
    sessions = registry.read_registry(registry_path)
    sessions[codex_rec["session_id"]] = registry.transition(codex_rec, "orphaned")
    registry.write_registry(registry_path, sessions)

    poll_session = _RecordingCall(side_effect=_fake_poll_session)

    rc = cli.cmd_run(args, **_run_once_kwargs(poll_session=poll_session))

    assert rc == 0
    dispatched_ids = {call[0][0]["session_id"] for call in poll_session.calls}
    assert dispatched_ids == {claude_rec["session_id"]}


def test_cmd_run_once_survives_one_session_pane_capture_failure(tmp_path: Path) -> None:
    args, claude_rec, codex_rec = _run_fixture(tmp_path)

    def flaky_capture_pane(target, **kwargs):
        if target == claude_rec["tmux_target"]:
            raise tmux_actuator.TmuxActuationError("no such pane")
        return "pane text"

    poll_session = _RecordingCall(side_effect=_fake_poll_session)

    rc = cli.cmd_run(
        args, **_run_once_kwargs(capture_pane=flaky_capture_pane, poll_session=poll_session)
    )

    assert rc == 0
    dispatched_ids = {call[0][0]["session_id"] for call in poll_session.calls}
    assert dispatched_ids == {codex_rec["session_id"]}


def test_cmd_run_exits_1_when_daemon_already_running(tmp_path: Path) -> None:
    from runtime.watchdog import daemon

    args, _claude_rec, _codex_rec = _run_fixture(tmp_path)
    lock_path = Path(args.lock_path)

    with daemon.run_lifecycle(lock_path):
        rc = cli.cmd_run(args, **_run_once_kwargs())

    assert rc == 1


# ── versioned root lifecycle contract ────────────────────────────────────────

def _json_result(capsys: pytest.CaptureFixture[str]) -> dict:
    return json.loads(capsys.readouterr().out)


def test_register_exact_replay_returns_same_durable_identity(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    manifest_path = planning_ingress.persist_supervision_manifest(
        tmp_path / "plan", "supervised"
    )
    registry_path = tmp_path / "sessions.json"
    argv = [
        "register", "--manifest-path", str(manifest_path),
        "--registry-path", str(registry_path),
    ]

    assert cli.main(argv) == 0
    first = _json_result(capsys)
    assert cli.main(argv) == 0
    replay = _json_result(capsys)

    assert first == {
        "schema_version": 1,
        "ok": True,
        "command": "register",
        "result": {
            "coordinator_id": first["result"]["coordinator_id"],
            "idempotency_key": first["result"]["idempotency_key"],
            "manifest_sha256": first["result"]["manifest_sha256"],
            "replayed": False,
            "state": "registered",
        },
    }
    assert replay["result"] == {**first["result"], "replayed": True}


def test_register_conflict_and_malformed_manifest_have_stable_json_errors(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    manifest_path = planning_ingress.persist_supervision_manifest(
        tmp_path / "plan", "supervised"
    )
    registry_path = tmp_path / "sessions.json"
    argv = [
        "register", "--manifest-path", str(manifest_path),
        "--registry-path", str(registry_path),
    ]
    assert cli.main(argv) == 0
    capsys.readouterr()

    normalized = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest_path.write_text(json.dumps({**normalized, "extra": True}), encoding="utf-8")
    assert cli.main(argv) == 2
    malformed_shape = _json_result(capsys)
    assert malformed_shape["error"]["code"] == "invalid_manifest"

    manifest_path.write_text(json.dumps(normalized), encoding="utf-8")
    assert cli.main(argv) == 0
    capsys.readouterr()
    normalized["topology"]["child_admission"] = "locked_dynamic"
    manifest_path.write_text(json.dumps(normalized), encoding="utf-8")
    assert cli.main(argv) == 3
    conflict = _json_result(capsys)
    assert conflict["error"]["code"] == "idempotency_conflict"


def test_register_malformed_coordinator_returns_versioned_json_error(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    manifest_path = planning_ingress.persist_supervision_manifest(
        tmp_path / "plan", "supervised"
    )
    registry_path = tmp_path / "sessions.json"
    argv = [
        "register", "--manifest-path", str(manifest_path),
        "--registry-path", str(registry_path),
    ]
    assert cli.main(argv) == 0
    capsys.readouterr()
    payload = json.loads(registry_path.read_text(encoding="utf-8"))
    entry = next(iter(payload["coordinators"].values()))
    del entry["coordinator_id"]
    registry_path.write_text(json.dumps(payload), encoding="utf-8")

    assert cli.main(argv) == 4
    result = _json_result(capsys)
    assert result["schema_version"] == cli.CLI_SCHEMA_VERSION
    assert result["ok"] is False
    assert result["error"]["code"] == "malformed_registry"


@pytest.mark.parametrize(
    "payload, code",
    [
        ({"schema_version": 999}, "unsupported_registry_version"),
        ({"schema_version": 1, "registry_version": 2}, "malformed_registry"),
    ],
)
def test_status_rejects_future_and_malformed_authority_as_json(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    payload: dict,
    code: str,
) -> None:
    registry_path = tmp_path / "sessions.json"
    registry_path.write_text(json.dumps(payload), encoding="utf-8")
    rc = cli.main(["status", "--registry-path", str(registry_path)])
    result = _json_result(capsys)
    assert rc == 4
    assert result["schema_version"] == 1
    assert result["ok"] is False
    assert result["error"]["code"] == code


def test_status_rejects_invalid_coordinator_key_as_json(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    registry_path = tmp_path / "sessions.json"
    registry.write_registry(registry_path, {})
    payload = json.loads(registry_path.read_text(encoding="utf-8"))
    payload["coordinators"]["invalid"] = {
        "registry_version": registry.REGISTRY_VERSION,
    }
    registry_path.write_text(json.dumps(payload), encoding="utf-8")

    assert cli.main(["status", "--registry-path", str(registry_path)]) == 4
    result = _json_result(capsys)
    assert result["schema_version"] == cli.CLI_SCHEMA_VERSION
    assert result["ok"] is False
    assert result["error"]["code"] == "malformed_registry"


def test_ensure_is_duplicate_safe_and_stop_never_rewrites_registry(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    registry_path = tmp_path / "sessions.json"
    manifest_path = planning_ingress.persist_supervision_manifest(
        tmp_path / "plan", "supervised"
    )
    registry.register_root_manifest(
        registry_path,
        idempotency_key=registry.root_idempotency_key(manifest_path),
        manifest=planning_ingress.load_opt_in_manifest(manifest_path),
    )
    before = registry_path.read_bytes()
    lock_path = tmp_path / "daemon.lock"
    lock_path.touch()
    held_fd: int | None = None
    spawn_calls: list[list[str]] = []
    spawn_kwargs: list[dict[str, object]] = []

    def fake_popen(argv: list[str], **kwargs: object) -> object:
        nonlocal held_fd
        spawn_calls.append(argv)
        spawn_kwargs.append(kwargs)
        held_fd = os.open(lock_path, os.O_RDWR)
        fcntl.flock(held_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        os.ftruncate(held_fd, 0)
        os.write(held_fd, b"4242\n")
        daemon.touch_heartbeat(args.heartbeat_path, "wd-test-incarnation-1")
        return object()

    args = argparse.Namespace(
        registry_path=str(registry_path),
        lock_path=str(lock_path),
        heartbeat_path=str(tmp_path / "heartbeat"),
        signals_path=str(tmp_path / "signals.jsonl"),
    )
    notifications = []

    def failed_notification(event):
        notifications.append(event)
        return notify.DeliveryResult(
            status="failed",
            event_id=event.event_id,
            delivery_class=event.delivery_class,
        )

    assert cli.cmd_ensure(
        args, popen=fake_popen, lifecycle_notify=failed_notification
    ) == 0
    first = _json_result(capsys)
    assert first["result"]["pid"] == 4242
    assert first["result"]["running"] is True
    assert first["result"]["started"] is True
    assert first["result"]["notification"]["status"] == "failed"
    assert first["result"]["notification"]["event_id"] == notifications[0].event_id
    assert cli.cmd_ensure(
        args, popen=fake_popen, lifecycle_notify=failed_notification
    ) == 0
    duplicate = _json_result(capsys)
    assert duplicate["result"] == {
        "pid": 4242,
        "running": True,
        "started": False,
        "notification": None,
    }
    assert len(spawn_calls) == 1
    assert "--managed-start" not in spawn_calls[0]
    inherited_fd = spawn_kwargs[0]["pass_fds"]
    assert inherited_fd == (int(spawn_kwargs[0]["env"][cli._MANAGED_START_FD_ENV]),)

    def fake_kill(pid: int, signum: int) -> None:
        nonlocal held_fd
        assert (pid, signum) == (4242, signal.SIGTERM)
        assert held_fd is not None
        fcntl.flock(held_fd, fcntl.LOCK_UN)
        os.close(held_fd)
        held_fd = None

    assert cli.cmd_stop(
        args, kill=fake_kill, lifecycle_notify=failed_notification
    ) == 0
    stopped = _json_result(capsys)
    assert stopped["result"]["pid"] == 4242
    assert stopped["result"]["running"] is False
    assert stopped["result"]["stopped"] is True
    assert stopped["result"]["notification"]["status"] == "failed"
    start_key = dict(notifications[0].stable_key)
    stop_key = dict(notifications[1].stable_key)
    assert start_key["incarnation_id"] == stop_key["incarnation_id"]
    assert start_key["transition"] == "started"
    assert stop_key["transition"] == "stopped"
    assert "pid" not in start_key | stop_key
    assert registry_path.read_bytes() == before
    assert cli.cmd_stop(
        args, kill=fake_kill, lifecycle_notify=failed_notification
    ) == 0
    no_op = _json_result(capsys)
    assert no_op["result"] == {
        "pid": None,
        "running": False,
        "stopped": False,
        "notification": None,
    }
    assert registry_path.read_bytes() == before


def test_concurrent_ensure_has_one_startup_owner(tmp_path: Path, capsys) -> None:
    lock_path = tmp_path / "daemon.lock"
    args = argparse.Namespace(
        registry_path=str(tmp_path / "sessions.json"),
        lock_path=str(lock_path),
        heartbeat_path=str(tmp_path / "heartbeat"),
        signals_path=str(tmp_path / "signals.jsonl"),
    )
    held_fd: int | None = None
    spawn_count = 0
    errors: list[BaseException] = []

    def fake_popen(_argv: list[str], **_kwargs: object) -> object:
        nonlocal held_fd, spawn_count
        spawn_count += 1
        held_fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o644)
        fcntl.flock(held_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        os.write(held_fd, b"4242\n")
        daemon.touch_heartbeat(args.heartbeat_path, "wd-test-incarnation-2")
        return object()

    def ensure() -> None:
        try:
            cli.cmd_ensure(
                args,
                popen=fake_popen,
                lifecycle_notify=lambda event: notify.DeliveryResult(
                    status="disabled",
                    event_id=event.event_id,
                    delivery_class=event.delivery_class,
                ),
            )
        except BaseException as exc:  # noqa: BLE001 -- asserted below
            errors.append(exc)

    threads = [threading.Thread(target=ensure) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)

    assert not errors
    assert all(not thread.is_alive() for thread in threads)
    assert spawn_count == 1
    results = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert sorted(result["result"]["started"] for result in results) == [False, True]
    assert held_fd is not None
    os.close(held_fd)


def test_concurrent_stops_make_one_attempt_and_one_noop(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    lock_path = tmp_path / "daemon.lock"
    held_fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o644)
    fcntl.flock(held_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    os.write(held_fd, b"4242\n")
    heartbeat_path = tmp_path / "heartbeat"
    daemon.touch_heartbeat(heartbeat_path, "wd-concurrent-stop")
    args = argparse.Namespace(
        registry_path=str(tmp_path / "sessions.json"),
        lock_path=str(lock_path),
        heartbeat_path=str(heartbeat_path),
        signals_path=str(tmp_path / "signals.jsonl"),
    )
    delivery_entered = threading.Event()
    release_delivery = threading.Event()
    errors: list[BaseException] = []
    kill_count = 0

    def fake_kill(pid: int, signum: int) -> None:
        nonlocal held_fd, kill_count
        assert (pid, signum) == (4242, signal.SIGTERM)
        kill_count += 1
        fcntl.flock(held_fd, fcntl.LOCK_UN)
        os.close(held_fd)

    def blocking_delivery(event):
        delivery_entered.set()
        assert release_delivery.wait(timeout=5)
        return notify.DeliveryResult(
            "failed", event.event_id, event.delivery_class
        )

    def stop() -> None:
        try:
            cli.cmd_stop(args, kill=fake_kill, lifecycle_notify=blocking_delivery)
        except BaseException as exc:  # noqa: BLE001 -- asserted below
            errors.append(exc)

    first = threading.Thread(target=stop)
    second = threading.Thread(target=stop)
    first.start()
    assert delivery_entered.wait(timeout=5)
    second.start()
    second.join(timeout=0.1)
    assert second.is_alive()
    release_delivery.set()
    first.join(timeout=5)
    second.join(timeout=5)

    assert not errors
    assert kill_count == 1
    results = [json.loads(line)["result"] for line in capsys.readouterr().out.splitlines()]
    assert sorted(result["stopped"] for result in results) == [False, True]
    notifying = next(result for result in results if result["stopped"])
    assert notifying["notification"]["status"] == "failed"


def test_replacement_ensure_waits_for_stop_delivery_boundary(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    lock_path = tmp_path / "daemon.lock"
    old_fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o644)
    fcntl.flock(old_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    os.write(old_fd, b"4242\n")
    heartbeat_path = tmp_path / "heartbeat"
    daemon.touch_heartbeat(heartbeat_path, "wd-old")
    args = argparse.Namespace(
        registry_path=str(tmp_path / "sessions.json"),
        lock_path=str(lock_path),
        heartbeat_path=str(heartbeat_path),
        signals_path=str(tmp_path / "signals.jsonl"),
    )
    delivery_entered = threading.Event()
    release_delivery = threading.Event()
    replacement_started = threading.Event()
    replacement_fd: int | None = None
    errors: list[BaseException] = []

    def fake_kill(_pid: int, _signum: int) -> None:
        fcntl.flock(old_fd, fcntl.LOCK_UN)
        os.close(old_fd)

    def blocking_delivery(event):
        delivery_entered.set()
        assert release_delivery.wait(timeout=5)
        return notify.DeliveryResult("disabled", event.event_id, event.delivery_class)

    def fake_popen(_argv: list[str], **_kwargs: object) -> object:
        nonlocal replacement_fd
        replacement_fd = os.open(lock_path, os.O_RDWR)
        fcntl.flock(replacement_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        os.ftruncate(replacement_fd, 0)
        os.write(replacement_fd, b"5252\n")
        daemon.touch_heartbeat(heartbeat_path, "wd-new")
        replacement_started.set()
        return object()

    def run_stop() -> None:
        try:
            cli.cmd_stop(args, kill=fake_kill, lifecycle_notify=blocking_delivery)
        except BaseException as exc:  # noqa: BLE001 -- asserted below
            errors.append(exc)

    def run_ensure() -> None:
        try:
            cli.cmd_ensure(
                args,
                popen=fake_popen,
                lifecycle_notify=lambda event: notify.DeliveryResult(
                    "delivered", event.event_id, event.delivery_class
                ),
            )
        except BaseException as exc:  # noqa: BLE001 -- asserted below
            errors.append(exc)

    stopper = threading.Thread(target=run_stop)
    starter = threading.Thread(target=run_ensure)
    stopper.start()
    assert delivery_entered.wait(timeout=5)
    starter.start()
    assert not replacement_started.wait(timeout=0.1)
    release_delivery.set()
    stopper.join(timeout=5)
    starter.join(timeout=5)

    assert not errors
    assert replacement_started.is_set()
    assert daemon.read_incarnation_id(heartbeat_path) == "wd-new"
    assert replacement_fd is not None
    os.close(replacement_fd)
    capsys.readouterr()


def test_spoofed_managed_start_fd_cannot_publish_during_blocked_stop(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    args, _claude_rec, _codex_rec = _run_fixture(tmp_path)
    args.once = False
    lock_path = Path(args.lock_path)
    old_fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o644)
    fcntl.flock(old_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    os.write(old_fd, b"4242\n")
    daemon.touch_heartbeat(args.heartbeat_path, "wd-old")
    delivery_entered = threading.Event()
    release_delivery = threading.Event()
    errors: list[BaseException] = []

    def fake_kill(_pid: int, _signum: int) -> None:
        fcntl.flock(old_fd, fcntl.LOCK_UN)
        os.close(old_fd)

    def blocking_delivery(event):
        delivery_entered.set()
        assert release_delivery.wait(timeout=5)
        return notify.DeliveryResult("disabled", event.event_id, event.delivery_class)

    def stop() -> None:
        try:
            cli.cmd_stop(args, kill=fake_kill, lifecycle_notify=blocking_delivery)
        except BaseException as exc:  # noqa: BLE001 -- asserted below
            errors.append(exc)

    stopper = threading.Thread(target=stop)
    stopper.start()
    assert delivery_entered.wait(timeout=5)

    spoof_fd = os.open(f"{lock_path}.startup", os.O_RDWR)
    child_env = os.environ.copy()
    child_env[cli._MANAGED_START_FD_ENV] = str(spoof_fd)
    child_code = f"""
import argparse
import os
from runtime.watchdog import cli, daemon
daemon.new_incarnation_id = lambda: 'wd-spoof-attempt'
args = argparse.Namespace(
    registry_path={args.registry_path!r}, lock_path={args.lock_path!r},
    heartbeat_path={args.heartbeat_path!r}, signals_path={args.signals_path!r},
    once=False,
)
def stop_after_publication(_target, *, timeout):
    raise RuntimeError('stop after authorized publication')
try:
    cli.cmd_run(args, has_session=stop_after_publication, get_config_int=lambda _key: 1)
except RuntimeError as exc:
    print(exc)
    try:
        os.fstat({spoof_fd})
    except OSError:
        print('INVALID_CLOSED')
    else:
        print('INVALID_LEAKED')
"""
    runner = subprocess.Popen(
        [sys.executable, "-c", child_code],
        cwd=cli._REPO_ROOT,
        env=child_env,
        pass_fds=(spoof_fd,),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        time.sleep(0.1)
        assert runner.poll() is None
        assert daemon.read_incarnation_id(args.heartbeat_path) == "wd-old"

        release_delivery.set()
        stopper.join(timeout=5)
        stdout, stderr = runner.communicate(timeout=5)
    finally:
        os.close(spoof_fd)
        if runner.poll() is None:
            runner.kill()
            runner.wait(timeout=5)

    assert not stopper.is_alive()
    assert not errors
    assert runner.returncode == 0, stderr
    assert "stop after authorized publication" in stdout
    assert "INVALID_CLOSED" in stdout
    assert daemon.read_incarnation_id(args.heartbeat_path) == "wd-spoof-attempt"
    capsys.readouterr()


def test_managed_ensure_capability_runs_without_deadlock_and_closes_child_fd(
    tmp_path: Path,
) -> None:
    args, _claude_rec, _codex_rec = _run_fixture(tmp_path)
    args.once = False
    parent_fd = cli._acquire_lifecycle_operation_lock(args.lock_path)
    os.set_inheritable(parent_fd, True)
    child_env = os.environ.copy()
    child_env[cli._MANAGED_START_FD_ENV] = str(parent_fd)
    child_code = f"""
import argparse
import os
from runtime.watchdog import cli, daemon
daemon.new_incarnation_id = lambda: 'wd-managed'
args = argparse.Namespace(
    registry_path={args.registry_path!r}, lock_path={args.lock_path!r},
    heartbeat_path={args.heartbeat_path!r}, signals_path={args.signals_path!r},
    once=False,
)
def stop_after_publication(_target, *, timeout):
    assert daemon.read_incarnation_id(args.heartbeat_path) == 'wd-managed'
    assert os.get_inheritable({parent_fd}) is False
    raise RuntimeError('stop after managed publication')
try:
    cli.cmd_run(args, has_session=stop_after_publication, get_config_int=lambda _key: 1)
except RuntimeError:
    try:
        os.fstat({parent_fd})
    except OSError:
        print('CLOSED')
    else:
        print('LEAKED')
"""
    try:
        result = subprocess.run(
            [sys.executable, "-c", child_code],
            cwd=cli._REPO_ROOT,
            env=child_env,
            pass_fds=(parent_fd,),
            capture_output=True,
            text=True,
            timeout=5,
        )
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == "CLOSED"
        assert os.get_inheritable(parent_fd) is True
        contender = os.open(f"{args.lock_path}.startup", os.O_RDWR)
        try:
            with pytest.raises(BlockingIOError):
                fcntl.flock(contender, fcntl.LOCK_EX | fcntl.LOCK_NB)
        finally:
            os.close(contender)
    finally:
        cli._release_lifecycle_operation_lock(parent_fd)


def test_managed_fd_non_inheritable_failure_closes_without_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    args, _claude_rec, _codex_rec = _run_fixture(tmp_path)
    args.once = False
    operation_fd = cli._acquire_lifecycle_operation_lock(args.lock_path)
    monkeypatch.setenv(cli._MANAGED_START_FD_ENV, str(operation_fd))

    def fail_non_inheritable(fd: int, inheritable: bool) -> None:
        assert (fd, inheritable) == (operation_fd, False)
        raise OSError("cannot set close-on-exec")

    def fail_fallback(_lock_path: Path | str) -> int:
        pytest.fail("accepted capability failure must not acquire the sidecar")

    monkeypatch.setattr(cli.os, "set_inheritable", fail_non_inheritable)
    monkeypatch.setattr(cli, "_acquire_lifecycle_operation_lock", fail_fallback)

    with pytest.raises(OSError, match="cannot set close-on-exec"):
        cli.cmd_run(
            args,
            get_config_int=lambda _key: pytest.fail(
                "configuration resolution must follow the FD boundary"
            ),
        )

    with pytest.raises(OSError):
        os.fstat(operation_fd)
    assert cli._MANAGED_START_FD_ENV not in os.environ


def test_direct_standing_run_publishes_before_reconcile_and_releases_on_failure(
    tmp_path: Path,
) -> None:
    args, _claude_rec, _codex_rec = _run_fixture(tmp_path)
    args.once = False
    expected = "wd-direct"
    operation_fd = cli._acquire_lifecycle_operation_lock(args.lock_path)
    reconcile_entered = threading.Event()
    errors: list[BaseException] = []

    def has_session(_target: str, *, timeout: float) -> bool:
        assert timeout > 0
        assert daemon.read_incarnation_id(args.heartbeat_path) == expected
        reconcile_entered.set()
        raise RuntimeError("stop after publication")

    def run() -> None:
        try:
            cli.cmd_run(
                args,
                has_session=has_session,
                get_config_int=lambda _key: 1,
                capture_pane=lambda _target, *, timeout: "",
                poll_session=lambda *_args, **_kwargs: {},
            )
        except BaseException as exc:  # noqa: BLE001 -- asserted below
            errors.append(exc)

    original = daemon.new_incarnation_id
    daemon.new_incarnation_id = lambda: expected
    try:
        thread = threading.Thread(target=run)
        thread.start()
        assert not reconcile_entered.wait(timeout=0.1)
        assert not Path(args.heartbeat_path).exists()
        cli._release_lifecycle_operation_lock(operation_fd)
        thread.join(timeout=5)
    finally:
        daemon.new_incarnation_id = original

    assert len(errors) == 1
    assert str(errors[0]) == "stop after publication"
    with daemon.run_lifecycle(args.lock_path):
        pass
    with cli._hold_lifecycle_operation_lock(args.lock_path):
        pass


def test_standing_publication_failure_releases_both_lifecycle_locks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    args, _claude_rec, _codex_rec = _run_fixture(tmp_path)
    args.once = False

    def fail_publication(_path: Path, _incarnation_id: str) -> None:
        raise OSError("heartbeat denied")

    monkeypatch.setattr(daemon, "touch_heartbeat", fail_publication)
    with pytest.raises(OSError, match="heartbeat denied"):
        cli.cmd_run(args, get_config_int=lambda _key: 1)

    with daemon.run_lifecycle(args.lock_path):
        pass
    with cli._hold_lifecycle_operation_lock(args.lock_path):
        pass


def test_raising_stop_delivery_releases_operation_lock(
    tmp_path: Path,
) -> None:
    lock_path = tmp_path / "daemon.lock"
    held_fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o644)
    fcntl.flock(held_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    os.write(held_fd, b"4242\n")
    heartbeat_path = tmp_path / "heartbeat"
    daemon.touch_heartbeat(heartbeat_path, "wd-raising-delivery")
    args = argparse.Namespace(
        lock_path=str(lock_path), heartbeat_path=str(heartbeat_path)
    )

    def fake_kill(_pid: int, _signum: int) -> None:
        fcntl.flock(held_fd, fcntl.LOCK_UN)
        os.close(held_fd)

    def raising_delivery(_event):
        raise RuntimeError("delivery exploded")

    with pytest.raises(RuntimeError, match="delivery exploded"):
        cli.cmd_stop(args, kill=fake_kill, lifecycle_notify=raising_delivery)

    assert registry.daemon_lock_status(lock_path) == (False, None)
    with cli._hold_lifecycle_operation_lock(lock_path):
        pass


def test_stop_rejects_held_lock_without_pid_as_json(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    lock_path = tmp_path / "daemon.lock"
    held_fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o644)
    fcntl.flock(held_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
        assert cli.main(["stop", "--lock-path", str(lock_path)]) == 5
        result = _json_result(capsys)
        assert result["error"]["code"] == "daemon_stop_failed"
        assert result["ok"] is False
    finally:
        os.close(held_fd)


@pytest.mark.parametrize("pid", [-1, 0])
def test_stop_rejects_held_lock_with_non_positive_pid_as_json(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    pid: int,
) -> None:
    lock_path = tmp_path / "daemon.lock"
    held_fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o644)
    fcntl.flock(held_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    os.write(held_fd, f"{pid}\n".encode())

    def fail_kill(_pid: int, _signum: int) -> None:
        pytest.fail("stop must not signal a non-positive pid")

    monkeypatch.setattr(cli.os, "kill", fail_kill)
    try:
        assert cli.main(["stop", "--lock-path", str(lock_path)]) == 5
        assert _json_result(capsys) == {
            "schema_version": cli.CLI_SCHEMA_VERSION,
            "ok": False,
            "error": {
                "code": "daemon_stop_failed",
                "message": "daemon lock is held without a readable pid",
            },
        }
    finally:
        os.close(held_fd)


def test_daemon_start_and_stop_os_failures_have_lifecycle_json_codes(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_start(*_args: object, **_kwargs: object) -> object:
        raise OSError("spawn denied")

    monkeypatch.setattr(cli.subprocess, "Popen", fail_start)
    paths = [
        "--lock-path", str(tmp_path / "daemon.lock"),
        "--heartbeat-path", str(tmp_path / "heartbeat"),
    ]
    assert cli.main(["ensure", *paths]) == 5
    assert _json_result(capsys)["error"]["code"] == "daemon_start_failed"

    monkeypatch.setattr(registry, "daemon_lock_status", lambda _path: (True, 4242))

    def fail_stop(_pid: int, _signum: int) -> None:
        raise PermissionError("signal denied")

    monkeypatch.setattr(cli.os, "kill", fail_stop)
    assert cli.main(["stop", *paths]) == 5
    assert _json_result(capsys)["error"]["code"] == "daemon_stop_failed"
