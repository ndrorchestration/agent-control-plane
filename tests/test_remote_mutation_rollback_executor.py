from __future__ import annotations

import hashlib

import pytest

from agent_control_plane.remote_mutation_rollback_authorization import (
    RepositoryRollbackAuthorizationStore,
)
from agent_control_plane.remote_mutation_rollback_custody import (
    RollbackMaterialDescriptor,
    RollbackMode,
)
from agent_control_plane.remote_mutation_rollback_executor import (
    AuthorizedRepositoryRollbackExecutor,
    DEFAULT_ROLLBACK_EXECUTOR_ID,
    RepositoryRollbackExecutorError,
)
from agent_control_plane.remote_mutation_rollback_journal import (
    RemoteMutationRollbackJournal,
    RollbackJournalState,
)
from agent_control_plane.remote_mutation_rollback_material_readback import (
    verify_rollback_material_readback,
)
from agent_control_plane.remote_mutation_rollback_plan import (
    RepositoryRollbackPlan,
    RollbackAction,
)
from agent_control_plane.remote_mutation_rollback_revalidation import (
    inspect_repository_rollback_state,
)

A = "a" * 64


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def repo(tmp_path):
    root = tmp_path / "repo"
    root.mkdir(parents=True)
    (root / ".git").mkdir()
    (root / "docs").mkdir()
    return root


def prepare_restore(tmp_path):
    root = repo(tmp_path)
    current = b"current-state"
    prior = b"prior-state"
    target = root / "docs" / "example.md"
    target.write_bytes(current)

    descriptor = RollbackMaterialDescriptor(
        operation_id="repo.write_text_file",
        path="docs/example.md",
        mode=RollbackMode.RESTORE_FILE_BYTES,
        prior_content_sha256=sha(prior),
        prior_content_size=len(prior),
    )
    plan = RepositoryRollbackPlan(
        rollback_request_id="rb-req",
        rollback_authority_id="rb-authority",
        rollback_transaction_id="rb-tx",
        original_transaction_id="orig-tx",
        original_request_id="orig-req",
        resource_id="repo:test",
        original_operation_id="repo.write_text_file",
        original_plan_sha256=A,
        original_journal_state="failed",
        requested_path="docs/example.md",
        rollback_descriptor_sha256=descriptor.descriptor_sha256,
        rollback_custody_ref="custody://rollback/executor",
        action=RollbackAction.RESTORE_FILE_BYTES,
        expected_current_target_exists=True,
        expected_current_content_sha256=sha(current),
        desired_target_exists=True,
        desired_content_sha256=sha(prior),
    )
    revalidation = inspect_repository_rollback_state(plan, repository_root=root)
    journal = RemoteMutationRollbackJournal(tmp_path / "journal.sqlite3")
    jr = journal.begin(plan=plan, created_at="2026-09-27T17:00:00Z")
    store = RepositoryRollbackAuthorizationStore(tmp_path / "auth.sqlite3")
    auth = store.issue(
        authorization_id="rb-authz",
        rollback_executor_id=DEFAULT_ROLLBACK_EXECUTOR_ID,
        plan=plan,
        revalidation=revalidation,
        journal=jr,
        issued_at="2026-09-27T17:00:00Z",
        expires_at="2026-09-27T17:05:00Z",
    )
    readback = verify_rollback_material_readback(
        plan, descriptor, auth, material=prior
    )
    executor = AuthorizedRepositoryRollbackExecutor(
        allowed_repository_roots=[root],
        experimental_enable=True,
    )
    return {
        "root": root,
        "target": target,
        "current": current,
        "prior": prior,
        "descriptor": descriptor,
        "plan": plan,
        "revalidation": revalidation,
        "journal": journal,
        "auth_store": store,
        "auth": auth,
        "readback": readback,
        "executor": executor,
    }


def execute(ctx, *, material_marker=True):
    material = ctx["prior"] if material_marker else None
    return ctx["executor"].execute(
        authorization_store=ctx["auth_store"],
        authorization_id=ctx["auth"].authorization_id,
        journal_store=ctx["journal"],
        plan=ctx["plan"],
        prior_revalidation=ctx["revalidation"],
        material_readback=ctx["readback"],
        repository_root=ctx["root"],
        rollback_material=material,
        authorization_consumed_at="2026-09-27T17:00:30Z",
        rollback_intent_at="2026-09-27T17:00:31Z",
        rollback_effect_at="2026-09-27T17:00:32Z",
        rollback_verified_at="2026-09-27T17:00:33Z",
    )


