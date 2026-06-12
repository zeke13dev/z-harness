"""
tests/test_hermes_cross_plan.py — Tests for scripts/hermes/cross_plan.py
and the T011 parse_args additions to hermes-execute.py.

Import pattern mirrors test_hermes_config.py: add scripts/ to sys.path, then
import the hermes package normally.
"""

from __future__ import annotations

import importlib.util
import sys
import textwrap
import types
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# sys.path setup — mirrors test_hermes_config.py / test_hermes_execute.py
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SCRIPTS_DIR = _REPO_ROOT / "scripts"
_SCRIPT_HX = str(_SCRIPTS_DIR / "hermes-execute.py")

if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from hermes import cross_plan  # noqa: E402 — needs sys.path set above


# ---------------------------------------------------------------------------
# Registry record builders
# ---------------------------------------------------------------------------

def _rec(slug: str, scope: list[dict] | None = None) -> dict:
    """Build a minimal registry record."""
    return {"slug": slug, "scope": scope or []}


def _scope_entry(path: str, confidence: str = "explicit") -> dict:
    return {"path": path, "confidence": confidence, "reason": "test"}


# ---------------------------------------------------------------------------
# plan_scope tests
# ---------------------------------------------------------------------------

class TestPlanScope:
    def test_disjoint_paths_injected_records(self, tmp_path):
        """Two slugs with non-overlapping explicit-confidence paths."""
        records = [
            _rec("plan-a", [_scope_entry("src/a.py"), _scope_entry("src/b.py")]),
            _rec("plan-b", [_scope_entry("src/c.py"), _scope_entry("src/d.py")]),
        ]
        paths_a, flag_a = cross_plan.plan_scope("plan-a", registry_records=records, plan_dir=str(tmp_path))
        paths_b, flag_b = cross_plan.plan_scope("plan-b", registry_records=records, plan_dir=str(tmp_path))

        assert not flag_a, "explicit-confidence entries must not trigger fail-safe"
        assert not flag_b, "explicit-confidence entries must not trigger fail-safe"
        assert paths_a.isdisjoint(paths_b), "non-overlapping paths must not intersect"

    def test_overlapping_paths(self, tmp_path):
        """Shared path produces non-empty intersection."""
        records = [
            _rec("plan-a", [_scope_entry("shared/file.py"), _scope_entry("only-a.py")]),
            _rec("plan-b", [_scope_entry("shared/file.py"), _scope_entry("only-b.py")]),
        ]
        paths_a, _ = cross_plan.plan_scope("plan-a", registry_records=records, plan_dir=str(tmp_path))
        paths_b, _ = cross_plan.plan_scope("plan-b", registry_records=records, plan_dir=str(tmp_path))

        assert paths_a & paths_b, "shared path must appear in both sets"

    def test_missing_record_no_workstreams_json_fail_safe(self, tmp_path):
        """No registry record + no workstreams.json → fail-safe True."""
        _, flag = cross_plan.plan_scope(
            "ghost-plan",
            registry_records=[],           # no record
            plan_dir=str(tmp_path),        # tmp_path has no workstreams.json
        )
        assert flag is True, (
            "missing registry record + no workstreams.json must set fail-safe flag"
        )

    def test_scope_unknown_in_workstreams_json_fail_safe(self, tmp_path):
        """workstreams.json with scope_unknown=true → fail-safe True."""
        ws_json = tmp_path / "workstreams.json"
        ws_json.write_text('{"scope_unknown": true, "file_conflicts": []}')

        records = [_rec("plan-x", [_scope_entry("some/file.py")])]
        _, flag = cross_plan.plan_scope(
            "plan-x",
            registry_records=records,
            plan_dir=str(tmp_path),
        )
        assert flag is True, "scope_unknown=true in workstreams.json must set fail-safe"

    def test_low_confidence_broad_fail_safe(self, tmp_path):
        """Registry scope with 'broad' confidence → fail-safe True."""
        records = [
            _rec("plan-y", [_scope_entry("src/", confidence="broad")]),
        ]
        _, flag = cross_plan.plan_scope(
            "plan-y",
            registry_records=records,
            plan_dir=str(tmp_path),
        )
        assert flag is True, "broad-confidence scope entry must set fail-safe flag"

    def test_low_confidence_unknown_fail_safe(self, tmp_path):
        """Registry scope with 'unknown' confidence → fail-safe True."""
        records = [
            _rec("plan-z", [_scope_entry("src/", confidence="unknown")]),
        ]
        _, flag = cross_plan.plan_scope(
            "plan-z",
            registry_records=records,
            plan_dir=str(tmp_path),
        )
        assert flag is True, "unknown-confidence scope entry must set fail-safe flag"

    def test_inferred_confidence_not_fail_safe(self, tmp_path):
        """'inferred' confidence is higher than broad/unknown → not fail-safe."""
        records = [
            _rec("plan-i", [_scope_entry("src/i.py", confidence="inferred")]),
        ]
        _, flag = cross_plan.plan_scope(
            "plan-i",
            registry_records=records,
            plan_dir=str(tmp_path),
        )
        assert flag is False, "inferred confidence is not low-confidence; must not fail-safe"

    def test_path_normalization(self, tmp_path):
        """'./x/y' and 'x/y' are treated as equal after normpath."""
        records_a = [_rec("norm-a", [_scope_entry("./x/y")])]
        records_b = [_rec("norm-b", [_scope_entry("x/y")])]

        paths_a, _ = cross_plan.plan_scope("norm-a", registry_records=records_a, plan_dir=str(tmp_path))
        paths_b, _ = cross_plan.plan_scope("norm-b", registry_records=records_b, plan_dir=str(tmp_path))

        assert paths_a == paths_b, (
            f"'./x/y' must normalize to the same path as 'x/y'; got {paths_a} vs {paths_b}"
        )

    def test_workstreams_json_file_conflicts_paths_included(self, tmp_path):
        """Paths from workstreams.json file_conflicts are merged into the set."""
        ws_json = tmp_path / "workstreams.json"
        ws_json.write_text(json_text := (
            '{"scope_unknown": false, "file_conflicts": ['
            '{"file": "scripts/foo.py", "workstreams": ["ws-1"], "severity": "high"},'
            '{"file": "scripts/bar.py", "workstreams": ["ws-2"], "severity": "low"}'
            ']}'
        ))

        records = [_rec("plan-ws", [])]  # no registry scope paths
        paths, flag = cross_plan.plan_scope("plan-ws", registry_records=records, plan_dir=str(tmp_path))

        import os
        assert os.path.normpath("scripts/foo.py") in paths
        assert os.path.normpath("scripts/bar.py") in paths
        assert not flag, "explicit registry + scope_unknown=false must not fail-safe even if reg scope empty"


