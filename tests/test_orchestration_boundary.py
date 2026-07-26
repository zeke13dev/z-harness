"""Hostile tests for the mandatory degraded dispatcher boundary."""

from __future__ import annotations

import multiprocessing
from dataclasses import fields, replace
from pathlib import Path
from threading import Event, Thread
from typing import Callable

import pytest

from runtime.capability_authority import (
    AUTHORITY_VERSION,
    Capability,
    CapabilityAuthority,
    CapabilityEvidence,
    CapabilityKey,
)
from runtime.dispatch.driver import DispatchHandle, HostDriver
from runtime.dispatch.dispatcher import Dispatcher
from runtime.dispatch.result import DispatchResult
from runtime.orchestration_boundary import (
    AdmissionDenied,
    AdmissionRequest,
    BoundarySources,
    OrchestrationBoundary,
    TransitionIds,
)
from runtime.orchestration_ledger import (
    AdmissionCeilingExceeded,
    IdentifierConflict,
    OrchestrationLedger,
    StaleWriter,
)


class _CallbackDriver(HostDriver):
    """Minimal driver whose dispatch hook exposes callback admission timing."""

    def __init__(self, hook: Callable[[], None] | None = None) -> None:
        self.calls = 0
        self._hook = hook

    def init(self, provider_config: dict, context: dict | None = None) -> None:
        """Accept test configuration without external I/O."""

    def dispatch(self, command_id: str, args: list[str], env: dict[str, str]) -> DispatchHandle:
        """Record the costly callback and run the optional hostile hook."""

        self.calls += 1
        if self._hook is not None:
            self._hook()
        return DispatchHandle(
            _events_fn=lambda: iter(()),
            _wait_fn=lambda: DispatchResult(exit_code=0, is_error=False),
        )


class _WrongDriver(_CallbackDriver):
    """Distinct driver type used to prove runtime binding."""


def _key() -> CapabilityKey:
    return CapabilityKey("codex", "cli", "build-1", "z-execute", "degraded")


def _request(suffix: str = "1") -> AdmissionRequest:
    return AdmissionRequest(
        logical_work_id=f"work-{suffix}",
        reservation_id=f"reservation-{suffix}",
        writer_id=f"writer-{suffix}",
        transitions=TransitionIds(
            reserve=f"reserve-{suffix}",
            dispatching=f"dispatching-{suffix}",
            started=f"started-{suffix}",
            indeterminate=f"indeterminate-{suffix}",
            settled=f"settled-{suffix}",
        ),
    )


def _fixture(
    tmp_path: Path,
) -> tuple[
    OrchestrationBoundary,
    CapabilityAuthority,
    OrchestrationLedger,
    dict[str, object],
]:
    authority = CapabilityAuthority(tmp_path / "authority.json")
    authority.persist(
        CapabilityEvidence(
            evidence_id="evidence-1",
            authority_version=AUTHORITY_VERSION,
            key=_key(),
            capability=Capability.DEGRADED_SINGLE_AGENT,
            evidence_surface="cli",
            installed_export_fingerprint="export-1",
            issued_at=10,
            expires_at=100,
        )
    )
    values: dict[str, object] = {
        "host": "codex",
        "surface": "cli",
        "build": "build-1",
        "fingerprint": "export-1",
        "now": 20,
    }
    ledger = OrchestrationLedger(tmp_path / "ledger.sqlite")
    sources = BoundarySources(
        supervisor_id="trusted-supervisor",
        host=lambda: str(values["host"]),
        surface=lambda: str(values["surface"]),
        runtime_build=lambda driver: str(values["build"]),
        installed_export_fingerprint=lambda: str(values["fingerprint"]),
        command="z-execute",
        posture="degraded",
        driver_type=_CallbackDriver,
        clock=lambda: int(values["now"]),
    )
    return OrchestrationBoundary(authority, ledger, sources), authority, ledger, values


