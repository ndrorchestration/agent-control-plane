"""Final ACP signed relay-chain sink for live Reticulum integration."""

import argparse
from pathlib import Path
import time

import RNS
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from agent_control_plane.authority_sync_watermark import AuthoritySyncWatermarkRegistry
from agent_control_plane.authority_sync_watermark_ed25519 import (
    Ed25519AuthoritySyncWatermarkVerifier,
)
from agent_control_plane.authority_sync_watermark_keys import (
    WatermarkAuthenticationKeyRecord,
    WatermarkAuthenticationKeyRegistry,
)
from agent_control_plane.authority_sync_watermark_relay_chain import (
    Ed25519RelayChainEndpoint,
    Ed25519RelayChainVerifier,
)
from agent_control_plane.reticulum_adapter import ReticulumSignedRelayChainServer


APP_NAME = "ndrorchestration"
ASPECTS = ("acp", "relay_chain_sink_live")
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


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config-dir", required=True)
    parser.add_argument("--destination-hash-file", required=True)
    parser.add_argument("--identity-hash-file", required=True)
    parser.add_argument("--terminal-relay-identity-hash", required=True)
    args = parser.parse_args()

    RNS.Reticulum(configdir=args.config_dir)
    identity = RNS.Identity()
    destination = RNS.Destination(
        identity,
        RNS.Destination.IN,
        RNS.Destination.SINGLE,
        APP_NAME,
        *ASPECTS,
    )
    destination.accepts_links(True)

    origin_registry = WatermarkAuthenticationKeyRegistry()
    origin_registry.register(key_record("origin-peer", "origin-ed-key"))

    relay_registry = WatermarkAuthenticationKeyRegistry()
    for relay_id in RELAY_PRIVATE:
        relay_registry.register(key_record(relay_id, "relay-ed-key"))

    endpoint = Ed25519RelayChainEndpoint(
        receiver_id="final-sink",
        verifier=Ed25519RelayChainVerifier(
            origin_verifier=Ed25519AuthoritySyncWatermarkVerifier(
                public_keys={
                    ("origin-peer", "origin-ed-key"): public_raw(ORIGIN_PRIVATE)
                },
                key_registry=origin_registry,
            ),
            relay_public_keys={
                (relay_id, "relay-ed-key"): public_raw(private_raw)
                for relay_id, private_raw in RELAY_PRIVATE.items()
            },
            relay_key_registry=relay_registry,
            max_hops=8,
        ),
        registry=AuthoritySyncWatermarkRegistry(
            {"authority-source": {"origin-peer"}}
        ),
    )
    terminal_hash = bytes.fromhex(args.terminal_relay_identity_hash)
    server = ReticulumSignedRelayChainServer(
        destination=destination,
        endpoint=endpoint,
        terminal_relay_identity_hashes={"relay-c": terminal_hash},
    )
    server.install(
        allow=RNS.Destination.ALLOW_LIST,
        allowed_list=[terminal_hash],
    )

    Path(args.destination_hash_file).write_text(
        destination.hash.hex(),
        encoding="utf-8",
    )
    Path(args.identity_hash_file).write_text(
        identity.hash.hex(),
        encoding="utf-8",
    )

    while True:
        destination.announce()
        time.sleep(5.0)


if __name__ == "__main__":
    main()
