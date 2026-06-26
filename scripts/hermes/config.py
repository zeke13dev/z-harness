"""
config.py — Hermes orchestrator configuration.

Loads hermes-config.yaml from repo root. Concurrency, retry, and timeout
knobs are file-only (no HERMES_* env overrides). Discord credentials may
still be overridden via HERMES_DISCORD_TOKEN / HERMES_DISCORD_USER_ID.
"""

import os
from pathlib import Path
from dataclasses import dataclass, field

try:
    import yaml
    _YAML_ERRORS = (yaml.YAMLError,)
except ImportError:
    yaml = None
    _YAML_ERRORS = ()


def _bool_coerce(val: str) -> bool:
    """Parse env var string to bool; handles 0/false/1/true (case-insensitive).

    Python's built-in bool("0") == True, which is the wrong behavior for env
    var overrides. This converter maps falsey strings ("0", "false", "no", "off")
    to False and truthy strings ("1", "true", "yes", "on") to True.
    """
    return val.strip().lower() not in ("0", "false", "no", "off", "")


def _str_set(value) -> set[str]:
    """Normalize scalar/list YAML config values into a string set."""
    if value is None:
        return set()
    if isinstance(value, (str, int)):
        text = str(value).strip()
        return {text} if text else set()
    try:
        return {str(item).strip() for item in value if str(item).strip()}
    except TypeError:
        return set()


@dataclass
class DiscordProjectAlias:
    repo_root: str = ""
    execution_host: str = "local"
    transport: str = "local"
    ssh_target: str = ""
    workdir: str = ""


@dataclass
class DiscordSoConfig:
    allowed_user_ids: set[str] = field(default_factory=set)
    allowed_channel_ids: set[str] = field(default_factory=set)
    allowed_hosts: set[str] = field(default_factory=set)
    project_aliases: dict[str, DiscordProjectAlias] = field(default_factory=dict)


@dataclass
class DiscordConfig:
    bot_token: str = ""
    user_id: str = ""
    so: DiscordSoConfig = field(default_factory=DiscordSoConfig)

@dataclass
class ConcurrencyConfig:
    # Default changed from 3 → 1 (sequential-by-default, INV-5: cap=1 reproduces
    # today's sequential behavior; non-1 values activate the parallel scheduler
    # that T010 will wire in).
    max_parallel_workstreams: int = 1
    max_parallel_plans: int = 1
    serialize_all: bool = False
    serialize_high_severity: bool = True


@dataclass
class StallDetectionConfig:
    no_progress_minutes: int = 15


@dataclass
class RetryConfig:
    max_retries: int = 1
    retry_delay_seconds: int = 30


@dataclass
class TimeoutConfig:
    per_workstream_minutes: int = 90


@dataclass
class PathsConfig:
    worktree_base: str = "../"
    hermes_state_root: str = "~/.hermes"


@dataclass
class HermesConfig:
    discord: DiscordConfig = field(default_factory=DiscordConfig)
    concurrency: ConcurrencyConfig = field(default_factory=ConcurrencyConfig)
    stall_detection: StallDetectionConfig = field(default_factory=StallDetectionConfig)
    retry: RetryConfig = field(default_factory=RetryConfig)
    timeouts: TimeoutConfig = field(default_factory=TimeoutConfig)
    paths: PathsConfig = field(default_factory=PathsConfig)


def _env_override(value, env_var: str, coerce=int):
    """Override value if env var is set."""
    env_val = os.environ.get(env_var)
    if env_val is not None:
        try:
            return coerce(env_val)
        except (ValueError, TypeError):
            pass
    return value


def load_config(repo_root: str = ".") -> HermesConfig:
    """Load config from hermes-config.yaml with env overrides."""
    config = HermesConfig()

    # Try loading YAML
    config_paths = [
        Path(repo_root) / "hermes-config.yaml",
        Path.home() / ".config" / "hermes" / "config.yaml",
    ]

    for config_path in config_paths:
        if config_path.exists() and yaml is not None:
            try:
                with open(config_path) as f:
                    data = yaml.safe_load(f) or {}

                if "discord" in data:
                    discord_data = data["discord"] or {}
                    config.discord.bot_token = discord_data.get("bot_token", "")
                    config.discord.user_id = str(discord_data.get("user_id", ""))
                    so_data = discord_data.get("so", {}) or {}
                    config.discord.so.allowed_user_ids = _str_set(
                        so_data.get("allowed_user_ids", discord_data.get("allowed_user_ids"))
                    )
                    config.discord.so.allowed_channel_ids = _str_set(
                        so_data.get("allowed_channel_ids", discord_data.get("allowed_channel_ids"))
                    )
                    config.discord.so.allowed_hosts = _str_set(
                        so_data.get("allowed_hosts", discord_data.get("allowed_so_hosts"))
                    )
                    aliases = so_data.get("project_aliases", discord_data.get("project_aliases", {})) or {}
                    config.discord.so.project_aliases = {
                        str(name): DiscordProjectAlias(
                            repo_root=str(alias.get("repo_root", "")),
                            execution_host=str(alias.get("execution_host", "local")),
                            transport=str(alias.get("transport", "local")),
                            ssh_target=str(alias.get("ssh_target", "")),
                            workdir=str(alias.get("workdir", "")),
                        )
                        for name, alias in aliases.items()
                        if isinstance(alias, dict)
                    }
                if "concurrency" in data:
                    config.concurrency.max_parallel_workstreams = int(
                        data["concurrency"].get("max_parallel_workstreams", 1)
                    )
                    config.concurrency.max_parallel_plans = int(
                        data["concurrency"].get("max_parallel_plans", 1)
                    )
                    config.concurrency.serialize_all = bool(
                        data["concurrency"].get("serialize_all", False)
                    )
                    config.concurrency.serialize_high_severity = bool(
                        data["concurrency"].get("serialize_high_severity", True)
                    )
                if "stall_detection" in data:
                    config.stall_detection.no_progress_minutes = int(
                        data["stall_detection"].get("no_progress_minutes", 15)
                    )
                if "retry" in data:
                    config.retry.max_retries = int(data["retry"].get("max_retries", 1))
                    config.retry.retry_delay_seconds = int(
                        data["retry"].get("retry_delay_seconds", 30)
                    )
                if "timeouts" in data:
                    config.timeouts.per_workstream_minutes = int(
                        data["timeouts"].get("per_workstream_minutes", 90)
                    )
                if "paths" in data:
                    config.paths.worktree_base = data["paths"].get("worktree_base", "../")
                    config.paths.hermes_state_root = data["paths"].get(
                        "hermes_state_root", "~/.hermes"
                    )

                break  # Use first found config
            except (ValueError, TypeError, OSError, *_YAML_ERRORS):
                pass

    # Discord credentials only — concurrency/retry/timeout knobs are file-only.
    config.discord.bot_token = _env_override(
        config.discord.bot_token, "HERMES_DISCORD_TOKEN", str
    )
    config.discord.user_id = _env_override(
        config.discord.user_id, "HERMES_DISCORD_USER_ID", str
    )

    return config
