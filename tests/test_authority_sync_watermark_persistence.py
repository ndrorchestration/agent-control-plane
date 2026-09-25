import sqlite3

import pytest

from agent_control_plane.authority import AuthorityValidationError
from agent_control_plane.authority_sync_watermark import (
    AuthoritySyncWatermark,
    WatermarkDisposition,
)
from agent_control_plane.authority_sync_watermark_persistence import (
    DurableAuthoritySyncWatermarkRegistry,
)


def watermark(watermark_id="wm-1", sequence=3):
    return AuthoritySyncWatermark(
        watermark_id=watermark_id,
        issuer_id="peer-a",
        target_sender_id="authority-source",
        min_sequence=sequence,
        issued_at="2026-09-25T15:02:00Z",
    )


def registry(path):
    return DurableAuthoritySyncWatermarkRegistry(
        {"authority-source": {"peer-a"}},
        database_path=path,
    )


def test_restart_recovers_required_floor_and_duplicate_identity(tmp_path):
    database = tmp_path / "watermarks.sqlite3"
    first = registry(database)
    assert first.apply(watermark()) is WatermarkDisposition.APPLIED
    assert first.required_sequence("authority-source") == 3

    recovered = registry(database)
    assert recovered.required_sequence("authority-source") == 3
    assert recovered.apply(watermark()) is WatermarkDisposition.DUPLICATE


def test_higher_floor_persists_across_restart(tmp_path):
    database = tmp_path / "watermarks.sqlite3"
    first = registry(database)
    first.apply(watermark("wm-1", 3))
    first.apply(watermark("wm-2", 5))

    recovered = registry(database)
    assert recovered.required_sequence("authority-source") == 5
    with pytest.raises(AuthorityValidationError, match="regression"):
        recovered.apply(watermark("wm-3", 4))


def test_manifest_content_root_is_stable_across_restart(tmp_path):
    database = tmp_path / "watermarks.sqlite3"
    first = registry(database)
    first.apply(watermark())
    before = first.manifest()["persistence"]

    recovered = registry(database)
    after = recovered.manifest()["persistence"]
    assert before == after
    assert before["watermark_count"] == 1
    assert len(before["content_root_sha256"]) == 64


def test_payload_tampering_fails_closed_on_restart(tmp_path):
    database = tmp_path / "watermarks.sqlite3"
    first = registry(database)
    first.apply(watermark())

    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE applied_watermarks SET payload = ? WHERE watermark_id = ?",
            (sqlite3.Binary(b"{}"), "wm-1"),
        )

    with pytest.raises(AuthorityValidationError, match="content hash mismatch"):
        registry(database)


def test_schema_mismatch_fails_closed(tmp_path):
    database = tmp_path / "watermarks.sqlite3"
    registry(database)
    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE watermark_metadata SET value = ? WHERE key = 'schema_version'",
            ("unsupported",),
        )

    with pytest.raises(AuthorityValidationError, match="unsupported"):
        registry(database)
