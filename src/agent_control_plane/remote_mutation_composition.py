"""Compose mutation authority admission with an exact transaction plan.

This layer prevents plan substitution after authority admission while remaining
strictly non-executing.
"""

from __future__ import annotations

from dataclasses import dataclass

from .remote_mutation_admission import RemoteMutationAdmissionRecord, RemoteMutationIntent
from .remote_mutation_transaction import MutationPlan, MutationTransactionReceipt

MUTATION_COMPOSITION_SCHEMA_VERSION = "agent-control-plane.remote-mutation-composition.v0-candidate"


class MutationCompositionError(ValueError):
    pass


@dataclass(frozen=True)
class MutationCompositionRecord:
    request_id: str
    authority_id: str
    operation_id: str
    resource_id: str
    plan_sha256: str
    admitted: bool
    reason: str
    execution_enabled: bool = False
    mutation_executed: bool = False
    schema_version: str = MUTATION_COMPOSITION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.execution_enabled is not False or self.mutation_executed is not False:
            raise MutationCompositionError("composition cannot enable or claim execution")


def compose_mutation_admission_and_plan(
    intent: RemoteMutationIntent,
    admission: RemoteMutationAdmissionRecord,
    plan: MutationPlan,
    transaction: MutationTransactionReceipt,
) -> MutationCompositionRecord:
    """Bind admission + plan + prepared transaction without enabling execution."""
    if not isinstance(intent, RemoteMutationIntent):
        raise TypeError("intent must be RemoteMutationIntent")
    if not isinstance(admission, RemoteMutationAdmissionRecord):
        raise TypeError("admission must be RemoteMutationAdmissionRecord")
    if not isinstance(plan, MutationPlan):
        raise TypeError("plan must be MutationPlan")
    if not isinstance(transaction, MutationTransactionReceipt):
        raise TypeError("transaction must be MutationTransactionReceipt")

    if admission.admitted is not True:
        return MutationCompositionRecord(
            request_id=intent.request_id,
            authority_id=admission.authority_id or "UNRESOLVED",
            operation_id=intent.operation_id,
            resource_id=intent.resource_id,
            plan_sha256=plan.plan_sha256,
            admitted=False,
            reason="mutation authority admission not satisfied",
        )
    if admission.execution_enabled is not False:
        raise MutationCompositionError("admission unexpectedly enables execution")

    mismatches = []
    if intent.request_id != admission.request_id or intent.request_id != plan.request_id:
        mismatches.append("request_id")
    if admission.authority_id != plan.authority_id:
        mismatches.append("authority_id")
    if intent.operation_id != plan.operation_id:
        mismatches.append("operation_id")
    if intent.resource_id != plan.resource_id:
        mismatches.append("resource_id")
    if intent.resource_type != plan.resource_type:
        mismatches.append("resource_type")
    if transaction.request_id != plan.request_id:
        mismatches.append("transaction.request_id")
    if transaction.authority_id != plan.authority_id:
        mismatches.append("transaction.authority_id")
    if transaction.operation_id != plan.operation_id:
        mismatches.append("transaction.operation_id")
    if transaction.plan_sha256 != plan.plan_sha256:
        mismatches.append("transaction.plan_sha256")
    if transaction.execution_enabled is not False or transaction.mutation_executed is not False:
        raise MutationCompositionError("transaction unexpectedly enables or claims execution")

    if mismatches:
        return MutationCompositionRecord(
            request_id=intent.request_id,
            authority_id=admission.authority_id or "UNRESOLVED",
            operation_id=intent.operation_id,
            resource_id=intent.resource_id,
            plan_sha256=plan.plan_sha256,
            admitted=False,
            reason="composition mismatch:" + ",".join(mismatches),
        )

    if transaction.preconditions_verified is not True or transaction.rollback_available is not True:
        return MutationCompositionRecord(
            request_id=intent.request_id,
            authority_id=admission.authority_id or "UNRESOLVED",
            operation_id=intent.operation_id,
            resource_id=intent.resource_id,
            plan_sha256=plan.plan_sha256,
            admitted=False,
            reason="transaction preconditions or rollback not verified",
        )

    return MutationCompositionRecord(
        request_id=intent.request_id,
        authority_id=admission.authority_id or "UNRESOLVED",
        operation_id=intent.operation_id,
        resource_id=intent.resource_id,
        plan_sha256=plan.plan_sha256,
        admitted=True,
        reason="authority and exact transaction plan are congruent; execution remains disabled",
    )
