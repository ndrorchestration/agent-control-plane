import pytest

from agent_control_plane.context_baseline import BaselineObservation, baseline_observation_sha256
from agent_control_plane.context_comparison import (
    BLOCKED_PRESERVATION_FAILURE,
    COMPARISON_PLAN_SCHEMA,
    ELIGIBLE_FOR_BOUNDED_ADVANCEMENT,
    INCONCLUSIVE_UNOBSERVED_METRIC,
    NO_MEASURED_REDUCTION,
    ComparisonPlan,
    TreatmentObservation,
    evaluate_treatment,
)
from agent_control_plane.context_metrics import ContextTelemetry
from agent_control_plane.context_state import ContextState, EvidenceReference


def state() -> ContextState:
    return ContextState(
        task_id="task-1",
        objective="inspect exact state",
        authority_boundaries=(
            "SCIENTIFIC_N_INCREMENT=0",
            "HIGH_ASSURANCE=NOT_AUTHORIZED",
        ),
        evidence=(
            EvidenceReference(
                source="github://ndrorchestration/agent-control-plane",
                identity="abc123",
            ),
        ),
    )


def baseline(
    *,
    exposed: int | None = 10,
    acceptance: str = "accepted",
) -> BaselineObservation:
    return BaselineObservation(
        observation_id="obs-control-001",
        task_contract="bounded inspection task",
        context_state=state(),
        telemetry=ContextTelemetry(
            input_tokens=1000,
            tool_definitions_exposed=exposed,
            tools_invoked=1 if exposed else 0,
        ),
        outcome="completed",
        acceptance=acceptance,
    )


def plan(control: BaselineObservation | None = None) -> ComparisonPlan:
    return ComparisonPlan(
        plan_id="cep-compare-001",
        baseline=control or baseline(),
        treatment="capability-driven tool gating",
        primary_metric="tool_definitions_exposed",
        preservation_checks=(
            "same task contract",
            "same authority boundaries",
            "same canonical evidence references",
            "no acceptance regression",
        ),
        acceptance_rule="reduce tool exposure with no acceptance regression",
    )


def treatment(
    *,
    exposed: int | None = 1,
    context_state: ContextState | None = None,
    task_contract: str = "bounded inspection task",
    outcome: str = "completed",
    acceptance: str = "accepted",
) -> TreatmentObservation:
    return TreatmentObservation(
        task_contract=task_contract,
        context_state=context_state or state(),
        telemetry=ContextTelemetry(
            input_tokens=1000,
            tool_definitions_exposed=exposed,
            tools_invoked=1 if exposed else 0,
        ),
        outcome=outcome,
        acceptance=acceptance,
    )


def test_comparison_plan_binds_frozen_baseline_identity() -> None:
    control = baseline()
    candidate = plan(control)

    mapping = candidate.to_mapping()

    assert mapping["schema"] == COMPARISON_PLAN_SCHEMA
    assert mapping["baseline_observation_sha256"] == baseline_observation_sha256(
        control
    )
    assert mapping["task_contract"] == control.task_contract


def test_comparison_plan_rejects_empty_acceptance_rule() -> None:
    with pytest.raises(ValueError):
        ComparisonPlan(
            plan_id="cep-compare-002",
            baseline=baseline(),
            treatment="tool gating",
            primary_metric="tool_definitions_exposed",
            acceptance_rule="",
        )


def test_comparison_plan_rejects_unmodeled_primary_metric() -> None:
    with pytest.raises(ValueError, match="supported observed telemetry"):
        ComparisonPlan(
            plan_id="cep-compare-003",
            baseline=baseline(),
            treatment="tool gating",
            primary_metric="estimated_cost_dollars",
            acceptance_rule="reduce cost",
        )


def test_treatment_is_eligible_only_after_preservation_and_reduction() -> None:
    result = evaluate_treatment(plan(), treatment(exposed=1))

    assert result.status == ELIGIBLE_FOR_BOUNDED_ADVANCEMENT
    assert result.baseline_metric == 10
    assert result.treatment_metric == 1
    assert result.to_mapping()["authority_effect"] == "NONE"
    assert result.to_mapping()["scientific_n_increment"] == 0


@pytest.mark.parametrize(
    "candidate, reason",
    [
        (
            treatment(task_contract="different task"),
            "TASK_CONTRACT_DRIFT",
        ),
        (
            treatment(
                context_state=ContextState(
                    task_id="task-1",
                    objective="inspect exact state",
                    authority_boundaries=("HIGH_ASSURANCE=AUTHORIZED",),
                    evidence=state().evidence,
                )
            ),
            "AUTHORITY_BOUNDARY_DRIFT",
        ),
        (
            treatment(
                context_state=ContextState(
                    task_id="task-1",
                    objective="inspect exact state",
                    authority_boundaries=state().authority_boundaries,
                    evidence=(
                        EvidenceReference(
                            source="github://ndrorchestration/agent-control-plane",
                            identity="different",
                        ),
                    ),
                )
            ),
            "EVIDENCE_REFERENCE_DRIFT",
        ),
        (
            treatment(outcome="partial"),
            "OUTCOME_REGRESSION_OR_DRIFT",
        ),
        (
            treatment(acceptance="rejected"),
            "ACCEPTANCE_REGRESSION_OR_DRIFT",
        ),
    ],
)
def test_preservation_drift_blocks_advancement(
    candidate: TreatmentObservation,
    reason: str,
) -> None:
    result = evaluate_treatment(plan(), candidate)

    assert result.status == BLOCKED_PRESERVATION_FAILURE
    assert reason in result.reasons


def test_unobserved_primary_metric_is_inconclusive_not_success() -> None:
    control = baseline(exposed=None)
    result = evaluate_treatment(plan(control), treatment(exposed=1))

    assert result.status == INCONCLUSIVE_UNOBSERVED_METRIC
    assert result.baseline_metric is None
    assert "PRIMARY_METRIC_UNOBSERVED" in result.reasons


def test_equal_or_higher_exposure_is_not_a_reduction() -> None:
    result = evaluate_treatment(plan(), treatment(exposed=10))

    assert result.status == NO_MEASURED_REDUCTION
    assert "PRIMARY_METRIC_NOT_REDUCED" in result.reasons
