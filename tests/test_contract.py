import pytest

from agent_control_plane.contract import (
    SCHEMA_VERSION,
    ArtifactRef,
    ComponentIdentity,
    ContractValidationError,
    ExecutionEvent,
    ExecutionIdentity,
    TraceContext,
    map_provenance_event,
)
from agent_control_plane.provenance import ProvenanceEvent


def test_execution_identity_serializes_deterministically():
    identity = ExecutionIdentity(execution_id="exec-1", run_id="run-1")

    assert identity.to_dict() == {
        "execution_id": "exec-1",
        "run_id": "run-1",
        "schema_version": SCHEMA_VERSION,
    }


@pytest.mark.parametrize("field", ["execution_id", "run_id"])
def test_execution_identity_rejects_blank_required_fields(field):
    values = {"execution_id": "exec-1", "run_id": "run-1"}
    values[field] = "   "

    with pytest.raises(ContractValidationError):
        ExecutionIdentity(**values)


def test_execution_identity_rejects_unsupported_schema_version():
    with pytest.raises(ContractValidationError):
        ExecutionIdentity(
            execution_id="exec-1",
            run_id="run-1",
            schema_version="agent-control-plane.execution.v999",
        )


def test_trace_context_serializes_with_optional_parent():
    trace = TraceContext(trace_id="trace-1", span_id="span-1", parent_span_id="span-0")

    assert trace.to_dict() == {
        "trace_id": "trace-1",
        "span_id": "span-1",
        "parent_span_id": "span-0",
    }


@pytest.mark.parametrize(
    "kwargs",
    [
        {"trace_id": "", "span_id": "span-1"},
        {"trace_id": "trace-1", "span_id": " "},
        {"trace_id": "trace-1", "span_id": "span-1", "parent_span_id": " "},
        {"trace_id": "trace-1", "span_id": "span-1", "parent_span_id": "span-1"},
    ],
)
def test_trace_context_rejects_invalid_identity(kwargs):
    with pytest.raises(ContractValidationError):
        TraceContext(**kwargs)


def test_component_identity_serializes_without_persona_dependency():
    component = ComponentIdentity(
        component_id="kernel",
        component_type="kernel",
        runtime_id="python",
        adapter_id="native-acp",
        version="0.1.0",
        source_ref="dbab7c1",
    )

    assert component.to_dict() == {
        "component_id": "kernel",
        "component_type": "kernel",
        "runtime_id": "python",
        "adapter_id": "native-acp",
        "version": "0.1.0",
        "source_ref": "dbab7c1",
    }


@pytest.mark.parametrize("field", ["component_id", "component_type", "runtime_id", "adapter_id"])
def test_component_identity_rejects_blank_required_fields(field):
    values = {
        "component_id": "kernel",
        "component_type": "kernel",
        "runtime_id": "python",
        "adapter_id": "native-acp",
    }
    values[field] = ""

    with pytest.raises(ContractValidationError):
        ComponentIdentity(**values)


def test_artifact_ref_serializes_valid_sha256():
    artifact = ArtifactRef(
        artifact_id="artifact-1",
        kind="input",
        uri="memory://artifact-1",
        version="v1",
        sha256="a" * 64,
    )

    assert artifact.to_dict() == {
        "artifact_id": "artifact-1",
        "kind": "input",
        "uri": "memory://artifact-1",
        "version": "v1",
        "sha256": "a" * 64,
    }


@pytest.mark.parametrize("sha256", ["A" * 64, "a" * 63, "g" * 64, "not-a-hash"])
def test_artifact_ref_rejects_malformed_sha256(sha256):
    with pytest.raises(ContractValidationError):
        ArtifactRef(artifact_id="artifact-1", kind="input", sha256=sha256)


@pytest.mark.parametrize("field", ["artifact_id", "kind"])
def test_artifact_ref_rejects_blank_required_fields(field):
    values = {"artifact_id": "artifact-1", "kind": "input"}
    values[field] = " "

    with pytest.raises(ContractValidationError):
        ArtifactRef(**values)


def _event_kwargs():
    return {
        "event_type": "task.completed",
        "identity": ExecutionIdentity(execution_id="exec-1", run_id="run-1"),
        "trace": TraceContext(trace_id="trace-1", span_id="span-1"),
        "component": ComponentIdentity(
            component_id="kernel",
            component_type="kernel",
            runtime_id="python",
            adapter_id="native-acp",
        ),
        "task_id": "task-1",
        "status": "completed",
        "utc_timestamp": "2026-09-14T23:00:00+00:00",
        "monotonic_ns": 42,
    }


