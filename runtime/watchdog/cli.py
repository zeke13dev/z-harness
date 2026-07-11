"""Argparse CLI for the session-watchdog daemon.

Purpose (T013, criterion #6): wire ``python3 -m runtime.watchdog.cli fanout
<root-slug>`` to ``fanout.run_fanout``, resolving the real production defaults
so the fanout logic itself stays free of CLI/subprocess concerns:

- the plan directory is resolved via the sibling ``scripts/plan-path.sh``
  resolver (STYLE.md:P-004 — shell out rather than reimplement the base-dir
  precedence chain);
- the registry path defaults to the daemon's documented state directory
  (``~/.local/state/z-harness/watchdog/sessions.json``, INTENT.md), overridable
  via ``--registry-path`` for tests/tooling.

Also (T019, criterion #1): ``status`` and ``run [--once]`` subcommands. Both
stay thin argparse wiring over already-composed primitives — ``status.py``
for the read side, ``daemon.run_startup_reconcile``/``daemon.run_poll_pass``
for the write side — so no business logic lives in this file (mirrors
``cmd_fanout``'s own thin-wrapper shape).

Design decisions:
- Origin-record resolution: the CLI looks up the existing root session record
  for ``root_slug`` in the registry (the record with ``slug == root_slug`` and
  ``parent_id is None`` — the session the daemon is already tracking for this
  plan) rather than inventing a new registration flow. If none exists, the CLI
  hard-fails with an actionable message: fanout only makes sense once a daemon
  is already watching a root session for this slug.
- Host-adapter selection (``select_adapter``) lives here, not in
  ``daemon.py``: ``daemon.run_poll_pass`` takes an injected
  ``adapter_for_host`` callable and stays host-agnostic (DI-seam discipline
  every sibling module already follows); this CLI is the one place that
  actually knows about ``ClaudeAdapter``/``CodexAdapter``/``OmpAdapter``.
- ``run`` without ``--once`` loops indefinitely (``time.sleep``'d
  ``watchdog.poll_interval_s`` between passes, SIGTERM-flushed via
  ``daemon.install_sigterm_handler``) — the INTENT's own "Consider for this"
  section frames ``--once`` as the mode external schedulers (launchd/cron)
  use, implying bare ``run`` is the standing daemon process. Both modes
  dispatch through the exact same ``daemon.run_poll_pass`` pass, so the
  looping wrapper itself carries no independent business logic to test beyond
  what the ``--once`` path already exercises.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path

from runtime.watchdog import daemon, fanout, notify, poll, registry, status, tmux_actuator
from runtime.watchdog.adapters import ClaudeAdapter, CodexAdapter, OmpAdapter
from runtime.watchdog.adapters.base import HostAdapter

_REPO_ROOT = Path(__file__).resolve().parents[2]
PLAN_PATH_SH = _REPO_ROOT / "scripts" / "plan-path.sh"

DEFAULT_STATE_DIR = Path.home() / ".local" / "state" / "z-harness" / "watchdog"
DEFAULT_REGISTRY_PATH = DEFAULT_STATE_DIR / "sessions.json"
DEFAULT_LOCK_PATH = DEFAULT_STATE_DIR / "daemon.lock"
DEFAULT_HEARTBEAT_PATH = DEFAULT_STATE_DIR / "heartbeat"
DEFAULT_SIGNALS_PATH = DEFAULT_STATE_DIR / "signals.jsonl"

PLAN_PATH_TIMEOUT_S = 10.0
"""Subprocess timeout (seconds) for the ``plan-path.sh`` resolver call."""

_ADAPTER_FACTORIES: dict[str, Callable[[], HostAdapter]] = {
    "claude": ClaudeAdapter,
    "codex": CodexAdapter,
    "omp": OmpAdapter,
}
"""Session record ``host`` -> ``HostAdapter`` factory (T019, criterion #1)."""


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


def select_adapter(host: str) -> HostAdapter:
    """Return a fresh ``HostAdapter`` instance for ``host``. Hard-fail.

    Args:
        host: A session record's ``host`` field (``"claude"``/``"codex"``/
            ``"omp"``).

    Returns:
        A new adapter instance (adapters are cheap, stateless-per-call
        objects — see each adapter's own constructor).

    Raises:
        CliError: if ``host`` has no registered adapter — a session record
            naming an unknown host is a data-integrity problem, not a
            transient condition to degrade from.
    """
    try:
        factory = _ADAPTER_FACTORIES[host]
    except KeyError:
        raise CliError(f"no HostAdapter registered for host {host!r}") from None
    return factory()


def cmd_status(args: argparse.Namespace) -> int:
    """Run the ``status`` subcommand: print registered sessions + heartbeat age.

    Composes ``status.compute_status`` (T018) and renders its result as one
    line per registered session (``session_id``/``slug``/``host``/``state``)
    plus a leading heartbeat-age line — ``"unknown"`` when the heartbeat file
    is absent (``heartbeat_age_s is None``).

    Returns:
        ``0`` always — a missing/corrupt registry or heartbeat file degrades
        gracefully via ``compute_status``'s own best-effort contract rather
        than failing the command.
    """
    result = status.compute_status(args.registry_path, args.heartbeat_path)
    heartbeat_age = result["heartbeat_age_s"]
    heartbeat_display = "unknown" if heartbeat_age is None else f"{heartbeat_age:.1f}"
    print(f"heartbeat_age_s: {heartbeat_display}")
    for entry in result["sessions"]:
        print(
            f"{entry['session_id']} slug={entry['slug']} host={entry['host']} "
            f"state={entry['state']}"
        )
    return 0


def _run_once(
    registry_path: Path,
    lock_path: Path,
    heartbeat_path: Path,
    signals_path: Path,
    *,
    get_config_int: Callable[[str], int],
    capture_pane: Callable[..., str],
    poll_session: Callable[..., dict],
) -> dict[str, dict]:
    """Acquire the lock, run one poll pass, touch the heartbeat, release.

    Composes ``daemon.run_lifecycle`` (single-instance lock) around
    ``daemon.run_poll_pass`` (knob resolution + per-session capture+dispatch,
    T019 criterion #1) and ``daemon.touch_heartbeat`` — the exact sequence
    both ``run --once`` and each iteration of the non-``--once`` loop use.

    Args:
        registry_path: Path to ``sessions.json``.
        lock_path: Path to the daemon single-instance pidfile+lock.
        heartbeat_path: Path to the daemon heartbeat file.
        signals_path: Path to ``signals.jsonl``.
        get_config_int: Forwarded to ``daemon.run_poll_pass``.
        capture_pane: Forwarded to ``daemon.run_poll_pass``.
        poll_session: Forwarded to ``daemon.run_poll_pass``.

    Returns:
        The post-pass ``session_id`` -> record mapping.

    Raises:
        DaemonAlreadyRunningError: propagated verbatim (via
            ``daemon.run_lifecycle``) when a live daemon already holds the
            lock.
    """
    with daemon.run_lifecycle(lock_path):
        sessions = registry.read_registry(registry_path)
        sessions = daemon.run_poll_pass(
            sessions,
            registry_path=registry_path,
            signals_path=signals_path,
            repo_root=_REPO_ROOT,
            adapter_for_host=select_adapter,
            get_config_int=get_config_int,
            capture_pane=capture_pane,
            poll_session=poll_session,
        )
        daemon.touch_heartbeat(heartbeat_path)
        return sessions


def cmd_run(
    args: argparse.Namespace,
    *,
    has_session: Callable[..., bool] = tmux_actuator.has_session,
    alert_fn: Callable[..., bool] = notify.send_discord_alert,
    get_config_int: Callable[[str], int] = registry.get_config_int,
    capture_pane: Callable[..., str] = tmux_actuator.capture_pane,
    poll_session: Callable[..., dict] = poll.poll_session,
) -> int:
    """Run the ``run [--once]`` subcommand.

    Always runs ``daemon.run_startup_reconcile`` first (T017: orphans
    dead-target records before any poll cycle sees them), then one poll pass
    via ``_run_once``. With ``--once`` the command exits after that single
    pass; otherwise it loops indefinitely, sleeping
    ``watchdog.poll_interval_s`` between passes, with a SIGTERM handler
    installed (``daemon.install_sigterm_handler``) so a shutdown signal
    flushes the current in-memory mapping before exit (see module docstring).

    The trailing keyword-only arguments mirror every composed module's own
    DI-seam discipline: ``args.func(args)`` (the real argparse dispatch path
    in ``main``) always uses the real defaults; tests call ``cmd_run``
    directly with fakes so no test touches a real tmux pane, provider CLI, or
    webhook (STYLE.md:T-002).

    Args:
        args: Parsed CLI arguments (``registry_path``/``lock_path``/
            ``heartbeat_path``/``signals_path``/``once``).
        has_session: Injected ``tmux_actuator.has_session``-shaped callable,
            forwarded to ``daemon.run_startup_reconcile``.
        alert_fn: Injected ``notify.send_discord_alert``-shaped callable,
            forwarded to ``daemon.run_startup_reconcile``.
        get_config_int: Injected ``registry.get_config_int``-shaped callable.
        capture_pane: Injected ``tmux_actuator.capture_pane``-shaped callable.
        poll_session: Injected ``poll.poll_session``-shaped callable.

    Returns:
        The process exit code (``0`` on success, ``1`` on a user-facing
        failure — currently only ``DaemonAlreadyRunningError``/``CliError``).
    """
    registry_path = Path(args.registry_path)
    lock_path = Path(args.lock_path)
    heartbeat_path = Path(args.heartbeat_path)
    signals_path = Path(args.signals_path)

    try:
        sessions = daemon.run_startup_reconcile(
            registry_path, lock_path, has_session=has_session, alert_fn=alert_fn,
        )
        sessions = _run_once(
            registry_path, lock_path, heartbeat_path, signals_path,
            get_config_int=get_config_int,
            capture_pane=capture_pane,
            poll_session=poll_session,
        )
    except (registry.DaemonAlreadyRunningError, CliError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    if args.once:
        return 0

    poll_interval_s = get_config_int("watchdog.poll_interval_s")
    daemon.install_sigterm_handler(lambda: sessions, registry_path)
    while True:
        time.sleep(poll_interval_s)
        try:
            sessions = _run_once(
                registry_path, lock_path, heartbeat_path, signals_path,
                get_config_int=get_config_int,
                capture_pane=capture_pane,
                poll_session=poll_session,
            )
        except registry.DaemonAlreadyRunningError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI's argparse parser (``fanout``/``status``/``run`` subcommands)."""
    parser = argparse.ArgumentParser(
        prog="python3 -m runtime.watchdog.cli",
        description="Session-watchdog daemon CLI.",
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

    status_parser = subparsers.add_parser(
        "status", help="Report registered sessions plus daemon heartbeat age"
    )
    status_parser.add_argument(
        "--registry-path",
        dest="registry_path",
        default=str(DEFAULT_REGISTRY_PATH),
        help=f"Path to sessions.json (default: {DEFAULT_REGISTRY_PATH})",
    )
    status_parser.add_argument(
        "--heartbeat-path",
        dest="heartbeat_path",
        default=str(DEFAULT_HEARTBEAT_PATH),
        help=f"Path to the daemon heartbeat file (default: {DEFAULT_HEARTBEAT_PATH})",
    )
    status_parser.set_defaults(func=cmd_status)

    run_parser = subparsers.add_parser(
        "run", help="Run one (--once) or repeated poll pass(es) over registered sessions"
    )
    run_parser.add_argument(
        "--once",
        dest="once",
        action="store_true",
        help="Perform exactly one poll pass and exit, instead of looping",
    )
    run_parser.add_argument(
        "--registry-path",
        dest="registry_path",
        default=str(DEFAULT_REGISTRY_PATH),
        help=f"Path to sessions.json (default: {DEFAULT_REGISTRY_PATH})",
    )
    run_parser.add_argument(
        "--lock-path",
        dest="lock_path",
        default=str(DEFAULT_LOCK_PATH),
        help=f"Path to the daemon single-instance lock (default: {DEFAULT_LOCK_PATH})",
    )
    run_parser.add_argument(
        "--heartbeat-path",
        dest="heartbeat_path",
        default=str(DEFAULT_HEARTBEAT_PATH),
        help=f"Path to the daemon heartbeat file (default: {DEFAULT_HEARTBEAT_PATH})",
    )
    run_parser.add_argument(
        "--signals-path",
        dest="signals_path",
        default=str(DEFAULT_SIGNALS_PATH),
        help=f"Path to signals.jsonl (default: {DEFAULT_SIGNALS_PATH})",
    )
    run_parser.set_defaults(func=cmd_run)

    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI entry point."""
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
