from __future__ import annotations

import pytest

from agent_control_plane.remote_mutation_journal import (
    MutationJournalEvent,
    MutationJournalRecord,
    MutationJournalState,
)
from agent_control_plane.remote_mutation_rollback_custody import (
    RollbackCustodyAdmissionRecord,
    RollbackMaterialDescriptor,
    RollbackMode,
)
from agent_control_plane.remote_mutation_rollback_journal import (
    ROLLBACK_JOURNAL_SCHEMA_VERSION,
    RemoteMutationRollbackJournal,
    RollbackJournalError,
    RollbackJournalState,
    RollbackRecoveryDisposition,
)
from agent_control_plane.remote_mutation_rollback_plan import (
    ROLLBACK_PLAN_SCHEMA_VERSION,
    RepositoryRollbackPlan,
    RollbackAction,
    RollbackPlanError,
    build_repository_rollback_plan,
)
from agent_control_plane.remote_mutation_transaction import MutationPlan

A = "a" * 64
B = "b" * 64
C = "c" * 64
D = "d" * 64


def original_write(*, created=False):
    descriptor = RollbackMaterialDescriptor(
        operation_id="repo.write_text_file",
        path="docs/example.md",
        mode=(
            RollbackMode.DELETE_CREATED_FILE
            if created
            else RollbackMode.RESTORE_FILE_BYTES
        ),
        prior_content_sha256=None if created else B,
        prior_content_size=None if created else 6,
    )
    plan = MutationPlan(
        request_id="req-original-1",
        authority_id="auth-original-1",
        resource_id="repo:test",
        resource_type="git_repository",
        operation_id="repo.write_text_file",
        parameters={"path": "docs/example.md", "content_sha256": C},
        precondition_sha256=A,
        rollback_sha256=descriptor.descriptor_sha256,
    )
    return plan, descriptor


def original_delete():
    descriptor = RollbackMaterialDescriptor(
        operation_id="repo.delete_file",
        path="docs/example.md",
        mode=RollbackMode.RESTORE_FILE_BYTES,
        prior_content_sha256=B,
        prior_content_size=6,
    )
    plan = MutationPlan(
        request_id="req-original-delete",
        authority_id="auth-original-delete",
        resource_id="repo:test",
        resource_type="git_repository",
        operation_id="repo.delete_file",
        parameters={"path": "docs/example.md", "prior_content_sha256": B},
        precondition_sha256=A,
        rollback_sha256=descriptor.descriptor_sha256,
    )
    return plan, descriptor


def custody_for(plan, descriptor):
    return RollbackCustodyAdmissionRecord(
        request_id=plan.request_id,
        resource_id=plan.resource_id,
        operation_id=plan.operation_id,
        plan_sha256=plan.plan_sha256,
        descriptor_sha256=descriptor.descriptor_sha256,
        custody_ref="custody://rollback/test-1",
        admitted=True,
        reason="verified",
        readback_verified=True,
    )


def journal_for(plan, descriptor, *, current=MutationJournalState.FAILED, with_intent=True):
    events = [
        MutationJournalEvent(
            transaction_id="tx-original-1",
            event_index=0,
            state=MutationJournalState.PREPARED,
            occurred_at="2026-09-27T12:00:00Z",
        )
    ]
    index = 1
    if with_intent:
        events.append(
            MutationJournalEvent(
                transaction_id="tx-original-1",
                event_index=index,
                state=MutationJournalState.EXECUTION_INTENT_RECORDED,
                occurred_at="2026-09-27T12:00:01Z",
            )
        )
        index += 1
    if current is MutationJournalState.EXTERNAL_EFFECT_REPORTED:
        events.append(
            MutationJournalEvent(
                transaction_id="tx-original-1",
                event_index=index,
                state=current,
                occurred_at="2026-09-27T12:00:02Z",
                evidence_sha256=D,
            )
        )
    elif current is MutationJournalState.POSTCONDITION_VERIFIED:
        events.append(
            MutationJournalEvent(
                transaction_id="tx-original-1",
                event_index=index,
                state=MutationJournalState.EXTERNAL_EFFECT_REPORTED,
                occurred_at="2026-09-27T12:00:02Z",
                evidence_sha256=D,
            )
        )
        events.append(
            MutationJournalEvent(
                transaction_id="tx-original-1",
                event_index=index + 1,
                state=current,
                occurred_at="2026-09-27T12:00:03Z",
                evidence_sha256=C,
            )
        )
    elif current is MutationJournalState.FAILED:
        events.append(
            MutationJournalEvent(
                transaction_id="tx-original-1",
                event_index=index,
                state=current,
                occurred_at="2026-09-27T12:00:02Z",
                error="simulated failure",
            )
        )
    elif current is MutationJournalState.EXECUTION_INTENT_RECORDED:
        pass
    elif current is MutationJournalState.PREPARED:
        events = events[:1]
    else:
        raise AssertionError(current)

    return MutationJournalRecord(
        transaction_id="tx-original-1",
        request_id=plan.request_id,
        resource_id=plan.resource_id,
        operation_id=plan.operation_id,
        plan_sha256=plan.plan_sha256,
        rollback_descriptor_sha256=descriptor.descriptor_sha256,
        custody_ref="custody://rollback/test-1",
        created_at="2026-09-27T12:00:00Z",
        events=tuple(events),
    )


