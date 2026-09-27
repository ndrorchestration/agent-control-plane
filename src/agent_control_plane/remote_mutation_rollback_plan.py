"""Non-executing explicit rollback plan for repository mutations.

Rollback is a separate governed action. This module never mutates a repository,
never reopens the original mutation journal, and never authorizes rollback.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import hashlib
import json

from .remote_mutation_journal import MutationJournalRecord, MutationJournalState
from .remote_mutation_rollback_custody import (
    RollbackCustodyAdmissionRecord,
    RollbackMaterialDescriptor,
    RollbackMode,
)
from .remote_mutation_transaction import MutationPlan

ROLLBACK_PLAN_SCHEMA_VERSION = "agent-control-plane.remote-mutation-rollback-plan.v0-candidate"


class RollbackPlanError(ValueError):
    pass


class RollbackAction(str, Enum):
    RESTORE_FILE_BYTES = "restore_file_bytes"
    DELETE_CREATED_FILE = "delete_created_file"


_ALLOWED_ORIGINAL_STATES = {
    MutationJournalState.EXECUTION_INTENT_RECORDED,
    MutationJournalState.EXTERNAL_EFFECT_REPORTED,
    MutationJournalState.FAILED,
}


def _required(value: str, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RollbackPlanError(f"{field} must not be blank")
    return value.strip()


def _sha256(value: str, field: str) -> str:
    value = _required(value, field)
    if len(value) != 64 or any(ch not in "0123456789abcdef" for ch in value):
        raise RollbackPlanError(f"{field} must be lowercase sha256")
    return value


@dataclass(frozen=True)
class RepositoryRollbackPlan:
    rollback_request_id: str
    rollback_authority_id: str
    rollback_transaction_id: str
    original_transaction_id: str
    original_request_id: str
    resource_id: str
    original_operation_id: str
    original_plan_sha256: str
    original_journal_state: str
    requested_path: str
    rollback_descriptor_sha256: str
    rollback_custody_ref: str
    action: RollbackAction
    expected_current_target_exists: bool
    expected_current_content_sha256: str | None
    desired_target_exists: bool
    desired_content_sha256: str | None
    execution_enabled: bool = False
    rollback_executed: bool = False
    schema_version: str = ROLLBACK_PLAN_SCHEMA_VERSION

    def __post_init__(self) -> None:
        for field in (
            "rollback_request_id",
            "rollback_authority_id",
            "rollback_transaction_id",
            "original_transaction_id",
            "original_request_id",
            "resource_id",
            "original_operation_id",
            "original_journal_state",
            "requested_path",
            "rollback_custody_ref",
        ):
            object.__setattr__(self, field, _required(getattr(self, field), field))
        for field in ("original_plan_sha256", "rollback_descriptor_sha256"):
            object.__setattr__(self, field, _sha256(getattr(self, field), field))
        if not isinstance(self.action, RollbackAction):
            raise RollbackPlanError("action must be RollbackAction")
        if not isinstance(self.expected_current_target_exists, bool):
            raise RollbackPlanError("expected_current_target_exists must be bool")
        if not isinstance(self.desired_target_exists, bool):
            raise RollbackPlanError("desired_target_exists must be bool")

        if self.expected_current_target_exists:
            if self.expected_current_content_sha256 is None:
                raise RollbackPlanError(
                    "existing expected current target requires content sha256"
                )
            object.__setattr__(
                self,
                "expected_current_content_sha256",
                _sha256(
                    self.expected_current_content_sha256,
                    "expected_current_content_sha256",
                ),
            )
        elif self.expected_current_content_sha256 is not None:
            raise RollbackPlanError(
                "absent expected current target must not carry content sha256"
            )

        if self.desired_target_exists:
            if self.desired_content_sha256 is None:
                raise RollbackPlanError(
                    "existing desired target requires content sha256"
                )
            object.__setattr__(
                self,
                "desired_content_sha256",
                _sha256(self.desired_content_sha256, "desired_content_sha256"),
            )
        elif self.desired_content_sha256 is not None:
            raise RollbackPlanError(
                "absent desired target must not carry content sha256"
            )

        if self.action is RollbackAction.RESTORE_FILE_BYTES:
            if not self.desired_target_exists:
                raise RollbackPlanError(
                    "restore_file_bytes requires desired target existence"
                )
        elif self.desired_target_exists:
            raise RollbackPlanError(
                "delete_created_file requires desired target absence"
            )

        if self.execution_enabled is not False or self.rollback_executed is not False:
            raise RollbackPlanError(
                "rollback plan cannot enable or claim rollback execution"
            )
        if self.schema_version != ROLLBACK_PLAN_SCHEMA_VERSION:
            raise RollbackPlanError(f"unsupported schema_version: {self.schema_version}")

    def canonical_bytes(self) -> bytes:
        payload = {
            "action": self.action.value,
            "desired_content_sha256": self.desired_content_sha256,
            "desired_target_exists": self.desired_target_exists,
            "expected_current_content_sha256": self.expected_current_content_sha256,
            "expected_current_target_exists": self.expected_current_target_exists,
            "original_journal_state": self.original_journal_state,
            "original_operation_id": self.original_operation_id,
            "original_plan_sha256": self.original_plan_sha256,
            "original_request_id": self.original_request_id,
            "original_transaction_id": self.original_transaction_id,
            "requested_path": self.requested_path,
            "resource_id": self.resource_id,
            "rollback_authority_id": self.rollback_authority_id,
            "rollback_custody_ref": self.rollback_custody_ref,
            "rollback_descriptor_sha256": self.rollback_descriptor_sha256,
            "rollback_request_id": self.rollback_request_id,
            "rollback_transaction_id": self.rollback_transaction_id,
        }
        return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")

    @property
    def rollback_plan_sha256(self) -> str:
        return hashlib.sha256(self.canonical_bytes()).hexdigest()


def build_repository_rollback_plan(
    original_plan: MutationPlan,
    descriptor: RollbackMaterialDescriptor,
    custody: RollbackCustodyAdmissionRecord,
    original_journal: MutationJournalRecord,
    *,
    rollback_request_id: str,
    rollback_authority_id: str,
    rollback_transaction_id: str,
    expected_current_target_exists: bool,
    expected_current_content_sha256: str | None,
) -> RepositoryRollbackPlan:
    """Build an exact rollback plan without performing or authorizing rollback."""
    if not isinstance(original_plan, MutationPlan):
        raise TypeError("original_plan must be MutationPlan")
    if not isinstance(descriptor, RollbackMaterialDescriptor):
        raise TypeError("descriptor must be RollbackMaterialDescriptor")
    if not isinstance(custody, RollbackCustodyAdmissionRecord):
        raise TypeError("custody must be RollbackCustodyAdmissionRecord")
    if not isinstance(original_journal, MutationJournalRecord):
        raise TypeError("original_journal must be MutationJournalRecord")

    if custody.admitted is not True or custody.readback_verified is not True:
        raise RollbackPlanError("rollback custody must be admitted and readback-verified")
    if custody.execution_enabled is not False or custody.mutation_executed is not False:
        raise RollbackPlanError("rollback custody unexpectedly enables execution")

    exact = (
        descriptor.operation_id == original_plan.operation_id
        and descriptor.path == original_plan.parameters["path"]
        and descriptor.descriptor_sha256 == original_plan.rollback_sha256
        and custody.request_id == original_plan.request_id
        and custody.resource_id == original_plan.resource_id
        and custody.operation_id == original_plan.operation_id
        and custody.plan_sha256 == original_plan.plan_sha256
        and custody.descriptor_sha256 == descriptor.descriptor_sha256
        and original_journal.request_id == original_plan.request_id
        and original_journal.resource_id == original_plan.resource_id
        and original_journal.operation_id == original_plan.operation_id
        and original_journal.plan_sha256 == original_plan.plan_sha256
        and original_journal.rollback_descriptor_sha256 == descriptor.descriptor_sha256
        and original_journal.custody_ref == custody.custody_ref
    )
    if not exact:
        raise RollbackPlanError(
            "original plan, rollback descriptor, custody, and journal identities diverge"
        )

    states = tuple(event.state for event in original_journal.events)
    if MutationJournalState.EXECUTION_INTENT_RECORDED not in states:
        raise RollbackPlanError(
            "rollback recovery requires original execution intent evidence"
        )
    if original_journal.current_state not in _ALLOWED_ORIGINAL_STATES:
        raise RollbackPlanError(
            "original journal state is not eligible for recovery rollback planning"
        )
    if (
        original_journal.current_state is MutationJournalState.FAILED
        and MutationJournalState.EXECUTION_INTENT_RECORDED not in states
    ):
        raise RollbackPlanError("pre-execution failure is not rollback-eligible")

    if descriptor.mode is RollbackMode.RESTORE_FILE_BYTES:
        action = RollbackAction.RESTORE_FILE_BYTES
        desired_exists = True
        desired_sha = descriptor.prior_content_sha256
    elif descriptor.mode is RollbackMode.DELETE_CREATED_FILE:
        action = RollbackAction.DELETE_CREATED_FILE
        desired_exists = False
        desired_sha = None
    else:
        raise RollbackPlanError("unsupported rollback descriptor mode")

    if original_plan.operation_id == "repo.delete_file":
        if descriptor.mode is not RollbackMode.RESTORE_FILE_BYTES:
            raise RollbackPlanError("delete recovery requires restore-file rollback")
        if descriptor.prior_content_sha256 != original_plan.parameters["prior_content_sha256"]:
            raise RollbackPlanError("delete rollback prior-content identity mismatch")
    elif original_plan.operation_id != "repo.write_text_file":
        raise RollbackPlanError("unsupported original mutation operation")

    return RepositoryRollbackPlan(
        rollback_request_id=rollback_request_id,
        rollback_authority_id=rollback_authority_id,
        rollback_transaction_id=rollback_transaction_id,
        original_transaction_id=original_journal.transaction_id,
        original_request_id=original_plan.request_id,
        resource_id=original_plan.resource_id,
        original_operation_id=original_plan.operation_id,
        original_plan_sha256=original_plan.plan_sha256,
        original_journal_state=original_journal.current_state.value,
        requested_path=descriptor.path,
        rollback_descriptor_sha256=descriptor.descriptor_sha256,
        rollback_custody_ref=custody.custody_ref,
        action=action,
        expected_current_target_exists=expected_current_target_exists,
        expected_current_content_sha256=expected_current_content_sha256,
        desired_target_exists=desired_exists,
        desired_content_sha256=desired_sha,
    )
