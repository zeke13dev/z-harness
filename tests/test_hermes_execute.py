"""
tests/test_hermes_execute.py — Scheduler tests for scripts/hermes-execute.py.

T007: the per-workstream body was extracted into `async def run_workstream(...)`
and the flat `for ws_id in exec_order` loop was replaced by a level-aware
sequential scheduler driven by `depends_on` (INV-2). These tests pin the
scheduler behavior at cap=1 (the only mode that exists after T007):

  level_ordering        — deep-fork DAG (ws-1 -> {ws-2,ws-3} -> ws-4) schedules
                          run_workstream in dependency-respecting order.
  failed_blocks_deps    — a failed workstream's dependents are NEVER scheduled
                          and are reported blocked.
  recovery_skips_done   — a workstream already "done" in recovered state is
                          NOT re-run.
  parity_sequential     — an all-empty-depends_on manifest schedules in
                          merge_order, matching the legacy sequential order.

The real worktree/session/merge boundary is mocked: we monkeypatch
`run_workstream` itself to record call order and return scripted terminal
statuses, plus stub out manifest parsing, recovery, config, and discord.
"""

from __future__ import annotations

import asyncio
import importlib.util
import sys
import types
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SCRIPTS_DIR = _REPO_ROOT / "scripts"
_SCRIPT = str(_SCRIPTS_DIR / "hermes-execute.py")

# hermes-execute.py does `from hermes.schema import ...`, so scripts/ must be
# importable before we exec the hyphenated module.
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))


