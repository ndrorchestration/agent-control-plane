import json

import pytest

from agent_control_plane.authority import AuthorityValidationError
from agent_control_plane.authority_sync_watermark import AuthoritySyncWatermark
from agent_control_plane.authority_sync_watermark_auth import (
    AUTHENTICATED_WATERMARK_ALGORITHM,
    HmacAuthoritySyncWatermarkVerifier,
    authenticate_authority_sync_watermark,
    decode_authenticated_authority_sync_watermark,
    encode_authenticated_authority_sync_watermark,
)


KEY = b"k" * 32


def watermark(sequence=3):
    return AuthoritySyncWatermark(
        watermark_id=f"peer-a:authority-source:{sequence}",
        issuer_id="peer-a",
        target_sender_id="authority-source",
        min_sequence=sequence,
        issued_at="2026-09-25T17:15:00Z",
    )


def verifier():
    return HmacAuthoritySyncWatermarkVerifier(
        {("peer-a", "key-1"): KEY}
    )


def test_authenticated_watermark_round_trip_and_verify():
    envelope = authenticate_authority_sync_watermark(
        watermark(),
        key_id="key-1",
        key=KEY,
    )
    assert envelope.algorithm == AUTHENTICATED_WATERMARK_ALGORITHM

    encoded = encode_authenticated_authority_sync_watermark(envelope)
    decoded = decode_authenticated_authority_sync_watermark(encoded)
    assert decoded == envelope
    assert verifier().verify(decoded) == watermark()


def test_tampered_watermark_fails_authentication():
    envelope = authenticate_authority_sync_watermark(
        watermark(),
        key_id="key-1",
        key=KEY,
    )
    data = json.loads(
        encode_authenticated_authority_sync_watermark(envelope)
    )
    data["watermark"]["min_sequence"] = 99

    tampered = decode_authenticated_authority_sync_watermark(
        json.dumps(data, sort_keys=True, separators=(",", ":"))
    )
    with pytest.raises(
        AuthorityValidationError,
        match="authentication failed",
    ):
        verifier().verify(tampered)


def test_signature_covers_key_id_and_origin_identity():
    envelope = authenticate_authority_sync_watermark(
        watermark(),
        key_id="key-1",
        key=KEY,
    )

    data = json.loads(
        encode_authenticated_authority_sync_watermark(envelope)
    )
    data["key_id"] = "key-2"
    changed_key_id = decode_authenticated_authority_sync_watermark(
        json.dumps(data, sort_keys=True, separators=(",", ":"))
    )
    with pytest.raises(
        AuthorityValidationError,
        match="unknown watermark authentication key",
    ):
        verifier().verify(changed_key_id)

    data = json.loads(
        encode_authenticated_authority_sync_watermark(envelope)
    )
    data["watermark"]["issuer_id"] = "peer-b"
    changed_issuer = decode_authenticated_authority_sync_watermark(
        json.dumps(data, sort_keys=True, separators=(",", ":"))
    )
    with pytest.raises(
        AuthorityValidationError,
        match="unknown watermark authentication key",
    ):
        verifier().verify(changed_issuer)


def test_wrong_secret_fails_authentication():
    envelope = authenticate_authority_sync_watermark(
        watermark(),
        key_id="key-1",
        key=KEY,
    )
    wrong = HmacAuthoritySyncWatermarkVerifier(
        {("peer-a", "key-1"): b"x" * 32}
    )
    with pytest.raises(
        AuthorityValidationError,
        match="authentication failed",
    ):
        wrong.verify(envelope)


def test_short_or_missing_keys_fail_closed():
    with pytest.raises(
        AuthorityValidationError,
        match="length >= 32",
    ):
        authenticate_authority_sync_watermark(
            watermark(),
            key_id="key-1",
            key=b"short",
        )

    envelope = authenticate_authority_sync_watermark(
        watermark(),
        key_id="key-1",
        key=KEY,
    )
    empty = HmacAuthoritySyncWatermarkVerifier({})
    with pytest.raises(
        AuthorityValidationError,
        match="unknown watermark authentication key",
    ):
        empty.verify(envelope)
