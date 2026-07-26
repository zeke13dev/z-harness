"""Behavioral tests for exactly-once controlled completion receipts."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, asdict
import re

import pytest

from runtime.orchestration_completion_receipts import (
    CompletionReceipt,
    CompletionReceiptValidator,
    CompletionValidationError,
    build_controlled_channel_close,
    build_controlled_marker,
)


_NONCE = "trial-nonce-001"
_CHANNEL = "host-result-channel-001"
_EXPECTED = ("plan", "implement", "review")
_CAPABILITY = bytes.fromhex("42" * 32)
_ATTACKER_CAPABILITY = bytes.fromhex("17" * 32)


def _validator(
    *,
    nonce: str = _NONCE,
    expected: tuple[str, ...] = _EXPECTED,
) -> CompletionReceiptValidator:
    return CompletionReceiptValidator(
        nonce=nonce,
        channel_id=_CHANNEL,
        expected_logical_work_ids=expected,
        host_capability=_CAPABILITY,
    )


def _marker(
    logical_work_id: str,
    event_id: str,
    *,
    nonce: str = _NONCE,
    capability: bytes = _CAPABILITY,
) -> dict[str, object]:
    return build_controlled_marker(
        nonce=nonce,
        channel_id=_CHANNEL,
        logical_work_id=logical_work_id,
        event_id=event_id,
        host_capability=capability,
    )


def _channel_close(
    marker_count: int,
    *,
    nonce: str = _NONCE,
    capability: bytes = _CAPABILITY,
) -> dict[str, object]:
    return build_controlled_channel_close(
        nonce=nonce,
        channel_id=_CHANNEL,
        marker_count=marker_count,
        host_capability=capability,
    )


def _complete_single_trial(nonce: str) -> CompletionReceipt:
    validator = _validator(nonce=nonce, expected=("same-logical-work",))
    receipt = validator.record_controlled_marker(
        _marker("same-logical-work", "same-event", nonce=nonce)
    )
    validator.close_controlled_channel(_channel_close(1, nonce=nonce))
    assert validator.finalize() == (receipt,)
    return receipt


def test_terminal_acceptance_requires_receipts_and_authenticated_channel_close() -> None:
    """Criterion #11: drained-channel receipts, not prose, gate acceptance."""
    validator = _validator()
    for index, logical_work_id in enumerate(reversed(_EXPECTED)):
        validator.record_controlled_marker(_marker(logical_work_id, f"event-{index}"))
    validator.close_controlled_channel(_channel_close(len(_EXPECTED)))

    receipts = validator.finalize()

    assert receipts == validator.receipts
    assert len(receipts) == len(_EXPECTED)
    assert len({receipt.receipt_id for receipt in receipts}) == len(_EXPECTED)
    assert [receipt.logical_work_pseudonym for receipt in receipts] != [
        receipt.logical_work_pseudonym for receipt in reversed(receipts)
    ]
    assert validator.finalize() is not receipts
    assert validator.finalize() == receipts


def test_finalize_before_authenticated_close_poison_rejects_terminal_acceptance() -> None:
    """Criterion #11: receipt count alone cannot bypass the host close transition."""
    validator = _validator()
    for index, logical_work_id in enumerate(_EXPECTED):
        validator.record_controlled_marker(_marker(logical_work_id, f"event-{index}"))

    with pytest.raises(CompletionValidationError) as caught:
        validator.finalize()

    assert caught.value.artifact.code == "channel_not_closed"
    with pytest.raises(CompletionValidationError) as close_after_failure:
        validator.close_controlled_channel(_channel_close(len(_EXPECTED)))
    assert close_after_failure.value.artifact == caught.value.artifact


