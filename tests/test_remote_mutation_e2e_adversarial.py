from __future__ import annotations

from pathlib import Path

import pytest

from agent_control_plane.remote_mutation_composition import MutationCompositionRecord
from agent_control_plane.remote_mutation_execution_authorization import (
    MutationExecutionAuthorizationError,
    RemoteMutationExecutionAuthorizationStore,
)
from agent_control_plane.remote_mutation_execution_closure import (
    close_authorized_mutation_execution,
)
from agent_control_plane.remote_mutation_execution_evidence import (
    ExternalMutationExecutionEvidence,
    bind_mutation_execution_evidence,
)
from agent_control_plane.remote_mutation_journal import (
    MutationJournalState,
    MutationRecoveryDisposition,
    RemoteMutationJournal,
)
from agent_control_plane.remote_mutation_path_safety import MutationPathSafetyRecord
from agent_control_plane.remote_mutation_postcondition import (
    MutationPostconditionRecord,
)
from agent_control_plane.remote_mutation_rollback_custody import (
    RollbackCustodyAdmissionRecord,
    RollbackMaterialDescriptor,
    RollbackMode,
)
from agent_control_plane.remote_mutation_transaction import (
    MutationPlan,
    MutationTransactionReceipt,
    MutationTransactionState,
)

A = "a" * 64
B = "b" * 64
C = "c" * 64
D = "d" * 64
E = "e" * 64


def build_pre_execution(tmp_path: Path):
    descriptor = RollbackMaterialDescriptor(
        operation_id="repo.write_text_file",
        path="docs/example.md",
        mode=RollbackMode.RESTORE_FILE_BYTES,
        prior_content_sha256=B,
        prior_content_size=6,
    )
    plan = MutationPlan(
        request_id="req-e2e",
        authority_id="auth-e2e",
        resource_id="repo:acp",
        resource_type="git_repository",
        operation_id="repo.write_text_file",
        parameters={"path": "docs/example.md", "content_sha256": C},
        precondition_sha256=A,
        rollback_sha256=descriptor.descriptor_sha256,
    )
    composition = MutationCompositionRecord(
        request_id=plan.request_id,
        authority_id=plan.authority_id,
        operation_id=plan.operation_id,
        resource_id=plan.resource_id,
        plan_sha256=plan.plan_sha256,
        admitted=True,
        reason="exact",
    )
    transaction = MutationTransactionReceipt(
        request_id=plan.request_id,
        authority_id=plan.authority_id,
        operation_id=plan.operation_id,
        plan_sha256=plan.plan_sha256,
        precondition_sha256=plan.precondition_sha256,
        rollback_sha256=plan.rollback_sha256,
        state=MutationTransactionState.PRECONDITIONS_VERIFIED,
        preconditions_verified=True,
        rollback_available=True,
    )
    root = tmp_path / "repo"
    root.mkdir()
    (root / ".git").mkdir()
    (root / "docs").mkdir()
    target = root / "docs" / "example.md"
    path = MutationPathSafetyRecord(
        request_id=plan.request_id,
        resource_id=plan.resource_id,
        operation_id=plan.operation_id,
        plan_sha256=plan.plan_sha256,
        requested_path=plan.parameters["path"],
        repository_root=str(root.resolve()),
        resolved_path=str(target.resolve(strict=False)),
        admitted=True,
        reason="safe",
        repository_boundary_verified=True,
        symlink_safe=True,
        repository_metadata_safe=True,
        operation_shape_verified=True,
        target_exists=True,
    )
    custody = RollbackCustodyAdmissionRecord(
        request_id=plan.request_id,
        resource_id=plan.resource_id,
        operation_id=plan.operation_id,
        plan_sha256=plan.plan_sha256,
        descriptor_sha256=descriptor.descriptor_sha256,
        custody_ref="custody://e2e/rollback",
        admitted=True,
        reason="verified",
        readback_verified=True,
    )
    journal_store = RemoteMutationJournal(tmp_path / "journal.sqlite3")
    journal = journal_store.begin(
        transaction_id="tx-e2e",
        plan=plan,
        path_safety=path,
        rollback_custody=custody,
        created_at="2026-09-27T12:00:00Z",
    )
    return plan, composition, transaction, path, custody, journal_store, journal


