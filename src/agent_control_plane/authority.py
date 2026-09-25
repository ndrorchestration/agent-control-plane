"""Candidate typed authority envelope for future ACP contract evolution.

This module is intentionally separate from agent-control-plane.execution.v1.
It provides engineering primitives for explicit authority semantics without
changing the frozen execution-v1 measurement target.
"""

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Dict, Optional, Tuple


AUTHORITY_SCHEMA_VERSION = "agent-control-plane.authority.v0-candidate"


class AuthorityValidationError(ValueError):
    """Raised when candidate authority data is incomplete or malformed."""


def _required(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise AuthorityValidationError(f"{field_name} must not be blank")
    return value.strip()


def _nonempty_tuple(values: Tuple[str, ...], field_name: str) -> Tuple[str, ...]:
    if not isinstance(values, tuple) or not values:
        raise AuthorityValidationError(f"{field_name} must be a non-empty tuple")
    normalized = tuple(_required(value, field_name) for value in values)
    if len(set(normalized)) != len(normalized):
        raise AuthorityValidationError(f"{field_name} must not contain duplicates")
    return normalized


def _canonical_utc_timestamp(value: str, field_name: str) -> str:
    _required(value, field_name)
    candidate = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError as exc:
        raise AuthorityValidationError(f"{field_name} must be valid ISO-8601") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise AuthorityValidationError(f"{field_name} must be timezone-aware UTC")
    if parsed.utcoffset() != timedelta(0):
        raise AuthorityValidationError(f"{field_name} must use UTC")
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_utc(value: str, field_name: str) -> datetime:
    canonical = _canonical_utc_timestamp(value, field_name)
    return datetime.fromisoformat(canonical[:-1] + "+00:00")


class DecisionOutcome(str, Enum):
    ALLOW = "allow"
    DENY = "deny"
    CONDITIONAL = "conditional"


@dataclass(frozen=True)
class PrincipalIdentity:
    principal_id: str
    principal_type: str = "unspecified"

    def __post_init__(self) -> None:
        object.__setattr__(self, "principal_id", _required(self.principal_id, "principal_id"))
        object.__setattr__(self, "principal_type", _required(self.principal_type, "principal_type"))

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ResourceScope:
    resource_id: str
    resource_type: str = "unspecified"

    def __post_init__(self) -> None:
        object.__setattr__(self, "resource_id", _required(self.resource_id, "resource_id"))
        object.__setattr__(self, "resource_type", _required(self.resource_type, "resource_type"))

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class Operation:
    action: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "action", _required(self.action, "action"))

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PolicyIdentity:
    policy_id: str
    version_or_hash: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "policy_id", _required(self.policy_id, "policy_id"))
        object.__setattr__(self, "version_or_hash", _required(self.version_or_hash, "version_or_hash"))

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class DecisionRecord:
    decision_id: str
    outcome: DecisionOutcome
    reason_code: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "decision_id", _required(self.decision_id, "decision_id"))
        if not isinstance(self.outcome, DecisionOutcome):
            raise AuthorityValidationError("outcome must be DecisionOutcome")
        object.__setattr__(self, "reason_code", _required(self.reason_code, "reason_code"))

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["outcome"] = self.outcome.value
        return data


@dataclass(frozen=True)
class Delegation:
    delegator_id: str
    scope: Tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "delegator_id", _required(self.delegator_id, "delegator_id"))
        object.__setattr__(self, "scope", _nonempty_tuple(self.scope, "scope"))

    def to_dict(self) -> Dict[str, Any]:
        return {"delegator_id": self.delegator_id, "scope": list(self.scope)}


@dataclass(frozen=True)
class AuthorityEnvelope:
    authority_id: str
    principal: PrincipalIdentity
    capability: str
    resource: ResourceScope
    operation: Operation
    policy: PolicyIdentity
    decision: DecisionRecord
    expires_at: str
    conditions: Tuple[str, ...] = ()
    delegation: Optional[Delegation] = None
    schema_version: str = AUTHORITY_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "authority_id", _required(self.authority_id, "authority_id"))
        if not isinstance(self.principal, PrincipalIdentity):
            raise AuthorityValidationError("principal must be PrincipalIdentity")
        object.__setattr__(self, "capability", _required(self.capability, "capability"))
        if not isinstance(self.resource, ResourceScope):
            raise AuthorityValidationError("resource must be ResourceScope")
        if not isinstance(self.operation, Operation):
            raise AuthorityValidationError("operation must be Operation")
        if not isinstance(self.policy, PolicyIdentity):
            raise AuthorityValidationError("policy must be PolicyIdentity")
        if not isinstance(self.decision, DecisionRecord):
            raise AuthorityValidationError("decision must be DecisionRecord")
        if self.schema_version != AUTHORITY_SCHEMA_VERSION:
            raise AuthorityValidationError(f"unsupported schema_version: {self.schema_version}")
        object.__setattr__(self, "expires_at", _canonical_utc_timestamp(self.expires_at, "expires_at"))
        if not isinstance(self.conditions, tuple):
            raise AuthorityValidationError("conditions must be a tuple")
        normalized_conditions = tuple(_required(value, "conditions") for value in self.conditions)
        if len(set(normalized_conditions)) != len(normalized_conditions):
            raise AuthorityValidationError("conditions must not contain duplicates")
        object.__setattr__(self, "conditions", normalized_conditions)
        if self.delegation is not None and not isinstance(self.delegation, Delegation):
            raise AuthorityValidationError("delegation must be Delegation")
        if self.decision.outcome is DecisionOutcome.CONDITIONAL and not self.conditions:
            raise AuthorityValidationError("conditional decision requires conditions")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "authority_id": self.authority_id,
            "principal": self.principal.to_dict(),
            "capability": self.capability,
            "resource": self.resource.to_dict(),
            "operation": self.operation.to_dict(),
            "policy": self.policy.to_dict(),
            "decision": self.decision.to_dict(),
            "expires_at": self.expires_at,
            "conditions": list(self.conditions),
            "delegation": self.delegation.to_dict() if self.delegation is not None else None,
            "schema_version": self.schema_version,
        }

    def is_valid_at(self, utc_timestamp: str) -> bool:
        """Return temporal validity only; this is not a complete authorization decision."""
        observed = _parse_utc(utc_timestamp, "utc_timestamp")
        expiry = _parse_utc(self.expires_at, "expires_at")
        return observed < expiry

    def assert_valid_at(self, utc_timestamp: str) -> None:
        """Fail closed when the authority lease is expired at the supplied UTC time."""
        if not self.is_valid_at(utc_timestamp):
            raise AuthorityValidationError("authority is expired at supplied utc_timestamp")
