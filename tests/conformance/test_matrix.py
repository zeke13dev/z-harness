"""
test_matrix.py — Parameterized cross-driver conformance tests.

Each row invokes run_conformance.py via subprocess with --mode=replay for a
single driver and asserts exit 0.  Rows are:

  - skipped   if the driver binary is not on PATH
  - xfail     if the driver's fixture contains a # PLACEHOLDER marker
              (expected failure until real fixtures are recorded via --record)
  - pass/fail otherwise
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from tests.conformance.conftest import DRIVERS, driver_available

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_HERE = Path(__file__).parent.resolve()
_FIXTURES_ROOT = _HERE / "fixtures"
_RUN_CONFORMANCE = _HERE / "run_conformance.py"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _has_placeholder_fixture(driver: str, command: str = "z-do") -> bool:
    """Return True if any golden fixture for *driver* contains '# PLACEHOLDER'."""
    driver_fix_dir = _FIXTURES_ROOT / command / driver
    for candidate in [
        driver_fix_dir / "artifacts.golden.txt",
        driver_fix_dir / "events.golden.jsonl",
    ]:
        if candidate.exists():
            content = candidate.read_text(encoding="utf-8")
            if "# PLACEHOLDER" in content:
                return True
    return False


# ---------------------------------------------------------------------------
# Build parametrize list — attach xfail or skip marks per driver
# ---------------------------------------------------------------------------


def _build_params() -> list:
    params = []
    for driver in DRIVERS:
        if not driver_available(driver):
            marks = [pytest.mark.skip(reason=f"{driver} binary unavailable")]
        elif _has_placeholder_fixture(driver):
            marks = [
                pytest.mark.xfail(
                    reason="placeholder fixture — run with --record to generate real fixtures",
                    strict=False,
                )
            ]
        else:
            marks = []
        params.append(pytest.param(driver, marks=marks, id=driver))
    return params


# ---------------------------------------------------------------------------
# Test
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("driver", _build_params())
def test_driver_conformance(driver: str) -> None:
    """Invoke run_conformance.py in replay mode for *driver* and assert exit 0."""
    result = subprocess.run(
        [
            sys.executable,
            str(_RUN_CONFORMANCE),
            "--command",
            "z-do",
            "--mode",
            "replay",
            "--drivers",
            driver,
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, (
        f"run_conformance.py exited {result.returncode} for driver {driver!r}.\n"
        f"stdout:\n{result.stdout}\n"
        f"stderr:\n{result.stderr}"
    )
