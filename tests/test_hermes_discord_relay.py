"""Tests for Hermes Discord relay configuration and `so` signal routing."""

from pathlib import Path
import sys

SCRIPTS_DIR = Path(__file__).parent.parent / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from hermes.config import HermesConfig, load_config  # noqa: E402
from hermes.discord_relay import (  # noqa: E402
    HermesDiscordClient,
    is_so_prefix,
    so_entry_prompt,
)


class FakeChannel:
    def __init__(self):
        self.sent = []

    async def send(self, message):
        self.sent.append(message)


async def _fake_fetch_channel(channel_id):
    assert channel_id == 123
    return FakeChannel()


def test_load_config_reads_so_authorization_and_aliases(tmp_path):
    (tmp_path / "hermes-config.yaml").write_text(
        """
        discord:
          user_id: "42"
          so:
            allowed_user_ids: ["42", "43"]
            allowed_channel_ids: ["100"]
            allowed_hosts: [omp]
            project_aliases:
              qt-bot:
                repo_root: ssh://zeke-pc/qt-bot
                execution_host: zeke-pc
                transport: ssh
                ssh_target: zeke-pc
                workdir: /home/zeke/dev/qt-bot
        """
    )

    cfg = load_config(str(tmp_path))

    assert cfg.discord.so.allowed_user_ids == {"42", "43"}
    assert cfg.discord.so.allowed_channel_ids == {"100"}
    assert cfg.discord.so.allowed_hosts == {"omp"}
    alias = cfg.discord.so.project_aliases["qt-bot"]
    assert alias.execution_host == "zeke-pc"
    assert alias.transport == "ssh"
    assert alias.workdir == "/home/zeke/dev/qt-bot"


def test_relay_exposes_only_signal_routing_for_so():
    assert not hasattr(HermesDiscordClient, "parse_so_command")
    assert hasattr(HermesDiscordClient, "_poll_so_signals")
    assert hasattr(HermesDiscordClient, "_route_so_signal")
    assert not hasattr(HermesDiscordClient, "launch_accepted_so_command")


def test_so_prefix_detection_is_thin():
    assert is_so_prefix("so omp z-harness fix x")
    assert is_so_prefix("  so")
    assert not is_so_prefix("soup")
    assert "Raw message: so omp z-harness fix x" in so_entry_prompt(
        "so omp z-harness fix x"
    )


def test_on_message_routes_authorized_raw_so_to_hermes():
    import asyncio
    from types import SimpleNamespace

    cfg = HermesConfig()
    cfg.discord.so.allowed_user_ids = {"42"}
    cfg.discord.so.allowed_channel_ids = {"100"}
    client = object.__new__(HermesDiscordClient)
    client.config = cfg
    routed = []

    async def route(message, prompt):
        routed.append((message.content, prompt))

    client._route_so_entry = route
    message = SimpleNamespace(
        content="so omp z harness repo fix x",
        author=SimpleNamespace(id=42, bot=False),
        channel=SimpleNamespace(id=100),
    )

    asyncio.run(client.on_message(message))

    assert routed[0][0] == "so omp z harness repo fix x"
    assert "Parse the host, project, task" in routed[0][1]


def test_on_message_rejects_unauthorized_so():
    import asyncio
    from types import SimpleNamespace

    cfg = HermesConfig()
    cfg.discord.so.allowed_user_ids = {"42"}
    cfg.discord.so.allowed_channel_ids = {"100"}
    client = object.__new__(HermesDiscordClient)
    client.config = cfg
    channel = FakeChannel()
    message = SimpleNamespace(
        content="so omp fix x",
        author=SimpleNamespace(id=99, bot=False),
        channel=channel,
    )

    asyncio.run(client.on_message(message))

    assert channel.sent == ["Not authorized to use Hermes `so` here."]


def test_route_so_signal_sends_to_discord_thread(monkeypatch):
    import asyncio

    client = object.__new__(HermesDiscordClient)
    channel = FakeChannel()

    async def fetch_channel(channel_id):
        assert channel_id == 123
        return channel

    client.fetch_channel = fetch_channel

    asyncio.run(
        client._route_so_signal(
            {
                "session_id": "so-test",
                "discord_thread_id": "123",
                "text": "Proceed?",
            }
        )
    )

    assert channel.sent == [
        "Hermes MCP session `so-test` needs attention.\n\nProceed?"
    ]
