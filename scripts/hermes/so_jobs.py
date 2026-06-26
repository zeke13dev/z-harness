"""Deprecated tmux/job-registry backend for Discord ``so``.

Replaced by ``hermes/so_mcp.py``. This module remains only as historical
reference; production gateway and ``discord_relay`` code must not import it.
Set ``HERMES_ALLOW_DEPRECATED_SO_BACKEND=1`` only for archaeology.
"""

from __future__ import annotations
import os

if os.environ.get("HERMES_ALLOW_DEPRECATED_SO_BACKEND") != "1":
    raise RuntimeError(
        "hermes.so_jobs is deprecated; use hermes.so_mcp for `so` orchestration"
    )


from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Optional
from uuid import uuid4

from hermes.config import HermesConfig

SCHEMA_VERSION = 1
TERMINAL_STATUSES = {"done", "failed", "aborted"}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_job_id(now: Optional[datetime] = None) -> str:
    stamp = (now or datetime.now(timezone.utc)).strftime("%Y%m%dT%H%M%SZ")
    return f"so-{stamp}-{uuid4().hex[:8]}"


@dataclass
class SoJobRecord:
    job_id: str
    discord_channel_id: str
    discord_message_id: str
    discord_thread_id: str
    requester_user_id: str
    host: str
    project: str
    repo_root: str
    execution_host: str
    transport: str
    ssh_target: str
    workdir: str
    z_command: Optional[str]
    task: str
    tmux_session: Optional[str] = None
    pid: Optional[int] = None
    z_harness_run_id: Optional[str] = None
    slug: Optional[str] = None
    status: str = "starting"
    last_pane_digest: Optional[str] = None
    last_progress_at: Optional[str] = None
    last_watchdog_event_id: Optional[str] = None
    prompt_records: list[dict[str, Any]] = field(default_factory=list)
    schema_version: int = SCHEMA_VERSION
    created_at: str = ""
    updated_at: str = ""

    def __post_init__(self) -> None:
        now = utc_now()
        if not self.created_at:
            self.created_at = now
        if not self.updated_at:
            self.updated_at = now

    @property
    def tmux_target(self) -> dict[str, Optional[str]]:
        """Authoritative execution endpoint for tmux operations."""
        return {
            "execution_host": self.execution_host,
            "transport": self.transport,
            "ssh_target": self.ssh_target or None,
            "workdir": self.workdir,
            "tmux_session": self.tmux_session,
        }

    @property
    def pid_target(self) -> dict[str, Optional[str] | int]:
        """Authoritative execution endpoint for pid operations."""
        return {
            "execution_host": self.execution_host,
            "transport": self.transport,
            "ssh_target": self.ssh_target or None,
            "pid": self.pid,
        }


def to_dict(record: SoJobRecord) -> dict[str, Any]:
    data = asdict(record)
    data["schema_version"] = SCHEMA_VERSION
    return data


def from_dict(data: dict[str, Any]) -> SoJobRecord:
    if data.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("unsupported so job schema_version")
    required = [
        "job_id",
        "discord_channel_id",
        "discord_message_id",
        "discord_thread_id",
        "requester_user_id",
        "host",
        "project",
        "repo_root",
        "execution_host",
        "transport",
        "ssh_target",
        "workdir",
        "task",
    ]
    missing = [key for key in required if key not in data]
    if missing:
        raise ValueError(f"missing so job fields: {', '.join(missing)}")
    return SoJobRecord(
        job_id=str(data["job_id"]),
        discord_channel_id=str(data["discord_channel_id"]),
        discord_message_id=str(data["discord_message_id"]),
        discord_thread_id=str(data["discord_thread_id"]),
        requester_user_id=str(data["requester_user_id"]),
        host=str(data["host"]),
        project=str(data["project"]),
        repo_root=str(data["repo_root"]),
        execution_host=str(data["execution_host"]),
        transport=str(data["transport"]),
        ssh_target=str(data["ssh_target"]),
        workdir=str(data["workdir"]),
        z_command=data.get("z_command"),
        task=str(data["task"]),
        tmux_session=data.get("tmux_session"),
        pid=data.get("pid"),
        z_harness_run_id=data.get("z_harness_run_id"),
        slug=data.get("slug"),
        status=str(data.get("status", "starting")),
        last_pane_digest=data.get("last_pane_digest"),
        last_progress_at=data.get("last_progress_at"),
        last_watchdog_event_id=data.get("last_watchdog_event_id"),
        prompt_records=list(data.get("prompt_records", [])),
        schema_version=int(data.get("schema_version", SCHEMA_VERSION)),
        created_at=str(data.get("created_at", "")),
        updated_at=str(data.get("updated_at", "")),
    )


