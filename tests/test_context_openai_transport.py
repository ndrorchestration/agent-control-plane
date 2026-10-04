import hashlib
import json
from pathlib import Path

from agent_control_plane.context_catalog_snapshot import (
    tool_catalog_snapshot_from_mapping,
)
from agent_control_plane.context_model_request import ModelRequestManifest
from agent_control_plane.context_openai_transport import (
    OpenAICompatibleRequest,
    send_openai_compatible_request,
)


TREATMENT = Path(
    "experiments/context_efficiency/catalogs/github-status-treatment-2026-10-04.json"
)


def prepared() -> OpenAICompatibleRequest:
    catalog = tool_catalog_snapshot_from_mapping(
        json.loads(TREATMENT.read_text(encoding="utf-8"))
    )
    prompt = "Inspect exact-head workflow status."
    manifest = ModelRequestManifest(
        request_id="transport-test-001",
        provider_family="openai-compatible",
        model="test-model",
        task_contract_sha256="task-contract-sha",
        catalog=catalog,
        prompt_sha256=hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
    )
    return OpenAICompatibleRequest(
        manifest=manifest,
        prompt=prompt,
        catalog=catalog,
    )


def test_openai_body_exposes_exactly_one_prebound_tool_alias() -> None:
    req = prepared()
    value = req.to_mapping()

    assert len(value["tools"]) == 1
    assert value["tools"][0]["function"]["name"] == "cep_tool_001"
    assert "mcp__GitHub__fetch_commit_workflow_runs" in (
        value["tools"][0]["function"]["description"]
    )
    assert req.alias_map() == {
        "cep_tool_001": "mcp__GitHub__fetch_commit_workflow_runs"
    }


class FakeResponse:
    status = 200

    def read(self):
        return json.dumps(
            {
                "id": "provider-request-001",
                "model": "test-model",
                "choices": [],
            }
        ).encode("utf-8")


def fake_opener(req, timeout):
    assert req.headers["Content-type"] == "application/json"
    assert req.headers["Authorization"] == "Bearer secret-not-recorded"
    assert timeout == 5.0
    return FakeResponse()


def test_transport_receipt_binds_sent_body_without_recording_secret() -> None:
    receipt = send_openai_compatible_request(
        prepared(),
        endpoint="http://127.0.0.1:9999/v1/chat/completions",
        api_key="secret-not-recorded",
        timeout_seconds=5.0,
        opener=fake_opener,
    )
    value = receipt.to_mapping()

    assert value["sent"] is True
    assert value["http_status"] == 200
    assert value["provider_request_id"] == "provider-request-001"
    assert value["provider_model"] == "test-model"
    assert value["model_visible_exposure_observed"] is True
    assert value["tool_count"] == 1
    assert "secret-not-recorded" not in json.dumps(value)


class EchoResponse:
    status = 200

    def read(self):
        return b'{"echo":true}'


def test_non_model_echo_transport_does_not_claim_model_visible_exposure() -> None:
    receipt = send_openai_compatible_request(
        prepared(),
        endpoint="http://127.0.0.1:9998/echo",
        api_key=None,
        opener=lambda req, timeout: EchoResponse(),
    )

    assert receipt.sent is True
    assert receipt.model_visible_exposure_observed is False
    assert receipt.provider_request_id is None
    assert receipt.provider_model is None
