import json
from pathlib import Path

from agent_control_plane.context_catalog_snapshot import (
    tool_catalog_snapshot_from_mapping,
    tool_catalog_snapshot_sha256,
)
from agent_control_plane.context_tool_exposure import gate_by_required_capabilities


SNAPSHOT = Path(
    "experiments/context_efficiency/catalogs/github-connector-runtime-2026-10-04.json"
)


def load_snapshot():
    return tool_catalog_snapshot_from_mapping(
        json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    )


def test_frozen_github_connector_snapshot_has_expected_catalog_size() -> None:
    snapshot = load_snapshot()

    assert len(snapshot.descriptors) == 89
    assert snapshot.source == "chatgpt-runtime://GitHub/connector-catalog"
    assert tool_catalog_snapshot_sha256(snapshot) == (
        "f9d463a1c8519061087cba30bd648b68357949f20ce932c61c3f99821663b82e"
    )


def test_exact_head_status_capability_resolves_to_one_descriptor() -> None:
    snapshot = load_snapshot()
    gated = gate_by_required_capabilities(
        snapshot.descriptors,
        required_capabilities=frozenset({"github.status.commit_workflow_runs"}),
    )

    assert [tool.name for tool in gated] == [
        "mcp__GitHub__fetch_commit_workflow_runs"
    ]


def test_exact_status_descriptor_is_data_only() -> None:
    snapshot = load_snapshot()
    [descriptor] = gate_by_required_capabilities(
        snapshot.descriptors,
        required_capabilities=frozenset({"github.status.commit_workflow_runs"}),
    )

    assert isinstance(descriptor.schema_text, str)
    assert not hasattr(descriptor, "invoke")
    assert not hasattr(descriptor, "credentials")
    assert not hasattr(descriptor, "authority")


def test_gated_catalog_preserves_observed_baseline_operational_tool() -> None:
    snapshot = load_snapshot()
    control_names = {tool.name for tool in snapshot.descriptors}
    gated = gate_by_required_capabilities(
        snapshot.descriptors,
        required_capabilities=frozenset({"github.status.commit_workflow_runs"}),
    )
    gated_names = {tool.name for tool in gated}

    assert gated_names < control_names
    assert gated_names == {"mcp__GitHub__fetch_commit_workflow_runs"}
    assert "mcp__GitHub__fetch_commit_workflow_runs" in control_names
