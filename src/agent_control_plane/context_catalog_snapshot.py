"""Validated external tool-catalog snapshots for CEP measurement.

Snapshots are data-only. Loading a snapshot never creates executable tool handles.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Mapping

from .context_tool_exposure import ToolDescriptor


TOOL_CATALOG_SNAPSHOT_SCHEMA = "agent-control-plane.tool-catalog-snapshot.v0-candidate"


@dataclass(frozen=True)
class ToolCatalogSnapshot:
    source: str
    collected_at: str
    descriptors: tuple[ToolDescriptor, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.source, str) or not self.source.strip():
            raise ValueError("source must be non-empty")
        if not isinstance(self.collected_at, str) or not self.collected_at.strip():
            raise ValueError("collected_at must be non-empty")
        if not isinstance(self.descriptors, tuple):
            raise TypeError("descriptors must be a tuple")
        if any(not isinstance(item, ToolDescriptor) for item in self.descriptors):
            raise TypeError("descriptors must contain ToolDescriptor values")

    def to_mapping(self) -> dict[str, object]:
        return {
            "schema": TOOL_CATALOG_SNAPSHOT_SCHEMA,
            "source": self.source,
            "collected_at": self.collected_at,
            "descriptors": [
                {
                    "name": item.name,
                    "capabilities": sorted(item.capabilities),
                    "schema_text": item.schema_text,
                }
                for item in self.descriptors
            ],
        }


def canonical_tool_catalog_snapshot_bytes(snapshot: ToolCatalogSnapshot) -> bytes:
    return json.dumps(
        snapshot.to_mapping(),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def tool_catalog_snapshot_sha256(snapshot: ToolCatalogSnapshot) -> str:
    return hashlib.sha256(canonical_tool_catalog_snapshot_bytes(snapshot)).hexdigest()


def tool_catalog_snapshot_from_mapping(value: Mapping[str, object]) -> ToolCatalogSnapshot:
    if not isinstance(value, Mapping):
        raise TypeError("snapshot must be a mapping")
    if set(value) != {"schema", "source", "collected_at", "descriptors"}:
        raise ValueError("tool catalog snapshot fields mismatch")
    if value["schema"] != TOOL_CATALOG_SNAPSHOT_SCHEMA:
        raise ValueError("unsupported tool catalog snapshot schema")
    raw = value["descriptors"]
    if not isinstance(raw, list):
        raise TypeError("descriptors must be a list")

    descriptors: list[ToolDescriptor] = []
    for item in raw:
        if not isinstance(item, Mapping):
            raise TypeError("descriptor must be a mapping")
        if set(item) != {"name", "capabilities", "schema_text"}:
            raise ValueError("descriptor fields mismatch")
        capabilities = item["capabilities"]
        if not isinstance(capabilities, list):
            raise TypeError("descriptor capabilities must be a list")
        descriptors.append(
            ToolDescriptor(
                name=item["name"],
                capabilities=frozenset(capabilities),
                schema_text=item["schema_text"],
            )
        )
    return ToolCatalogSnapshot(
        source=value["source"],
        collected_at=value["collected_at"],
        descriptors=tuple(descriptors),
    )
