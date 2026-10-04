"""Frozen-control comparison plans for Context Efficiency Plane experiments."""

from __future__ import annotations

from dataclasses import dataclass, field

from .context_baseline import BaselineObservation, baseline_observation_sha256


COMPARISON_PLAN_SCHEMA = "agent-control-plane.context-comparison-plan.v0-candidate"


def _non_empty(value: str, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value


@dataclass(frozen=True)
class ComparisonPlan:
    """Preregister a treatment against an immutable baseline observation identity."""

    plan_id: str
    baseline: BaselineObservation
    treatment: str
    primary_metric: str
    preservation_checks: tuple[str, ...] = field(default_factory=tuple)
    acceptance_rule: str = ""

    def __post_init__(self) -> None:
        _non_empty(self.plan_id, "plan_id")
        if not isinstance(self.baseline, BaselineObservation):
            raise TypeError("baseline must be BaselineObservation")
        _non_empty(self.treatment, "treatment")
        _non_empty(self.primary_metric, "primary_metric")
        _non_empty(self.acceptance_rule, "acceptance_rule")
        if not isinstance(self.preservation_checks, tuple):
            raise TypeError("preservation_checks must be a tuple")
        if any(not isinstance(item, str) or not item.strip() for item in self.preservation_checks):
            raise ValueError("preservation_checks must contain non-empty strings")

    def to_mapping(self) -> dict[str, object]:
        return {
            "schema": COMPARISON_PLAN_SCHEMA,
            "plan_id": self.plan_id,
            "baseline_observation_sha256": baseline_observation_sha256(self.baseline),
            "baseline_observation_id": self.baseline.observation_id,
            "task_contract": self.baseline.task_contract,
            "treatment": self.treatment,
            "primary_metric": self.primary_metric,
            "preservation_checks": list(self.preservation_checks),
            "acceptance_rule": self.acceptance_rule,
        }
