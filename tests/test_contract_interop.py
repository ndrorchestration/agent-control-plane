"""Bounded tests for non-authorizing execution-v1 interoperability."""

from copy import deepcopy
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker

from agent_control_plane.contract import (
    ComponentIdentity,
    ContractValidationError,
    ExecutionEvent,
    ExecutionIdentity,
    TraceContext,
)
from agent_control_plane.contract.interop import (
    from_cloudevent,
    to_cloudevent,
    to_otel_trace_context,
)


def _event(*, trace_id="1" * 32, span_id="2" * 16, parent_span_id=None):
    return ExecutionEvent(
        event_type="task.completed",
        identity=ExecutionIdentity(execution_id="exec-1", run_id="run-1"),
        trace=TraceContext(
            trace_id=trace_id, span_id=span_id, parent_span_id=parent_span_id
        ),
        component=ComponentIdentity(
            component_id="kernel", component_type="kernel",
            runtime_id="python", adapter_id="native-acp"
        ),
        task_id="task-1",
        status="completed",
        utc_timestamp="2026-11-15T18:00:00Z",
        monotonic_ns=42,
        policy_decision_ref="decision-1",
    )


def _validator():
    path = Path(__file__).resolve().parents[1] / "contracts" / "execution.v1.schema.json"
    schema = json.loads(path.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, format_checker=FormatChecker())


def test_execution_v1_schema_accepts_serialized_native_event():
    assert _validator().is_valid(_event().to_dict())


@pytest.mark.parametrize(
    ("path", "bad"),
    [
        (("identity", "schema_version"), "agent-control-plane.execution.v2"),
        (("trace", "span_id"), ""),
        (("monotonic_ns",), -1),
        (("monotonic_ns",), True),
        (("utc_timestamp",), "2026-11-15T18:00:00"),
        (("policy_decision_ref",), 123),
    ],
)
def test_execution_v1_schema_rejects_invalid_serialization(path, bad):
    record = _event().to_dict()
    target = record
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = bad
    assert not _validator().is_valid(record)


def test_schema_rejects_unknown_keys_and_missing_serialized_fields():
    record = _event().to_dict()
    record["unsupported_promotion"] = True
    assert not _validator().is_valid(record)
    del record["unsupported_promotion"]
    del record["output_artifacts"]
    assert not _validator().is_valid(record)


def test_cloudevents_roundtrip_is_deterministic_and_non_authorizing():
    event = _event()
    projected = to_cloudevent(event)
    assert projected["specversion"] == "1.0"
    assert projected["source"] == "/agent-control-plane/python/kernel"
    assert projected["type"] == "org.ndrorchestration.acp.execution.v1"
    assert projected["datacontenttype"] == "application/json"
    assert len(projected["id"]) == 64
    assert to_cloudevent(event) == projected
    assert from_cloudevent(projected) == event
    assert from_cloudevent(projected).policy_decision_ref == "decision-1"


def test_cloudevents_rejects_changed_data_without_updated_digest():
    projected = to_cloudevent(_event())
    projected["data"]["status"] = "authorized"
    with pytest.raises(ContractValidationError):
        from_cloudevent(projected)


@pytest.mark.parametrize(
    "alter",
    [
        lambda x: x.update(specversion="2.0"),
        lambda x: x.update(source="/wrong/source"),
        lambda x: x.update(id="0" * 64),
        lambda x: x.update(time="2026-11-15T19:00:00Z"),
        lambda x: x.update(unsupported_promotion=True),
        lambda x: x.pop("id"),
    ],
)
def test_cloudevents_rejects_malformed_or_mismatched_envelope(alter):
    projected = to_cloudevent(_event())
    alter(projected)
    with pytest.raises(ContractValidationError):
        from_cloudevent(projected)


def test_cloudevents_rejects_non_json_payload_without_fabricating_receipt():
    event = _event()
    object.__setattr__(event, "detail", object())
    with pytest.raises(ContractValidationError, match="canonical JSON"):
        to_cloudevent(event)


def test_otel_context_accepts_only_original_valid_ids():
    event = _event(parent_span_id="3" * 16)
    assert to_otel_trace_context(event) == {
        "trace_id": "1" * 32,
        "span_id": "2" * 16,
        "parent_span_id": "3" * 16,
    }
    assert to_otel_trace_context(_event())["parent_span_id"] is None


@pytest.mark.parametrize(
    "values",
    [
        {"trace_id": "trace-1", "span_id": "span-1"},
        {"trace_id": "0" * 32},
        {"trace_id": "A" * 32},
        {"span_id": "0" * 16},
        {"span_id": "F" * 16},
        {"parent_span_id": "0" * 16},
    ],
)
def test_otel_context_fails_closed_on_legacy_or_invalid_ids(values):
    with pytest.raises(ContractValidationError):
        to_otel_trace_context(_event(**values))


def test_cloudevents_different_events_have_distinct_ids():
    first = _event()
    changed = deepcopy(first)
    object.__setattr__(changed, "monotonic_ns", 43)
    assert to_cloudevent(first)["id"] != to_cloudevent(changed)["id"]
