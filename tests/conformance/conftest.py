"""
conftest.py — Shared pytest fixtures and helpers for the conformance suite.
"""

from __future__ import annotations

import shutil
import textwrap
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# DRIVERS — canonical list of supported driver names
# ---------------------------------------------------------------------------

DRIVERS: list[str] = ["claude-code", "codex", "agy", "cursor-agent"]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def driver_available(driver_name: str) -> bool:
    """Return True if the binary for *driver_name* is on PATH.

    Mapping mirrors run_conformance._DRIVER_BINARIES.
    """
    _BINARIES: dict[str, str] = {
        "claude-code": "claude",
        "codex": "codex",
        "agy": "agy",
        "cursor-agent": "cursor-agent",
    }
    binary = _BINARIES.get(driver_name)
    if binary is None:
        return False
    return shutil.which(binary) is not None


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def tmp_workdir(tmp_path: Path) -> Path:
    """Return a tmp_path pre-populated with a minimal git-repo stub.

    The stub contains:
    - .git/          (bare directory; enough for path-detection code)
    - CLAUDE.md      (empty; signals a z-harness workspace)
    - tasks/         (empty task directory)

    Callers receive the Path to the repo root.
    """
    git_dir = tmp_path / ".git"
    git_dir.mkdir()
    (git_dir / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")

    (tmp_path / "CLAUDE.md").write_text(
        textwrap.dedent("""\
            # Workspace stub for conformance tests
        """),
        encoding="utf-8",
    )
    (tmp_path / "tasks").mkdir()

    return tmp_path
