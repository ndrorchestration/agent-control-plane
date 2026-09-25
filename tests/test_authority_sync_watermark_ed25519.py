import json

import pytest

cryptography = pytest.importorskip("cryptography")

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from agent_control_plane.authority import AuthorityValidationError
from agent_control_plane.authority_sync_watermark import AuthoritySyncWatermark
from agent_control_plane.authority_sync_watermark_ed25519 import (
    Ed25519AuthoritySyncWatermarkVerifier,
    decode_ed25519_authority_sync_watermark,
    encode_ed25519_authority_sync_watermark,
    sign_authority_sync_watermark_ed25519,
)
from agent_control_plane.authority_sync_watermark_keys import (
    WatermarkAuthenticationKeyRecord,
    WatermarkAuthenticationKeyRegistry,
)


PRIVATE = bytes(range(32))


def private_key():
    return Ed25519PrivateKey.from_private_bytes(PRIVATE)


def public_raw():
    return private_key().public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )


def watermark(issued_at="2026-09-25T17:30:00Z"):
    return AuthoritySyncWatermark(
        watermark_id=f"peer-a:authority-source:{issued_at}",
        issuer_id="peer-a",
        target_sender_id="authority-source",
        min_sequence=3,
        issued_at=issued_at,
    )


def key_registry():
    registry = WatermarkAuthenticationKeyRegistry()
    registry.register(
        WatermarkAuthenticationKeyRecord(
            issuer_id="peer-a",
            key_id="ed-key-1",
            valid_from="2026-09-25T17:00:00Z",
            valid_until="2026-09-25T18:00:00Z",
        )
    )
    return registry


def verifier():
    return Ed25519AuthoritySyncWatermarkVerifier(
        public_keys={("peer-a", "ed-key-1"): public_raw()},
        key_registry=key_registry(),
    )


def signed():
    return sign_authority_sync_watermark_ed25519(
        watermark(),
        key_id="ed-key-1",
        private_key_raw=PRIVATE,
    )


def test_ed25519_round_trip_and_public_key_verification():
    envelope = signed()
    encoded = encode_ed25519_authority_sync_watermark(envelope)
    decoded = decode_ed25519_authority_sync_watermark(encoded)
    assert decoded == envelope
    assert verifier().verify(decoded) == watermark()


def test_tampered_watermark_fails_signature_verification():
    envelope = signed()
    data = json.loads(encode_ed25519_authority_sync_watermark(envelope))
    data["watermark"]["min_sequence"] = 99
    tampered = decode_ed25519_authority_sync_watermark(
        json.dumps(data, sort_keys=True, separators=(",", ":"))
    )
    with pytest.raises(
        AuthorityValidationError,
        match="signature verification failed",
    ):
        verifier().verify(tampered)


def test_wrong_public_key_fails_signature_verification():
    envelope = signed()
    other = Ed25519PrivateKey.from_private_bytes(b"x" * 32)
    other_public = other.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    bad = Ed25519AuthoritySyncWatermarkVerifier(
        public_keys={("peer-a", "ed-key-1"): other_public},
        key_registry=key_registry(),
    )
    with pytest.raises(
        AuthorityValidationError,
        match="signature verification failed",
    ):
        bad.verify(envelope)


def test_revoked_key_fails_before_signature_verification():
    registry = key_registry()
    registry.revoke(
        issuer_id="peer-a",
        key_id="ed-key-1",
        revoked_at="2026-09-25T17:45:00Z",
    )
    checked = Ed25519AuthoritySyncWatermarkVerifier(
        public_keys={("peer-a", "ed-key-1"): public_raw()},
        key_registry=registry,
    )
    with pytest.raises(AuthorityValidationError, match="key revoked"):
        checked.verify(signed())


def test_unknown_lifecycle_or_public_key_fails_closed():
    empty_registry = WatermarkAuthenticationKeyRegistry()
    no_lifecycle = Ed25519AuthoritySyncWatermarkVerifier(
        public_keys={("peer-a", "ed-key-1"): public_raw()},
        key_registry=empty_registry,
    )
    with pytest.raises(
        AuthorityValidationError,
        match="lifecycle unknown",
    ):
        no_lifecycle.verify(signed())

    no_public = Ed25519AuthoritySyncWatermarkVerifier(
        public_keys={},
        key_registry=key_registry(),
    )
    with pytest.raises(
        AuthorityValidationError,
        match="unknown Ed25519 watermark public key",
    ):
        no_public.verify(signed())