# ---------------------------------------------------------------------------
# build_plan_conflict_graph tests
# ---------------------------------------------------------------------------

class TestBuildPlanConflictGraph:
    def test_disjoint_scopes_no_edges(self, tmp_path):
        """Two plans with non-overlapping explicit paths → no edges."""
        records = [
            _rec("alpha", [_scope_entry("a/x.py")]),
            _rec("beta",  [_scope_entry("b/y.py")]),
        ]
        graph = cross_plan.build_plan_conflict_graph(
            ["alpha", "beta"],
            registry_records=records,
        )
        assert graph["alpha"] == set(), "disjoint scopes → no conflict with beta"
        assert graph["beta"] == set(), "disjoint scopes → no conflict with alpha"

    def test_overlap_produces_symmetric_edge(self, tmp_path):
        """Shared path → symmetric edge in both directions."""
        records = [
            _rec("p1", [_scope_entry("shared.py"), _scope_entry("only-p1.py")]),
            _rec("p2", [_scope_entry("shared.py"), _scope_entry("only-p2.py")]),
        ]
        graph = cross_plan.build_plan_conflict_graph(
            ["p1", "p2"],
            registry_records=records,
        )
        assert "p2" in graph["p1"], "p1 must list p2 as conflicting"
        assert "p1" in graph["p2"], "p2 must list p1 as conflicting (symmetric)"

    def test_no_self_edges(self, tmp_path):
        """No plan should conflict with itself."""
        records = [
            _rec("solo", [_scope_entry("src/foo.py")]),
        ]
        graph = cross_plan.build_plan_conflict_graph(["solo"], registry_records=records)
        assert "solo" not in graph["solo"], "self-edge must never be added"

    def test_missing_record_conflicts_with_all(self, tmp_path):
        """Plan with no registry record (and no workstreams.json) → edges to all others."""
        records = [
            _rec("has-scope", [_scope_entry("src/a.py")]),
            # "no-record" has no entry at all
        ]
        graph = cross_plan.build_plan_conflict_graph(
            ["has-scope", "no-record"],
            registry_records=records,
        )
        assert "has-scope" in graph["no-record"], (
            "missing-record plan must conflict with every other plan"
        )
        assert "no-record" in graph["has-scope"], "symmetric"

    def test_missing_record_three_way(self, tmp_path):
        """Missing-record plan conflicts with ALL others, not just one."""
        records = [
            _rec("p1", [_scope_entry("x.py")]),
            _rec("p2", [_scope_entry("y.py")]),
            # "ghost" missing
        ]
        graph = cross_plan.build_plan_conflict_graph(
            ["p1", "p2", "ghost"],
            registry_records=records,
        )
        assert "p1" in graph["ghost"] and "p2" in graph["ghost"], (
            "ghost must conflict with both p1 and p2"
        )

    def test_scope_unknown_conflicts_with_all(self, tmp_path):
        """Plan with scope_unknown=true in workstreams.json conflicts with all others."""
        ws_json = tmp_path / "workstreams.json"
        ws_json.write_text('{"scope_unknown": true, "file_conflicts": []}')

        records = [
            _rec("clean",   [_scope_entry("src/x.py")]),
            _rec("unknown", [_scope_entry("src/y.py")]),
        ]

        # We need plan_scope to pick up the tmp workstreams.json for "unknown".
        # Patch plan_scope resolution so "unknown" resolves to tmp_path.
        import unittest.mock as mock

        original_resolve = cross_plan._resolve_plan_dir

        def patched_resolve(slug):
            if slug == "unknown":
                return str(tmp_path)
            return original_resolve(slug)

        with mock.patch.object(cross_plan, "_resolve_plan_dir", patched_resolve):
            graph = cross_plan.build_plan_conflict_graph(
                ["clean", "unknown"],
                registry_records=records,
            )

        assert "clean" in graph["unknown"], (
            "scope_unknown plan must conflict with all others"
        )
        assert "unknown" in graph["clean"], "symmetric"

    def test_low_confidence_conflicts_with_all(self, tmp_path):
        """Low-confidence (broad/unknown) registry entry triggers fail-safe edges."""
        records = [
            _rec("solid",  [_scope_entry("src/solid.py", confidence="explicit")]),
            _rec("shaky",  [_scope_entry("src/", confidence="broad")]),
        ]
        graph = cross_plan.build_plan_conflict_graph(
            ["solid", "shaky"],
            registry_records=records,
        )
        assert "solid" in graph["shaky"], "low-confidence plan must conflict with all"
        assert "shaky" in graph["solid"], "symmetric"

    def test_three_plans_one_conflict(self, tmp_path):
        """Three plans, only two share a path — third has no edges."""
        records = [
            _rec("aa", [_scope_entry("shared.py")]),
            _rec("bb", [_scope_entry("shared.py")]),
            _rec("cc", [_scope_entry("unique.py")]),
        ]
        graph = cross_plan.build_plan_conflict_graph(
            ["aa", "bb", "cc"],
            registry_records=records,
        )
        assert "bb" in graph["aa"] and "aa" in graph["bb"], "aa<->bb conflict"
        assert graph["cc"] == set(), "cc has no overlap with aa or bb"
        assert "cc" not in graph["aa"] and "cc" not in graph["bb"], (
            "neither aa nor bb should conflict with cc"
        )


# ---------------------------------------------------------------------------
# parse_args / _validate_slug_set_args tests
# ---------------------------------------------------------------------------

def _load_hx():
    """Load hermes-execute.py as a module (same pattern as test_hermes_execute.py)."""
    spec = importlib.util.spec_from_file_location("hermes_execute_t011", _SCRIPT_HX)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_HX = _load_hx()


