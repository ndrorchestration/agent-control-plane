"""Two-process localhost Reticulum live integration for ACP authority sync."""

import argparse
import socket
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

import RNS

from agent_control_plane.authority_state import AuthorityStateSnapshot
from agent_control_plane.authority_sync import (
    RevocationSyncMessage,
    SnapshotSyncMessage,
    SyncDisposition,
    decode_sync_acknowledgement,
    encode_sync_message,
)
from agent_control_plane.authority_sync_watermark import (
    AuthoritySyncWatermark,
    WatermarkDisposition,
    decode_authority_sync_watermark_acknowledgement,
    encode_authority_sync_watermark,
)
from agent_control_plane.authority_sync_watermark_auth import (
    authenticate_authority_sync_watermark,
    encode_authenticated_authority_sync_watermark,
)
from agent_control_plane.authority_sync_watermark_relay import (
    decode_relayed_watermark_acknowledgement,
    encode_relayed_authenticated_watermark,
    wrap_authenticated_watermark_for_relay,
)
from agent_control_plane.reticulum_adapter import (
    ReticulumAuthoritySyncTransport,
    ReticulumAuthoritySyncWatermarkTransport,
    ReticulumRelayedWatermarkTransport,
)
from agent_control_plane.revocation import RevocationRecord


APP_NAME = "ndrorchestration"
ASPECTS = ("acp", "authority_sync_live")
RELAY_ORIGIN_KEY = bytes.fromhex("11" * 32)


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def write_config(path: Path, interface_block: str) -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / "config").write_text(
        "[reticulum]\n"
        "enable_transport = No\n"
        "share_instance = No\n\n"
        "[logging]\n"
        "loglevel = 2\n\n"
        "[interfaces]\n"
        + interface_block,
        encoding="utf-8",
    )


def wait_for_file(path: Path, process: subprocess.Popen, timeout: float) -> str:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"Reticulum server exited early with code {process.returncode}")
        if path.exists() and path.read_text(encoding="utf-8").strip():
            return path.read_text(encoding="utf-8").strip()
        time.sleep(0.1)
    raise RuntimeError("timed out waiting for Reticulum server destination hash")


