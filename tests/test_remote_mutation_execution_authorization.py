from __future__ import annotations

from pathlib import Path

import pytest

from agent_control_plane.remote_mutation_composition import MutationCompositionRecord
from agent_control_plane.remote_mutation_execution_authorization import (
    MUTATION_EXECUTION_AUTHORIZATION_SCHEMA_VERSION,
    MutationExecutionAuthorizationError,
    RemoteMutationExecutionAuthorizationStore,
)
from agent_control_plane.remote_mutation_journal import (
    MutationJournalEvent,
    MutationJournalRecord,
    MutationJournalState,
)
from agent_control_plane.remote_mutation_path_safety import MutationPathSafetyRecord
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


def upstream():
    descriptor = RollbackMaterialDescriptor(
        operation_id="repo.write_text_file",
        path="docs/example.md",
        mode=RollbackMode.RESTORE_FILE_BYTES,
        prior_content_sha256=B,
        prior_content_size=6,
    )
    plan = MutationPlan(
        request_id="req-authz-1",
        authority_id="authority-authz-1",
        resource_id="repo:acp",
        resource_type="git_repository",
        operation_id="repo.write_text_file",
        parameters={"path": "docs/example.md", "content_sha256": C},
        precondition_sha256=A,
        rollback_sha256=descriptor.descriptor_sha256,
    )
    composition = MutationCompositionRecord(
        request_id=plan.request_id, authority_id=plan.authority_id,
        operation_id=plan.operation_id, resource_id=plan.resource_id,
        plan_sha256=plan.plan_sha256, admitted=True, reason="exact",
    )
    transaction = MutationTransactionReceipt(
        request_id=plan.request_id, authority_id=plan.authority_id,
        operation_id=plan.operation_id, plan_sha256=plan.plan_sha256,
        precondition_sha256=plan.precondition_sha256, rollback_sha256=plan.rollback_sha256,
        state=MutationTransactionState.PRECONDITIONS_VERIFIED,
        preconditions_verified=True, rollback_available=True,
    )
    path = MutationPathSafetyRecord(
        request_id=plan.request_id, resource_id=plan.resource_id,
        operation_id=plan.operation_id, plan_sha256=plan.plan_sha256,
        requested_path=plan.parameters["path"], repository_root=str(Path.cwd()),
        resolved_path=str(Path.cwd() / plan.parameters["path"]), admitted=True,
        reason="safe", repository_boundary_verified=True, symlink_safe=True,
        repository_metadata_safe=True, operation_shape_verified=True, target_exists=True,
    )
    custody = RollbackCustodyAdmissionRecord(
        request_id=plan.request_id, resource_id=plan.resource_id,
        operation_id=plan.operation_id, plan_sha256=plan.plan_sha256,
        descriptor_sha256=descriptor.descriptor_sha256,
        custody_ref="custody://operator-local/authz-1",
        admitted=True, reason="verified", readback_verified=True,
    )
    journal = MutationJournalRecord(
        transaction_id="tx-authz-1", request_id=plan.request_id,
        resource_id=plan.resource_id, operation_id=plan.operation_id,
        plan_sha256=plan.plan_sha256, rollback_descriptor_sha256=plan.rollback_sha256,
        custody_ref=custody.custody_ref, created_at="2026-09-27T10:00:00Z",
        events=(
            MutationJournalEvent(
                transaction_id="tx-authz-1", event_index=0,
                state=MutationJournalState.PREPARED, occurred_at="2026-09-27T10:00:00Z",
            ),
        ),
    )
    return plan, composition, transaction, path, custody, journal


def issue(tmp_path, **overrides):
    plan, composition, transaction, path, custody, journal = upstream()
    values = {
        "authorization_id": "mutation-authz-1",
        "executor_id": "external-executor:rdc-neontic",
        "composition": composition,
        "plan": plan,
        "transaction": transaction,
        "path_safety": path,
        "rollback_custody": custody,
        "journal": journal,
        "issued_at": "2026-09-27T10:00:00Z",
        "expires_at": "2026-09-27T10:05:00Z",
    }
    values.update(overrides)
    store = RemoteMutationExecutionAuthorizationStore(tmp_path / "authz.sqlite3")
    auth = store.issue(**values)
    return store, auth, (plan, composition, transaction, path, custody, journal)


