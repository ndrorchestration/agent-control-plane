import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from agent_control_plane.remote_execution_adapter import (
    ContractValidationError,
    DurableRemoteExecutionReplayGuard,
    RemoteExecutionFreshness,
    RemoteExecutionRequest,
    verify_request_hmac_sha256,
)

p = argparse.ArgumentParser()
p.add_argument("request_file")
p.add_argument("--key", required=True)
p.add_argument("--device-identity", required=True)
p.add_argument("--replay-db", required=True)
args = p.parse_args()

payload = json.loads(Path(args.request_file).read_text(encoding="utf-8"))
if payload.get("schema_version") != "ndr.remote-execution-request.v1":
    raise SystemExit("REMOTE_REQUEST_FAIL: unsupported schema")
r = payload["request"]
f = payload["freshness"]
request = RemoteExecutionRequest(
    request_id=r["request_id"],
    device_id=r["device_id"],
    expected_device_identity_fingerprint=r["expected_device_identity_fingerprint"],
    expected_device_attestation_level=r["expected_device_attestation_level"],
    execution_profile=r["execution_profile"],
    expected_side_effect_class=r["expected_side_effect_class"],
    working_directory=r["working_directory"],
    command_or_action=r["command_or_action"],
    action_sha256=r["action_sha256"],
)
freshness = RemoteExecutionFreshness(
    nonce=f["nonce"],
    issued_at_epoch_seconds=f["issued_at_epoch_seconds"],
    expires_at_epoch_seconds=f["expires_at_epoch_seconds"],
)
identity = json.loads(Path(args.device_identity).read_text(encoding="utf-8"))
if request.device_id != identity["device_name"]:
    raise SystemExit("REMOTE_REQUEST_FAIL: device name mismatch")
if request.expected_device_identity_fingerprint != identity["fingerprint_sha256"]:
    raise SystemExit("REMOTE_REQUEST_FAIL: device fingerprint mismatch")
if request.expected_device_attestation_level != identity["attestation_level"]:
    raise SystemExit("REMOTE_REQUEST_FAIL: attestation level mismatch")
if request.execution_profile != "READ_ONLY_DISCOVERY":
    raise SystemExit("REMOTE_REQUEST_FAIL: only READ_ONLY_DISCOVERY is admissible")
if request.expected_side_effect_class != "READ_ONLY":
    raise SystemExit("REMOTE_REQUEST_FAIL: only READ_ONLY side effects are admissible")
try:
    verify_request_hmac_sha256(
        request,
        freshness,
        key=Path(args.key).read_bytes(),
        signature=payload["signature"],
    )
    DurableRemoteExecutionReplayGuard(args.replay_db).consume(
        request, freshness, now_epoch_seconds=int(time.time())
    )
except ContractValidationError as exc:
    print(f"REMOTE_REQUEST_FAIL: {exc}")
    raise SystemExit(2)

print("REMOTE_REQUEST=PASS")
print(json.dumps(r, separators=(",", ":")))
