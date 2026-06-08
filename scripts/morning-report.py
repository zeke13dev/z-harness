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


_NO_BRIEFS_ = "__NO_PER_STEP_BRIEFS__"


def _build_per_step_briefs(state: dict, base_dir: str) -> str:
    """Build ## Per-step briefs content from step run-brief.json files.

    For each completed step, look for archive/<step-run-id>/run-brief.json under
    base_dir. Returns _NO_BRIEFS_ when no brief files are found.
    """
    lines = []
    for sr in state.get("step_runs", []):
        if sr.get("status") != "complete":
            continue
        step_run_id = sr.get("run_id")
        if not step_run_id:
            continue
        brief_path = os.path.join(base_dir, "archive", step_run_id, "run-brief.json")
        if not os.path.isfile(brief_path):
            continue
        try:
            with open(brief_path, "r", encoding="utf-8") as fh:
                brief = json.load(fh)
        except (json.JSONDecodeError, OSError):
            continue
        command = brief.get("command", "?")
        intent = brief.get("intent", "?")
        outcome = brief.get("outcome", "?")
        lines.append(f"- **{command}** ({step_run_id}): {intent} → {outcome}")

    if not lines:
        return _NO_BRIEFS_
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


def _find_halt_event(state: dict, events: list) -> dict:
    """Return the terminal halt event dict for the halted step, or empty dict."""
    # Find the halted step_run
    halted_step = None
    for sr in state.get("step_runs", []):
        if sr.get("status") in ("halt", "halted"):
            halted_step = sr
            break
    if halted_step is None:
        return {}

    step_name = halted_step.get("step", "")
    position = halted_step.get("position")

    # Look for overnight_step_halt event matching this step
    for ev in events:
        if ev.get("kind") == "overnight_step_halt":
            if ev.get("step") == step_name or ev.get("position") == position:
                return ev
    return {}


def _build_recommended_next(state: dict, events: list, run_id: str) -> str:
    """Build the ## Recommended next section, branching on terminal halt event kind."""
    overall_status = state.get("status", "unknown")
    diff_stat = state.get("git_diff_stat_at_end", "")

    lines = []
    if overall_status == "complete":
        lines.append("All steps completed successfully. No resume required.")
    else:
        halt_ev = _find_halt_event(state, events)
        halt_reason = halt_ev.get("halt_reason", "")
        halt_event_payload = halt_ev.get("halt_event", {})
        # terminal_event_kind from the halted step_run
        halted_step = next(
            (sr for sr in state.get("step_runs", []) if sr.get("status") in ("halt", "halted")),
            {},
        )
        terminal_kind = halted_step.get("terminal_event_kind", "")

        if halt_reason in ("no_ask_blocked", "unknown_ask_blocked") or terminal_kind in (
            "no_ask_blocked",
            "unknown_ask_blocked",
        ):
            question_id = halt_event_payload.get("question_id", halt_ev.get("question_id", "(unknown)"))
            lines.append(
                "Halted because NO_ASK=halt converted an AskUser call to a halt "
                f"(question_id: `{question_id}`). No interactive question was asked in the conversation."
            )
            lines.append("To unblock, choose one of:")
            lines.append(
                f"  (a) Instrument the callsite: run `scripts/lint-askuser.sh --strict` "
                f"and add `{question_id}` to the registry."
            )
            lines.append(
                f"  (b) Extend the allowlist: add `{question_id}` to "
                f"`Z_HARNESS_OVERNIGHT_AUTODECIDE` with a chosen answer."
            )
            lines.append("  (c) Accept the gap and review manually before resuming.")
            lines.append(f"Then resume with: /z-overnight resume {run_id}")
        elif terminal_kind == "slug_collision_halt" or halt_reason == "slug_collision_halt":
            slug = halt_ev.get("slug", "(unknown)")
            conflicting = halt_ev.get("conflicting_artifact", "(unknown)")
            lines.append(
                f"Halted due to slug collision: slug `{slug}` already has a finished plan "
                f"(conflicting artifact: `{conflicting}`)."
            )
            lines.append("To unblock, choose one of:")
            lines.append("  (a) Pass a fresh slug for a new run.")
            lines.append(f"  (b) Resume the prior run: /z-overnight resume {run_id}")
        elif terminal_kind == "skill_tool_failure" or halt_reason == "skill_tool_failure":
            error_step = halted_step
            error_event = error_step.get("error_event", {})
            message = error_event.get("message", "(no message captured)")
            lines.append(f"Halted due to a skill tool failure. Captured error: {message}")
            lines.append("Investigate the root cause before resuming.")
            lines.append(f"Resume with: /z-overnight resume {run_id}")
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

    # Per-step briefs (omitted when no step has run-brief.json)
    per_step_briefs = _build_per_step_briefs(state, base_dir)
    if per_step_briefs != _NO_BRIEFS_:
        sections.append("## Per-step briefs")
        sections.append(per_step_briefs)

    # Unilateral decisions
    sections.append("## Unilateral decisions")
    sections.append(_build_unilateral_decisions(events, state))

    # Test outcomes
    sections.append("## Test outcomes")
    sections.append(_build_test_outcomes(events))

    # Recommended next
    sections.append("## Recommended next")
    sections.append(_build_recommended_next(state, events, run_id))

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