def test_exact_authorization_is_issued_and_consumed_once(tmp_path):
    store, auth, upstream_records = issue(tmp_path)
    plan = upstream_records[0]
    assert auth.schema_version == MUTATION_EXECUTION_AUTHORIZATION_SCHEMA_VERSION
    assert auth.consumed is False
    consumed = store.consume(
        auth.authorization_id, executor_id=auth.executor_id,
        transaction_id=auth.transaction_id, plan_sha256=plan.plan_sha256,
        now="2026-09-27T10:01:00Z",
    )
    assert consumed.consumed is True
    assert consumed.consumed_at == "2026-09-27T10:01:00Z"


def test_consumed_authorization_cannot_be_replayed(tmp_path):
    store, auth, records = issue(tmp_path)
    plan = records[0]
    store.consume(
        auth.authorization_id, executor_id=auth.executor_id,
        transaction_id=auth.transaction_id, plan_sha256=plan.plan_sha256,
        now="2026-09-27T10:01:00Z",
    )
    with pytest.raises(MutationExecutionAuthorizationError, match="already consumed"):
        store.consume(
            auth.authorization_id, executor_id=auth.executor_id,
            transaction_id=auth.transaction_id, plan_sha256=plan.plan_sha256,
            now="2026-09-27T10:02:00Z",
        )


def test_authorization_survives_store_reopen_and_replay_remains_blocked(tmp_path):
    db = tmp_path / "authz.sqlite3"
    store, auth, records = issue(tmp_path)
    plan = records[0]
    store.consume(
        auth.authorization_id, executor_id=auth.executor_id,
        transaction_id=auth.transaction_id, plan_sha256=plan.plan_sha256,
        now="2026-09-27T10:01:00Z",
    )
    reopened = RemoteMutationExecutionAuthorizationStore(db)
    loaded = reopened.get(auth.authorization_id)
    assert loaded is not None and loaded.consumed is True
    with pytest.raises(MutationExecutionAuthorizationError, match="already consumed"):
        reopened.consume(
            auth.authorization_id, executor_id=auth.executor_id,
            transaction_id=auth.transaction_id, plan_sha256=plan.plan_sha256,
            now="2026-09-27T10:02:00Z",
        )


def test_authorization_rejects_wrong_executor_transaction_or_plan(tmp_path):
    store, auth, records = issue(tmp_path)
    plan = records[0]
    cases = [
        {"executor_id": "external-executor:other", "transaction_id": auth.transaction_id, "plan_sha256": plan.plan_sha256},
        {"executor_id": auth.executor_id, "transaction_id": "tx-other", "plan_sha256": plan.plan_sha256},
        {"executor_id": auth.executor_id, "transaction_id": auth.transaction_id, "plan_sha256": A},
    ]
    for values in cases:
        with pytest.raises(MutationExecutionAuthorizationError, match="binding mismatch"):
            store.consume(auth.authorization_id, now="2026-09-27T10:01:00Z", **values)


def test_authorization_not_active_before_issue_time(tmp_path):
    store, auth, records = issue(tmp_path)
    with pytest.raises(MutationExecutionAuthorizationError, match="not active yet"):
        store.consume(
            auth.authorization_id, executor_id=auth.executor_id,
            transaction_id=auth.transaction_id, plan_sha256=records[0].plan_sha256,
            now="2026-09-27T09:59:59Z",
        )


def test_authorization_expires_fail_closed(tmp_path):
    store, auth, records = issue(tmp_path)
    with pytest.raises(MutationExecutionAuthorizationError, match="expired"):
        store.consume(
            auth.authorization_id, executor_id=auth.executor_id,
            transaction_id=auth.transaction_id, plan_sha256=records[0].plan_sha256,
            now="2026-09-27T10:05:01Z",
        )


def test_authorization_identity_is_deterministic_and_stable_after_consumption(tmp_path):
    store, auth, records = issue(tmp_path)
    before = auth.authorization_sha256
    consumed = store.consume(
        auth.authorization_id, executor_id=auth.executor_id,
        transaction_id=auth.transaction_id, plan_sha256=records[0].plan_sha256,
        now="2026-09-27T10:01:00Z",
    )
    assert consumed.authorization_sha256 == before


