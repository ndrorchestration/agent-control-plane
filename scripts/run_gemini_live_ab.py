#!/usr/bin/env python3
"""Run the first CEP live Gemini control/treatment tool-exposure A/B.

This script performs model-boundary work only:
- loads frozen control/treatment catalogs and Gemini transport profile;
- requires GEMINI_API_KEY from process environment;
- sends both exact OpenAI-compatible requests;
- attests request/response/tool-selection evidence;
- emits a pre-bound execution handoff when both arms select the required tool.

It does NOT execute the downstream connector. That remains a separate governed
step so connector evidence can be attached explicitly rather than inferred.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path


from agent_control_plane.context_catalog_snapshot import (
    tool_catalog_snapshot_from_mapping,
    tool_catalog_snapshot_sha256,
)
from agent_control_plane.context_model_request import (
    ModelRequestManifest,
    model_request_manifest_sha256,
)
from agent_control_plane.context_openai_transport import (
    OpenAICompatibleRequest,
    send_openai_compatible_request,
)
from agent_control_plane.context_transport_profile import TransportProfile
from agent_control_plane.context_prebound_execution import (
    PreboundToolExecution,
    prebound_tool_execution_sha256,
)

ROOT = Path("experiments/context_efficiency")
CONTROL_PATH = ROOT / "catalogs/github-connector-runtime-2026-10-04.json"
TREATMENT_PATH = ROOT / "catalogs/github-status-treatment-2026-10-04.json"
PROFILE_PATH = ROOT / "transports/gemini-openai-compatible-v1.json"
BINDING_PATH = ROOT / "bindings/github-status-pr164-head-001.json"

TASK_CONTRACT = (
    "Verify exact-head workflow status with equivalent evidence and acceptance "
    "under full GitHub catalog exposure versus the frozen one-tool treatment."
)
PROMPT = (
    "Select the single tool needed to verify the exact-head workflow status for "
    "the pre-bound task. Do not answer from memory and do not choose any tool "
    "that would mutate state."
)
ENCODING = "o200k_base"
EXPECTED_TOOL = "mcp__GitHub__fetch_commit_workflow_runs"


def load_catalog(path: Path):
    return tool_catalog_snapshot_from_mapping(
        json.loads(path.read_text(encoding="utf-8"))
    )


def load_profile() -> TransportProfile:
    value = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
    return TransportProfile(
        profile_id=value["profile_id"],
        provider_family=value["provider_family"],
        endpoint=value["endpoint"],
        model=value["model"],
        api_key_env=value["api_key_env"],
        headers=value["headers"],
    )


def load_binding() -> PreboundToolExecution:
    value = json.loads(BINDING_PATH.read_text(encoding="utf-8"))
    binding = PreboundToolExecution(
        binding_id=value["binding_id"],
        tool_name=value["tool_name"],
        arguments=value["arguments"],
    )
    if prebound_tool_execution_sha256(binding) != value["sha256"]:
        raise SystemExit("pre-bound execution identity mismatch")
    return binding


def make_request(label: str, catalog, profile: TransportProfile) -> OpenAICompatibleRequest:
    prompt_sha = hashlib.sha256(PROMPT.encode("utf-8")).hexdigest()
    task_sha = hashlib.sha256(TASK_CONTRACT.encode("utf-8")).hexdigest()
    manifest = ModelRequestManifest(
        request_id=f"github-status-live-{label}-001",
        provider_family=profile.provider_family,
        model=profile.model,
        task_contract_sha256=task_sha,
        catalog=catalog,
        prompt_sha256=prompt_sha,
    )
    return OpenAICompatibleRequest(
        manifest=manifest,
        prompt=PROMPT,
        catalog=catalog,
    )


def tool_tokens(request: OpenAICompatibleRequest, tiktoken_module) -> int:
    encoding = tiktoken_module.get_encoding(ENCODING)
    tool_payload = json.dumps(
        request.to_mapping()["tools"],
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
    return len(encoding.encode(tool_payload))


def arm_result(label: str, prepared: OpenAICompatibleRequest, receipt, tiktoken_module) -> dict[str, object]:
    return {
        "arm": label,
        "catalog_sha256": tool_catalog_snapshot_sha256(prepared.catalog),
        "manifest_sha256": model_request_manifest_sha256(prepared.manifest),
        "request_body_sha256": receipt.request_body_sha256,
        "request_body_bytes": receipt.request_body_bytes,
        "model_visible_tool_count": receipt.tool_count,
        "model_visible_tool_tokens": tool_tokens(prepared, tiktoken_module),
        "provider_request_id": receipt.provider_request_id,
        "provider_model": receipt.provider_model,
        "selected_alias": receipt.selected_alias,
        "selected_tool": receipt.selected_tool,
        "latency_ms": receipt.latency_ms,
        "response_sha256": receipt.response_sha256,
        "sent": receipt.sent,
        "model_visible_exposure_observed": receipt.model_visible_exposure_observed,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--send",
        action="store_true",
        help=(
            "Send the frozen control/treatment requests. Without --send the "
            "runner performs no credential read and no network request."
        ),
    )
    args = parser.parse_args()

    profile = load_profile()
    if not args.send:
        print(
            json.dumps(
                {
                    "schema": "agent-control-plane.live-model-ab.v0-candidate",
                    "status": "BLOCKED_SEND_NOT_REQUESTED",
                    "profile_id": profile.profile_id,
                    "required_env": profile.api_key_env,
                    "credential_read": False,
                    "network_request_sent": False,
                    "scientific_n_increment": 0,
                    "efficacy_effect": "NONE",
                    "independent_validation_effect": "NONE",
                    "high_assurance_effect": "NONE",
                },
                sort_keys=True,
            )
        )
        return 0

    api_key = os.environ.get(profile.api_key_env)
    if not api_key:
        print(
            json.dumps(
                {
                    "schema": "agent-control-plane.live-model-ab.v0-candidate",
                    "status": "BLOCKED_TRANSPORT_CREDENTIAL_MISSING",
                    "required_env": profile.api_key_env,
                    "profile_id": profile.profile_id,
                    "credential_value_recorded": False,
                    "scientific_n_increment": 0,
                    "efficacy_effect": "NONE",
                    "high_assurance_effect": "NONE",
                },
                sort_keys=True,
            )
        )
        return 2

    try:
        import tiktoken
    except ImportError:
        print(
            json.dumps(
                {
                    "schema": "agent-control-plane.live-model-ab.v0-candidate",
                    "status": "BLOCKED_MEASUREMENT_DEPENDENCY_MISSING",
                    "required_dependency": "tiktoken==0.14.0",
                    "network_request_sent": False,
                    "credential_value_recorded": False,
                    "scientific_n_increment": 0,
                    "efficacy_effect": "NONE",
                    "high_assurance_effect": "NONE",
                },
                sort_keys=True,
            )
        )
        return 4

    control = make_request("control", load_catalog(CONTROL_PATH), profile)
    treatment = make_request("treatment", load_catalog(TREATMENT_PATH), profile)
    binding = load_binding()

    control_receipt = send_openai_compatible_request(
        control,
        endpoint=profile.endpoint,
        api_key=api_key,
        extra_headers=dict(profile.headers),
    )
    treatment_receipt = send_openai_compatible_request(
        treatment,
        endpoint=profile.endpoint,
        api_key=api_key,
        extra_headers=dict(profile.headers),
    )

    control_result = arm_result("control", control, control_receipt, tiktoken)
    treatment_result = arm_result("treatment", treatment, treatment_receipt, tiktoken)

    exposure_ok = (
        control_receipt.model_visible_exposure_observed
        and treatment_receipt.model_visible_exposure_observed
    )
    selection_ok = (
        control_receipt.selected_tool == EXPECTED_TOOL
        and treatment_receipt.selected_tool == EXPECTED_TOOL
        and binding.tool_name == EXPECTED_TOOL
    )

    if not exposure_ok:
        status = "BLOCKED_DYNAMIC_EXPOSURE_UNOBSERVED"
    elif not selection_ok:
        status = "BLOCKED_TOOL_SELECTION_DRIFT"
    else:
        status = "READY_FOR_PREBOUND_EXECUTION"

    output = {
        "schema": "agent-control-plane.live-model-ab.v0-candidate",
        "status": status,
        "profile_id": profile.profile_id,
        "provider_family": profile.provider_family,
        "model": profile.model,
        "encoding": ENCODING,
        "task_contract": TASK_CONTRACT,
        "prompt_sha256": hashlib.sha256(PROMPT.encode("utf-8")).hexdigest(),
        "control": control_result,
        "treatment": treatment_result,
        "prebound_execution": {
            "binding_id": binding.binding_id,
            "binding_sha256": prebound_tool_execution_sha256(binding),
            "tool_name": binding.tool_name,
            "arguments": dict(binding.arguments),
        },
        "credential_value_recorded": False,
        "scientific_n_increment": 0,
        "efficacy_effect": "NONE",
        "independent_validation_effect": "NONE",
        "high_assurance_effect": "NONE",
    }
    print(json.dumps(output, sort_keys=True))
    return 0 if status == "READY_FOR_PREBOUND_EXECUTION" else 3


if __name__ == "__main__":
    raise SystemExit(main())
