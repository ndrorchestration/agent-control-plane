import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from agent_control_plane.contract.model import ContractValidationError
from agent_control_plane.remote_execution_adapter import DurableRemoteExecutionReplayGuard
from agent_control_plane.typed_remote_execution import (
    TypedRemoteExecutionResult,
    execute_read_only_operation_bounded,
    render_read_only_operation_argv,
    resolve_authorized_working_directory,
    typed_request_envelope_from_mapping,
    verify_typed_request_hmac_sha256,
)

p = argparse.ArgumentParser()
p.add_argument("request_file")
p.add_argument("--key", required=True)
p.add_argument("--device-identity", required=True)
p.add_argument("--replay-db", required=True)
p.add_argument("--allowed-root", action="append", required=True)
p.add_argument("--evidence-root", required=True)
args = p.parse_args()

request_path = Path(args.request_file)
try:
    request_bytes = request_path.read_bytes()
    request_envelope_sha256 = hashlib.sha256(request_bytes).hexdigest()
    payload = json.loads(request_bytes.decode("utf-8"))
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
    render_read_only_operation_argv(
        request.operation_id,
        request.operation_parameters,
    )
    cwd = resolve_authorized_working_directory(
        request.working_directory,
        args.allowed_root,
    )
    try:
        evidence_root = Path(args.evidence_root).resolve(strict=True)
    except OSError as exc:
        raise ContractValidationError(
            "evidence root cannot be resolved"
        ) from exc
    if not evidence_root.is_dir():
        raise ContractValidationError("evidence root is not a directory")
    DurableRemoteExecutionReplayGuard(args.replay_db).consume(
        request,
        freshness,
        now_epoch_seconds=int(time.time()),
    )
except (
    ContractValidationError,
    KeyError,
    TypeError,
    ValueError,
    OSError,
    UnicodeDecodeError,
    json.JSONDecodeError,
) as exc:
    print(f"TYPED_REQUEST_EXECUTION_FAIL: {exc}")
    raise SystemExit(2)

execution = execute_read_only_operation_bounded(
    request.operation_id,
    request.operation_parameters,
    cwd=cwd,
)
argv = execution["argv"]
result_payload = {
    "schema_version": "ndr.typed-operation-result.v1",
    "request_id": request.request_id,
    "operation_id": request.operation_id,
    "operation_parameters": dict(request.operation_parameters),
    "operation_sha256": request.operation_sha256,
    "argv": list(argv),
    "shell": False,
    "working_directory": str(cwd),
    "exit_code": execution["exit_code"],
    "request_envelope_sha256": request_envelope_sha256,
    "started_epoch_seconds": execution["started_epoch_seconds"],
    "finished_epoch_seconds": execution["finished_epoch_seconds"],
    "timed_out": execution["timed_out"],
    "stdout_sha256": execution["stdout_sha256"],
    "stderr_sha256": execution["stderr_sha256"],
    "stdout_bytes": execution["stdout_bytes"],
    "stderr_bytes": execution["stderr_bytes"],
    "stdout_truncated": execution["stdout_truncated"],
    "stderr_truncated": execution["stderr_truncated"],
    "stdout": execution["stdout"],
    "stderr": execution["stderr"],
}

validated = TypedRemoteExecutionResult.from_mapping(result_payload)
validated.assert_matches(request)

out = evidence_root / f"{request.request_id}.typed-result.json"
out.write_text(
    json.dumps(result_payload, indent=2, sort_keys=True) + "\n",
    encoding="utf-8",
)
print("TYPED_REQUEST_EXECUTION=PASS")
print(f"TYPED_OPERATION_RESULT={out}")
print(f"TYPED_OPERATION_EXIT_CODE={execution['exit_code']}")
raise SystemExit(execution["exit_code"])