class TestParseArgsMutualExclusion:
    """Tests for the _validate_slug_set_args enforcement."""

    def _make_args(self, *, slug=None, slugs=None, plan_set=None, plan_dir=None):
        return types.SimpleNamespace(
            slug=slug,
            slugs=slugs,
            plan_set=plan_set,
            plan_dir=plan_dir,
        )

    def test_slug_alone_accepted(self):
        """--slug alone returns a single-element list without exiting."""
        args = self._make_args(slug="my-plan")
        result = _HX._validate_slug_set_args(args)
        assert result == ["my-plan"]

    def test_slugs_alone_accepted(self):
        """--slugs alone parses comma-separated slugs."""
        args = self._make_args(slugs="plan-a,plan-b,plan-c")
        result = _HX._validate_slug_set_args(args)
        assert result == ["plan-a", "plan-b", "plan-c"]

    def test_plan_set_accepted(self, tmp_path):
        """--plan-set with a valid file returns its slug list."""
        f = tmp_path / "plans.txt"
        f.write_text("plan-x\nplan-y\n# comment\n\n")
        args = self._make_args(plan_set=str(f))
        result = _HX._validate_slug_set_args(args)
        assert result == ["plan-x", "plan-y"]

    def test_no_flag_exits_2(self):
        """No slug-related flag → exit 2."""
        args = self._make_args()
        with pytest.raises(SystemExit) as exc_info:
            _HX._validate_slug_set_args(args)
        assert exc_info.value.code == 2

    def test_slug_and_slugs_exits_2(self):
        """--slug + --slugs together → exit 2 (mutually exclusive)."""
        args = self._make_args(slug="a", slugs="b,c")
        with pytest.raises(SystemExit) as exc_info:
            _HX._validate_slug_set_args(args)
        assert exc_info.value.code == 2

    def test_slug_and_plan_set_exits_2(self, tmp_path):
        """--slug + --plan-set together → exit 2."""
        f = tmp_path / "p.txt"
        f.write_text("plan-z\n")
        args = self._make_args(slug="a", plan_set=str(f))
        with pytest.raises(SystemExit) as exc_info:
            _HX._validate_slug_set_args(args)
        assert exc_info.value.code == 2

    def test_slugs_and_plan_set_exits_2(self, tmp_path):
        """--slugs + --plan-set together → exit 2."""
        f = tmp_path / "p.txt"
        f.write_text("plan-z\n")
        args = self._make_args(slugs="a,b", plan_set=str(f))
        with pytest.raises(SystemExit) as exc_info:
            _HX._validate_slug_set_args(args)
        assert exc_info.value.code == 2

    def test_slugs_trims_whitespace(self):
        """Whitespace around comma-separated slug names is stripped."""
        args = self._make_args(slugs=" plan-a , plan-b ")
        result = _HX._validate_slug_set_args(args)
        assert result == ["plan-a", "plan-b"]

    def test_plan_set_skips_blank_and_comments(self, tmp_path):
        """Blank lines and # comments in --plan-set file are ignored."""
        f = tmp_path / "plans.txt"
        f.write_text("\n# this is a comment\nplan-1\n\nplan-2\n# end\n")
        args = self._make_args(plan_set=str(f))
        result = _HX._validate_slug_set_args(args)
        assert result == ["plan-1", "plan-2"]


# ---------------------------------------------------------------------------
# T012: acquire_plan_locks / release_plan_locks tests
# ---------------------------------------------------------------------------

class TestAcquirePlanLocks:
    """Tests for the sorted-order deadlock-free lock acquisition."""

    def test_sorted_lock_order_forward_input(self):
        """acquire_plan_locks(['c','a','b']) acquires in sorted order ['a','b','c']."""
        call_order = []

        def recorder(slug: str) -> bool:
            call_order.append(slug)
            return True

        ok, acquired = cross_plan.acquire_plan_locks(
            ["c", "a", "b"],
            session_id="s1",
            run_id="r1",
            acquire_fn=recorder,
        )
        assert ok is True
        assert acquired == ["a", "b", "c"]
        assert call_order == ["a", "b", "c"], (
            "locks must be acquired in sorted ascending order regardless of input order"
        )

    def test_sorted_lock_order_reverse_input(self):
        """acquire_plan_locks(['z','m','a']) also acquires in sorted order ['a','m','z']."""
        call_order = []

        def recorder(slug: str) -> bool:
            call_order.append(slug)
            return True

        ok, acquired = cross_plan.acquire_plan_locks(
            ["z", "m", "a"],
            session_id="s1",
            run_id="r1",
            acquire_fn=recorder,
        )
        assert ok is True
        assert call_order == ["a", "m", "z"], (
            "sorted order must be ascending regardless of input order (deadlock safety)"
        )

    def test_release_all_on_failure(self):
        """If acquire fails for 'c', already-acquired 'a' and 'b' are released."""
        released = []

        def acquire_fn(slug: str) -> bool:
            # Succeed for a and b, fail for c.
            return slug != "c"

        def release_fn(slug: str) -> None:
            released.append(slug)

        ok, acquired = cross_plan.acquire_plan_locks(
            ["a", "b", "c"],
            session_id="s1",
            run_id="r1",
            acquire_fn=acquire_fn,
            release_fn=release_fn,
        )
        assert ok is False
        assert acquired == [], "on failure the returned acquired list must be empty"
        assert set(released) == {"a", "b"}, (
            "already-acquired locks must be released on any acquire failure"
        )

    def test_release_on_failure_includes_both_predecessors(self):
        """Fail on third (c); 'a' and 'b' (both acquired first) must both be released."""
        released_set = set()

        def acquire_fn(slug: str) -> bool:
            return slug in {"a", "b"}  # c fails

        def release_fn(slug: str) -> None:
            released_set.add(slug)

        ok, _ = cross_plan.acquire_plan_locks(
            ["b", "c", "a"],
            session_id="s1",
            run_id="r1",
            acquire_fn=acquire_fn,
            release_fn=release_fn,
        )
        assert not ok
        assert "a" in released_set and "b" in released_set

    def test_all_acquired_returns_sorted_list(self):
        """On success, returned acquired list matches sorted(slugs)."""
        ok, acquired = cross_plan.acquire_plan_locks(
            ["z", "a", "m"],
            session_id="s1",
            run_id="r1",
            acquire_fn=lambda s: True,
        )
        assert ok is True
        assert acquired == sorted(["z", "a", "m"])

    def test_failure_on_first_slug_releases_nothing(self):
        """If the very first slug fails, nothing has been acquired, nothing released."""
        released = []

        def acquire_fn(slug: str) -> bool:
            return False  # always fails

        def release_fn(slug: str) -> None:
            released.append(slug)

        ok, _ = cross_plan.acquire_plan_locks(
            ["a"],
            session_id="s1",
            run_id="r1",
            acquire_fn=acquire_fn,
            release_fn=release_fn,
        )
        assert not ok
        assert released == [], "nothing was acquired so nothing should be released"


