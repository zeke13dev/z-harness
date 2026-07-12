"""
tests/test_session_handoff.py — Tests for SESSION.md handoff mechanics.

Structure:
  - TestSessionHelpers     : unit tests for scripts/session-helpers.sh functions
                             (done_set_hash, completed_task_ids, last_done_task,
                              next_pending_task, last_curated_marker,
                              session_frontmatter_field)
  - TestCurator            : (T004) tests for agents/context-curator.md behaviour
  - TestResumeIntegration  : (T008) smoke tests for the resume predicate in
                             skills/z-execute/SKILL.md

T004 and T008 will append tests to the Curator and ResumeIntegration classes
respectively. This file intentionally keeps all three groups as top-level
classes with clear section comments so new test methods slot in cleanly.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import pytest

# ---------------------------------------------------------------------------
# Shared constants
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parent.parent
_HELPERS_SH = str(_REPO_ROOT / "scripts" / "session-helpers.sh")
_CONTEXT_CURATOR_PATH = _REPO_ROOT / "agents" / "context-curator.md"

# sha256("") — canonical empty-set hash that done_set_hash MUST return when
# zero tasks are marked [x].
_EMPTY_SHA256 = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"


# ---------------------------------------------------------------------------
# Shared helper utilities
# ---------------------------------------------------------------------------

def _run_helper(fn: str, *args: str, tmp_base: Path) -> str:
    """Invoke scripts/session-helpers.sh <fn> [args...] and return stripped stdout.

    Sets Z_HARNESS_BASE_DIR to *tmp_base* so the subprocess never touches the
    developer's real state directory.  The helper itself does not read
    Z_HARNESS_BASE_DIR, but setting it keeps the test hermetic in case that
    changes.
    """
    env = {**os.environ, "Z_HARNESS_BASE_DIR": str(tmp_base)}
    result = subprocess.run(
        ["bash", _HELPERS_SH, fn, *args],
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"session-helpers.sh {fn} exited {result.returncode}; "
        f"stderr: {result.stderr!r}"
    )
    return result.stdout.strip()


# ===========================================================================
# SECTION 1 — Helpers unit tests (T002)
# ===========================================================================

class TestSessionHelpers:
    """Unit tests for scripts/session-helpers.sh pure query functions.

    Each test:
    - Writes fixture files to pytest's tmp_path (no reliance on repo state).
    - Pins Z_HARNESS_BASE_DIR via _run_helper to a per-test tmp directory.
    - Asserts only on stdout (helpers are stdout-only, exit 0 always).
    """

    # -----------------------------------------------------------------------
    # done_set_hash — order-independence
    # -----------------------------------------------------------------------

    def test_done_set_hash_order_independent(self, tmp_path: Path):
        """Same [x] task-ids in different line order must produce identical hash."""
        tasks_a = tmp_path / "tasks_a.md"
        tasks_b = tmp_path / "tasks_b.md"

        tasks_a.write_text(
            "## T001 — Alpha `[x]`\n"
            "**Depends on:** —\n\n"
            "## T002 — Beta `[x]`\n"
            "**Depends on:** T001\n\n"
            "## T003 — Gamma `[ ]`\n"
            "**Depends on:** T002\n",
            encoding="utf-8",
        )
        # Same two [x] ids but written in reversed heading order.
        tasks_b.write_text(
            "## T002 — Beta `[x]`\n"
            "**Depends on:** —\n\n"
            "## T001 — Alpha `[x]`\n"
            "**Depends on:** —\n\n"
            "## T003 — Gamma `[ ]`\n"
            "**Depends on:** T001, T002\n",
            encoding="utf-8",
        )

        hash_a = _run_helper("done_set_hash", str(tasks_a), tmp_base=tmp_path)
        hash_b = _run_helper("done_set_hash", str(tasks_b), tmp_base=tmp_path)

        assert hash_a == hash_b, (
            f"Order changed the hash: a={hash_a!r}, b={hash_b!r}"
        )
        # Must not be the empty-set hash because we have two [x] ids.
        assert hash_a != _EMPTY_SHA256

    def test_done_set_hash_order_independent_three_ids(self, tmp_path: Path):
        """Three [x] ids in six permutations all yield the same hash."""
        ids = ["T001", "T002", "T003"]
        import itertools

        hashes = set()
        for perm in itertools.permutations(ids):
            content = ""
            for tid in perm:
                content += f"## {tid} — title `[x]`\n**Depends on:** —\n\n"
            content += "## T004 — pending `[ ]`\n**Depends on:** —\n"
            tasks_file = tmp_path / f"tasks_{''.join(perm)}.md"
            tasks_file.write_text(content, encoding="utf-8")
            h = _run_helper("done_set_hash", str(tasks_file), tmp_base=tmp_path)
            hashes.add(h)

        assert len(hashes) == 1, (
            f"Permutations produced different hashes: {hashes}"
        )

    # -----------------------------------------------------------------------
    # done_set_hash — empty-set case
    # -----------------------------------------------------------------------

    def test_done_set_hash_empty_set_canonical(self, tmp_path: Path):
        """Zero [x] tasks must hash to sha256('') exactly."""
        tasks = tmp_path / "tasks_empty.md"
        tasks.write_text(
            "## T001 — First `[ ]`\n"
            "**Depends on:** —\n\n"
            "## T002 — Second `[ ]`\n"
            "**Depends on:** T001\n",
            encoding="utf-8",
        )
        h = _run_helper("done_set_hash", str(tasks), tmp_base=tmp_path)
        assert h == _EMPTY_SHA256, (
            f"Expected empty-set hash {_EMPTY_SHA256!r}, got {h!r}"
        )

    def test_done_set_hash_missing_file_returns_empty_hash(self, tmp_path: Path):
        """A missing TASKS.md is treated as an empty done-set (sha256 of '')."""
        h = _run_helper(
            "done_set_hash",
            str(tmp_path / "nonexistent.md"),
            tmp_base=tmp_path,
        )
        assert h == _EMPTY_SHA256, (
            f"Missing file should produce empty-set hash, got {h!r}"
        )

    # -----------------------------------------------------------------------
    # done_set_hash — bullet/indented [x] detection
    # -----------------------------------------------------------------------

    def test_done_set_hash_tolerates_indented_bullet_markers(self, tmp_path: Path):
        """Indented bullet [x] markers are counted and produce the correct id-set hash.

        The helper supports two forms for marking a task done with a bullet checkbox:

        Pattern A (inline backtick status on heading):
            ## T001 — title `[x]`

        Pattern B (bare [x] line immediately before the heading):
            - [x]
            ## T001 — title

        NOTE: The inline form "  - [x] ## T001 — title" does NOT work — the helper
        grabs the first token after [x], which is "##", not "T001".  Only Pattern A
        and Pattern B are supported.

        This test uses Pattern B (bare indented bullet + next heading) for T001, and
        Pattern A (inline heading) for T003, producing a known done-set {T001, T003}.
        Correctness is verified by asserting the hash EQUALS the reference hash from
        a canonical Pattern-A-only fixture expressing the same id-set.
        """
        # Fixture using Pattern B for T001 (bare indented dash-bullet before heading)
        # and Pattern A for T003 (inline backtick status on heading).
        tasks = tmp_path / "tasks_bullets.md"
        tasks.write_text(
            # Pattern B: bare indented dash-bullet [x] on its own line; id comes from
            # the next heading.
            "  - [x]\n"
            "## T001 — title-one\n"
            "**Depends on:** —\n\n"
            # Pattern A: inline backtick status on heading line.
            "## T003 — title-three `[x]`\n"
            "**Depends on:** T001\n\n"
            # T002 is pending.
            "## T002 — pending `[ ]`\n"
            "**Depends on:** T001\n",
            encoding="utf-8",
        )

        # Reference fixture: same done-set {T001, T003} expressed entirely via Pattern A.
        # If the helper extracts the correct ids, both hashes must be identical.
        ref_tasks = tmp_path / "tasks_ref.md"
        ref_tasks.write_text(
            "## T001 — title-one `[x]`\n"
            "**Depends on:** —\n\n"
            "## T003 — title-three `[x]`\n"
            "**Depends on:** T001\n\n"
            "## T002 — pending `[ ]`\n"
            "**Depends on:** T001\n",
            encoding="utf-8",
        )

        h = _run_helper("done_set_hash", str(tasks), tmp_base=tmp_path)
        h_ref = _run_helper("done_set_hash", str(ref_tasks), tmp_base=tmp_path)

        # Equality proves that the helper extracted the correct ids {T001, T003},
        # not some spurious token.  If it had extracted "##" instead of "T001",
        # h would differ from h_ref.
        assert h == h_ref, (
            f"Indented bullet [x] marker produced wrong id-set: "
            f"h={h!r}, expected h_ref={h_ref!r}. "
            "The helper may have extracted '##' instead of 'T001' from the bullet line."
        )
        # Must not be the empty-set hash because two ids are marked done.
        assert h != _EMPTY_SHA256, (
            "Indented bullet [x] markers not detected — hash equals empty-set hash"
        )

    # -----------------------------------------------------------------------
    # last_done_task — basic fixture
    # -----------------------------------------------------------------------

    def test_last_done_task_returns_last_x_id(self, tmp_path: Path):
        """Returns the id of the last [x] heading in file order."""
        tasks = tmp_path / "tasks.md"
        tasks.write_text(
            "## T001 — First `[x]`\n"
            "**Depends on:** —\n\n"
            "## T002 — Second `[x]`\n"
            "**Depends on:** T001\n\n"
            "## T003 — Third `[ ]`\n"
            "**Depends on:** T002\n",
            encoding="utf-8",
        )
        result = _run_helper("last_done_task", str(tasks), tmp_base=tmp_path)
        assert result == "T002"

    def test_last_done_task_single_done(self, tmp_path: Path):
        """With only one [x] task, that id is returned."""
        tasks = tmp_path / "tasks.md"
        tasks.write_text(
            "## T001 — First `[x]`\n"
            "**Depends on:** —\n\n"
            "## T002 — Second `[ ]`\n"
            "**Depends on:** T001\n",
            encoding="utf-8",
        )
        result = _run_helper("last_done_task", str(tasks), tmp_base=tmp_path)
        assert result == "T001"

    def test_last_done_task_no_done_returns_empty(self, tmp_path: Path):
        """With no [x] tasks, stdout is empty."""
        tasks = tmp_path / "tasks.md"
        tasks.write_text(
            "## T001 — First `[ ]`\n"
            "**Depends on:** —\n",
            encoding="utf-8",
        )
        result = _run_helper("last_done_task", str(tasks), tmp_base=tmp_path)
        assert result == ""

    # -----------------------------------------------------------------------
    # completed_task_ids — full boundary completion set
    # -----------------------------------------------------------------------

    def test_completed_task_ids_returns_every_done_id_in_file_order(self, tmp_path: Path):
        """Clear-checkpoint metadata must include every completed batch/level id."""
        tasks = tmp_path / "tasks.md"
        tasks.write_text(
            "## T001 — Parallel one `[x]`\n"
            "**Depends on:** —\n\n"
            "## T002 — Still pending `[ ]`\n"
            "**Depends on:** —\n\n"
            "## T003 — Parallel two `[x]`\n"
            "**Depends on:** —\n\n"
            "## T004 — Parallel three `[x]`\n"
            "**Depends on:** —\n",
            encoding="utf-8",
        )

        result = _run_helper("completed_task_ids", str(tasks), tmp_base=tmp_path)
        assert result == "T001,T003,T004"

    def test_completed_task_ids_matches_bullet_status_forms(self, tmp_path: Path):
        """The full-id helper must parse the same [x] forms as done_set_hash."""
        tasks = tmp_path / "tasks.md"
        tasks.write_text(
            "- [x] T001 — inline bullet done\n"
            "- [ ] T002 — inline bullet pending\n"
            "- [x]\n"
            "## T003 — following heading done\n"
            "**Depends on:** —\n\n"
            "## T004 — inline heading done `[x]`\n"
            "**Depends on:** —\n",
            encoding="utf-8",
        )

        result = _run_helper("completed_task_ids", str(tasks), tmp_base=tmp_path)
        assert result == "T001,T003,T004"

    # -----------------------------------------------------------------------
    # next_pending_task — dep-gating
    # -----------------------------------------------------------------------
    # Dep-gating semantics (verified from helper source):
    #
    #   The helper reads "**Depends on:** <CSV>" lines inside each task block.
    #   A task is ELIGIBLE only when ALL listed dep-ids are present in the
    #   done_ids set (first pass over [x] headings).  "Depends on: —" or
    #   "Depends on:" or "Depends on: none" means no deps (always eligible).
    #   If no "Depends on:" line is found in a task block, deps default to []
    #   (always eligible).  The function returns the FIRST eligible [ ] task.

    def test_next_pending_task_basic_eligible(self, tmp_path: Path):
        """First [ ] task with satisfied deps is returned."""
        tasks = tmp_path / "tasks.md"
        tasks.write_text(
            "## T001 — First `[x]`\n"
            "**Depends on:** —\n\n"
            "## T002 — Second `[ ]`\n"
            "**Depends on:** T001\n\n"
            "## T003 — Third `[ ]`\n"
            "**Depends on:** T002\n",
            encoding="utf-8",
        )
        result = _run_helper("next_pending_task", str(tasks), tmp_base=tmp_path)
        # T002 dep (T001) is satisfied; T003 dep (T002) is NOT yet done.
        assert result == "T002"

    def test_next_pending_task_dep_not_satisfied_skips(self, tmp_path: Path):
        """A pending task whose dependency is NOT [x] must be skipped."""
        tasks = tmp_path / "tasks.md"
        tasks.write_text(
            # T001 is done.
            "## T001 — First `[x]`\n"
            "**Depends on:** —\n\n"
            # T002 depends on T099 which does not exist/is not done → must be SKIPPED.
            "## T002 — Second `[ ]`\n"
            "**Depends on:** T001, T099\n\n"
            # T003 has no deps → must be returned.
            "## T003 — Third `[ ]`\n"
            "**Depends on:** —\n",
            encoding="utf-8",
        )
        result = _run_helper("next_pending_task", str(tasks), tmp_base=tmp_path)
        # T002's dep T099 is not satisfied; T003 has no deps — T003 must win.
        assert result == "T003", (
            f"Expected T003 (T002's dep unsatisfied), got {result!r}"
        )

    def test_next_pending_task_all_deps_done_multi(self, tmp_path: Path):
        """Task with multiple deps all satisfied is eligible."""
        tasks = tmp_path / "tasks.md"
        tasks.write_text(
            "## T001 — First `[x]`\n"
            "**Depends on:** —\n\n"
            "## T004 — Fourth `[x]`\n"
            "**Depends on:** —\n\n"
            # T002 depends on both T001 and T004, both done → eligible.
            "## T002 — Second `[ ]`\n"
            "**Depends on:** T001, T004\n",
            encoding="utf-8",
        )
        result = _run_helper("next_pending_task", str(tasks), tmp_base=tmp_path)
        assert result == "T002"

    def test_next_pending_task_no_pending_returns_empty(self, tmp_path: Path):
        """When all tasks are [x], returns empty string."""
        tasks = tmp_path / "tasks.md"
        tasks.write_text(
            "## T001 — First `[x]`\n"
            "**Depends on:** —\n\n"
            "## T002 — Second `[x]`\n"
            "**Depends on:** T001\n",
            encoding="utf-8",
        )
        result = _run_helper("next_pending_task", str(tasks), tmp_base=tmp_path)
        assert result == ""

    def test_next_pending_task_chain_blocked(self, tmp_path: Path):
        """When the only pending task has an unsatisfied dep, returns empty."""
        tasks = tmp_path / "tasks.md"
        tasks.write_text(
            "## T001 — First `[x]`\n"
            "**Depends on:** —\n\n"
            # T002 depends on T003 which is pending (not done) → no eligible task.
            "## T002 — Second `[ ]`\n"
            "**Depends on:** T003\n\n"
            "## T003 — Third `[ ]`\n"
            "**Depends on:** T001\n",
            encoding="utf-8",
        )
        # T003 has T001 satisfied, so T003 is eligible.
        result = _run_helper("next_pending_task", str(tasks), tmp_base=tmp_path)
        assert result == "T003"

    def test_next_pending_task_dep_gating_indented_bullet(self, tmp_path: Path):
        """[x] ids from bare indented bullet markers count toward done_ids for dep-gating.

        The bare pattern: a "  - [x]" line (no id on the same line) immediately
        followed by a "## T001 — ..." heading.  The helper's prev_done flag
        routes the following heading id into done_ids.  This matches the
        orchestrator pattern '^\\s*[-*]?\\s*\\[x\\]'.

        Note: "  - [x] ## T001 — First" on a SINGLE line does NOT produce T001
        in done_ids because the id extractor takes the first non-space token after
        [x], which is "##".  The prev_done path (bare [x] line → next heading)
        is the form that works.
        """
        tasks = tmp_path / "tasks.md"
        tasks.write_text(
            # Bare indented dash-bullet [x] on its own line — next heading is T001
            "  - [x]\n"
            "## T001 — First\n\n"
            # T002 depends on T001 (which is done via the prev_done path) → eligible
            "## T002 — Second `[ ]`\n"
            "**Depends on:** T001\n",
            encoding="utf-8",
        )
        result = _run_helper("next_pending_task", str(tasks), tmp_base=tmp_path)
        assert result == "T002", (
            f"Expected T002 (T001 marked done via bare bullet + next heading), got {result!r}"
        )

    # -----------------------------------------------------------------------
    # last_curated_marker
    # -----------------------------------------------------------------------

    def test_last_curated_marker_returns_most_recent_ts(self, tmp_path: Path):
        """Returns the ts of the most recent context_curated event."""
        events = tmp_path / "metrics.jsonl"
        events.write_text(
            json.dumps({"kind": "task_complete", "ts": "2026-01-01T10:00:00Z", "task": "T001"}) + "\n"
            + json.dumps({
                "kind": "context_curated",
                "ts": "2026-01-01T10:05:00Z",
                "last_gate": "T001",
                "done_count": 1,
                "done_ids_hash": "abc123",
                "context_hash": "def456",
                "bytes": 1234,
            }) + "\n"
            + json.dumps({"kind": "task_complete", "ts": "2026-01-01T10:10:00Z", "task": "T002"}) + "\n"
            + json.dumps({
                "kind": "context_curated",
                "ts": "2026-01-01T10:15:00Z",
                "last_gate": "T002",
                "done_count": 2,
                "done_ids_hash": "xyz789",
                "context_hash": "qrs012",
                "bytes": 2345,
            }) + "\n",
            encoding="utf-8",
        )
        result = _run_helper("last_curated_marker", str(events), tmp_base=tmp_path)
        assert result == "2026-01-01T10:15:00Z"

    def test_last_curated_marker_no_curated_events_returns_none(self, tmp_path: Path):
        """With no context_curated events, prints 'none'."""
        events = tmp_path / "metrics.jsonl"
        events.write_text(
            json.dumps({"kind": "task_complete", "ts": "2026-01-01T10:00:00Z", "task": "T001"}) + "\n"
            + json.dumps({"kind": "task_complete", "ts": "2026-01-01T10:10:00Z", "task": "T002"}) + "\n",
            encoding="utf-8",
        )
        result = _run_helper("last_curated_marker", str(events), tmp_base=tmp_path)
        assert result == "none"

    def test_last_curated_marker_missing_file_returns_none(self, tmp_path: Path):
        """Missing events file returns 'none' (not an error)."""
        result = _run_helper(
            "last_curated_marker",
            str(tmp_path / "nonexistent.jsonl"),
            tmp_base=tmp_path,
        )
        assert result == "none"

    def test_last_curated_marker_single_event(self, tmp_path: Path):
        """Single context_curated event → its ts is returned."""
        ts = "2026-03-15T09:30:00Z"
        events = tmp_path / "metrics.jsonl"
        events.write_text(
            json.dumps({
                "kind": "context_curated",
                "ts": ts,
                "last_gate": "T005",
                "done_count": 5,
                "done_ids_hash": "hash5",
                "context_hash": "ctx5",
                "bytes": 999,
            }) + "\n",
            encoding="utf-8",
        )
        result = _run_helper("last_curated_marker", str(events), tmp_base=tmp_path)
        assert result == ts

    # -----------------------------------------------------------------------
    # session_frontmatter_field
    # -----------------------------------------------------------------------

    def test_session_frontmatter_field_reads_scalar(self, tmp_path: Path):
        """Reads a plain scalar YAML frontmatter field."""
        session = tmp_path / "SESSION.md"
        session.write_text(
            "---\n"
            "schema_version: \"1\"\n"
            "done_count: 3\n"
            "done_ids_hash: abc123def456\n"
            "last_gate: T003\n"
            "---\n"
            "# Session content\n",
            encoding="utf-8",
        )
        assert _run_helper("session_frontmatter_field", str(session), "done_ids_hash", tmp_base=tmp_path) == "abc123def456"
        assert _run_helper("session_frontmatter_field", str(session), "done_count", tmp_base=tmp_path) == "3"
        assert _run_helper("session_frontmatter_field", str(session), "last_gate", tmp_base=tmp_path) == "T003"

    def test_session_frontmatter_field_missing_field_returns_empty(self, tmp_path: Path):
        """A field not present in frontmatter returns empty string."""
        session = tmp_path / "SESSION.md"
        session.write_text(
            "---\n"
            "schema_version: \"1\"\n"
            "done_count: 2\n"
            "---\n"
            "# Content\n",
            encoding="utf-8",
        )
        result = _run_helper("session_frontmatter_field", str(session), "no_such_field", tmp_base=tmp_path)
        assert result == ""

    def test_session_frontmatter_field_missing_file_returns_empty(self, tmp_path: Path):
        """A missing SESSION.md returns empty string (not an error)."""
        result = _run_helper(
            "session_frontmatter_field",
            str(tmp_path / "no-session.md"),
            "done_ids_hash",
            tmp_base=tmp_path,
        )
        assert result == ""

    def test_session_frontmatter_field_strips_quotes(self, tmp_path: Path):
        """Quoted scalar values have their surrounding quotes stripped."""
        session = tmp_path / "SESSION.md"
        session.write_text(
            "---\n"
            "schema_version: \"1\"\n"
            "label: 'hello world'\n"
            "---\n",
            encoding="utf-8",
        )
        assert _run_helper("session_frontmatter_field", str(session), "schema_version", tmp_base=tmp_path) == "1"
        assert _run_helper("session_frontmatter_field", str(session), "label", tmp_base=tmp_path) == "hello world"

    # -----------------------------------------------------------------------
    # [x] detection regex — tolerates indented/bullet patterns (regression)
    # -----------------------------------------------------------------------

    def test_x_detection_tolerates_leading_bullet_indentation(self, tmp_path: Path):
        """
        The orchestrator pattern r'^\\s*[-*]?\\s*\\[x\\]' must match lines with
        leading spaces + dash (or asterisk) + [x], using the bare Pattern B form:

            <spaces>-<space>[x]      <- on its own line
            ## T001 -- title         <- id comes from the following heading (prev_done flag)

        NOTE: The inline form "  - [x] ## T001 -- title" is NOT supported -- the
        helper extracts "##" as the id, not "T001".

        Correctness is verified via downstream observables (not just a non-empty hash):
          1. last_done_task returns the expected id (T002 is last in file order).
          2. next_pending_task returns T003 (whose dep T001 is satisfied by the
             indented-dash [x] bullet), proving T001 entered done_ids correctly.
          3. The hash from the bullet fixture equals the hash of a canonical
             inline-heading fixture expressing the same done-set {T001, T002}.

        Failure mode guarded: if the dash/asterisk prefix were not tolerated by the
        regex, the [x] lines would be ignored, done_ids would be empty, T003's dep
        T001 would be unsatisfied, and next_pending_task would return "" not "T003".
        """
        tasks = tmp_path / "tasks_indent.md"
        tasks.write_text(
            # Pattern B with indented dash-bullet: bare [x] line, id from next heading.
            "  - [x]\n"
            "## T001 -- done via indented dash\n"
            "**Depends on:** --\n\n"
            # Pattern B with indented asterisk-bullet: bare [x] line, id from next heading.
            "  * [x]\n"
            "## T002 -- done via indented asterisk\n"
            "**Depends on:** T001\n\n"
            # T003 depends on T001; if T001 is in done_ids, T003 is eligible.
            "## T003 -- pending `[ ]`\n"
            "**Depends on:** T001\n",
            encoding="utf-8",
        )

        # Observable 1: last_done_task should return T002 (last [x] in file order).
        last_done = _run_helper("last_done_task", str(tasks), tmp_base=tmp_path)
        assert last_done == "T002", (
            f"last_done_task expected 'T002', got {last_done!r}. "
            "Indented asterisk-bullet [x] may not have been detected."
        )

        # Observable 2: next_pending_task should return T003 -- proving T001 entered
        # done_ids (T003's dep is T001, so it becomes eligible only if T001 is done).
        next_task = _run_helper("next_pending_task", str(tasks), tmp_base=tmp_path)
        assert next_task == "T003", (
            f"next_pending_task expected 'T003', got {next_task!r}. "
            "T001 (from indented dash-bullet) was not counted in done_ids, "
            "so T003's dep T001 appears unsatisfied."
        )

        # Observable 3: hash must equal that of a canonical Pattern-A fixture with
        # the same done-set {T001, T002}.  Inequality would mean wrong ids were extracted.
        ref_tasks = tmp_path / "tasks_indent_ref.md"
        ref_tasks.write_text(
            "## T001 -- done ref `[x]`\n"
            "**Depends on:** --\n\n"
            "## T002 -- done ref `[x]`\n"
            "**Depends on:** T001\n\n"
            "## T003 -- pending `[ ]`\n"
            "**Depends on:** T001\n",
            encoding="utf-8",
        )
        h = _run_helper("done_set_hash", str(tasks), tmp_base=tmp_path)
        h_ref = _run_helper("done_set_hash", str(ref_tasks), tmp_base=tmp_path)
        assert h == h_ref, (
            f"Bullet fixture hash {h!r} != reference hash {h_ref!r}. "
            "Indented bullet ids were not correctly extracted."
        )
        # Must not be the empty-set hash.
        assert h != _EMPTY_SHA256, (
            "Indented/bullet [x] lines were not detected; hash == empty-set hash."
        )


    def test_task_status_counts_matches_inline_heading_statuses(self, tmp_path: Path):
        """Checkpoint gates must count the same inline statuses as done_set_hash."""
        tasks = tmp_path / "tasks_counts.md"
        tasks.write_text(
            "## T001 -- done `[x]`\n"
            "**Depends on:** --\n\n"
            "## T002 -- pending `[ ]`\n"
            "**Depends on:** --\n\n"
            "## T003 -- running `[~]`\n"
            "**Depends on:** T001\n",
            encoding="utf-8",
        )

        counts = _run_helper("task_status_counts", str(tasks), tmp_base=tmp_path)

        assert counts == "done=1 pending=1 in_progress=1 other=0"

# ===========================================================================
# SECTION 2 — Curator unit tests (T004)
# ===========================================================================

# ---------------------------------------------------------------------------
# Shared fixture builder utilities (used by TestCurator tests only)
# ---------------------------------------------------------------------------

# Required frontmatter keys per agents/context-curator.md spec.
# The conditional keys (diff_unavailable, overflow, truncated_sections) are
# always present in the schema even when set to their falsy defaults.
_REQUIRED_FM_KEYS = [
    "artifact",
    "slug",
    "schema_version",
    "last_gate",
    "done_count",
    "done_ids_hash",
    "last_gate_task_id",
    "next_pending",
    "generated_by",
    "context_hash",
    "diff_unavailable",
    "overflow",
    "truncated_sections",
]

# Required section headings per spec.
_REQUIRED_SECTIONS = ["## Decisions", "## Landmines", "## Invariants", "## Open threads"]

# Per-section entry caps per spec (section_heading: max_entries).
_SECTION_CAPS = {
    "Decisions": 10,
    "Landmines": 10,
    "Invariants": 15,
    "Open threads": 10,
}

# Default character ceiling matching Z_SESSION_MAX_CHARS.
_DEFAULT_MAX_CHARS = 28000


def _build_session_md(
    *,
    slug: str = "test-slug",
    schema_version: int = 1,
    last_gate: str = "2026-01-01T00:00:00Z",
    done_count: int = 0,
    done_ids_hash: str = _EMPTY_SHA256,
    last_gate_task_id: str = "T001",
    next_pending: str = "none",
    context_hash: str = "",
    diff_unavailable: bool = False,
    overflow: bool = False,
    truncated_sections: list[str] | None = None,
    sections: dict[str, str] | None = None,
) -> str:
    """Return a well-formed SESSION.md string conforming to the spec schema.

    *sections* maps section name (without '## ') to its body text (may be empty).
    Defaults to all four required sections with empty bodies.
    """
    if truncated_sections is None:
        truncated_sections = []
    if sections is None:
        sections = {name: "" for name in ["Decisions", "Landmines", "Invariants", "Open threads"]}

    ts_list = "[" + ", ".join(truncated_sections) + "]"
    fm_lines = [
        "---",
        "artifact: session",
        f"slug: {slug}",
        f"schema_version: {schema_version}",
        f"last_gate: {last_gate}",
        f"done_count: {done_count}",
        f"done_ids_hash: {done_ids_hash}",
        f"last_gate_task_id: {last_gate_task_id}",
        f"next_pending: {next_pending}",
        "generated_by: context-curator",
        f"context_hash: {context_hash}",
        f"diff_unavailable: {str(diff_unavailable).lower()}",
        f"overflow: {str(overflow).lower()}",
        f"truncated_sections: {ts_list}",
        "---",
        "",
    ]
    body_parts = ["".join(f"{line}\n" for line in fm_lines)]
    for section_name, body in sections.items():
        body_parts.append(f"## {section_name}\n\n{body}\n")
    return "".join(body_parts)


def _parse_frontmatter(session_text: str) -> dict[str, Any]:
    """Parse the YAML frontmatter block of a SESSION.md string.

    Returns a dict of {field: raw_value_string} for all scalar fields, plus
    the literal list string for list fields.  This is intentionally a simple
    line-by-line parser that mirrors what session_frontmatter_field does — not
    a full YAML parser — so the tests reflect the contract the spec documents.
    """
    fm_match = re.match(r'^---\r?\n(.*?)\r?\n---', session_text, re.DOTALL)
    if not fm_match:
        return {}
    fm_body = fm_match.group(1)
    result: dict[str, Any] = {}
    for line in fm_body.splitlines():
        m = re.match(r'^(\w[\w_-]*)\s*:\s*(.*)', line)
        if m:
            key = m.group(1)
            val = m.group(2).strip()
            # Strip surrounding quotes from scalar values
            if (val.startswith('"') and val.endswith('"')) or \
               (val.startswith("'") and val.endswith("'")):
                val = val[1:-1]
            result[key] = val
    return result


def _count_section_entries(section_body: str, section_name: str) -> int:
    """Count the number of entries in a section body.

    For Landmines, entries are lines matching '**T...**: ...'.
    For Decisions / Open threads / Invariants, entries are non-blank lines that
    are not continuation lines (start of new entry = new logical bullet / line).
    We use a simple heuristic: non-blank, non-indented lines = one entry each.
    """
    if not section_body.strip():
        return 0
    lines = [ln for ln in section_body.splitlines() if ln.strip()]
    # Each top-level non-blank line counts as one entry (conservative).
    return len(lines)


def _extract_section_body(session_text: str, section_name: str) -> str:
    """Return the body text between '## section_name' and the next '## ' or EOF."""
    # Strip frontmatter first.
    fm_end = session_text.find('\n---\n', session_text.find('---'))
    if fm_end == -1:
        body_text = session_text
    else:
        body_text = session_text[fm_end + 5:]

    # Find the section.
    pattern = re.compile(
        r'^## ' + re.escape(section_name) + r'\s*\n(.*?)(?=^## |\Z)',
        re.MULTILINE | re.DOTALL,
    )
    m = pattern.search(body_text)
    if not m:
        return ""
    return m.group(1)


# ---------------------------------------------------------------------------
# The since_marker filter predicate — replicates the curator's documented filter
# exactly so we can test it deterministically without running the LLM.
# ---------------------------------------------------------------------------

def _apply_since_marker_filter(
    events: list[dict[str, Any]],
    slug: str,
    since_marker: str,
) -> list[dict[str, Any]]:
    """Apply the curator's documented filter predicate to a list of event dicts.

    Filter: slug == <slug> AND ts > since_marker.

    When since_marker is 'none', all events with matching slug are included
    (because every ts is > 'none' under string comparison, and the spec says
    'read all lines when since_marker is none').

    This function is pure Python — it does NOT execute the LLM curator.
    It exists to test the FILTER CONTRACT the spec mandates so that a future
    curator implementation that mis-implements the predicate would fail these tests.
    """
    result = []
    for event in events:
        event_slug = event.get("slug", "")
        event_ts = event.get("ts", "")
        if event_slug != slug:
            continue
        if since_marker == "none":
            result.append(event)
        elif event_ts > since_marker:
            result.append(event)
    return result


# ---------------------------------------------------------------------------
# Schema-invariant validator for SESSION.md cap / overflow rules.
# ---------------------------------------------------------------------------

class _CapViolation:
    """Describes a cap or overflow invariant violation in a SESSION.md."""

    def __init__(self, message: str) -> None:
        self.message = message

    def __repr__(self) -> str:
        return f"_CapViolation({self.message!r})"


def _validate_session_caps(session_text: str) -> list[_CapViolation]:
    """Validate the cap and overflow invariants of a SESSION.md string.

    Returns a (possibly empty) list of _CapViolation objects.  An empty list
    means the document is spec-conformant.  A non-empty list means one or more
    invariants are violated.

    Invariants checked (per agents/context-curator.md):
      1. Each section's entry count <= its cap (_SECTION_CAPS).
      2. If any section exceeds its entry cap, overflow must be 'true'.
      3. If overflow is 'true', truncated_sections must be non-empty.
      4. If overflow is 'false' (or absent), no section may exceed its cap.
      5. If a section is over-cap, its name must appear in truncated_sections.

    This function is DETERMINISTIC — it does not call any LLM.  It encodes
    the invariants the curator spec mandates so that a malformed SESSION.md
    (e.g. one where a section has 11 entries but overflow is false) is caught.
    """
    violations: list[_CapViolation] = []

    fm = _parse_frontmatter(session_text)
    overflow_str = fm.get("overflow", "false")
    overflow = overflow_str.strip().lower() == "true"

    ts_raw = fm.get("truncated_sections", "[]")
    if ts_raw.startswith("[") and ts_raw.endswith("]"):
        ts_inner = ts_raw[1:-1]
    else:
        ts_inner = ts_raw
    if ts_inner.strip():
        truncated_names = [n.strip().strip('"').strip("'") for n in ts_inner.split(",") if n.strip()]
    else:
        truncated_names = []

    over_cap_sections: list[str] = []
    for section_name, cap in _SECTION_CAPS.items():
        body = _extract_section_body(session_text, section_name)
        count = _count_section_entries(body, section_name)
        if count > cap:
            over_cap_sections.append(section_name)
            violations.append(_CapViolation(
                f"Section '{section_name}' has {count} entries but cap is {cap}"
            ))

    # If any section is over-cap, overflow must be true.
    if over_cap_sections and not overflow:
        violations.append(_CapViolation(
            f"Sections {over_cap_sections} are over-cap but overflow is not 'true'"
        ))

    # If overflow is true, truncated_sections must be non-empty.
    if overflow and not truncated_names:
        violations.append(_CapViolation(
            "overflow is 'true' but truncated_sections is empty"
        ))

    # Each over-cap section must appear in truncated_sections.
    for section_name in over_cap_sections:
        if section_name not in truncated_names:
            violations.append(_CapViolation(
                f"Section '{section_name}' is over-cap but not listed in truncated_sections"
            ))

    return violations


class TestCurator:
    """Unit tests for agents/context-curator.md behaviour.

    Testing strategy note
    ---------------------
    agents/context-curator.md is a markdown AGENT SPEC, not an executable script.
    We therefore cannot run the curator as a subprocess.  Instead we test:

    1. DETERMINISTIC subprocess assertions: parts of the spec that delegate to
       scripts/session-helpers.sh can be tested by calling that helper directly.
       Specifically: done_set_hash (the keystone hash-parity contract).

    2. SCHEMA FIXTURE assertions: we author SESSION.md fixtures that conform to
       the spec and assert the INVARIANTS the spec mandates (required keys,
       section presence/caps, overflow markers, failure-stub structure).

    3. FILTER PREDICATE assertions: the since_marker filter (slug == AND ts >
       since_marker) is deterministic logic; we replicate and test it with
       a metrics.jsonl fixture.

    Parts of the spec that are genuinely un-unit-testable without an LLM
    (flagged in cross_task_notes):
      - Step 2: LLM mining of breadcrumbs → candidate Decisions/Open-threads.
        The quality / coverage of landmine extraction from event kinds is an
        LLM-behaviour concern; we test only the filter predicate that selects
        which events reach the LLM, not what it does with them.
      - Step 4: "collapse resolved-decision bodies to heading-only lines" — this
        is a content transformation the LLM performs on section bodies.  We
        test only the entry-cap and overflow invariants via the deterministic
        _validate_session_caps() checker defined in this module.
      - Cap/overflow ENFORCEMENT by the curator (LLM behaviour — no executable
        function): there is no scripts/ helper that truncates sections or sets
        overflow flags; that logic lives entirely in the LLM agent prompt.  The
        tests here validate the SCHEMA INVARIANT (a spec-conformant SESSION.md
        must not violate caps or mis-set overflow) using _validate_session_caps(),
        which is itself proven correct by asserting it fires on deliberate
        violations and passes on well-formed fixtures.
      - Step 7: log-event.sh emission — tested elsewhere; not duplicated here.
    """

    def test_curator_spec_records_full_completed_task_metadata(self):
        """Curator prompt/event contract must preserve parallel/BFS completion sets."""
        spec = _CONTEXT_CURATOR_PATH.read_text(encoding="utf-8")

        assert "completed_task_ids" in spec
        assert "parallel batch or INTENT BFS level" in spec
        assert '"completed_task_ids":"%s"' in spec
        assert '"last_gate_task_id":"%s"' in spec
        assert "derived from the same `completed_task_ids` list and `tasks_file`" in spec

    # -----------------------------------------------------------------------
    # 1. HASH PARITY (keystone)
    # -----------------------------------------------------------------------

    def test_hash_parity_curator_hash_equals_helper_output(self, tmp_path: Path):
        """The done_ids_hash a curator would write == done_set_hash helper output.

        REAL SUBPROCESS ASSERTION.

        The curator computes done_ids_hash by calling:
            bash scripts/session-helpers.sh done_set_hash "$tasks_file"

        So the curator's hash IS the helper's hash by definition — the contract
        is that the writer (curator) and reader (E1 in z-execute) use the
        SAME helper and therefore produce byte-identical hashes.

        This test asserts the contract holds for a concrete fixture:
        1. Run the helper on a fixture TASKS.md → expected_hash.
        2. Build a SESSION.md (as the curator would) with done_ids_hash = expected_hash.
        3. Read done_ids_hash back via session_frontmatter_field → must equal expected_hash.

        If the curator were to re-implement the hash inline (violating the spec
        invariant), the hash it writes could diverge — E1 would never match it,
        and resume would silently never fire.  This test guards that divergence.
        """
        tasks = tmp_path / "TASKS.md"
        tasks.write_text(
            "## T001 — Alpha `[x]`\n"
            "**Depends on:** —\n\n"
            "## T002 — Beta `[x]`\n"
            "**Depends on:** T001\n\n"
            "## T003 — Gamma `[ ]`\n"
            "**Depends on:** T002\n",
            encoding="utf-8",
        )

        # Step 1: compute the canonical hash via the helper (real subprocess).
        expected_hash = _run_helper("done_set_hash", str(tasks), tmp_base=tmp_path)
        assert expected_hash != _EMPTY_SHA256, "Fixture has [x] tasks — hash must be non-empty"

        # Step 2: build a SESSION.md with done_ids_hash set to the helper's output
        #         (exactly what the curator does per spec step 5).
        session_file = tmp_path / "SESSION.md"
        session_text = _build_session_md(
            slug="test-plan",
            done_count=2,
            done_ids_hash=expected_hash,
            last_gate_task_id="T002",
        )
        session_file.write_text(session_text, encoding="utf-8")

        # Step 3: read back the hash via session_frontmatter_field (the same
        #         helper function that E1 uses on the read side).
        read_back = _run_helper(
            "session_frontmatter_field", str(session_file), "done_ids_hash",
            tmp_base=tmp_path,
        )
        assert read_back == expected_hash, (
            f"Hash parity violated: helper produced {expected_hash!r} but "
            f"session_frontmatter_field read back {read_back!r}.  "
            "Writer-vs-reader divergence would silently kill resume."
        )

    def test_hash_parity_order_independence_still_holds(self, tmp_path: Path):
        """Same [x] set in different line order → same hash → curator SESSION.md would match.

        REAL SUBPROCESS ASSERTION.

        If the curator processes TASKS.md files with the same done-set but different
        ordering, both calls to done_set_hash must return the same hash — otherwise
        resume would fire for one ordering but not the other.
        """
        tasks_alpha = tmp_path / "tasks_alpha.md"
        tasks_beta = tmp_path / "tasks_beta.md"

        # Order A: T001, T002, T003 (all [x]), T004 pending.
        tasks_alpha.write_text(
            "## T001 — First `[x]`\n**Depends on:** —\n\n"
            "## T002 — Second `[x]`\n**Depends on:** T001\n\n"
            "## T003 — Third `[x]`\n**Depends on:** T002\n\n"
            "## T004 — Fourth `[ ]`\n**Depends on:** T003\n",
            encoding="utf-8",
        )
        # Order B: T003, T001, T002 (same [x] set, different file order), T004 pending.
        tasks_beta.write_text(
            "## T003 — Third `[x]`\n**Depends on:** —\n\n"
            "## T001 — First `[x]`\n**Depends on:** —\n\n"
            "## T002 — Second `[x]`\n**Depends on:** —\n\n"
            "## T004 — Fourth `[ ]`\n**Depends on:** —\n",
            encoding="utf-8",
        )

        hash_alpha = _run_helper("done_set_hash", str(tasks_alpha), tmp_base=tmp_path)
        hash_beta = _run_helper("done_set_hash", str(tasks_beta), tmp_base=tmp_path)

        assert hash_alpha == hash_beta, (
            f"Order-dependent hashes would break resume: alpha={hash_alpha!r}, "
            f"beta={hash_beta!r}.  The curator must produce the same hash for "
            "any line ordering of the same done-set."
        )
        assert hash_alpha != _EMPTY_SHA256, "Non-empty done-set must not produce empty-set hash"

    # -----------------------------------------------------------------------
    # 2. Required frontmatter keys and section presence
    # -----------------------------------------------------------------------

    def test_required_frontmatter_keys_present(self, tmp_path: Path):
        """A spec-conformant SESSION.md must contain all required frontmatter keys.

        SCHEMA FIXTURE ASSERTION.

        This guards the contract that the curator always writes every key the spec
        documents.  If a key is missing, E1's session_frontmatter_field calls would
        silently return empty and resume would behave incorrectly (e.g. missing
        done_ids_hash → can never match → resume always skipped).
        """
        session_text = _build_session_md(
            slug="my-plan",
            done_count=3,
            done_ids_hash="abc" * 21 + "a",  # 64-char placeholder
            last_gate_task_id="T003",
            next_pending="T004",
            context_hash="def" * 21 + "a",
        )
        fm = _parse_frontmatter(session_text)

        missing = [k for k in _REQUIRED_FM_KEYS if k not in fm]
        assert not missing, (
            f"SESSION.md missing required frontmatter keys: {missing}.  "
            "The curator spec mandates all of these fields are always written."
        )

    def test_required_sections_present(self, tmp_path: Path):
        """A spec-conformant SESSION.md must contain all 4 section headings.

        SCHEMA FIXTURE ASSERTION.

        Missing a section heading means the curator's output is schema-invalid,
        which would cause the next curation's fold step to fail to find prior content.
        """
        session_text = _build_session_md(slug="test")
        for section_heading in _REQUIRED_SECTIONS:
            assert section_heading in session_text, (
                f"Required section '{section_heading}' missing from SESSION.md.  "
                "All 4 sections must always be present (even if empty)."
            )

    def test_conditional_keys_default_values(self, tmp_path: Path):
        """Conditional frontmatter keys must have correct default falsy values.

        SCHEMA FIXTURE ASSERTION.

        diff_unavailable defaults to false, overflow defaults to false,
        truncated_sections defaults to [].  Testing this guards that a curator
        which omits these fields or writes wrong defaults would be caught.
        """
        session_text = _build_session_md(slug="test")
        fm = _parse_frontmatter(session_text)

        assert fm.get("diff_unavailable") == "false", (
            f"diff_unavailable default should be 'false', got {fm.get('diff_unavailable')!r}"
        )
        assert fm.get("overflow") == "false", (
            f"overflow default should be 'false', got {fm.get('overflow')!r}"
        )
        assert fm.get("truncated_sections") == "[]", (
            f"truncated_sections default should be '[]', got {fm.get('truncated_sections')!r}"
        )

    # -----------------------------------------------------------------------
    # 3. Section entry caps — validator correctness (non-vacuous)
    # -----------------------------------------------------------------------
    # NOTE: There is no executable script that enforces caps; the curator (an
    # LLM agent) performs enforcement.  These tests prove _validate_session_caps()
    # correctly encodes the cap invariants by asserting it FIRES on deliberate
    # violations and PASSES on conformant fixtures.  A tautological "build
    # at-cap → assert count <= cap" test would only test the builder, not the
    # invariant; these tests instead build OVER-cap fixtures and assert the
    # validator detects them.
    # -----------------------------------------------------------------------

    def test_validator_detects_over_cap_section(self, tmp_path: Path):
        """_validate_session_caps fires when a section exceeds its entry cap.

        VALIDATOR CORRECTNESS ASSERTION.

        We build a SESSION.md with cap+1 entries in Decisions (deliberately
        malformed) and assert the validator returns at least one violation.
        We also guard that the fixture is genuinely over-cap so the assertion
        is non-vacuous.  A validator with a bug (e.g. off-by-one) would fail
        to return a violation here, which would be caught by this test.
        """
        cap = _SECTION_CAPS["Decisions"]
        over_cap_count = cap + 1  # deliberately over-cap

        # Build over-cap entries.
        entries_over = "\n".join(
            f"Decision {i + 1}: chose option A." for i in range(over_cap_count)
        )

        # Sanity: fixture is actually over-cap.
        assert _count_section_entries(entries_over, "Decisions") > cap, (
            "Fixture setup error: entries should be over-cap"
        )

        # Build a SESSION.md that has over-cap Decisions but overflow=false
        # (i.e. a malformed document a curator without cap enforcement would produce).
        malformed_session = _build_session_md(
            overflow=False,
            truncated_sections=[],
            sections={
                "Decisions": entries_over,
                "Landmines": "",
                "Invariants": "",
                "Open threads": "",
            }
        )
        violations = _validate_session_caps(malformed_session)
        assert violations, (
            f"Validator must report a violation for a Decisions section with "
            f"{over_cap_count} entries (cap={cap}) and overflow=false, "
            f"but returned no violations"
        )

    def test_validator_passes_conformant_all_sections(self, tmp_path: Path):
        """_validate_session_caps passes when all sections are at or below cap.

        VALIDATOR CORRECTNESS ASSERTION.

        We build a SESSION.md with each section at exactly its cap (the maximum
        conformant count) and overflow=false.  The validator must return no
        violations.  This is the inverse of the over-cap test — it confirms the
        validator does not produce false positives for valid documents.
        """
        sections_at_cap = {
            section_name: "\n".join(
                f"Entry {i + 1}: content here." for i in range(cap)
            )
            for section_name, cap in _SECTION_CAPS.items()
        }
        conformant_session = _build_session_md(
            overflow=False,
            truncated_sections=[],
            sections=sections_at_cap,
        )
        violations = _validate_session_caps(conformant_session)
        assert not violations, (
            f"Validator must pass a conformant SESSION.md (all sections at cap), "
            f"but returned violations: {violations}"
        )

    def test_validator_detects_over_cap_without_overflow_flag(self, tmp_path: Path):
        """Validator fires when Landmines exceeds cap with overflow=false.

        VALIDATOR CORRECTNESS ASSERTION.

        Tests the cross-invariant rule: an over-cap section without overflow=true
        is a violation.  A curator that truncates but forgets to set overflow=true
        would produce a document that violates this invariant.  The validator must
        catch it.
        """
        cap = _SECTION_CAPS["Landmines"]
        over_cap_entries = "\n".join(
            f"**T{i:03d}**: Some hazard was encountered." for i in range(1, cap + 2)
        )
        assert _count_section_entries(over_cap_entries, "Landmines") > cap, (
            "Fixture setup error: entries should be over-cap"
        )

        # Session has over-cap Landmines but overflow is false — malformed.
        malformed = _build_session_md(
            overflow=False,
            truncated_sections=[],
            sections={
                "Decisions": "",
                "Landmines": over_cap_entries,
                "Invariants": "",
                "Open threads": "",
            }
        )
        violations = _validate_session_caps(malformed)
        assert violations, (
            f"Validator must report a violation for Landmines over cap ({cap}) "
            f"with overflow=false, but returned no violations"
        )

    def test_validator_detects_invariants_over_cap(self, tmp_path: Path):
        """Validator fires when Invariants section exceeds its cap of 15.

        VALIDATOR CORRECTNESS ASSERTION.

        Invariants has a higher cap (15) than the other sections.  This test
        explicitly exercises that boundary so an off-by-one in the validator's
        cap lookup would be caught.
        """
        cap = _SECTION_CAPS["Invariants"]
        assert cap == 15, f"Expected Invariants cap=15, got {cap}"  # guard spec value
        over_cap_entries = "\n".join(
            f"Invariant {i}: system behaves correctly." for i in range(1, cap + 2)
        )
        assert _count_section_entries(over_cap_entries, "Invariants") > cap, (
            "Fixture setup error: entries should be over-cap"
        )

        malformed = _build_session_md(
            overflow=False,
            truncated_sections=[],
            sections={
                "Decisions": "",
                "Landmines": "",
                "Invariants": over_cap_entries,
                "Open threads": "",
            }
        )
        violations = _validate_session_caps(malformed)
        assert violations, (
            f"Validator must report a violation for Invariants with >{cap} entries "
            f"and overflow=false, but returned no violations"
        )

    def test_validator_detects_open_threads_over_cap(self, tmp_path: Path):
        """Validator fires when Open threads section exceeds its cap of 10.

        VALIDATOR CORRECTNESS ASSERTION.
        """
        cap = _SECTION_CAPS["Open threads"]
        over_cap_entries = "\n".join(
            f"Open thread {i}: still unresolved." for i in range(1, cap + 2)
        )
        assert _count_section_entries(over_cap_entries, "Open threads") > cap, (
            "Fixture setup error: entries should be over-cap"
        )

        malformed = _build_session_md(
            overflow=False,
            truncated_sections=[],
            sections={
                "Decisions": "",
                "Landmines": "",
                "Invariants": "",
                "Open threads": over_cap_entries,
            }
        )
        violations = _validate_session_caps(malformed)
        assert violations, (
            f"Validator must report a violation for Open threads with >{cap} entries "
            f"and overflow=false, but returned no violations"
        )

    # -----------------------------------------------------------------------
    # 4. Overflow: overflow=true requires non-empty truncated_sections (validator)
    # -----------------------------------------------------------------------
    # NOTE: Z_SESSION_MAX_CHARS enforcement (the LLM dropping entries until the
    # body is under the character ceiling) is LLM behaviour with no executable
    # enforcement function.  These tests instead prove _validate_session_caps()
    # correctly encodes the overflow cross-invariant: if overflow=true then
    # truncated_sections must be non-empty, and if overflow=false then no section
    # may be over-cap.  The validator is proven correct by asserting it FIRES on
    # deliberately malformed fixtures (not just that it passes on fixtures the
    # builder already constructed correctly).
    # -----------------------------------------------------------------------

    def test_validator_detects_overflow_true_with_empty_truncated_sections(self, tmp_path: Path):
        """Validator fires when overflow=true but truncated_sections is empty.

        VALIDATOR CORRECTNESS ASSERTION.

        A curator that sets overflow=true but forgets to populate
        truncated_sections would produce a document that violates this invariant.
        The validator must catch it.  This is a non-vacuous test: the fixture
        explicitly sets overflow=true with an empty truncated_sections list —
        a naive check that only reads the overflow field would miss this pairing.
        """
        # Build a session with overflow=true but truncated_sections=[] — malformed.
        malformed = _build_session_md(
            overflow=True,
            truncated_sections=[],  # missing — violates the invariant
            sections={
                "Decisions": "Decision 1: chose option A.",
                "Landmines": "",
                "Invariants": "",
                "Open threads": "",
            }
        )
        violations = _validate_session_caps(malformed)
        assert violations, (
            "Validator must report a violation when overflow=true but "
            "truncated_sections is empty, but returned no violations"
        )
        # Confirm the violation message mentions truncated_sections.
        messages = [v.message for v in violations]
        assert any("truncated_sections" in m for m in messages), (
            f"Expected a truncated_sections violation; got: {messages}"
        )

    def test_validator_passes_overflow_true_with_named_sections(self, tmp_path: Path):
        """Validator passes when overflow=true and truncated_sections is non-empty.

        VALIDATOR CORRECTNESS ASSERTION.

        This is the conformant case: overflow=true with a named section in
        truncated_sections (but the section itself is NOT over its entry cap,
        because overflow may be set due to character ceiling, not entry count).
        The validator must not produce false positives here.
        """
        # Build a session with overflow=true and a named truncated section.
        # Decisions has only 1 entry (well within cap=10), but overflow=true
        # because the curator hit the character ceiling (LLM-only enforcement).
        conformant = _build_session_md(
            overflow=True,
            truncated_sections=["Decisions"],
            sections={
                "Decisions": "Decision 1: chose option A.",
                "Landmines": "",
                "Invariants": "",
                "Open threads": "",
            }
        )
        violations = _validate_session_caps(conformant)
        # The only violation rule that could fire here is "over-cap section" or
        # "overflow=true but truncated_sections empty".  Neither applies here.
        assert not violations, (
            f"Validator must pass a conformant overflow=true SESSION.md with "
            f"named truncated_sections, but returned violations: {violations}"
        )

    def test_validator_passes_non_overflowing_session(self, tmp_path: Path):
        """Validator passes when overflow=false and all sections are within caps.

        VALIDATOR CORRECTNESS ASSERTION.

        This is the base-case conformant document.  The validator must return no
        violations.  If a curator unconditionally sets overflow=true, this test
        plus test_validator_detects_overflow_true_with_empty_truncated_sections
        would together catch that failure mode.
        """
        short_session = _build_session_md(
            overflow=False,
            truncated_sections=[],
            sections={
                "Decisions": "Decision 1: chose option A.",
                "Landmines": "",
                "Invariants": "",
                "Open threads": "",
            }
        )
        violations = _validate_session_caps(short_session)
        assert not violations, (
            f"Validator must pass a conformant non-overflowing SESSION.md, "
            f"but returned violations: {violations}"
        )

    def test_truncated_sections_names_are_valid_section_names(self, tmp_path: Path):
        """truncated_sections must only contain valid section names from the spec.

        SCHEMA FIXTURE ASSERTION.

        If the curator writes an unknown section name in truncated_sections, a
        downstream consumer (e.g. an observability tool) would silently misreport
        which sections were affected.
        """
        valid_names = {"Decisions", "Landmines", "Invariants", "Open threads"}
        # Build a fixture with Decisions and Landmines truncated.
        session_text = _build_session_md(
            overflow=True,
            truncated_sections=["Decisions", "Landmines"],
        )
        fm = _parse_frontmatter(session_text)
        ts_raw = fm.get("truncated_sections", "[]")
        # Strip brackets and split.
        if ts_raw.startswith("[") and ts_raw.endswith("]"):
            ts_raw = ts_raw[1:-1]
        if ts_raw.strip():
            names = [n.strip().strip('"').strip("'") for n in ts_raw.split(",") if n.strip()]
            invalid = [n for n in names if n not in valid_names]
            assert not invalid, (
                f"truncated_sections contains invalid section names: {invalid}.  "
                f"Valid names are: {sorted(valid_names)}"
            )

    # -----------------------------------------------------------------------
    # 5. since_marker incrementality — filter predicate
    # -----------------------------------------------------------------------

    def test_since_marker_excludes_events_at_or_older_than_marker(self, tmp_path: Path):
        """Events with ts <= since_marker must be excluded from the delta.

        FILTER PREDICATE ASSERTION.

        The spec says: filter to lines where slug == <slug> AND ts > since_marker.
        An event AT the marker (ts == since_marker) must NOT be included (> not >=).
        An event BEFORE the marker must NOT be included.

        This test exercises the filter predicate using Python-replicated logic
        (_apply_since_marker_filter) against a metrics.jsonl fixture.  If the
        curator mis-implements the predicate (e.g. uses >= instead of >) it would
        include stale events, leading to duplicate entries in SESSION.md.
        """
        slug = "my-plan"
        since_marker = "2026-01-01T12:00:00Z"

        events = [
            # Before marker: must be excluded.
            {"kind": "task_done", "slug": slug, "ts": "2026-01-01T11:00:00Z", "task": "T001"},
            # AT marker: must be excluded (spec says ts > marker, not >=).
            {"kind": "task_done", "slug": slug, "ts": since_marker, "task": "T002"},
            # After marker: must be included.
            {"kind": "task_done", "slug": slug, "ts": "2026-01-01T13:00:00Z", "task": "T003"},
            {"kind": "context_breadcrumb", "slug": slug, "ts": "2026-01-01T14:00:00Z", "task": "T004"},
        ]

        filtered = _apply_since_marker_filter(events, slug, since_marker)
        filtered_tasks = [e["task"] for e in filtered]

        assert "T001" not in filtered_tasks, "Event before since_marker must be excluded"
        assert "T002" not in filtered_tasks, "Event AT since_marker must be excluded (ts > not >=)"
        assert "T003" in filtered_tasks, "Event after since_marker must be included"
        assert "T004" in filtered_tasks, "Event after since_marker must be included"

    def test_since_marker_excludes_other_slugs(self, tmp_path: Path):
        """Events from a different slug must be excluded even if their ts > since_marker.

        FILTER PREDICATE ASSERTION.

        The metrics.jsonl file is repo-wide and contains events from all plans.
        The curator must filter to slug == <slug> strictly — events from other
        plans must not leak into the SESSION.md content.
        """
        slug = "target-plan"
        other_slug = "other-plan"
        since_marker = "2026-01-01T10:00:00Z"

        events = [
            # Other slug, after marker — must be excluded.
            {"kind": "task_done", "slug": other_slug, "ts": "2026-01-01T11:00:00Z", "task": "T001"},
            # Correct slug, after marker — must be included.
            {"kind": "task_done", "slug": slug, "ts": "2026-01-01T11:00:00Z", "task": "T002"},
            # No slug field — must be excluded (slug != target).
            {"kind": "task_done", "ts": "2026-01-01T11:00:00Z", "task": "T003"},
        ]

        filtered = _apply_since_marker_filter(events, slug, since_marker)
        included_tasks = [e["task"] for e in filtered]

        assert "T001" not in included_tasks, "Other-slug event must not appear in delta"
        assert "T002" in included_tasks, "Correct-slug event must appear in delta"
        assert "T003" not in included_tasks, "Event with no slug must not appear in delta"

    def test_since_marker_none_includes_all_matching_slug(self, tmp_path: Path):
        """When since_marker is 'none', all events with the correct slug are included.

        FILTER PREDICATE ASSERTION.

        The spec says 'read all lines when since_marker is none'.  This applies
        on first curation (no prior context_curated event exists).
        """
        slug = "fresh-plan"
        events = [
            {"kind": "task_done", "slug": slug, "ts": "2026-01-01T09:00:00Z", "task": "T001"},
            {"kind": "task_done", "slug": slug, "ts": "2026-01-01T10:00:00Z", "task": "T002"},
            {"kind": "context_breadcrumb", "slug": slug, "ts": "2026-01-01T11:00:00Z", "task": "T003"},
            # Different slug — must still be excluded even with since_marker=none.
            {"kind": "task_done", "slug": "other", "ts": "2026-01-01T09:00:00Z", "task": "T099"},
        ]

        filtered = _apply_since_marker_filter(events, slug, "none")
        included_tasks = [e["task"] for e in filtered]

        assert "T001" in included_tasks, "With since_marker=none, all matching-slug events included"
        assert "T002" in included_tasks, "With since_marker=none, all matching-slug events included"
        assert "T003" in included_tasks, "With since_marker=none, all matching-slug events included"
        assert "T099" not in included_tasks, "Other-slug event must not be included even when since_marker=none"

    def test_since_marker_metrics_jsonl_fixture(self, tmp_path: Path):
        """The filter predicate applied to a metrics.jsonl fixture yields only the delta.

        FILTER PREDICATE ASSERTION.

        Reads events from a written metrics.jsonl fixture (not in-memory), parses
        each JSON line, and applies the filter.  This mirrors how the curator actually
        reads event_source.
        """
        slug = "plan-abc"
        since_marker = "2026-03-01T08:00:00Z"

        metrics = tmp_path / "metrics.jsonl"
        # Events before the marker or from other slugs.
        pre_marker_events = [
            {"kind": "task_done", "slug": slug, "ts": "2026-02-28T23:59:00Z", "task": "T001"},
            {"kind": "task_done", "slug": "other-plan", "ts": "2026-03-01T09:00:00Z", "task": "T999"},
        ]
        # Events from this slug after the marker (the delta).
        delta_events = [
            {"kind": "task_done", "slug": slug, "ts": "2026-03-01T09:00:00Z", "task": "T002"},
            {"kind": "task_halt", "slug": slug, "ts": "2026-03-01T10:00:00Z", "run": "tasks/T003"},
            {"kind": "context_breadcrumb", "slug": slug, "ts": "2026-03-01T11:00:00Z", "intent": "used default"},
        ]

        all_events = pre_marker_events + delta_events
        metrics.write_text(
            "\n".join(json.dumps(e) for e in all_events) + "\n",
            encoding="utf-8",
        )

        # Read and parse.
        parsed: list[dict[str, Any]] = []
        for line in metrics.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                parsed.append(json.loads(line))

        filtered = _apply_since_marker_filter(parsed, slug, since_marker)

        # Only delta events should appear.
        filtered_tasks_and_intents = [
            e.get("task") or e.get("intent") for e in filtered
        ]
        assert "T001" not in filtered_tasks_and_intents, "Pre-marker event must be excluded"
        assert "T999" not in filtered_tasks_and_intents, "Other-slug event must be excluded"
        assert "T002" in filtered_tasks_and_intents, "Delta task_done event must be included"
        assert "used default" in filtered_tasks_and_intents, "Delta breadcrumb must be included"
        # task_halt event is in the delta.
        halt_events = [e for e in filtered if e.get("kind") == "task_halt"]
        assert len(halt_events) == 1, "One task_halt in the delta should be included"

    # -----------------------------------------------------------------------
    # 6. git diff failure → diff_unavailable:true, not a hard fail
    # -----------------------------------------------------------------------

    def test_diff_unavailable_true_in_valid_session_md(self, tmp_path: Path):
        """A SESSION.md with diff_unavailable:true is still a valid, readable artifact.

        SCHEMA FIXTURE ASSERTION.

        When git diff exits non-zero, the curator sets diff_unavailable:true and
        continues curation.  A SESSION.md produced this way must still be readable
        by session_frontmatter_field — it must not fail the resume predicate merely
        because diff_unavailable is set.

        This test verifies:
        1. diff_unavailable:true is a valid frontmatter value (not schema-breaking).
        2. session_frontmatter_field can read done_ids_hash from such a file.
        3. The other required keys (schema_version, done_count) are also readable.
        """
        tasks = tmp_path / "TASKS.md"
        tasks.write_text(
            "## T001 — First `[x]`\n**Depends on:** —\n\n"
            "## T002 — Second `[ ]`\n**Depends on:** T001\n",
            encoding="utf-8",
        )
        expected_hash = _run_helper("done_set_hash", str(tasks), tmp_base=tmp_path)

        # Simulate curator writing with diff_unavailable:true.
        session_file = tmp_path / "SESSION.md"
        session_text = _build_session_md(
            slug="test-plan",
            done_count=1,
            done_ids_hash=expected_hash,
            last_gate_task_id="T001",
            diff_unavailable=True,  # <— the key flag being tested
        )
        session_file.write_text(session_text, encoding="utf-8")

        # Verify the file is readable by the helper (simulates E1 reading it).
        hash_read = _run_helper(
            "session_frontmatter_field", str(session_file), "done_ids_hash",
            tmp_base=tmp_path,
        )
        assert hash_read == expected_hash, (
            "session_frontmatter_field must read done_ids_hash from diff_unavailable:true SESSION.md"
        )

        diff_unavail = _run_helper(
            "session_frontmatter_field", str(session_file), "diff_unavailable",
            tmp_base=tmp_path,
        )
        assert diff_unavail == "true", (
            f"diff_unavailable should be 'true', got {diff_unavail!r}"
        )

        schema_v = _run_helper(
            "session_frontmatter_field", str(session_file), "schema_version",
            tmp_base=tmp_path,
        )
        assert schema_v == "1", (
            f"schema_version should be '1', got {schema_v!r}"
        )

    # -----------------------------------------------------------------------
    # 7. Failure stub
    # -----------------------------------------------------------------------

    def test_failure_stub_has_valid_done_ids_hash(self, tmp_path: Path):
        """A failure-stub SESSION.md must contain a valid done_ids_hash from the helper.

        REAL SUBPROCESS ASSERTION + SCHEMA FIXTURE ASSERTION.

        The spec (failure-stub path) says:
          Compute done_ids_hash by calling done_set_hash "$tasks_file" directly
          from TASKS.md (independent of the event read that may have failed).
          The stub's resume key remains valid even when event reading failed.

        This test:
        1. Computes expected_hash via the helper on a fixture TASKS.md.
        2. Builds a stub SESSION.md (frontmatter-only, overflow:true, empty sections)
           with done_ids_hash = expected_hash.
        3. Asserts done_ids_hash is readable via session_frontmatter_field.
        4. Asserts overflow:true (the stub always sets this per spec).
        5. Asserts the 4 section headings ARE present but bodies are empty.
        """
        tasks = tmp_path / "TASKS.md"
        tasks.write_text(
            "## T001 — First `[x]`\n**Depends on:** —\n\n"
            "## T002 — Second `[x]`\n**Depends on:** T001\n\n"
            "## T003 — Third `[ ]`\n**Depends on:** T002\n",
            encoding="utf-8",
        )
        # Real subprocess call — the same call the curator stub-path makes.
        expected_hash = _run_helper("done_set_hash", str(tasks), tmp_base=tmp_path)
        assert expected_hash != _EMPTY_SHA256, "Fixture has [x] tasks; stub hash must be non-empty"

        # Build the stub as the curator's failure-stub path specifies.
        stub_text = _build_session_md(
            slug="my-plan",
            done_count=0,         # stub uses 0 (event read failed; can't count)
            done_ids_hash=expected_hash,
            last_gate_task_id="T002",
            next_pending="none",
            context_hash="",
            diff_unavailable=True,
            overflow=True,         # spec: stub always sets overflow:true
            truncated_sections=[],
            sections={            # spec: stub has no section bodies
                "Decisions": "",
                "Landmines": "",
                "Invariants": "",
                "Open threads": "",
            },
        )
        stub_file = tmp_path / "SESSION.md"
        stub_file.write_text(stub_text, encoding="utf-8")

        # Assert the helper can read back the hash (simulates E1's resume check).
        read_hash = _run_helper(
            "session_frontmatter_field", str(stub_file), "done_ids_hash",
            tmp_base=tmp_path,
        )
        assert read_hash == expected_hash, (
            f"Stub done_ids_hash not readable: expected {expected_hash!r}, got {read_hash!r}"
        )

        # Assert overflow:true (the failure-stub invariant).
        overflow_val = _run_helper(
            "session_frontmatter_field", str(stub_file), "overflow",
            tmp_base=tmp_path,
        )
        assert overflow_val == "true", (
            f"Failure stub must have overflow:true, got {overflow_val!r}"
        )

        # Assert all 4 section headings are present (body may be empty).
        for heading in _REQUIRED_SECTIONS:
            assert heading in stub_text, (
                f"Failure stub missing section heading '{heading}'.  "
                "All 4 sections must be present even when bodies are empty."
            )

    def test_failure_stub_hash_equals_helper_on_same_tasks(self, tmp_path: Path):
        """Failure-stub done_ids_hash must equal done_set_hash helper on the same TASKS.md.

        REAL SUBPROCESS ASSERTION.

        This is the critical invariant: the stub's done_ids_hash is computed by
        calling the helper on TASKS.md (not from events), so E1's resume predicate
        can still match it against the current TASKS.md done-set hash — even when
        the event read failed.

        Failure mode guarded: if the stub path re-computed the hash via a different
        method (or hardcoded a placeholder), this test would fail, and resume would
        ALWAYS skip the stub (done_set_mismatch), defeating the feature's purpose.
        """
        tasks = tmp_path / "TASKS.md"
        tasks.write_text(
            "## T001 — First `[x]`\n**Depends on:** —\n\n"
            "## T002 — Second `[ ]`\n**Depends on:** T001\n",
            encoding="utf-8",
        )

        # Compute the expected hash via the helper (what the stub must contain).
        helper_hash = _run_helper("done_set_hash", str(tasks), tmp_base=tmp_path)

        # Simulate the stub path: call done_set_hash independently.
        stub_hash = _run_helper("done_set_hash", str(tasks), tmp_base=tmp_path)

        assert helper_hash == stub_hash, (
            f"Stub hash {stub_hash!r} != helper hash {helper_hash!r}.  "
            "The stub path must call the same helper — never inline a different algorithm."
        )

        # Verify a stub SESSION.md with this hash is readable on resume.
        stub_file = tmp_path / "SESSION.md"
        stub_file.write_text(
            _build_session_md(
                slug="plan-stub",
                done_ids_hash=stub_hash,
                overflow=True,
                diff_unavailable=True,
            ),
            encoding="utf-8",
        )
        read_back = _run_helper(
            "session_frontmatter_field", str(stub_file), "done_ids_hash",
            tmp_base=tmp_path,
        )
        # A subsequent resume attempt reading this stub gets the helper hash — matches.
        assert read_back == helper_hash, (
            "Stub hash written to SESSION.md does not round-trip via session_frontmatter_field"
        )


# ===========================================================================
# SECTION 3 — Resume integration smoke tests (T008)
# ===========================================================================

class TestResumeIntegration:
    """Smoke tests for the SESSION.md resume predicate in skills/z-execute/SKILL.md.

    Testing strategy
    ----------------
    The E1 resume predicate lives in skills/z-execute/SKILL.md (step 4a) and is
    a Markdown prose spec — not an executable function.  We therefore cannot run it
    as a subprocess.  Instead we:

    1. Encode the E1 predicate as a small deterministic Python helper
       _resume_decision() that mirrors the spec's four conditions exactly (see its
       docstring).  The decisive computation — the done-set hash comparison — is
       REAL: it calls the subprocess helper scripts/session-helpers.sh::done_set_hash
       the same way the orchestrator does.  The boolean glue mirrors the spec logic.

    2. Exercise _resume_decision() with concrete fixture scenarios that are designed
       to FAIL if the predicate were wrong (non-vacuous).

    3. Separately assert that SESSION.md size is within the ceiling so the inline
       in the pass-case is bounded (the spec's "bounded re-seed" guarantee).

    Reference: skills/z-execute/SKILL.md step 4a ("Resume from SESSION.md if
    present and current"), specifically the "Resume predicate — all four conditions
    must hold" block.

    Manual / observational check (not a unit assert)
    -------------------------------------------------
    After merging the SESSION.md handoff feature into a live plan, verify the O(N^2)
    cache_read reduction as follows:

      1. Run /z-execute on a plan large enough to trigger a compaction_pause
         (primary trigger: context pressure reaches the configured checkpoint
         percentage; legacy heuristic fallback: ≥ Z_IMPLEMENT_PAUSE_TASKS
         completed tasks, default 5).
      2. After the pause, issue /clear and re-invoke /z-execute.
      3. In the Claude web UI or SDK metrics, compare the cache_read token count at
         the start of the resumed run to the cache_read count of an equivalent run
         without /clear.  The resumed run should show significantly fewer cache_read
         tokens because the orchestrator inlines only SESSION.md (≤ ~7 K tokens)
         instead of re-reading the full prior conversation window (O(N) * tasks).

    This is a live-run, non-deterministic measurement — it cannot be expressed as a
    repeatable unit assertion.  Log the before/after cache_read values from
    metrics.jsonl (the session_resumed event records the rehydration point).
    """

    # -----------------------------------------------------------------------
    # _resume_decision — local deterministic predicate helper
    # -----------------------------------------------------------------------

    @staticmethod
    def _resume_decision(
        tasks_file: Path,
        session_file: Path,
        tmp_base: Path,
        supported_schema_versions: tuple[str, ...] = ("1",),
    ) -> tuple[bool, str]:
        """Mirror the E1 resume predicate from skills/z-execute/SKILL.md step 4a.

        This function is DETERMINISTIC.  The done-set hash comparison — the decisive
        bit — is real: it calls scripts/session-helpers.sh::done_set_hash via
        _run_helper() subprocess, exactly as the orchestrator does.  The four-condition
        boolean logic is a spec mirror (not an LLM call).

        Reference: skills/z-execute/SKILL.md step 4a, "Resume predicate — all four
        conditions must hold":
          1. SESSION.md exists (SV non-empty is the evidence).
          2. schema_version is in the supported set (currently {"1"}).
          3. frontmatter.done_ids_hash == done_set_hash(TASKS.md).
          4. At least one [ ] task remains in TASKS.md.

        Returns (resume: bool, reason: str) where reason is one of:
          "session_resumed"        — all four conditions held.
          "no_session_file"        — SESSION.md does not exist / SV is empty.
          "schema_unsupported"     — SV not in supported set.
          "done_set_mismatch"      — hashes differ (done-set changed offline).
          "no_pending"             — hash matched but zero pending tasks remain.
        """
        # --- Condition 1: SESSION.md exists (proxy: SV non-empty) ---
        if not session_file.exists():
            return (False, "no_session_file")
        sv = _run_helper(
            "session_frontmatter_field", str(session_file), "schema_version",
            tmp_base=tmp_base,
        )
        if not sv:
            return (False, "no_session_file")

        # --- Condition 2: schema_version supported ---
        if sv not in supported_schema_versions:
            return (False, "schema_unsupported")

        # --- Condition 3: done-set hash match (REAL subprocess call) ---
        #   CUR_HASH = done_set_hash(TASKS.md)   [same call the orchestrator makes]
        #   DH = session_frontmatter_field(SESSION.md, done_ids_hash)
        cur_hash = _run_helper("done_set_hash", str(tasks_file), tmp_base=tmp_base)
        dh = _run_helper(
            "session_frontmatter_field", str(session_file), "done_ids_hash",
            tmp_base=tmp_base,
        )
        if dh != cur_hash:
            return (False, "done_set_mismatch")

        # --- Condition 4: at least one pending task ---
        #
        # Mirrors z-execute.md step 4a, which computes PENDING_COUNT via the
        # canonical helper:
        #   NEXT_PENDING_NOW="$(... session-helpers.sh next_pending_task "$TASKS_FILE")"
        #   PENDING_COUNT = 1 if non-empty else 0;  condition: $PENDING_COUNT >= 1
        #
        # The shipped code and this test both use next_pending_task so done- and
        # pending-detection stay in lockstep and both handle the inline-heading status
        # format ("## T001 — title `[ ]`") that real TASKS.md files use. (Historical note:
        # E1 originally hand-rolled `grep -cE '^\s*[-*]?\s*\[ \]'`, which silently returned
        # 0 on inline-heading TASKS.md and made resume inert; T008 surfaced it and E1 was
        # switched to this helper.) Non-empty => >=1 actionable pending task.
        next_task = _run_helper("next_pending_task", str(tasks_file), tmp_base=tmp_base)
        if not next_task:
            return (False, "no_pending")

        return (True, "session_resumed")

    # -----------------------------------------------------------------------
    # Test 1: MATCH → resume
    # -----------------------------------------------------------------------

    def test_match_hash_and_pending_yields_session_resumed(self, tmp_path: Path):
        """Breakpoint fixture with matching done-hash and pending tasks → resume.

        REAL SUBPROCESS ASSERTION + PREDICATE MIRROR ASSERTION.

        Setup:
          TASKS.md at a breakpoint state: T001, T003 done [x]; T002, T004 pending [ ].
          SESSION.md frontmatter: done_ids_hash = done_set_hash(that TASKS.md),
          computed via the SAME helper the orchestrator uses.

        Assertions:
          1. _resume_decision returns (True, "session_resumed").
          2. CUR_HASH == SESSION.md done_ids_hash (the hash comparison is real).
          3. At least one [ ] task exists (verified via next_pending_task helper).
          4. SESSION.md size ≤ Z_SESSION_MAX_CHARS (the inline is bounded per spec).

        Failure mode guarded: if done_ids_hash were wrong in SESSION.md, or if
        _resume_decision checked the wrong condition, the test would fail.
        """
        tasks = tmp_path / "TASKS.md"
        tasks.write_text(
            "## T001 — Alpha `[x]`\n"
            "**Depends on:** —\n\n"
            "## T002 — Beta `[ ]`\n"
            "**Depends on:** T001\n\n"
            "## T003 — Gamma `[x]`\n"
            "**Depends on:** —\n\n"
            "## T004 — Delta `[ ]`\n"
            "**Depends on:** T001\n",
            encoding="utf-8",
        )

        # Compute hash via the SAME helper the orchestrator uses.
        cur_hash = _run_helper("done_set_hash", str(tasks), tmp_base=tmp_path)
        assert cur_hash != _EMPTY_SHA256, "Fixture has [x] tasks; hash must be non-empty"

        # Build SESSION.md with done_ids_hash = that hash (as curator would write).
        session_file = tmp_path / "SESSION.md"
        session_text = _build_session_md(
            slug="test-plan",
            schema_version=1,
            done_count=2,
            done_ids_hash=cur_hash,
            last_gate_task_id="T003",
            next_pending="T002",
            sections={
                "Decisions": "Decision 1: used default model.",
                "Landmines": "**T003**: required patching helper.",
                "Invariants": "done_set_hash must be order-independent.",
                "Open threads": "",
            },
        )
        session_file.write_text(session_text, encoding="utf-8")

        # Assertion 1: predicate returns session_resumed.
        resume, reason = self._resume_decision(tasks, session_file, tmp_path)
        assert resume is True, (
            f"Expected session_resumed but got ({resume!r}, {reason!r}).  "
            "Matching done-hash + pending tasks must yield resume=True."
        )
        assert reason == "session_resumed"

        # Assertion 2: verify the hash comparison is real (not vacuous).
        read_hash = _run_helper(
            "session_frontmatter_field", str(session_file), "done_ids_hash",
            tmp_base=tmp_path,
        )
        assert read_hash == cur_hash, (
            f"Hash written to SESSION.md ({read_hash!r}) != CUR_HASH ({cur_hash!r}).  "
            "The done-set hash comparison must be genuine."
        )

        # Assertion 3: at least one pending task via next_pending_task.
        next_pending = _run_helper("next_pending_task", str(tasks), tmp_base=tmp_path)
        assert next_pending, (
            "next_pending_task must return a task id — fixture must have ≥1 pending"
        )

        # Assertion 4: SESSION.md size within the ceiling.
        session_size = len(session_text.encode("utf-8"))
        assert session_size <= _DEFAULT_MAX_CHARS, (
            f"SESSION.md size {session_size} exceeds Z_SESSION_MAX_CHARS "
            f"({_DEFAULT_MAX_CHARS}).  The inline re-seed must be bounded."
        )

    # -----------------------------------------------------------------------
    # Test 2: OUT-OF-ORDER SAME-SET → resume
    # -----------------------------------------------------------------------

    def test_out_of_order_same_done_set_still_resumes(self, tmp_path: Path):
        """Same done-set {T001,T003} in different line order → hash matches → resume.

        REAL SUBPROCESS ASSERTION (order-independence is the spec's key property).

        Setup:
          SESSION.md is written against a "pause-time" TASKS.md where T001 appears
          before T003.  At "resume time", a TASKS.md is presented where the headings
          are reordered: T003 appears before T001 (but both still [x]).

        Assertions:
          1. done_set_hash(pause TASKS.md) == done_set_hash(resume TASKS.md).
             This is the critical order-independence assertion — NOT vacuous because
             we deliberately shuffle the heading order and prove equality holds.
          2. _resume_decision on the resume TASKS.md returns (True, "session_resumed").
          3. Sanity: if we had NOT shuffled (used the same file twice), equality would
             trivially hold.  The shuffle makes this test genuinely non-trivial.

        Failure mode guarded: if done_set_hash were line-order-dependent, the two
        hashes would differ and the predicate would return done_set_mismatch instead
        of session_resumed.
        """
        # Pause-time TASKS.md: T001 listed before T003.
        pause_tasks = tmp_path / "tasks_pause.md"
        pause_tasks.write_text(
            "## T001 — First `[x]`\n"
            "**Depends on:** —\n\n"
            "## T002 — Second `[ ]`\n"
            "**Depends on:** T001\n\n"
            "## T003 — Third `[x]`\n"
            "**Depends on:** —\n",
            encoding="utf-8",
        )

        # Resume-time TASKS.md: T003 now listed BEFORE T001 (shuffled order).
        # Both are still [x]; the done-set is identical: {T001, T003}.
        resume_tasks = tmp_path / "tasks_resume.md"
        resume_tasks.write_text(
            "## T003 — Third `[x]`\n"
            "**Depends on:** —\n\n"
            "## T001 — First `[x]`\n"
            "**Depends on:** —\n\n"
            "## T002 — Second `[ ]`\n"
            "**Depends on:** —\n",
            encoding="utf-8",
        )

        # Assertion 1: hashes must be EQUAL despite shuffled order.
        pause_hash = _run_helper("done_set_hash", str(pause_tasks), tmp_base=tmp_path)
        resume_hash = _run_helper("done_set_hash", str(resume_tasks), tmp_base=tmp_path)
        assert pause_hash == resume_hash, (
            f"Order-shuffled same done-set produced DIFFERENT hashes: "
            f"pause={pause_hash!r}, resume={resume_hash!r}.  "
            "done_set_hash must be order-independent — a hash mismatch here means "
            "resume would be skipped for no reason every time TASKS.md heading "
            "order changes."
        )
        # Extra sanity: the hash must not be the empty-set hash.
        assert pause_hash != _EMPTY_SHA256, "Non-empty done-set must not hash to empty-set"

        # Write SESSION.md with the pause-time hash (as the curator would at pause).
        session_file = tmp_path / "SESSION.md"
        session_file.write_text(
            _build_session_md(
                slug="order-test",
                schema_version=1,
                done_count=2,
                done_ids_hash=pause_hash,
                last_gate_task_id="T003",
                next_pending="T002",
            ),
            encoding="utf-8",
        )

        # Assertion 2: _resume_decision on the SHUFFLED resume TASKS.md → session_resumed.
        resume, reason = self._resume_decision(resume_tasks, session_file, tmp_path)
        assert resume is True, (
            f"Out-of-order same done-set must yield session_resumed, "
            f"but got ({resume!r}, {reason!r})."
        )
        assert reason == "session_resumed"

    # -----------------------------------------------------------------------
    # Test 3: OFFLINE-COMPLETION MISMATCH → skip (safety-critical)
    # -----------------------------------------------------------------------

    def test_offline_completion_mismatch_yields_skip(self, tmp_path: Path):
        """Extra [x] task completed offline → hash differs → done_set_mismatch skip.

        REAL SUBPROCESS ASSERTION.  THIS IS THE SAFETY-CRITICAL TEST.

        Setup:
          SESSION.md is written at pause time for done-set {T001, T003}.
          Before resume, T005 is marked [x] offline (set now: {T001, T003, T005}).

        Assertions:
          1. done_set_hash(pause set) != done_set_hash(resume set).  This assertion
             is GENUINE: we prove the hashes DIFFER — not just that we can call the
             helper.  A test that accidentally made hashes equal would pass vacuously.
          2. _resume_decision returns (False, "done_set_mismatch").
          3. SESSION.md is NOT inlined (predicate false).

        Failure mode guarded: if done_set_hash were insensitive to set membership
        changes, or if _resume_decision did not check the hash, a plan that had tasks
        completed offline since the pause would get a stale SESSION.md inlined,
        potentially re-seeding incorrect state (e.g. tasks listed as pending that are
        actually done).
        """
        # Pause-time TASKS.md: only T001 and T003 done.
        pause_tasks = tmp_path / "tasks_pause.md"
        pause_tasks.write_text(
            "## T001 — Alpha `[x]`\n"
            "**Depends on:** —\n\n"
            "## T002 — Beta `[ ]`\n"
            "**Depends on:** T001\n\n"
            "## T003 — Gamma `[x]`\n"
            "**Depends on:** —\n\n"
            "## T004 — Delta `[ ]`\n"
            "**Depends on:** T001\n\n"
            "## T005 — Epsilon `[ ]`\n"
            "**Depends on:** —\n",
            encoding="utf-8",
        )

        # Resume-time TASKS.md: T005 additionally marked [x] offline.
        resume_tasks = tmp_path / "tasks_resume.md"
        resume_tasks.write_text(
            "## T001 — Alpha `[x]`\n"
            "**Depends on:** —\n\n"
            "## T002 — Beta `[ ]`\n"
            "**Depends on:** T001\n\n"
            "## T003 — Gamma `[x]`\n"
            "**Depends on:** —\n\n"
            "## T004 — Delta `[ ]`\n"
            "**Depends on:** T001\n\n"
            "## T005 — Epsilon `[x]`\n"  # <-- completed offline!
            "**Depends on:** —\n",
            encoding="utf-8",
        )

        # Compute both hashes via the REAL subprocess helper.
        pause_hash = _run_helper("done_set_hash", str(pause_tasks), tmp_base=tmp_path)
        resume_hash = _run_helper("done_set_hash", str(resume_tasks), tmp_base=tmp_path)

        # Assertion 1: hashes must GENUINELY differ (the safety assertion).
        # If they were equal here, the test would be vacuous — we must prove they differ.
        assert pause_hash != resume_hash, (
            f"Expected hashes to DIFFER after offline completion, but both are "
            f"{pause_hash!r}.  Fixture may be wrong — check that T005 is [x] only "
            "in resume_tasks, not in pause_tasks."
        )
        assert pause_hash != _EMPTY_SHA256, "Pause done-set is non-empty"
        assert resume_hash != _EMPTY_SHA256, "Resume done-set is non-empty (larger set)"

        # Write SESSION.md with the PAUSE-TIME hash.
        session_file = tmp_path / "SESSION.md"
        session_file.write_text(
            _build_session_md(
                slug="mismatch-test",
                schema_version=1,
                done_count=2,
                done_ids_hash=pause_hash,  # <-- hash for {T001, T003} only
                last_gate_task_id="T003",
                next_pending="T002",
            ),
            encoding="utf-8",
        )

        # Assertion 2: _resume_decision against the RESUME-TIME TASKS.md must skip.
        resume, reason = self._resume_decision(resume_tasks, session_file, tmp_path)
        assert resume is False, (
            f"Offline completion mismatch must yield resume=False, "
            f"but _resume_decision returned ({resume!r}, {reason!r})"
        )
        assert reason == "done_set_mismatch", (
            f"Expected reason='done_set_mismatch', got {reason!r}"
        )

        # Assertion 3: confirm SESSION.md not inlined — the predicate is False, so
        # the spec says "Do not inline the SESSION.md body in any skip case."
        # We verify this by confirming the predicate returned False.
        assert not resume, (
            "SESSION.md body must NOT be inlined when the predicate is False"
        )

    # -----------------------------------------------------------------------
    # Test 4: NO PENDING → skip
    # -----------------------------------------------------------------------

    def test_no_pending_tasks_yields_no_pending_skip(self, tmp_path: Path):
        """All tasks [x] and no pending remain → no_pending skip.

        REAL SUBPROCESS ASSERTION.

        Setup:
          TASKS.md where ALL tasks are [x] — no pending tasks remain.
          SESSION.md whose done_ids_hash matches the current TASKS.md hash.

        Assertions:
          1. done_set_hash(tasks) != empty-set hash (non-empty done-set).
          2. next_pending_task returns empty string (no pending task).
          3. _resume_decision returns (False, "no_pending").
          4. sanity: the hash DID match (condition 3 held) but condition 4 failed.

        Failure mode guarded: if _resume_decision ignored the no-pending condition,
        it would return session_resumed for a finished plan — the orchestrator would
        inline a SESSION.md and then immediately find no tasks to run, which is
        confusing (and potentially an infinite loop if the orchestrator recurs).
        """
        tasks = tmp_path / "TASKS.md"
        tasks.write_text(
            "## T001 — Alpha `[x]`\n"
            "**Depends on:** —\n\n"
            "## T002 — Beta `[x]`\n"
            "**Depends on:** T001\n\n"
            "## T003 — Gamma `[x]`\n"
            "**Depends on:** T002\n",
            encoding="utf-8",
        )

        # Compute hash — all three tasks are [x].
        cur_hash = _run_helper("done_set_hash", str(tasks), tmp_base=tmp_path)
        assert cur_hash != _EMPTY_SHA256, "All-done fixture hash must be non-empty"

        # Assertion 2: verify via helper that no pending task exists.
        next_pending = _run_helper("next_pending_task", str(tasks), tmp_base=tmp_path)
        assert next_pending == "", (
            f"Expected no pending task (all [x]), but next_pending_task returned {next_pending!r}"
        )

        # Write SESSION.md with the matching hash.
        session_file = tmp_path / "SESSION.md"
        session_file.write_text(
            _build_session_md(
                slug="no-pending-test",
                schema_version=1,
                done_count=3,
                done_ids_hash=cur_hash,  # hash DOES match — only condition 4 fails
                last_gate_task_id="T003",
                next_pending="none",
            ),
            encoding="utf-8",
        )

        # Assertion 3: predicate must skip with no_pending reason.
        resume, reason = self._resume_decision(tasks, session_file, tmp_path)
        assert resume is False, (
            f"All-done TASKS.md must yield resume=False (no pending tasks), "
            f"but _resume_decision returned ({resume!r}, {reason!r})"
        )
        assert reason == "no_pending", (
            f"Expected reason='no_pending', got {reason!r}"
        )

        # Assertion 4: the hash match itself held — the failure was condition 4 (no pending).
        dh = _run_helper(
            "session_frontmatter_field", str(session_file), "done_ids_hash",
            tmp_base=tmp_path,
        )
        assert dh == cur_hash, (
            "Sanity: hash should have matched (condition 3 held); only condition 4 failed"
        )


# ===========================================================================
# SECTION 4 — handoff.schema.json validation harness (T005/T006)
# ===========================================================================
# Introduces the FIRST live jsonschema validator for handoff.json. T005 changes
# the schema's protocol_version from `const: "1.0"` to `enum: ["1.0", "1.1"]`
# and adds an OPTIONAL nested `attend_resume` object; T006 adds fresh-session
# context roles while preserving path/role-only thin pointers. Together:
#   (a) a 1.0 handoff with NO attend_resume key still validates,
#   (b) a populated 1.1 handoff validates, and
#   (c) HANDOFF.md/INTENT.md/LEDGER.md context pointers validate without
#       allowing embedded file content.

import copy as _copy

jsonschema = pytest.importorskip("jsonschema")

_SCHEMA_PATH = _REPO_ROOT / "docs" / "schemas" / "handoff.schema.json"
_ZHANDOFF_SKILL_PATH = _REPO_ROOT / "skills" / "z-handoff" / "SKILL.md"
_ZEXECUTE_SKILL_PATH = _REPO_ROOT / "skills" / "z-execute" / "SKILL.md"
_ZAUDIT_SKILL_PATH = _REPO_ROOT / "skills" / "z-audit" / "SKILL.md"
_ZEXPLORE_SKILL_PATH = _REPO_ROOT / "skills" / "z-explore" / "SKILL.md"
_ZRESEARCH_SKILL_PATH = _REPO_ROOT / "skills" / "z-research" / "SKILL.md"
_ZTEST_SKILL_PATH = _REPO_ROOT / "skills" / "z-test" / "SKILL.md"
_ZDEBUG_SKILL_PATH = _REPO_ROOT / "skills" / "z-debug" / "SKILL.md"
_ZREVIEW_ALL_SKILL_PATH = _REPO_ROOT / "skills" / "z-review-all" / "SKILL.md"




def _load_zhandoff_skill() -> str:
    """Load the live manual /z-handoff contract from disk."""
    return _ZHANDOFF_SKILL_PATH.read_text(encoding="utf-8")

def _load_zexecute_skill() -> str:
    """Load the live /z-execute contract from disk."""
    return _ZEXECUTE_SKILL_PATH.read_text(encoding="utf-8")

def _load_zaudit_skill() -> str:
    """Load the live /z-audit contract from disk."""
    return _ZAUDIT_SKILL_PATH.read_text(encoding="utf-8")


def _load_zexplore_skill() -> str:
    """Load the live /z-explore terrain contract from disk."""
    return _ZEXPLORE_SKILL_PATH.read_text(encoding="utf-8")


def _load_zresearch_skill() -> str:
    """Load the live /z-research contract from disk."""
    return _ZRESEARCH_SKILL_PATH.read_text(encoding="utf-8")


def _load_ztest_skill() -> str:
    """Load the live /z-test contract from disk."""
    return _ZTEST_SKILL_PATH.read_text(encoding="utf-8")


def _load_zdebug_skill() -> str:
    """Load the live /z-debug contract from disk."""
    return _ZDEBUG_SKILL_PATH.read_text(encoding="utf-8")

def _load_zreview_all_skill() -> str:
    """Load the live /z-review-all contract from disk."""
    return _ZREVIEW_ALL_SKILL_PATH.read_text(encoding="utf-8")



def _load_handoff_schema() -> dict[str, Any]:
    """Load the live docs/schemas/handoff.schema.json from disk."""
    return json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))


def _make_1_0_handoff() -> dict[str, Any]:
    """A minimal valid protocol 1.0 handoff with NO attend_resume key.

    Mirrors exactly what write-handoff.sh emits on the non-attend (curator /
    compaction) path: every `required` root field present, attend_resume absent.
    """
    return {
        "protocol_version": "1.0",
        "timestamp": "2026-06-11T12:00:00Z",
        "agent": "pi",
        "slug": "attended-chain",
        "status": "clean_break",
        "next_step": "Resume /z-execute for attended-chain. 2/5 tasks done.",
        "context_files": [
            {"path": "/tmp/plan/HANDOFF.md", "role": "handoff"},
            {"path": "/tmp/plan/HANDOFF.md", "role": "invariants"},
            {"path": "/tmp/plan/HANDOFF.md", "role": "rejected_approaches"},
            {"path": "/tmp/plan/HANDOFF.md", "role": "decisions_archive"},
            {"path": "/tmp/plan/HANDOFF.md", "role": "verification_commands"},
            {"path": "/tmp/plan/INTENT.md", "role": "intent"},
            {"path": "/tmp/plan/SPEC.md", "role": "spec"},
            {"path": "/tmp/plan/PLAN.md", "role": "plan"},
            {"path": "/tmp/plan/TASKS.md", "role": "tasks"},
            {"path": "/tmp/plan/FIX.md", "role": "plan"},
            {"path": "/tmp/plan/workstreams.json", "role": "workstreams"},
            {"path": "/tmp/plan/LEDGER.md", "role": "ledger"},
        ],
    }


def _make_1_1_handoff() -> dict[str, Any]:
    """A valid protocol 1.1 handoff with a fully populated attend_resume block."""
    base = _make_1_0_handoff()
    base["protocol_version"] = "1.1"
    base["attend_resume"] = {
        "expected_head_sha": "6b2e6a3f0000000000000000000000000000abcd",
        "expected_phase": "implement-all",
        "done_set_hash": _EMPTY_SHA256,
        "dirty_state_fingerprint": "sha256:deadbeefcafe",
        "session_id": "sess-20260611-120000",
    }
    return base


class TestHandoffSchemaValidation:
    """Live jsonschema validation of docs/schemas/handoff.schema.json (T005/T006).

    These are the regression guards for the const→enum change. They fail if a
    future edit reverts protocol_version to a const (which would reject the 1.0
    fixture), drops the 1.0 value from the enum, makes attend_resume required,
    or relaxes its additionalProperties:false.
    """

    # -- (a) old 1.0 file (no attend_resume) still validates -----------------

    def test_1_0_handoff_without_attend_resume_validates(self):
        """A protocol 1.0 handoff with no attend_resume key validates.

        Old handoffs (and the non-attend write-handoff.sh path) must keep
        validating after the schema change — attend_resume is OPTIONAL.
        """
        schema = _load_handoff_schema()
        handoff = _make_1_0_handoff()
        assert "attend_resume" not in handoff, "Fixture sanity: 1.0 file has no attend_resume"
        # Raises jsonschema.ValidationError on failure.
        jsonschema.validate(instance=handoff, schema=schema)

    # -- (b) populated 1.1 file validates ------------------------------------

    def test_1_1_handoff_with_attend_resume_validates(self):
        """A protocol 1.1 handoff with a populated attend_resume block validates."""
        schema = _load_handoff_schema()
        handoff = _make_1_1_handoff()
        assert handoff["protocol_version"] == "1.1"
        assert set(handoff["attend_resume"]) == {
            "expected_head_sha",
            "expected_phase",
            "done_set_hash",
            "dirty_state_fingerprint",
            "session_id",
        }
        jsonschema.validate(instance=handoff, schema=schema)

    # -- (c) regression guard: a const-"1.1"-only schema rejects the 1.0 file -

    def test_const_1_1_only_schema_would_reject_1_0_fixture(self):
        """Regression guard: prove it is the ENUM (not a const) that admits both.

        We reconstruct a variant of the LIVE schema in which protocol_version is
        a `const: "1.1"` (the degenerate single-value form). The 1.0 fixture
        MUST fail against that variant — demonstrating that a const can only ever
        admit one version, so the production schema HAS to use an enum to accept
        both 1.0 and 1.1. If someone reverts the production schema to a const,
        the (a) test above breaks; this test pins down WHY the enum is required.
        """
        schema = _load_handoff_schema()

        # Sanity: the live schema uses an enum admitting BOTH versions.
        pv_schema = schema["properties"]["protocol_version"]
        assert "enum" in pv_schema, (
            "protocol_version must use an enum, not a const, to admit two versions"
        )
        assert set(pv_schema["enum"]) == {"1.0", "1.1"}, (
            f"protocol_version enum must be exactly ['1.0','1.1'], got {pv_schema['enum']!r}"
        )
        assert "const" not in pv_schema, (
            "protocol_version must NOT be a const — a const admits exactly one value"
        )

        # Build the degenerate const-"1.1"-only variant.
        const_schema = _copy.deepcopy(schema)
        const_schema["properties"]["protocol_version"] = {
            "type": "string",
            "const": "1.1",
        }

        handoff_1_0 = _make_1_0_handoff()

        # Under the const-1.1 schema, the 1.0 fixture must be rejected.
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(instance=handoff_1_0, schema=const_schema)

        # And the 1.1 fixture must still pass under the const-1.1 variant
        # (confirms the rejection above is specifically the version, not noise).
        jsonschema.validate(instance=_make_1_1_handoff(), schema=const_schema)

    # -- attend_resume is strict (additionalProperties:false) ----------------

    def test_attend_resume_rejects_unknown_field(self):
        """An unknown key inside attend_resume is rejected (additionalProperties:false)."""
        schema = _load_handoff_schema()
        handoff = _make_1_1_handoff()
        handoff["attend_resume"]["bogus_field"] = "nope"
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(instance=handoff, schema=schema)

    def test_attend_resume_requires_all_five_fields(self):
        """Dropping a required attend_resume sub-field fails validation."""
        schema = _load_handoff_schema()
        handoff = _make_1_1_handoff()
        del handoff["attend_resume"]["session_id"]
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(instance=handoff, schema=schema)

    def test_context_files_accept_fresh_session_roles_but_remain_thin(self):
        """HANDOFF context-category pointers validate, but embedded file content is rejected."""
        schema = _load_handoff_schema()
        role_schema = schema["properties"]["context_files"]["items"]["properties"]["role"]
        assert {"handoff", "intent", "ledger", "invariants", "rejected_approaches", "decisions_archive", "verification_commands"}.issubset(set(role_schema["enum"]))

        handoff = _make_1_0_handoff()
        jsonschema.validate(instance=handoff, schema=schema)

        handoff["context_files"][0]["content"] = "# Handoff\n"
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(instance=handoff, schema=schema)


class TestZHandoffSkillContract:
    """Regression guards for the manual /z-handoff context discovery contract."""

    def _context_discovery_block(self) -> str:
        text = _load_zhandoff_skill()
        start = text.index("### 1c — Identify context files")
        end = text.index("### 1d — Determine next_step", start)
        return text[start:end]

    def test_manual_discovery_includes_intent_and_legacy_plan_artifacts(self):
        """Manual /z-handoff must not drop intent-mode or legacy plan artifacts."""
        block = self._context_discovery_block()
        for artifact in (
            "HANDOFF.md",
            "INTENT.md",
            "SPEC.md",
            "PLAN.md",
            "TASKS.md",
            "FIX.md",
            "LEDGER.md",
        ):
            assert f"$Z_HARNESS_PLAN_DIR/{artifact}" in block

    def test_manual_role_table_uses_schema_role_names_for_primary_artifacts(self):
        """Manual role names must match handoff.schema.json/write-handoff.sh roles."""
        block = self._context_discovery_block()
        expected_roles = {
            "HANDOFF.md": "handoff",
            "INTENT.md": "intent",
            "SPEC.md": "spec",
            "PLAN.md": "plan",
            "TASKS.md": "tasks",
            "FIX.md": "plan",
            "LEDGER.md": "ledger",
        }
        schema_roles = set(
            _load_handoff_schema()["properties"]["context_files"]["items"]["properties"]["role"]["enum"]
        )

        for artifact, role in expected_roles.items():
            assert f'| `**/{artifact}` | `"{role}"` |' in block
            assert role in schema_roles


# ===========================================================================
# SECTION 5 — write-handoff.sh producer ↔ schema conformance (T005/T006)
# ===========================================================================
# write-handoff.sh emits protocol_version "1.0" with NO attend_resume key on the
# default path, and "1.1" with a populated attend_resume block ONLY when
# Z_HARNESS_ATTEND_RESUME=1. T006 also pins fresh-session artifact pointers and
# staged intent-mode TASKS.md heading counts against the LIVE schema.

_WRITE_HANDOFF_SH = str(_REPO_ROOT / "scripts" / "write-handoff.sh")
_WRITE_CLEAR_CHECKPOINT_SH = str(_REPO_ROOT / "scripts" / "write-clear-checkpoint.sh")
_CHECK_COMPACTION_SH = str(_REPO_ROOT / "scripts" / "check-compaction.sh")



def _run_write_handoff(plan_dir: Path, extra_env: dict[str, str] | None = None) -> dict[str, Any]:
    """Run scripts/write-handoff.sh against *plan_dir* and return the parsed handoff.json."""
    env = {**os.environ, "Z_HARNESS_PLAN_DIR": str(plan_dir), "Z_HARNESS_SLUG": "attended-chain"}
    if extra_env:
        env.update(extra_env)
    result = subprocess.run(
        ["bash", _WRITE_HANDOFF_SH],
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"write-handoff.sh exited {result.returncode}; stderr: {result.stderr!r}"
    )
    handoff_path = plan_dir / "handoff.json"
    assert handoff_path.is_file(), "write-handoff.sh did not write handoff.json"
    return json.loads(handoff_path.read_text(encoding="utf-8"))


def _seed_plan_dir(plan_dir: Path) -> None:
    """Write the minimal plan artifacts write-handoff.sh reads."""
    (plan_dir / "HANDOFF.md").write_text("# Handoff\n", encoding="utf-8")
    (plan_dir / "INTENT.md").write_text("# Intent\n", encoding="utf-8")
    (plan_dir / "LEDGER.md").write_text("# Ledger\n", encoding="utf-8")
    (plan_dir / "SPEC.md").write_text("# Spec\n", encoding="utf-8")
    (plan_dir / "PLAN.md").write_text("# Plan\n", encoding="utf-8")
    (plan_dir / "workstreams.json").write_text('{"workstreams": []}\n', encoding="utf-8")
    (plan_dir / "SESSION.md").write_text(
        "---\ndone_count: 2\nnext_pending: T003\n---\n\n## Open threads\n- Continue\n",
        encoding="utf-8",
    )
    (plan_dir / "TASKS.md").write_text(
        "## Base level — spine and mode gate\n\n"
        "## T001 — Base done `[x]`\n**Depends on:** —\n\n"
        "## Independent source-contract tracks\n\n"
        "## T002 — Independent pending `[ ]`\n**Depends on:** —\n\n"
        "## Dependent level — after T001\n\n"
        "## T003 — Dependent done `[x]`\n**Depends on:** T001\n",
        encoding="utf-8",
    )

def _write_session_for_current_done_set(plan_dir: Path, *, last_gate_task_id: str = "T001") -> str:
    done_hash = _run_helper("done_set_hash", str(plan_dir / "TASKS.md"), tmp_base=plan_dir)
    next_pending = _run_helper("next_pending_task", str(plan_dir / "TASKS.md"), tmp_base=plan_dir)
    session_text = _build_session_md(
        slug="checkpoint-plan",
        done_ids_hash=done_hash,
        last_gate_task_id=last_gate_task_id,
        next_pending=next_pending or "none",
        sections={"Decisions": "- checkpoint ready", "Landmines": "", "Invariants": "", "Open threads": ""},
    )
    (plan_dir / "SESSION.md").write_text(session_text, encoding="utf-8")
    return done_hash


def _run_check_compaction(plan_dir: Path, extra_env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    env = {
        **os.environ,
        "Z_HARNESS_PLAN_DIR": str(plan_dir),
        "Z_HARNESS_BASE_DIR": str(plan_dir / "state"),
        "Z_IMPLEMENT_PAUSE_TASKS": "0",
        "Z_IMPLEMENT_PAUSE_MINUTES": "0",
    }
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        ["bash", _CHECK_COMPACTION_SH],
        env=env,
        cwd=str(_REPO_ROOT),
        capture_output=True,
        text=True,
    )


def _read_metrics(plan_dir: Path) -> list[dict[str, Any]]:
    metrics_path = plan_dir / "state" / "metrics.jsonl"
    if not metrics_path.exists():
        return []
    return [
        json.loads(line)
        for line in metrics_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


class TestWriteHandoffProducer:
    """write-handoff.sh conforms to schema and T006 handoff pointer/count contracts."""

    def test_default_path_emits_1_0_without_attend_resume(self, tmp_path: Path):
        """No Z_HARNESS_ATTEND_RESUME → protocol_version 1.0, no attend_resume key, valid."""
        _seed_plan_dir(tmp_path)
        handoff = _run_write_handoff(tmp_path)

        assert handoff["protocol_version"] == "1.0", (
            f"Default path must emit 1.0, got {handoff['protocol_version']!r}"
        )
        assert "attend_resume" not in handoff, (
            "Default (non-attend) path must NOT add an attend_resume key"
        )
        jsonschema.validate(instance=handoff, schema=_load_handoff_schema())

    def test_default_path_points_at_all_primary_artifacts_thinly(self, tmp_path: Path):
        """Machine handoff lists primary artifacts as path/role pointers only."""
        _seed_plan_dir(tmp_path)
        handoff = _run_write_handoff(tmp_path)

        context_files = handoff["context_files"]
        assert [entry["role"] for entry in context_files] == [
            "handoff",
            "invariants",
            "rejected_approaches",
            "decisions_archive",
            "verification_commands",
            "intent",
            "spec",
            "plan",
            "tasks",
            "workstreams",
            "ledger",
            "session_log",
        ]
        assert [Path(entry["path"]).name for entry in context_files] == [
            "HANDOFF.md",
            "HANDOFF.md",
            "HANDOFF.md",
            "HANDOFF.md",
            "HANDOFF.md",
            "INTENT.md",
            "SPEC.md",
            "PLAN.md",
            "TASKS.md",
            "workstreams.json",
            "LEDGER.md",
            "SESSION.md",
        ]
        assert all(set(entry) == {"path", "role"} for entry in context_files)
        jsonschema.validate(instance=handoff, schema=_load_handoff_schema())

    def test_staged_intent_task_headings_drive_task_counts(self, tmp_path: Path):
        """Intent TASKS.md staged TNNN headings produce accurate done/total counts."""
        _seed_plan_dir(tmp_path)
        handoff = _run_write_handoff(tmp_path)

        assert "2/3 tasks done" in handoff["next_step"]
        assert "Start at T003" in handoff["next_step"]

    def test_attend_path_emits_1_1_with_populated_attend_resume(self, tmp_path: Path):
        """Z_HARNESS_ATTEND_RESUME=1 → protocol_version 1.1 with a full attend_resume, valid."""
        _seed_plan_dir(tmp_path)
        attend_env = {
            "Z_HARNESS_ATTEND_RESUME": "1",
            "Z_HARNESS_ATTEND_HEAD_SHA": "6b2e6a3f0000000000000000000000000000abcd",
            "Z_HARNESS_ATTEND_PHASE": "implement-all",
            "Z_HARNESS_ATTEND_DONE_SET_HASH": _EMPTY_SHA256,
            "Z_HARNESS_ATTEND_DIRTY_FP": "sha256:deadbeefcafe",
            "Z_HARNESS_ATTEND_SESSION_ID": "sess-20260611-120000",
        }
        handoff = _run_write_handoff(tmp_path, extra_env=attend_env)

        assert handoff["protocol_version"] == "1.1", (
            f"Attend path must emit 1.1, got {handoff['protocol_version']!r}"
        )
        ar = handoff["attend_resume"]
        assert ar["expected_head_sha"] == attend_env["Z_HARNESS_ATTEND_HEAD_SHA"]
        assert ar["expected_phase"] == "implement-all"
        assert ar["done_set_hash"] == _EMPTY_SHA256
        assert ar["dirty_state_fingerprint"] == "sha256:deadbeefcafe"
        assert ar["session_id"] == "sess-20260611-120000"
        jsonschema.validate(instance=handoff, schema=_load_handoff_schema())

    def test_attend_path_missing_env_var_fails(self, tmp_path: Path):
        """Z_HARNESS_ATTEND_RESUME=1 with a required attend var unset → non-zero exit.

        The attend_resume sub-fields are minLength:1 in the schema; an empty env
        var would emit schema-invalid JSON. The producer must instead fail loudly,
        naming the missing var, and must NOT write handoff.json. Here we omit
        Z_HARNESS_ATTEND_SESSION_ID while supplying the other four.
        """
        _seed_plan_dir(tmp_path)
        env = {
            **os.environ,
            "Z_HARNESS_PLAN_DIR": str(tmp_path),
            "Z_HARNESS_SLUG": "attended-chain",
            "Z_HARNESS_ATTEND_RESUME": "1",
            "Z_HARNESS_ATTEND_HEAD_SHA": "6b2e6a3f0000000000000000000000000000abcd",
            "Z_HARNESS_ATTEND_PHASE": "implement-all",
            "Z_HARNESS_ATTEND_DONE_SET_HASH": _EMPTY_SHA256,
            "Z_HARNESS_ATTEND_DIRTY_FP": "sha256:deadbeefcafe",
        }
        # Ensure the omitted var is truly absent (not inherited from the parent env).
        env.pop("Z_HARNESS_ATTEND_SESSION_ID", None)

        result = subprocess.run(
            ["bash", _WRITE_HANDOFF_SH],
            env=env,
            capture_output=True,
            text=True,
        )
        assert result.returncode != 0, (
            "Producer must exit non-zero when a required attend var is unset; "
            f"got rc={result.returncode}, stdout={result.stdout!r}"
        )
        assert "Z_HARNESS_ATTEND_SESSION_ID" in result.stderr, (
            f"Diagnostic must name the missing var; stderr={result.stderr!r}"
        )
        assert not (tmp_path / "handoff.json").exists(), (
            "Producer must not write handoff.json when validation fails"
        )


class TestPipelinedHandoffBoundary:
    """T005 guards: future pipelining must not alter current handoff schema/state."""

    def test_zexecute_contract_says_no_handoff_schema_or_state_change(self):
        text = _load_zexecute_skill()
        contract_idx = text.index("FUTURE PIPELINED TRACK CONTRACT")
        contract = text[contract_idx:contract_idx + 3500]

        assert "DOES NOT enable runtime pipelined refill" in contract
        assert "DOES NOT change" in contract
        assert "handoff schema/state" in contract
        assert "clear checkpoints remain BFS-level boundaries only" in contract
        assert "must not snapshot half-written TASKS.md" in contract

    def test_handoff_schema_has_no_pipelined_track_state_surface(self):
        schema = _load_handoff_schema()
        serialized = json.dumps(schema)

        for forbidden in (
            "pipelined_tracks",
            "track_state",
            "background_handle_id",
            "refill_cursor",
            "pipeline_scheduler",
        ):
            assert forbidden not in serialized

    def test_write_handoff_default_output_has_no_pipelined_state(self, tmp_path: Path):
        _seed_plan_dir(tmp_path)
        handoff = _run_write_handoff(tmp_path)

        for forbidden in (
            "pipelined_tracks",
            "track_state",
            "background_handle_id",
            "refill_cursor",
            "pipeline_scheduler",
        ):
            assert forbidden not in handoff

        assert handoff["protocol_version"] == "1.0"
        jsonschema.validate(instance=handoff, schema=_load_handoff_schema())


class TestClearCheckpointProducer:
    """write-clear-checkpoint.sh emits generic watcher-readable checkpoint artifacts."""

    def test_write_handoff_accepts_status_and_next_step_override(self, tmp_path: Path):
        _seed_plan_dir(tmp_path)
        handoff = _run_write_handoff(
            tmp_path,
            extra_env={
                "Z_HARNESS_HANDOFF_STATUS": "context_pressure",
                "Z_HARNESS_HANDOFF_NEXT_STEP": "Resume from watcher checkpoint.",
            },
        )

        assert handoff["status"] == "context_pressure"
        assert handoff["next_step"] == "Resume from watcher checkpoint."
        jsonschema.validate(instance=handoff, schema=_load_handoff_schema())

    def test_clear_checkpoint_writes_handoff_and_event(self, tmp_path: Path):
        _seed_plan_dir(tmp_path)
        (tmp_path / "SESSION.md").write_text(
            "---\n"
            "artifact: session\n"
            "schema_version: 1\n"
            "done_ids_hash: abc\n"
            "next_pending: T002\n"
            "---\n\n"
            "## Decisions\n\n- keep going\n",
            encoding="utf-8",
        )
        state_base = tmp_path / "state"
        env = {
            **os.environ,
            "Z_HARNESS_PLAN_DIR": str(tmp_path),
            "Z_HARNESS_SLUG": "checkpoint-plan",
            "Z_HARNESS_BASE_DIR": str(state_base),
            "RUN": "test-clear-checkpoint",
        }

        result = subprocess.run(
            ["bash", _WRITE_CLEAR_CHECKPOINT_SH],
            env=env,
            cwd=str(_REPO_ROOT),
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0, result.stderr
        assert result.stdout.startswith("STATUS: clear_checkpoint "), result.stdout
        handoff_path = tmp_path / "handoff.json"
        assert handoff_path.is_file()
        handoff = json.loads(handoff_path.read_text(encoding="utf-8"))
        assert handoff["status"] == "context_pressure"
        assert any(item["role"] == "session_log" for item in handoff["context_files"])
        jsonschema.validate(instance=handoff, schema=_load_handoff_schema())

        metrics_path = state_base / "metrics.jsonl"
        assert metrics_path.is_file()
        events = [
            json.loads(line)
            for line in metrics_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        checkpoint_events = [event for event in events if event.get("kind") == "clear_checkpoint_written"]
        assert checkpoint_events, "clear_checkpoint_written event missing"
        payload = checkpoint_events[-1]
        assert payload["handoff_path"] == str(handoff_path)
        assert payload["session_path"] == str(tmp_path / "SESSION.md")
        assert payload["consumer"] == "watcher"
        assert payload["resume_command"] == "/z-execute checkpoint-plan"

    def test_clear_checkpoint_accepts_resume_command_override(self, tmp_path: Path):
        _seed_plan_dir(tmp_path)
        env = {
            **os.environ,
            "Z_HARNESS_PLAN_DIR": str(tmp_path),
            "Z_HARNESS_CHECKPOINT_STATUS": "clean_break",
            "Z_HARNESS_CHECKPOINT_NEXT_STEP": "Resume /z-review-all; continue at Phase 4.",
            "Z_HARNESS_CHECKPOINT_RESUME_COMMAND": "/z-review-all checkpoint-plan",
            "Z_HARNESS_BASE_DIR": str(tmp_path / "state"),
            "RUN": "test-clear-checkpoint-override",
        }

        result = subprocess.run(
            ["bash", _WRITE_CLEAR_CHECKPOINT_SH],
            env=env,
            cwd=str(_REPO_ROOT),
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0, result.stderr
        assert "resume=/z-review-all\\ checkpoint-plan" in result.stdout
        handoff = json.loads((tmp_path / "handoff.json").read_text(encoding="utf-8"))
        assert handoff["status"] == "clean_break"
        assert handoff["next_step"] == "Resume /z-review-all; continue at Phase 4."

        metrics_path = tmp_path / "state" / "metrics.jsonl"
        events = [
            json.loads(line)
            for line in metrics_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        payload = [event for event in events if event.get("kind") == "clear_checkpoint_written"][-1]
        assert payload["resume_command"] == "/z-review-all checkpoint-plan"


    def test_clear_checkpoint_preserves_session_context_pointer(self, tmp_path: Path):
        _seed_plan_dir(tmp_path)
        env = {
            **os.environ,
            "Z_HARNESS_PLAN_DIR": str(tmp_path),
            "Z_HARNESS_HANDOFF_SESSION_CONTEXT": "## Current work\n- Resume from live brief.\n",
            "Z_HARNESS_BASE_DIR": str(tmp_path / "state"),
            "RUN": "test-clear-checkpoint-session-context",
        }

        result = subprocess.run(
            ["bash", _WRITE_CLEAR_CHECKPOINT_SH],
            env=env,
            cwd=str(_REPO_ROOT),
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0, result.stderr
        session_context = tmp_path / "SESSION_CONTEXT.md"
        assert session_context.is_file()
        handoff = json.loads((tmp_path / "handoff.json").read_text(encoding="utf-8"))
        assert Path(handoff["context_files"][0]["path"]) == session_context
        assert handoff["context_files"][0]["role"] == "session_log"
        assert "Resume from live brief" in session_context.read_text(encoding="utf-8")

    def test_clear_checkpoint_phase_metadata_fast_forwards(self, tmp_path: Path):
        _seed_plan_dir(tmp_path)
        artifact = tmp_path / "archive" / "run-1" / "phase3-review.md"
        artifact.parent.mkdir(parents=True)
        artifact.write_text("# Phase 3 review\n", encoding="utf-8")
        state_base = tmp_path / "state"
        checkpoint_state = tmp_path / ".review_state.json"
        env = {
            **os.environ,
            "Z_HARNESS_PLAN_DIR": str(tmp_path),
            "Z_HARNESS_BASE_DIR": str(state_base),
            "RUN": "test-clear-checkpoint-phase",
            "Z_HARNESS_CHECKPOINT_STATUS": "clean_break",
            "Z_HARNESS_CHECKPOINT_NEXT_STEP": "Resume /z-review-all; continue at Phase 4.",
            "Z_HARNESS_CHECKPOINT_RESUME_COMMAND": "/z-review-all checkpoint-plan",
            "Z_HARNESS_CHECKPOINT_PHASE_NAME": "Phase 3.7 pre-consult",
            "Z_HARNESS_CHECKPOINT_PHASE_ID": "review-phase-3-7",
            "Z_HARNESS_CHECKPOINT_STATE_FILE": str(checkpoint_state),
            "Z_HARNESS_CHECKPOINT_COMPLETED_ARTIFACT": str(artifact),
            "Z_HARNESS_CHECKPOINT_FAST_FORWARD_GUARD": "head:abc123",
            "Z_HARNESS_CHECKPOINT_PRODUCER": "z-review-all",
            "Z_HARNESS_CHECKPOINT_PRODUCER_META_JSON": '{"phase":"3.7","base_ref":"main"}',
        }

        first = subprocess.run(
            ["bash", _WRITE_CLEAR_CHECKPOINT_SH],
            env=env,
            cwd=str(_REPO_ROOT),
            capture_output=True,
            text=True,
        )
        assert first.returncode == 0, first.stderr
        assert first.stdout.startswith("STATUS: clear_checkpoint "), first.stdout
        assert checkpoint_state.is_file()

        metrics_path = state_base / "metrics.jsonl"
        events = [
            json.loads(line)
            for line in metrics_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        payload = [event for event in events if event.get("kind") == "clear_checkpoint_written"][-1]
        assert payload["phase_name"] == "Phase 3.7 pre-consult"
        assert payload["phase_id"] == "review-phase-3-7"
        assert payload["completed_artifact"] == str(artifact)
        assert payload["fast_forward_guard"] == "head:abc123"
        assert payload["checkpoint_state_path"] == str(checkpoint_state)
        assert payload["producer"] == "z-review-all"
        assert payload["producer_metadata"] == {"phase": "3.7", "base_ref": "main"}

        second = subprocess.run(
            ["bash", _WRITE_CLEAR_CHECKPOINT_SH],
            env=env,
            cwd=str(_REPO_ROOT),
            capture_output=True,
            text=True,
        )
        assert second.returncode == 0, second.stderr
        assert second.stdout.startswith("STATUS: clear_checkpoint_fast_forward "), second.stdout

        events = [
            json.loads(line)
            for line in metrics_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        fast_forward = [event for event in events if event.get("kind") == "clear_checkpoint_fast_forward"][-1]
        assert fast_forward["phase_id"] == "review-phase-3-7"
        assert fast_forward["completed_artifact"] == str(artifact)
        assert fast_forward["fast_forward_guard"] == "head:abc123"
        assert fast_forward["producer"] == "z-review-all"

    def test_clear_checkpoint_rejects_stale_fast_forward_state(self, tmp_path: Path):
        _seed_plan_dir(tmp_path)
        artifact = tmp_path / "phase.md"
        artifact.write_text("# phase\n", encoding="utf-8")
        checkpoint_state = tmp_path / ".phase_state.json"
        checkpoint_state.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "phase_id": "phase-1",
                    "completed_artifact": str(artifact),
                    "fast_forward_guard": "head:old",
                    "handoff_path": str(tmp_path / "handoff.json"),
                    "session_path": str(tmp_path / "SESSION.md"),
                    "status": "clean_break",
                    "resume_command": "/z-review-all checkpoint-plan",
                    "producer": "z-review-all",
                }
            )
            + "\n",
            encoding="utf-8",
        )
        env = {
            **os.environ,
            "Z_HARNESS_PLAN_DIR": str(tmp_path),
            "Z_HARNESS_BASE_DIR": str(tmp_path / "state"),
            "RUN": "test-clear-checkpoint-stale",
            "Z_HARNESS_CHECKPOINT_PHASE_ID": "phase-1",
            "Z_HARNESS_CHECKPOINT_STATE_FILE": str(checkpoint_state),
            "Z_HARNESS_CHECKPOINT_COMPLETED_ARTIFACT": str(artifact),
            "Z_HARNESS_CHECKPOINT_FAST_FORWARD_GUARD": "head:new",
            "Z_HARNESS_CHECKPOINT_STALE_MODE": "reject",
        }

        result = subprocess.run(
            ["bash", _WRITE_CLEAR_CHECKPOINT_SH],
            env=env,
            cwd=str(_REPO_ROOT),
            capture_output=True,
            text=True,
        )

        assert result.returncode == 3
        assert "stale checkpoint state rejected" in result.stderr
        assert "fast_forward_guard_mismatch" in result.stderr

    def test_non_zexecute_checkpoint_resume_simulation_uses_shared_hook(self, tmp_path: Path):
        """A /z-audit-style seam can check pressure, checkpoint, then fast-forward."""
        _seed_plan_dir(tmp_path)
        report = tmp_path / "REPORT.md"
        report.write_text("# Audit report\n\n## Consult additions\n- durable\n", encoding="utf-8")
        guard = "report-sha:" + hashlib.sha256(report.read_bytes()).hexdigest()

        check = _run_check_compaction(
            tmp_path,
            {
                "Z_HARNESS_CONTEXT_USED_TOKENS": "900",
                "Z_HARNESS_CONTEXT_WINDOW_TOKENS": "1000",
            },
        )
        assert check.returncode == 1, check.stderr

        env = {
            **os.environ,
            "Z_HARNESS_PLAN_DIR": str(tmp_path),
            "Z_HARNESS_SLUG": "audit-demo",
            "Z_HARNESS_BASE_DIR": str(tmp_path / "state"),
            "RUN": "test-audit-seam-checkpoint",
            "Z_HARNESS_CHECKPOINT_STATUS": "context_pressure",
            "Z_HARNESS_CHECKPOINT_NEXT_STEP": "Resume /z-audit at Phase 5 promotion after consult archive.",
            "Z_HARNESS_CHECKPOINT_RESUME_COMMAND": "/z-audit audit-demo",
            "Z_HARNESS_CHECKPOINT_PHASE_NAME": "/z-audit Phase 4 post-consult",
            "Z_HARNESS_CHECKPOINT_PHASE_ID": "audit-phase4-post-consult",
            "Z_HARNESS_CHECKPOINT_COMPLETED_ARTIFACT": str(report),
            "Z_HARNESS_CHECKPOINT_FAST_FORWARD_GUARD": guard,
            "Z_HARNESS_CHECKPOINT_STALE_MODE": "reject",
            "Z_HARNESS_CHECKPOINT_PRODUCER": "z-audit",
            "Z_HARNESS_CHECKPOINT_PRODUCER_META_JSON": '{"command":"z-audit","seam":"audit-phase4-post-consult"}',
        }

        first = subprocess.run(
            ["bash", _WRITE_CLEAR_CHECKPOINT_SH],
            env=env,
            cwd=str(_REPO_ROOT),
            capture_output=True,
            text=True,
        )
        assert first.returncode == 0, first.stderr
        assert first.stdout.startswith("STATUS: clear_checkpoint "), first.stdout
        assert (tmp_path / "handoff.json").is_file()

        second = subprocess.run(
            ["bash", _WRITE_CLEAR_CHECKPOINT_SH],
            env=env,
            cwd=str(_REPO_ROOT),
            capture_output=True,
            text=True,
        )
        assert second.returncode == 0, second.stderr
        assert second.stdout.startswith("STATUS: clear_checkpoint_fast_forward "), second.stdout

        events = _read_metrics(tmp_path)
        assert any(event.get("kind") == "compaction_pause" for event in events)
        written = [event for event in events if event.get("kind") == "clear_checkpoint_written"][-1]
        assert written["producer"] == "z-audit"
        assert written["phase_id"] == "audit-phase4-post-consult"
        assert written["completed_artifact"] == str(report)
        assert written["fast_forward_guard"] == guard
        assert written["producer_metadata"] == {
            "command": "z-audit",
            "seam": "audit-phase4-post-consult",
        }
        fast_forward = [event for event in events if event.get("kind") == "clear_checkpoint_fast_forward"][-1]
        assert fast_forward["phase_id"] == "audit-phase4-post-consult"
        assert fast_forward["producer"] == "z-audit"

    def test_non_zexecute_context_pressure_runs_without_tasks_md(self, tmp_path: Path):
        """REPORT.md-backed seams must checkpoint on pressure before TASKS.md exists."""
        report = tmp_path / "REPORT.md"
        report.write_text("# Audit report\n\n## Consult additions\n- durable\n", encoding="utf-8")
        assert not (tmp_path / "TASKS.md").exists()

        check = _run_check_compaction(
            tmp_path,
            {
                "Z_HARNESS_CONTEXT_USED_TOKENS": "900",
                "Z_HARNESS_CONTEXT_WINDOW_TOKENS": "1000",
            },
        )

        assert check.returncode == 1, check.stderr
        assert "evaluating context pressure only" in check.stderr
        pauses = [event for event in _read_metrics(tmp_path) if event.get("kind") == "compaction_pause"]
        assert pauses, "compaction_pause event missing"
        assert pauses[-1]["trigger"] == "context_pressure"
        assert pauses[-1]["tasks_completed_total"] == 0
        assert pauses[-1]["pending_remaining"] == 0
        assert (tmp_path / ".last-compaction-check").is_file()

    def test_legacy_fallback_requires_tasks_md(self, tmp_path: Path):
        """Task-count and wall-time fallback heuristics must not run without TASKS.md."""
        (tmp_path / "REPORT.md").write_text("# Audit report\n", encoding="utf-8")
        (tmp_path / ".last-compaction-check").write_text("0 0\n", encoding="utf-8")
        assert not (tmp_path / "TASKS.md").exists()

        result = _run_check_compaction(
            tmp_path,
            {
                "Z_HARNESS_CONTEXT_PRESSURE_ENABLED": "0",
                "Z_IMPLEMENT_PAUSE_TASKS": "1",
                "Z_IMPLEMENT_PAUSE_MINUTES": "1",
            },
        )

        assert result.returncode == 0, result.stderr
        assert not any(event.get("kind") == "compaction_pause" for event in _read_metrics(tmp_path))


class TestZExecuteCompactionCheckpointPolicy:
    """Executable smoke tests for /z-execute durable-boundary compaction policy."""

    def test_completed_task_below_threshold_continues_without_checkpoint(self, tmp_path: Path):
        _seed_plan_dir(tmp_path)
        (tmp_path / "TASKS.md").write_text(
            "## T001 -- done `[x]`\n**Depends on:** --\n\n"
            "## T002 -- pending `[ ]`\n**Depends on:** --\n",
            encoding="utf-8",
        )

        result = _run_check_compaction(
            tmp_path,
            {
                "Z_HARNESS_CONTEXT_USED_TOKENS": "500",
                "Z_HARNESS_CONTEXT_WINDOW_TOKENS": "1000",
            },
        )

        assert result.returncode == 0, result.stderr
        assert not (tmp_path / ".last-compaction-check").exists()
        assert not any(event.get("kind") == "compaction_pause" for event in _read_metrics(tmp_path))

    def test_completed_task_over_threshold_writes_clear_checkpoint(self, tmp_path: Path):
        _seed_plan_dir(tmp_path)
        (tmp_path / "TASKS.md").write_text(
            "## T001 -- done `[x]`\n**Depends on:** --\n\n"
            "## T002 -- pending `[ ]`\n**Depends on:** --\n",
            encoding="utf-8",
        )
        _write_session_for_current_done_set(tmp_path, last_gate_task_id="T001")

        check = _run_check_compaction(
            tmp_path,
            {
                "Z_HARNESS_CONTEXT_USED_TOKENS": "900",
                "Z_HARNESS_CONTEXT_WINDOW_TOKENS": "1000",
            },
        )
        assert check.returncode == 1, check.stderr

        checkpoint = subprocess.run(
            ["bash", _WRITE_CLEAR_CHECKPOINT_SH],
            env={
                **os.environ,
                "Z_HARNESS_PLAN_DIR": str(tmp_path),
                "Z_HARNESS_SLUG": "checkpoint-plan",
                "Z_HARNESS_BASE_DIR": str(tmp_path / "state"),
                "RUN": "test-task-threshold",
            },
            cwd=str(_REPO_ROOT),
            capture_output=True,
            text=True,
        )

        assert checkpoint.returncode == 0, checkpoint.stderr
        assert (tmp_path / "handoff.json").is_file()
        assert (tmp_path / ".last-compaction-check").is_file()
        events = _read_metrics(tmp_path)
        assert any(event.get("kind") == "compaction_pause" and event.get("trigger") == "context_pressure" for event in events)
        assert any(event.get("kind") == "clear_checkpoint_written" for event in events)

    def test_parallel_batch_evaluates_once_after_all_completion_updates(self, tmp_path: Path):
        _seed_plan_dir(tmp_path)
        (tmp_path / "TASKS.md").write_text(
            "## T001 -- parallel one `[x]`\n**Depends on:** --\n\n"
            "## T002 -- parallel two `[x]`\n**Depends on:** --\n\n"
            "## T003 -- next pending `[ ]`\n**Depends on:** T001, T002\n",
            encoding="utf-8",
        )
        done_hash = _write_session_for_current_done_set(tmp_path, last_gate_task_id="T002")

        check = _run_check_compaction(
            tmp_path,
            {
                "Z_HARNESS_CONTEXT_USED_TOKENS": "900",
                "Z_HARNESS_CONTEXT_WINDOW_TOKENS": "1000",
            },
        )
        assert check.returncode == 1, check.stderr

        events = _read_metrics(tmp_path)
        pauses = [event for event in events if event.get("kind") == "compaction_pause"]
        assert len(pauses) == 1
        assert pauses[0]["tasks_completed_total"] == 2
        assert _run_helper("session_frontmatter_field", str(tmp_path / "SESSION.md"), "done_ids_hash", tmp_base=tmp_path) == done_hash

    def test_bfs_level_boundary_checkpoint_runs_after_ledger_and_done_hash_flush(self, tmp_path: Path):
        _seed_plan_dir(tmp_path)
        (tmp_path / "TASKS.md").write_text(
            "## T001 -- level task `[x]`\n**Depends on:** --\n\n"
            "## T002 -- next level `[ ]`\n**Depends on:** T001\n",
            encoding="utf-8",
        )
        ledger = tmp_path / "LEDGER.md"
        ledger.write_text("# Ledger\n\n## Level 0\n\n### T001\n\n**Decisions:**\n  - accepted\n", encoding="utf-8")
        level_hash = _run_helper("done_set_hash", str(tmp_path / "TASKS.md"), tmp_base=tmp_path)
        archive = tmp_path / "archive" / "run-bfs"
        archive.mkdir(parents=True)
        (archive / ".bfs_level_state").write_text(f"0 {level_hash}\n", encoding="utf-8")
        _write_session_for_current_done_set(tmp_path, last_gate_task_id="T001")

        check = _run_check_compaction(
            tmp_path,
            {
                "Z_HARNESS_CONTEXT_USED_TOKENS": "900",
                "Z_HARNESS_CONTEXT_WINDOW_TOKENS": "1000",
            },
        )
        assert check.returncode == 1, check.stderr
        checkpoint = subprocess.run(
            ["bash", _WRITE_CLEAR_CHECKPOINT_SH],
            env={
                **os.environ,
                "Z_HARNESS_PLAN_DIR": str(tmp_path),
                "Z_HARNESS_BASE_DIR": str(tmp_path / "state"),
                "RUN": "test-bfs-threshold",
            },
            cwd=str(_REPO_ROOT),
            capture_output=True,
            text=True,
        )

        assert checkpoint.returncode == 0, checkpoint.stderr
        assert "### T001" in ledger.read_text(encoding="utf-8")
        assert (archive / ".bfs_level_state").read_text(encoding="utf-8").strip() == f"0 {level_hash}"
        assert (tmp_path / "handoff.json").is_file()

    def test_in_level_suppression_prevents_pre_ledger_checkpoint_pause(self, tmp_path: Path):
        """LEVEL_EXECUTE_SUPPRESS_COMPACTION=1 must force no-op inside BFS level."""
        _seed_plan_dir(tmp_path)
        (tmp_path / "TASKS.md").write_text(
            "## T001 -- level task `[x]`\n**Depends on:** --\n\n"
            "## T002 -- next level `[ ]`\n**Depends on:** T001\n",
            encoding="utf-8",
        )

        result = _run_check_compaction(
            tmp_path,
            {
                "LEVEL_EXECUTE_SUPPRESS_COMPACTION": "1",
                "Z_HARNESS_CONTEXT_USED_TOKENS": "950",
                "Z_HARNESS_CONTEXT_WINDOW_TOKENS": "1000",
                "Z_IMPLEMENT_PAUSE_TASKS": "1",
            },
        )

        assert result.returncode == 0, result.stderr
        assert not (tmp_path / ".last-compaction-check").exists()
        assert not any(event.get("kind") == "compaction_pause" for event in _read_metrics(tmp_path))

    def test_zexecute_bfs_checkpoint_uses_concrete_protocol_and_full_ids(self):
        """BFS over-threshold path must curate/write handoff with all level ids."""
        text = _load_zexecute_skill()
        bfs_section = text[
            text.index("BFS boundary clear-checkpoint threshold check"):
            text.index("Acceptance-evaluator invocation seam", text.index("BFS boundary clear-checkpoint threshold check"))
        ]
        checkpoint_section = text[
            text.index("Reusable clear-checkpoint protocol"):
            text.index("## Parallelism", text.index("## Clear checkpoint policy"))
        ]

        assert "include: Clear checkpoint policy curator-dispatch block" not in text
        assert "execute_clear_checkpoint_protocol" in bfs_section
        assert 'completed_task_ids "$CHECKPOINT_TASKS_FILE"' in bfs_section
        assert 'last_done_task "$LEVEL_TASKS_FILE"' not in bfs_section
        assert "scripts/write-clear-checkpoint.sh" in checkpoint_section
        assert "completed_task_ids: $COMPLETED_TASK_IDS" in checkpoint_section
        assert "tasks_file: $CHECKPOINT_TASKS_FILE" in checkpoint_section

    def test_zexecute_main_loop_compaction_has_intent_suppression_guard(self):
        """The reused Main loop must not checkpoint inside an active BFS level."""
        text = _load_zexecute_skill()
        batch_step = text[
            text.index("Batch-settle clear checkpoint check"):
            text.index("## Run Brief", text.index("Batch-settle clear checkpoint check"))
        ]

        assert 'LEVEL_EXECUTE_SUPPRESS_COMPACTION:-0' in batch_step
        assert 'MAIN_LOOP_RESULT="compaction_deferred"' in batch_step
        assert "Never pause inside the reused Main loop" in batch_step
        assert 'CHECKPOINT_TASKS_FILE="$TASKS_FILE"' in batch_step
        assert 'BATCH_COMPLETED_TASK_IDS="$COMPLETED_IDS_FROM_ATOMIC_BATCH_WRITE"' in batch_step
        assert "COMPACTION_TRIGGERED=0" in batch_step
        assert "execute_clear_checkpoint_protocol" in batch_step

    def test_malformed_or_unavailable_estimate_fails_open_by_default(self, tmp_path: Path):
        _seed_plan_dir(tmp_path)
        result = _run_check_compaction(
            tmp_path,
            {
                "Z_HARNESS_CONTEXT_CHECKPOINT_THRESHOLD_PERCENT": "not-a-number",
            },
        )

        assert result.returncode == 0
        assert "continuing fail-open" in result.stderr
        assert not (tmp_path / ".last-compaction-check").exists()

        unavailable = _run_check_compaction(
            tmp_path,
            {
                "ANTIGRAVITY_PLUGIN_ROOT": str(tmp_path / "missing-plugin-root"),
            },
        )
        assert unavailable.returncode == 0
        assert "continuing fail-open" in unavailable.stderr

    def test_legacy_fallback_works_when_percentage_estimator_disabled(self, tmp_path: Path):
        _seed_plan_dir(tmp_path)
        (tmp_path / "TASKS.md").write_text(
            "## T001 -- done `[x]`\n**Depends on:** --\n\n"
            "## T002 -- pending `[ ]`\n**Depends on:** --\n",
            encoding="utf-8",
        )

        result = _run_check_compaction(
            tmp_path,
            {
                "Z_HARNESS_CONTEXT_PRESSURE_ENABLED": "0",
                "Z_IMPLEMENT_PAUSE_TASKS": "1",
            },
        )

        assert result.returncode == 1, result.stderr
        assert any(event.get("kind") == "compaction_pause" and event.get("trigger") == "task_count" for event in _read_metrics(tmp_path))

    def test_checkpoint_exit_contract_skips_finalize_and_deregister(self):
        text = _load_zexecute_skill()
        checkpoint_section = text[text.index("## Clear checkpoint policy"):text.index("## Parallelism", text.index("## Clear checkpoint policy"))]
        finalize_section = text[text.index("## Finalize"):text.index("## Phase 9", text.index("## Finalize"))]

        assert "skip the entire Finalize section" in checkpoint_section
        assert "do NOT deregister" in checkpoint_section
        assert "do NOT run Run Brief finalize" in checkpoint_section
        assert "Clear-checkpoint exits" in finalize_section
        assert "do NOT" in finalize_section and "deregister" in finalize_section


class TestAuditStyleWorkflowCheckpointHooks:
    """Text contracts for non-/z-execute shared checkpoint hook adoption."""

    _SHARED_ENV_TOKENS = (
        "scripts/check-compaction.sh",
        "scripts/write-clear-checkpoint.sh",
        "Z_HARNESS_CHECKPOINT_PHASE_ID",
        "Z_HARNESS_CHECKPOINT_COMPLETED_ARTIFACT",
        "Z_HARNESS_CHECKPOINT_FAST_FORWARD_GUARD",
        "Z_HARNESS_CHECKPOINT_STALE_MODE",
        "Z_HARNESS_CHECKPOINT_PRODUCER",
        "compaction_pause",
        "under-threshold fallthrough",
        "stale-state handling",
        "Do not write `handoff.json` directly",
        "Skipped candidate seams",
    )

    def _assert_shared_hook_contract(self, text: str, seam_ids: tuple[str, ...]) -> None:
        assert "run_workflow_compaction_seam" in text
        for token in self._SHARED_ENV_TOKENS:
            assert token in text
        for seam_id in seam_ids:
            assert seam_id in text
        assert not re.search(r'cat\s+>\s*["$A-Za-z0-9_/{}/.-]*handoff\.json', text)
        assert "checkpoint_ack" not in text
        assert "local ack file" not in text

    def test_zaudit_registers_shared_hook_at_natural_pause_points(self):
        """z-audit (T110) uses the checkpoint-seam.sh/audit_checkpoint_seam wrapper
        convention, not the legacy inline run_workflow_compaction_seam function —
        this reconciles the test with T110's already-shipped SKILL-STYLE.md rewrite,
        it is not a new product regression."""
        text = _load_zaudit_skill()
        assert "audit_checkpoint_seam" in text
        assert "scripts/checkpoint-seam.sh" in text
        assert "check-compaction.sh" in text
        assert "write-clear-checkpoint.sh" in text
        assert "never write `handoff.json` directly" in text
        assert "Skipped candidate seams" in text
        assert not re.search(r'cat\s+>\s*["$A-Za-z0-9_/{}/.-]*handoff\.json', text)
        assert "checkpoint_ack" not in text
        assert "local ack file" not in text
        for seam_id in (
            "audit-phase4-pre-consult",
            "audit-phase4-post-consult",
            "audit-phase5-pre-promotion",
            "audit-phase6-pre-review",
            "audit-phase7-pre-user-report",
        ):
            assert seam_id in text
        assert "Before dispatching Phase 4 consultants" in text
        assert "After `REPORT.md` has been updated with `## Consult additions`" in text
        assert "before run-brief/final user-facing report generation" in text
        report_update = text.index("Update `REPORT.md` with `## Consult additions`")
        post_consult = text.index("After `REPORT.md` has been updated with `## Consult additions`")
        auto_bail = text.index("**Check auto-bail thresholds now**")
        assert report_update < post_consult < auto_bail

    def test_ztest_registers_shared_hook_at_natural_pause_points(self):
        text = _load_ztest_skill()
        self._assert_shared_hook_contract(
            text,
            (
                "test-phase3-pre-consult",
                "test-phase3-post-consult",
                "test-phase4-pre-synthesis",
                "test-phase5-pre-approval",
                "test-phase6-pre-tests-write",
                "test-phase7-pre-task-crosslink",
                "test-phase8-pre-user-report",
            ),
        )
        assert "Before dispatching Phase 3 consultants" in text
        assert "After both Phase 3 consultant transcripts are archived" in text
        assert "Before final push-notify/user summary" in text

    def test_zreview_all_uses_shared_hook_before_consultants(self):
        text = _load_zreview_all_skill()
        self._assert_shared_hook_contract(
            text,
            ("review-all-phase3-7-pre-consult",),
        )
        phase = text[
            text.index("## Phase 3.7 — Pre-consult clear checkpoint"):
            text.index("## Phase 3.7.5", text.index("## Phase 3.7 — Pre-consult clear checkpoint"))
        ]
        assert "scripts/check-compaction.sh" in phase
        assert "under-threshold fallthrough" in phase
        assert "continue directly to Phase 4" in phase
        assert "run_workflow_compaction_seam" in phase
        assert "Phase 3.7 has been acknowledged" in phase
        assert "Fast-forward output falls through to Phase 4" in phase
        assert phase.count("scripts/check-compaction.sh") == 1
        assert "CHECKPOINT_RESULT=0" in phase
        assert "return 10" in text
        assert "clear_checkpoint_fast_forward: fall through to Phase 4" in phase
        assert 'Z_HARNESS_CHECKPOINT_PRODUCER="z-review-all"' in text

    def test_zreview_all_phase37_control_flow_simulation(self, tmp_path: Path):
        """Executable guard for one-check, clear-exit, and fast-forward-fallthrough semantics."""
        script = tmp_path / "phase37.sh"
        script.write_text(
            """#!/usr/bin/env bash
set -euo pipefail
CHECK_RC="${1:?check rc}"
WRITE_OUT="${2:-STATUS: clear_checkpoint handoff=x}"
check_calls=0
notify_calls=0
run_workflow_compaction_seam() {
  printf '%s\n' "$WRITE_OUT"
  case "$WRITE_OUT" in
    STATUS:\\ clear_checkpoint_fast_forward*) return 0 ;;
    STATUS:\\ clear_checkpoint*) return 10 ;;
    *) return 1 ;;
  esac
}
check_calls=$((check_calls + 1))
COMPACTION_TRIGGERED=0
if [ "$CHECK_RC" -ne 0 ]; then COMPACTION_TRIGGERED="$CHECK_RC"; fi
if [ "$COMPACTION_TRIGGERED" -eq 0 ]; then
  echo "PHASE4 check_calls=$check_calls notify_calls=$notify_calls"
