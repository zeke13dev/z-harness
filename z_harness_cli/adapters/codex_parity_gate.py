"""Codex parity gate — single source of truth for fidelity and command tiers.

Codex support must advance only when Codex-specific parity evidence exists.
This gate intentionally does not treat the current host session's subagent
tools as shipped Codex capability evidence: promotion is tied to resolvable
test classes that exercise the Codex adapter/runtime surface.

Current command posture is conservative and preserves existing behaviour:
adapter fidelity remains ``flattened``; ordinary commands are ``degraded``
single-agent transliterations; and multi-agent families (``z-execute``,
``z-panel``, ``z-consult``, ``z-gate``) are ``blocked`` until their required
Codex command evidence and runtime primitive evidence resolve.  Export
fidelity may advance independently when Codex-native export artifacts are
proved.

Native subagent dispatch is intentionally gated separately from adapter-wide
fidelity and command-family tiers.  Codex CLI custom-agent export is not proof
that the active CLI has a callable native subagent dispatch primitive.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

FidelityTier = Literal["native", "high", "flattened", "partial", "unsupported"]
CommandTier = Literal["native", "degraded", "blocked"]
EvidenceEntry = tuple[str, str]
PrimitiveName = Literal["native_subagent_dispatch"]

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


# Narrow primitive evidence for z_subagent_dispatch.  Do not infer this from
# Codex adapter fidelity, exported .codex/agents TOML files, or the current
# interactive Codex session's own tools.
NATIVE_SUBAGENT_DISPATCH_EVIDENCE: list[EvidenceEntry] = [
    (_PARITY_MODULE, "TestCodexNativeSubagentDispatchPrimitive"),
]


RUNTIME_PRIMITIVE_EVIDENCE: dict[PrimitiveName, list[EvidenceEntry]] = {
    "native_subagent_dispatch": NATIVE_SUBAGENT_DISPATCH_EVIDENCE,
}


# Native command-family orchestration requires both behavioral parity evidence
# for the family and the runtime primitive needed to execute that family.  This
# keeps preservation/export/fallback fixtures from promoting command execution.
COMMAND_RUNTIME_PRIMITIVES: dict[str, tuple[PrimitiveName, ...]] = {
    command: ("native_subagent_dispatch",)
    for command in NATIVE_CANDIDATE_FAMILIES
}


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


def _runtime_primitive_entries(primitive: PrimitiveName) -> list[EvidenceEntry]:
    return RUNTIME_PRIMITIVE_EVIDENCE.get(primitive, [])


def has_runtime_primitive_evidence(primitive: PrimitiveName) -> bool:
    """Return True when the named Codex runtime primitive is proven."""
    return _all_entries_resolvable(_runtime_primitive_entries(primitive))


def _missing_runtime_primitives(command: str) -> list[str]:
    missing: list[str] = []
    for primitive in COMMAND_RUNTIME_PRIMITIVES.get(command, ()):
        entries = _runtime_primitive_entries(primitive)
        if not _all_entries_resolvable(entries):
            missing_entries = ", ".join(_missing_entries(entries))
            if missing_entries:
                missing.append(f"{primitive} ({missing_entries})")
            else:
                missing.append(primitive)
    return missing


def _command_runtime_primitives_available(command: str) -> bool:
    return not _missing_runtime_primitives(command)


def has_parity_evidence(command: str) -> bool:
    """Return True when command-family Codex evidence for *command* resolves."""
    return _all_entries_resolvable(PARITY_EVIDENCE.get(command, []))


def has_native_command_support(command: str) -> bool:
    """Return True when *command* has both command evidence and primitives."""
    return has_parity_evidence(command) and _command_runtime_primitives_available(command)


def codex_command_decision(command: str) -> CommandDecision:
    """Return the command tier and downgrade reason for *command*."""
    evidence = PARITY_EVIDENCE.get(command, [])

    if command in NATIVE_CANDIDATE_FAMILIES:
        if not evidence:
            return CommandDecision(
                tier="blocked",
                reason=(
                    "No Codex parity evidence is registered for native "
                    f"{command} support."
                ),
            )

        missing_evidence = _missing_entries(evidence)
        if missing_evidence:
            missing = ", ".join(missing_evidence)
            return CommandDecision(
                tier="blocked",
                reason=(
                    "Missing required Codex native command evidence for "
                    f"{command} support: {missing}."
                ),
            )

        missing_primitives = _missing_runtime_primitives(command)
        if missing_primitives:
            missing = ", ".join(missing_primitives)
            return CommandDecision(
                tier="blocked",
                reason=(
                    "Missing required Codex runtime primitive for native "
                    f"{command} support: {missing}."
                ),
            )

        return CommandDecision(
            tier="native",
            reason="Codex native command evidence and runtime primitives resolved.",
        )

    if evidence:
        missing_evidence = _missing_entries(evidence)
        if not missing_evidence:
            return CommandDecision(
                tier="native",
                reason="Codex parity evidence resolved for this command family.",
            )
        missing = ", ".join(missing_evidence)
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
    return all(has_native_command_support(command) for command in NATIVE_CANDIDATE_FAMILIES)


def _all_adapter_evidence_proven() -> bool:
    return _all_native_candidates_proven() and _all_entries_resolvable(ADAPTER_EVIDENCE)


def _any_adapter_evidence_resolvable() -> bool:
    return _any_resolvable(PARITY_EVIDENCE) or any(
        _entry_resolvable(entry) for entry in ADAPTER_EVIDENCE
    ) or any(
        _entry_resolvable(entry)
        for entries in RUNTIME_PRIMITIVE_EVIDENCE.values()
        for entry in entries
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


def codex_native_subagent_dispatch_available() -> bool:
    """Return whether Codex native subagent dispatch is explicitly proven.

    This is a primitive-level gate for MCP ``z_subagent_dispatch``.  It must
    remain independent from command-family promotion and export fidelity:
    exported ``.codex/agents/*.toml`` files are necessary host artifacts, not
    evidence that the CLI can dispatch one by name at runtime.
    """
    return has_runtime_primitive_evidence("native_subagent_dispatch")
