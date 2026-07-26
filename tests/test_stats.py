"""tests/test_stats.py — Tests for scripts/stats.py.

/z-stats's report phases (progress, wall-time, token spend, coordination
tallies, halts, suggested next command) shell out to `scripts/stats.py
<subcommand>` instead of inline jq/awk. This file unit-tests the pure
compute_* functions directly (scripts/stats.py uses a hyphen-free filename,
so a plain `import` works) and smoke-tests the CLI subcommands via
subprocess for the ones that shell out to real scripts
(plan-path.sh / active-plan-registry.py / session-helpers.sh).

Cases:
  progress_counts               — done/in_progress/pending via the real
                                   inline-heading TASKS.md format (delegated
                                   to session-helpers.sh, not a private regex)
  progress_missing_file         — TASKS.md absent -> exists=False, zero counts
  progress_skip_marker          — **SKIP:** marker counted independently
  walltime_sum_avg_sorted_desc  — groups *_end kinds, sums/averages wall_ms,
                                   sorted by total descending
  walltime_ignores_non_end_kind — a non-"_end" kind is excluded
  tokens_real_counts_preferred  — subagent_input/output_tokens used verbatim
                                   when present
  tokens_char_estimate_fallback — prompt_chars/response_chars //4 fallback
                                   when provider token fields are absent
  tokens_skips_missing_model    — events without subagent_model are ignored
  native_usage_uses_canonical_marginals_and_timing
                                 — cumulative child counters and overlapping
                                   timing retain canonical uncertainty/provenance
  coordination_all_seven_shown  — all 7 kinds always present, zero for absent
  coordination_run_id_filter    — --run-id filters out other runs' events
  halts_last_ten_only           — only the last 10 halt-kind events kept
  halts_ignores_other_kinds     — non-halt kinds are excluded
  next_command_no_plan          — no TASKS.md, no FIX.md -> /z-plan or /z-debug
  next_command_halts_pending    — a recent halt event wins over any other row
  next_command_all_done_no_review
                                 — all done, no review_all_end -> /z-review-all
  next_command_all_done_review_accepted
                                 — review_all_end shipped_clean -> /z-maintain-docs
  next_command_pending_tasks    — pending > 0 -> /z-execute
  next_command_fresh_no_tests   — no task_start, no TESTS.md -> /z-test then /z-execute
  next_command_fresh_with_tests — no task_start, TESTS.md present -> /z-execute
  next_command_fix_docs_touched — light-mode FIX.md w/ non-empty Docs touched
  cli_progress_subprocess       — CLI smoke test: `progress` subcommand output
  cli_next_command_subprocess   — CLI smoke test: `next-command` subcommand
"""

from __future__ import annotations

import importlib.util as _ilu
import json
import subprocess
import sys
import tempfile
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SCRIPT = _REPO_ROOT / "scripts" / "stats.py"

