import pytest

from agent_control_plane.relay_forward_queue import DurableRelayForwardQueue
from agent_control_plane.relay_retry_policy import (
    BoundedRelayRetryPolicy,
    RelayRetryDisposition,
    RetryingRelayForwarder,
)


def test_exponential_backoff_is_bounded():
    policy = BoundedRelayRetryPolicy(
        max_attempts=5,
        base_delay_seconds=2,
        multiplier=3,
        max_delay_seconds=10,
    )
    assert policy.delay_after_attempt(1) == 2
    assert policy.delay_after_attempt(2) == 6
    assert policy.delay_after_attempt(3) == 10
    assert policy.delay_after_attempt(4) == 10


def test_retry_sweep_defers_until_due(tmp_path):
    q = DurableRelayForwardQueue(tmp_path / "queue.sqlite3")
    item = q.enqueue(
        relay_id="relay-a",
        downstream_id="relay-b",
        payload=b"payload",
        item_id="item-1",
        enqueued_at="2026-09-25T20:00:00Z",
    )
    q.mark_attempt(
        item.item_id,
        attempted_at="2026-09-25T20:00:00Z",
    )

    forwarder = RetryingRelayForwarder(
        queue=q,
        policy=BoundedRelayRetryPolicy(
            max_attempts=3,
            base_delay_seconds=10,
        ),
        exchange_for=lambda downstream_id: lambda payload: b"ack",
    )
    result = forwarder.sweep(now="2026-09-25T20:00:05Z")
    assert result[0].disposition is RelayRetryDisposition.DEFERRED
    assert result[0].next_attempt_at == "2026-09-25T20:00:10Z"
    assert q.get("item-1").attempt_count == 1


def test_due_retry_delivers_and_removes_pending_item(tmp_path):
    q = DurableRelayForwardQueue(tmp_path / "queue.sqlite3")
    item = q.enqueue(
        relay_id="relay-a",
        downstream_id="relay-b",
        payload=b"payload",
        item_id="item-1",
    )
    q.mark_attempt(
        item.item_id,
        attempted_at="2026-09-25T20:00:00Z",
    )
    seen = []

    forwarder = RetryingRelayForwarder(
        queue=q,
        policy=BoundedRelayRetryPolicy(
            max_attempts=3,
            base_delay_seconds=10,
        ),
        exchange_for=lambda downstream_id: lambda payload: (
            seen.append((downstream_id, payload)) or b"ack"
        ),
    )
    result = forwarder.sweep(now="2026-09-25T20:00:10Z")
    assert result[0].disposition is RelayRetryDisposition.DELIVERED
    assert result[0].attempt_count == 2
    assert seen == [("relay-b", b"payload")]
    assert q.pending() == ()


def test_failed_retry_advances_attempt_and_schedules_next(tmp_path):
    q = DurableRelayForwardQueue(tmp_path / "queue.sqlite3")
    q.enqueue(
        relay_id="relay-a",
        downstream_id="relay-b",
        payload=b"payload",
        item_id="item-1",
    )

    forwarder = RetryingRelayForwarder(
        queue=q,
        policy=BoundedRelayRetryPolicy(
            max_attempts=3,
            base_delay_seconds=4,
            multiplier=2,
        ),
        exchange_for=lambda downstream_id: lambda payload: (
            (_ for _ in ()).throw(RuntimeError("offline"))
        ),
    )
    result = forwarder.sweep(now="2026-09-25T20:00:00Z")
    assert result[0].disposition is RelayRetryDisposition.FAILED
    assert result[0].attempt_count == 1
    assert result[0].next_attempt_at == "2026-09-25T20:00:04Z"
    assert q.get("item-1").attempt_count == 1


def test_attempt_limit_reports_exhausted_without_extra_send(tmp_path):
    q = DurableRelayForwardQueue(tmp_path / "queue.sqlite3")
    item = q.enqueue(
        relay_id="relay-a",
        downstream_id="relay-b",
        payload=b"payload",
        item_id="item-1",
    )
    q.mark_attempt(item.item_id, attempted_at="2026-09-25T20:00:00Z")
    q.mark_attempt(item.item_id, attempted_at="2026-09-25T20:00:10Z")
    calls = []

    forwarder = RetryingRelayForwarder(
        queue=q,
        policy=BoundedRelayRetryPolicy(
            max_attempts=2,
            base_delay_seconds=1,
        ),
        exchange_for=lambda downstream_id: lambda payload: (
            calls.append(payload) or b"ack"
        ),
    )
    result = forwarder.sweep(now="2026-09-25T21:00:00Z")
    assert result[0].disposition is RelayRetryDisposition.EXHAUSTED
    assert result[0].attempt_count == 2
    assert calls == []
    assert len(q.pending()) == 1


def test_failure_on_last_allowed_attempt_becomes_exhausted(tmp_path):
    q = DurableRelayForwardQueue(tmp_path / "queue.sqlite3")
    item = q.enqueue(
        relay_id="relay-a",
        downstream_id="relay-b",
        payload=b"payload",
        item_id="item-1",
    )
    q.mark_attempt(item.item_id, attempted_at="2026-09-25T20:00:00Z")

    forwarder = RetryingRelayForwarder(
        queue=q,
        policy=BoundedRelayRetryPolicy(
            max_attempts=2,
            base_delay_seconds=1,
        ),
        exchange_for=lambda downstream_id: lambda payload: (
            (_ for _ in ()).throw(RuntimeError("still offline"))
        ),
    )
    result = forwarder.sweep(now="2026-09-25T20:00:01Z")
    assert result[0].disposition is RelayRetryDisposition.EXHAUSTED
    assert result[0].attempt_count == 2
    assert result[0].next_attempt_at is None
    assert len(q.pending()) == 1


def test_retry_policy_validation_rejects_invalid_bounds():
    with pytest.raises(Exception):
        BoundedRelayRetryPolicy(max_attempts=0)
    with pytest.raises(Exception):
        BoundedRelayRetryPolicy(base_delay_seconds=0)
    with pytest.raises(Exception):
        BoundedRelayRetryPolicy(multiplier=0.5)