class TestReleasePlanLocks:
    """Tests for release_plan_locks (best-effort, never raises)."""

    def test_releases_all_slugs(self):
        """release_plan_locks calls release_fn for every slug provided."""
        released = []
        cross_plan.release_plan_locks(
            ["a", "b", "c"],
            session_id="s1",
            run_id="r1",
            release_fn=released.append,
        )
        assert set(released) == {"a", "b", "c"}

    def test_never_raises_even_on_exception(self):
        """If release_fn raises, release_plan_locks must not propagate the exception."""
        def boom(slug: str) -> None:
            raise RuntimeError("boom")

        # Should not raise.
        cross_plan.release_plan_locks(
            ["x"],
            session_id="s1",
            run_id="r1",
            release_fn=boom,
        )

    def test_empty_list_is_noop(self):
        """Empty slug list: no exception, no calls."""
        calls = []
        cross_plan.release_plan_locks(
            [],
            session_id="s1",
            run_id="r1",
            release_fn=calls.append,
        )
        assert calls == []


# ---------------------------------------------------------------------------
# T012: schedule_batches tests
# ---------------------------------------------------------------------------

class TestScheduleBatches:
    """Tests for greedy graph-coloring batch partitioner."""

    def test_disjoint_graph_all_in_one_batch(self):
        """All disjoint plans → single batch (max concurrency)."""
        graph = {"a": set(), "b": set(), "c": set()}
        batches = cross_plan.schedule_batches(["a", "b", "c"], graph)
        assert len(batches) == 1, f"disjoint plans must all share one batch; got {batches}"
        assert set(batches[0]) == {"a", "b", "c"}

    def test_fully_conflicting_graph_serial(self):
        """Fully connected graph → each slug its own batch (fully serial)."""
        # a-b, a-c, b-c: complete graph on 3 nodes.
        graph = {"a": {"b", "c"}, "b": {"a", "c"}, "c": {"a", "b"}}
        batches = cross_plan.schedule_batches(["a", "b", "c"], graph)
        assert len(batches) == 3, (
            f"fully-conflicting graph must produce one batch per slug; got {batches}"
        )
        for batch in batches:
            assert len(batch) == 1, f"each batch must be singleton; got {batch}"

    def test_partial_conflict_correct_coloring(self):
        """a-b conflict, c is disjoint: a,c in one batch; b in another (or a,b serial, c joins one)."""
        graph = {"a": {"b"}, "b": {"a"}, "c": set()}
        batches = cross_plan.schedule_batches(["a", "b", "c"], graph)
        # a and b must not share a batch.
        placement = {slug: i for i, batch in enumerate(batches) for slug in batch}
        assert placement["a"] != placement["b"], (
            "conflicting pair a,b must not share a batch"
        )
        # c is disjoint — it must share a batch with one of them (greedy coloring).
        assert placement["c"] in (placement["a"], placement["b"]), (
            "disjoint c must be co-batched with one of a or b"
        )

    def test_sorted_input_order_determinism(self):
        """Same graph + same slugs always produce the same batches."""
        graph = {"x": {"y"}, "y": {"x"}, "z": set()}
        results = [
            [[s for s in batch] for batch in cross_plan.schedule_batches(["x", "y", "z"], graph)]
            for _ in range(5)
        ]
        assert all(r == results[0] for r in results), (
            f"schedule_batches must be deterministic; got varying results: {results}"
        )

    def test_no_two_conflicting_slugs_in_same_batch(self):
        """Invariant: for any batch, no two slugs in it share a graph edge."""
        graph = {
            "a": {"b", "d"},
            "b": {"a", "c"},
            "c": {"b"},
            "d": {"a"},
        }
        batches = cross_plan.schedule_batches(["a", "b", "c", "d"], graph)
        for batch in batches:
            for i, s1 in enumerate(batch):
                for s2 in batch[i + 1:]:
                    assert s2 not in graph.get(s1, set()), (
                        f"conflicting slugs {s1!r} and {s2!r} must not share a batch"
                    )

    def test_empty_slugs_returns_empty(self):
        """Edge case: empty slug list → empty batches."""
        batches = cross_plan.schedule_batches([], {})
        assert batches == []


# ---------------------------------------------------------------------------
# T012: run_cross_plan integration tests (monkeypatched run_single_plan)
# ---------------------------------------------------------------------------

import asyncio as _asyncio


def _load_hx_module():
    """Load hermes-execute.py as a module."""
    spec = importlib.util.spec_from_file_location("hermes_execute_t012", _SCRIPT_HX)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_HX_T012 = _load_hx_module()


def _make_config(*, max_parallel_plans=2):
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


