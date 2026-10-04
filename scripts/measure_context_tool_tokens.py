#!/usr/bin/env python3
"""Measure CEP synthetic tool exposure with one pinned tokenizer encoding."""

from __future__ import annotations

import json

import tiktoken

from agent_control_plane.context_tool_exposure import (
    ToolDescriptor,
    canonical_tool_catalog_bytes,
    expose_all,
    gate_by_required_capabilities,
)


ENCODING = "o200k_base"


def catalog() -> tuple[ToolDescriptor, ...]:
    names_caps = (
        ("github.workflow_runs", {"github.status"}),
        ("github.read_file", {"github.read"}),
        ("github.write_file", {"github.write"}),
        ("notion.search", {"notion.read"}),
        ("notion.update", {"notion.write"}),
        ("rdc.read_file", {"local.read"}),
        ("rdc.start_process", {"local.execute"}),
        ("web.search", {"web.read"}),
    )
    return tuple(
        ToolDescriptor(
            name,
            frozenset(capabilities),
            schema_text=f'{{"name":"{name}","args":["example"]}}',
        )
        for name, capabilities in names_caps
    )


def main() -> int:
    encoding = tiktoken.get_encoding(ENCODING)
    full = expose_all(catalog())
    gated = gate_by_required_capabilities(
        full,
        required_capabilities=frozenset({"github.status"}),
    )
    baseline_text = canonical_tool_catalog_bytes(full).decode("utf-8")
    treatment_text = canonical_tool_catalog_bytes(gated).decode("utf-8")
    baseline_tokens = len(encoding.encode(baseline_text))
    treatment_tokens = len(encoding.encode(treatment_text))
    result = {
        "schema": "agent-control-plane.context-tool-token-result.v0-candidate",
        "experiment": "SYNTHETIC_TOOL_EXPOSURE_001",
        "tiktoken_version": tiktoken.__version__,
        "encoding": ENCODING,
        "baseline_bytes": len(baseline_text.encode("utf-8")),
        "treatment_bytes": len(treatment_text.encode("utf-8")),
        "baseline_tokens": baseline_tokens,
        "treatment_tokens": treatment_tokens,
        "tokens_removed": baseline_tokens - treatment_tokens,
        "token_reduction_fraction": (
            (baseline_tokens - treatment_tokens) / baseline_tokens
            if baseline_tokens
            else None
        ),
        "claim_boundary": (
            "Synthetic pinned-tokenizer characterization only; "
            "not a live connector, latency, cost, or efficacy result."
        ),
    }
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
