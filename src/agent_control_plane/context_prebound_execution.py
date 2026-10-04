"""Immutable pre-bound tool execution records for CEP paired experiments."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Mapping


PREBOUND_TOOL_EXECUTION_SCHEMA = (
    "agent-control-plane.prebound-tool-execution.v0-candidate"
)


def _non_empty(value: str, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value


@dataclass(frozen=True)
class PreboundToolExecution:
    """Exact connector tool and arguments bound outside model inference."""

    binding_id: str
    tool_name: str
    arguments: Mapping[str, object]

    def __post_init__(self) -> None:
        _non_empty(self.binding_id, "binding_id")
        _non_empty(self.tool_name, "tool_name")
        if not isinstance(self.arguments, Mapping):
            raise TypeError("arguments must be a mapping")
        # Validate deterministic JSON serialization at construction time.
        try:
            json.dumps(
                dict(self.arguments),
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
                allow_nan=False,
            )
        except (TypeError, ValueError) as exc:
            raise ValueError("arguments must be canonical JSON values") from exc

    def to_mapping(self) -> dict[str, object]:
        return {
            "schema": PREBOUND_TOOL_EXECUTION_SCHEMA,
            "binding_id": self.binding_id,
            "tool_name": self.tool_name,
            "arguments": dict(self.arguments),
        }


def canonical_prebound_tool_execution_bytes(binding: PreboundToolExecution) -> bytes:
    if not isinstance(binding, PreboundToolExecution):
        raise TypeError("binding must be PreboundToolExecution")
    return json.dumps(
        binding.to_mapping(),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def prebound_tool_execution_sha256(binding: PreboundToolExecution) -> str:
    return hashlib.sha256(canonical_prebound_tool_execution_bytes(binding)).hexdigest()
