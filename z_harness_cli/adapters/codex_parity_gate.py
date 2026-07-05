"""Codex parity gate — single source of truth for fidelity and command tiers.

Codex support must advance only when Codex-specific parity evidence exists.
This gate intentionally does not treat the current host session's subagent
tools as shipped Codex capability evidence: promotion is tied to resolvable
test classes that exercise the Codex adapter/runtime surface.

Current default posture is conservative and preserves existing behaviour:
adapter/export fidelity remains ``flattened``; ordinary commands are
``degraded`` single-agent transliterations; and multi-agent families
(``z-execute``, ``z-panel``, ``z-consult``, ``z-gate``) are ``blocked`` until
their required Codex evidence classes resolve.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

FidelityTier = Literal["native", "high", "flattened", "partial", "unsupported"]
CommandTier = Literal["native", "degraded", "blocked"]
EvidenceEntry = tuple[str, str]

_PARITY_MODULE = "runtime.tests.test_codex_parity"
_EXPORT_MODULE = "tests.drivers.test_codex_export_driver"


@dataclass(frozen=True)
class CommandDecision:
    """Gate decision for one command family."""

    tier: CommandTier
    reason: str


# Multi-agent command families that must remain blocked unless Codex-native
# behavioral parity has been proved for that family.
NATIVE_CANDIDATE_FAMILIES: frozenset[str] = frozenset(
    {
        "z-execute",
        "z-panel",
        "z-consult",
        "z-gate",
    }
)


# Anticipated Codex parity evidence.  These modules/classes are intentionally
# Codex-specific and may not exist yet.  Missing or renamed classes keep the
# corresponding family blocked rather than silently promoting native support.
PARITY_EVIDENCE: dict[str, list[EvidenceEntry]] = {
    "z-execute": [
        (_PARITY_MODULE, "TestSubagentFanOutParity"),
        (_PARITY_MODULE, "TestMultiAgentCommandPath"),
    ],
    "z-consult": [
        (_PARITY_MODULE, "TestConsultantDispatchIsolation"),
    ],
    "z-gate": [
        (_PARITY_MODULE, "TestAskUserGateParity"),
    ],
    "z-panel": [
        (_PARITY_MODULE, "TestSubagentFanOutParity"),
    ],
}


# Adapter-wide evidence that is not owned by a single command family.
ADAPTER_EVIDENCE: list[EvidenceEntry] = [
    (_PARITY_MODULE, "TestTelemetryParity"),
]


# Export fidelity is separately gated so runtime export cannot claim native
# Codex agent export just because command/runtime evidence appears.
EXPORT_EVIDENCE: list[EvidenceEntry] = [
    (_EXPORT_MODULE, "TestCodexNativeAgentExport"),
]


def _entry_resolvable(entry: EvidenceEntry) -> bool:
    module_path, class_name = entry
    try:
        import importlib

        mod = importlib.import_module(module_path)
    except ImportError:
        return False
    return hasattr(mod, class_name)


def _all_entries_resolvable(entries: list[EvidenceEntry]) -> bool:
    return bool(entries) and all(_entry_resolvable(entry) for entry in entries)


def _missing_entries(entries: list[EvidenceEntry]) -> list[str]:
    return [
        f"{module_path}.{class_name}"
        for module_path, class_name in entries
        if not _entry_resolvable((module_path, class_name))
    ]


def _any_resolvable(entries_by_family: dict[str, list[EvidenceEntry]]) -> bool:
    return any(
        _entry_resolvable(entry)
        for entries in entries_by_family.values()
        for entry in entries
    )


def has_parity_evidence(command: str) -> bool:
    """Return True when all required Codex evidence for *command* resolves."""
    return _all_entries_resolvable(PARITY_EVIDENCE.get(command, []))


def codex_command_decision(command: str) -> CommandDecision:
    """Return the command tier and downgrade reason for *command*."""
    evidence = PARITY_EVIDENCE.get(command, [])
    if evidence and _all_entries_resolvable(evidence):
        return CommandDecision(
            tier="native",
            reason="Codex parity evidence resolved for this command family.",
        )

    if command in NATIVE_CANDIDATE_FAMILIES:
        if evidence:
            missing = ", ".join(_missing_entries(evidence))
            return CommandDecision(
                tier="blocked",
                reason=(
                    "Missing required Codex parity evidence for native "
                    f"{command} support: {missing}."
                ),
            )
        return CommandDecision(
            tier="blocked",
            reason=(
                "No Codex parity evidence is registered for native "
                f"{command} support."
            ),
        )

    if evidence:
        missing = ", ".join(_missing_entries(evidence))
        return CommandDecision(
            tier="blocked",
            reason=(
                "Codex parity evidence is registered but unresolvable for "
                f"{command}: {missing}."
            ),
        )

    return CommandDecision(
        tier="degraded",
        reason="No native Codex parity evidence registered; using degraded single-agent transliteration.",
    )


def codex_command_tier(command: str) -> CommandTier:
    """Return the Codex command tier authorized by the parity gate."""
    return codex_command_decision(command).tier


def _all_native_candidates_proven() -> bool:
    return all(has_parity_evidence(command) for command in NATIVE_CANDIDATE_FAMILIES)


def _all_adapter_evidence_proven() -> bool:
    return _all_native_candidates_proven() and _all_entries_resolvable(ADAPTER_EVIDENCE)


def _any_adapter_evidence_resolvable() -> bool:
    return _any_resolvable(PARITY_EVIDENCE) or any(
        _entry_resolvable(entry) for entry in ADAPTER_EVIDENCE
    )


def codex_adapter_fidelity() -> FidelityTier:
    """Return the current Codex adapter fidelity tier.

    ``native`` requires all native-candidate command families to have
    resolvable Codex parity evidence.  Partial evidence yields ``partial``.
    With no evidence, the adapter remains ``flattened`` to preserve current
    shipped behaviour.
    """
    if _all_adapter_evidence_proven():
        return "native"
    if _any_adapter_evidence_resolvable():
        return "partial"
    return "flattened"


def codex_export_fidelity() -> FidelityTier:
    """Return the Codex export fidelity tier authorized by evidence.

    Export promotion requires native command-family evidence and explicit
    Codex-native export evidence.  This prevents the runtime exporter from
    overclaiming native export fidelity before native agent export is proved.
    """
    if _all_adapter_evidence_proven() and _all_entries_resolvable(EXPORT_EVIDENCE):
        return "native"
    if _any_adapter_evidence_resolvable() or any(
        _entry_resolvable(entry) for entry in EXPORT_EVIDENCE
    ):
        return "partial"
    return "flattened"