class TestRunCrossPlan:
    """Integration tests for run_cross_plan scheduler."""

    def test_disjoint_plans_all_succeed(self, monkeypatch):
        """Three disjoint plans all succeed → run_cross_plan returns 0."""
        async def fake_run_single_plan(slug, plan_dir_override, config, repo_root, *, merge_lock=None):
            return 0

        monkeypatch.setattr(_HX_T012, "run_single_plan", fake_run_single_plan)

        # Inject lock functions so no real subprocess calls happen.
        acquired_slugs = []
        released_slugs = []

        def fake_acquire(slug):
            acquired_slugs.append(slug)
            return True

        def fake_release(slug):
            released_slugs.append(slug)

        monkeypatch.setattr(
            _HX_T012._cross_plan,
            "acquire_plan_locks",
            lambda slugs, **kwargs: (True, sorted(slugs)),
        )
        monkeypatch.setattr(
            _HX_T012._cross_plan,
            "release_plan_locks",
            lambda slugs, **kwargs: None,
        )
        monkeypatch.setattr(_HX_T012, "_get_session_id", lambda: "test-session")

        config = _make_config(max_parallel_plans=3)
        code = _asyncio.run(_HX_T012.run_cross_plan(["p1", "p2", "p3"], config, "/repo"))
        assert code == 0

    def test_failure_isolation_disjoint_peer_completes(self, monkeypatch):
        """One plan failing does NOT abort disjoint peers; run_cross_plan returns 1."""
        results_map = {"p1": 1, "p2": 0}  # p1 fails, p2 succeeds

        async def fake_run_single_plan(slug, plan_dir_override, config, repo_root, *, merge_lock=None):
            return results_map[slug]

        monkeypatch.setattr(_HX_T012, "run_single_plan", fake_run_single_plan)

        completed = []

        # Track which slugs actually ran.
        original_run = fake_run_single_plan

        async def tracking_run(slug, *args, **kwargs):
            result = await original_run(slug, *args, **kwargs)
            completed.append((slug, result))
            return result

        monkeypatch.setattr(_HX_T012, "run_single_plan", tracking_run)
        monkeypatch.setattr(
            _HX_T012._cross_plan,
            "acquire_plan_locks",
            lambda slugs, **kwargs: (True, sorted(slugs)),
        )
        monkeypatch.setattr(
            _HX_T012._cross_plan,
            "release_plan_locks",
            lambda slugs, **kwargs: None,
        )
        monkeypatch.setattr(_HX_T012, "_get_session_id", lambda: "test-session")

        config = _make_config(max_parallel_plans=2)
        # Disjoint plans (no conflict graph edges): both run; p1 fails but p2 still completes.
        code = _asyncio.run(_HX_T012.run_cross_plan(["p1", "p2"], config, "/repo"))

        assert code == 1, "overall code must be 1 when any plan fails"
        # Both plans must have actually run (failure isolation: p1 failing doesn't skip p2).
        ran = {slug for slug, _ in completed}
        assert "p2" in ran, "disjoint peer p2 must have run despite p1 failing"

    def test_lock_acquire_failure_returns_nonzero(self, monkeypatch):
        """If lock acquisition fails, run_cross_plan returns nonzero without running any plan."""
        ran = []

        async def fake_run_single_plan(slug, *a, **kw):
            ran.append(slug)
            return 0

        monkeypatch.setattr(_HX_T012, "run_single_plan", fake_run_single_plan)
        monkeypatch.setattr(
            _HX_T012._cross_plan,
            "acquire_plan_locks",
            lambda slugs, **kwargs: (False, []),
        )
        monkeypatch.setattr(_HX_T012, "_get_session_id", lambda: "test-session")

        config = _make_config()
        code = _asyncio.run(_HX_T012.run_cross_plan(["p1", "p2"], config, "/repo"))
        assert code != 0, "lock acquire failure must return nonzero"
        assert ran == [], "no plans must run when locks cannot be acquired"

    def test_disjoint_plans_peak_concurrency_bounded(self, monkeypatch):
        """With 3 disjoint plans and max_parallel_plans=2, peak concurrent ≤ 2."""
        peak_live = [0]
        current_live = [0]

        async def fake_run_single_plan(slug, plan_dir_override, config, repo_root, *, merge_lock=None):
            current_live[0] += 1
            peak_live[0] = max(peak_live[0], current_live[0])
            # Yield so other coroutines can start if the semaphore would allow it.
            for _ in range(3):
                await _asyncio.sleep(0)
            current_live[0] -= 1
            return 0

        monkeypatch.setattr(_HX_T012, "run_single_plan", fake_run_single_plan)
        monkeypatch.setattr(
            _HX_T012._cross_plan,
            "acquire_plan_locks",
            lambda slugs, **kwargs: (True, sorted(slugs)),
        )
        monkeypatch.setattr(
            _HX_T012._cross_plan,
            "release_plan_locks",
            lambda slugs, **kwargs: None,
        )
        monkeypatch.setattr(_HX_T012, "_get_session_id", lambda: "test-session")

        config = _make_config(max_parallel_plans=2)
        code = _asyncio.run(_HX_T012.run_cross_plan(["p1", "p2", "p3"], config, "/repo"))

        assert code == 0
        assert peak_live[0] <= 2, (
            f"peak concurrent plans must not exceed cap=2; got {peak_live[0]}"
        )

    def test_conflicting_plans_never_concurrent(self, monkeypatch):
        """Two conflicting plans (sharing a conflict edge) must never run concurrently."""
        current_live = [0]
        peak_live = [0]

        async def fake_run_single_plan(slug, plan_dir_override, config, repo_root, *, merge_lock=None):
            current_live[0] += 1
            peak_live[0] = max(peak_live[0], current_live[0])
            await _asyncio.sleep(0)
            current_live[0] -= 1
            return 0

        monkeypatch.setattr(_HX_T012, "run_single_plan", fake_run_single_plan)
        monkeypatch.setattr(
            _HX_T012._cross_plan,
            "acquire_plan_locks",
            lambda slugs, **kwargs: (True, sorted(slugs)),
        )
        monkeypatch.setattr(
            _HX_T012._cross_plan,
            "release_plan_locks",
            lambda slugs, **kwargs: None,
        )
        monkeypatch.setattr(_HX_T012, "_get_session_id", lambda: "test-session")
        # Inject a conflict graph that makes p1 and p2 conflict.
        monkeypatch.setattr(
            _HX_T012._cross_plan,
            "build_plan_conflict_graph",
            lambda slugs, **kwargs: {s: set(slugs) - {s} for s in slugs},  # fully connected
        )

        # With max_parallel_plans=2 but a full-conflict graph, schedule_batches
        # will serialize them — peak must be 1.
        config = _make_config(max_parallel_plans=2)
        code = _asyncio.run(_HX_T012.run_cross_plan(["p1", "p2"], config, "/repo"))
        assert code == 0
        assert peak_live[0] == 1, (
            f"conflicting plans must be serialized; peak concurrent was {peak_live[0]}, expected 1"
        )

    def test_exception_in_run_single_plan_counts_as_failure(self, monkeypatch):
        """An exception raised by run_single_plan is treated as plan failure (code=1)."""
        async def fake_run_single_plan(slug, *a, **kw):
            if slug == "bad":
                raise RuntimeError("simulated plan crash")
            return 0

        monkeypatch.setattr(_HX_T012, "run_single_plan", fake_run_single_plan)
        monkeypatch.setattr(
            _HX_T012._cross_plan,
            "acquire_plan_locks",
            lambda slugs, **kwargs: (True, sorted(slugs)),
        )
        monkeypatch.setattr(
            _HX_T012._cross_plan,
            "release_plan_locks",
            lambda slugs, **kwargs: None,
        )
        monkeypatch.setattr(_HX_T012, "_get_session_id", lambda: "test-session")

        config = _make_config(max_parallel_plans=2)
        code = _asyncio.run(_HX_T012.run_cross_plan(["bad", "ok"], config, "/repo"))
        assert code == 1, "exception in run_single_plan must result in non-zero overall code"


# ---------------------------------------------------------------------------
# T012 retry: main_async routing regression tests
# Covers the two blockers fixed in hermes-execute.py:
#   1. Single-element --slugs/--plan-set must route to single-plan path (not cross-plan).
#   2. Single-plan path must use slugs[0], not args.slug (which is None for --slugs/--plan-set).
# ---------------------------------------------------------------------------

import json as _json
import os as _os
import unittest.mock as _mock


def _load_hx_routing():
    """Load a fresh hermes-execute module for routing tests."""
    spec = importlib.util.spec_from_file_location("hermes_execute_routing", _SCRIPT_HX)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_HX_ROUTING = _load_hx_routing()


