import json

import pytest

cryptography = pytest.importorskip("cryptography")

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from agent_control_plane.authority import AuthorityValidationError
from agent_control_plane.authority_sync_watermark import AuthoritySyncWatermark
from agent_control_plane.authority_sync_watermark_ed25519 import (
    Ed25519AuthoritySyncWatermarkVerifier,
    encode_ed25519_authority_sync_watermark,
    sign_authority_sync_watermark_ed25519,
)
from agent_control_plane.authority_sync_watermark_keys import (
    WatermarkAuthenticationKeyRecord,
    WatermarkAuthenticationKeyRegistry,
)
from agent_control_plane.authority_sync_watermark_relay_chain import (
    Ed25519RelayChainVerifier,
    RelayHopAttestation,
    append_ed25519_relay_hop,
    decode_ed25519_relay_chain,
    encode_ed25519_relay_chain,
    new_ed25519_relay_chain,
)


ORIGIN_PRIVATE = bytes(range(32))
RELAY_A_PRIVATE = b"a" * 32
RELAY_B_PRIVATE = b"b" * 32
RELAY_C_PRIVATE = b"c" * 32


def public_raw(private_raw):
    private = Ed25519PrivateKey.from_private_bytes(private_raw)
    return private.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )


def key_record(issuer_id, key_id):
    return WatermarkAuthenticationKeyRecord(
        issuer_id=issuer_id,
        key_id=key_id,
        valid_from="2026-09-25T17:00:00Z",
    )


def origin_payload():
    watermark = AuthoritySyncWatermark(
        watermark_id="origin:authority-source:7",
        issuer_id="origin",
        target_sender_id="authority-source",
        min_sequence=7,
        issued_at="2026-09-25T17:50:00Z",
    )
    envelope = sign_authority_sync_watermark_ed25519(
        watermark,
        key_id="origin-key",
        private_key_raw=ORIGIN_PRIVATE,
    )
    return encode_ed25519_authority_sync_watermark(envelope)


def origin_verifier():
    registry = WatermarkAuthenticationKeyRegistry()
    registry.register(key_record("origin", "origin-key"))
    return Ed25519AuthoritySyncWatermarkVerifier(
        public_keys={
            ("origin", "origin-key"): public_raw(ORIGIN_PRIVATE)
        },
        key_registry=registry,
    )


def relay_registry():
    registry = WatermarkAuthenticationKeyRegistry()
    registry.register(key_record("relay-a", "relay-key"))
    registry.register(key_record("relay-b", "relay-key"))
    registry.register(key_record("relay-c", "relay-key"))
    return registry


def chain_verifier(max_hops=16):
    return Ed25519RelayChainVerifier(
        origin_verifier=origin_verifier(),
        relay_public_keys={
            ("relay-a", "relay-key"): public_raw(RELAY_A_PRIVATE),
            ("relay-b", "relay-key"): public_raw(RELAY_B_PRIVATE),
            ("relay-c", "relay-key"): public_raw(RELAY_C_PRIVATE),
        },
        relay_key_registry=relay_registry(),
        max_hops=max_hops,
    )


def three_hop_chain():
    chain = new_ed25519_relay_chain(origin_payload())
    chain = append_ed25519_relay_hop(
        chain,
        relay_id="relay-a",
        key_id="relay-key",
        private_key_raw=RELAY_A_PRIVATE,
        relayed_at="2026-09-25T17:51:00Z",
        next_receiver_id="relay-b",
    )
    chain = append_ed25519_relay_hop(
        chain,
        relay_id="relay-b",
        key_id="relay-key",
        private_key_raw=RELAY_B_PRIVATE,
        relayed_at="2026-09-25T17:52:00Z",
        next_receiver_id="relay-c",
    )
    return append_ed25519_relay_hop(
        chain,
        relay_id="relay-c",
        key_id="relay-key",
        private_key_raw=RELAY_C_PRIVATE,
        relayed_at="2026-09-25T17:53:00Z",
        next_receiver_id="destination",
    )


