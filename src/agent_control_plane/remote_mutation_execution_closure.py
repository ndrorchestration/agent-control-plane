"""Close one authorized external mutation attempt against its exact evidence chain."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .remote_mutation_execution_authorization import RemoteMutationExecutionAuthorization
from .remote_mutation_execution_evidence import MutationExecutionEvidenceReceipt
from .remote_mutation_journal import MutationJournalRecord, MutationJournalState

MUTATION_EXECUTION_CLOSURE_SCHEMA_VERSION = (
    "agent-control-plane.remote-mutation-execution-closure.v0-candidate"
)


class MutationExecutionClosureError(ValueError):
    pass


def _parse(value: str) -> datetime:
    candidate = value[:-1] + "+00:00" if value.endswith("Z") else value
    return datetime.fromisoformat(candidate)


@dataclass(frozen=True)
class MutationExecutionClosureRecord:
    authorization_id: str
    authorization_sha256: str
    evidence_sha256: str
    executor_id: str
    execution_id: str
    transaction_id: str
    request_id: str
    resource_id: str
    operation_id: str
    plan_sha256: str
    closed: bool
    reason: str
    further_execution_authorized: bool = False
    acp_mutation_executed: bool = False
    schema_version: str = MUTATION_EXECUTION_CLOSURE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.further_execution_authorized is not False or self.acp_mutation_executed is not False:
            raise MutationExecutionClosureError(
                "closure cannot authorize further execution or claim ACP mutation execution"
            )


def close_authorized_mutation_execution(
    authorization: RemoteMutationExecutionAuthorization,
    journal: MutationJournalRecord,
    receipt: MutationExecutionEvidenceReceipt,
) -> MutationExecutionClosureRecord:
    """Bind a consumed exact authorization to its terminal evidence receipt."""
    if not isinstance(authorization, RemoteMutationExecutionAuthorization):
        raise TypeError("authorization must be RemoteMutationExecutionAuthorization")
    if not isinstance(journal, MutationJournalRecord):
        raise TypeError("journal must be MutationJournalRecord")
    if not isinstance(receipt, MutationExecutionEvidenceReceipt):
        raise TypeError("receipt must be MutationExecutionEvidenceReceipt")

    mismatches: list[str] = []
    if authorization.consumed is not True:
        mismatches.append("authorization.not_consumed")
    if receipt.evidence_bound is not True:
        mismatches.append("receipt.not_bound")
    if receipt.execution_authorized is not False or receipt.acp_mutation_executed is not False:
        raise MutationExecutionClosureError("receipt unexpectedly authorizes or claims ACP execution")

    if (
        authorization.executor_id != receipt.executor_id
        or authorization.transaction_id != receipt.transaction_id
        or authorization.request_id != receipt.request_id
        or authorization.resource_id != receipt.resource_id
        or authorization.operation_id != receipt.operation_id
        or authorization.plan_sha256 != receipt.plan_sha256
    ):
        mismatches.append("authorization.receipt_identity")

    if (
        journal.transaction_id != authorization.transaction_id
        or journal.request_id != authorization.request_id
        or journal.resource_id != authorization.resource_id
        or journal.operation_id != authorization.operation_id
        or journal.plan_sha256 != authorization.plan_sha256
    ):
        mismatches.append("authorization.journal_identity")

    intent_events = [
        event for event in journal.events
        if event.state is MutationJournalState.EXECUTION_INTENT_RECORDED
    ]
    if len(intent_events) != 1:
        mismatches.append("journal.execution_intent_event")
    elif authorization.consumed_at is None:
        mismatches.append("authorization.not_consumed")
    elif _parse(authorization.consumed_at) > _parse(intent_events[0].occurred_at):
        mismatches.append("authorization.consumed_after_execution_intent")

    if journal.current_state is not MutationJournalState.POSTCONDITION_VERIFIED:
        mismatches.append("journal.not_terminal_postcondition")

    closed = not mismatches
    reason = (
        "consumed exact authorization is closed against terminal mutation evidence; no further execution is authorized"
        if closed
        else "mutation execution closure blocked:" + ",".join(dict.fromkeys(mismatches))
    )
    return MutationExecutionClosureRecord(
        authorization_id=authorization.authorization_id,
        authorization_sha256=authorization.authorization_sha256,
        evidence_sha256=receipt.evidence_sha256,
        executor_id=receipt.executor_id,
        execution_id=receipt.execution_id,
        transaction_id=receipt.transaction_id,
        request_id=receipt.request_id,
        resource_id=receipt.resource_id,
        operation_id=receipt.operation_id,
        plan_sha256=receipt.plan_sha256,
        closed=closed,
        reason=reason,
    )