def rollback_plan(*, created=False, original_state=MutationJournalState.FAILED):
    plan, descriptor = original_write(created=created)
    current_exists = True
    current_sha = C
    return build_repository_rollback_plan(
        plan,
        descriptor,
        custody_for(plan, descriptor),
        journal_for(plan, descriptor, current=original_state),
        rollback_request_id="rollback-req-1",
        rollback_authority_id="rollback-auth-1",
        rollback_transaction_id="rollback-tx-1",
        expected_current_target_exists=current_exists,
        expected_current_content_sha256=current_sha,
    )


def test_restore_plan_is_separate_nonexecuting_action():
    plan = rollback_plan(created=False)
    assert plan.schema_version == ROLLBACK_PLAN_SCHEMA_VERSION
    assert plan.action is RollbackAction.RESTORE_FILE_BYTES
    assert plan.desired_target_exists is True
    assert plan.desired_content_sha256 == B
    assert plan.expected_current_content_sha256 == C
    assert plan.execution_enabled is False
    assert plan.rollback_executed is False
    assert len(plan.rollback_plan_sha256) == 64
    assert plan.rollback_transaction_id != plan.original_transaction_id


def test_created_file_plan_requests_delete_of_created_file():
    plan = rollback_plan(created=True)
    assert plan.action is RollbackAction.DELETE_CREATED_FILE
    assert plan.desired_target_exists is False
    assert plan.desired_content_sha256 is None


def test_delete_original_plan_restores_prior_bytes():
    original, descriptor = original_delete()
    plan = build_repository_rollback_plan(
        original,
        descriptor,
        custody_for(original, descriptor),
        journal_for(original, descriptor),
        rollback_request_id="rollback-delete-req",
        rollback_authority_id="rollback-delete-auth",
        rollback_transaction_id="rollback-delete-tx",
        expected_current_target_exists=False,
        expected_current_content_sha256=None,
    )
    assert plan.action is RollbackAction.RESTORE_FILE_BYTES
    assert plan.desired_content_sha256 == B


def test_pre_execution_journal_is_not_rollback_eligible():
    original, descriptor = original_write()
    with pytest.raises(RollbackPlanError, match="execution intent"):
        build_repository_rollback_plan(
            original,
            descriptor,
            custody_for(original, descriptor),
            journal_for(
                original,
                descriptor,
                current=MutationJournalState.PREPARED,
                with_intent=False,
            ),
            rollback_request_id="rb",
            rollback_authority_id="auth",
            rollback_transaction_id="tx",
            expected_current_target_exists=True,
            expected_current_content_sha256=C,
        )


def test_verified_success_is_not_recovery_rollback_eligible():
    original, descriptor = original_write()
    with pytest.raises(RollbackPlanError, match="not eligible"):
        build_repository_rollback_plan(
            original,
            descriptor,
            custody_for(original, descriptor),
            journal_for(
                original,
                descriptor,
                current=MutationJournalState.POSTCONDITION_VERIFIED,
            ),
            rollback_request_id="rb",
            rollback_authority_id="auth",
            rollback_transaction_id="tx",
            expected_current_target_exists=True,
            expected_current_content_sha256=C,
        )


