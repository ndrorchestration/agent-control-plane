"""Local Reticulum server process for ACP live integration testing."""

import argparse
from pathlib import Path
import time

import RNS

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from agent_control_plane.authority_sync_persistence import DurableAuthoritySyncReconciler
from agent_control_plane.authority_sync_watermark import AuthoritySyncWatermarkRegistry
from agent_control_plane.authority_sync_watermark_auth import HmacAuthoritySyncWatermarkVerifier
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
from agent_control_plane.authority_sync_watermark_persistence import DurableAuthoritySyncWatermarkRegistry
from agent_control_plane.authority_sync_watermark_relay import (
    RelayedWatermarkAdmission,
    RelayedWatermarkEndpoint,
)
from agent_control_plane.reticulum_adapter import (
    ReticulumAuthoritySyncServer,
    ReticulumAuthoritySyncWatermarkServer,
    ReticulumRelayedWatermarkServer,
    ReticulumSignedRelayChainServer,
)
from agent_control_plane.sync_transport import AuthoritySyncEndpoint
from agent_control_plane.watermark_transport import AuthoritySyncWatermarkEndpoint


APP_NAME = "ndrorchestration"
ASPECTS = ("acp", "authority_sync_live")
RELAY_ORIGIN_KEY = bytes.fromhex("11" * 32)
CHAIN_ORIGIN_PRIVATE = bytes(range(32))
CHAIN_RELAY_A_PRIVATE = b"a" * 32
CHAIN_RELAY_B_PRIVATE = b"b" * 32
CHAIN_RELAY_C_PRIVATE = b"c" * 32


def ed25519_public_raw(private_raw: bytes) -> bytes:
    return Ed25519PrivateKey.from_private_bytes(private_raw).public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config-dir", required=True)
    parser.add_argument("--hash-file", required=True)
    parser.add_argument("--allowed-sender-id", required=True)
    parser.add_argument("--allowed-identity-hash", required=True)
    parser.add_argument("--terminal-relay-identity-hash")
    parser.add_argument("--state-db", required=True)
    parser.add_argument("--watermark-db", required=True)
    parser.add_argument("--announce-interval", type=float, default=1.0)
    args = parser.parse_args()
    if args.announce_interval <= 0:
        raise RuntimeError("announce interval must be > 0")

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

    endpoint = AuthoritySyncEndpoint(
        DurableAuthoritySyncReconciler(
            receiver_id="reticulum-server",
            database_path=args.state_db,
        )
    )
    allowed_identity_hash = bytes.fromhex(args.allowed_identity_hash)
    terminal_relay_identity_hash = (
        bytes.fromhex(args.terminal_relay_identity_hash)
        if args.terminal_relay_identity_hash is not None
        else allowed_identity_hash
    )
    server = ReticulumAuthoritySyncServer(
        destination=destination,
        endpoint=endpoint,
        peer_identity_hashes={args.allowed_sender_id: allowed_identity_hash},
    )
    server.install(
        allow=RNS.Destination.ALLOW_LIST,
        allowed_list=[allowed_identity_hash],
    )

    watermark_server = ReticulumAuthoritySyncWatermarkServer(
        destination=destination,
        endpoint=AuthoritySyncWatermarkEndpoint(
            receiver_id="reticulum-server",
            registry=DurableAuthoritySyncWatermarkRegistry(
                {args.allowed_sender_id: {args.allowed_sender_id}},
                database_path=args.watermark_db,
            ),
        ),
        peer_identity_hashes={args.allowed_sender_id: allowed_identity_hash},
    )
    watermark_server.install(
        allow=RNS.Destination.ALLOW_LIST,
        allowed_list=[allowed_identity_hash],
    )

    relay_server = ReticulumRelayedWatermarkServer(
        destination=destination,
        endpoint=RelayedWatermarkEndpoint(
            receiver_id="reticulum-server",
            admission=RelayedWatermarkAdmission(
                verifier=HmacAuthoritySyncWatermarkVerifier(
                    {("origin-peer", "key-1"): RELAY_ORIGIN_KEY}
                ),
                registry=AuthoritySyncWatermarkRegistry(
                    {args.allowed_sender_id: {"origin-peer"}}
                ),
            ),
        ),
        relay_identity_hashes={args.allowed_sender_id: allowed_identity_hash},
    )
    relay_server.install(
        allow=RNS.Destination.ALLOW_LIST,
        allowed_list=[allowed_identity_hash],
    )

    origin_keys = WatermarkAuthenticationKeyRegistry()
    origin_keys.register(
        WatermarkAuthenticationKeyRecord(
            issuer_id="origin-peer",
            key_id="origin-ed-key",
            valid_from="2026-09-25T17:00:00Z",
        )
    )
    relay_keys = WatermarkAuthenticationKeyRegistry()
    for relay_id in ("relay-a", "relay-b", "relay-c"):
        relay_keys.register(
            WatermarkAuthenticationKeyRecord(
                issuer_id=relay_id,
                key_id="relay-ed-key",
                valid_from="2026-09-25T17:00:00Z",
            )
        )

    chain_server = ReticulumSignedRelayChainServer(
        destination=destination,
        endpoint=Ed25519RelayChainEndpoint(
            receiver_id="reticulum-server",
            verifier=Ed25519RelayChainVerifier(
                origin_verifier=Ed25519AuthoritySyncWatermarkVerifier(
                    public_keys={
                        ("origin-peer", "origin-ed-key"): ed25519_public_raw(
                            CHAIN_ORIGIN_PRIVATE
                        )
                    },
                    key_registry=origin_keys,
                ),
                relay_public_keys={
                    ("relay-a", "relay-ed-key"): ed25519_public_raw(
                        CHAIN_RELAY_A_PRIVATE
                    ),
                    ("relay-b", "relay-ed-key"): ed25519_public_raw(
                        CHAIN_RELAY_B_PRIVATE
                    ),
                    ("relay-c", "relay-ed-key"): ed25519_public_raw(
                        CHAIN_RELAY_C_PRIVATE
                    ),
                },
                relay_key_registry=relay_keys,
                max_hops=8,
            ),
            registry=AuthoritySyncWatermarkRegistry(
                {args.allowed_sender_id: {"origin-peer"}}
            ),
        ),
        terminal_relay_identity_hashes={
            "relay-c": terminal_relay_identity_hash
        },
    )
    chain_server.install(
        allow=RNS.Destination.ALLOW_LIST,
        allowed_list=[terminal_relay_identity_hash],
    )

    Path(args.hash_file).write_text(destination.hash.hex(), encoding="utf-8")

    while True:
        destination.announce()
        time.sleep(args.announce_interval)


if __name__ == "__main__":
    main()
