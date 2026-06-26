"""Hermes ``so`` MCP orchestrator with internal tmux lifecycle ownership."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
from typing import Any, Optional, Protocol
from uuid import uuid4

from hermes.config import DiscordProjectAlias, HermesConfig, load_config

STATE_FILENAME = "so-mcp-sessions.json"
CAPTURE_LIMIT = 120


class SoMcpError(RuntimeError):
    """MCP orchestrator operation failed."""


class CommandRunner(Protocol):
    def run(
        self,
        argv: list[str],
        *,
        cwd: Optional[str] = None,
        env: Optional[dict[str, str]] = None,
        timeout: Optional[int] = None,
    ) -> subprocess.CompletedProcess[str]:
        ...


class SubprocessCommandRunner:
    def run(
        self,
        argv: list[str],
        *,
        cwd: Optional[str] = None,
        env: Optional[dict[str, str]] = None,
        timeout: Optional[int] = None,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            argv,
            cwd=cwd,
            env=env,
            timeout=timeout,
            capture_output=True,
            text=True,
            check=False,
        )


@dataclass
class SoSessionRecord:
    session_id: str
    host: str
    project: str
    task: str
    z_command: Optional[str]
    requester_user_id: str = ""
    discord_channel_id: str = ""
    discord_message_id: str = ""
    discord_thread_id: str = ""
    repo_root: str = ""
    execution_host: str = "local"
    transport: str = "local"
    ssh_target: str = ""
    workdir: str = ""
    tmux_session: str = ""
    status: str = "created"
    turn_count: int = 0
    created_at: str = ""
    updated_at: str = ""
    last_output: str = ""
    last_exit_code: int = 0

    @property
    def job_id(self) -> str:
        """Compatibility for existing Discord response formatting."""
        return self.session_id


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_session_id(now: Optional[datetime] = None) -> str:
    stamp = (now or datetime.now(timezone.utc)).strftime("%Y%m%dT%H%M%SZ")
    return f"so-{stamp}-{uuid4().hex[:8]}"


def tmux_session_name(session_id: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", session_id).strip("-")
    return f"hermes-so-{safe}"


def state_path(config: HermesConfig) -> Path:
    return Path(config.paths.hermes_state_root).expanduser() / STATE_FILENAME


class SoSessionStore:
    def __init__(self, path: str | Path):
        self.path = Path(path).expanduser()
        self.path.parent.mkdir(parents=True, exist_ok=True)

    @classmethod
    def from_config(cls, config: HermesConfig) -> "SoSessionStore":
        return cls(state_path(config))

    def load(self) -> dict[str, SoSessionRecord]:
        try:
            raw = json.loads(self.path.read_text())
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return {}
        if not isinstance(raw, dict):
            return {}
        records: dict[str, SoSessionRecord] = {}
        for sid, data in raw.items():
            if not isinstance(data, dict):
                continue
            try:
                records[str(sid)] = SoSessionRecord(**data)
            except TypeError:
                continue
        return records

    def save_all(self, records: dict[str, SoSessionRecord]) -> None:
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(
            json.dumps(
                {sid: asdict(record) for sid, record in records.items()},
                indent=2,
                sort_keys=True,
            )
        )
        tmp.replace(self.path)

    def save(self, record: SoSessionRecord) -> SoSessionRecord:
        records = self.load()
        records[record.session_id] = record
        self.save_all(records)
        return record

    def get(self, session_id: str) -> Optional[SoSessionRecord]:
        return self.load().get(session_id)

    def list(self) -> list[SoSessionRecord]:
        return sorted(
            self.load().values(),
            key=lambda record: record.updated_at or record.created_at,
            reverse=True,
        )


def build_initial_prompt(command: Any, session_id: str) -> str:
    z_part = (
        f"Use the z-harness command `{command.z_command}`."
        if command.z_command
        else "Use the appropriate z-harness command for this task."
    )
    return (
        "You are running in a Hermes `so` MCP-managed tmux session. "
        f"Hermes MCP session id: {session_id}. {z_part} "
        f"User task: {command.task}"
    )


def _shell_join(argv: list[str]) -> str:
    return " ".join(shlex.quote(part) for part in argv)


def _run_for_alias(
    alias: DiscordProjectAlias,
    argv: list[str],
    env: dict[str, str],
) -> tuple[list[str], Optional[str]]:
    workdir = alias.workdir or None
    if alias.transport != "ssh":
        return argv, workdir
    if not alias.ssh_target:
        raise SoMcpError("ssh transport requires ssh_target")
    exports = " ".join(
        f"{shlex.quote(key)}={shlex.quote(value)}"
        for key, value in env.items()
        if key.startswith("HERMES_SO_")
    )
    command = _shell_join(argv)
    if exports:
        command = f"{exports} {command}"
    if workdir:
        command = f"cd {shlex.quote(workdir)} && {command}"
    return ["ssh", alias.ssh_target, command], None


def _run_checked(
    runner: CommandRunner,
    alias: DiscordProjectAlias,
    argv: list[str],
    env: dict[str, str],
    *,
    timeout: int = 30,
) -> subprocess.CompletedProcess[str]:
    run_argv, cwd = _run_for_alias(alias, argv, env)
    proc = runner.run(run_argv, cwd=cwd, env=env, timeout=timeout)
    if proc.returncode != 0:
        raise SoMcpError((proc.stderr or proc.stdout or "command failed").strip())
    return proc


def _env(record: SoSessionRecord) -> dict[str, str]:
    env = dict(os.environ)
    env["HERMES_SO_SESSION_ID"] = record.session_id
    env["HERMES_SO_TMUX_SESSION"] = record.tmux_session
    env["HERMES_SO_PROJECT"] = record.project
    env["HERMES_SO_HOST"] = record.host
    return env


def _needs_input(text: str) -> bool:
    lowered = text.lower()
    markers = ("?", "choose", "confirm", "proceed", "waiting", "input")
    return any(marker in lowered for marker in markers)


def _payload(record: SoSessionRecord) -> dict[str, Any]:
    data = asdict(record)
    data["needs_input"] = _needs_input(record.last_output)
    data["job_id"] = record.session_id
    return data


def _record_from_command(command: Any, session_id: str) -> SoSessionRecord:
    alias = command.project_alias
    now = utc_now()
    return SoSessionRecord(
        session_id=session_id,
        host=command.host,
        project=command.project,
        task=command.task,
        z_command=command.z_command,
        requester_user_id=command.requester_user_id,
        discord_channel_id=command.discord_channel_id,
        discord_message_id=command.discord_message_id,
        discord_thread_id=command.discord_thread_id or command.discord_channel_id,
        repo_root=alias.repo_root,
        execution_host=alias.execution_host,
        transport=alias.transport,
        ssh_target=alias.ssh_target,
        workdir=alias.workdir,
        tmux_session=tmux_session_name(session_id),
        status="created",
        created_at=now,
        updated_at=now,
    )


def start_so_session(
    command: Any,
    config: HermesConfig,
    *,
    runner: Optional[CommandRunner] = None,
    store: Optional[SoSessionStore] = None,
    session_id: Optional[str] = None,
) -> SoSessionRecord:
    runner = runner or SubprocessCommandRunner()
    store = store or SoSessionStore.from_config(config)
    sid = session_id or new_session_id()
    record = _record_from_command(command, sid)
    store.save(record)
    alias = command.project_alias
    env = _env(record)
    try:
        _run_checked(
            runner,
            alias,
            ["tmux", "new-session", "-d", "-s", record.tmux_session, command.host],
            env,
        )
        prompt = build_initial_prompt(command, sid)
        _run_checked(
            runner,
            alias,
            ["tmux", "send-keys", "-t", record.tmux_session, prompt, "C-m"],
            env,
        )
        record.status = "running"
        record.turn_count = 1
        record.updated_at = utc_now()
    except SoMcpError:
        record.status = "failed"
        record.updated_at = utc_now()
        store.save(record)
        raise
    store.save(record)
    return record


def send_to_so_session(
    session_id: str,
    message: str,
    config: HermesConfig,
    *,
    runner: Optional[CommandRunner] = None,
    store: Optional[SoSessionStore] = None,
) -> SoSessionRecord:
    runner = runner or SubprocessCommandRunner()
    store = store or SoSessionStore.from_config(config)
    record = store.get(session_id)
    if record is None:
        raise SoMcpError(f"session not found: {session_id}")
    alias = config.discord.so.project_aliases.get(record.project)
    if alias is None:
        raise SoMcpError(f"project alias not configured: {record.project}")
    _run_checked(
        runner,
        alias,
        ["tmux", "send-keys", "-t", record.tmux_session, message, "C-m"],
        _env(record),
    )
    record.turn_count += 1
    record.status = "running"
    record.updated_at = utc_now()
    store.save(record)
    return record


def read_so_session(
    session_id: str,
    config: HermesConfig,
    *,
    runner: Optional[CommandRunner] = None,
    store: Optional[SoSessionStore] = None,
    limit: int = CAPTURE_LIMIT,
) -> SoSessionRecord:
    runner = runner or SubprocessCommandRunner()
    store = store or SoSessionStore.from_config(config)
    record = store.get(session_id)
    if record is None:
        raise SoMcpError(f"session not found: {session_id}")
    alias = config.discord.so.project_aliases.get(record.project)
    if alias is None:
        raise SoMcpError(f"project alias not configured: {record.project}")
    proc = _run_checked(
        runner,
        alias,
        ["tmux", "capture-pane", "-p", "-t", record.tmux_session, "-S", f"-{limit}"],
        _env(record),
    )
    record.last_output = proc.stdout.strip()
    record.last_exit_code = proc.returncode
    record.status = "needs_input" if _needs_input(record.last_output) else "running"
    record.updated_at = utc_now()
    store.save(record)
    return record


try:
    from mcp.server.fastmcp import FastMCP
except ImportError:  # pragma: no cover
    FastMCP = None  # type: ignore[assignment]


mcp = FastMCP("Hermes so orchestrator") if FastMCP is not None else None


if mcp is not None:

    @mcp.tool()
    def so_start_session(
        host: str,
        project: str,
        task: str,
        z_command: Optional[str] = None,
        requester_user_id: str = "",
        discord_channel_id: str = "",
        discord_message_id: str = "",
        discord_thread_id: str = "",
    ) -> dict[str, Any]:
        """Start an MCP-managed tmux session and return structured state."""
        from hermes.discord_relay import SoCommand

        config = load_config(os.environ.get("Z_HARNESS_REPO", "."))
        alias = config.discord.so.project_aliases.get(project)
        if alias is None:
            return {"ok": False, "error": f"unknown project: {project}"}
        command = SoCommand(
            host=host,
            project=project,
            project_alias=alias,
            task=task,
            z_command=z_command,
            requester_user_id=requester_user_id,
            discord_channel_id=discord_channel_id,
            discord_message_id=discord_message_id,
            discord_thread_id=discord_thread_id,
        )
        try:
            record = start_so_session(command, config)
        except SoMcpError as exc:
            return {"ok": False, "error": str(exc)}
        return {"ok": True, "session_id": record.session_id, **_payload(record)}

    @mcp.tool()
    def so_send(session_id: str, message: str) -> dict[str, Any]:
        """Send a message to an MCP-managed tmux session."""
        config = load_config(os.environ.get("Z_HARNESS_REPO", "."))
        try:
            record = send_to_so_session(session_id, message, config)
        except SoMcpError as exc:
            return {"ok": False, "session_id": session_id, "error": str(exc)}
        return {"ok": True, **_payload(record)}

    @mcp.tool()
    def so_read(session_id: str) -> dict[str, Any]:
        """Capture output on demand and report whether it appears to need input."""
        config = load_config(os.environ.get("Z_HARNESS_REPO", "."))
        try:
            record = read_so_session(session_id, config)
        except SoMcpError as exc:
            return {"ok": False, "session_id": session_id, "error": str(exc)}
        return {"ok": True, "output": record.last_output, **_payload(record)}

    @mcp.tool()
    def so_list_sessions() -> dict[str, Any]:
        """List all MCP-managed ``so`` sessions."""
        config = load_config(os.environ.get("Z_HARNESS_REPO", "."))
        records = SoSessionStore.from_config(config).list()
        return {"sessions": [_payload(record) for record in records], "count": len(records)}


def main(argv: list[str] | None = None) -> int:
    if mcp is None:
        raise SystemExit("mcp package is not installed")
    mcp.run()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