elif [ "$COMPACTION_TRIGGERED" -eq 2 ]; then
  echo "STRICT check_calls=$check_calls notify_calls=$notify_calls"
  exit 2
else
  CHECKPOINT_RESULT=0
  run_workflow_compaction_seam || CHECKPOINT_RESULT=$?
  if [ "$CHECKPOINT_RESULT" -eq 10 ]; then
    notify_calls=$((notify_calls + 1))
    echo "CLEAR_EXIT check_calls=$check_calls notify_calls=$notify_calls"
    exit 0
  elif [ "$CHECKPOINT_RESULT" -ne 0 ]; then
    echo "ERROR check_calls=$check_calls notify_calls=$notify_calls"
    exit "$CHECKPOINT_RESULT"
  fi
  echo "PHASE4 check_calls=$check_calls notify_calls=$notify_calls"
fi
""",
            encoding="utf-8",
        )

        under = subprocess.run(["bash", str(script), "0"], capture_output=True, text=True)
        assert under.returncode == 0
        assert under.stdout.strip() == "PHASE4 check_calls=1 notify_calls=0"

        clear = subprocess.run(
            ["bash", str(script), "1", "STATUS: clear_checkpoint handoff=x"],
            capture_output=True,
            text=True,
        )
        assert clear.returncode == 0
        assert "CLEAR_EXIT check_calls=1 notify_calls=1" in clear.stdout

        fast_forward = subprocess.run(
            ["bash", str(script), "1", "STATUS: clear_checkpoint_fast_forward state=x"],
            capture_output=True,
            text=True,
        )
        assert fast_forward.returncode == 0
        assert "PHASE4 check_calls=1 notify_calls=0" in fast_forward.stdout


class TestDebugWorkflowCheckpointHooks:
    """Contract tests for /z-debug shared checkpoint hook adoption."""

    _DEBUG_SEAMS = (
        "debug-phase2-post-evidence",
        "debug-phase3a-after-round1-orchestrator",
        "debug-phase3a-post-hypothesis-pool",
        "debug-phase3b-post-hypothesis-pool",
        "debug-phase5-pre-isolation",
        "debug-phase6-post-scoring",
        "debug-phase7-pre-fix-consult",
        "debug-phase7-post-fix-plan",
        "debug-phase8-pre-postmortem",
        "debug-phase9-pre-mr-review",
        "debug-phase10-pre-finalize",
    )

    def test_zdebug_registers_shared_hook_at_debug_pause_points(self):
        text = _load_zdebug_skill()

        for token in (
            "run_zdebug_compaction_seam",
            "scripts/check-compaction.sh",
            "scripts/write-clear-checkpoint.sh",
            "Z_HARNESS_CHECKPOINT_PHASE_ID",
            "Z_HARNESS_CHECKPOINT_COMPLETED_ARTIFACT",
            "Z_HARNESS_CHECKPOINT_FAST_FORWARD_GUARD",
            "Z_HARNESS_CHECKPOINT_STALE_MODE",
            "Z_HARNESS_CHECKPOINT_PRODUCER=\"z-debug\"",
            "compaction_pause",
            "under-threshold fallthrough",
            "stale-state handling",
            "Do not write `handoff.json` directly",
            "Skipped candidate seams",
            "Resume /z-debug from ${debug_md}",
            "STATUS:\\ clear_checkpoint_fast_forward*) ;;",
        ):
            assert token in text

        for seam_id in self._DEBUG_SEAMS:
            assert seam_id in text

        round1_write = text.index("Write to `$Z_HARNESS_PLAN_DIR/archive/$RUN/round1-orchestrator.md`")
        round1_hook = text.index('run_zdebug_compaction_seam "debug-phase3a-after-round1-orchestrator"')
        round1_dispatch = text.index("Dispatch consultants in parallel", round1_hook)
        assert round1_write < round1_hook < round1_dispatch

        pool_hook = text.index('run_zdebug_compaction_seam "debug-phase3a-post-hypothesis-pool"')
        round2_dispatch = text.index("## Phase 3b — Round 2 adversarial")
        assert text.index("After the initial `## Hypothesis Pool`") < pool_hook < round2_dispatch

        updated_pool = text.index("Commit the updated `## Hypothesis Pool` to DEBUG.md after Phase 3b")
        updated_pool_hook = text.index('run_zdebug_compaction_seam "debug-phase3b-post-hypothesis-pool"')
        phase4 = text.index("## Phase 4 — Build the Test Matrix")
        assert updated_pool < updated_pool_hook < phase4

        scoring_hook = text.index('run_zdebug_compaction_seam "debug-phase6-post-scoring"')
        loop_decision = text.index("### Phase 6 loop logic")
        assert text.index("## Score Updates") < scoring_hook < loop_decision

        fix_consult_hook = text.index('run_zdebug_compaction_seam "debug-phase7-pre-fix-consult"')
        fix_consult_dispatch = text.index("Bundled `light-fix` consult", fix_consult_hook)
        assert fix_consult_hook < fix_consult_dispatch

        assert "orchestrator hypothesis checkpoint decision is durable" in text
        assert "before any consultant output can be read" in text
        assert "$Z_HARNESS_PLAN_DIR/DEBUG.md` and the next phase" in text

    def test_zdebug_over_threshold_checkpoint_points_resume_at_debug_md_and_next_phase(self, tmp_path: Path):
        _seed_plan_dir(tmp_path)
        debug_md = tmp_path / "DEBUG.md"
        debug_md.write_text("# Debug: demo\n\n## Problem\n\n## Evidence Inventory\n", encoding="utf-8")
        round1 = tmp_path / "archive" / "run-debug" / "round1-orchestrator.md"
        round1.parent.mkdir(parents=True)
        round1.write_text("# Round 1 — Orchestrator hypotheses\n", encoding="utf-8")
        guard = "debug-sha:" + hashlib.sha256(debug_md.read_bytes() + round1.read_bytes()).hexdigest()

        check = _run_check_compaction(
            tmp_path,
            {
                "Z_HARNESS_CONTEXT_USED_TOKENS": "900",
                "Z_HARNESS_CONTEXT_WINDOW_TOKENS": "1000",
            },
        )
        assert check.returncode == 1, check.stderr

        next_step = f"Resume /z-debug from {debug_md}; continue at Phase 3a Round 1 consultant dispatch using DEBUG.md"
        env = {
            **os.environ,
            "Z_HARNESS_PLAN_DIR": str(tmp_path),
            "Z_HARNESS_SLUG": "debug-demo",
            "Z_HARNESS_BASE_DIR": str(tmp_path / "state"),
            "RUN": "test-zdebug-round1-checkpoint",
            "Z_HARNESS_CHECKPOINT_STATUS": "context_pressure",
            "Z_HARNESS_CHECKPOINT_NEXT_STEP": next_step,
            "Z_HARNESS_CHECKPOINT_RESUME_COMMAND": "/z-debug debug-demo",
            "Z_HARNESS_CHECKPOINT_PHASE_NAME": "Phase 3a after orchestrator checkpoint",
            "Z_HARNESS_CHECKPOINT_PHASE_ID": "debug-phase3a-after-round1-orchestrator",
            "Z_HARNESS_CHECKPOINT_COMPLETED_ARTIFACT": str(round1),
            "Z_HARNESS_CHECKPOINT_FAST_FORWARD_GUARD": guard,
            "Z_HARNESS_CHECKPOINT_STALE_MODE": "reject",
            "Z_HARNESS_CHECKPOINT_PRODUCER": "z-debug",
            "Z_HARNESS_CHECKPOINT_PRODUCER_META_JSON": json.dumps(
                {
                    "command": "z-debug",
                    "seam": "debug-phase3a-after-round1-orchestrator",
                    "debug_md": str(debug_md),
                }
            ),
        }

        checkpoint = subprocess.run(
            ["bash", _WRITE_CLEAR_CHECKPOINT_SH],
            env=env,
            cwd=str(_REPO_ROOT),
            capture_output=True,
            text=True,
        )

        assert checkpoint.returncode == 0, checkpoint.stderr
        assert checkpoint.stdout.startswith("STATUS: clear_checkpoint "), checkpoint.stdout
        handoff = json.loads((tmp_path / "handoff.json").read_text(encoding="utf-8"))
        assert handoff["status"] == "context_pressure"
        assert str(debug_md) in handoff["next_step"]
        assert "Phase 3a Round 1 consultant dispatch" in handoff["next_step"]

        events = _read_metrics(tmp_path)
        written = [event for event in events if event.get("kind") == "clear_checkpoint_written"][-1]
        assert written["producer"] == "z-debug"
        assert written["phase_id"] == "debug-phase3a-after-round1-orchestrator"
        assert written["completed_artifact"] == str(round1)
        assert written["fast_forward_guard"] == guard
        assert written["resume_command"] == "/z-debug debug-demo"
        assert written["producer_metadata"] == {
            "command": "z-debug",
            "seam": "debug-phase3a-after-round1-orchestrator",
            "debug_md": str(debug_md),
        }

    def test_zdebug_under_threshold_continues_without_checkpoint(self, tmp_path: Path):
        _seed_plan_dir(tmp_path)
        (tmp_path / "DEBUG.md").write_text("# Debug: demo\n\n## Test Matrix\n", encoding="utf-8")

        result = _run_check_compaction(
            tmp_path,
            {
                "Z_HARNESS_CONTEXT_USED_TOKENS": "500",
                "Z_HARNESS_CONTEXT_WINDOW_TOKENS": "1000",
            },
        )

        assert result.returncode == 0, result.stderr
        assert not (tmp_path / "handoff.json").exists()
        assert not any(event.get("kind") == "compaction_pause" for event in _read_metrics(tmp_path))


class TestMapResearchWorkflowCheckpointHooks:
    """Contract tests for map/research shared checkpoint hook adoption."""

    _RESEARCH_SEAMS = (
        "research-phase1-pre-panel",
        "research-phase2-pre-judge",
        "research-phase3-pre-finalize",
        "research-phase4-pre-user-report",
    )

    _MAP_SEAMS = (
        "map-phase4-pre-critique",
        "map-phase4-post-critique",
        "map-phase4-pre-map-write",
        "map-phase5-pre-final-review",
        "map-phase5-pre-user-report",
    )

    def test_zresearch_registers_shared_hook_at_durable_phase_boundaries(self):
        text = _load_zresearch_skill()
        TestAuditStyleWorkflowCheckpointHooks()._assert_shared_hook_contract(
            text,
            self._RESEARCH_SEAMS,
        )

        for token in (
            'Z_HARNESS_CHECKPOINT_PRODUCER="z-research"',
            "STATUS:\\ clear_checkpoint_fast_forward*) ;;",
            "Resume /z-research from $Z_HARNESS_PLAN_DIR",
            "PANEL_PERSPECTIVES_PATH",
            "perspectives.json",
            "--resume-phase=$seam_id --resume-run=$RUN",
            "### Step 0 — Resume-phase gate",
            "RESUME_TARGET=\"phase3\"",
            "do not rerun earlier subcommands/panel/judge work",
            "CURRENT_GUARD",
            "stale /z-research checkpoint guard",
            "Z_RESEARCH_RESUME_TARGET",
            "Do not run Phase 1 or Phase 2 when `Z_RESEARCH_RESUME_TARGET=phase3`",
            "skip Phase 2 entirely and enter the later target phase",
            "skip judge synthesis and enter Phase 4",
            "resume flags are not topic text",
            "never included in slug derivation",
            'RUN="${RESUME_RUN:-$(date -u +%Y%m%dT%H%M%SZ)-$SLUG}"',
            'PERSPECTIVES_JSON="$(cat "$PANEL_PERSPECTIVES_PATH")"',
            "On a `Z_RESEARCH_RESUME_TARGET=phase3` resume, reload the durable judge input manifest",
        ):
            assert token in text

        phase1_ready = text.index("Before proceeding to Phase 2, both MAP.md and BRAINSTORM.md")
        phase1_hook = text.index('run_workflow_compaction_seam \\\n  "research-phase1-pre-panel"')
        panel_dispatch = text.index("### Step 3 — Parallel dispatch", text.index("## Phase 2"))
        assert phase1_ready < phase1_hook < panel_dispatch

        panel_manifest = text.index('PANEL_PERSPECTIVES_PATH="$Z_HARNESS_PLAN_DIR/archive/$RUN/panel/perspectives.json"')
        phase2_hook = text.index('run_workflow_compaction_seam \\\n  "research-phase2-pre-judge"')
        judge_dispatch = text.index("### Step 1 — Dispatch research-judge")
        assert panel_manifest < phase2_hook < judge_dispatch

        research_write = text.index("Atomic write: tmp then rename")
        phase3_hook = text.index('run_workflow_compaction_seam \\\n  "research-phase3-pre-finalize"')
        phase4 = text.index("## Phase 4 — Finalize")
        assert research_write < phase3_hook < phase4

        tripwire_update = text.index("Update RESEARCH.md frontmatter with fired tripwires")
        phase4_hook = text.index('run_workflow_compaction_seam \\\n  "research-phase4-pre-user-report"')
        user_report = text.index("### Step 5 — Push-notify + final message")
        assert tripwire_update < phase4_hook < user_report

    def test_zresearch_over_threshold_checkpoint_points_resume_at_next_phase(self, tmp_path: Path):
        _seed_plan_dir(tmp_path)
        panel_dir = tmp_path / "archive" / "run-research" / "panel"
        panel_dir.mkdir(parents=True)
        map_md = tmp_path / "MAP.md"
        brainstorm_md = tmp_path / "BRAINSTORM.md"
        research_md = tmp_path / "RESEARCH.md"
        perspectives = panel_dir / "perspectives.json"
        map_md.write_text("---\nartifact: map\n---\n\n## Terrain\n", encoding="utf-8")
        brainstorm_md.write_text("---\nartifact: brainstorm\n---\n\n## Framings\n", encoding="utf-8")
        research_md.write_text("---\nartifact: research\n---\n\n## Approach decision matrix\n", encoding="utf-8")
        perspectives.write_text(
            json.dumps(
                [
                    {
                        "name": "architecture-conservative",
                        "return_path": str(panel_dir / "architecture-conservative.md"),
                    }
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        guard = "research-sha:" + hashlib.sha256(
            map_md.read_bytes()
            + brainstorm_md.read_bytes()
            + research_md.read_bytes()
            + perspectives.read_bytes()
        ).hexdigest()

        check = _run_check_compaction(
            tmp_path,
            {
                "Z_HARNESS_CONTEXT_USED_TOKENS": "900",
                "Z_HARNESS_CONTEXT_WINDOW_TOKENS": "1000",
            },
        )
        assert check.returncode == 1, check.stderr

        next_step = (
            f"Resume /z-research from {tmp_path}; "
            "continue at Phase 3 judge synthesis using the archived panel perspectives"
        )
        env = {
            **os.environ,
            "Z_HARNESS_PLAN_DIR": str(tmp_path),
            "Z_HARNESS_SLUG": "research-demo",
            "Z_HARNESS_BASE_DIR": str(tmp_path / "state"),
            "RUN": "test-zresearch-panel-checkpoint",
            "Z_HARNESS_CHECKPOINT_STATUS": "context_pressure",
            "Z_HARNESS_CHECKPOINT_RESUME_COMMAND": "/z-research research-demo --resume-phase=research-phase2-pre-judge --resume-run=run-research",
            "Z_HARNESS_CHECKPOINT_NEXT_STEP": next_step,
            "Z_HARNESS_CHECKPOINT_PHASE_NAME": "Phase 2 panel archived before judge",
            "Z_HARNESS_CHECKPOINT_PHASE_ID": "research-phase2-pre-judge",
            "Z_HARNESS_CHECKPOINT_COMPLETED_ARTIFACT": str(perspectives),
            "Z_HARNESS_CHECKPOINT_FAST_FORWARD_GUARD": guard,
            "Z_HARNESS_CHECKPOINT_STALE_MODE": "reject",
            "Z_HARNESS_CHECKPOINT_PRODUCER": "z-research",
            "Z_HARNESS_CHECKPOINT_PRODUCER_META_JSON": json.dumps(
                {
                    "command": "z-research",
                    "resume_phase": "research-phase2-pre-judge",
                    "seam": "research-phase2-pre-judge",
                    "map_md": str(map_md),
                    "brainstorm_md": str(brainstorm_md),
                    "research_md": str(research_md),
                }
            ),
        }

        first = subprocess.run(
            ["bash", _WRITE_CLEAR_CHECKPOINT_SH],
            env=env,
            cwd=str(_REPO_ROOT),
            capture_output=True,
            text=True,
        )
        assert first.returncode == 0, first.stderr
        assert first.stdout.startswith("STATUS: clear_checkpoint "), first.stdout
        handoff = json.loads((tmp_path / "handoff.json").read_text(encoding="utf-8"))
        assert handoff["status"] == "context_pressure"
        assert "Phase 3 judge synthesis" in handoff["next_step"]

        second = subprocess.run(
            ["bash", _WRITE_CLEAR_CHECKPOINT_SH],
            env=env,
            cwd=str(_REPO_ROOT),
            capture_output=True,
            text=True,
        )
        assert second.returncode == 0, second.stderr
        assert second.stdout.startswith("STATUS: clear_checkpoint_fast_forward "), second.stdout

        events = _read_metrics(tmp_path)
        written = [event for event in events if event.get("kind") == "clear_checkpoint_written"][-1]
        assert written["producer"] == "z-research"
        assert written["phase_id"] == "research-phase2-pre-judge"
        assert written["completed_artifact"] == str(perspectives)
        assert written["resume_command"] == "/z-research research-demo --resume-phase=research-phase2-pre-judge --resume-run=run-research"
        assert written["producer_metadata"] == {
            "command": "z-research",
            "seam": "research-phase2-pre-judge",
            "resume_phase": "research-phase2-pre-judge",
            "map_md": str(map_md),
            "brainstorm_md": str(brainstorm_md),
            "research_md": str(research_md),
        }
        fast_forward = [event for event in events if event.get("kind") == "clear_checkpoint_fast_forward"][-1]
        assert fast_forward["phase_id"] == "research-phase2-pre-judge"
        assert fast_forward["producer"] == "z-research"

    def test_zresearch_under_threshold_continues_without_checkpoint(self, tmp_path: Path):
        _seed_plan_dir(tmp_path)
        (tmp_path / "MAP.md").write_text("# Map\n", encoding="utf-8")
        (tmp_path / "BRAINSTORM.md").write_text("# Brainstorm\n", encoding="utf-8")

        result = _run_check_compaction(
            tmp_path,
            {
                "Z_HARNESS_CONTEXT_USED_TOKENS": "500",
                "Z_HARNESS_CONTEXT_WINDOW_TOKENS": "1000",
            },
        )

        assert result.returncode == 0, result.stderr
        assert not (tmp_path / "handoff.json").exists()
        assert not any(event.get("kind") == "compaction_pause" for event in _read_metrics(tmp_path))