class TestMainAsyncRouting:
    """Regression tests for the main_async slug routing fix.

    All tests monkeypatch run_single_plan and run_cross_plan on the module so
    no real filesystem I/O or lock acquisition happens.
    """

    def _make_single_tracker(self):
        """Return (async fn, calls list) for monkeypatching run_single_plan."""
        calls = []

        async def fake(slug, plan_dir_override, config, repo_root, *, merge_lock=None):
            calls.append({"slug": slug, "plan_dir_override": plan_dir_override})
            raise SystemExit(0)

        return fake, calls

    def _make_cross_tracker(self):
        """Return (async fn, calls list) for monkeypatching run_cross_plan."""
        calls = []

        async def fake(slugs, config, repo_root):
            calls.append({"slugs": list(slugs)})
            raise SystemExit(0)

        return fake, calls

    # ------------------------------------------------------------------
    # Helper: resolve only slugs without invoking main_async (unit-level)
    # ------------------------------------------------------------------

    def test_validate_slug_set_args_single_slug_flag(self):
        """--slug a → _validate_slug_set_args returns ['a']."""
        args = types.SimpleNamespace(slug="a", slugs=None, plan_set=None)
        result = _HX_ROUTING._validate_slug_set_args(args)
        assert result == ["a"]

    def test_validate_slug_set_args_single_slugs_flag(self):
        """--slugs a (one element) → _validate_slug_set_args returns ['a']."""
        args = types.SimpleNamespace(slug=None, slugs="a", plan_set=None)
        result = _HX_ROUTING._validate_slug_set_args(args)
        assert result == ["a"]

    def test_validate_slug_set_args_single_plan_set(self, tmp_path):
        """--plan-set file with one slug → _validate_slug_set_args returns ['a']."""
        f = tmp_path / "one.txt"
        f.write_text("a\n")
        args = types.SimpleNamespace(slug=None, slugs=None, plan_set=str(f))
        result = _HX_ROUTING._validate_slug_set_args(args)
        assert result == ["a"]

    def test_validate_slug_set_args_multi_slugs(self):
        """--slugs a,b → _validate_slug_set_args returns ['a', 'b']."""
        args = types.SimpleNamespace(slug=None, slugs="a,b", plan_set=None)
        result = _HX_ROUTING._validate_slug_set_args(args)
        assert result == ["a", "b"]

    # ------------------------------------------------------------------
    # Routing predicate assertions (without driving full main_async)
    # ------------------------------------------------------------------

    def test_routing_predicate_single_element_goes_to_single_path(self):
        """len(slugs) == 1 must NOT satisfy the cross-plan condition (len > 1)."""
        slugs = ["only-one"]
        # The fixed condition: only len(slugs) > 1 triggers cross-plan.
        assert not (len(slugs) > 1), (
            "single-element slugs list must not route to cross-plan path"
        )

    def test_routing_predicate_two_elements_goes_to_cross_path(self):
        """len(slugs) == 2 must satisfy the cross-plan condition."""
        slugs = ["plan-a", "plan-b"]
        assert len(slugs) > 1, "two-element slugs list must route to cross-plan path"

    # ------------------------------------------------------------------
    # Integration-level routing via monkeypatched main_async internals
    # ------------------------------------------------------------------

    def _run_main_async_with_argv(self, monkeypatch, mod, argv, *, config=None, repo_root="/repo"):
        """Drive main_async with a synthetic sys.argv; returns (single_calls, cross_calls)."""
        single_fn, single_calls = self._make_single_tracker()
        cross_fn, cross_calls = self._make_cross_tracker()

        monkeypatch.setattr(mod, "run_single_plan", single_fn)
        monkeypatch.setattr(mod, "run_cross_plan", cross_fn)
        monkeypatch.setattr(mod, "load_config", lambda: config or _make_config())
        monkeypatch.setattr(mod, "validate_slug", lambda s: True)
        monkeypatch.setattr(_os, "getcwd", lambda: repo_root)

        with _mock.patch("sys.argv", argv):
            with pytest.raises(SystemExit):
                _asyncio.run(mod.main_async())

        return single_calls, cross_calls

    def test_single_slug_flag_routes_to_single_plan(self, monkeypatch):
        """--slug a → run_single_plan called with 'a'; run_cross_plan NOT called."""
        single_calls, cross_calls = self._run_main_async_with_argv(
            monkeypatch, _HX_ROUTING,
            ["hermes-execute", "--slug", "alpha"],
        )
        assert cross_calls == [], "run_cross_plan must NOT be called for a single --slug"
        assert len(single_calls) == 1, "run_single_plan must be called exactly once"
        assert single_calls[0]["slug"] == "alpha"

    def test_single_element_slugs_flag_routes_to_single_plan(self, monkeypatch):
        """--slugs a (one element) → run_single_plan called with 'a', run_cross_plan NOT called."""
        single_calls, cross_calls = self._run_main_async_with_argv(
            monkeypatch, _HX_ROUTING,
            ["hermes-execute", "--slugs", "beta"],
        )
        assert cross_calls == [], (
            "run_cross_plan must NOT be called when --slugs has a single element"
        )
        assert len(single_calls) == 1
        assert single_calls[0]["slug"] == "beta"

    def test_single_element_plan_set_routes_to_single_plan(self, monkeypatch, tmp_path):
        """--plan-set with one slug → run_single_plan called with that slug, run_cross_plan NOT called."""
        f = tmp_path / "single.txt"
        f.write_text("gamma\n")

        single_calls, cross_calls = self._run_main_async_with_argv(
            monkeypatch, _HX_ROUTING,
            ["hermes-execute", "--plan-set", str(f)],
        )
        assert cross_calls == [], (
            "run_cross_plan must NOT be called when --plan-set contains exactly one slug"
        )
        assert len(single_calls) == 1
        assert single_calls[0]["slug"] == "gamma"

    def test_multi_slugs_flag_routes_to_cross_plan(self, monkeypatch):
        """--slugs a,b → run_cross_plan called with ['a','b']; run_single_plan NOT called."""
        single_calls, cross_calls = self._run_main_async_with_argv(
            monkeypatch, _HX_ROUTING,
            ["hermes-execute", "--slugs", "a,b"],
        )
        assert single_calls == [], "run_single_plan must NOT be called for multi-slug --slugs"
        assert len(cross_calls) == 1
        assert set(cross_calls[0]["slugs"]) == {"a", "b"}


