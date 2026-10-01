"""Framework-neutral, non-executing action-admission core.

This module evaluates whether a declared action intent is congruent with a
supplied authority envelope at a caller-supplied observation time. It never
executes, enqueues, retries, or mutates the requested action.

The module deliberately does not depend on ACP Task or ControlPlane types.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Callable, Optional

from .authority import AuthorityEnvelope, AuthorityValidationError, DecisionOutcome

ACTION_ADMISSION_SCHEMA_VERSION = "agent-control-plane.action-admission.v0-candidate"

RevocationChecker = Callable[[str, str], bool]
DelegationEvaluator = Callable[[AuthorityEnvelope, "ActionIntent"], bool]
ConditionEvaluator = Callable[[AuthorityEnvelope, "ActionIntent"], bool]
StateFreshnessChecker = Callable[[AuthorityEnvelope, str], Optional[str]]


def _required(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must not be blank")
    return value.strip()


class AdmissionReason(str, Enum):
    AUTHORITY_MISSING_OR_INVALID = "AUTHORITY_MISSING_OR_INVALID"
    PRINCIPAL_MISMATCH = "PRINCIPAL_MISMATCH"
    CAPABILITY_MISMATCH = "CAPABILITY_MISMATCH"
    RESOURCE_MISMATCH = "RESOURCE_MISMATCH"
    OPERATION_MISMATCH = "OPERATION_MISMATCH"
    LEASE_INVALID_OR_EXPIRED = "LEASE_INVALID_OR_EXPIRED"
    STATE_CHECK_FAILED = "STATE_CHECK_FAILED"
    STATE_STALE = "STATE_STALE"
    REVOCATION_CHECK_FAILED = "REVOCATION_CHECK_FAILED"
    AUTHORITY_REVOKED = "AUTHORITY_REVOKED"
    DELEGATION_SCOPE_MISMATCH = "DELEGATION_SCOPE_MISMATCH"
    DELEGATION_UNRESOLVED = "DELEGATION_UNRESOLVED"
    DELEGATION_INVALID = "DELEGATION_INVALID"
    CONDITIONS_UNRESOLVED = "CONDITIONS_UNRESOLVED"
    CONDITIONS_UNSATISFIED = "CONDITIONS_UNSATISFIED"
    OUTCOME_NOT_ALLOW = "OUTCOME_NOT_ALLOW"
    ADMITTED = "ADMITTED"


@dataclass(frozen=True)
class ActionIntent:
    intent_id: str
    principal_id: str
    capability: str
    resource_id: str
    resource_type: str
    operation: str
    side_effect_class: Optional[str] = None
    context_id: Optional[str] = None

    def __post_init__(self) -> None:
        for field_name in (
            "intent_id",
            "principal_id",
            "capability",
            "resource_id",
            "resource_type",
            "operation",
        ):
            object.__setattr__(self, field_name, _required(getattr(self, field_name), field_name))
        if self.side_effect_class is not None:
            object.__setattr__(
                self,
                "side_effect_class",
                _required(self.side_effect_class, "side_effect_class"),
            )
        if self.context_id is not None:
            object.__setattr__(self, "context_id", _required(self.context_id, "context_id"))


@dataclass(frozen=True)
class AdmissionReceipt:
    admitted: bool
    reason_code: AdmissionReason
    intent_id: str
    authority_id: Optional[str]
    decision_id: Optional[str]
    policy_id: Optional[str]
    observed_at: Optional[str]
    principal_checked: bool
    capability_checked: bool
    resource_checked: bool
    operation_checked: bool
    lease_checked: bool
    revocation_checked: bool
    delegation_checked: bool
    conditions_checked: bool
    state_checked: bool
    state_reason: Optional[str] = None
    execution_enabled: bool = False
    schema_version: str = ACTION_ADMISSION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.execution_enabled is not False:
            raise ValueError("action admission never enables execution")
        if not isinstance(self.reason_code, AdmissionReason):
            raise ValueError("reason_code must be AdmissionReason")


def _receipt(
    intent: ActionIntent,
    authority: Optional[AuthorityEnvelope],
    *,
    admitted: bool,
    reason_code: AdmissionReason,
    observed_at: Optional[str] = None,
    principal_checked: bool = False,
    capability_checked: bool = False,
    resource_checked: bool = False,
    operation_checked: bool = False,
    lease_checked: bool = False,
    revocation_checked: bool = False,
    delegation_checked: bool = False,
    conditions_checked: bool = False,
    state_checked: bool = False,
    state_reason: Optional[str] = None,
) -> AdmissionReceipt:
    valid_authority = authority if isinstance(authority, AuthorityEnvelope) else None
    return AdmissionReceipt(
        admitted=admitted,
        reason_code=reason_code,
        intent_id=intent.intent_id,
        authority_id=valid_authority.authority_id if valid_authority is not None else None,
        decision_id=(
            valid_authority.decision.decision_id if valid_authority is not None else None
        ),
        policy_id=valid_authority.policy.policy_id if valid_authority is not None else None,
        observed_at=observed_at,
        principal_checked=principal_checked,
        capability_checked=capability_checked,
        resource_checked=resource_checked,
        operation_checked=operation_checked,
        lease_checked=lease_checked,
        revocation_checked=revocation_checked,
        delegation_checked=delegation_checked,
        conditions_checked=conditions_checked,
        state_checked=state_checked,
        state_reason=state_reason,
    )


def assess_action_intent(
    intent: ActionIntent,
    authority: Optional[AuthorityEnvelope],
    *,
    observed_at: str,
    revocation_checker: RevocationChecker,
    delegation_evaluator: Optional[DelegationEvaluator] = None,
    condition_evaluator: Optional[ConditionEvaluator] = None,
    state_freshness_checker: Optional[StateFreshnessChecker] = None,
) -> AdmissionReceipt:
    """Assess an intent against supplied authority without executing the action."""

    if not isinstance(intent, ActionIntent):
        raise TypeError("intent must be ActionIntent")
    if not callable(revocation_checker):
        raise TypeError("revocation_checker must be callable")
    if not isinstance(authority, AuthorityEnvelope):
        return _receipt(
            intent,
            None,
            admitted=False,
            reason_code=AdmissionReason.AUTHORITY_MISSING_OR_INVALID,
        )

    if authority.principal.principal_id != intent.principal_id:
        return _receipt(
            intent,
            authority,
            admitted=False,
            reason_code=AdmissionReason.PRINCIPAL_MISMATCH,
            principal_checked=True,
        )

    if authority.capability != intent.capability:
        return _receipt(
            intent,
            authority,
            admitted=False,
            reason_code=AdmissionReason.CAPABILITY_MISMATCH,
            principal_checked=True,
            capability_checked=True,
        )

    if (
        authority.resource.resource_id != intent.resource_id
        or authority.resource.resource_type != intent.resource_type
    ):
        return _receipt(
            intent,
            authority,
            admitted=False,
            reason_code=AdmissionReason.RESOURCE_MISMATCH,
            principal_checked=True,
            capability_checked=True,
            resource_checked=True,
        )

    if authority.operation.action != intent.operation:
        return _receipt(
            intent,
            authority,
            admitted=False,
            reason_code=AdmissionReason.OPERATION_MISMATCH,
            principal_checked=True,
            capability_checked=True,
            resource_checked=True,
            operation_checked=True,
        )

    try:
        authority.assert_valid_at(observed_at)
    except (AuthorityValidationError, ValueError, TypeError):
        return _receipt(
            intent,
            authority,
            admitted=False,
            reason_code=AdmissionReason.LEASE_INVALID_OR_EXPIRED,
            principal_checked=True,
            capability_checked=True,
            resource_checked=True,
            operation_checked=True,
            lease_checked=True,
        )

    common = dict(
        observed_at=observed_at,
        principal_checked=True,
        capability_checked=True,
        resource_checked=True,
        operation_checked=True,
        lease_checked=True,
    )

    state_checked = False
    state_reason = None
    if state_freshness_checker is not None:
        state_checked = True
        try:
            state_reason = state_freshness_checker(authority, observed_at)
        except Exception:
            return _receipt(
                intent,
                authority,
                admitted=False,
                reason_code=AdmissionReason.STATE_CHECK_FAILED,
                state_checked=True,
                state_reason="checker_error",
                **common,
            )
        if state_reason is not None:
            return _receipt(
                intent,
                authority,
                admitted=False,
                reason_code=AdmissionReason.STATE_STALE,
                state_checked=True,
                state_reason=state_reason,
                **common,
            )

    try:
        revoked = revocation_checker(authority.authority_id, observed_at)
    except Exception:
        return _receipt(
            intent,
            authority,
            admitted=False,
            reason_code=AdmissionReason.REVOCATION_CHECK_FAILED,
            revocation_checked=True,
            state_checked=state_checked,
            state_reason=state_reason,
            **common,
        )
    if revoked is not False:
        return _receipt(
            intent,
            authority,
            admitted=False,
            reason_code=AdmissionReason.AUTHORITY_REVOKED,
            revocation_checked=True,
            state_checked=state_checked,
            state_reason=state_reason,
            **common,
        )

    delegation_checked = False
    if authority.delegation is not None:
        delegation_checked = True
        if intent.operation not in authority.delegation.scope:
            return _receipt(
                intent,
                authority,
                admitted=False,
                reason_code=AdmissionReason.DELEGATION_SCOPE_MISMATCH,
                revocation_checked=True,
                delegation_checked=True,
                state_checked=state_checked,
                state_reason=state_reason,
                **common,
            )
        if delegation_evaluator is None:
            return _receipt(
                intent,
                authority,
                admitted=False,
                reason_code=AdmissionReason.DELEGATION_UNRESOLVED,
                revocation_checked=True,
                delegation_checked=True,
                state_checked=state_checked,
                state_reason=state_reason,
                **common,
            )
        try:
            delegation_valid = delegation_evaluator(authority, intent)
        except Exception:
            delegation_valid = False
        if delegation_valid is not True:
            return _receipt(
                intent,
                authority,
                admitted=False,
                reason_code=AdmissionReason.DELEGATION_INVALID,
                revocation_checked=True,
                delegation_checked=True,
                state_checked=state_checked,
                state_reason=state_reason,
                **common,
            )

    conditions_checked = False
    if authority.conditions or authority.decision.outcome is DecisionOutcome.CONDITIONAL:
        conditions_checked = True
        if condition_evaluator is None:
            return _receipt(
                intent,
                authority,
                admitted=False,
                reason_code=AdmissionReason.CONDITIONS_UNRESOLVED,
                revocation_checked=True,
                delegation_checked=delegation_checked,
                conditions_checked=True,
                state_checked=state_checked,
                state_reason=state_reason,
                **common,
            )
        try:
            conditions_satisfied = condition_evaluator(authority, intent)
        except Exception:
            conditions_satisfied = False
        if conditions_satisfied is not True:
            return _receipt(
                intent,
                authority,
                admitted=False,
                reason_code=AdmissionReason.CONDITIONS_UNSATISFIED,
                revocation_checked=True,
                delegation_checked=delegation_checked,
                conditions_checked=True,
                state_checked=state_checked,
                state_reason=state_reason,
                **common,
            )

    if authority.decision.outcome not in (DecisionOutcome.ALLOW, DecisionOutcome.CONDITIONAL):
        return _receipt(
            intent,
            authority,
            admitted=False,
            reason_code=AdmissionReason.OUTCOME_NOT_ALLOW,
            revocation_checked=True,
            delegation_checked=delegation_checked,
            conditions_checked=conditions_checked,
            state_checked=state_checked,
            state_reason=state_reason,
            **common,
        )

    return _receipt(
        intent,
        authority,
        admitted=True,
        reason_code=AdmissionReason.ADMITTED,
        revocation_checked=True,
        delegation_checked=delegation_checked,
        conditions_checked=conditions_checked,
        state_checked=state_checked,
        state_reason=state_reason,
        **common,
    )
