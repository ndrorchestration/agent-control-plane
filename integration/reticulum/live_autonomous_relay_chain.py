"""Autonomous multi-stage Reticulum forwarding for signed ACP relay chains."""

import argparse
import socket
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

import RNS

from agent_control_plane.authority_sync_watermark import (
    AuthoritySyncWatermark,
    WatermarkDisposition,
    decode_authority_sync_watermark_acknowledgement,
)
from agent_control_plane.authority_sync_watermark_ed25519 import (
    encode_ed25519_authority_sync_watermark,
    sign_authority_sync_watermark_ed25519,
)
from agent_control_plane.authority_sync_watermark_relay_chain import (
    encode_ed25519_relay_chain,
    new_ed25519_relay_chain,
)
from agent_control_plane.reticulum_adapter import (
    ReticulumAdapterError,
    ReticulumRelayStageTransport,
)


APP_NAME = "ndrorchestration"
RELAY_ASPECTS = ("acp", "relay_stage_live")
ORIGIN_PRIVATE = bytes(range(32))


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def write_config(
    path: Path,
    *,
    transport: bool,
    instance_name: str,
    interface_block: str,
) -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / "config").write_text(
        "[reticulum]\n"
        f"enable_transport = {'Yes' if transport else 'No'}\n"
        "share_instance = Yes\n"
        f"instance_name = {instance_name}\n\n"
        "[logging]\n"
        "loglevel = 4\n\n"
        "[interfaces]\n"
        + interface_block,
        encoding="utf-8",
    )


def wait_for_file(path: Path, process: subprocess.Popen, timeout: float) -> str:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            output = ""
            if process.stdout is not None:
                output = process.stdout.read()
            raise RuntimeError(
                f"process exited early with code {process.returncode}: {output}"
            )
        if path.exists():
            value = path.read_text(encoding="utf-8").strip()
            if value:
                return value
        time.sleep(0.1)
    raise RuntimeError(f"timed out waiting for {path.name}")


