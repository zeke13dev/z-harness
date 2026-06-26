"""Deprecated tests for the retired Hermes `so` tmux launcher.

Discord `so` session launch was replaced by `hermes.so_mcp`; these tests are
kept for reference only and are not part of active verification.
"""

from pathlib import Path
import subprocess
import sys

import pytest
pytest.skip("deprecated so backend reference tests", allow_module_level=True)


SCRIPTS_DIR = Path(__file__).parent.parent / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from hermes.config import DiscordProjectAlias  # noqa: E402
from hermes.discord_relay import SoCommand  # noqa: E402
from hermes.session import (  # noqa: E402
    TmuxLaunchError,
    hermes_tmux_session_name,
    launch_so_job,
)
from hermes.so_jobs import SoJobRegistry  # noqa: E402


class FakeRunner:
    def __init__(
        self, registry: SoJobRegistry | None = None, fail_new: bool = False
    ):
        self.registry = registry
        self.fail_new = fail_new
        self.calls = []
        self.envs = []

    def run(self, argv, *, cwd=None, env=None):
        self.calls.append((list(argv), cwd))
        self.envs.append(dict(env or {}))
        if argv[:2] == ["tmux", "new-session"] and self.fail_new:
            return subprocess.CompletedProcess(argv, 1, "", "new failed")
        if argv[:2] == ["tmux", "display-message"]:
            return subprocess.CompletedProcess(argv, 0, "4321\n", "")
        if argv[:2] == ["tmux", "send-keys"]:
            assert self.registry is not None
            assert self.registry.get("so-test") is not None
        return subprocess.CompletedProcess(argv, 0, "", "")


def _command(*, transport="local") -> SoCommand:
    return SoCommand(
        host="omp",
        project="qt-bot",
        project_alias=DiscordProjectAlias(
            repo_root="ssh://zeke-pc/qt-bot",
            execution_host="zeke-pc" if transport == "ssh" else "local",
            transport=transport,
            ssh_target="zeke-pc" if transport == "ssh" else "",
            workdir="/home/zeke/dev/qt-bot",
        ),
        task="fix blah",
        z_command="z-debug",
        requester_user_id="user-1",
        discord_channel_id="chan-1",
        discord_message_id="msg-1",
        discord_thread_id="thread-1",
    )


def test_launch_creates_tmux_then_sends_initial_prompt(tmp_path):
    registry = SoJobRegistry(tmp_path)
    runner = FakeRunner(registry)

    record = launch_so_job(
        _command(), registry, runner=runner, job_id="so-test"
    )

    assert record.status == "running"
    assert record.tmux_session == "hermes-so-so-test"
    assert record.pid == 4321
    assert runner.calls[0][0][:2] == ["tmux", "new-session"]
    assert runner.calls[1][0][:2] == ["tmux", "display-message"]
    assert runner.calls[2][0][:2] == ["tmux", "send-keys"]
    send_args = runner.calls[2][0]
    assert any("fix blah" in arg for arg in send_args)
    assert any("z-debug" in arg for arg in send_args)
    assert all(env["HERMES_SO_JOB_ID"] == "so-test" for env in runner.envs)

def test_ssh_transport_runs_tmux_on_recorded_host(tmp_path):
    registry = SoJobRegistry(tmp_path)
    runner = FakeRunner(registry)

    record = launch_so_job(
        _command(transport="ssh"), registry, runner=runner, job_id="so-test"
    )

    assert record.execution_host == "zeke-pc"
    assert record.transport == "ssh"
    assert runner.calls[0][0][0:2] == ["ssh", "zeke-pc"]
    assert "HERMES_SO_JOB_ID=so-test" in runner.calls[0][0][2]
    assert "tmux new-session" in runner.calls[0][0][2]


def test_generated_session_name_is_safe():
    assert hermes_tmux_session_name("so/odd id") == "hermes-so-so-odd-id"


def test_registry_write_happens_before_send_keys(tmp_path):
    registry = SoJobRegistry(tmp_path)
    runner = FakeRunner(registry)

    launch_so_job(_command(), registry, runner=runner, job_id="so-test")

    assert registry.get("so-test").status == "running"


def test_launch_failure_marks_job_failed(tmp_path):
    registry = SoJobRegistry(tmp_path)
    runner = FakeRunner(registry, fail_new=True)

    with pytest.raises(TmuxLaunchError, match="new failed"):
        launch_so_job(_command(), registry, runner=runner, job_id="so-test")

    assert registry.get("so-test").status == "failed"
