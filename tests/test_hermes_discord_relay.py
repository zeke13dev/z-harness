"""Tests for Hermes Discord `so` command intake."""

from pathlib import Path
import sys

import pytest

SCRIPTS_DIR = Path(__file__).parent.parent / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from hermes.config import DiscordProjectAlias, HermesConfig, load_config
from hermes.discord_relay import SoCommandError, parse_so_command


def _config() -> HermesConfig:
    cfg = HermesConfig()
    cfg.discord.user_id = "42"
    cfg.discord.so.allowed_user_ids = {"42"}
    cfg.discord.so.allowed_channel_ids = {"100"}
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


def _parse(content: str, cfg: HermesConfig | None = None):
    return parse_so_command(
        content,
        requester_user_id="42",
        channel_id="100",
        message_id="555",
        config=cfg or _config(),
    )


def test_parse_so_command_with_using():
    command = _parse("so omp qt-bot fix blah using z-debug")

    assert command.host == "omp"
    assert command.project == "qt-bot"
    assert command.task == "fix blah"
    assert command.z_command == "z-debug"
    assert command.requester_user_id == "42"
    assert command.discord_channel_id == "100"
    assert command.discord_message_id == "555"
    assert command.project_alias.workdir == "/home/zeke/dev/qt-bot"


def test_parse_so_command_without_using():
    command = _parse("so omp qt-bot fix blah")

    assert command.task == "fix blah"
    assert command.z_command is None


def test_reject_unknown_host():
    with pytest.raises(SoCommandError, match="Unknown Hermes host"):
        _parse("so claude qt-bot fix blah using z-debug")


def test_reject_unknown_project():
    with pytest.raises(SoCommandError, match="Unknown Hermes project"):
        _parse("so omp missing-project fix blah using z-debug")


def test_reject_unauthorized_requester():
    with pytest.raises(SoCommandError, match="not authorized"):
        parse_so_command(
            "so omp qt-bot fix blah using z-debug",
            requester_user_id="99",
            channel_id="100",
            message_id="555",
            config=_config(),
        )


def test_reject_unauthorized_channel():
    with pytest.raises(SoCommandError, match="channel is not authorized"):
        parse_so_command(
            "so omp qt-bot fix blah using z-debug",
            requester_user_id="42",
            channel_id="200",
            message_id="555",
            config=_config(),
        )


def test_preserve_task_text_exactly_before_using_suffix():
    command = _parse("so omp qt-bot fix  blah / with punctuation using z-debug")

    assert command.task == "fix  blah / with punctuation"


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