_spec = _ilu.spec_from_file_location("stats", _SCRIPT)
assert _spec is not None and _spec.loader is not None
stats = _ilu.module_from_spec(_spec)
_spec.loader.exec_module(stats)  # type: ignore[union-attr]


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _write_native_usage(path: Path) -> None:
    """Write a root/child fixture with cumulative counters and overlapping timing."""
    rows = [
        {"event": "usage", "session_id": "root", "timestamp": 10_000_000_000, "input_tokens": 80, "cached_input_tokens": 10, "output_tokens": 20, "reasoning_output_tokens": 5, "total_tokens": 100},
        {"event": "turn_start", "session_id": "root", "timestamp": 10_000_000_000, "turn_id": "root-turn"},
        {"event": "tool_start", "session_id": "root", "timestamp": 10_000_000_200, "tool_call_id": "root-tool"},
        {"event": "tool_end", "session_id": "root", "timestamp": 10_000_000_600, "tool_call_id": "root-tool"},
        {"event": "usage", "session_id": "root", "timestamp": 10_000_001_000, "input_tokens": 120, "cached_input_tokens": 10, "output_tokens": 30, "reasoning_output_tokens": 5, "total_tokens": 150},
        {"event": "turn_end", "session_id": "root", "timestamp": 10_000_001_000, "turn_id": "root-turn"},
        {"event": "usage", "session_id": "child", "parent_session_id": "root", "timestamp": 10_000_000_100, "input_tokens": 80, "cached_input_tokens": 10, "output_tokens": 20, "reasoning_output_tokens": 5, "total_tokens": 100},
        {"event": "turn_start", "session_id": "child", "parent_session_id": "root", "timestamp": 10_000_000_100, "turn_id": "child-turn"},
        {"event": "tool_start", "session_id": "child", "parent_session_id": "root", "timestamp": 10_000_000_400, "tool_call_id": "child-tool"},
        {"event": "tool_end", "session_id": "child", "parent_session_id": "root", "timestamp": 10_000_000_600, "tool_call_id": "child-tool"},
        {"event": "usage", "session_id": "child", "parent_session_id": "root", "timestamp": 10_000_000_700, "input_tokens": 100, "cached_input_tokens": 10, "output_tokens": 25, "reasoning_output_tokens": 5, "total_tokens": 125},
        {"event": "turn_end", "session_id": "child", "parent_session_id": "root", "timestamp": 10_000_000_900, "turn_id": "child-turn"},
    ]
    _write(path, "\n".join(json.dumps(row) for row in rows) + "\n")


# ---------------------------------------------------------------------------
# progress
# ---------------------------------------------------------------------------

def test_progress_counts():
    with tempfile.TemporaryDirectory() as tmp:
        tasks = _write(
            Path(tmp) / "TASKS.md",
            "## T001 — one `[x]`\n"
            "## T002 — two `[~]`\n"
            "## T003 — three `[ ]`\n"
            "## T004 — four `[ ]`\n",
        )
        result = stats.compute_progress(tasks)
        assert result["exists"] is True
        assert result["done"] == 1
        assert result["in_progress"] == 1
        assert result["pending"] == 2
        assert result["total"] == 4


def test_progress_missing_file():
    with tempfile.TemporaryDirectory() as tmp:
        result = stats.compute_progress(Path(tmp) / "TASKS.md")
        assert result["exists"] is False
        assert result["done"] == 0
        assert result["total"] == 0


def test_progress_skip_marker():
    with tempfile.TemporaryDirectory() as tmp:
        tasks = _write(
            Path(tmp) / "TASKS.md",
            "## T001 — one `[ ]`\n**SKIP: user override, superseded by T002**\n",
        )
        result = stats.compute_progress(tasks)
        assert result["skipped"] == 1


# ---------------------------------------------------------------------------
# walltime
# ---------------------------------------------------------------------------

def test_walltime_sum_avg_sorted_desc():
    events = [
        {"kind": "task_end", "wall_ms": 1000},
        {"kind": "task_end", "wall_ms": 3000},
        {"kind": "review_end", "wall_ms": 500},
    ]
    rows = stats.compute_walltime(events)
    assert rows[0] == ("task_end", 2, 4000)
    assert rows[1] == ("review_end", 1, 500)


def test_walltime_ignores_non_end_kind():
    events = [{"kind": "task_start", "wall_ms": 9999}]
    rows = stats.compute_walltime(events)
    assert rows == []


# ---------------------------------------------------------------------------
# tokens
# ---------------------------------------------------------------------------

def test_tokens_real_counts_preferred():
    events = [
        {"subagent_model": "sonnet", "subagent_input_tokens": 100, "subagent_output_tokens": 50},
    ]
    rows = stats.compute_tokens(events)
    assert rows == [("sonnet", 1, 100, 50)]


def test_tokens_char_estimate_fallback():
    events = [
        {"subagent_model": "haiku", "prompt_chars": 400, "response_chars": 40},
    ]
    rows = stats.compute_tokens(events)
    assert rows == [("haiku", 1, 100, 10)]


def test_tokens_skips_missing_model():
    events = [{"subagent_input_tokens": 100}]
    rows = stats.compute_tokens(events)
    assert rows == []


