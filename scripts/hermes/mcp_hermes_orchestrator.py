"""Hermes ``so`` MCP orchestrator with internal tmux lifecycle ownership."""

from __future__ import annotations

from dataclasses import asdict, dataclass, fields
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import time
from typing import Any, Callable, Optional, Protocol
from uuid import uuid4

SCRIPTS_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from hermes.config import DiscordProjectAlias, HermesConfig, load_config

STATE_FILENAME = "so-mcp-sessions.json"
SIGNAL_FILENAME = "so-mcp-signals.jsonl"
CAPTURE_LIMIT = 15
DEFAULT_SESSION_TTL_SECONDS = 24 * 60 * 60
TERMINAL_STATUSES = {"dead", "expired", "failed", "closed"}


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



@dataclass(frozen=True)
class SoStartRequest:
    host: str
    project: str
    project_alias: DiscordProjectAlias
    task: str
    z_command: Optional[str]
    requester_user_id: str = ""
    discord_channel_id: str = ""
    discord_message_id: str = ""
    discord_thread_id: str = ""

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
    expires_at: str = ""
    ended_at: str = ""
    last_liveness_at: str = ""
    last_signal_at: str = ""
    last_signal_digest: str = ""

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

def signal_path(config: HermesConfig) -> Path:
    return Path(config.paths.hermes_state_root).expanduser() / SIGNAL_FILENAME


def _parse_time(value: str) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _expired(record: SoSessionRecord, now: datetime) -> bool:
    expires_at = _parse_time(record.expires_at)
    return expires_at is not None and expires_at <= now


def _digest(text: str) -> str:
    import hashlib

    return "sha256:" + hashlib.sha256(text.encode()).hexdigest()


def _session_ttl(config: HermesConfig) -> int:
    raw = os.environ.get("HERMES_SO_SESSION_TTL_SECONDS")
    if raw:
        try:
            return max(0, int(raw))
        except ValueError:
            pass
    return DEFAULT_SESSION_TTL_SECONDS


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
            known = {field.name for field in fields(SoSessionRecord)}
            filtered = {key: value for key, value in data.items() if key in known}
            try:
                records[str(sid)] = SoSessionRecord(**filtered)
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


class SoSignalStore:
    def __init__(self, path: str | Path):
        self.path = Path(path).expanduser()
        self.path.parent.mkdir(parents=True, exist_ok=True)

    @classmethod
    def from_config(cls, config: HermesConfig) -> "SoSignalStore":
        return cls(signal_path(config))

    def append(self, event: dict[str, Any]) -> None:
        with self.path.open("a") as fh:
            fh.write(json.dumps(event, sort_keys=True) + "\n")

    def drain(self) -> list[dict[str, Any]]:
        try:
            lines = self.path.read_text().splitlines()
        except FileNotFoundError:
            return []
        events: list[dict[str, Any]] = []
        for line in lines:
            if not line.strip():
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(event, dict):
                events.append(event)
        self.path.write_text("")
        return events


def _signal_payload(
    record: SoSessionRecord,
    event: str,
    text: str,
    options: Optional[list[str]] = None,
) -> dict[str, Any]:
    return {
        "event": event,
        "session_id": record.session_id,
        "job_id": record.session_id,
        "status": record.status,
        "project": record.project,
        "task": record.task,
        "requester_user_id": record.requester_user_id,
        "discord_channel_id": record.discord_channel_id,
        "discord_thread_id": record.discord_thread_id,
        "text": text,
        "options": options if options is not None else [],
        "created_at": utc_now(),
    }


def _emit_signal(
    record: SoSessionRecord,
    config: HermesConfig,
    event: str,
    text: str,
    *,
    store: Optional[SoSignalStore] = None,
    options: Optional[list[str]] = None,
) -> bool:
    """Emit a signal event, debounced by state-stable digest.

    The digest key uses event + record.status (not the tmux output text)
    so repeated reads of the same session state don't re-emit signals.
    """
    digest = _digest(f"{event}\0{record.status}")
    if record.last_signal_digest == digest:
        return False
    (store or SoSignalStore.from_config(config)).append(
        _signal_payload(record, event, text, options)
    )
    record.last_signal_at = utc_now()
    record.last_signal_digest = digest
    return True


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


