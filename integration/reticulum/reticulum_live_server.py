"""Local Reticulum server process for ACP live integration testing."""

import argparse
from pathlib import Path
import time

import RNS

from agent_control_plane.authority_sync_persistence import DurableAuthoritySyncReconciler
from agent_control_plane.authority_sync_watermark import AuthoritySyncWatermarkRegistry
from agent_control_plane.authority_sync_watermark_auth import HmacAuthoritySyncWatermarkVerifier
from agent_control_plane.authority_sync_watermark_persistence import DurableAuthoritySyncWatermarkRegistry
from agent_control_plane.authority_sync_watermark_relay import (
    RelayedWatermarkAdmission,
    RelayedWatermarkEndpoint,
)
from agent_control_plane.reticulum_adapter import (
    ReticulumAuthoritySyncServer,
    ReticulumAuthoritySyncWatermarkServer,
    ReticulumRelayedWatermarkServer,
)
from agent_control_plane.sync_transport import AuthoritySyncEndpoint
from agent_control_plane.watermark_transport import AuthoritySyncWatermarkEndpoint


APP_NAME = "ndrorchestration"
ASPECTS = ("acp", "authority_sync_live")
RELAY_ORIGIN_KEY = bytes.fromhex("11" * 32)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config-dir", required=True)
    parser.add_argument("--hash-file", required=True)
    parser.add_argument("--allowed-sender-id", required=True)
    parser.add_argument("--allowed-identity-hash", required=True)
    parser.add_argument("--state-db", required=True)
    parser.add_argument("--watermark-db", required=True)
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

    endpoint = AuthoritySyncEndpoint(
        DurableAuthoritySyncReconciler(
            receiver_id="reticulum-server",
            database_path=args.state_db,
        )
    )
    allowed_identity_hash = bytes.fromhex(args.allowed_identity_hash)
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

    Path(args.hash_file).write_text(destination.hash.hex(), encoding="utf-8")

    while True:
        destination.announce()
        time.sleep(1.0)


if __name__ == "__main__":
    main()
