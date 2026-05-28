#!/usr/bin/env python3
"""morning-report.py — Generate MORNING_REPORT.md from overnight-state.json + events.jsonl.

Usage:
    python3 scripts/morning-report.py <slug>
    python3 scripts/morning-report.py --self-test

Reads the latest overnight RUN archive for <slug> and writes
z-harness/<slug>/MORNING_REPORT.md atomically (tmp + os.rename).
"""

import argparse
import json
import os
import sys
import tempfile


# ---------------------------------------------------------------------------
# Path resolution
# ---------------------------------------------------------------------------

def _repo_root() -> str:
    """Return the repository root (directory containing scripts/)."""
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _resolve_base(slug: str) -> str:
    """Resolve the plan base directory for <slug>.

    Tries canonical (z-harness/plans/<slug>/) then legacy (z-harness/<slug>/).
    Returns the first existing path; raises FileNotFoundError if neither exists.
    """
    repo = _repo_root()
    canonical = os.path.join(repo, "z-harness", "plans", slug)
    legacy = os.path.join(repo, "z-harness", slug)
    if os.path.isdir(canonical):
        return canonical
    if os.path.isdir(legacy):
        return legacy
    raise FileNotFoundError(
        f"Plan directory not found for slug '{slug}'. "
        f"Tried: {canonical}, {legacy}"
    )


