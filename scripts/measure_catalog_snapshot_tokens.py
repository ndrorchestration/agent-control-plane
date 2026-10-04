#!/usr/bin/env python3
"""Measure a frozen data-only connector catalog under an exact capability gate."""

from __future__ import annotations

import json
from pathlib import Path

import tiktoken

from agent_control_plane.context_catalog_snapshot import (
    tool_catalog_snapshot_from_mapping,
    tool_catalog_snapshot_sha256,
)
from agent_control_plane.context_tool_exposure import (
    canonical_tool_catalog_bytes,
    gate_by_required_capabilities,
)

SNAPSHOT = Path(
    "experiments/context_efficiency/catalogs/github-connector-runtime-2026-10-04.json"
)
ENCODING = "o200k_base"
REQUIRED = frozenset({"github.status.commit_workflow_runs"})


def main() -> int:
    raw = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    snapshot = tool_catalog_snapshot_from_mapping(raw)
    gated = gate_by_required_capabilities(
        snapshot.descriptors,
        required_capabilities=REQUIRED,
    )
    if [tool.name for tool in gated] != ["mcp__GitHub__fetch_commit_workflow_runs"]:
        raise SystemExit("exact capability gate did not resolve to the expected single tool")

    encoding = tiktoken.get_encoding(ENCODING)
    baseline_bytes_blob = canonical_tool_catalog_bytes(snapshot.descriptors)
    treatment_bytes_blob = canonical_tool_catalog_bytes(gated)
    baseline_text = baseline_bytes_blob.decode("utf-8")
    treatment_text = treatment_bytes_blob.decode("utf-8")
    baseline_tokens = len(encoding.encode(baseline_text))
    treatment_tokens = len(encoding.encode(treatment_text))

    result = {
        "schema": "agent-control-plane.context-live-catalog-token-result.v0-candidate",
        "experiment": "GITHUB_CONNECTOR_RUNTIME_CATALOG_2026_10_04",
        "snapshot_sha256": tool_catalog_snapshot_sha256(snapshot),
        "snapshot_source": snapshot.source,
        "snapshot_collected_at": snapshot.collected_at,
        "encoding": ENCODING,
        "tiktoken_version": tiktoken.__version__,
        "baseline_descriptor_count": len(snapshot.descriptors),
        "treatment_descriptor_count": len(gated),
        "selected_tools": [tool.name for tool in gated],
        "baseline_bytes": len(baseline_bytes_blob),
        "treatment_bytes": len(treatment_bytes_blob),
        "bytes_removed": len(baseline_bytes_blob) - len(treatment_bytes_blob),
        "byte_reduction_fraction": (
            (len(baseline_bytes_blob) - len(treatment_bytes_blob))
            / len(baseline_bytes_blob)
            if baseline_bytes_blob
            else None
        ),
        "baseline_tokens": baseline_tokens,
        "treatment_tokens": treatment_tokens,
        "tokens_removed": baseline_tokens - treatment_tokens,
        "token_reduction_fraction": (
            (baseline_tokens - treatment_tokens) / baseline_tokens
            if baseline_tokens
            else None
        ),
        "claim_boundary": (
            "Measured against a frozen real connector metadata snapshot, but not "
            "a live model prompt, latency, monetary-cost, or task-efficacy result."
        ),
    }
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
