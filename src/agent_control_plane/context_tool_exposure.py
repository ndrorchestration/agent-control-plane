"""Non-executing candidate tool-catalog gating for CEP experiments.

This module only selects descriptors from an explicit catalog. It does not invoke
tools, grant authority, change policy, or inspect runtime credentials.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class ToolDescriptor:
    name: str
    capabilities: frozenset[str]

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("tool name must be non-empty")
        if not isinstance(self.capabilities, frozenset):
            raise TypeError("capabilities must be a frozenset")
        if any(not isinstance(value, str) or not value.strip() for value in self.capabilities):
            raise ValueError("capabilities must contain non-empty strings")


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

    selected = tuple(
        tool for tool in catalog if tool.capabilities & required_capabilities
    )
    return selected


def exposure_count(catalog: Iterable[ToolDescriptor]) -> int:
    return len(tuple(catalog))
