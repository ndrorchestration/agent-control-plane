from __future__ import annotations

from pathlib import Path

import pytest

from agent_control_plane.remote_mutation_journal import (
    MUTATION_JOURNAL_SCHEMA_VERSION,
    MutationJournalError,
    MutationJournalState,
    MutationRecoveryDisposition,
    RemoteMutationJournal,
)
from agent_control_plane.remote_mutation_path_safety import MutationPathSafetyRecord
from agent_control_plane.remote_mutation_rollback_custody import (
    RollbackCustodyAdmissionRecord,
    RollbackMaterialDescriptor,
    RollbackMode,
)
from agent_control_plane.remote_mutation_transaction import MutationPlan

A = "a" * 64
B = "b" * 64
C = "c" * 64
D = "d" * 64


def upstream():
    descriptor = RollbackMaterialDescriptor(
        operation_id="repo.write_text_file",
        path="docs/example.md",
        mode=RollbackMode.RESTORE_FILE_BYTES,
        prior_content_sha256=B,
        prior_content_size=6,
    )
    plan = MutationPlan(
        request_id="req-journal-1",
        authority_id="auth-journal-1",
        resource_id="repo:acp",
        resource_type="git_repository",
        operation_id="repo.write_text_file",
        parameters={"path": "docs/example.md", "content_sha256": C},
        precondition_sha256=A,
        rollback_sha256=descriptor.descriptor_sha256,
    )
    path = MutationPathSafetyRecord(
        request_id=plan.request_id,
        resource_id=plan.resource_id,
        operation_id=plan.operation_id,
        plan_sha256=plan.plan_sha256,
        requested_path=plan.parameters["path"],
        repository_root=str(Path.cwd()),
        resolved_path=str(Path.cwd() / plan.parameters["path"]),
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
        custody_ref="custody://operator-local/journal-1",
        admitted=True,
        reason="verified",
        readback_verified=True,
    )
    return plan, path, custody


def begin(tmp_path, transaction_id="tx-1"):
    plan, path, custody = upstream()
    journal = RemoteMutationJournal(tmp_path / "mutation.sqlite3")
    record = journal.begin(
        transaction_id=transaction_id, plan=plan, path_safety=path,
        rollback_custody=custody, created_at="2026-09-27T08:00:00Z",
    )
    return journal, record, plan, path, custody


def append(journal, state, second, *, evidence=None, error=None):
    return journal.append(
        "tx-1", state=state, occurred_at=f"2026-09-27T08:00:{second:02d}Z",
        evidence_sha256=evidence, error=error,
    )


def test_begin_is_idempotent_and_binds_exact_upstream_identity(tmp_path):
    journal, record, plan, path, custody = begin(tmp_path)
    assert record.schema_version == MUTATION_JOURNAL_SCHEMA_VERSION
    assert record.current_state is MutationJournalState.PREPARED
    assert record.plan_sha256 == plan.plan_sha256
    same = journal.begin(
        transaction_id="tx-1", plan=plan, path_safety=path, rollback_custody=custody,
        created_at="2026-09-27T08:00:00Z",
    )
    assert same == record


def test_transaction_id_conflict_fails_closed(tmp_path):
    journal, _, plan, path, custody = begin(tmp_path)
    with pytest.raises(MutationJournalError, match="transaction_id conflict"):
        journal.begin(
            transaction_id="tx-1", plan=plan, path_safety=path,
            rollback_custody=custody, created_at="2026-09-27T08:00:01Z",
        )


def test_prepared_recovery_is_safe_pre_execution(tmp_path):
    journal, _, *_ = begin(tmp_path)
    assessment = journal.assess_recovery("tx-1")
    assert assessment.disposition is MutationRecoveryDisposition.SAFE_PRE_EXECUTION
    assert assessment.repository_mutation_may_exist is False
    assert assessment.new_execution_authorization_required is True


def test_crash_after_execution_intent_holds_ambiguous_effect(tmp_path):
    journal, _, *_ = begin(tmp_path)
    append(journal, MutationJournalState.EXECUTION_INTENT_RECORDED, 1)
    assessment = journal.assess_recovery("tx-1")
    assert assessment.disposition is MutationRecoveryDisposition.HOLD_AMBIGUOUS_EFFECT
    assert assessment.repository_mutation_may_exist is True


def test_reported_effect_requires_postcondition(tmp_path):
    journal, _, *_ = begin(tmp_path)
    append(journal, MutationJournalState.EXECUTION_INTENT_RECORDED, 1)
    append(journal, MutationJournalState.EXTERNAL_EFFECT_REPORTED, 2, evidence=C)
    assessment = journal.assess_recovery("tx-1")
    assert assessment.disposition is MutationRecoveryDisposition.HOLD_POSTCONDITION_REQUIRED
    assert assessment.repository_mutation_may_exist is True


def test_verified_postcondition_is_clean_terminal_observation(tmp_path):
    journal, _, *_ = begin(tmp_path)
    append(journal, MutationJournalState.EXECUTION_INTENT_RECORDED, 1)
    append(journal, MutationJournalState.EXTERNAL_EFFECT_REPORTED, 2, evidence=C)
    append(journal, MutationJournalState.POSTCONDITION_VERIFIED, 3, evidence=D)
    assessment = journal.assess_recovery("tx-1")
    assert assessment.disposition is MutationRecoveryDisposition.CLEAN_POSTCONDITION_VERIFIED
    assert assessment.repository_mutation_may_exist is True
    with pytest.raises(MutationJournalError, match="terminal"):
        append(journal, MutationJournalState.ROLLBACK_INTENT_RECORDED, 4)


