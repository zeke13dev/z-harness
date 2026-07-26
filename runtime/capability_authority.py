"""Versioned, fail-closed capability and promotion authority.

The authority binds one decision to the exact host, ingress surface, runtime
build, command, posture, and installed-export fingerprint that produced its
evidence (INTENT criterion #12).  Unknown, malformed, expired, revoked, or
cross-surface evidence never authorizes work.  This module defines the durable
contract only; executable-boundary wiring is intentionally deferred.

Exported surface:

* ``CapabilityKey`` identifies the exact invocation being authorized.
* ``CapabilityEvidence`` is the immutable evidence supplied for promotion.
* ``CapabilityAuthority.persist`` and ``revoke`` update the store atomically.
* ``CapabilityAuthority.resolve`` returns a deterministic fail-closed result.

Concurrency: writers serialize through a sidecar ``flock`` and publish a fully
fsynced JSON document with ``os.replace``.  Readers need no lock because they
can observe only the complete old or complete new document.
"""

from __future__ import annotations

import fcntl
import json
import os
import tempfile
from dataclasses import asdict, dataclass
from enum import Enum
from pathlib import Path


SCHEMA_VERSION = 1
AUTHORITY_VERSION = 1


class Capability(str, Enum):
    """The complete set of authority outcomes."""

    NATIVE_BOUNDED = "native_bounded"
    DEGRADED_SINGLE_AGENT = "degraded_single_agent"
    BLOCKED = "blocked"


@dataclass(frozen=True)
class CapabilityKey:
    """Identify an invocation at the exact authorization granularity."""

    host: str
    surface: str
    runtime_build: str
    command: str
    posture: str


@dataclass(frozen=True)
class CapabilityEvidence:
    """Immutable evidence for one exact capability decision.

    ``evidence_surface`` records where the proof was collected.  It must equal
    the target key's ingress surface, preventing CLI evidence from promoting
    Codex App ingress.  Times are UTC epoch seconds and ``expires_at`` is an
    exclusive bound. Optional primitive claims name the exact executable host
    operations proven for bounded terminal collection and child termination.
    """

    evidence_id: str
    authority_version: int
    key: CapabilityKey
    capability: Capability
    evidence_surface: str
    installed_export_fingerprint: str
    issued_at: int
    expires_at: int
    terminal_collection_primitive: str | None = None
    active_child_termination_primitive: str | None = None


@dataclass(frozen=True)
class CapabilityResolution:
    """A deterministic authorization outcome and audit-safe reason."""

    capability: Capability
    reason: str
    evidence_id: str | None = None
    terminal_collection_primitive: str | None = None
    active_child_termination_primitive: str | None = None


class AuthorityStoreError(RuntimeError):
    """Raised when a durable authority mutation cannot be performed safely."""


