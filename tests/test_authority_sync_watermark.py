import pytest

from agent_control_plane import ControlPlane, Task, TaskState
from agent_control_plane.authority import (
    AuthorityEnvelope,
    AuthorityValidationError,
    DecisionOutcome,
    DecisionRecord,
    Operation,
    PolicyIdentity,
    PrincipalIdentity,
    ResourceScope,
)
from agent_control_plane.authority_policy import AuthorityPolicy
from agent_control_plane.authority_state import AuthorityStateRequirement, AuthorityStateSnapshot
from agent_control_plane.authority_sync import RevocationSyncMessage, SnapshotSyncMessage, SyncDisposition
from agent_control_plane.authority_sync_guard import AuthoritySyncProgressGuard
from agent_control_plane.authority_sync_persistence import DurableAuthoritySyncReconciler
from agent_control_plane.authority_sync_watermark import (
    AuthoritySyncWatermark,
    AuthoritySyncWatermarkRegistry,
    decode_authority_sync_watermark,
    encode_authority_sync_watermark,
)
from agent_control_plane.revocation import RevocationRecord


def envelope():
    return AuthorityEnvelope(
        authority_id="auth-1",
        principal=PrincipalIdentity("principal-1", "agent"),
        capability="read",
        resource=ResourceScope("resource-1", "document"),
        operation=Operation("inspect"),
        policy=PolicyIdentity("policy-1", "v1"),
        decision=DecisionRecord("decision-1", DecisionOutcome.ALLOW, "test_allow"),
        expires_at="2026-09-25T16:00:00Z",
    )


def snapshot(message_id, sequence, epoch, issued_at):
    return SnapshotSyncMessage(
        message_id=message_id,
        sender_id="authority-source",
        sequence=sequence,
        snapshot=AuthorityStateSnapshot("auth-1", epoch, issued_at, "authority-source"),
    )


def revocation():
    return RevocationSyncMessage(
        message_id="rev-3",
        sender_id="authority-source",
        sequence=3,
        revocation=RevocationRecord(
            "auth-1",
            "2026-09-25T15:02:30Z",
            "operator_revoked",
        ),
    )


def dispatch(reconciler, registry):
    guard = AuthoritySyncProgressGuard(
        reconciler=reconciler,
        sender_id="authority-source",
        watermark_registry=registry,
        state_requirement=AuthorityStateRequirement(2, 300),
    )
    policy = AuthorityPolicy(
        resolver=lambda capability, task: envelope(),
        observed_at=lambda capability, task: "2026-09-25T15:03:00Z",
        state_freshness_checker=guard,
        revocation_checker=reconciler.revocations.is_revoked_at,
    )
    plane = ControlPlane(policy=policy, run_id="watermark-reconnect")
    plane.register("read", lambda task: "should-not-run")
    task = plane.dispatch("read", Task(payload={}))
    return task


def test_watermark_wire_round_trip_is_canonical():
    record = AuthoritySyncWatermark(
        "wm-1", "peer-a", "authority-source", 3, "2026-09-25T15:02:00Z"
    )
    encoded = encode_authority_sync_watermark(record)
    assert decode_authority_sync_watermark(encoded) == record
    assert encode_authority_sync_watermark(decode_authority_sync_watermark(encoded)) == encoded


def test_untrusted_issuer_and_regression_fail_closed():
    registry = AuthoritySyncWatermarkRegistry({"authority-source": {"peer-a"}})
    with pytest.raises(AuthorityValidationError, match="untrusted"):
        registry.apply(
            AuthoritySyncWatermark(
                "wm-x", "peer-b", "authority-source", 4, "2026-09-25T15:01:00Z"
            )
        )

    registry.apply(
        AuthoritySyncWatermark(
            "wm-1", "peer-a", "authority-source", 3, "2026-09-25T15:01:00Z"
        )
    )
    with pytest.raises(AuthorityValidationError, match="regression"):
        registry.apply(
            AuthoritySyncWatermark(
                "wm-2", "peer-a", "authority-source", 2, "2026-09-25T15:02:00Z"
            )
        )


def test_multiple_trusted_issuers_take_maximum_required_floor():
    registry = AuthoritySyncWatermarkRegistry(
        {"authority-source": {"peer-a", "peer-b"}}
    )
    registry.apply(
        AuthoritySyncWatermark(
            "wm-a", "peer-a", "authority-source", 2, "2026-09-25T15:01:00Z"
        )
    )
    registry.apply(
        AuthoritySyncWatermark(
            "wm-b", "peer-b", "authority-source", 4, "2026-09-25T15:01:30Z"
        )
    )
    assert registry.required_sequence("authority-source") == 4


def test_reconnecting_node_uses_peer_watermark_then_delayed_revocation_denies(tmp_path):
    reconciler = DurableAuthoritySyncReconciler(
        receiver_id="node-b",
        database_path=tmp_path / "sync.sqlite3",
    )
    registry = AuthoritySyncWatermarkRegistry(
        {"authority-source": {"peer-a"}}
    )
    registry.apply(
        AuthoritySyncWatermark(
            "wm-3", "peer-a", "authority-source", 3, "2026-09-25T15:02:45Z"
        )
    )

    reconciler.apply(snapshot("s1", 1, 1, "2026-09-25T15:00:00Z"))
    assert dispatch(reconciler, registry).error == "authority state stale:sync_sequence"

    reconciler.apply(snapshot("s2", 2, 2, "2026-09-25T15:02:00Z"))
    assert dispatch(reconciler, registry).error == "authority state stale:sync_sequence"

    assert reconciler.apply(revocation()).disposition is SyncDisposition.APPLIED
    task = dispatch(reconciler, registry)
    assert task.state is TaskState.CREATED
    assert task.error == "authority revoked"


def test_missing_dynamic_watermark_fails_closed(tmp_path):
    reconciler = DurableAuthoritySyncReconciler(
        receiver_id="node-b",
        database_path=tmp_path / "sync.sqlite3",
    )
    registry = AuthoritySyncWatermarkRegistry(
        {"authority-source": {"peer-a"}}
    )
    guard = AuthoritySyncProgressGuard(
        reconciler=reconciler,
        sender_id="authority-source",
        watermark_registry=registry,
    )
    assert guard(envelope(), "2026-09-25T15:03:00Z") == "sync_watermark_missing"