def test_execution_event_serializes_deterministically_with_canonical_utc():
    input_artifacts = (
        ArtifactRef(artifact_id="input-1", kind="input"),
        ArtifactRef(artifact_id="input-2", kind="input"),
    )
    output_artifacts = (ArtifactRef(artifact_id="output-1", kind="output"),)
    event = ExecutionEvent(
        **_event_kwargs(),
        capability="echo",
        policy_decision_ref="policy-1",
        input_artifacts=input_artifacts,
        output_artifacts=output_artifacts,
        detail="steps=1",
    )

    assert event.to_dict() == {
        "event_type": "task.completed",
        "identity": {
            "execution_id": "exec-1",
            "run_id": "run-1",
            "schema_version": SCHEMA_VERSION,
        },
        "trace": {
            "trace_id": "trace-1",
            "span_id": "span-1",
            "parent_span_id": None,
        },
        "component": {
            "component_id": "kernel",
            "component_type": "kernel",
            "runtime_id": "python",
            "adapter_id": "native-acp",
            "version": None,
            "source_ref": None,
        },
        "task_id": "task-1",
        "status": "completed",
        "utc_timestamp": "2026-09-14T23:00:00Z",
        "monotonic_ns": 42,
        "capability": "echo",
        "policy_decision_ref": "policy-1",
        "input_artifacts": [
            {"artifact_id": "input-1", "kind": "input", "uri": None, "version": None, "sha256": None},
            {"artifact_id": "input-2", "kind": "input", "uri": None, "version": None, "sha256": None},
        ],
        "output_artifacts": [
            {"artifact_id": "output-1", "kind": "output", "uri": None, "version": None, "sha256": None}
        ],
        "detail": "steps=1",
    }


def test_execution_event_preserves_artifact_order():
    event = ExecutionEvent(
        **_event_kwargs(),
        input_artifacts=(
            ArtifactRef(artifact_id="first", kind="input"),
            ArtifactRef(artifact_id="second", kind="input"),
        ),
    )

    assert [item["artifact_id"] for item in event.to_dict()["input_artifacts"]] == ["first", "second"]


def test_execution_event_rejects_negative_monotonic_value():
    values = _event_kwargs()
    values["monotonic_ns"] = -1

    with pytest.raises(ContractValidationError):
        ExecutionEvent(**values)


@pytest.mark.parametrize(
    "timestamp",
    [
        "2026-09-14T23:00:00",
        "2026-09-15T00:00:00+01:00",
    ],
)
def test_execution_event_rejects_naive_or_non_utc_timestamp(timestamp):
    values = _event_kwargs()
    values["utc_timestamp"] = timestamp

    with pytest.raises(ContractValidationError):
        ExecutionEvent(**values)


def _mapping_context(run_id="run-1"):
    return {
        "identity": ExecutionIdentity(execution_id="exec-1", run_id=run_id),
        "trace": TraceContext(trace_id="trace-1", span_id="span-1"),
        "component": ComponentIdentity(
            component_id="kernel",
            component_type="kernel",
            runtime_id="python",
            adapter_id="native-acp",
        ),
        "monotonic_ns": 77,
    }


def test_map_provenance_event_preserves_legacy_fields_and_context():
    source = ProvenanceEvent(
        event="task.completed",
        task_id="task-1",
        run_id="run-1",
        capability="echo",
        state="completed",
        detail="steps=1",
        timestamp="2026-09-14T23:00:00+00:00",
    )
    input_artifact = ArtifactRef(artifact_id="input-1", kind="input")

    mapped = map_provenance_event(
        source,
        **_mapping_context(),
        input_artifacts=(input_artifact,),
        policy_decision_ref="policy-1",
    )

    assert mapped.event_type == "task.completed"
    assert mapped.task_id == "task-1"
    assert mapped.identity.run_id == "run-1"
    assert mapped.capability == "echo"
    assert mapped.status == "completed"
    assert mapped.detail == "steps=1"
    assert mapped.utc_timestamp == "2026-09-14T23:00:00Z"
    assert mapped.monotonic_ns == 77
    assert mapped.input_artifacts == (input_artifact,)
    assert mapped.policy_decision_ref == "policy-1"


def test_map_provenance_event_maps_absent_state_to_unspecified():
    source = ProvenanceEvent(
        event="task.rejected",
        task_id="task-1",
        run_id="run-1",
        timestamp="2026-09-14T23:00:00Z",
    )

    mapped = map_provenance_event(source, **_mapping_context())

    assert mapped.status == "unspecified"


def test_map_provenance_event_rejects_run_mismatch():
    source = ProvenanceEvent(
        event="task.started",
        task_id="task-1",
        run_id="run-source",
        state="running",
        timestamp="2026-09-14T23:00:00Z",
    )

    with pytest.raises(ContractValidationError):
        map_provenance_event(source, **_mapping_context(run_id="run-contract"))
