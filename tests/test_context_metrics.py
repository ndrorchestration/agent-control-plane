import pytest

from agent_control_plane.context_metrics import ContextTelemetry


def test_characterization_metrics_are_computed_from_observed_counts() -> None:
    telemetry = ContextTelemetry(
        input_tokens=1000,
        output_tokens=200,
        tool_result_tokens=300,
        tool_definitions_exposed=10,
        tools_invoked=2,
        retrieved_tokens=400,
        used_retrieved_tokens=100,
        retrieved_items=4,
        cacheable_prefix_tokens=600,
        novel_prefix_tokens=200,
        decision_relevant_input_tokens=500,
    )

    assert telemetry.context_efficiency == 0.5
    assert telemetry.retrieval_yield == 0.25
    assert telemetry.tool_utilization == 0.2
    assert telemetry.context_churn == 0.25


def test_unobservable_metrics_remain_unavailable() -> None:
    telemetry = ContextTelemetry(input_tokens=100)

    assert telemetry.context_efficiency is None
    assert telemetry.retrieval_yield is None
    assert telemetry.tool_utilization is None
    assert telemetry.context_churn is None


@pytest.mark.parametrize(
    "kwargs",
    [
        {"input_tokens": -1},
        {"tools_invoked": 2, "tool_definitions_exposed": 1},
        {"retrieved_tokens": 10, "used_retrieved_tokens": 11},
        {"input_tokens": 10, "decision_relevant_input_tokens": 11},
        {
            "input_tokens": 10,
            "cacheable_prefix_tokens": 7,
            "novel_prefix_tokens": 4,
        },
    ],
)
def test_impossible_or_negative_measurements_fail_closed(kwargs) -> None:
    with pytest.raises(ValueError):
        ContextTelemetry(**kwargs)


def test_zero_denominators_do_not_invent_efficiency() -> None:
    telemetry = ContextTelemetry(
        input_tokens=0,
        tool_definitions_exposed=0,
        tools_invoked=0,
        retrieved_tokens=0,
        used_retrieved_tokens=0,
        cacheable_prefix_tokens=0,
        novel_prefix_tokens=0,
        decision_relevant_input_tokens=0,
    )

    assert telemetry.context_efficiency is None
    assert telemetry.retrieval_yield is None
    assert telemetry.tool_utilization is None
    assert telemetry.context_churn is None
