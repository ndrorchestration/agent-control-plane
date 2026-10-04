#!/usr/bin/env python3
"""Build CEP control/treatment request attestations without sending a model request."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from agent_control_plane.context_catalog_snapshot import tool_catalog_snapshot_from_mapping
from agent_control_plane.context_model_request import (
    ModelRequestManifest,
    ModelTransportReceipt,
    model_request_manifest_sha256,
)


CONTROL = Path(
    "experiments/context_efficiency/catalogs/github-connector-runtime-2026-10-04.json"
)
TREATMENT = Path(
    "experiments/context_efficiency/catalogs/github-status-treatment-2026-10-04.json"
)
TASK_CONTRACT = (
    "Verify exact-head workflow status with equivalent evidence and acceptance "
    "under full GitHub catalog exposure versus the frozen one-tool treatment."
)
PROMPT = (
    "Inspect the exact-head workflow status and report the observed run status "
    "and conclusion without widening scope."
)


def load(path: Path):
    return tool_catalog_snapshot_from_mapping(
        json.loads(path.read_text(encoding="utf-8"))
    )


def build(label: str, catalog) -> dict[str, object]:
    manifest = ModelRequestManifest(
        request_id=f"github-status-{label}-request-001",
        provider_family="openai-compatible",
        model="UNBOUND_NOT_CONFIGURED",
        task_contract_sha256=hashlib.sha256(TASK_CONTRACT.encode("utf-8")).hexdigest(),
        catalog=catalog,
        prompt_sha256=hashlib.sha256(PROMPT.encode("utf-8")).hexdigest(),
    )
    receipt = ModelTransportReceipt(
        request_manifest_sha256=model_request_manifest_sha256(manifest),
        transport="NOT_CONFIGURED",
        sent=False,
    )
    return {
        "arm": label,
        "manifest": manifest.to_mapping(),
        "manifest_sha256": model_request_manifest_sha256(manifest),
        "transport_receipt": receipt.to_mapping(),
    }


def main() -> int:
    output = {
        "schema": "agent-control-plane.model-request-ab-preflight.v0-candidate",
        "task_contract": TASK_CONTRACT,
        "prompt": PROMPT,
        "control": build("control", load(CONTROL)),
        "treatment": build("treatment", load(TREATMENT)),
        "dynamic_exposure_observed": False,
        "status": "BLOCKED_TRANSPORT_NOT_CONFIGURED",
        "claim_boundary": (
            "Exact request manifests are constructed and hashed, but no model "
            "transport is configured or sent."
        ),
    }
    print(json.dumps(output, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
