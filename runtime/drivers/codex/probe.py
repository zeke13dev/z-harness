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

3. Capability contract probe
   Best-effort discovery of Codex app/plugin multi-agent support, CLI-visible
   agent support, AskUser/gate support, and event-frame support.  Results are
   represented as structured per-surface status/evidence records so downstream
   code does not rely on stale host-wide assumptions.

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
from enum import Enum
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


class CapabilityStatus(str, Enum):
    """Tri-state capability status emitted by the Codex probe."""

    SUPPORTED = "supported"
    UNSUPPORTED = "unsupported"
    UNKNOWN = "unknown"


class CodexSurface(str, Enum):
    """Codex surface where a capability was observed or not observed."""

    APP_PLUGIN = "app_plugin"
    CLI = "cli"
    CLI_STREAM = "cli_stream"


class CodexSupportTier(str, Enum):
    """Concise classification derived from the individual probe fields."""

    UNKNOWN = "unknown"
    FLATTENED_CLI = "flattened_cli"
    CLI_PARTIAL = "cli_partial"
    CLI_NATIVE_CANDIDATE = "cli_native_candidate"
    APP_PLUGIN_MULTI_AGENT_CLI_DEGRADED = "app_plugin_multi_agent_cli_degraded"
    FULL_NATIVE_CANDIDATE = "full_native_candidate"


@dataclass
class CapabilityResult:
    """Evidence-backed result for one Codex capability on one surface."""

    status: CapabilityStatus
    surface: CodexSurface
    evidence: str


