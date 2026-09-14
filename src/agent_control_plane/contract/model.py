"""Framework-neutral execution contract primitives."""

from dataclasses import asdict, dataclass
import re
from typing import Any, Dict, Optional

SCHEMA_VERSION = "agent-control-plane.execution.v1"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class ContractValidationError(ValueError):
    """Raised when required execution-contract data is invalid."""


def _required(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContractValidationError(f"{field_name} must not be blank")
    return value


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