def test_three_hop_chain_round_trip_and_verification():
    chain = three_hop_chain()
    encoded = encode_ed25519_relay_chain(chain)
    decoded = decode_ed25519_relay_chain(encoded)
    assert decoded == chain

    verified = chain_verifier().verify(
        decoded,
        final_receiver_id="destination",
    )
    assert verified.watermark.min_sequence == 7
    assert verified.relay_path == ("relay-a", "relay-b", "relay-c")
    assert verified.final_receiver_id == "destination"


def test_wrong_final_destination_fails_closed():
    with pytest.raises(
        AuthorityValidationError,
        match="next receiver mismatch",
    ):
        chain_verifier().verify(
            three_hop_chain(),
            final_receiver_id="other-destination",
        )


def test_dropping_middle_hop_breaks_hash_or_destination_link():
    chain = three_hop_chain()
    dropped = type(chain)(
        origin_envelope_b64=chain.origin_envelope_b64,
        hops=(chain.hops[0], chain.hops[2]),
    )
    with pytest.raises(AuthorityValidationError):
        chain_verifier().verify(
            dropped,
            final_receiver_id="destination",
        )


def test_tampered_hop_metadata_fails_signature_verification():
    chain = three_hop_chain()
    middle = chain.hops[1]
    tampered_middle = RelayHopAttestation(
        relay_id=middle.relay_id,
        key_id=middle.key_id,
        hop_index=middle.hop_index,
        relayed_at=middle.relayed_at,
        previous_sha256=middle.previous_sha256,
        next_receiver_id="attacker-controlled",
        algorithm=middle.algorithm,
        signature_b64=middle.signature_b64,
    )
    tampered = type(chain)(
        origin_envelope_b64=chain.origin_envelope_b64,
        hops=(chain.hops[0], tampered_middle, chain.hops[2]),
    )
    with pytest.raises(AuthorityValidationError):
        chain_verifier().verify(
            tampered,
            final_receiver_id="destination",
        )


def test_repeat_relay_loop_is_rejected_while_appending():
    chain = new_ed25519_relay_chain(origin_payload())
    chain = append_ed25519_relay_hop(
        chain,
        relay_id="relay-a",
        key_id="relay-key",
        private_key_raw=RELAY_A_PRIVATE,
        relayed_at="2026-09-25T17:51:00Z",
        next_receiver_id="relay-b",
    )
    with pytest.raises(
        AuthorityValidationError,
        match="must not repeat",
    ):
        append_ed25519_relay_hop(
            chain,
            relay_id="relay-a",
            key_id="relay-key",
            private_key_raw=RELAY_A_PRIVATE,
            relayed_at="2026-09-25T17:52:00Z",
            next_receiver_id="destination",
        )


def test_revoked_relay_key_fails_closed():
    chain = three_hop_chain()
    registry = relay_registry()
    registry.revoke(
        issuer_id="relay-b",
        key_id="relay-key",
        revoked_at="2026-09-25T17:59:00Z",
    )
    verifier = Ed25519RelayChainVerifier(
        origin_verifier=origin_verifier(),
        relay_public_keys={
            ("relay-a", "relay-key"): public_raw(RELAY_A_PRIVATE),
            ("relay-b", "relay-key"): public_raw(RELAY_B_PRIVATE),
            ("relay-c", "relay-key"): public_raw(RELAY_C_PRIVATE),
        },
        relay_key_registry=registry,
    )
    with pytest.raises(
        AuthorityValidationError,
        match="relay signing key revoked",
    ):
        verifier.verify(
            chain,
            final_receiver_id="destination",
        )


def test_max_hop_bound_fails_closed():
    with pytest.raises(
        AuthorityValidationError,
        match="exceeds max_hops",
    ):
        chain_verifier(max_hops=2).verify(
            three_hop_chain(),
            final_receiver_id="destination",
        )


def test_origin_payload_tampering_fails_origin_verification():
    chain = three_hop_chain()
    data = json.loads(chain.origin_payload())
    data["watermark"]["min_sequence"] = 999
    tampered_origin = json.dumps(
        data,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    tampered_chain = type(chain)(
        origin_envelope_b64=__import__("base64").b64encode(
            tampered_origin
        ).decode("ascii"),
        hops=chain.hops,
    )
    with pytest.raises(AuthorityValidationError):
        chain_verifier().verify(
            tampered_chain,
            final_receiver_id="destination",
        )
