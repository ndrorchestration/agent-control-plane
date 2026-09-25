"""Live Reticulum application relay stage for autonomous signed-chain forwarding."""

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
    Ed25519ForwardingRelayStageEndpoint,
    Ed25519RelayChainAppender,
    Ed25519RelayChainVerifier,
)
from agent_control_plane.reticulum_adapter import (
    ReticulumReconnectingRelayStageTransport,
    ReticulumReconnectingSignedRelayChainTransport,
    ReticulumRelayStageServer,
)


APP_NAME = "ndrorchestration"
RELAY_ASPECTS = ("acp", "relay_stage_live")
FINAL_ASPECTS = ("acp", "authority_sync_live")
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


def wait_for_path(destination_hash: bytes, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    RNS.Transport.request_path(destination_hash)
    while time.monotonic() < deadline:
        if RNS.Transport.has_path(destination_hash):
            return
        time.sleep(0.1)
    raise RuntimeError("timed out waiting for downstream Reticulum path")


def wait_for_identity(destination_hash: bytes, timeout: float):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        identity = RNS.Identity.recall(destination_hash)
        if identity is not None:
            return identity
        time.sleep(0.1)
    raise RuntimeError("timed out waiting for downstream Reticulum identity")


def establish_identified_link(remote_destination, identity, timeout: float):
    established = threading.Event()
    link = RNS.Link(
        remote_destination,
        established_callback=lambda active_link: established.set(),
    )
    if not established.wait(timeout):
        raise RuntimeError("timed out establishing downstream Reticulum link")
    link.identify(identity)
    return link


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config-dir", required=True)
    parser.add_argument("--identity-file", required=True)
    parser.add_argument("--destination-hash-file", required=True)
    parser.add_argument("--ready-file", required=True)
    parser.add_argument("--relay-id", required=True, choices=sorted(RELAY_PRIVATE))
    parser.add_argument("--upstream-id", required=True)
    parser.add_argument("--upstream-identity-hash", required=True)
    parser.add_argument("--next-destination-hash", required=True)
    parser.add_argument("--next-kind", required=True, choices=("relay", "final"))
    parser.add_argument("--next-receiver-id", required=True)
    parser.add_argument("--relayed-at", required=True)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--announce-interval", type=float, default=60.0)
    args = parser.parse_args()

    if args.timeout <= 0 or args.announce_interval <= 0:
        raise RuntimeError("timeout and announce interval must be > 0")

    RNS.Reticulum(configdir=args.config_dir)
    identity = RNS.Identity.from_file(args.identity_file)
    if identity is None:
        raise RuntimeError("could not load Reticulum relay identity")

    inbound = RNS.Destination(
        identity,
        RNS.Destination.IN,
        RNS.Destination.SINGLE,
        APP_NAME,
        *RELAY_ASPECTS,
    )
    inbound.accepts_links(True)
    Path(args.destination_hash_file).write_text(
        inbound.hash.hex(),
        encoding="utf-8",
    )
    inbound.announce()

    downstream_hash = bytes.fromhex(args.next_destination_hash)
    downstream_aspects = (
        RELAY_ASPECTS if args.next_kind == "relay" else FINAL_ASPECTS
    )
    reconnect_timeout = min(args.timeout, 5.0)

    def connect_downstream():
        wait_for_path(downstream_hash, reconnect_timeout)
        downstream_identity = wait_for_identity(
            downstream_hash,
            reconnect_timeout,
        )
        downstream_destination = RNS.Destination(
            downstream_identity,
            RNS.Destination.OUT,
            RNS.Destination.SINGLE,
            APP_NAME,
            *downstream_aspects,
        )
        return establish_identified_link(
            downstream_destination,
            identity,
            reconnect_timeout,
        )

    link = connect_downstream()

    reconnect_kwargs = dict(
        link_factory=lambda peer_id: connect_downstream(),
        peer_destination_hashes={"next": downstream_hash},
        attempts=2,
        retry_backoff_seconds=0.25,
        timeout_seconds=reconnect_timeout,
        max_response_size=65536,
    )
    if args.next_kind == "relay":
        transport = ReticulumReconnectingRelayStageTransport(
            {"next": link},
            **reconnect_kwargs,
        )
    else:
        transport = ReticulumReconnectingSignedRelayChainTransport(
            {"next": link},
            **reconnect_kwargs,
        )

    appender = Ed25519RelayChainAppender(
        relay_id=args.relay_id,
        key_id="relay-ed-key",
        private_key_raw=RELAY_PRIVATE[args.relay_id],
        next_receiver_id=args.next_receiver_id,
        origin_verifier=origin_verifier(),
        prefix_verifier=prefix_verifier(),
    )
    endpoint = Ed25519ForwardingRelayStageEndpoint(
        appender=appender,
        relayed_at_provider=lambda: args.relayed_at,
        downstream_exchange=lambda payload: transport.exchange("next", payload),
    )
    upstream_hash = bytes.fromhex(args.upstream_identity_hash)
    server = ReticulumRelayStageServer(
        destination=inbound,
        endpoint=endpoint,
        upstream_identity_hashes={args.upstream_id: upstream_hash},
    )
    server.install(
        allow=RNS.Destination.ALLOW_LIST,
        allowed_list=[upstream_hash],
    )
    inbound.announce()
    Path(args.ready_file).write_text(
        args.relay_id,
        encoding="utf-8",
    )

    print(
        f"RELAY_STAGE_READY={args.relay_id}:"
        f"{identity.hash.hex()}:{inbound.hash.hex()}",
        flush=True,
    )

    while True:
        time.sleep(args.announce_interval)
        inbound.announce()


if __name__ == "__main__":
    main()