class CapabilityAuthority:
    """Persist and resolve exact capability evidence.

    Store mutations hard-fail rather than replacing unreadable or incompatible
    evidence.  Resolution is deliberately best-effort and returns ``blocked``
    with a stable reason for every invalid state.
    """

    def __init__(self, path: Path | str) -> None:
        """Create an authority backed by ``path``; no I/O occurs yet."""

        self._path = Path(path)
        self._lock_path = self._path.with_name(f"{self._path.name}.lock")

    def persist(self, evidence: CapabilityEvidence) -> None:
        """Atomically publish or replace evidence for its exact key. Hard-fail.

        Args:
            evidence: Versioned evidence to publish.

        Raises:
            ValueError: if evidence is invalid or crosses ingress surfaces.
            AuthorityStoreError: if the existing store is malformed or I/O
                prevents a durable update; no sentinel fallback is used.
        """

        _validate_evidence(evidence)
        with self._exclusive_lock():
            document, invalid_reason = self._load_document()
            if invalid_reason is not None:
                raise AuthorityStoreError(f"cannot update authority: {invalid_reason}")
            records = document["records"]
            records[_key_id(evidence.key)] = _evidence_to_record(evidence)
            self._atomic_write(document)

    def revoke(self, key: CapabilityKey, *, revoked_at: int, reason: str) -> None:
        """Atomically revoke evidence for ``key``. Hard-fail.

        Args:
            key: Exact tuple whose evidence must be revoked.
            revoked_at: UTC epoch second of revocation.
            reason: Non-empty audit reason.

        Raises:
            ValueError: if the timestamp or reason is invalid.
            KeyError: if no exact evidence exists.
            AuthorityStoreError: if the store is malformed or cannot be
                durably updated; no sentinel fallback is used.
        """

        if revoked_at < 0 or not reason:
            raise ValueError("revocation requires a non-negative time and non-empty reason")
        with self._exclusive_lock():
            document, invalid_reason = self._load_document()
            if invalid_reason is not None:
                raise AuthorityStoreError(f"cannot revoke authority: {invalid_reason}")
            key_id = _key_id(key)
            record = document["records"].get(key_id)
            if record is None:
                raise KeyError("no evidence for exact capability tuple")
            updated = dict(record)
            updated["revoked_at"] = revoked_at
            updated["revocation_reason"] = reason
            document["records"][key_id] = updated
            self._atomic_write(document)

    def resolve(
        self,
        key: CapabilityKey,
        *,
        installed_export_fingerprint: str,
        now: int,
    ) -> CapabilityResolution:
        """Resolve an exact tuple, returning ``blocked`` on every uncertainty.

        Args:
            key: Exact invocation tuple.
            installed_export_fingerprint: Fingerprint of the installed export
                that would execute the command.
            now: Current UTC epoch second for deterministic expiry checks.

        Returns:
            The authorized capability or ``blocked`` with a stable reason.
            This best-effort read never raises for absent or malformed state.
        """

        document, invalid_reason = self._load_document()
        if invalid_reason is not None:
            return _blocked(invalid_reason)
        record = document["records"].get(_key_id(key))
        if record is None:
            return _blocked("unknown_capability")
        evidence = _record_to_evidence(record)
        if evidence is None or evidence.key != key:
            return _blocked("evidence_mismatch")
        if evidence.authority_version != AUTHORITY_VERSION:
            return _blocked("authority_version_mismatch", evidence.evidence_id)
        if evidence.evidence_surface != key.surface:
            return _blocked("evidence_surface_mismatch", evidence.evidence_id)
        if record.get("revoked_at") is not None:
            return _blocked("revoked_evidence", evidence.evidence_id)
        if now < evidence.issued_at or now >= evidence.expires_at:
            return _blocked("stale_evidence", evidence.evidence_id)
        if evidence.installed_export_fingerprint != installed_export_fingerprint:
            return _blocked("re_export_required", evidence.evidence_id)
        if evidence.capability is Capability.BLOCKED:
            return _blocked("explicitly_blocked", evidence.evidence_id)
        return CapabilityResolution(
            evidence.capability,
            "authorized",
            evidence.evidence_id,
            evidence.terminal_collection_primitive,
            evidence.active_child_termination_primitive,
        )

    def _load_document(self) -> tuple[dict[str, object], str | None]:
        """Best-effort load; return a fail-closed reason rather than raise."""

        if not self._path.exists():
            return _empty_document(), None
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            return _empty_document(), "invalid_authority_store"
        if not isinstance(raw, dict):
            return _empty_document(), "invalid_authority_store"
        if raw.get("schema_version") != SCHEMA_VERSION:
            return _empty_document(), "authority_schema_mismatch"
        if raw.get("authority_version") != AUTHORITY_VERSION:
            return _empty_document(), "authority_version_mismatch"
        if not isinstance(raw.get("records"), dict):
            return _empty_document(), "invalid_authority_store"
        return raw, None

    def _atomic_write(self, document: dict[str, object]) -> None:
        """Publish ``document`` via fsync and atomic replace. Hard-fail."""

        temp_path: Path | None = None
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            descriptor, temp_name = tempfile.mkstemp(
                prefix=f".{self._path.name}.", suffix=".tmp", dir=self._path.parent
            )
            temp_path = Path(temp_name)
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(document, handle, indent=2, sort_keys=True)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_path, self._path)
            directory_fd = os.open(self._path.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except (OSError, TypeError, ValueError) as exc:
            raise AuthorityStoreError(f"authority write failed: {exc}") from exc
        finally:
            if temp_path is not None:
                try:
                    temp_path.unlink(missing_ok=True)
                except OSError:
                    pass

    def _exclusive_lock(self) -> _FileLock:
        """Return the hard-fail writer lock context."""

        return _FileLock(self._lock_path)


class _FileLock:
    """Exclusive sidecar lock used by authority mutations."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._descriptor: int | None = None

    def __enter__(self) -> _FileLock:
        """Acquire the lock. Hard-fail on filesystem errors."""

        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._descriptor = os.open(self._path, os.O_CREAT | os.O_RDWR, 0o600)
            fcntl.flock(self._descriptor, fcntl.LOCK_EX)
        except OSError as exc:
            if self._descriptor is not None:
                os.close(self._descriptor)
                self._descriptor = None
            raise AuthorityStoreError(f"authority lock failed: {exc}") from exc
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        """Release the lock; cleanup is best-effort and never masks failures."""

        if self._descriptor is None:
            return
        try:
            try:
                fcntl.flock(self._descriptor, fcntl.LOCK_UN)
            finally:
                os.close(self._descriptor)
        except OSError:
            pass
        self._descriptor = None


def _empty_document() -> dict[str, object]:
    """Return a new schema-complete authority document."""

    return {
        "schema_version": SCHEMA_VERSION,
        "authority_version": AUTHORITY_VERSION,
        "records": {},
    }


def _key_id(key: CapabilityKey) -> str:
    """Return a collision-free canonical JSON representation of ``key``."""

    return json.dumps(asdict(key), sort_keys=True, separators=(",", ":"))


def _validate_evidence(evidence: CapabilityEvidence) -> None:
    """Validate promotion evidence. Hard-fail with ``ValueError``."""

    values = (*asdict(evidence.key).values(), evidence.evidence_id, evidence.evidence_surface)
    if any(not isinstance(value, str) or not value for value in values):
        raise ValueError("capability tuple and evidence identity fields must be non-empty strings")
    if not evidence.installed_export_fingerprint:
        raise ValueError("installed export fingerprint must be non-empty")
    if not isinstance(evidence.capability, Capability):
        raise ValueError("capability must be a recognized authority outcome")
    if evidence.authority_version != AUTHORITY_VERSION:
        raise ValueError("evidence authority version does not match this authority")
    if evidence.evidence_surface != evidence.key.surface:
        raise ValueError("evidence cannot promote a different ingress surface")
    if type(evidence.issued_at) is not int or type(evidence.expires_at) is not int:
        raise ValueError("evidence times must be integer UTC epoch seconds")
    if evidence.issued_at < 0 or evidence.expires_at <= evidence.issued_at:
        raise ValueError("evidence expiry must be later than its non-negative issue time")
    primitive_claims = (
        evidence.terminal_collection_primitive,
        evidence.active_child_termination_primitive,
    )
    if any(
        claim is not None and (not isinstance(claim, str) or not claim)
        for claim in primitive_claims
    ):
        raise ValueError("primitive claims must be non-empty strings when present")


def _evidence_to_record(evidence: CapabilityEvidence) -> dict[str, object]:
    """Serialize immutable evidence to its durable representation."""

    return {
        "evidence_id": evidence.evidence_id,
        "authority_version": evidence.authority_version,
        "key": asdict(evidence.key),
        "capability": evidence.capability.value,
        "evidence_surface": evidence.evidence_surface,
        "installed_export_fingerprint": evidence.installed_export_fingerprint,
        "issued_at": evidence.issued_at,
        "expires_at": evidence.expires_at,
        "terminal_collection_primitive": evidence.terminal_collection_primitive,
        "active_child_termination_primitive": evidence.active_child_termination_primitive,
        "revoked_at": None,
        "revocation_reason": None,
    }


def _record_to_evidence(record: object) -> CapabilityEvidence | None:
    """Best-effort parse of a durable record; return ``None`` when malformed."""

    if not isinstance(record, dict) or not isinstance(record.get("key"), dict):
        return None
    try:
        key = CapabilityKey(**record["key"])
        evidence = CapabilityEvidence(
            evidence_id=record["evidence_id"],
            authority_version=record["authority_version"],
            key=key,
            capability=Capability(record["capability"]),
            evidence_surface=record["evidence_surface"],
            installed_export_fingerprint=record["installed_export_fingerprint"],
            issued_at=record["issued_at"],
            expires_at=record["expires_at"],
            terminal_collection_primitive=record.get("terminal_collection_primitive"),
            active_child_termination_primitive=record.get(
                "active_child_termination_primitive"
            ),
        )
    except (KeyError, TypeError, ValueError):
        return None
    string_values = (
        *asdict(evidence.key).values(),
        evidence.evidence_id,
        evidence.evidence_surface,
        evidence.installed_export_fingerprint,
    )
    if any(not isinstance(value, str) or not value for value in string_values):
        return None
    if type(evidence.authority_version) is not int:
        return None
    if type(evidence.issued_at) is not int or type(evidence.expires_at) is not int:
        return None
    if evidence.issued_at < 0 or evidence.expires_at <= evidence.issued_at:
        return None
    primitive_claims = (
        evidence.terminal_collection_primitive,
        evidence.active_child_termination_primitive,
    )
    if any(
        claim is not None and (not isinstance(claim, str) or not claim)
        for claim in primitive_claims
    ):
        return None
    return evidence


def _blocked(reason: str, evidence_id: str | None = None) -> CapabilityResolution:
    """Return the single fail-closed outcome with a deterministic reason."""

    return CapabilityResolution(Capability.BLOCKED, reason, evidence_id)
