"""Non-executing rollback-material custody admission for repository mutations."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import hashlib
import json

from .remote_mutation_composition import MutationCompositionRecord
from .remote_mutation_path_safety import MutationPathSafetyRecord
from .remote_mutation_transaction import MutationPlan, MutationTransactionReceipt

ROLLBACK_CUSTODY_SCHEMA_VERSION = (
    "agent-control-plane.remote-mutation-rollback-custody.v0-candidate"
)


class RollbackCustodyError(ValueError):
    pass


class RollbackMode(str, Enum):
    RESTORE_FILE_BYTES = "restore_file_bytes"
    DELETE_CREATED_FILE = "delete_created_file"


def _required(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RollbackCustodyError(f"{field_name} must not be blank")
    return value.strip()


def _sha256(value: str, field_name: str) -> str:
    value = _required(value, field_name)
    if len(value) != 64 or any(ch not in "0123456789abcdef" for ch in value):
        raise RollbackCustodyError(f"{field_name} must be lowercase sha256")
    return value


@dataclass(frozen=True)
class RollbackMaterialDescriptor:
    operation_id: str
    path: str
    mode: RollbackMode
    prior_content_sha256: str | None = None
    prior_content_size: int | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "operation_id", _required(self.operation_id, "operation_id"))
        if not isinstance(self.path, str) or not self.path:
            raise RollbackCustodyError("path must not be blank")
        if not isinstance(self.mode, RollbackMode):
            raise RollbackCustodyError("mode must be RollbackMode")

        if self.mode is RollbackMode.RESTORE_FILE_BYTES:
            if self.prior_content_sha256 is None:
                raise RollbackCustodyError(
                    "restore_file_bytes requires prior_content_sha256"
                )
            object.__setattr__(
                self,
                "prior_content_sha256",
                _sha256(self.prior_content_sha256, "prior_content_sha256"),
            )
            if (
                isinstance(self.prior_content_size, bool)
                or not isinstance(self.prior_content_size, int)
                or self.prior_content_size < 0
            ):
                raise RollbackCustodyError(
                    "restore_file_bytes requires non-negative prior_content_size"
                )
        else:
            if self.prior_content_sha256 is not None or self.prior_content_size is not None:
                raise RollbackCustodyError(
                    "delete_created_file must not carry prior file material"
                )

    def canonical_bytes(self) -> bytes:
        payload = {
            "mode": self.mode.value,
            "operation_id": self.operation_id,
            "path": self.path,
            "prior_content_sha256": self.prior_content_sha256,
            "prior_content_size": self.prior_content_size,
        }
        return json.dumps(
            payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")

    @property
    def descriptor_sha256(self) -> str:
        return hashlib.sha256(self.canonical_bytes()).hexdigest()


@dataclass(frozen=True)
class RollbackCustodyEvidence:
    request_id: str
    resource_id: str
    operation_id: str
    plan_sha256: str
    descriptor_sha256: str
    custody_ref: str
    custody_object_sha256: str
    observed_readback_sha256: str

    def __post_init__(self) -> None:
        for field in ("request_id", "resource_id", "operation_id", "custody_ref"):
            object.__setattr__(self, field, _required(getattr(self, field), field))
        for field in (
            "plan_sha256",
            "descriptor_sha256",
            "custody_object_sha256",
            "observed_readback_sha256",
        ):
            object.__setattr__(self, field, _sha256(getattr(self, field), field))


@dataclass(frozen=True)
class RollbackCustodyAdmissionRecord:
    request_id: str
    resource_id: str
    operation_id: str
    plan_sha256: str
    descriptor_sha256: str
    custody_ref: str
    admitted: bool
    reason: str
    readback_verified: bool
    execution_enabled: bool = False
    mutation_executed: bool = False
    schema_version: str = ROLLBACK_CUSTODY_SCHEMA_VERSION

    def __post_init__(self) -> None:
        for field in ("request_id", "resource_id", "operation_id", "custody_ref"):
            object.__setattr__(self, field, _required(getattr(self, field), field))
        _sha256(self.plan_sha256, "plan_sha256")
        _sha256(self.descriptor_sha256, "descriptor_sha256")
        if self.execution_enabled is not False or self.mutation_executed is not False:
            raise RollbackCustodyError(
                "rollback custody cannot enable or claim mutation execution"
            )
        if self.admitted and self.readback_verified is not True:
            raise RollbackCustodyError(
                "admitted rollback custody requires verified readback"
            )


def admit_rollback_custody(
    composition: MutationCompositionRecord,
    plan: MutationPlan,
    transaction: MutationTransactionReceipt,
    path_safety: MutationPathSafetyRecord,
    descriptor: RollbackMaterialDescriptor,
    evidence: RollbackCustodyEvidence,
) -> RollbackCustodyAdmissionRecord:
    """Bind rollback descriptor and caller-observed custody evidence without execution."""
    if not isinstance(composition, MutationCompositionRecord):
        raise TypeError("composition must be MutationCompositionRecord")
    if not isinstance(plan, MutationPlan):
        raise TypeError("plan must be MutationPlan")
    if not isinstance(transaction, MutationTransactionReceipt):
        raise TypeError("transaction must be MutationTransactionReceipt")
    if not isinstance(path_safety, MutationPathSafetyRecord):
        raise TypeError("path_safety must be MutationPathSafetyRecord")
    if not isinstance(descriptor, RollbackMaterialDescriptor):
        raise TypeError("descriptor must be RollbackMaterialDescriptor")
    if not isinstance(evidence, RollbackCustodyEvidence):
        raise TypeError("evidence must be RollbackCustodyEvidence")

    descriptor_hash = descriptor.descriptor_sha256
    mismatches: list[str] = []

    if composition.admitted is not True:
        mismatches.append("composition.admitted")
    if composition.execution_enabled is not False or composition.mutation_executed is not False:
        raise RollbackCustodyError("composition unexpectedly enables or claims execution")

    if (
        composition.request_id != plan.request_id
        or composition.resource_id != plan.resource_id
        or composition.operation_id != plan.operation_id
        or composition.plan_sha256 != plan.plan_sha256
    ):
        mismatches.append("composition.plan_identity")

    if (
        transaction.request_id != plan.request_id
        or transaction.authority_id != plan.authority_id
        or transaction.operation_id != plan.operation_id
        or transaction.plan_sha256 != plan.plan_sha256
    ):
        mismatches.append("transaction.plan_identity")
    if (
        transaction.preconditions_verified is not True
        or transaction.rollback_available is not True
    ):
        mismatches.append("transaction.rollback_ready")
    if transaction.execution_enabled is not False or transaction.mutation_executed is not False:
        raise RollbackCustodyError("transaction unexpectedly enables or claims execution")

    if (
        path_safety.admitted is not True
        or path_safety.request_id != plan.request_id
        or path_safety.resource_id != plan.resource_id
        or path_safety.operation_id != plan.operation_id
        or path_safety.plan_sha256 != plan.plan_sha256
        or path_safety.requested_path != plan.parameters["path"]
    ):
        mismatches.append("path_safety")
    if path_safety.execution_enabled is not False or path_safety.mutation_executed is not False:
        raise RollbackCustodyError("path safety unexpectedly enables or claims execution")

    if descriptor.operation_id != plan.operation_id or descriptor.path != plan.parameters["path"]:
        mismatches.append("descriptor.plan_identity")
    if descriptor_hash != plan.rollback_sha256:
        mismatches.append("descriptor.rollback_sha256")

    if plan.operation_id == "repo.delete_file":
        if descriptor.mode is not RollbackMode.RESTORE_FILE_BYTES:
            mismatches.append("descriptor.mode")
        if descriptor.prior_content_sha256 != plan.parameters["prior_content_sha256"]:
            mismatches.append("descriptor.prior_content_sha256")
    elif plan.operation_id == "repo.write_text_file":
        expected_mode = (
            RollbackMode.RESTORE_FILE_BYTES
            if path_safety.target_exists
            else RollbackMode.DELETE_CREATED_FILE
        )
        if descriptor.mode is not expected_mode:
            mismatches.append("descriptor.mode")
    else:
        mismatches.append("operation_id")

    if (
        evidence.request_id != plan.request_id
        or evidence.resource_id != plan.resource_id
        or evidence.operation_id != plan.operation_id
        or evidence.plan_sha256 != plan.plan_sha256
    ):
        mismatches.append("evidence.plan_identity")
    if evidence.descriptor_sha256 != descriptor_hash:
        mismatches.append("evidence.descriptor_sha256")

    expected_custody_object_sha256 = (
        descriptor.prior_content_sha256
        if descriptor.mode is RollbackMode.RESTORE_FILE_BYTES
        else descriptor_hash
    )
    if evidence.custody_object_sha256 != expected_custody_object_sha256:
        mismatches.append("evidence.custody_object_sha256")

    readback_verified = (
        evidence.observed_readback_sha256 == evidence.custody_object_sha256
    )
    if not readback_verified:
        mismatches.append("evidence.readback_sha256")

    admitted = not mismatches
    reason = (
        "rollback descriptor and custody readback are congruent; execution remains disabled"
        if admitted
        else "rollback custody blocked:" + ",".join(mismatches)
    )
    return RollbackCustodyAdmissionRecord(
        request_id=plan.request_id,
        resource_id=plan.resource_id,
        operation_id=plan.operation_id,
        plan_sha256=plan.plan_sha256,
        descriptor_sha256=descriptor_hash,
        custody_ref=evidence.custody_ref,
        admitted=admitted,
        reason=reason,
        readback_verified=readback_verified,
    )
