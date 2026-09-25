"""Local Reticulum server process for ACP live integration testing."""

import argparse
from pathlib import Path
import time

import RNS

from agent_control_plane.authority_state import InMemoryAuthorityStateCache
from agent_control_plane.authority_sync import AuthoritySyncReconciler
from agent_control_plane.reticulum_adapter import ReticulumAuthoritySyncServer
from agent_control_plane.revocation import InMemoryRevocationRegistry
from agent_control_plane.sync_transport import AuthoritySyncEndpoint


APP_NAME = "ndrorchestration"
ASPECTS = ("acp", "authority_sync_live")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config-dir", required=True)
    parser.add_argument("--hash-file", required=True)
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
        AuthoritySyncReconciler(
            receiver_id="reticulum-server",
            state_cache=InMemoryAuthorityStateCache(),
            revocations=InMemoryRevocationRegistry(),
        )
    )
    server = ReticulumAuthoritySyncServer(destination=destination, endpoint=endpoint)
    server.install(allow=RNS.Destination.ALLOW_ALL)

    Path(args.hash_file).write_text(destination.hash.hex(), encoding="utf-8")

    while True:
        destination.announce()
        time.sleep(1.0)


if __name__ == "__main__":
    main()