def test_rollback_intent_is_ambiguous_until_verified(tmp_path):
    journal, _, *_ = begin(tmp_path)
    append(journal, MutationJournalState.EXECUTION_INTENT_RECORDED, 1)
    append(journal, MutationJournalState.EXTERNAL_EFFECT_REPORTED, 2, evidence=C)
    append(journal, MutationJournalState.ROLLBACK_INTENT_RECORDED, 3)
    assessment = journal.assess_recovery("tx-1")
    assert assessment.disposition is MutationRecoveryDisposition.HOLD_ROLLBACK_AMBIGUOUS
    assert assessment.repository_mutation_may_exist is True


def test_verified_rollback_classifies_clean_no_remaining_mutation(tmp_path):
    journal, _, *_ = begin(tmp_path)
    append(journal, MutationJournalState.EXECUTION_INTENT_RECORDED, 1)
    append(journal, MutationJournalState.EXTERNAL_EFFECT_REPORTED, 2, evidence=C)
    append(journal, MutationJournalState.ROLLBACK_INTENT_RECORDED, 3)
    append(journal, MutationJournalState.ROLLBACK_VERIFIED, 4, evidence=D)
    assessment = journal.assess_recovery("tx-1")
    assert assessment.disposition is MutationRecoveryDisposition.CLEAN_ROLLED_BACK
    assert assessment.repository_mutation_may_exist is False


def test_failure_before_execution_intent_is_nonmutating_failure(tmp_path):
    journal, _, *_ = begin(tmp_path)
    append(journal, MutationJournalState.FAILED, 1, error="pre-execution gate failed")
    assessment = journal.assess_recovery("tx-1")
    assert assessment.disposition is MutationRecoveryDisposition.FAILED_PRE_EXECUTION
    assert assessment.repository_mutation_may_exist is False


def test_failure_after_execution_intent_holds_possible_effect(tmp_path):
    journal, _, *_ = begin(tmp_path)
    append(journal, MutationJournalState.EXECUTION_INTENT_RECORDED, 1)
    append(journal, MutationJournalState.FAILED, 2, error="external executor disconnected")
    assessment = journal.assess_recovery("tx-1")
    assert assessment.disposition is MutationRecoveryDisposition.HOLD_FAILED_AFTER_EXECUTION_INTENT
    assert assessment.repository_mutation_may_exist is True


def test_invalid_transition_fails_closed(tmp_path):
    journal, _, *_ = begin(tmp_path)
    with pytest.raises(MutationJournalError, match="invalid mutation journal transition"):
        append(journal, MutationJournalState.POSTCONDITION_VERIFIED, 1, evidence=D)


@pytest.mark.parametrize(
    "state",
    [MutationJournalState.EXTERNAL_EFFECT_REPORTED, MutationJournalState.POSTCONDITION_VERIFIED, MutationJournalState.ROLLBACK_VERIFIED],
)
def test_evidence_states_require_sha256(tmp_path, state):
    journal, _, *_ = begin(tmp_path)
    if state is not MutationJournalState.EXTERNAL_EFFECT_REPORTED:
        append(journal, MutationJournalState.EXECUTION_INTENT_RECORDED, 1)
        if state is MutationJournalState.POSTCONDITION_VERIFIED:
            append(journal, MutationJournalState.EXTERNAL_EFFECT_REPORTED, 2, evidence=C)
        else:
            append(journal, MutationJournalState.ROLLBACK_INTENT_RECORDED, 2)
    else:
        append(journal, MutationJournalState.EXECUTION_INTENT_RECORDED, 1)
    with pytest.raises(MutationJournalError, match="requires evidence_sha256"):
        journal.append("tx-1", state=state, occurred_at="2026-09-27T08:00:03Z")


def test_failed_state_requires_error(tmp_path):
    journal, _, *_ = begin(tmp_path)
    with pytest.raises(MutationJournalError, match="requires error"):
        append(journal, MutationJournalState.FAILED, 1)


def test_unadmitted_upstream_records_cannot_begin_journal(tmp_path):
    plan, path, custody = upstream()
    bad_path = MutationPathSafetyRecord(
        request_id=path.request_id, resource_id=path.resource_id,
        operation_id=path.operation_id, plan_sha256=path.plan_sha256,
        requested_path=path.requested_path, repository_root=path.repository_root,
        resolved_path=path.resolved_path, admitted=False, reason="blocked",
        repository_boundary_verified=False, symlink_safe=False,
        repository_metadata_safe=False, operation_shape_verified=False,
        target_exists=True,
    )
    journal = RemoteMutationJournal(tmp_path / "mutation.sqlite3")
    with pytest.raises(MutationJournalError, match="path safety must be admitted"):
        journal.begin(
            transaction_id="tx-bad", plan=plan, path_safety=bad_path,
            rollback_custody=custody, created_at="2026-09-27T08:00:00Z",
        )


def test_journal_survives_reopen_and_preserves_event_order(tmp_path):
    db = tmp_path / "mutation.sqlite3"
    journal, _, *_ = begin(tmp_path)
    append(journal, MutationJournalState.EXECUTION_INTENT_RECORDED, 1)
    append(journal, MutationJournalState.EXTERNAL_EFFECT_REPORTED, 2, evidence=C)
    reopened = RemoteMutationJournal(db)
    record = reopened.get("tx-1")
    assert record is not None
    assert [event.event_index for event in record.events] == [0, 1, 2]
    assert record.current_state is MutationJournalState.EXTERNAL_EFFECT_REPORTED