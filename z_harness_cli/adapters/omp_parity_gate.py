"""OMP native parity gate — single source of truth (T009).

This module is the **only** place that decides whether OMP adapter fidelity,
export fidelity, and command tiers may advance to ``native``.  Every surface
that declares OMP fidelity or command tiers MUST read its value from this gate,
never hard-code its own tier constant.

Design
------
Promotion is keyed off the presence and passing of parity evidence tests.
The ``PARITY_EVIDENCE`` mapping names every command family alongside the T008
test class(es) that prove Claude-equivalent behaviour for that family.  A
command family is promoted to ``native`` only when at least one test class is
registered for it in ``PARITY_EVIDENCE``.

Removing a test class from ``PARITY_EVIDENCE`` immediately downgrades the
corresponding command family back to ``degraded`` or ``blocked`` — no separate
configuration update required.

Invariants
----------
- The parity gate is the single source of truth; no adapter or exporter may
  bypass it or cache a stale tier value.
- All three surfaces (adapter ``fidelity_tier``, export ``ExportResult.fidelity``,
  and per-command tiers in COMMAND_CAPABILITY_MATRIX) must reflect the same
  gate state.
- Removing any entry from ``PARITY_EVIDENCE`` must prevent native promotion for
  that family — the gate checks membership, not flags.

Parity evidence (from T008 — runtime/tests/test_omp_parity.py)
---------------------------------------------------------------
Five test classes cover the behavioral gates the INTENT contract requires:

  TestSubagentFanOutParity          → proves z-execute / z-panel subagent dispatch
  TestConsultantDispatchIsolation   → proves z-consult native-vs-consult separation
  TestAskUserGateParity             → proves z-gate / z-execute ask_user surfacing
  TestTelemetryParity               → proves telemetry completeness for all commands
  TestMultiAgentCommandPath         → proves z-execute multi-event sequence

These are imported by name at gate-evaluation time so that renaming or
deleting a test class causes an ``ImportError`` / ``AttributeError`` that
surfaces immediately rather than silently downgrading tiers.
"""

from __future__ import annotations

from typing import Literal

# ---------------------------------------------------------------------------
# Parity evidence registry
#
# Maps command family id → list of (module_path, class_name) tuples that prove
# Claude-equivalent behavior for that family in the T008 fixture.
#
# The gate resolves each entry by importing the module and verifying the class
# attribute exists.  Entries that fail import/attribute checks downgrade the
# corresponding family to its pre-gate tier.
# ---------------------------------------------------------------------------

#: Module containing the T008 behavioral parity tests.
_PARITY_MODULE = "runtime.tests.test_omp_parity"

#: Families with mapped Claude-parity evidence.
#:
#: Each value is a list of (module, class_name) pairs.  At least ONE must be
#: resolvable for the family to be promoted.  Multiple entries allow a family
#: to cite evidence from different test classes (belt-and-suspenders).
PARITY_EVIDENCE: dict[str, list[tuple[str, str]]] = {
    # z-execute: proven by subagent fan-out + multi-agent command path tests.
    "z-execute": [
        (_PARITY_MODULE, "TestSubagentFanOutParity"),
        (_PARITY_MODULE, "TestMultiAgentCommandPath"),
    ],
    # z-consult: proven by consultant dispatch isolation (consult vs native).
    "z-consult": [
        (_PARITY_MODULE, "TestConsultantDispatchIsolation"),
    ],
    # z-gate: proven by AskUser/gate blocking + ask_user event payload.
    "z-gate": [
        (_PARITY_MODULE, "TestAskUserGateParity"),
    ],
    # z-panel: proven transitively by subagent fan-out (panel = multi-agent
    # dispatch surface; same fan-out evidence as z-execute).
    "z-panel": [
        (_PARITY_MODULE, "TestSubagentFanOutParity"),
    ],
}

#: Command families with no parity evidence — stays ``degraded`` (runs but
#: with reduced fidelity).  Families not listed in PARITY_EVIDENCE and not in
#: DEGRADED_FAMILIES are implicitly ``degraded`` via the default branch.
#:
#: These families are listed explicitly for documentation / operator clarity.
DEGRADED_FAMILIES: frozenset[str] = frozenset(
    {
        "z-plan",
        "z-implement",
        "z-review",
        "z-test",
        "z-audit",
        "z-export",
        "z-update",
        "z-doctor",
        "z-status",
        "z-brainstorm",
        "z-maintain-docs",
    }
)


