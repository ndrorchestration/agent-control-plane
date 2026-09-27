from __future__ import annotations

from pathlib import Path
import sqlite3

import pytest

from agent_control_plane.remote_mutation_path_safety import MutationPathSafetyRecord
from agent_control_plane.remote_mutation_postcondition import (
    MutationPostconditionRecord,
)
from agent_control_plane.remote_mutation_recovery_journal import (
    MutationJournalState,
    MutationRecoveryDisposition,
    MutationRecoveryJournal,
    MutationRecoveryJournalError,
)
from agent_control_plane.remote_mutation_rollback_custody import (
    RollbackCustodyAdmissionRecord,
    RollbackMaterialDescriptor,
    RollbackMode,
)
from agent_control_plane.remote_mutation_transaction import MutationPlan

A = "a" * 64
B = "b" * 64
C = "c" * 64


def build():
    descriptor = RollbackMaterialDescriptor(
        operation_id="repo.write_text_file",
        path="docs/example.md",
        mode=RollbackMode.RESTORE_FILE_BYTES,
        prior_content_sha256=B,
        prior_content_size=6,
    )
    plan = MutationPlan(
        request_id="req-recovery",
        authority_id="auth-recovery",
        resource_id="repo:acp",
        resource_type="git_repository",
        operation_id="repo.write_text_file",
        parameters={
            "path": "docs/example.md",
            "content_sha256": C,
        },
        precondition_sha256=A,
        rollback_sha256=descriptor.descriptor_sha256,
    )
    path = MutationPathSafetyRecord(
        request_id=plan.request_id,
        resource_id=plan.resource_id,
        operation_id=plan.operation_id,
        plan_sha256=plan.plan_sha256,
        requested_path=plan.parameters["path"],
        repository_root="C:/repo",
        resolved_path="C:/repo/docs/example.md",
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
        custody_ref="custody://recovery/1",
        admitted=True,
        reason="verified",
        readback_verified=True,
    )
    postcondition = MutationPostconditionRecord(
        request_id=plan.request_id,
        resource_id=plan.resource_id,
        operation_id=plan.operation_id,
        plan_sha256=plan.plan_sha256,
        requested_path=plan.parameters["path"],
        repository_root="C:/repo",
        resolved_path="C:/repo/docs/example.md",
        rollback_descriptor_sha256=descriptor.descriptor_sha256,
        rollback_custody_ref=custody.custody_ref,
        target_exists=True,
        observed_content_sha256=C,
        path_revalidated=True,
        postcondition_verified=True,
        reason="verified",
    )
    return plan, path, custody, postcondition


def begin(tmp_path: Path):
    plan, path, custody, postcondition = build()
    journal = MutationRecoveryJournal(tmp_path / "recovery.sqlite3")
    record = journal.begin(
        journal_id="journal-1",
        plan=plan,
        path_safety=path,
        rollback_custody=custody,
    )
    return journal, record, plan, path, custody, postcondition


def test_prepared_journal_is_safe_pre_effect(tmp_path):
    journal, record, *_ = begin(tmp_path)

    assert record.current_state is MutationJournalState.PREPARED
    assessment = journal.assess(record.journal_id)
    assert assessment.disposition is MutationRecoveryDisposition.SAFE_PRE_EFFECT
    assert assessment.effect_may_exist is False
    assert assessment.recovery_hold is False
    assert assessment.execution_enabled is False
    assert assessment.mutation_executed is False


def test_effect_intent_without_postcondition_holds_unknown_effect(tmp_path):
    journal, record, *_ = begin(tmp_path)
    journal.append(record.journal_id, MutationJournalState.EFFECT_INTENT_RECORDED)

    assessment = journal.assess(record.journal_id)

    assert assessment.disposition is MutationRecoveryDisposition.HOLD_UNKNOWN_EFFECT
    assert assessment.effect_may_exist is True
    assert assessment.recovery_hold is True


def test_verified_postcondition_advances_and_can_close(tmp_path):
    journal, record, *_, postcondition = begin(tmp_path)
    journal.append(record.journal_id, MutationJournalState.EFFECT_INTENT_RECORDED)
    journal.append(
        record.journal_id,
        MutationJournalState.POSTCONDITION_VERIFIED,
        postcondition=postcondition,
    )

    assessment = journal.assess(record.journal_id)
    assert assessment.disposition is MutationRecoveryDisposition.VERIFIED_EFFECT
    assert assessment.recovery_hold is False

    closed = journal.append(
        record.journal_id,
        MutationJournalState.CLOSED_VERIFIED,
    )
    assert closed.current_state is MutationJournalState.CLOSED_VERIFIED
    assert (
        journal.assess(record.journal_id).disposition
        is MutationRecoveryDisposition.CLEAN_VERIFIED
    )