def test_reordered_close_and_late_marker_fail_closed() -> None:
    """Criterion #11: close must follow a full drain and no marker may follow it."""
    early = _validator()
    early.record_controlled_marker(_marker("plan", "event-1"))
    with pytest.raises(CompletionValidationError) as reordered:
        early.close_controlled_channel(_channel_close(1))
    assert reordered.value.artifact.code == "missing_logical_work"
    assert reordered.value.artifact.affected_count == 2
    with pytest.raises(CompletionValidationError) as poisoned:
        early.record_controlled_marker(_marker("implement", "event-2"))
    assert poisoned.value.artifact == reordered.value.artifact

    late = _validator(expected=("plan",))
    late.record_controlled_marker(_marker("plan", "event-1"))
    late.close_controlled_channel(_channel_close(1))
    with pytest.raises(CompletionValidationError) as after_close:
        late.record_controlled_marker(_marker("plan", "event-late"))
    assert after_close.value.artifact.code == "marker_after_channel_close"
    with pytest.raises(CompletionValidationError) as terminal:
        late.finalize()
    assert terminal.value.artifact == after_close.value.artifact


def test_authenticated_close_count_must_match_drained_receipts() -> None:
    """Criterion #11: a signed close cannot misstate how many markers drained."""
    validator = _validator(expected=("plan",))
    validator.record_controlled_marker(_marker("plan", "event-1"))

    with pytest.raises(CompletionValidationError) as caught:
        validator.close_controlled_channel(_channel_close(0))

    assert caught.value.artifact.code == "channel_marker_count_mismatch"
    assert caught.value.artifact.affected_count == 1
    with pytest.raises(CompletionValidationError) as terminal:
        validator.finalize()
    assert terminal.value.artifact == caught.value.artifact


@pytest.mark.parametrize(
    ("changed_field", "replacement", "code"),
    [
        ("nonce", "another-trial", "nonce_mismatch"),
        ("channel_id", "model-output", "channel_mismatch"),
        ("logical_work_id", "unexpected", "unexpected_logical_work"),
    ],
)
def test_marker_is_bound_to_nonce_channel_and_logical_work(
    changed_field: str, replacement: str, code: str
) -> None:
    """Criterion #11: a marker cannot move between trials, channels, or work."""
    marker = _marker("plan", "event-1")
    marker[changed_field] = replacement
    validator = _validator()

    with pytest.raises(CompletionValidationError) as caught:
        validator.record_controlled_marker(marker)

    assert caught.value.artifact.code == code
    with pytest.raises(CompletionValidationError) as terminal:
        validator.finalize()
    assert terminal.value.artifact == caught.value.artifact


def test_binding_rejects_field_substitution_even_for_expected_work() -> None:
    """Criterion #11: authenticated envelope fields cannot be substituted."""
    marker = _marker("plan", "event-1")
    marker["logical_work_id"] = "review"

    with pytest.raises(CompletionValidationError) as caught:
        _validator().record_controlled_marker(marker)

    assert caught.value.artifact.code == "malformed_binding"


def test_well_formed_marker_and_close_forged_without_host_capability_are_rejected() -> None:
    """Criterion #11: public channel data is not marker or close authority."""
    marker_validator = _validator()
    forged_marker = _marker("plan", "event-1", capability=_ATTACKER_CAPABILITY)
    assert re.fullmatch(r"[0-9a-f]{64}", str(forged_marker["binding"]))

    with pytest.raises(CompletionValidationError) as marker_failure:
        marker_validator.record_controlled_marker(forged_marker)
    assert marker_failure.value.artifact.code == "malformed_binding"

    close_validator = _validator(expected=("plan",))
    close_validator.record_controlled_marker(_marker("plan", "event-1"))
    forged_close = _channel_close(1, capability=_ATTACKER_CAPABILITY)
    assert re.fullmatch(r"[0-9a-f]{64}", str(forged_close["binding"]))
    with pytest.raises(CompletionValidationError) as close_failure:
        close_validator.close_controlled_channel(forged_close)
    assert close_failure.value.artifact.code == "malformed_channel_close_binding"


