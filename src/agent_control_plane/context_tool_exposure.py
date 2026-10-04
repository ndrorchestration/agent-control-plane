"""Non-executing candidate tool-catalog gating for CEP experiments.

This module only selects and serializes descriptors from an explicit catalog. It
does not invoke tools, grant authority, change policy, or inspect credentials.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Iterable


@dataclass(frozen=True)
class ToolDescriptor:
    name: str
    capabilities: frozenset[str]
    schema_text: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("tool name must be non-empty")
        if not isinstance(self.capabilities, frozenset):
            raise TypeError("capabilities must be a frozenset")
        if any(not isinstance(value, str) or not value.strip() for value in self.capabilities):
            raise ValueError("capabilities must contain non-empty strings")
        if not isinstance(self.schema_text, str):
            raise TypeError("schema_text must be a string")


def expose_all(catalog: Iterable[ToolDescriptor]) -> tuple[ToolDescriptor, ...]:
    """Baseline exposure: return the complete explicit catalog."""
    return tuple(catalog)


def gate_by_required_capabilities(
    catalog: Iterable[ToolDescriptor],
    *,
    required_capabilities: frozenset[str],
) -> tuple[ToolDescriptor, ...]:
    """Return only descriptors intersecting the declared task capability set."""
    if not isinstance(required_capabilities, frozenset):
        raise TypeError("required_capabilities must be a frozenset")
    if any(
        not isinstance(value, str) or not value.strip()
        for value in required_capabilities
    ):
        raise ValueError("required_capabilities must contain non-empty strings")
    if not required_capabilities:
        return tuple()

    return tuple(
        tool for tool in catalog if tool.capabilities & required_capabilities
    )


def exposure_count(catalog: Iterable[ToolDescriptor]) -> int:
    return len(tuple(catalog))


def canonical_tool_catalog_bytes(catalog: Iterable[ToolDescriptor]) -> bytes:
    """Serialize exposed descriptors deterministically for model-independent cost."""
    payload = [
        {
            "name": tool.name,
            "capabilities": sorted(tool.capabilities),
            "schema_text": tool.schema_text,
        }
        for tool in catalog
    ]
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def exposure_bytes(catalog: Iterable[ToolDescriptor]) -> int:
    """Return exact UTF-8 byte size of the canonical exposed descriptor payload."""
    return len(canonical_tool_catalog_bytes(catalog))


def byte_reduction_fraction(
    baseline: Iterable[ToolDescriptor],
    treatment: Iterable[ToolDescriptor],
) -> float | None:
    """Return fractional byte reduction, or None for an empty baseline payload."""
    baseline_bytes = exposure_bytes(baseline)
    if baseline_bytes == 0:
        return None
    treatment_bytes = exposure_bytes(treatment)
    return (baseline_bytes - treatment_bytes) / baseline_bytes