def issue_authorization(tmp_path: Path):
    values = build_pre_execution(tmp_path)
    plan, composition, transaction, path, custody, _, journal = values
    store = RemoteMutationExecutionAuthorizationStore(
        tmp_path / "authorization.sqlite3"
    )
    authorization = store.issue(
        authorization_id="mutation-authz-e2e",
        executor_id="external-executor:rdc-neontic",
        composition=composition,
        plan=plan,
        transaction=transaction,
        path_safety=path,
        rollback_custody=custody,
        journal=journal,
        issued_at="2026-09-27T12:00:00Z",
        expires_at="2026-09-27T12:05:00Z",
    )
    return (*values, store, authorization)


def verified_postcondition(plan: MutationPlan, path: MutationPathSafetyRecord, custody):
    return MutationPostconditionRecord(
        request_id=plan.request_id,
        resource_id=plan.resource_id,
        operation_id=plan.operation_id,
        plan_sha256=plan.plan_sha256,
        requested_path=plan.parameters["path"],
        repository_root=path.repository_root,
        resolved_path=path.resolved_path,
        rollback_descriptor_sha256=custody.descriptor_sha256,
        rollback_custody_ref=custody.custody_ref,
        target_exists=True,
        observed_content_sha256=plan.parameters["content_sha256"],
        path_revalidated=True,
        postcondition_verified=True,
        reason="verified",
    )


def finish_journal(journal_store, postcondition):
    journal_store.append(
        "tx-e2e",
        state=MutationJournalState.EXECUTION_INTENT_RECORDED,
        occurred_at="2026-09-27T12:01:01Z",
    )
    journal_store.append(
        "tx-e2e",
        state=MutationJournalState.EXTERNAL_EFFECT_REPORTED,
        occurred_at="2026-09-27T12:01:02Z",
        evidence_sha256=D,
    )
    return journal_store.append(
        "tx-e2e",
        state=MutationJournalState.POSTCONDITION_VERIFIED,
        occurred_at="2026-09-27T12:01:03Z",
        evidence_sha256=E,
    )


def test_exact_chain_binds_and_closes_without_acp_execution(tmp_path):
    (
        plan,
        _,
        _,
        path,
        custody,
        journal_store,
        _,
        authorization_store,
        authorization,
    ) = issue_authorization(tmp_path)
    consumed = authorization_store.consume(
        authorization.authorization_id,
        executor_id=authorization.executor_id,
        transaction_id=authorization.transaction_id,
        plan_sha256=plan.plan_sha256,
        now="2026-09-27T12:01:00Z",
    )
    postcondition = verified_postcondition(plan, path, custody)
    journal = finish_journal(journal_store, postcondition)
    evidence = ExternalMutationExecutionEvidence(
        executor_id=authorization.executor_id,
        execution_id="execution-e2e",
        transaction_id=journal.transaction_id,
        request_id=plan.request_id,
        resource_id=plan.resource_id,
        operation_id=plan.operation_id,
        plan_sha256=plan.plan_sha256,
        result_sha256=A,
        external_effect_sha256=D,
        postcondition_evidence_sha256=E,
    )
    receipt = bind_mutation_execution_evidence(plan, journal, postcondition, evidence)
    closure = close_authorized_mutation_execution(consumed, journal, receipt)

    assert receipt.evidence_bound is True
    assert receipt.execution_authorized is False
    assert receipt.acp_mutation_executed is False
    assert closure.closed is True
    assert closure.further_execution_authorized is False
    assert closure.acp_mutation_executed is False


def test_authorization_is_single_use_across_store_reopen(tmp_path):
    *_, store, authorization = issue_authorization(tmp_path)
    store.consume(
        authorization.authorization_id,
        executor_id=authorization.executor_id,
        transaction_id=authorization.transaction_id,
        plan_sha256=authorization.plan_sha256,
        now="2026-09-27T12:01:00Z",
    )
    reopened = RemoteMutationExecutionAuthorizationStore(
        tmp_path / "authorization.sqlite3"
    )
    with pytest.raises(MutationExecutionAuthorizationError, match="already consumed"):
        reopened.consume(
            authorization.authorization_id,
            executor_id=authorization.executor_id,
            transaction_id=authorization.transaction_id,
            plan_sha256=authorization.plan_sha256,
            now="2026-09-27T12:01:30Z",
        )


