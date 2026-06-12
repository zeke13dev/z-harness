"""
tests/test_surface_shortcut.py — Tests for scripts/surface-shortcut.sh.

Covers the M3 exit-code contract:
  1. Non-empty --declined (+ --chosen + RUN) ⇒ exit 1 AND a shortcut_proposed
     event was appended to metrics.jsonl.
  2. Empty/missing --declined ⇒ exit 0, no event written.
  3. Success path exits exactly 1 even if log-event.sh returns non-zero — and a
     genuine log-event.sh failure surfaces as exit 2 (infra), never the leaked
     code and never the shortcut signal (1).
  4. Missing --chosen on the event path ⇒ exit 2, no event.
  5. Unset/empty RUN on the event path ⇒ exit 2, no event.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SCRIPT = str(_REPO_ROOT / "scripts" / "surface-shortcut.sh")


def _run_shortcut(
    *extra_args: str,
    tmp_base: Path,
    run_id: str = "test-run-001",
    env_overrides: dict | None = None,
) -> subprocess.CompletedProcess:
    """Run surface-shortcut.sh with a hermetic base dir.

    Sets Z_HARNESS_BASE_DIR to *tmp_base* so all artifact writes land in the
    temp dir and never touch the developer's real metrics.jsonl.
    Also sets Z_HARNESS_HOST to a fixed value to skip the detect-host.sh
    subprocess (keeps tests fast and deterministic).
    """
    env = {
        **os.environ,
        "Z_HARNESS_BASE_DIR": str(tmp_base),
        "Z_HARNESS_HOST": "test-host",
        "RUN": run_id,
    }
    if env_overrides:
        env.update(env_overrides)
    return subprocess.run(
        ["bash", _SCRIPT, *extra_args],
        env=env,
        capture_output=True,
        text=True,
    )


def _read_metrics_events(tmp_base: Path) -> list[dict]:
    """Return all events from metrics.jsonl as a list of dicts (may be empty)."""
    metrics = tmp_base / "metrics.jsonl"
    if not metrics.exists():
        return []
    events = []
    for line in metrics.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            events.append(json.loads(line))
    return events


# ---------------------------------------------------------------------------
# Branch 1: non-empty --declined ⇒ exit 1 + shortcut_proposed event
# ---------------------------------------------------------------------------

class TestNonEmptyDeclined:
    """Non-empty --declined must emit shortcut_proposed and exit 1."""

    def test_exit_code_is_1(self, tmp_path: Path):
        """surface-shortcut.sh exits 1 when --declined is non-empty."""
        result = _run_shortcut(
            "--chosen", "use /z-do",
            "--declined", "use /z-plan (full spec pass)",
            "--why", "speed",
            tmp_base=tmp_path,
        )
        assert result.returncode == 1, (
            f"Expected exit 1 (caller must surface shortcut ask), "
            f"got {result.returncode}. stderr: {result.stderr!r}"
        )

    def test_shortcut_proposed_event_written(self, tmp_path: Path):
        """A shortcut_proposed event is appended to metrics.jsonl."""
        _run_shortcut(
            "--chosen", "use /z-do",
            "--declined", "use /z-plan (full spec pass)",
            "--why", "speed",
            tmp_base=tmp_path,
        )
        events = _read_metrics_events(tmp_path)
        shortcut_events = [e for e in events if e.get("kind") == "shortcut_proposed"]
        assert shortcut_events, (
            f"No shortcut_proposed event in metrics.jsonl after non-empty --declined. "
            f"All events: {events}"
        )

    def test_payload_contains_chosen_and_declined(self, tmp_path: Path):
        """The shortcut_proposed event payload carries both chosen and declined paths."""
        chosen_val = "use /z-do"
        declined_val = "use /z-plan (full spec pass)"
        _run_shortcut(
            "--chosen", chosen_val,
            "--declined", declined_val,
            tmp_base=tmp_path,
        )
        events = _read_metrics_events(tmp_path)
        shortcut_events = [e for e in events if e.get("kind") == "shortcut_proposed"]
        assert shortcut_events, "No shortcut_proposed event found"

        event = shortcut_events[0]
        assert event.get("chosen") == chosen_val, (
            f"Event missing 'chosen' field. event={event!r}"
        )
        assert event.get("declined") == declined_val, (
            f"Event missing 'declined' field. event={event!r}"
        )

    def test_payload_contains_why_when_provided(self, tmp_path: Path):
        """The shortcut_proposed event payload includes 'why' when provided."""
        _run_shortcut(
            "--chosen", "skip audit",
            "--declined", "run /z-audit-plan",
            "--why", "audit adds 10 min and task is trivial",
            tmp_base=tmp_path,
        )
        events = _read_metrics_events(tmp_path)
        shortcut_events = [e for e in events if e.get("kind") == "shortcut_proposed"]
        assert shortcut_events, "No shortcut_proposed event found"

        event = shortcut_events[0]
        assert event.get("why") == "audit adds 10 min and task is trivial", (
            f"Event 'why' field wrong. event={event!r}"
        )

    def test_violation_invariant_6_exit_1_vs_empty_declined_exit_0(self, tmp_path: Path):
        """Explicitly contrast: non-empty declined ⇒ exit 1, which differs from
        empty declined ⇒ exit 0.  This is the load-bearing behavioral contract (M3).

        If the script got the logic backwards (exit 0 on non-empty declined),
        the caller would never surface the shortcut ask.
        """
        # Non-empty declined MUST exit 1
        result_nonempty = _run_shortcut(
            "--chosen", "cheap path",
            "--declined", "robust path",
            tmp_base=tmp_path,
        )
        assert result_nonempty.returncode == 1, (
            f"Non-empty --declined must exit 1 (M3 contract), got {result_nonempty.returncode}"
        )

        # Empty declined MUST exit 0 (tested in isolation in the next class)
        result_empty = _run_shortcut(
            "--chosen", "cheap path",
            "--declined", "",
            tmp_base=tmp_path / "sub",
        )
        assert result_empty.returncode == 0, (
            f"Empty --declined must exit 0 (Invariant 6), got {result_empty.returncode}"
        )

        # Outcome must differ — the whole point of M3
        assert result_nonempty.returncode != result_empty.returncode, (
            "Exit codes are the same for non-empty and empty --declined; M3 contract broken"
        )


# ---------------------------------------------------------------------------
# Branch 2: empty / missing --declined ⇒ exit 0, no event (Invariant 6)
# ---------------------------------------------------------------------------

class TestEmptyOrMissingDeclined:
    """Empty or missing --declined must be a silent no-op (exit 0, no event)."""

    def test_empty_declined_exits_0(self, tmp_path: Path):
        """surface-shortcut.sh exits 0 when --declined is empty string."""
        result = _run_shortcut(
            "--chosen", "use /z-do",
            "--declined", "",
            tmp_base=tmp_path,
        )
        assert result.returncode == 0, (
            f"Empty --declined must exit 0 (Invariant 6: not a shortcut without "
            f"a namable alternative), got {result.returncode}. "
            f"stderr: {result.stderr!r}"
        )

    def test_empty_declined_writes_no_event(self, tmp_path: Path):
        """No shortcut_proposed event is written when --declined is empty."""
        _run_shortcut(
            "--chosen", "use /z-do",
            "--declined", "",
            tmp_base=tmp_path,
        )
        events = _read_metrics_events(tmp_path)
        shortcut_events = [e for e in events if e.get("kind") == "shortcut_proposed"]
        assert not shortcut_events, (
            f"shortcut_proposed event must NOT be written for empty --declined "
            f"(Invariant 6). Found: {shortcut_events}"
        )

    def test_no_declined_flag_exits_0(self, tmp_path: Path):
        """surface-shortcut.sh exits 0 when --declined flag is absent entirely."""
        result = _run_shortcut(
            # No --chosen, no --declined, no --why
            tmp_base=tmp_path,
        )
        assert result.returncode == 0, (
            f"Missing --declined must exit 0 (Invariant 6), "
            f"got {result.returncode}. stderr: {result.stderr!r}"
        )

    def test_no_declined_flag_writes_no_event(self, tmp_path: Path):
        """No event is written when --declined flag is absent entirely."""
        _run_shortcut(tmp_base=tmp_path)
        events = _read_metrics_events(tmp_path)
        shortcut_events = [e for e in events if e.get("kind") == "shortcut_proposed"]
        assert not shortcut_events, (
            f"No shortcut_proposed event should be written when --declined is absent. "
            f"Found: {shortcut_events}"
        )


# ---------------------------------------------------------------------------
# Branch 3: deterministic exit code — log-event.sh's rc must NOT leak.
# This is the load-bearing M3 reliability guarantee.
# ---------------------------------------------------------------------------

def _make_stub_plugin_root(tmp_path: Path, *, log_event_rc: int) -> Path:
    """Create a fake PLUGIN_ROOT whose scripts/log-event.sh exits *log_event_rc*.

    surface-shortcut.sh resolves log-event.sh from
    ANTIGRAVITY_PLUGIN_ROOT/CLAUDE_PLUGIN_ROOT, so pointing CLAUDE_PLUGIN_ROOT at
    this dir lets us deterministically force a log-event.sh return code without a
    PATH stub. Returns the plugin-root dir.
    """
    root = tmp_path / "stub_plugin_root"
    scripts = root / "scripts"
    scripts.mkdir(parents=True)
    stub = scripts / "log-event.sh"
    stub.write_text(
        "#!/usr/bin/env bash\n"
        f'echo "stub log-event: forced rc={log_event_rc}" >&2\n'
        f"exit {log_event_rc}\n",
        encoding="utf-8",
    )
    stub.chmod(0o755)
    return root


class TestLogEventRcDoesNotLeak:
    """log-event.sh's exit code must never become the script's exit code.

    The whole point of T009 is a reliable exit-code contract: a caller keys on
    exit 1 to surface the inline shortcut ask. If log-event.sh's rc leaked, a
    benign non-zero (or, worse, a value that happens to be 0) would corrupt the
    signal. The success path must reliably exit 1; a genuine log-event failure
    must surface as exit 2 (infra), distinct from both 1 and 0.
    """

    def test_success_path_exits_1_when_log_event_returns_zero(self, tmp_path: Path):
        """Baseline: with a stub log-event that returns 0, success path exits 1."""
        root = _make_stub_plugin_root(tmp_path, log_event_rc=0)
        result = _run_shortcut(
            "--chosen", "cheap path",
            "--declined", "robust path",
            tmp_base=tmp_path / "base",
            env_overrides={"CLAUDE_PLUGIN_ROOT": str(root)},
        )
        assert result.returncode == 1, (
            f"Success path must exit 1 (shortcut signal), got {result.returncode}. "
            f"stderr: {result.stderr!r}"
        )

    def test_log_event_failure_surfaces_as_exit_2_not_leaked_code(self, tmp_path: Path):
        """A forced log-event rc=99 must become exit 2 (infra), NOT 99 and NOT 1.

        This is the BLOCKER fix: silent event-loss must not masquerade as the
        shortcut signal (1) or success (0).
        """
        root = _make_stub_plugin_root(tmp_path, log_event_rc=99)
        result = _run_shortcut(
            "--chosen", "cheap path",
            "--declined", "robust path",
            tmp_base=tmp_path / "base",
            env_overrides={"CLAUDE_PLUGIN_ROOT": str(root)},
        )
        assert result.returncode == 2, (
            f"A failing log-event.sh (rc=99) must surface as exit 2 (infra failure), "
            f"not the leaked code and not the shortcut signal. got {result.returncode}. "
            f"stderr: {result.stderr!r}"
        )
        assert result.returncode != 99, "log-event.sh's rc leaked into the script's exit code"
        assert result.returncode != 1, (
            "Event was NOT recorded but script returned the shortcut signal (1); "
            "silent event-loss is masquerading as success"
        )


# ---------------------------------------------------------------------------
# Branch 4: non-empty --declined REQUIRES non-empty --chosen ⇒ exit 2, no event.
# ---------------------------------------------------------------------------

class TestChosenRequiredWithDeclined:
    """A shortcut needs both a chosen looser route AND a declined alternative."""

    def test_missing_chosen_exits_2(self, tmp_path: Path):
        """--declined non-empty with no --chosen ⇒ exit 2 (caller wiring bug)."""
        result = _run_shortcut(
            "--declined", "robust path",
            tmp_base=tmp_path,
        )
        assert result.returncode == 2, (
            f"Missing --chosen on the event path must exit 2, got {result.returncode}. "
            f"stderr: {result.stderr!r}"
        )

    def test_empty_chosen_exits_2(self, tmp_path: Path):
        """--declined non-empty with an explicitly empty --chosen ⇒ exit 2."""
        result = _run_shortcut(
            "--chosen", "",
            "--declined", "robust path",
            tmp_base=tmp_path,
        )
        assert result.returncode == 2, (
            f"Empty --chosen on the event path must exit 2, got {result.returncode}. "
            f"stderr: {result.stderr!r}"
        )

    def test_missing_chosen_writes_no_event(self, tmp_path: Path):
        """No shortcut_proposed event is written when --chosen is missing."""
        _run_shortcut("--declined", "robust path", tmp_base=tmp_path)
        events = _read_metrics_events(tmp_path)
        shortcut_events = [e for e in events if e.get("kind") == "shortcut_proposed"]
        assert not shortcut_events, (
            f"No event must be written when --chosen is missing. Found: {shortcut_events}"
        )


# ---------------------------------------------------------------------------
# Branch 5: RUN must be set on the event path ⇒ exit 2, no event.
# ---------------------------------------------------------------------------

class TestRunRequiredOnEventPath:
    """An unset/empty RUN is a caller wiring bug; the script must fail fast."""

    def test_unset_run_exits_2(self, tmp_path: Path):
        """RUN env var unset ⇒ exit 2, no 'unknown-run' placeholder event."""
        env = {
            **os.environ,
            "Z_HARNESS_BASE_DIR": str(tmp_path),
            "Z_HARNESS_HOST": "test-host",
        }
        env.pop("RUN", None)  # ensure RUN is genuinely unset
        result = subprocess.run(
            ["bash", _SCRIPT, "--chosen", "cheap path", "--declined", "robust path"],
            env=env,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 2, (
            f"Unset RUN on the event path must exit 2, got {result.returncode}. "
            f"stderr: {result.stderr!r}"
        )

    def test_empty_run_exits_2(self, tmp_path: Path):
        """RUN set to empty string ⇒ exit 2 (same as unset)."""
        result = _run_shortcut(
            "--chosen", "cheap path",
            "--declined", "robust path",
            tmp_base=tmp_path,
            env_overrides={"RUN": ""},
        )
        assert result.returncode == 2, (
            f"Empty RUN on the event path must exit 2, got {result.returncode}. "
            f"stderr: {result.stderr!r}"
        )

    def test_unset_run_writes_no_event(self, tmp_path: Path):
        """No 'unknown-run' (or any) shortcut_proposed event is written."""
        env = {
            **os.environ,
            "Z_HARNESS_BASE_DIR": str(tmp_path),
            "Z_HARNESS_HOST": "test-host",
        }
        env.pop("RUN", None)
        subprocess.run(
            ["bash", _SCRIPT, "--chosen", "cheap path", "--declined", "robust path"],
            env=env,
            capture_output=True,
            text=True,
        )
        events = _read_metrics_events(tmp_path)
        shortcut_events = [e for e in events if e.get("kind") == "shortcut_proposed"]
        assert not shortcut_events, (
            f"No event must be written when RUN is unset. Found: {shortcut_events}"
        )
