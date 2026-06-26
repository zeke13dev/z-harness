"""Fake Discord/agent-CLI e2e for Hermes `so` MCP orchestration."""

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
from hermes.so_mcp import (  # noqa: E402
    SoSessionStore,
    send_to_so_session,
    start_so_session,
)


class FakeAgentRunner:
    def __init__(self):
        self.calls = []
        self.outputs = ["started", "Need user confirmation?"]

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
        output = self.outputs.pop(0) if self.outputs else "ok"
        return subprocess.CompletedProcess(argv, 0, output, "")


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


def test_fake_discord_to_mcp_agent_session_to_reply_flow(tmp_path):
    cfg = _config(tmp_path)
    command = parse_so_command(
        "so omp qt-bot fix blah using z-debug",
        requester_user_id="user-1",
        channel_id="chan-1",
        message_id="msg-1",
        thread_id="thread-1",
        config=cfg,
    )
    runner = FakeAgentRunner()

    launched = start_so_session(
        command,
        cfg,
        runner=runner,
        session_id="so-test",
        timeout=30,
    )

    assert launched.session_id == "so-test"
    assert launched.status == "running"
    assert runner.calls[0]["argv"][:2] == ["ssh", "zeke-pc"]
    assert "tmux" not in " ".join(runner.calls[0]["argv"])
    assert "z-debug" in runner.calls[0]["input"]
    assert "fix blah" in runner.calls[0]["input"]

    continued = send_to_so_session("so-test", "continue", cfg, runner=runner)

    assert continued.status == "needs_input"
    assert runner.calls[1]["input"] == "continue"
    assert SoSessionStore.from_config(cfg).get("so-test").turn_count == 2


def test_discord_launcher_uses_mcp_backend(monkeypatch, tmp_path):
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

    monkeypatch.setattr("hermes.so_mcp.start_so_session", fake_start)

    result = launch_accepted_so_command(command, cfg)

    assert result.job_id == "so-test"
    assert calls == [(command, cfg)]