def test_replay_and_distinct_duplicate_logical_completion_fail_closed() -> None:
    """Criterion #11: event replay and duplicate logical work are distinct failures."""
    replay_validator = _validator()
    marker = _marker("plan", "event-1")
    replay_validator.record_controlled_marker(marker)
    with pytest.raises(CompletionValidationError) as replayed:
        replay_validator.record_controlled_marker(marker)
    assert replayed.value.artifact.code == "replayed_marker"

    cross_work_replay = _validator()
    cross_work_replay.record_controlled_marker(_marker("plan", "shared-event"))
    with pytest.raises(CompletionValidationError) as replayed_across_work:
        cross_work_replay.record_controlled_marker(_marker("implement", "shared-event"))
    assert replayed_across_work.value.artifact.code == "replayed_marker"

    duplicate_validator = _validator()
    duplicate_validator.record_controlled_marker(_marker("plan", "event-1"))
    with pytest.raises(CompletionValidationError) as duplicate:
        duplicate_validator.record_controlled_marker(_marker("plan", "event-2"))
    assert duplicate.value.artifact.code == "duplicate_logical_work"


@pytest.mark.parametrize(
    "marker",
    [
        {},
        {"schema_version": 1},
        {**_marker("plan", "event-1"), "content": "model says done"},
        {**_marker("plan", "event-1"), "schema_version": True},
        {**_marker("plan", "event-1"), "binding": "0" * 63},
    ],
)
def test_malformed_markers_poison_before_terminal_acceptance(
    marker: dict[str, object],
) -> None:
    """Criterion #11: the marker envelope is closed and malformed input poisons."""
    validator = _validator()
    with pytest.raises(CompletionValidationError) as caught:
        validator.record_controlled_marker(marker)
    assert caught.value.artifact.code == "malformed_marker"
    with pytest.raises(CompletionValidationError) as terminal:
        validator.finalize()
    assert terminal.value.artifact == caught.value.artifact


@pytest.mark.parametrize("binding", ["é" * 64, "\ud800" * 64])
def test_unicode_or_surrogate_binding_rejects_and_remains_poisoned(binding: str) -> None:
    """Criterion #11: hostile non-ASCII bindings never escape as raw errors."""
    validator = _validator()
    marker = _marker("plan", "event-1")
    marker["binding"] = binding

    with pytest.raises(CompletionValidationError) as caught:
        validator.record_controlled_marker(marker)
    assert caught.value.artifact.code == "malformed_marker"
    with pytest.raises(CompletionValidationError) as repeated:
        validator.record_controlled_marker(_marker("plan", "event-2"))
    assert repeated.value.artifact == caught.value.artifact


def test_missing_completion_produces_deterministic_content_free_failure() -> None:
    """Criterion #11: authenticated close exposes stable evidence for missing work."""
    first = _validator()
    second = _validator()
    for validator in (first, second):
        validator.record_controlled_marker(_marker("plan", "event-1"))

    with pytest.raises(CompletionValidationError) as left:
        first.close_controlled_channel(_channel_close(1))
    with pytest.raises(CompletionValidationError) as right:
        second.close_controlled_channel(_channel_close(1))

    artifact = left.value.artifact
    assert artifact == right.value.artifact
    assert asdict(artifact) == {
        "schema_version": 1,
        "status": "rejected",
        "code": "missing_logical_work",
        "trial_pseudonym": artifact.trial_pseudonym,
        "logical_work_pseudonym": None,
        "affected_count": 2,
    }
    assert re.fullmatch(r"[0-9a-f]{64}", artifact.trial_pseudonym)
    with pytest.raises(FrozenInstanceError):
        artifact.code = "accepted"  # type: ignore[misc]


