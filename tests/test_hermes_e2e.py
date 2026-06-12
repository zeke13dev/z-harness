"""
tests/test_hermes_e2e.py — End-to-end integration tests for the Hermes scheduler.

What's REAL:
- create_worktree / delete_worktree (scripts/hermes/worktree.py)
- merge_workstream (scripts/hermes/merge.py)
- The scheduler itself: run_single_plan's partition_level, asyncio.gather,
  asyncio.Semaphore, and merge_lock flows.

What's FAKED:
- spawn_session / poll_session — the fake spawn commits real files onto the
  worktree branch (so merge_workstream has something to merge); poll_session
  returns a "running" status on first call then "done" after a brief sleep.
- discord relay connect / disconnect — async no-ops.
- attempt_recovery — returns None (fresh run every time).
- cleanup_orphaned, clear_state, save_state — no-ops.

Tests:
1. test_parallel_overlap  — cap=3, 3 disjoint workstreams: peak concurrent > 1.
2. test_high_severity_serialize — ws-A and ws-B share a HIGH conflict; ws-C
   is disjoint. Peak concurrent for (ws-A, ws-B) pair == 1; ws-C can overlap.
3. test_merge_mutex_sequential — merge_lock serializes: peak concurrent merges
   == 1 across concurrent workstreams.
4. test_cap1_equals_cap3_tree — run same plan at cap=1 and cap=3; git trees
   (git ls-tree -r HEAD) are identical (content determinism).
5. test_cross_plan_disjoint_overlap — two plans with disjoint scopes run
   concurrently (peak plan concurrency 2 at max_parallel_plans=2).
6. test_cross_plan_overlap_serialize — two plans sharing a scope conflict are
   serialized (peak plan concurrency 1).
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import threading
import time
import types
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Git availability guard
# ---------------------------------------------------------------------------

pytestmark = pytest.mark.skipif(
    shutil.which("git") is None,
    reason="git required for e2e worktree tests",
)

# ---------------------------------------------------------------------------
# sys.path setup — mirrors test_hermes_execute.py
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SCRIPTS_DIR = _REPO_ROOT / "scripts"
_SCRIPT = str(_SCRIPTS_DIR / "hermes-execute.py")

if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))


def _load_hx():
    """Load hermes-execute.py as a module (fresh copy for isolation)."""
    spec = importlib.util.spec_from_file_location("hermes_execute_e2e", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_HX = _load_hx()

from hermes.schema import FileConflict, Workstream, WorkstreamsManifest  # noqa: E402
from hermes.worktree import create_worktree, delete_worktree  # noqa: E402
from hermes.merge import merge_workstream  # noqa: E402


# ---------------------------------------------------------------------------
# Temp git repo fixture
# ---------------------------------------------------------------------------

def _git(repo: Path, *args, check=True):
    """Run git in repo, returning CompletedProcess."""
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
    result = subprocess.run(
        ["git", *args],
        cwd=str(repo),
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    if check and result.returncode != 0:
        raise RuntimeError(
            f"git {args} failed in {repo}:\n  stdout={result.stdout!r}\n  stderr={result.stderr!r}"
        )
    return result


@pytest.fixture()
def git_repo(tmp_path):
    """A real temp git repo with an initial commit on a stable base branch.

    Yields (repo_root: Path, base_branch: str).
    """
    repo = tmp_path / "repo"
    repo.mkdir()

    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test User")

    # Initial commit so branches can be created.
    readme = repo / "README.md"
    readme.write_text("# hermes e2e test repo\n")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-m", "initial commit")

    base_branch = _git(repo, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()

    yield repo, base_branch


# ---------------------------------------------------------------------------
# Helper: build a plan dir with workstreams.json
# ---------------------------------------------------------------------------

def _build_plan_dir(
    tmp_path: Path,
    slug: str,
    workstreams: list[dict],
    merge_order: list[str],
    *,
    file_conflicts: list[dict] | None = None,
    scope_unknown: bool = False,
) -> Path:
    """Create a minimal plan dir with workstreams.json."""
    plan_dir = tmp_path / "plans" / slug
    plan_dir.mkdir(parents=True, exist_ok=True)

    manifest = {
        "protocol": "hermes-v1",
        "slug": slug,
        "source": "/z-plan",
        "generated_at": "2026-01-01T00:00:00Z",
        "partial_tree": False,
        "scope_unknown": scope_unknown,
        "workstreams": workstreams,
        "merge_order": merge_order,
        "file_conflicts": file_conflicts or [],
    }
    (plan_dir / "workstreams.json").write_text(json.dumps(manifest, indent=2))
    return plan_dir


def _seed_tasks_md(repo: Path, workstreams: list[dict]) -> None:
    """Commit stub TASKS.md files for each workstream into the repo's HEAD.

    run_workstream checks os.path.exists(wt_path / ws.path / "TASKS.md") before
    calling spawn_session.  Since worktrees are created from HEAD, seeding these
    files into HEAD means every worktree will carry them automatically.
    """
    for ws in workstreams:
        ws_path = Path(ws["path"])
        target = repo / ws_path / "TASKS.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(f"## T001 — placeholder\n")
        _git(repo, "add", str(ws_path / "TASKS.md"))

    # Commit if there are staged changes (there always will be).
    _git(repo, "commit", "-m", "seed TASKS.md stubs")


def _make_config(
    *,
    max_parallel_workstreams: int = 1,
    worktree_base: str = "..",
) -> types.SimpleNamespace:
    return types.SimpleNamespace(
        paths=types.SimpleNamespace(worktree_base=worktree_base),
        concurrency=types.SimpleNamespace(
            max_parallel_workstreams=max_parallel_workstreams,
            serialize_all=False,
            serialize_high_severity=True,
        ),
        timeouts=types.SimpleNamespace(per_workstream_minutes=60),
        retry=types.SimpleNamespace(max_retries=1, retry_delay_seconds=1),
        stall_detection=types.SimpleNamespace(no_progress_minutes=30),
    )


# ---------------------------------------------------------------------------
# Fake session helpers
# ---------------------------------------------------------------------------

def _write_session_status(worktree_path: str, status: str) -> None:
    """Write a session-status.json into the worktree."""
    payload = {
        "status": status,
        "tasks_done": 1,
        "tasks_total": 1,
        "current_task": "T001",
        "updated_at": "2026-01-01T00:00:00Z",
        "halt_reason": None,
    }
    out = Path(worktree_path) / "session-status.json"
    out.write_text(json.dumps(payload))


def _make_fake_spawn(
    slug: str,
    ws_to_file: dict[str, str],
    repo_root: str,
    live_counter: list[int],
    peak_counter: list[int],
    counter_lock: threading.Lock,
) -> callable:
    """Return a fake spawn_session that:
    - Commits the workstream's designated file onto the worktree branch.
    - Records a 'running' session-status.json.
    - Increments the live counter (so concurrency can be measured).
    - Returns a fake PID (ws_id hash).
    """
    def fake_spawn(worktree_path: str, tasks_path: str) -> int:
        # Figure out which ws_id owns this worktree from the branch name.
        # Branch is hermes/<slug>/<ws_id>; worktree dir is ../hermes-<slug>-<ws_id>
        wt_name = Path(worktree_path).name  # hermes-<slug>-<ws_id>
        prefix = f"hermes-{slug}-"
        ws_id = wt_name[len(prefix):] if wt_name.startswith(prefix) else wt_name

        # Commit the workstream's file onto the worktree branch.
        filename = ws_to_file.get(ws_id, f"{ws_id}-output.txt")
        target = Path(worktree_path) / filename
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(f"work by {ws_id}\n")

        _git(Path(worktree_path), "add", filename)
        _git(Path(worktree_path), "commit", "-m", f"work: {ws_id} writes {filename}")

        # Mark as 'running' — poll_session will upgrade to 'done' later.
        _write_session_status(worktree_path, "running")

        with counter_lock:
            live_counter[0] += 1
            peak_counter[0] = max(peak_counter[0], live_counter[0])

        return abs(hash(ws_id)) % 999999 + 1  # fake PID

    return fake_spawn


def _make_fake_poll(live_counter: list[int], counter_lock: threading.Lock) -> callable:
    """Return a fake poll_session that:
    - On FIRST call for a given worktree: sleeps briefly (simulates real work
      overlapping across concurrent threads via asyncio.to_thread), returns 'running'.
    - On SECOND+ call: decrements the live counter, writes 'done', returns 'done'.

    The brief sleep (0.05 s) in to_thread genuinely lets other workstreams start
    before this one finishes — proving real concurrency.
    """
    first_call: dict[str, bool] = {}
    call_lock = threading.Lock()

    from hermes.schema import SessionStatus

    def fake_poll(worktree_path: str):
        key = worktree_path
        with call_lock:
            is_first = key not in first_call
            if is_first:
                first_call[key] = True

        if is_first:
            # Simulate real work: sleep in thread (offloaded via asyncio.to_thread)
            # so other workstreams' spawns can proceed.
            time.sleep(0.05)
            return SessionStatus(status="running", tasks_done=0, tasks_total=1)

        # Second call → done
        _write_session_status(worktree_path, "done")
        with counter_lock:
            live_counter[0] = max(0, live_counter[0] - 1)

        return SessionStatus(status="done", tasks_done=1, tasks_total=1)

    return fake_poll


# ---------------------------------------------------------------------------
# Standard monkeypatches for run_single_plan (no real discord/recovery/state)
# ---------------------------------------------------------------------------

def _patch_run_single_plan(
    monkeypatch,
    slug: str,
    plan_dir: Path,
    repo_root: Path,
    config: types.SimpleNamespace,
    *,
    fake_spawn: callable,
    fake_poll: callable,
):
    """Apply all the run_single_plan stubs except worktree/merge (those stay real)."""
    import hermes.discord_relay as dr

    async def _noop(*a, **k):
        return None

    monkeypatch.setattr(dr, "connect", _noop, raising=False)
    monkeypatch.setattr(dr, "disconnect", _noop, raising=False)

    monkeypatch.setattr(_HX, "spawn_session", fake_spawn)
    monkeypatch.setattr(_HX, "poll_session", fake_poll)
    monkeypatch.setattr(_HX, "is_session_alive", lambda pid: False)  # proc "exited" → fine after done
    monkeypatch.setattr(_HX, "kill_session", lambda pid: None)
    monkeypatch.setattr(_HX, "check_timeout", lambda *a, **k: False)
    monkeypatch.setattr(_HX, "check_stall", lambda *a, **k: False)
    monkeypatch.setattr(_HX, "attempt_recovery", lambda *a, **k: None)
    monkeypatch.setattr(_HX, "cleanup_orphaned", lambda *a, **k: None)
    monkeypatch.setattr(_HX, "clear_state", lambda *a, **k: None)
    monkeypatch.setattr(_HX, "save_state", lambda *a, **k: None)
    monkeypatch.setattr(_HX, "validate_gates", lambda m, d: [])
    monkeypatch.setattr(_HX, "resolve_plan_dir", lambda slug, explicit=None: str(plan_dir))

    # Fast sleep so tests don't wait 5 s per poll cycle.
    # We save a reference to the REAL asyncio.sleep before patching.
    _real_asyncio_sleep = asyncio.sleep

    async def fast_sleep(t):
        # Skip long sleeps (e.g. the 5-second poll interval); keep short ones.
        if t >= 1:
            await _real_asyncio_sleep(0)
        else:
            await _real_asyncio_sleep(t)

    monkeypatch.setattr(_HX.asyncio, "sleep", fast_sleep)


# ---------------------------------------------------------------------------
# Tree equality helper
# ---------------------------------------------------------------------------

def _tree_hash(repo: Path) -> str:
    """Return the git tree SHA of HEAD^{tree} — content-addressed, stable across runs."""
    return _git(repo, "rev-parse", "HEAD^{tree}").stdout.strip()


def _tree_entries(repo: Path) -> list[tuple[str, str]]:
    """Return sorted (path, blob-sha) pairs from git ls-tree -r HEAD."""
    out = _git(repo, "ls-tree", "-r", "HEAD").stdout.strip()
    entries = []
    for line in out.splitlines():
        # format: <mode> blob <sha>\t<path>
        parts = line.split("\t", 1)
        if len(parts) == 2:
            sha_part = parts[0].split()[2]
            entries.append((parts[1], sha_part))
    return sorted(entries)


# ---------------------------------------------------------------------------
# Test 1: parallel_overlap — peak concurrent > 1 at cap=3
# ---------------------------------------------------------------------------

def test_parallel_overlap(monkeypatch, git_repo, tmp_path):
    """Three disjoint workstreams at cap=3 must run with peak concurrency > 1.

    Real: create_worktree, merge_workstream, scheduler gather+semaphore.
    Faked: spawn_session (commits files), poll_session (running→done),
           discord, recovery, state.
    """
    repo, base_branch = git_repo
    slug = "e2e-overlap"
    ws_ids = ["ws-1", "ws-2", "ws-3"]
    ws_to_file = {"ws-1": "a.txt", "ws-2": "b.txt", "ws-3": "c.txt"}

    workstreams = [
        {"id": wid, "status": "ready", "name": wid, "path": f"plans/{slug}/{wid}",
         "tasks": ["T001"], "depends_on": []}
        for wid in ws_ids
    ]
    plan_dir = _build_plan_dir(
        tmp_path, slug, workstreams, merge_order=ws_ids,
    )
    # Seed TASKS.md files into HEAD so all worktrees carry them automatically.
    _seed_tasks_md(repo, workstreams)

    live = [0]
    peak = [0]
    lock = threading.Lock()

    config = _make_config(
        max_parallel_workstreams=3,
        worktree_base=str(tmp_path / "worktrees"),
    )
    (tmp_path / "worktrees").mkdir(parents=True, exist_ok=True)

    fake_spawn = _make_fake_spawn(slug, ws_to_file, str(repo), live, peak, lock)
    fake_poll = _make_fake_poll(live, lock)

    _patch_run_single_plan(
        monkeypatch, slug, plan_dir, repo, config,
        fake_spawn=fake_spawn,
        fake_poll=fake_poll,
    )

    code = asyncio.run(_HX.run_single_plan(slug, str(plan_dir), config, str(repo)))

    assert code == 0, f"run_single_plan must succeed; got code={code}"
    assert peak[0] > 1, (
        f"peak concurrent sessions must be > 1 at cap=3; got peak={peak[0]}. "
        "This would fail if gather is not actually running workstreams concurrently."
    )


# ---------------------------------------------------------------------------
# Test 2: HIGH-severity serialization — conflicting pair never overlaps
# ---------------------------------------------------------------------------

def test_high_severity_serialize(monkeypatch, git_repo, tmp_path):
    """ws-A and ws-B share a HIGH file conflict → placed in different sub-batches.

    ws-C is disjoint and CAN overlap with one of A/B.  The peak concurrent
    count for the (ws-A, ws-B) pair must be 1 (they never co-run).
    """
    repo, base_branch = git_repo
    slug = "e2e-high"
    # Each writes a unique file so merges don't conflict.
    ws_to_file = {"ws-a": "file-a.txt", "ws-b": "file-b.txt", "ws-c": "file-c.txt"}

    workstreams = [
        {"id": "ws-a", "status": "ready", "name": "ws-a", "path": "plans/e2e-high/ws-a",
         "tasks": ["T001"], "depends_on": []},
        {"id": "ws-b", "status": "ready", "name": "ws-b", "path": "plans/e2e-high/ws-b",
         "tasks": ["T001"], "depends_on": []},
        {"id": "ws-c", "status": "ready", "name": "ws-c", "path": "plans/e2e-high/ws-c",
         "tasks": ["T001"], "depends_on": []},
    ]
    file_conflicts = [
        {"file": "src/shared.py", "workstreams": ["ws-a", "ws-b"], "severity": "high"}
    ]
    plan_dir = _build_plan_dir(
        tmp_path, slug, workstreams,
        merge_order=["ws-a", "ws-b", "ws-c"],
        file_conflicts=file_conflicts,
    )
    _seed_tasks_md(repo, workstreams)

    # Track per-ws liveness so we can detect if ws-a and ws-b ever co-run.
    ab_overlap_peak = [0]
    ab_current = [0]
    ab_lock = threading.Lock()

    spawned_ws: dict[str, bool] = {}
    polled_ws: dict[str, int] = {}
    spawn_lock = threading.Lock()

    from hermes.schema import SessionStatus

    def fake_spawn(worktree_path: str, tasks_path: str) -> int:
        wt_name = Path(worktree_path).name
        prefix = f"hermes-{slug}-"
        ws_id = wt_name[len(prefix):] if wt_name.startswith(prefix) else wt_name

        filename = ws_to_file.get(ws_id, f"{ws_id}.txt")
        target = Path(worktree_path) / filename
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(f"work by {ws_id}\n")
        _git(Path(worktree_path), "add", filename)
        _git(Path(worktree_path), "commit", "-m", f"work: {ws_id}")
        _write_session_status(worktree_path, "running")

        with ab_lock:
            spawned_ws[ws_id] = True
            if ws_id in ("ws-a", "ws-b"):
                ab_current[0] += 1
                ab_overlap_peak[0] = max(ab_overlap_peak[0], ab_current[0])

        return abs(hash(ws_id)) % 999999 + 1

    def fake_poll(worktree_path: str):
        wt_name = Path(worktree_path).name
        prefix = f"hermes-{slug}-"
        ws_id = wt_name[len(prefix):] if wt_name.startswith(prefix) else wt_name

        with spawn_lock:
            count = polled_ws.get(ws_id, 0)
            polled_ws[ws_id] = count + 1

        if count == 0:
            time.sleep(0.05)
            return SessionStatus(status="running", tasks_done=0, tasks_total=1)

        _write_session_status(worktree_path, "done")
        with ab_lock:
            if ws_id in ("ws-a", "ws-b"):
                ab_current[0] = max(0, ab_current[0] - 1)
        return SessionStatus(status="done", tasks_done=1, tasks_total=1)

    config = _make_config(
        max_parallel_workstreams=3,
        worktree_base=str(tmp_path / "worktrees"),
    )
    (tmp_path / "worktrees").mkdir(parents=True, exist_ok=True)

    _patch_run_single_plan(
        monkeypatch, slug, plan_dir, repo, config,
        fake_spawn=fake_spawn,
        fake_poll=fake_poll,
    )

    code = asyncio.run(_HX.run_single_plan(slug, str(plan_dir), config, str(repo)))

    assert code == 0, f"run must succeed; got code={code}"
    assert ab_overlap_peak[0] == 1, (
        f"ws-a and ws-b share a HIGH conflict; they must never overlap. "
        f"Peak concurrent for (ws-a, ws-b) pair: {ab_overlap_peak[0]} (expected 1). "
        "partition_level must have placed them in different sub-batches."
    )


# ---------------------------------------------------------------------------
# Test 3: merge mutex — merges are sequential (peak concurrent merges == 1)
# ---------------------------------------------------------------------------

def test_merge_mutex_sequential(monkeypatch, git_repo, tmp_path):
    """Three disjoint workstreams at cap=3: merges are serialized by merge_lock.

    Real merge_workstream is called; merge_lock is the real asyncio.Lock threaded
    through run_single_plan → run_workstream.  We verify that the peak number of
    concurrent real merge_workstream calls is 1.
    """
    repo, base_branch = git_repo
    slug = "e2e-mutex"
    ws_to_file = {"ws-1": "m1.txt", "ws-2": "m2.txt", "ws-3": "m3.txt"}
    ws_ids = ["ws-1", "ws-2", "ws-3"]

    workstreams = [
        {"id": wid, "status": "ready", "name": wid, "path": f"plans/{slug}/{wid}",
         "tasks": ["T001"], "depends_on": []}
        for wid in ws_ids
    ]
    plan_dir = _build_plan_dir(tmp_path, slug, workstreams, merge_order=ws_ids)
    _seed_tasks_md(repo, workstreams)

    merge_peak = [0]
    merge_current = [0]
    merge_lock_tracker = threading.Lock()

    # Wrap the REAL merge_workstream with a concurrency tracker.
    real_merge = _HX.merge_workstream

    def tracked_merge(ws_id, slug, repo_root):
        with merge_lock_tracker:
            merge_current[0] += 1
            merge_peak[0] = max(merge_peak[0], merge_current[0])
        try:
            return real_merge(ws_id, slug, repo_root)
        finally:
            with merge_lock_tracker:
                merge_current[0] -= 1

    monkeypatch.setattr(_HX, "merge_workstream", tracked_merge)

    live = [0]
    peak = [0]
    lock = threading.Lock()
    config = _make_config(
        max_parallel_workstreams=3,
        worktree_base=str(tmp_path / "worktrees"),
    )
    (tmp_path / "worktrees").mkdir(parents=True, exist_ok=True)

    fake_spawn = _make_fake_spawn(slug, ws_to_file, str(repo), live, peak, lock)
    fake_poll = _make_fake_poll(live, lock)

    _patch_run_single_plan(
        monkeypatch, slug, plan_dir, repo, config,
        fake_spawn=fake_spawn,
        fake_poll=fake_poll,
    )

    code = asyncio.run(_HX.run_single_plan(slug, str(plan_dir), config, str(repo)))

    assert code == 0, f"run must succeed; got code={code}"
    assert merge_peak[0] == 1, (
        f"merges must be serialized by merge_lock; peak concurrent merges: {merge_peak[0]}. "
        "Expected 1. If > 1, merge_lock is not being held correctly."
    )


# ---------------------------------------------------------------------------
# Test 4: cap=1 tree == cap=3 tree (content determinism)
# ---------------------------------------------------------------------------

def test_cap1_equals_cap3_tree(tmp_path):
    """Same plan executed at cap=1 and cap=3 must produce identical git trees.

    Each run uses its OWN git repo so the trees are built independently.
    We compare sorted (path, blob-sha) pairs from git ls-tree -r HEAD.

    Real: create_worktree, merge_workstream, scheduler gather+semaphore.
    Faked: spawn (commits fixed files), poll, discord, recovery, state.
    """
    slug = "e2e-det"
    ws_to_file = {"ws-1": "det1.txt", "ws-2": "det2.txt", "ws-3": "det3.txt"}
    ws_ids = ["ws-1", "ws-2", "ws-3"]

    workstreams = [
        {"id": wid, "status": "ready", "name": wid, "path": f"plans/{slug}/{wid}",
         "tasks": ["T001"], "depends_on": []}
        for wid in ws_ids
    ]

    def _run_at_cap(cap: int, repo_base: Path) -> list[tuple[str, str]]:
        """Initialise a fresh repo and run the plan at the given cap."""
        # Load a FRESH module to avoid state contamination across runs.
        spec = importlib.util.spec_from_file_location(
            f"hermes_execute_e2e_det_{cap}", _SCRIPT
        )
        hx = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(hx)

        repo = repo_base / f"repo-cap{cap}"
        repo.mkdir(parents=True)
        _git(repo, "init", "-b", "main")
        _git(repo, "config", "user.email", "test@example.com")
        _git(repo, "config", "user.name", "Test User")
        readme = repo / "README.md"
        readme.write_text("# determinism test\n")
        _git(repo, "add", "README.md")
        _git(repo, "commit", "-m", "initial")

        worktree_base = repo_base / f"wt-cap{cap}"
        worktree_base.mkdir(parents=True)
        plan_dir = _build_plan_dir(
            repo_base / f"plan-cap{cap}", slug, workstreams, merge_order=ws_ids,
        )
        # Seed TASKS.md into the repo HEAD so all worktrees carry it.
        _seed_tasks_md(repo, workstreams)

        config = _make_config(
            max_parallel_workstreams=cap,
            worktree_base=str(worktree_base),
        )

        live = [0]
        peak = [0]
        lock = threading.Lock()

        # Deterministic fake spawn: always writes the same content.
        def det_spawn(worktree_path: str, tasks_path: str) -> int:
            wt_name = Path(worktree_path).name
            prefix = f"hermes-{slug}-"
            ws_id = wt_name[len(prefix):] if wt_name.startswith(prefix) else wt_name

            filename = ws_to_file.get(ws_id, f"{ws_id}.txt")
            target = Path(worktree_path) / filename
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(f"deterministic content for {ws_id}\n")
            _git(Path(worktree_path), "add", filename)
            _git(Path(worktree_path), "commit", "-m", f"work: {ws_id}")
            _write_session_status(worktree_path, "running")
            with lock:
                live[0] += 1
                peak[0] = max(peak[0], live[0])
            return abs(hash(ws_id)) % 999999 + 1

        first_call: dict[str, bool] = {}
        first_call_lock = threading.Lock()
        from hermes.schema import SessionStatus

        def det_poll(worktree_path: str):
            key = worktree_path
            with first_call_lock:
                is_first = key not in first_call
                if is_first:
                    first_call[key] = True
            if is_first:
                time.sleep(0.02)
                return SessionStatus(status="running", tasks_done=0, tasks_total=1)
            _write_session_status(worktree_path, "done")
            with lock:
                live[0] = max(0, live[0] - 1)
            return SessionStatus(status="done", tasks_done=1, tasks_total=1)

        import hermes.discord_relay as dr

        async def _noop(*a, **k):
            return None

        # Save a reference to the real asyncio.sleep BEFORE patching.
        _real_sleep = asyncio.sleep

        async def fast_sleep(t):
            # Skip long sleeps (e.g. the 5-second poll interval).
            if t >= 1:
                await _real_sleep(0)
            else:
                await _real_sleep(t)

        # Patch the fresh module directly (no monkeypatch fixture here).
        hx.spawn_session = det_spawn
        hx.poll_session = det_poll
        hx.is_session_alive = lambda pid: False
        hx.kill_session = lambda pid: None
        hx.check_timeout = lambda *a, **k: False
        hx.check_stall = lambda *a, **k: False
        hx.attempt_recovery = lambda *a, **k: None
        hx.cleanup_orphaned = lambda *a, **k: None
        hx.clear_state = lambda *a, **k: None
        hx.save_state = lambda *a, **k: None
        hx.validate_gates = lambda m, d: []
        hx.resolve_plan_dir = lambda s, e=None: str(plan_dir)
        hx.asyncio.sleep = fast_sleep
        dr.connect = _noop
        dr.disconnect = _noop

        code = asyncio.run(hx.run_single_plan(slug, str(plan_dir), config, str(repo)))
        assert code == 0, f"run at cap={cap} must succeed; got code={code}"

        return _tree_entries(repo)

    tree_cap1 = _run_at_cap(1, tmp_path / "det1")
    tree_cap3 = _run_at_cap(3, tmp_path / "det3")

    assert tree_cap1 == tree_cap3, (
        f"Trees must be identical regardless of concurrency cap.\n"
        f"cap=1 entries: {tree_cap1}\n"
        f"cap=3 entries: {tree_cap3}\n"
        "If they differ, the scheduler is producing non-deterministic file contents."
    )


# ---------------------------------------------------------------------------
# Test 5 & 6: cross-plan disjoint overlap / overlapping serialize
# ---------------------------------------------------------------------------

def _load_hx_cp():
    """Load a fresh hermes-execute module for cross-plan tests."""
    spec = importlib.util.spec_from_file_location("hermes_execute_e2e_cp", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_HX_CP = _load_hx_cp()


def _make_cross_plan_config(*, max_parallel_plans: int = 2) -> types.SimpleNamespace:
    return types.SimpleNamespace(
        concurrency=types.SimpleNamespace(
            max_parallel_plans=max_parallel_plans,
            max_parallel_workstreams=1,
            serialize_all=False,
            serialize_high_severity=True,
        ),
        paths=types.SimpleNamespace(worktree_base="/tmp/wt"),
        timeouts=types.SimpleNamespace(per_workstream_minutes=90),
        retry=types.SimpleNamespace(max_retries=1, retry_delay_seconds=1),
        stall_detection=types.SimpleNamespace(no_progress_minutes=15),
    )


def test_cross_plan_disjoint_overlap(monkeypatch):
    """Two plans with disjoint scopes run concurrently (peak plan concurrency 2)."""
    peak = [0]
    current = [0]

    async def fake_run_single_plan(slug, plan_dir_override, config, repo_root, *, merge_lock=None):
        current[0] += 1
        peak[0] = max(peak[0], current[0])
        # Yield so the second plan can start before the first finishes.
        for _ in range(3):
            await asyncio.sleep(0)
        current[0] -= 1
        return 0

    monkeypatch.setattr(_HX_CP, "run_single_plan", fake_run_single_plan)

    # Disjoint scopes → no conflict graph edges → both land in one batch.
    monkeypatch.setattr(
        _HX_CP._cross_plan,
        "build_plan_conflict_graph",
        lambda slugs, **kwargs: {s: set() for s in slugs},
    )
    monkeypatch.setattr(
        _HX_CP._cross_plan,
        "acquire_plan_locks",
        lambda slugs, **kwargs: (True, sorted(slugs)),
    )
    monkeypatch.setattr(
        _HX_CP._cross_plan,
        "release_plan_locks",
        lambda slugs, **kwargs: None,
    )
    monkeypatch.setattr(_HX_CP, "_get_session_id", lambda: "test-session")

    config = _make_cross_plan_config(max_parallel_plans=2)
    code = asyncio.run(_HX_CP.run_cross_plan(["plan-a", "plan-b"], config, "/repo"))

    assert code == 0
    assert peak[0] == 2, (
        f"Disjoint plans must run concurrently; peak was {peak[0]}, expected 2. "
        "If peak==1 the scheduler is serializing plans that have no conflict."
    )


def test_cross_plan_overlap_serialize(monkeypatch):
    """Two plans with overlapping scopes are serialized (peak plan concurrency 1)."""
    peak = [0]
    current = [0]

    async def fake_run_single_plan(slug, plan_dir_override, config, repo_root, *, merge_lock=None):
        current[0] += 1
        peak[0] = max(peak[0], current[0])
        await asyncio.sleep(0)
        current[0] -= 1
        return 0

    monkeypatch.setattr(_HX_CP, "run_single_plan", fake_run_single_plan)

    # Fully conflicting graph → both plans serialize.
    monkeypatch.setattr(
        _HX_CP._cross_plan,
        "build_plan_conflict_graph",
        lambda slugs, **kwargs: {s: set(slugs) - {s} for s in slugs},
    )
    monkeypatch.setattr(
        _HX_CP._cross_plan,
        "acquire_plan_locks",
        lambda slugs, **kwargs: (True, sorted(slugs)),
    )
    monkeypatch.setattr(
        _HX_CP._cross_plan,
        "release_plan_locks",
        lambda slugs, **kwargs: None,
    )
    monkeypatch.setattr(_HX_CP, "_get_session_id", lambda: "test-session")

    config = _make_cross_plan_config(max_parallel_plans=2)
    code = asyncio.run(_HX_CP.run_cross_plan(["plan-x", "plan-y"], config, "/repo"))

    assert code == 0
    assert peak[0] == 1, (
        f"Overlapping plans must be serialized; peak was {peak[0]}, expected 1. "
        "If > 1 the conflict graph is not being respected."
    )
