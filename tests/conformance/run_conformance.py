"""
run_conformance.py — Main runner for the z-harness conformance suite.

Invokes each supported driver against a z-command, normalizes the output,
and diffs against golden fixtures to verify cross-driver conformance.

Usage:
    python tests/conformance/run_conformance.py \\
        --command z-do \\
        --mode replay|live \\
        [--record] \\
        [--drivers claude-code,codex,agy,cursor-agent]

Environment variables:
    CONFORMANCE_REPLAY_HOOK   Path to a shim script that wraps driver invocation
                              to inject replay responses when the driver does not
                              natively support replay mode.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

# ---------------------------------------------------------------------------
# Import normalize — works both as a package (from .normalize import ...) and
# as a standalone script (python tests/conformance/run_conformance.py ...).
# ---------------------------------------------------------------------------

_HERE = Path(__file__).parent.resolve()

try:
    from .normalize import normalize_artifact_list, normalize_events  # type: ignore[assignment]
except ImportError:
    _norm_spec = importlib.util.spec_from_file_location("normalize", _HERE / "normalize.py")
    assert _norm_spec is not None and _norm_spec.loader is not None
    _norm_mod = importlib.util.module_from_spec(_norm_spec)
    _norm_spec.loader.exec_module(_norm_mod)  # type: ignore[union-attr]
    normalize_events: Callable[[str], str] = _norm_mod.normalize_events  # type: ignore[assignment]
    normalize_artifact_list: Callable[[list[str]], list[str]] = _norm_mod.normalize_artifact_list  # type: ignore[assignment]

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_FIXTURES_ROOT = _HERE / "fixtures"
_REPLAY_ROOT = _HERE / "replay"

# ---------------------------------------------------------------------------
# Driver registry: logical name -> binary name
# ---------------------------------------------------------------------------

_DRIVER_BINARIES: dict[str, str] = {
    "claude-code": "claude",
    "codex": "codex",
    "agy": "agy",
    "cursor-agent": "cursor-agent",
}

_ALL_DRIVERS = list(_DRIVER_BINARIES.keys())

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _emit(event: dict) -> None:
    """Write a single conformance event to stdout as JSONL."""
    sys.stdout.write(json.dumps(event, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def _driver_available(driver: str) -> bool:
    """Return True if the driver binary is on PATH."""
    binary = _DRIVER_BINARIES[driver]
    return shutil.which(binary) is not None


def _fixture_dir(command: str, driver: str) -> Path:
    return _FIXTURES_ROOT / command / driver


def _replay_path(command: str, driver: str) -> Path:
    return _REPLAY_ROOT / command / f"{driver}.jsonl"


# ---------------------------------------------------------------------------
# Driver invocation stub
# ---------------------------------------------------------------------------


def invoke_driver(
    driver_name: str,
    command: str,
    prompt: str,
    mode: str,
    replay_path: Optional[Path],
) -> tuple[str, list[str], int]:
    """Invoke a driver and return (events_jsonl, artifact_paths, exit_code).

    For spawn-based drivers (codex, agy, cursor-agent): uses subprocess.run.
    For claude-code: placeholder — returns canned empty values until the
    in-process hook is wired up (C1/C2 dependency).

    In replay mode the CONFORMANCE_REPLAY_HOOK env var (if set) is forwarded
    as a wrapper shim; otherwise CONFORMANCE_REPLAY_FILE is exported so that
    drivers that natively consume it can use the recorded response feed.

    Returns:
        (events_jsonl_str, artifact_path_list, exit_code)
    """
    binary = _DRIVER_BINARIES[driver_name]
    replay_hook = os.environ.get("CONFORMANCE_REPLAY_HOOK")

    if driver_name == "claude-code":
        # Placeholder: in-process invocation path not yet implemented.
        # Returns empty events + empty artifacts so that the diff step will
        # fail against any non-empty golden fixture — fail-by-design until
        # wired via C1/C2.
        return ("", [], 0)

    # Build the command argv for spawn-based drivers.
    if replay_hook and mode == "replay":
        argv = [replay_hook, binary, command]
    else:
        argv = [binary, command]

    env = os.environ.copy()
    if mode == "replay" and replay_path is not None and replay_path.exists():
        env["CONFORMANCE_REPLAY_FILE"] = str(replay_path)

    with tempfile.TemporaryDirectory() as tmpdir:
        events_file = Path(tmpdir) / "events.jsonl"
        env["CONFORMANCE_EVENTS_OUT"] = str(events_file)

        try:
            result = subprocess.run(
                argv,
                env=env,
                cwd=tmpdir,
                capture_output=True,
                text=True,
                timeout=300,
            )
        except FileNotFoundError:
            # Binary disappeared between which-check and run.
            return ("", [], 127)
        except subprocess.TimeoutExpired:
            return ("", [], 124)

        exit_code = result.returncode

        # Read captured events if the driver wrote them.
        if events_file.exists():
            events_jsonl = events_file.read_text(encoding="utf-8")
        else:
            # Fall back to driver stdout.
            events_jsonl = result.stdout

        # Parse artifact paths from driver exit metadata on stdout (best-effort).
        artifact_paths: list[str] = []
        for line in result.stdout.splitlines():
            try:
                obj = json.loads(line)
            except (json.JSONDecodeError, ValueError):
                continue
            if isinstance(obj, dict) and "artifacts" in obj:
                arts = obj["artifacts"]
                if isinstance(arts, list):
                    artifact_paths.extend(str(p) for p in arts)

    return (events_jsonl, artifact_paths, exit_code)


# ---------------------------------------------------------------------------
# Diff helpers
# ---------------------------------------------------------------------------


def _diff_lines(actual: str, expected: str) -> list[str]:
    """Return a compact unified-diff-style line list (no file headers)."""
    import difflib

    actual_lines = actual.splitlines(keepends=True)
    expected_lines = expected.splitlines(keepends=True)
    diff = list(
        difflib.unified_diff(expected_lines, actual_lines, fromfile="golden", tofile="actual", lineterm="")
    )
    return diff


def _exit_matches(actual_code: int, golden_exit: str) -> bool:
    golden = golden_exit.strip()
    if golden == "0":
        return actual_code == 0
    if golden == "nonzero":
        return actual_code != 0
    # Attempt exact integer match.
    try:
        return actual_code == int(golden)
    except ValueError:
        return False


# ---------------------------------------------------------------------------
# Record mode — write fixtures from a live run
# ---------------------------------------------------------------------------


def record_driver(
    driver: str,
    command: str,
    events_jsonl: str,
    artifact_paths: list[str],
    exit_code: int,
) -> None:
    """Write normalized output to both fixtures and replay directories."""
    fix_dir = _fixture_dir(command, driver)
    fix_dir.mkdir(parents=True, exist_ok=True)

    normalized_events = normalize_events(events_jsonl)
    normalized_artifacts = normalize_artifact_list(artifact_paths)

    (fix_dir / "events.golden.jsonl").write_text(normalized_events + "\n", encoding="utf-8")
    artifacts_content = "\n".join(normalized_artifacts)
    (fix_dir / "artifacts.golden.txt").write_text(
        artifacts_content + "\n" if artifacts_content else "", encoding="utf-8"
    )
    exit_str = "0" if exit_code == 0 else "nonzero"
    (fix_dir / "exit.golden").write_text(exit_str + "\n", encoding="utf-8")

    # Write replay feed (raw events for use as mock response in future runs).
    replay_dir = _REPLAY_ROOT / command
    replay_dir.mkdir(parents=True, exist_ok=True)
    (_REPLAY_ROOT / command / f"{driver}.jsonl").write_text(
        events_jsonl, encoding="utf-8"
    )


# ---------------------------------------------------------------------------
# Per-driver test execution
# ---------------------------------------------------------------------------


def run_driver(
    driver: str,
    command: str,
    mode: str,
    record: bool,
    prompt: str,
) -> dict:
    """Run conformance for one driver.  Returns a driver_run_end payload dict."""
    fix_dir = _fixture_dir(command, driver)
    replay_p = _replay_path(command, driver)

    # --- availability check --------------------------------------------------
    if not _driver_available(driver):
        return {
            "driver": driver,
            "command": command,
            "result": "skipped",
            "reason": f"{_DRIVER_BINARIES[driver]} unavailable",
        }

    # --- invoke ---------------------------------------------------------------
    events_jsonl, artifact_paths, exit_code = invoke_driver(
        driver, command, prompt, mode, replay_p
    )

    # --- record mode ----------------------------------------------------------
    if record:
        record_driver(driver, command, events_jsonl, artifact_paths, exit_code)
        return {
            "driver": driver,
            "command": command,
            "result": "pass",
            "reason": "recorded",
        }

    # --- diff against fixtures ------------------------------------------------
    diff_lines: list[str] = []
    reasons: list[str] = []

    # 1. Normalize events and diff.
    normalized_events = normalize_events(events_jsonl)
    golden_events_path = fix_dir / "events.golden.jsonl"
    if golden_events_path.exists():
        golden_events = golden_events_path.read_text(encoding="utf-8").rstrip("\n")
        events_diff = _diff_lines(normalized_events, golden_events)
        if events_diff:
            diff_lines.extend(events_diff[:50])  # cap to avoid huge output
            reasons.append("events diff mismatch")
    else:
        reasons.append(f"missing fixture: {golden_events_path}")

    # 2. Normalize artifact list and diff.
    normalized_artifacts = normalize_artifact_list(artifact_paths)
    golden_artifacts_path = fix_dir / "artifacts.golden.txt"
    if golden_artifacts_path.exists():
        raw_golden_artifacts = golden_artifacts_path.read_text(encoding="utf-8")
        golden_artifacts = [
            line for line in raw_golden_artifacts.splitlines()
            if line and not line.startswith("#")
        ]
        if normalized_artifacts != golden_artifacts:
            diff_lines.extend(_diff_lines("\n".join(normalized_artifacts), "\n".join(golden_artifacts))[:20])
            reasons.append("artifacts diff mismatch")
    else:
        reasons.append(f"missing fixture: {golden_artifacts_path}")

    # 3. Exit code check.
    golden_exit_path = fix_dir / "exit.golden"
    if golden_exit_path.exists():
        golden_exit = golden_exit_path.read_text(encoding="utf-8").strip()
        if not _exit_matches(exit_code, golden_exit):
            reasons.append(f"exit code mismatch: got {exit_code}, expected {golden_exit!r}")
    else:
        reasons.append(f"missing fixture: {golden_exit_path}")

    if reasons:
        payload: dict = {
            "driver": driver,
            "command": command,
            "result": "fail",
            "reason": "; ".join(reasons),
        }
        if diff_lines:
            payload["diff_lines"] = diff_lines
        return payload

    return {
        "driver": driver,
        "command": command,
        "result": "pass",
    }


# ---------------------------------------------------------------------------
# Main runner
# ---------------------------------------------------------------------------


def run_conformance(
    command: str,
    mode: str,
    drivers: list[str],
    record: bool,
    prompt: str,
) -> int:
    """Execute conformance for all requested drivers.

    Returns 0 if all non-skipped drivers pass, 1 otherwise.
    """
    run_id = f"{datetime.now(tz=timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-conformance-{uuid.uuid4().hex[:8]}"

    _emit(
        {
            "type": "conformance_run_start",
            "timestamp": _now_iso(),
            "command": command,
            "mode": mode,
            "drivers": drivers,
            "run_id": run_id,
        }
    )

    passed = 0
    failed = 0
    skipped = 0

    for driver in drivers:
        _emit(
            {
                "type": "driver_run_start",
                "timestamp": _now_iso(),
                "driver": driver,
                "command": command,
                "mode": mode,
            }
        )

        result = run_driver(driver, command, mode, record, prompt)
        outcome = result.get("result", "fail")

        end_event = {
            "type": "driver_run_end",
            "timestamp": _now_iso(),
            **result,
        }
        _emit(end_event)

        if outcome == "pass":
            passed += 1
        elif outcome == "skipped":
            skipped += 1
        else:
            failed += 1

    total = passed + failed + skipped
    _emit(
        {
            "type": "conformance_run_end",
            "timestamp": _now_iso(),
            "command": command,
            "passed": passed,
            "failed": failed,
            "skipped": skipped,
            "total": total,
        }
    )

    return 0 if failed == 0 else 1


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run z-harness conformance suite against one or more drivers.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent(
            """\
            Examples:
              python tests/conformance/run_conformance.py --command z-do --mode replay
              python tests/conformance/run_conformance.py --command z-do --mode live --record --drivers claude-code
            """
        ),
    )
    parser.add_argument(
        "--command",
        required=True,
        help="z-command to test, e.g. z-do",
    )
    parser.add_argument(
        "--mode",
        choices=["replay", "live"],
        required=True,
        help="replay: use recorded fixtures as mock responses; live: call real LLM",
    )
    parser.add_argument(
        "--record",
        action="store_true",
        default=False,
        help="Run live driver and write output to fixtures and replay dirs",
    )
    parser.add_argument(
        "--drivers",
        default=",".join(_ALL_DRIVERS),
        help=(
            "Comma-separated list of drivers to test "
            f"(default: {','.join(_ALL_DRIVERS)})"
        ),
    )
    parser.add_argument(
        "--prompt",
        default="echo hello",
        help="Prompt / task string to pass to the driver (default: 'echo hello')",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    raw_drivers = [d.strip() for d in args.drivers.split(",") if d.strip()]
    unknown = [d for d in raw_drivers if d not in _DRIVER_BINARIES]
    if unknown:
        print(
            f"error: unknown driver(s): {', '.join(unknown)}. "
            f"Valid choices: {', '.join(_ALL_DRIVERS)}",
            file=sys.stderr,
        )
        return 2

    if args.record and args.mode != "live":
        print("error: --record requires --mode live", file=sys.stderr)
        return 2

    return run_conformance(
        command=args.command,
        mode=args.mode,
        drivers=raw_drivers,
        record=args.record,
        prompt=args.prompt,
    )


if __name__ == "__main__":
    sys.exit(main())
