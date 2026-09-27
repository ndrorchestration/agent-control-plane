"""Fail-closed contract for externally executed ACP actions and receipts."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
import re
import sqlite3
from typing import Any, Mapping, Tuple

from .contract.model import ContractValidationError

REMOTE_EXECUTION_SCHEMA_VERSION = "agent-control-plane.remote-execution.v0-candidate"
LEGACY_SIGNED_COMMAND_REQUESTS_DEPRECATED = True
REMOTE_EXECUTION_MAX_TTL_SECONDS = 300
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

READ_ONLY_COMMAND_ALLOWLIST = frozenset(
    {
        "git status --short",
        "git status --porcelain=v1",
        "git rev-parse HEAD",
        "git branch --show-current",
        "git remote get-url origin",
        "git diff --name-only",
        "git diff --cached --check",
    }
)


def assert_read_only_command_allowed(command_or_action: str) -> None:
    """Admit only exact pre-reviewed shell commands on the signed read-only path."""
    action_sha256(command_or_action)
    if command_or_action not in READ_ONLY_COMMAND_ALLOWLIST:
        raise ContractValidationError(
            "command is not in signed read-only allowlist"
        )


def action_sha256(command_or_action: str) -> str:
    if not isinstance(command_or_action, str) or not command_or_action.strip():
        raise ContractValidationError("command_or_action must not be blank")
    return hashlib.sha256(command_or_action.encode("utf-8")).hexdigest()


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
@dataclass(frozen=True)
class RemoteExecutionRequest:
    request_id: str
    device_id: str
    expected_device_identity_fingerprint: str
    expected_device_attestation_level: str
    execution_profile: str
    expected_side_effect_class: str
    working_directory: str
    command_or_action: str
    action_sha256: str
    schema_version: str = REMOTE_EXECUTION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        _required(self.request_id, "request_id")
        _required(self.device_id, "device_id")
        _sha256(self.expected_device_identity_fingerprint, "expected_device_identity_fingerprint")
        _required(self.expected_device_attestation_level, "expected_device_attestation_level")
        _required(self.execution_profile, "execution_profile")
        _required(self.expected_side_effect_class, "expected_side_effect_class")
        _required(self.working_directory, "working_directory")
        expected = action_sha256(self.command_or_action)
        if _sha256(self.action_sha256, "action_sha256") != expected:
            raise ContractValidationError("action_sha256 does not bind command_or_action")
        if self.schema_version != REMOTE_EXECUTION_SCHEMA_VERSION:
            raise ContractValidationError(
                f"unsupported schema_version: {self.schema_version}"
            )


@dataclass(frozen=True)
class RemoteExecutionReceipt:
    request_id: str
    device_id: str
    device_identity_fingerprint: str
    device_attestation_level: str
    execution_profile: str
    side_effect_class: str
    working_directory: str
    command_or_action: str
    action_sha256: str
    exit_code: int
    sequence_number: int
    previous_receipt_sha256: str | None
    clock_rollback_detected: bool
    trusted_time_established: bool
    files_changed: Tuple[str, ...]
    artifacts: Tuple[Mapping[str, Any], ...]
    side_effects: Tuple[Mapping[str, Any] | str, ...]
    not_established: Tuple[str, ...]
    postconditions: Mapping[str, Any]
    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "RemoteExecutionReceipt":
        if not isinstance(data, Mapping):
            raise ContractValidationError("remote execution receipt must be a mapping")
        try:
            device_id = data["device_id"] if "device_id" in data else data["device"]
            receipt = cls(
                request_id=data["request_id"],
                device_id=device_id,
                device_identity_fingerprint=data["device_identity_fingerprint"],
                device_attestation_level=data["device_attestation_level"],
                execution_profile=data["execution_profile"],
                side_effect_class=data["side_effect_class"],
                working_directory=data["working_directory"],
                command_or_action=data["command_or_action"],
                action_sha256=data["action_sha256"],
                exit_code=data["exit_code"],
                sequence_number=data["sequence_number"],
                previous_receipt_sha256=data.get("previous_receipt_sha256"),
                clock_rollback_detected=data["clock_rollback_detected"],
                trusted_time_established=data["trusted_time_established"],
                files_changed=tuple(data.get("files_changed", ())),
                artifacts=tuple(data.get("artifacts", ())),
                side_effects=tuple(data.get("side_effects", ())),
                not_established=tuple(data.get("not_established", ())),
                postconditions=dict(data.get("postconditions", {})),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ContractValidationError("malformed remote execution receipt") from exc
        receipt._validate()
        return receipt

    def _validate(self) -> None:
        _required(self.request_id, "request_id")
        _required(self.device_id, "device_id")
        _sha256(self.device_identity_fingerprint, "device_identity_fingerprint")
        _required(self.device_attestation_level, "device_attestation_level")
        _required(self.execution_profile, "execution_profile")
        _required(self.side_effect_class, "side_effect_class")
        _required(self.working_directory, "working_directory")
        expected = action_sha256(self.command_or_action)
        if _sha256(self.action_sha256, "action_sha256") != expected:
            raise ContractValidationError("receipt action digest mismatch")
        if isinstance(self.exit_code, bool) or not isinstance(self.exit_code, int):
            raise ContractValidationError("exit_code must be an integer")
        if isinstance(self.sequence_number, bool) or not isinstance(self.sequence_number, int) or self.sequence_number < 1:
            raise ContractValidationError("sequence_number must be a positive integer")
        if self.previous_receipt_sha256 is not None:
            _sha256(self.previous_receipt_sha256, "previous_receipt_sha256")
        if not isinstance(self.clock_rollback_detected, bool):
            raise ContractValidationError("clock_rollback_detected must be boolean")
        if not isinstance(self.trusted_time_established, bool):
            raise ContractValidationError("trusted_time_established must be boolean")
        for artifact in self.artifacts:
            if not isinstance(artifact, Mapping):
                raise ContractValidationError("artifact records must be mappings")
            digest = artifact.get("sha256")
            if digest is not None:
                _sha256(digest, "artifact sha256")
    def assert_matches(self, request: RemoteExecutionRequest) -> None:
        if not isinstance(request, RemoteExecutionRequest):
            raise ContractValidationError("request must be RemoteExecutionRequest")
        comparisons = (
            ("request_id", self.request_id, request.request_id),
            ("device_id", self.device_id, request.device_id),
            ("device_identity_fingerprint", self.device_identity_fingerprint, request.expected_device_identity_fingerprint),
            ("device_attestation_level", self.device_attestation_level, request.expected_device_attestation_level),
            ("execution_profile", self.execution_profile, request.execution_profile),
            ("side_effect_class", self.side_effect_class, request.expected_side_effect_class),
            ("working_directory", self.working_directory, request.working_directory),
            ("command_or_action", self.command_or_action, request.command_or_action),
            ("action_sha256", self.action_sha256, request.action_sha256),
        )
        for field_name, observed, expected in comparisons:
            if observed != expected:
                raise ContractValidationError(
                    f"remote execution receipt {field_name} mismatch"
                )

    def assert_completed(self) -> None:
        if self.exit_code != 0:
            raise ContractValidationError("remote execution did not exit successfully")
        if self.postconditions.get("command_completed") is not True:
            raise ContractValidationError("remote execution completion not established")

    def assert_read_only(self) -> None:
        self.assert_completed()
        if self.execution_profile != "READ_ONLY_DISCOVERY":
            raise ContractValidationError("receipt is not READ_ONLY_DISCOVERY")
        if self.side_effect_class != "READ_ONLY":
            raise ContractValidationError("read-only receipt side-effect class mismatch")
        if self.clock_rollback_detected:
            raise ContractValidationError("local clock rollback detected")
        if self.files_changed:
            raise ContractValidationError("read-only execution changed files")
        if self.side_effects:
            raise ContractValidationError("read-only execution reported side effects")
        unchanged = self.postconditions.get("working_tree_unchanged")
        if unchanged is False:
            raise ContractValidationError("read-only execution changed working tree")


@dataclass(frozen=True)
class RemoteExecutionFreshness:
    nonce: str
    issued_at_epoch_seconds: int
    expires_at_epoch_seconds: int

    def __post_init__(self) -> None:
        _required(self.nonce, "nonce")
        if isinstance(self.issued_at_epoch_seconds, bool) or not isinstance(
            self.issued_at_epoch_seconds, int
        ):
            raise ContractValidationError("issued_at_epoch_seconds must be integer")
        if isinstance(self.expires_at_epoch_seconds, bool) or not isinstance(
            self.expires_at_epoch_seconds, int
        ):
            raise ContractValidationError("expires_at_epoch_seconds must be integer")
        if self.expires_at_epoch_seconds <= self.issued_at_epoch_seconds:
            raise ContractValidationError("freshness expiry must follow issue time")
        if self.expires_at_epoch_seconds - self.issued_at_epoch_seconds > REMOTE_EXECUTION_MAX_TTL_SECONDS:
            raise ContractValidationError("freshness ttl exceeds maximum")

    def assert_fresh(self, *, now_epoch_seconds: int) -> None:
        if now_epoch_seconds < self.issued_at_epoch_seconds:
            raise ContractValidationError("remote execution request not yet valid")
        if now_epoch_seconds > self.expires_at_epoch_seconds:
            raise ContractValidationError("remote execution request expired")


class RemoteExecutionReplayGuard:
    """Process-local single-use guard for request identity + nonce pairs."""

    def __init__(self) -> None:
        self._consumed: set[tuple[str, str]] = set()

    def consume(
        self,
        request: RemoteExecutionRequest | TypedRemoteExecutionRequest,
        freshness: RemoteExecutionFreshness,
        *,
        now_epoch_seconds: int,
    ) -> None:
        if not isinstance(request, (RemoteExecutionRequest, TypedRemoteExecutionRequest)):
            raise ContractValidationError("request must be a remote execution request")
        if not isinstance(freshness, RemoteExecutionFreshness):
            raise ContractValidationError("freshness must be RemoteExecutionFreshness")
        freshness.assert_fresh(now_epoch_seconds=now_epoch_seconds)
        key = (request.request_id, freshness.nonce)
        if key in self._consumed:
            raise ContractValidationError("remote execution request replay detected")
        self._consumed.add(key)


def classify_remote_outcome(receipt: RemoteExecutionReceipt) -> str:
    """Return a narrow outcome class; UNKNOWN is fail-closed, never success."""
    if not isinstance(receipt, RemoteExecutionReceipt):
        raise ContractValidationError("receipt must be RemoteExecutionReceipt")
    completed = receipt.postconditions.get("command_completed")
    if completed is not True:
        return "UNKNOWN"
    if receipt.exit_code == 0:
        return "SUCCEEDED"
    return "FAILED"


def assert_known_success(receipt: RemoteExecutionReceipt) -> None:
    outcome = classify_remote_outcome(receipt)
    if outcome != "SUCCEEDED":
        raise ContractValidationError(
            f"remote execution outcome is not known success: {outcome}"
        )


class DurableRemoteExecutionReplayGuard:
    """SQLite-backed single-use guard that survives process restart."""

    def __init__(self, database_path: str | Path) -> None:
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.database_path) as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS consumed_remote_requests (
                    request_id TEXT NOT NULL,
                    nonce TEXT NOT NULL,
                    consumed_at_epoch_seconds INTEGER NOT NULL,
                    PRIMARY KEY (request_id, nonce)
                )
                """
            )

    def is_consumed(
        self,
        request: RemoteExecutionRequest | TypedRemoteExecutionRequest,
        freshness: RemoteExecutionFreshness,
    ) -> bool:
        if not isinstance(
            request,
            (RemoteExecutionRequest, TypedRemoteExecutionRequest),
        ):
            raise ContractValidationError(
                "request must be a remote execution request"
            )
        if not isinstance(freshness, RemoteExecutionFreshness):
            raise ContractValidationError(
                "freshness must be RemoteExecutionFreshness"
            )
        with sqlite3.connect(self.database_path) as connection:
            row = connection.execute(
                """
                SELECT 1
                FROM consumed_remote_requests
                WHERE request_id = ? AND nonce = ?
                LIMIT 1
                """,
                (request.request_id, freshness.nonce),
            ).fetchone()
        return row is not None

    def consume(
        self,
        request: RemoteExecutionRequest | TypedRemoteExecutionRequest,
        freshness: RemoteExecutionFreshness,
        *,
        now_epoch_seconds: int,
    ) -> None:
        if not isinstance(request, (RemoteExecutionRequest, TypedRemoteExecutionRequest)):
            raise ContractValidationError("request must be a remote execution request")
        if not isinstance(freshness, RemoteExecutionFreshness):
            raise ContractValidationError("freshness must be RemoteExecutionFreshness")
        freshness.assert_fresh(now_epoch_seconds=now_epoch_seconds)
        try:
            with sqlite3.connect(self.database_path) as connection:
                connection.execute(
                    """
                    INSERT INTO consumed_remote_requests
                    (request_id, nonce, consumed_at_epoch_seconds)
                    VALUES (?, ?, ?)
                    """,
                    (request.request_id, freshness.nonce, now_epoch_seconds),
                )
        except sqlite3.IntegrityError as exc:
            raise ContractValidationError(
                "remote execution request replay detected"
            ) from exc