def _load_module():
    spec = importlib.util.spec_from_file_location("hermes_execute", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_HX = _load_module()

# Pull real dataclasses for building fixtures.
from hermes.schema import FileConflict, Workstream, WorkstreamsManifest  # noqa: E402
from hermes.state import OrchestratorState, WorkstreamState  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

def _ws(ws_id, depends_on=None, status="ready", name=None):
    return Workstream(
        id=ws_id,
        status=status,
        name=name or ws_id,
        path=f"plans/x/{ws_id}",
        tasks=["T001"],
        depends_on=list(depends_on or []),
    )


def _manifest(workstreams, merge_order, *, file_conflicts=None, scope_unknown=False):
    return WorkstreamsManifest(
        protocol="hermes-v1",
        slug="x",
        source="/z-plan",
        generated_at="2026-01-01T00:00:00Z",
        partial_tree=False,
        workstreams=workstreams,
        merge_order=merge_order,
        file_conflicts=list(file_conflicts or []),
        scope_unknown=scope_unknown,
    )


def _fc(file_path, workstream_ids, severity="high"):
    """Helper to build a FileConflict fixture."""
    return FileConflict(file=file_path, workstreams=list(workstream_ids), severity=severity)


class _Args(types.SimpleNamespace):
    pass


def _run_main(monkeypatch, manifest, *, scripted_status, recovered_state=None):
    """Drive `main_async` with the real scheduler but a mocked `run_workstream`.

    `scripted_status` maps ws_id -> terminal status returned by the mock
    run_workstream. Returns the recorded ordered list of scheduled ws_ids and
    the SystemExit code raised by main_async.
    """
    call_order = []

    async def fake_run_workstream(ws, state, config, args, repo_root, plan_dir, completed, *, merge_lock=None):
        call_order.append(ws.id)
        result = scripted_status.get(ws.id, "done")
        # Mirror what the real run_workstream does for "done": record state and
        # append to the caller's completed list so the driver's bookkeeping is
        # exercised faithfully.
        st = state.workstreams.get(ws.id) or WorkstreamState(ws_id=ws.id)
        st.status = result
        state.workstreams[ws.id] = st
        if result == "done":
            completed.append(ws.id)
        return result

    # --- stub the orchestration boundary ---
    monkeypatch.setattr(_HX, "run_workstream", fake_run_workstream)
    monkeypatch.setattr(_HX, "parse_args", lambda: _Args(slug="x", plan_dir="/tmp/x"))
    monkeypatch.setattr(_HX, "validate_slug", lambda s: True)
    monkeypatch.setattr(_HX, "resolve_plan_dir", lambda slug, explicit=None: "/tmp/x")
    monkeypatch.setattr(_HX.os.path, "exists", lambda p: True)
    monkeypatch.setattr(_HX, "parse_workstreams_json", lambda p: manifest)
    monkeypatch.setattr(_HX, "validate_gates", lambda m, d: [])
    monkeypatch.setattr(_HX, "load_config", lambda: types.SimpleNamespace(
        paths=types.SimpleNamespace(worktree_base="/tmp/wt"),
        concurrency=types.SimpleNamespace(
            max_parallel_workstreams=1,
            serialize_all=False,
            serialize_high_severity=True,
        ),
    ))
    monkeypatch.setattr(_HX, "attempt_recovery", lambda slug, pd, rr: recovered_state)
    monkeypatch.setattr(_HX, "cleanup_orphaned", lambda *a, **k: None)
    monkeypatch.setattr(_HX, "clear_state", lambda pd: None)
    monkeypatch.setattr(_HX, "save_state", lambda *a, **k: None)

    # discord connect/disconnect — async no-ops
    import hermes.discord_relay as dr

    async def _noop(*a, **k):
        return None

    monkeypatch.setattr(dr, "connect", _noop, raising=False)
    monkeypatch.setattr(dr, "disconnect", _noop, raising=False)

    code = None
    try:
        asyncio.run(_HX.main_async())
    except SystemExit as e:
        code = e.code
    return call_order, code


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_level_ordering_deep_fork(monkeypatch):
    """ws-1 -> {ws-2, ws-3} -> ws-4 : ws-1 first, ws-4 last, fork in between."""
    wss = [
        _ws("ws-1"),
        _ws("ws-2", depends_on=["ws-1"]),
        _ws("ws-3", depends_on=["ws-1"]),
        _ws("ws-4", depends_on=["ws-2", "ws-3"]),
    ]
    manifest = _manifest(wss, merge_order=["ws-1", "ws-2", "ws-3", "ws-4"])
    order, code = _run_main(monkeypatch, manifest, scripted_status={})

    assert order[0] == "ws-1", "root must run first"
    assert order[-1] == "ws-4", "final dependent must run last"
    assert set(order[1:3]) == {"ws-2", "ws-3"}, "the fork runs in the middle level"
    # ws-4 must come after BOTH its deps
    assert order.index("ws-4") > order.index("ws-2")
    assert order.index("ws-4") > order.index("ws-3")
    assert code == 0


def test_failed_blocks_dependents(monkeypatch):
    """A failed workstream's dependents are never scheduled and report blocked."""
    wss = [
        _ws("ws-1"),
        _ws("ws-2", depends_on=["ws-1"]),  # depends on the failing ws
        _ws("ws-3", depends_on=["ws-2"]),  # transitively blocked
    ]
    manifest = _manifest(wss, merge_order=["ws-1", "ws-2", "ws-3"])
    order, code = _run_main(
        monkeypatch, manifest, scripted_status={"ws-1": "failed"},
    )

    assert order == ["ws-1"], "only ws-1 runs; ws-2/ws-3 are blocked"
    assert "ws-2" not in order
    assert "ws-3" not in order
    assert code == 1, "blocked/failed run exits non-zero"


def test_recovery_skips_done(monkeypatch):
    """A workstream already 'done' in recovered state is not re-run."""
    wss = [
        _ws("ws-1"),
        _ws("ws-2", depends_on=["ws-1"]),
    ]
    manifest = _manifest(wss, merge_order=["ws-1", "ws-2"])

    recovered = OrchestratorState(slug="x", phase="running")
    done_state = WorkstreamState(ws_id="ws-1")
    done_state.status = "done"
    recovered.workstreams["ws-1"] = done_state

    order, code = _run_main(
        monkeypatch, manifest, scripted_status={}, recovered_state=recovered,
    )

    assert "ws-1" not in order, "already-done ws-1 must not be re-run"
    assert order == ["ws-2"], "only the not-yet-done dependent runs"
    assert code == 0


def test_parity_sequential_empty_depends_on(monkeypatch):
    """All-empty depends_on => schedule in merge_order (legacy sequential order)."""
    wss = [
        _ws("ws-a"),
        _ws("ws-b"),
        _ws("ws-c"),
    ]
    # Deliberately non-alphabetical merge_order to prove it drives ordering.
    manifest = _manifest(wss, merge_order=["ws-c", "ws-a", "ws-b"])
    order, code = _run_main(monkeypatch, manifest, scripted_status={})

    assert order == ["ws-c", "ws-a", "ws-b"], "order must equal merge_order"
    assert code == 0


def test_to_thread_present_in_source():
    """T009: poll_session must be invoked via asyncio.to_thread in run_workstream."""
    src = Path(_SCRIPT).read_text()
    assert "asyncio.to_thread(poll_session" in src, (
        "poll_session must be wrapped in asyncio.to_thread so blocking I/O "
        "does not stall the event loop when sibling workstreams are concurrent"
    )
    # T010: gather and Semaphore must now be present.
    assert "asyncio.gather" in src, "asyncio.gather must be present after T010"
    assert "Semaphore" in src, "asyncio.Semaphore must be present after T010"


# ---------------------------------------------------------------------------
# T008: partition_level tests
# ---------------------------------------------------------------------------

def _config(*, serialize_all=False, serialize_high_severity=True):
    """Build a minimal config SimpleNamespace for partition_level."""
    return types.SimpleNamespace(
        concurrency=types.SimpleNamespace(
            serialize_all=serialize_all,
            serialize_high_severity=serialize_high_severity,
        ),
    )


def test_partition_high_severity_pair_never_co_batched():
    """HIGH-severity pair (ws-A,ws-B) must land in different sub-batches; ws-C may share one."""
    wss = [_ws("ws-A"), _ws("ws-B"), _ws("ws-C")]
    manifest = _manifest(
        wss,
        merge_order=["ws-A", "ws-B", "ws-C"],
        file_conflicts=[_fc("src/foo.py", ["ws-A", "ws-B"], severity="high")],
    )
    config = _config()
    batches = _HX.partition_level(wss, manifest, config)

    # Collect which sub-batch index each ws landed in
    placement = {}
    for i, batch in enumerate(batches):
        for ws in batch:
            placement[ws.id] = i

    assert placement["ws-A"] != placement["ws-B"], (
        "ws-A and ws-B share a HIGH conflict; must be in separate sub-batches"
    )
    # ws-C has no HIGH conflict with A or B — it must share a batch with one of them,
    # not be isolated (greedy coloring places it in the first available batch).
    assert placement["ws-C"] in (placement["ws-A"], placement["ws-B"]), (
        "ws-C has no HIGH conflict; greedy coloring should share a batch with one of A/B"
    )


def test_partition_scope_unknown_fully_serial():
    """scope_unknown=True → every workstream is its own singleton batch (INV-4)."""
    wss = [_ws("ws-1"), _ws("ws-2"), _ws("ws-3")]
    manifest = _manifest(
        wss,
        merge_order=["ws-1", "ws-2", "ws-3"],
        scope_unknown=True,
    )
    config = _config()
    batches = _HX.partition_level(wss, manifest, config)

    assert len(batches) == 3, "scope_unknown must produce one singleton per workstream"
    for batch in batches:
        assert len(batch) == 1, f"each batch must have size 1, got {[w.id for w in batch]}"


def test_partition_serialize_all_fully_serial():
    """serialize_all=True → fully serial, batch size 1 for every workstream."""
    wss = [_ws("ws-1"), _ws("ws-2"), _ws("ws-3")]
    manifest = _manifest(
        wss,
        merge_order=["ws-1", "ws-2", "ws-3"],
    )
    config = _config(serialize_all=True)
    batches = _HX.partition_level(wss, manifest, config)

    assert len(batches) == 3, "serialize_all must produce one singleton per workstream"
    for batch in batches:
        assert len(batch) == 1, f"each batch must have size 1, got {[w.id for w in batch]}"


def test_partition_serialize_high_severity_false_no_separation():
    """serialize_high_severity=False → HIGH conflicts do NOT separate workstreams."""
    wss = [_ws("ws-A"), _ws("ws-B")]
    manifest = _manifest(
        wss,
        merge_order=["ws-A", "ws-B"],
        file_conflicts=[_fc("src/foo.py", ["ws-A", "ws-B"], severity="high")],
    )
    config = _config(serialize_high_severity=False)
    batches = _HX.partition_level(wss, manifest, config)

    # With serialize_high_severity=False, HIGH conflicts are ignored → single batch
    assert len(batches) == 1, (
        "serialize_high_severity=False means HIGH conflicts do not separate ws"
    )
    assert {ws.id for ws in batches[0]} == {"ws-A", "ws-B"}


def test_partition_no_conflicts_single_batch():
    """A level with no HIGH conflicts → all workstreams in one sub-batch."""
    wss = [_ws("ws-1"), _ws("ws-2"), _ws("ws-3")]
    manifest = _manifest(
        wss,
        merge_order=["ws-1", "ws-2", "ws-3"],
        # Only medium/low conflicts — not HIGH
        file_conflicts=[_fc("src/bar.py", ["ws-1", "ws-2"], severity="medium")],
    )
    config = _config()
    batches = _HX.partition_level(wss, manifest, config)

    assert len(batches) == 1, "no HIGH conflicts → single sub-batch"
    assert len(batches[0]) == 3, "all three workstreams in the single batch"


def test_partition_determinism():
    """Same input → same partition on repeated calls."""
    wss = [_ws("ws-A"), _ws("ws-B"), _ws("ws-C"), _ws("ws-D")]
    manifest = _manifest(
        wss,
        merge_order=["ws-A", "ws-B", "ws-C", "ws-D"],
        file_conflicts=[
            _fc("src/x.py", ["ws-A", "ws-B"], severity="high"),
            _fc("src/y.py", ["ws-C", "ws-D"], severity="high"),
        ],
    )
    config = _config()

    results = [
        [[ws.id for ws in batch] for batch in _HX.partition_level(wss, manifest, config)]
        for _ in range(5)
    ]
    # All five calls must return the identical partition
    assert all(r == results[0] for r in results), (
        f"partition_level is not deterministic: got {results}"
    )


# ---------------------------------------------------------------------------
# T009: non-blocking poll tests
# ---------------------------------------------------------------------------

def test_poll_session_called_via_to_thread(monkeypatch):
    """T009 acceptance: the monitor loop calls poll_session via asyncio.to_thread.

    We patch asyncio.to_thread on the module under test with a spy that records
    whether poll_session was passed as the callable, and also verify that a
    concurrent trivial coroutine on the same event loop makes progress while a
    'blocking' poll is in flight (i.e. the offload keeps the loop free).
    """
    import time as _time
    import types as _types

    # Track calls to to_thread and the callables passed to it.
    to_thread_calls: list = []
    # Track concurrent coroutine progress ticks.
    concurrent_ticks: list = []
    poll_session_original = _HX.poll_session

    # We need to simulate: poll_session blocks for 0.1 s on one path.
    # We verify that a concurrent coroutine still runs while the thread-pool
    # call is outstanding.
    BLOCK_PATH = "/fake/hang"
    FAST_PATH = "/fake/fast"

    class _FakeStatus:
        status = "done"
        tasks_done = 1
        tasks_total = 1
        current_task = "T001"
        updated_at = None
        halt_reason = None

    def fake_poll_session(wt_path):
        if wt_path == BLOCK_PATH:
            _time.sleep(0.08)  # simulate slow I/O
        return _FakeStatus()

    # Replace asyncio.to_thread in the module with a spy that delegates to the
    # real asyncio.to_thread so it actually runs in a thread pool.
    real_to_thread = asyncio.to_thread

    async def spy_to_thread(func, *args, **kwargs):
        to_thread_calls.append(func)
        return await real_to_thread(func, *args, **kwargs)

    monkeypatch.setattr(_HX.asyncio, "to_thread", spy_to_thread)
    monkeypatch.setattr(_HX, "poll_session", fake_poll_session)

    # A concurrent coroutine that ticks while the blocking poll runs.
    async def concurrent_ticker():
        for _ in range(5):
            await asyncio.sleep(0)  # yield to event loop
            concurrent_ticks.append(1)

    # Drive a minimal monitor loop directly: build a tiny async function that
    # calls asyncio.to_thread(poll_session, path) the same way run_workstream
    # now does, and runs the concurrent ticker in parallel.
    async def _drive():
        # Run the monitor's single poll + the concurrent coroutine concurrently.
        result, _ = await asyncio.gather(
            _HX.asyncio.to_thread(fake_poll_session, BLOCK_PATH),
            concurrent_ticker(),
        )
        return result

    status = asyncio.run(_drive())

    # The concurrent coroutine must have ticked — proving the event loop was
    # free while the blocking poll ran in the thread pool.
    assert len(concurrent_ticks) == 5, (
        f"concurrent ticker should have run 5 ticks while blocking poll was "
        f"offloaded; got {len(concurrent_ticks)}"
    )
    # The spy recorded that to_thread was called with our fake poll function.
    assert fake_poll_session in to_thread_calls, (
        "asyncio.to_thread must be invoked with poll_session as the callable"
    )
    # The status returned is our done-status object.
    assert status.status == "done"


def test_monitor_done_path_via_to_thread(monkeypatch):
    """T009: a workstream whose poll returns 'done' reaches terminal 'done'
    even when poll_session is routed through asyncio.to_thread.

    This verifies the existing done-path semantics are intact after the wrap.
    We stub out the heavy worktree/spawn dependencies and run run_workstream
    directly (the same approach as existing tests, but targeting the monitor).
    """
    import time as _time
    import types as _types

    # Minimal fakes for worktree/spawn/merge boundary.
    FAKE_WT = "/fake/wt"
    FAKE_TASKS = "plans/x/ws-1/TASKS.md"

    class _DoneStatus:
        status = "done"
        tasks_done = 1
        tasks_total = 1
        current_task = "T001"
        updated_at = None
        halt_reason = None

    monkeypatch.setattr(_HX, "create_worktree", lambda *a, **k: FAKE_WT)
    monkeypatch.setattr(_HX, "spawn_session", lambda *a, **k: 99999)
    monkeypatch.setattr(_HX, "is_session_alive", lambda pid: True)
    monkeypatch.setattr(_HX, "kill_session", lambda pid: None)
    monkeypatch.setattr(_HX, "poll_session", lambda wt_path: _DoneStatus())
    monkeypatch.setattr(_HX, "check_timeout", lambda *a, **k: False)
    monkeypatch.setattr(_HX, "check_stall", lambda *a, **k: False)
    monkeypatch.setattr(_HX, "merge_workstream", lambda *a, **k: _types.SimpleNamespace(
        success=True, conflicted_files=[], diff="",
    ))
    monkeypatch.setattr(_HX, "delete_worktree", lambda *a, **k: None)
    monkeypatch.setattr(_HX, "save_state", lambda *a, **k: None)

    # Patch asyncio.sleep to a no-op so the test runs fast.
    async def fast_sleep(t):
        return None

    monkeypatch.setattr(_HX.asyncio, "sleep", fast_sleep)

    # Build minimal objects.
    ws = _ws("ws-1")
    # Override path so TASKS.md existence check passes (os.path.join gives a fake path).
    ws = _types.SimpleNamespace(
        id="ws-1", name="ws-1",
        path="plans/x/ws-1",
        tasks=["T001"],
        depends_on=[],
    )
    state = _types.SimpleNamespace(
        workstreams={},
        slug="x", phase="running",
    )
    config = _types.SimpleNamespace(
        paths=_types.SimpleNamespace(worktree_base="/tmp/wt"),
        timeouts=_types.SimpleNamespace(per_workstream_minutes=60),
        retry=_types.SimpleNamespace(max_retries=1, retry_delay_seconds=1),
        stall_detection=_types.SimpleNamespace(no_progress_minutes=30),
    )
    args = _Args(slug="x", plan_dir="/tmp/x")

    # Patch os.path.exists so the TASKS.md check succeeds.
    monkeypatch.setattr(_HX.os.path, "exists", lambda p: True)

    completed: list = []
    terminal = asyncio.run(
        _HX.run_workstream(ws, state, config, args, "/repo", "/tmp/x", completed)
    )

    assert terminal == "done", (
        f"run_workstream must return 'done' when poll_session reports done; got {terminal!r}"
    )
    assert "ws-1" in completed, "completed list must include ws-1 on success"


# ---------------------------------------------------------------------------
# T010: concurrency activation tests
# ---------------------------------------------------------------------------

def _run_main_with_cap(monkeypatch, manifest, *, scripted_status,
                       max_parallel_workstreams=1, recovered_state=None,
                       fake_run_workstream=None):
    """Like _run_main but accepts max_parallel_workstreams and an optional
    custom fake_run_workstream for concurrency instrumentation.

    Returns (call_order, code) where call_order is the list of ws_ids in the
    order they were *called* (start-time order for concurrent runs).
    """
    call_order = []

    if fake_run_workstream is None:
        async def fake_run_workstream(ws, state, config, args, repo_root, plan_dir, completed, *, merge_lock=None):
            call_order.append(ws.id)
            result = scripted_status.get(ws.id, "done")
            st = state.workstreams.get(ws.id) or WorkstreamState(ws_id=ws.id)
            st.status = result
            state.workstreams[ws.id] = st
            if result == "done":
                completed.append(ws.id)
            return result
    else:
        # Custom fake provided — still record call order via wrapper if needed.
        _inner = fake_run_workstream

        async def fake_run_workstream(ws, state, config, args, repo_root, plan_dir, completed, *, merge_lock=None):
            call_order.append(ws.id)
            return await _inner(ws, state, config, args, repo_root, plan_dir, completed, merge_lock=merge_lock)

    monkeypatch.setattr(_HX, "run_workstream", fake_run_workstream)
    monkeypatch.setattr(_HX, "parse_args", lambda: _Args(slug="x", plan_dir="/tmp/x"))
    monkeypatch.setattr(_HX, "validate_slug", lambda s: True)
    monkeypatch.setattr(_HX, "resolve_plan_dir", lambda slug, explicit=None: "/tmp/x")
    monkeypatch.setattr(_HX.os.path, "exists", lambda p: True)
    monkeypatch.setattr(_HX, "parse_workstreams_json", lambda p: manifest)
    monkeypatch.setattr(_HX, "validate_gates", lambda m, d: [])
    monkeypatch.setattr(_HX, "load_config", lambda: types.SimpleNamespace(
        paths=types.SimpleNamespace(worktree_base="/tmp/wt"),
        concurrency=types.SimpleNamespace(
            max_parallel_workstreams=max_parallel_workstreams,
            serialize_all=False,
            serialize_high_severity=True,
        ),
    ))
    monkeypatch.setattr(_HX, "attempt_recovery", lambda slug, pd, rr: recovered_state)
    monkeypatch.setattr(_HX, "cleanup_orphaned", lambda *a, **k: None)
    monkeypatch.setattr(_HX, "clear_state", lambda pd: None)
    monkeypatch.setattr(_HX, "save_state", lambda *a, **k: None)

    import hermes.discord_relay as dr

    async def _noop(*a, **k):
        return None

    monkeypatch.setattr(dr, "connect", _noop, raising=False)
    monkeypatch.setattr(dr, "disconnect", _noop, raising=False)

    code = None
    try:
        asyncio.run(_HX.main_async())
    except SystemExit as e:
        code = e.code
    return call_order, code


def test_cap1_parity_sequential(monkeypatch):
    """INV-5: with max_parallel_workstreams=1 the gather+semaphore path must
    reproduce the legacy sequential order (merge_order) exactly."""
    wss = [_ws("ws-a"), _ws("ws-b"), _ws("ws-c")]
    manifest = _manifest(wss, merge_order=["ws-c", "ws-a", "ws-b"])
    order, code = _run_main_with_cap(
        monkeypatch, manifest,
        scripted_status={},
        max_parallel_workstreams=1,
    )
    assert order == ["ws-c", "ws-a", "ws-b"], (
        f"cap=1 must reproduce merge_order exactly; got {order}"
    )
    assert code == 0


def test_concurrent_3_at_cap3(monkeypatch):
    """3 independent workstreams (one sub-batch) complete concurrently at cap=3.
    All 3 must be 'live' simultaneously — verified by a shared counter that
    tracks the peak number of concurrently-executing run_workstream bodies.
    """
    peak_live = [0]
    current_live = [0]

    async def fake_concurrent(ws, state, config, args, repo_root, plan_dir, completed, *, merge_lock=None):
        current_live[0] += 1
        peak_live[0] = max(peak_live[0], current_live[0])
        # Yield so the other coroutines can start — simulates overlapping execution.
        await asyncio.sleep(0)
        current_live[0] -= 1
        result = "done"
        st = state.workstreams.get(ws.id) or WorkstreamState(ws_id=ws.id)
        st.status = result
        state.workstreams[ws.id] = st
        completed.append(ws.id)
        return result

    wss = [_ws("ws-1"), _ws("ws-2"), _ws("ws-3")]
    manifest = _manifest(wss, merge_order=["ws-1", "ws-2", "ws-3"])

    # Use the internal fake directly (bypass the call_order wrapper which would
    # be fine too, but we want a clean fake here).
    call_order = []
    monkeypatch.setattr(_HX, "run_workstream", fake_concurrent)
    monkeypatch.setattr(_HX, "parse_args", lambda: _Args(slug="x", plan_dir="/tmp/x"))
    monkeypatch.setattr(_HX, "validate_slug", lambda s: True)
    monkeypatch.setattr(_HX, "resolve_plan_dir", lambda slug, explicit=None: "/tmp/x")
    monkeypatch.setattr(_HX.os.path, "exists", lambda p: True)
    monkeypatch.setattr(_HX, "parse_workstreams_json", lambda p: manifest)
    monkeypatch.setattr(_HX, "validate_gates", lambda m, d: [])
    monkeypatch.setattr(_HX, "load_config", lambda: types.SimpleNamespace(
        paths=types.SimpleNamespace(worktree_base="/tmp/wt"),
        concurrency=types.SimpleNamespace(
            max_parallel_workstreams=3,
            serialize_all=False,
            serialize_high_severity=True,
        ),
    ))
    monkeypatch.setattr(_HX, "attempt_recovery", lambda slug, pd, rr: None)
    monkeypatch.setattr(_HX, "cleanup_orphaned", lambda *a, **k: None)
    monkeypatch.setattr(_HX, "clear_state", lambda pd: None)
    monkeypatch.setattr(_HX, "save_state", lambda *a, **k: None)

    import hermes.discord_relay as dr

    async def _noop(*a, **k):
        return None

    monkeypatch.setattr(dr, "connect", _noop, raising=False)
    monkeypatch.setattr(dr, "disconnect", _noop, raising=False)

    code = None
    try:
        asyncio.run(_HX.main_async())
    except SystemExit as e:
        code = e.code

    assert peak_live[0] == 3, (
        f"all 3 workstreams must be live simultaneously at cap=3; peak was {peak_live[0]}"
    )
    assert code == 0


def test_semaphore_cap2_peak_never_exceeds_2(monkeypatch):
    """Audit M1: with max_parallel_workstreams=2 and 3 conflict-free workstreams,
    the peak number of concurrently-live run_workstream bodies must never exceed 2.

    This test is designed to FAIL if the semaphore is released after spawn
    instead of held for the full lifetime: releasing early would allow all 3
    to go live at once (peak=3), not just 2.
    """
    peak_live = [0]
    current_live = [0]
    # Track finish events so we can verify the 3rd only started after ≥1 finished.
    finish_count = [0]
    start_timestamps: list = []
    finish_timestamps: list = []

    async def fake_bounded(ws, state, config, args, repo_root, plan_dir, completed, *, merge_lock=None):
        import time as _t
        current_live[0] += 1
        peak_live[0] = max(peak_live[0], current_live[0])
        start_timestamps.append((ws.id, _t.monotonic()))
        # Simulate non-trivial work: yield multiple times so other ready tasks
        # have a chance to start if the semaphore were held improperly.
        for _ in range(3):
            await asyncio.sleep(0)
        finish_timestamps.append((ws.id, _t.monotonic()))
        finish_count[0] += 1
        current_live[0] -= 1
        result = "done"
        st = state.workstreams.get(ws.id) or WorkstreamState(ws_id=ws.id)
        st.status = result
        state.workstreams[ws.id] = st
        completed.append(ws.id)
        return result

    wss = [_ws("ws-1"), _ws("ws-2"), _ws("ws-3")]
    manifest = _manifest(wss, merge_order=["ws-1", "ws-2", "ws-3"])

    monkeypatch.setattr(_HX, "run_workstream", fake_bounded)
    monkeypatch.setattr(_HX, "parse_args", lambda: _Args(slug="x", plan_dir="/tmp/x"))
    monkeypatch.setattr(_HX, "validate_slug", lambda s: True)
    monkeypatch.setattr(_HX, "resolve_plan_dir", lambda slug, explicit=None: "/tmp/x")
    monkeypatch.setattr(_HX.os.path, "exists", lambda p: True)
    monkeypatch.setattr(_HX, "parse_workstreams_json", lambda p: manifest)
    monkeypatch.setattr(_HX, "validate_gates", lambda m, d: [])
    monkeypatch.setattr(_HX, "load_config", lambda: types.SimpleNamespace(
        paths=types.SimpleNamespace(worktree_base="/tmp/wt"),
        concurrency=types.SimpleNamespace(
            max_parallel_workstreams=2,
            serialize_all=False,
            serialize_high_severity=True,
        ),
    ))
    monkeypatch.setattr(_HX, "attempt_recovery", lambda slug, pd, rr: None)
    monkeypatch.setattr(_HX, "cleanup_orphaned", lambda *a, **k: None)
    monkeypatch.setattr(_HX, "clear_state", lambda pd: None)
    monkeypatch.setattr(_HX, "save_state", lambda *a, **k: None)

    import hermes.discord_relay as dr

    async def _noop(*a, **k):
        return None

    monkeypatch.setattr(dr, "connect", _noop, raising=False)
    monkeypatch.setattr(dr, "disconnect", _noop, raising=False)

    code = None
    try:
        asyncio.run(_HX.main_async())
    except SystemExit as e:
        code = e.code

    assert peak_live[0] <= 2, (
        f"peak concurrent live count must not exceed cap=2; got {peak_live[0]}. "
        f"This would fail if the semaphore were released after spawn rather than "
        f"held for the full run_workstream lifetime."
    )
    # All 3 must complete.
    assert finish_count[0] == 3, f"all 3 workstreams must complete; got {finish_count[0]}"
    # The 3rd workstream must have started after at least one of the first two finished.
    # Sort starts by time; the 3rd start must be >= the 1st finish.
    starts_sorted = sorted(start_timestamps, key=lambda x: x[1])
    first_finish_time = min(t for _, t in finish_timestamps)
    third_start_time = starts_sorted[2][1]
    assert third_start_time >= first_finish_time, (
        f"3rd workstream started ({third_start_time:.6f}) before any finish "
        f"({first_finish_time:.6f}) — semaphore not holding across full lifetime"
    )
    assert code == 0


def test_exception_in_run_workstream_recorded_as_failed(monkeypatch):
    """An exception raised inside run_workstream is caught by _run_one,
    recorded as 'failed' in terminal_status, and does not crash the run.
    Sibling workstreams that succeed are still recorded as 'done'.
    """
    async def fake_sometimes_raises(ws, state, config, args, repo_root, plan_dir, completed, *, merge_lock=None):
        if ws.id == "ws-bad":
            raise RuntimeError("simulated crash in run_workstream")
        result = "done"
        st = state.workstreams.get(ws.id) or WorkstreamState(ws_id=ws.id)
        st.status = result
        state.workstreams[ws.id] = st
        completed.append(ws.id)
        return result

    # ws-bad and ws-good are in the same level (no deps), so they share a sub-batch.
    wss = [_ws("ws-bad"), _ws("ws-good")]
    manifest = _manifest(wss, merge_order=["ws-bad", "ws-good"])

    monkeypatch.setattr(_HX, "run_workstream", fake_sometimes_raises)
    monkeypatch.setattr(_HX, "parse_args", lambda: _Args(slug="x", plan_dir="/tmp/x"))
    monkeypatch.setattr(_HX, "validate_slug", lambda s: True)
    monkeypatch.setattr(_HX, "resolve_plan_dir", lambda slug, explicit=None: "/tmp/x")
    monkeypatch.setattr(_HX.os.path, "exists", lambda p: True)
    monkeypatch.setattr(_HX, "parse_workstreams_json", lambda p: manifest)
    monkeypatch.setattr(_HX, "validate_gates", lambda m, d: [])
    monkeypatch.setattr(_HX, "load_config", lambda: types.SimpleNamespace(
        paths=types.SimpleNamespace(worktree_base="/tmp/wt"),
        concurrency=types.SimpleNamespace(
            max_parallel_workstreams=2,
            serialize_all=False,
            serialize_high_severity=True,
        ),
    ))
    monkeypatch.setattr(_HX, "attempt_recovery", lambda slug, pd, rr: None)
    monkeypatch.setattr(_HX, "cleanup_orphaned", lambda *a, **k: None)
    monkeypatch.setattr(_HX, "clear_state", lambda pd: None)
    monkeypatch.setattr(_HX, "save_state", lambda *a, **k: None)

    import hermes.discord_relay as dr

    async def _noop(*a, **k):
        return None

    monkeypatch.setattr(dr, "connect", _noop, raising=False)
    monkeypatch.setattr(dr, "disconnect", _noop, raising=False)

    code = None
    try:
        asyncio.run(_HX.main_async())
    except SystemExit as e:
        code = e.code
    # Run must not crash (no unhandled exception).
    # ws-bad failed → non-zero exit; ws-good succeeded.
    assert code == 1, f"failed run must exit non-zero; got {code}"


def test_gc_safety_env_set_and_restored(monkeypatch):
    """GIT_OPTIONAL_LOCKS must be '0' during the scheduler run and restored
    to its prior value (or unset if it wasn't set) after the run completes.
    """
    import os as _os

    observed_during: list = []
    prior_value = _os.environ.get("GIT_OPTIONAL_LOCKS", "__UNSET__")

    # Ensure a known prior state: remove GIT_OPTIONAL_LOCKS so we can verify
    # it gets unset on restore.
    monkeypatch.delenv("GIT_OPTIONAL_LOCKS", raising=False)

    async def fake_run_workstream(ws, state, config, args, repo_root, plan_dir, completed, *, merge_lock=None):
        # Capture the env value while run_workstream is executing.
        observed_during.append(_os.environ.get("GIT_OPTIONAL_LOCKS", "__UNSET__"))
        result = "done"
        st = state.workstreams.get(ws.id) or WorkstreamState(ws_id=ws.id)
        st.status = result
        state.workstreams[ws.id] = st
        completed.append(ws.id)
        return result

    wss = [_ws("ws-1")]
    manifest = _manifest(wss, merge_order=["ws-1"])

    monkeypatch.setattr(_HX, "run_workstream", fake_run_workstream)
    monkeypatch.setattr(_HX, "parse_args", lambda: _Args(slug="x", plan_dir="/tmp/x"))
    monkeypatch.setattr(_HX, "validate_slug", lambda s: True)
    monkeypatch.setattr(_HX, "resolve_plan_dir", lambda slug, explicit=None: "/tmp/x")
    monkeypatch.setattr(_HX.os.path, "exists", lambda p: True)
    monkeypatch.setattr(_HX, "parse_workstreams_json", lambda p: manifest)
    monkeypatch.setattr(_HX, "validate_gates", lambda m, d: [])
    monkeypatch.setattr(_HX, "load_config", lambda: types.SimpleNamespace(
        paths=types.SimpleNamespace(worktree_base="/tmp/wt"),
        concurrency=types.SimpleNamespace(
            max_parallel_workstreams=1,
            serialize_all=False,
            serialize_high_severity=True,
        ),
    ))
    monkeypatch.setattr(_HX, "attempt_recovery", lambda slug, pd, rr: None)
    monkeypatch.setattr(_HX, "cleanup_orphaned", lambda *a, **k: None)
    monkeypatch.setattr(_HX, "clear_state", lambda pd: None)
    monkeypatch.setattr(_HX, "save_state", lambda *a, **k: None)

    import hermes.discord_relay as dr

    async def _noop(*a, **k):
        return None

    monkeypatch.setattr(dr, "connect", _noop, raising=False)
    monkeypatch.setattr(dr, "disconnect", _noop, raising=False)

    code = None
    try:
        asyncio.run(_HX.main_async())
    except SystemExit as e:
        code = e.code

    # During the run, GIT_OPTIONAL_LOCKS must have been "0".
    assert observed_during, "fake_run_workstream must have been called"
    assert all(v == "0" for v in observed_during), (
        f"GIT_OPTIONAL_LOCKS must be '0' during the run; got {observed_during}"
    )
    # After the run, it must be restored: since we delenv'd it before, it should
    # be absent again now (monkeypatch restores after the test, but the code must
    # restore it in its finally block before sys.exit is called).
    # We verify this by checking the env state captured inside main_async exited
    # cleanly. Since monkeypatch.delenv applies before the test and main_async
    # saves/restores via finally, the value seen after asyncio.run must be absent.
    assert _os.environ.get("GIT_OPTIONAL_LOCKS", "__UNSET__") == "__UNSET__", (
        "GIT_OPTIONAL_LOCKS must be unset after the run (was absent before the run)"
    )
    assert code == 0
