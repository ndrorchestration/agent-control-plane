"""Non-authorizing interoperability projections for ACP execution.v1.

CloudEvents 1.0 structured JSON is a portable observation envelope. A
content digest identifies the serialized event but does not authenticate it.
OpenTelemetry trace context is emitted only for pre-existing valid IDs.
"""

import hashlib
import json
import re
from typing import Any, Mapping
from urllib.parse import quote

from .model import ContractValidationError, ExecutionEvent

CLOUDEVENTS_SPEC_VERSION = "1.0"
CLOUDEVENTS_TYPE = "org.ndrorchestration.acp.execution.v1"
_ENVELOPE_FIELDS = frozenset(
    {"specversion", "id", "source", "type", "subject", "time", "datacontenttype", "data"}
)
_TRACE_ID_RE = re.compile(r"^[0-9a-f]{32}$")
_SPAN_ID_RE = re.compile(r"^[0-9a-f]{16}$")


def _serialized_event_bytes(data: Mapping[str, Any]) -> bytes:
    try:
        return json.dumps(
            data, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeError) as exc:
        raise ContractValidationError("execution event is not canonical JSON") from exc


def to_cloudevent(event: ExecutionEvent) -> dict:
    """Project an ACP event into a CloudEvents 1.0 JSON-format envelope.

    The source + deterministic digest identifies the exact serialized content.
    Repeated delivery of the same event retains the ID. The digest is not a
    signature, durable custody claim, or authority decision.
    """
    if not isinstance(event, ExecutionEvent):
        raise ContractValidationError("event must be an ExecutionEvent")
    data = event.to_dict()
    event_id = hashlib.sha256(_serialized_event_bytes(data)).hexdigest()
    runtime = quote(event.component.runtime_id, safe="")
    component = quote(event.component.component_id, safe="")
    return {
        "specversion": CLOUDEVENTS_SPEC_VERSION,
        "id": event_id,
        "source": f"/agent-control-plane/{runtime}/{component}",
        "type": CLOUDEVENTS_TYPE,
        "subject": event.task_id,
        "time": event.utc_timestamp,
        "datacontenttype": "application/json",
        "data": data,
    }


def from_cloudevent(envelope: Mapping[str, Any]) -> ExecutionEvent:
    """Strictly reconstruct a round-trippable ACP-produced CloudEvent.

    Unknown envelope members are rejected by this bounded ACP profile, even
    though CloudEvents permits extensions. Neither parsing nor reconstruction
    evaluates policy, attests an event, or permits execution.
    """
    if not isinstance(envelope, Mapping) or set(envelope) != _ENVELOPE_FIELDS:
        raise ContractValidationError("unexpected CloudEvents envelope fields")
    if not isinstance(envelope["data"], Mapping):
        raise ContractValidationError("CloudEvents data must be an execution object")
    event = ExecutionEvent.from_dict(envelope["data"])
    if dict(envelope) != to_cloudevent(event):
        raise ContractValidationError("CloudEvents envelope and ACP data disagree")
    return event


def to_otel_trace_context(event: ExecutionEvent) -> dict:
    """Project existing trace IDs to OTel-compatible hexadecimal context.

    This is not an OTLP span or log exporter. Legacy ACP trace IDs may be
    arbitrary strings; rejecting them is safer than synthesizing identifiers.
    """
    if not isinstance(event, ExecutionEvent):
        raise ContractValidationError("event must be an ExecutionEvent")
    trace = event.trace
    if not _TRACE_ID_RE.fullmatch(trace.trace_id) or int(trace.trace_id, 16) == 0:
        raise ContractValidationError("trace_id is not a valid OTel trace ID")
    if not _SPAN_ID_RE.fullmatch(trace.span_id) or int(trace.span_id, 16) == 0:
        raise ContractValidationError("span_id is not a valid OTel span ID")
    if trace.parent_span_id is not None and (
        not _SPAN_ID_RE.fullmatch(trace.parent_span_id)
        or int(trace.parent_span_id, 16) == 0
    ):
        raise ContractValidationError("parent_span_id is not a valid OTel span ID")
    return {
        "trace_id": trace.trace_id,
        "span_id": trace.span_id,
        "parent_span_id": trace.parent_span_id,
    }