def _run_fixture(fixture_dir: str) -> tuple:
    """Run a single golden-file comparison for the given fixture directory.

    Returns (passed: bool, label: str, diff_lines: list).
    """
    import difflib

    state_path = os.path.join(fixture_dir, "overnight-state.json")
    events_path = os.path.join(fixture_dir, "events.jsonl")
    golden_path = os.path.join(fixture_dir, "MORNING_REPORT.md.golden")

    label = os.path.basename(fixture_dir)

    for p in (state_path, events_path, golden_path):
        if not os.path.isfile(p):
            return False, label, [f"FAIL [{label}]: fixture file not found: {p}\n"]

    try:
        state = _load_state(state_path)
    except json.JSONDecodeError as exc:
        return False, label, [f"FAIL [{label}]: Could not parse overnight-state.json: {exc}\n"]

    events = _load_events(events_path)

    overnight_start = next(
        (e for e in events if e.get("kind") == "overnight_start"), {}
    )
    slug = overnight_start.get("slug", "unknown-slug")
    run_id = overnight_start.get("run", f"20260528T000000Z-overnight-{slug}")

    actual = generate_report(slug, fixture_dir, run_id, state, events)

    with open(golden_path, "r", encoding="utf-8") as fh:
        expected = fh.read()

    if actual == expected:
        return True, label, []

    diff = list(difflib.unified_diff(
        expected.splitlines(keepends=True),
        actual.splitlines(keepends=True),
        fromfile=f"expected ({label}/MORNING_REPORT.md.golden)",
        tofile=f"actual (generated for {label})",
    ))
    return False, label, diff


def cmd_self_test() -> int:
    """Run golden-file comparisons against all fixture data. Returns exit code."""
    repo_root = _repo_root()
    fixtures_base = os.path.join(
        repo_root,
        "z-harness", "overnight-run", "tests", "morning-report-fixtures"
    )

    # The root fixture dir is the primary (no_ask_blocked halt) case.
    # Sub-directories are additional halt-kind variants.
    fixture_dirs = [fixtures_base]
    if os.path.isdir(fixtures_base):
        for entry in sorted(os.listdir(fixtures_base)):
            sub = os.path.join(fixtures_base, entry)
            if os.path.isdir(sub) and os.path.isfile(os.path.join(sub, "MORNING_REPORT.md.golden")):
                fixture_dirs.append(sub)

    overall_pass = True
    for fixture_dir in fixture_dirs:
        passed, label, diff_lines = _run_fixture(fixture_dir)
        if passed:
            print(f"PASS [{label}]: golden-file comparison passed")
        else:
            overall_pass = False
            print(f"FAIL [{label}]: generated output differs from golden", file=sys.stderr)
            print("".join(diff_lines), file=sys.stderr)

    if overall_pass:
        print("PASS: all fixtures passed")
        return 0
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
