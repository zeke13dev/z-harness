"""Adapter registry — detect_all(), select(), and the Rich host picker.

Public surface (D10, SPEC adapters/registry.py):
  detect_all()         -> list[tuple[HostAdapter, DetectResult]]
  select(host=None, interactive=True) -> tuple[HostAdapter, DetectResult]
  UnknownHostError     — raised by select() for a bad --host name
  NoHostInstalledError — raised by select() when nothing is found

Importing each concrete adapter module triggers its import-time
``register_command_tiers(...)`` call.  The registry imports all adapter modules
unconditionally so command_tier() always has complete data.

The Rich interactive picker is used only when ``interactive=True`` and no
``--host`` override is given AND more than one host is installed.  If exactly
one host is installed it is returned directly.

Reuse notes:
  * detect_all() calls adapter.detect() for each adapter — the same
    PATH probe pattern used in scripts/discover-providers.py.
  * select() respects a ``--host`` flag passed by the caller; it does NOT
    re-implement driver selection logic from runtime/drivers/__init__.py.
    The registry owns HostAdapter lookup; runtime/drivers owns HostDriver lookup.
"""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

# Import all adapters so their module-level register_command_tiers() calls run.
# Order is canonical: claude (native), antigravity (high), cursor/codex
# (flattened), then OMP (partial until native parity gates land).
from z_harness_cli.adapters.claude import ClaudeAdapter
from z_harness_cli.adapters.antigravity import AntigravityAdapter
from z_harness_cli.adapters.cursor import CursorAdapter
from z_harness_cli.adapters.codex import CodexAdapter
from z_harness_cli.adapters.omp import OmpAdapter
from z_harness_cli.adapters.base import DetectResult, HostAdapter

if TYPE_CHECKING:
    pass


# ---------------------------------------------------------------------------
# Public exceptions
# ---------------------------------------------------------------------------


class UnknownHostError(ValueError):
    """Raised by select() when the requested --host name is not registered.

    The error message includes the list of valid host names.
    """


class NoHostInstalledError(RuntimeError):
    """Raised by select() (interactive or non-interactive) when detect_all()
    finds no installed hosts.

    Callers should print an installation hint and exit.
    """


# ---------------------------------------------------------------------------
# All registered adapters (ordered: fidelity desc)
# ---------------------------------------------------------------------------

#: The canonical ordered list of adapters.  Order determines display order in
#: the Rich picker and in doctor output: native first, then high, then
#: flattened, then partial.
_ALL_ADAPTERS: list[HostAdapter] = [
    ClaudeAdapter(),
    AntigravityAdapter(),
    CursorAdapter(),
    CodexAdapter(),
    OmpAdapter(),
]

#: Map of host name -> adapter instance for O(1) lookup by name.
_ADAPTER_BY_NAME: dict[str, HostAdapter] = {a.name: a for a in _ALL_ADAPTERS}


# ---------------------------------------------------------------------------
# detect_all
# ---------------------------------------------------------------------------


def detect_all() -> list[tuple[HostAdapter, DetectResult]]:
    """Probe all registered adapters and return their detection results.

    Each adapter's ``detect()`` is called once; results are returned in
    canonical order (native → high → flattened).  Adapters that are not
    installed are included in the list with ``DetectResult(installed=False)``.

    This mirrors the discover-providers.py pattern: probe every known host
    regardless of prior state; never cache across calls.

    Returns
    -------
    list of (adapter, DetectResult) pairs, one per registered adapter.
    """
    results: list[tuple[HostAdapter, DetectResult]] = []
    for adapter in _ALL_ADAPTERS:
        result = adapter.detect()
        results.append((adapter, result))
    return results


# ---------------------------------------------------------------------------
# select
# ---------------------------------------------------------------------------


