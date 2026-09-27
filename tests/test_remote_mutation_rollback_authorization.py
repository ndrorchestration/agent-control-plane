from pathlib import Path

import pytest

from agent_control_plane.remote_mutation_composition import MutationCompositionRecord
from agent_control_plane.remote_mutation_journal import (
    MutationJournalState,
    RemoteMutationJournal,
)
from agent_control_plane.remote_mutation_path_safety import (
    inspect_repository_mutation_path,
)
from agent_control_plane.remote_mutation_rollback_authorization import (
    ROLLBACK_OPERATION_ID,
    RemoteMutationRollbackAuthorizationStore,
    RollbackAuthorizationError,
    RollbackCurrentStateObservation,
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


def repo(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    (root / ".git").mkdir()
    (root / "docs").mkdir()
    return root


def build(
    tmp_path,
    *,
    operation_id="repo.write_text_file",
    target_existed=True,
):
    root = repo(tmp_path)
    target = root / "docs" / "example.md"
    if target_existed:
        target.write_bytes(b"before")

    if operation_id == "repo.write_text_file":
        descriptor = (
            RollbackMaterialDescriptor(
                operation_id=operation_id,
                path="docs/example.md",
                mode=RollbackMode.RESTORE_FILE_BYTES,
                prior_content_sha256=B,
                prior_content_size=6,
            )
            if target_existed
            else RollbackMaterialDescriptor(
                operation_id=operation_id,
                path="docs/example.md",
                mode=RollbackMode.DELETE_CREATED_FILE,
            )
        )
        parameters = {
            "path": "docs/example.md",
            "content_sha256": C,
        }
    else:
        descriptor = RollbackMaterialDescriptor(
            operation_id=operation_id,
            path="docs/example.md",
            mode=RollbackMode.RESTORE_FILE_BYTES,
            prior_content_sha256=B,
            prior_content_size=6,
        )
        parameters = {
            "path": "docs/example.md",
            "prior_content_sha256": B,
        }

    plan = MutationPlan(
        request_id="req-rollback",
        authority_id="auth-forward",
        resource_id="repo:test",
        resource_type="git_repository",
        operation_id=operation_id,
        parameters=parameters,
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
    path_safety = inspect_repository_mutation_path(
        composition,
        plan,
        repository_root=root,
    )
    assert path_safety.admitted is True

    custody = RollbackCustodyAdmissionRecord(
        request_id=plan.request_id,
        resource_id=plan.resource_id,
        operation_id=plan.operation_id,
        plan_sha256=plan.plan_sha256,
        descriptor_sha256=descriptor.descriptor_sha256,
        custody_ref="custody://rollback/test",
        admitted=True,
        reason="verified",
        readback_verified=True,
    )
    journal_store = RemoteMutationJournal(tmp_path / "journal.sqlite3")
    journal = journal_store.begin(
        transaction_id="tx-rollback",
        plan=plan,
        path_safety=path_safety,
        rollback_custody=custody,
        created_at="2026-09-27T12:00:00Z",
    )
    journal = journal_store.append(
        journal.transaction_id,
        state=MutationJournalState.EXECUTION_INTENT_RECORDED,
        occurred_at="2026-09-27T12:01:00Z",
    )
    return plan, descriptor, custody, journal_store, journal


def issue(
    tmp_path,
    *,
    operation_id="repo.write_text_file",
    target_existed=True,
    current_state=None,
):
    plan, descriptor, custody, journal_store, journal = build(
        tmp_path,
        operation_id=operation_id,
        target_existed=target_existed,
    )
    if current_state is None:
        if operation_id == "repo.delete_file":
            current_state = RollbackCurrentStateObservation(
                target_exists=False,
                content_sha256=None,
            )
        else:
            current_state = RollbackCurrentStateObservation(
                target_exists=True,
                content_sha256=C,
            )
    store = RemoteMutationRollbackAuthorizationStore(
        tmp_path / "rollback_authorization.sqlite3"
    )
    authorization = store.issue(
        authorization_id="rollback-authz-1",
        rollback_authority_id="authority:rollback:1",
        rollback_executor_id="executor:rollback:1",
        plan=plan,
        descriptor=descriptor,
        custody=custody,
        journal=journal,
        current_state=current_state,
        issued_at="2026-09-27T12:02:00Z",
        expires_at="2026-09-27T12:07:00Z",
    )
    return (
        plan,
        descriptor,
        custody,
        journal_store,
        journal,
        store,
        authorization,
        current_state,
    )


def test_rollback_is_separate_typed_authorization(tmp_path):
    *_, authorization, current_state = issue(tmp_path)

    assert authorization.rollback_operation_id == ROLLBACK_OPERATION_ID
    assert authorization.rollback_authority_id == "authority:rollback:1"
    assert authorization.current_state_sha256 == current_state.observation_sha256
    assert authorization.execution_enabled is False
    assert authorization.rollback_executed is False


def test_single_use_consumption_survives_store_reopen(tmp_path):
    *_, store, authorization, current_state = issue(tmp_path)

    consumed = store.consume(
        authorization.authorization_id,
        rollback_executor_id=authorization.rollback_executor_id,
        current_state_sha256=current_state.observation_sha256,
        now="2026-09-27T12:03:00Z",
    )
    assert consumed.consumed is True

    reopened = RemoteMutationRollbackAuthorizationStore(
        tmp_path / "rollback_authorization.sqlite3"
    )
    with pytest.raises(RollbackAuthorizationError, match="already consumed"):
        reopened.consume(
            authorization.authorization_id,
            rollback_executor_id=authorization.rollback_executor_id,
            current_state_sha256=current_state.observation_sha256,
            now="2026-09-27T12:04:00Z",
        )


def test_concurrent_write_drift_refuses_restore(tmp_path):
    current = RollbackCurrentStateObservation(
        target_exists=True,
        content_sha256="d" * 64,
    )
    with pytest.raises(
        RollbackAuthorizationError,
        match="current repository state is unsafe",
    ):
        issue(tmp_path, current_state=current)


def test_created_file_must_still_match_planned_post_state(tmp_path):
    current = RollbackCurrentStateObservation(
        target_exists=True,
        content_sha256="d" * 64,
    )
    with pytest.raises(
        RollbackAuthorizationError,
        match="current repository state is unsafe",
    ):
        issue(tmp_path, target_existed=False, current_state=current)


def test_delete_rollback_requires_target_still_absent(tmp_path):
    current = RollbackCurrentStateObservation(
        target_exists=True,
        content_sha256="d" * 64,
    )
    with pytest.raises(
        RollbackAuthorizationError,
        match="current repository state is unsafe",
    ):
        issue(
            tmp_path,
            operation_id="repo.delete_file",
            current_state=current,
        )


def test_terminal_journal_state_refuses_new_rollback_authorization(tmp_path):
    plan, descriptor, custody, journal_store, journal = build(tmp_path)
    journal_store.append(
        journal.transaction_id,
        state=MutationJournalState.EXTERNAL_EFFECT_REPORTED,
        occurred_at="2026-09-27T12:01:01Z",
        evidence_sha256="e" * 64,
    )
    journal_store.append(
        journal.transaction_id,
        state=MutationJournalState.POSTCONDITION_VERIFIED,
        occurred_at="2026-09-27T12:01:02Z",
        evidence_sha256="f" * 64,
    )
    terminal = journal_store.get(journal.transaction_id)
    assert terminal is not None
    store = RemoteMutationRollbackAuthorizationStore(
        tmp_path / "rollback_authorization.sqlite3"
    )

    with pytest.raises(
        RollbackAuthorizationError,
        match="not eligible",
    ):
        store.issue(
            authorization_id="rollback-authz-terminal",
            rollback_authority_id="authority:rollback:2",
            rollback_executor_id="executor:rollback:1",
            plan=plan,
            descriptor=descriptor,
            custody=custody,
            journal=terminal,
            current_state=RollbackCurrentStateObservation(
                target_exists=True,
                content_sha256=C,
            ),
            issued_at="2026-09-27T12:03:00Z",
            expires_at="2026-09-27T12:08:00Z",
        )


def test_expired_rollback_authorization_fails_closed(tmp_path):
    *_, store, authorization, current_state = issue(tmp_path)
    with pytest.raises(RollbackAuthorizationError, match="expired"):
        store.consume(
            authorization.authorization_id,
            rollback_executor_id=authorization.rollback_executor_id,
            current_state_sha256=current_state.observation_sha256,
            now="2026-09-27T12:07:01Z",
        )


def test_current_state_substitution_fails_consumption(tmp_path):
    *_, store, authorization, _ = issue(tmp_path)
    substituted = RollbackCurrentStateObservation(
        target_exists=True,
        content_sha256="d" * 64,
    )
    with pytest.raises(RollbackAuthorizationError, match="binding mismatch"):
        store.consume(
            authorization.authorization_id,
            rollback_executor_id=authorization.rollback_executor_id,
            current_state_sha256=substituted.observation_sha256,
            now="2026-09-27T12:03:00Z",
        )
