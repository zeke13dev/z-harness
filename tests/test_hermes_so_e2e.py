"""Fake LLM/MCP/tmux e2e for Hermes `so` orchestration."""

from pathlib import Path
import subprocess
import sys

import pytest

SCRIPTS_DIR = Path(__file__).parent.parent / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from hermes.config import DiscordProjectAlias, HermesConfig  # noqa: E402
from hermes.mcp_hermes_orchestrator import (  # noqa: E402
    SoSessionStore,
    SoStartRequest,
    read_so_session,
    send_to_so_session,
    start_so_session,
)
from hermes import so_watcher  # noqa: E402


@pytest.fixture(autouse=True)
def _no_spawn_sleep(monkeypatch):
    """Neutralise the spawn settle/readiness sleeps so tests stay fast."""
    monkeypatch.setattr(
        "hermes.mcp_hermes_orchestrator._sleep", lambda *_a, **_k: None
    )


class FakeTmuxRunner:
    def __init__(self):
        self.calls = []

    def run(self, argv, *, cwd=None, env=None, timeout=None):
        self.calls.append(
            {"argv": list(argv), "cwd": cwd, "env": dict(env or {}), "timeout": timeout}
        )
        text = " ".join(argv)
        stdout = "Need input?\n>" if "capture-pane" in text else ""
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


def _llm_parsed_request(cfg):
    return SoStartRequest(
        host="omp",
        project="qt-bot",
        project_alias=cfg.discord.so.project_aliases["qt-bot"],
        task="fix blah",
        z_command="z-debug",
        requester_user_id="user-1",
        discord_channel_id="chan-1",
        discord_message_id="msg-1",
        discord_thread_id="thread-1",
    )


def test_fake_llm_to_mcp_tmux_to_reply_flow(tmp_path):
    cfg = _config(tmp_path)
    command = _llm_parsed_request(cfg)
    runner = FakeTmuxRunner()

    launched = start_so_session(command, cfg, runner=runner, session_id="so-test")

    assert launched.session_id == "so-test"
    assert launched.status == "running"
    assert runner.calls[0]["argv"][:2] == ["ssh", "zeke-pc"]
    assert "tmux new-session" in runner.calls[0]["argv"][2]
    # calls[1] is the readiness capture-pane poll; the prompt lands in calls[2],
    # with Enter sent separately in calls[3].
    assert "tmux capture-pane" in runner.calls[1]["argv"][2]
    assert "tmux send-keys" in runner.calls[2]["argv"][2]
    assert "z-debug" in runner.calls[2]["argv"][2]
    assert "fix blah" in runner.calls[2]["argv"][2]
    assert runner.calls[3]["argv"][2].strip().endswith("Enter")

    continued = send_to_so_session("so-test", "continue", cfg, runner=runner)
    read_back = read_so_session("so-test", cfg, runner=runner)

    assert continued.turn_count == 2
    assert read_back.status == "needs_input"
    assert SoSessionStore.from_config(cfg).get("so-test").last_output == "Need input?\n>"


def test_deterministic_watcher_script_runs_one_poll(monkeypatch, capsys):
    calls = []

    def fake_load_config(repo_root):
        calls.append(("load_config", repo_root))
        return "cfg"

    def fake_poll(config, *, ttl_seconds=None):
        calls.append(("poll", config, ttl_seconds))
        return {"checked": ["so-test"], "needs_input": ["so-test"]}

    monkeypatch.setattr(so_watcher, "load_config", fake_load_config)
    monkeypatch.setattr(so_watcher, "poll_so_sessions", fake_poll)

    assert so_watcher.main(["--repo-root", "/repo", "--ttl-seconds", "7"]) == 0

    assert calls == [("load_config", "/repo"), ("poll", "cfg", 7)]
    assert '"needs_input": ["so-test"]' in capsys.readouterr().out