# --- spawn robustness: avoid the send-keys/Enter race against a booting TUI ---
#: How many times to poll capture-pane for a painted first frame before giving up.
_TUI_READY_ATTEMPTS = 40
#: Seconds between readiness polls (40 * 0.25 = up to 10s bounded wait).
_TUI_READY_INTERVAL = 0.25
#: Settle gap between typing the prompt and sending the submit Enter, so the
#: TUI's bracketed-paste closes before Enter arrives.
_SUBMIT_SETTLE_SECONDS = 0.2
#: Indirection so tests can monkeypatch the sleep to a no-op.
_sleep: Callable[[float], None] = time.sleep


def _await_tui_ready(
    runner: CommandRunner,
    alias: DiscordProjectAlias,
    record: SoSessionRecord,
    env: dict[str, str],
) -> bool:
    """Wait until the agent TUI has painted its first frame.

    A freshly created tmux window is not immediately ready for input: a
    ``send-keys`` fired before the TUI paints can land in a half-initialised
    composer where the trailing Enter is swallowed, leaving the prompt typed
    but never submitted (the session then sits idle forever). We poll
    ``capture-pane`` until the pane is non-empty. Best-effort: on timeout we
    return ``False`` and the caller proceeds anyway rather than failing spawn.
    """
    for attempt in range(_TUI_READY_ATTEMPTS):
        argv, cwd = _run_for_alias(
            alias,
            ["tmux", "capture-pane", "-p", "-t", record.tmux_session],
            env,
        )
        proc = runner.run(argv, cwd=cwd, env=env, timeout=15)
        if proc.returncode == 0 and (proc.stdout or "").strip():
            return True
        if attempt < _TUI_READY_ATTEMPTS - 1:
            _sleep(_TUI_READY_INTERVAL)
    return False


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


def _alias_for_record(
    config: HermesConfig,
    record: SoSessionRecord,
) -> DiscordProjectAlias | None:
    alias = config.discord.so.project_aliases.get(record.project)
    if alias is None:
        return None
    return alias


def session_is_alive(
    record: SoSessionRecord,
    config: HermesConfig,
    *,
    runner: Optional[CommandRunner] = None,
) -> bool:
    runner = runner or SubprocessCommandRunner()
    alias = _alias_for_record(config, record)
    if alias is None:
        return False  # can't verify = not alive
    argv, cwd = _run_for_alias(
        alias,
        ["tmux", "has-session", "-t", record.tmux_session],
        _env(record),
    )
    proc = runner.run(argv, cwd=cwd, env=_env(record), timeout=15)
    return proc.returncode == 0


def _env(record: SoSessionRecord) -> dict[str, str]:
    env = dict(os.environ)
    env["HERMES_SO_SESSION_ID"] = record.session_id
    env["HERMES_SO_TMUX_SESSION"] = record.tmux_session
    env["HERMES_SO_PROJECT"] = record.project
    env["HERMES_SO_HOST"] = record.host
    return env


def _needs_input(text: str) -> bool:
    """Detect whether omp is actually waiting for user input.

    Checks the LAST 3 lines of captured output for omp's prompt character
    (❯ or >) at the END of a line — NOT a broad substring match.
    omp's TUI shows `❯` as the input prompt when it is waiting.
    Claude Code shows `> ` as a prompt continuation.
    Garbage like \"? for keyboard shortcuts\" is NOT matched.
    """
    lines = [line.rstrip() for line in text.strip().splitlines() if line.strip()]
    # Prompt-char check stays tight (last 3 lines) to avoid matching a stray
    # '>' inside code/box-drawing output.
    for line in lines[-3:]:
        stripped = line.strip()
        # omp prompt: line ending with ❯ or >
        if stripped.endswith("❯") or stripped.endswith(">"):
            return True
        # Claude Code prompt: bare > on its own line
        if stripped == ">":
            return True
    # Interactive selection menus (omp Accept/Defer/Reject, Claude option
    # pickers) don't end in a prompt char — they render an options list with a
    # navigation footer, sometimes below a trailing separator rule. Scan a
    # slightly wider tail for those footer hints. The phrases are specific
    # enough that a broad substring match is safe here.
    for line in lines[-8:]:
        low = line.strip().lower()
        if "enter select" in low or "esc cancel" in low:
            return True
    return False


