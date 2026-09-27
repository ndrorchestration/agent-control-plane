"""Fail-closed, non-executing admission for future remote mutation intents.

This module deliberately stops before execution. It answers only whether an
explicit mutation intent is congruent with a supplied ACP authority envelope at
the stated observation time.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

from .authority import AuthorityEnvelope, AuthorityValidationError, DecisionOutcome

REMOTE_MUTATION_ADMISSION_SCHEMA_VERSION = "agent-control-plane.remote-mutation-admission.v0-candidate"
REMOTE_MUTATION_CAPABILITY = "remote.mutation"
REMOTE_MUTATION_SIDE_EFFECT_CLASS = "MUTATING"

RevocationChecker = Callable[[str, str], bool]
DelegationEvaluator = Callable[[AuthorityEnvelope, "RemoteMutationIntent"], bool]


def _required(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must not be blank")
    return value.strip()


@dataclass(frozen=True)
class RemoteMutationIntent:
    request_id: str
    principal_id: str
    device_id: str
    resource_id: str
    resource_type: str
    operation_id: str
    capability: str = REMOTE_MUTATION_CAPABILITY
    expected_side_effect_class: str = REMOTE_MUTATION_SIDE_EFFECT_CLASS

    def __post_init__(self) -> None:
        for field_name in (
            "request_id",
            "principal_id",
            "device_id",
            "resource_id",
            "resource_type",
            "operation_id",
            "capability",
            "expected_side_effect_class",
        ):
            object.__setattr__(self, field_name, _required(getattr(self, field_name), field_name))
        if self.capability != REMOTE_MUTATION_CAPABILITY:
            raise ValueError("remote mutation intent must use remote.mutation capability")
        if self.expected_side_effect_class != REMOTE_MUTATION_SIDE_EFFECT_CLASS:
            raise ValueError("remote mutation intent must declare MUTATING side-effect class")


@dataclass(frozen=True)
class RemoteMutationAdmissionRecord:
    admitted: bool
    reason: str
    request_id: str
    authority_id: Optional[str]
    decision_id: Optional[str]
    policy_id: Optional[str]
    principal_checked: bool
    capability_checked: bool
    resource_checked: bool
    operation_checked: bool
    lease_checked: bool
    revocation_checked: bool
    delegation_checked: bool
    execution_enabled: bool = False
    schema_version: str = REMOTE_MUTATION_ADMISSION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.execution_enabled is not False:
            raise ValueError("remote mutation execution is not enabled by admission record")


def _record(intent: RemoteMutationIntent, authority: Optional[AuthorityEnvelope], *, admitted: bool, reason: str,
            principal_checked: bool = False, capability_checked: bool = False, resource_checked: bool = False,
            operation_checked: bool = False, lease_checked: bool = False, revocation_checked: bool = False,
            delegation_checked: bool = False) -> RemoteMutationAdmissionRecord:
    return RemoteMutationAdmissionRecord(
        admitted=admitted,
        reason=reason,
        request_id=intent.request_id,
        authority_id=authority.authority_id if isinstance(authority, AuthorityEnvelope) else None,
        decision_id=authority.decision.decision_id if isinstance(authority, AuthorityEnvelope) else None,
        policy_id=authority.policy.policy_id if isinstance(authority, AuthorityEnvelope) else None,
        principal_checked=principal_checked,
        capability_checked=capability_checked,
        resource_checked=resource_checked,
        operation_checked=operation_checked,
        lease_checked=lease_checked,
        revocation_checked=revocation_checked,
        delegation_checked=delegation_checked,
    )


def assess_remote_mutation_intent(
    intent: RemoteMutationIntent,
    authority: Optional[AuthorityEnvelope],
    *,
    observed_at: str,
    revocation_checker: RevocationChecker,
    delegation_evaluator: Optional[DelegationEvaluator] = None,
) -> RemoteMutationAdmissionRecord:
    """Assess exact authority congruence without enabling or performing mutation."""
    if not isinstance(intent, RemoteMutationIntent):
        raise TypeError("intent must be RemoteMutationIntent")
    if not isinstance(authority, AuthorityEnvelope):
        return _record(intent, None, admitted=False, reason="authority missing or invalid")

    if authority.principal.principal_id != intent.principal_id:
        return _record(intent, authority, admitted=False, reason="principal mismatch", principal_checked=True)
    if authority.capability != intent.capability:
        return _record(
            intent, authority, admitted=False, reason="capability mismatch",
            principal_checked=True, capability_checked=True,
        )
    if authority.resource.resource_id != intent.resource_id or authority.resource.resource_type != intent.resource_type:
        return _record(
            intent, authority, admitted=False, reason="resource mismatch",
            principal_checked=True, capability_checked=True, resource_checked=True,
        )
    if authority.operation.action != intent.operation_id:
        return _record(
            intent, authority, admitted=False, reason="operation mismatch",
            principal_checked=True, capability_checked=True, resource_checked=True, operation_checked=True,
        )

    try:
        authority.assert_valid_at(observed_at)
    except (AuthorityValidationError, ValueError):
        return _record(
            intent, authority, admitted=False, reason="authority lease invalid or expired",
            principal_checked=True, capability_checked=True, resource_checked=True, operation_checked=True,
            lease_checked=True,
        )

    try:
        revoked = revocation_checker(authority.authority_id, observed_at)
    except Exception:
        return _record(
            intent, authority, admitted=False, reason="revocation check failed",
            principal_checked=True, capability_checked=True, resource_checked=True, operation_checked=True,
            lease_checked=True, revocation_checked=True,
        )
    if revoked is not False:
        return _record(
            intent, authority, admitted=False, reason="authority revoked",
            principal_checked=True, capability_checked=True, resource_checked=True, operation_checked=True,
            lease_checked=True, revocation_checked=True,
        )

    delegation_checked = False
    if authority.delegation is not None:
        delegation_checked = True
        if intent.operation_id not in authority.delegation.scope:
            return _record(
                intent, authority, admitted=False, reason="delegation scope mismatch",
                principal_checked=True, capability_checked=True, resource_checked=True, operation_checked=True,
                lease_checked=True, revocation_checked=True, delegation_checked=True,
            )
        if delegation_evaluator is None:
            return _record(
                intent, authority, admitted=False, reason="delegation unresolved",
                principal_checked=True, capability_checked=True, resource_checked=True, operation_checked=True,
                lease_checked=True, revocation_checked=True, delegation_checked=True,
            )
        try:
            delegation_valid = delegation_evaluator(authority, intent)
        except Exception:
            delegation_valid = False
        if delegation_valid is not True:
            return _record(
                intent, authority, admitted=False, reason="delegation invalid",
                principal_checked=True, capability_checked=True, resource_checked=True, operation_checked=True,
                lease_checked=True, revocation_checked=True, delegation_checked=True,
            )

    if authority.conditions:
        return _record(
            intent, authority, admitted=False, reason="conditional mutation authority unresolved",
            principal_checked=True, capability_checked=True, resource_checked=True, operation_checked=True,
            lease_checked=True, revocation_checked=True, delegation_checked=delegation_checked,
        )
    if authority.decision.outcome is not DecisionOutcome.ALLOW:
        return _record(
            intent, authority, admitted=False, reason=f"authority outcome not allow:{authority.decision.outcome.value}",
            principal_checked=True, capability_checked=True, resource_checked=True, operation_checked=True,
            lease_checked=True, revocation_checked=True, delegation_checked=delegation_checked,
        )

    return _record(
        intent, authority, admitted=True, reason="authority bindings satisfied; mutation execution remains disabled",
        principal_checked=True, capability_checked=True, resource_checked=True, operation_checked=True,
        lease_checked=True, revocation_checked=True, delegation_checked=delegation_checked,
    )
