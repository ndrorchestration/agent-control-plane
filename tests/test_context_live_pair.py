import pytest

from agent_control_plane.context_baseline import BaselineObservation
from agent_control_plane.context_live_pair import (
    MEASUREMENT_BLOCKED,
    PairedTaskObservation,
    evaluate_paired_task,
)
from agent_control_plane.context_metrics import ContextTelemetry
from agent_control_plane.context_state import ContextState, EvidenceReference


def state() -> ContextState:
    return ContextState(
        task_id="workflow-status-001",
        objective="inspect exact-head workflow status",
        authority_boundaries=(
            "SCIENTIFIC_N_INCREMENT=0",
            "INDEPENDENT_VALIDATION=NOT_ESTABLISHED",
            "CANONICAL_DGAF_EFFICACY=NOT_ESTABLISHED",
            "HIGH_ASSURANCE=NOT_AUTHORIZED",
            "AUTOMATIC_CONTEXT_GATING=NOT_ENABLED",
        ),
        evidence=(
            EvidenceReference(
                source="github://ndrorchestration/agent-control-plane",
                identity="exact-head-abc",
            ),
        ),
    )


def observation(
    observation_id: str,
    *,
    input_tokens: int | None,
    exposed: int,
    acceptance: str = "accepted",
) -> BaselineObservation:
    return BaselineObservation(
        observation_id=observation_id,
        task_contract="report exact-head workflow status",
        context_state=state(),
        telemetry=ContextTelemetry(
            input_tokens=input_tokens,
            tool_definitions_exposed=exposed,
            tools_invoked=1,
        ),
        outcome="completed",
        acceptance=acceptance,
    )


def pair(
    *,
    control_tokens: int | None = 40000,
    treatment_tokens: int | None = 8000,
    treatment_acceptance: str = "accepted",
) -> PairedTaskObservation:
    return PairedTaskObservation(
        pair_id="pair-001",
        model_identity="model-family/version",
        config_identity="temperature=0;tools=preselected",
        control=observation("control-001", input_tokens=control_tokens, exposed=89),
        treatment=observation(
            "treatment-001",
            input_tokens=treatment_tokens,
            exposed=1,
            acceptance=treatment_acceptance,
        ),
        primary_metric="input_tokens",
    )


def test_pair_is_non_authorizing_and_accepts_observed_reduction() -> None:
    result = evaluate_paired_task(pair())

    assert result["disposition"] == "ELIGIBLE_FOR_BOUNDED_ADVANCEMENT"
    assert result["execution_effect"] == "NONE"
    assert result["routing_effect"] == "NONE"
    assert result["automatic_tool_selection"] == "DISABLED"
    assert result["comparison"]["scientific_n_increment"] == 0
    assert result["comparison"]["efficacy_effect"] == "NONE"
    assert result["comparison"]["independent_validation_effect"] == "NONE"
    assert result["comparison"]["high_assurance_effect"] == "NONE"


def test_unobserved_live_metric_is_measurement_blocked() -> None:
    result = evaluate_paired_task(
        pair(control_tokens=None, treatment_tokens=None)
    )

    assert result["disposition"] == MEASUREMENT_BLOCKED
    assert result["comparison"]["baseline_metric"] is None
    assert result["comparison"]["treatment_metric"] is None


def test_acceptance_regression_blocks_pair() -> None:
    result = evaluate_paired_task(pair(treatment_acceptance="rejected"))

    assert result["disposition"] == "BLOCKED_PRESERVATION_FAILURE"
    assert "ACCEPTANCE_REGRESSION_OR_DRIFT" in result["comparison"]["reasons"]


def test_task_contract_drift_is_rejected_before_adjudication() -> None:
    treatment = BaselineObservation(
        observation_id="treatment-002",
        task_contract="different task",
        context_state=state(),
        telemetry=ContextTelemetry(input_tokens=100, tool_definitions_exposed=1),
        outcome="completed",
        acceptance="accepted",
    )
    with pytest.raises(ValueError, match="exact task contract"):
        PairedTaskObservation(
            pair_id="pair-drift",
            model_identity="model-family/version",
            config_identity="temperature=0;tools=preselected",
            control=observation("control-002", input_tokens=200, exposed=89),
            treatment=treatment,
            primary_metric="input_tokens",
        )