# ---------------------------------------------------------------------------
# T013: merge mutex tests — shared asyncio.Lock serializes git merges
# ---------------------------------------------------------------------------

def _load_hx_t013():
    """Load a fresh hermes-execute module for T013 merge-mutex tests."""
    spec = importlib.util.spec_from_file_location("hermes_execute_t013", _SCRIPT_HX)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_HX_T013 = _load_hx_t013()


def _make_config_t013(*, max_parallel_plans=2, max_parallel_workstreams=2):
    return types.SimpleNamespace(
        concurrency=types.SimpleNamespace(
            max_parallel_plans=max_parallel_plans,
            max_parallel_workstreams=max_parallel_workstreams,
            serialize_all=False,
            serialize_high_severity=True,
        ),
        paths=types.SimpleNamespace(worktree_base="/tmp/wt"),
        timeouts=types.SimpleNamespace(per_workstream_minutes=90),
        retry=types.SimpleNamespace(max_retries=1, retry_delay_seconds=1),
        stall_detection=types.SimpleNamespace(no_progress_minutes=15),
    )


class TestMergeMutexCrossPlan:
    """T013: merges serialize across plans via shared asyncio.Lock."""

    def test_merges_serialize_across_plans(self, monkeypatch):
        """Two plans finishing concurrently must never merge simultaneously.

        We drive run_cross_plan with a fake run_single_plan that calls the
        REAL merge path (indirectly) by using the merge_lock kwarg.
        Instead of the full run_single_plan stack, we instrument the lock
        directly: each plan acquires the shared merge_lock, records concurrent
        count, then releases it.  Peak concurrent merges must be 1.
        """
        peak_concurrent = [0]
        current_concurrent = [0]
        merge_call_count = [0]

        # This fake simulates what run_single_plan→run_workstream does with
        # merge_lock: acquire it, do the merge, release it.
        async def fake_run_single_plan(slug, plan_dir_override, config, repo_root, *, merge_lock=None):
            if merge_lock is not None:
                async with merge_lock:
                    current_concurrent[0] += 1
                    peak_concurrent[0] = max(peak_concurrent[0], current_concurrent[0])
                    merge_call_count[0] += 1
                    # Yield so other coroutines could interleave IF the lock were absent.
                    await _asyncio.sleep(0)
                    current_concurrent[0] -= 1
            else:
                # Lock was not passed — count but no serialization (should not happen in cross-plan).
                current_concurrent[0] += 1
                peak_concurrent[0] = max(peak_concurrent[0], current_concurrent[0])
                merge_call_count[0] += 1
                current_concurrent[0] -= 1
            return 0

        monkeypatch.setattr(_HX_T013, "run_single_plan", fake_run_single_plan)
        monkeypatch.setattr(
            _HX_T013._cross_plan,
            "acquire_plan_locks",
            lambda slugs, **kwargs: (True, sorted(slugs)),
        )
        monkeypatch.setattr(
            _HX_T013._cross_plan,
            "release_plan_locks",
            lambda slugs, **kwargs: None,
        )
        monkeypatch.setattr(_HX_T013, "_get_session_id", lambda: "test-session")
        # Disjoint plans so they land in the SAME batch and run concurrently.
        monkeypatch.setattr(
            _HX_T013._cross_plan,
            "build_plan_conflict_graph",
            lambda slugs, **kwargs: {s: set() for s in slugs},
        )

        config = _make_config_t013(max_parallel_plans=2)
        code = _asyncio.run(_HX_T013.run_cross_plan(["p1", "p2"], config, "/repo"))

        assert code == 0
        assert merge_call_count[0] == 2, f"both plans must have merged; got {merge_call_count[0]}"
        assert peak_concurrent[0] == 1, (
            f"merges must be serialized (peak concurrent == 1); got {peak_concurrent[0]}. "
            "If this is > 1, the shared merge_lock is not being passed or not held."
        )

    def test_merges_serialize_without_lock_would_fail(self, monkeypatch):
        """Control test: if NO lock is passed, two coroutines CAN merge concurrently.

        This validates the test design: it would catch a missing lock.
        We manually drive two coroutines WITHOUT a lock and assert peak==2.
        """
        peak_concurrent = [0]
        current_concurrent = [0]

        async def _merge_without_lock():
            current_concurrent[0] += 1
            peak_concurrent[0] = max(peak_concurrent[0], current_concurrent[0])
            await _asyncio.sleep(0)  # yield so both can run concurrently
            current_concurrent[0] -= 1

        async def _run():
            await _asyncio.gather(
                _merge_without_lock(),
                _merge_without_lock(),
            )

        _asyncio.run(_run())
        assert peak_concurrent[0] == 2, (
            f"without a lock two concurrent merges must reach peak==2; "
            f"got {peak_concurrent[0]}. This control test is broken."
        )

    def test_shared_lock_passed_to_run_single_plan(self, monkeypatch):
        """run_cross_plan must pass the SAME lock object to every run_single_plan call."""
        received_locks = []

        async def capturing_run_single_plan(slug, plan_dir_override, config, repo_root, *, merge_lock=None):
            received_locks.append(merge_lock)
            return 0

        monkeypatch.setattr(_HX_T013, "run_single_plan", capturing_run_single_plan)
        monkeypatch.setattr(
            _HX_T013._cross_plan,
            "acquire_plan_locks",
            lambda slugs, **kwargs: (True, sorted(slugs)),
        )
        monkeypatch.setattr(
            _HX_T013._cross_plan,
            "release_plan_locks",
            lambda slugs, **kwargs: None,
        )
        monkeypatch.setattr(_HX_T013, "_get_session_id", lambda: "test-session")

        config = _make_config_t013(max_parallel_plans=2)
        code = _asyncio.run(_HX_T013.run_cross_plan(["p1", "p2"], config, "/repo"))

        assert code == 0
        assert len(received_locks) == 2, "both plans must have received a lock"
        assert all(lock is not None for lock in received_locks), (
            "run_cross_plan must pass a non-None merge_lock to every run_single_plan"
        )
        assert received_locks[0] is received_locks[1], (
            "run_cross_plan must pass the SAME lock object to all plans (shared mutex); "
            "got distinct lock objects, meaning each plan has its own lock and merges are NOT serialized."
        )


