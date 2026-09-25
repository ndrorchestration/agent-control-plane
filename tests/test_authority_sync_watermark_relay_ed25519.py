import pytest

cryptography = pytest.importorskip("cryptography")

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from agent_control_plane.authority import AuthorityValidationError
from agent_control_plane.authority_sync_watermark import (
    AuthoritySyncWatermark,
    AuthoritySyncWatermarkRegistry,
    WatermarkDisposition,
)
from agent_control_plane.authority_sync_watermark_ed25519 import (
    Ed25519AuthoritySyncWatermarkVerifier,
    encode_ed25519_authority_sync_watermark,
    sign_authority_sync_watermark_ed25519,
)
from agent_control_plane.authority_sync_watermark_keys import (
    WatermarkAuthenticationKeyRecord,
    WatermarkAuthenticationKeyRegistry,
)
from agent_control_plane.authority_sync_watermark_relay import (
    Ed25519RelayedWatermarkAdmission,
    RelayedWatermarkEndpoint,
    decode_relayed_watermark_acknowledgement,
    encode_relayed_authenticated_watermark,
    wrap_authenticated_watermark_for_relay,
)


PRIVATE = bytes(range(32))


def public_raw():
    private = Ed25519PrivateKey.from_private_bytes(PRIVATE)
    return private.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )


def origin_payload(sequence=3):
    watermark = AuthoritySyncWatermark(
        watermark_id=f"origin:authority-source:{sequence}",
        issuer_id="origin",
        target_sender_id="authority-source",
        min_sequence=sequence,
        issued_at="2026-09-25T17:50:00Z",
    )
    signed = sign_authority_sync_watermark_ed25519(
        watermark,
        key_id="ed-key-1",
        private_key_raw=PRIVATE,
    )
    return encode_ed25519_authority_sync_watermark(signed)


def endpoint(public_key=None):
    metadata = WatermarkAuthenticationKeyRegistry()
    metadata.register(
        WatermarkAuthenticationKeyRecord(
            issuer_id="origin",
            key_id="ed-key-1",
            valid_from="2026-09-25T17:00:00Z",
        )
    )
    verifier = Ed25519AuthoritySyncWatermarkVerifier(
        public_keys={
            ("origin", "ed-key-1"):
                public_raw() if public_key is None else public_key
        },
        key_registry=metadata,
    )
    admission = Ed25519RelayedWatermarkAdmission(
        verifier=verifier,
        registry=AuthoritySyncWatermarkRegistry(
            {"authority-source": {"origin"}}
        ),
    )
    return RelayedWatermarkEndpoint(
        receiver_id="destination",
        admission=admission,
    )


def relayed_payload():
    relayed = wrap_authenticated_watermark_for_relay(
        origin_payload(),
        relay_id="relay-b",
        relayed_at="2026-09-25T17:51:00Z",
    )
    return encode_relayed_authenticated_watermark(relayed)


def test_ed25519_origin_survives_relay_without_private_key_at_destination():
    target = endpoint()
    ack = decode_relayed_watermark_acknowledgement(
        target.receive(
            relayed_payload(),
            authenticated_relay_id="relay-b",
        )
    )
    assert ack.disposition is WatermarkDisposition.APPLIED


def test_exact_ed25519_relay_replay_is_duplicate():
    target = endpoint()
    payload = relayed_payload()
    first = decode_relayed_watermark_acknowledgement(
        target.receive(payload, authenticated_relay_id="relay-b")
    )
    second = decode_relayed_watermark_acknowledgement(
        target.receive(payload, authenticated_relay_id="relay-b")
    )
    assert first.disposition is WatermarkDisposition.APPLIED
    assert second.disposition is WatermarkDisposition.DUPLICATE


def test_relay_identity_mismatch_fails_before_origin_application():
    target = endpoint()
    with pytest.raises(
        AuthorityValidationError,
        match="relay identity mismatch",
    ):
        target.receive(
            relayed_payload(),
            authenticated_relay_id="relay-c",
        )


def test_wrong_public_key_fails_origin_signature_verification():
    other = Ed25519PrivateKey.from_private_bytes(b"x" * 32)
    other_public = other.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    target = endpoint(other_public)
    with pytest.raises(
        AuthorityValidationError,
        match="signature verification failed",
    ):
        target.receive(
            relayed_payload(),
            authenticated_relay_id="relay-b",
        )
