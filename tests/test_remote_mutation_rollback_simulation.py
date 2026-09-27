from __future__ import annotations

import hashlib

import pytest

from agent_control_plane.remote_mutation_rollback_authorization import (
    RepositoryRollbackAuthorizationStore,
)
from agent_control_plane.remote_mutation_rollback_journal import (
    RemoteMutationRollbackJournal,
    RollbackJournalState,
    RollbackRecoveryDisposition,
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
from agent_control_plane.remote_mutation_rollback_custody import (
    RollbackMaterialDescriptor,
    RollbackMode,
)
from agent_control_plane.remote_mutation_rollback_simulation import (
    ROLLBACK_SIMULATION_SCHEMA_VERSION,
    RollbackSimulationError,
    simulate_authorized_rollback,
)

A = "a" * 64


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def setup_restore(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    (root / ".git").mkdir()
    (root / "docs").mkdir()
    current = b"current-state"
    prior = b"prior-state"
    (root / "docs" / "example.md").write_bytes(current)
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
        rollback_custody_ref="custody://rollback/sim",
        action=RollbackAction.RESTORE_FILE_BYTES,
        expected_current_target_exists=True,
        expected_current_content_sha256=sha(current),
        desired_target_exists=True,
        desired_content_sha256=sha(prior),
    )
    revalidation = inspect_repository_rollback_state(plan, repository_root=root)
    journal = RemoteMutationRollbackJournal(tmp_path / "journal.sqlite3")
    journal_record = journal.begin(plan=plan, created_at="2026-09-27T16:00:00Z")
    store = RepositoryRollbackAuthorizationStore(tmp_path / "auth.sqlite3")
    auth = store.issue(
        authorization_id="simulation:rb-authz",
        rollback_executor_id="simulation:rollback-executor",
        plan=plan,
        revalidation=revalidation,
        journal=journal_record,
        issued_at="2026-09-27T16:00:00Z",
        expires_at="2026-09-27T16:05:00Z",
    )
    material = verify_rollback_material_readback(
        plan, descriptor, auth, material=prior
    )
    return root, current, prior, plan, revalidation, journal, store, auth, material


def run(setup, **kwargs):
    root, current, prior, plan, revalidation, journal, store, auth, material = setup
    initial = {"docs/example.md": current}
    return simulate_authorized_rollback(
        authorization_store=store,
        authorization=auth,
        journal=journal,
        plan=plan,
        revalidation=revalidation,
        material_readback=material,
        initial_state=initial,
        rollback_material=kwargs.pop("rollback_material", prior),
        rollback_executor_id=kwargs.pop(
            "rollback_executor_id", "simulation:rollback-executor"
        ),
        simulation_id=kwargs.pop("simulation_id", "simulation:rollback-1"),
        consume_at=kwargs.pop("consume_at", "2026-09-27T16:00:01Z"),
        intent_at=kwargs.pop("intent_at", "2026-09-27T16:00:02Z"),
        effect_at=kwargs.pop("effect_at", "2026-09-27T16:00:03Z"),
        verified_at=kwargs.pop("verified_at", "2026-09-27T16:00:04Z"),
        **kwargs,
    )


def test_restore_simulation_closes_rollback_journal_without_live_side_effect(tmp_path):
    setup = setup_restore(tmp_path)
    root = setup[0]
    before = (root / "docs" / "example.md").read_bytes()
    result, final_state = run(setup)
    assert result.schema_version == ROLLBACK_SIMULATION_SCHEMA_VERSION
    assert result.simulation_only is True
    assert result.live_side_effect_performed is False
    assert result.rollback_executed is False
    assert result.authorization_consumed is True
    assert result.rollback_intent_recorded is True
    assert result.simulated_effect_applied is True
    assert result.rollback_verified is True
    assert final_state["docs/example.md"] == b"prior-state"
    assert (root / "docs" / "example.md").read_bytes() == before
    assert (
        setup[5].get("rb-tx").current_state
        is RollbackJournalState.ROLLBACK_VERIFIED
    )


def test_interrupt_after_intent_enters_recovery_hold_without_effect(tmp_path):
    setup = setup_restore(tmp_path)
    result, final_state = run(setup, interrupt_after_intent=True)
    assert result.authorization_consumed is True
    assert result.simulated_effect_applied is False
    assert result.rollback_verified is False
    assert result.recovery_hold is True
    assert final_state["docs/example.md"] == b"current-state"
    assessment = setup[5].assess_recovery("rb-tx")
    assert assessment.disposition is RollbackRecoveryDisposition.HOLD_AMBIGUOUS_ROLLBACK


def test_wrong_executor_fails_before_authorization_consumption(tmp_path):
    setup = setup_restore(tmp_path)
    with pytest.raises(RollbackSimulationError, match="executor identity"):
        run(setup, rollback_executor_id="simulation:other")
    assert setup[6].get("simulation:rb-authz").consumed is False
    assert setup[5].get("rb-tx").current_state is RollbackJournalState.PREPARED


def test_non_simulation_namespace_fails_before_consumption(tmp_path):
    setup = setup_restore(tmp_path)
    with pytest.raises(RollbackSimulationError, match="simulation: namespace"):
        run(setup, simulation_id="live:rollback")
    assert setup[6].get("simulation:rb-authz").consumed is False


def test_current_state_drift_fails_before_consumption(tmp_path):
    setup = setup_restore(tmp_path)
    root, current, prior, plan, revalidation, journal, store, auth, material = setup
    with pytest.raises(RollbackSimulationError, match="current content drift"):
        simulate_authorized_rollback(
            authorization_store=store,
            authorization=auth,
            journal=journal,
            plan=plan,
            revalidation=revalidation,
            material_readback=material,
            initial_state={"docs/example.md": b"drift"},
            rollback_material=prior,
            rollback_executor_id="simulation:rollback-executor",
            simulation_id="simulation:rollback-1",
            consume_at="2026-09-27T16:00:01Z",
            intent_at="2026-09-27T16:00:02Z",
            effect_at="2026-09-27T16:00:03Z",
            verified_at="2026-09-27T16:00:04Z",
        )
    assert store.get(auth.authorization_id).consumed is False


def test_wrong_material_fails_before_consumption(tmp_path):
    setup = setup_restore(tmp_path)
    with pytest.raises(RollbackSimulationError, match="readback record"):
        run(setup, rollback_material=b"wrong")
    assert setup[6].get("simulation:rb-authz").consumed is False


def test_consumed_authorization_cannot_replay(tmp_path):
    setup = setup_restore(tmp_path)
    result, _ = run(setup)
    assert result.rollback_verified is True
    with pytest.raises(RollbackSimulationError, match="unconsumed"):
        run(setup)


def test_delete_created_file_simulation(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    (root / ".git").mkdir()
    (root / "docs").mkdir()
    created = b"created"
    (root / "docs" / "new.md").write_bytes(created)
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
        rollback_custody_ref="custody://rollback/delete-sim",
        action=RollbackAction.DELETE_CREATED_FILE,
        expected_current_target_exists=True,
        expected_current_content_sha256=sha(created),
        desired_target_exists=False,
        desired_content_sha256=None,
    )
    revalidation = inspect_repository_rollback_state(plan, repository_root=root)
    journal = RemoteMutationRollbackJournal(tmp_path / "journal-del.sqlite3")
    jr = journal.begin(plan=plan, created_at="2026-09-27T16:00:00Z")
    store = RepositoryRollbackAuthorizationStore(tmp_path / "auth-del.sqlite3")
    auth = store.issue(
        authorization_id="simulation:rb-del-authz",
        rollback_executor_id="simulation:rollback-executor",
        plan=plan,
        revalidation=revalidation,
        journal=jr,
        issued_at="2026-09-27T16:00:00Z",
        expires_at="2026-09-27T16:05:00Z",
    )
    material = verify_rollback_material_readback(
        plan, descriptor, auth, material=None
    )
    result, final_state = simulate_authorized_rollback(
        authorization_store=store,
        authorization=auth,
        journal=journal,
        plan=plan,
        revalidation=revalidation,
        material_readback=material,
        initial_state={"docs/new.md": created},
        rollback_material=None,
        rollback_executor_id="simulation:rollback-executor",
        simulation_id="simulation:rollback-delete",
        consume_at="2026-09-27T16:00:01Z",
        intent_at="2026-09-27T16:00:02Z",
        effect_at="2026-09-27T16:00:03Z",
        verified_at="2026-09-27T16:00:04Z",
    )
    assert result.rollback_verified is True
    assert "docs/new.md" not in final_state
    assert (root / "docs" / "new.md").exists()
