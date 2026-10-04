import pytest

from agent_control_plane.context_baseline import (
    BASELINE_OBSERVATION_SCHEMA,
    BaselineObservation,
    baseline_observation_from_mapping,
)
from agent_control_plane.context_metrics import ContextTelemetry
from agent_control_plane.context_state import ContextState, EvidenceReference


def state() -> ContextState:
    return ContextState(
        task_id="task-baseline-1",
        objective="Characterize current context construction.",
        authority_boundaries=("HIGH_ASSURANCE=NOT_AUTHORIZED",),
        evidence=(
            EvidenceReference(source="github://repo", identity="abc123"),
        ),
        recent_delta=("Telemetry contract added.",),
    )


def observation() -> BaselineObservation:
    return BaselineObservation(
        observation_id="obs-001",
        task_contract="inspect bounded task and report exact state",
        context_state=state(),
        telemetry=ContextTelemetry(
            input_tokens=1000,
            tool_definitions_exposed=10,
            tools_invoked=2,
        ),
        outcome="completed",
        acceptance="accepted",
    )


def test_baseline_observation_round_trip_binds_context_state_identity() -> None:
    original = observation()
    mapping = original.to_mapping()

    assert mapping["schema"] == BASELINE_OBSERVATION_SCHEMA
    restored = baseline_observation_from_mapping(
        mapping,
        context_state=original.context_state,
    )
    assert restored == original


def test_baseline_observation_rejects_wrong_context_state() -> None:
    mapping = observation().to_mapping()
    different = ContextState(
        task_id="task-baseline-1",
        objective="Different objective.",
    )

    with pytest.raises(ValueError, match="context state identity mismatch"):
        baseline_observation_from_mapping(mapping, context_state=different)


def test_baseline_observation_requires_non_empty_acceptance_and_outcome() -> None:
    with pytest.raises(ValueError):
        BaselineObservation(
            observation_id="obs-002",
            task_contract="contract",
            context_state=state(),
            telemetry=ContextTelemetry(),
            outcome="",
            acceptance="accepted",
        )
