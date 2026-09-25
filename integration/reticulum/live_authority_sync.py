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
from agent_control_plane.reticulum_adapter import ReticulumAuthoritySyncTransport
from agent_control_plane.revocation import RevocationRecord


APP_NAME = "ndrorchestration"
ASPECTS = ("acp", "authority_sync_live")


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

        server = subprocess.Popen(
            [
                sys.executable,
                str(server_script),
                "--config-dir",
                str(server_config),
                "--hash-file",
                str(hash_file),
                "--allowed-sender-id",
                "reticulum-client",
                "--allowed-identity-hash",
                client_identity_hash.hex(),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        try:
            destination_hex = wait_for_file(hash_file, server, args.timeout)
            destination_hash = bytes.fromhex(destination_hex)
            wait_for_path(destination_hash, args.timeout)
            identity = wait_for_identity(destination_hash, args.timeout)

            remote_destination = RNS.Destination(
                identity,
                RNS.Destination.OUT,
                RNS.Destination.SINGLE,
                APP_NAME,
                *ASPECTS,
            )
            established = threading.Event()
            link = RNS.Link(remote_destination, established_callback=lambda active_link: established.set())
            if not established.wait(args.timeout):
                raise RuntimeError("timed out establishing Reticulum link")
            link.identify(client_identity)

            transport = ReticulumAuthoritySyncTransport(
                {"server": link},
                peer_destination_hashes={"server": destination_hash},
                timeout_seconds=args.timeout,
                max_response_size=65536,
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
            snapshot_ack = decode_sync_acknowledgement(
                transport.exchange("server", encode_sync_message(snapshot))
            )
            if snapshot_ack.disposition is not SyncDisposition.APPLIED:
                raise RuntimeError(f"snapshot not applied: {snapshot_ack}")

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
            revocation_ack = decode_sync_acknowledgement(
                transport.exchange("server", encode_sync_message(revocation))
            )
            if revocation_ack.disposition is not SyncDisposition.APPLIED:
                raise RuntimeError(f"revocation not applied: {revocation_ack}")

            link.teardown()
            print("RETICULUM_LIVE_INTEGRATION=PASS")
            print(f"DESTINATION={destination_hex}")
            print(f"SNAPSHOT_ACK={snapshot_ack.disposition.value}")
            print(f"REVOCATION_ACK={revocation_ack.disposition.value}")
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
            server.terminate()
            try:
                server.wait(timeout=5)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait(timeout=5)


if __name__ == "__main__":
    main()
