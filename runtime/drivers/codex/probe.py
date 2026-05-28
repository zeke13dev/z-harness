"""
runtime/drivers/codex/probe.py — one-shot diagnostic probes for the Codex CLI.

Probes (run in sequence by run_probes()):

1. Session-resumption probe
   Runs ``codex exec --help`` and scans the help text for any flag whose name
   contains "session", "resume", or "continue".  Records the flag string in
   ProbeResults.session_resume_flag (None if not found).  If not found, a
   WARNING is emitted to stderr and the feature is marked unsupported in the
   JSON output; no exception is raised.

2. Cross-env collision probe
   Launches ``codex exec -`` with both ANTHROPIC_API_KEY and OPENAI_API_KEY
   set in the subprocess environment (values are dummy stubs — the subprocess
   is expected to fail quickly).  Records the exit code and any warning lines
   from stderr in ProbeResults.cross_env_collision_outcome.

Telemetry:
  ``codex_env_collision_detected`` is fired (informational) if ANTHROPIC_API_KEY
  is present in the parent process environment at probe time.

Output:
  Results are written to ``runtime/drivers/codex/probe_results.json`` (the
  directory containing this module), overwriting any previous result.

Usage:
  python -m runtime.drivers.codex.probe  # run probes and exit
  or import run_probes() and call it from integration code.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

try:
    from runtime.compat import log_event as _log_event
except ImportError:
    _log_event = None  # type: ignore[assignment]

# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

_PROBE_RESULTS_PATH = Path(__file__).parent / "probe_results.json"


@dataclass
class ProbeResults:
    """Structured result of a single probe run.

    Attributes
    ----------
    session_resume_flag:
        The CLI flag string (e.g. ``--session-id``) found in ``codex exec --help``
        that matches "session", "resume", or "continue"; or ``None`` if no such
        flag exists.  When ``None``, ``session_resume_supported`` is ``False``.
    session_resume_supported:
        ``True`` iff a session-resumption flag was detected.
    cross_env_collision_outcome:
        Short descriptor of the cross-env probe result: ``"exit_zero"`` when the
        subprocess exited 0, ``"non_zero_exit:<code>"`` otherwise.  Includes a
        ``"warnings:<n>"`` suffix when warning lines were captured from stderr.
    cross_env_collision_warnings:
        Raw warning lines captured from stderr during the cross-env probe.
    codex_path:
        The codex binary path passed to run_probes().
    """

    session_resume_flag: Optional[str]
    session_resume_supported: bool
    cross_env_collision_outcome: str
    cross_env_collision_warnings: list[str] = field(default_factory=list)
    codex_path: str = "codex"


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def run_probes(codex_path: str = "codex") -> ProbeResults:
    """Run all diagnostic probes against the Codex CLI at *codex_path*.

    Fires ``codex_env_collision_detected`` telemetry (informational) if
    ``ANTHROPIC_API_KEY`` is present in the parent process environment.

    Writes results to ``runtime/drivers/codex/probe_results.json`` next to
    this module file (overwrites any previous result).

    Parameters
    ----------
    codex_path:
        Path or name of the codex executable.  Defaults to ``"codex"``, which
        relies on ``PATH`` resolution.

    Returns
    -------
    ProbeResults
        Populated result dataclass.  Always returned (never raises on probe
        failure); individual probe failures are recorded in the result.
    """
    _maybe_fire_collision_telemetry()

    session_flag = _probe_session_resume(codex_path)
    collision_outcome, collision_warnings = _probe_cross_env_collision(codex_path)

    results = ProbeResults(
        session_resume_flag=session_flag,
        session_resume_supported=session_flag is not None,
        cross_env_collision_outcome=collision_outcome,
        cross_env_collision_warnings=collision_warnings,
        codex_path=codex_path,
    )

    _write_results(results)
    return results


# ---------------------------------------------------------------------------
# Probe 1 — session-resumption flag detection
# ---------------------------------------------------------------------------

_SESSION_PATTERN = re.compile(r"--[\w-]*(?:session|resume|continue)[\w-]*", re.IGNORECASE)


def _probe_session_resume(codex_path: str) -> Optional[str]:
    """Run ``codex exec --help`` and look for a session/resume/continue flag.

    Returns the first matching flag string, or None if not found.
    Logs a WARNING to stderr and returns None if the flag is absent.
    Never raises.
    """
    try:
        proc = subprocess.run(
            [codex_path, "exec", "--help"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        help_text = proc.stdout + proc.stderr
    except (OSError, subprocess.TimeoutExpired) as exc:
        print(
            f"[codex_probe] WARNING: could not run '{codex_path} exec --help': {exc}",
            file=sys.stderr,
        )
        return None

    match = _SESSION_PATTERN.search(help_text)
    if match:
        return match.group(0)

    print(
        "[codex_probe] WARNING: no session/resume/continue flag found in "
        f"'{codex_path} exec --help'; session-resumption feature marked unsupported.",
        file=sys.stderr,
    )
    return None


# ---------------------------------------------------------------------------
# Probe 2 — cross-env collision smoke test
# ---------------------------------------------------------------------------

_WARNING_PATTERN = re.compile(r"warn(?:ing)?", re.IGNORECASE)

_STUB_KEY = "probe-stub-key-do-not-use"


def _probe_cross_env_collision(codex_path: str) -> tuple[str, list[str]]:
    """Launch ``codex exec -`` with both ANTHROPIC_API_KEY and OPENAI_API_KEY set.

    The subprocess is expected to fail quickly (stdin is closed immediately, no
    real prompt is sent).  Records whether it exited 0 or non-zero, and captures
    any lines from stderr that contain the word "warn" / "warning".

    Returns
    -------
    (outcome_str, warning_lines)
        outcome_str is one of:
          - ``"exit_zero"``
          - ``"exit_zero+warnings:<n>"``
          - ``"non_zero_exit:<code>"``
          - ``"non_zero_exit:<code>+warnings:<n>"``
          - ``"probe_error:<description>"`` — if the subprocess could not be launched
    """
    probe_env = {**os.environ, "ANTHROPIC_API_KEY": _STUB_KEY, "OPENAI_API_KEY": _STUB_KEY}

    try:
        proc = subprocess.run(
            [codex_path, "exec", "-"],
            input="",
            capture_output=True,
            text=True,
            timeout=10,
            env=probe_env,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return f"probe_error:{exc}", []

    exit_code = proc.returncode
    stderr_lines = proc.stderr.splitlines()
    warning_lines = [ln for ln in stderr_lines if _WARNING_PATTERN.search(ln)]

    if exit_code == 0:
        base = "exit_zero"
    else:
        base = f"non_zero_exit:{exit_code}"

    if warning_lines:
        outcome = f"{base}+warnings:{len(warning_lines)}"
    else:
        outcome = base

    return outcome, warning_lines


# ---------------------------------------------------------------------------
# Telemetry
# ---------------------------------------------------------------------------


def _maybe_fire_collision_telemetry() -> None:
    """Fire ``codex_env_collision_detected`` if ANTHROPIC_API_KEY is in parent env."""
    if "ANTHROPIC_API_KEY" not in os.environ:
        return
    if _log_event is None:
        return
    try:
        _log_event(
            run_id="codex-probe",
            kind="codex_env_collision_detected",
            payload={
                "source": "probe",
                "detected_key": "ANTHROPIC_API_KEY",
            },
            repo_root=str(Path(__file__).parents[3]),
        )
    except Exception as exc:  # noqa: BLE001 — telemetry must never block probe
        print(
            f"[codex_probe] WARNING: telemetry codex_env_collision_detected failed: {exc}",
            file=sys.stderr,
        )


# ---------------------------------------------------------------------------
# JSON output
# ---------------------------------------------------------------------------


def _write_results(results: ProbeResults) -> None:
    """Serialize *results* to probe_results.json next to this module."""
    data = asdict(results)
    _PROBE_RESULTS_PATH.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import shutil

    codex_exe = sys.argv[1] if len(sys.argv) > 1 else "codex"
    if not shutil.which(codex_exe):
        print(f"[codex_probe] ERROR: '{codex_exe}' not found on PATH.", file=sys.stderr)
        sys.exit(1)

    r = run_probes(codex_exe)
    print(json.dumps(asdict(r), indent=2))
