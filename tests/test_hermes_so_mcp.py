"""Tests for the Hermes `so` MCP tmux orchestrator."""

import json
from pathlib import Path
import subprocess
import sys

import pytest

SCRIPTS_DIR = Path(__file__).parent.parent / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from hermes.config import DiscordProjectAlias, HermesConfig  # noqa: E402
from hermes.mcp_hermes_orchestrator import (  # noqa: E402
    SoMcpError,
    SoFanoutRequest,
    SoSessionStore,
    SoStartRequest,
    drain_signal_events,
    authorize_so_start,
    build_initial_prompt,
    fanout_group_summary,
    list_so_sessions,
    read_so_session,
    poll_so_sessions,
    reap_so_sessions,
    send_to_so_session,
    start_fanout_sessions,
    start_so_session,
    tmux_session_name,
)


class FakeRunner:
    def __init__(self, fail_on=None, capture="Proceed?"):
        self.fail_on = fail_on or set()
        self.capture = capture
        self.calls = []

    def run(self, argv, *, cwd=None, env=None, timeout=None):
        self.calls.append(
            {
                "argv": list(argv),
                "cwd": cwd,
                "env": dict(env or {}),
                "timeout": timeout,
            }
        )
        text = " ".join(argv)
        if any(token in text for token in self.fail_on):
            return subprocess.CompletedProcess(argv, 1, "", "boom")
        stdout = self.capture if "capture-pane" in text else ""
        return subprocess.CompletedProcess(argv, 0, stdout, "")


def _config(tmp_path, *, transport="local"):
    cfg = HermesConfig()
    cfg.paths.hermes_state_root = str(tmp_path)
    alias = DiscordProjectAlias(
        repo_root="ssh://zeke-pc/home/zeke/dev/qt-bot",
        execution_host="zeke-pc" if transport == "ssh" else "local",
        transport=transport,
        ssh_target="zeke-pc" if transport == "ssh" else "",
        workdir=(
            "/home/zeke/dev/qt-bot" if transport == "ssh" else str(tmp_path)
        ),
    )
    cfg.discord.so.project_aliases["qt-bot"] = alias
    return cfg, alias


def _command(alias):
    return SoStartRequest(
        host="omp",
        project="qt-bot",
        project_alias=alias,
        task="fix blah",
        z_command="z-debug",
        requester_user_id="user-1",
        discord_channel_id="chan-1",
        discord_message_id="msg-1",
        discord_thread_id="thread-1",
    )


def _write_workstreams(tmp_path, *, workstreams=None, slug="split-session-fanout"):
    data = {
        "protocol": "hermes-v1",
        "slug": slug,
        "source": "/z-plan-split",
        "generated_at": "2026-07-03T00:00:00+00:00",
        "partial_tree": any(
            ws.get("status") != "ready" for ws in (workstreams or [])
        ),
        "scope_unknown": False,
        "workstreams": workstreams
        or [
            {
                "id": "ws-1",
                "name": "cluster one",
                "status": "ready",
                "path": "z-harness/demo/ws-1",
                "tasks": [],
                "depends_on": [],
                "parallel_group": "level-0",
            }
        ],
        "file_conflicts": [],
        "merge_order": [
            ws["id"] for ws in (
                workstreams
                or [
                    {
                        "id": "ws-1",
                    }
                ]
            )
        ],
    }
    path = tmp_path / "workstreams.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_start_session_creates_tmux_and_sends_initial_prompt(tmp_path):
    cfg, alias = _config(tmp_path)
    runner = FakeRunner()
    record = start_so_session(
        _command(alias), cfg, runner=runner, session_id="so-test"
    )

    assert record.session_id == "so-test"
    assert record.status == "running"
    assert runner.calls[0]["argv"][:3] == ["tmux", "new-session", "-d"]
    assert runner.calls[1]["argv"][:3] == ["tmux", "send-keys", "-t"]
    prompt = runner.calls[1]["argv"][4]
    assert "fix blah" in prompt
    assert "z-debug" in prompt
    assert SoSessionStore.from_config(cfg).get("so-test").tmux_session


def test_store_loads_legacy_records_without_fanout_fields(tmp_path):
    cfg, _alias = _config(tmp_path)
    path = Path(cfg.paths.hermes_state_root) / "so-mcp-sessions.json"
    path.write_text(
        json.dumps(
            {
                "so-legacy": {
                    "session_id": "so-legacy",
                    "host": "omp",
                    "project": "qt-bot",
                    "task": "legacy task",
                    "z_command": "z-plan",
                }
            }
        ),
        encoding="utf-8",
    )

    record = SoSessionStore.from_config(cfg).get("so-legacy")

    assert record is not None
    assert record.fanout_group_id == ""
    assert record.workstream_id == ""


def test_ssh_transport_runs_tmux_on_recorded_host(tmp_path):
    cfg, alias = _config(tmp_path, transport="ssh")
    runner = FakeRunner()

    start_so_session(_command(alias), cfg, runner=runner, session_id="so-test")

    assert runner.calls[0]["argv"][:2] == ["ssh", "zeke-pc"]
    remote = runner.calls[0]["argv"][2]
    assert "cd /home/zeke/dev/qt-bot" in remote
    assert "HERMES_SO_SESSION_ID=so-test" in remote
    assert "tmux new-session" in remote


