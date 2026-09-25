import pytest

from agent_control_plane.authority import AuthorityValidationError
from agent_control_plane.authority_sync_watermark import AuthoritySyncWatermark
from agent_control_plane.authority_sync_watermark_auth import (
    HmacAuthoritySyncWatermarkVerifier,
    authenticate_authority_sync_watermark,
)
from agent_control_plane.authority_sync_watermark_keys import (
    LifecycleAwareHmacWatermarkVerifier,
    WatermarkAuthenticationKeyRecord,
    WatermarkAuthenticationKeyRegistry,
    WatermarkKeyStatus,
)


KEY1 = b"a" * 32
KEY2 = b"b" * 32


def watermark(issued_at="2026-09-25T17:30:00Z"):
    return AuthoritySyncWatermark(
        watermark_id=f"peer-a:authority-source:{issued_at}",
        issuer_id="peer-a",
        target_sender_id="authority-source",
        min_sequence=3,
        issued_at=issued_at,
    )


def registry():
    result = WatermarkAuthenticationKeyRegistry()
    result.register(
        WatermarkAuthenticationKeyRecord(
            issuer_id="peer-a",
            key_id="key-1",
            valid_from="2026-09-25T17:00:00Z",
            valid_until="2026-09-25T18:00:00Z",
        )
    )
    result.register(
        WatermarkAuthenticationKeyRecord(
            issuer_id="peer-a",
            key_id="key-2",
            valid_from="2026-09-25T18:00:00Z",
        )
    )
    return result


def verifier(metadata):
    return LifecycleAwareHmacWatermarkVerifier(
        verifier=HmacAuthoritySyncWatermarkVerifier(
            {
                ("peer-a", "key-1"): KEY1,
                ("peer-a", "key-2"): KEY2,
            }
        ),
        key_registry=metadata,
    )


def signed(key_id="key-1", key=KEY1, issued_at="2026-09-25T17:30:00Z"):
    return authenticate_authority_sync_watermark(
        watermark(issued_at),
        key_id=key_id,
        key=key,
    )


def test_active_key_inside_validity_window_verifies():
    metadata = registry()
    assert verifier(metadata).verify(signed()) == watermark()


def test_key_not_yet_valid_fails_closed():
    metadata = registry()
    with pytest.raises(AuthorityValidationError, match="not yet valid"):
        verifier(metadata).verify(
            signed(issued_at="2026-09-25T16:59:59Z")
        )


def test_expired_key_fails_closed_at_valid_until_boundary():
    metadata = registry()
    with pytest.raises(AuthorityValidationError, match="expired"):
        verifier(metadata).verify(
            signed(issued_at="2026-09-25T18:00:00Z")
        )


def test_revocation_is_hard_fail_even_for_pre_revocation_watermark():
    metadata = registry()
    metadata.revoke(
        issuer_id="peer-a",
        key_id="key-1",
        revoked_at="2026-09-25T17:45:00Z",
    )
    with pytest.raises(AuthorityValidationError, match="key revoked"):
        verifier(metadata).verify(signed())


def test_rotation_accepts_new_key_after_old_window_closes():
    metadata = registry()
    rotated = signed(
        key_id="key-2",
        key=KEY2,
        issued_at="2026-09-25T18:00:00Z",
    )
    assert verifier(metadata).verify(rotated) == watermark(
        "2026-09-25T18:00:00Z"
    )


def test_unknown_lifecycle_record_fails_before_secret_lookup():
    metadata = WatermarkAuthenticationKeyRegistry()
    with pytest.raises(
        AuthorityValidationError,
        match="lifecycle unknown",
    ):
        verifier(metadata).verify(signed())


def test_key_record_conflict_and_revocation_conflict_fail_closed():
    metadata = registry()
    with pytest.raises(AuthorityValidationError, match="record conflict"):
        metadata.register(
            WatermarkAuthenticationKeyRecord(
                issuer_id="peer-a",
                key_id="key-1",
                valid_from="2026-09-25T16:00:00Z",
            )
        )

    revoked = metadata.revoke(
        issuer_id="peer-a",
        key_id="key-1",
        revoked_at="2026-09-25T17:45:00Z",
    )
    assert revoked.status is WatermarkKeyStatus.REVOKED

    with pytest.raises(AuthorityValidationError, match="revocation conflict"):
        metadata.revoke(
            issuer_id="peer-a",
            key_id="key-1",
            revoked_at="2026-09-25T17:46:00Z",
        )


def test_manifest_contains_metadata_but_never_secret_material():
    metadata = registry()
    manifest = metadata.manifest()
    assert manifest["key_count"] == 2
    serialized = str(manifest)
    assert "aaaaaaaa" not in serialized
    assert "bbbbbbbb" not in serialized
