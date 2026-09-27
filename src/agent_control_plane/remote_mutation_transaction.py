"""Non-executing typed mutation transaction contract.

This candidate models mutation planning, preconditions, rollback, and evidence
without providing any executor capable of changing external state.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import hashlib
import json
from types import MappingProxyType
from typing import Any, Mapping, Tuple

MUTATION_TRANSACTION_SCHEMA_VERSION = "agent-control-plane.remote-mutation-transaction.v0-candidate"


class MutationTransactionError(ValueError):
    pass


class MutationTransactionState(str, Enum):
    PLANNED = "planned"
    PRECONDITIONS_VERIFIED = "preconditions_verified"
    BLOCKED = "blocked"


def _required(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise MutationTransactionError(f"{field_name} must not be blank")
    return value.strip()


def _sha256(value: str, field_name: str) -> str:
    value = _required(value, field_name)
    if len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
        raise MutationTransactionError(f"{field_name} must be lowercase sha256")
    return value


@dataclass(frozen=True)
class MutationOperationSpec:
    operation_id: str
    resource_type: str
    parameter_names: Tuple[str, ...]
    rollback_required: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "operation_id", _required(self.operation_id, "operation_id"))
        object.__setattr__(self, "resource_type", _required(self.resource_type, "resource_type"))
        if not isinstance(self.parameter_names, tuple):
            raise MutationTransactionError("parameter_names must be tuple")
        normalized = tuple(_required(v, "parameter_names") for v in self.parameter_names)
        if len(set(normalized)) != len(normalized):
            raise MutationTransactionError("parameter_names must not contain duplicates")
        object.__setattr__(self, "parameter_names", normalized)


_MUTATION_REGISTRY = {
    "repo.write_text_file": MutationOperationSpec(
        "repo.write_text_file", "git_repository", ("path", "content_sha256")
    ),
    "repo.delete_file": MutationOperationSpec(
        "repo.delete_file", "git_repository", ("path", "prior_content_sha256")
    ),
}
MUTATION_OPERATION_REGISTRY: Mapping[str, MutationOperationSpec] = MappingProxyType(_MUTATION_REGISTRY)


def get_mutation_operation(operation_id: str) -> MutationOperationSpec:
    try:
        return MUTATION_OPERATION_REGISTRY[operation_id]
    except KeyError as exc:
        raise MutationTransactionError("unknown mutation operation") from exc


@dataclass(frozen=True)
class MutationPlan:
    request_id: str
    authority_id: str
    resource_id: str
    resource_type: str
    operation_id: str
    parameters: Mapping[str, str]
    precondition_sha256: str
    rollback_sha256: str

    def __post_init__(self) -> None:
        for field in ("request_id", "authority_id", "resource_id", "resource_type", "operation_id"):
            object.__setattr__(self, field, _required(getattr(self, field), field))
        spec = get_mutation_operation(self.operation_id)
        if self.resource_type != spec.resource_type:
            raise MutationTransactionError("resource_type does not match operation")
        if not isinstance(self.parameters, Mapping):
            raise MutationTransactionError("parameters must be mapping")
        keys = tuple(sorted(self.parameters))
        if keys != tuple(sorted(spec.parameter_names)):
            raise MutationTransactionError("parameters must exactly match operation schema")
        normalized = {}
        for k, v in self.parameters.items():
            if k == "path":
                if not isinstance(v, str) or not v:
                    raise MutationTransactionError("parameters.path must not be blank")
                normalized[k] = v
            else:
                normalized[k] = _required(v, f"parameters.{k}")
        for k, v in normalized.items():
            if k.endswith("sha256"):
                _sha256(v, f"parameters.{k}")
        object.__setattr__(self, "parameters", MappingProxyType(normalized))
        object.__setattr__(self, "precondition_sha256", _sha256(self.precondition_sha256, "precondition_sha256"))
        object.__setattr__(self, "rollback_sha256", _sha256(self.rollback_sha256, "rollback_sha256"))

    def canonical_bytes(self) -> bytes:
        payload = {
            "authority_id": self.authority_id,
            "operation_id": self.operation_id,
            "parameters": dict(sorted(self.parameters.items())),
            "precondition_sha256": self.precondition_sha256,
            "request_id": self.request_id,
            "resource_id": self.resource_id,
            "resource_type": self.resource_type,
            "rollback_sha256": self.rollback_sha256,
        }
        return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")

    @property
    def plan_sha256(self) -> str:
        return hashlib.sha256(self.canonical_bytes()).hexdigest()


@dataclass(frozen=True)
class MutationTransactionReceipt:
    request_id: str
    authority_id: str
    operation_id: str
    plan_sha256: str
    precondition_sha256: str
    rollback_sha256: str
    state: MutationTransactionState
    preconditions_verified: bool
    rollback_available: bool
    mutation_executed: bool = False
    execution_enabled: bool = False
    schema_version: str = MUTATION_TRANSACTION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        for field in ("request_id", "authority_id", "operation_id"):
            object.__setattr__(self, field, _required(getattr(self, field), field))
        for field in ("plan_sha256", "precondition_sha256", "rollback_sha256"):
            object.__setattr__(self, field, _sha256(getattr(self, field), field))
        if not isinstance(self.state, MutationTransactionState):
            raise MutationTransactionError("state must be MutationTransactionState")
        if self.mutation_executed is not False:
            raise MutationTransactionError("mutation execution is not implemented")
        if self.execution_enabled is not False:
            raise MutationTransactionError("execution is not enabled")
        if self.state is MutationTransactionState.PRECONDITIONS_VERIFIED:
            if self.preconditions_verified is not True or self.rollback_available is not True:
                raise MutationTransactionError("verified state requires preconditions and rollback")


def prepare_mutation_transaction(
    plan: MutationPlan,
    *,
    observed_precondition_sha256: str,
    observed_rollback_sha256: str,
) -> MutationTransactionReceipt:
    if not isinstance(plan, MutationPlan):
        raise TypeError("plan must be MutationPlan")
    precondition = _sha256(observed_precondition_sha256, "observed_precondition_sha256")
    rollback = _sha256(observed_rollback_sha256, "observed_rollback_sha256")
    preconditions_verified = precondition == plan.precondition_sha256
    rollback_available = rollback == plan.rollback_sha256
    state = (
        MutationTransactionState.PRECONDITIONS_VERIFIED
        if preconditions_verified and rollback_available
        else MutationTransactionState.BLOCKED
    )
    return MutationTransactionReceipt(
        request_id=plan.request_id,
        authority_id=plan.authority_id,
        operation_id=plan.operation_id,
        plan_sha256=plan.plan_sha256,
        precondition_sha256=precondition,
        rollback_sha256=rollback,
        state=state,
        preconditions_verified=preconditions_verified,
        rollback_available=rollback_available,
    )
