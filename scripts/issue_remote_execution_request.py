import argparse
import json
import secrets
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from agent_control_plane.remote_execution_adapter import (
    RemoteExecutionFreshness,
    RemoteExecutionRequest,
    action_sha256,
    sign_request_hmac_sha256,
)

p = argparse.ArgumentParser()
p.add_argument("--device", required=True)
p.add_argument("--device-fingerprint", required=True)
p.add_argument("--device-attestation-level", required=True)
p.add_argument("--profile", required=True)
p.add_argument("--side-effect-class", required=True)
p.add_argument("--cwd", required=True)
p.add_argument("--command", required=True)
p.add_argument("--ttl", type=int, default=60)
p.add_argument("--key", required=True)
p.add_argument("--output", required=True)
args = p.parse_args()

now = int(time.time())
request = RemoteExecutionRequest(
    request_id=str(uuid.uuid4()),
    device_id=args.device,
    expected_device_identity_fingerprint=args.device_fingerprint,
    expected_device_attestation_level=args.device_attestation_level,
    execution_profile=args.profile,
    expected_side_effect_class=args.side_effect_class,
    working_directory=args.cwd,
    command_or_action=args.command,
    action_sha256=action_sha256(args.command),
)
freshness = RemoteExecutionFreshness(
    nonce=secrets.token_hex(16),
    issued_at_epoch_seconds=now,
    expires_at_epoch_seconds=now + args.ttl,
)
key = Path(args.key).read_bytes()
signature = sign_request_hmac_sha256(request, freshness, key=key)
payload = {
    "schema_version": "ndr.remote-execution-request.v1",
    "request": {
        "request_id": request.request_id,
        "device_id": request.device_id,
        "expected_device_identity_fingerprint": request.expected_device_identity_fingerprint,
        "expected_device_attestation_level": request.expected_device_attestation_level,
        "execution_profile": request.execution_profile,
        "expected_side_effect_class": request.expected_side_effect_class,
        "working_directory": request.working_directory,
        "command_or_action": request.command_or_action,
        "action_sha256": request.action_sha256,
    },
    "freshness": {
        "nonce": freshness.nonce,
        "issued_at_epoch_seconds": freshness.issued_at_epoch_seconds,
        "expires_at_epoch_seconds": freshness.expires_at_epoch_seconds,
    },
    "signature": signature,
}
out = Path(args.output)
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
print(out)