@dataclass
class CodexCapabilityContract:
    """Capability contract for current Codex app/plugin and CLI surfaces."""

    app_plugin_multi_agent_support: CapabilityResult
    cli_visible_agent_support: CapabilityResult
    ask_user_gate_support: CapabilityResult
    event_frame_support: CapabilityResult
    support_tier: CodexSupportTier

    @classmethod
    def unknown(cls) -> "CodexCapabilityContract":
        return cls(
            app_plugin_multi_agent_support=CapabilityResult(
                status=CapabilityStatus.UNKNOWN,
                surface=CodexSurface.APP_PLUGIN,
                evidence="not probed",
            ),
            cli_visible_agent_support=CapabilityResult(
                status=CapabilityStatus.UNKNOWN,
                surface=CodexSurface.CLI,
                evidence="not probed",
            ),
            ask_user_gate_support=CapabilityResult(
                status=CapabilityStatus.UNKNOWN,
                surface=CodexSurface.CLI,
                evidence="not probed",
            ),
            event_frame_support=CapabilityResult(
                status=CapabilityStatus.UNKNOWN,
                surface=CodexSurface.CLI_STREAM,
                evidence="not probed",
            ),
            support_tier=CodexSupportTier.UNKNOWN,
        )


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
    codex_capabilities:
        Structured Codex app/plugin and CLI capability contract.
    """

    session_resume_flag: Optional[str]
    session_resume_supported: bool
    cross_env_collision_outcome: str
    cross_env_collision_warnings: list[str] = field(default_factory=list)
    codex_path: str = "codex"
    codex_capabilities: CodexCapabilityContract = field(
        default_factory=CodexCapabilityContract.unknown
    )


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
    codex_capabilities = _probe_codex_capabilities(codex_path)

    results = ProbeResults(
        session_resume_flag=session_flag,
        session_resume_supported=session_flag is not None,
        cross_env_collision_outcome=collision_outcome,
        cross_env_collision_warnings=collision_warnings,
        codex_path=codex_path,
        codex_capabilities=codex_capabilities,
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
# Probe 3 — Codex capability contract
# ---------------------------------------------------------------------------

_CLI_AGENT_PATTERN = re.compile(
    r"--[\w-]*(?:agent|subagent)[\w-]*|"
    r"\b(?:agent|agents|subagent|subagents)\s+"
    r"(?:run|list|exec|dispatch|spawn)\b",
    re.IGNORECASE,
)
_ASK_USER_GATE_PATTERN = re.compile(
    # Positive AskUser/gate evidence only. Bypass, sandbox, trust, or generic
    # approval flags are not proof that Codex can stop for a user gate.
    r"(?<![\w-])--(?:ask-user|user-gate|prompt-user|approval-request)(?![\w-])|"
    r"(?<![\w-])(?:ask(?:[-_ \t]+)?user|user[-_ \t]+gate|"
    r"prompt[-_ \t]+user|approval[-_ \t]+request)(?![\w-])",
    re.IGNORECASE,
)
_EVENT_FRAME_PATTERN = re.compile(
    r"--output-format[^\n]*(?:stream-json|jsonl)|"
    r"\b(?:stream-json|jsonl|event[-_\s]?frames?)\b",
    re.IGNORECASE,
)


def _probe_codex_capabilities(codex_path: str) -> CodexCapabilityContract:
    """Probe Codex app/plugin and CLI capability surfaces.

    The app/plugin multi-agent signal is read from ``codex features list`` when
    that command is available.  CLI agent, AskUser/gate, and event-frame signals
    are read from ``codex exec --help``.  Missing commands produce ``unknown``
    rather than a host-wide negative claim.
    """
    features_text, features_exit, features_error = _run_capability_command(
        codex_path, ["features", "list"], timeout=10
    )
    help_text, help_exit, help_error = _run_capability_command(
        codex_path, ["exec", "--help"], timeout=15
    )

    app_plugin_multi_agent = _app_plugin_multi_agent_result(
        features_text, features_exit, features_error
    )
    cli_visible_agent, ask_user_gate, event_frame = _cli_capability_results(
        help_text, help_exit, help_error
    )

    return CodexCapabilityContract(
        app_plugin_multi_agent_support=app_plugin_multi_agent,
        cli_visible_agent_support=cli_visible_agent,
        ask_user_gate_support=ask_user_gate,
        event_frame_support=event_frame,
        support_tier=_classify_codex_support(
            app_plugin_multi_agent,
            cli_visible_agent,
            ask_user_gate,
            event_frame,
        ),
    )


def _run_capability_command(
    codex_path: str, args: list[str], *, timeout: int
) -> tuple[Optional[str], Optional[int], Optional[str]]:
    """Run a lightweight Codex discovery command and capture text output."""
    try:
        proc = subprocess.run(
            [codex_path, *args],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return None, None, f"could not run '{codex_path} {' '.join(args)}': {exc}"

    return (proc.stdout or "") + (proc.stderr or ""), proc.returncode, None


def _app_plugin_multi_agent_result(
    features_text: Optional[str],
    features_exit: Optional[int],
    features_error: Optional[str],
) -> CapabilityResult:
    if features_error is not None:
        return CapabilityResult(
            status=CapabilityStatus.UNKNOWN,
            surface=CodexSurface.APP_PLUGIN,
            evidence=features_error,
        )

    feature_enabled = _feature_enabled(features_text or "", "multi_agent")
    if feature_enabled is True:
        return CapabilityResult(
            status=CapabilityStatus.SUPPORTED,
            surface=CodexSurface.APP_PLUGIN,
            evidence="codex features list reports multi_agent enabled",
        )
    if feature_enabled is False:
        return CapabilityResult(
            status=CapabilityStatus.UNSUPPORTED,
            surface=CodexSurface.APP_PLUGIN,
            evidence="codex features list reports multi_agent disabled",
        )

    if features_exit not in (0, None):
        return CapabilityResult(
            status=CapabilityStatus.UNKNOWN,
            surface=CodexSurface.APP_PLUGIN,
            evidence=(
                f"codex features list exited {features_exit}; "
                "app/plugin multi_agent support unverified"
            ),
        )

    return CapabilityResult(
        status=CapabilityStatus.UNSUPPORTED,
        surface=CodexSurface.APP_PLUGIN,
        evidence="codex features list did not report multi_agent enabled",
    )


def _feature_enabled(features_text: str, feature_name: str) -> Optional[bool]:
    """Return enabled state for a feature-list row, or None when absent."""
    wanted = feature_name.replace("-", "_").lower()
    for raw_line in features_text.splitlines():
        line = raw_line.strip().replace("-", "_").lower()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if not parts or parts[0] != wanted:
            continue
        value_tokens = {
            token.removeprefix("enabled=")
            .removeprefix("stable=")
            .removeprefix("default=")
            for token in parts[1:]
        }
        if value_tokens.intersection({"true", "enabled", "yes"}):
            return True
        if value_tokens.intersection({"false", "disabled", "no"}):
            return False
    return None


def _cli_capability_results(
    help_text: Optional[str],
    help_exit: Optional[int],
    help_error: Optional[str],
) -> tuple[CapabilityResult, CapabilityResult, CapabilityResult]:
    if help_error is not None or not (help_text or "").strip():
        evidence = help_error or f"codex exec --help exited {help_exit} with no output"
        return (
            CapabilityResult(CapabilityStatus.UNKNOWN, CodexSurface.CLI, evidence),
            CapabilityResult(CapabilityStatus.UNKNOWN, CodexSurface.CLI, evidence),
            CapabilityResult(
                CapabilityStatus.UNKNOWN, CodexSurface.CLI_STREAM, evidence
            ),
        )

    text = help_text or ""
    agent_match = _CLI_AGENT_PATTERN.search(text)
    ask_match = _ASK_USER_GATE_PATTERN.search(text)
    event_match = _EVENT_FRAME_PATTERN.search(text)

    cli_visible_agent = CapabilityResult(
        status=CapabilityStatus.SUPPORTED
        if agent_match
        else CapabilityStatus.UNSUPPORTED,
        surface=CodexSurface.CLI,
        evidence=_match_evidence(
            agent_match, "codex exec --help has no agent/subagent flags or commands"
        ),
    )
    ask_user_gate = CapabilityResult(
        status=CapabilityStatus.SUPPORTED
        if ask_match
        else CapabilityStatus.UNSUPPORTED,
        surface=CodexSurface.CLI,
        evidence=_match_evidence(
            ask_match, "codex exec --help has no AskUser/gate markers"
        ),
    )
    event_frame = CapabilityResult(
        status=CapabilityStatus.SUPPORTED
        if event_match
        else CapabilityStatus.UNSUPPORTED,
        surface=CodexSurface.CLI_STREAM,
        evidence=_match_evidence(
            event_match, "codex exec --help has no stream-json/jsonl event output"
        ),
    )
    return cli_visible_agent, ask_user_gate, event_frame


def _match_evidence(match: Optional[re.Match[str]], fallback: str) -> str:
    if match is None:
        return fallback
    token = " ".join(match.group(0).strip().split())
    return f"codex exec --help exposes {token!r}"


def _classify_codex_support(
    app_plugin_multi_agent: CapabilityResult,
    cli_visible_agent: CapabilityResult,
    ask_user_gate: CapabilityResult,
    event_frame: CapabilityResult,
) -> CodexSupportTier:
    statuses = [
        app_plugin_multi_agent.status,
        cli_visible_agent.status,
        ask_user_gate.status,
        event_frame.status,
    ]
    if all(status == CapabilityStatus.UNKNOWN for status in statuses):
        return CodexSupportTier.UNKNOWN

    app_supported = app_plugin_multi_agent.status == CapabilityStatus.SUPPORTED
    cli_agent_supported = cli_visible_agent.status == CapabilityStatus.SUPPORTED
    ask_supported = ask_user_gate.status == CapabilityStatus.SUPPORTED
    event_supported = event_frame.status == CapabilityStatus.SUPPORTED

    if app_supported and cli_agent_supported and ask_supported and event_supported:
        return CodexSupportTier.FULL_NATIVE_CANDIDATE
    if app_supported:
        return CodexSupportTier.APP_PLUGIN_MULTI_AGENT_CLI_DEGRADED
    if cli_agent_supported and ask_supported and event_supported:
        return CodexSupportTier.CLI_NATIVE_CANDIDATE
    if cli_agent_supported or ask_supported:
        return CodexSupportTier.CLI_PARTIAL
    return CodexSupportTier.FLATTENED_CLI


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
