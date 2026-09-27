"""Bind external mutation result evidence to the exact non-executing ACP control chain."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json

from .remote_mutation_journal import MutationJournalRecord, MutationJournalState
from .remote_mutation_postcondition import MutationPostconditionRecord
from .remote_mutation_transaction import MutationPlan

MUTATION_EXECUTION_EVIDENCE_SCHEMA_VERSION = (
    "agent-control-plane.remote-mutation-execution-evidence.v0-candidate"
)


class MutationExecutionEvidenceError(ValueError):
    pass


def _required(value: str, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise MutationExecutionEvidenceError(f"{field} must not be blank")
    return value.strip()


def _sha256(value: str, field: str) -> str:
    value = _required(value, field)
    if len(value) != 64 or any(ch not in "0123456789abcdef" for ch in value):
        raise MutationExecutionEvidenceError(f"{field} must be lowercase sha256")
    return value


@dataclass(frozen=True)
class ExternalMutationExecutionEvidence:
    executor_id: str
    execution_id: str
    transaction_id: str
    request_id: str
    resource_id: str
    operation_id: str
    plan_sha256: str
    result_sha256: str
    external_effect_sha256: str
    postcondition_evidence_sha256: str

    def __post_init__(self) -> None:
        for field in (
            "executor_id", "execution_id", "transaction_id", "request_id",
            "resource_id", "operation_id",
        ):
            object.__setattr__(self, field, _required(getattr(self, field), field))
        for field in (
            "plan_sha256", "result_sha256", "external_effect_sha256",
            "postcondition_evidence_sha256",
        ):
            object.__setattr__(self, field, _sha256(getattr(self, field), field))

    def canonical_bytes(self) -> bytes:
        payload = {
            "execution_id": self.execution_id,
            "executor_id": self.executor_id,
            "external_effect_sha256": self.external_effect_sha256,
            "operation_id": self.operation_id,
            "plan_sha256": self.plan_sha256,
            "postcondition_evidence_sha256": self.postcondition_evidence_sha256,
            "request_id": self.request_id,
            "resource_id": self.resource_id,
            "result_sha256": self.result_sha256,
            "transaction_id": self.transaction_id,
        }
        return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")

    @property
    def evidence_sha256(self) -> str:
        return hashlib.sha256(self.canonical_bytes()).hexdigest()


@dataclass(frozen=True)
class MutationExecutionEvidenceReceipt:
    transaction_id: str
    execution_id: str
    executor_id: str
    request_id: str
    resource_id: str
    operation_id: str
    plan_sha256: str
    result_sha256: str
    external_effect_sha256: str
    postcondition_evidence_sha256: str
    evidence_sha256: str
    evidence_bound: bool
    reason: str
    execution_authorized: bool = False
    acp_mutation_executed: bool = False
    schema_version: str = MUTATION_EXECUTION_EVIDENCE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        for field in (
            "plan_sha256", "result_sha256", "external_effect_sha256",
            "postcondition_evidence_sha256", "evidence_sha256",
        ):
            _sha256(getattr(self, field), field)
        if self.execution_authorized is not False or self.acp_mutation_executed is not False:
            raise MutationExecutionEvidenceError(
                "execution evidence cannot authorize or claim ACP mutation execution"
            )


def bind_mutation_execution_evidence(
    plan: MutationPlan,
    journal: MutationJournalRecord,
    postcondition: MutationPostconditionRecord,
    evidence: ExternalMutationExecutionEvidence,
) -> MutationExecutionEvidenceReceipt:
    """Bind caller-supplied external execution evidence to exact ACP records."""
    if not isinstance(plan, MutationPlan):
        raise TypeError("plan must be MutationPlan")
    if not isinstance(journal, MutationJournalRecord):
        raise TypeError("journal must be MutationJournalRecord")
    if not isinstance(postcondition, MutationPostconditionRecord):
        raise TypeError("postcondition must be MutationPostconditionRecord")
    if not isinstance(evidence, ExternalMutationExecutionEvidence):
        raise TypeError("evidence must be ExternalMutationExecutionEvidence")

    mismatches: list[str] = []
    if (
        journal.request_id != plan.request_id
        or journal.resource_id != plan.resource_id
        or journal.operation_id != plan.operation_id
        or journal.plan_sha256 != plan.plan_sha256
        or journal.rollback_descriptor_sha256 != plan.rollback_sha256
    ):
        mismatches.append("journal.plan_identity")

    if (
        postcondition.request_id != plan.request_id
        or postcondition.resource_id != plan.resource_id
        or postcondition.operation_id != plan.operation_id
        or postcondition.plan_sha256 != plan.plan_sha256
        or postcondition.rollback_descriptor_sha256 != journal.rollback_descriptor_sha256
        or postcondition.rollback_descriptor_sha256 != plan.rollback_sha256
        or postcondition.rollback_custody_ref != journal.custody_ref
        or postcondition.postcondition_verified is not True
        or postcondition.execution_enabled is not False
        or postcondition.mutation_executed is not False
    ):
        mismatches.append("postcondition")

    if (
        evidence.transaction_id != journal.transaction_id
        or evidence.request_id != plan.request_id
        or evidence.resource_id != plan.resource_id
        or evidence.operation_id != plan.operation_id
        or evidence.plan_sha256 != plan.plan_sha256
    ):
        mismatches.append("evidence.plan_identity")

    effect_events = [
        event for event in journal.events
        if event.state is MutationJournalState.EXTERNAL_EFFECT_REPORTED
    ]
    post_events = [
        event for event in journal.events
        if event.state is MutationJournalState.POSTCONDITION_VERIFIED
    ]
    if len(effect_events) != 1:
        mismatches.append("journal.external_effect_event")
    elif effect_events[0].evidence_sha256 != evidence.external_effect_sha256:
        mismatches.append("external_effect_sha256")

    if journal.current_state is not MutationJournalState.POSTCONDITION_VERIFIED:
        mismatches.append("journal.current_state")
    if len(post_events) != 1:
        mismatches.append("journal.postcondition_event")
    elif post_events[0].evidence_sha256 != evidence.postcondition_evidence_sha256:
        mismatches.append("postcondition_evidence_sha256")

    bound = not mismatches
    reason = (
        "external result evidence is congruent with exact ACP plan, journal, and verified postcondition; execution remains unauthorized"
        if bound
        else "execution evidence blocked:" + ",".join(mismatches)
    )

    return MutationExecutionEvidenceReceipt(
        transaction_id=evidence.transaction_id,
        execution_id=evidence.execution_id,
        executor_id=evidence.executor_id,
        request_id=evidence.request_id,
        resource_id=evidence.resource_id,
        operation_id=evidence.operation_id,
        plan_sha256=evidence.plan_sha256,
        result_sha256=evidence.result_sha256,
        external_effect_sha256=evidence.external_effect_sha256,
        postcondition_evidence_sha256=evidence.postcondition_evidence_sha256,
        evidence_sha256=evidence.evidence_sha256,
        evidence_bound=bound,
        reason=reason,
    )