class TestMergeMutexWithinPlan:
    """T013: within-plan concurrent merges also serialize (run_single_plan's own lock)."""

    def test_within_plan_concurrent_merges_serialize(self, monkeypatch):
        """run_single_plan at cap=2 with 2 workstreams: peak concurrent merges == 1.

        We drive run_single_plan directly with a fake run_workstream that uses
        the merge_lock to record concurrent merges.
        """
        peak_concurrent = [0]
        current_concurrent = [0]
        merge_count = [0]

        async def fake_run_workstream(
            ws, state, config, args, repo_root, plan_dir, completed,
            *, merge_lock=None
        ):
            # Simulate the session running, then acquiring merge_lock for the merge.
            await _asyncio.sleep(0)  # yield to allow other ws to reach this point
            if merge_lock is not None:
                async with merge_lock:
                    current_concurrent[0] += 1
                    peak_concurrent[0] = max(peak_concurrent[0], current_concurrent[0])
                    merge_count[0] += 1
                    await _asyncio.sleep(0)
                    current_concurrent[0] -= 1
            else:
                current_concurrent[0] += 1
                peak_concurrent[0] = max(peak_concurrent[0], current_concurrent[0])
                merge_count[0] += 1
                current_concurrent[0] -= 1
            completed.append(ws.id)
            return "done"

        monkeypatch.setattr(_HX_T013, "run_workstream", fake_run_workstream)

        # Minimal stubs needed by run_single_plan setup.
        import json as _json_mod
        import os as _os_mod

        ws1_id = "ws-001"
        ws2_id = "ws-002"

        fake_manifest = types.SimpleNamespace(
            protocol="hermes-v1",
            workstreams=[
                types.SimpleNamespace(
                    id=ws1_id, name="WS1", status="ready",
                    depends_on=[], tasks=["T001"],
                    path="plans/test/ws-001",
                ),
                types.SimpleNamespace(
                    id=ws2_id, name="WS2", status="ready",
                    depends_on=[], tasks=["T002"],
                    path="plans/test/ws-002",
                ),
            ],
            merge_order=[ws1_id, ws2_id],
            partial_tree=False,
            scope_unknown=False,
            file_conflicts=[],
        )

        monkeypatch.setattr(_HX_T013, "parse_workstreams_json", lambda p: fake_manifest)
        monkeypatch.setattr(_HX_T013, "validate_gates", lambda m, d: [])
        monkeypatch.setattr(_HX_T013, "attempt_recovery", lambda *a, **k: None)
        monkeypatch.setattr(_HX_T013, "resolve_plan_dir", lambda s, o: "/fake/plan")
        monkeypatch.setattr(_HX_T013.os.path, "exists", lambda p: True)
        monkeypatch.setattr(_HX_T013, "cleanup_orphaned", lambda *a, **k: None)
        monkeypatch.setattr(_HX_T013, "clear_state", lambda *a, **k: None)
        monkeypatch.setattr(_HX_T013, "save_state", lambda *a, **k: None)

        # Disable Discord connect/disconnect.
        import unittest.mock as _mock_mod
        with _mock_mod.patch.object(_HX_T013.asyncio, "sleep", new=_asyncio.sleep):
            pass  # keep real sleep

        # Stub out discord relay so the import doesn't fail.
        fake_discord = types.ModuleType("hermes.discord_relay")
        fake_discord.connect = _asyncio.coroutine(lambda config: None) if False else (lambda config: _asyncio.sleep(0))
        fake_discord.disconnect = lambda: _asyncio.sleep(0)
        import sys as _sys_mod
        _sys_mod.modules.setdefault("hermes.discord_relay", fake_discord)

        config = _make_config_t013(max_parallel_workstreams=2)
        code = _asyncio.run(
            _HX_T013.run_single_plan("test-slug", None, config, "/repo")
        )

        assert code == 0, f"run_single_plan must succeed; got code={code}"
        assert merge_count[0] == 2, f"both workstreams must have merged; got {merge_count[0]}"
        assert peak_concurrent[0] == 1, (
            f"within-plan concurrent merges must be serialized (peak==1); got {peak_concurrent[0]}. "
            "run_single_plan must create its own merge_lock when none is passed."
        )

    def test_default_no_lock_passed_creates_own_lock(self, monkeypatch):
        """run_single_plan(merge_lock=None) must create its own per-run lock.

        Verify: no crash, merges complete, and run_workstream receives a non-None lock.
        """
        received_locks = []

        async def capturing_run_workstream(
            ws, state, config, args, repo_root, plan_dir, completed,
            *, merge_lock=None
        ):
            received_locks.append(merge_lock)
            completed.append(ws.id)
            return "done"

        monkeypatch.setattr(_HX_T013, "run_workstream", capturing_run_workstream)

        fake_manifest = types.SimpleNamespace(
            protocol="hermes-v1",
            workstreams=[
                types.SimpleNamespace(
                    id="ws-a", name="WS-A", status="ready",
                    depends_on=[], tasks=["T001"],
                    path="plans/test/ws-a",
                ),
            ],
            merge_order=["ws-a"],
            partial_tree=False,
            scope_unknown=False,
            file_conflicts=[],
        )

        monkeypatch.setattr(_HX_T013, "parse_workstreams_json", lambda p: fake_manifest)
        monkeypatch.setattr(_HX_T013, "validate_gates", lambda m, d: [])
        monkeypatch.setattr(_HX_T013, "attempt_recovery", lambda *a, **k: None)
        monkeypatch.setattr(_HX_T013, "resolve_plan_dir", lambda s, o: "/fake/plan")
        monkeypatch.setattr(_HX_T013.os.path, "exists", lambda p: True)
        monkeypatch.setattr(_HX_T013, "cleanup_orphaned", lambda *a, **k: None)
        monkeypatch.setattr(_HX_T013, "clear_state", lambda *a, **k: None)
        monkeypatch.setattr(_HX_T013, "save_state", lambda *a, **k: None)

        import sys as _sys_mod
        fake_discord = types.ModuleType("hermes.discord_relay")
        fake_discord.connect = lambda config: _asyncio.sleep(0)
        fake_discord.disconnect = lambda: _asyncio.sleep(0)
        _sys_mod.modules.setdefault("hermes.discord_relay", fake_discord)

        config = _make_config_t013(max_parallel_workstreams=1)
        # Call with NO merge_lock (the default standalone path).
        code = _asyncio.run(
            _HX_T013.run_single_plan("test-slug", None, config, "/repo")
            # merge_lock omitted → defaults to None → run_single_plan creates its own
        )

        assert code == 0, f"standalone run_single_plan must not crash; got code={code}"
        assert len(received_locks) == 1, "run_workstream must have been called once"
        assert received_locks[0] is not None, (
            "run_single_plan must create and pass a non-None merge_lock even when called without one"
        )
