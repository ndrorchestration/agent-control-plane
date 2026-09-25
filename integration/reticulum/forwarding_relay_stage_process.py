"""One autonomous ACP signed relay stage for live Reticulum integration."""

import argparse
from pathlib import Path
import threading
import time

import RNS
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
    Ed25519RelayAppenderEndpoint,
    Ed25519RelayChainAppender,
    Ed25519RelayChainVerifier,
)
from agent_control_plane.reticulum_adapter import (
    ReticulumForwardingRelayStageServer,
    ReticulumRelayStageTransport,
    ReticulumSignedRelayChainTransport,
)


APP_NAME = "ndrorchestration"
RELAY_ASPECTS = ("acp", "relay_stage_live")
SINK_ASPECTS = ("acp", "relay_chain_sink_live")
ORIGIN_PRIVATE = bytes(range(32))
RELAY_PRIVATE = {
    "relay-a": b"a" * 32,
    "relay-b": b"b" * 32,
    "relay-c": b"c" * 32,
}
RELAY_TIME = {
    "relay-a": "2026-09-25T19:10:10Z",
    "relay-b": "2026-09-25T19:10:20Z",
    "relay-c": "2026-09-25T19:10:30Z",
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


def wait_for_path(destination_hash: bytes, timeout: float) -> None:
    RNS.Transport.request_path(destination_hash)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if RNS.Transport.has_path(destination_hash):
            return
        time.sleep(0.2)
    raise RuntimeError("relay timed out waiting for downstream path")


def wait_for_identity(destination_hash: bytes, timeout: float):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        identity = RNS.Identity.recall(destination_hash)
        if identity is not None:
            return identity
        time.sleep(0.2)
    raise RuntimeError("relay timed out waiting for downstream identity")


def establish_link(remote_destination, identity, timeout: float):
    established = threading.Event()
    link = RNS.Link(
        remote_destination,
        established_callback=lambda active_link: established.set(),
    )
    if not established.wait(timeout):
        raise RuntimeError("relay timed out establishing downstream link")
    link.identify(identity)
    return link


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config-dir", required=True)
    parser.add_argument("--relay-id", required=True, choices=sorted(RELAY_PRIVATE))
    parser.add_argument("--next-receiver-id", required=True)
    parser.add_argument("--next-destination-hash", required=True)
    parser.add_argument("--next-kind", choices=("relay", "sink"), required=True)
    parser.add_argument("--upstream-id", required=True)
    parser.add_argument("--upstream-identity-hash", required=True)
    parser.add_argument("--destination-hash-file", required=True)
    parser.add_argument("--identity-hash-file", required=True)
    parser.add_argument("--timeout", type=float, default=30.0)
    args = parser.parse_args()

    RNS.Reticulum(configdir=args.config_dir)
    identity = RNS.Identity()

    next_hash = bytes.fromhex(args.next_destination_hash)
    wait_for_path(next_hash, args.timeout)
    next_identity = wait_for_identity(next_hash, args.timeout)
    next_aspects = RELAY_ASPECTS if args.next_kind == "relay" else SINK_ASPECTS
    remote_destination = RNS.Destination(
        next_identity,
        RNS.Destination.OUT,
        RNS.Destination.SINGLE,
        APP_NAME,
        *next_aspects,
    )
    downstream_link = establish_link(
        remote_destination,
        identity,
        args.timeout,
    )

    if args.next_kind == "relay":
        downstream_transport = ReticulumRelayStageTransport(
            {"next": downstream_link},
            peer_destination_hashes={"next": next_hash},
            timeout_seconds=args.timeout,
            max_response_size=65536,
        )
    else:
        downstream_transport = ReticulumSignedRelayChainTransport(
            {"next": downstream_link},
            peer_destination_hashes={"next": next_hash},
            timeout_seconds=args.timeout,
            max_response_size=65536,
        )

    origin_registry = WatermarkAuthenticationKeyRegistry()
    origin_registry.register(key_record("origin-peer", "origin-ed-key"))
    origin_verifier = Ed25519AuthoritySyncWatermarkVerifier(
        public_keys={
            ("origin-peer", "origin-ed-key"): public_raw(ORIGIN_PRIVATE)
        },
        key_registry=origin_registry,
    )

    relay_registry = WatermarkAuthenticationKeyRegistry()
    for relay_id in RELAY_PRIVATE:
        relay_registry.register(key_record(relay_id, "relay-ed-key"))
    prefix_verifier = Ed25519RelayChainVerifier(
        origin_verifier=origin_verifier,
        relay_public_keys={
            (relay_id, "relay-ed-key"): public_raw(private_raw)
            for relay_id, private_raw in RELAY_PRIVATE.items()
        },
        relay_key_registry=relay_registry,
        max_hops=8,
    )

    endpoint = Ed25519RelayAppenderEndpoint(
        appender=Ed25519RelayChainAppender(
            relay_id=args.relay_id,
            key_id="relay-ed-key",
            private_key_raw=RELAY_PRIVATE[args.relay_id],
            next_receiver_id=args.next_receiver_id,
            origin_verifier=origin_verifier,
            prefix_verifier=prefix_verifier,
        ),
        relayed_at_provider=lambda: RELAY_TIME[args.relay_id],
    )

    destination = RNS.Destination(
        identity,
        RNS.Destination.IN,
        RNS.Destination.SINGLE,
        APP_NAME,
        *RELAY_ASPECTS,
    )
    destination.accepts_links(True)

    upstream_hash = bytes.fromhex(args.upstream_identity_hash)
    server = ReticulumForwardingRelayStageServer(
        destination=destination,
        endpoint=endpoint,
        downstream_transport=downstream_transport,
        downstream_peer_id="next",
        upstream_identity_hashes={args.upstream_id: upstream_hash},
    )
    server.install(
        allow=RNS.Destination.ALLOW_LIST,
        allowed_list=[upstream_hash],
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
