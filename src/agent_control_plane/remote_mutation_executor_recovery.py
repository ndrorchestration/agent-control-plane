"""Cross-store recovery assessment for the bounded repository mutation executor.

This module reconciles the durable execution authorization record with the
durable mutation journal. It performs no repository mutation and issues no
authorization.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .remote_mutation_execution_authorization import (
    RemoteMutationExecutionAuthorization,
)
from .remote_mutation_journal import MutationJournalRecord, MutationJournalState

EXECUTOR_RECOVERY_SCHEMA_VERSION = (
    "agent-control-plane.remote-mutation-executor-recovery.v0-candidate"
)


class ExecutorRecoveryError(ValueError):
    pass


class ExecutorRecoveryDisposition(str, Enum):
    SAFE_AUTH_PENDING_PRE_EXECUTION = "safe_auth_pending_pre_execution"
    SAFE_AUTH_CONSUMED_BEFORE_INTENT_REAUTH_REQUIRED = (
        "safe_auth_consumed_before_intent_reauth_required"
    )
    HOLD_AUTHORIZATION_JOURNAL_DIVERGENCE = (
        "hold_authorization_journal_divergence"
    )
    HOLD_AMBIGUOUS_EFFECT = "hold_ambiguous_effect"
    HOLD_POSTCONDITION_REQUIRED = "hold_postcondition_required"
    CLEAN_POSTCONDITION_VERIFIED = "clean_postcondition_verified"
    HOLD_ROLLBACK_AMBIGUOUS = "hold_rollback_ambiguous"
    CLEAN_ROLLED_BACK = "clean_rolled_back"
    FAILED_PRE_EXECUTION = "failed_pre_execution"
    HOLD_FAILED_AFTER_EXECUTION_INTENT = "hold_failed_after_execution_intent"


@dataclass(frozen=True)
class ExecutorRecoveryAssessment:
    authorization_id: str
    transaction_id: str
    plan_sha256: str
    journal_state: MutationJournalState
    authorization_consumed: bool
    disposition: ExecutorRecoveryDisposition
    repository_mutation_may_exist: bool
    recovery_hold: bool
    new_authorization_required: bool
    reason: str
    execution_enabled: bool = False
    mutation_executed: bool = False
    schema_version: str = EXECUTOR_RECOVERY_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.execution_enabled is not False or self.mutation_executed is not False:
            raise ExecutorRecoveryError(
                "recovery assessment cannot enable or claim mutation execution"
            )


def assess_executor_recovery(
    authorization: RemoteMutationExecutionAuthorization,
    journal: MutationJournalRecord,
) -> ExecutorRecoveryAssessment:
    """Reconcile authorization consumption with journal state fail-closed."""
    if not isinstance(authorization, RemoteMutationExecutionAuthorization):
        raise TypeError("authorization must be RemoteMutationExecutionAuthorization")
    if not isinstance(journal, MutationJournalRecord):
        raise TypeError("journal must be MutationJournalRecord")

    exact = (
        authorization.transaction_id == journal.transaction_id
        and authorization.request_id == journal.request_id
        and authorization.resource_id == journal.resource_id
        and authorization.operation_id == journal.operation_id
        and authorization.plan_sha256 == journal.plan_sha256
        and authorization.rollback_descriptor_sha256
        == journal.rollback_descriptor_sha256
        and authorization.custody_ref == journal.custody_ref
    )
    if not exact:
        return ExecutorRecoveryAssessment(
            authorization_id=authorization.authorization_id,
            transaction_id=journal.transaction_id,
            plan_sha256=journal.plan_sha256,
            journal_state=journal.current_state,
            authorization_consumed=authorization.consumed,
            disposition=ExecutorRecoveryDisposition.HOLD_AUTHORIZATION_JOURNAL_DIVERGENCE,
            repository_mutation_may_exist=True,
            recovery_hold=True,
            new_authorization_required=True,
            reason="authorization and journal identities diverge; hold for operator review",
        )

    states = tuple(event.state for event in journal.events)
    current = journal.current_state
    saw_intent = MutationJournalState.EXECUTION_INTENT_RECORDED in states

    if current is MutationJournalState.PREPARED:
        if authorization.consumed:
            return ExecutorRecoveryAssessment(
                authorization_id=authorization.authorization_id,
                transaction_id=journal.transaction_id,
                plan_sha256=journal.plan_sha256,
                journal_state=current,
                authorization_consumed=True,
                disposition=ExecutorRecoveryDisposition.SAFE_AUTH_CONSUMED_BEFORE_INTENT_REAUTH_REQUIRED,
                repository_mutation_may_exist=False,
                recovery_hold=False,
                new_authorization_required=True,
                reason=(
                    "authorization was consumed before execution intent was durably recorded; "
                    "this executor performs no side effect before intent, so no repository effect "
                    "may exist, but the consumed authorization cannot be replayed"
                ),
            )
        return ExecutorRecoveryAssessment(
            authorization_id=authorization.authorization_id,
            transaction_id=journal.transaction_id,
            plan_sha256=journal.plan_sha256,
            journal_state=current,
            authorization_consumed=False,
            disposition=ExecutorRecoveryDisposition.SAFE_AUTH_PENDING_PRE_EXECUTION,
            repository_mutation_may_exist=False,
            recovery_hold=False,
            new_authorization_required=True,
            reason=(
                "journal remains prepared and authorization is unconsumed; no executor "
                "side effect may exist, but recovery never reuses prior authorization "
                "without a fresh authorization decision"
            ),
        )

    if not authorization.consumed:
        return ExecutorRecoveryAssessment(
            authorization_id=authorization.authorization_id,
            transaction_id=journal.transaction_id,
            plan_sha256=journal.plan_sha256,
            journal_state=current,
            authorization_consumed=False,
            disposition=ExecutorRecoveryDisposition.HOLD_AUTHORIZATION_JOURNAL_DIVERGENCE,
            repository_mutation_may_exist=True,
            recovery_hold=True,
            new_authorization_required=True,
            reason="journal advanced beyond prepared while authorization remains unconsumed; impossible under bounded executor ordering",
        )

    mapping = {
        MutationJournalState.EXECUTION_INTENT_RECORDED: (
            ExecutorRecoveryDisposition.HOLD_AMBIGUOUS_EFFECT, True, True, True
        ),
        MutationJournalState.EXTERNAL_EFFECT_REPORTED: (
            ExecutorRecoveryDisposition.HOLD_POSTCONDITION_REQUIRED, True, True, True
        ),
        MutationJournalState.POSTCONDITION_VERIFIED: (
            ExecutorRecoveryDisposition.CLEAN_POSTCONDITION_VERIFIED, True, False, True
        ),
        MutationJournalState.ROLLBACK_INTENT_RECORDED: (
            ExecutorRecoveryDisposition.HOLD_ROLLBACK_AMBIGUOUS, True, True, True
        ),
        MutationJournalState.ROLLBACK_VERIFIED: (
            ExecutorRecoveryDisposition.CLEAN_ROLLED_BACK, False, False, True
        ),
    }
    if current is MutationJournalState.FAILED:
        if saw_intent:
            disposition = ExecutorRecoveryDisposition.HOLD_FAILED_AFTER_EXECUTION_INTENT
            may_exist = True
            hold = True
        else:
            disposition = ExecutorRecoveryDisposition.FAILED_PRE_EXECUTION
            may_exist = False
            hold = False
        return ExecutorRecoveryAssessment(
            authorization_id=authorization.authorization_id,
            transaction_id=journal.transaction_id,
            plan_sha256=journal.plan_sha256,
            journal_state=current,
            authorization_consumed=True,
            disposition=disposition,
            repository_mutation_may_exist=may_exist,
            recovery_hold=hold,
            new_authorization_required=True,
            reason="failed journal state reconciled with consumed authorization",
        )

    disposition, may_exist, hold, reauth = mapping[current]
    return ExecutorRecoveryAssessment(
        authorization_id=authorization.authorization_id,
        transaction_id=journal.transaction_id,
        plan_sha256=journal.plan_sha256,
        journal_state=current,
        authorization_consumed=True,
        disposition=disposition,
        repository_mutation_may_exist=may_exist,
        recovery_hold=hold,
        new_authorization_required=reauth,
        reason="authorization consumption and journal state are congruent with bounded executor ordering",
    )