def _find_latest_overnight_run(archive_dir: str) -> str:
    """Return the lexically-largest dir in archive_dir matching *-overnight-*.

    Raises FileNotFoundError if no matching directory exists.
    """
    if not os.path.isdir(archive_dir):
        raise FileNotFoundError(f"Archive directory not found: {archive_dir}")
    candidates = [
        d for d in os.listdir(archive_dir)
        if "-overnight-" in d
        and os.path.isdir(os.path.join(archive_dir, d))
    ]
    if not candidates:
        raise FileNotFoundError(
            f"No overnight RUN directories found in {archive_dir}"
        )
    candidates.sort()
    return candidates[-1]


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def _load_state(state_path: str) -> dict:
    """Load and return overnight-state.json."""
    with open(state_path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def _load_events(events_path: str) -> list:
    """Load events.jsonl as a list of dicts; skip malformed lines."""
    events = []
    if not os.path.isfile(events_path):
        return events
    with open(events_path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                pass  # Tolerate malformed lines per C6 robustness requirement
    return events


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------

def _format_status(state: dict) -> str:
    """Convert overall state status to human-readable form."""
    status = state.get("status", "unknown")
    if status == "complete":
        return "complete"
    if status in ("halt", "halted"):
        # Find the halted step index (1-based for display)
        for sr in state.get("step_runs", []):
            if sr.get("status") in ("halt", "halted"):
                return f"halted-at-step-{sr.get('position', 0) + 1}"
        return "halted"
    if status in ("error", "errored"):
        for sr in state.get("step_runs", []):
            if sr.get("status") in ("error", "errored"):
                return f"errored-at-step-{sr.get('position', 0) + 1}"
        return "errored"
    if status == "running":
        return "in progress"
    return status


def _head_sha_end(state: dict) -> str:
    """Return the HEAD SHA at run end (last step's head_sha_after)."""
    step_runs = state.get("step_runs", [])
    for sr in reversed(step_runs):
        sha = sr.get("head_sha_after")
        if sha:
            return sha
    return state.get("head_sha_at_start", "unknown")


def _build_chain_summary(state: dict, events: list, run_id: str) -> str:
    """Build the ## Chain summary section."""
    lines = []

    # Check for head_sha_mismatch_at_resume event — banner at top per C8
    mismatch_events = [e for e in events if e.get("kind") == "head_sha_mismatch_at_resume"]
    if mismatch_events:
        ev = mismatch_events[-1]
        lines.append(
            f"> **CRITICAL: HEAD SHA mismatch at resume.** "
            f"Expected: `{ev.get('expected', '?')}`, "
            f"Actual: `{ev.get('actual', '?')}` "
            f"(last completed step: {ev.get('last_step', '?')}). "
            f"Verify git state before proceeding."
        )
        lines.append("")

    chain = state.get("chain", [])
    chain_str = " → ".join(chain) if chain else "(empty)"
    started = state.get("started_at", "unknown")
    ended = state.get("ended_at") or "in progress"
    status_str = _format_status(state)
    sha_start = state.get("head_sha_at_start", "unknown")
    sha_end = _head_sha_end(state)

    lines.append(f"- Chain: {chain_str}")
    lines.append(f"- Started: {started}")
    lines.append(f"- Ended: {ended}")
    lines.append(f"- Status: {status_str}")
    lines.append(f"- HEAD at start / end: {sha_start} / {sha_end}")

    return "\n".join(lines)


def _build_phase_results(state: dict) -> str:
    """Build the ## Phase results table."""
    step_runs = state.get("step_runs", [])
    if not step_runs:
        return "_No step runs recorded._"

    header = "| # | Step | RUN_ID | Wall (ms) | Status | Terminal event |"
    separator = "|---|------|--------|-----------|--------|----------------|"
    rows = [header, separator]

    for sr in step_runs:
        num = sr.get("position", 0) + 1
        step = sr.get("step", "?")
        run_id_col = sr.get("run_id", "?")
        wall_ms = sr.get("wall_ms", "?")
        status = sr.get("status", "?")
        terminal = sr.get("terminal_event_kind", "?")
        rows.append(f"| {num} | {step} | {run_id_col} | {wall_ms} | {status} | {terminal} |")

    return "\n".join(rows)


def _build_unilateral_decisions(events: list, state: dict) -> str:
    """Build the ## Unilateral decisions table from overnight_decision events."""
    decision_events = [e for e in events if e.get("kind") == "overnight_decision"]
    if not decision_events:
        return "_No unilateral decisions recorded._"

    # Build a position→step lookup from state for annotating the table
    step_by_ts = {}
    step_runs = state.get("step_runs", [])
    # We'll match decisions to steps by timestamp ordering
    # Build sorted step time ranges
    step_ranges = []
    for sr in step_runs:
        step_ranges.append({
            "step": sr.get("step", "?"),
            "started_at": sr.get("started_at", ""),
            "ended_at": sr.get("ended_at", ""),
        })

    def _event_step(ev: dict) -> str:
        ts = ev.get("ts", "")
        for sr in step_ranges:
            started = sr.get("started_at", "")
            ended = sr.get("ended_at", "")
            if started and ended and started <= ts <= ended:
                return sr["step"]
        # Fallback: use last step that has started before this event
        for sr in reversed(step_ranges):
            if sr.get("started_at", "") <= ts:
                return sr["step"]
        return "?"

    header = "| Step | question_id | chosen | rule_id | source | strength |"
    separator = "|------|-------------|--------|---------|--------|----------|"
    rows = [header, separator]

    for ev in decision_events:
        step = _event_step(ev)
        qid = ev.get("question_id", "?")
        chosen = ev.get("chosen", "?")
        rule_id = ev.get("rule_id", "?")
        source = ev.get("source", "?")
        strength = ev.get("strength", "?")
        rows.append(f"| {step} | {qid} | {chosen} | {rule_id} | {source} | {strength} |")

    return "\n".join(rows)


# Test-suite-related event kinds that indicate test activity
_TEST_SUITE_KINDS = {
    "test_plan_end",
    "test_run_end",
    "test_suite_end",
    "implement_end",  # implement_end may carry test info
}

_TEST_SUITE_PREFIXES = ("test_", "suite_")


def _is_test_related(event: dict) -> bool:
    """Return True if this event is related to test suite execution."""
    kind = event.get("kind", "")
    if kind in _TEST_SUITE_KINDS:
        return True
    for prefix in _TEST_SUITE_PREFIXES:
        if kind.startswith(prefix):
            return True
    return False


def _build_test_outcomes(events: list) -> str:
    """Build the ## Test outcomes section."""
    test_events = [e for e in events if _is_test_related(e)]
    if not test_events:
        return "no tests run."

    lines = []
    for ev in test_events:
        kind = ev.get("kind", "?")
        ts = ev.get("ts", "?")
        # Build a summary line from known fields
        parts = [f"{kind} at {ts}"]
        if "suite" in ev:
            parts.append(f"suite: {ev['suite']}")
        if "tests_written" in ev:
            parts.append(f"tests_written: {ev['tests_written']}")
        if "tests_run" in ev:
            parts.append(f"tests_run: {ev['tests_run']}")
        if "passed" in ev:
            parts.append(f"passed: {ev['passed']}")
        if "failed" in ev:
            parts.append(f"failed: {ev['failed']}")
        if "status" in ev:
            parts.append(f"status: {ev['status']}")
        line = " — ".join([parts[0]] + [", ".join(parts[1:])]) if len(parts) > 1 else parts[0]
        lines.append(line)

    return "\n".join(lines)


def _build_recommended_next(state: dict, run_id: str) -> str:
    """Build the ## Recommended next section."""
    overall_status = state.get("status", "unknown")
    diff_stat = state.get("git_diff_stat_at_end", "")

    lines = []
    if overall_status == "complete":
        lines.append("All steps completed successfully. No resume required.")
    else:
        lines.append(
            f"Resume with: /z-overnight resume {run_id} after resolving the halt above."
        )

    if diff_stat:
        lines.append(f"git diff --stat headline: {diff_stat}")
    else:
        lines.append("git diff --stat headline: (not captured)")

    return "\n".join(lines)


def generate_report(slug: str, base_dir: str, run_id: str, state: dict, events: list) -> str:
    """Generate the full MORNING_REPORT.md content string."""
    sections = []

    # Title
    sections.append(f"# MORNING_REPORT — {slug} — {run_id}")

    # Chain summary
    sections.append("## Chain summary")
    sections.append(_build_chain_summary(state, events, run_id))

    # Phase results
    sections.append("## Phase results")
    sections.append(_build_phase_results(state))

    # Unilateral decisions
    sections.append("## Unilateral decisions")
    sections.append(_build_unilateral_decisions(events, state))

    # Test outcomes
    sections.append("## Test outcomes")
    sections.append(_build_test_outcomes(events))

    # Recommended next
    sections.append("## Recommended next")
    sections.append(_build_recommended_next(state, run_id))

    # Join sections with double newlines
    return "\n\n".join(sections) + "\n"


def _write_atomic(path: str, content: str) -> None:
    """Write content to path atomically via tmp + os.rename."""
    dir_path = os.path.dirname(path)
    fd, tmp_path = tempfile.mkstemp(dir=dir_path, prefix=".morning-report-tmp-", suffix=".md")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(content)
        os.rename(tmp_path, path)
    except OSError:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def cmd_generate(slug: str) -> int:
    """Generate MORNING_REPORT.md for the named slug. Returns exit code."""
    try:
        base = _resolve_base(slug)
    except FileNotFoundError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    archive_dir = os.path.join(base, "archive")
    try:
        run_id = _find_latest_overnight_run(archive_dir)
    except FileNotFoundError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    run_dir = os.path.join(archive_dir, run_id)
    state_path = os.path.join(run_dir, "overnight-state.json")
    events_path = os.path.join(run_dir, "events.jsonl")

    if not os.path.isfile(state_path):
        print(f"ERROR: overnight-state.json not found at {state_path}", file=sys.stderr)
        return 1

    try:
        state = _load_state(state_path)
    except json.JSONDecodeError as exc:
        print(f"ERROR: Failed to parse overnight-state.json: {exc}", file=sys.stderr)
        return 1

    events = _load_events(events_path)

    content = generate_report(slug, base, run_id, state, events)

    out_path = os.path.join(base, "MORNING_REPORT.md")
    _write_atomic(out_path, content)

    print(f"Wrote {out_path}")
    return 0


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------

def cmd_self_test() -> int:
    """Run golden-file comparison against fixture data. Returns exit code."""
    repo_root = _repo_root()
    fixtures_dir = os.path.join(
        repo_root,
        "z-harness", "overnight-run", "tests", "morning-report-fixtures"
    )

    state_path = os.path.join(fixtures_dir, "overnight-state.json")
    events_path = os.path.join(fixtures_dir, "events.jsonl")
    golden_path = os.path.join(fixtures_dir, "MORNING_REPORT.md.golden")

    # Validate fixture files exist
    for p in (state_path, events_path, golden_path):
        if not os.path.isfile(p):
            print(f"FAIL: fixture file not found: {p}", file=sys.stderr)
            return 1

    # Load fixtures
    try:
        state = _load_state(state_path)
    except json.JSONDecodeError as exc:
        print(f"FAIL: Could not parse fixture overnight-state.json: {exc}", file=sys.stderr)
        return 1

    events = _load_events(events_path)

    # Determine slug and run_id from fixture state
    # The fixture run_id is derived from the overnight_start event or we use a fixed value
    overnight_start = next(
        (e for e in events if e.get("kind") == "overnight_start"), {}
    )
    slug = overnight_start.get("slug", "my-slug")
    # run_id is the value in the "run" field of overnight_start event
    run_id = overnight_start.get("run", "20260528T220000Z-overnight-my-slug")
    base = fixtures_dir  # dummy base for self-test (not used for path in generate_report)

    actual = generate_report(slug, base, run_id, state, events)

    with open(golden_path, "r", encoding="utf-8") as fh:
        expected = fh.read()

    if actual == expected:
        print("PASS: golden-file comparison passed")
        return 0

    # Show diff
    import difflib
    diff = list(difflib.unified_diff(
        expected.splitlines(keepends=True),
        actual.splitlines(keepends=True),
        fromfile="expected (MORNING_REPORT.md.golden)",
        tofile="actual (generated)",
    ))
    print("FAIL: generated output differs from golden", file=sys.stderr)
    print("".join(diff), file=sys.stderr)
    return 1


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate MORNING_REPORT.md from overnight run state."
    )
    parser.add_argument(
        "slug",
        nargs="?",
        help="The plan slug (e.g. 'overnight-run'). Omit when using --self-test.",
    )
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="Run golden-file comparison on fixture data and exit.",
    )

    args = parser.parse_args()

    if args.self_test:
        return cmd_self_test()

    if not args.slug:
        parser.error("slug is required unless --self-test is specified.")

    return cmd_generate(args.slug)


if __name__ == "__main__":
    sys.exit(main())
