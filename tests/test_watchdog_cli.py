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
  pane, touches the heartbeat, exits 0, and never sleeps/loops a second pass;
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
from pathlib import Path

import pytest

from runtime.watchdog import cli, registry, tmux_actuator
from runtime.watchdog.adapters import ClaudeAdapter, CodexAdapter, OmpAdapter


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
    out = capsys.readouterr().out
    assert "heartbeat_age_s: unknown" in out
    session_id = next(iter(fixture))
    assert session_id in out
    assert "slug=alpha" in out
    assert "host=claude" in out
    assert "state=running" in out


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
    out = capsys.readouterr().out
    assert "heartbeat_age_s: unknown" not in out
    assert "heartbeat_age_s:" in out


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


def test_cmd_run_once_touches_heartbeat_and_releases_lock(tmp_path: Path) -> None:
    args, _claude_rec, _codex_rec = _run_fixture(tmp_path)

    rc = cli.cmd_run(args, **_run_once_kwargs())

    assert rc == 0
    assert Path(args.heartbeat_path).exists()
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