#: Navigation-footer phrases that mark a selection menu but carry no answer
#: value themselves — dropped from the extracted context.
_MENU_FOOTER_HINTS = ("up/down", "enter select", "esc cancel", "tab ")


def _is_rule(stripped: str) -> bool:
    """True for a pure box-drawing separator rule (─, —, -, =, _)."""
    return bool(stripped) and all(ch in "─—-=_" for ch in stripped)


def _extract_needs_input_context(text: str, *, limit: int = 1600) -> str:
    """Turn a raw needs_input pane into an answerable question+options summary.

    The captured tmux pane is dominated by box-drawing rules and a navigation
    footer, and a blind ``[-N:]`` tail slice can cut the actual question off the
    top (exactly what happened when a 9h-parked retro menu reached Discord as a
    header-less box dump). This strips separator rules, unwraps ``│ … │`` box
    rows to their inner text, and drops the ``up/down … enter select`` footer,
    leaving the prompt prose and option labels. Best-effort: if nothing
    survives (unknown TUI shape), fall back to the raw tail so no signal is
    ever emitted empty.
    """
    cleaned: list[str] = []
    for raw in text.strip().splitlines():
        stripped = raw.strip()
        if not stripped or _is_rule(stripped):
            continue
        low = stripped.lower()
        if any(hint in low for hint in _MENU_FOOTER_HINTS):
            continue
        # Unwrap box rows: strip leading/trailing vertical borders + padding.
        inner = stripped.strip("│|").strip()
        if inner:
            cleaned.append(inner)
    summary = "\n".join(cleaned).strip()
    if not summary:
        return text.strip()[-limit:]
    # Keep the TAIL of the cleaned block: the live question/options sit at the
    # bottom of the pane, above the footer we already dropped.
    return summary[-limit:]


def _extract_menu_options(text: str) -> list[str]:
    """Pull the ordered option labels out of a box-drawn selection menu.

    Each option is a ``│ Label │`` row; some options carry an indented
    ``│    description │`` row directly below them. Only the flush label rows
    are option text — indented rows, separator rules, the nav footer, and any
    question prose above the box are not options. Returns ``[]`` when the pane
    has no box-drawn menu (e.g. a bare ``❯`` prompt).
    """
    options: list[str] = []
    for raw in text.strip("\n").splitlines():
        stripped = raw.strip()
        if not stripped or _is_rule(stripped):
            continue
        low = stripped.lower()
        if any(hint in low for hint in _MENU_FOOTER_HINTS):
            continue
        if len(stripped) < 2 or not (stripped.startswith("│") and stripped.endswith("│")):
            continue
        inner = stripped[1:-1]
        # Strip the single mandatory padding space; anything left starting
        # with whitespace is an indented description row, not a label.
        if inner.startswith(" "):
            inner = inner[1:]
        if inner.strip() and inner[:1].isspace():
            continue
        label = inner.strip()
        if label:
            options.append(label)
    return options


def _payload(record: SoSessionRecord) -> dict[str, Any]:
    data = asdict(record)
    data["needs_input"] = _needs_input(record.last_output)
    data["job_id"] = record.session_id
    return data

def _allowed(value: str, allowed_values: set[str]) -> bool:
    return not allowed_values or value in allowed_values


def authorize_so_start(
    config: HermesConfig,
    *,
    host: str,
    requester_user_id: str = "",
    discord_channel_id: str = "",
) -> None:
    """Enforce the deterministic auth envelope; parsing stays with the LLM."""
    if not _allowed(requester_user_id, config.discord.so.allowed_user_ids):
        raise SoMcpError("requester is not authorized for so")
    if not _allowed(discord_channel_id, config.discord.so.allowed_channel_ids):
        raise SoMcpError("channel is not authorized for so")
    if not _allowed(host, config.discord.so.allowed_hosts):
        raise SoMcpError(f"host is not authorized for so: {host}")


