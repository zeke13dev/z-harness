"""
worktree.py — Git worktree lifecycle management.

C2 of the Hermes orchestrator. Creates/deletes namespaced worktrees
with hermes/<slug>/<id> branch naming. Handles crash recovery
(orphan detection) and validation.
"""

import os
import re
import subprocess
from pathlib import Path
from typing import Optional


# ---------------------------------------------------------------------------
# Branch name helpers (T001)
# ---------------------------------------------------------------------------

# Safe slug pattern (kebab-case, no special chars)
SAFE_REF_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


def branch_name(slug: str, ws_id: str) -> str:
    """Build git branch name: hermes/<slug>/<ws_id>"""
    return f"hermes/{slug}/{ws_id}"


def worktree_path(slug: str, ws_id: str, base: str = "..") -> str:
    """Build worktree path: ../hermes-<slug>-<ws_id>"""
    return os.path.join(base, f"hermes-{slug}-{ws_id}")


def validate_ref(slug: str, ws_id: str = None) -> None:
    """Raise ValueError if slug or ws_id is unsafe for git refs.
    
    ws_id is optional — when None or empty, only slug is validated.
    """
    if not SAFE_REF_RE.match(slug):
        raise ValueError(
            f"Invalid slug '{slug}': must match ^[a-z0-9]+(-[a-z0-9]+)*$"
        )
    if ws_id and not SAFE_REF_RE.match(ws_id):
        raise ValueError(
            f"Invalid ws_id '{ws_id}': must match ^[a-z0-9]+(-[a-z0-9]+)*$"
        )


# ---------------------------------------------------------------------------
# create_worktree (T002)
# ---------------------------------------------------------------------------

class WorktreeError(Exception):
    """Worktree operation failed."""
    pass


def main_worktree_path(repo_root: str = ".") -> str:
    """Return the primary checkout, which must be checked out on ``main``."""
    try:
        result = subprocess.run(
            ["git", "worktree", "list", "--porcelain"],
            capture_output=True, text=True, check=True, cwd=repo_root,
        )
    except subprocess.CalledProcessError as exc:
        raise WorktreeError(f"Unable to list worktrees: {exc.stderr}") from exc

    primary_path = ""
    primary_branch = ""
    for line in result.stdout.splitlines():
        if line.startswith("worktree "):
            if primary_path:
                break
            primary_path = line[len("worktree "):]
        elif line.startswith("branch ") and primary_path:
            primary_branch = line[len("branch "):]

    if primary_path and primary_branch == "refs/heads/main":
        return os.path.abspath(primary_path)
    raise WorktreeError(
        "The primary worktree must be checked out on local main before creating "
        "or merging a worktree branch."
    )


def require_clean_main_worktree(repo_root: str = ".") -> str:
    """Return local main's path, refusing an uncommitted or merging checkout."""
    main_root = main_worktree_path(repo_root)
    status = subprocess.run(
        ["git", "status", "--porcelain"],
        capture_output=True, text=True, cwd=main_root,
    )
    if status.returncode != 0:
        raise WorktreeError(f"Unable to inspect main worktree: {status.stderr}")
    if status.stdout.strip():
        raise WorktreeError(
            f"Refusing to use dirty main worktree at {main_root}; commit, stash, "
            "or discard its changes before creating or merging a worktree branch."
        )

    merge_head = subprocess.run(
        ["git", "rev-parse", "-q", "--verify", "MERGE_HEAD"],
        capture_output=True, text=True, cwd=main_root,
    )
    if merge_head.returncode == 0:
        raise WorktreeError(
            f"Refusing to use main worktree at {main_root}; it has a merge in progress."
        )
    return main_root


def create_worktree(slug: str, ws_id: str, repo_root: str = ".", base: str = "..") -> str:
    """Create a git worktree with namespaced branch.
    
    Returns the absolute path to the worktree.
    Raises WorktreeError on failure.
    """
    validate_ref(slug, ws_id)
    main_root = require_clean_main_worktree(repo_root)
    branch = branch_name(slug, ws_id)
    wt_path = os.path.abspath(worktree_path(slug, ws_id, base))
    
    # Check if worktree already exists (crash recovery path)
    if os.path.isdir(wt_path) and os.path.isdir(os.path.join(wt_path, ".git")):
        print(f"  Worktree already exists at {wt_path} — reusing")
        return wt_path
    
    # Check if branch already exists (crash recovery — worktree may have been pruned)
    try:
        result = subprocess.run(
            ["git", "branch", "--list", branch],
            capture_output=True, text=True, check=True,
            cwd=main_root,
        )
        if result.stdout.strip():
            # Branch exists but worktree doesn't — try to recreate
            print(f"  Branch {branch} exists — recreating worktree")
    except subprocess.CalledProcessError:
        pass
    
    # Create worktree
    try:
        result = subprocess.run(
            ["git", "worktree", "add", wt_path, "-b", branch],
            capture_output=True, text=True, check=True,
            cwd=main_root,
        )
        print(f"  Created worktree: {wt_path} (branch: {branch})")
    except subprocess.CalledProcessError as e:
        # If branch already exists, try without -b
        if "already exists" in e.stderr or "already exists" in e.stdout:
            result = subprocess.run(
                ["git", "worktree", "add", wt_path, branch],
                capture_output=True, text=True,
                cwd=main_root,
            )
            if result.returncode != 0:
                raise WorktreeError(
                    f"Failed to create worktree at {wt_path}: {result.stderr}"
                ) from e
        else:
            raise WorktreeError(
                f"Failed to create worktree at {wt_path}: {e.stderr}"
            ) from e
    
    # Validate
    if not os.path.isdir(wt_path):
        raise WorktreeError(f"Worktree path {wt_path} not found after creation")
    
    git_dir = os.path.join(wt_path, ".git")
    if not os.path.isdir(git_dir) and not os.path.isfile(git_dir):
        raise WorktreeError(f"Worktree {wt_path} has no .git directory")
    
    return wt_path


