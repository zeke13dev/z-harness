"""
test_strict.py — F7 fail-loud conformance + adapter round-trip conformance.

This is the **strict** half of the conformance suite (MF2 / audit-finding F7).
Unlike ``test_matrix.py`` — which *skips* a driver row when its binary is
absent and *xfails* a row when its fixtures are still placeholders — this
module is a REAL integration test against the live driver-selection layer.
It fails loudly when:

  1. A host driver is missing — i.e. ``select_driver(host)`` does NOT return a
     live :class:`HostDriver` for one of the four supported hosts (claude,
     cursor, codex, antigravity).  Opt out per-host only via the
     ``--allow-missing`` strict-runner flag (see ``run_strict.py``); the
     default pytest run NEVER allows a missing host.
  2. Zero drivers actually ran — i.e. the conformance matrix passed only
     because every row was skipped / xfailed and nothing real executed.  A
     green run with zero live coverage is treated as a FAILURE here.
  3. A fixture is a placeholder or missing — any golden fixture still carrying
     the ``# PLACEHOLDER`` marker (or an empty events golden) means no real
     output was ever recorded, so "conformance" is vacuous.

It also asserts the contract edges F7 names explicitly:

  - ``select_driver("unknown")`` raises :class:`DriverNotFoundError` with a
    clear, host-naming message.
  - Each driver's ``.init()`` does not crash with unset auth: it either
    returns cleanly or surfaces a *recognized clear config error* (never a
    bare ``KeyError`` / ``AttributeError`` / ``TypeError`` stack trace).

Plus adapter round-trip conformance: each supported host name routes to a
distinct, live ``HostDriver`` subclass instance.

NOTE on namespaces: the conformance *matrix* keys drivers by BINARY name
(``claude-code``, ``codex``, ``agy``, ``cursor-agent`` — see
``conftest.DRIVERS``).  The driver-SELECTION layer (``select_driver``) keys by
HOST name (``claude``, ``codex``, ``antigravity``, ``cursor``).  These are
deliberately distinct namespaces; this module exercises the host-name layer.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Strict-mode gate
# ---------------------------------------------------------------------------
#
# The fail-loud placeholder/zero-coverage check FAILS as long as golden
# fixtures are still placeholders — that is the whole point of the gate. But we
# do NOT want it to break the regular `make test` / `make conformance`
# regression suites (which run the entire tests/conformance/ tree on every PR)
# while fixtures are legitimately not-yet-recorded. So that single check is
# gated behind the Z_HARNESS_CONFORMANCE_STRICT=1 env var, which `make
# conformance-strict` sets. Outside strict mode the check SKIPS (it does not
# silently pass — skip is visible). The contract-edge tests (live drivers,
# unknown-host, init-no-crash, distinct routing) always run; they reflect
# real, satisfiable invariants and pass today.
_STRICT_ENABLED: bool = os.environ.get("Z_HARNESS_CONFORMANCE_STRICT") == "1"
_strict_only = pytest.mark.skipif(
    not _STRICT_ENABLED,
    reason="fail-loud strict check — enable with Z_HARNESS_CONFORMANCE_STRICT=1 "
    "(set by `make conformance-strict`)",
)

from runtime.dispatch.driver import HostDriver
from runtime.drivers import DriverNotFoundError, select_driver
from tests.conformance import run_conformance as _run_conformance_mod

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# The four host names F7 requires a live driver for. These are HOST names
# (select_driver namespace), not binary names.
SUPPORTED_HOSTS: list[str] = ["claude", "cursor", "codex", "antigravity"]

# Expected concrete driver class name per host. select_driver must return an
# instance of HostDriver whose class matches — this catches a regression where
# a host silently routes to the wrong (or a stubbed) driver.
EXPECTED_DRIVER_CLASS: dict[str, str] = {
    "claude": "SubprocessClaudeDriver",
    "cursor": "CursorCLIDriver",
    "codex": "CodexDriver",
    "antigravity": "AntigravityHostDriverShim",
}

# Exception types that constitute a *clear config error* from .init() when auth
# is unset. Surfacing one of these (with a message) is acceptable F7 behavior;
# a bare KeyError/AttributeError/TypeError (an unhandled stack trace) is NOT.
#
# Imported lazily/defensively: these live in driver sub-packages and we only
# need the ones that exist. Any that fail to import are simply omitted from the
# allow-list (their absence cannot mask a real failure because init() raising
# an *unlisted* type is what the test flags).
_CLEAR_CONFIG_ERRORS: tuple[type[BaseException], ...]


def _resolve_clear_config_errors() -> tuple[type[BaseException], ...]:
    errs: list[type[BaseException]] = []
    try:
        from runtime.drivers.cursor.cli_driver import (
            DriverConfigError,
            DriverInitError,
        )

        errs.extend([DriverConfigError, DriverInitError])
    except ImportError:
        pass
    try:
        from runtime.drivers.codex.auth import AuthResolutionError

        errs.append(AuthResolutionError)
    except ImportError:
        pass
    try:
        from runtime.drivers.antigravity.preflight import DriverUnavailableError

        errs.append(DriverUnavailableError)
    except ImportError:
        pass
    # NotImplementedError is a clear, intentional signal (e.g. tombstoned
    # paths) — acceptable, not a crash.
    errs.append(NotImplementedError)
    return tuple(errs)


_CLEAR_CONFIG_ERRORS = _resolve_clear_config_errors()

# Exception types that represent an UNHANDLED crash from .init() — a bug, not a
# surfaced config error.
_CRASH_EXCEPTIONS: tuple[type[BaseException], ...] = (
    KeyError,
    AttributeError,
    TypeError,
    IndexError,
)

# Fixture layout (shared with run_conformance.py / test_matrix.py).
_HERE = Path(__file__).parent.resolve()
_FIXTURES_ROOT = _HERE / "fixtures"

# Canonical driver (BINARY) names whose golden fixtures MUST exist for real
# coverage. These are the keys run_conformance.py uses for the fixture layout
# (fixtures/<command>/<driver>/...) — NOT the select_driver HOST names. The
# strict gate builds expected fixture paths from THIS list so that DELETING a
# host's fixture directory is a failure (missing != pass), rather than silently
# narrowing the set to whatever directories happen to remain on disk.
_CANONICAL_DRIVERS: list[str] = ["claude-code", "codex", "agy", "cursor-agent"]

# The golden fixture files every driver directory must carry.
_GOLDEN_FILENAMES: tuple[str, ...] = (
    "artifacts.golden.txt",
    "events.golden.jsonl",
    "exit.golden",
)

# A minimal provider_config sufficient to call .init() without depending on a
# real providers.json. Drivers read optional keys via .get(); none index a
# required key at init time, so an empty-ish dict is a valid no-auth probe.
_MINIMAL_PROVIDER_CONFIG: dict = {
    "host": "<probe>",
    "args_template": [],
}


# ---------------------------------------------------------------------------
# (a) Missing host driver -> FAIL: each supported host returns a live driver
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("host", SUPPORTED_HOSTS)
def test_supported_host_returns_live_driver(host: str) -> None:
    """F7(a): select_driver(host) returns a LIVE HostDriver for each host.

    A "live" driver is a concrete, instantiated HostDriver subclass — not a
    None, not a placeholder string, not a class object. If select_driver
    raises DriverNotFoundError for a supported host, that host's driver is
    effectively MISSING and this fails loudly (per MF2 / F7).
    """
    driver = select_driver(host)

    assert driver is not None, f"select_driver({host!r}) returned None — host driver missing"
    assert isinstance(driver, HostDriver), (
        f"select_driver({host!r}) returned {type(driver).__name__}, "
        f"which is not a HostDriver subclass instance"
    )
    assert type(driver).__name__ == EXPECTED_DRIVER_CLASS[host], (
        f"select_driver({host!r}) returned {type(driver).__name__}; "
        f"expected {EXPECTED_DRIVER_CLASS[host]}"
    )


def test_all_supported_hosts_route_to_distinct_drivers() -> None:
    """Adapter round-trip: the four hosts map to four DISTINCT driver classes.

    Guards against a regression where two hosts collapse onto the same driver
    (e.g. an accidental fall-through making codex route to the claude driver).
    """
    classes = {host: type(select_driver(host)).__name__ for host in SUPPORTED_HOSTS}
    distinct = set(classes.values())
    assert len(distinct) == len(SUPPORTED_HOSTS), (
        f"Expected {len(SUPPORTED_HOSTS)} distinct driver classes, got "
        f"{len(distinct)}: {classes}"
    )


# ---------------------------------------------------------------------------
# Unsupported host -> DriverNotFoundError with a clear message
# ---------------------------------------------------------------------------


def test_unknown_host_raises_driver_not_found() -> None:
    """F7: select_driver('unknown') raises DriverNotFoundError clearly.

    The message must name the offending host and enumerate the supported
    hosts, so the operator can self-correct without reading source.
    """
    with pytest.raises(DriverNotFoundError) as excinfo:
        select_driver("unknown")

    msg = str(excinfo.value)
    assert "unknown" in msg, f"error message does not name the bad host: {msg!r}"
    # Enumerate the supported hosts so the message is actionable.
    for host in SUPPORTED_HOSTS:
        assert host in msg, (
            f"DriverNotFoundError message omits supported host {host!r}: {msg!r}"
        )


@pytest.mark.parametrize("bad_host", ["", "claude-code", "gpt", "gemini", "self"])
def test_other_unsupported_hosts_raise_driver_not_found(bad_host: str) -> None:
    """Several plausible-but-wrong host strings all raise DriverNotFoundError.

    'claude-code' is the BINARY name, not the host name — feeding the binary
    namespace into the host namespace must fail, not silently succeed.
    """
    with pytest.raises(DriverNotFoundError):
        select_driver(bad_host)


# ---------------------------------------------------------------------------
# .init() does not crash with unset auth — surfaces a clear config error
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("host", SUPPORTED_HOSTS)
def test_init_does_not_crash_with_unset_auth(host: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """F7: driver.init() with unset auth must not crash with a stack trace.

    With every known auth env var cleared, calling .init() must EITHER:
      - return cleanly (driver defers auth resolution to dispatch()), OR
      - raise a *recognized clear config error* (DriverConfigError,
        DriverInitError, AuthResolutionError, DriverUnavailableError,
        NotImplementedError) carrying a non-empty message.

    It must NOT raise a bare KeyError / AttributeError / TypeError / IndexError
    — those indicate an unhandled crash rather than a surfaced config error.
    """
    # Strip every credential env var a driver might consult so this is a true
    # "unset auth" probe regardless of the developer's local environment.
    for var in (
        "CURSOR_API_KEY",
        "ANTHROPIC_API_KEY",
        "OPENAI_API_KEY",
        "CODEX_API_KEY",
        "GEMINI_API_KEY",
        "GOOGLE_API_KEY",
        "ANTIGRAVITY_API_KEY",
    ):
        monkeypatch.delenv(var, raising=False)

    driver = select_driver(host)

    try:
        driver.init(dict(_MINIMAL_PROVIDER_CONFIG))
    except _CRASH_EXCEPTIONS as exc:  # pragma: no cover - this is the failure path
        pytest.fail(
            f"{type(driver).__name__}.init() crashed with unhandled "
            f"{type(exc).__name__}: {exc!r}. init() must surface a clear "
            f"config error (e.g. DriverConfigError) instead of crashing."
        )
    except _CLEAR_CONFIG_ERRORS as exc:
        # Acceptable: a clear, surfaced config error — but it must carry a
        # human-readable message, not be an empty marker.
        assert str(exc).strip(), (
            f"{type(driver).__name__}.init() raised {type(exc).__name__} with "
            f"an empty message; the config error must be actionable"
        )
    # else: init() returned cleanly — also acceptable (auth deferred to dispatch).


# ---------------------------------------------------------------------------
# (b) Zero actual driver coverage -> FAIL
# (c) Placeholder / missing fixtures -> FAIL
# ---------------------------------------------------------------------------


def _golden_files_for(command: str = "z-do") -> list[Path]:
    """Return every EXPECTED golden fixture file for *command*.

    Critically, this builds the path list from the CANONICAL driver roster
    (``_CANONICAL_DRIVERS``) — NOT by iterating directories that happen to
    exist on disk. Iterating only existing directories would let a deleted
    host's fixtures silently disappear from the gate, so a green run no longer
    proves that host has real coverage. By enumerating the canonical roster we
    guarantee that a MISSING driver directory or golden file surfaces as a
    ``missing fixture`` failure in :func:`_placeholder_or_missing`.
    """
    files: list[Path] = []
    for driver in _CANONICAL_DRIVERS:
        driver_dir = _FIXTURES_ROOT / command / driver
        for name in _GOLDEN_FILENAMES:
            files.append(driver_dir / name)
    return files


def _events_golden_reason(path: Path, content: str) -> str | None:
    """Validate an ``events.golden.jsonl`` carries REAL recorded coverage.

    Returns a reason string when the file is not real coverage, else None.

    Real coverage means the file parses as JSONL and contains at least one
    VALID conformance event — a JSON object carrying a ``"type"`` field, which
    is the event shape :mod:`run_conformance.py` records (every event it emits
    via ``_emit`` is a dict with a ``"type"`` key). Junk text, a bare scalar,
    a JSON array, or an object lacking ``"type"`` does NOT count: those would
    let an empty-but-non-blank file masquerade as coverage.
    """
    import json

    stripped = content.strip()
    if not stripped:
        return f"empty events golden (no recorded coverage): {path}"

    valid_event_count = 0
    malformed_lines: list[int] = []
    for lineno, raw in enumerate(content.splitlines(), start=1):
        line = raw.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            malformed_lines.append(lineno)
            continue
        # A valid conformance event is a JSON object with a non-empty "type".
        if isinstance(obj, dict) and isinstance(obj.get("type"), str) and obj["type"].strip():
            valid_event_count += 1

    if valid_event_count == 0:
        detail = (
            f" ({len(malformed_lines)} malformed line(s))"
            if malformed_lines
            else ""
        )
        return (
            f"events golden has no valid conformance event "
            f"(needs >=1 JSON object with a 'type' field, the shape "
            f"run_conformance.py records){detail}: {path}"
        )
    return None


def _placeholder_or_missing(path: Path) -> str | None:
    """Return a reason string if *path* is missing/placeholder/empty, else None.

    A golden fixture counts as non-real coverage when:
      - it does not exist, OR
      - it carries the '# PLACEHOLDER' marker, OR
      - (for events.golden.jsonl) it lacks at least one VALID conformance event
        (see :func:`_events_golden_reason`).
    """
    if not path.exists():
        return f"missing fixture: {path}"
    content = path.read_text(encoding="utf-8")
    if "# PLACEHOLDER" in content:
        return f"placeholder fixture (# PLACEHOLDER): {path}"
    if path.name == "events.golden.jsonl":
        return _events_golden_reason(path, content)
    return None


def _strict_fixture_reasons(command: str = "z-do") -> list[str]:
    """Collect all placeholder/missing/empty fixture reasons for *command*.

    Expected fixtures are derived from the canonical driver roster, so a
    missing driver directory or golden file is reported as a failure rather
    than being skipped.
    """
    files = _golden_files_for(command)
    if not files:
        return [f"no fixtures recorded under {_FIXTURES_ROOT / command}"]
    reasons: list[str] = []
    for f in files:
        reason = _placeholder_or_missing(f)
        if reason is not None:
            reasons.append(reason)
    return reasons


# ---------------------------------------------------------------------------
# Roster sync: _CANONICAL_DRIVERS must stay in lockstep with _DRIVER_BINARIES
# ---------------------------------------------------------------------------


def test_canonical_drivers_matches_run_conformance_driver_binaries() -> None:
    """The strict canonical roster and run_conformance._DRIVER_BINARIES must match.

    Both lists define the same set of driver binary names. If run_conformance
    gains or renames a driver, _CANONICAL_DRIVERS must be updated too, and
    vice-versa. This test fails immediately with the symmetric difference so
    the drift is obvious and actionable.
    """
    roster = set(_CANONICAL_DRIVERS)
    binaries = set(_run_conformance_mod._DRIVER_BINARIES.keys())
    symmetric_diff = roster.symmetric_difference(binaries)
    assert not symmetric_diff, (
        "Roster drift detected between test_strict._CANONICAL_DRIVERS and "
        "run_conformance._DRIVER_BINARIES:\n"
        f"  in _CANONICAL_DRIVERS only: {sorted(roster - binaries)}\n"
        f"  in _DRIVER_BINARIES only:   {sorted(binaries - roster)}\n"
        "Update _CANONICAL_DRIVERS (test_strict.py) to match _DRIVER_BINARIES "
        "(run_conformance.py), or update both if a driver was renamed."
    )


@_strict_only
def test_strict_fails_on_placeholder_or_missing_fixtures() -> None:
    """F7(b)+(c): strict conformance FAILS while fixtures are placeholders.

    This is the fail-loud heart of the gate. As long as ANY golden fixture is
    a '# PLACEHOLDER' / empty / missing, there is ZERO real recorded driver
    coverage, so a "passing" conformance run would be vacuous. This test must
    FAIL in that state — i.e. it asserts there are no such reasons.

    To make the gate green you must record real fixtures with:
        python tests/conformance/run_conformance.py \\
            --command z-do --mode live --record --drivers <driver>
    which replaces the placeholders with real recorded output.
    """
    reasons = _strict_fixture_reasons("z-do")
    assert not reasons, (
        "conformance-strict: no real driver coverage — every golden fixture "
        "is a placeholder/empty/missing, so a passing run would be vacuous. "
        "Record real fixtures (run_conformance.py --mode live --record). "
        "Offending fixtures:\n  - " + "\n  - ".join(reasons)
    )
