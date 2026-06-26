"""DispatchResult dataclass for capturing the outcome of a dispatched command."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class DispatchResult:
    """Holds the outcome of a single dispatched command invocation."""

    exit_code: int
    is_error: bool
    stdout_events: list[dict] = field(default_factory=list)
    stdout: str = ""
    stderr: str = ""
    wall_ms: float = 0.0
    session_id: str | None = None

    @property
    def success(self) -> bool:
        """Return True iff exit_code is 0 and no error flag is set."""
        return self.exit_code == 0 and not self.is_error