def wait_for_path(destination_hash: bytes, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    RNS.Transport.request_path(destination_hash)
    while time.monotonic() < deadline:
        if RNS.Transport.has_path(destination_hash):
            return
        time.sleep(0.1)
    raise RuntimeError("timed out waiting for relay-a path")


def wait_for_identity(destination_hash: bytes, timeout: float):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        identity = RNS.Identity.recall(destination_hash)
        if identity is not None:
            return identity
        time.sleep(0.1)
    raise RuntimeError("timed out waiting for relay-a identity")


def establish_identified_link(remote_destination, identity, timeout: float):
    established = threading.Event()
    link = RNS.Link(
        remote_destination,
        established_callback=lambda active_link: established.set(),
    )
    if not established.wait(timeout):
        raise RuntimeError("timed out establishing link to relay-a")
    link.identify(identity)
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


def start_process(args: list[str]) -> subprocess.Popen:
    return subprocess.Popen(
        [sys.executable, *args],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )


def start_relay(
    *,
    script: Path,
    config_dir: Path,
    identity_file: Path,
    destination_hash_file: Path,
    ready_file: Path,
    queue_db: Path,
    relay_id: str,
    upstream_id: str,
    upstream_identity_hash: bytes,
    next_destination_hash: str,
    next_kind: str,
    next_receiver_id: str,
    relayed_at: str,
    timeout: float,
) -> subprocess.Popen:
    for path in (destination_hash_file, ready_file):
        if path.exists():
            path.unlink()
    return start_process(
        [
            str(script),
            "--config-dir",
            str(config_dir),
            "--identity-file",
            str(identity_file),
            "--destination-hash-file",
            str(destination_hash_file),
            "--ready-file",
            str(ready_file),
            "--queue-db",
            str(queue_db),
            "--relay-id",
            relay_id,
            "--upstream-id",
            upstream_id,
            "--upstream-identity-hash",
            upstream_identity_hash.hex(),
            "--next-destination-hash",
            next_destination_hash,
            "--next-kind",
            next_kind,
            "--next-receiver-id",
            next_receiver_id,
            "--relayed-at",
            relayed_at,
            "--timeout",
            str(timeout),
            "--announce-interval",
            "60",
        ]
    )


def origin_chain_payload(
    *,
    watermark_id: str,
    sequence: int,
    issued_at: str,
) -> bytes:
    watermark = AuthoritySyncWatermark(
        watermark_id=watermark_id,
        issuer_id="origin-peer",
        target_sender_id="origin-peer",
        min_sequence=sequence,
        issued_at=issued_at,
    )
    envelope = sign_authority_sync_watermark_ed25519(
        watermark,
        key_id="origin-ed-key",
        private_key_raw=ORIGIN_PRIVATE,
    )
    return encode_ed25519_relay_chain(
        new_ed25519_relay_chain(
            encode_ed25519_authority_sync_watermark(envelope)
        )
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--timeout", type=float, default=35.0)
    args = parser.parse_args()

    router_port = free_port()

    with tempfile.TemporaryDirectory(prefix="acp-reticulum-autonomous-") as tmp:
        root = Path(tmp)

        router_config = root / "router"
        destination_config = root / "destination"
        origin_config = root / "origin"
        relay_configs = {
            relay_id: root / relay_id
            for relay_id in ("relay-a", "relay-b", "relay-c")
        }

        gateway_interface = (
            "[[Router TCP Gateway]]\n"
            "  type = TCPServerInterface\n"
            "  enabled = yes\n"
            "  mode = gateway\n"
            "  recursive_prs = yes\n"
            "  listen_ip = 127.0.0.1\n"
            f"  listen_port = {router_port}\n"
        )
        leaf_interface = (
            "[[Gateway Client]]\n"
            "  type = TCPClientInterface\n"
            "  enabled = yes\n"
            "  target_host = 127.0.0.1\n"
            f"  target_port = {router_port}\n"
        )

        write_config(
            router_config,
            transport=True,
            instance_name="acp-autonomous-router",
            interface_block=gateway_interface,
        )
        write_config(
            destination_config,
            transport=False,
            instance_name="acp-autonomous-destination",
            interface_block=leaf_interface,
        )
        write_config(
            origin_config,
            transport=False,
            instance_name="acp-autonomous-origin",
            interface_block=leaf_interface,
        )
        for relay_id, config_dir in relay_configs.items():
            write_config(
                config_dir,
                transport=False,
                instance_name=f"acp-autonomous-{relay_id}",
                interface_block=leaf_interface,
            )

        origin_identity = RNS.Identity()
        relay_identity = {
            relay_id: RNS.Identity()
            for relay_id in ("relay-a", "relay-b", "relay-c")
        }
        identity_files = {}
        for relay_id, identity in relay_identity.items():
            identity_file = root / f"{relay_id}.identity"
            if not identity.to_file(str(identity_file)):
                raise RuntimeError(f"could not persist {relay_id} identity")
            identity_files[relay_id] = identity_file

        router_script = Path(__file__).with_name("reticulum_transport_node.py")
        server_script = Path(__file__).with_name("reticulum_live_server.py")
        relay_script = Path(__file__).with_name("reticulum_relay_stage_process.py")

        router = start_process(
            [
                str(router_script),
                "--config-dir",
                str(router_config),
            ]
        )
        time.sleep(1.0)

        destination_hash_file = root / "destination.hash"
        state_db = root / "authority-sync.sqlite3"
        watermark_db = root / "authority-watermarks.sqlite3"
        destination = start_process(
            [
                str(server_script),
                "--config-dir",
                str(destination_config),
                "--hash-file",
                str(destination_hash_file),
                "--state-db",
                str(state_db),
                "--watermark-db",
                str(watermark_db),
                "--announce-interval",
                "60",
                "--allowed-sender-id",
                "origin-peer",
                "--allowed-identity-hash",
                origin_identity.hash.hex(),
                "--terminal-relay-identity-hash",
                relay_identity["relay-c"].hash.hex(),
            ]
        )

        processes = {
            "router": router,
            "destination": destination,
        }

        try:
            destination_hex = wait_for_file(
                destination_hash_file,
                destination,
                args.timeout,
            )

            relay_c_hash_file = root / "relay-c.hash"
            relay_c_ready = root / "relay-c.ready"
            relay_c = start_relay(
                script=relay_script,
                config_dir=relay_configs["relay-c"],
                identity_file=identity_files["relay-c"],
                destination_hash_file=relay_c_hash_file,
                ready_file=relay_c_ready,
                queue_db=root / "relay-c-forward.sqlite3",
                relay_id="relay-c",
                upstream_id="relay-b",
                upstream_identity_hash=relay_identity["relay-b"].hash,
                next_destination_hash=destination_hex,
                next_kind="final",
                next_receiver_id="reticulum-server",
                relayed_at="2026-09-25T20:10:30Z",
                timeout=args.timeout,
            )
            processes["relay-c"] = relay_c
            relay_c_hex = wait_for_file(
                relay_c_hash_file,
                relay_c,
                args.timeout,
            )
            relay_c_ready_value = wait_for_file(
                relay_c_ready,
                relay_c,
                args.timeout,
            )
            if relay_c_ready_value != "relay-c:0":
                raise RuntimeError(
                    f"unexpected initial relay-c drain state: {relay_c_ready_value}"
                )

            relay_b_hash_file = root / "relay-b.hash"
            relay_b_ready = root / "relay-b.ready"
            relay_b = start_relay(
                script=relay_script,
                config_dir=relay_configs["relay-b"],
                identity_file=identity_files["relay-b"],
                destination_hash_file=relay_b_hash_file,
                ready_file=relay_b_ready,
                queue_db=root / "relay-b-forward.sqlite3",
                relay_id="relay-b",
                upstream_id="relay-a",
                upstream_identity_hash=relay_identity["relay-a"].hash,
                next_destination_hash=relay_c_hex,
                next_kind="relay",
                next_receiver_id="relay-c",
                relayed_at="2026-09-25T20:10:20Z",
                timeout=args.timeout,
            )
            processes["relay-b"] = relay_b
            relay_b_hex = wait_for_file(
                relay_b_hash_file,
                relay_b,
                args.timeout,
            )
            relay_b_ready_value = wait_for_file(
                relay_b_ready,
                relay_b,
                args.timeout,
            )
            if relay_b_ready_value != "relay-b:0":
                raise RuntimeError(
                    f"unexpected initial relay-b drain state: {relay_b_ready_value}"
                )

            relay_a_hash_file = root / "relay-a.hash"
            relay_a_ready = root / "relay-a.ready"
            relay_a = start_relay(
                script=relay_script,
                config_dir=relay_configs["relay-a"],
                identity_file=identity_files["relay-a"],
                destination_hash_file=relay_a_hash_file,
                ready_file=relay_a_ready,
                queue_db=root / "relay-a-forward.sqlite3",
                relay_id="relay-a",
                upstream_id="origin-peer",
                upstream_identity_hash=origin_identity.hash,
                next_destination_hash=relay_b_hex,
                next_kind="relay",
                next_receiver_id="relay-b",
                relayed_at="2026-09-25T20:10:10Z",
                timeout=args.timeout,
            )
            processes["relay-a"] = relay_a
            relay_a_hex = wait_for_file(
                relay_a_hash_file,
                relay_a,
                args.timeout,
            )
            relay_a_ready_value = wait_for_file(
                relay_a_ready,
                relay_a,
                args.timeout,
            )
            if relay_a_ready_value != "relay-a:0":
                raise RuntimeError(
                    f"unexpected initial relay-a drain state: {relay_a_ready_value}"
                )

            RNS.Reticulum(configdir=str(origin_config))
            relay_a_hash = bytes.fromhex(relay_a_hex)
            wait_for_path(relay_a_hash, args.timeout)
            relay_a_identity = wait_for_identity(relay_a_hash, args.timeout)
            relay_a_destination = RNS.Destination(
                relay_a_identity,
                RNS.Destination.OUT,
                RNS.Destination.SINGLE,
                APP_NAME,
                *RELAY_ASPECTS,
            )
            link = establish_identified_link(
                relay_a_destination,
                origin_identity,
                args.timeout,
            )
            transport = ReticulumRelayStageTransport(
                {"relay-a": link},
                peer_destination_hashes={"relay-a": relay_a_hash},
                timeout_seconds=min(args.timeout, 8.0),
                max_response_size=65536,
            )

            payload = origin_chain_payload(
                watermark_id="autonomous-origin-watermark-1",
                sequence=1,
                issued_at="2026-09-25T20:10:00Z",
            )

            acknowledgement = decode_authority_sync_watermark_acknowledgement(
                transport.exchange("relay-a", payload)
            )
            if acknowledgement.disposition is not WatermarkDisposition.APPLIED:
                raise RuntimeError(
                    f"autonomous relay chain not applied: {acknowledgement}"
                )

            duplicate = decode_authority_sync_watermark_acknowledgement(
                transport.exchange("relay-a", payload)
            )
            if duplicate.disposition is not WatermarkDisposition.DUPLICATE:
                raise RuntimeError(
                    f"autonomous relay-chain replay not duplicate: {duplicate}"
                )

            recovery_payload = origin_chain_payload(
                watermark_id="autonomous-origin-watermark-2",
                sequence=2,
                issued_at="2026-09-25T20:20:00Z",
            )

            # Remove the middle application relay while keeping the origin,
            # first relay and final destination alive. The new watermark must
            # not be accepted while the forwarding chain is incomplete.
            stop_process(relay_b)
            time.sleep(1.0)
            outage_failed_closed = False
            try:
                transport.exchange("relay-a", recovery_payload)
            except ReticulumAdapterError:
                outage_failed_closed = True
            if not outage_failed_closed:
                raise RuntimeError(
                    "relay-b outage did not fail closed at the origin"
                )

            link.teardown()
            stop_process(relay_a)
            stop_process(relay_c)
            time.sleep(1.0)

            # Restart all relay stages with the exact same provisioned
            # Reticulum identities. The final destination remains alive and
            # retains the previously accepted watermark floor.
            relay_c = start_relay(
                script=relay_script,
                config_dir=relay_configs["relay-c"],
                identity_file=identity_files["relay-c"],
                destination_hash_file=relay_c_hash_file,
                ready_file=relay_c_ready,
                queue_db=root / "relay-c-forward.sqlite3",
                relay_id="relay-c",
                upstream_id="relay-b",
                upstream_identity_hash=relay_identity["relay-b"].hash,
                next_destination_hash=destination_hex,
                next_kind="final",
                next_receiver_id="reticulum-server",
                relayed_at="2026-09-25T20:20:30Z",
                timeout=args.timeout,
            )
            processes["relay-c"] = relay_c
            recovered_relay_c_hex = wait_for_file(
                relay_c_hash_file,
                relay_c,
                args.timeout,
            )
            recovered_relay_c_ready = wait_for_file(
                relay_c_ready,
                relay_c,
                args.timeout,
            )
            if recovered_relay_c_ready != "relay-c:0":
                raise RuntimeError(
                    "unexpected recovered relay-c drain state: "
                    f"{recovered_relay_c_ready}"
                )

            relay_b = start_relay(
                script=relay_script,
                config_dir=relay_configs["relay-b"],
                identity_file=identity_files["relay-b"],
                destination_hash_file=relay_b_hash_file,
                ready_file=relay_b_ready,
                queue_db=root / "relay-b-forward.sqlite3",
                relay_id="relay-b",
                upstream_id="relay-a",
                upstream_identity_hash=relay_identity["relay-a"].hash,
                next_destination_hash=recovered_relay_c_hex,
                next_kind="relay",
                next_receiver_id="relay-c",
                relayed_at="2026-09-25T20:20:20Z",
                timeout=args.timeout,
            )
            processes["relay-b"] = relay_b
            recovered_relay_b_hex = wait_for_file(
                relay_b_hash_file,
                relay_b,
                args.timeout,
            )
            recovered_relay_b_ready = wait_for_file(
                relay_b_ready,
                relay_b,
                args.timeout,
            )
            if recovered_relay_b_ready != "relay-b:0":
                raise RuntimeError(
                    "unexpected recovered relay-b drain state: "
                    f"{recovered_relay_b_ready}"
                )

            relay_a = start_relay(
                script=relay_script,
                config_dir=relay_configs["relay-a"],
                identity_file=identity_files["relay-a"],
                destination_hash_file=relay_a_hash_file,
                ready_file=relay_a_ready,
                queue_db=root / "relay-a-forward.sqlite3",
                relay_id="relay-a",
                upstream_id="origin-peer",
                upstream_identity_hash=origin_identity.hash,
                next_destination_hash=recovered_relay_b_hex,
                next_kind="relay",
                next_receiver_id="relay-b",
                relayed_at="2026-09-25T20:20:10Z",
                timeout=args.timeout,
            )
            processes["relay-a"] = relay_a
            recovered_relay_a_hex = wait_for_file(
                relay_a_hash_file,
                relay_a,
                args.timeout,
            )
            recovered_relay_a_ready = wait_for_file(
                relay_a_ready,
                relay_a,
                args.timeout,
            )
            if recovered_relay_a_ready != "relay-a:1":
                raise RuntimeError(
                    "recovered relay-a did not drain exactly one pending "
                    f"forward: {recovered_relay_a_ready}"
                )

            if recovered_relay_a_hex != relay_a_hex:
                raise RuntimeError("relay-a destination identity changed")
            if recovered_relay_b_hex != relay_b_hex:
                raise RuntimeError("relay-b destination identity changed")
            if recovered_relay_c_hex != relay_c_hex:
                raise RuntimeError("relay-c destination identity changed")

            time.sleep(1.0)
            recovered_relay_a_hash = bytes.fromhex(recovered_relay_a_hex)
            wait_for_path(recovered_relay_a_hash, args.timeout)
            recovered_relay_a_identity = wait_for_identity(
                recovered_relay_a_hash,
                args.timeout,
            )
            recovered_destination = RNS.Destination(
                recovered_relay_a_identity,
                RNS.Destination.OUT,
                RNS.Destination.SINGLE,
                APP_NAME,
                *RELAY_ASPECTS,
            )
            recovered_link = establish_identified_link(
                recovered_destination,
                origin_identity,
                args.timeout,
            )
            recovered_transport = ReticulumRelayStageTransport(
                {"relay-a": recovered_link},
                peer_destination_hashes={
                    "relay-a": recovered_relay_a_hash
                },
                timeout_seconds=min(args.timeout, 8.0),
                max_response_size=65536,
            )

            recovery_ack = decode_authority_sync_watermark_acknowledgement(
                recovered_transport.exchange(
                    "relay-a",
                    recovery_payload,
                )
            )
            if recovery_ack.disposition is not WatermarkDisposition.DUPLICATE:
                raise RuntimeError(
                    "recovered relay-chain resend was not duplicate after "
                    f"startup drain: {recovery_ack}"
                )

            recovery_duplicate = (
                decode_authority_sync_watermark_acknowledgement(
                    recovered_transport.exchange(
                        "relay-a",
                        recovery_payload,
                    )
                )
            )
            if (
                recovery_duplicate.disposition
                is not WatermarkDisposition.DUPLICATE
            ):
                raise RuntimeError(
                    "recovered relay-chain replay not duplicate: "
                    f"{recovery_duplicate}"
                )
            recovered_link.teardown()

            print("RETICULUM_AUTONOMOUS_RELAY_CHAIN=PASS")
            print("ROUTE=origin->relay-a->relay-b->relay-c->destination")
            print(f"ACK={acknowledgement.disposition.value}")
            print(f"REPLAY_ACK={duplicate.disposition.value}")
            print("OUTAGE_FAIL_CLOSED=PASS")
            print("RECOVERY_DRAINED_PENDING=1")
            print(f"RECOVERY_RESEND_ACK={recovery_ack.disposition.value}")
            print(
                "RECOVERY_REPLAY_ACK="
                f"{recovery_duplicate.disposition.value}"
            )
            print(f"RELAY_A_DESTINATION={relay_a_hex}")
            print(f"RELAY_B_DESTINATION={relay_b_hex}")
            print(f"RELAY_C_DESTINATION={relay_c_hex}")
            print(f"FINAL_DESTINATION={destination_hex}")
        except Exception:
            for process in processes.values():
                stop_process(process)
            for name, process in processes.items():
                if process.stdout is not None:
                    output = process.stdout.read()
                    if output:
                        print(f"{name.upper()}_OUTPUT_BEGIN")
                        print(output)
                        print(f"{name.upper()}_OUTPUT_END")
            raise
        finally:
            for process in reversed(tuple(processes.values())):
                stop_process(process)


if __name__ == "__main__":
    main()