def _record_from_command(
    command: Any,
    session_id: str,
    *,
    ttl_seconds: int = DEFAULT_SESSION_TTL_SECONDS,
) -> SoSessionRecord:
    alias = command.project_alias
    now_dt = datetime.now(timezone.utc)
    now = now_dt.isoformat()
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
        expires_at=(now_dt + timedelta(seconds=ttl_seconds)).isoformat(),
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
    record = _record_from_command(command, sid, ttl_seconds=_session_ttl(config))
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
        # Wait for the TUI to paint, then type the prompt and submit Enter as a
        # SEPARATE keystroke. Sending prompt + "C-m" in one call races the
        # booting composer's bracketed-paste and the Enter gets swallowed,
        # leaving the session stuck with an unsubmitted prompt.
        _await_tui_ready(runner, alias, record, env)
        _run_checked(
            runner,
            alias,
            ["tmux", "send-keys", "-t", record.tmux_session, "-l", prompt],
            env,
        )
        _sleep(_SUBMIT_SETTLE_SECONDS)
        _run_checked(
            runner,
            alias,
            ["tmux", "send-keys", "-t", record.tmux_session, "Enter"],
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
    alias = _alias_for_record(config, record)
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
    record.last_signal_digest = ""
    record.updated_at = utc_now()
    store.save(record)
    return record


def navigate_so_session(
    session_id: str,
    option_index: int,
    config: HermesConfig,
    *,
    runner: Optional[CommandRunner] = None,
    store: Optional[SoSessionStore] = None,
) -> SoSessionRecord:
    """Drive a reaction-index selection into the session's tmux pane.

    Re-reads the pane and only sends keystrokes if it is CURRENTLY at a menu
    (``_extract_menu_options`` non-empty) and ``option_index`` is in range.
    Otherwise this is a benign no-op — the reaction may have landed after the
    menu moved on, and stray keystrokes into a non-menu pane would be worse
    than doing nothing.
    """
    runner = runner or SubprocessCommandRunner()
    store = store or SoSessionStore.from_config(config)
    record = store.get(session_id)
    if record is None:
        raise SoMcpError(f"session not found: {session_id}")
    alias = _alias_for_record(config, record)
    if alias is None:
        raise SoMcpError(f"project alias not configured: {record.project}")
    env = _env(record)
    proc = _run_checked(
        runner,
        alias,
        ["tmux", "capture-pane", "-p", "-t", record.tmux_session],
        env,
    )
    options = _extract_menu_options(proc.stdout or "")
    if not options or not (0 <= option_index < len(options)):
        # Fail-safe: not a menu right now, or index no longer valid — send
        # nothing and leave the record untouched.
        return record
    for _ in range(option_index):
        _run_checked(
            runner,
            alias,
            ["tmux", "send-keys", "-t", record.tmux_session, "Down"],
            env,
        )
    _run_checked(
        runner,
        alias,
        ["tmux", "send-keys", "-t", record.tmux_session, "Enter"],
        env,
    )
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
    alias = _alias_for_record(config, record)
    if alias is None:
        record.status = "dead"
        record.ended_at = utc_now()
        record.updated_at = record.ended_at
        _emit_signal(
            record,
            config,
            "so_session_dead",
            f"Hermes MCP session `{record.session_id}` has no configured project alias.",
        )
        store.save(record)
        raise SoMcpError(f"project alias not configured: {record.project}")
    try:
        proc = _run_checked(
            runner,
            alias,
            [
                "tmux",
                "capture-pane",
                "-p",
                "-t",
                record.tmux_session,
                "-S",
                f"-{limit}",
            ],
            _env(record),
        )
    except SoMcpError:
        record.status = "dead"
        record.ended_at = utc_now()
        record.updated_at = record.ended_at
        _emit_signal(
            record,
            config,
            "so_session_dead",
            f"Hermes MCP session `{record.session_id}` is no longer alive.",
        )
        store.save(record)
        raise
    record.last_output = proc.stdout.strip()
    record.last_exit_code = proc.returncode
    new_status = "needs_input" if _needs_input(record.last_output) else "running"
    # Only emit signal on actual transition — not every repeat poll
    old_status = record.status
    if new_status != old_status:
        record.status = new_status
        if old_status == "running" and new_status == "needs_input":
            # Use stable digest: event + status only, not changing tmux text
            _emit_signal(
                record,
                config,
                "so_needs_input",
                _extract_needs_input_context(record.last_output),
                options=_extract_menu_options(record.last_output),
            )
    record.updated_at = utc_now()
    store.save(record)
    return record


def reap_so_sessions(
    config: HermesConfig,
    *,
    runner: Optional[CommandRunner] = None,
    store: Optional[SoSessionStore] = None,
    ttl_seconds: Optional[int] = None,
) -> dict[str, list[str]]:
    runner = runner or SubprocessCommandRunner()
    store = store or SoSessionStore.from_config(config)
    ttl = _session_ttl(config) if ttl_seconds is None else max(0, ttl_seconds)
    records = store.load()
    now = datetime.now(timezone.utc)
    changed = False
    dead: list[str] = []
    expired: list[str] = []
    removed: list[str] = []

    for session_id, record in list(records.items()):
        if record.status in TERMINAL_STATUSES:
            ended = _parse_time(record.ended_at or record.updated_at)
            if ended is not None and now - ended >= timedelta(seconds=ttl):
                removed.append(session_id)
                del records[session_id]
                changed = True
            continue

        record.last_liveness_at = now.isoformat()
        if _expired(record, now):
            record.status = "expired"
            record.ended_at = now.isoformat()
            record.updated_at = record.ended_at
            _emit_signal(
                record,
                config,
                "so_session_expired",
                f"Hermes MCP session `{session_id}` exceeded its TTL.",
            )
            expired.append(session_id)
            changed = True
            continue

        if not session_is_alive(record, config, runner=runner):
            record.status = "dead"
            record.ended_at = now.isoformat()
            record.updated_at = record.ended_at
            _emit_signal(
                record,
                config,
                "so_session_dead",
                f"Hermes MCP session `{session_id}` tmux pane is gone.",
            )
            dead.append(session_id)
            changed = True

    if changed:
        store.save_all(records)
    return {"dead": dead, "expired": expired, "removed": removed}


def poll_so_sessions(
    config: HermesConfig,
    *,
    runner: Optional[CommandRunner] = None,
    store: Optional[SoSessionStore] = None,
    ttl_seconds: Optional[int] = None,
) -> dict[str, Any]:
    """Capture active sessions once, emit input signals, then reap stale records."""
    runner = runner or SubprocessCommandRunner()
    store = store or SoSessionStore.from_config(config)
    checked: list[str] = []
    needs_input: list[str] = []
    errors: dict[str, str] = {}

    for record in store.list():
        if record.status in TERMINAL_STATUSES:
            continue
        try:
            updated = read_so_session(
                record.session_id,
                config,
                runner=runner,
                store=store,
            )
            checked.append(record.session_id)
            if updated.status == "needs_input":
                needs_input.append(record.session_id)
        except SoMcpError as exc:
            errors[record.session_id] = str(exc)

    reaped = reap_so_sessions(
        config,
        runner=runner,
        store=store,
        ttl_seconds=ttl_seconds,
    )
    return {
        "checked": checked,
        "needs_input": needs_input,
        "errors": errors,
        "reaped": reaped,
    }


def drain_signal_events(config: HermesConfig) -> list[dict[str, Any]]:
    return SoSignalStore.from_config(config).drain()


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
        config = load_config(os.environ.get("Z_HARNESS_REPO", "."))
        try:
            authorize_so_start(
                config,
                host=host,
                requester_user_id=requester_user_id,
                discord_channel_id=discord_channel_id,
            )
            alias = config.discord.so.project_aliases.get(project)
            if alias is None:
                return {"ok": False, "error": f"unknown project: {project}"}
            command = SoStartRequest(
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
    def so_reap_sessions(ttl_seconds: Optional[int] = None) -> dict[str, Any]:
        """Check tmux liveness, expire old sessions, and prune terminal records."""
        config = load_config(os.environ.get("Z_HARNESS_REPO", "."))
        return {"ok": True, **reap_so_sessions(config, ttl_seconds=ttl_seconds)}

    @mcp.tool()
    def so_drain_signals() -> dict[str, Any]:
        """Drain Discord-routable session lifecycle/input events."""
        config = load_config(os.environ.get("Z_HARNESS_REPO", "."))
        events = drain_signal_events(config)
        return {"events": events, "count": len(events)}

    @mcp.tool()
    def so_list_sessions() -> dict[str, Any]:
        """List all MCP-managed ``so`` sessions."""
        config = load_config(os.environ.get("Z_HARNESS_REPO", "."))
        records = SoSessionStore.from_config(config).list()
        return {
            "sessions": [_payload(record) for record in records],
            "count": len(records),
        }


def main(argv: list[str] | None = None) -> int:
    if mcp is None:
        raise SystemExit("mcp package is not installed")
    mcp.run()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