def wait_for_path(destination_hash: bytes, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    RNS.Transport.request_path(destination_hash)
    while time.monotonic() < deadline:
        if RNS.Transport.has_path(destination_hash):
            return
        time.sleep(0.1)
    raise RuntimeError("timed out waiting for Reticulum path")


def wait_for_identity(destination_hash: bytes, timeout: float):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        identity = RNS.Identity.recall(destination_hash)
        if identity is not None:
            return identity
        time.sleep(0.1)
    raise RuntimeError("timed out waiting for announced Reticulum identity")


def establish_identified_link(remote_destination, client_identity, timeout):
    established = threading.Event()
    link = RNS.Link(
        remote_destination,
        established_callback=lambda active_link: established.set(),
    )
    if not established.wait(timeout):
        raise RuntimeError("timed out establishing Reticulum link")
    link.identify(client_identity)
    return link


def start_server(
    server_script: Path,
    server_config: Path,
    hash_file: Path,
    state_db: Path,
    watermark_db: Path,
    client_identity_hash: bytes,
) -> subprocess.Popen:
    if hash_file.exists():
        hash_file.unlink()
    return subprocess.Popen(
        [
            sys.executable,
            str(server_script),
            "--config-dir",
            str(server_config),
            "--hash-file",
            str(hash_file),
            "--state-db",
            str(state_db),
            "--watermark-db",
            str(watermark_db),
            "--allowed-sender-id",
            "reticulum-client",
            "--allowed-identity-hash",
            client_identity_hash.hex(),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )


def stop_server(server: subprocess.Popen) -> None:
    if server.poll() is not None:
        return
    server.terminate()
    try:
        server.wait(timeout=5)
    except subprocess.TimeoutExpired:
        server.kill()
        server.wait(timeout=5)


def connect_transport(
    *,
    hash_file: Path,
    server: subprocess.Popen,
    client_identity,
    timeout: float,
):
    destination_hex = wait_for_file(hash_file, server, timeout)
    destination_hash = bytes.fromhex(destination_hex)
    wait_for_path(destination_hash, timeout)
    identity = wait_for_identity(destination_hash, timeout)
    remote_destination = RNS.Destination(
        identity,
        RNS.Destination.OUT,
        RNS.Destination.SINGLE,
        APP_NAME,
        *ASPECTS,
    )
    link = establish_identified_link(remote_destination, client_identity, timeout)
    transport = ReticulumAuthoritySyncTransport(
        {"server": link},
        peer_destination_hashes={"server": destination_hash},
        timeout_seconds=timeout,
        max_response_size=65536,
    )
    watermark_transport = ReticulumAuthoritySyncWatermarkTransport(
        {"server": link},
        peer_destination_hashes={"server": destination_hash},
        timeout_seconds=timeout,
        max_response_size=65536,
    )
    relay_transport = ReticulumRelayedWatermarkTransport(
        {"server": link},
        peer_destination_hashes={"server": destination_hash},
        timeout_seconds=timeout,
        max_response_size=65536,
    )
    return destination_hex, link, transport, watermark_transport, relay_transport


def exchange(transport, message):
    return decode_sync_acknowledgement(
        transport.exchange("server", encode_sync_message(message))
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--timeout", type=float, default=20.0)
    args = parser.parse_args()

    port = free_port()
    with tempfile.TemporaryDirectory(prefix="acp-reticulum-live-") as tmp:
        root = Path(tmp)
        server_config = root / "server"
        client_config = root / "client"
        hash_file = root / "server-destination.txt"
        state_db = root / "authority-sync.sqlite3"
        watermark_db = root / "authority-watermarks.sqlite3"

        write_config(
            server_config,
            "[[ACP TCP Server]]\n"
            "  type = TCPServerInterface\n"
            "  enabled = yes\n"
            "  listen_ip = 127.0.0.1\n"
            f"  listen_port = {port}\n",
        )
        write_config(
            client_config,
            "[[ACP TCP Client]]\n"
            "  type = TCPClientInterface\n"
            "  enabled = yes\n"
            "  target_host = 127.0.0.1\n"
            f"  target_port = {port}\n",
        )

        server_script = Path(__file__).with_name("reticulum_live_server.py")
        RNS.Reticulum(configdir=str(client_config))
        client_identity = RNS.Identity()
        client_identity_hash = client_identity.hash
        if not isinstance(client_identity_hash, bytes) or not client_identity_hash:
            raise RuntimeError("Reticulum client identity hash unavailable")

        server = start_server(
            server_script,
            server_config,
            hash_file,
            state_db,
            watermark_db,
            client_identity_hash,
        )

        try:
            first_destination_hex, link, transport, watermark_transport, relay_transport = connect_transport(
                hash_file=hash_file,
                server=server,
                client_identity=client_identity,
                timeout=args.timeout,
            )

            snapshot = SnapshotSyncMessage(
                message_id="live-snapshot-1",
                sender_id="reticulum-client",
                sequence=1,
                snapshot=AuthorityStateSnapshot(
                    "auth-live-1",
                    1,
                    "2026-09-25T15:00:00Z",
                    "reticulum-client",
                ),
            )
            snapshot_ack = exchange(transport, snapshot)
            if snapshot_ack.disposition is not SyncDisposition.APPLIED:
                raise RuntimeError(f"snapshot not applied: {snapshot_ack}")

            same_link_duplicate_ack = exchange(transport, snapshot)
            if same_link_duplicate_ack.disposition is not SyncDisposition.DUPLICATE:
                raise RuntimeError(
                    f"same-link duplicate not detected: {same_link_duplicate_ack}"
                )

            revocation = RevocationSyncMessage(
                message_id="live-revocation-1",
                sender_id="reticulum-client",
                sequence=2,
                revocation=RevocationRecord(
                    "auth-live-1",
                    "2026-09-25T15:01:00Z",
                    "live_test_revocation",
                ),
            )
            revocation_ack = exchange(transport, revocation)
            if revocation_ack.disposition is not SyncDisposition.APPLIED:
                raise RuntimeError(f"revocation not applied: {revocation_ack}")

            watermark = AuthoritySyncWatermark(
                watermark_id="live-watermark-1",
                issuer_id="reticulum-client",
                target_sender_id="reticulum-client",
                min_sequence=2,
                issued_at="2026-09-25T15:01:30Z",
            )
            watermark_ack = decode_authority_sync_watermark_acknowledgement(
                watermark_transport.exchange(
                    "server",
                    encode_authority_sync_watermark(watermark),
                )
            )
            if watermark_ack.disposition is not WatermarkDisposition.APPLIED:
                raise RuntimeError(f"watermark not applied: {watermark_ack}")

            watermark_duplicate_ack = decode_authority_sync_watermark_acknowledgement(
                watermark_transport.exchange(
                    "server",
                    encode_authority_sync_watermark(watermark),
                )
            )
            if watermark_duplicate_ack.disposition is not WatermarkDisposition.DUPLICATE:
                raise RuntimeError(
                    f"watermark duplicate not detected: {watermark_duplicate_ack}"
                )


            relay_origin = AuthoritySyncWatermark(
                watermark_id="origin-peer:reticulum-client:2",
                issuer_id="origin-peer",
                target_sender_id="reticulum-client",
                min_sequence=2,
                issued_at="2026-09-25T15:01:45Z",
            )
            authenticated_origin = authenticate_authority_sync_watermark(
                relay_origin,
                key_id="key-1",
                key=RELAY_ORIGIN_KEY,
            )
            relayed = wrap_authenticated_watermark_for_relay(
                encode_authenticated_authority_sync_watermark(authenticated_origin),
                relay_id="reticulum-client",
                relayed_at="2026-09-25T15:01:50Z",
            )
            relay_ack = decode_relayed_watermark_acknowledgement(
                relay_transport.exchange(
                    "server",
                    encode_relayed_authenticated_watermark(relayed),
                )
            )
            if relay_ack.disposition is not WatermarkDisposition.APPLIED:
                raise RuntimeError(f"relayed watermark not applied: {relay_ack}")

            relay_duplicate_ack = decode_relayed_watermark_acknowledgement(
                relay_transport.exchange(
                    "server",
                    encode_relayed_authenticated_watermark(relayed),
                )
            )
            if relay_duplicate_ack.disposition is not WatermarkDisposition.DUPLICATE:
                raise RuntimeError(
                    f"relayed watermark duplicate not detected: {relay_duplicate_ack}"
                )

            link.teardown()
            stop_server(server)
            time.sleep(1.0)

            server = start_server(
                server_script,
                server_config,
                hash_file,
                state_db,
                watermark_db,
                client_identity_hash,
            )
            restart_destination_hex, restart_link, restart_transport, restart_watermark_transport, _ = connect_transport(
                hash_file=hash_file,
                server=server,
                client_identity=client_identity,
                timeout=args.timeout,
            )

            restart_snapshot_duplicate_ack = exchange(restart_transport, snapshot)
            if restart_snapshot_duplicate_ack.disposition is not SyncDisposition.DUPLICATE:
                raise RuntimeError(
                    "snapshot duplicate not preserved across server process restart: "
                    f"{restart_snapshot_duplicate_ack}"
                )

            restart_revocation_duplicate_ack = exchange(restart_transport, revocation)
            if restart_revocation_duplicate_ack.disposition is not SyncDisposition.DUPLICATE:
                raise RuntimeError(
                    "revocation duplicate not preserved across server process restart: "
                    f"{restart_revocation_duplicate_ack}"
                )

            restart_watermark_duplicate_ack = decode_authority_sync_watermark_acknowledgement(
                restart_watermark_transport.exchange(
                    "server",
                    encode_authority_sync_watermark(watermark),
                )
            )
            if restart_watermark_duplicate_ack.disposition is not WatermarkDisposition.DUPLICATE:
                raise RuntimeError(
                    "watermark duplicate not preserved across server process restart: "
                    f"{restart_watermark_duplicate_ack}"
                )

            regression = SnapshotSyncMessage(
                message_id="live-regression-after-restart",
                sender_id="reticulum-client",
                sequence=1,
                snapshot=AuthorityStateSnapshot(
                    "auth-live-1",
                    2,
                    "2026-09-25T15:00:30Z",
                    "reticulum-client",
                ),
            )
            regression_ack = exchange(restart_transport, regression)
            if regression_ack.disposition is not SyncDisposition.REJECTED:
                raise RuntimeError(
                    f"sequence regression not rejected after restart: {regression_ack}"
                )
            if regression_ack.reason_code != "replay_or_sequence_regression":
                raise RuntimeError(
                    f"unexpected regression reason: {regression_ack.reason_code}"
                )

            conflicting_revocation = RevocationSyncMessage(
                message_id="live-revocation-conflict",
                sender_id="reticulum-client",
                sequence=3,
                revocation=RevocationRecord(
                    "auth-live-1",
                    "2026-09-25T15:02:00Z",
                    "different_reason",
                ),
            )
            conflict_ack = exchange(restart_transport, conflicting_revocation)
            if conflict_ack.disposition is not SyncDisposition.REJECTED:
                raise RuntimeError(
                    f"recovered revocation conflict not rejected: {conflict_ack}"
                )
            if "different record" not in conflict_ack.reason_code:
                raise RuntimeError(
                    f"unexpected recovered revocation reason: {conflict_ack.reason_code}"
                )

            newer_snapshot = SnapshotSyncMessage(
                message_id="live-snapshot-2",
                sender_id="reticulum-client",
                sequence=3,
                snapshot=AuthorityStateSnapshot(
                    "auth-live-1",
                    2,
                    "2026-09-25T15:03:00Z",
                    "reticulum-client",
                ),
            )
            newer_snapshot_ack = exchange(restart_transport, newer_snapshot)
            if newer_snapshot_ack.disposition is not SyncDisposition.APPLIED:
                raise RuntimeError(
                    f"new sequence not applied after restart: {newer_snapshot_ack}"
                )

            restart_link.teardown()

            print("RETICULUM_LIVE_INTEGRATION=PASS")
            print("PROCESS_RESTART_RECOVERY=PASS")
            print(f"FIRST_DESTINATION={first_destination_hex}")
            print(f"RESTART_DESTINATION={restart_destination_hex}")
            print(f"SNAPSHOT_ACK={snapshot_ack.disposition.value}")
            print(f"SAME_LINK_DUPLICATE_ACK={same_link_duplicate_ack.disposition.value}")
            print(f"REVOCATION_ACK={revocation_ack.disposition.value}")
            print(f"WATERMARK_ACK={watermark_ack.disposition.value}")
            print(f"WATERMARK_DUPLICATE_ACK={watermark_duplicate_ack.disposition.value}")
            print(f"RELAY_ACK={relay_ack.disposition.value}")
            print(f"RELAY_DUPLICATE_ACK={relay_duplicate_ack.disposition.value}")
            print(
                "RESTART_SNAPSHOT_DUPLICATE_ACK="
                f"{restart_snapshot_duplicate_ack.disposition.value}"
            )
            print(
                "RESTART_REVOCATION_DUPLICATE_ACK="
                f"{restart_revocation_duplicate_ack.disposition.value}"
            )
            print(
                "RESTART_WATERMARK_DUPLICATE_ACK="
                f"{restart_watermark_duplicate_ack.disposition.value}"
            )
            print(
                f"RESTART_REGRESSION_ACK={regression_ack.disposition.value}:"
                f"{regression_ack.reason_code}"
            )
            print(
                f"RESTART_REVOCATION_CONFLICT_ACK={conflict_ack.disposition.value}:"
                f"{conflict_ack.reason_code}"
            )
            print(f"RESTART_NEW_SEQUENCE_ACK={newer_snapshot_ack.disposition.value}")
            print(f"CLIENT_IDENTITY_HASH={client_identity_hash.hex()}")
        except Exception:
            if server.stdout is not None:
                output = server.stdout.read() if server.poll() is not None else ""
                if output:
                    print("SERVER_OUTPUT_BEGIN")
                    print(output)
                    print("SERVER_OUTPUT_END")
            raise
        finally:
            stop_server(server)


if __name__ == "__main__":
    main()
