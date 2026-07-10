"""Minimal argparse seed CLI for the session-watchdog daemon.

Purpose (T013, criterion #6): wire ``python3 -m runtime.watchdog.cli fanout
<root-slug>`` to ``fanout.run_fanout``, resolving the real production defaults
so the fanout logic itself stays free of CLI/subprocess concerns:

- the plan directory is resolved via the sibling ``scripts/plan-path.sh``
  resolver (STYLE.md:P-004 — shell out rather than reimplement the base-dir
  precedence chain);
- the registry path defaults to the daemon's documented state directory
  (``~/.local/state/z-harness/watchdog/sessions.json``, INTENT.md), overridable
  via ``--registry-path`` for tests/tooling.

This file is the seed CLI: a later level extends it with ``status``/``run``
subcommands (no other level-1 task touches this file — execution-strategy.md).

Design decisions:
- Origin-record resolution: the CLI looks up the existing root session record
  for ``root_slug`` in the registry (the record with ``slug == root_slug`` and
  ``parent_id is None`` — the session the daemon is already tracking for this
  plan) rather than inventing a new registration flow. If none exists, the CLI
  hard-fails with an actionable message: fanout only makes sense once a daemon
  is already watching a root session for this slug.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from runtime.watchdog import fanout, registry

_REPO_ROOT = Path(__file__).resolve().parents[2]
PLAN_PATH_SH = _REPO_ROOT / "scripts" / "plan-path.sh"

DEFAULT_STATE_DIR = Path.home() / ".local" / "state" / "z-harness" / "watchdog"
DEFAULT_REGISTRY_PATH = DEFAULT_STATE_DIR / "sessions.json"

PLAN_PATH_TIMEOUT_S = 10.0
"""Subprocess timeout (seconds) for the ``plan-path.sh`` resolver call."""


class CliError(RuntimeError):
    """A user-facing CLI failure (bad slug, no origin session, ...). Hard-fail."""


def resolve_plan_dir(root_slug: str, *, timeout: float = PLAN_PATH_TIMEOUT_S) -> Path:
    """Resolve ``root_slug`` to its plan directory via ``scripts/plan-path.sh``.

    Shells out to the sibling resolver (STYLE.md:P-004) rather than
    reimplementing its base-dir precedence chain.

    Args:
        root_slug: The ``/z-plan-split`` root slug.
        timeout: Subprocess timeout in seconds.

    Returns:
        The resolved, existing plan directory.

    Raises:
        CliError: if the resolver fails, times out, or the resolved directory
            does not exist.
    """
    try:
        result = subprocess.run(
            ["bash", str(PLAN_PATH_SH), "resolve_plan_path", root_slug],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        raise CliError(f"plan-path.sh resolve_plan_path failed: {exc}") from exc
    if result.returncode != 0:
        raise CliError(
            f"plan-path.sh resolve_plan_path {root_slug!r} failed: "
            f"{result.stderr.strip()}"
        )
    plan_dir = Path(result.stdout.strip())
    if not plan_dir.is_dir():
        raise CliError(f"resolved plan directory does not exist: {plan_dir}")
    return plan_dir


def find_origin_record(sessions: dict[str, dict], root_slug: str) -> dict:
    """Return the root session record for ``root_slug`` (``parent_id is None``).

    Args:
        sessions: The registry's session mapping (``registry.read_registry``).
        root_slug: The ``/z-plan-split`` root slug.

    Returns:
        The matching root session record.

    Raises:
        CliError: if no matching record is registered.
    """
    for record in sessions.values():
        if record.get("slug") == root_slug and record.get("parent_id") is None:
            return record
    raise CliError(
        f"no registered root session found for slug {root_slug!r}; "
        "the watchdog must be tracking a root session before fanout can run"
    )


def cmd_fanout(args: argparse.Namespace) -> int:
    """Run the ``fanout <root-slug>`` subcommand.

    Returns:
        The process exit code (``0`` on success, ``1`` on a user-facing
        failure).
    """
    registry_path = Path(args.registry_path)
    try:
        plan_dir = resolve_plan_dir(args.root_slug)
        sessions = registry.read_registry(registry_path)
        origin_record = find_origin_record(sessions, args.root_slug)
        _sessions, child_records = fanout.run_fanout(plan_dir, origin_record, registry_path)
    except (CliError, fanout.ManifestParseError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"spawned {len(child_records)} cluster session(s) for {args.root_slug!r}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    """Build the seed CLI's argparse parser (``fanout`` subcommand only)."""
    parser = argparse.ArgumentParser(
        prog="python3 -m runtime.watchdog.cli",
        description="Session-watchdog daemon CLI (seed: fanout only).",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    fanout_parser = subparsers.add_parser(
        "fanout", help="Spawn one child tmux session per /z-plan-split MANIFEST cluster"
    )
    fanout_parser.add_argument("root_slug", help="The /z-plan-split root slug to fan out")
    fanout_parser.add_argument(
        "--registry-path",
        dest="registry_path",
        default=str(DEFAULT_REGISTRY_PATH),
        help=f"Path to sessions.json (default: {DEFAULT_REGISTRY_PATH})",
    )
    fanout_parser.set_defaults(func=cmd_fanout)

    return parser


def main(argv: list[str] | None = None) -> int:
    """Seed CLI entry point."""
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
