"""Tests for the Hermes `so` MCP backend."""

from pathlib import Path
import subprocess
import sys

import pytest

SCRIPTS_DIR = Path(__file__).parent.parent / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from hermes.config import DiscordProjectAlias, HermesConfig  # noqa: E402
from hermes.discord_relay import SoCommand  # noqa: E402
from hermes.so_mcp import (  # noqa: E402
    AgentCommandError,
    SoSessionStore,
    build_initial_so_prompt,
    send_to_so_session,
    start_so_session,
)


class FakeRunner:
    def __init__(self, stdout="done", returncode=0):
        self.stdout = stdout
        self.returncode = returncode
        self.calls = []

    def run(self, argv, *, cwd=None, env=None, input=None, timeout=None):
        self.calls.append(
            {
                "argv": list(argv),
                "cwd": cwd,
                "env": dict(env or {}),
                "input": input,
                "timeout": timeout,
            }
        )
        return subprocess.CompletedProcess(
            argv,
            self.returncode,
            self.stdout if self.returncode == 0 else "",
            "boom" if self.returncode else "",
        )


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


def test_start_session_runs_agent_cli_and_persists_metadata(tmp_path):
    cfg, alias = _config(tmp_path)
    runner = FakeRunner(stdout="working")
    record = start_so_session(
        _command(alias),
        cfg,
        runner=runner,
        session_id="so-test",
        timeout=12,
    )

    assert record.session_id == "so-test"
    assert record.job_id == "so-test"
    assert record.status == "running"
    assert record.turn_count == 1
    assert runner.calls[0]["argv"] == [
        "omp",
        "-p",
        "--mode",
        "text",
        "--session-id",
        "so-test",
    ]
    assert runner.calls[0]["cwd"] == str(tmp_path)
    assert "HERMES_SO_SESSION_ID" in runner.calls[0]["env"]
    assert "fix blah" in runner.calls[0]["input"]
    assert "z-debug" in runner.calls[0]["input"]
    assert SoSessionStore.from_config(cfg).get("so-test").task == "fix blah"


def test_ssh_transport_runs_agent_on_recorded_host(tmp_path):
    cfg, alias = _config(tmp_path, transport="ssh")
    runner = FakeRunner(stdout="remote ok")

    start_so_session(_command(alias), cfg, runner=runner, session_id="so-test")

    assert runner.calls[0]["argv"][:2] == ["ssh", "zeke-pc"]
    remote_command = runner.calls[0]["argv"][2]
    assert "cd /home/zeke/dev/qt-bot" in remote_command
    assert "HERMES_SO_SESSION_ID=so-test" in remote_command
    assert "omp -p --mode text --session-id so-test" in remote_command


def test_send_continues_existing_session_and_updates_status(tmp_path):
    cfg, alias = _config(tmp_path)
    store = SoSessionStore.from_config(cfg)
    start_so_session(_command(alias), cfg, runner=FakeRunner(), session_id="so-test")

    runner = FakeRunner(stdout="Should I proceed?")
    record = send_to_so_session("so-test", "continue", cfg, runner=runner)

    assert record.status == "needs_input"
    assert record.turn_count == 2
    assert runner.calls[0]["input"] == "continue"
    assert store.get("so-test").last_output == "Should I proceed?"


def test_failed_agent_marks_session_failed(tmp_path):
    cfg, alias = _config(tmp_path)
    runner = FakeRunner(returncode=2)

    with pytest.raises(AgentCommandError):
        start_so_session(_command(alias), cfg, runner=runner, session_id="so-test")

    record = SoSessionStore.from_config(cfg).get("so-test")
    assert record.status == "failed"
    assert record.last_exit_code == 2


def test_prompt_names_mcp_backend_not_tmux(tmp_path):
    _cfg, alias = _config(tmp_path)
    prompt = build_initial_so_prompt(_command(alias), "so-test")

    assert "MCP session" in prompt
    assert "tmux" not in prompt.lower()
