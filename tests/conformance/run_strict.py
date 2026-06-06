"""
run_strict.py — fail-loud strict conformance runner (MF2 / audit-finding F7).

This is the CLI entry point behind ``make conformance-strict``. It is a REAL
integration check, not a placeholder: it exits NON-ZERO (loudly) when

  (a) a supported host's driver is MISSING — ``select_driver(host)`` does not
      yield a live :class:`HostDriver` — unless ``--allow-missing`` is passed;
  (b) ZERO drivers actually have real recorded coverage (every golden fixture
      is a ``# PLACEHOLDER`` / empty / missing), so a green run would be vacuous;
  (c) any individual golden fixture is a placeholder / missing.

It ALSO verifies the F7 contract edges directly:

  - ``select_driver("unknown")`` raises :class:`DriverNotFoundError`;
  - each driver's ``.init()`` with unset auth does not crash (surfaces a clear
    config error or returns cleanly).

Usage::

    python tests/conformance/run_strict.py [--command z-do] [--allow-missing]

Exit codes:
    0  all strict checks passed (live drivers present, real coverage exists,
       contract edges hold)
    1  one or more strict checks FAILED (the fail-loud path)
    2  usage error

``--allow-missing`` only relaxes check (a): a host whose driver cannot be
selected is downgraded from a hard failure to a printed warning. It does NOT
relax the zero-coverage (b) or placeholder (c) checks — opting into a missing
HOST must never be a backdoor to passing with no real fixtures.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Import the shared strict helpers from the test module so the runner and the
# pytest assertions stay in lockstep (single source of truth for what counts
# as "live driver", "placeholder", "clear config error", etc.).
# ---------------------------------------------------------------------------

_HERE = Path(__file__).parent.resolve()
_REPO_ROOT = _HERE.parent.parent  # tests/conformance -> repo root

# Ensure the repo root is importable when run as a standalone script (so that
# `import runtime...` and `from tests.conformance...` resolve).
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from runtime.drivers import DriverNotFoundError, select_driver  # noqa: E402
from runtime.dispatch.driver import HostDriver  # noqa: E402
from tests.conformance.test_strict import (  # noqa: E402
    EXPECTED_DRIVER_CLASS,
    SUPPORTED_HOSTS,
    _CLEAR_CONFIG_ERRORS,
    _CRASH_EXCEPTIONS,
    _MINIMAL_PROVIDER_CONFIG,
    _strict_fixture_reasons,
)


def _check_live_drivers(allow_missing: bool) -> tuple[list[str], list[str], int]:
    """Check every supported host yields a live driver.

    Returns (failures, warnings, live_count). When allow_missing is True a
    missing host produces a warning instead of a failure, but a host that
    routes to the WRONG driver class is always a failure (it is a real
    misconfiguration, not an absence).
    """
    failures: list[str] = []
    warnings: list[str] = []
    live_count = 0

    for host in SUPPORTED_HOSTS:
        try:
            driver = select_driver(host)
        except DriverNotFoundError as exc:
            if allow_missing:
                warnings.append(f"host {host!r} driver missing (allowed): {exc}")
            else:
                failures.append(
                    f"host {host!r}: select_driver raised DriverNotFoundError "
                    f"(driver MISSING): {exc}"
                )
            continue
        except Exception as exc:  # noqa: BLE001 - any other error here is itself a failure
            failures.append(
                f"host {host!r}: select_driver raised unexpected "
                f"{type(exc).__name__}: {exc}"
            )
            continue

        if not isinstance(driver, HostDriver):
            failures.append(
                f"host {host!r}: select_driver returned {type(driver).__name__}, "
                f"not a HostDriver instance"
            )
            continue

        actual = type(driver).__name__
        expected = EXPECTED_DRIVER_CLASS[host]
        if actual != expected:
            failures.append(
                f"host {host!r}: routed to {actual}, expected {expected}"
            )
            continue

        live_count += 1

    return failures, warnings, live_count


def _check_unknown_host_raises() -> list[str]:
    """Verify select_driver('unknown') raises DriverNotFoundError."""
    try:
        select_driver("unknown")
    except DriverNotFoundError:
        return []
    except Exception as exc:  # noqa: BLE001
        return [
            f"select_driver('unknown') raised {type(exc).__name__}, "
            f"expected DriverNotFoundError"
        ]
    return ["select_driver('unknown') did NOT raise — unsupported host accepted"]


def _check_init_no_crash() -> list[str]:
    """Verify each driver's .init() with unset auth does not crash."""
    failures: list[str] = []
    # Clear known credential env vars for the duration of this probe.
    import os

    cleared: dict[str, str] = {}
    for var in (
        "CURSOR_API_KEY",
        "ANTHROPIC_API_KEY",
        "OPENAI_API_KEY",
        "CODEX_API_KEY",
        "GEMINI_API_KEY",
        "GOOGLE_API_KEY",
        "ANTIGRAVITY_API_KEY",
    ):
        if var in os.environ:
            cleared[var] = os.environ.pop(var)
    try:
        for host in SUPPORTED_HOSTS:
            try:
                driver = select_driver(host)
            except DriverNotFoundError:
                # Absence is covered by _check_live_drivers; skip here.
                continue
            try:
                driver.init(dict(_MINIMAL_PROVIDER_CONFIG))
            except _CRASH_EXCEPTIONS as exc:
                failures.append(
                    f"host {host!r}: {type(driver).__name__}.init() crashed with "
                    f"unhandled {type(exc).__name__}: {exc!r}"
                )
            except _CLEAR_CONFIG_ERRORS as exc:
                if not str(exc).strip():
                    failures.append(
                        f"host {host!r}: {type(driver).__name__}.init() raised "
                        f"{type(exc).__name__} with an empty message"
                    )
            except Exception as exc:  # noqa: BLE001
                failures.append(
                    f"host {host!r}: {type(driver).__name__}.init() raised "
                    f"unrecognized {type(exc).__name__}: {exc!r} — not a clear "
                    f"config error"
                )
    finally:
        os.environ.update(cleared)
    return failures


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Strict fail-loud conformance gate (MF2 / F7).",
    )
    parser.add_argument(
        "--command",
        default="z-do",
        help="z-command whose fixtures to inspect for real coverage (default: z-do)",
    )
    parser.add_argument(
        "--allow-missing",
        action="store_true",
        default=False,
        help=(
            "Downgrade a MISSING host driver from a failure to a warning. "
            "Does NOT relax the zero-coverage / placeholder checks."
        ),
    )
    args = parser.parse_args(argv)

    all_failures: list[str] = []
    all_warnings: list[str] = []

    # (a) live-driver presence + correct routing.
    drv_failures, drv_warnings, live_count = _check_live_drivers(args.allow_missing)
    all_failures.extend(drv_failures)
    all_warnings.extend(drv_warnings)

    # Contract edges: unknown host + init-no-crash.
    all_failures.extend(_check_unknown_host_raises())
    all_failures.extend(_check_init_no_crash())

    # (b)+(c) real recorded coverage.
    fixture_reasons = _strict_fixture_reasons(args.command)
    all_failures.extend(fixture_reasons)

    # (b) zero actual coverage: require that at least one host's driver is live.
    # This check is UNCONDITIONAL — --allow-missing downgrades only the
    # per-host MISSING check in _check_live_drivers(), never this aggregate.
    # If every host is absent the gate must still FAIL loudly (F7: "strict run
    # FAILS when nothing actually ran"); allowing individual missing hosts must
    # never be a backdoor to passing with zero real coverage.
    if live_count == 0:
        all_failures.append(
            "zero live drivers — no host produced a selectable HostDriver, so "
            "no real conformance coverage is possible (this check is "
            "unconditional; --allow-missing does NOT relax it)"
        )

    # --- report -------------------------------------------------------------
    for w in all_warnings:
        print(f"conformance-strict: WARNING: {w}", file=sys.stderr)

    if all_failures:
        print(
            f"conformance-strict: FAILED with {len(all_failures)} issue(s):",
            file=sys.stderr,
        )
        for f in all_failures:
            print(f"  - {f}", file=sys.stderr)
        return 1

    print(
        f"conformance-strict: PASSED — {live_count}/{len(SUPPORTED_HOSTS)} live "
        f"host drivers, real fixture coverage for command {args.command!r}."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