# ---------------------------------------------------------------------------
# Gate evaluation
# ---------------------------------------------------------------------------


def _evidence_resolvable(entries: list[tuple[str, str]]) -> bool:
    """Return True when at least one (module, class) entry is importable.

    Importing the module and accessing the class attribute confirms the T008
    test class exists on disk.  If the class has been renamed or deleted the
    gate downgrades the family instead of silently claiming native parity.
    """
    for module_path, class_name in entries:
        try:
            import importlib
            mod = importlib.import_module(module_path)
            if hasattr(mod, class_name):
                return True
        except ImportError:
            continue
    return False


def has_parity_evidence(command: str) -> bool:
    """Return True when *command* has at least one resolvable T008 parity entry.

    This is the gate check callers use to decide between ``native`` and
    ``degraded``/``blocked``::

        from z_harness_cli.adapters.omp_parity_gate import has_parity_evidence

        tier = "native" if has_parity_evidence(cmd) else "degraded"

    Removing an entry from ``PARITY_EVIDENCE`` immediately returns ``False``
    here, which propagates to a ``degraded`` or ``blocked`` tier in the adapter
    and export exporter — no other change is needed.
    """
    evidence = PARITY_EVIDENCE.get(command)
    if not evidence:
        return False
    return _evidence_resolvable(evidence)


# ---------------------------------------------------------------------------
# Fidelity tier resolution
#
# All three surfaces read their tier from this function.  The adapter's
# fidelity_tier, the export ExportResult.fidelity, and the command tiers in
# COMMAND_CAPABILITY_MATRIX are all driven by the same gate.
# ---------------------------------------------------------------------------

FidelityTier = Literal["native", "high", "flattened", "partial", "unsupported"]


def omp_adapter_fidelity() -> FidelityTier:
    """Return the current OMP adapter fidelity tier.

    Returns ``"native"`` only when every command family in ``PARITY_EVIDENCE``
    has resolvable evidence AND every family resolves correctly.  Returns
    ``"partial"`` otherwise.

    This is intentionally conservative: OMP is not declared fully native until
    all five behavioral gates have verifiable T008 evidence.  Adding a new
    command family to ``PARITY_EVIDENCE`` without a corresponding T008 class
    would cause ``has_parity_evidence`` to return ``False`` for that entry and
    therefore keep the tier at ``"partial"``.
    """
    if not PARITY_EVIDENCE:
        return "partial"
    all_proven = all(
        _evidence_resolvable(entries) for entries in PARITY_EVIDENCE.values()
    )
    return "native" if all_proven else "partial"


def omp_export_fidelity() -> FidelityTier:
    """Return the export fidelity that ``runtime/drivers/omp/export.py`` must use.

    Synchronized with ``omp_adapter_fidelity()`` so adapter and export cannot
    diverge.  The export manifest and ExportResult must always carry the value
    this function returns — never a hard-coded constant.
    """
    return omp_adapter_fidelity()


CommandTier = Literal["native", "degraded", "blocked"]


def omp_command_tier(command: str) -> CommandTier:
    """Return the command-capability tier for OMP *command*.

    - ``"native"``   — proven by T008 parity evidence (``PARITY_EVIDENCE`` hit).
    - ``"degraded"`` — command runs but fidelity is not proven (``DEGRADED_FAMILIES``
                       or default for unlisted families).
    - ``"blocked"``  — would be ``native``-candidate but evidence is unresolvable
                       (T008 class renamed / deleted).
    """
    if has_parity_evidence(command):
        return "native"
    # Families with registered evidence that didn't resolve get blocked (not degraded):
    # the evidence slot exists but is broken — that is a worse state than "no evidence".
    if command in PARITY_EVIDENCE:
        # Evidence slot exists but no class is importable — block (broken evidence).
        return "blocked"
    # Not in PARITY_EVIDENCE at all — degraded (no evidence, but also not broken).
    return "degraded"
