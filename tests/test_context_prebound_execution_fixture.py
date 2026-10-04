import json
from pathlib import Path

from agent_control_plane.context_prebound_execution import (
    PreboundToolExecution,
    prebound_tool_execution_sha256,
)


BINDING = Path(
    "experiments/context_efficiency/bindings/"
    "github-status-pr164-head-001.json"
)


def test_frozen_github_status_binding_identity() -> None:
    value = json.loads(BINDING.read_text(encoding="utf-8"))
    binding = PreboundToolExecution(
        binding_id=value["binding_id"],
        tool_name=value["tool_name"],
        arguments=value["arguments"],
    )

    assert value["tool_name"] == "mcp__GitHub__fetch_commit_workflow_runs"
    assert value["arguments"]["repo_full_name"] == (
        "ndrorchestration/agent-control-plane"
    )
    assert value["arguments"]["commit_sha"] == (
        "8fc6880972f272e712eafd00e7b09f8f928d82c4"
    )
    assert prebound_tool_execution_sha256(binding) == value["sha256"]
