"""Framework-neutral execution contract primitives."""

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
import re
from typing import Any, Dict, Optional, Tuple

SCHEMA_VERSION = "agent-control-plane.execution.v1"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class ContractValidationError(ValueError):
    """Raised when required execution-contract data is invalid."""


def _required(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContractValidationError(f"{field_name} must not be blank")
    return value


def _canonical_utc_timestamp(value: str) -> str:
    _required(value, "utc_timestamp")
    candidate = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError as exc:
        raise ContractValidationError("utc_timestamp must be valid ISO-8601") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ContractValidationError("utc_timestamp must be timezone-aware UTC")
    if parsed.utcoffset() != timedelta(0):
        raise ContractValidationError("utc_timestamp must use UTC")
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class ExecutionIdentity:
    execution_id: str
    run_id: str
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        _required(self.execution_id, "execution_id")
        _required(self.run_id, "run_id")
        if self.schema_version != SCHEMA_VERSION:
            raise ContractValidationError(f"unsupported schema_version: {self.schema_version}")

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class TraceContext:
    trace_id: str
    span_id: str
    parent_span_id: Optional[str] = None

    def __post_init__(self) -> None:
        _required(self.trace_id, "trace_id")
        _required(self.span_id, "span_id")
        if self.parent_span_id is not None:
            _required(self.parent_span_id, "parent_span_id")
            if self.parent_span_id == self.span_id:
                raise ContractValidationError("span_id must not equal parent_span_id")

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ComponentIdentity:
    component_id: str
    component_type: str
    runtime_id: str
    adapter_id: str
    version: Optional[str] = None
    source_ref: Optional[str] = None

    def __post_init__(self) -> None:
        _required(self.component_id, "component_id")
        _required(self.component_type, "component_type")
        _required(self.runtime_id, "runtime_id")
        _required(self.adapter_id, "adapter_id")

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ArtifactRef:
    artifact_id: str
    kind: str
    uri: Optional[str] = None
    version: Optional[str] = None
    sha256: Optional[str] = None

    def __post_init__(self) -> None:
        _required(self.artifact_id, "artifact_id")
        _required(self.kind, "kind")
        if self.sha256 is not None and _SHA256_RE.fullmatch(self.sha256) is None:
            raise ContractValidationError("sha256 must be 64 lowercase hexadecimal characters")

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ExecutionEvent:
    event_type: str
    identity: ExecutionIdentity
    trace: TraceContext
    component: ComponentIdentity
    task_id: str
    status: str
    utc_timestamp: str
    monotonic_ns: int
    capability: Optional[str] = None
    policy_decision_ref: Optional[str] = None
    input_artifacts: Tuple[ArtifactRef, ...] = ()
    output_artifacts: Tuple[ArtifactRef, ...] = ()
    detail: Optional[str] = None

    def __post_init__(self) -> None:
        _required(self.event_type, "event_type")
        _required(self.task_id, "task_id")
        _required(self.status, "status")
        if isinstance(self.monotonic_ns, bool) or not isinstance(self.monotonic_ns, int):
            raise ContractValidationError("monotonic_ns must be an integer >= 0")
        if self.monotonic_ns < 0:
            raise ContractValidationError("monotonic_ns must be an integer >= 0")
        object.__setattr__(self, "utc_timestamp", _canonical_utc_timestamp(self.utc_timestamp))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_type": self.event_type,
            "identity": self.identity.to_dict(),
            "trace": self.trace.to_dict(),
            "component": self.component.to_dict(),
            "task_id": self.task_id,
            "status": self.status,
            "utc_timestamp": self.utc_timestamp,
            "monotonic_ns": self.monotonic_ns,
            "capability": self.capability,
            "policy_decision_ref": self.policy_decision_ref,
            "input_artifacts": [artifact.to_dict() for artifact in self.input_artifacts],
            "output_artifacts": [artifact.to_dict() for artifact in self.output_artifacts],
            "detail": self.detail,
        }