def test_native_usage_uses_canonical_marginals_and_timing(tmp_path):
    """INTENT criteria #8/#9: stats preserves unknown usage and overlap timing."""
    _write_native_usage(tmp_path / "native-usage.jsonl")
    result = stats.compute_native_usage(tmp_path)
    assert result is not None
    sessions = {item["session_hash"]: item for item in result["sessions"]}
    root = sessions[stats.session_hash("root")]
    child = sessions[stats.session_hash("child")]
    assert root["canonical_usage"] == {
        "schema_version": 1,
        "known_subtotal_tokens": 150,
        "unknown_segment_count": 0,
        "unknown_reasons": [],
        "completeness": "complete",
        "marginal_deltas": root["canonical_usage"]["marginal_deltas"],
        "quality_flags": [],
    }
    assert child["canonical_usage"]["known_subtotal_tokens"] == 25
    assert child["canonical_usage"]["unknown_segment_count"] == 1
    assert child["canonical_usage"]["unknown_reasons"] == ["ambiguous_inheritance"]
    assert child["canonical_usage"]["completeness"] == "partial"
    assert root["canonical_timing"]["run_elapsed_ms"] == 1000
    assert root["canonical_timing"]["clock_provenance"] == ["provider"]
    assert root["canonical_timing"]["overlap_duration_ms"] == 400
    assert root["canonical_timing"]["derived_idle_ms"] == 0