def registry_dir(config: HermesConfig) -> Path:
    return Path(config.paths.hermes_state_root).expanduser() / "so-jobs"


class SoJobRegistry:
    def __init__(self, root: str | Path):
        self.root = Path(root).expanduser()
        self.root.mkdir(parents=True, exist_ok=True)

    @classmethod
    def from_config(cls, config: HermesConfig) -> "SoJobRegistry":
        return cls(registry_dir(config))

    def path_for(self, job_id: str) -> Path:
        if not job_id or "/" in job_id or "\\" in job_id:
            raise ValueError("invalid job_id")
        return self.root / f"{job_id}.json"

    def save(self, record: SoJobRecord) -> SoJobRecord:
        record.updated_at = utc_now()
        path = self.path_for(record.job_id)
        tmp = path.with_suffix(path.suffix + ".tmp")
        with open(tmp, "w") as f:
            json.dump(to_dict(record), f, indent=2, sort_keys=True)
            f.write("\n")
        tmp.replace(path)
        return record

    def create(self, record: SoJobRecord) -> SoJobRecord:
        path = self.path_for(record.job_id)
        if path.exists():
            raise FileExistsError(record.job_id)
        return self.save(record)

    def get(self, job_id: str) -> Optional[SoJobRecord]:
        path = self.path_for(job_id)
        try:
            with open(path) as f:
                return from_dict(json.load(f))
        except (
            FileNotFoundError,
            json.JSONDecodeError,
            OSError,
            ValueError,
            TypeError,
        ):
            return None

    def list(self) -> list[SoJobRecord]:
        records: list[SoJobRecord] = []
        for path in sorted(self.root.glob("*.json")):
            try:
                with open(path) as f:
                    records.append(from_dict(json.load(f)))
            except (json.JSONDecodeError, OSError, ValueError, TypeError):
                continue
        return records

    def update(self, job_id: str, **changes: Any) -> SoJobRecord:
        record = self.get(job_id)
        if record is None:
            raise KeyError(job_id)
        for key, value in changes.items():
            if not hasattr(record, key):
                raise AttributeError(key)
            setattr(record, key, value)
        return self.save(record)

    def transition(
        self, job_id: str, status: str, **changes: Any
    ) -> SoJobRecord:
        return self.update(job_id, status=status, **changes)

    def mark_watchdog_event_seen(self, job_id: str, event_id: str) -> bool:
        record = self.get(job_id)
        if record is None:
            raise KeyError(job_id)
        if record.last_watchdog_event_id == event_id:
            return False
        record.last_watchdog_event_id = event_id
        self.save(record)
        return True

    def find_by_run_id(self, run_id: str) -> Optional[SoJobRecord]:
        return self._first(lambda record: record.z_harness_run_id == run_id)

    def find_by_pid(
        self, pid: int, *, execution_host: Optional[str] = None
    ) -> Optional[SoJobRecord]:
        return self._first(
            lambda record: record.pid == pid
            and (execution_host is None or record.execution_host == execution_host)
        )

    def find_by_slug(self, slug: str) -> Optional[SoJobRecord]:
        return self._first(lambda record: record.slug == slug)

    def find_by_discord_message(
        self, *, channel_id: str, message_id: str
    ) -> Optional[SoJobRecord]:
        channel_id = str(channel_id)
        message_id = str(message_id)
        return self._first(
            lambda record: record.discord_channel_id == channel_id
            and record.discord_message_id == message_id
        )

    def find_by_discord_thread(
        self, *, channel_id: str, thread_id: str
    ) -> Optional[SoJobRecord]:
        channel_id = str(channel_id)
        thread_id = str(thread_id)
        return self._first(
            lambda record: record.discord_channel_id == channel_id
            and record.discord_thread_id == thread_id
        )

    def resolve(
        self,
        *,
        job_id: Optional[str] = None,
        run_id: Optional[str] = None,
        pid: Optional[int] = None,
        slug: Optional[str] = None,
        execution_host: Optional[str] = None,
    ) -> Optional[SoJobRecord]:
        if job_id:
            found = self.get(job_id)
            if found:
                return found
        if run_id:
            found = self.find_by_run_id(run_id)
            if found:
                return found
        if pid is not None:
            found = self.find_by_pid(pid, execution_host=execution_host)
            if found:
                return found
        if slug:
            return self.find_by_slug(slug)
        return None

    def _first(self, predicate) -> Optional[SoJobRecord]:
        for record in self.list():
            if predicate(record):
                return record
        return None
