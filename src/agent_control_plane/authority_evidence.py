"""Additive authority-decision evidence sidecar for ACP policy evaluations."""

from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING, Dict

from .authority_policy import AuthorityPolicy, AuthorityPolicyEvaluation

if TYPE_CHECKING:
    from .core import Task


@dataclass(frozen=True)
class AuthorityDecisionEvidence:
    task_id: str
    run_id: str
    capability: str
    allowed: bool
    denial_reason: str | None
    authority_id: str | None
    decision_id: str | None
    policy_id: str | None
    outcome: str | None
    reason_code: str | None
    observed_at: str | None
    revocation_checked: bool
    delegation_checked: bool
    conditions_checked: bool
    schema: str = "agent-control-plane.authority-decision-evidence.v0-candidate"

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


class EvidenceAuthorityPolicy:
    """Policy wrapper that records one structured decision evidence record per task."""

    def __init__(self, policy: AuthorityPolicy, *, run_id: str) -> None:
        if not isinstance(policy, AuthorityPolicy):
            raise TypeError("policy must be AuthorityPolicy")
        if not isinstance(run_id, str) or not run_id.strip():
            raise ValueError("run_id must not be blank")
        self.policy = policy
        self.run_id = run_id.strip()
        self._records: Dict[str, AuthorityDecisionEvidence] = {}

    def __call__(self, capability: str, task: "Task") -> str | None:
        evaluation = self.policy.evaluate(capability, task)
        self._records[task.id] = self._evidence(capability, task.id, evaluation)
        return evaluation.denial_reason

    def _evidence(self, capability: str, task_id: str, evaluation: AuthorityPolicyEvaluation) -> AuthorityDecisionEvidence:
        return AuthorityDecisionEvidence(
            task_id=task_id,
            run_id=self.run_id,
            capability=capability,
            allowed=evaluation.allowed,
            denial_reason=evaluation.denial_reason,
            authority_id=evaluation.authority_id,
            decision_id=evaluation.decision_id,
            policy_id=evaluation.policy_id,
            outcome=evaluation.outcome,
            reason_code=evaluation.reason_code,
            observed_at=evaluation.observed_at,
            revocation_checked=evaluation.revocation_checked,
            delegation_checked=evaluation.delegation_checked,
            conditions_checked=evaluation.conditions_checked,
        )

    def get(self, task_id: str) -> AuthorityDecisionEvidence | None:
        return self._records.get(task_id)

    def manifest(self) -> dict[str, object]:
        records = [self._records[key].to_dict() for key in sorted(self._records)]
        return {
            "schema": "agent-control-plane.authority-decision-evidence.v0-candidate",
            "run_id": self.run_id,
            "record_count": len(records),
            "records": records,
        }
