"""tests/test_block_shared_tree_edit.py

Characterizes scripts/block-shared-tree-edit.sh — the primary-main and
linked-worktree isolation PreToolUse hook.

The hook reads a Claude Code PreToolUse JSON payload on stdin and exits 0 (allow)
or 2 (block). Content edits in the primary checkout are always blocked.
Ownership of a linked working tree goes to the first live session to edit it; a
second concurrent session in the same linked tree is blocked until it isolates.

Run: python3 -m pytest tests/test_block_shared_tree_edit.py -v
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
HOOK = REPO_ROOT / "scripts" / "block-shared-tree-edit.sh"


def run_hook(session: str, file_path: str, cwd: str, *, env_extra=None, tool="Edit"):
    payload = {
        "session_id": session,
        "cwd": cwd,
        "tool_name": tool,
        "tool_input": ({"notebook_path": file_path} if tool == "NotebookEdit"
                       else {"file_path": file_path}),
    }
    env = dict(os.environ)
    if env_extra:
        env.update(env_extra)
    proc = subprocess.run(
        ["bash", str(HOOK)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=env,
    )
    return proc.returncode, proc.stderr


@pytest.fixture()
def repo(tmp_path):
    """A primary main checkout plus one linked implementation worktree."""
    main = tmp_path / "main"
    main.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=main, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=main, check=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=main, check=True)
    (main / "file.txt").write_text("x\n")
    subprocess.run(["git", "add", "file.txt"], cwd=main, check=True)
    subprocess.run(["git", "commit", "-qm", "initial"], cwd=main, check=True)
    worker = tmp_path / "worker"
    subprocess.run(["git", "worktree", "add", "-q", "-b", "worker", str(worker)], cwd=main, check=True)
    return main, worker, worker / "file.txt"


def _markdir(repo_path: Path) -> Path:
    gitdir = subprocess.run(
        ["git", "-C", str(repo_path), "rev-parse", "--absolute-git-dir"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    return Path(gitdir) / "z-harness-active-editors"


def test_linked_worktree_solo_session_allowed_and_claims(repo):
    _, repo_path, f = repo
    rc, _ = run_hook("sessA", str(f), str(repo_path))
    assert rc == 0
    assert (_markdir(repo_path) / "sessA").exists()


def test_second_concurrent_session_blocked(repo):
    _, repo_path, f = repo
    assert run_hook("sessA", str(f), str(repo_path))[0] == 0   # A claims
    rc, err = run_hook("sessB", str(f), str(repo_path))        # B intrudes
    assert rc == 2
    assert "BLOCKED" in err
    # Claude Code gets EnterWorktree; OMP/pi and other cwd-aware hosts should
    # understand that moving the current session cwd into a linked worktree is
    # also valid. Manual git worktree creation remains the generic fallback.
    assert "EnterWorktree" in err
    assert "this session's cwd" in err
    assert "git worktree add" in err


def test_owner_keeps_editing(repo):
    _, repo_path, f = repo
    assert run_hook("sessA", str(f), str(repo_path))[0] == 0
    run_hook("sessB", str(f), str(repo_path))
    # A is still owner (earliest claim) -> still allowed.
    assert run_hook("sessA", str(f), str(repo_path))[0] == 0


def test_idle_owner_pruned_lets_next_claim(repo):
    _, repo_path, f = repo
    assert run_hook("sessA", str(f), str(repo_path))[0] == 0
    # Backdate A's marker well past TTL so it is pruned as idle.
    mark = _markdir(repo_path) / "sessA"
    old = time.time() - 5000
    os.utime(mark, (old, old))
    rc, _ = run_hook("sessB", str(f), str(repo_path),
                     env_extra={"Z_HARNESS_EDIT_CLAIM_TTL": "1200"})
    assert rc == 0
    assert not mark.exists()             # stale A marker reclaimed


def test_override_env_bypasses_linked_worktree_contention(repo):
    _, repo_path, f = repo
    assert run_hook("sessA", str(f), str(repo_path))[0] == 0
    rc, _ = run_hook("sessB", str(f), str(repo_path),
                     env_extra={"Z_HARNESS_ALLOW_SHARED_TREE": "1"})
    assert rc == 0


def test_separate_linked_worktrees_do_not_collide(repo, tmp_path):
    main, worker_one, f = repo
    worker_two = tmp_path / "worker-two"
    subprocess.run(
        ["git", "worktree", "add", "-q", "-b", "worker-two", str(worker_two)],
        cwd=main, check=True,
    )
    assert run_hook("sessA", str(f), str(worker_one))[0] == 0
    # sessB in a distinct linked tree is unaffected by sessA's claim.
    assert run_hook("sessB", str(worker_two / "file.txt"), str(worker_two))[0] == 0


def test_primary_main_tree_blocked_even_with_override(repo):
    main, _, _ = repo
    primary_file = main / "file.txt"
    rc, err = run_hook(
        "sessA", str(primary_file), str(main),
        env_extra={"Z_HARNESS_ALLOW_SHARED_TREE": "1"},
    )
    assert rc == 2
    assert "primary main worktree" in err
    assert "git worktree add" in err


def test_non_repo_path_allowed(tmp_path):
    plain = tmp_path / "notrepo"
    plain.mkdir()
    f = plain / "f.txt"
    f.write_text("x\n")
    assert run_hook("sessA", str(f), str(plain))[0] == 0


def test_malformed_stdin_fails_open():
    proc = subprocess.run(["bash", str(HOOK)], input="not json{",
                          capture_output=True, text=True)
    assert proc.returncode == 0


def test_empty_stdin_fails_open():
    proc = subprocess.run(["bash", str(HOOK)], input="",
                          capture_output=True, text=True)
    assert proc.returncode == 0


def test_notebook_edit_path_guarded(repo):
    _, repo_path, f = repo
    nb = repo_path / "nb.ipynb"
    nb.write_text("{}")
    assert run_hook("sessA", str(nb), str(repo_path), tool="NotebookEdit")[0] == 0
    rc, err = run_hook("sessB", str(nb), str(repo_path), tool="NotebookEdit")
    assert rc == 2 and "BLOCKED" in err
