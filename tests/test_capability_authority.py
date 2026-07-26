"""Behavioral tests for the versioned capability authority (criterion #12)."""

from __future__ import annotations

import json
import os
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import pytest

from runtime.capability_authority import (
    AUTHORITY_VERSION,
    AuthorityStoreError,
    Capability,
    CapabilityAuthority,
    CapabilityEvidence,
    CapabilityKey,
)


@pytest.fixture
def key() -> CapabilityKey:
    return CapabilityKey("codex", "cli", "build-abc", "z-execute", "bounded")


@pytest.fixture
def evidence(key: CapabilityKey) -> CapabilityEvidence:
    return CapabilityEvidence(
        evidence_id="proof-1",
        authority_version=AUTHORITY_VERSION,
        key=key,
        capability=Capability.NATIVE_BOUNDED,
        evidence_surface="cli",
        installed_export_fingerprint="export-abc",
        issued_at=100,
        expires_at=200,
    )


@pytest.mark.parametrize(
    "capability",
    (
        Capability.NATIVE_BOUNDED,
        Capability.DEGRADED_SINGLE_AGENT,
        Capability.BLOCKED,
    ),
)
def test_exact_tuple_resolves_only_recorded_outcome(
    tmp_path: Path,
    evidence: CapabilityEvidence,
    capability: Capability,
) -> None:
    authority = CapabilityAuthority(tmp_path / "authority.json")
    authority.persist(replace(evidence, capability=capability))

    result = authority.resolve(
        evidence.key, installed_export_fingerprint="export-abc", now=150
    )

    assert result.capability is capability
    expected_reason = (
        "explicitly_blocked" if capability is Capability.BLOCKED else "authorized"
    )
    assert result.reason == expected_reason


def test_unknown_and_near_match_tuples_fail_closed(
    tmp_path: Path, evidence: CapabilityEvidence
) -> None:
    authority = CapabilityAuthority(tmp_path / "authority.json")
    authority.persist(evidence)

    unknown = authority.resolve(
        replace(evidence.key, runtime_build="build-other"),
        installed_export_fingerprint="export-abc",
        now=150,
    )

    assert unknown.capability is Capability.BLOCKED
    assert unknown.reason == "unknown_capability"


@pytest.mark.parametrize("now", (99, 200, 201))
def test_not_yet_valid_or_expired_evidence_is_stale(
    tmp_path: Path, evidence: CapabilityEvidence, now: int
) -> None:
    authority = CapabilityAuthority(tmp_path / "authority.json")
    authority.persist(evidence)

    result = authority.resolve(
        evidence.key, installed_export_fingerprint="export-abc", now=now
    )

    assert result.capability is Capability.BLOCKED
    assert result.reason == "stale_evidence"


def test_installed_export_mismatch_requires_re_export(
    tmp_path: Path, evidence: CapabilityEvidence
) -> None:
    authority = CapabilityAuthority(tmp_path / "authority.json")
    authority.persist(evidence)

    result = authority.resolve(
        evidence.key, installed_export_fingerprint="stale-export", now=150
    )

    assert result.capability is Capability.BLOCKED
    assert result.reason == "re_export_required"


def test_revocation_is_durable_and_fail_closed(
    tmp_path: Path, evidence: CapabilityEvidence
) -> None:
    path = tmp_path / "authority.json"
    CapabilityAuthority(path).persist(evidence)
    CapabilityAuthority(path).revoke(evidence.key, revoked_at=151, reason="build withdrawn")

    result = CapabilityAuthority(path).resolve(
        evidence.key, installed_export_fingerprint="export-abc", now=152
    )

    assert result.capability is Capability.BLOCKED
    assert result.reason == "revoked_evidence"
    assert json.loads(path.read_text())["records"]


def test_cli_evidence_cannot_promote_app_ingress(
    tmp_path: Path, evidence: CapabilityEvidence
) -> None:
    app_evidence = replace(
        evidence,
        key=replace(evidence.key, surface="app"),
        evidence_surface="cli",
    )

    with pytest.raises(ValueError, match="different ingress surface"):
        CapabilityAuthority(tmp_path / "authority.json").persist(app_evidence)


def test_malformed_and_version_mismatched_stores_fail_closed(tmp_path: Path) -> None:
    path = tmp_path / "authority.json"
    path.write_text("not-json", encoding="utf-8")
    authority = CapabilityAuthority(path)
    key = CapabilityKey("codex", "app", "build", "z-execute", "bounded")

    malformed = authority.resolve(key, installed_export_fingerprint="x", now=1)
    assert malformed.reason == "invalid_authority_store"
    path.write_text(
        json.dumps({"schema_version": 1, "authority_version": 999, "records": {}}),
        encoding="utf-8",
    )
    mismatched = authority.resolve(key, installed_export_fingerprint="x", now=1)
    assert mismatched.reason == "authority_version_mismatch"


def test_mismatched_record_identity_fails_closed(
    tmp_path: Path, evidence: CapabilityEvidence
) -> None:
    path = tmp_path / "authority.json"
    authority = CapabilityAuthority(path)
    authority.persist(evidence)
    document = json.loads(path.read_text())
    record = next(iter(document["records"].values()))
    record["key"]["posture"] = "different"
    path.write_text(json.dumps(document), encoding="utf-8")

    result = authority.resolve(
        evidence.key, installed_export_fingerprint="export-abc", now=150
    )

    assert result.capability is Capability.BLOCKED
    assert result.reason == "evidence_mismatch"


@pytest.mark.parametrize(
    ("field", "value", "expected_reason"),
    (
        ("authority_version", 999, "authority_version_mismatch"),
        ("evidence_surface", "app", "evidence_surface_mismatch"),
    ),
)
def test_mismatched_evidence_metadata_fails_closed(
    tmp_path: Path,
    evidence: CapabilityEvidence,
    field: str,
    value: object,
    expected_reason: str,
) -> None:
    path = tmp_path / "authority.json"
    authority = CapabilityAuthority(path)
    authority.persist(evidence)
    document = json.loads(path.read_text())
    record = next(iter(document["records"].values()))
    record[field] = value
    path.write_text(json.dumps(document), encoding="utf-8")

    result = authority.resolve(
        evidence.key, installed_export_fingerprint="export-abc", now=150
    )

    assert result.capability is Capability.BLOCKED
    assert result.reason == expected_reason


def test_failed_atomic_replace_preserves_previous_evidence(
    tmp_path: Path, evidence: CapabilityEvidence
) -> None:
    path = tmp_path / "authority.json"
    authority = CapabilityAuthority(path)
    authority.persist(evidence)
    before = path.read_bytes()

    with patch.object(os, "replace", side_effect=OSError("crash before publish")):
        with pytest.raises(AuthorityStoreError, match="authority write failed"):
            authority.persist(replace(evidence, capability=Capability.DEGRADED_SINGLE_AGENT))

    assert path.read_bytes() == before
    assert authority.resolve(
        evidence.key, installed_export_fingerprint="export-abc", now=150
    ).capability is Capability.NATIVE_BOUNDED


def test_mutation_refuses_to_overwrite_invalid_store(
    tmp_path: Path, evidence: CapabilityEvidence
) -> None:
    path = tmp_path / "authority.json"
    path.write_text("{}", encoding="utf-8")

    with pytest.raises(AuthorityStoreError, match="authority_schema_mismatch"):
        CapabilityAuthority(path).persist(evidence)

    assert path.read_text(encoding="utf-8") == "{}"
