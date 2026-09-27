"""Typed, fail-closed read-only remote execution contract.

This module is the active v2 execution surface. It carries operation IDs and
validated structured parameters rather than shell command text.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
import re
from types import MappingProxyType
from typing import Any, Mapping, Tuple

from .contract.model import ContractValidationError

TYPED_REMOTE_EXECUTION_SCHEMA_VERSION = "agent-control-plane.remote-execution.v1"
TYPED_REQUEST_ENVELOPE_SCHEMA_VERSION = "ndr.remote-execution-request.v2"
REMOTE_EXECUTION_MAX_RUNTIME_SECONDS = 30
REMOTE_EXECUTION_MAX_OUTPUT_BYTES = 1024 * 1024
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_SAFE_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,128}$")


@dataclass(frozen=True)
class ReadOnlyOperationSpec:
    argv: Tuple[str, ...]
    parameter_names: frozenset[str]


GIT_READ_ONLY_PREFIX = ("git", "-c", "core.fsmonitor=false")

READ_ONLY_OPERATION_SPECS: Mapping[str, ReadOnlyOperationSpec] = MappingProxyType(
    {
        "git.status.short": ReadOnlyOperationSpec(
            argv=GIT_READ_ONLY_PREFIX
            + ("status", "--short", "--ignore-submodules=all"),
            parameter_names=frozenset(),
        ),
        "git.status.porcelain_v1": ReadOnlyOperationSpec(
            argv=GIT_READ_ONLY_PREFIX
            + ("status", "--porcelain=v1", "--ignore-submodules=all"),
            parameter_names=frozenset(),
        ),
        "git.rev_parse.head": ReadOnlyOperationSpec(
            argv=GIT_READ_ONLY_PREFIX + ("rev-parse", "HEAD"),
            parameter_names=frozenset(),
        ),
        "git.branch.current": ReadOnlyOperationSpec(
            argv=GIT_READ_ONLY_PREFIX + ("branch", "--show-current"),
            parameter_names=frozenset(),
        ),
        "git.remote.origin": ReadOnlyOperationSpec(
            argv=GIT_READ_ONLY_PREFIX + ("remote", "get-url", "origin"),
            parameter_names=frozenset(),
        ),
        "git.diff.name_only": ReadOnlyOperationSpec(
            argv=GIT_READ_ONLY_PREFIX
            + ("diff", "--no-ext-diff", "--ignore-submodules=all", "--name-only"),
            parameter_names=frozenset(),
        ),
        "git.diff.cached.check": ReadOnlyOperationSpec(
            argv=GIT_READ_ONLY_PREFIX
            + (
                "diff",
                "--no-ext-diff",
                "--ignore-submodules=all",
                "--cached",
                "--check",
            ),
            parameter_names=frozenset(),
        ),
        "git.show.file": ReadOnlyOperationSpec(
            argv=GIT_READ_ONLY_PREFIX + ("show",),
            parameter_names=frozenset({"revision", "path"}),
        ),
    }
)


def _required(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContractValidationError(f"{field_name} must not be blank")
    return value


def _sha256(value: str, field_name: str) -> str:
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        raise ContractValidationError(
            f"{field_name} must be 64 lowercase hexadecimal characters"
        )
    return value


def _canonical_json_bytes(value: Mapping[str, Any]) -> bytes:
    import json
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _remote_freshness_type():
    from .remote_execution_adapter import RemoteExecutionFreshness
    return RemoteExecutionFreshness


def _validate_freshness(freshness: Any) -> None:
    if not isinstance(freshness, _remote_freshness_type()):
        raise ContractValidationError("freshness must be RemoteExecutionFreshness")
def _validate_operation_parameters(
    operation_id: str,
    parameters: Mapping[str, Any],
) -> Mapping[str, Any]:
    spec = READ_ONLY_OPERATION_SPECS.get(operation_id)
    if spec is None:
        raise ContractValidationError("operation_id is not an admitted read-only operation")
    if not isinstance(parameters, Mapping):
        raise ContractValidationError("operation_parameters must be a mapping")
    observed = set(parameters.keys())
    if observed != set(spec.parameter_names):
        raise ContractValidationError("operation_parameters do not match operation schema")

    normalized = dict(parameters)
    if operation_id == "git.show.file":
        revision = normalized.get("revision")
        path = normalized.get("path")
        if (
            not isinstance(revision, str)
            or not re.fullmatch(r"[0-9A-Za-z._/-]{1,128}", revision)
            or revision.startswith("-")
        ):
            raise ContractValidationError("revision is not admissible")
        if not isinstance(path, str) or not path or len(path) > 512:
            raise ContractValidationError("path is not admissible")
        if (
            path.startswith("-")
            or path.startswith("/")
            or path.startswith("\\")
            or ":" in path
            or "\x00" in path
            or "\r" in path
            or "\n" in path
            or "\\" in path
        ):
            raise ContractValidationError("path is not admissible")
        parts = path.split("/")
        if any(part in {"", ".", ".."} for part in parts):
            raise ContractValidationError("path is not admissible")
    return normalized


def operation_sha256(operation_id: str, parameters: Mapping[str, Any]) -> str:
    _required(operation_id, "operation_id")
    normalized = _validate_operation_parameters(operation_id, parameters)
    payload = {"operation_id": operation_id, "operation_parameters": normalized}
    return hashlib.sha256(_canonical_json_bytes(payload)).hexdigest()


def render_read_only_operation_argv(
    operation_id: str,
    parameters: Mapping[str, Any],
) -> Tuple[str, ...]:
    normalized = _validate_operation_parameters(operation_id, parameters)
    spec = READ_ONLY_OPERATION_SPECS[operation_id]
    if operation_id == "git.show.file":
        return spec.argv + (f"{normalized['revision']}:{normalized['path']}",)
    return spec.argv


@dataclass(frozen=True)
class TypedRemoteExecutionRequest:
    request_id: str
    device_id: str
    expected_device_identity_fingerprint: str
    expected_device_attestation_level: str
    execution_profile: str
    expected_side_effect_class: str
    working_directory: str
    operation_id: str
    operation_parameters: Mapping[str, Any]
    operation_sha256: str
    schema_version: str = TYPED_REMOTE_EXECUTION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        _required(self.request_id, "request_id")
        if (
            _SAFE_REQUEST_ID_RE.fullmatch(self.request_id) is None
            or self.request_id in {".", ".."}
        ):
            raise ContractValidationError("request_id is not path-safe")
        _required(self.device_id, "device_id")
        _sha256(
            self.expected_device_identity_fingerprint,
            "expected_device_identity_fingerprint",
        )
        _required(
            self.expected_device_attestation_level,
            "expected_device_attestation_level",
        )
        if self.execution_profile != "READ_ONLY_DISCOVERY":
            raise ContractValidationError(
                "typed execution profile must be READ_ONLY_DISCOVERY"
            )
        if self.expected_side_effect_class != "READ_ONLY":
            raise ContractValidationError("typed side-effect class must be READ_ONLY")
        _required(self.working_directory, "working_directory")

        normalized = dict(
            _validate_operation_parameters(
                self.operation_id,
                self.operation_parameters,
            )
        )
        object.__setattr__(
            self,
            "operation_parameters",
            MappingProxyType(normalized),
        )
        expected = operation_sha256(self.operation_id, normalized)
        if _sha256(self.operation_sha256, "operation_sha256") != expected:
            raise ContractValidationError(
                "operation_sha256 does not bind typed operation"
            )
        if self.schema_version != TYPED_REMOTE_EXECUTION_SCHEMA_VERSION:
            raise ContractValidationError(
                f"unsupported typed schema_version: {self.schema_version}"
            )
def canonical_typed_request_bytes(
    request: TypedRemoteExecutionRequest,
    freshness: Any,
) -> bytes:
    if not isinstance(request, TypedRemoteExecutionRequest):
        raise ContractValidationError(
            "request must be TypedRemoteExecutionRequest"
        )
    _validate_freshness(freshness)
    payload = {
        "schema_version": request.schema_version,
        "request_id": request.request_id,
        "device_id": request.device_id,
        "expected_device_identity_fingerprint": request.expected_device_identity_fingerprint,
        "expected_device_attestation_level": request.expected_device_attestation_level,
        "execution_profile": request.execution_profile,
        "expected_side_effect_class": request.expected_side_effect_class,
        "working_directory": request.working_directory,
        "operation_id": request.operation_id,
        "operation_parameters": dict(request.operation_parameters),
        "operation_sha256": request.operation_sha256,
        "nonce": freshness.nonce,
        "issued_at_epoch_seconds": freshness.issued_at_epoch_seconds,
        "expires_at_epoch_seconds": freshness.expires_at_epoch_seconds,
    }
    return _canonical_json_bytes(payload)


def sign_typed_request_hmac_sha256(
    request: TypedRemoteExecutionRequest,
    freshness: Any,
    *,
    key: bytes,
) -> str:
    import hmac
    if not isinstance(key, (bytes, bytearray)) or len(key) < 32:
        raise ContractValidationError("signing key must be at least 32 bytes")
    return hmac.new(
        bytes(key),
        canonical_typed_request_bytes(request, freshness),
        hashlib.sha256,
    ).hexdigest()


def verify_typed_request_hmac_sha256(
    request: TypedRemoteExecutionRequest,
    freshness: Any,
    *,
    key: bytes,
    signature: str,
) -> None:
    import hmac
    _sha256(signature, "signature")
    expected = sign_typed_request_hmac_sha256(request, freshness, key=key)
    if not hmac.compare_digest(expected, signature):
        raise ContractValidationError(
            "typed remote execution request signature mismatch"
        )


def typed_request_envelope_mapping(
    request: TypedRemoteExecutionRequest,
    freshness: Any,
    signature: str,
) -> Mapping[str, Any]:
    if not isinstance(request, TypedRemoteExecutionRequest):
        raise ContractValidationError(
            "request must be TypedRemoteExecutionRequest"
        )
    _validate_freshness(freshness)
    _sha256(signature, "signature")
    return {
        "schema_version": TYPED_REQUEST_ENVELOPE_SCHEMA_VERSION,
        "request": {
            "schema_version": request.schema_version,
            "request_id": request.request_id,
            "device_id": request.device_id,
            "expected_device_identity_fingerprint": request.expected_device_identity_fingerprint,
            "expected_device_attestation_level": request.expected_device_attestation_level,
            "execution_profile": request.execution_profile,
            "expected_side_effect_class": request.expected_side_effect_class,
            "working_directory": request.working_directory,
            "operation_id": request.operation_id,
            "operation_parameters": dict(request.operation_parameters),
            "operation_sha256": request.operation_sha256,
        },
        "freshness": {
            "nonce": freshness.nonce,
            "issued_at_epoch_seconds": freshness.issued_at_epoch_seconds,
            "expires_at_epoch_seconds": freshness.expires_at_epoch_seconds,
        },
        "signature": signature,
    }
def typed_request_envelope_from_mapping(
    payload: Mapping[str, Any],
) -> tuple[TypedRemoteExecutionRequest, Any, str]:
    if not isinstance(payload, Mapping):
        raise ContractValidationError(
            "typed request envelope must be a mapping"
        )
    if payload.get("schema_version") != TYPED_REQUEST_ENVELOPE_SCHEMA_VERSION:
        raise ContractValidationError(
            "unsupported typed request envelope schema"
        )
    try:
        r = payload["request"]
        f = payload["freshness"]
        request = TypedRemoteExecutionRequest(
            request_id=r["request_id"],
            device_id=r["device_id"],
            expected_device_identity_fingerprint=r[
                "expected_device_identity_fingerprint"
            ],
            expected_device_attestation_level=r[
                "expected_device_attestation_level"
            ],
            execution_profile=r["execution_profile"],
            expected_side_effect_class=r["expected_side_effect_class"],
            working_directory=r["working_directory"],
            operation_id=r["operation_id"],
            operation_parameters=r["operation_parameters"],
            operation_sha256=r["operation_sha256"],
            schema_version=r["schema_version"],
        )
        freshness_type = _remote_freshness_type()
        freshness = freshness_type(
            nonce=f["nonce"],
            issued_at_epoch_seconds=f["issued_at_epoch_seconds"],
            expires_at_epoch_seconds=f["expires_at_epoch_seconds"],
        )
        signature = payload["signature"]
    except ContractValidationError:
        raise
    except (KeyError, TypeError, ValueError) as exc:
        raise ContractValidationError(
            "malformed typed request envelope"
        ) from exc
    _sha256(signature, "signature")
    return request, freshness, signature


@dataclass(frozen=True)
class TypedRemoteExecutionResult:
    request_id: str
    operation_id: str
    operation_parameters: Mapping[str, Any]
    operation_sha256: str
    request_envelope_sha256: str
    argv: Tuple[str, ...]
    shell: bool
    working_directory: str
    exit_code: int
    started_epoch_seconds: float
    finished_epoch_seconds: float
    timed_out: bool
    stdout_sha256: str
    stderr_sha256: str
    stdout_bytes: int
    stderr_bytes: int
    stdout_truncated: bool
    stderr_truncated: bool
    stdout: str
    stderr: str

    @classmethod
    def from_mapping(
        cls,
        data: Mapping[str, Any],
    ) -> "TypedRemoteExecutionResult":
        if not isinstance(data, Mapping):
            raise ContractValidationError(
                "typed execution result must be a mapping"
            )
        try:
            result = cls(
                request_id=data["request_id"],
                operation_id=data["operation_id"],
                operation_parameters=dict(data["operation_parameters"]),
                operation_sha256=data["operation_sha256"],
                request_envelope_sha256=data["request_envelope_sha256"],
                argv=tuple(data["argv"]),
                shell=data["shell"],
                working_directory=data["working_directory"],
                exit_code=data["exit_code"],
                started_epoch_seconds=data["started_epoch_seconds"],
                finished_epoch_seconds=data["finished_epoch_seconds"],
                timed_out=data["timed_out"],
                stdout_sha256=data["stdout_sha256"],
                stderr_sha256=data["stderr_sha256"],
                stdout_bytes=data["stdout_bytes"],
                stderr_bytes=data["stderr_bytes"],
                stdout_truncated=data["stdout_truncated"],
                stderr_truncated=data["stderr_truncated"],
                stdout=data["stdout"],
                stderr=data["stderr"],
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ContractValidationError(
                "malformed typed execution result"
            ) from exc
        result._validate()
        return result

    @staticmethod
    def _validate_stream(
        *,
        name: str,
        text: str,
        digest: str,
        total_bytes: int,
        truncated: bool,
    ) -> None:
        if not isinstance(text, str):
            raise ContractValidationError(f"{name} must be text")
        _sha256(digest, f"{name}_sha256")
        if (
            isinstance(total_bytes, bool)
            or not isinstance(total_bytes, int)
            or total_bytes < 0
        ):
            raise ContractValidationError(
                f"{name}_bytes must be a non-negative integer"
            )
        if not isinstance(truncated, bool):
            raise ContractValidationError(
                f"{name}_truncated must be boolean"
            )
        retained = text.encode("utf-8")
        retained_bytes = len(retained)
        if retained_bytes > REMOTE_EXECUTION_MAX_OUTPUT_BYTES:
            raise ContractValidationError(
                f"{name} retained output exceeds execution bound"
            )
        if truncated:
            if total_bytes <= retained_bytes:
                raise ContractValidationError(
                    f"{name} truncation byte count is inconsistent"
                )
        else:
            if total_bytes != retained_bytes:
                raise ContractValidationError(
                    f"{name} byte count mismatch"
                )
            observed = hashlib.sha256(retained).hexdigest()
            if observed != digest:
                raise ContractValidationError(
                    f"{name} digest mismatch"
                )

    def _validate(self) -> None:
        _required(self.request_id, "request_id")
        if (
            _SAFE_REQUEST_ID_RE.fullmatch(self.request_id) is None
            or self.request_id in {".", ".."}
        ):
            raise ContractValidationError("request_id is not path-safe")
        _required(self.operation_id, "operation_id")
        _validate_operation_parameters(
            self.operation_id,
            self.operation_parameters,
        )
        expected_operation_sha256 = operation_sha256(
            self.operation_id,
            self.operation_parameters,
        )
        if (
            _sha256(self.operation_sha256, "operation_sha256")
            != expected_operation_sha256
        ):
            raise ContractValidationError(
                "typed result operation digest mismatch"
            )
        _sha256(
            self.request_envelope_sha256,
            "request_envelope_sha256",
        )
        expected_argv = render_read_only_operation_argv(
            self.operation_id,
            self.operation_parameters,
        )
        if self.argv != expected_argv:
            raise ContractValidationError("typed execution argv mismatch")
        if self.shell is not False:
            raise ContractValidationError(
                "typed read-only execution must use shell=false"
            )
        _required(self.working_directory, "working_directory")
        if (
            isinstance(self.exit_code, bool)
            or not isinstance(self.exit_code, int)
        ):
            raise ContractValidationError(
                "typed execution exit_code must be integer"
            )
        for value, field_name in (
            (self.started_epoch_seconds, "started_epoch_seconds"),
            (self.finished_epoch_seconds, "finished_epoch_seconds"),
        ):
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or value < 0
            ):
                raise ContractValidationError(
                    f"{field_name} must be a non-negative number"
                )
        if self.finished_epoch_seconds < self.started_epoch_seconds:
            raise ContractValidationError(
                "typed execution finish precedes start"
            )
        if not isinstance(self.timed_out, bool):
            raise ContractValidationError(
                "typed execution timed_out must be boolean"
            )
        if self.timed_out and self.exit_code != 124:
            raise ContractValidationError(
                "typed execution timeout must use exit code 124"
            )
        self._validate_stream(
            name="stdout",
            text=self.stdout,
            digest=self.stdout_sha256,
            total_bytes=self.stdout_bytes,
            truncated=self.stdout_truncated,
        )
        self._validate_stream(
            name="stderr",
            text=self.stderr,
            digest=self.stderr_sha256,
            total_bytes=self.stderr_bytes,
            truncated=self.stderr_truncated,
        )

    def assert_matches(
        self,
        request: TypedRemoteExecutionRequest,
        *,
        request_envelope_sha256: str | None = None,
    ) -> None:
        if not isinstance(request, TypedRemoteExecutionRequest):
            raise ContractValidationError(
                "request must be TypedRemoteExecutionRequest"
            )
        comparisons = (
            ("request_id", self.request_id, request.request_id),
            ("operation_id", self.operation_id, request.operation_id),
            (
                "operation_parameters",
                dict(self.operation_parameters),
                dict(request.operation_parameters),
            ),
            (
                "operation_sha256",
                self.operation_sha256,
                request.operation_sha256,
            ),
            (
                "working_directory",
                self.working_directory,
                request.working_directory,
            ),
        )
        for field_name, observed, expected in comparisons:
            if observed != expected:
                raise ContractValidationError(
                    f"typed execution result {field_name} mismatch"
                )
        if request_envelope_sha256 is not None:
            expected_envelope = _sha256(
                request_envelope_sha256,
                "expected request_envelope_sha256",
            )
            if self.request_envelope_sha256 != expected_envelope:
                raise ContractValidationError(
                    "typed execution result request envelope digest mismatch"
                )

    def assert_succeeded(self) -> None:
        if self.timed_out:
            raise ContractValidationError(
                "typed execution timed out"
            )
        if self.exit_code != 0:
            raise ContractValidationError(
                "typed execution did not exit successfully"
            )


def resolve_authorized_working_directory(
    working_directory: str,
    allowed_roots: Tuple[str, ...] | list[str],
) -> Path:
    _required(working_directory, "working_directory")
    if not isinstance(allowed_roots, (tuple, list)) or not allowed_roots:
        raise ContractValidationError(
            "at least one allowed working root is required"
        )
    try:
        candidate = Path(working_directory).resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise ContractValidationError(
            "working directory cannot be resolved"
        ) from exc
    if not candidate.is_dir():
        raise ContractValidationError(
            "working directory is not a directory"
        )

    for root_value in allowed_roots:
        _required(root_value, "allowed_root")
        try:
            root = Path(root_value).resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise ContractValidationError(
                "allowed working root cannot be resolved"
            ) from exc
        if not root.is_dir():
            raise ContractValidationError(
                "allowed working root is not a directory"
            )
        try:
            candidate.relative_to(root)
            return candidate
        except ValueError:
            continue
    raise ContractValidationError(
        "working directory is outside allowed roots"
    )


def _execute_argv_bounded(
    argv: Tuple[str, ...],
    *,
    cwd: Path,
    timeout_seconds: int = REMOTE_EXECUTION_MAX_RUNTIME_SECONDS,
    max_output_bytes: int = REMOTE_EXECUTION_MAX_OUTPUT_BYTES,
) -> Mapping[str, Any]:
    import os
    import subprocess
    import tempfile
    import time

    if not isinstance(argv, tuple) or not argv or not all(
        isinstance(item, str) and item for item in argv
    ):
        raise ContractValidationError(
            "argv must be a non-empty tuple of strings"
        )
    if not isinstance(cwd, Path) or not cwd.is_dir():
        raise ContractValidationError(
            "cwd must be an existing Path directory"
        )
    if (
        isinstance(timeout_seconds, bool)
        or not isinstance(timeout_seconds, int)
        or timeout_seconds < 1
        or timeout_seconds > REMOTE_EXECUTION_MAX_RUNTIME_SECONDS
    ):
        raise ContractValidationError(
            "timeout_seconds exceeds execution bound"
        )
    if (
        isinstance(max_output_bytes, bool)
        or not isinstance(max_output_bytes, int)
        or max_output_bytes < 1
        or max_output_bytes > REMOTE_EXECUTION_MAX_OUTPUT_BYTES
    ):
        raise ContractValidationError(
            "max_output_bytes exceeds execution bound"
        )
    def summarize(handle) -> tuple[str, str, int, bool]:
        handle.flush()
        handle.seek(0, 2)
        total = handle.tell()
        handle.seek(0)
        digest = hashlib.sha256()
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
        handle.seek(0)
        data = handle.read(max_output_bytes)
        text = data.decode("utf-8", errors="replace")
        return (
            text,
            digest.hexdigest(),
            total,
            total > max_output_bytes,
        )

    process_env = None
    if argv[0] == "git":
        process_env = {
            key: value
            for key, value in os.environ.items()
            if not key.upper().startswith("GIT_")
        }
        process_env.update(
            {
                "GIT_OPTIONAL_LOCKS": "0",
                "GIT_PAGER": "cat",
                "PAGER": "cat",
                "GIT_TERMINAL_PROMPT": "0",
                "GIT_CONFIG_NOSYSTEM": "1",
                "GIT_CONFIG_GLOBAL": os.devnull,
                "GIT_ATTR_NOSYSTEM": "1",
                "GIT_NO_LAZY_FETCH": "1",
                "GIT_WORK_TREE": str(cwd),
            }
        )

    started = time.time()
    with (
        tempfile.TemporaryFile() as stdout_file,
        tempfile.TemporaryFile() as stderr_file,
    ):
        timed_out = False
        try:
            completed = subprocess.run(
                list(argv),
                cwd=str(cwd),
                shell=False,
                stdout=stdout_file,
                stderr=stderr_file,
                timeout=timeout_seconds,
                check=False,
                env=process_env,
            )
            exit_code = completed.returncode
        except subprocess.TimeoutExpired:
            timed_out = True
            exit_code = 124
        finished = time.time()
        (
            stdout,
            stdout_sha256,
            stdout_bytes,
            stdout_truncated,
        ) = summarize(stdout_file)
        (
            stderr,
            stderr_sha256,
            stderr_bytes,
            stderr_truncated,
        ) = summarize(stderr_file)

    return {
        "exit_code": exit_code,
        "timed_out": timed_out,
        "started_epoch_seconds": started,
        "finished_epoch_seconds": finished,
        "stdout": stdout,
        "stderr": stderr,
        "stdout_sha256": stdout_sha256,
        "stderr_sha256": stderr_sha256,
        "stdout_bytes": stdout_bytes,
        "stderr_bytes": stderr_bytes,
        "stdout_truncated": stdout_truncated,
        "stderr_truncated": stderr_truncated,
    }


def execute_read_only_operation_bounded(
    operation_id: str,
    parameters: Mapping[str, Any],
    *,
    cwd: Path,
    timeout_seconds: int = REMOTE_EXECUTION_MAX_RUNTIME_SECONDS,
    max_output_bytes: int = REMOTE_EXECUTION_MAX_OUTPUT_BYTES,
) -> Mapping[str, Any]:
    """Execute one admitted typed operation under fixed resource bounds."""
    argv = render_read_only_operation_argv(operation_id, parameters)
    result = dict(
        _execute_argv_bounded(
            argv,
            cwd=cwd,
            timeout_seconds=timeout_seconds,
            max_output_bytes=max_output_bytes,
        )
    )
    result["argv"] = argv
    return result


__all__ = [
    "READ_ONLY_OPERATION_SPECS",
    "REMOTE_EXECUTION_MAX_OUTPUT_BYTES",
    "REMOTE_EXECUTION_MAX_RUNTIME_SECONDS",
    "ReadOnlyOperationSpec",
    "TYPED_REMOTE_EXECUTION_SCHEMA_VERSION",
    "TYPED_REQUEST_ENVELOPE_SCHEMA_VERSION",
    "TypedRemoteExecutionRequest",
    "TypedRemoteExecutionResult",
    "canonical_typed_request_bytes",
    "execute_read_only_operation_bounded",
    "operation_sha256",
    "render_read_only_operation_argv",
    "resolve_authorized_working_directory",
    "sign_typed_request_hmac_sha256",
    "typed_request_envelope_from_mapping",
    "typed_request_envelope_mapping",
    "validate_git_repository_boundary",
    "verify_typed_request_hmac_sha256",
]


_GIT_CONFIG_MAX_BYTES = 1024 * 1024


def _resolve_allowed_roots(
    allowed_roots: Tuple[str, ...] | list[str],
) -> Tuple[Path, ...]:
    if not isinstance(allowed_roots, (tuple, list)) or not allowed_roots:
        raise ContractValidationError(
            "at least one allowed working root is required"
        )
    resolved = []
    for root_value in allowed_roots:
        _required(root_value, "allowed_root")
        try:
            root = Path(root_value).resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise ContractValidationError(
                "allowed working root cannot be resolved"
            ) from exc
        if not root.is_dir():
            raise ContractValidationError(
                "allowed working root is not a directory"
            )
        resolved.append(root)
    return tuple(resolved)


def _assert_path_within_allowed_roots(
    path: Path,
    allowed_roots: Tuple[Path, ...],
    *,
    field_name: str,
) -> Path:
    try:
        resolved = path.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise ContractValidationError(
            f"{field_name} cannot be resolved"
        ) from exc
    for root in allowed_roots:
        try:
            resolved.relative_to(root)
            return resolved
        except ValueError:
            continue
    raise ContractValidationError(
        f"{field_name} is outside allowed roots"
    )


def _read_small_git_control_file(path: Path, *, field_name: str) -> str:
    try:
        if path.stat().st_size > _GIT_CONFIG_MAX_BYTES:
            raise ContractValidationError(
                f"{field_name} exceeds size bound"
            )
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise ContractValidationError(
            f"{field_name} cannot be read"
        ) from exc


def validate_git_repository_boundary(
    cwd: Path,
    allowed_roots: Tuple[str, ...] | list[str],
) -> Mapping[str, str]:
    """Reject Git metadata/config indirection that escapes executor roots."""
    if not isinstance(cwd, Path) or not cwd.is_dir():
        raise ContractValidationError(
            "cwd must be an existing Path directory"
        )
    roots = _resolve_allowed_roots(allowed_roots)
    _assert_path_within_allowed_roots(
        cwd, roots, field_name="working directory"
    )

    dotgit = cwd / ".git"
    if dotgit.is_dir():
        git_dir = _assert_path_within_allowed_roots(
            dotgit, roots, field_name="git directory"
        )
    elif dotgit.is_file():
        control = _read_small_git_control_file(
            dotgit, field_name=".git control file"
        )
        lines = control.splitlines()
        if len(lines) != 1 or not lines[0].lower().startswith("gitdir:"):
            raise ContractValidationError(
                ".git control file is not an exact gitdir pointer"
            )
        target_text = lines[0].split(":", 1)[1].strip()
        if not target_text:
            raise ContractValidationError(
                ".git control file has blank gitdir"
            )
        target = Path(target_text)
        if not target.is_absolute():
            target = cwd / target
        git_dir = _assert_path_within_allowed_roots(
            target, roots, field_name="git directory"
        )
        if not git_dir.is_dir():
            raise ContractValidationError(
                "git directory is not a directory"
            )
    else:
        raise ContractValidationError(
            "working directory is not an admitted Git worktree"
        )

    common_dir = git_dir
    commondir_file = git_dir / "commondir"
    if commondir_file.exists():
        commondir_file = _assert_path_within_allowed_roots(
            commondir_file,
            roots,
            field_name="git commondir control file",
        )
        common_text = _read_small_git_control_file(
            commondir_file,
            field_name="git commondir control file",
        ).strip()
        if not common_text or "\n" in common_text or "\r" in common_text:
            raise ContractValidationError(
                "git commondir pointer is malformed"
            )
        common_target = Path(common_text)
        if not common_target.is_absolute():
            common_target = git_dir / common_target
        common_dir = _assert_path_within_allowed_roots(
            common_target,
            roots,
            field_name="git common directory",
        )
        if not common_dir.is_dir():
            raise ContractValidationError(
                "git common directory is not a directory"
            )

    for alternate_name in ("alternates", "http-alternates"):
        alternate = common_dir / "objects" / "info" / alternate_name
        if alternate.exists():
            raise ContractValidationError(
                "git object alternates are not admitted"
            )

    config_paths = [common_dir / "config", git_dir / "config.worktree"]
    inspected = []
    for config_path in config_paths:
        if not config_path.exists():
            continue
        resolved_config = _assert_path_within_allowed_roots(
            config_path,
            roots,
            field_name="git config",
        )
        if not resolved_config.is_file():
            raise ContractValidationError(
                "git config is not a regular file"
            )
        config_text = _read_small_git_control_file(
            resolved_config,
            field_name="git config",
        )
        _validate_git_config_policy(config_text)
        inspected.append(str(resolved_config))

    return MappingProxyType(
        {
            "git_dir": str(git_dir),
            "common_dir": str(common_dir),
            "configs_inspected": "|".join(inspected),
        }
    )


_FORBIDDEN_GIT_CONFIG_SECTIONS = frozenset(
    {"include", "includeif", "filter", "diff"}
)
_FORBIDDEN_GIT_CORE_KEYS = frozenset(
    {"worktree", "attributesfile", "excludesfile", "hookspath", "fsmonitor"}
)


def _validate_git_config_policy(config_text: str) -> None:
    current_section = None
    for raw_line in config_text.splitlines():
        stripped = raw_line.strip()
        if not stripped or stripped.startswith(("#", ";")):
            continue
        if stripped.startswith("["):
            end = stripped.find("]")
            if end < 0:
                raise ContractValidationError(
                    "git config contains malformed section header"
                )
            section_text = stripped[1:end].strip()
            if not section_text:
                raise ContractValidationError(
                    "git config contains blank section header"
                )
            section_name = (
                section_text.split(None, 1)[0]
                .split(".", 1)[0]
                .lower()
            )
            current_section = section_name
            if current_section in _FORBIDDEN_GIT_CONFIG_SECTIONS:
                raise ContractValidationError(
                    f"git config section {current_section} is not admitted"
                )
            continue

        if current_section == "core":
            key = stripped.split("=", 1)[0].strip().lower()
            if key in _FORBIDDEN_GIT_CORE_KEYS:
                raise ContractValidationError(
                    f"git core.{key} is not admitted"
                )
