"""Read-only rollback custody material readback preflight.

The caller supplies material already retrieved from custody. ACP verifies exact
identity without consuming authorization and without performing rollback.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib

from .remote_mutation_rollback_authorization import RepositoryRollbackAuthorization
from .remote_mutation_rollback_plan import RepositoryRollbackPlan, RollbackAction
from .remote_mutation_rollback_custody import (
    RollbackMaterialDescriptor,
    RollbackMode,
)

ROLLBACK_MATERIAL_READBACK_SCHEMA_VERSION = (
    "agent-control-plane.remote-mutation-rollback-material-readback.v0-candidate"
)


class RollbackMaterialReadbackError(ValueError):
    pass


@dataclass(frozen=True)
class RollbackMaterialReadbackRecord:
    authorization_id: str
    rollback_transaction_id: str
    rollback_plan_sha256: str
    rollback_descriptor_sha256: str
    rollback_custody_ref: str
    action: RollbackAction
    material_required: bool
    observed_material_sha256: str | None
    observed_material_size: int | None
    admitted: bool
    reason: str
    authorization_consumed: bool
    execution_enabled: bool = False
    rollback_executed: bool = False
    schema_version: str = ROLLBACK_MATERIAL_READBACK_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.execution_enabled is not False or self.rollback_executed is not False:
            raise RollbackMaterialReadbackError(
                "material readback cannot enable or claim rollback execution"
            )
        if self.admitted and self.authorization_consumed:
            raise RollbackMaterialReadbackError(
                "admitted material readback requires unconsumed authorization"
            )


def verify_rollback_material_readback(
    plan: RepositoryRollbackPlan,
    descriptor: RollbackMaterialDescriptor,
    authorization: RepositoryRollbackAuthorization,
    *,
    material: bytes | None,
) -> RollbackMaterialReadbackRecord:
    """Verify caller-retrieved rollback material against exact custody identity."""
    if not isinstance(plan, RepositoryRollbackPlan):
        raise TypeError("plan must be RepositoryRollbackPlan")
    if not isinstance(descriptor, RollbackMaterialDescriptor):
        raise TypeError("descriptor must be RollbackMaterialDescriptor")
    if not isinstance(authorization, RepositoryRollbackAuthorization):
        raise TypeError("authorization must be RepositoryRollbackAuthorization")
    if plan.execution_enabled is not False or plan.rollback_executed is not False:
        raise RollbackMaterialReadbackError("rollback plan unexpectedly enables execution")
    if authorization.rollback_executed is not False:
        raise RollbackMaterialReadbackError(
            "rollback authorization unexpectedly claims execution"
        )

    mismatches: list[str] = []
    if (
        authorization.rollback_transaction_id != plan.rollback_transaction_id
        or authorization.rollback_request_id != plan.rollback_request_id
        or authorization.rollback_authority_id != plan.rollback_authority_id
        or authorization.rollback_plan_sha256 != plan.rollback_plan_sha256
        or authorization.original_transaction_id != plan.original_transaction_id
        or authorization.original_plan_sha256 != plan.original_plan_sha256
        or authorization.rollback_descriptor_sha256
        != plan.rollback_descriptor_sha256
        or authorization.rollback_custody_ref != plan.rollback_custody_ref
    ):
        mismatches.append("authorization.plan_identity")

    if (
        descriptor.operation_id != plan.original_operation_id
        or descriptor.path != plan.requested_path
        or descriptor.descriptor_sha256 != plan.rollback_descriptor_sha256
    ):
        mismatches.append("descriptor.plan_identity")

    if authorization.consumed:
        mismatches.append("authorization.consumed")

    material_required = plan.action is RollbackAction.RESTORE_FILE_BYTES
    observed_sha: str | None = None
    observed_size: int | None = None

    if material_required:
        if descriptor.mode is not RollbackMode.RESTORE_FILE_BYTES:
            mismatches.append("descriptor.mode")
        if not isinstance(material, bytes):
            mismatches.append("material.missing")
        else:
            observed_sha = hashlib.sha256(material).hexdigest()
            observed_size = len(material)
            if descriptor.prior_content_sha256 != observed_sha:
                mismatches.append("material.sha256")
            if descriptor.prior_content_size != observed_size:
                mismatches.append("material.size")
            if plan.desired_content_sha256 != observed_sha:
                mismatches.append("plan.desired_content_sha256")
    else:
        if descriptor.mode is not RollbackMode.DELETE_CREATED_FILE:
            mismatches.append("descriptor.mode")
        if material is not None:
            mismatches.append("material.unexpected")
        if plan.desired_target_exists or plan.desired_content_sha256 is not None:
            mismatches.append("plan.desired_state")

    admitted = not mismatches
    reason = (
        "rollback custody material readback verified; authorization remains unconsumed"
        if admitted
        else "rollback material readback blocked:" + ",".join(mismatches)
    )
    return RollbackMaterialReadbackRecord(
        authorization_id=authorization.authorization_id,
        rollback_transaction_id=plan.rollback_transaction_id,
        rollback_plan_sha256=plan.rollback_plan_sha256,
        rollback_descriptor_sha256=plan.rollback_descriptor_sha256,
        rollback_custody_ref=plan.rollback_custody_ref,
        action=plan.action,
        material_required=material_required,
        observed_material_sha256=observed_sha,
        observed_material_size=observed_size,
        admitted=admitted,
        reason=reason,
        authorization_consumed=authorization.consumed,
    )
