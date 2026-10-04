"""Frozen-control comparison plans and fail-closed treatment evaluation for CEP."""

from __future__ import annotations

from dataclasses import dataclass, field

from .context_baseline import BaselineObservation, baseline_observation_sha256
from .context_metrics import ContextTelemetry
from .context_state import ContextState


COMPARISON_PLAN_SCHEMA = "agent-control-plane.context-comparison-plan.v0-candidate"
COMPARISON_RESULT_SCHEMA = "agent-control-plane.context-comparison-result.v0-candidate"

ELIGIBLE_FOR_BOUNDED_ADVANCEMENT = "ELIGIBLE_FOR_BOUNDED_ADVANCEMENT"
BLOCKED_PRESERVATION_FAILURE = "BLOCKED_PRESERVATION_FAILURE"
INCONCLUSIVE_UNOBSERVED_METRIC = "INCONCLUSIVE_UNOBSERVED_METRIC"
NO_MEASURED_REDUCTION = "NO_MEASURED_REDUCTION"

_SUPPORTED_METRICS = frozenset(
    {
        "input_tokens",
        "output_tokens",
        "tool_result_tokens",
        "tool_definitions_exposed",
        "tools_invoked",
        "retrieved_tokens",
        "used_retrieved_tokens",
        "retrieved_items",
        "cacheable_prefix_tokens",
        "novel_prefix_tokens",
        "decision_relevant_input_tokens",
    }
)


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
        if self.primary_metric not in _SUPPORTED_METRICS:
            raise ValueError("primary_metric is not a supported observed telemetry field")
        _non_empty(self.acceptance_rule, "acceptance_rule")
        if not isinstance(self.preservation_checks, tuple):
            raise TypeError("preservation_checks must be a tuple")
        if any(
            not isinstance(item, str) or not item.strip()
            for item in self.preservation_checks
        ):
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


@dataclass(frozen=True)
class TreatmentObservation:
    """One treatment observation evaluated against a frozen comparison plan."""

    task_contract: str
    context_state: ContextState
    telemetry: ContextTelemetry
    outcome: str
    acceptance: str

    def __post_init__(self) -> None:
        _non_empty(self.task_contract, "task_contract")
        if not isinstance(self.context_state, ContextState):
            raise TypeError("context_state must be ContextState")
        if not isinstance(self.telemetry, ContextTelemetry):
            raise TypeError("telemetry must be ContextTelemetry")
        _non_empty(self.outcome, "outcome")
        _non_empty(self.acceptance, "acceptance")


@dataclass(frozen=True)
class ComparisonResult:
    """Fail-closed result for one treatment-vs-control comparison."""

    plan_id: str
    baseline_observation_sha256: str
    status: str
    reasons: tuple[str, ...]
    primary_metric: str
    baseline_metric: int | None
    treatment_metric: int | None

    def to_mapping(self) -> dict[str, object]:
        return {
            "schema": COMPARISON_RESULT_SCHEMA,
            "plan_id": self.plan_id,
            "baseline_observation_sha256": self.baseline_observation_sha256,
            "status": self.status,
            "reasons": list(self.reasons),
            "primary_metric": self.primary_metric,
            "baseline_metric": self.baseline_metric,
            "treatment_metric": self.treatment_metric,
            "evaluation_scope": "BOUNDED_CONTEXT_COST_PRESERVATION_ONLY",
            "authority_effect": "NONE",
            "scientific_n_increment": 0,
            "efficacy_effect": "NONE",
            "independent_validation_effect": "NONE",
            "high_assurance_effect": "NONE",
        }


def _observed_metric(telemetry: ContextTelemetry, metric: str) -> int | None:
    if metric not in _SUPPORTED_METRICS:
        raise ValueError("unsupported primary metric")
    value = getattr(telemetry, metric)
    if value is not None and (isinstance(value, bool) or not isinstance(value, int)):
        raise TypeError("observed primary metric must be an integer or None")
    return value


def evaluate_treatment(
    plan: ComparisonPlan,
    treatment: TreatmentObservation,
) -> ComparisonResult:
    """Evaluate a candidate without inferring missing measurements or authority."""

    if not isinstance(plan, ComparisonPlan):
        raise TypeError("plan must be ComparisonPlan")
    if not isinstance(treatment, TreatmentObservation):
        raise TypeError("treatment must be TreatmentObservation")

    baseline = plan.baseline
    reasons: list[str] = []

    if treatment.task_contract != baseline.task_contract:
        reasons.append("TASK_CONTRACT_DRIFT")
    if treatment.context_state.task_id != baseline.context_state.task_id:
        reasons.append("TASK_ID_DRIFT")
    if treatment.context_state.objective != baseline.context_state.objective:
        reasons.append("OBJECTIVE_DRIFT")
    if (
        treatment.context_state.authority_boundaries
        != baseline.context_state.authority_boundaries
    ):
        reasons.append("AUTHORITY_BOUNDARY_DRIFT")
    if treatment.context_state.evidence != baseline.context_state.evidence:
        reasons.append("EVIDENCE_REFERENCE_DRIFT")
    if treatment.outcome != baseline.outcome:
        reasons.append("OUTCOME_REGRESSION_OR_DRIFT")
    if treatment.acceptance != baseline.acceptance:
        reasons.append("ACCEPTANCE_REGRESSION_OR_DRIFT")

    baseline_metric = _observed_metric(baseline.telemetry, plan.primary_metric)
    treatment_metric = _observed_metric(treatment.telemetry, plan.primary_metric)

    if reasons:
        status = BLOCKED_PRESERVATION_FAILURE
    elif baseline_metric is None or treatment_metric is None:
        status = INCONCLUSIVE_UNOBSERVED_METRIC
        reasons.append("PRIMARY_METRIC_UNOBSERVED")
    elif treatment_metric >= baseline_metric:
        status = NO_MEASURED_REDUCTION
        reasons.append("PRIMARY_METRIC_NOT_REDUCED")
    else:
        status = ELIGIBLE_FOR_BOUNDED_ADVANCEMENT
        reasons.append("PRESERVATION_CHECKS_PASS_AND_PRIMARY_METRIC_REDUCED")

    return ComparisonResult(
        plan_id=plan.plan_id,
        baseline_observation_sha256=baseline_observation_sha256(baseline),
        status=status,
        reasons=tuple(reasons),
        primary_metric=plan.primary_metric,
        baseline_metric=baseline_metric,
        treatment_metric=treatment_metric,
    )
