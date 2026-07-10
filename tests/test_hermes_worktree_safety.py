"""Safety invariants for Hermes' main-to-worktree lifecycle."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

from hermes.merge import merge_workstream
from hermes.worktree import WorktreeError, create_worktree


def git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=True)


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    git(root, "init", "-b", "main")
    git(root, "config", "user.email", "test@example.com")
    git(root, "config", "user.name", "Test User")
    (root / "base.txt").write_text("main base\n")
    git(root, "add", "base.txt")
    git(root, "commit", "-m", "initial")
    return root


def test_create_worktree_bases_branch_on_main_not_caller_branch(repo: Path, tmp_path: Path):
    caller = tmp_path / "caller"
    git(repo, "worktree", "add", "-b", "caller", str(caller))
    (caller / "caller-only.txt").write_text("not on main\n")
    git(caller, "add", "caller-only.txt")
    git(caller, "commit", "-m", "caller change")

    worktree = Path(create_worktree("safe-base", "ws-1", str(caller), str(tmp_path / "worktrees")))

    assert not (worktree / "caller-only.txt").exists()


def test_create_worktree_refuses_dirty_main(repo: Path, tmp_path: Path):
    (repo / "uncommitted.txt").write_text("dirty\n")

    with pytest.raises(WorktreeError, match="dirty main worktree"):
        create_worktree("dirty-main", "ws-1", str(repo), str(tmp_path / "worktrees"))


def test_create_worktree_refuses_when_primary_is_not_main(repo: Path, tmp_path: Path):
    git(repo, "branch", "feature")
    git(repo, "checkout", "feature")

    with pytest.raises(WorktreeError, match="primary worktree must be checked out"):
        create_worktree("wrong-primary", "ws-1", str(repo), str(tmp_path / "worktrees"))


def test_merge_refuses_dirty_main_without_touching_workstream(repo: Path, tmp_path: Path):
    worktree = Path(create_worktree("merge-safety", "ws-1", str(repo), str(tmp_path / "worktrees")))
    (worktree / "work.txt").write_text("ready\n")
    git(worktree, "add", "work.txt")
    git(worktree, "commit", "-m", "workstream change")
    (repo / "uncommitted.txt").write_text("dirty\n")

    result = merge_workstream("ws-1", "merge-safety", str(worktree))

    assert not result.success
    assert "dirty main worktree" in (result.diff or "")
    assert not (repo / "work.txt").exists()
