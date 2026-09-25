import pytest

from agent_control_plane.authority import AuthorityValidationError
from agent_control_plane.authority_state import AuthorityStateSnapshot, InMemoryAuthorityStateCache
from agent_control_plane.authority_sync import (
    AuthoritySyncReconciler,
    SnapshotSyncMessage,
    SyncDisposition,
    decode_sync_acknowledgement,
    encode_sync_message,
)
from agent_control_plane.revocation import InMemoryRevocationRegistry
from agent_control_plane.sync_transport import (
    AuthoritySyncEndpoint,
    LoopbackAuthoritySyncTransport,
)


def endpoint(receiver_id="node-b"):
    return AuthoritySyncEndpoint(
        AuthoritySyncReconciler(
            receiver_id=receiver_id,
            state_cache=InMemoryAuthorityStateCache(),
            revocations=InMemoryRevocationRegistry(),
        )
    )


def message(message_id="m-1", sequence=1, epoch=1):
    return SnapshotSyncMessage(
        message_id=message_id,
        sender_id="node-a",
        sequence=sequence,
        snapshot=AuthorityStateSnapshot("auth-1", epoch, "2026-09-25T14:00:00Z", "node-a"),
    )


def test_loopback_adapter_carries_canonical_message_and_ack_bytes():
    transport = LoopbackAuthoritySyncTransport()
    target = endpoint("node-b")
    transport.register("node-b", target)
    ack_bytes = transport.exchange("node-b", encode_sync_message(message()))
    ack = decode_sync_acknowledgement(ack_bytes)
    assert ack.receiver_id == "node-b"
    assert ack.disposition is SyncDisposition.APPLIED
    assert ack.authority_id == "auth-1"
    assert target.reconciler.state_cache.get("auth-1").epoch == 1


def test_duplicate_delivery_remains_reconciler_semantics_not_transport_semantics():
    transport = LoopbackAuthoritySyncTransport()
    target = endpoint()
    transport.register("node-b", target)
    payload = encode_sync_message(message())
    first = decode_sync_acknowledgement(transport.exchange("node-b", payload))
    second = decode_sync_acknowledgement(transport.exchange("node-b", payload))
    assert first.disposition is SyncDisposition.APPLIED
    assert second.disposition is SyncDisposition.DUPLICATE


def test_unknown_peer_fails_closed_before_delivery():
    transport = LoopbackAuthoritySyncTransport()
    with pytest.raises(AuthorityValidationError, match="unknown sync peer"):
        transport.exchange("missing", encode_sync_message(message()))


def test_adapter_rejects_non_bytes_payload():
    transport = LoopbackAuthoritySyncTransport()
    transport.register("node-b", endpoint())
    with pytest.raises(AuthorityValidationError, match="payload must be bytes"):
        transport.exchange("node-b", "{}")


def test_endpoint_rejects_malformed_wire_payload():
    target = endpoint()
    with pytest.raises(AuthorityValidationError, match="valid JSON"):
        target.receive(b"{not-json}")


def test_duplicate_peer_registration_fails_closed():
    transport = LoopbackAuthoritySyncTransport()
    target = endpoint()
    transport.register("node-b", target)
    with pytest.raises(AuthorityValidationError, match="already registered"):
        transport.register("node-b", target)
