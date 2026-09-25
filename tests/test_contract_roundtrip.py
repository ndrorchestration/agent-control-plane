import pytest

from agent_control_plane.contract import (
    SCHEMA_VERSION,
    ArtifactRef,
    ComponentIdentity,
    ContractValidationError,
    ExecutionEvent,
    ExecutionIdentity,
    TraceContext,
)


def _full_event():
    return ExecutionEvent(
        event_type="task.completed",
        identity=ExecutionIdentity(execution_id="exec-1", run_id="run-1"),
        trace=TraceContext(trace_id="trace-1", span_id="span-1", parent_span_id="span-0"),
        component=ComponentIdentity(
            component_id="kernel",
            component_type="kernel",
            runtime_id="python",
            adapter_id="native-acp",
            version="0.1.0",
            source_ref="commit:dbab7c1",
        ),
        task_id="task-1",
        status="completed",
        utc_timestamp="2026-09-14T23:00:00Z",
        monotonic_ns=123,
        capability="echo",
        policy_decision_ref="policy-1",
        input_artifacts=(
            ArtifactRef(
                artifact_id="input-1",
                kind="input",
                uri="memory://input-1",
                version="v1",
                sha256="a" * 64,
            ),
        ),
        output_artifacts=(ArtifactRef(artifact_id="output-1", kind="output"),),
        detail="steps=1",
    )


def test_execution_event_round_trip_preserves_semantics():
    event = _full_event()

    reconstructed = ExecutionEvent.from_dict(event.to_dict())

    assert reconstructed == event
    assert reconstructed.to_dict() == event.to_dict()


def test_execution_event_from_dict_rejects_unsupported_schema_version():
    payload = _full_event().to_dict()
    payload["identity"]["schema_version"] = "agent-control-plane.execution.v999"

    with pytest.raises(ContractValidationError):
        ExecutionEvent.from_dict(payload)


def test_execution_event_from_dict_rejects_malformed_structure_fail_closed():
    payload = _full_event().to_dict()
    del payload["trace"]["span_id"]

    with pytest.raises(ContractValidationError):
        ExecutionEvent.from_dict(payload)