def test_custody_identity_drift_blocks_plan():
    original, descriptor = original_write()
    bad = RollbackCustodyAdmissionRecord(
        request_id=original.request_id,
        resource_id=original.resource_id,
        operation_id=original.operation_id,
        plan_sha256=original.plan_sha256,
        descriptor_sha256=D,
        custody_ref="custody://rollback/test-1",
        admitted=True,
        reason="bad",
        readback_verified=True,
    )
    with pytest.raises(RollbackPlanError, match="identities diverge"):
        build_repository_rollback_plan(
            original,
            descriptor,
            bad,
            journal_for(original, descriptor),
            rollback_request_id="rb",
            rollback_authority_id="auth",
            rollback_transaction_id="tx",
            expected_current_target_exists=True,
            expected_current_content_sha256=C,
        )


def test_current_state_expectation_must_be_explicit():
    with pytest.raises(RollbackPlanError, match="requires content sha256"):
        RepositoryRollbackPlan(
            rollback_request_id="rb",
            rollback_authority_id="auth",
            rollback_transaction_id="rb-tx",
            original_transaction_id="orig-tx",
            original_request_id="orig-req",
            resource_id="repo:test",
            original_operation_id="repo.write_text_file",
            original_plan_sha256=A,
            original_journal_state="failed",
            requested_path="docs/example.md",
            rollback_descriptor_sha256=B,
            rollback_custody_ref="custody://x",
            action=RollbackAction.RESTORE_FILE_BYTES,
            expected_current_target_exists=True,
            expected_current_content_sha256=None,
            desired_target_exists=True,
            desired_content_sha256=C,
        )


def test_rollback_plan_cannot_claim_execution():
    plan = rollback_plan()
    values = dict(plan.__dict__)
    values["rollback_executed"] = True
    with pytest.raises(RollbackPlanError, match="cannot enable"):
        RepositoryRollbackPlan(**values)


def test_rollback_journal_begins_separately_and_preserves_linkage(tmp_path):
    plan = rollback_plan()
    store = RemoteMutationRollbackJournal(tmp_path / "rollback.sqlite3")
    record = store.begin(plan=plan, created_at="2026-09-27T13:00:00Z")
    assert record.schema_version == ROLLBACK_JOURNAL_SCHEMA_VERSION
    assert record.current_state is RollbackJournalState.PREPARED
    assert record.original_transaction_id == plan.original_transaction_id
    assert record.rollback_plan_sha256 == plan.rollback_plan_sha256


def test_rollback_journal_recovery_state_machine(tmp_path):
    plan = rollback_plan()
    store = RemoteMutationRollbackJournal(tmp_path / "rollback.sqlite3")
    store.begin(plan=plan, created_at="2026-09-27T13:00:00Z")

    prepared = store.assess_recovery(plan.rollback_transaction_id)
    assert prepared.disposition is RollbackRecoveryDisposition.SAFE_PRE_ROLLBACK
    assert prepared.rollback_effect_may_exist is False

    store.append(
        plan.rollback_transaction_id,
        state=RollbackJournalState.ROLLBACK_INTENT_RECORDED,
        occurred_at="2026-09-27T13:00:01Z",
    )
    intent = store.assess_recovery(plan.rollback_transaction_id)
    assert intent.disposition is RollbackRecoveryDisposition.HOLD_AMBIGUOUS_ROLLBACK
    assert intent.rollback_effect_may_exist is True

    store.append(
        plan.rollback_transaction_id,
        state=RollbackJournalState.ROLLBACK_EFFECT_REPORTED,
        occurred_at="2026-09-27T13:00:02Z",
        evidence_sha256=C,
    )
    effect = store.assess_recovery(plan.rollback_transaction_id)
    assert effect.disposition is RollbackRecoveryDisposition.HOLD_ROLLBACK_POSTCONDITION_REQUIRED

    store.append(
        plan.rollback_transaction_id,
        state=RollbackJournalState.ROLLBACK_VERIFIED,
        occurred_at="2026-09-27T13:00:03Z",
        evidence_sha256=D,
    )
    clean = store.assess_recovery(plan.rollback_transaction_id)
    assert clean.disposition is RollbackRecoveryDisposition.CLEAN_ROLLED_BACK
    assert clean.rollback_effect_may_exist is True
    assert clean.new_rollback_authorization_required is True


