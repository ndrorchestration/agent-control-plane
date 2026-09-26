from agent_control_plane.relay_dead_letter import DurableRelayDeadLetterStore
from agent_control_plane.relay_forward_queue import DurableRelayForwardQueue
from agent_control_plane.relay_retry_policy import BoundedRelayRetryPolicy
from agent_control_plane.relay_supervisor import (
    RelaySupervisorCycle,
    RelaySupervisorHealth,
)


def supervisor(tmp_path, *, exchange):
    queue = DurableRelayForwardQueue(tmp_path / "pending.sqlite3")
    dead = DurableRelayDeadLetterStore(tmp_path / "dead.sqlite3")
    policy = BoundedRelayRetryPolicy(
        max_attempts=2,
        base_delay_seconds=1,
    )
    cycle = RelaySupervisorCycle(
        queue=queue,
        dead_letter_store=dead,
        retry_policy=policy,
        exchange_for=lambda downstream_id: exchange,
    )
    return queue, dead, cycle


def test_idle_cycle_reports_idle(tmp_path):
    _, _, cycle = supervisor(
        tmp_path,
        exchange=lambda payload: b"ack",
    )
    report = cycle.run(now="2026-09-25T21:00:00Z")
    assert report.health is RelaySupervisorHealth.IDLE
    assert report.pending_count == 0
    assert report.dead_letter_count == 0


def test_due_retry_delivery_reports_healthy(tmp_path):
    queue, _, cycle = supervisor(
        tmp_path,
        exchange=lambda payload: b"ack",
    )
    item = queue.enqueue(
        relay_id="relay-a",
        downstream_id="relay-b",
        payload=b"payload",
        item_id="item-1",
    )
    queue.mark_attempt(
        item.item_id,
        attempted_at="2026-09-25T21:00:00Z",
    )

    report = cycle.run(now="2026-09-25T21:00:01Z")
    assert report.health is RelaySupervisorHealth.HEALTHY
    assert report.pending_count == 0
    assert report.dead_letter_count == 0


def test_deferred_retry_reports_degraded(tmp_path):
    queue, _, cycle = supervisor(
        tmp_path,
        exchange=lambda payload: b"ack",
    )
    item = queue.enqueue(
        relay_id="relay-a",
        downstream_id="relay-b",
        payload=b"payload",
        item_id="item-1",
    )
    queue.mark_attempt(
        item.item_id,
        attempted_at="2026-09-25T21:00:00Z",
    )

    report = cycle.run(now="2026-09-25T21:00:00Z")
    assert report.health is RelaySupervisorHealth.DEGRADED
    assert report.pending_count == 1


def test_failed_retry_reports_degraded_before_exhaustion(tmp_path):
    queue, _, cycle = supervisor(
        tmp_path,
        exchange=lambda payload: (_ for _ in ()).throw(
            RuntimeError("offline")
        ),
    )
    queue.enqueue(
        relay_id="relay-a",
        downstream_id="relay-b",
        payload=b"payload",
        item_id="item-1",
    )

    report = cycle.run(now="2026-09-25T21:00:00Z")
    assert report.health is RelaySupervisorHealth.DEGRADED
    assert report.pending_count == 1
    assert report.dead_letter_count == 0


def test_exhausted_retry_moves_to_dead_letter_and_reports_blocked(tmp_path):
    queue, dead, cycle = supervisor(
        tmp_path,
        exchange=lambda payload: (_ for _ in ()).throw(
            RuntimeError("still offline")
        ),
    )
    item = queue.enqueue(
        relay_id="relay-a",
        downstream_id="relay-b",
        payload=b"payload",
        item_id="item-1",
    )
    queue.mark_attempt(
        item.item_id,
        attempted_at="2026-09-25T21:00:00Z",
    )

    report = cycle.run(now="2026-09-25T21:00:01Z")

    assert report.health is RelaySupervisorHealth.BLOCKED
    assert report.dead_lettered_item_ids == ("item-1",)
    assert report.pending_count == 0
    assert report.dead_letter_count == 1
    assert dead.get("item-1").reason == "retry attempts exhausted"


def test_mixed_items_preserve_retryable_pending_state(tmp_path):
    queue, _, cycle = supervisor(
        tmp_path,
        exchange=lambda payload: (_ for _ in ()).throw(
            RuntimeError("offline")
        ),
    )

    exhausted = queue.enqueue(
        relay_id="relay-a",
        downstream_id="relay-b",
        payload=b"exhausted",
        item_id="exhausted",
    )
    queue.mark_attempt(
        exhausted.item_id,
        attempted_at="2026-09-25T21:00:00Z",
    )

    queue.enqueue(
        relay_id="relay-a",
        downstream_id="relay-b",
        payload=b"fresh",
        item_id="fresh",
    )

    report = cycle.run(now="2026-09-25T21:00:01Z")

    assert report.health is RelaySupervisorHealth.BLOCKED
    assert report.dead_lettered_item_ids == ("exhausted",)
    assert tuple(item.item_id for item in queue.pending()) == ("fresh",)
