"""Fake Discord/tmux/OMP e2e for Hermes `so` orchestration."""

from pathlib import Path
import subprocess
import sys

SCRIPTS_DIR = Path(__file__).parent.parent / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from hermes.config import DiscordProjectAlias, HermesConfig  # noqa: E402
from hermes.discord_relay import parse_so_command  # noqa: E402
from hermes.session import launch_so_job  # noqa: E402
from hermes.so_jobs import SoJobRegistry  # noqa: E402
from hermes.supervisor import HermesSupervisor  # noqa: E402
from hermes.watchdog_webhook import (  # noqa: E402
    WatchdogPayload,
    handle_watchdog_payload,
)


class FakeTmuxRunner:
    def __init__(self):
        self.calls = []

    def run(self, argv, *, cwd=None, env=None):
        self.calls.append((list(argv), cwd, dict(env or {})))
        if argv[:2] == ["tmux", "display-message"]:
            return subprocess.CompletedProcess(argv, 0, "4321\n", "")
        return subprocess.CompletedProcess(argv, 0, "", "")


class FakeTmuxIO:
    def __init__(self):
        self.pane_text = "OMP asks: continue?"
        self.sent = []
        self.exists = True
        self.alive = True
        self.aborted = []
        self.restarts = []

    def capture_pane(self, job, *, limit=80):
        return self.pane_text

    def send_keys(self, job, text):
        self.sent.append((job.job_id, text))

    def session_exists(self, job):
        return self.exists

    def pid_alive(self, job):
        return self.alive

    def attach_guidance(self, job):
        return (
            f"Attach on {job.execution_host}: "
            f"tmux attach -t {job.tmux_session}"
        )

    def abort(self, job):
        self.aborted.append(job.job_id)

    def restart(self, job):
        self.restarts.append(job.job_id)
        return "hermes-so-restarted", 5678


class FakeDiscord:
    def __init__(self):
        self.thread_posts = []
        self.ops_posts = []
        self.asks = []
        self.checkups = []

    def post_thread(self, *, channel_id, thread_id, requester_user_id, text):
        self.thread_posts.append(
            (channel_id, thread_id, requester_user_id, text)
        )

    def post_ops(self, text):
        self.ops_posts.append(text)

    def ask_user(self, *, channel_id, thread_id, requester_user_id, text):
        self.asks.append((channel_id, thread_id, requester_user_id, text))

    def post_checkup(self, *, channel_id, thread_id, requester_user_id, text):
        self.checkups.append((channel_id, thread_id, requester_user_id, text))


class FakeSubscriptions:
    def __init__(self):
        self.deliveries = []

    def deliver(self, *, job, payload, text):
        self.deliveries.append((job, payload, text))


def _config() -> HermesConfig:
    cfg = HermesConfig()
    cfg.discord.user_id = "user-1"
    cfg.discord.so.allowed_user_ids = {"user-1"}
    cfg.discord.so.allowed_channel_ids = {"chan-1"}
    cfg.discord.so.allowed_hosts = {"omp"}
    cfg.discord.so.project_aliases = {
        "qt-bot": DiscordProjectAlias(
            repo_root="ssh://zeke-pc/qt-bot",
            execution_host="zeke-pc",
            transport="ssh",
            ssh_target="zeke-pc",
            workdir="/home/zeke/dev/qt-bot",
        )
    }
    return cfg


def test_fake_discord_to_tmux_to_watchdog_to_reply_flow(tmp_path):
    registry = SoJobRegistry(tmp_path)
    command = parse_so_command(
        "so omp qt-bot fix blah using z-debug",
        requester_user_id="user-1",
        channel_id="chan-1",
        message_id="msg-1",
        thread_id="thread-1",
        config=_config(),
    )
    tmux_runner = FakeTmuxRunner()

    launched = launch_so_job(
        command, registry, runner=tmux_runner, job_id="so-test"
    )

    assert launched.status == "running"
    assert tmux_runner.calls[0][0][:2] == ["ssh", "zeke-pc"]
    assert "tmux new-session" in tmux_runner.calls[0][0][2]
    assert "tmux send-keys" in tmux_runner.calls[2][0][2]
    assert "fix blah" in tmux_runner.calls[2][0][2]
    assert "z-debug" in tmux_runner.calls[2][0][2]

    discord = FakeDiscord()
    payload = WatchdogPayload(
        event="watchdog_stall",
        event_id="evt-1",
        severity="warning",
        reason="agent stalled",
        job_id="so-test",
        run_id="run-1",
    )
    webhook = handle_watchdog_payload(
        payload, registry=registry, discord=discord
    )

    assert webhook.status == "delivered"
    assert webhook.delivered_via == "thread"
    assert discord.thread_posts[0][1] == "thread-1"

    tmux_io = FakeTmuxIO()
    supervisor = HermesSupervisor(
        registry=registry, tmux=tmux_io, discord=discord
    )
    asked = supervisor.inspect_and_ask("so-test")

    assert asked.status == "asked"
    assert "continue?" in discord.asks[0][3]
    assert tmux_io.sent == []

    reply = supervisor.handle_discord_reply(
        channel_id="chan-1",
        thread_id="thread-1",
        requester_user_id="user-1",
        text="continue please",
    )

    assert reply.status == "sent"
    assert tmux_io.sent == [("so-test", "continue please")]
    records = registry.get("so-test").prompt_records
    assert records[-1]["sent_text"] == "continue please"


def test_fake_subscription_fallback_and_checkup_actions(tmp_path):
    registry = SoJobRegistry(tmp_path)
    command = parse_so_command(
        "so omp qt-bot fix blah using z-debug",
        requester_user_id="user-1",
        channel_id="chan-1",
        message_id="msg-1",
        config=_config(),
    )
    launch_so_job(command, registry, runner=FakeTmuxRunner(), job_id="so-test")
    registry.update("so-test", discord_thread_id="")
    discord = FakeDiscord()
    subscriptions = FakeSubscriptions()

    result = handle_watchdog_payload(
        WatchdogPayload(
            event="watchdog_timeout",
            event_id="evt-2",
            severity="error",
            reason="timeout",
            job_id="so-test",
        ),
        registry=registry,
        discord=discord,
        subscriptions=subscriptions,
    )

    assert result.delivered_via == "subscription"
    assert subscriptions.deliveries[0][0].job_id == "so-test"

    tmux_io = FakeTmuxIO()
    supervisor = HermesSupervisor(
        registry=registry, tmux=tmux_io, discord=discord
    )
    tmux_io.exists = False
    dead = supervisor.check_session_health("so-test")
    attach = supervisor.handle_checkup_action("so-test", "attach")
    abort = supervisor.handle_checkup_action("so-test", "abort")
    registry.transition("so-test", "stale")
    restart = supervisor.handle_checkup_action("so-test", "restart")

    assert dead.status == "dead"
    assert attach.status == "attach_guidance"
    assert abort.status == "aborted"
    assert restart.status == "restarted"
    assert tmux_io.aborted == ["so-test"]
    assert tmux_io.restarts == ["so-test"]
