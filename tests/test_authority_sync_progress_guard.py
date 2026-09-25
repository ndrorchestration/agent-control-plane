from agent_control_plane import ControlPlane, Task, TaskState
from agent_control_plane.authority import (
    AuthorityEnvelope,
    DecisionOutcome,
    DecisionRecord,
    Operation,
    PolicyIdentity,
    PrincipalIdentity,
    ResourceScope,
)
from agent_control_plane.authority_policy import AuthorityPolicy
from agent_control_plane.authority_state import (
    AuthorityStateRequirement,
    AuthorityStateSnapshot,
)
from agent_control_plane.authority_sync import (
    RevocationSyncMessage,
    SnapshotSyncMessage,
    SyncDisposition,
)
from agent_control_plane.authority_sync_guard import AuthoritySyncProgressGuard
from agent_control_plane.authority_sync_persistence import DurableAuthoritySyncReconciler
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
        snapshot=AuthorityStateSnapshot(
            "auth-1",
            epoch,
            issued_at,
            "authority-source",
        ),
    )


def revocation(message_id="rev-1", sequence=3):
    return RevocationSyncMessage(
        message_id=message_id,
        sender_id="authority-source",
        sequence=sequence,
        revocation=RevocationRecord(
            "auth-1",
            "2026-09-25T15:02:30Z",
            "operator_revoked",
        ),
    )


def dispatch(reconciler, *, min_sequence=3):
    guard = AuthoritySyncProgressGuard(
        reconciler=reconciler,
        sender_id="authority-source",
        min_sequence=min_sequence,
        state_requirement=AuthorityStateRequirement(
            min_epoch=2,
            max_age_seconds=300,
        ),
    )
    policy = AuthorityPolicy(
        resolver=lambda capability, task: envelope(),
        observed_at=lambda capability, task: "2026-09-25T15:03:00Z",
        state_freshness_checker=guard,
        revocation_checker=reconciler.revocations.is_revoked_at,
    )
    plane = ControlPlane(policy=policy, run_id="partition-recovery")
    plane.register("read", lambda task: "should-not-run")
    task = plane.dispatch("read", Task(payload={"resource_id": "resource-1"}))
    return plane, task


def test_reconnect_stays_fail_closed_until_required_sync_sequence_then_revocation_denies(tmp_path):
    database = tmp_path / "authority-sync.sqlite3"
    reconciler = DurableAuthoritySyncReconciler(
        receiver_id="isolated-node",
        database_path=database,
    )

    assert reconciler.apply(
        snapshot("snapshot-1", 1, 1, "2026-09-25T15:00:00Z")
    ).disposition is SyncDisposition.APPLIED

    _, isolated = dispatch(reconciler)
    assert isolated.state is TaskState.CREATED
    assert isolated.error == "authority state stale:sync_sequence"

    assert reconciler.apply(
        snapshot("snapshot-2", 2, 2, "2026-09-25T15:02:00Z")
    ).disposition is SyncDisposition.APPLIED

    _, partially_reconciled = dispatch(reconciler)
    assert partially_reconciled.state is TaskState.CREATED
    assert partially_reconciled.error == "authority state stale:sync_sequence"

    assert reconciler.apply(revocation()).disposition is SyncDisposition.APPLIED

    plane, fully_reconciled = dispatch(reconciler)
    assert fully_reconciled.state is TaskState.CREATED
    assert fully_reconciled.error == "authority revoked"
    assert plane.events[-1].event == "task.denied"


def test_restart_preserves_sync_floor_and_revocation_fail_closure(tmp_path):
    database = tmp_path / "authority-sync.sqlite3"
    first = DurableAuthoritySyncReconciler(
        receiver_id="isolated-node",
        database_path=database,
    )
    first.apply(snapshot("snapshot-1", 1, 1, "2026-09-25T15:00:00Z"))
    first.apply(snapshot("snapshot-2", 2, 2, "2026-09-25T15:02:00Z"))
    first.apply(revocation())

    recovered = DurableAuthoritySyncReconciler(
        receiver_id="isolated-node",
        database_path=database,
    )
    assert recovered.manifest()["sender_sequences"] == {"authority-source": 3}

    _, task = dispatch(recovered)
    assert task.state is TaskState.CREATED
    assert task.error == "authority revoked"

    regressed = recovered.apply(
        snapshot("snapshot-regressed", 2, 3, "2026-09-25T15:03:00Z")
    )
    assert regressed.disposition is SyncDisposition.REJECTED
    assert regressed.reason_code == "replay_or_sequence_regression"
    assert recovered.manifest()["sender_sequences"] == {"authority-source": 3}


def test_sync_floor_can_gate_without_authority_state_requirement(tmp_path):
    reconciler = DurableAuthoritySyncReconciler(
        receiver_id="node",
        database_path=tmp_path / "authority-sync.sqlite3",
    )
    guard = AuthoritySyncProgressGuard(
        reconciler=reconciler,
        sender_id="authority-source",
        min_sequence=1,
    )

    assert guard(envelope(), "2026-09-25T15:03:00Z") == "sync_sequence"
    reconciler.apply(snapshot("snapshot-1", 1, 1, "2026-09-25T15:00:00Z"))
    assert guard(envelope(), "2026-09-25T15:03:00Z") is None
