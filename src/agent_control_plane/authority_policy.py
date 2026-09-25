"""Fail-closed adapter from candidate authority envelopes to ACP policy hooks."""

from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable, Optional

from .authority import AuthorityEnvelope, AuthorityValidationError, DecisionOutcome

if TYPE_CHECKING:
    from .core import Task


AuthorityResolver = Callable[[str, "Task"], Optional[AuthorityEnvelope]]
ObservationTimeResolver = Callable[[str, "Task"], str]
ConditionEvaluator = Callable[[AuthorityEnvelope, str, "Task"], bool]
DelegationEvaluator = Callable[[AuthorityEnvelope, str, "Task"], bool]
RevocationChecker = Callable[[str, str], bool]


@dataclass(frozen=True)
class AuthorityPolicyEvaluation:
    allowed: bool
    denial_reason: Optional[str] = None
    authority_id: Optional[str] = None
    decision_id: Optional[str] = None
    policy_id: Optional[str] = None
    outcome: Optional[str] = None
    reason_code: Optional[str] = None
    observed_at: Optional[str] = None
    revocation_checked: bool = False
    delegation_checked: bool = False
    conditions_checked: bool = False


@dataclass(frozen=True)
class AuthorityPolicy:
    """Adapt a candidate authority envelope into the existing ACP policy contract.

    This adapter enforces only the subset it can prove locally: envelope presence,
    capability binding, lease validity at caller-supplied time, explicit deny, and
    explicit conditional evaluation. It does not authenticate identities, validate
    policy signatures, prove delegation legitimacy, or infer resource/operation fit.
    """

    resolver: AuthorityResolver
    observed_at: ObservationTimeResolver
    condition_evaluator: Optional[ConditionEvaluator] = None
    delegation_evaluator: Optional[DelegationEvaluator] = None
    revocation_checker: Optional[RevocationChecker] = None

    def evaluate(self, capability: str, task: "Task") -> AuthorityPolicyEvaluation:
        try:
            authority = self.resolver(capability, task)
        except Exception:
            return AuthorityPolicyEvaluation(False, "authority resolution failed")

        if authority is None:
            return AuthorityPolicyEvaluation(False, "authority missing")
        if not isinstance(authority, AuthorityEnvelope):
            return AuthorityPolicyEvaluation(False, "authority invalid")
        if authority.capability != capability:
            return AuthorityPolicyEvaluation(False, "authority capability mismatch", authority_id=authority.authority_id, decision_id=authority.decision.decision_id, policy_id=authority.policy.policy_id, outcome=authority.decision.outcome.value, reason_code=authority.decision.reason_code)

        try:
            observed_at = self.observed_at(capability, task)
            authority.assert_valid_at(observed_at)
        except AuthorityValidationError:
            return AuthorityPolicyEvaluation(False, "authority lease invalid or expired", authority_id=authority.authority_id, decision_id=authority.decision.decision_id, policy_id=authority.policy.policy_id, outcome=authority.decision.outcome.value, reason_code=authority.decision.reason_code)
        except Exception:
            return AuthorityPolicyEvaluation(False, "authority time resolution failed", authority_id=authority.authority_id, decision_id=authority.decision.decision_id, policy_id=authority.policy.policy_id, outcome=authority.decision.outcome.value, reason_code=authority.decision.reason_code)

        if self.revocation_checker is not None:
            try:
                revoked = self.revocation_checker(authority.authority_id, observed_at)
            except Exception:
                return AuthorityPolicyEvaluation(False, "authority revocation check failed", authority_id=authority.authority_id, decision_id=authority.decision.decision_id, policy_id=authority.policy.policy_id, outcome=authority.decision.outcome.value, reason_code=authority.decision.reason_code, observed_at=observed_at, revocation_checked=True)
            if revoked is not False:
                return AuthorityPolicyEvaluation(False, "authority revoked", authority_id=authority.authority_id, decision_id=authority.decision.decision_id, policy_id=authority.policy.policy_id, outcome=authority.decision.outcome.value, reason_code=authority.decision.reason_code, observed_at=observed_at, revocation_checked=True)

        if authority.delegation is not None:
            if self.delegation_evaluator is None:
                return AuthorityPolicyEvaluation(False, "authority delegation unresolved", authority_id=authority.authority_id, decision_id=authority.decision.decision_id, policy_id=authority.policy.policy_id, outcome=authority.decision.outcome.value, reason_code=authority.decision.reason_code, observed_at=observed_at, revocation_checked=self.revocation_checker is not None)
            try:
                delegation_valid = self.delegation_evaluator(authority, capability, task)
            except Exception:
                return AuthorityPolicyEvaluation(False, "authority delegation evaluation failed", authority_id=authority.authority_id, decision_id=authority.decision.decision_id, policy_id=authority.policy.policy_id, outcome=authority.decision.outcome.value, reason_code=authority.decision.reason_code, observed_at=observed_at, revocation_checked=self.revocation_checker is not None, delegation_checked=True)
            if delegation_valid is not True:
                return AuthorityPolicyEvaluation(False, "authority delegation invalid", authority_id=authority.authority_id, decision_id=authority.decision.decision_id, policy_id=authority.policy.policy_id, outcome=authority.decision.outcome.value, reason_code=authority.decision.reason_code, observed_at=observed_at, revocation_checked=self.revocation_checker is not None, delegation_checked=True)

        outcome = authority.decision.outcome
        if outcome is DecisionOutcome.DENY:
            return AuthorityPolicyEvaluation(False, f"authority denied:{authority.decision.reason_code}", authority_id=authority.authority_id, decision_id=authority.decision.decision_id, policy_id=authority.policy.policy_id, outcome=authority.decision.outcome.value, reason_code=authority.decision.reason_code, observed_at=observed_at, revocation_checked=self.revocation_checker is not None, delegation_checked=authority.delegation is not None)

        if outcome is DecisionOutcome.CONDITIONAL:
            if self.condition_evaluator is None:
                return AuthorityPolicyEvaluation(False, "authority conditions unresolved", authority_id=authority.authority_id, decision_id=authority.decision.decision_id, policy_id=authority.policy.policy_id, outcome=authority.decision.outcome.value, reason_code=authority.decision.reason_code, observed_at=observed_at, revocation_checked=self.revocation_checker is not None, delegation_checked=authority.delegation is not None)
            try:
                satisfied = self.condition_evaluator(authority, capability, task)
            except Exception:
                return AuthorityPolicyEvaluation(False, "authority condition evaluation failed", authority_id=authority.authority_id, decision_id=authority.decision.decision_id, policy_id=authority.policy.policy_id, outcome=authority.decision.outcome.value, reason_code=authority.decision.reason_code, observed_at=observed_at, revocation_checked=self.revocation_checker is not None, delegation_checked=authority.delegation is not None, conditions_checked=True)
            if satisfied is not True:
                return AuthorityPolicyEvaluation(False, "authority conditions unsatisfied", authority_id=authority.authority_id, decision_id=authority.decision.decision_id, policy_id=authority.policy.policy_id, outcome=authority.decision.outcome.value, reason_code=authority.decision.reason_code, observed_at=observed_at, revocation_checked=self.revocation_checker is not None, delegation_checked=authority.delegation is not None, conditions_checked=True)

        return AuthorityPolicyEvaluation(True, authority_id=authority.authority_id, decision_id=authority.decision.decision_id, policy_id=authority.policy.policy_id, outcome=authority.decision.outcome.value, reason_code=authority.decision.reason_code, observed_at=observed_at, revocation_checked=self.revocation_checker is not None, delegation_checked=authority.delegation is not None, conditions_checked=authority.decision.outcome is DecisionOutcome.CONDITIONAL)


    def __call__(self, capability: str, task: "Task") -> Optional[str]:
        return self.evaluate(capability, task).denial_reason