def test_cli_native_usage_reports_the_canonical_result(tmp_path):
    """The user-facing stats subcommand emits the same canonical contract."""
    _write_native_usage(tmp_path / "native-usage.jsonl")
    proc = subprocess.run(
        [sys.executable, str(_SCRIPT), "native-usage", str(tmp_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0
    sessions = json.loads(proc.stdout)["sessions"]
    usages = {item["canonical_usage"]["completeness"]: item["canonical_usage"] for item in sessions}
    assert usages["complete"]["known_subtotal_tokens"] == 150
    assert usages["partial"]["known_subtotal_tokens"] == 25


def test_tokens_command_prefers_canonical_marginals_over_cumulative_events(tmp_path):
    """INTENT criterion #8: the established command cannot double-count children."""
    _write_native_usage(tmp_path / "native-usage.jsonl")
    metrics = _write(
        tmp_path / "metrics.jsonl",
        json.dumps({
            "subagent_model": "sonnet",
            "subagent_input_tokens": 500,
            "subagent_output_tokens": 250,
        }) + "\n",
    )
    proc = subprocess.run(
        [sys.executable, str(_SCRIPT), "tokens", str(metrics)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0
    assert proc.stdout.strip() == (
        "native-marginal observations=3 known_tok=175 "
        "unknown_segments=1 unknown_reasons=ambiguous_inheritance "
        "completeness=partial"
    )
    assert "750" not in proc.stdout


# ---------------------------------------------------------------------------
# coordination
# ---------------------------------------------------------------------------

def test_coordination_all_seven_shown():
    counts = stats.compute_coordination([{"kind": "lease_claimed"}])
    assert counts["lease_claimed"] == 1
    assert set(counts.keys()) == set(stats._COORD_KINDS)
    for kind in stats._COORD_KINDS:
        if kind != "lease_claimed":
            assert counts[kind] == 0


def test_coordination_run_id_filter():
    events = [
        {"kind": "lease_claimed", "run_id": "run-a"},
        {"kind": "lease_claimed", "run_id": "run-b"},
    ]
    counts = stats.compute_coordination(events, run_id="run-a")
    assert counts["lease_claimed"] == 1


# ---------------------------------------------------------------------------
# halts
# ---------------------------------------------------------------------------

def test_halts_last_ten_only():
    events = [{"kind": "task_halt", "n": i} for i in range(15)]
    result = stats.compute_halts(events)
    assert len(result) == 10
    assert result[0]["n"] == 5
    assert result[-1]["n"] == 14


def test_halts_ignores_other_kinds():
    events = [{"kind": "task_done"}, {"kind": "decision_gate"}]
    result = stats.compute_halts(events)
    assert len(result) == 1
    assert result[0]["kind"] == "decision_gate"


# ---------------------------------------------------------------------------
# next-command
# ---------------------------------------------------------------------------

def test_next_command_no_plan():
    with tempfile.TemporaryDirectory() as tmp:
        result = stats.compute_next_command(Path(tmp), [])
        assert result["state"] == "no_plan"


def test_next_command_halts_pending():
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        _write(base / "TASKS.md", "## T001 — one `[ ]`\n")
        events = [{"kind": "task_halt", "reason": "wall_clock_cap"}]
        result = stats.compute_next_command(base, events)
        assert result["state"] == "halts_pending"
        assert result["halts"][0]["reason"] == "wall_clock_cap"


def test_next_command_all_done_no_review():
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        _write(base / "TASKS.md", "## T001 — one `[x]`\n")
        result = stats.compute_next_command(base, [])
        assert result["state"] == "all_done_no_review"
        assert "/z-review-all" in result["label"]


def test_next_command_all_done_review_accepted():
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        _write(base / "TASKS.md", "## T001 — one `[x]`\n")
        events = [{"kind": "review_all_end", "user_action": "shipped_clean"}]
        result = stats.compute_next_command(base, events)
        assert result["state"] == "review_all_accepted"
        assert "/z-maintain-docs" in result["label"]


def test_next_command_pending_tasks():
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        _write(base / "TASKS.md", "## T001 — one `[x]`\n## T002 — two `[ ]`\n")
        # Execution has already started (task_start present) — this is the
        # generic mid-run case, distinct from a never-started "fresh" plan.
        events = [{"kind": "task_start"}]
        result = stats.compute_next_command(base, events)
        assert result["state"] == "pending_tasks"
        assert result["label"] == "/z-execute"


def test_next_command_fresh_no_tests():
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        _write(base / "TASKS.md", "## T001 — one `[ ]`\n")
        result = stats.compute_next_command(base, [])
        assert result["state"] == "fresh_no_tests"
        assert "/z-test" in result["label"]


def test_next_command_fresh_with_tests():
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        _write(base / "TASKS.md", "## T001 — one `[ ]`\n")
        _write(base / "TESTS.md", "status: drafted\n")
        result = stats.compute_next_command(base, [])
        assert result["state"] == "fresh_with_tests"
        assert result["label"].startswith("/z-execute")


def test_next_command_fix_docs_touched():
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        _write(
            base / "FIX.md",
            "## Docs touched\ndocs/llm/foo.json\n\n## Approach\nsomething\n",
        )
        result = stats.compute_next_command(base, [])
        assert result["state"] == "light_mode_shipped"
        assert "/z-maintain-docs" in result["label"]


# ---------------------------------------------------------------------------
# CLI smoke tests (subprocess)
# ---------------------------------------------------------------------------

def test_cli_progress_subprocess():
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        _write(base / "TASKS.md", "## T001 — one `[x]`\n## T002 — two `[ ]`\n")
        proc = subprocess.run(
            [sys.executable, str(_SCRIPT), "progress", str(base), "my-slug"],
            capture_output=True, text=True, timeout=15,
        )
        assert proc.returncode == 0
        assert "Plan: my-slug" in proc.stdout
        assert "1/2 done" in proc.stdout


def test_cli_next_command_subprocess():
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        _write(base / "TASKS.md", "## T001 — one `[ ]`\n")
        proc = subprocess.run(
            [sys.executable, str(_SCRIPT), "next-command", str(base)],
            capture_output=True, text=True, timeout=15,
        )
        assert proc.returncode == 0
        assert "/z-test" in proc.stdout


def test_cli_walltime_subprocess():
    with tempfile.TemporaryDirectory() as tmp:
        metrics = Path(tmp) / "metrics.jsonl"
        metrics.write_text(
            json.dumps({"kind": "task_end", "wall_ms": 2000}) + "\n",
            encoding="utf-8",
        )
        proc = subprocess.run(
            [sys.executable, str(_SCRIPT), "walltime", str(metrics)],
            capture_output=True, text=True, timeout=15,
        )
        assert proc.returncode == 0
        assert "task_end" in proc.stdout
        assert "sum=0m" in proc.stdout
