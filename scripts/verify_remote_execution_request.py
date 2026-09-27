import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from agent_control_plane.contract.model import ContractValidationError
from agent_control_plane.remote_execution_adapter import DurableRemoteExecutionReplayGuard
from agent_control_plane.typed_remote_execution import (
    render_read_only_operation_argv,
    resolve_authorized_working_directory,
    validate_git_repository_boundary,
    typed_request_envelope_from_mapping,
    verify_typed_request_hmac_sha256,
)

p = argparse.ArgumentParser()
p.add_argument("request_file")
p.add_argument("--key", required=True)
p.add_argument("--device-identity", required=True)
p.add_argument("--replay-db", required=True)
p.add_argument("--allowed-root", action="append", required=True)
args = p.parse_args()

payload = json.loads(Path(args.request_file).read_text(encoding="utf-8"))
if payload.get("schema_version") != "ndr.remote-execution-request.v2":
    raise SystemExit("REMOTE_REQUEST_FAIL: unsupported schema")
try:
    request, freshness, signature = typed_request_envelope_from_mapping(payload)
    identity = json.loads(Path(args.device_identity).read_text(encoding="utf-8"))
    if request.device_id != identity["device_name"]:
        raise ContractValidationError("device name mismatch")
    if request.expected_device_identity_fingerprint != identity["fingerprint_sha256"]:
        raise ContractValidationError("device fingerprint mismatch")
    if request.expected_device_attestation_level != identity["attestation_level"]:
        raise ContractValidationError("attestation level mismatch")
    verify_typed_request_hmac_sha256(
        request,
        freshness,
        key=Path(args.key).read_bytes(),
        signature=signature,
    )
    freshness.assert_fresh(now_epoch_seconds=int(time.time()))
    argv = render_read_only_operation_argv(
        request.operation_id,
        request.operation_parameters,
    )
    resolved_cwd = resolve_authorized_working_directory(
        request.working_directory,
        args.allowed_root,
    )
    validate_git_repository_boundary(resolved_cwd, args.allowed_root)
    DurableRemoteExecutionReplayGuard(args.replay_db).consume(
        request, freshness, now_epoch_seconds=int(time.time())
    )
except (ContractValidationError, KeyError, TypeError, ValueError) as exc:
    print(f"REMOTE_REQUEST_FAIL: {exc}")
    raise SystemExit(2)

print("REMOTE_REQUEST=PASS")
print(json.dumps({
    "request_id": request.request_id,
    "device_id": request.device_id,
    "execution_profile": request.execution_profile,
    "expected_side_effect_class": request.expected_side_effect_class,
    "working_directory": str(resolved_cwd),
    "operation_id": request.operation_id,
    "operation_parameters": dict(request.operation_parameters),
    "operation_sha256": request.operation_sha256,
    "argv": list(argv),
}, sort_keys=True, separators=(",", ":")))
