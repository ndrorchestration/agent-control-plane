from agent_control_plane.authority_state import (
    AuthorityStateSnapshot,
    InMemoryAuthorityStateCache,
)
from agent_control_plane.authority_sync import (
    AuthoritySyncReconciler,
    SnapshotSyncMessage,
    SyncDisposition,
)
from agent_control_plane.authority_sync_watermark import (
    AuthoritySyncWatermarkRegistry,
    WatermarkDisposition,
)
from agent_control_plane.revocation import InMemoryRevocationRegistry
from agent_control_plane.watermark_convergence import (
    AuthoritySyncWatermarkPublisher,
    DirectWatermarkPeer,
    converge_direct_watermarks,
)


def reconciler(node_id):
    return AuthoritySyncReconciler(
        receiver_id=node_id,
        state_cache=InMemoryAuthorityStateCache(),
        revocations=InMemoryRevocationRegistry(),
    )


def snapshot(sequence, epoch=None):
    return SnapshotSyncMessage(
        message_id=f"m-{sequence}",
        sender_id="authority-source",
        sequence=sequence,
        snapshot=AuthorityStateSnapshot(
            "auth-1",
            sequence if epoch is None else epoch,
            f"2026-09-25T15:0{sequence}:00Z",
            "authority-source",
        ),
    )


def peer(node_id, reconciler_instance, trusted):
    return DirectWatermarkPeer(
        node_id=node_id,
        publisher=AuthoritySyncWatermarkPublisher(
            node_id=node_id,
            reconciler=reconciler_instance,
        ),
        registry=AuthoritySyncWatermarkRegistry(
            {"authority-source": set(trusted)}
        ),
    )


def test_partitioned_peers_converge_to_highest_direct_observation_after_reconnect():
    a = reconciler("peer-a")
    b = reconciler("peer-b")
    c = reconciler("peer-c")

    for message in (snapshot(1), snapshot(2), snapshot(3)):
        assert a.apply(message).disposition is SyncDisposition.APPLIED
    for message in (snapshot(1), snapshot(2)):
        assert b.apply(message).disposition is SyncDisposition.APPLIED
    assert c.apply(snapshot(1)).disposition is SyncDisposition.APPLIED

    peers = {
        "peer-a": peer("peer-a", a, {"peer-a", "peer-b", "peer-c"}),
        "peer-b": peer("peer-b", b, {"peer-a", "peer-b", "peer-c"}),
        "peer-c": peer("peer-c", c, {"peer-a", "peer-b", "peer-c"}),
    }

    partition_results = converge_direct_watermarks(
        peers,
        target_sender_id="authority-source",
        issued_at="2026-09-25T15:10:00Z",
        links=(("peer-b", "peer-c"), ("peer-c", "peer-b")),
    )
    assert partition_results == {
        ("peer-b", "peer-c"): WatermarkDisposition.APPLIED,
        ("peer-c", "peer-b"): WatermarkDisposition.APPLIED,
    }
    assert peers["peer-b"].registry.required_sequence("authority-source") == 1
    assert peers["peer-c"].registry.required_sequence("authority-source") == 2

    reconnect_results = converge_direct_watermarks(
        peers,
        target_sender_id="authority-source",
        issued_at="2026-09-25T15:11:00Z",
        links=(
            ("peer-a", "peer-b"),
            ("peer-a", "peer-c"),
            ("peer-b", "peer-a"),
            ("peer-c", "peer-a"),
        ),
    )
    assert reconnect_results[("peer-a", "peer-b")] is WatermarkDisposition.APPLIED
    assert reconnect_results[("peer-a", "peer-c")] is WatermarkDisposition.APPLIED

    assert peers["peer-a"].registry.required_sequence("authority-source") == 2
    assert peers["peer-b"].registry.required_sequence("authority-source") == 3
    assert peers["peer-c"].registry.required_sequence("authority-source") == 3


def test_publisher_cannot_claim_beyond_locally_reconciled_sequence():
    a = reconciler("peer-a")
    a.apply(snapshot(1))
    a.apply(snapshot(2))
    publisher = AuthoritySyncWatermarkPublisher(node_id="peer-a", reconciler=a)

    watermark = publisher.issue(
        target_sender_id="authority-source",
        issued_at="2026-09-25T15:10:00Z",
    )
    assert watermark is not None
    assert watermark.min_sequence == 2
    assert watermark.watermark_id == "peer-a:authority-source:2"


def test_peer_with_no_local_progress_emits_no_watermark():
    empty = reconciler("peer-empty")
    publisher = AuthoritySyncWatermarkPublisher(
        node_id="peer-empty",
        reconciler=empty,
    )
    assert publisher.issue(
        target_sender_id="authority-source",
        issued_at="2026-09-25T15:10:00Z",
    ) is None


def test_repeated_same_observation_is_idempotent_at_destination():
    a = reconciler("peer-a")
    b = reconciler("peer-b")
    a.apply(snapshot(1))

    peers = {
        "peer-a": peer("peer-a", a, {"peer-a"}),
        "peer-b": peer("peer-b", b, {"peer-a"}),
    }

    first = converge_direct_watermarks(
        peers,
        target_sender_id="authority-source",
        issued_at="2026-09-25T15:10:00Z",
        links=(("peer-a", "peer-b"),),
    )
    second = converge_direct_watermarks(
        peers,
        target_sender_id="authority-source",
        issued_at="2026-09-25T15:10:00Z",
        links=(("peer-a", "peer-b"),),
    )

    assert first[("peer-a", "peer-b")] is WatermarkDisposition.APPLIED
    assert second[("peer-a", "peer-b")] is WatermarkDisposition.DUPLICATE


def test_direct_convergence_does_not_forward_third_party_claims():
    a = reconciler("peer-a")
    b = reconciler("peer-b")
    c = reconciler("peer-c")
    a.apply(snapshot(3))
    b.apply(snapshot(1))
    c.apply(snapshot(1))

    peers = {
        "peer-a": peer("peer-a", a, {"peer-a", "peer-b", "peer-c"}),
        "peer-b": peer("peer-b", b, {"peer-a", "peer-b", "peer-c"}),
        "peer-c": peer("peer-c", c, {"peer-a", "peer-b", "peer-c"}),
    }

    converge_direct_watermarks(
        peers,
        target_sender_id="authority-source",
        issued_at="2026-09-25T15:10:00Z",
        links=(("peer-a", "peer-b"),),
    )
    assert peers["peer-b"].registry.required_sequence("authority-source") == 3

    converge_direct_watermarks(
        peers,
        target_sender_id="authority-source",
        issued_at="2026-09-25T15:11:00Z",
        links=(("peer-b", "peer-c"),),
    )

    # peer-b may only issue what peer-b itself reconciled (sequence 1).
    # It cannot re-originate peer-a's sequence-3 claim as if locally observed.
    assert peers["peer-c"].registry.required_sequence("authority-source") == 1
