from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from agent_control_plane.remote_mutation_composition import MutationCompositionRecord
from agent_control_plane.remote_mutation_execution_authorization import (
    RemoteMutationExecutionAuthorizationStore,
)
from agent_control_plane.remote_mutation_journal import (
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
from agent_control_plane.remote_mutation_simulation import (
    MUTATION_SIMULATION_SCHEMA_VERSION,
    MutationSimulationError,
    simulate_authorized_mutation,
)
from agent_control_plane.remote_mutation_transaction import (
    MutationPlan,
    MutationTransactionReceipt,
    MutationTransactionState,
)


def sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def build(
    tmp_path: Path,
    *,
    operation_id: str = "repo.write_text_file",
    target_exists: bool = True,
    after: bytes = b"after\n",
):
    prior = b"before\n"
    path = "docs/example.md"
    if operation_id == "repo.write_text_file":
        descriptor = (
            RollbackMaterialDescriptor(
                operation_id=operation_id,
                path=path,
                mode=RollbackMode.RESTORE_FILE_BYTES,
                prior_content_sha256=sha(prior),
                prior_content_size=len(prior),
            )
            if target_exists
            else RollbackMaterialDescriptor(
                operation_id=operation_id,
                path=path,
                mode=RollbackMode.DELETE_CREATED_FILE,
            )
        )
        parameters = {"path": path, "content_sha256": sha(after)}
    else:
        descriptor = RollbackMaterialDescriptor(
            operation_id=operation_id,
            path=path,
            mode=RollbackMode.RESTORE_FILE_BYTES,
            prior_content_sha256=sha(prior),
            prior_content_size=len(prior),
        )
        parameters = {"path": path, "prior_content_sha256": sha(prior)}

    plan = MutationPlan(
        request_id="req-sim-1",
        authority_id="auth-sim-1",
        resource_id="repo:sim",
        resource_type="git_repository",
        operation_id=operation_id,
        parameters=parameters,
        precondition_sha256="a" * 64,
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
    path_safety = MutationPathSafetyRecord(
        request_id=plan.request_id,
        resource_id=plan.resource_id,
        operation_id=plan.operation_id,
        plan_sha256=plan.plan_sha256,
        requested_path=path,
        repository_root="C:/simulation/repo",
        resolved_path=f"C:/simulation/repo/{path}",
        admitted=True,
        reason="simulated pre-execution path identity",
        repository_boundary_verified=True,
        symlink_safe=True,
        repository_metadata_safe=True,
        operation_shape_verified=True,
        target_exists=target_exists,
    )
    custody = RollbackCustodyAdmissionRecord(
        request_id=plan.request_id,
        resource_id=plan.resource_id,
        operation_id=plan.operation_id,
        plan_sha256=plan.plan_sha256,
        descriptor_sha256=descriptor.descriptor_sha256,
        custody_ref="custody://simulation/rollback-1",
        admitted=True,
        reason="simulated custody identity",
        readback_verified=True,
    )
    journal = RemoteMutationJournal(tmp_path / "journal.sqlite3")
    journal_record = journal.begin(
        transaction_id="simulation:tx-1",
        plan=plan,
        path_safety=path_safety,
        rollback_custody=custody,
        created_at="2026-09-27T12:00:00Z",
    )
    store = RemoteMutationExecutionAuthorizationStore(tmp_path / "authz.sqlite3")
    authorization = store.issue(
        authorization_id="simulation:authz-1",
        executor_id="simulation:test",
        composition=composition,
        plan=plan,
        transaction=transaction,
        path_safety=path_safety,
        rollback_custody=custody,
        journal=journal_record,
        issued_at="2026-09-27T12:00:00Z",
        expires_at="2026-09-27T12:05:00Z",
    )
    initial = {path: prior} if target_exists else {}
    return plan, descriptor, store, authorization, journal, initial, after


def run_simulation(plan, descriptor, store, authorization, journal, initial, **kwargs):
    return simulate_authorized_mutation(
        authorization_store=store,
        authorization=authorization,
        journal=journal,
        plan=plan,
        rollback_descriptor=descriptor,
        initial_state=initial,
        repository_id="unit-test",
        executor_id=kwargs.pop("executor_id", authorization.executor_id),
        execution_id=kwargs.pop("execution_id", "simulation:exec-1"),
        consume_at=kwargs.pop("consume_at", "2026-09-27T12:00:01Z"),
        intent_at=kwargs.pop("intent_at", "2026-09-27T12:00:02Z"),
        effect_at=kwargs.pop("effect_at", "2026-09-27T12:00:03Z"),
        postcondition_at=kwargs.pop("postcondition_at", "2026-09-27T12:00:04Z"),
        **kwargs,
    )


@pytest.mark.parametrize("target_exists", [True, False])
def test_write_simulation_closes_exact_chain_without_live_side_effect(
    tmp_path, target_exists
):
    plan, descriptor, store, authorization, journal, initial, after = build(
        tmp_path,
        target_exists=target_exists,
    )
    original = dict(initial)

    result, final_state = run_simulation(
        plan,
        descriptor,
        store,
        authorization,
        journal,
        initial,
        write_content=after,
    )

    assert result.schema_version == MUTATION_SIMULATION_SCHEMA_VERSION
    assert result.simulation_only is True
    assert result.live_side_effect_performed is False
    assert result.acp_mutation_executed is False
    assert result.authorization_consumed is True
    assert result.execution_intent_recorded is True
    assert result.simulated_effect_applied is True
    assert result.postcondition_verified is True
    assert result.evidence_bound is True
    assert result.closure_closed is True
    assert result.recovery_hold is False
    assert final_state[plan.parameters["path"]] == after
    assert initial == original
    assert (
        journal.get("simulation:tx-1").current_state
        is MutationJournalState.POSTCONDITION_VERIFIED
    )


def test_delete_simulation_closes_exact_chain(tmp_path):
    plan, descriptor, store, authorization, journal, initial, _ = build(
        tmp_path,
        operation_id="repo.delete_file",
    )

    result, final_state = run_simulation(
        plan, descriptor, store, authorization, journal, initial
    )

    assert result.closure_closed is True
    assert plan.parameters["path"] not in final_state
    assert result.live_side_effect_performed is False


def test_interrupt_after_intent_enters_recovery_hold_without_effect(tmp_path):
    plan, descriptor, store, authorization, journal, initial, after = build(tmp_path)
    original = dict(initial)

    result, final_state = run_simulation(
        plan,
        descriptor,
        store,
        authorization,
        journal,
        initial,
        write_content=after,
        interrupt_after_intent=True,
    )

    assert result.authorization_consumed is True
    assert result.execution_intent_recorded is True
    assert result.simulated_effect_applied is False
    assert result.postcondition_verified is False
    assert result.evidence_bound is False
    assert result.closure_closed is False
    assert result.recovery_hold is True
    assert dict(final_state) == original
    assessment = journal.assess_recovery("simulation:tx-1")
    assert assessment.disposition is MutationRecoveryDisposition.HOLD_AMBIGUOUS_EFFECT


def test_wrong_executor_fails_before_authorization_consumption(tmp_path):
    plan, descriptor, store, authorization, journal, initial, after = build(tmp_path)

    with pytest.raises(MutationSimulationError, match="executor_id"):
        run_simulation(
            plan,
            descriptor,
            store,
            authorization,
            journal,
            initial,
            write_content=after,
            executor_id="simulation:other",
        )

    assert store.get(authorization.authorization_id).consumed is False
    assert journal.get("simulation:tx-1").current_state is MutationJournalState.PREPARED


def test_wrong_write_bytes_fail_after_intent_but_before_effect_report(tmp_path):
    plan, descriptor, store, authorization, journal, initial, _ = build(tmp_path)

    with pytest.raises(MutationSimulationError, match="content_sha256"):
        run_simulation(
            plan,
            descriptor,
            store,
            authorization,
            journal,
            initial,
            write_content=b"wrong\n",
        )

    assert store.get(authorization.authorization_id).consumed is True
    assert (
        journal.get("simulation:tx-1").current_state
        is MutationJournalState.EXECUTION_INTENT_RECORDED
    )


def test_consumed_authorization_cannot_be_replayed(tmp_path):
    plan, descriptor, store, authorization, journal, initial, after = build(tmp_path)

    first, _ = run_simulation(
        plan,
        descriptor,
        store,
        authorization,
        journal,
        initial,
        write_content=after,
    )
    assert first.closure_closed is True

    with pytest.raises(MutationSimulationError, match="unconsumed"):
        run_simulation(
            plan,
            descriptor,
            store,
            store.get(authorization.authorization_id),
            journal,
            initial,
            write_content=after,
        )


def test_prestate_drift_fails_before_authorization_consumption(tmp_path):
    plan, descriptor, store, authorization, journal, initial, after = build(tmp_path)
    drifted = dict(initial)
    drifted[plan.parameters["path"]] = b"unexpected-prestate\n"

    with pytest.raises(MutationSimulationError, match="rollback material"):
        run_simulation(
            plan,
            descriptor,
            store,
            authorization,
            journal,
            drifted,
            write_content=after,
        )

    assert store.get(authorization.authorization_id).consumed is False
    assert journal.get("simulation:tx-1").current_state is MutationJournalState.PREPARED


def test_backward_chronology_fails_before_authorization_consumption(tmp_path):
    plan, descriptor, store, authorization, journal, initial, after = build(tmp_path)

    with pytest.raises(MutationSimulationError, match="chronology"):
        run_simulation(
            plan,
            descriptor,
            store,
            authorization,
            journal,
            initial,
            write_content=after,
            effect_at="2026-09-27T12:00:05Z",
            postcondition_at="2026-09-27T12:00:04Z",
        )

    assert store.get(authorization.authorization_id).consumed is False
    assert journal.get("simulation:tx-1").current_state is MutationJournalState.PREPARED


def test_non_simulation_namespace_fails_before_authorization_consumption(tmp_path):
    plan, descriptor, store, authorization, journal, initial, after = build(tmp_path)

    with pytest.raises(MutationSimulationError, match="simulation: namespace"):
        run_simulation(
            plan,
            descriptor,
            store,
            authorization,
            journal,
            initial,
            write_content=after,
            execution_id="external:exec-1",
        )

    assert store.get(authorization.authorization_id).consumed is False
    assert journal.get("simulation:tx-1").current_state is MutationJournalState.PREPARED
