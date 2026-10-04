import pytest

from agent_control_plane.context_catalog_snapshot import (
    TOOL_CATALOG_SNAPSHOT_SCHEMA,
    ToolCatalogSnapshot,
    tool_catalog_snapshot_from_mapping,
    tool_catalog_snapshot_sha256,
)
from agent_control_plane.context_tool_exposure import ToolDescriptor


def snapshot() -> ToolCatalogSnapshot:
    return ToolCatalogSnapshot(
        source="mcp://example/catalog",
        collected_at="2026-10-04T14:40:00Z",
        descriptors=(
            ToolDescriptor(
                "github.workflow_runs",
                frozenset({"github.status"}),
                '{"type":"object"}',
            ),
        ),
    )


def test_snapshot_round_trip_and_identity_are_deterministic() -> None:
    original = snapshot()
    restored = tool_catalog_snapshot_from_mapping(original.to_mapping())
    assert restored == original
    assert tool_catalog_snapshot_sha256(restored) == tool_catalog_snapshot_sha256(original)


def test_snapshot_loader_rejects_executable_or_unknown_fields() -> None:
    value = snapshot().to_mapping()
    value["descriptors"][0]["invoke"] = "not-allowed"
    with pytest.raises(ValueError, match="descriptor fields mismatch"):
        tool_catalog_snapshot_from_mapping(value)


def test_snapshot_schema_is_explicit() -> None:
    assert snapshot().to_mapping()["schema"] == TOOL_CATALOG_SNAPSHOT_SCHEMA
