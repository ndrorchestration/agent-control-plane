import hashlib
import sqlite3

import pytest

from agent_control_plane.authority import AuthorityValidationError
from agent_control_plane.authority_state import AuthorityStateSnapshot
from agent_control_plane.authority_sync import (
    RevocationSyncMessage,
    SnapshotSyncMessage,
    SyncDisposition,
)
from agent_control_plane.authority_sync_persistence import (
    AUTHORITY_SYNC_LOG_SCHEMA_VERSION,
    DurableAuthoritySyncReconciler,
)
from agent_control_plane.revocation import RevocationRecord


def snapshot_message(message_id="m-1", sequence=1, epoch=1):
    return SnapshotSyncMessage(
        message_id=message_id,
        sender_id="node-a",
        sequence=sequence,
        snapshot=AuthorityStateSnapshot(
            "auth-1",
            epoch,
            "2026-09-25T15:00:00Z",
            "node-a",
        ),
    )


def revocation_message(message_id="r-1", sequence=2):
    return RevocationSyncMessage(
        message_id=message_id,
        sender_id="node-a",
        sequence=sequence,
        revocation=RevocationRecord(
            "auth-1",
            "2026-09-25T15:01:00Z",
            "operator_revoked",
        ),
    )


def test_restart_recovers_authority_revocation_duplicate_and_replay_state(tmp_path):
    database = tmp_path / "sync" / "authority-sync.sqlite3"

    first = DurableAuthoritySyncReconciler(
        receiver_id="node-b",
        database_path=database,
    )
    assert first.apply(snapshot_message()).disposition is SyncDisposition.APPLIED
    assert first.apply(revocation_message()).disposition is SyncDisposition.APPLIED

    recovered = DurableAuthoritySyncReconciler(
        receiver_id="node-b",
        database_path=database,
    )

    assert recovered.state_cache.get("auth-1").epoch == 1
    assert recovered.revocations.is_revoked_at(
        "auth-1",
        "2026-09-25T15:01:00Z",
    ) is True

    duplicate = recovered.apply(snapshot_message())
    assert duplicate.disposition is SyncDisposition.DUPLICATE
    assert duplicate.reason_code == "duplicate_message"

    regression = recovered.apply(
        snapshot_message(message_id="m-regressed", sequence=1, epoch=2)
    )
    assert regression.disposition is SyncDisposition.REJECTED
    assert regression.reason_code == "replay_or_sequence_regression"
    assert recovered.manifest()["sender_sequences"] == {"node-a": 2}


def test_manifest_has_stable_content_root_across_restart(tmp_path):
    database = tmp_path / "authority-sync.sqlite3"
    first = DurableAuthoritySyncReconciler(
        receiver_id="node-b",
        database_path=database,
    )
    first.apply(snapshot_message())
    first.apply(revocation_message())

    first_manifest = first.manifest()["persistence"]
    recovered = DurableAuthoritySyncReconciler(
        receiver_id="node-b",
        database_path=database,
    )
    recovered_manifest = recovered.manifest()["persistence"]

    assert first_manifest == recovered_manifest
    assert first_manifest["schema"] == AUTHORITY_SYNC_LOG_SCHEMA_VERSION
    assert first_manifest["message_count"] == 2
    assert len(first_manifest["content_root_sha256"]) == 64
    int(first_manifest["content_root_sha256"], 16)


def test_empty_log_has_deterministic_content_root(tmp_path):
    durable = DurableAuthoritySyncReconciler(
        receiver_id="node-b",
        database_path=tmp_path / "authority-sync.sqlite3",
    )
    persistence = durable.manifest()["persistence"]
    assert persistence["message_count"] == 0
    assert persistence["content_root_sha256"] == hashlib.sha256(b"").hexdigest()


def test_payload_tampering_is_detected_fail_closed_on_restart(tmp_path):
    database = tmp_path / "authority-sync.sqlite3"
    durable = DurableAuthoritySyncReconciler(
        receiver_id="node-b",
        database_path=database,
    )
    durable.apply(snapshot_message())

    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE applied_messages SET payload = ? WHERE message_id = ?",
            (sqlite3.Binary(b"{}"), "m-1"),
        )

    with pytest.raises(AuthorityValidationError, match="content hash mismatch"):
        DurableAuthoritySyncReconciler(
            receiver_id="node-b",
            database_path=database,
        )


def test_schema_mismatch_is_detected_fail_closed(tmp_path):
    database = tmp_path / "authority-sync.sqlite3"
    DurableAuthoritySyncReconciler(
        receiver_id="node-b",
        database_path=database,
    )

    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE metadata SET value = ? WHERE key = 'schema_version'",
            ("unsupported",),
        )

    with pytest.raises(AuthorityValidationError, match="unsupported authority sync log schema"):
        DurableAuthoritySyncReconciler(
            receiver_id="node-b",
            database_path=database,
        )
