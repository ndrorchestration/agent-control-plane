"""Simulation-only repository rollback execution composition.

This module consumes one exact rollback authorization and applies the rollback
only to an in-memory byte mapping. It never touches the filesystem.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from types import MappingProxyType
from typing import Mapping

from .remote_mutation_rollback_authorization import (
    RepositoryRollbackAuthorization,
    RepositoryRollbackAuthorizationStore,
)
from .remote_mutation_rollback_journal import (
    RemoteMutationRollbackJournal,
    RollbackJournalState,
    RollbackRecoveryDisposition,
)
from .remote_mutation_rollback_material_readback import (
    RollbackMaterialReadbackRecord,
)
from .remote_mutation_rollback_plan import (
    RepositoryRollbackPlan,
    RollbackAction,
)
from .remote_mutation_rollback_revalidation import (
    RepositoryRollbackRevalidationRecord,
)

ROLLBACK_SIMULATION_SCHEMA_VERSION = (
    "agent-control-plane.remote-mutation-rollback-simulation.v0-candidate"
)


class RollbackSimulationError(ValueError):
    pass


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


@dataclass(frozen=True)
class RollbackSimulationResult:
    authorization_id: str
    rollback_transaction_id: str
    rollback_plan_sha256: str
    rollback_executor_id: str
    simulation_id: str
    authorization_consumed: bool
    rollback_intent_recorded: bool
    simulated_effect_applied: bool
    rollback_verified: bool
    recovery_hold: bool
    final_target_exists: bool
    final_content_sha256: str | None
    simulation_only: bool = True
    live_side_effect_performed: bool = False
    rollback_executed: bool = False
    schema_version: str = ROLLBACK_SIMULATION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.simulation_only is not True:
            raise RollbackSimulationError("rollback simulation must remain simulation_only")
        if self.live_side_effect_performed is not False:
            raise RollbackSimulationError("rollback simulation cannot perform live side effects")
        if self.rollback_executed is not False:
            raise RollbackSimulationError("rollback simulation cannot claim rollback execution")


def _validate_identity(
    *,
    plan: RepositoryRollbackPlan,
    revalidation: RepositoryRollbackRevalidationRecord,
    material: RollbackMaterialReadbackRecord,
    authorization: RepositoryRollbackAuthorization,
    journal: RemoteMutationRollbackJournal,
) -> None:
    if revalidation.admitted is not True:
        raise RollbackSimulationError("rollback revalidation must be admitted")
    if material.admitted is not True:
        raise RollbackSimulationError("rollback material readback must be admitted")
    if authorization.consumed:
        raise RollbackSimulationError("rollback authorization must be unconsumed")
    record = journal.get(plan.rollback_transaction_id)
    if record is None:
        raise RollbackSimulationError("rollback journal transaction not found")
    if record.current_state is not RollbackJournalState.PREPARED:
        raise RollbackSimulationError("rollback journal must be PREPARED")
    exact = (
        revalidation.rollback_transaction_id == plan.rollback_transaction_id
        and revalidation.rollback_plan_sha256 == plan.rollback_plan_sha256
        and material.rollback_transaction_id == plan.rollback_transaction_id
        and material.rollback_plan_sha256 == plan.rollback_plan_sha256
        and material.authorization_id == authorization.authorization_id
        and authorization.rollback_transaction_id == plan.rollback_transaction_id
        and authorization.rollback_plan_sha256 == plan.rollback_plan_sha256
        and record.rollback_transaction_id == plan.rollback_transaction_id
        and record.rollback_plan_sha256 == plan.rollback_plan_sha256
    )
    if not exact:
        raise RollbackSimulationError("rollback simulation identity mismatch")


def simulate_authorized_rollback(
    *,
    authorization_store: RepositoryRollbackAuthorizationStore,
    authorization: RepositoryRollbackAuthorization,
    journal: RemoteMutationRollbackJournal,
    plan: RepositoryRollbackPlan,
    revalidation: RepositoryRollbackRevalidationRecord,
    material_readback: RollbackMaterialReadbackRecord,
    initial_state: Mapping[str, bytes],
    rollback_material: bytes | None,
    rollback_executor_id: str,
    simulation_id: str,
    consume_at: str,
    intent_at: str,
    effect_at: str,
    verified_at: str,
    interrupt_after_intent: bool = False,
) -> tuple[RollbackSimulationResult, Mapping[str, bytes]]:
    """Execute one rollback only against an in-memory mapping."""
    if not isinstance(initial_state, Mapping):
        raise TypeError("initial_state must be a mapping")
    if not isinstance(simulation_id, str) or not simulation_id.startswith("simulation:"):
        raise RollbackSimulationError("simulation_id must use simulation: namespace")
    if not isinstance(rollback_executor_id, str) or not rollback_executor_id.startswith("simulation:"):
        raise RollbackSimulationError("rollback_executor_id must use simulation: namespace")
    if authorization.rollback_executor_id != rollback_executor_id:
        raise RollbackSimulationError("rollback executor identity mismatch")
    durable_authorization = authorization_store.get(authorization.authorization_id)
    if durable_authorization is None:
        raise RollbackSimulationError("rollback authorization not found in durable store")
    if durable_authorization.authorization_sha256 != authorization.authorization_sha256:
        raise RollbackSimulationError("rollback authorization durable identity mismatch")
    if durable_authorization.consumed:
        raise RollbackSimulationError("rollback authorization must be unconsumed")
    authorization = durable_authorization
    for path, content in initial_state.items():
        if not isinstance(path, str) or not isinstance(content, bytes):
            raise RollbackSimulationError("simulated rollback state must map paths to bytes")

    _validate_identity(
        plan=plan,
        revalidation=revalidation,
        material=material_readback,
        authorization=authorization,
        journal=journal,
    )

    path = plan.requested_path
    exists = path in initial_state
    observed_sha = _sha(initial_state[path]) if exists else None
    if exists is not plan.expected_current_target_exists:
        raise RollbackSimulationError("simulated current target existence drift")
    if exists and observed_sha != plan.expected_current_content_sha256:
        raise RollbackSimulationError("simulated current content drift")

    if plan.action is RollbackAction.RESTORE_FILE_BYTES:
        if not isinstance(rollback_material, bytes):
            raise RollbackSimulationError("restore simulation requires rollback material bytes")
        if material_readback.observed_material_sha256 != _sha(rollback_material):
            raise RollbackSimulationError("rollback material bytes do not match readback record")
    else:
        if rollback_material is not None:
            raise RollbackSimulationError("delete-created simulation must not receive rollback bytes")

    consumed = authorization_store.consume(
        authorization.authorization_id,
        rollback_executor_id=rollback_executor_id,
        rollback_transaction_id=plan.rollback_transaction_id,
        rollback_plan_sha256=plan.rollback_plan_sha256,
        now=consume_at,
    )
    journal.append(
        plan.rollback_transaction_id,
        state=RollbackJournalState.ROLLBACK_INTENT_RECORDED,
        occurred_at=intent_at,
    )

    if interrupt_after_intent:
        assessment = journal.assess_recovery(plan.rollback_transaction_id)
        result = RollbackSimulationResult(
            authorization_id=authorization.authorization_id,
            rollback_transaction_id=plan.rollback_transaction_id,
            rollback_plan_sha256=plan.rollback_plan_sha256,
            rollback_executor_id=rollback_executor_id,
            simulation_id=simulation_id,
            authorization_consumed=consumed.consumed,
            rollback_intent_recorded=True,
            simulated_effect_applied=False,
            rollback_verified=False,
            recovery_hold=assessment.disposition
            is RollbackRecoveryDisposition.HOLD_AMBIGUOUS_ROLLBACK,
            final_target_exists=exists,
            final_content_sha256=observed_sha,
        )
        return result, MappingProxyType(dict(initial_state))

    simulated = dict(initial_state)
    if plan.action is RollbackAction.RESTORE_FILE_BYTES:
        assert isinstance(rollback_material, bytes)
        simulated[path] = bytes(rollback_material)
    elif plan.action is RollbackAction.DELETE_CREATED_FILE:
        simulated.pop(path, None)
    else:
        raise RollbackSimulationError("unsupported rollback action")

    effect_sha = hashlib.sha256(
        (
            simulation_id
            + "|"
            + plan.rollback_plan_sha256
            + "|"
            + str(path in simulated)
            + "|"
            + (_sha(simulated[path]) if path in simulated else "absent")
        ).encode("utf-8")
    ).hexdigest()
    journal.append(
        plan.rollback_transaction_id,
        state=RollbackJournalState.ROLLBACK_EFFECT_REPORTED,
        occurred_at=effect_at,
        evidence_sha256=effect_sha,
    )

    final_exists = path in simulated
    final_sha = _sha(simulated[path]) if final_exists else None
    verified = (
        final_exists is plan.desired_target_exists
        and final_sha == plan.desired_content_sha256
    )
    if not verified:
        raise RollbackSimulationError("simulated rollback postcondition mismatch")

    verify_sha = hashlib.sha256(
        (
            effect_sha
            + "|"
            + str(final_exists)
            + "|"
            + (final_sha or "absent")
        ).encode("utf-8")
    ).hexdigest()
    journal.append(
        plan.rollback_transaction_id,
        state=RollbackJournalState.ROLLBACK_VERIFIED,
        occurred_at=verified_at,
        evidence_sha256=verify_sha,
    )

    result = RollbackSimulationResult(
        authorization_id=authorization.authorization_id,
        rollback_transaction_id=plan.rollback_transaction_id,
        rollback_plan_sha256=plan.rollback_plan_sha256,
        rollback_executor_id=rollback_executor_id,
        simulation_id=simulation_id,
        authorization_consumed=consumed.consumed,
        rollback_intent_recorded=True,
        simulated_effect_applied=True,
        rollback_verified=True,
        recovery_hold=False,
        final_target_exists=final_exists,
        final_content_sha256=final_sha,
    )
    return result, MappingProxyType(simulated)
