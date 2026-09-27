from __future__ import annotations

import hashlib

import pytest

from agent_control_plane.remote_mutation_rollback_authorization import (
    ROLLBACK_AUTHORIZATION_SCHEMA_VERSION,
    RepositoryRollbackAuthorization,
    RepositoryRollbackAuthorizationStore,
    RollbackAuthorizationError,
)
from agent_control_plane.remote_mutation_rollback_journal import (
    RemoteMutationRollbackJournal,
    RollbackJournalState,
)
from agent_control_plane.remote_mutation_rollback_plan import (
    RepositoryRollbackPlan,
    RollbackAction,
)
from agent_control_plane.remote_mutation_rollback_revalidation import (
    inspect_repository_rollback_state,
)

A = "a" * 64
B = "b" * 64


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def fixture(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    (root / ".git").mkdir()
    (root / "docs").mkdir()
    target = root / "docs" / "example.md"
    current = b"current-state"
    target.write_bytes(current)

    plan = RepositoryRollbackPlan(
        rollback_request_id="rollback-req-1",
        rollback_authority_id="rollback-auth-1",
        rollback_transaction_id="rollback-tx-1",
        original_transaction_id="original-tx-1",
        original_request_id="original-req-1",
        resource_id="repo:test",
        original_operation_id="repo.write_text_file",
        original_plan_sha256=A,
        original_journal_state="failed",
        requested_path="docs/example.md",
        rollback_descriptor_sha256=B,
        rollback_custody_ref="custody://rollback/test-1",
        action=RollbackAction.RESTORE_FILE_BYTES,
        expected_current_target_exists=True,
        expected_current_content_sha256=sha(current),
        desired_target_exists=True,
        desired_content_sha256=sha(b"prior-state"),
    )
    revalidation = inspect_repository_rollback_state(plan, repository_root=root)
    assert revalidation.admitted is True
    journal_store = RemoteMutationRollbackJournal(tmp_path / "rollback-journal.sqlite3")
    journal = journal_store.begin(plan=plan, created_at="2026-09-27T14:00:00Z")
    store = RepositoryRollbackAuthorizationStore(tmp_path / "rollback-auth.sqlite3")
    return root, plan, revalidation, journal_store, journal, store


def issue(tmp_path, **overrides):
    root, plan, revalidation, journal_store, journal, store = fixture(tmp_path)
    values = {
        "authorization_id": "rollback-authz-1",
        "rollback_executor_id": "rollback-executor:test",
        "plan": plan,
        "revalidation": revalidation,
        "journal": journal,
        "issued_at": "2026-09-27T14:00:00Z",
        "expires_at": "2026-09-27T14:05:00Z",
    }
    values.update(overrides)
    auth = store.issue(**values)
    return root, plan, revalidation, journal_store, journal, store, auth


def test_exact_authorization_is_nonexecuting_and_single_use(tmp_path):
    _, plan, _, _, _, store, auth = issue(tmp_path)
    assert auth.schema_version == ROLLBACK_AUTHORIZATION_SCHEMA_VERSION
    assert auth.consumed is False
    assert auth.rollback_executed is False
    consumed = store.consume(
        auth.authorization_id,
        rollback_executor_id=auth.rollback_executor_id,
        rollback_transaction_id=plan.rollback_transaction_id,
        rollback_plan_sha256=plan.rollback_plan_sha256,
        now="2026-09-27T14:01:00Z",
    )
    assert consumed.consumed is True
    assert consumed.rollback_executed is False
    with pytest.raises(RollbackAuthorizationError, match="already consumed"):
        store.consume(
            auth.authorization_id,
            rollback_executor_id=auth.rollback_executor_id,
            rollback_transaction_id=plan.rollback_transaction_id,
            rollback_plan_sha256=plan.rollback_plan_sha256,
            now="2026-09-27T14:02:00Z",
        )


def test_authorization_survives_store_reopen_and_replay_stays_blocked(tmp_path):
    _, plan, _, _, _, store, auth = issue(tmp_path)
    store.consume(
        auth.authorization_id,
        rollback_executor_id=auth.rollback_executor_id,
        rollback_transaction_id=plan.rollback_transaction_id,
        rollback_plan_sha256=plan.rollback_plan_sha256,
        now="2026-09-27T14:01:00Z",
    )
    reopened = RepositoryRollbackAuthorizationStore(
        tmp_path / "rollback-auth.sqlite3"
    )
    loaded = reopened.get(auth.authorization_id)
    assert loaded is not None and loaded.consumed is True
    with pytest.raises(RollbackAuthorizationError, match="already consumed"):
        reopened.consume(
            auth.authorization_id,
            rollback_executor_id=auth.rollback_executor_id,
            rollback_transaction_id=plan.rollback_transaction_id,
            rollback_plan_sha256=plan.rollback_plan_sha256,
            now="2026-09-27T14:02:00Z",
        )


@pytest.mark.parametrize(
    "kwargs",
    [
        {"rollback_executor_id": "rollback-executor:other"},
        {"rollback_transaction_id": "rollback-tx-other"},
        {"rollback_plan_sha256": A},
    ],
)
def test_consume_rejects_binding_mismatch(tmp_path, kwargs):
    _, plan, _, _, _, store, auth = issue(tmp_path)
    values = {
        "rollback_executor_id": auth.rollback_executor_id,
        "rollback_transaction_id": plan.rollback_transaction_id,
        "rollback_plan_sha256": plan.rollback_plan_sha256,
        "now": "2026-09-27T14:01:00Z",
    }
    values.update(kwargs)
    with pytest.raises(RollbackAuthorizationError, match="binding mismatch"):
        store.consume(auth.authorization_id, **values)
    assert store.get(auth.authorization_id).consumed is False


def test_authorization_not_active_before_issue_time(tmp_path):
    _, plan, _, _, _, store, auth = issue(tmp_path)
    with pytest.raises(RollbackAuthorizationError, match="not active yet"):
        store.consume(
            auth.authorization_id,
            rollback_executor_id=auth.rollback_executor_id,
            rollback_transaction_id=plan.rollback_transaction_id,
            rollback_plan_sha256=plan.rollback_plan_sha256,
            now="2026-09-27T13:59:59Z",
        )


def test_authorization_expires_fail_closed(tmp_path):
    _, plan, _, _, _, store, auth = issue(tmp_path)
    with pytest.raises(RollbackAuthorizationError, match="expired"):
        store.consume(
            auth.authorization_id,
            rollback_executor_id=auth.rollback_executor_id,
            rollback_transaction_id=plan.rollback_transaction_id,
            rollback_plan_sha256=plan.rollback_plan_sha256,
            now="2026-09-27T14:05:01Z",
        )


def test_authorization_requires_admitted_current_state(tmp_path):
    root, plan, _, _, journal, store = fixture(tmp_path)
    (root / "docs" / "example.md").write_bytes(b"drifted")
    blocked = inspect_repository_rollback_state(plan, repository_root=root)
    assert blocked.admitted is False
    with pytest.raises(RollbackAuthorizationError, match="revalidation"):
        store.issue(
            authorization_id="rollback-authz-1",
            rollback_executor_id="rollback-executor:test",
            plan=plan,
            revalidation=blocked,
            journal=journal,
            issued_at="2026-09-27T14:00:00Z",
            expires_at="2026-09-27T14:05:00Z",
        )


def test_authorization_requires_prepared_rollback_journal(tmp_path):
    _, plan, revalidation, journal_store, journal, store = fixture(tmp_path)
    journal = journal_store.append(
        plan.rollback_transaction_id,
        state=RollbackJournalState.ROLLBACK_INTENT_RECORDED,
        occurred_at="2026-09-27T14:00:01Z",
    )
    with pytest.raises(RollbackAuthorizationError, match="PREPARED"):
        store.issue(
            authorization_id="rollback-authz-1",
            rollback_executor_id="rollback-executor:test",
            plan=plan,
            revalidation=revalidation,
            journal=journal,
            issued_at="2026-09-27T14:00:00Z",
            expires_at="2026-09-27T14:05:00Z",
        )


def test_authorization_id_conflict_fails_closed(tmp_path):
    _, plan, revalidation, _, journal, store, auth = issue(tmp_path)
    with pytest.raises(RollbackAuthorizationError, match="authorization_id conflict"):
        store.issue(
            authorization_id=auth.authorization_id,
            rollback_executor_id="rollback-executor:other",
            plan=plan,
            revalidation=revalidation,
            journal=journal,
            issued_at="2026-09-27T14:00:00Z",
            expires_at="2026-09-27T14:05:00Z",
        )


def test_authorization_identity_is_deterministic_across_consumption(tmp_path):
    _, plan, _, _, _, store, auth = issue(tmp_path)
    before = auth.authorization_sha256
    consumed = store.consume(
        auth.authorization_id,
        rollback_executor_id=auth.rollback_executor_id,
        rollback_transaction_id=plan.rollback_transaction_id,
        rollback_plan_sha256=plan.rollback_plan_sha256,
        now="2026-09-27T14:01:00Z",
    )
    assert consumed.authorization_sha256 == before


def test_authorization_record_cannot_claim_rollback_execution():
    with pytest.raises(RollbackAuthorizationError, match="cannot claim"):
        RepositoryRollbackAuthorization(
            authorization_id="a",
            rollback_executor_id="executor",
            rollback_transaction_id="tx",
            rollback_request_id="req",
            rollback_authority_id="authority",
            rollback_plan_sha256=A,
            original_transaction_id="orig-tx",
            original_plan_sha256=A,
            rollback_descriptor_sha256=B,
            rollback_custody_ref="custody://x",
            issued_at="2026-09-27T14:00:00Z",
            expires_at="2026-09-27T14:05:00Z",
            rollback_executed=True,
        )
