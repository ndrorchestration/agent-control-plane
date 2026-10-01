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
    RepositoryMutationExecutorError,
)
from agent_control_plane.remote_mutation_journal import (
    MutationJournalState,
    RemoteMutationJournal,
)
from agent_control_plane.remote_mutation_path_safety import (
    inspect_repository_mutation_path,
)
from agent_control_plane.remote_mutation_rollback_authorization import (
    RepositoryRollbackAuthorizationStore,
)
from agent_control_plane.remote_mutation_rollback_custody import (
    RollbackCustodyAdmissionRecord,
    RollbackMaterialDescriptor,
    RollbackMode,
)
from agent_control_plane.remote_mutation_rollback_executor import (
    AuthorizedRepositoryRollbackExecutor,
    DEFAULT_ROLLBACK_EXECUTOR_ID,
)
from agent_control_plane.remote_mutation_rollback_journal import (
    RemoteMutationRollbackJournal,
    RollbackJournalState,
)
from agent_control_plane.remote_mutation_rollback_material_readback import (
    verify_rollback_material_readback,
)
from agent_control_plane.remote_mutation_rollback_plan import (
    build_repository_rollback_plan,
)
from agent_control_plane.remote_mutation_rollback_revalidation import (
    inspect_repository_rollback_state,
)
from agent_control_plane.remote_mutation_transaction import (
    MutationPlan,
    MutationTransactionReceipt,
    MutationTransactionState,
)

