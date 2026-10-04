import pytest

from agent_control_plane.context_prebound_execution import (
    PreboundToolExecution,
    prebound_tool_execution_sha256,
)


def test_prebound_execution_identity_is_deterministic() -> None:
    first = PreboundToolExecution(
        binding_id="github-status-001",
        tool_name="mcp__GitHub__fetch_commit_workflow_runs",
        arguments={
            "repo_full_name": "ndrorchestration/agent-control-plane",
            "commit_sha": "abc123",
        },
    )
    second = PreboundToolExecution(
        binding_id="github-status-001",
        tool_name="mcp__GitHub__fetch_commit_workflow_runs",
        arguments={
            "commit_sha": "abc123",
            "repo_full_name": "ndrorchestration/agent-control-plane",
        },
    )

    assert prebound_tool_execution_sha256(first) == prebound_tool_execution_sha256(
        second
    )


def test_prebound_execution_rejects_non_json_arguments() -> None:
    with pytest.raises(ValueError):
        PreboundToolExecution(
            binding_id="bad",
            tool_name="mcp__GitHub__fetch_commit_workflow_runs",
            arguments={"not_json": object()},
        )
