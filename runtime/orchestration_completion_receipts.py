"""Exactly-once logical-completion receipts for controlled result channels.

This module advances INTENT criterion #11. A host-owned capability authenticates
nonce-, channel-, logical-work-, and event-bound markers plus the channel-close
transition. Terminal acceptance requires the authenticated close to arrive only
after every expected completion, so model-authored prose or a caller-chosen
channel identifier cannot stand in for host-observed completion.

The validator is intentionally in-memory and single-owner. The first protocol
failure poisons it, and later calls reproduce the same bounded, content-free
failure artifact. Retained identifiers are trial-scoped keyed pseudonyms rather
than stable hashes, preventing correlation of equal identifiers across trials.

Exported surface:
  - ``build_controlled_marker`` authenticates a host-channel completion marker.
  - ``build_controlled_channel_close`` authenticates the drained-channel close.
  - ``CompletionReceiptValidator`` retains receipts and gates terminal acceptance.
  - ``CompletionReceipt`` and ``CompletionFailure`` are immutable artifacts.
  - ``CompletionValidationError`` carries deterministic rejection evidence.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import hashlib
import hmac


SCHEMA_VERSION = 1
_MARKER_FIELDS = frozenset(
    {"schema_version", "nonce", "channel_id", "logical_work_id", "event_id", "binding"}
)
_CHANNEL_CLOSE_FIELDS = frozenset(
    {"schema_version", "nonce", "channel_id", "marker_count", "binding"}
)
_MAX_IDENTITY_BYTES = 256
_MAX_EXPECTED_COUNT = 1024
_HOST_CAPABILITY_BYTES = 32
_SHA256_HEX_LENGTH = 64
_LOWER_HEX = frozenset("0123456789abcdef")


def _framed_bytes(domain: str, *parts: str) -> bytes:
    """Return unambiguous domain-separated bytes for validated text parts."""
    payload = bytearray(b"z-harness-completion-v1\x00")
    for part in (domain, *parts):
        encoded = part.encode("utf-8")
        payload.extend(len(encoded).to_bytes(4, "big"))
        payload.extend(encoded)
    return bytes(payload)


def _keyed_digest(host_capability: bytes, domain: str, *parts: str) -> str:
    """Return a domain-separated SHA-256 HMAC in canonical lowercase hex."""
    return hmac.new(
        host_capability,
        _framed_bytes(domain, *parts),
        hashlib.sha256,
    ).hexdigest()


def _valid_text(value: object) -> bool:
    """Return whether an identity is non-empty, UTF-8-safe, and byte-bounded."""
    if not isinstance(value, str):
        return False
    try:
        encoded = value.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return 0 < len(encoded) <= _MAX_IDENTITY_BYTES


def _valid_binding(value: object) -> bool:
    """Return whether a binding is canonical ASCII SHA-256 hex."""
    return (
        isinstance(value, str)
        and len(value) == _SHA256_HEX_LENGTH
        and all(character in _LOWER_HEX for character in value)
    )


def _require_identity(value: object, name: str) -> str:
    """Validate one boundary-owned identity and hard-fail on invalid input.

    Args:
        value: Candidate identity.
        name: Field name used in the diagnostic.

    Returns:
        The validated UTF-8-safe string.

    Raises:
        ValueError: If the identity is empty, invalid UTF-8, non-string, or
            longer than the protocol byte limit. There is no fallback.
    """
    if not _valid_text(value):
        raise ValueError(
            f"{name} must be a non-empty UTF-8 string of at most "
            f"{_MAX_IDENTITY_BYTES} bytes"
        )
    return value


def _require_host_capability(value: object) -> bytes:
    """Require the exact-size immutable host capability used by the protocol.

    Args:
        value: Candidate out-of-band host capability.

    Returns:
        The validated immutable capability bytes.

    Raises:
        ValueError: If the capability is not exactly 32 bytes. There is no
            fallback because unauthenticated markers must never be admitted.
    """
    if not isinstance(value, bytes) or len(value) != _HOST_CAPABILITY_BYTES:
        raise ValueError(
            f"host_capability must be exactly {_HOST_CAPABILITY_BYTES} bytes"
        )
    return value


def build_controlled_marker(
    *,
    nonce: str,
    channel_id: str,
    logical_work_id: str,
    event_id: str,
    host_capability: bytes,
) -> dict[str, object]:
    """Build a host-authenticated logical-completion marker.

    The out-of-band capability must remain at the host boundary. Possession of
    public envelope values, including ``channel_id``, is insufficient to forge
    a marker.

    Args:
        nonce: Fresh benchmark-trial nonce.
        channel_id: Identity of the host-owned result channel.
        logical_work_id: Immutable identity of the completed logical work.
        event_id: Unique host terminal-event identity used for replay detection.
        host_capability: Exact 32-byte secret owned by the host boundary.

    Returns:
        A closed marker mapping with an HMAC-SHA-256 binding.

    Raises:
        ValueError: If any identity or the host capability violates its protocol
            bound. There is no fallback.
    """
    nonce = _require_identity(nonce, "nonce")
    channel_id = _require_identity(channel_id, "channel_id")
    logical_work_id = _require_identity(logical_work_id, "logical_work_id")
    event_id = _require_identity(event_id, "event_id")
    host_capability = _require_host_capability(host_capability)
    return {
        "schema_version": SCHEMA_VERSION,
        "nonce": nonce,
        "channel_id": channel_id,
        "logical_work_id": logical_work_id,
        "event_id": event_id,
        "binding": _keyed_digest(
            host_capability,
            "marker",
            str(SCHEMA_VERSION),
            nonce,
            channel_id,
            logical_work_id,
            event_id,
        ),
    }


def build_controlled_channel_close(
    *,
    nonce: str,
    channel_id: str,
    marker_count: int,
    host_capability: bytes,
) -> dict[str, object]:
    """Build the host-authenticated transition that seals a drained channel.

    Args:
        nonce: Fresh benchmark-trial nonce.
        channel_id: Identity of the host-owned result channel.
        marker_count: Number of markers the host drained before closing.
        host_capability: Exact 32-byte secret owned by the host boundary.

    Returns:
        A closed channel-close mapping with an HMAC-SHA-256 binding.

    Raises:
        ValueError: If an identity, count, or capability violates its protocol
            bound. There is no fallback.
    """
    nonce = _require_identity(nonce, "nonce")
    channel_id = _require_identity(channel_id, "channel_id")
    if type(marker_count) is not int or not 0 <= marker_count <= _MAX_EXPECTED_COUNT:
        raise ValueError(
            f"marker_count must be an integer from 0 to {_MAX_EXPECTED_COUNT}"
        )
    host_capability = _require_host_capability(host_capability)
    return {
        "schema_version": SCHEMA_VERSION,
        "nonce": nonce,
        "channel_id": channel_id,
        "marker_count": marker_count,
        "binding": _keyed_digest(
            host_capability,
            "channel-close",
            str(SCHEMA_VERSION),
            nonce,
            channel_id,
            str(marker_count),
        ),
    }


@dataclass(frozen=True, slots=True)
class CompletionReceipt:
    """Fixed-size, content-free evidence of one validated logical completion."""

    schema_version: int
    receipt_id: str
    trial_pseudonym: str
    channel_pseudonym: str
    logical_work_pseudonym: str
    event_pseudonym: str
    marker_authenticator_sha256: str


@dataclass(frozen=True, slots=True)
class CompletionFailure:
    """Deterministic, bounded, content-free terminal-rejection evidence."""

    schema_version: int
    status: str
    code: str
    trial_pseudonym: str
    logical_work_pseudonym: str | None
    affected_count: int


class CompletionValidationError(ValueError):
    """Raised with an immutable failure artifact when validation fails."""

    def __init__(self, artifact: CompletionFailure) -> None:
        super().__init__(f"logical completion validation rejected: {artifact.code}")
        self.artifact = artifact


class CompletionReceiptValidator:
    """Validate authenticated controlled markers exactly once before acceptance."""

    def __init__(
        self,
        *,
        nonce: str,
        channel_id: str,
        expected_logical_work_ids: tuple[str, ...],
        host_capability: bytes,
    ) -> None:
        """Create a single-trial validator with an immutable expected-work set.

        Args:
            nonce: Fresh benchmark-trial nonce.
            channel_id: Exact controlled result-channel identity.
            expected_logical_work_ids: Non-empty ordered logical-work identities.
            host_capability: Exact 32-byte secret owned by the host boundary.

        Raises:
            ValueError: If an identity or capability is invalid, expected work
                is empty or duplicated, or its count exceeds the protocol
                maximum. Construction hard-fails; there is no fallback.
        """
        self._nonce = _require_identity(nonce, "nonce")
        self._channel_id = _require_identity(channel_id, "channel_id")
        self._host_capability = _require_host_capability(host_capability)
        if not isinstance(expected_logical_work_ids, tuple) or not expected_logical_work_ids:
            raise ValueError("expected_logical_work_ids must be a non-empty tuple")
        if len(expected_logical_work_ids) > _MAX_EXPECTED_COUNT:
            raise ValueError(
                "expected_logical_work_ids must contain at most "
                f"{_MAX_EXPECTED_COUNT} identities"
            )
        expected = tuple(
            _require_identity(value, "logical_work_id") for value in expected_logical_work_ids
        )
        if len(expected) != len(set(expected)):
            raise ValueError("expected_logical_work_ids must be unique")
        self._expected = expected
        self._expected_set = frozenset(expected)
        self._receipts: dict[str, CompletionReceipt] = {}
        self._seen_events: set[str] = set()
        self._failure: CompletionFailure | None = None
        self._channel_closed = False
        self._terminal_accepted = False

    @property
    def receipts(self) -> tuple[CompletionReceipt, ...]:
        """Return retained immutable receipts in expected-work order."""
        return tuple(self._receipts[item] for item in self._expected if item in self._receipts)

    def _pseudonym(self, label: str, value: str) -> str:
        """Return a trial-scoped keyed pseudonym for one validated identity."""
        return _keyed_digest(
            self._host_capability,
            "trial-pseudonym",
            self._nonce,
            label,
            value,
        )

    def _reject(
        self,
        code: str,
        *,
        logical_work_id: str | None = None,
        affected_count: int = 1,
    ) -> None:
        """Poison validation and raise the first deterministic failure artifact.

        Args:
            code: Closed protocol rejection code.
            logical_work_id: Optional validated work identity to pseudonymize.
            affected_count: Bounded number of affected logical completions.

        Raises:
            CompletionValidationError: Always. Later calls reproduce the first
                artifact so malformed input cannot steer terminal diagnostics.
        """
        if self._failure is None:
            self._failure = CompletionFailure(
                schema_version=SCHEMA_VERSION,
                status="rejected",
                code=code,
                trial_pseudonym=self._pseudonym("trial", self._nonce),
                logical_work_pseudonym=(
                    self._pseudonym("logical-work", logical_work_id)
                    if logical_work_id is not None
                    else None
                ),
                affected_count=affected_count,
            )
        raise CompletionValidationError(self._failure)

    def record_controlled_marker(self, marker: Mapping[str, object]) -> CompletionReceipt:
        """Validate and retain one marker delivered by the controlled channel.

        Args:
            marker: Closed envelope from ``build_controlled_marker``.

        Returns:
            The newly retained immutable receipt.

        Raises:
            CompletionValidationError: If validation already failed or reached
                terminal acceptance, the channel is closed, or the marker is
                malformed, unauthenticated, unexpected, duplicated, or replayed.
        """
        if self._failure is not None:
            raise CompletionValidationError(self._failure)
        if self._terminal_accepted:
            self._reject("terminal_already_accepted")
        if self._channel_closed:
            self._reject("marker_after_channel_close")
        if not isinstance(marker, Mapping) or frozenset(marker) != _MARKER_FIELDS:
            self._reject("malformed_marker")
        if type(marker["schema_version"]) is not int or marker["schema_version"] != SCHEMA_VERSION:
            self._reject("malformed_marker")
        if not all(
            _valid_text(marker[field])
            for field in ("nonce", "channel_id", "logical_work_id", "event_id")
        ) or not _valid_binding(marker["binding"]):
            self._reject("malformed_marker")

        nonce = marker["nonce"]
        channel_id = marker["channel_id"]
        logical_work_id = marker["logical_work_id"]
        event_id = marker["event_id"]
        binding = marker["binding"]
        assert isinstance(nonce, str)
        assert isinstance(channel_id, str)
        assert isinstance(logical_work_id, str)
        assert isinstance(event_id, str)
        assert isinstance(binding, str)

        if nonce != self._nonce:
            self._reject("nonce_mismatch")
        if channel_id != self._channel_id:
            self._reject("channel_mismatch")
        if logical_work_id not in self._expected_set:
            self._reject("unexpected_logical_work")
        expected_binding = _keyed_digest(
            self._host_capability,
            "marker",
            str(SCHEMA_VERSION),
            nonce,
            channel_id,
            logical_work_id,
            event_id,
        )
        if not hmac.compare_digest(binding.encode("ascii"), expected_binding.encode("ascii")):
            self._reject("malformed_binding", logical_work_id=logical_work_id)
        event_key = self._pseudonym("event", event_id)
        if event_key in self._seen_events:
            self._reject("replayed_marker", logical_work_id=logical_work_id)
        if logical_work_id in self._receipts:
            self._reject("duplicate_logical_work", logical_work_id=logical_work_id)

        receipt = CompletionReceipt(
            schema_version=SCHEMA_VERSION,
            receipt_id=_keyed_digest(
                self._host_capability,
                "receipt",
                nonce,
                channel_id,
                logical_work_id,
                event_id,
                binding,
            ),
            trial_pseudonym=self._pseudonym("trial", nonce),
            channel_pseudonym=self._pseudonym("channel", channel_id),
            logical_work_pseudonym=self._pseudonym("logical-work", logical_work_id),
            event_pseudonym=event_key,
            marker_authenticator_sha256=hashlib.sha256(
                binding.encode("ascii")
            ).hexdigest(),
        )
        self._seen_events.add(event_key)
        self._receipts[logical_work_id] = receipt
        return receipt

    def close_controlled_channel(self, channel_close: Mapping[str, object]) -> None:
        """Authenticate the host transition that seals the drained channel.

        Args:
            channel_close: Closed envelope from
                ``build_controlled_channel_close``.

        Raises:
            CompletionValidationError: If validation already failed, close is
                malformed, unauthenticated, duplicated, reordered before all
                expected receipts, or disagrees with the drained marker count.
                There is no fallback.
        """
        if self._failure is not None:
            raise CompletionValidationError(self._failure)
        if self._terminal_accepted:
            self._reject("terminal_already_accepted")
        if self._channel_closed:
            self._reject("duplicate_channel_close")
        if (
            not isinstance(channel_close, Mapping)
            or frozenset(channel_close) != _CHANNEL_CLOSE_FIELDS
        ):
            self._reject("malformed_channel_close")
        if (
            type(channel_close["schema_version"]) is not int
            or channel_close["schema_version"] != SCHEMA_VERSION
            or not _valid_text(channel_close["nonce"])
            or not _valid_text(channel_close["channel_id"])
            or type(channel_close["marker_count"]) is not int
            or not 0 <= channel_close["marker_count"] <= _MAX_EXPECTED_COUNT
            or not _valid_binding(channel_close["binding"])
        ):
            self._reject("malformed_channel_close")

        nonce = channel_close["nonce"]
        channel_id = channel_close["channel_id"]
        marker_count = channel_close["marker_count"]
        binding = channel_close["binding"]
        assert isinstance(nonce, str)
        assert isinstance(channel_id, str)
        assert isinstance(marker_count, int)
        assert isinstance(binding, str)

        if nonce != self._nonce:
            self._reject("channel_close_nonce_mismatch")
        if channel_id != self._channel_id:
            self._reject("channel_close_channel_mismatch")
        expected_binding = _keyed_digest(
            self._host_capability,
            "channel-close",
            str(SCHEMA_VERSION),
            nonce,
            channel_id,
            str(marker_count),
        )
        if not hmac.compare_digest(binding.encode("ascii"), expected_binding.encode("ascii")):
            self._reject("malformed_channel_close_binding")
        if marker_count != len(self._receipts):
            self._reject(
                "channel_marker_count_mismatch",
                affected_count=abs(marker_count - len(self._receipts)),
            )
        missing = tuple(item for item in self._expected if item not in self._receipts)
        if missing:
            self._reject(
                "missing_logical_work",
                logical_work_id=missing[0] if len(missing) == 1 else None,
                affected_count=len(missing),
            )
        self._channel_closed = True

    def finalize(self) -> tuple[CompletionReceipt, ...]:
        """Accept terminal completion only after authenticated channel close.

        Returns:
            Exactly one immutable receipt per expected logical work item, in the
            constructor's deterministic order.

        Raises:
            CompletionValidationError: If validation previously failed, the
                controlled channel has not authenticated its drained close, or
                any expected completion is missing. There is no fallback.
        """
        if self._failure is not None:
            raise CompletionValidationError(self._failure)
        if self._terminal_accepted:
            return self.receipts
        if not self._channel_closed:
            self._reject("channel_not_closed")
        missing = tuple(item for item in self._expected if item not in self._receipts)
        if missing:
            self._reject(
                "missing_logical_work",
                logical_work_id=missing[0] if len(missing) == 1 else None,
                affected_count=len(missing),
            )
        self._terminal_accepted = True
        return self.receipts