A = "a" * 64


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def test_bounded_local_mutation_failure_then_separately_authorized_rollback(
    tmp_path,
    monkeypatch,
):
    root = tmp_path / "repo"
    root.mkdir()
    (root / ".git").mkdir()
    (root / "docs").mkdir()
    target = root / "docs" / "example.md"

    prior = b"before"
    intended = b"after"
    wrong = b"wrong-post-state"
    target.write_bytes(prior)

    descriptor = RollbackMaterialDescriptor(
        operation_id="repo.write_text_file",
        path="docs/example.md",
        mode=RollbackMode.RESTORE_FILE_BYTES,
        prior_content_sha256=sha(prior),
        prior_content_size=len(prior),
    )
    plan = MutationPlan(
        request_id="req-local-test",
        authority_id="authority-local-test",
        resource_id="repo:disposable-local-test",
        resource_type="git_repository",
        operation_id="repo.write_text_file",
        parameters={
            "path": "docs/example.md",
            "content_sha256": sha(intended),
        },
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
        reason="bounded disposable LOCAL_TEST composition",
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
        custody_ref="custody://disposable-local-test/prior-bytes",
        admitted=True,
        reason="bounded test custody",
        readback_verified=True,
    )

    mutation_journal = RemoteMutationJournal(tmp_path / "mutation-journal.sqlite3")
    prepared = mutation_journal.begin(
        transaction_id="mutation-tx-local-test",
        plan=plan,
        path_safety=path_safety,
        rollback_custody=custody,
        created_at="2026-10-01T21:10:00Z",
    )
    mutation_auth = RemoteMutationExecutionAuthorizationStore(
        tmp_path / "mutation-authorization.sqlite3"
    )
    authorization = mutation_auth.issue(
        authorization_id="mutation-auth-local-test",
        executor_id=DEFAULT_REPOSITORY_MUTATION_EXECUTOR_ID,
        composition=composition,
        plan=plan,
        transaction=transaction,
        path_safety=path_safety,
        rollback_custody=custody,
        journal=prepared,
        issued_at="2026-10-01T21:10:00Z",
        expires_at="2026-10-01T21:20:00Z",
    )
    mutation_executor = AuthorizedRepositoryMutationExecutor(
        allowed_repository_roots=[root],
        experimental_enable=True,
    )

    def wrong_side_effect(plan, repository_root, target, *, content):
        target.write_bytes(wrong)

    monkeypatch.setattr(
        AuthorizedRepositoryMutationExecutor,
        "_perform_side_effect",
        staticmethod(wrong_side_effect),
    )

    with pytest.raises(RepositoryMutationExecutorError, match="postcondition"):
        mutation_executor.execute(
            authorization_store=mutation_auth,
            authorization_id=authorization.authorization_id,
            journal_store=mutation_journal,
            composition=composition,
            plan=plan,
            prior_path_safety=path_safety,
            rollback_custody=custody,
            rollback_descriptor=descriptor,
            repository_root=root,
            execution_id="mutation-exec-local-test",
            content=intended,
            authorization_consumed_at="2026-10-01T21:10:30Z",
            execution_intent_at="2026-10-01T21:10:31Z",
            external_effect_at="2026-10-01T21:10:32Z",
            postcondition_at="2026-10-01T21:10:33Z",
        )

    assert target.read_bytes() == wrong
    consumed = mutation_auth.get(authorization.authorization_id)
    assert consumed is not None and consumed.consumed is True
    failed_journal = mutation_journal.get("mutation-tx-local-test")
    assert failed_journal is not None
    assert failed_journal.current_state is MutationJournalState.FAILED
    recovery = mutation_journal.assess_recovery("mutation-tx-local-test")
    assert recovery.repository_mutation_may_exist is True

    rollback_plan = build_repository_rollback_plan(
        plan,
        descriptor,
        custody,
        failed_journal,
        rollback_request_id="rollback-req-local-test",
        rollback_authority_id="rollback-authority-local-test",
        rollback_transaction_id="rollback-tx-local-test",
        expected_current_target_exists=True,
        expected_current_content_sha256=sha(wrong),
    )
    rollback_revalidation = inspect_repository_rollback_state(
        rollback_plan,
        repository_root=root,
    )
    assert rollback_revalidation.admitted is True

    rollback_journal = RemoteMutationRollbackJournal(
        tmp_path / "rollback-journal.sqlite3"
    )
    rollback_prepared = rollback_journal.begin(
        plan=rollback_plan,
        created_at="2026-10-01T21:11:00Z",
    )
    rollback_auth = RepositoryRollbackAuthorizationStore(
        tmp_path / "rollback-authorization.sqlite3"
    )
    rollback_authorization = rollback_auth.issue(
        authorization_id="rollback-auth-local-test",
        rollback_executor_id=DEFAULT_ROLLBACK_EXECUTOR_ID,
        plan=rollback_plan,
        revalidation=rollback_revalidation,
        journal=rollback_prepared,
        issued_at="2026-10-01T21:11:00Z",
        expires_at="2026-10-01T21:21:00Z",
    )
    readback = verify_rollback_material_readback(
        rollback_plan,
        descriptor,
        rollback_authorization,
        material=prior,
    )
    rollback_executor = AuthorizedRepositoryRollbackExecutor(
        allowed_repository_roots=[root],
        experimental_enable=True,
    )
    rollback_result = rollback_executor.execute(
        authorization_store=rollback_auth,
        authorization_id=rollback_authorization.authorization_id,
        journal_store=rollback_journal,
        plan=rollback_plan,
        prior_revalidation=rollback_revalidation,
        material_readback=readback,
        repository_root=root,
        rollback_material=prior,
        authorization_consumed_at="2026-10-01T21:11:30Z",
        rollback_intent_at="2026-10-01T21:11:31Z",
        rollback_effect_at="2026-10-01T21:11:32Z",
        rollback_verified_at="2026-10-01T21:11:33Z",
    )

    assert rollback_result.rollback_executed is True
    assert rollback_result.authorization_consumed is True
    assert rollback_result.rollback_postcondition_verified is True
    assert target.read_bytes() == prior

    final_rollback_journal = rollback_journal.get("rollback-tx-local-test")
    assert final_rollback_journal is not None
    assert (
        final_rollback_journal.current_state
        is RollbackJournalState.ROLLBACK_VERIFIED
    )

    preserved_original = mutation_journal.get("mutation-tx-local-test")
    assert preserved_original is not None
    assert preserved_original.current_state is MutationJournalState.FAILED