def select(
    host: str | None = None,
    interactive: bool = True,
) -> tuple[HostAdapter, DetectResult]:
    """Select and return an (adapter, DetectResult) pair.

    Resolution order:
    1. If *host* is not None, look it up in the registry.  Raise
       ``UnknownHostError`` if not found.  The adapter's detect() is called
       to confirm installation; the caller decides whether to error on
       ``installed=False``.
    2. Run detect_all() to find installed hosts.
    3. If no host is installed, raise ``NoHostInstalledError``.
    4. If exactly one host is installed, return it directly (no picker needed).
    5. If multiple hosts are installed and ``interactive=True``, show the Rich
       picker so the user can choose.
    6. If multiple hosts are installed and ``interactive=False``, return the
       first installed adapter in canonical order (deterministic; highest
       fidelity first).

    Parameters
    ----------
    host:
        The --host override, e.g. ``"claude"``, ``"cursor"``.  None = auto.
    interactive:
        Whether to show the Rich picker when multiple hosts are installed.
        Set to False in non-interactive scripts / CI.

    Returns
    -------
    (adapter, DetectResult)

    Raises
    ------
    UnknownHostError:
        *host* is not a recognized adapter name.
    NoHostInstalledError:
        No host is installed and *host* was not specified.
    """
    if host is not None:
        adapter = _ADAPTER_BY_NAME.get(host)
        if adapter is None:
            valid = sorted(_ADAPTER_BY_NAME.keys())
            raise UnknownHostError(
                f"Unknown host {host!r}. Valid hosts: {valid}."
            )
        result = adapter.detect()
        return adapter, result

    # Auto-detect installed hosts.
    all_results = detect_all()
    installed = [(adapter, result) for adapter, result in all_results if result.installed]

    if not installed:
        raise NoHostInstalledError(
            "No supported host is installed. "
            "Install one of: "
            + ", ".join(f"'{a.name}'" for a in _ALL_ADAPTERS)
            + ". Then re-run z-harness."
        )

    if len(installed) == 1:
        return installed[0]

    # Multiple hosts installed.
    if not interactive:
        # Deterministic: canonical order, highest fidelity first.
        return installed[0]

    return _rich_picker(installed)


# ---------------------------------------------------------------------------
# Rich interactive picker
# ---------------------------------------------------------------------------

_FIDELITY_ORDER = {"native": 0, "high": 1, "flattened": 2, "partial": 3, "unsupported": 4}


def _rich_picker(
    installed: list[tuple[HostAdapter, DetectResult]],
) -> tuple[HostAdapter, DetectResult]:
    """Display a Rich interactive picker and return the chosen adapter.

    Falls back to a plain stdin prompt when Rich is not available (e.g. in
    minimal CI environments where rich is absent).

    Parameters
    ----------
    installed:
        Non-empty list of (adapter, DetectResult) for installed hosts.

    Returns
    -------
    (adapter, DetectResult) chosen by the user.
    """
    try:
        from rich.console import Console
        from rich.table import Table
        from rich.prompt import IntPrompt
        return _rich_picker_rich(installed)
    except ImportError:
        return _rich_picker_plain(installed)


def _rich_picker_rich(
    installed: list[tuple[HostAdapter, DetectResult]],
) -> tuple[HostAdapter, DetectResult]:
    """Rich-library picker implementation."""
    from rich.console import Console
    from rich.table import Table
    from rich.prompt import IntPrompt

    console = Console(stderr=True)
    table = Table(title="Installed hosts", show_header=True, header_style="bold cyan")
    table.add_column("#", style="dim", width=3)
    table.add_column("Host", style="bold")
    table.add_column("Fidelity")
    table.add_column("Version")
    table.add_column("Binary")

    for idx, (adapter, result) in enumerate(installed, start=1):
        table.add_row(
            str(idx),
            adapter.name,
            adapter.fidelity_tier,
            result.version or "(unknown)",
            result.binary or "(unknown)",
        )

    console.print(table)

    choice = IntPrompt.ask(
        "Select host",
        choices=[str(i) for i in range(1, len(installed) + 1)],
        console=console,
    )
    return installed[choice - 1]


def _rich_picker_plain(
    installed: list[tuple[HostAdapter, DetectResult]],
) -> tuple[HostAdapter, DetectResult]:
    """Plain-stdin fallback picker when Rich is not available."""
    print("Installed hosts:", file=sys.stderr)
    for idx, (adapter, result) in enumerate(installed, start=1):
        version = f"  v{result.version}" if result.version else ""
        print(f"  [{idx}] {adapter.name} ({adapter.fidelity_tier}){version}", file=sys.stderr)

    while True:
        try:
            raw = input(f"Select host [1-{len(installed)}]: ").strip()
        except EOFError:
            # Non-interactive stdin; fall back to first.
            return installed[0]

        if raw.isdigit():
            idx = int(raw)
            if 1 <= idx <= len(installed):
                return installed[idx - 1]
        print(
            f"Please enter a number between 1 and {len(installed)}.",
            file=sys.stderr,
        )
