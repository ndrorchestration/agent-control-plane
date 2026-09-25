"""Three-process localhost Reticulum multi-hop integration for ACP authority sync."""

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
    SnapshotSyncMessage,
    SyncDisposition,
    decode_sync_acknowledgement,
    encode_sync_message,
)
from agent_control_plane.reticulum_adapter import ReticulumAuthoritySyncTransport


APP_NAME = "ndrorchestration"
ASPECTS = ("acp", "authority_sync_live")


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def write_config(path: Path, *, transport: bool, interface_block: str) -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / "config").write_text(
        "[reticulum]\n"
        f"enable_transport = {'Yes' if transport else 'No'}\n"
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
            raise RuntimeError(
                f"Reticulum destination exited early with code {process.returncode}"
            )
        if path.exists():
            value = path.read_text(encoding="utf-8").strip()
            if value:
                return value
        time.sleep(0.1)
    raise RuntimeError("timed out waiting for destination hash")


def wait_for_path(destination_hash: bytes, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        RNS.Transport.request_path(destination_hash)
        if RNS.Transport.has_path(destination_hash):
            return
        time.sleep(0.2)
    raise RuntimeError("timed out waiting for multi-hop Reticulum path")


def wait_for_identity(destination_hash: bytes, timeout: float):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        identity = RNS.Identity.recall(destination_hash)
        if identity is not None:
            return identity
        time.sleep(0.2)
    raise RuntimeError("timed out waiting for destination identity")


def establish_identified_link(remote_destination, client_identity, timeout):
    established = threading.Event()
    link = RNS.Link(
        remote_destination,
        established_callback=lambda active_link: established.set(),
    )
    if not established.wait(timeout):
        raise RuntimeError("timed out establishing multi-hop Reticulum link")
    link.identify(client_identity)
    return link


def stop_process(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def start_destination(
    *,
    server_script: Path,
    config_dir: Path,
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
            str(config_dir),
            "--hash-file",
            str(hash_file),
            "--state-db",
            str(state_db),
            "--watermark-db",
            str(watermark_db),
            "--allowed-sender-id",
            "multihop-client",
            "--allowed-identity-hash",
            client_identity_hash.hex(),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )


def start_transport_node(
    *,
    transport_script: Path,
    config_dir: Path,
) -> subprocess.Popen:
    return subprocess.Popen(
        [
            sys.executable,
            str(transport_script),
            "--config-dir",
            str(config_dir),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--timeout", type=float, default=30.0)
    args = parser.parse_args()

    router_port = free_port()

    with tempfile.TemporaryDirectory(prefix="acp-reticulum-multihop-") as tmp:
        root = Path(tmp)
        destination_config = root / "destination"
        router_config = root / "router"
        client_config = root / "client"
        hash_file = root / "destination-hash.txt"
        state_db = root / "authority-sync.sqlite3"
        watermark_db = root / "authority-watermarks.sqlite3"

        write_config(
            destination_config,
            transport=False,
            interface_block=(
                "[[Destination TCP Client]]\n"
                "  type = TCPClientInterface\n"
                "  enabled = yes\n"
                "  target_host = 127.0.0.1\n"
                f"  target_port = {router_port}\n"
            ),
        )
        write_config(
            router_config,
            transport=True,
            interface_block=(
                "[[Router TCP Gateway]]\n"
                "  type = TCPServerInterface\n"
                "  enabled = yes\n"
                "  mode = gateway\n"
                "  recursive_prs = yes\n"
                "  listen_ip = 127.0.0.1\n"
                f"  listen_port = {router_port}\n"
            ),
        )
        write_config(
            client_config,
            transport=False,
            interface_block=(
                "[[Client TCP Interface]]\n"
                "  type = TCPClientInterface\n"
                "  enabled = yes\n"
                "  target_host = 127.0.0.1\n"
                f"  target_port = {router_port}\n"
            ),
        )

        client_identity = RNS.Identity()
        client_identity_hash = client_identity.hash
        if not isinstance(client_identity_hash, bytes) or not client_identity_hash:
            raise RuntimeError("client identity hash unavailable")

        server_script = Path(__file__).with_name("reticulum_live_server.py")
        transport_script = Path(__file__).with_name("reticulum_transport_node.py")

        router = start_transport_node(
            transport_script=transport_script,
            config_dir=router_config,
        )
        # Use the documented same-host gateway shape: one transport-enabled
        # TCP server, with both edge instances connecting as TCP clients.
        time.sleep(1.0)

        destination = start_destination(
            server_script=server_script,
            config_dir=destination_config,
            hash_file=hash_file,
            state_db=state_db,
            watermark_db=watermark_db,
            client_identity_hash=client_identity_hash,
        )
        time.sleep(1.5)

        RNS.Reticulum(configdir=str(client_config))

        try:
            destination_hex = wait_for_file(hash_file, destination, args.timeout)
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
            link = establish_identified_link(
                remote_destination,
                client_identity,
                args.timeout,
            )

            transport = ReticulumAuthoritySyncTransport(
                {"destination": link},
                peer_destination_hashes={"destination": destination_hash},
                timeout_seconds=args.timeout,
                max_response_size=65536,
            )
            snapshot = SnapshotSyncMessage(
                message_id="multihop-snapshot-1",
                sender_id="multihop-client",
                sequence=1,
                snapshot=AuthorityStateSnapshot(
                    "auth-multihop-1",
                    1,
                    "2026-09-25T19:00:00Z",
                    "multihop-client",
                ),
            )
            acknowledgement = decode_sync_acknowledgement(
                transport.exchange(
                    "destination",
                    encode_sync_message(snapshot),
                )
            )
            if acknowledgement.disposition is not SyncDisposition.APPLIED:
                raise RuntimeError(
                    f"multi-hop snapshot not applied: {acknowledgement}"
                )

            duplicate = decode_sync_acknowledgement(
                transport.exchange(
                    "destination",
                    encode_sync_message(snapshot),
                )
            )
            if duplicate.disposition is not SyncDisposition.DUPLICATE:
                raise RuntimeError(
                    f"multi-hop duplicate not detected: {duplicate}"
                )

            link.teardown()

            print("RETICULUM_MULTIHOP_INTEGRATION=PASS")
            print("TOPOLOGY=client->transport-node->destination")
            print(f"DESTINATION={destination_hex}")
            print(f"SNAPSHOT_ACK={acknowledgement.disposition.value}")
            print(f"DUPLICATE_ACK={duplicate.disposition.value}")
            print(f"CLIENT_IDENTITY_HASH={client_identity_hash.hex()}")
        except Exception:
            for name, process in (
                ("ROUTER", router),
                ("DESTINATION", destination),
            ):
                if process.poll() is not None and process.stdout is not None:
                    output = process.stdout.read()
                    if output:
                        print(f"{name}_OUTPUT_BEGIN")
                        print(output)
                        print(f"{name}_OUTPUT_END")
            raise
        finally:
            stop_process(router)
            stop_process(destination)


if __name__ == "__main__":
    main()
