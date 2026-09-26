import argparse
import json
import secrets
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from agent_control_plane.remote_execution_adapter import RemoteExecutionFreshness
from agent_control_plane.typed_remote_execution import (
    TypedRemoteExecutionRequest,
    operation_sha256,
    sign_typed_request_hmac_sha256,
    typed_request_envelope_mapping,
)

p = argparse.ArgumentParser()
p.add_argument("--device", required=True)
p.add_argument("--device-fingerprint", required=True)
p.add_argument("--device-attestation-level", required=True)
p.add_argument("--profile", default="READ_ONLY_DISCOVERY")
p.add_argument("--side-effect-class", default="READ_ONLY")
p.add_argument("--cwd", required=True)
p.add_argument("--operation-id", required=True)
parameter_group = p.add_mutually_exclusive_group()
parameter_group.add_argument("--parameters-json")
parameter_group.add_argument("--parameters-file")
p.add_argument("--ttl", type=int, default=60)
p.add_argument("--key", required=True)
p.add_argument("--output", required=True)
args = p.parse_args()

try:
    if args.parameters_file:
        parameters = json.loads(Path(args.parameters_file).read_text(encoding="utf-8"))
    elif args.parameters_json is not None:
        parameters = json.loads(args.parameters_json)
    else:
        parameters = {}
except (json.JSONDecodeError, OSError) as exc:
    raise SystemExit(f"invalid operation parameters: {exc}") from exc
if not isinstance(parameters, dict):
    raise SystemExit("operation parameters must decode to an object")

now = int(time.time())
request = TypedRemoteExecutionRequest(
    request_id=str(uuid.uuid4()),
    device_id=args.device,
    expected_device_identity_fingerprint=args.device_fingerprint,
    expected_device_attestation_level=args.device_attestation_level,
    execution_profile=args.profile,
    expected_side_effect_class=args.side_effect_class,
    working_directory=args.cwd,
    operation_id=args.operation_id,
    operation_parameters=parameters,
    operation_sha256=operation_sha256(args.operation_id, parameters),
)
freshness = RemoteExecutionFreshness(
    nonce=secrets.token_hex(16),
    issued_at_epoch_seconds=now,
    expires_at_epoch_seconds=now + args.ttl,
)
key = Path(args.key).read_bytes()
signature = sign_typed_request_hmac_sha256(request, freshness, key=key)
payload = typed_request_envelope_mapping(request, freshness, signature)
out = Path(args.output)
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
print(out)
