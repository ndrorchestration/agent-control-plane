import pytest

from agent_control_plane.contract import (
    SCHEMA_VERSION,
    ArtifactRef,
    ComponentIdentity,
    ContractValidationError,
    ExecutionIdentity,
    TraceContext,
)


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
