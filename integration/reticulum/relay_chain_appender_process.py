"""Integration helper: verify a relay-chain prefix and append exactly one signed hop."""

import argparse
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from agent_control_plane.authority_sync_watermark_ed25519 import (
    Ed25519AuthoritySyncWatermarkVerifier,
)
from agent_control_plane.authority_sync_watermark_keys import (
    WatermarkAuthenticationKeyRecord,
    WatermarkAuthenticationKeyRegistry,
)
from agent_control_plane.authority_sync_watermark_relay_chain import (
    Ed25519RelayChainAppender,
    Ed25519RelayChainVerifier,
    decode_ed25519_relay_chain,
    encode_ed25519_relay_chain,
)


ORIGIN_PRIVATE = bytes(range(32))
RELAY_PRIVATE = {
    "relay-a": b"a" * 32,
    "relay-b": b"b" * 32,
    "relay-c": b"c" * 32,
}


def public_raw(private_raw: bytes) -> bytes:
    return Ed25519PrivateKey.from_private_bytes(private_raw).public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )


def key_record(subject_id: str, key_id: str) -> WatermarkAuthenticationKeyRecord:
    return WatermarkAuthenticationKeyRecord(
        issuer_id=subject_id,
        key_id=key_id,
        valid_from="2026-09-25T17:00:00Z",
    )


def origin_verifier() -> Ed25519AuthoritySyncWatermarkVerifier:
    registry = WatermarkAuthenticationKeyRegistry()
    registry.register(key_record("origin-peer", "origin-ed-key"))
    return Ed25519AuthoritySyncWatermarkVerifier(
        public_keys={
            ("origin-peer", "origin-ed-key"): public_raw(ORIGIN_PRIVATE)
        },
        key_registry=registry,
    )


def prefix_verifier() -> Ed25519RelayChainVerifier:
    relay_registry = WatermarkAuthenticationKeyRegistry()
    for relay_id in RELAY_PRIVATE:
        relay_registry.register(key_record(relay_id, "relay-ed-key"))
    return Ed25519RelayChainVerifier(
        origin_verifier=origin_verifier(),
        relay_public_keys={
            (relay_id, "relay-ed-key"): public_raw(private_raw)
            for relay_id, private_raw in RELAY_PRIVATE.items()
        },
        relay_key_registry=relay_registry,
        max_hops=8,
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--relay-id", required=True, choices=sorted(RELAY_PRIVATE))
    parser.add_argument("--next-receiver-id", required=True)
    parser.add_argument("--relayed-at", required=True)
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    payload = Path(args.input).read_bytes()
    chain = decode_ed25519_relay_chain(payload)

    appender = Ed25519RelayChainAppender(
        relay_id=args.relay_id,
        key_id="relay-ed-key",
        private_key_raw=RELAY_PRIVATE[args.relay_id],
        next_receiver_id=args.next_receiver_id,
        origin_verifier=origin_verifier(),
        prefix_verifier=prefix_verifier(),
    )
    updated = appender.append(chain, relayed_at=args.relayed_at)
    Path(args.output).write_bytes(encode_ed25519_relay_chain(updated))

    print(f"RELAY_APPEND=PASS:{args.relay_id}")
    print(f"HOP_COUNT={len(updated.hops)}")


if __name__ == "__main__":
    main()
