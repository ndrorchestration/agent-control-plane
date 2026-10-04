import json
from pathlib import Path

import pytest

from agent_control_plane.context_catalog_snapshot import (
    tool_catalog_snapshot_from_mapping,
)
from agent_control_plane.context_model_request import (
    ModelRequestManifest,
    ModelTransportReceipt,
    model_request_manifest_sha256,
)


CATALOG = Path(
    "experiments/context_efficiency/catalogs/github-status-treatment-2026-10-04.json"
)


def manifest() -> ModelRequestManifest:
    catalog = tool_catalog_snapshot_from_mapping(
        json.loads(CATALOG.read_text(encoding="utf-8"))
    )
    return ModelRequestManifest(
        request_id="cep-live-ab-treatment-001",
        provider_family="openai-compatible",
        model="unbound-model",
        task_contract_sha256="task-contract-sha",
        catalog=catalog,
        prompt_sha256="prompt-sha",
    )


def test_manifest_binds_exact_treatment_catalog_and_tool_payload() -> None:
    value = manifest().to_mapping()

    assert value["tool_count"] == 1
    assert value["catalog_sha256"] == (
        "c9dc0dfa022e4d367ce57f58cecac075c4bff419e7a4cd14cd358344b9b17cbb"
    )
    assert len(value["tool_payload_sha256"]) == 64
    assert value["tool_payload_bytes"] > 0
    assert len(model_request_manifest_sha256(manifest())) == 64


def test_unsent_receipt_is_explicit_and_has_no_provider_identity() -> None:
    receipt = ModelTransportReceipt(
        request_manifest_sha256=model_request_manifest_sha256(manifest()),
        transport="not-configured",
        sent=False,
    )

    value = receipt.to_mapping()
    assert value["sent"] is False
    assert value["provider_request_id"] is None
    assert value["response_sha256"] is None
    assert value["authority_effect"] == "NONE"


def test_unsent_receipt_rejects_fake_provider_response_identity() -> None:
    with pytest.raises(ValueError):
        ModelTransportReceipt(
            request_manifest_sha256=model_request_manifest_sha256(manifest()),
            transport="not-configured",
            sent=False,
            provider_request_id="invented",
        )
