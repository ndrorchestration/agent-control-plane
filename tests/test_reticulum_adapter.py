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
from agent_control_plane.reticulum_adapter import (
    RETICULUM_SYNC_PATH,
    ReticulumAdapterError,
    ReticulumAuthoritySyncServer,
    ReticulumAuthoritySyncTransport,
)
from agent_control_plane.revocation import InMemoryRevocationRegistry
from agent_control_plane.sync_transport import AuthoritySyncEndpoint


class FakeReceipt:
    def __init__(self, response, concluded_after=1):
        self.response = response
        self.calls = 0
        self.concluded_after = concluded_after

    def concluded(self):
        self.calls += 1
        return self.calls >= self.concluded_after

    def get_response(self):
        return self.response


class FakeLink:
    def __init__(self, receipt):
        self.receipt = receipt
        self.calls = []

    def request(self, path, data=None, timeout=None, max_response_size=None):
        self.calls.append({
            "path": path,
            "data": data,
            "timeout": timeout,
            "max_response_size": max_response_size,
        })
        return self.receipt


class FakeDestination:
    def __init__(self):
        self.registration = None

    def register_request_handler(self, path, response_generator=None, allow=None, allowed_list=None, auto_compress=True):
        self.registration = {
            "path": path,
            "response_generator": response_generator,
            "allow": allow,
            "allowed_list": allowed_list,
            "auto_compress": auto_compress,
        }


def endpoint():
    return AuthoritySyncEndpoint(
        AuthoritySyncReconciler(
            receiver_id="node-b",
            state_cache=InMemoryAuthorityStateCache(),
            revocations=InMemoryRevocationRegistry(),
        )
    )


def message():
    return SnapshotSyncMessage(
        message_id="m-1",
        sender_id="node-a",
        sequence=1,
        snapshot=AuthorityStateSnapshot("auth-1", 1, "2026-09-25T14:00:00Z", "node-a"),
    )


def test_client_transport_uses_documented_link_request_surface():
    target = endpoint()
    ack_bytes = target.receive(encode_sync_message(message()))
    link = FakeLink(FakeReceipt(ack_bytes))
    transport = ReticulumAuthoritySyncTransport(
        {"node-b": link},
        sleep=lambda seconds: None,
    )
    response = transport.exchange("node-b", encode_sync_message(message()))
    ack = decode_sync_acknowledgement(response)
    assert ack.disposition is SyncDisposition.DUPLICATE
    assert link.calls == [{
        "path": RETICULUM_SYNC_PATH,
        "data": encode_sync_message(message()),
        "timeout": 15.0,
        "max_response_size": 65536,
    }]


def test_server_registers_documented_request_handler_shape_and_processes_bytes():
    destination = FakeDestination()
    target = endpoint()
    server = ReticulumAuthoritySyncServer(destination=destination, endpoint=target)
    server.install(allow="ALLOW_ALL", allowed_list=None, auto_compress=True)
    assert destination.registration["path"] == RETICULUM_SYNC_PATH
    response = destination.registration["response_generator"](
        RETICULUM_SYNC_PATH, encode_sync_message(message()), b"req", b"link", None, 0
    )
    ack = decode_sync_acknowledgement(response)
    assert ack.disposition is SyncDisposition.APPLIED


def test_client_unknown_peer_fails_closed():
    transport = ReticulumAuthoritySyncTransport({}, sleep=lambda seconds: None)
    with pytest.raises(ReticulumAdapterError, match="unknown Reticulum peer link"):
        transport.exchange("node-b", b"{}")


def test_client_unsent_request_fails_closed():
    link = FakeLink(False)
    transport = ReticulumAuthoritySyncTransport({"node-b": link}, sleep=lambda seconds: None)
    with pytest.raises(ReticulumAdapterError, match="not sent"):
        transport.exchange("node-b", b"{}")


def test_client_timeout_fails_closed():
    class NeverReceipt(FakeReceipt):
        def concluded(self):
            return False

    times = iter([0.0, 0.0, 1.0])
    transport = ReticulumAuthoritySyncTransport(
        {"node-b": FakeLink(NeverReceipt(b"ack"))},
        timeout_seconds=0.5,
        poll_interval_seconds=0.1,
        monotonic=lambda: next(times),
        sleep=lambda seconds: None,
    )
    with pytest.raises(ReticulumAdapterError, match="timed out locally"):
        transport.exchange("node-b", b"{}")


def test_client_requires_byte_response():
    transport = ReticulumAuthoritySyncTransport(
        {"node-b": FakeLink(FakeReceipt(None))}, sleep=lambda seconds: None
    )
    with pytest.raises(ReticulumAdapterError, match="without byte response"):
        transport.exchange("node-b", b"{}")


def test_server_rejects_double_install_and_wrong_path_or_payload():
    destination = FakeDestination()
    server = ReticulumAuthoritySyncServer(destination=destination, endpoint=endpoint())
    server.install(allow="ALLOW_ALL")
    with pytest.raises(ReticulumAdapterError, match="already installed"):
        server.install(allow="ALLOW_ALL")
    handler = destination.registration["response_generator"]
    with pytest.raises(ReticulumAdapterError, match="unexpected Reticulum request path"):
        handler("/wrong", b"{}", None, None, None, None)
    with pytest.raises(ReticulumAdapterError, match="payload must be bytes"):
        handler(RETICULUM_SYNC_PATH, "{}", None, None, None, None)


def test_constructor_validation_fails_closed():
    with pytest.raises(AuthorityValidationError, match="timeout_seconds"):
        ReticulumAuthoritySyncTransport({}, timeout_seconds=0)
    with pytest.raises(AuthorityValidationError, match="max_response_size"):
        ReticulumAuthoritySyncTransport({}, max_response_size=0)
