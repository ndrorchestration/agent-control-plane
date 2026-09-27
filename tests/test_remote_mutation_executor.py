from __future__ import annotations

import hashlib

import pytest

from agent_control_plane.remote_mutation_composition import MutationCompositionRecord
from agent_control_plane.remote_mutation_execution_authorization import (
    RemoteMutationExecutionAuthorizationStore,
)
from agent_control_plane.remote_mutation_executor import (
    AuthorizedRepositoryMutationExecutor,
    DEFAULT_REPOSITORY_MUTATION_EXECUTOR_ID,
    FilesystemObjectIdentity,
    RepositoryMutationExecutorError,
)
from agent_control_plane.remote_mutation_executor_recovery import (
    ExecutorRecoveryDisposition,
    assess_executor_recovery,
)
from agent_control_plane.remote_mutation_journal import (
    MutationJournalState,
    RemoteMutationJournal,
)
from agent_control_plane.remote_mutation_path_safety import (
    inspect_repository_mutation_path,
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


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def repo(tmp_path):
    root = tmp_path / "repo"
    root.mkdir(parents=True)
    (root / ".git").mkdir()
    (root / "docs").mkdir()
    return root


def prepare(
    tmp_path,
    *,
    operation_id="repo.write_text_file",
    path="docs/example.md",
    prior: bytes | None = b"before",
    after: bytes | None = b"after",
):
    root = repo(tmp_path)
    target = root.joinpath(*path.split("/"))
    target.parent.mkdir(parents=True, exist_ok=True)

    if prior is not None:
        target.write_bytes(prior)

    if operation_id == "repo.write_text_file":
        if prior is None:
            descriptor = RollbackMaterialDescriptor(
                operation_id=operation_id,
                path=path,
                mode=RollbackMode.DELETE_CREATED_FILE,
            )
        else:
            descriptor = RollbackMaterialDescriptor(
                operation_id=operation_id,
                path=path,
                mode=RollbackMode.RESTORE_FILE_BYTES,
                prior_content_sha256=sha(prior),
                prior_content_size=len(prior),
            )
        parameters = {"path": path, "content_sha256": sha(after or b"")}
    else:
        assert prior is not None
        descriptor = RollbackMaterialDescriptor(
            operation_id=operation_id,
            path=path,
            mode=RollbackMode.RESTORE_FILE_BYTES,
            prior_content_sha256=sha(prior),
            prior_content_size=len(prior),
        )
        parameters = {"path": path, "prior_content_sha256": sha(prior)}

    plan = MutationPlan(
        request_id="req-executor-1",
        authority_id="authority-executor-1",
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
        reason="exact composition",
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
        custody_ref="custody://temp-test/executor-1",
        admitted=True,
        reason="test custody",
        readback_verified=True,
    )

    journal_store = RemoteMutationJournal(tmp_path / "journal.sqlite3")
    journal = journal_store.begin(
        transaction_id="tx-executor-1",
        plan=plan,
        path_safety=path_safety,
        rollback_custody=custody,
        created_at="2026-09-27T11:00:00Z",
    )

    auth_store = RemoteMutationExecutionAuthorizationStore(
        tmp_path / "authorization.sqlite3"
    )
    authorization = auth_store.issue(
        authorization_id="authz-executor-1",
        executor_id=DEFAULT_REPOSITORY_MUTATION_EXECUTOR_ID,
        composition=composition,
        plan=plan,
        transaction=transaction,
        path_safety=path_safety,
        rollback_custody=custody,
        journal=journal,
        issued_at="2026-09-27T11:00:00Z",
        expires_at="2026-09-27T11:05:00Z",
    )

    executor = AuthorizedRepositoryMutationExecutor(
        allowed_repository_roots=[root],
        experimental_enable=True,
    )
    return {
        "root": root,
        "target": target,
        "plan": plan,
        "composition": composition,
        "transaction": transaction,
        "path_safety": path_safety,
        "descriptor": descriptor,
        "custody": custody,
        "journal_store": journal_store,
        "auth_store": auth_store,
        "authorization": authorization,
        "executor": executor,
        "after": after,
    }


def execute(ctx, *, content_marker=True):
    content = (
        ctx["after"]
        if ctx["plan"].operation_id == "repo.write_text_file" and content_marker
        else None
    )
    return ctx["executor"].execute(
        authorization_store=ctx["auth_store"],
        authorization_id=ctx["authorization"].authorization_id,
        journal_store=ctx["journal_store"],
        composition=ctx["composition"],
        plan=ctx["plan"],
        prior_path_safety=ctx["path_safety"],
        rollback_custody=ctx["custody"],
        rollback_descriptor=ctx["descriptor"],
        repository_root=ctx["root"],
        execution_id="exec-executor-1",
        content=content,
        authorization_consumed_at="2026-09-27T11:00:30Z",
        execution_intent_at="2026-09-27T11:00:31Z",
        external_effect_at="2026-09-27T11:00:32Z",
        postcondition_at="2026-09-27T11:00:33Z",
    )


def test_executor_is_disabled_without_explicit_opt_in(tmp_path):
    root = repo(tmp_path)
    with pytest.raises(RepositoryMutationExecutorError, match="experimental_enable"):
        AuthorizedRepositoryMutationExecutor(
            allowed_repository_roots=[root],
            experimental_enable=False,
        )


def test_executor_rejects_non_allowlisted_repository(tmp_path):
    allowed = repo(tmp_path / "allowed")
    other = repo(tmp_path / "other")
    executor = AuthorizedRepositoryMutationExecutor(
        allowed_repository_roots=[allowed],
        experimental_enable=True,
    )
    with pytest.raises(
        RepositoryMutationExecutorError, match="not in executor allowlist"
    ):
        executor._allowed_root(other)


def test_existing_file_write_end_to_end_closes_evidence_chain(tmp_path):
    ctx = prepare(tmp_path, prior=b"before", after=b"after")
    result = execute(ctx)

    assert ctx["target"].read_bytes() == b"after"
    assert result.target_exists_after is True
    assert result.content_sha256_after == sha(b"after")
    assert result.authorization.consumed is True
    assert result.evidence_receipt.evidence_bound is True
    assert result.closure.closed is True

    journal = ctx["journal_store"].get("tx-executor-1")
    assert journal is not None
    assert journal.current_state is MutationJournalState.POSTCONDITION_VERIFIED


def test_new_file_write_end_to_end(tmp_path):
    ctx = prepare(tmp_path, prior=None, after=b"new-file")
    assert not ctx["target"].exists()

    result = execute(ctx)

    assert ctx["target"].read_bytes() == b"new-file"
    assert result.closure.closed is True


def test_delete_file_end_to_end(tmp_path):
    ctx = prepare(
        tmp_path,
        operation_id="repo.delete_file",
        prior=b"remove-me",
        after=None,
    )
    assert ctx["target"].exists()

    result = execute(ctx, content_marker=False)

    assert not ctx["target"].exists()
    assert result.target_exists_after is False
    assert result.content_sha256_after is None
    assert result.closure.closed is True


def test_wrong_write_content_is_rejected_before_authorization_consumption(tmp_path):
    ctx = prepare(tmp_path, prior=b"before", after=b"expected")
    ctx["after"] = b"wrong"

    with pytest.raises(RepositoryMutationExecutorError, match="content sha256"):
        execute(ctx)

    assert ctx["target"].read_bytes() == b"before"
    auth = ctx["auth_store"].get("authz-executor-1")
    assert auth is not None and auth.consumed is False
    journal = ctx["journal_store"].get("tx-executor-1")
    assert journal is not None
    assert journal.current_state is MutationJournalState.PREPARED


def test_pre_execution_content_drift_is_rejected_before_authorization_consumption(
    tmp_path,
):
    ctx = prepare(tmp_path, prior=b"before", after=b"after")
    ctx["target"].write_bytes(b"drifted-after-authorization")

    with pytest.raises(
        RepositoryMutationExecutorError, match="drifted after authorization"
    ):
        execute(ctx)

    assert ctx["target"].read_bytes() == b"drifted-after-authorization"
    auth = ctx["auth_store"].get("authz-executor-1")
    assert auth is not None and auth.consumed is False
    journal = ctx["journal_store"].get("tx-executor-1")
    assert journal is not None
    assert journal.current_state is MutationJournalState.PREPARED


def test_consumed_authorization_prevents_replay(tmp_path):
    ctx = prepare(tmp_path, prior=b"before", after=b"after")
    first = execute(ctx)
    assert first.closure.closed is True

    with pytest.raises(
        (RepositoryMutationExecutorError, ValueError),
        match="already consumed|journal must be PREPARED",
    ):
        execute(ctx)

    assert ctx["target"].read_bytes() == b"after"


def test_delete_content_drift_is_rejected_before_authorization_consumption(tmp_path):
    ctx = prepare(
        tmp_path,
        operation_id="repo.delete_file",
        prior=b"original",
        after=None,
    )
    ctx["target"].write_bytes(b"changed")

    with pytest.raises(
        RepositoryMutationExecutorError, match="drifted after authorization"
    ):
        execute(ctx, content_marker=False)

    assert ctx["target"].read_bytes() == b"changed"
    auth = ctx["auth_store"].get("authz-executor-1")
    assert auth is not None and auth.consumed is False


def test_failure_after_execution_intent_consumes_auth_and_enters_recovery_hold(
    tmp_path, monkeypatch
):
    ctx = prepare(tmp_path, prior=b"before", after=b"after")

    def fail_side_effect(plan, target, *, content):
        raise OSError("simulated filesystem failure after intent")

    monkeypatch.setattr(
        AuthorizedRepositoryMutationExecutor,
        "_perform_side_effect",
        staticmethod(fail_side_effect),
    )

    with pytest.raises(RepositoryMutationExecutorError, match="executor failed"):
        execute(ctx)

    assert ctx["target"].read_bytes() == b"before"
    auth = ctx["auth_store"].get("authz-executor-1")
    assert auth is not None and auth.consumed is True
    journal = ctx["journal_store"].get("tx-executor-1")
    assert journal is not None
    assert journal.current_state is MutationJournalState.FAILED
    assessment = ctx["journal_store"].assess_recovery("tx-executor-1")
    assert assessment.repository_mutation_may_exist is True


def test_wrong_post_state_after_side_effect_fails_closed_and_requires_recovery(
    tmp_path, monkeypatch
):
    ctx = prepare(tmp_path, prior=b"before", after=b"expected")

    def wrong_side_effect(plan, target, *, content):
        target.write_bytes(b"wrong-post-state")

    monkeypatch.setattr(
        AuthorizedRepositoryMutationExecutor,
        "_perform_side_effect",
        staticmethod(wrong_side_effect),
    )

    with pytest.raises(RepositoryMutationExecutorError, match="postcondition"):
        execute(ctx)

    assert ctx["target"].read_bytes() == b"wrong-post-state"
    auth = ctx["auth_store"].get("authz-executor-1")
    assert auth is not None and auth.consumed is True
    journal = ctx["journal_store"].get("tx-executor-1")
    assert journal is not None
    assert journal.current_state is MutationJournalState.FAILED
    assessment = ctx["journal_store"].assess_recovery("tx-executor-1")
    assert assessment.repository_mutation_may_exist is True

    # Simulate process restart: reconstruct both durable stores and reconcile
    # authorization consumption with the persisted failed journal.
    reopened_auth = RemoteMutationExecutionAuthorizationStore(
        tmp_path / "authorization.sqlite3"
    ).get("authz-executor-1")
    reopened_journal = RemoteMutationJournal(tmp_path / "journal.sqlite3").get(
        "tx-executor-1"
    )
    assert reopened_auth is not None and reopened_journal is not None
    cross_store = assess_executor_recovery(reopened_auth, reopened_journal)
    assert (
        cross_store.disposition
        is ExecutorRecoveryDisposition.HOLD_FAILED_AFTER_EXECUTION_INTENT
    )
    assert cross_store.repository_mutation_may_exist is True
    assert cross_store.recovery_hold is True
    assert cross_store.new_authorization_required is True


def test_parent_object_identity_drift_fails_after_intent_without_side_effect(
    tmp_path, monkeypatch
):
    ctx = prepare(tmp_path, prior=b"before", after=b"after")
    parent = FilesystemObjectIdentity.capture(ctx["target"].parent)
    target = FilesystemObjectIdentity.capture(ctx["target"])
    sequence = iter(
        [
            parent,
            target,
            FilesystemObjectIdentity(
                path=parent.path,
                exists=True,
                device=parent.device,
                inode=(parent.inode or 0) + 1,
                mode=parent.mode,
            ),
            target,
        ]
    )

    monkeypatch.setattr(
        FilesystemObjectIdentity,
        "capture",
        classmethod(lambda cls, path: next(sequence)),
    )

    with pytest.raises(
        RepositoryMutationExecutorError, match="target parent object identity changed"
    ):
        execute(ctx)

    assert ctx["target"].read_bytes() == b"before"
    auth = ctx["auth_store"].get("authz-executor-1")
    assert auth is not None and auth.consumed is True
    journal = ctx["journal_store"].get("tx-executor-1")
    assert journal is not None
    assert journal.current_state is MutationJournalState.FAILED
    assert (
        ctx["journal_store"]
        .assess_recovery("tx-executor-1")
        .repository_mutation_may_exist
        is True
    )


def test_target_object_identity_drift_fails_after_intent_without_side_effect(
    tmp_path, monkeypatch
):
    ctx = prepare(tmp_path, prior=b"before", after=b"after")
    parent = FilesystemObjectIdentity.capture(ctx["target"].parent)
    target = FilesystemObjectIdentity.capture(ctx["target"])
    sequence = iter(
        [
            parent,
            target,
            parent,
            FilesystemObjectIdentity(
                path=target.path,
                exists=True,
                device=target.device,
                inode=(target.inode or 0) + 1,
                mode=target.mode,
            ),
        ]
    )

    monkeypatch.setattr(
        FilesystemObjectIdentity,
        "capture",
        classmethod(lambda cls, path: next(sequence)),
    )

    with pytest.raises(
        RepositoryMutationExecutorError, match="target object identity changed"
    ):
        execute(ctx)

    assert ctx["target"].read_bytes() == b"before"
    auth = ctx["auth_store"].get("authz-executor-1")
    assert auth is not None and auth.consumed is True
    journal = ctx["journal_store"].get("tx-executor-1")
    assert journal is not None
    assert journal.current_state is MutationJournalState.FAILED
