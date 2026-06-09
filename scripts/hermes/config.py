"""
config.py — Hermes orchestrator configuration.

Loads hermes-config.yaml from repo root, with env var overrides.
"""

import os
from pathlib import Path
from dataclasses import dataclass, field

try:
    import yaml
except ImportError:
    yaml = None


@dataclass
class DiscordConfig:
    bot_token: str = ""
    user_id: str = ""


@dataclass
class ConcurrencyConfig:
    max_parallel_sessions: int = 3


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
                    config.discord.bot_token = data["discord"].get("bot_token", "")
                    config.discord.user_id = str(data["discord"].get("user_id", ""))
                if "concurrency" in data:
                    config.concurrency.max_parallel_sessions = int(
                        data["concurrency"].get("max_parallel_sessions", 3)
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
                
                break  # Use first found config
            except Exception:
                pass
    
    # Env var overrides
    config.discord.bot_token = _env_override(
        config.discord.bot_token, "HERMES_DISCORD_TOKEN", str
    )
    config.discord.user_id = _env_override(
        config.discord.user_id, "HERMES_DISCORD_USER_ID", str
    )
    config.concurrency.max_parallel_sessions = _env_override(
        config.concurrency.max_parallel_sessions, "HERMES_MAX_PARALLEL", int
    )
    config.retry.max_retries = _env_override(
        config.retry.max_retries, "HERMES_MAX_RETRIES", int
    )
    config.timeouts.per_workstream_minutes = _env_override(
        config.timeouts.per_workstream_minutes, "HERMES_WORKSTREAM_TIMEOUT_MINUTES", int
    )
    
    return config