def test_authorization_id_conflict_fails_closed(tmp_path):
    store, auth, records = issue(tmp_path)
    plan, composition, transaction, path, custody, journal = records
    with pytest.raises(MutationExecutionAuthorizationError, match="authorization_id conflict"):
        store.issue(
            authorization_id=auth.authorization_id, executor_id="external-executor:other",
            composition=composition, plan=plan, transaction=transaction,
            path_safety=path, rollback_custody=custody, journal=journal,
            issued_at=auth.issued_at, expires_at=auth.expires_at,
        )


def test_journal_must_still_be_prepared_at_issue_time(tmp_path):
    plan, composition, transaction, path, custody, journal = upstream()
    journal = MutationJournalRecord(
        transaction_id=journal.transaction_id, request_id=journal.request_id,
        resource_id=journal.resource_id, operation_id=journal.operation_id,
        plan_sha256=journal.plan_sha256,
        rollback_descriptor_sha256=journal.rollback_descriptor_sha256,
        custody_ref=journal.custody_ref, created_at=journal.created_at,
        events=journal.events + (
            MutationJournalEvent(
                transaction_id=journal.transaction_id, event_index=1,
                state=MutationJournalState.EXECUTION_INTENT_RECORDED,
                occurred_at="2026-09-27T10:00:01Z",
            ),
        ),
    )
    store = RemoteMutationExecutionAuthorizationStore(tmp_path / "authz.sqlite3")
    with pytest.raises(MutationExecutionAuthorizationError, match="journal must be PREPARED"):
        store.issue(
            authorization_id="authz", executor_id="external:test", composition=composition,
            plan=plan, transaction=transaction, path_safety=path, rollback_custody=custody,
            journal=journal, issued_at="2026-09-27T10:00:00Z", expires_at="2026-09-27T10:05:00Z",
        )


def test_unadmitted_composition_is_rejected(tmp_path):
    plan, composition, transaction, path, custody, journal = upstream()
    composition = MutationCompositionRecord(
        request_id=composition.request_id, authority_id=composition.authority_id,
        operation_id=composition.operation_id, resource_id=composition.resource_id,
        plan_sha256=composition.plan_sha256, admitted=False, reason="blocked",
    )
    store = RemoteMutationExecutionAuthorizationStore(tmp_path / "authz.sqlite3")
    with pytest.raises(MutationExecutionAuthorizationError, match="composition must be admitted"):
        store.issue(
            authorization_id="authz", executor_id="external:test", composition=composition,
            plan=plan, transaction=transaction, path_safety=path, rollback_custody=custody,
            journal=journal, issued_at="2026-09-27T10:00:00Z", expires_at="2026-09-27T10:05:00Z",
        )


def test_unverified_transaction_is_rejected(tmp_path):
    plan, composition, transaction, path, custody, journal = upstream()
    transaction = MutationTransactionReceipt(
        request_id=plan.request_id, authority_id=plan.authority_id,
        operation_id=plan.operation_id, plan_sha256=plan.plan_sha256,
        precondition_sha256=plan.precondition_sha256, rollback_sha256=plan.rollback_sha256,
        state=MutationTransactionState.BLOCKED, preconditions_verified=False, rollback_available=True,
    )
    store = RemoteMutationExecutionAuthorizationStore(tmp_path / "authz.sqlite3")
    with pytest.raises(MutationExecutionAuthorizationError, match="preconditions and rollback"):
        store.issue(
            authorization_id="authz", executor_id="external:test", composition=composition,
            plan=plan, transaction=transaction, path_safety=path, rollback_custody=custody,
            journal=journal, issued_at="2026-09-27T10:00:00Z", expires_at="2026-09-27T10:05:00Z",
        )


def test_expiry_must_be_after_issue_time(tmp_path):
    with pytest.raises(MutationExecutionAuthorizationError, match="expires_at must be after"):
        issue(tmp_path, expires_at="2026-09-27T10:00:00Z")