def canonical_request_bytes(
    request: RemoteExecutionRequest,
    freshness: RemoteExecutionFreshness,
) -> bytes:
    if not isinstance(request, RemoteExecutionRequest):
        raise ContractValidationError("request must be RemoteExecutionRequest")
    if not isinstance(freshness, RemoteExecutionFreshness):
        raise ContractValidationError("freshness must be RemoteExecutionFreshness")
    payload = {
        "request_id": request.request_id,
        "device_id": request.device_id,
        "expected_device_identity_fingerprint": request.expected_device_identity_fingerprint,
        "expected_device_attestation_level": request.expected_device_attestation_level,
        "execution_profile": request.execution_profile,
        "expected_side_effect_class": request.expected_side_effect_class,
        "working_directory": request.working_directory,
        "command_or_action": request.command_or_action,
        "action_sha256": request.action_sha256,
        "nonce": freshness.nonce,
        "issued_at_epoch_seconds": freshness.issued_at_epoch_seconds,
        "expires_at_epoch_seconds": freshness.expires_at_epoch_seconds,
    }
    import json
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sign_request_hmac_sha256(
    request: RemoteExecutionRequest,
    freshness: RemoteExecutionFreshness,
    *,
    key: bytes,
    allow_legacy: bool = False,
) -> str:
    if not allow_legacy:
        raise ContractValidationError(
            "legacy shell-text request signing is disabled; use typed remote execution"
        )
    if not isinstance(key, (bytes, bytearray)) or len(key) < 32:
        raise ContractValidationError("signing key must be at least 32 bytes")
    import hmac
    return hmac.new(bytes(key), canonical_request_bytes(request, freshness), hashlib.sha256).hexdigest()


