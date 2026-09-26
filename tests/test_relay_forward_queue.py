from pathlib import Path

import pytest

from agent_control_plane.authority import AuthorityValidationError
from agent_control_plane.relay_forward_queue import (
    DurableRelayForwardQueue,
    RelayQueueCapacityExceeded,
)


def queue(tmp_path):
    return DurableRelayForwardQueue(tmp_path / "relay-forward.sqlite3")


def test_forward_persists_before_send_and_removes_only_after_byte_response(tmp_path):
    q = queue(tmp_path)
    seen = []

    def exchange(payload):
        pending = q.pending()
        assert len(pending) == 1
        assert pending[0].payload == payload
        assert pending[0].attempt_count == 1
        seen.append(payload)
        return b"ack"

    response = q.forward(
        relay_id="relay-a",
        downstream_id="relay-b",
        payload=b"signed-chain",
        exchange=exchange,
    )
    assert response == b"ack"
    assert seen == [b"signed-chain"]
    assert q.pending() == ()


def test_failed_forward_remains_pending_with_attempt_count(tmp_path):
    q = queue(tmp_path)

    def exchange(payload):
        raise RuntimeError("downstream unavailable")

    with pytest.raises(RuntimeError, match="downstream unavailable"):
        q.forward(
            relay_id="relay-a",
            downstream_id="relay-b",
            payload=b"signed-chain",
            exchange=exchange,
        )

    pending = q.pending()
    assert len(pending) == 1
    assert pending[0].attempt_count == 1


def test_pending_survives_queue_reopen_and_can_be_drained(tmp_path):
    path = tmp_path / "relay-forward.sqlite3"
    first = DurableRelayForwardQueue(path)

    with pytest.raises(RuntimeError):
        first.forward(
            relay_id="relay-b",
            downstream_id="relay-c",
            payload=b"payload-2",
            exchange=lambda payload: (_ for _ in ()).throw(RuntimeError("offline")),
        )

    reopened = DurableRelayForwardQueue(path)
    assert len(reopened.pending()) == 1

    completed = reopened.drain(
        exchange_for=lambda downstream_id: (
            lambda payload: b"recovered-ack"
        )
    )
    assert len(completed) == 1
    assert reopened.pending() == ()


def test_same_payload_enqueue_is_idempotent_but_item_id_conflict_fails(tmp_path):
    q = queue(tmp_path)
    first = q.enqueue(
        relay_id="relay-a",
        downstream_id="relay-b",
        payload=b"same",
        item_id="item-1",
        enqueued_at="2026-09-25T21:00:00Z",
    )
    second = q.enqueue(
        relay_id="relay-a",
        downstream_id="relay-b",
        payload=b"same",
        item_id="item-1",
        enqueued_at="2026-09-25T21:01:00Z",
    )
    assert first == second

    with pytest.raises(
        AuthorityValidationError,
        match="item_id conflict",
    ):
        q.enqueue(
            relay_id="relay-a",
            downstream_id="relay-c",
            payload=b"different",
            item_id="item-1",
        )


def test_non_byte_downstream_response_remains_pending(tmp_path):
    q = queue(tmp_path)
    with pytest.raises(
        AuthorityValidationError,
        match="must return bytes",
    ):
        q.forward(
            relay_id="relay-a",
            downstream_id="relay-b",
            payload=b"signed-chain",
            exchange=lambda payload: "bad-response",
        )
    assert len(q.pending()) == 1


def test_manifest_exposes_hashes_not_payload_bytes(tmp_path):
    q = queue(tmp_path)
    q.enqueue(
        relay_id="relay-a",
        downstream_id="relay-b",
        payload=b"secret-ish-payload",
        item_id="item-1",
        enqueued_at="2026-09-25T21:00:00Z",
    )
    manifest = q.manifest()
    assert manifest["pending_count"] == 1
    assert "secret-ish-payload" not in str(manifest)



def test_pending_item_capacity_fails_closed(tmp_path):
    q = DurableRelayForwardQueue(
        tmp_path / "queue.sqlite3",
        max_pending_items=1,
    )
    q.enqueue(
        relay_id="relay-a",
        downstream_id="relay-b",
        payload=b"one",
        item_id="item-1",
    )
    with pytest.raises(
        RelayQueueCapacityExceeded,
        match="pending-item capacity",
    ):
        q.enqueue(
            relay_id="relay-a",
            downstream_id="relay-b",
            payload=b"two",
            item_id="item-2",
        )


def test_pending_byte_capacity_fails_closed(tmp_path):
    q = DurableRelayForwardQueue(
        tmp_path / "queue.sqlite3",
        max_pending_bytes=5,
    )
    q.enqueue(
        relay_id="relay-a",
        downstream_id="relay-b",
        payload=b"123",
        item_id="item-1",
    )
    with pytest.raises(
        RelayQueueCapacityExceeded,
        match="pending-byte capacity",
    ):
        q.enqueue(
            relay_id="relay-a",
            downstream_id="relay-b",
            payload=b"456",
            item_id="item-2",
        )


def test_idempotent_existing_item_is_allowed_at_capacity(tmp_path):
    q = DurableRelayForwardQueue(
        tmp_path / "queue.sqlite3",
        max_pending_items=1,
        max_pending_bytes=3,
    )
    first = q.enqueue(
        relay_id="relay-a",
        downstream_id="relay-b",
        payload=b"abc",
        item_id="item-1",
    )
    second = q.enqueue(
        relay_id="relay-a",
        downstream_id="relay-b",
        payload=b"abc",
        item_id="item-1",
    )
    assert first == second
    assert q.usage()["pending_items"] == 1
    assert q.usage()["pending_bytes"] == 3


def test_acknowledgement_releases_capacity(tmp_path):
    q = DurableRelayForwardQueue(
        tmp_path / "queue.sqlite3",
        max_pending_items=1,
    )
    q.enqueue(
        relay_id="relay-a",
        downstream_id="relay-b",
        payload=b"one",
        item_id="item-1",
    )
    q.acknowledge("item-1")
    q.enqueue(
        relay_id="relay-a",
        downstream_id="relay-b",
        payload=b"two",
        item_id="item-2",
    )
    assert tuple(item.item_id for item in q.pending()) == ("item-2",)


def test_usage_and_manifest_report_capacity_without_payload(tmp_path):
    q = DurableRelayForwardQueue(
        tmp_path / "queue.sqlite3",
        max_pending_items=3,
        max_pending_bytes=100,
    )
    q.enqueue(
        relay_id="relay-a",
        downstream_id="relay-b",
        payload=b"abcde",
        item_id="item-1",
    )
    usage = q.usage()
    assert usage == {
        "pending_items": 1,
        "pending_bytes": 5,
        "max_pending_items": 3,
        "max_pending_bytes": 100,
    }
    manifest = q.manifest()
    assert manifest["pending_bytes"] == 5
    assert manifest["max_pending_items"] == 3
    assert manifest["max_pending_bytes"] == 100
    assert "abcde" not in str(manifest)


def test_capacity_configuration_validation(tmp_path):
    with pytest.raises(AuthorityValidationError):
        DurableRelayForwardQueue(
            tmp_path / "queue.sqlite3",
            max_pending_items=0,
        )
    with pytest.raises(AuthorityValidationError):
        DurableRelayForwardQueue(
            tmp_path / "queue.sqlite3",
            max_pending_bytes=0,
        )
