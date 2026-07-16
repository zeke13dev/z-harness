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

The opt-in root lifecycle surface is a versioned JSON contract:
``register`` stores a normalized manifest under a stable path-derived key,
``ensure`` starts at most one standing daemon, ``status`` reports registry and
daemon authority, and ``stop`` releases daemon process authority without
rewriting registry state. ``run [--once]`` remains the internal daemon entry.

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
- ``run`` without ``--once`` holds the daemon flock for its full lifetime and
  persists each poll mutation immediately. Default SIGTERM termination is
  therefore a safe stop boundary that does not rewrite registered authority.
"""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import signal
import subprocess
import sys
import time
from collections.abc import Callable
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from runtime.watchdog import (
    daemon,
    fanout,
    handoff,
    notify,
    planning_ingress,
    poll,
    registry,
    status,
    tmux_actuator,
)
from runtime.watchdog.adapters import ClaudeAdapter, CodexAdapter, OmpAdapter
from runtime.watchdog.adapters.base import HostAdapter

_REPO_ROOT = Path(__file__).resolve().parents[2]
PLAN_PATH_SH = _REPO_ROOT / "scripts" / "plan-path.sh"

DEFAULT_STATE_DIR = Path.home() / ".local" / "state" / "z-harness" / "watchdog"
DEFAULT_REGISTRY_PATH = DEFAULT_STATE_DIR / "sessions.json"
DEFAULT_LOCK_PATH = DEFAULT_STATE_DIR / "daemon.lock"
DEFAULT_HEARTBEAT_PATH = DEFAULT_STATE_DIR / "heartbeat"
DEFAULT_SIGNALS_PATH = DEFAULT_STATE_DIR / "signals.jsonl"
CLI_SCHEMA_VERSION = 1
DAEMON_START_TIMEOUT_S = 5.0
DAEMON_STOP_TIMEOUT_S = 5.0
_MANAGED_START_FD_ENV = "Z_HARNESS_WATCHDOG_LIFECYCLE_FD"

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


class LifecycleCliError(CliError):
    """A stable machine-readable lifecycle CLI failure."""

    def __init__(self, code: str, message: str, exit_code: int) -> None:
        super().__init__(message)
        self.code = code
        self.exit_code = exit_code


class JsonArgumentParser(argparse.ArgumentParser):
    """Argument parser whose failures obey the versioned JSON contract."""

    def error(self, message: str) -> None:
        print(json.dumps({
            "schema_version": CLI_SCHEMA_VERSION,
            "ok": False,
            "error": {"code": "invalid_arguments", "message": message},
        }, sort_keys=True))
        raise SystemExit(2)


def _print_success(command: str, result: dict[str, object]) -> None:
    """Print one successful lifecycle result as compact versioned JSON."""
    print(json.dumps({
        "schema_version": CLI_SCHEMA_VERSION,
        "ok": True,
        "command": command,
        "result": result,
    }, sort_keys=True, separators=(",", ":")))


def _print_error(error: LifecycleCliError) -> None:
    """Print one stable lifecycle error result as compact versioned JSON."""
    print(json.dumps({
        "schema_version": CLI_SCHEMA_VERSION,
        "ok": False,
        "error": {"code": error.code, "message": str(error)},
    }, sort_keys=True, separators=(",", ":")))


def _delivery_payload(result: notify.DeliveryResult) -> dict[str, str | None]:
    """Return the explicit public subset of a lifecycle delivery result."""
    return {
        "status": result.status,
        "event_id": result.event_id,
        "delivery_class": result.delivery_class,
    }


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
    """Print authoritative lifecycle status as versioned JSON.

    Args:
        args: Parsed registry, heartbeat, and daemon-lock paths.

    Returns:
        Zero on success. Registry errors are translated by ``main``.

    Raises:
        RegistryFormatError: if authoritative state is malformed or future.
        OSError: on an authoritative read failure.
    """
    result = status.compute_status(
        args.registry_path,
        args.heartbeat_path,
        getattr(args, "lock_path", DEFAULT_LOCK_PATH),
    )
    _print_success("status", result)
    return 0


def cmd_register(args: argparse.Namespace) -> int:
    """Register one normalized opt-in root manifest idempotently.

    Args:
        args: Parsed manifest and registry paths.

    Returns:
        Zero on a new registration or exact replay.

    Raises:
        LifecycleCliError: for an invalid manifest or identity conflict.
        RegistryFormatError: if authoritative state is malformed or future.
    """
    manifest_path = Path(args.manifest_path)
    try:
        manifest = planning_ingress.load_opt_in_manifest(manifest_path)
    except (ValueError, OSError) as exc:
        raise LifecycleCliError("invalid_manifest", str(exc), 2) from exc
    idempotency_key = registry.root_idempotency_key(manifest_path)
    try:
        registration, replayed = registry.register_root_manifest(
            args.registry_path,
            idempotency_key=idempotency_key,
            manifest=manifest,
        )
    except registry.RootRegistrationConflictError as exc:
        raise LifecycleCliError("idempotency_conflict", str(exc), 3) from exc
    _print_success("register", {
        "coordinator_id": registration["coordinator_id"],
        "idempotency_key": registration["idempotency_key"],
        "manifest_sha256": registration["manifest_sha256"],
        "replayed": replayed,
        "state": registration["state"],
    })
    return 0


def cmd_report_outcome(
    args: argparse.Namespace,
    *,
    lifecycle_notify: Callable[..., notify.DeliveryResult] = (
        notify.deliver_lifecycle_notification
    ),
) -> int:
    """Authorize and commit one child terminal report, then notify fail-open."""
    if args.schema_version != registry.CHILD_OUTCOME_SCHEMA_VERSION:
        raise LifecycleCliError(
            "unsupported_outcome_version",
            f"unsupported child outcome schema version {args.schema_version}",
            2,
        )
    try:
        evidence = json.loads(args.evidence_json)
    except json.JSONDecodeError as exc:
        raise LifecycleCliError("invalid_outcome", "evidence must be valid JSON", 2) from exc
    if not isinstance(evidence, dict):
        raise LifecycleCliError("invalid_outcome", "evidence must be a JSON object", 2)
    try:
        outcome, replayed = registry.report_child_outcome(
            args.registry_path,
            child_id=args.child_id,
            generation=args.generation,
            reporter_id=args.reporter_id,
            report_capability=args.report_capability,
            state=args.state,
            evidence=evidence,
        )
    except registry.UnauthorizedChildReporterError as exc:
        raise LifecycleCliError("unauthorized_reporter", str(exc), 3) from exc
    except registry.StaleChildGenerationError as exc:
        raise LifecycleCliError("stale_generation", str(exc), 3) from exc
    except registry.ChildOutcomeConflictError as exc:
        raise LifecycleCliError("outcome_conflict", str(exc), 3) from exc
    except registry.ChildOutcomeError as exc:
        raise LifecycleCliError("invalid_outcome", str(exc), 2) from exc

    delivery = None
    claimed = registry.claim_child_outcome_notification(
        args.registry_path, str(outcome["outcome_id"])
    )
    if claimed is not None:
        event = notify.child_outcome_notification(claimed)
        result = lifecycle_notify(event)
        registry.finish_child_outcome_notification(
            args.registry_path,
            str(outcome["outcome_id"]),
            status=result.status,
            attempt=int(claimed["notification_attempts"]),
        )
        delivery = _delivery_payload(result)
    _print_success("report-outcome", {
        "outcome_id": outcome["outcome_id"],
        "child_id": outcome["child_id"],
        "generation": outcome["generation"],
        "state": outcome["state"],
        "replayed": replayed,
        "notification": delivery,
    })
    return 0


def cmd_seal_group(args: argparse.Namespace) -> int:
    """Seal one registration epoch through the versioned lifecycle CLI."""
    try:
        group, replayed = registry.seal_group(
            args.registry_path, args.group_id, epoch=args.epoch
        )
    except registry.GroupAdmissionError as exc:
        raise LifecycleCliError("group_seal_conflict", str(exc), 3) from exc
    _print_success("seal-group", {
        "group_id": group["group_id"],
        "epoch": group["epoch"],
        "state": group["state"],
        "join_id": group["join_id"],
        "replayed": replayed,
    })
    return 0


def cmd_ack_join(args: argparse.Namespace) -> int:
    """Generation-fence and deduplicate coordinator join acknowledgement."""
    try:
        outbox, replayed = registry.acknowledge_join_wake(
            args.registry_path,
            args.outbox_id,
            coordinator_generation=args.coordinator_generation,
        )
    except registry.StaleCoordinatorGenerationError as exc:
        raise LifecycleCliError("stale_coordinator_generation", str(exc), 3) from exc
    except ValueError as exc:
        raise LifecycleCliError("invalid_join_ack", str(exc), 2) from exc
    _print_success("ack-join", {
        "outbox_id": outbox["outbox_id"],
        "join_id": outbox["join_id"],
        "state": outbox["state"],
        "replayed": replayed,
    })
    return 0


def cmd_rollover_coordinator(
    args: argparse.Namespace,
    *,
    lifecycle_notify: Callable[..., notify.DeliveryResult] = (
        notify.deliver_lifecycle_notification
    ),
) -> int:
    """Commit a generation-fenced coordinator rollover and notify fail-open."""
    try:
        rollover, replayed, handoff_path = handoff.rollover_coordinator(
            args.registry_path,
            session_id=args.session_id,
            expected_generation=args.expected_generation,
            target=args.target,
            transcript_path=args.transcript_path,
        )
    except registry.StaleCoordinatorRolloverError as exc:
        raise LifecycleCliError("stale_coordinator_generation", str(exc), 3) from exc
    except registry.CoordinatorRolloverConflictError as exc:
        raise LifecycleCliError("rollover_conflict", str(exc), 3) from exc
    except ValueError as exc:
        raise LifecycleCliError("invalid_rollover", str(exc), 2) from exc
    # Rollover is deliberately best-effort/at-most-once. A replay restores
    # authority but must not redeliver the same stable lifecycle event.
    delivery = None if replayed else _delivery_payload(lifecycle_notify(
        notify.coordinator_rollover_notification(rollover)
    ))
    _print_success("rollover-coordinator", {
        "rollover_id": rollover["rollover_id"],
        "logical_coordinator_id": rollover["logical_coordinator_id"],
        "to_generation": rollover["to_generation"],
        "handoff_path": str(handoff_path),
        "replayed": replayed,
        "notification": delivery,
    })
    return 0


def _daemon_argv(args: argparse.Namespace) -> list[str]:
    """Build the standing daemon argv from lifecycle path arguments."""
    return [
        sys.executable,
        "-m",
        "runtime.watchdog.cli",
        "run",
        "--registry-path", str(args.registry_path),
        "--lock-path", str(args.lock_path),
        "--heartbeat-path", str(args.heartbeat_path),
        "--signals-path", str(args.signals_path),
    ]


def _acquire_lifecycle_operation_lock(lock_path: Path | str) -> int:
    """Acquire the ensure/run/stop serialization sidecar and return its fd."""
    operation_path = Path(f"{lock_path}.startup")
    operation_path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(operation_path), os.O_CREAT | os.O_RDWR, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
    except OSError:
        os.close(fd)
        raise
    return fd


def _release_lifecycle_operation_lock(fd: int) -> None:
    """Release one lifecycle-operation fd, preserving its stable pathname."""
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)
    except OSError:
        pass


@contextmanager
def _hold_lifecycle_operation_lock(lock_path: Path | str) -> Iterator[int]:
    """Serialize managed ensure, direct standing run, and stop operations.

    Args:
        lock_path: Daemon lock whose lifecycle ownership is being coordinated.

    Yields:
        The locked descriptor while the private lifecycle-operation flock is held.

    Raises:
        OSError: if the operation lock cannot be created or acquired.
    """
    fd = _acquire_lifecycle_operation_lock(lock_path)
    try:
        yield fd
    finally:
        _release_lifecycle_operation_lock(fd)


def _take_managed_start_fd(lock_path: Path | str) -> int | None:
    """Consume and verify an ensure parent's inherited lock capability.

    A descriptor is accepted only when it names the stable sidecar inode, that
    inode is already locked, and this exact inherited open-file description
    owns the lock. An accepted descriptor is immediately made non-inheritable
    before the caller can resolve configuration or perform lifecycle work.
    Invalid inherited descriptors are closed best-effort and return ``None``
    so the caller joins normal lifecycle serialization.

    Args:
        lock_path: Daemon lock whose sidecar capability is expected.

    Returns:
        The verified inherited descriptor, or ``None`` when absent/invalid.

    Raises:
        OSError: if an accepted descriptor cannot be made non-inheritable. The
            descriptor is closed before the error propagates.
    """
    raw_fd = os.environ.pop(_MANAGED_START_FD_ENV, None)
    if raw_fd is None:
        return None
    try:
        fd = int(raw_fd)
    except ValueError:
        return None
    if fd < 0:
        return None

    valid = False
    probe_fd = None
    try:
        operation_path = Path(f"{lock_path}.startup")
        inherited_stat = os.fstat(fd)
        path_stat = operation_path.stat()
        if (
            inherited_stat.st_dev != path_stat.st_dev
            or inherited_stat.st_ino != path_stat.st_ino
        ):
            return None
        probe_fd = os.open(str(operation_path), os.O_RDWR)
        try:
            fcntl.flock(probe_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            pass
        else:
            fcntl.flock(probe_fd, fcntl.LOCK_UN)
            return None
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return None
        valid = True
    except (OSError, ValueError):
        return None
    finally:
        if probe_fd is not None:
            try:
                os.close(probe_fd)
            except OSError:
                pass
        if not valid and fd > 2:
            try:
                os.close(fd)
            except OSError:
                pass
    try:
        os.set_inheritable(fd, False)
    except OSError:
        try:
            os.close(fd)
        except OSError:
            pass
        raise
    return fd


def cmd_ensure(
    args: argparse.Namespace,
    *,
    popen: Callable[..., subprocess.Popen] | None = None,
    monotonic: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
    lifecycle_notify: Callable[..., notify.DeliveryResult] = (
        notify.deliver_lifecycle_notification
    ),
) -> int:
    """Idempotently ensure exactly one standing daemon is running.

    Args:
        args: Parsed daemon state paths.
        popen: Optional process launcher override for hermetic tests.
        monotonic: Monotonic clock, injectable for tests.
        sleep: Bounded polling wait, injectable for tests.
        lifecycle_notify: Fail-open lifecycle delivery callable invoked only
            after daemon readiness is confirmed.

    Returns:
        Zero when one ready daemon holds the lock.

    Raises:
        LifecycleCliError: if the spawned daemon does not publish readiness.
        OSError: on lock, heartbeat, or process-launch failure.
    """
    popen_fn = popen if popen is not None else subprocess.Popen
    started = False
    incarnation_id = daemon.read_incarnation_id(args.heartbeat_path)
    with _hold_lifecycle_operation_lock(args.lock_path) as operation_fd:
        running, pid = registry.daemon_lock_status(args.lock_path)
        if not running:
            heartbeat_path = Path(args.heartbeat_path)
            try:
                heartbeat_before = heartbeat_path.stat().st_mtime_ns
            except FileNotFoundError:
                heartbeat_before = None
            incarnation_before = daemon.read_incarnation_id(heartbeat_path)
            try:
                child_env = os.environ.copy()
                child_env[_MANAGED_START_FD_ENV] = str(operation_fd)
                popen_fn(
                    _daemon_argv(args),
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True,
                    cwd=_REPO_ROOT,
                    pass_fds=(operation_fd,),
                    env=child_env,
                )
            except OSError as exc:
                raise LifecycleCliError("daemon_start_failed", str(exc), 5) from exc
            deadline = monotonic() + DAEMON_START_TIMEOUT_S
            while monotonic() < deadline:
                running, pid = registry.daemon_lock_status(args.lock_path)
                try:
                    heartbeat_now = heartbeat_path.stat().st_mtime_ns
                except FileNotFoundError:
                    heartbeat_now = None
                incarnation_now = daemon.read_incarnation_id(heartbeat_path)
                if (
                    running
                    and heartbeat_now is not None
                    and heartbeat_now != heartbeat_before
                    and incarnation_now is not None
                    and incarnation_now != incarnation_before
                ):
                    started = True
                    incarnation_id = incarnation_now
                    break
                sleep(0.02)
            if not started:
                raise LifecycleCliError(
                    "daemon_start_failed",
                    "daemon did not acquire its lock and publish a fresh heartbeat",
                    5,
                )
    notification = None
    if started:
        event = notify.lifecycle_notification(
            "daemon",
            {
                "incarnation_id": str(incarnation_id),
                "transition": "started",
            },
            "watchdog daemon started",
            f"pid={pid}",
        )
        notification = _delivery_payload(lifecycle_notify(event))
    _print_success("ensure", {
        "pid": pid,
        "running": True,
        "started": started,
        "notification": notification,
    })
    return 0


def cmd_stop(
    args: argparse.Namespace,
    *,
    kill: Callable[[int, int], None] | None = None,
    monotonic: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
    lifecycle_notify: Callable[..., notify.DeliveryResult] = (
        notify.deliver_lifecycle_notification
    ),
) -> int:
    """Idempotently stop the daemon without mutating registry authority.

    Args:
        args: Parsed daemon state paths.
        kill: Optional signal sender override for hermetic tests.
        monotonic: Monotonic clock, injectable for tests.
        sleep: Bounded polling wait, injectable for tests.
        lifecycle_notify: Fail-open lifecycle delivery callable invoked only
            after the daemon lock is observed released.

    Returns:
        Zero when no daemon remains, including an already-stopped replay.

    Raises:
        LifecycleCliError: if the daemon retains its lock past the deadline.
        OSError: on lock inspection or signal delivery failure.
    """
    kill_fn = kill if kill is not None else os.kill
    with _hold_lifecycle_operation_lock(args.lock_path):
        running, pid = registry.daemon_lock_status(args.lock_path)
        if not running:
            _print_success("stop", {
                "pid": None,
                "running": False,
                "stopped": False,
                "notification": None,
            })
            return 0
        if pid is None or pid <= 0:
            raise LifecycleCliError(
                "daemon_stop_failed", "daemon lock is held without a readable pid", 5
            )
        incarnation_id = daemon.read_incarnation_id(args.heartbeat_path)
        try:
            kill_fn(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        except OSError as exc:
            raise LifecycleCliError("daemon_stop_failed", str(exc), 5) from exc
        deadline = monotonic() + DAEMON_STOP_TIMEOUT_S
        while monotonic() < deadline:
            running, _current_pid = registry.daemon_lock_status(args.lock_path)
            if not running:
                notification = None
                if incarnation_id is not None:
                    event = notify.lifecycle_notification(
                        "daemon",
                        {
                            "incarnation_id": incarnation_id,
                            "transition": "stopped",
                        },
                        "watchdog daemon stopped",
                        f"pid={pid}",
                    )
                    notification = _delivery_payload(lifecycle_notify(event))
                _print_success("stop", {
                    "pid": pid,
                    "running": False,
                    "stopped": True,
                    "notification": notification,
                })
                return 0
            sleep(0.02)
        raise LifecycleCliError("daemon_stop_failed", f"daemon pid {pid} did not stop", 5)


def _run_once(
    registry_path: Path,
    lock_path: Path,
    signals_path: Path,
    *,
    get_config_int: Callable[[str], int],
    capture_pane: Callable[..., str],
    poll_session: Callable[..., dict],
) -> dict[str, dict]:
    """Acquire the lock, run one poll pass, and release without readiness.

    Composes ``daemon.run_lifecycle`` (single-instance lock) around
    ``daemon.run_poll_pass`` (knob resolution + per-session capture+dispatch,
    T019 criterion #1). It intentionally omits ``touch_heartbeat`` because a
    one-shot poll is not a standing daemon readiness authority.

    Args:
        registry_path: Path to ``sessions.json``.
        lock_path: Path to the daemon single-instance pidfile+lock.
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

    With ``--once``, startup reconciliation precedes one poll pass and no
    standing readiness is published. Otherwise the direct command joins the
    lifecycle-operation boundary (unless its managed ``ensure`` parent already
    owns it), acquires the single-instance lock, publishes its incarnation,
    reconciles through the already-held-lock path, then releases operation
    serialization while retaining daemon ownership for the polling loop.

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
    incarnation_id = daemon.new_incarnation_id()

    try:
        if args.once:
            daemon.run_startup_reconcile(
                registry_path, lock_path, has_session=has_session, alert_fn=alert_fn,
            )
            _run_once(
                registry_path, lock_path, signals_path,
                get_config_int=get_config_int,
                capture_pane=capture_pane,
                poll_session=poll_session,
            )
    except (registry.DaemonAlreadyRunningError, CliError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    if args.once:
        return 0

    operation_fd = _take_managed_start_fd(lock_path)
    delegated_operation = operation_fd is not None
    try:
        poll_interval_s = get_config_int("watchdog.poll_interval_s")
        if operation_fd is None:
            operation_fd = _acquire_lifecycle_operation_lock(lock_path)
        with daemon.run_lifecycle(lock_path):
            daemon.touch_heartbeat(heartbeat_path, incarnation_id)
            daemon.run_startup_reconcile(
                registry_path,
                lock_path,
                has_session=has_session,
                alert_fn=alert_fn,
                lifecycle_lock_held=True,
            )
            if operation_fd is not None:
                if delegated_operation:
                    os.close(operation_fd)
                else:
                    _release_lifecycle_operation_lock(operation_fd)
                operation_fd = None
            while True:
                sessions = registry.read_registry(registry_path)
                daemon.run_poll_pass(
                    sessions,
                    registry_path=registry_path,
                    signals_path=signals_path,
                    repo_root=_REPO_ROOT,
                    adapter_for_host=select_adapter,
                    get_config_int=get_config_int,
                    capture_pane=capture_pane,
                    poll_session=poll_session,
                )
                daemon.touch_heartbeat(heartbeat_path, incarnation_id)
                time.sleep(poll_interval_s)
    except registry.DaemonAlreadyRunningError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    finally:
        if operation_fd is not None:
            if delegated_operation:
                try:
                    os.close(operation_fd)
                except OSError:
                    pass
            else:
                _release_lifecycle_operation_lock(operation_fd)


def _add_daemon_paths(parser: argparse.ArgumentParser) -> None:
    """Add the common daemon state path arguments to one subcommand."""
    parser.add_argument("--registry-path", default=str(DEFAULT_REGISTRY_PATH))
    parser.add_argument("--lock-path", default=str(DEFAULT_LOCK_PATH))
    parser.add_argument("--heartbeat-path", default=str(DEFAULT_HEARTBEAT_PATH))
    parser.add_argument("--signals-path", default=str(DEFAULT_SIGNALS_PATH))


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI's argparse parser (``fanout``/``status``/``run`` subcommands)."""
    parser = JsonArgumentParser(
        prog="python3 -m runtime.watchdog.cli",
        description="Session-watchdog daemon CLI.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    register_parser = subparsers.add_parser(
        "register", help="Register a normalized opt-in root manifest"
    )
    register_parser.add_argument("--manifest-path", required=True)
    register_parser.add_argument(
        "--registry-path", default=str(DEFAULT_REGISTRY_PATH)
    )
    register_parser.set_defaults(func=cmd_register)

    outcome_parser = subparsers.add_parser(
        "report-outcome", help="Submit an authorized child terminal outcome"
    )
    outcome_parser.add_argument("--schema-version", required=True, type=int)
    outcome_parser.add_argument("--child-id", required=True)
    outcome_parser.add_argument("--generation", required=True)
    outcome_parser.add_argument("--reporter-id", required=True)
    outcome_parser.add_argument("--report-capability", required=True)
    outcome_parser.add_argument(
        "--state", required=True, choices=sorted(registry.CHILD_OUTCOME_STATES)
    )
    outcome_parser.add_argument("--evidence-json", required=True)
    outcome_parser.add_argument(
        "--registry-path", default=str(DEFAULT_REGISTRY_PATH)
    )
    outcome_parser.set_defaults(func=cmd_report_outcome)

    seal_parser = subparsers.add_parser(
        "seal-group", help="Seal a fanout registration epoch"
    )
    seal_parser.add_argument("--group-id", required=True)
    seal_parser.add_argument("--epoch", required=True, type=int)
    seal_parser.add_argument("--registry-path", default=str(DEFAULT_REGISTRY_PATH))
    seal_parser.set_defaults(func=cmd_seal_group)

    ack_parser = subparsers.add_parser(
        "ack-join", help="Acknowledge one generation-fenced coordinator wake"
    )
    ack_parser.add_argument("--outbox-id", required=True)
    ack_parser.add_argument("--coordinator-generation", required=True)
    ack_parser.add_argument("--registry-path", default=str(DEFAULT_REGISTRY_PATH))
    ack_parser.set_defaults(func=cmd_ack_join)

    rollover_parser = subparsers.add_parser(
        "rollover-coordinator", help="Transfer coordinator authority to a newer incarnation"
    )
    rollover_parser.add_argument("--session-id", required=True)
    rollover_parser.add_argument("--expected-generation", required=True)
    rollover_parser.add_argument("--target", required=True)
    rollover_parser.add_argument("--transcript-path", required=True)
    rollover_parser.add_argument("--registry-path", default=str(DEFAULT_REGISTRY_PATH))
    rollover_parser.set_defaults(func=cmd_rollover_coordinator)

    ensure_parser = subparsers.add_parser(
        "ensure", help="Idempotently ensure one daemon is running"
    )
    _add_daemon_paths(ensure_parser)
    ensure_parser.set_defaults(func=cmd_ensure)

    stop_parser = subparsers.add_parser(
        "stop", help="Idempotently stop the daemon without changing registry state"
    )
    _add_daemon_paths(stop_parser)
    stop_parser.set_defaults(func=cmd_stop)

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
        "--lock-path",
        dest="lock_path",
        default=str(DEFAULT_LOCK_PATH),
        help=f"Path to daemon.lock (default: {DEFAULT_LOCK_PATH})",
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
    try:
        return args.func(args)
    except LifecycleCliError as exc:
        _print_error(exc)
        return exc.exit_code
    except registry.UnsupportedRegistryVersionError as exc:
        error = LifecycleCliError("unsupported_registry_version", str(exc), 4)
        _print_error(error)
        return error.exit_code
    except registry.RegistryFormatError as exc:
        error = LifecycleCliError("malformed_registry", str(exc), 4)
        _print_error(error)
        return error.exit_code
    except OSError as exc:
        error = LifecycleCliError("io_error", str(exc), 5)
        _print_error(error)
        return error.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
