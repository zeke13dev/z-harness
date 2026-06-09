"""
state.py — OrchestratorState model for crash recovery.

Serializable to/from JSON. Used by C6 (crash recovery) and C1 (main loop).
"""

from dataclasses import dataclass, field, asdict
from typing import Optional
from datetime import datetime, timezone
import json
from pathlib import Path


@dataclass
class WorkstreamState:
    """Per-workstream execution state."""
    ws_id: str
    status: str = "pending"            # pending | running | done | halted | skipped | failed
    branch: Optional[str] = None       # git branch name
    worktree_path: Optional[str] = None
    pid: Optional[int] = None
    tasks_done: int = 0
    tasks_total: int = 0
    current_task: Optional[str] = None
    halt_reason: Optional[str] = None
    retry_count: int = 0               # Tracked per spec ("retry once")


@dataclass
class MergeProgress:
    """Merge execution state."""
    merge_order: list[str] = field(default_factory=list)
    completed: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    current: Optional[str] = None
    conflict_file: Optional[str] = None


@dataclass
class OrchestratorState:
    """Full orchestrator execution state for crash recovery."""
    slug: str
    phase: str = "init"                # init | spawning | running | merging | cleanup | done
    workstreams: dict[str, WorkstreamState] = field(default_factory=dict)
    merge_progress: Optional[MergeProgress] = None
    started_at: str = ""
    updated_at: str = ""

    def __post_init__(self):
        if not self.started_at:
            self.started_at = datetime.now(timezone.utc).isoformat()
        self.updated_at = datetime.now(timezone.utc).isoformat()


def to_dict(state: OrchestratorState) -> dict:
    """Serialize to JSON-safe dict."""
    return {
        "slug": state.slug,
        "phase": state.phase,
        "workstreams": {
            ws_id: asdict(ws) for ws_id, ws in state.workstreams.items()
        },
        "merge_progress": asdict(state.merge_progress) if state.merge_progress else None,
        "started_at": state.started_at,
        "updated_at": state.updated_at,
    }


def from_dict(data: dict) -> OrchestratorState:
    """Deserialize from dict."""
    workstreams = {}
    for ws_id, ws_data in data.get("workstreams", {}).items():
        workstreams[ws_id] = WorkstreamState(**ws_data)
    
    merge_progress = None
    if data.get("merge_progress"):
        merge_progress = MergeProgress(**data["merge_progress"])
    
    return OrchestratorState(
        slug=data["slug"],
        phase=data.get("phase", "init"),
        workstreams=workstreams,
        merge_progress=merge_progress,
        started_at=data.get("started_at", ""),
        updated_at=data.get("updated_at", ""),
    )


def save_state(state: OrchestratorState, plan_dir: str) -> None:
    """Persist state to <plan_dir>/hermes-state.json atomically."""
    state.updated_at = datetime.now(timezone.utc).isoformat()
    path = Path(plan_dir) / "hermes-state.json"
    tmp = str(path) + ".tmp"
    with open(tmp, "w") as f:
        json.dump(to_dict(state), f, indent=2)
        f.write("\n")
    Path(tmp).rename(path)


def load_state(plan_dir: str) -> Optional[OrchestratorState]:
    """Load state from <plan_dir>/hermes-state.json. Returns None if missing."""
    path = Path(plan_dir) / "hermes-state.json"
    try:
        with open(path) as f:
            data = json.load(f)
        return from_dict(data)
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def clear_state(plan_dir: str) -> None:
    """Delete state file on successful completion."""
    path = Path(plan_dir) / "hermes-state.json"
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass
