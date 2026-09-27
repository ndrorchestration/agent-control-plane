from __future__ import annotations

import pytest

from agent_control_plane.remote_mutation_execution_authorization import (
    RemoteMutationExecutionAuthorization,
)
from agent_control_plane.remote_mutation_executor_recovery import (
    EXECUTOR_RECOVERY_SCHEMA_VERSION,
    ExecutorRecoveryAssessment,
    ExecutorRecoveryDisposition,
    ExecutorRecoveryError,
    assess_executor_recovery,
)
from agent_control_plane.remote_mutation_journal import (
    MutationJournalEvent,
    MutationJournalRecord,
    MutationJournalState,
)

A = "a" * 64
B = "b" * 64
C = "c" * 64


def authorization(*, consumed=False, plan_sha=A, custody_ref="custody://rb/1"):
    return RemoteMutationExecutionAuthorization(
        authorization_id="authz-1",
        executor_id="executor:test",
        transaction_id="tx-1",
        request_id="req-1",
        authority_id="authority-1",
        resource_id="repo:acp",
        operation_id="repo.write_text_file",
        plan_sha256=plan_sha,
        rollback_descriptor_sha256=B,
        custody_ref=custody_ref,
        issued_at="2026-09-27T08:00:00Z",
        expires_at="2026-09-27T09:00:00Z",
        consumed_at="2026-09-27T08:10:00Z" if consumed else None,
    )


def event(index, state, *, evidence=None, error=None):
    return MutationJournalEvent(
        transaction_id="tx-1",
        event_index=index,
        state=state,
        occurred_at=f"2026-09-27T08:0{index}:00Z",
        evidence_sha256=evidence,
        error=error,
    )


def journal(state: MutationJournalState, *, plan_sha=A, custody_ref="custody://rb/1", failed_after_intent=True):
    events = [event(0, MutationJournalState.PREPARED)]
    if state is MutationJournalState.PREPARED:
        pass
    elif state is MutationJournalState.FAILED and not failed_after_intent:
        events.append(event(1, MutationJournalState.FAILED, error="pre-execution failure"))
    else:
        events.append(event(1, MutationJournalState.EXECUTION_INTENT_RECORDED))
        if state is MutationJournalState.EXECUTION_INTENT_RECORDED:
            pass
        elif state is MutationJournalState.FAILED:
            events.append(event(2, MutationJournalState.FAILED, error="failure after intent"))
        elif state is MutationJournalState.EXTERNAL_EFFECT_REPORTED:
            events.append(event(2, state, evidence=C))
        elif state is MutationJournalState.POSTCONDITION_VERIFIED:
            events.append(event(2, MutationJournalState.EXTERNAL_EFFECT_REPORTED, evidence=C))
            events.append(event(3, state, evidence=C))
        elif state is MutationJournalState.ROLLBACK_INTENT_RECORDED:
            events.append(event(2, state))
        elif state is MutationJournalState.ROLLBACK_VERIFIED:
            events.append(event(2, MutationJournalState.ROLLBACK_INTENT_RECORDED))
            events.append(event(3, state, evidence=C))
        else:
            raise AssertionError(state)
    return MutationJournalRecord(
        transaction_id="tx-1",
        request_id="req-1",
        resource_id="repo:acp",
        operation_id="repo.write_text_file",
        plan_sha256=plan_sha,
        rollback_descriptor_sha256=B,
        custody_ref=custody_ref,
        created_at="2026-09-27T08:00:00Z",
        events=tuple(events),
    )


def test_prepared_unconsumed_is_safe_pre_execution():
    rec = assess_executor_recovery(
        authorization(consumed=False), journal(MutationJournalState.PREPARED)
    )
    assert rec.schema_version == EXECUTOR_RECOVERY_SCHEMA_VERSION
    assert rec.disposition is ExecutorRecoveryDisposition.SAFE_AUTH_PENDING_PRE_EXECUTION
    assert rec.repository_mutation_may_exist is False
    assert rec.recovery_hold is False
    assert rec.new_authorization_required is False
    assert rec.execution_enabled is False
    assert rec.mutation_executed is False


def test_consumed_before_intent_is_safe_but_requires_reauthorization():
    rec = assess_executor_recovery(
        authorization(consumed=True), journal(MutationJournalState.PREPARED)
    )
    assert rec.disposition is ExecutorRecoveryDisposition.SAFE_AUTH_CONSUMED_BEFORE_INTENT_REAUTH_REQUIRED
    assert rec.repository_mutation_may_exist is False
    assert rec.recovery_hold is False
    assert rec.new_authorization_required is True


def test_journal_advanced_with_unconsumed_authorization_holds():
    rec = assess_executor_recovery(
        authorization(consumed=False),
        journal(MutationJournalState.EXECUTION_INTENT_RECORDED),
    )
    assert rec.disposition is ExecutorRecoveryDisposition.HOLD_AUTHORIZATION_JOURNAL_DIVERGENCE
    assert rec.repository_mutation_may_exist is True
    assert rec.recovery_hold is True


@pytest.mark.parametrize(
    "state,disposition,may_exist,hold",
    [
        (MutationJournalState.EXECUTION_INTENT_RECORDED, ExecutorRecoveryDisposition.HOLD_AMBIGUOUS_EFFECT, True, True),
        (MutationJournalState.EXTERNAL_EFFECT_REPORTED, ExecutorRecoveryDisposition.HOLD_POSTCONDITION_REQUIRED, True, True),
        (MutationJournalState.POSTCONDITION_VERIFIED, ExecutorRecoveryDisposition.CLEAN_POSTCONDITION_VERIFIED, True, False),
        (MutationJournalState.ROLLBACK_INTENT_RECORDED, ExecutorRecoveryDisposition.HOLD_ROLLBACK_AMBIGUOUS, True, True),
        (MutationJournalState.ROLLBACK_VERIFIED, ExecutorRecoveryDisposition.CLEAN_ROLLED_BACK, False, False),
    ],
)
def test_consumed_authorization_reconciles_journal_states(state, disposition, may_exist, hold):
    rec = assess_executor_recovery(authorization(consumed=True), journal(state))
    assert rec.disposition is disposition
    assert rec.repository_mutation_may_exist is may_exist
    assert rec.recovery_hold is hold
    assert rec.new_authorization_required is True


def test_failed_after_intent_requires_hold():
    rec = assess_executor_recovery(
        authorization(consumed=True), journal(MutationJournalState.FAILED)
    )
    assert rec.disposition is ExecutorRecoveryDisposition.HOLD_FAILED_AFTER_EXECUTION_INTENT
    assert rec.repository_mutation_may_exist is True
    assert rec.recovery_hold is True


def test_failed_before_intent_is_no_effect_but_requires_new_authorization():
    rec = assess_executor_recovery(
        authorization(consumed=True),
        journal(MutationJournalState.FAILED, failed_after_intent=False),
    )
    assert rec.disposition is ExecutorRecoveryDisposition.FAILED_PRE_EXECUTION
    assert rec.repository_mutation_may_exist is False
    assert rec.recovery_hold is False
    assert rec.new_authorization_required is True


@pytest.mark.parametrize(
    "auth,j",
    [
        (authorization(consumed=True, plan_sha=C), journal(MutationJournalState.PREPARED)),
        (authorization(consumed=True, custody_ref="custody://other"), journal(MutationJournalState.PREPARED)),
        (authorization(consumed=True), journal(MutationJournalState.PREPARED, plan_sha=C)),
        (authorization(consumed=True), journal(MutationJournalState.PREPARED, custody_ref="custody://other")),
    ],
)
def test_identity_divergence_is_fail_closed(auth, j):
    rec = assess_executor_recovery(auth, j)
    assert rec.disposition is ExecutorRecoveryDisposition.HOLD_AUTHORIZATION_JOURNAL_DIVERGENCE
    assert rec.recovery_hold is True
    assert rec.new_authorization_required is True


def test_recovery_record_cannot_claim_execution():
    with pytest.raises(ExecutorRecoveryError, match="cannot enable"):
        ExecutorRecoveryAssessment(
            authorization_id="authz",
            transaction_id="tx",
            plan_sha256=A,
            journal_state=MutationJournalState.PREPARED,
            authorization_consumed=False,
            disposition=ExecutorRecoveryDisposition.SAFE_AUTH_PENDING_PRE_EXECUTION,
            repository_mutation_may_exist=False,
            recovery_hold=False,
            new_authorization_required=False,
            reason="invalid",
            execution_enabled=True,
        )