def test_pre_effect_close_never_implies_effect(tmp_path):
    journal, record, *_ = begin(tmp_path)
    journal.append(record.journal_id, MutationJournalState.CLOSED_PRE_EFFECT)

    assessment = journal.assess(record.journal_id)
    assert assessment.disposition is MutationRecoveryDisposition.CLEAN_PRE_EFFECT
    assert assessment.effect_may_exist is False


def test_restart_preserves_unknown_effect_hold(tmp_path):
    journal, record, *_ = begin(tmp_path)
    journal.append(record.journal_id, MutationJournalState.EFFECT_INTENT_RECORDED)

    reopened = MutationRecoveryJournal(tmp_path / "recovery.sqlite3")
    restored = reopened.get(record.journal_id)
    assert restored is not None
    assert restored.current_state is MutationJournalState.EFFECT_INTENT_RECORDED
    assert reopened.assess(record.journal_id).recovery_hold is True


def test_begin_is_idempotent_for_same_identity(tmp_path):
    journal, record, plan, path, custody, _ = begin(tmp_path)

    again = journal.begin(
        journal_id=record.journal_id,
        plan=plan,
        path_safety=path,
        rollback_custody=custody,
    )

    assert again == record
    assert len(again.events) == 1


def test_journal_id_conflict_fails_closed(tmp_path):
    journal, record, plan, path, custody, _ = begin(tmp_path)
    other = MutationPlan(
        request_id="other-request",
        authority_id=plan.authority_id,
        resource_id=plan.resource_id,
        resource_type=plan.resource_type,
        operation_id=plan.operation_id,
        parameters=plan.parameters,
        precondition_sha256=plan.precondition_sha256,
        rollback_sha256=plan.rollback_sha256,
    )
    bad_path = MutationPathSafetyRecord(
        **{
            **path.__dict__,
            "request_id": other.request_id,
            "plan_sha256": other.plan_sha256,
        }
    )
    bad_custody = RollbackCustodyAdmissionRecord(
        **{
            **custody.__dict__,
            "request_id": other.request_id,
            "plan_sha256": other.plan_sha256,
        }
    )

    with pytest.raises(MutationRecoveryJournalError, match="different mutation"):
        journal.begin(
            journal_id=record.journal_id,
            plan=other,
            path_safety=bad_path,
            rollback_custody=bad_custody,
        )


def test_postcondition_identity_substitution_fails_closed(tmp_path):
    journal, record, _, _, _, postcondition = begin(tmp_path)
    journal.append(record.journal_id, MutationJournalState.EFFECT_INTENT_RECORDED)
    bad = MutationPostconditionRecord(
        **{
            **postcondition.__dict__,
            "rollback_custody_ref": "custody://other",
        }
    )

    with pytest.raises(MutationRecoveryJournalError, match="not congruent"):
        journal.append(
            record.journal_id,
            MutationJournalState.POSTCONDITION_VERIFIED,
            postcondition=bad,
        )


def test_invalid_transition_fails_closed(tmp_path):
    journal, record, *_ = begin(tmp_path)

    with pytest.raises(MutationRecoveryJournalError, match="invalid journal"):
        journal.append(record.journal_id, MutationJournalState.CLOSED_VERIFIED)


def test_terminal_journal_rejects_further_events(tmp_path):
    journal, record, *_ = begin(tmp_path)
    journal.append(record.journal_id, MutationJournalState.CLOSED_PRE_EFFECT)

    with pytest.raises(MutationRecoveryJournalError, match="already terminal"):
        journal.append(
            record.journal_id,
            MutationJournalState.EFFECT_INTENT_RECORDED,
        )


def test_custody_descriptor_substitution_fails_begin(tmp_path):
    plan, path, custody, _ = build()
    bad = RollbackCustodyAdmissionRecord(
        request_id=custody.request_id,
        resource_id=custody.resource_id,
        operation_id=custody.operation_id,
        plan_sha256=custody.plan_sha256,
        descriptor_sha256="f" * 64,
        custody_ref=custody.custody_ref,
        admitted=True,
        reason="fabricated",
        readback_verified=True,
    )
    journal = MutationRecoveryJournal(tmp_path / "recovery.sqlite3")

    with pytest.raises(MutationRecoveryJournalError, match="custody"):
        journal.begin(
            journal_id="journal-bad",
            plan=plan,
            path_safety=path,
            rollback_custody=bad,
        )


def test_corrupted_persisted_history_fails_closed(tmp_path):
    journal, record, *_ = begin(tmp_path)
    database = tmp_path / "recovery.sqlite3"
    with sqlite3.connect(database) as connection:
        connection.execute(
            """
            UPDATE mutation_recovery_event
            SET state = ?
            WHERE journal_id = ? AND event_index = 0
            """,
            (
                MutationJournalState.CLOSED_VERIFIED.value,
                record.journal_id,
            ),
        )

    reopened = MutationRecoveryJournal(database)
    with pytest.raises(
        MutationRecoveryJournalError,
        match="must begin in prepared state",
    ):
        reopened.get(record.journal_id)