def verify_request_hmac_sha256(
    request: RemoteExecutionRequest,
    freshness: RemoteExecutionFreshness,
    *,
    key: bytes,
    signature: str,
) -> None:
    import hmac
    _sha256(signature, "signature")
    expected = sign_request_hmac_sha256(
        request, freshness, key=key, allow_legacy=True
    )
    if not hmac.compare_digest(expected, signature):
        raise ContractValidationError("remote execution request signature mismatch")


def canonical_receipt_bytes(receipt: RemoteExecutionReceipt) -> bytes:
    if not isinstance(receipt, RemoteExecutionReceipt):
        raise ContractValidationError("receipt must be RemoteExecutionReceipt")
    payload = {
        "request_id": receipt.request_id,
        "device_id": receipt.device_id,
        "device_identity_fingerprint": receipt.device_identity_fingerprint,
        "device_attestation_level": receipt.device_attestation_level,
        "execution_profile": receipt.execution_profile,
        "side_effect_class": receipt.side_effect_class,
        "working_directory": receipt.working_directory,
        "command_or_action": receipt.command_or_action,
        "action_sha256": receipt.action_sha256,
        "exit_code": receipt.exit_code,
        "sequence_number": receipt.sequence_number,
        "previous_receipt_sha256": receipt.previous_receipt_sha256,
        "clock_rollback_detected": receipt.clock_rollback_detected,
        "trusted_time_established": receipt.trusted_time_established,
        "files_changed": list(receipt.files_changed),
        "artifacts": [dict(item) for item in receipt.artifacts],
        "side_effects": [dict(item) if isinstance(item, Mapping) else item for item in receipt.side_effects],
        "not_established": list(receipt.not_established),
        "postconditions": dict(receipt.postconditions),
    }
    import json
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sign_receipt_hmac_sha256(receipt: RemoteExecutionReceipt, *, key: bytes) -> str:
    if not isinstance(key, (bytes, bytearray)) or len(key) < 32:
        raise ContractValidationError("signing key must be at least 32 bytes")
    import hmac
    return hmac.new(bytes(key), canonical_receipt_bytes(receipt), hashlib.sha256).hexdigest()