def _dispatcher(
    tmp_path: Path,
    boundary: OrchestrationBoundary,
    run_id: str = "caller-run",
) -> Dispatcher:
    return Dispatcher(
        repo_root=str(tmp_path),
        run_id=run_id,
        orchestration_boundary=boundary,
    )


def _run(
    tmp_path: Path,
    boundary: OrchestrationBoundary,
    request: AdmissionRequest,
    driver: HostDriver,
    *,
    command: str = "/z-execute",
    run_id: str = "caller-run",
) -> DispatchResult:
    return _dispatcher(tmp_path, boundary, run_id).run(
        driver,
        command,
        [],
        {"args_template": []},
        admission=request,
    )


@pytest.fixture(autouse=True)
def _disable_dispatch_logging(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("runtime.dispatch.dispatcher.log_event", lambda *args, **kwargs: None)


def test_public_dispatcher_run_cannot_bypass_admission(tmp_path: Path) -> None:
    """The production entrypoint rejects before touching an unbound driver."""

    driver = _CallbackDriver()
    with pytest.raises(AdmissionDenied, match="requires executable admission"):
        Dispatcher(str(tmp_path), "caller-run").run(
            driver, "/z-execute", [], {"args_template": []}
        )
    assert driver.calls == 0


def test_public_dispatcher_preserves_unbounded_standalone_single_agent(
    tmp_path: Path,
) -> None:
    """A non-orchestration command still uses the ordinary single-agent path."""

    driver = _CallbackDriver()
    result = Dispatcher(str(tmp_path), "caller-run").run(
        driver, "z-ask", [], {"args_template": []}
    )
    assert result.success
    assert driver.calls == 1


def test_admission_request_cannot_assert_authority_or_run_identity() -> None:
    """Caller data has no fields that can mint authority, time, or a ceiling."""

    assert {item.name for item in fields(AdmissionRequest)} == {
        "logical_work_id",
        "reservation_id",
        "writer_id",
        "transitions",
        "reentry_of",
    }


@pytest.mark.parametrize("command", ["z-review", "z-recovery", "z-follow-up", "z-collect"])
def test_nonimplementation_paths_fail_before_driver(
    tmp_path: Path, command: str
) -> None:
    """Review, recovery, follow-up, and collection cannot impersonate implementation."""

    boundary, _, _, _ = _fixture(tmp_path)
    driver = _CallbackDriver()
    with pytest.raises(AdmissionDenied, match="boundary_command_mismatch"):
        _run(tmp_path, boundary, _request(), driver, command=command)
    assert driver.calls == 0


@pytest.mark.parametrize(
    ("source", "bad_value", "reason"),
    [
        ("host", "claude", "unknown_capability"),
        ("surface", "app", "unknown_capability"),
        ("build", "build-2", "unknown_capability"),
        ("fingerprint", "export-2", "re_export_required"),
        ("now", 100, "stale_evidence"),
    ],
)
def test_authority_uses_fresh_boundary_sources(
    tmp_path: Path, source: str, bad_value: object, reason: str
) -> None:
    """Actual boundary/export source changes fail closed before dispatch."""

    boundary, _, _, values = _fixture(tmp_path)
    values[source] = bad_value
    driver = _CallbackDriver()
    with pytest.raises(AdmissionDenied, match=reason):
        _run(tmp_path, boundary, _request(), driver)
    assert driver.calls == 0


def test_actual_driver_type_is_bound_to_authority_context(tmp_path: Path) -> None:
    """A caller cannot authorize a different driver with a valid tuple."""

    boundary, _, _, _ = _fixture(tmp_path)
    driver = _WrongDriver()
    with pytest.raises(AdmissionDenied, match="boundary_driver_mismatch"):
        _run(tmp_path, boundary, _request(), driver)
    assert driver.calls == 0


def test_exactly_one_implementation_and_new_caller_run_cannot_reset_ceiling(
    tmp_path: Path,
) -> None:
    """Telemetry run IDs do not select the durable supervisor ceiling."""

    boundary, _, ledger, _ = _fixture(tmp_path)
    first = _CallbackDriver()
    second = _CallbackDriver()
    assert _run(tmp_path, boundary, _request(), first, run_id="claimed-a").success
    with pytest.raises(AdmissionCeilingExceeded):
        _run(tmp_path, boundary, _request("2"), second, run_id="claimed-b")
    assert first.calls == 1
    assert second.calls == 0
    assert ledger.run_usage("trusted-supervisor") == (1, 1)


def test_completed_reservation_replay_never_restarts_driver(tmp_path: Path) -> None:
    """Idempotent ledger replay cannot become duplicate costly execution."""

    boundary, _, _, _ = _fixture(tmp_path)
    request = _request()
    first = _CallbackDriver()
    replay = _CallbackDriver()
    _run(tmp_path, boundary, request, first)
    with pytest.raises(AdmissionDenied, match="replay_cannot_restart"):
        _run(tmp_path, boundary, request, replay)
    assert first.calls == 1
    assert replay.calls == 0


def test_explicit_reentry_cannot_reset_degraded_ceiling(tmp_path: Path) -> None:
    """Naming a settled predecessor still cannot consume a second slot."""

    boundary, _, _, _ = _fixture(tmp_path)
    first = _request()
    _run(tmp_path, boundary, first, _CallbackDriver())
    reentry = replace(_request("reentry"), reentry_of=first.reservation_id)
    driver = _CallbackDriver()
    with pytest.raises(AdmissionCeilingExceeded):
        _run(tmp_path, boundary, reentry, driver, run_id="fresh-run")
    assert driver.calls == 0


def test_nested_reentry_with_fresh_dispatcher_is_rejected(tmp_path: Path) -> None:
    """A callback cannot recursively enter even with a different caller run ID."""

    boundary, _, _, _ = _fixture(tmp_path)
    nested = _CallbackDriver()

    def attempt_nested() -> None:
        with pytest.raises(AdmissionDenied, match="nested degraded execution"):
            _run(tmp_path, boundary, _request("nested"), nested, run_id="fresh-run")

    outer = _CallbackDriver(attempt_nested)
    _run(tmp_path, boundary, _request(), outer)
    assert outer.calls == 1
    assert nested.calls == 0


def test_cross_thread_attempt_rejects_immediately_instead_of_deadlocking(
    tmp_path: Path,
) -> None:
    """A second thread fails closed while the first callback holds the scope."""

    boundary, _, _, _ = _fixture(tmp_path)
    entered = Event()
    release = Event()
    outer = _CallbackDriver(lambda: (entered.set(), release.wait(timeout=2)))
    outcome: list[BaseException] = []

    thread = Thread(target=lambda: _run(tmp_path, boundary, _request(), outer))
    thread.start()
    assert entered.wait(timeout=1)
    contender = _CallbackDriver()
    try:
        _run(tmp_path, boundary, _request("thread"), contender, run_id="other")
    except BaseException as exc:
        outcome.append(exc)
    release.set()
    thread.join(timeout=1)

    assert not thread.is_alive()
    assert len(outcome) == 1
    assert isinstance(outcome[0], AdmissionDenied)
    assert "already active" in str(outcome[0])
    assert contender.calls == 0


def _process_attempt(tmp_dir: str, queue: multiprocessing.Queue) -> None:
    """Attempt admission in a forked process and report its fail-closed result."""

    root = Path(tmp_dir)
    boundary, _, _, _ = _fixture(root)
    driver = _CallbackDriver()
    try:
        _run(root, boundary, _request("process"), driver, run_id="process-run")
    except AdmissionDenied as exc:
        queue.put((type(exc).__name__, str(exc), driver.calls))
    else:
        queue.put(("allowed", "", driver.calls))


def test_cross_process_attempt_rejects_immediately(tmp_path: Path) -> None:
    """The nonblocking process lock rejects instead of waiting on live work."""

    boundary, _, _, _ = _fixture(tmp_path)
    entered = Event()
    release = Event()
    outer = _CallbackDriver(lambda: (entered.set(), release.wait(timeout=3)))
    thread = Thread(target=lambda: _run(tmp_path, boundary, _request(), outer))
    thread.start()
    assert entered.wait(timeout=1)

    context = multiprocessing.get_context("spawn")
    queue = context.Queue()
    process = context.Process(target=_process_attempt, args=(str(tmp_path), queue))
    process.start()
    process.join(timeout=3)
    release.set()
    thread.join(timeout=1)

    assert not process.is_alive()
    assert queue.get(timeout=1) == (
        "AdmissionDenied",
        "degraded execution already active",
        0,
    )


def test_crash_cut_is_indeterminate_and_terminal_settlement_remains_available(
    tmp_path: Path,
) -> None:
    """Callback failure consumes the slot but remains terminally settleable."""

    boundary, authority, ledger, _ = _fixture(tmp_path)

    def crash() -> None:
        raise ValueError("boom")

    with pytest.raises(ValueError, match="boom"):
        _run(tmp_path, boundary, _request(), _CallbackDriver(crash))

    reservation = ledger.get_reservation("reservation-1")
    assert reservation.state == "indeterminate"
    authority.revoke(_key(), revoked_at=21, reason="test revocation")
    settled = boundary.settle(
        reservation_id=reservation.reservation_id,
        transition_id="terminal-after-revocation",
        writer_id=reservation.writer_id,
        writer_fence=reservation.writer_fence,
    )
    assert settled.state == "settled"


def test_duplicate_live_logical_work_fails_before_driver(tmp_path: Path) -> None:
    """An indeterminate attempt cannot be duplicated under a fresh identity."""

    boundary, _, _, _ = _fixture(tmp_path)

    def crash() -> None:
        raise RuntimeError("crash")

    with pytest.raises(RuntimeError, match="crash"):
        _run(tmp_path, boundary, _request(), _CallbackDriver(crash))
    duplicate = replace(_request("duplicate"), logical_work_id="work-1")
    driver = _CallbackDriver()
    with pytest.raises(AdmissionCeilingExceeded):
        _run(tmp_path, boundary, duplicate, driver, run_id="fresh-run")
    assert driver.calls == 0


def test_stale_writer_cannot_settle(tmp_path: Path) -> None:
    """A transferred writer fence invalidates stale terminal writers."""

    boundary, _, ledger, _ = _fixture(tmp_path)
    with pytest.raises(ValueError):
        _run(
            tmp_path,
            boundary,
            _request(),
            _CallbackDriver(lambda: (_ for _ in ()).throw(ValueError())),
        )
    old = ledger.get_reservation("reservation-1")
    current = ledger.transfer_writer(
        reservation_id=old.reservation_id,
        transition_id="recovery-transfer",
        writer_id=old.writer_id,
        writer_fence=old.writer_fence,
        new_writer_id="recovery-writer",
    )
    with pytest.raises(StaleWriter):
        boundary.settle(
            reservation_id=old.reservation_id,
            transition_id="stale-settlement",
            writer_id=old.writer_id,
            writer_fence=old.writer_fence,
        )
    assert boundary.settle(
        reservation_id=current.reservation_id,
        transition_id="current-settlement",
        writer_id=current.writer_id,
        writer_fence=current.writer_fence,
    ).state == "settled"


def test_transition_identity_reuse_fails_before_driver(tmp_path: Path) -> None:
    """Reserve and lifecycle transitions cannot share one immutable identity."""

    boundary, _, _, _ = _fixture(tmp_path)
    request = _request()
    request = replace(
        request,
        transitions=replace(request.transitions, dispatching=request.transitions.reserve),
    )
    driver = _CallbackDriver()
    with pytest.raises(IdentifierConflict):
        _run(tmp_path, boundary, request, driver)
    assert driver.calls == 0