def test_send_uses_existing_tmux_session(tmp_path):
    cfg, alias = _config(tmp_path)
    start_so_session(
        _command(alias), cfg, runner=FakeRunner(), session_id="so-test"
    )
    runner = FakeRunner()

    record = send_to_so_session("so-test", "continue", cfg, runner=runner)

    assert record.turn_count == 2
    assert runner.calls[0]["argv"] == [
        "tmux",
        "send-keys",
        "-t",
        tmux_session_name("so-test"),
        "continue",
        "C-m",
    ]


def test_read_captures_on_demand_and_sets_needs_input(tmp_path):
    cfg, alias = _config(tmp_path)
    start_so_session(
        _command(alias), cfg, runner=FakeRunner(), session_id="so-test"
    )

    record = read_so_session(
        "so-test", cfg, runner=FakeRunner(capture="Proceed?\n❯")
    )

    assert record.status == "needs_input"
    assert record.last_output == "Proceed?\n❯"

    events = drain_signal_events(cfg)
    assert events[0]["event"] == "so_needs_input"
    assert events[0]["session_id"] == "so-test"
    assert events[0]["discord_thread_id"] == "thread-1"


def test_read_deduplicates_needs_input_signals(tmp_path):
    cfg, alias = _config(tmp_path)
    start_so_session(
        _command(alias), cfg, runner=FakeRunner(), session_id="so-test"
    )

    read_so_session("so-test", cfg, runner=FakeRunner(capture="Proceed?\n❯"))
    read_so_session("so-test", cfg, runner=FakeRunner(capture="Proceed?\n❯"))

    assert len(drain_signal_events(cfg)) == 1


def test_send_allows_next_needs_input_signal(tmp_path):
    cfg, alias = _config(tmp_path)
    start_so_session(
        _command(alias), cfg, runner=FakeRunner(), session_id="so-test"
    )

    read_so_session("so-test", cfg, runner=FakeRunner(capture="Proceed?\n❯"))
    send_to_so_session("so-test", "continue", cfg, runner=FakeRunner())
    read_so_session("so-test", cfg, runner=FakeRunner(capture="Next?\n❯"))

    events = drain_signal_events(cfg)
    assert [event["event"] for event in events] == [
        "so_needs_input",
        "so_needs_input",
    ]


def test_reaper_marks_missing_tmux_session_dead(tmp_path):
    cfg, alias = _config(tmp_path)
    start_so_session(
        _command(alias), cfg, runner=FakeRunner(), session_id="so-test"
    )

    result = reap_so_sessions(cfg, runner=FakeRunner(fail_on={"has-session"}))

    assert result["dead"] == ["so-test"]
    assert SoSessionStore.from_config(cfg).get("so-test").status == "dead"
    assert drain_signal_events(cfg)[0]["event"] == "so_session_dead"


def test_reaper_expires_sessions_past_ttl(tmp_path):
    cfg, alias = _config(tmp_path)
    start_so_session(
        _command(alias), cfg, runner=FakeRunner(), session_id="so-test"
    )
    store = SoSessionStore.from_config(cfg)
    record = store.get("so-test")
    record.expires_at = "2000-01-01T00:00:00+00:00"
    store.save(record)

    result = reap_so_sessions(cfg, runner=FakeRunner())

    assert result["expired"] == ["so-test"]
    assert store.get("so-test").status == "expired"
    assert drain_signal_events(cfg)[0]["event"] == "so_session_expired"


def test_failed_tmux_marks_session_failed(tmp_path):
    cfg, alias = _config(tmp_path)

    with pytest.raises(SoMcpError):
        start_so_session(
            _command(alias),
            cfg,
            runner=FakeRunner(fail_on={"new-session"}),
            session_id="so-test",
        )

    assert SoSessionStore.from_config(cfg).get("so-test").status == "failed"


def test_prompt_names_mcp_managed_tmux(tmp_path):
    _cfg, alias = _config(tmp_path)
    prompt = build_initial_prompt(_command(alias), "so-test")

    assert "MCP-managed tmux session" in prompt
    assert "z-debug" in prompt


