"""
tests/test_generate_workstreams.py — Characterization tests for
scripts/generate-workstreams.py.

Covers:
  py_compile_smoke     — module compiles without errors
  linear_chain         — T001→T002→T003→T004 collapses to 1 workstream
  fan_out              — T001→{T002,T003,T004,T005} produces 2 workstreams
  two_independent_chains — T001→T002, T003→T004 produces 2 workstreams
  deep_fork            — T001 forks to T002→T003 and T004→T005,
                         T006 depends on T003+T005 → 4 workstreams

These tests are the safety net for all later changes to the 5-rule algorithm.
They pin the current depends_on and merge_order output per the worked examples
in docs/human/hermes-integration-v1.md lines ~161-184.
"""

from __future__ import annotations

import importlib.util
import py_compile
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SCRIPT = str(_REPO_ROOT / "scripts" / "generate-workstreams.py")


# ---------------------------------------------------------------------------
# Load module (hyphenated filename — cannot use normal import)
# ---------------------------------------------------------------------------

def _load_module():
    spec = importlib.util.spec_from_file_location("generate_workstreams", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_mod = _load_module()


# ---------------------------------------------------------------------------
# Smoke test: module must compile
# ---------------------------------------------------------------------------

class TestCompileSmoke:
    def test_py_compile_passes(self) -> None:
        """scripts/generate-workstreams.py must be free of syntax/indent errors."""
        # py_compile.compile raises py_compile.PyCompileError on failure.
        py_compile.compile(_SCRIPT, doraise=True)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ws_tasks(ws_objects: list[dict], ws_id: str) -> list[str]:
    for w in ws_objects:
        if w["id"] == ws_id:
            return w["tasks"]
    raise KeyError(f"workstream {ws_id!r} not found in result")


def _ws_depends_on(ws_objects: list[dict], ws_id: str) -> list[str]:
    for w in ws_objects:
        if w["id"] == ws_id:
            return w["depends_on"]
    raise KeyError(f"workstream {ws_id!r} not found in result")


# ---------------------------------------------------------------------------
# Characterization tests: four worked examples
# ---------------------------------------------------------------------------

class TestLinearChain:
    """T001→T002→T003→T004 must collapse to a single workstream."""

    def setup_method(self):
        task_ids = ["T001", "T002", "T003", "T004"]
        deps = {
            "T001": [],
            "T002": ["T001"],
            "T003": ["T002"],
            "T004": ["T003"],
        }
        self.ws, self.merge_order = _mod.run_5rule_algorithm(task_ids, deps)

    def test_single_workstream_produced(self) -> None:
        assert len(self.ws) == 1, (
            f"Expected 1 workstream for linear chain, got {len(self.ws)}: "
            f"{[w['id'] for w in self.ws]}"
        )

    def test_all_tasks_in_ws1(self) -> None:
        tasks = _ws_tasks(self.ws, "ws-1")
        assert set(tasks) == {"T001", "T002", "T003", "T004"}

    def test_ws1_tasks_sorted(self) -> None:
        tasks = _ws_tasks(self.ws, "ws-1")
        assert tasks == ["T001", "T002", "T003", "T004"]

    def test_ws1_has_no_depends_on(self) -> None:
        assert _ws_depends_on(self.ws, "ws-1") == []

    def test_merge_order_is_ws1_only(self) -> None:
        assert self.merge_order == ["ws-1"]


class TestFanOut:
    """T001→{T002,T003,T004,T005}: depth-0 is {T001}, depth-1 is the four tasks.

    Step 4 does not collapse because depth-1 has 4 tasks (not 1).
    Result: ws-1 {T001}, ws-2 {T002,T003,T004,T005}.
    """

    def setup_method(self):
        task_ids = ["T001", "T002", "T003", "T004", "T005"]
        deps = {
            "T001": [],
            "T002": ["T001"],
            "T003": ["T001"],
            "T004": ["T001"],
            "T005": ["T001"],
        }
        self.ws, self.merge_order = _mod.run_5rule_algorithm(task_ids, deps)

    def test_two_workstreams_produced(self) -> None:
        assert len(self.ws) == 2, (
            f"Expected 2 workstreams for fan-out, got {len(self.ws)}: "
            f"{[w['id'] for w in self.ws]}"
        )

    def test_ws1_contains_only_root(self) -> None:
        assert _ws_tasks(self.ws, "ws-1") == ["T001"]

    def test_ws2_contains_all_leaves(self) -> None:
        tasks = _ws_tasks(self.ws, "ws-2")
        assert set(tasks) == {"T002", "T003", "T004", "T005"}

    def test_ws2_tasks_sorted(self) -> None:
        tasks = _ws_tasks(self.ws, "ws-2")
        assert tasks == ["T002", "T003", "T004", "T005"]

    def test_ws1_has_no_depends_on(self) -> None:
        assert _ws_depends_on(self.ws, "ws-1") == []

    def test_ws2_depends_on_ws1(self) -> None:
        assert _ws_depends_on(self.ws, "ws-2") == ["ws-1"]

    def test_merge_order(self) -> None:
        assert self.merge_order == ["ws-1", "ws-2"]


class TestTwoIndependentChains:
    """T001→T002, T003→T004: two chains with no shared root.

    depth-0 = {T001, T003}, depth-1 = {T002, T004}.
    Step 5: T002 and T004 both have parents in ws-1, so they stay together.
    Result: ws-1 {T001,T003}, ws-2 {T002,T004}.
    """

    def setup_method(self):
        task_ids = ["T001", "T002", "T003", "T004"]
        deps = {
            "T001": [],
            "T002": ["T001"],
            "T003": [],
            "T004": ["T003"],
        }
        self.ws, self.merge_order = _mod.run_5rule_algorithm(task_ids, deps)

    def test_two_workstreams_produced(self) -> None:
        assert len(self.ws) == 2, (
            f"Expected 2 workstreams for two independent chains, got {len(self.ws)}: "
            f"{[w['id'] for w in self.ws]}"
        )

    def test_ws1_contains_roots(self) -> None:
        tasks = _ws_tasks(self.ws, "ws-1")
        assert set(tasks) == {"T001", "T003"}

    def test_ws1_tasks_sorted(self) -> None:
        tasks = _ws_tasks(self.ws, "ws-1")
        assert tasks == ["T001", "T003"]

    def test_ws2_contains_leaves(self) -> None:
        tasks = _ws_tasks(self.ws, "ws-2")
        assert set(tasks) == {"T002", "T004"}

    def test_ws2_tasks_sorted(self) -> None:
        tasks = _ws_tasks(self.ws, "ws-2")
        assert tasks == ["T002", "T004"]

    def test_ws1_has_no_depends_on(self) -> None:
        assert _ws_depends_on(self.ws, "ws-1") == []

    def test_ws2_depends_on_ws1(self) -> None:
        assert _ws_depends_on(self.ws, "ws-2") == ["ws-1"]

    def test_merge_order(self) -> None:
        assert self.merge_order == ["ws-1", "ws-2"]


class TestDeepFork:
    """T001 forks to T002→T003 and T004→T005; T006 depends on T003+T005.

    depth-0 = {T001}, depth-1 = {T002, T004}, depth-2 = {T003, T005},
    depth-3 = {T006}.
    Step 5: at depth-1 both share parent ws-1 → same workstream.
            at depth-2 both share parent ws-2 → same workstream.
            T006 has 2 parents (both ws-3) → single ws-4.
    Result: ws-1 {T001}, ws-2 {T002,T004}, ws-3 {T003,T005}, ws-4 {T006}
            with ws-4 depends_on ["ws-3"].
    """

    def setup_method(self):
        task_ids = ["T001", "T002", "T003", "T004", "T005", "T006"]
        deps = {
            "T001": [],
            "T002": ["T001"],
            "T003": ["T002"],
            "T004": ["T001"],
            "T005": ["T004"],
            "T006": ["T003", "T005"],
        }
        self.ws, self.merge_order = _mod.run_5rule_algorithm(task_ids, deps)

    def test_four_workstreams_produced(self) -> None:
        assert len(self.ws) == 4, (
            f"Expected 4 workstreams for deep fork, got {len(self.ws)}: "
            f"{[w['id'] for w in self.ws]}"
        )

    def test_ws1_is_root(self) -> None:
        assert _ws_tasks(self.ws, "ws-1") == ["T001"]

    def test_ws2_is_first_fork(self) -> None:
        tasks = _ws_tasks(self.ws, "ws-2")
        assert set(tasks) == {"T002", "T004"}
        assert tasks == ["T002", "T004"]

    def test_ws3_is_second_fork(self) -> None:
        tasks = _ws_tasks(self.ws, "ws-3")
        assert set(tasks) == {"T003", "T005"}
        assert tasks == ["T003", "T005"]

    def test_ws4_is_join(self) -> None:
        assert _ws_tasks(self.ws, "ws-4") == ["T006"]

    def test_ws1_has_no_depends_on(self) -> None:
        assert _ws_depends_on(self.ws, "ws-1") == []

    def test_ws2_depends_on_ws1(self) -> None:
        assert _ws_depends_on(self.ws, "ws-2") == ["ws-1"]

    def test_ws3_depends_on_ws2(self) -> None:
        assert _ws_depends_on(self.ws, "ws-3") == ["ws-2"]

    def test_ws4_depends_on_ws3(self) -> None:
        assert _ws_depends_on(self.ws, "ws-4") == ["ws-3"]

    def test_merge_order(self) -> None:
        assert self.merge_order == ["ws-1", "ws-2", "ws-3", "ws-4"]


# ---------------------------------------------------------------------------
# Tests: parse_task_files and workstream_scope (T002 acceptance)
# ---------------------------------------------------------------------------

class TestParseTaskFiles:
    """Unit tests for parse_task_files()."""

    def test_basic_files_line(self) -> None:
        """Tasks with **Files:** lines yield correct path tokens."""
        md = """\
## T001 — Some task
**Files:** `scripts/foo.py`, `scripts/bar.py`
**Depends on:** —

## T002 — Another task
**Files:** `tests/test_foo.py`
"""
        result = _mod.parse_task_files(md)
        assert result["T001"] == ["scripts/foo.py", "scripts/bar.py"]
        assert result["T002"] == ["tests/test_foo.py"]

    def test_suffix_and_backtick_stripping(self) -> None:
        """Annotation suffixes (new), (NEW), (MODIFY) and backticks are stripped."""
        md = """\
## T001 — Add scripts
**Files:** `scripts/foo.py` (new), `scripts/bar.py`
"""
        result = _mod.parse_task_files(md)
        assert result["T001"] == ["scripts/foo.py", "scripts/bar.py"]

    def test_multiple_annotation_variants(self) -> None:
        """(NEW), (MODIFY), (deleted), (renamed from ...) are all stripped."""
        md = """\
## T001 — Misc
**Files:** `scripts/a.py` (NEW), `scripts/b.py` (MODIFY), `scripts/c.py` (deleted), `scripts/d.py` (renamed from scripts/e.py)
"""
        result = _mod.parse_task_files(md)
        assert result["T001"] == [
            "scripts/a.py",
            "scripts/b.py",
            "scripts/c.py",
            "scripts/d.py",
        ]

    def test_missing_files_line_yields_empty_list(self) -> None:
        """A task block with no **Files:** line maps to an empty list; no exception."""
        md = """\
## T001 — Task without files line
**Depends on:** —
Some description.

## T002 — Task with files
**Files:** `scripts/foo.py`
"""
        result = _mod.parse_task_files(md)
        assert result["T001"] == []
        assert result["T002"] == ["scripts/foo.py"]

    def test_no_exception_on_empty_files_value(self) -> None:
        """A **Files:** line with an empty value maps to an empty list; no exception."""
        md = """\
## T001 — Empty files
**Files:**
"""
        result = _mod.parse_task_files(md)
        assert result["T001"] == []

    def test_empty_tasks_md(self) -> None:
        """Empty TASKS.md text returns an empty dict; no exception."""
        result = _mod.parse_task_files("")
        assert result == {}

    def test_no_tasks_md_tasks(self) -> None:
        """TASKS.md with no task headings returns an empty dict."""
        md = "# Just a header\nSome content.\n"
        result = _mod.parse_task_files(md)
        assert result == {}


class TestWorkstreamScope:
    """Unit tests for workstream_scope()."""

    def _make_ws(self, ws_id: str, tasks: list) -> dict:
        return {"id": ws_id, "tasks": tasks, "depends_on": [], "name": tasks[0] if tasks else ws_id}

    def test_single_workstream_single_task(self) -> None:
        """A single workstream with one task yields that task's paths."""
        ws_objects = [self._make_ws("ws-1", ["T001"])]
        task_files = {"T001": ["scripts/foo.py", "scripts/bar.py"]}
        result = _mod.workstream_scope(ws_objects, task_files)
        assert result["ws-1"] == {"scripts/foo.py", "scripts/bar.py"}

    def test_two_tasks_in_same_workstream_union(self) -> None:
        """Two tasks in the same workstream have their paths unioned."""
        ws_objects = [self._make_ws("ws-1", ["T001", "T002"])]
        task_files = {
            "T001": ["scripts/foo.py"],
            "T002": ["scripts/bar.py", "scripts/foo.py"],
        }
        result = _mod.workstream_scope(ws_objects, task_files)
        assert result["ws-1"] == {"scripts/foo.py", "scripts/bar.py"}

    def test_two_workstreams_separate_paths(self) -> None:
        """Two workstreams with different tasks get separate path sets."""
        ws_objects = [
            self._make_ws("ws-1", ["T001"]),
            self._make_ws("ws-2", ["T002"]),
        ]
        task_files = {
            "T001": ["scripts/a.py"],
            "T002": ["scripts/b.py"],
        }
        result = _mod.workstream_scope(ws_objects, task_files)
        assert result["ws-1"] == {"scripts/a.py"}
        assert result["ws-2"] == {"scripts/b.py"}

    def test_task_with_no_files_contributes_empty_set(self) -> None:
        """A task mapped to an empty list contributes no paths; no exception."""
        ws_objects = [self._make_ws("ws-1", ["T001", "T002"])]
        task_files = {
            "T001": ["scripts/a.py"],
            "T002": [],  # no files
        }
        result = _mod.workstream_scope(ws_objects, task_files)
        assert result["ws-1"] == {"scripts/a.py"}

    def test_task_missing_from_task_files_silently_skipped(self) -> None:
        """A task not present in task_files is silently skipped (contributes empty set)."""
        ws_objects = [self._make_ws("ws-1", ["T001", "T999"])]
        task_files = {"T001": ["scripts/a.py"]}
        result = _mod.workstream_scope(ws_objects, task_files)
        assert result["ws-1"] == {"scripts/a.py"}

    def test_workstream_with_no_tasks_yields_empty_set(self) -> None:
        """A workstream with an empty task list yields an empty path set."""
        ws_objects = [self._make_ws("ws-1", [])]
        task_files = {}
        result = _mod.workstream_scope(ws_objects, task_files)
        assert result["ws-1"] == set()

    def test_full_integration_with_run_5rule_algorithm(self) -> None:
        """parse_task_files + workstream_scope compose correctly with 5-rule output.

        Plan: T001→T002→T003 (linear chain → 1 workstream).
        T001 and T002 share scripts/shared.py; T003 has tests/test_shared.py.
        Expected: ws-1 scope = {scripts/shared.py, tests/test_shared.py}.
        """
        task_ids = ["T001", "T002", "T003"]
        deps = {"T001": [], "T002": ["T001"], "T003": ["T002"]}
        ws_objects, _ = _mod.run_5rule_algorithm(task_ids, deps)

        tasks_md = """\
## T001 — First
**Files:** `scripts/shared.py`

## T002 — Second
**Files:** `scripts/shared.py`, `scripts/helper.py`

## T003 — Third
**Files:** `tests/test_shared.py`
"""
        task_files = _mod.parse_task_files(tasks_md)
        scope = _mod.workstream_scope(ws_objects, task_files)

        assert scope["ws-1"] == {
            "scripts/shared.py",
            "scripts/helper.py",
            "tests/test_shared.py",
        }


# ---------------------------------------------------------------------------
# Tests: file_conflicts derivation + scope_unknown flag (T003 acceptance)
# ---------------------------------------------------------------------------

def _make_build_from_flat_plan(tmp_path, tasks_md_text):
    """Write a TASKS.md into tmp_path and return the path as str."""
    tasks_path = tmp_path / "TASKS.md"
    tasks_path.write_text(tasks_md_text)
    return str(tmp_path)


class TestFileConflictsDerivation:
    """build_from_flat derives file_conflicts when all tasks have Files lines."""

    def test_overlapping_paths_produces_conflict_entry(self, tmp_path) -> None:
        """Two workstreams that share a path emit a file_conflicts entry."""
        tasks_md = """\
## T001 — Root task
**Files:** `scripts/shared.py`, `scripts/a.py`
**Depends on:** —

## T002 — Leaf task
**Files:** `scripts/shared.py`, `scripts/b.py`
**Depends on:** T001
"""
        # T001 and T002 form a linear chain → 1 workstream → no cross-ws overlap
        # Use a fan-out so they land in separate workstreams.
        tasks_md_fanout = """\
## T001 — Root task
**Files:** `scripts/shared.py`
**Depends on:** —

## T002 — Branch A
**Files:** `scripts/shared.py`, `scripts/a.py`
**Depends on:** T001

## T003 — Branch B
**Files:** `scripts/shared.py`, `scripts/b.py`
**Depends on:** T001
"""
        plan_dir = _make_build_from_flat_plan(tmp_path, tasks_md_fanout)
        workstreams, file_conflicts, merge_order, partial_tree, scope_unknown = (
            _mod.build_from_flat(plan_dir, "test-plan")
        )

        assert scope_unknown is False, "All tasks have Files lines — scope_unknown must be False"

        conflict_files = {fc["file"] for fc in file_conflicts}
        assert "scripts/shared.py" in conflict_files, (
            f"Expected scripts/shared.py in file_conflicts, got: {conflict_files}"
        )

        # The conflict entry for shared.py must reference ≥2 workstreams
        shared_conflict = next(fc for fc in file_conflicts if fc["file"] == "scripts/shared.py")
        assert len(shared_conflict["workstreams"]) >= 2
        # workstreams list must be sorted
        assert shared_conflict["workstreams"] == sorted(shared_conflict["workstreams"])
        # severity must be a known value
        assert shared_conflict["severity"] in ("high", "medium", "low")

    def test_overlapping_conflict_severity_from_derive_severity(self, tmp_path) -> None:
        """derive_severity is called; a .yaml path must be 'high' severity."""
        tasks_md = """\
## T001 — Root
**Files:** `config.yaml`
**Depends on:** —

## T002 — Branch A
**Files:** `config.yaml`, `scripts/a.py`
**Depends on:** T001

## T003 — Branch B
**Files:** `config.yaml`, `scripts/b.py`
**Depends on:** T001
"""
        plan_dir = _make_build_from_flat_plan(tmp_path, tasks_md)
        _, file_conflicts, _, _, scope_unknown = _mod.build_from_flat(plan_dir, "test-plan")

        assert scope_unknown is False
        yaml_conflict = next(
            (fc for fc in file_conflicts if fc["file"] == "config.yaml"), None
        )
        assert yaml_conflict is not None, "Expected a conflict entry for config.yaml"
        assert yaml_conflict["severity"] == "high", (
            f"Expected 'high' severity for .yaml file, got '{yaml_conflict['severity']}'"
        )

    def test_no_overlaps_yields_empty_file_conflicts(self, tmp_path) -> None:
        """Fully-attributed plan with no cross-workstream overlaps → file_conflicts: [] + scope_unknown: false."""
        tasks_md = """\
## T001 — Root
**Files:** `scripts/root.py`
**Depends on:** —

## T002 — Branch A
**Files:** `scripts/a.py`
**Depends on:** T001

## T003 — Branch B
**Files:** `scripts/b.py`
**Depends on:** T001
"""
        plan_dir = _make_build_from_flat_plan(tmp_path, tasks_md)
        _, file_conflicts, _, _, scope_unknown = _mod.build_from_flat(plan_dir, "test-plan")

        assert scope_unknown is False
        assert file_conflicts == [], f"Expected empty file_conflicts, got: {file_conflicts}"

    def test_conflict_output_is_deterministic(self, tmp_path) -> None:
        """Multiple calls with identical input produce byte-identical file_conflicts."""
        tasks_md = """\
## T001 — Root
**Files:** `scripts/shared.py`
**Depends on:** —

## T002 — Branch A
**Files:** `scripts/shared.py`, `scripts/a.py`
**Depends on:** T001

## T003 — Branch B
**Files:** `scripts/shared.py`, `scripts/b.py`
**Depends on:** T001
"""
        plan_dir = _make_build_from_flat_plan(tmp_path, tasks_md)
        _, fc1, _, _, _ = _mod.build_from_flat(plan_dir, "test-plan")
        _, fc2, _, _, _ = _mod.build_from_flat(plan_dir, "test-plan")
        assert fc1 == fc2


class TestScopeUnknownFlag:
    """build_from_flat sets scope_unknown=True when any task lacks a **Files:** line."""

    def test_missing_files_line_triggers_scope_unknown(self, tmp_path) -> None:
        """A plan where one task has no **Files:** line → file_conflicts: [] + scope_unknown: True."""
        tasks_md = """\
## T001 — Root task with no Files line
**Depends on:** —

## T002 — Task with Files line
**Files:** `scripts/a.py`
**Depends on:** T001
"""
        plan_dir = _make_build_from_flat_plan(tmp_path, tasks_md)
        _, file_conflicts, _, _, scope_unknown = _mod.build_from_flat(plan_dir, "test-plan")

        assert scope_unknown is True, (
            "Expected scope_unknown=True when a task block has no **Files:** line"
        )
        assert file_conflicts == [], (
            "Expected file_conflicts=[] (fail-safe) when scope_unknown=True"
        )

    def test_all_tasks_missing_files_line_triggers_scope_unknown(self, tmp_path) -> None:
        """All tasks missing **Files:** lines → scope_unknown: True."""
        tasks_md = """\
## T001 — No files
**Depends on:** —

## T002 — Also no files
**Depends on:** T001
"""
        plan_dir = _make_build_from_flat_plan(tmp_path, tasks_md)
        _, file_conflicts, _, _, scope_unknown = _mod.build_from_flat(plan_dir, "test-plan")

        assert scope_unknown is True
        assert file_conflicts == []

    def test_fully_attributed_plan_has_scope_unknown_false(self, tmp_path) -> None:
        """Every task has a **Files:** line → scope_unknown: False."""
        tasks_md = """\
## T001 — Has files
**Files:** `scripts/a.py`
**Depends on:** —

## T002 — Also has files
**Files:** `scripts/b.py`
**Depends on:** T001
"""
        plan_dir = _make_build_from_flat_plan(tmp_path, tasks_md)
        _, _, _, _, scope_unknown = _mod.build_from_flat(plan_dir, "test-plan")

        assert scope_unknown is False

    def test_glob_token_counts_as_has_files(self, tmp_path) -> None:
        """A task with a glob/broad token (e.g. scripts/*.py) still counts as scope known."""
        tasks_md = """\
## T001 — Glob files
**Files:** `scripts/*.py`
**Depends on:** —
"""
        plan_dir = _make_build_from_flat_plan(tmp_path, tasks_md)
        _, _, _, _, scope_unknown = _mod.build_from_flat(plan_dir, "test-plan")

        assert scope_unknown is False, (
            "A task with a glob token must count as 'has files' (scope known)"
        )


# ---------------------------------------------------------------------------
# Tests: schema.py scope_unknown round-trip (T003 acceptance)
# ---------------------------------------------------------------------------

import importlib.util as _ilu
import json
import tempfile

_SCHEMA_PATH = str(_REPO_ROOT / "scripts" / "hermes" / "schema.py")


def _load_schema_module():
    spec = _ilu.spec_from_file_location("hermes_schema", _SCHEMA_PATH)
    mod = _ilu.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_schema = _load_schema_module()


class TestSchemaRoundTrip:
    """WorkstreamsManifest.scope_unknown parses and serializes correctly."""

    def _write_manifest(self, path, scope_unknown):
        data = {
            "protocol": "hermes-v1",
            "slug": "test-plan",
            "source": "/z-plan",
            "generated_at": "2026-01-01T00:00:00+00:00",
            "partial_tree": False,
            "scope_unknown": scope_unknown,
            "workstreams": [
                {
                    "id": "ws-1",
                    "status": "ready",
                    "name": "T001",
                    "path": "z-harness/test-plan/ws-1",
                    "tasks": ["T001"],
                    "depends_on": [],
                    "parallel_group": None,
                }
            ],
            "file_conflicts": [],
            "merge_order": ["ws-1"],
        }
        with open(path, "w") as f:
            json.dump(data, f)

    def test_scope_unknown_true_parses(self, tmp_path) -> None:
        """parse_workstreams_json reads scope_unknown=true from JSON."""
        p = str(tmp_path / "workstreams.json")
        self._write_manifest(p, True)
        manifest = _schema.parse_workstreams_json(p)
        assert manifest.scope_unknown is True

    def test_scope_unknown_false_parses(self, tmp_path) -> None:
        """parse_workstreams_json reads scope_unknown=false from JSON."""
        p = str(tmp_path / "workstreams.json")
        self._write_manifest(p, False)
        manifest = _schema.parse_workstreams_json(p)
        assert manifest.scope_unknown is False

    def test_scope_unknown_defaults_false_when_absent(self, tmp_path) -> None:
        """parse_workstreams_json defaults scope_unknown=False when key is absent."""
        data = {
            "protocol": "hermes-v1",
            "slug": "test-plan",
            "source": "/z-plan",
            "generated_at": "2026-01-01T00:00:00+00:00",
            "partial_tree": False,
            # scope_unknown intentionally absent
            "workstreams": [],
            "file_conflicts": [],
            "merge_order": [],
        }
        p = str(tmp_path / "workstreams.json")
        with open(p, "w") as f:
            json.dump(data, f)
        manifest = _schema.parse_workstreams_json(p)
        assert manifest.scope_unknown is False

    def test_validate_manifest_rejects_non_bool_scope_unknown(self, tmp_path) -> None:
        """validate_manifest returns an error when scope_unknown is not a bool."""
        p = str(tmp_path / "workstreams.json")
        self._write_manifest(p, True)
        manifest = _schema.parse_workstreams_json(p)
        # Manually corrupt the field to a non-bool
        manifest.scope_unknown = "yes"  # type: ignore[assignment]
        errors = _schema.validate_manifest(manifest)
        assert any("scope_unknown" in e for e in errors), (
            f"Expected a scope_unknown type error, got: {errors}"
        )

    def test_scope_unknown_serializes_via_asdict(self, tmp_path) -> None:
        """asdict(manifest) must include scope_unknown so callers can re-serialize it.

        This is the serialize direction of the round-trip:
          parse_workstreams_json → WorkstreamsManifest → asdict → dict

        If scope_unknown were omitted from the dataclass declaration, asdict would
        silently drop it and a subsequent json.dump would produce a manifest missing
        the field.  This test catches that regression.
        """
        from dataclasses import asdict as _asdict
        p = str(tmp_path / "workstreams.json")
        self._write_manifest(p, True)
        manifest = _schema.parse_workstreams_json(p)
        d = _asdict(manifest)
        assert "scope_unknown" in d, "asdict must include scope_unknown key"
        assert d["scope_unknown"] is True, (
            f"Expected asdict scope_unknown=True, got {d['scope_unknown']!r}"
        )

        # Also verify the False case round-trips correctly.
        self._write_manifest(p, False)
        manifest_false = _schema.parse_workstreams_json(p)
        d_false = _asdict(manifest_false)
        assert d_false["scope_unknown"] is False


# ---------------------------------------------------------------------------
# Tests: parallel_group population from workstream-DAG depth (T004 acceptance)
# ---------------------------------------------------------------------------

def _ws_parallel_group(ws_objects: list[dict], ws_id: str) -> str | None:
    """Return parallel_group for the named workstream."""
    for w in ws_objects:
        if w["id"] == ws_id:
            return w["parallel_group"]
    raise KeyError(f"workstream {ws_id!r} not found in result")


class TestParallelGroupLinearChain:
    """T001→T002→T003→T004 collapses to 1 workstream → parallel_group 'level-0'."""

    def setup_method(self):
        task_ids = ["T001", "T002", "T003", "T004"]
        deps = {
            "T001": [],
            "T002": ["T001"],
            "T003": ["T002"],
            "T004": ["T003"],
        }
        self.ws, _ = _mod.run_5rule_algorithm(task_ids, deps)

    def test_single_workstream_level_0(self) -> None:
        """Linear chain collapses to 1 ws; that ws must be level-0."""
        assert len(self.ws) == 1
        assert _ws_parallel_group(self.ws, "ws-1") == "level-0", (
            f"Expected parallel_group 'level-0', got {_ws_parallel_group(self.ws, 'ws-1')!r}"
        )


class TestParallelGroupFanOut:
    """T001→{T002,T003}: ws-1 (root) is level-0; ws-2 (leaves) is level-1."""

    def setup_method(self):
        task_ids = ["T001", "T002", "T003"]
        deps = {
            "T001": [],
            "T002": ["T001"],
            "T003": ["T001"],
        }
        self.ws, _ = _mod.run_5rule_algorithm(task_ids, deps)

    def test_ws1_is_level_0(self) -> None:
        assert _ws_parallel_group(self.ws, "ws-1") == "level-0"

    def test_ws2_is_level_1(self) -> None:
        assert _ws_parallel_group(self.ws, "ws-2") == "level-1"


class TestParallelGroupDeepFork:
    """Deep fork: ws-1..ws-4 must get level-0..level-3 matching longest-path depth.

    Graph from TestDeepFork:
      ws-1 {T001}       — no deps         → level-0
      ws-2 {T002,T004}  — depends on ws-1 → level-1
      ws-3 {T003,T005}  — depends on ws-2 → level-2
      ws-4 {T006}       — depends on ws-3 → level-3
    """

    def setup_method(self):
        task_ids = ["T001", "T002", "T003", "T004", "T005", "T006"]
        deps = {
            "T001": [],
            "T002": ["T001"],
            "T003": ["T002"],
            "T004": ["T001"],
            "T005": ["T004"],
            "T006": ["T003", "T005"],
        }
        self.ws, _ = _mod.run_5rule_algorithm(task_ids, deps)

    def test_ws1_level_0(self) -> None:
        assert _ws_parallel_group(self.ws, "ws-1") == "level-0"

    def test_ws2_level_1(self) -> None:
        assert _ws_parallel_group(self.ws, "ws-2") == "level-1"

    def test_ws3_level_2(self) -> None:
        assert _ws_parallel_group(self.ws, "ws-3") == "level-2"

    def test_ws4_level_3(self) -> None:
        assert _ws_parallel_group(self.ws, "ws-4") == "level-3"

    def test_rule7_passes_via_validate_workstreams(self) -> None:
        """validate_workstreams must not raise — Rule 7 passes by construction."""
        # validate_workstreams requires each ws dict to have a 'path' key
        # (Rule 5 check).  run_5rule_algorithm does not add paths — that is
        # done by build_from_flat.  Attach minimal stub paths here.
        ws_with_paths = [
            dict(w, path=f"z-harness/test/{w['id']}") for w in self.ws
        ]
        merge_order = _mod.topological_sort_ws(ws_with_paths)
        # Should not raise ValidationError.
        _mod.validate_workstreams(ws_with_paths, [], merge_order)

    def test_same_level_workstreams_are_mutually_independent(self) -> None:
        """No two workstreams at the same level may have a dependency between them.

        This is the invariant that makes parallel execution safe.  If ws-A and
        ws-B share a level but ws-B depends (directly or transitively) on ws-A,
        the test fails — Rule 7 would be violated.
        """
        from collections import defaultdict
        groups: dict = defaultdict(list)
        for w in self.ws:
            groups[w["parallel_group"]].append(w["id"])

        ws_map = {w["id"]: w for w in self.ws}

        def transitive_deps(wid):
            result = set()
            stack = list(ws_map[wid]["depends_on"])
            while stack:
                dep = stack.pop()
                if dep not in result:
                    result.add(dep)
                    stack.extend(ws_map[dep]["depends_on"])
            return result

        for group, members in groups.items():
            for a in members:
                a_deps = transitive_deps(a)
                for b in members:
                    assert b not in a_deps or a == b, (
                        f"ws '{a}' (group {group}) depends transitively on ws '{b}' "
                        f"in the same parallel_group — Rule 7 violation"
                    )


class TestBuildWorkstreamsJsonEndToEnd:
    """End-to-end CLI path: build_workstreams_json() runs validate_workstreams().

    The other tests in this module call build_from_flat()/build_from_light()
    directly, BELOW the validation layer — so they never caught that those
    builders emitted a workstream `path` with a trailing '/', which
    validate_workstreams() (and schema.py) reject. That made `--source z-plan`
    and `--source z-plan-light` always exit 2 in the shipped CLI. These tests
    exercise the full entry point so a trailing-slash regression fails loudly.
    """

    def test_z_plan_source_passes_validation(self, tmp_path) -> None:
        (tmp_path / "TASKS.md").write_text(
            "# Tasks\n\n"
            "## T001 — first `[ ]`\n**Files:** `src/a.py`\n\n"
            "## T002 — second `[ ]`\n**Files:** `src/b.py`\nDepends on: T001\n"
        )
        result = _mod.build_workstreams_json("test-plan", "z-plan", str(tmp_path))
        assert result["workstreams"], "expected at least one workstream"
        for w in result["workstreams"]:
            assert not w["path"].endswith("/"), (
                f"workstream path must not end with '/': {w['path']!r}"
            )

    def test_z_plan_light_source_passes_validation(self, tmp_path) -> None:
        (tmp_path / "FIX.md").write_text("# Fix\n\n## T001 — only task\n")
        result = _mod.build_workstreams_json("test-plan", "z-plan-light", str(tmp_path))
        assert result["workstreams"], "expected at least one workstream"
        for w in result["workstreams"]:
            assert not w["path"].endswith("/"), (
                f"workstream path must not end with '/': {w['path']!r}"
            )