def verify_receipt_hmac_sha256(
    receipt: RemoteExecutionReceipt,
    *,
    key: bytes,
    signature: str,
) -> None:
    import hmac
    _sha256(signature, "signature")
    expected = sign_receipt_hmac_sha256(receipt, key=key)
    if not hmac.compare_digest(expected, signature):
        raise ContractValidationError("remote execution receipt signature mismatch")


def verify_detached_receipt_file_hmac(
    receipt_path: str | Path,
    signature_path: str | Path,
    *,
    key: bytes,
) -> None:
    import hmac
    receipt = Path(receipt_path)
    signature_file = Path(signature_path)
    if not receipt.is_file():
        raise ContractValidationError("receipt file missing")
    if not signature_file.is_file():
        raise ContractValidationError("receipt signature file missing")
    if not isinstance(key, (bytes, bytearray)) or len(key) < 32:
        raise ContractValidationError("signing key must be at least 32 bytes")
    signature = signature_file.read_text(encoding="ascii").strip()
    _sha256(signature, "signature")
    expected = hmac.new(bytes(key), receipt.read_bytes(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature):
        raise ContractValidationError("detached receipt file signature mismatch")


def verify_receipt_signature_envelope(
    receipt_path: str | Path,
    envelope_path: str | Path,
    *,
    key: bytes,
) -> None:
    import hmac
    import json

    receipt = Path(receipt_path)
    envelope_file = Path(envelope_path)
    if not receipt.is_file():
        raise ContractValidationError("receipt file missing")
    if not envelope_file.is_file():
        raise ContractValidationError("receipt signature envelope missing")
    if not isinstance(key, (bytes, bytearray)) or len(key) < 32:
        raise ContractValidationError("signing key must be at least 32 bytes")

    try:
        envelope = json.loads(envelope_file.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise ContractValidationError("malformed receipt signature envelope") from exc

    if envelope.get("schema_version") != "ndr.receipt-signature.v1":
        raise ContractValidationError("unsupported receipt signature envelope")
    if envelope.get("algorithm") != "HMAC-SHA256":
        raise ContractValidationError("unsupported receipt signature algorithm")

    receipt_bytes = receipt.read_bytes()
    observed_receipt_sha256 = hashlib.sha256(receipt_bytes).hexdigest()
    if envelope.get("receipt_sha256") != observed_receipt_sha256:
        raise ContractValidationError("receipt sha256 mismatch")

    expected_key_id = hashlib.sha256(bytes(key)).hexdigest()[:16]
    if envelope.get("key_id") != expected_key_id:
        raise ContractValidationError("receipt signature key id mismatch")

    signature = envelope.get("signature")
    _sha256(signature, "signature")
    expected = hmac.new(bytes(key), receipt_bytes, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature):
        raise ContractValidationError("receipt signature envelope mismatch")


def verify_receipt_chain_link(
    previous_receipt_path: str | Path,
    current_receipt_path: str | Path,
) -> None:
    import json

    previous_path = Path(previous_receipt_path)
    current_path = Path(current_receipt_path)
    if not previous_path.is_file():
        raise ContractValidationError("previous receipt file missing")
    if not current_path.is_file():
        raise ContractValidationError("current receipt file missing")

    try:
        previous_data = json.loads(previous_path.read_text(encoding="utf-8-sig"))
        current_data = json.loads(current_path.read_text(encoding="utf-8-sig"))
    except (json.JSONDecodeError, OSError) as exc:
        raise ContractValidationError("malformed receipt chain input") from exc

    previous = RemoteExecutionReceipt.from_mapping(previous_data)
    current = RemoteExecutionReceipt.from_mapping(current_data)

    expected_previous_hash = hashlib.sha256(previous_path.read_bytes()).hexdigest()
    if current.previous_receipt_sha256 != expected_previous_hash:
        raise ContractValidationError("previous receipt hash link mismatch")
    if current.sequence_number != previous.sequence_number + 1:
        raise ContractValidationError("receipt sequence is not contiguous")

# Temporary compatibility re-exports for callers that imported the v2 API
# from remote_execution_adapter during the candidate phase.
from .typed_remote_execution import (
    READ_ONLY_OPERATION_SPECS,
    REMOTE_EXECUTION_MAX_OUTPUT_BYTES,
    REMOTE_EXECUTION_MAX_RUNTIME_SECONDS,
    TYPED_REMOTE_EXECUTION_SCHEMA_VERSION,
    TYPED_REQUEST_ENVELOPE_SCHEMA_VERSION,
    ReadOnlyOperationSpec,
    TypedRemoteExecutionRequest,
    TypedRemoteExecutionResult,
    canonical_typed_request_bytes,
    execute_read_only_operation_bounded,
    operation_sha256,
    render_read_only_operation_argv,
    resolve_authorized_working_directory,
    sign_typed_request_hmac_sha256,
    typed_request_envelope_from_mapping,
    typed_request_envelope_mapping,
    verify_typed_request_hmac_sha256,
)
