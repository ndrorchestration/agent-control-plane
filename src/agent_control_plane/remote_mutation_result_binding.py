"""Bind external mutation-result evidence to ACP mutation safety records.

This module does not authenticate an executor or authorize/perform mutation.
SHA-256 values provide content identity only.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
import hashlib
import json

from .remote_mutation_journal import (
    MutationJournalRecord,
    MutationJournalState,
    MutationRecoveryAssessment,
    MutationRecoveryDisposition,
)
from .remote_mutation_postcondition import MutationPostconditionRecord

MUTATION_RESULT_BINDING_SCHEMA_VERSION = (
    "agent-control-plane.remote-mutation-result-binding.v0-candidate"
)


class MutationResultBindingError(ValueError):
    pass


def _required(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise MutationResultBindingError(f"{field_name} must not be blank")
    return value.strip()


def _sha256(value: str, field_name: str) -> str:
    value = _required(value, field_name)
    if len(value) != 64 or any(ch not in "0123456789abcdef" for ch in value):
        raise MutationResultBindingError(f"{field_name} must be lowercase sha256")
    return value


class MutationExternalOutcome(str, Enum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    UNKNOWN = "unknown"


def canonical_postcondition_bytes(record: MutationPostconditionRecord) -> bytes:
    if not isinstance(record, MutationPostconditionRecord):
        raise TypeError("record must be MutationPostconditionRecord")
    return json.dumps(
        asdict(record),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def mutation_postcondition_sha256(record: MutationPostconditionRecord) -> str:
    return hashlib.sha256(canonical_postcondition_bytes(record)).hexdigest()


@dataclass(frozen=True)
class MutationExternalResultReceipt:
    execution_id: str
    executor_ref: str
    request_id: str
    resource_id: str
    operation_id: str
    plan_sha256: str
    journal_id: str
    rollback_descriptor_sha256: str
    rollback_custody_ref: str
    outcome: MutationExternalOutcome
    result_sha256: str
    postcondition_sha256: str | None = None
    schema_version: str = MUTATION_RESULT_BINDING_SCHEMA_VERSION

    def __post_init__(self) -> None:
        for field in (
            "execution_id",
            "executor_ref",
            "request_id",
            "resource_id",
            "operation_id",
            "journal_id",
            "rollback_custody_ref",
        ):
            object.__setattr__(self, field, _required(getattr(self, field), field))
        for field in (
            "plan_sha256",
            "rollback_descriptor_sha256",
            "result_sha256",
        ):
            object.__setattr__(self, field, _sha256(getattr(self, field), field))
        if self.postcondition_sha256 is not None:
            object.__setattr__(
                self,
                "postcondition_sha256",
                _sha256(self.postcondition_sha256, "postcondition_sha256"),
            )
        if not isinstance(self.outcome, MutationExternalOutcome):
            raise MutationResultBindingError("outcome must be MutationExternalOutcome")
        if self.schema_version != MUTATION_RESULT_BINDING_SCHEMA_VERSION:
            raise MutationResultBindingError(
                f"unsupported schema_version: {self.schema_version}"
            )


def canonical_mutation_result_receipt_bytes(
    receipt: MutationExternalResultReceipt,
) -> bytes:
    if not isinstance(receipt, MutationExternalResultReceipt):
        raise TypeError("receipt must be MutationExternalResultReceipt")
    payload = asdict(receipt)
    payload["outcome"] = receipt.outcome.value
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def mutation_result_receipt_sha256(receipt: MutationExternalResultReceipt) -> str:
    return hashlib.sha256(canonical_mutation_result_receipt_bytes(receipt)).hexdigest()


@dataclass(frozen=True)
class MutationResultBindingRecord:
    execution_id: str
    executor_ref: str
    request_id: str
    resource_id: str
    operation_id: str
    plan_sha256: str
    journal_id: str
    receipt_sha256: str
    outcome: MutationExternalOutcome
    receipt_bound: bool
    success_established: bool
    postcondition_correlated: bool
    recovery_hold: bool
    executor_authenticated: bool = False
    execution_authorized: bool = False
    acp_mutation_executed: bool = False
    schema_version: str = MUTATION_RESULT_BINDING_SCHEMA_VERSION

    def __post_init__(self) -> None:
        _sha256(self.plan_sha256, "plan_sha256")
        _sha256(self.receipt_sha256, "receipt_sha256")
        if (
            self.executor_authenticated is not False
            or self.execution_authorized is not False
            or self.acp_mutation_executed is not False
        ):
            raise MutationResultBindingError(
                "result binding cannot establish authentication, "
                "authorization, or ACP mutation execution"
            )
        if self.success_established and (
            self.receipt_bound is not True
            or self.postcondition_correlated is not True
            or self.recovery_hold is not False
            or self.outcome is not MutationExternalOutcome.SUCCEEDED
        ):
            raise MutationResultBindingError(
                "success requires bound succeeded receipt and verified postcondition"
            )


_HOLD_DISPOSITIONS = {
    MutationRecoveryDisposition.HOLD_AMBIGUOUS_EFFECT,
    MutationRecoveryDisposition.HOLD_POSTCONDITION_REQUIRED,
    MutationRecoveryDisposition.HOLD_ROLLBACK_AMBIGUOUS,
    MutationRecoveryDisposition.HOLD_FAILED_AFTER_EXECUTION_INTENT,
}


def bind_mutation_execution_result(
    journal: MutationJournalRecord,
    assessment: MutationRecoveryAssessment,
    receipt: MutationExternalResultReceipt,
    *,
    postcondition: MutationPostconditionRecord | None = None,
) -> MutationResultBindingRecord:
    if not isinstance(journal, MutationJournalRecord):
        raise TypeError("journal must be MutationJournalRecord")
    if not isinstance(assessment, MutationRecoveryAssessment):
        raise TypeError("assessment must be MutationRecoveryAssessment")
    if not isinstance(receipt, MutationExternalResultReceipt):
        raise TypeError("receipt must be MutationExternalResultReceipt")
    if postcondition is not None and not isinstance(
        postcondition,
        MutationPostconditionRecord,
    ):
        raise TypeError("postcondition must be MutationPostconditionRecord or None")

    identity = (
        receipt.request_id == journal.request_id
        and receipt.resource_id == journal.resource_id
        and receipt.operation_id == journal.operation_id
        and receipt.plan_sha256 == journal.plan_sha256
        and receipt.journal_id == journal.transaction_id
        and receipt.rollback_descriptor_sha256 == journal.rollback_descriptor_sha256
        and receipt.rollback_custody_ref == journal.custody_ref
    )
    if not identity:
        raise MutationResultBindingError(
            "external result receipt does not match journal identity"
        )

    if (
        assessment.transaction_id != journal.transaction_id
        or assessment.current_state is not journal.current_state
        or assessment.new_execution_authorization_required is not True
    ):
        raise MutationResultBindingError(
            "recovery assessment does not match journal state"
        )

    postcondition_correlated = False
    if postcondition is not None:
        if (
            postcondition.request_id != journal.request_id
            or postcondition.resource_id != journal.resource_id
            or postcondition.operation_id != journal.operation_id
            or postcondition.plan_sha256 != journal.plan_sha256
            or postcondition.rollback_descriptor_sha256
            != journal.rollback_descriptor_sha256
            or postcondition.rollback_custody_ref != journal.custody_ref
        ):
            raise MutationResultBindingError(
                "postcondition does not match journal identity"
            )
        postcondition_correlated = (
            postcondition.postcondition_verified is True
            and postcondition.execution_enabled is False
            and postcondition.mutation_executed is False
            and receipt.postcondition_sha256
            == mutation_postcondition_sha256(postcondition)
        )
    elif receipt.postcondition_sha256 is not None:
        raise MutationResultBindingError(
            "receipt references postcondition but none was supplied"
        )

    recovery_hold = assessment.disposition in _HOLD_DISPOSITIONS
    journal_confirms_postcondition = (
        journal.current_state is MutationJournalState.POSTCONDITION_VERIFIED
    )
    assessment_confirms_effect = (
        assessment.disposition
        is MutationRecoveryDisposition.CLEAN_POSTCONDITION_VERIFIED
    )
    success_established = (
        receipt.outcome is MutationExternalOutcome.SUCCEEDED
        and postcondition_correlated
        and journal_confirms_postcondition
        and assessment_confirms_effect
        and recovery_hold is False
    )

    return MutationResultBindingRecord(
        execution_id=receipt.execution_id,
        executor_ref=receipt.executor_ref,
        request_id=receipt.request_id,
        resource_id=receipt.resource_id,
        operation_id=receipt.operation_id,
        plan_sha256=receipt.plan_sha256,
        journal_id=receipt.journal_id,
        receipt_sha256=mutation_result_receipt_sha256(receipt),
        outcome=receipt.outcome,
        receipt_bound=True,
        success_established=success_established,
        postcondition_correlated=postcondition_correlated,
        recovery_hold=recovery_hold,
    )