def test_executor_disabled_without_explicit_opt_in(tmp_path):
    root = repo(tmp_path)
    with pytest.raises(RepositoryRollbackExecutorError, match="experimental_enable"):
        AuthorizedRepositoryRollbackExecutor(
            allowed_repository_roots=[root],
            experimental_enable=False,
        )


def test_executor_rejects_nonallowlisted_repository(tmp_path):
    allowed = repo(tmp_path / "allowed")
    other = repo(tmp_path / "other")
    executor = AuthorizedRepositoryRollbackExecutor(
        allowed_repository_roots=[allowed],
        experimental_enable=True,
    )
    with pytest.raises(RepositoryRollbackExecutorError, match="allowlist"):
        executor._allowed_root(other)


def test_restore_file_end_to_end_in_temp_repo(tmp_path):
    ctx = prepare_restore(tmp_path)
    result = execute(ctx)
    assert ctx["target"].read_bytes() == ctx["prior"]
    assert result.rollback_executed is True
    assert result.authorization_consumed is True
    assert result.rollback_postcondition_verified is True
    assert result.final_target_exists is True
    assert result.final_content_sha256 == sha(ctx["prior"])
    assert (
        ctx["journal"].get("rb-tx").current_state
        is RollbackJournalState.ROLLBACK_VERIFIED
    )


def test_delete_created_file_end_to_end_in_temp_repo(tmp_path):
    root = repo(tmp_path)
    target = root / "docs" / "new.md"
    created = b"created"
    target.write_bytes(created)
    descriptor = RollbackMaterialDescriptor(
        operation_id="repo.write_text_file",
        path="docs/new.md",
        mode=RollbackMode.DELETE_CREATED_FILE,
    )
    plan = RepositoryRollbackPlan(
        rollback_request_id="rb-del-req",
        rollback_authority_id="rb-authority",
        rollback_transaction_id="rb-del-tx",
        original_transaction_id="orig-tx",
        original_request_id="orig-req",
        resource_id="repo:test",
        original_operation_id="repo.write_text_file",
        original_plan_sha256=A,
        original_journal_state="failed",
        requested_path="docs/new.md",
        rollback_descriptor_sha256=descriptor.descriptor_sha256,
        rollback_custody_ref="custody://rollback/delete",
        action=RollbackAction.DELETE_CREATED_FILE,
        expected_current_target_exists=True,
        expected_current_content_sha256=sha(created),
        desired_target_exists=False,
        desired_content_sha256=None,
    )
    revalidation = inspect_repository_rollback_state(plan, repository_root=root)
    journal = RemoteMutationRollbackJournal(tmp_path / "journal-del.sqlite3")
    jr = journal.begin(plan=plan, created_at="2026-09-27T17:00:00Z")
    store = RepositoryRollbackAuthorizationStore(tmp_path / "auth-del.sqlite3")
    auth = store.issue(
        authorization_id="rb-del-authz",
        rollback_executor_id=DEFAULT_ROLLBACK_EXECUTOR_ID,
        plan=plan,
        revalidation=revalidation,
        journal=jr,
        issued_at="2026-09-27T17:00:00Z",
        expires_at="2026-09-27T17:05:00Z",
    )
    readback = verify_rollback_material_readback(
        plan, descriptor, auth, material=None
    )
    executor = AuthorizedRepositoryRollbackExecutor(
        allowed_repository_roots=[root],
        experimental_enable=True,
    )
    result = executor.execute(
        authorization_store=store,
        authorization_id=auth.authorization_id,
        journal_store=journal,
        plan=plan,
        prior_revalidation=revalidation,
        material_readback=readback,
        repository_root=root,
        rollback_material=None,
        authorization_consumed_at="2026-09-27T17:00:30Z",
        rollback_intent_at="2026-09-27T17:00:31Z",
        rollback_effect_at="2026-09-27T17:00:32Z",
        rollback_verified_at="2026-09-27T17:00:33Z",
    )
    assert not target.exists()
    assert result.rollback_executed is True
    assert result.final_target_exists is False
    assert journal.get("rb-del-tx").current_state is RollbackJournalState.ROLLBACK_VERIFIED


