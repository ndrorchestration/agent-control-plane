import pytest

from agent_control_plane.authority import AuthorityValidationError
from agent_control_plane.relay_dead_letter import DurableRelayDeadLetterStore
from agent_control_plane.relay_forward_queue import DurableRelayForwardQueue


def exhausted_item(tmp_path):
    queue = DurableRelayForwardQueue(tmp_path / "pending.sqlite3")
    item = queue.enqueue(
        relay_id="relay-a",
        downstream_id="relay-b",
        payload=b"signed-chain",
        item_id="item-1",
        enqueued_at="2026-09-25T20:00:00Z",
    )
    queue.mark_attempt(
        item.item_id,
        attempted_at="2026-09-25T20:00:01Z",
    )
    queue.mark_attempt(
        item.item_id,
        attempted_at="2026-09-25T20:00:02Z",
    )
    return queue, queue.get(item.item_id)


def test_store_preserves_terminal_payload_and_metadata(tmp_path):
    queue, item = exhausted_item(tmp_path)
    store = DurableRelayDeadLetterStore(tmp_path / "dead.sqlite3")
    dead = store.store(
        item,
        reason="retry attempts exhausted",
        dead_lettered_at="2026-09-25T20:01:00Z",
    )
    assert dead.item_id == "item-1"
    assert dead.payload == b"signed-chain"
    assert dead.attempt_count == 2
    assert dead.reason == "retry attempts exhausted"
    assert len(queue.pending()) == 1


def test_move_persists_before_removing_pending_item(tmp_path):
    queue, item = exhausted_item(tmp_path)
    store = DurableRelayDeadLetterStore(tmp_path / "dead.sqlite3")
    dead = store.move_from_queue(
        queue,
        item_id=item.item_id,
        reason="retry attempts exhausted",
        dead_lettered_at="2026-09-25T20:01:00Z",
    )
    assert dead.item_id == item.item_id
    assert queue.pending() == ()
    assert store.get(item.item_id) == dead


def test_store_is_idempotent_for_same_terminal_record(tmp_path):
    _, item = exhausted_item(tmp_path)
    store = DurableRelayDeadLetterStore(tmp_path / "dead.sqlite3")
    first = store.store(
        item,
        reason="retry attempts exhausted",
        dead_lettered_at="2026-09-25T20:01:00Z",
    )
    second = store.store(
        item,
        reason="retry attempts exhausted",
        dead_lettered_at="2026-09-25T20:02:00Z",
    )
    assert first == second


def test_conflicting_repeat_dead_letter_fails_closed(tmp_path):
    _, item = exhausted_item(tmp_path)
    store = DurableRelayDeadLetterStore(tmp_path / "dead.sqlite3")
    store.store(
        item,
        reason="retry attempts exhausted",
    )
    with pytest.raises(
        AuthorityValidationError,
        match="dead-letter conflict",
    ):
        store.store(
            item,
            reason="different terminal reason",
        )


def test_unattempted_item_cannot_be_dead_lettered(tmp_path):
    queue = DurableRelayForwardQueue(tmp_path / "pending.sqlite3")
    item = queue.enqueue(
        relay_id="relay-a",
        downstream_id="relay-b",
        payload=b"signed-chain",
    )
    store = DurableRelayDeadLetterStore(tmp_path / "dead.sqlite3")
    with pytest.raises(
        AuthorityValidationError,
        match="unattempted",
    ):
        store.store(item, reason="not actually exhausted")


def test_manifest_omits_payload_bytes(tmp_path):
    _, item = exhausted_item(tmp_path)
    store = DurableRelayDeadLetterStore(tmp_path / "dead.sqlite3")
    store.store(item, reason="retry attempts exhausted")
    manifest = store.manifest()
    assert manifest["dead_letter_count"] == 1
    assert "signed-chain" not in str(manifest)
