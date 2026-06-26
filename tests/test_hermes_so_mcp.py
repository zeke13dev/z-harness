"""Tests for the Hermes `so` MCP tmux orchestrator."""

from pathlib import Path
import subprocess
import sys

import pytest

SCRIPTS_DIR = Path(__file__).parent.parent / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from hermes.config import DiscordProjectAlias, HermesConfig  # noqa: E402
from hermes.discord_relay import SoCommand  # noqa: E402
from hermes.mcp_hermes_orchestrator import (  # noqa: E402
    SoMcpError,
    SoSessionStore,
    build_initial_prompt,
    read_so_session,
    send_to_so_session,
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
            {"argv": list(argv), "cwd": cwd, "env": dict(env or {}), "timeout": timeout}
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
        workdir="/home/zeke/dev/qt-bot" if transport == "ssh" else str(tmp_path),
    )
    cfg.discord.so.project_aliases["qt-bot"] = alias
    return cfg, alias


def _command(alias):
    return SoCommand(
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
    start_so_session(_command(alias), cfg, runner=FakeRunner(), session_id="so-test")
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
    start_so_session(_command(alias), cfg, runner=FakeRunner(), session_id="so-test")

    record = read_so_session("so-test", cfg, runner=FakeRunner(capture="Proceed?"))

    assert record.status == "needs_input"
    assert record.last_output == "Proceed?"


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