def test_receipts_are_immutable_bounded_and_contain_no_source_or_capability() -> None:
    """Criterion #11: retained evidence has fixed content-free keyed fields."""
    secretish_values = {
        "nonce": "private-trial-nonce",
        "channel": "private-controlled-channel",
        "logical": "private-logical-work",
        "event": "private-terminal-event",
    }
    validator = CompletionReceiptValidator(
        nonce=secretish_values["nonce"],
        channel_id=secretish_values["channel"],
        expected_logical_work_ids=(secretish_values["logical"],),
        host_capability=_CAPABILITY,
    )
    receipt = validator.record_controlled_marker(
        build_controlled_marker(
            nonce=secretish_values["nonce"],
            channel_id=secretish_values["channel"],
            logical_work_id=secretish_values["logical"],
            event_id=secretish_values["event"],
            host_capability=_CAPABILITY,
        )
    )
    validator.close_controlled_channel(
        build_controlled_channel_close(
            nonce=secretish_values["nonce"],
            channel_id=secretish_values["channel"],
            marker_count=1,
            host_capability=_CAPABILITY,
        )
    )
    validator.finalize()

    document = asdict(receipt)
    assert set(document) == {
        "schema_version",
        "receipt_id",
        "trial_pseudonym",
        "channel_pseudonym",
        "logical_work_pseudonym",
        "event_pseudonym",
        "marker_authenticator_sha256",
    }
    assert all(
        re.fullmatch(r"[0-9a-f]{64}", value)
        for key, value in document.items()
        if key != "schema_version"
    )
    serialized = repr(document)
    assert all(value not in serialized for value in secretish_values.values())
    assert _CAPABILITY.hex() not in serialized
    with pytest.raises(FrozenInstanceError):
        receipt.receipt_id = "0" * 64  # type: ignore[misc]


def test_equal_identifiers_are_unlinkable_across_trial_nonces() -> None:
    """Criterion #11: keyed pseudonyms are scoped to one nonce."""
    first = asdict(_complete_single_trial("trial-a"))
    second = asdict(_complete_single_trial("trial-b"))

    for field in (
        "receipt_id",
        "trial_pseudonym",
        "channel_pseudonym",
        "logical_work_pseudonym",
        "event_pseudonym",
        "marker_authenticator_sha256",
    ):
        assert first[field] != second[field]


def test_model_authored_claims_cannot_replace_controlled_markers() -> None:
    """Criterion #11: prose and booleans never enter terminal validation."""
    validator = _validator()
    model_claim = {"logical_completions_verified": True, "result": "all work complete"}

    with pytest.raises(CompletionValidationError) as caught:
        validator.record_controlled_marker(model_claim)

    assert caught.value.artifact.code == "malformed_marker"


def test_builder_and_constructor_enforce_identity_capability_and_count_bounds() -> None:
    """Criterion #11: protocol inputs and expected identity count are bounded."""
    with pytest.raises(ValueError, match="at most 256 bytes"):
        build_controlled_marker(
            nonce="é" * 129,
            channel_id=_CHANNEL,
            logical_work_id="plan",
            event_id="event-1",
            host_capability=_CAPABILITY,
        )
    with pytest.raises(ValueError, match="UTF-8"):
        build_controlled_marker(
            nonce="\ud800",
            channel_id=_CHANNEL,
            logical_work_id="plan",
            event_id="event-1",
            host_capability=_CAPABILITY,
        )
    with pytest.raises(ValueError, match="exactly 32 bytes"):
        CompletionReceiptValidator(
            nonce=_NONCE,
            channel_id=_CHANNEL,
            expected_logical_work_ids=("plan",),
            host_capability=b"public",
        )
    with pytest.raises(ValueError, match="unique"):
        CompletionReceiptValidator(
            nonce=_NONCE,
            channel_id=_CHANNEL,
            expected_logical_work_ids=("plan", "plan"),
            host_capability=_CAPABILITY,
        )
    with pytest.raises(ValueError, match="at most 1024"):
        CompletionReceiptValidator(
            nonce=_NONCE,
            channel_id=_CHANNEL,
            expected_logical_work_ids=tuple(f"work-{index}" for index in range(1025)),
            host_capability=_CAPABILITY,
        )
