from __future__ import annotations

import pytest

from agent_control_plane.remote_mutation_execution_authorization import (
    RemoteMutationExecutionAuthorization,
)
from agent_control_plane.remote_mutation_execution_closure import (
    MUTATION_EXECUTION_CLOSURE_SCHEMA_VERSION,
    MutationExecutionClosureError,
    MutationExecutionClosureRecord,
    close_authorized_mutation_execution,
)
from agent_control_plane.remote_mutation_execution_evidence import (
    MutationExecutionEvidenceReceipt,
)
from agent_control_plane.remote_mutation_journal import (
    MutationJournalEvent,
    MutationJournalRecord,
    MutationJournalState,
)

A = "a" * 64
B = "b" * 64
C = "c" * 64
D = "d" * 64
E = "e" * 64


def authorization(*, consumed_at="2026-09-27T10:00:30Z", executor_id="external:rdc"):
    return RemoteMutationExecutionAuthorization(
        authorization_id="authz-close-1", executor_id=executor_id,
        transaction_id="tx-close-1", request_id="req-close-1",
        authority_id="authority-close-1", resource_id="repo:acp",
        operation_id="repo.write_text_file", plan_sha256=A,
        rollback_descriptor_sha256=B, custody_ref="custody://close/1",
        issued_at="2026-09-27T10:00:00Z", expires_at="2026-09-27T10:05:00Z",
        consumed_at=consumed_at,
    )


def journal(*, intent_at="2026-09-27T10:00:31Z", terminal=True):
    events = [
        MutationJournalEvent(
            transaction_id="tx-close-1", event_index=0, state=MutationJournalState.PREPARED,
            occurred_at="2026-09-27T10:00:00Z",
        ),
        MutationJournalEvent(
            transaction_id="tx-close-1", event_index=1,
            state=MutationJournalState.EXECUTION_INTENT_RECORDED, occurred_at=intent_at,
        ),
        MutationJournalEvent(
            transaction_id="tx-close-1", event_index=2,
            state=MutationJournalState.EXTERNAL_EFFECT_REPORTED,
            occurred_at="2026-09-27T10:00:40Z", evidence_sha256=C,
        ),
    ]
    if terminal:
        events.append(
            MutationJournalEvent(
                transaction_id="tx-close-1", event_index=3,
                state=MutationJournalState.POSTCONDITION_VERIFIED,
                occurred_at="2026-09-27T10:00:45Z", evidence_sha256=D,
            )
        )
    return MutationJournalRecord(
        transaction_id="tx-close-1", request_id="req-close-1",
        resource_id="repo:acp", operation_id="repo.write_text_file",
        plan_sha256=A, rollback_descriptor_sha256=B, custody_ref="custody://close/1",
        created_at="2026-09-27T10:00:00Z", events=tuple(events),
    )


def receipt(*, executor_id="external:rdc", bound=True, transaction_id="tx-close-1"):
    return MutationExecutionEvidenceReceipt(
        transaction_id=transaction_id, execution_id="exec-close-1", executor_id=executor_id,
        request_id="req-close-1", resource_id="repo:acp",
        operation_id="repo.write_text_file", plan_sha256=A, result_sha256=E,
        external_effect_sha256=C, postcondition_evidence_sha256=D,
        evidence_sha256=B, evidence_bound=bound, reason="bound" if bound else "blocked",
    )


def test_exact_consumed_authorization_closes_against_terminal_evidence():
    record = close_authorized_mutation_execution(authorization(), journal(), receipt())
    assert record.schema_version == MUTATION_EXECUTION_CLOSURE_SCHEMA_VERSION
    assert record.closed is True
    assert record.authorization_id == "authz-close-1"
    assert record.further_execution_authorized is False
    assert record.acp_mutation_executed is False


def test_unconsumed_authorization_blocks_closure():
    record = close_authorized_mutation_execution(
        authorization(consumed_at=None), journal(), receipt()
    )
    assert record.closed is False
    assert "authorization.not_consumed" in record.reason


def test_authorization_consumed_after_execution_intent_blocks():
    record = close_authorized_mutation_execution(
        authorization(consumed_at="2026-09-27T10:00:35Z"),
        journal(intent_at="2026-09-27T10:00:31Z"),
        receipt(),
    )
    assert record.closed is False
    assert "consumed_after_execution_intent" in record.reason


def test_executor_identity_drift_blocks():
    record = close_authorized_mutation_execution(
        authorization(executor_id="external:authorized"),
        journal(),
        receipt(executor_id="external:other"),
    )
    assert record.closed is False
    assert "authorization.receipt_identity" in record.reason


def test_transaction_identity_drift_blocks():
    record = close_authorized_mutation_execution(
        authorization(), journal(), receipt(transaction_id="tx-other")
    )
    assert record.closed is False
    assert "authorization.receipt_identity" in record.reason


def test_unbound_execution_evidence_blocks():
    record = close_authorized_mutation_execution(
        authorization(), journal(), receipt(bound=False)
    )
    assert record.closed is False
    assert "receipt.not_bound" in record.reason


def test_nonterminal_journal_blocks():
    record = close_authorized_mutation_execution(
        authorization(), journal(terminal=False), receipt()
    )
    assert record.closed is False
    assert "journal.not_terminal_postcondition" in record.reason


def test_missing_execution_intent_blocks():
    j = journal()
    j = MutationJournalRecord(
        transaction_id=j.transaction_id, request_id=j.request_id, resource_id=j.resource_id,
        operation_id=j.operation_id, plan_sha256=j.plan_sha256,
        rollback_descriptor_sha256=j.rollback_descriptor_sha256, custody_ref=j.custody_ref,
        created_at=j.created_at,
        events=tuple(event for event in j.events if event.state is not MutationJournalState.EXECUTION_INTENT_RECORDED),
    )
    record = close_authorized_mutation_execution(authorization(), j, receipt())
    assert record.closed is False
    assert "journal.execution_intent_event" in record.reason


def test_closure_record_cannot_authorize_more_execution():
    with pytest.raises(MutationExecutionClosureError, match="cannot authorize"):
        MutationExecutionClosureRecord(
            authorization_id="a", authorization_sha256=A, evidence_sha256=B,
            executor_id="e", execution_id="x", transaction_id="t", request_id="r",
            resource_id="repo", operation_id="repo.write_text_file", plan_sha256=C,
            closed=True, reason="invalid", further_execution_authorized=True,
        )