import pytest

from agent_control_plane.context_baseline import BaselineObservation, baseline_observation_sha256
from agent_control_plane.context_comparison import COMPARISON_PLAN_SCHEMA, ComparisonPlan
from agent_control_plane.context_metrics import ContextTelemetry
from agent_control_plane.context_state import ContextState


def baseline() -> BaselineObservation:
    return BaselineObservation(
        observation_id="obs-control-001",
        task_contract="bounded inspection task",
        context_state=ContextState(task_id="task-1", objective="inspect exact state"),
        telemetry=ContextTelemetry(input_tokens=1000, tool_definitions_exposed=10, tools_invoked=2),
        outcome="completed",
        acceptance="accepted",
    )


def test_comparison_plan_binds_frozen_baseline_identity() -> None:
    control = baseline()
    plan = ComparisonPlan(
        plan_id="cep-compare-001",
        baseline=control,
        treatment="capability-driven tool gating",
        primary_metric="tool_definitions_exposed",
        preservation_checks=("same task contract", "same authority boundaries"),
        acceptance_rule="reduce tool exposure with no acceptance regression",
    )

    mapping = plan.to_mapping()

    assert mapping["schema"] == COMPARISON_PLAN_SCHEMA
    assert mapping["baseline_observation_sha256"] == baseline_observation_sha256(control)
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
