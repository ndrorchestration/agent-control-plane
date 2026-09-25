"""Fail-closed adapter from candidate authority envelopes to ACP policy hooks."""

from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable, Optional

from .authority import AuthorityEnvelope, AuthorityValidationError, DecisionOutcome

if TYPE_CHECKING:
    from .core import Task


AuthorityResolver = Callable[[str, "Task"], Optional[AuthorityEnvelope]]
ObservationTimeResolver = Callable[[str, "Task"], str]
ConditionEvaluator = Callable[[AuthorityEnvelope, str, "Task"], bool]


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

    def __call__(self, capability: str, task: "Task") -> Optional[str]:
        try:
            authority = self.resolver(capability, task)
        except Exception:
            return "authority resolution failed"

        if authority is None:
            return "authority missing"
        if not isinstance(authority, AuthorityEnvelope):
            return "authority invalid"
        if authority.capability != capability:
            return "authority capability mismatch"

        try:
            observed_at = self.observed_at(capability, task)
            authority.assert_valid_at(observed_at)
        except AuthorityValidationError:
            return "authority lease invalid or expired"
        except Exception:
            return "authority time resolution failed"

        outcome = authority.decision.outcome
        if outcome is DecisionOutcome.DENY:
            return f"authority denied:{authority.decision.reason_code}"

        if outcome is DecisionOutcome.CONDITIONAL:
            if self.condition_evaluator is None:
                return "authority conditions unresolved"
            try:
                satisfied = self.condition_evaluator(authority, capability, task)
            except Exception:
                return "authority condition evaluation failed"
            if satisfied is not True:
                return "authority conditions unsatisfied"

        return None