def test_wrong_material_rejected_before_authorization_consumption(tmp_path):
    ctx = prepare_restore(tmp_path)
    ctx["prior"] = b"wrong"
    with pytest.raises(RepositoryRollbackExecutorError, match="material bytes"):
        execute(ctx)
    assert ctx["target"].read_bytes() == ctx["current"]
    assert ctx["auth_store"].get("rb-authz").consumed is False
    assert ctx["journal"].get("rb-tx").current_state is RollbackJournalState.PREPARED


def test_current_state_drift_rejected_before_authorization_consumption(tmp_path):
    ctx = prepare_restore(tmp_path)
    ctx["target"].write_bytes(b"concurrent-change")
    with pytest.raises(RepositoryRollbackExecutorError, match="revalidation"):
        execute(ctx)
    assert ctx["target"].read_bytes() == b"concurrent-change"
    assert ctx["auth_store"].get("rb-authz").consumed is False
    assert ctx["journal"].get("rb-tx").current_state is RollbackJournalState.PREPARED


def test_consumed_authorization_prevents_replay(tmp_path):
    ctx = prepare_restore(tmp_path)
    first = execute(ctx)
    assert first.rollback_postcondition_verified is True
    with pytest.raises(
        RepositoryRollbackExecutorError,
        match="already consumed|journal must be PREPARED",
    ):
        execute(ctx)


def test_failure_after_intent_consumes_auth_and_holds_recovery(tmp_path, monkeypatch):
    ctx = prepare_restore(tmp_path)

    def fail(plan, target, *, rollback_material):
        raise OSError("simulated rollback filesystem failure")

    monkeypatch.setattr(
        AuthorizedRepositoryRollbackExecutor,
        "_perform_rollback",
        staticmethod(fail),
    )
    with pytest.raises(RepositoryRollbackExecutorError, match="executor failed"):
        execute(ctx)
    assert ctx["target"].read_bytes() == ctx["current"]
    assert ctx["auth_store"].get("rb-authz").consumed is True
    journal = ctx["journal"].get("rb-tx")
    assert journal.current_state is RollbackJournalState.FAILED
    assessment = ctx["journal"].assess_recovery("rb-tx")
    assert assessment.rollback_effect_may_exist is True


def test_wrong_post_state_fails_closed_after_effect(tmp_path, monkeypatch):
    ctx = prepare_restore(tmp_path)

    def wrong(plan, target, *, rollback_material):
        target.write_bytes(b"wrong-post-state")

    monkeypatch.setattr(
        AuthorizedRepositoryRollbackExecutor,
        "_perform_rollback",
        staticmethod(wrong),
    )
    with pytest.raises(RepositoryRollbackExecutorError, match="postcondition"):
        execute(ctx)
    assert ctx["target"].read_bytes() == b"wrong-post-state"
    assert ctx["auth_store"].get("rb-authz").consumed is True
    assert ctx["journal"].get("rb-tx").current_state is RollbackJournalState.FAILED
    assert ctx["journal"].assess_recovery("rb-tx").rollback_effect_may_exist is True


def test_failed_state_and_consumed_auth_survive_store_reopen(tmp_path, monkeypatch):
    ctx = prepare_restore(tmp_path)

    def wrong(plan, target, *, rollback_material):
        target.write_bytes(b"wrong-post-state")

    monkeypatch.setattr(
        AuthorizedRepositoryRollbackExecutor,
        "_perform_rollback",
        staticmethod(wrong),
    )
    with pytest.raises(RepositoryRollbackExecutorError):
        execute(ctx)

    reopened_auth = RepositoryRollbackAuthorizationStore(
        tmp_path / "auth.sqlite3"
    ).get("rb-authz")
    reopened_journal_store = RemoteMutationRollbackJournal(
        tmp_path / "journal.sqlite3"
    )
    reopened_journal = reopened_journal_store.get("rb-tx")
    assert reopened_auth is not None and reopened_auth.consumed is True
    assert reopened_journal is not None
    assert reopened_journal.current_state is RollbackJournalState.FAILED
    assert (
        reopened_journal_store.assess_recovery("rb-tx").rollback_effect_may_exist
        is True
    )
