"""MCP-backed orchestration for Discord ``so`` agent sessions.

This module intentionally does not manage tmux panes, watchdog webhooks, or a
Hermes-owned job registry. It follows the proven ``pi-mcp-server.py`` pattern:
run an agent CLI as structured MCP tools, persist lightweight MCP session
metadata, and let callers continue by session id.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import time
from typing import Any, Optional, Protocol
from uuid import uuid4

from hermes.config import DiscordProjectAlias, HermesConfig, load_config

DEFAULT_AGENT = "omp"
DEFAULT_TIMEOUT = 300
STATE_FILENAME = "so-mcp-sessions.json"


class AgentCommandError(RuntimeError):
    """Agent CLI execution failed."""


class CommandRunner(Protocol):
    def run(
        self,
        argv: list[str],
        *,
        cwd: Optional[str] = None,
        env: Optional[dict[str, str]] = None,
        input: Optional[str] = None,
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
        input: Optional[str] = None,
        timeout: Optional[int] = None,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            argv,
            cwd=cwd,
            env=env,
            input=input,
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
    agent_cli: str = DEFAULT_AGENT
    repo_root: str = ""
    execution_host: str = "local"
    transport: str = "local"
    ssh_target: str = ""
    workdir: str = ""
    status: str = "created"
    turn_count: int = 0
    created_at: str = ""
    last_used: str = ""
    last_output: str = ""
    last_exit_code: int = 0

    @property
    def job_id(self) -> str:
        """Compatibility for the Discord adapter response text."""
        return self.session_id


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_session_id(now: Optional[datetime] = None) -> str:
    stamp = (now or datetime.now(timezone.utc)).strftime("%Y%m%dT%H%M%SZ")
    return f"so-{stamp}-{uuid4().hex[:8]}"


def session_state_path(config: HermesConfig) -> Path:
    return Path(config.paths.hermes_state_root).expanduser() / STATE_FILENAME


class SoSessionStore:
    def __init__(self, path: str | Path):
        self.path = Path(path).expanduser()
        self.path.parent.mkdir(parents=True, exist_ok=True)

    @classmethod
    def from_config(cls, config: HermesConfig) -> "SoSessionStore":
        return cls(session_state_path(config))

    def load(self) -> dict[str, SoSessionRecord]:
        try:
            raw = json.loads(self.path.read_text())
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return {}
        records: dict[str, SoSessionRecord] = {}
        if not isinstance(raw, dict):
            return records
        for session_id, data in raw.items():
            if isinstance(data, dict):
                try:
                    records[str(session_id)] = SoSessionRecord(**data)
                except TypeError:
                    continue
        return records

    def save_all(self, records: dict[str, SoSessionRecord]) -> None:
        payload = {sid: asdict(record) for sid, record in records.items()}
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, indent=2, sort_keys=True))
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
            self.load().values(), key=lambda record: record.last_used, reverse=True
        )


def build_initial_so_prompt(command: Any, session_id: str) -> str:
    z_part = (
        f"Use the z-harness command `{command.z_command}`."
        if command.z_command
        else "Use the appropriate z-harness command for this task."
    )
    return (
        "You are running as a Hermes Discord `so` MCP session. "
        f"Hermes session id: {session_id}. "
        f"{z_part} User task: {command.task}"
    )


def _cli_argv(agent_cli: str, session_id: str) -> list[str]:
    session_flag = os.environ.get("HERMES_SO_AGENT_SESSION_FLAG", "--session-id")
    argv = [agent_cli, "-p", "--mode", "text"]
    if session_flag:
        argv.extend([session_flag, session_id])
    return argv


def _run_command_for_alias(
    alias: DiscordProjectAlias,
    *,
    argv: list[str],
    env: dict[str, str],
) -> tuple[list[str], Optional[str]]:
    workdir = alias.workdir or None
    if alias.transport != "ssh":
        return argv, workdir
    if not alias.ssh_target:
        raise AgentCommandError("ssh transport requires ssh_target")
    exports = " ".join(
        f"{shlex.quote(key)}={shlex.quote(value)}"
        for key, value in env.items()
        if key.startswith("HERMES_SO_")
    )
    command = " ".join(shlex.quote(part) for part in argv)
    if exports:
        command = f"{exports} {command}"
    if workdir:
        command = f"cd {shlex.quote(workdir)} && {command}"
    return ["ssh", alias.ssh_target, command], None


def _has_question(output: str) -> bool:
    text = output.lower()
    markers = ("?", "please confirm", "choose", "which", "should i", "proceed")
    return any(marker in text for marker in markers)


def _record_from_command(command: Any, session_id: str, agent_cli: str) -> SoSessionRecord:
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
        agent_cli=agent_cli,
        repo_root=alias.repo_root,
        execution_host=alias.execution_host,
        transport=alias.transport,
        ssh_target=alias.ssh_target,
        workdir=alias.workdir,
        status="created",
        created_at=now,
        last_used=now,
    )


def _execute_turn(
    record: SoSessionRecord,
    alias: DiscordProjectAlias,
    text: str,
    *,
    runner: CommandRunner,
    timeout: int,
) -> SoSessionRecord:
    env = dict(os.environ)
    env["HERMES_SO_SESSION_ID"] = record.session_id
    env["HERMES_SO_PROJECT"] = record.project
    env["HERMES_SO_HOST"] = record.host
    argv, cwd = _run_command_for_alias(
        alias,
        argv=_cli_argv(record.agent_cli, record.session_id),
        env=env,
    )
    start = time.monotonic()
    try:
        proc = runner.run(argv, cwd=cwd, env=env, input=text, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        record.status = "timeout"
        record.last_exit_code = -1
        record.last_output = f"timed out after {time.monotonic() - start:.0f}s"
        raise AgentCommandError(record.last_output) from exc

    record.turn_count += 1
    record.last_used = utc_now()
    record.last_exit_code = int(proc.returncode)
    record.last_output = (proc.stdout or proc.stderr or "").strip()
    if proc.returncode != 0:
        record.status = "failed"
        raise AgentCommandError(
            (proc.stderr or proc.stdout or f"{record.agent_cli} exited {proc.returncode}").strip()
        )
    record.status = "needs_input" if _has_question(record.last_output) else "running"
    return record


def start_so_session(
    command: Any,
    config: HermesConfig,
    *,
    runner: Optional[CommandRunner] = None,
    store: Optional[SoSessionStore] = None,
    session_id: Optional[str] = None,
    agent_cli: str = DEFAULT_AGENT,
    timeout: int = DEFAULT_TIMEOUT,
) -> SoSessionRecord:
    """Start a Discord-authorized ``so`` session through an agent CLI."""
    runner = runner or SubprocessCommandRunner()
    store = store or SoSessionStore.from_config(config)
    sid = session_id or new_session_id()
    record = _record_from_command(command, sid, agent_cli)
    store.save(record)
    prompt = build_initial_so_prompt(command, sid)
    try:
        record = _execute_turn(
            record,
            command.project_alias,
            prompt,
            runner=runner,
            timeout=timeout,
        )
    finally:
        store.save(record)
    return record


def send_to_so_session(
    session_id: str,
    message: str,
    config: HermesConfig,
    *,
    runner: Optional[CommandRunner] = None,
    store: Optional[SoSessionStore] = None,
    timeout: int = DEFAULT_TIMEOUT,
) -> SoSessionRecord:
    runner = runner or SubprocessCommandRunner()
    store = store or SoSessionStore.from_config(config)
    record = store.get(session_id)
    if record is None:
        raise AgentCommandError(f"session not found: {session_id}")
    alias = config.discord.so.project_aliases.get(record.project)
    if alias is None:
        raise AgentCommandError(f"project alias not configured: {record.project}")
    try:
        record = _execute_turn(record, alias, message, runner=runner, timeout=timeout)
    finally:
        store.save(record)
    return record


def _record_payload(record: SoSessionRecord) -> dict[str, Any]:
    payload = asdict(record)
    payload["job_id"] = record.session_id
    payload["has_pending_question"] = _has_question(record.last_output)
    return payload


try:
    from mcp.server.fastmcp import FastMCP
except ImportError:  # pragma: no cover - direct helpers remain usable without MCP.
    FastMCP = None  # type: ignore[assignment]


mcp = FastMCP("Hermes so MCP") if FastMCP is not None else None


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
        timeout: int = DEFAULT_TIMEOUT,
        agent_cli: str = DEFAULT_AGENT,
    ) -> dict[str, Any]:
        """Start an OMP/Claude-code session for a Hermes ``so`` request."""
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
            record = start_so_session(
                command, config, timeout=timeout, agent_cli=agent_cli
            )
        except AgentCommandError as exc:
            return {"ok": False, "error": str(exc)}
        return {"ok": True, **_record_payload(record)}

    @mcp.tool()
    def so_send(
        session_id: str, message: str, timeout: int = DEFAULT_TIMEOUT
    ) -> dict[str, Any]:
        """Send a follow-up message to an existing ``so`` MCP session."""
        config = load_config(os.environ.get("Z_HARNESS_REPO", "."))
        try:
            record = send_to_so_session(session_id, message, config, timeout=timeout)
        except AgentCommandError as exc:
            return {"ok": False, "session_id": session_id, "error": str(exc)}
        return {"ok": True, **_record_payload(record)}

    @mcp.tool()
    def so_list_sessions() -> dict[str, Any]:
        """List known ``so`` MCP sessions."""
        config = load_config(os.environ.get("Z_HARNESS_REPO", "."))
        store = SoSessionStore.from_config(config)
        sessions = [_record_payload(record) for record in store.list()]
        return {"sessions": sessions, "count": len(sessions)}

    @mcp.tool()
    def so_status(session_id: str) -> dict[str, Any]:
        """Return metadata and latest output for one ``so`` MCP session."""
        config = load_config(os.environ.get("Z_HARNESS_REPO", "."))
        store = SoSessionStore.from_config(config)
        record = store.get(session_id)
        if record is None:
            return {"found": False, "session_id": session_id}
        return {"found": True, **_record_payload(record)}

    @mcp.tool()
    def so_instruct(
        host: str,
        project: str,
        instruction: str,
        timeout: int = DEFAULT_TIMEOUT,
        agent_cli: str = DEFAULT_AGENT,
    ) -> dict[str, Any]:
        """Run a one-shot instruction through the configured agent CLI."""
        from hermes.discord_relay import SoCommand

        config = load_config(os.environ.get("Z_HARNESS_REPO", "."))
        alias = config.discord.so.project_aliases.get(project)
        if alias is None:
            return {"ok": False, "error": f"unknown project: {project}"}
        command = SoCommand(
            host=host,
            project=project,
            project_alias=alias,
            task=instruction,
            z_command=None,
            requester_user_id="",
            discord_channel_id="",
            discord_message_id="",
        )
        try:
            record = start_so_session(
                command,
                config,
                timeout=timeout,
                agent_cli=agent_cli,
                session_id=new_session_id(),
            )
        except AgentCommandError as exc:
            return {"ok": False, "error": str(exc)}
        return {"ok": True, **_record_payload(record)}


def main(argv: list[str] | None = None) -> int:
    if mcp is None:
        raise SystemExit("mcp package is not installed")
    mcp.run()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
