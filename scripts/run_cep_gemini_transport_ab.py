#!/usr/bin/env python3
"""Run the first bounded CEP Gemini transport A/B without persisting credentials.

Dry-run is the default. A real send requires --send and an explicitly supplied
credential in the transport profile's named environment variable.

This script establishes transport/model-visible catalog evidence only. It does
not invoke the selected connector tool and cannot establish end-to-end task
acceptance or efficacy by itself.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Callable, Mapping
from urllib import request as urllib_request

from agent_control_plane.context_catalog_snapshot import (
    ToolCatalogSnapshot,
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
from agent_control_plane.context_prebound_execution import (
    PreboundToolExecution,
    prebound_tool_execution_sha256,
)
from agent_control_plane.context_tool_exposure import canonical_tool_catalog_bytes
from agent_control_plane.context_transport_profile import TransportProfile


ROOT = Path(__file__).resolve().parents[1]
PROFILE_PATH = ROOT / (
    "experiments/context_efficiency/transports/"
    "gemini-openai-compatible-v1.json"
)
CONTROL_PATH = ROOT / (
    "experiments/context_efficiency/catalogs/"
    "github-connector-runtime-2026-10-04.json"
)
TREATMENT_PATH = ROOT / (
    "experiments/context_efficiency/catalogs/"
    "github-status-treatment-2026-10-04.json"
)
TOKEN_RESULT_PATH = ROOT / (
    "experiments/context_efficiency/results/"
    "github-connector-runtime-token-2026-10-04.json"
)
PREFLIGHT_PATH = ROOT / (
    "experiments/context_efficiency/results/"
    "model-request-ab-preflight-2026-10-04.json"
)
BINDING_PATH = ROOT / (
    "experiments/context_efficiency/bindings/"
    "github-status-pr164-head-001.json"
)
ENCODING = "o200k_base"

EXPECTED_CONTROL_SHA = (
    "f9d463a1c8519061087cba30bd648b68357949f20ce932c61c3f99821663b82e"
)
EXPECTED_TREATMENT_SHA = (
    "c9dc0dfa022e4d367ce57f58cecac075c4bff419e7a4cd14cd358344b9b17cbb"
)
EXPECTED_TOOL = "mcp__GitHub__fetch_commit_workflow_runs"


def _load_json(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def _load_profile() -> TransportProfile:
    raw = _load_json(PROFILE_PATH)
    return TransportProfile(
        profile_id=str(raw["profile_id"]),
        provider_family=str(raw["provider_family"]),
        endpoint=str(raw["endpoint"]),
        model=str(raw["model"]),
        api_key_env=str(raw["api_key_env"]),
        headers=dict(raw["headers"]),
    )


def _load_catalog(path: Path) -> ToolCatalogSnapshot:
    return tool_catalog_snapshot_from_mapping(_load_json(path))


def _load_binding() -> PreboundToolExecution:
    raw = _load_json(BINDING_PATH)
    binding = PreboundToolExecution(
        binding_id=str(raw["binding_id"]),
        tool_name=str(raw["tool_name"]),
        arguments=dict(raw["arguments"]),
    )
    expected_sha = raw.get("sha256")
    if prebound_tool_execution_sha256(binding) != expected_sha:
        raise ValueError("pre-bound execution identity drift")
    if binding.tool_name != EXPECTED_TOOL:
        raise ValueError("pre-bound execution tool drift")
    return binding


def _task_and_prompt() -> tuple[str, str]:
    raw = _load_json(PREFLIGHT_PATH)
    task_contract = raw.get("task_contract")
    prompt = raw.get("prompt")
    if not isinstance(task_contract, str) or not task_contract.strip():
        raise ValueError("frozen preflight task_contract is unavailable")
    if not isinstance(prompt, str) or not prompt.strip():
        raise ValueError("frozen preflight prompt is unavailable")
    return task_contract, prompt


def _build_request(
    *,
    label: str,
    catalog: ToolCatalogSnapshot,
    profile: TransportProfile,
    task_contract: str,
    prompt: str,
) -> OpenAICompatibleRequest:
    manifest = ModelRequestManifest(
        request_id=f"github-status-{label}-live-request-001",
        provider_family=profile.provider_family,
        model=profile.model,
        task_contract_sha256=hashlib.sha256(
            task_contract.encode("utf-8")
        ).hexdigest(),
        catalog=catalog,
        prompt_sha256=hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
    )
    return OpenAICompatibleRequest(
        manifest=manifest,
        prompt=prompt,
        catalog=catalog,
    )


def _validate_frozen_inputs(
    control: ToolCatalogSnapshot,
    treatment: ToolCatalogSnapshot,
) -> dict[str, object]:
    control_sha = tool_catalog_snapshot_sha256(control)
    treatment_sha = tool_catalog_snapshot_sha256(treatment)
    if control_sha != EXPECTED_CONTROL_SHA:
        raise ValueError("control catalog identity drift")
    if treatment_sha != EXPECTED_TREATMENT_SHA:
        raise ValueError("treatment catalog identity drift")

    token_result = _load_json(TOKEN_RESULT_PATH)
    if token_result.get("snapshot_sha256") != control_sha:
        raise ValueError("token result is not bound to control catalog")
    control_bytes = canonical_tool_catalog_bytes(control.descriptors)
    treatment_bytes = canonical_tool_catalog_bytes(treatment.descriptors)
    if token_result.get("baseline_descriptor_count") != len(control.descriptors):
        raise ValueError("token result control descriptor-count drift")
    if token_result.get("treatment_descriptor_count") != len(treatment.descriptors):
        raise ValueError("token result treatment descriptor-count drift")
    if token_result.get("baseline_bytes") != len(control_bytes):
        raise ValueError("token result control byte-count drift")
    if token_result.get("treatment_bytes") != len(treatment_bytes):
        raise ValueError("token result treatment byte-count drift")
    if token_result.get("selected_tools") != [EXPECTED_TOOL]:
        raise ValueError("token result selected-tool identity drift")
    if not isinstance(token_result.get("baseline_tokens"), int):
        raise ValueError("token result control token count unavailable")
    if not isinstance(token_result.get("treatment_tokens"), int):
        raise ValueError("token result treatment token count unavailable")
    return token_result


def _request_summary(prepared: OpenAICompatibleRequest) -> dict[str, object]:
    body = prepared.canonical_body_bytes()
    manifest = prepared.manifest
    mapped = manifest.to_mapping()
    return {
        "request_manifest_sha256": model_request_manifest_sha256(manifest),
        "catalog_sha256": mapped["catalog_sha256"],
        "request_body_sha256": hashlib.sha256(body).hexdigest(),
        "request_body_bytes": len(body),
        "tool_count": mapped["tool_count"],
        "sent": False,
        "provider_request_id": None,
        "provider_model": None,
        "selected_tool": None,
        "latency_ms": None,
        "model_visible_exposure_observed": False,
    }


def _exact_sent_tool_tokens(
    prepared: OpenAICompatibleRequest,
    tokenizer,
) -> int:
    encoding = tokenizer.get_encoding(ENCODING)
    tool_payload = json.dumps(
        prepared.to_mapping()["tools"],
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
    return len(encoding.encode(tool_payload))


def _transport_summary(receipt) -> dict[str, object]:
    return {
        "request_manifest_sha256": receipt.request_manifest_sha256,
        "request_body_sha256": receipt.request_body_sha256,
        "request_body_bytes": receipt.request_body_bytes,
        "tool_count": receipt.tool_count,
        "sent": receipt.sent,
        "http_status": receipt.http_status,
        "provider_request_id": receipt.provider_request_id,
        "provider_model": receipt.provider_model,
        "selected_tool": receipt.selected_tool,
        "latency_ms": receipt.latency_ms,
        "response_sha256": receipt.response_sha256,
        "model_visible_exposure_observed": (
            receipt.model_visible_exposure_observed
        ),
    }


def run_pair(
    *,
    send: bool,
    environ: Mapping[str, str],
    opener: Callable[..., object] = urllib_request.urlopen,
    order: tuple[str, str] = ("control", "treatment"),
    tokenizer=None,
) -> dict[str, object]:
    profile = _load_profile()
    control = _load_catalog(CONTROL_PATH)
    treatment = _load_catalog(TREATMENT_PATH)
    token_result = _validate_frozen_inputs(control, treatment)
    binding = _load_binding()
    task_contract, prompt = _task_and_prompt()

    prepared = {
        "control": _build_request(
            label="control",
            catalog=control,
            profile=profile,
            task_contract=task_contract,
            prompt=prompt,
        ),
        "treatment": _build_request(
            label="treatment",
            catalog=treatment,
            profile=profile,
            task_contract=task_contract,
            prompt=prompt,
        ),
    }

    if set(order) != {"control", "treatment"} or len(order) != 2:
        raise ValueError("order must contain control and treatment exactly once")

    base = {
        "schema": "agent-control-plane.cep-gemini-live-transport-ab.v0-candidate",
        "profile": profile.to_mapping(),
        "task_contract": task_contract,
        "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
        "order": list(order),
        "frozen_catalog_characterization": {
            "encoding": token_result["encoding"],
            "tiktoken_version": token_result["tiktoken_version"],
            "control_catalog_tokens": token_result["baseline_tokens"],
            "treatment_catalog_tokens": token_result["treatment_tokens"],
            "claim_boundary": (
                "Historical canonical-catalog serialization only; not reused as "
                "the live sent-tool token endpoint."
            ),
        },
        "prebound_execution": {
            "binding_id": binding.binding_id,
            "binding_sha256": prebound_tool_execution_sha256(binding),
            "tool_name": binding.tool_name,
            "arguments": dict(binding.arguments),
        },
        "execution_effect": "NONE",
        "routing_effect": "NONE",
        "scientific_n_increment": 0,
        "efficacy_effect": "NONE",
        "independent_validation_effect": "NONE",
        "high_assurance_effect": "NONE",
    }

    if not send:
        return {
            **base,
            "status": "BLOCKED_SEND_NOT_REQUESTED",
            "credential_env": profile.api_key_env,
            "credential_read": False,
            "control": _request_summary(prepared["control"]),
            "treatment": _request_summary(prepared["treatment"]),
            "next_gate": (
                "Explicit --send plus credential, followed by provider/model "
                "identity and valid tool-call evidence for both arms."
            ),
        }

    api_key = environ.get(profile.api_key_env)
    if not isinstance(api_key, str) or not api_key:
        return {
            **base,
            "status": "BLOCKED_CREDENTIAL_NOT_CONFIGURED",
            "credential_env": profile.api_key_env,
            "credential_read": True,
            "control": _request_summary(prepared["control"]),
            "treatment": _request_summary(prepared["treatment"]),
            "next_gate": (
                f"Supply {profile.api_key_env} only in the invoking process "
                "environment; do not write it into repository artifacts."
            ),
        }

    if tokenizer is None:
        try:
            import tiktoken as tokenizer
        except ImportError:
            return {
                **base,
                "status": "BLOCKED_MEASUREMENT_DEPENDENCY_MISSING",
                "credential_env": profile.api_key_env,
                "credential_read": True,
                "required_dependency": "tiktoken==0.14.0",
                "network_request_sent": False,
                "control": _request_summary(prepared["control"]),
                "treatment": _request_summary(prepared["treatment"]),
                "next_gate": (
                    "Install the pinned context-measure dependency before any "
                    "provider request is sent."
                ),
            }

    exact_tool_tokens = {
        arm: _exact_sent_tool_tokens(prepared[arm], tokenizer)
        for arm in ("control", "treatment")
    }

    receipts: dict[str, dict[str, object]] = {}
    for arm in order:
        receipt = send_openai_compatible_request(
            prepared[arm],
            endpoint=profile.endpoint,
            api_key=api_key,
            extra_headers=dict(profile.headers),
            opener=opener,
        )
        receipts[arm] = _transport_summary(receipt)

    control_receipt = receipts["control"]
    treatment_receipt = receipts["treatment"]
    both_observed = bool(
        control_receipt["model_visible_exposure_observed"]
        and treatment_receipt["model_visible_exposure_observed"]
    )
    selected_expected = (
        control_receipt["selected_tool"] == EXPECTED_TOOL
        and treatment_receipt["selected_tool"] == EXPECTED_TOOL
    )

    if not both_observed:
        status = "BLOCKED_DYNAMIC_EXPOSURE_UNOBSERVED"
        next_gate = (
            "Both arms require provider/model identity and a valid returned "
            "tool-call alias from the exact sent catalog."
        )
    elif not selected_expected:
        status = "BLOCKED_SELECTED_TOOL_NOT_PRESERVED"
        next_gate = (
            "Both arms must select the frozen workflow-status tool before "
            "downstream result adjudication."
        )
    else:
        status = "TRANSPORT_PAIR_READY_FOR_RESULT_ADJUDICATION"
        next_gate = (
            "Execute the frozen pre-bound workflow-status observation once, "
            "bind normalized result/evidence/acceptance identically to both "
            "arms, then apply the paired evaluation gate. This status is not "
            "an end-to-end PASS."
        )

    return {
        **base,
        "status": status,
        "credential_env": profile.api_key_env,
        "credential_read": True,
        "control": {
            **control_receipt,
            "catalog_sha256": EXPECTED_CONTROL_SHA,
            "model_visible_tool_tokens": (
                exact_tool_tokens["control"] if both_observed else None
            ),
            "model_visible_tool_token_basis": (
                "TOKENIZED_EXACT_SENT_TOOLS_JSON" if both_observed else None
            ),
        },
        "treatment": {
            **treatment_receipt,
            "catalog_sha256": EXPECTED_TREATMENT_SHA,
            "model_visible_tool_tokens": (
                exact_tool_tokens["treatment"] if both_observed else None
            ),
            "model_visible_tool_token_basis": (
                "TOKENIZED_EXACT_SENT_TOOLS_JSON" if both_observed else None
            ),
        },
        "next_gate": next_gate,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--send",
        action="store_true",
        help="Actually send both frozen requests. Default is dry-run only.",
    )
    parser.add_argument(
        "--treatment-first",
        action="store_true",
        help="Send treatment before control while preserving the same pair.",
    )
    args = parser.parse_args()
    order = (
        ("treatment", "control")
        if args.treatment_first
        else ("control", "treatment")
    )
    result = run_pair(send=args.send, environ=os.environ, order=order)
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] != "BLOCKED_CREDENTIAL_NOT_CONFIGURED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
