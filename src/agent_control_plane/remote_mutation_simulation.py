"""Simulation-only composition of the candidate remote-mutation control chain.

This module never writes a repository and never calls Remote Desktop Commander.
It applies a typed mutation only to an in-memory byte mapping after consuming an
already-issued exact single-use authorization and journaling execution intent.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
from types import MappingProxyType
from typing import Mapping

from .remote_mutation_execution_authorization import (
    RemoteMutationExecutionAuthorization,
    RemoteMutationExecutionAuthorizationStore,
)
from .remote_mutation_execution_closure import (
    MutationExecutionClosureRecord,
    close_authorized_mutation_execution,
)
from .remote_mutation_execution_evidence import (
    ExternalMutationExecutionEvidence,
    MutationExecutionEvidenceReceipt,
    bind_mutation_execution_evidence,
)
from .remote_mutation_journal import MutationJournalState, RemoteMutationJournal
from .remote_mutation_postcondition import MutationPostconditionRecord
from .remote_mutation_rollback_custody import (
    RollbackMaterialDescriptor,
    RollbackMode,
)
from .remote_mutation_transaction import MutationPlan

MUTATION_SIMULATION_SCHEMA_VERSION = (
    "agent-control-plane.remote-mutation-simulation.v0-candidate"
)


class MutationSimulationError(ValueError):
    pass


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_json(value: Mapping[str, object]) -> str:
    data = json.dumps(
        dict(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def _parse_utc(value: str, field: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise MutationSimulationError(f"{field} must not be blank")
    raw = value.strip()
    candidate = raw[:-1] + "+00:00" if raw.endswith("Z") else raw
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError as exc:
        raise MutationSimulationError(f"{field} must be valid ISO-8601") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise MutationSimulationError(f"{field} must be timezone-aware UTC")
    if parsed.utcoffset() != timedelta(0):
        raise MutationSimulationError(f"{field} must use UTC")
    return parsed.astimezone(timezone.utc)


def _validate_chronology(
    *,
    consume_at: str,
    intent_at: str,
    effect_at: str,
    postcondition_at: str,
    interrupt_after_intent: bool,
) -> None:
    consume = _parse_utc(consume_at, "consume_at")
    intent = _parse_utc(intent_at, "intent_at")
    if consume > intent:
        raise MutationSimulationError("consume_at must not be after intent_at")
    if interrupt_after_intent:
        return
    effect = _parse_utc(effect_at, "effect_at")
    postcondition = _parse_utc(postcondition_at, "postcondition_at")
    if intent > effect or effect > postcondition:
        raise MutationSimulationError(
            "simulation chronology must be consume <= intent <= effect <= postcondition"
        )


def _validate_simulated_prestate(
    *,
    plan: MutationPlan,
    rollback_descriptor: RollbackMaterialDescriptor,
    authorization: RemoteMutationExecutionAuthorization,
    initial_state: Mapping[str, bytes],
) -> None:
    if rollback_descriptor.descriptor_sha256 != plan.rollback_sha256:
        raise MutationSimulationError("rollback descriptor does not match plan")
    if (
        authorization.rollback_descriptor_sha256
        != rollback_descriptor.descriptor_sha256
    ):
        raise MutationSimulationError("authorization rollback descriptor mismatch")
    if rollback_descriptor.operation_id != plan.operation_id:
        raise MutationSimulationError("rollback descriptor operation mismatch")
    if rollback_descriptor.path != plan.parameters["path"]:
        raise MutationSimulationError("rollback descriptor path mismatch")

    for path, content in initial_state.items():
        if not isinstance(path, str) or not path:
            raise MutationSimulationError(
                "simulated state path must be non-empty string"
            )
        if not isinstance(content, bytes):
            raise MutationSimulationError("simulated state content must be bytes")

    path = plan.parameters["path"]
    exists = path in initial_state
    if rollback_descriptor.mode is RollbackMode.DELETE_CREATED_FILE:
        if exists:
            raise MutationSimulationError(
                "delete-created rollback requires target absent in simulated prestate"
            )
        return

    if rollback_descriptor.mode is not RollbackMode.RESTORE_FILE_BYTES:
        raise MutationSimulationError("unsupported rollback mode")
    if not exists:
        raise MutationSimulationError(
            "restore-file rollback requires target present in simulated prestate"
        )
    observed = _sha256_bytes(initial_state[path])
    if observed != rollback_descriptor.prior_content_sha256:
        raise MutationSimulationError(
            "simulated prestate content does not match rollback material"
        )
    if len(initial_state[path]) != rollback_descriptor.prior_content_size:
        raise MutationSimulationError(
            "simulated prestate size does not match rollback material"
        )


@dataclass(frozen=True)
class MutationSimulationResult:
    transaction_id: str
    authorization_id: str
    executor_id: str
    execution_id: str
    plan_sha256: str
    final_state_sha256: str
    authorization_consumed: bool
    execution_intent_recorded: bool
    simulated_effect_applied: bool
    postcondition_verified: bool
    evidence_bound: bool
    closure_closed: bool
    recovery_hold: bool
    simulation_only: bool = True
    live_side_effect_performed: bool = False
    acp_mutation_executed: bool = False
    schema_version: str = MUTATION_SIMULATION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.simulation_only is not True:
            raise MutationSimulationError(
                "simulation result must remain simulation_only"
            )
        if self.live_side_effect_performed is not False:
            raise MutationSimulationError(
                "simulation cannot perform a live side effect"
            )
        if self.acp_mutation_executed is not False:
            raise MutationSimulationError(
                "simulation cannot claim ACP mutation execution"
            )


def _state_sha256(state: Mapping[str, bytes]) -> str:
    payload = {path: _sha256_bytes(content) for path, content in sorted(state.items())}
    return _sha256_json(payload)


def _postcondition_record(
    plan: MutationPlan,
    *,
    repository_id: str,
    simulated_state: Mapping[str, bytes],
    rollback_descriptor_sha256: str,
    rollback_custody_ref: str,
) -> MutationPostconditionRecord:
    path = plan.parameters["path"]
    target_exists = path in simulated_state
    observed = _sha256_bytes(simulated_state[path]) if target_exists else None

    if plan.operation_id == "repo.write_text_file":
        verified = target_exists and observed == plan.parameters["content_sha256"]
    elif plan.operation_id == "repo.delete_file":
        verified = not target_exists
    else:
        raise MutationSimulationError("unsupported simulated mutation operation")

    return MutationPostconditionRecord(
        request_id=plan.request_id,
        resource_id=plan.resource_id,
        operation_id=plan.operation_id,
        plan_sha256=plan.plan_sha256,
        requested_path=path,
        repository_root=f"simulation://{repository_id}",
        resolved_path=f"simulation://{repository_id}/{path}",
        rollback_descriptor_sha256=rollback_descriptor_sha256,
        rollback_custody_ref=rollback_custody_ref,
        target_exists=target_exists,
        observed_content_sha256=observed,
        path_revalidated=True,
        postcondition_verified=verified,
        reason=(
            "simulated postcondition matches exact plan"
            if verified
            else "simulated postcondition mismatch"
        ),
    )


def simulate_authorized_mutation(
    *,
    authorization_store: RemoteMutationExecutionAuthorizationStore,
    authorization: RemoteMutationExecutionAuthorization,
    journal: RemoteMutationJournal,
    plan: MutationPlan,
    rollback_descriptor: RollbackMaterialDescriptor,
    initial_state: Mapping[str, bytes],
    repository_id: str,
    executor_id: str,
    execution_id: str,
    consume_at: str,
    intent_at: str,
    effect_at: str,
    postcondition_at: str,
    write_content: bytes | None = None,
    interrupt_after_intent: bool = False,
) -> tuple[MutationSimulationResult, Mapping[str, bytes]]:
    """Run one exact mutation *simulation* without any filesystem/RDC side effect."""
    if authorization.consumed:
        raise MutationSimulationError(
            "authorization must be unconsumed at simulation start"
        )
    for value, field in (
        (authorization.authorization_id, "authorization_id"),
        (authorization.transaction_id, "transaction_id"),
        (executor_id, "executor_id"),
        (execution_id, "execution_id"),
    ):
        if not isinstance(value, str) or not value.startswith("simulation:"):
            raise MutationSimulationError(
                f"simulation {field} must use the simulation: namespace"
            )
    if authorization.executor_id != executor_id:
        raise MutationSimulationError("executor_id does not match authorization")
    current = journal.get(authorization.transaction_id)
    if current is None:
        raise MutationSimulationError("journal transaction not found")
    if authorization.transaction_id != current.transaction_id:
        raise MutationSimulationError("journal transaction identity mismatch")
    if authorization.plan_sha256 != plan.plan_sha256:
        raise MutationSimulationError("authorization plan mismatch")

    _validate_chronology(
        consume_at=consume_at,
        intent_at=intent_at,
        effect_at=effect_at,
        postcondition_at=postcondition_at,
        interrupt_after_intent=interrupt_after_intent,
    )
    _validate_simulated_prestate(
        plan=plan,
        rollback_descriptor=rollback_descriptor,
        authorization=authorization,
        initial_state=initial_state,
    )

    if current.current_state is not MutationJournalState.PREPARED:
        raise MutationSimulationError("journal must be PREPARED before simulation")

    consumed = authorization_store.consume(
        authorization.authorization_id,
        executor_id=executor_id,
        transaction_id=authorization.transaction_id,
        plan_sha256=plan.plan_sha256,
        now=consume_at,
    )
    journal.append(
        authorization.transaction_id,
        state=MutationJournalState.EXECUTION_INTENT_RECORDED,
        occurred_at=intent_at,
    )

    if interrupt_after_intent:
        assessment = journal.assess_recovery(authorization.transaction_id)
        result = MutationSimulationResult(
            transaction_id=authorization.transaction_id,
            authorization_id=authorization.authorization_id,
            executor_id=executor_id,
            execution_id=execution_id,
            plan_sha256=plan.plan_sha256,
            final_state_sha256=_state_sha256(initial_state),
            authorization_consumed=consumed.consumed,
            execution_intent_recorded=True,
            simulated_effect_applied=False,
            postcondition_verified=False,
            evidence_bound=False,
            closure_closed=False,
            recovery_hold=assessment.repository_mutation_may_exist,
        )
        return result, MappingProxyType(dict(initial_state))
    simulated = dict(initial_state)
    path = plan.parameters["path"]

    if plan.operation_id == "repo.write_text_file":
        if write_content is None:
            raise MutationSimulationError("write simulation requires write_content")
        if _sha256_bytes(write_content) != plan.parameters["content_sha256"]:
            raise MutationSimulationError(
                "write_content does not match planned content_sha256"
            )
        simulated[path] = bytes(write_content)
    elif plan.operation_id == "repo.delete_file":
        simulated.pop(path, None)
    else:
        raise MutationSimulationError("unsupported simulated mutation operation")

    effect_sha = _sha256_json(
        {
            "executor_id": executor_id,
            "execution_id": execution_id,
            "operation_id": plan.operation_id,
            "path": path,
            "plan_sha256": plan.plan_sha256,
            "simulated_state_sha256": _state_sha256(simulated),
        }
    )
    journal.append(
        authorization.transaction_id,
        state=MutationJournalState.EXTERNAL_EFFECT_REPORTED,
        occurred_at=effect_at,
        evidence_sha256=effect_sha,
    )

    postcondition = _postcondition_record(
        plan,
        repository_id=repository_id,
        simulated_state=simulated,
        rollback_descriptor_sha256=authorization.rollback_descriptor_sha256,
        rollback_custody_ref=authorization.custody_ref,
    )
    post_sha = _sha256_json(
        {
            "operation_id": postcondition.operation_id,
            "plan_sha256": postcondition.plan_sha256,
            "postcondition_verified": postcondition.postcondition_verified,
            "rollback_descriptor_sha256": postcondition.rollback_descriptor_sha256,
            "rollback_custody_ref": postcondition.rollback_custody_ref,
            "target_exists": postcondition.target_exists,
            "observed_content_sha256": postcondition.observed_content_sha256,
        }
    )
    if not postcondition.postcondition_verified:
        raise MutationSimulationError("simulated postcondition verification failed")

    terminal = journal.append(
        authorization.transaction_id,
        state=MutationJournalState.POSTCONDITION_VERIFIED,
        occurred_at=postcondition_at,
        evidence_sha256=post_sha,
    )
    evidence = ExternalMutationExecutionEvidence(
        executor_id=executor_id,
        execution_id=execution_id,
        transaction_id=authorization.transaction_id,
        request_id=plan.request_id,
        resource_id=plan.resource_id,
        operation_id=plan.operation_id,
        plan_sha256=plan.plan_sha256,
        result_sha256=_state_sha256(simulated),
        external_effect_sha256=effect_sha,
        postcondition_evidence_sha256=post_sha,
    )
    receipt: MutationExecutionEvidenceReceipt = bind_mutation_execution_evidence(
        plan,
        terminal,
        postcondition,
        evidence,
    )
    closure: MutationExecutionClosureRecord = close_authorized_mutation_execution(
        consumed,
        terminal,
        receipt,
    )

    result = MutationSimulationResult(
        transaction_id=authorization.transaction_id,
        authorization_id=authorization.authorization_id,
        executor_id=executor_id,
        execution_id=execution_id,
        plan_sha256=plan.plan_sha256,
        final_state_sha256=_state_sha256(simulated),
        authorization_consumed=consumed.consumed,
        execution_intent_recorded=True,
        simulated_effect_applied=True,
        postcondition_verified=postcondition.postcondition_verified,
        evidence_bound=receipt.evidence_bound,
        closure_closed=closure.closed,
        recovery_hold=False,
    )
    return result, MappingProxyType(simulated)