def test_failed_before_rollback_intent_is_no_effect(tmp_path):
    plan = rollback_plan()
    store = RemoteMutationRollbackJournal(tmp_path / "rollback.sqlite3")
    store.begin(plan=plan, created_at="2026-09-27T13:00:00Z")
    store.append(
        plan.rollback_transaction_id,
        state=RollbackJournalState.FAILED,
        occurred_at="2026-09-27T13:00:01Z",
        error="pre-rollback failure",
    )
    assessment = store.assess_recovery(plan.rollback_transaction_id)
    assert assessment.disposition is RollbackRecoveryDisposition.FAILED_PRE_ROLLBACK
    assert assessment.rollback_effect_may_exist is False


def test_failed_after_rollback_intent_holds(tmp_path):
    plan = rollback_plan()
    store = RemoteMutationRollbackJournal(tmp_path / "rollback.sqlite3")
    store.begin(plan=plan, created_at="2026-09-27T13:00:00Z")
    store.append(
        plan.rollback_transaction_id,
        state=RollbackJournalState.ROLLBACK_INTENT_RECORDED,
        occurred_at="2026-09-27T13:00:01Z",
    )
    store.append(
        plan.rollback_transaction_id,
        state=RollbackJournalState.FAILED,
        occurred_at="2026-09-27T13:00:02Z",
        error="rollback interrupted",
    )
    assessment = store.assess_recovery(plan.rollback_transaction_id)
    assert assessment.disposition is RollbackRecoveryDisposition.HOLD_FAILED_AFTER_ROLLBACK_INTENT
    assert assessment.rollback_effect_may_exist is True


def test_rollback_journal_requires_evidence_hash(tmp_path):
    plan = rollback_plan()
    store = RemoteMutationRollbackJournal(tmp_path / "rollback.sqlite3")
    store.begin(plan=plan, created_at="2026-09-27T13:00:00Z")
    store.append(
        plan.rollback_transaction_id,
        state=RollbackJournalState.ROLLBACK_INTENT_RECORDED,
        occurred_at="2026-09-27T13:00:01Z",
    )
    with pytest.raises(RollbackJournalError, match="requires evidence"):
        store.append(
            plan.rollback_transaction_id,
            state=RollbackJournalState.ROLLBACK_EFFECT_REPORTED,
            occurred_at="2026-09-27T13:00:02Z",
        )


def test_rollback_journal_survives_reopen(tmp_path):
    plan = rollback_plan()
    db = tmp_path / "rollback.sqlite3"
    store = RemoteMutationRollbackJournal(db)
    store.begin(plan=plan, created_at="2026-09-27T13:00:00Z")
    store.append(
        plan.rollback_transaction_id,
        state=RollbackJournalState.ROLLBACK_INTENT_RECORDED,
        occurred_at="2026-09-27T13:00:01Z",
    )

    reopened = RemoteMutationRollbackJournal(db)
    record = reopened.get(plan.rollback_transaction_id)
    assert record is not None
    assert record.current_state is RollbackJournalState.ROLLBACK_INTENT_RECORDED
    assessment = reopened.assess_recovery(plan.rollback_transaction_id)
    assert assessment.disposition is RollbackRecoveryDisposition.HOLD_AMBIGUOUS_ROLLBACK


def test_original_failed_journal_is_not_modified_by_rollback_journal(tmp_path):
    original, descriptor = original_write()
    original_record = journal_for(original, descriptor)
    original_events = original_record.events
    plan = build_repository_rollback_plan(
        original,
        descriptor,
        custody_for(original, descriptor),
        original_record,
        rollback_request_id="rb",
        rollback_authority_id="auth",
        rollback_transaction_id="rb-tx",
        expected_current_target_exists=True,
        expected_current_content_sha256=C,
    )
    store = RemoteMutationRollbackJournal(tmp_path / "rollback.sqlite3")
    store.begin(plan=plan, created_at="2026-09-27T13:00:00Z")
    assert original_record.events == original_events
    assert original_record.current_state is MutationJournalState.FAILED
