import pytest

from agent_control_plane.authority import AuthorityValidationError
from agent_control_plane.authority_state import AuthorityStateSnapshot, InMemoryAuthorityStateCache
from agent_control_plane.authority_sync import (
    AuthoritySyncReconciler,
    RevocationSyncMessage,
    SnapshotSyncMessage,
    SyncDisposition,
)
from agent_control_plane.revocation import InMemoryRevocationRegistry, RevocationRecord


def reconciler():
    return AuthoritySyncReconciler(
        receiver_id="node-b",
        state_cache=InMemoryAuthorityStateCache(),
        revocations=InMemoryRevocationRegistry(),
    )


def snapshot_message(message_id="m-1", sequence=1, epoch=1, sender_id="node-a", issued_at="2026-09-25T14:00:00Z"):
    return SnapshotSyncMessage(
        message_id=message_id,
        sender_id=sender_id,
        sequence=sequence,
        snapshot=AuthorityStateSnapshot("auth-1", epoch, issued_at, sender_id),
    )


def revocation_message(message_id="r-1", sequence=2, sender_id="node-a", revoked_at="2026-09-25T14:01:00Z"):
    return RevocationSyncMessage(
        message_id=message_id,
        sender_id=sender_id,
        sequence=sequence,
        revocation=RevocationRecord("auth-1", revoked_at, "operator_revoked"),
    )


def test_snapshot_message_applies_and_acknowledges_explicitly():
    sync = reconciler()
    ack = sync.apply(snapshot_message())
    assert ack.disposition is SyncDisposition.APPLIED
    assert ack.reason_code == "applied"
    assert ack.applied_sequence == 1
    assert ack.authority_id == "auth-1"
    assert sync.state_cache.get("auth-1").epoch == 1


def test_exact_duplicate_message_is_idempotent():
    sync = reconciler()
    message = snapshot_message()
    assert sync.apply(message).disposition is SyncDisposition.APPLIED
    duplicate = sync.apply(message)
    assert duplicate.disposition is SyncDisposition.DUPLICATE
    assert duplicate.reason_code == "duplicate_message"


def test_same_message_id_with_different_content_is_rejected():
    sync = reconciler()
    sync.apply(snapshot_message(message_id="same", epoch=1))
    conflict = sync.apply(snapshot_message(message_id="same", sequence=2, epoch=2))
    assert conflict.disposition is SyncDisposition.REJECTED
    assert conflict.reason_code == "message_id_conflict"


def test_sender_sequence_regression_and_replay_are_rejected():
    sync = reconciler()
    assert sync.apply(snapshot_message(message_id="m-2", sequence=2, epoch=2)).disposition is SyncDisposition.APPLIED
    replay = sync.apply(snapshot_message(message_id="m-1", sequence=1, epoch=1))
    assert replay.disposition is SyncDisposition.REJECTED
    assert replay.reason_code == "replay_or_sequence_regression"


def test_snapshot_epoch_regression_is_rejected_even_with_new_transport_sequence():
    sync = reconciler()
    sync.apply(snapshot_message(message_id="m-1", sequence=1, epoch=2))
    bad = sync.apply(snapshot_message(message_id="m-2", sequence=2, epoch=1))
    assert bad.disposition is SyncDisposition.REJECTED
    assert "epoch regression" in bad.reason_code


def test_same_epoch_conflicting_snapshot_is_rejected():
    sync = reconciler()
    sync.apply(snapshot_message(message_id="m-1", sequence=1, epoch=2, issued_at="2026-09-25T14:00:00Z"))
    conflict = sync.apply(snapshot_message(message_id="m-2", sequence=2, epoch=2, issued_at="2026-09-25T14:00:01Z"))
    assert conflict.disposition is SyncDisposition.REJECTED
    assert "conflicting authority state" in conflict.reason_code


def test_revocation_applies_after_snapshot_and_is_queryable():
    sync = reconciler()
    sync.apply(snapshot_message(sequence=1, epoch=2))
    ack = sync.apply(revocation_message(sequence=2))
    assert ack.disposition is SyncDisposition.APPLIED
    assert sync.revocations.is_revoked_at("auth-1", "2026-09-25T14:01:00Z") is True


def test_conflicting_revocation_is_rejected():
    sync = reconciler()
    sync.apply(revocation_message(message_id="r-1", sequence=1, revoked_at="2026-09-25T14:01:00Z"))
    conflict = sync.apply(
        RevocationSyncMessage(
            message_id="r-2",
            sender_id="node-a",
            sequence=2,
            revocation=RevocationRecord("auth-1", "2026-09-25T14:02:00Z", "different_reason"),
        )
    )
    assert conflict.disposition is SyncDisposition.REJECTED
    assert "different record" in conflict.reason_code


def test_sender_sequences_are_independent_per_sender():
    sync = reconciler()
    assert sync.apply(snapshot_message(message_id="a1", sequence=1, sender_id="node-a")).disposition is SyncDisposition.APPLIED
    assert sync.apply(snapshot_message(message_id="b1", sequence=1, sender_id="node-b", epoch=2)).disposition is SyncDisposition.APPLIED
    assert sync.manifest()["sender_sequences"] == {"node-a": 1, "node-b": 1}


def test_invalid_sequence_and_schema_fail_during_message_construction():
    with pytest.raises(AuthorityValidationError):
        snapshot_message(sequence=-1)
    with pytest.raises(AuthorityValidationError, match="schema_version"):
        SnapshotSyncMessage(
            message_id="m-1",
            sender_id="node-a",
            sequence=1,
            snapshot=AuthorityStateSnapshot("auth-1", 1, "2026-09-25T14:00:00Z", "node-a"),
            schema_version="wrong",
        )
