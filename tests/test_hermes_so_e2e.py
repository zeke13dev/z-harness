"""Fake Discord/MCP/tmux e2e for Hermes `so` orchestration."""

from pathlib import Path
import subprocess
import sys

SCRIPTS_DIR = Path(__file__).parent.parent / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from hermes.config import DiscordProjectAlias, HermesConfig  # noqa: E402
from hermes.discord_relay import (  # noqa: E402
    launch_accepted_so_command,
    parse_so_command,
)
from hermes.mcp_hermes_orchestrator import (  # noqa: E402
    SoSessionStore,
    read_so_session,
    send_to_so_session,
    start_so_session,
)


class FakeTmuxRunner:
    def __init__(self):
        self.calls = []

    def run(self, argv, *, cwd=None, env=None, timeout=None):
        self.calls.append(
            {"argv": list(argv), "cwd": cwd, "env": dict(env or {}), "timeout": timeout}
        )
        text = " ".join(argv)
        stdout = "Need input?" if "capture-pane" in text else ""
        return subprocess.CompletedProcess(argv, 0, stdout, "")


def _config(tmp_path):
    cfg = HermesConfig()
    cfg.paths.hermes_state_root = str(tmp_path)
    cfg.discord.user_id = "user-1"
    cfg.discord.so.allowed_user_ids = {"user-1"}
    cfg.discord.so.allowed_channel_ids = {"chan-1"}
    cfg.discord.so.allowed_hosts = {"omp"}
    cfg.discord.so.project_aliases["qt-bot"] = DiscordProjectAlias(
        repo_root="ssh://zeke-pc/home/zeke/dev/qt-bot",
        execution_host="zeke-pc",
        transport="ssh",
        ssh_target="zeke-pc",
        workdir="/home/zeke/dev/qt-bot",
    )
    return cfg


def test_fake_discord_to_mcp_tmux_to_reply_flow(tmp_path):
    cfg = _config(tmp_path)
    command = parse_so_command(
        "so omp qt-bot fix blah using z-debug",
        requester_user_id="user-1",
        channel_id="chan-1",
        message_id="msg-1",
        thread_id="thread-1",
        config=cfg,
    )
    runner = FakeTmuxRunner()

    launched = start_so_session(command, cfg, runner=runner, session_id="so-test")

    assert launched.session_id == "so-test"
    assert launched.status == "running"
    assert runner.calls[0]["argv"][:2] == ["ssh", "zeke-pc"]
    assert "tmux new-session" in runner.calls[0]["argv"][2]
    assert "tmux send-keys" in runner.calls[1]["argv"][2]
    assert "z-debug" in runner.calls[1]["argv"][2]
    assert "fix blah" in runner.calls[1]["argv"][2]

    continued = send_to_so_session("so-test", "continue", cfg, runner=runner)
    read_back = read_so_session("so-test", cfg, runner=runner)

    assert continued.turn_count == 2
    assert read_back.status == "needs_input"
    assert SoSessionStore.from_config(cfg).get("so-test").last_output == "Need input?"


def test_discord_launcher_uses_mcp_orchestrator(monkeypatch, tmp_path):
    cfg = _config(tmp_path)
    command = parse_so_command(
        "so omp qt-bot fix blah using z-debug",
        requester_user_id="user-1",
        channel_id="chan-1",
        message_id="msg-1",
        config=cfg,
    )
    calls = []

    def fake_start(command_arg, config_arg):
        calls.append((command_arg, config_arg))
        return type(
            "Result",
            (),
            {"job_id": "so-test", "session_id": "so-test", "task": command_arg.task},
        )()

    monkeypatch.setattr("hermes.mcp_hermes_orchestrator.start_so_session", fake_start)

    result = launch_accepted_so_command(command, cfg)

    assert result.session_id == "so-test"
    assert calls == [(command, cfg)]
