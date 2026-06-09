"""
merge.py — Merge orchestration.

C5 of the Hermes orchestrator. Merges completed workstream branches
in merge_order sequence, detects conflicts, and handles resolution
strategies (manual, spawn pi session, skip, abort).
"""

import subprocess
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class MergeResult:
    """Result of a git merge operation."""
    success: bool
    conflicted_files: list[str] = field(default_factory=list)
    diff: Optional[str] = None
    workstream_id: str = ""
    branch: str = ""


# ---------------------------------------------------------------------------
# merge_workstream (T001)
# ---------------------------------------------------------------------------

def merge_workstream(ws_id: str, slug: str, repo_root: str = ".") -> MergeResult:
    """Merge a workstream branch into the current branch.
    
    Uses git merge --no-ff for traceable merge commits.
    Returns MergeResult indicating success or conflict details.
    """
    branch = f"hermes/{slug}/{ws_id}"
    
    # First, abort any in-progress merge
    try:
        subprocess.run(
            ["git", "merge", "--abort"],
            capture_output=True, text=True,
            cwd=repo_root,
        )
    except subprocess.CalledProcessError:
        pass  # No merge in progress — fine
    
    # Check if branch exists
    try:
        result = subprocess.run(
            ["git", "branch", "--list", branch],
            capture_output=True, text=True, check=True,
            cwd=repo_root,
        )
        if not result.stdout.strip():
            return MergeResult(
                success=False,
                workstream_id=ws_id,
                branch=branch,
                conflicted_files=[],
                diff=f"Branch {branch} not found",
            )
    except subprocess.CalledProcessError:
        pass
    
    # Execute merge
    commit_msg = f"merge: {branch}"
    try:
        result = subprocess.run(
            ["git", "merge", branch, "--no-ff", "-m", commit_msg],
            capture_output=True, text=True,
            cwd=repo_root,
        )
        
        if result.returncode == 0:
            print(f"  Merged {branch} successfully")
            return MergeResult(
                success=True,
                workstream_id=ws_id,
                branch=branch,
            )
        else:
            # Merge conflict
            return _handle_merge_failure(ws_id, branch, result, repo_root)
    
    except subprocess.CalledProcessError as e:
        return MergeResult(
            success=False,
            workstream_id=ws_id,
            branch=branch,
            diff=str(e),
        )


def _handle_merge_failure(
    ws_id: str,
    branch: str,
    result: subprocess.CompletedProcess,
    repo_root: str,
) -> MergeResult:
    """Parse merge failure output for conflict details."""
    # Get list of conflicted files
    try:
        status = subprocess.run(
            ["git", "diff", "--name-only", "--diff-filter=U"],
            capture_output=True, text=True,
            cwd=repo_root,
        )
        conflicted = [
            f.strip() for f in status.stdout.splitlines() if f.strip()
        ]
    except subprocess.CalledProcessError:
        conflicted = []
    
    # Get diff for conflicted files
    diff = result.stdout + "\n" + result.stderr
    try:
        diff_result = subprocess.run(
            ["git", "diff"],
            capture_output=True, text=True,
            cwd=repo_root,
        )
        diff = diff_result.stdout if diff_result.stdout else diff
    except subprocess.CalledProcessError:
        pass
    
    print(f"  CONFLICT merging {branch}: {conflicted}")
    
    return MergeResult(
        success=False,
        conflicted_files=conflicted,
        diff=diff,
        workstream_id=ws_id,
        branch=branch,
    )


# ---------------------------------------------------------------------------
# abort_merge (T001)
# ---------------------------------------------------------------------------

def abort_merge(repo_root: str = ".") -> None:
    """Abort an in-progress merge, resetting to pre-merge state."""
    try:
        subprocess.run(
            ["git", "merge", "--abort"],
            capture_output=True, text=True, check=True,
            cwd=repo_root,
        )
        print("  Merge aborted — reset to pre-merge state")
    except subprocess.CalledProcessError as e:
        print(f"  WARNING: Failed to abort merge: {e.stderr}")


# ---------------------------------------------------------------------------
# skip_workstream (T001)
# ---------------------------------------------------------------------------

def skip_workstream(ws_id: str, repo_root: str = ".") -> None:
    """Abort current merge and mark workstream as skipped."""
    abort_merge(repo_root)
    print(f"  Skipped workstream: {ws_id}")


# ---------------------------------------------------------------------------
# Resolution strategies (T003)
# ---------------------------------------------------------------------------

def resolve_manual(files: list[str], repo_root: str = ".") -> bool:
    """Check if manual resolution is complete (all files staged).
    
    Returns True if all conflicts appear resolved.
    """
    try:
        status = subprocess.run(
            ["git", "diff", "--name-only", "--diff-filter=U"],
            capture_output=True, text=True,
            cwd=repo_root,
        )
        remaining = [f.strip() for f in status.stdout.splitlines() if f.strip()]
        return len(remaining) == 0
    except subprocess.CalledProcessError:
        return False


def continue_merge(repo_root: str = ".") -> bool:
    """Run git merge --continue after manual resolution.
    
    Returns True if merge completed successfully.
    """
    try:
        result = subprocess.run(
            ["git", "merge", "--continue"],
            capture_output=True, text=True, check=True,
            cwd=repo_root,
        )
        print("  Merge continued successfully")
        return True
    except subprocess.CalledProcessError as e:
        print(f"  WARNING: merge --continue failed: {e.stderr}")
        return False


def revert_all_completed(
    completed: list[str],
    slug: str,
    repo_root: str = ".",
) -> None:
    """Revert all previously merged workstreams (abort plan).
    
    Walks completed list in reverse and reverts each merge commit.
    This is best-effort — manual cleanup may be needed.
    """
    for ws_id in reversed(completed):
        branch = f"hermes/{slug}/{ws_id}"
        print(f"  Reverting merge of {branch}...")
        try:
            # Find the merge commit
            log = subprocess.run(
                ["git", "log", "--oneline", "--grep", f"merge: {branch}", "-n", "1"],
                capture_output=True, text=True,
                cwd=repo_root,
            )
            if log.stdout.strip():
                commit = log.stdout.split()[0]
                subprocess.run(
                    ["git", "revert", commit, "--no-edit"],
                    capture_output=True, text=True, check=True,
                    cwd=repo_root,
                )
                print(f"  Reverted {branch}")
        except subprocess.CalledProcessError as e:
            print(f"  WARNING: Failed to revert {branch}: {e.stderr}")