# ---------------------------------------------------------------------------
# delete_worktree + list_worktrees (T003)
# ---------------------------------------------------------------------------

def delete_worktree(slug: str, ws_id: str, repo_root: str = ".", base: str = "..") -> None:
    """Delete worktree and its branch. Non-fatal — logs warnings on failure."""
    validate_ref(slug, ws_id)
    
    branch = branch_name(slug, ws_id)
    wt_path = os.path.abspath(worktree_path(slug, ws_id, base))
    
    # Remove worktree
    if os.path.isdir(wt_path):
        try:
            subprocess.run(
                ["git", "worktree", "remove", wt_path, "--force"],
                capture_output=True, text=True, check=True,
                cwd=repo_root,
            )
            print(f"  Removed worktree: {wt_path}")
        except subprocess.CalledProcessError as e:
            print(f"  WARNING: Failed to remove worktree {wt_path}: {e.stderr}")
    
    # Delete branch
    try:
        subprocess.run(
            ["git", "branch", "-D", branch],
            capture_output=True, text=True, check=True,
            cwd=repo_root,
        )
        print(f"  Deleted branch: {branch}")
    except subprocess.CalledProcessError as e:
        # Branch may already be gone — not an error
        if "not found" in e.stderr or "not found" in e.stdout:
            pass
        else:
            print(f"  WARNING: Failed to delete branch {branch}: {e.stderr}")


def list_worktrees(slug: str, repo_root: str = ".") -> list[str]:
    """List existing worktree branches for a slug.
    
    Returns list of ws_ids extracted from branch names.
    """
    validate_ref(slug)
    prefix = f"hermes/{slug}/"
    
    try:
        result = subprocess.run(
            ["git", "branch", "--list", f"hermes/{slug}/*"],
            capture_output=True, text=True, check=True,
            cwd=repo_root,
        )
    except subprocess.CalledProcessError:
        return []
    
    ws_ids = []
    for line in result.stdout.splitlines():
        line = line.strip().lstrip("*").strip()
        if line.startswith(prefix):
            ws_id = line[len(prefix):]
            if ws_id and SAFE_REF_RE.match(ws_id):
                ws_ids.append(ws_id)
    
    return ws_ids


def get_worktree_info(slug: str, ws_id: str, repo_root: str = ".") -> Optional[dict]:
    """Get worktree path for a specific workstream. Returns None if not found."""
    validate_ref(slug, ws_id)
    branch = branch_name(slug, ws_id)
    
    try:
        result = subprocess.run(
            ["git", "worktree", "list", "--porcelain"],
            capture_output=True, text=True, check=True,
            cwd=repo_root,
        )
    except subprocess.CalledProcessError:
        return None
    
    current = {}
    for line in result.stdout.splitlines():
        if line.startswith("worktree "):
            if current and current.get("branch") == f"refs/heads/{branch}":
                return current
            current = {"path": line[len("worktree "):]}
        elif line.startswith("HEAD "):
            current["head"] = line[len("HEAD "):]
        elif line.startswith("branch "):
            current["branch"] = line[len("branch "):]
    
    if current and current.get("branch") == f"refs/heads/{branch}":
        return current
    
    return None


# ---------------------------------------------------------------------------
# cleanup_orphaned (T004)
# ---------------------------------------------------------------------------

def cleanup_orphaned(slug: str, active_ids: set[str], repo_root: str = ".", base: str = "..") -> None:
    """Delete worktrees and branches for workstreams NOT in active_ids."""
    validate_ref(slug)
    
    existing = list_worktrees(slug, repo_root)
    orphaned = [ws_id for ws_id in existing if ws_id not in active_ids]
    
    for ws_id in orphaned:
        print(f"  Cleaning up orphaned workstream: {ws_id}")
        try:
            delete_worktree(slug, ws_id, repo_root, base)
        except Exception as e:
            print(f"  WARNING: Failed to clean up orphan {ws_id}: {e}")