def test_expired_authorization_fails_before_execution_intent(tmp_path):
    *_, store, authorization = issue_authorization(tmp_path)
    with pytest.raises(MutationExecutionAuthorizationError, match="expired"):
        store.consume(
            authorization.authorization_id,
            executor_id=authorization.executor_id,
            transaction_id=authorization.transaction_id,
            plan_sha256=authorization.plan_sha256,
            now="2026-09-27T12:05:01Z",
        )


def test_consume_after_execution_intent_cannot_close(tmp_path):
    (
        plan,
        _,
        _,
        path,
        custody,
        journal_store,
        _,
        authorization_store,
        authorization,
    ) = issue_authorization(tmp_path)
    journal_store.append(
        "tx-e2e",
        state=MutationJournalState.EXECUTION_INTENT_RECORDED,
        occurred_at="2026-09-27T12:01:00Z",
    )
    consumed = authorization_store.consume(
        authorization.authorization_id,
        executor_id=authorization.executor_id,
        transaction_id=authorization.transaction_id,
        plan_sha256=plan.plan_sha256,
        now="2026-09-27T12:01:01Z",
    )
    journal_store.append(
        "tx-e2e",
        state=MutationJournalState.EXTERNAL_EFFECT_REPORTED,
        occurred_at="2026-09-27T12:01:02Z",
        evidence_sha256=D,
    )
    journal = journal_store.append(
        "tx-e2e",
        state=MutationJournalState.POSTCONDITION_VERIFIED,
        occurred_at="2026-09-27T12:01:03Z",
        evidence_sha256=E,
    )
    postcondition = verified_postcondition(plan, path, custody)
    evidence = ExternalMutationExecutionEvidence(
        executor_id=authorization.executor_id,
        execution_id="execution-e2e",
        transaction_id=journal.transaction_id,
        request_id=plan.request_id,
        resource_id=plan.resource_id,
        operation_id=plan.operation_id,
        plan_sha256=plan.plan_sha256,
        result_sha256=A,
        external_effect_sha256=D,
        postcondition_evidence_sha256=E,
    )
    receipt = bind_mutation_execution_evidence(plan, journal, postcondition, evidence)
    closure = close_authorized_mutation_execution(consumed, journal, receipt)

    assert closure.closed is False
    assert "consumed_after_execution_intent" in closure.reason


def test_interruption_after_intent_remains_recovery_hold(tmp_path):
    *_, journal_store, journal, _, _ = issue_authorization(tmp_path)
    journal_store.append(
        journal.transaction_id,
        state=MutationJournalState.EXECUTION_INTENT_RECORDED,
        occurred_at="2026-09-27T12:01:00Z",
    )
    assessment = RemoteMutationJournal(tmp_path / "journal.sqlite3").assess_recovery(
        journal.transaction_id
    )

    assert assessment.disposition is MutationRecoveryDisposition.HOLD_AMBIGUOUS_EFFECT
    assert assessment.repository_mutation_may_exist is True
    assert assessment.new_execution_authorization_required is True


def test_execution_evidence_hash_substitution_blocks_binding(tmp_path):
    (
        plan,
        _,
        _,
        path,
        custody,
        journal_store,
        _,
        authorization_store,
        authorization,
    ) = issue_authorization(tmp_path)
    authorization_store.consume(
        authorization.authorization_id,
        executor_id=authorization.executor_id,
        transaction_id=authorization.transaction_id,
        plan_sha256=plan.plan_sha256,
        now="2026-09-27T12:01:00Z",
    )
    postcondition = verified_postcondition(plan, path, custody)
    journal = finish_journal(journal_store, postcondition)
    evidence = ExternalMutationExecutionEvidence(
        executor_id=authorization.executor_id,
        execution_id="execution-e2e",
        transaction_id=journal.transaction_id,
        request_id=plan.request_id,
        resource_id=plan.resource_id,
        operation_id=plan.operation_id,
        plan_sha256=plan.plan_sha256,
        result_sha256=A,
        external_effect_sha256=C,
        postcondition_evidence_sha256=E,
    )
    receipt = bind_mutation_execution_evidence(plan, journal, postcondition, evidence)

    assert receipt.evidence_bound is False
    assert "external_effect_sha256" in receipt.reason