def test_fanout_start_skips_failed_and_records_group_metadata(tmp_path):
    cfg, alias = _config(tmp_path)
    _write_workstreams(
        tmp_path,
        workstreams=[
            {
                "id": "ws-1",
                "name": "cluster one",
                "status": "ready",
                "path": "z-harness/demo/ws-1",
                "tasks": [],
                "depends_on": [],
                "parallel_group": "level-0",
            },
            {
                "id": "ws-2",
                "name": "cluster two",
                "status": "failed",
                "path": "z-harness/demo/ws-2",
                "tasks": [],
                "depends_on": [],
                "parallel_group": "level-0",
            },
        ],
    )
    runner = FakeRunner()
    request = SoFanoutRequest(
        host="omp",
        project="qt-bot",
        project_alias=alias,
        slug="split-session-fanout",
        workstreams_path="workstreams.json",
        task="Continue the split plan",
        group_id="fanout-test",
        shared_concerns_path="SHARED-CONCERNS.md",
        handoff_paths=("HANDOFF.md",),
        requester_user_id="user-1",
        discord_channel_id="chan-1",
    )

    result = start_fanout_sessions(
        request,
        cfg,
        runner=runner,
        session_id_factory=lambda ws: f"so-{ws.id}",
    )

    assert result["ok"] is True
    assert result["fanout_group_id"] == "fanout-test"
    assert [child["session_id"] for child in result["children"]] == ["so-ws-1"]
    assert result["skipped"] == [
        {"workstream_id": "ws-2", "status": "failed", "reason": "not_ready"}
    ]

    record = SoSessionStore.from_config(cfg).get("so-ws-1")
    assert record.fanout_group_id == "fanout-test"
    assert record.fanout_slug == "split-session-fanout"
    assert record.workstream_id == "ws-1"
    assert record.workstream_path == "z-harness/demo/ws-1"

    prompt = runner.calls[1]["argv"][4]
    assert "Fanout group: fanout-test" in prompt
    assert "Assigned workstream: ws-1" in prompt
    assert "Do not assume the workstream directory contains TASKS.md" in prompt


def test_fanout_rejects_unsafe_manifest_path(tmp_path):
    cfg, alias = _config(tmp_path)
    request = SoFanoutRequest(
        host="omp",
        project="qt-bot",
        project_alias=alias,
        slug="split-session-fanout",
        workstreams_path="../workstreams.json",
    )

    with pytest.raises(SoMcpError, match="workstreams_path"):
        start_fanout_sessions(request, cfg, runner=FakeRunner())


def test_fanout_signal_payload_includes_group_metadata(tmp_path):
    cfg, alias = _config(tmp_path)
    _write_workstreams(tmp_path)
    request = SoFanoutRequest(
        host="omp",
        project="qt-bot",
        project_alias=alias,
        slug="split-session-fanout",
        workstreams_path="workstreams.json",
        group_id="fanout-test",
    )
    start_fanout_sessions(
        request,
        cfg,
        runner=FakeRunner(),
        session_id_factory=lambda ws: f"so-{ws.id}",
    )

    read_so_session("so-ws-1", cfg, runner=FakeRunner(capture="Blocked?\n❯"))

    events = drain_signal_events(cfg)
    assert events[0]["event"] == "so_needs_input"
    assert events[0]["fanout_group_id"] == "fanout-test"
    assert events[0]["workstream_id"] == "ws-1"
    assert events[0]["workstream_path"] == "z-harness/demo/ws-1"


def test_fanout_group_summary_and_filtered_list(tmp_path):
    cfg, alias = _config(tmp_path)
    _write_workstreams(tmp_path)
    request = SoFanoutRequest(
        host="omp",
        project="qt-bot",
        project_alias=alias,
        slug="split-session-fanout",
        workstreams_path="workstreams.json",
        group_id="fanout-test",
    )
    start_fanout_sessions(
        request,
        cfg,
        runner=FakeRunner(),
        session_id_factory=lambda ws: f"so-{ws.id}",
    )
    read_so_session("so-ws-1", cfg, runner=FakeRunner(capture="Blocked?\n❯"))

    records = list_so_sessions(cfg, fanout_group_id="fanout-test")
    summary = fanout_group_summary("fanout-test", cfg)

    assert [record.session_id for record in records] == ["so-ws-1"]
    assert summary["count"] == 1
    assert summary["counts"]["needs_input"] == 1
    assert summary["complete"] is False


def test_start_auth_rejects_unallowed_user_channel_and_host(tmp_path):
    cfg, _alias = _config(tmp_path)
    cfg.discord.so.allowed_user_ids = {"user-1"}
    cfg.discord.so.allowed_channel_ids = {"chan-1"}
    cfg.discord.so.allowed_hosts = {"omp"}

    with pytest.raises(SoMcpError):
        authorize_so_start(
            cfg,
            host="omp",
            requester_user_id="user-2",
            discord_channel_id="chan-1",
        )
    with pytest.raises(SoMcpError):
        authorize_so_start(
            cfg,
            host="omp",
            requester_user_id="user-1",
            discord_channel_id="chan-2",
        )
    with pytest.raises(SoMcpError):
        authorize_so_start(
            cfg,
            host="other",
            requester_user_id="user-1",
            discord_channel_id="chan-1",
        )


def test_poll_so_sessions_reads_active_sessions_and_reaps(tmp_path):
    cfg, alias = _config(tmp_path)
    start_so_session(
        _command(alias), cfg, runner=FakeRunner(), session_id="so-test"
    )

    result = poll_so_sessions(
        cfg,
        runner=FakeRunner(capture="Waiting for input\n❯"),
    )

    assert result["checked"] == ["so-test"]
    assert result["needs_input"] == ["so-test"]
    assert result["errors"] == {}
    assert drain_signal_events(cfg)[0]["event"] == "so_needs_input"
