"""Attested OpenAI-compatible HTTP transport for CEP experiments.

This transport is deliberately provider-neutral. It sends an explicit per-request
tool catalog using deterministic aliases and pre-bound execution semantics.

The first CEP A/B does not test argument generation. The model selects a tool
alias; ACP maps that alias to a frozen connector tool whose execution arguments
are bound by the task contract outside the model request.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import time
from typing import Callable
from urllib import request as urllib_request

from .context_catalog_snapshot import ToolCatalogSnapshot, tool_catalog_snapshot_sha256
from .context_model_request import ModelRequestManifest, model_request_manifest_sha256


OPENAI_COMPATIBLE_REQUEST_SCHEMA = (
    "agent-control-plane.openai-compatible-request.v0-candidate"
)
OPENAI_COMPATIBLE_RECEIPT_SCHEMA = (
    "agent-control-plane.openai-compatible-http-receipt.v0-candidate"
)


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _tool_alias(index: int) -> str:
    return f"cep_tool_{index:03d}"


@dataclass(frozen=True)
class OpenAICompatibleRequest:
    """Exact JSON body prepared for one OpenAI-compatible model request."""

    manifest: ModelRequestManifest
    prompt: str
    catalog: ToolCatalogSnapshot

    def __post_init__(self) -> None:
        if not isinstance(self.prompt, str) or not self.prompt.strip():
            raise ValueError("prompt must be non-empty")
        if not isinstance(self.catalog, ToolCatalogSnapshot):
            raise TypeError("catalog must be ToolCatalogSnapshot")
        if tool_catalog_snapshot_sha256(self.catalog) != self.manifest.to_mapping()[
            "catalog_sha256"
        ]:
            raise ValueError("request catalog does not match manifest catalog identity")
        prompt_sha256 = hashlib.sha256(self.prompt.encode("utf-8")).hexdigest()
        if prompt_sha256 != self.manifest.prompt_sha256:
            raise ValueError("request prompt does not match manifest prompt identity")

    def alias_map(self) -> dict[str, str]:
        return {
            _tool_alias(index): descriptor.name
            for index, descriptor in enumerate(self.catalog.descriptors, start=1)
        }

    def to_mapping(self) -> dict[str, object]:
        tools: list[dict[str, object]] = []
        for index, descriptor in enumerate(self.catalog.descriptors, start=1):
            alias = _tool_alias(index)
            tools.append(
                {
                    "type": "function",
                    "function": {
                        "name": alias,
                        "description": (
                            f"Frozen connector tool: {descriptor.name}\n\n"
                            f"{descriptor.schema_text}"
                        ),
                        "parameters": {
                            "type": "object",
                            "properties": {},
                            "additionalProperties": False,
                        },
                    },
                }
            )
        return {
            "model": self.manifest.model,
            "messages": [{"role": "user", "content": self.prompt}],
            "tools": tools,
            "tool_choice": "auto",
        }

    def canonical_body_bytes(self) -> bytes:
        return json.dumps(
            self.to_mapping(),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")


@dataclass(frozen=True)
class OpenAICompatibleHttpReceipt:
    """Transport receipt for the exact HTTP request body sent."""

    request_manifest_sha256: str
    endpoint: str
    request_body_sha256: str
    request_body_bytes: int
    tool_count: int
    sent: bool
    http_status: int | None
    latency_ms: int | None
    provider_request_id: str | None
    provider_model: str | None
    selected_alias: str | None
    selected_tool: str | None
    response_sha256: str | None
    model_visible_exposure_observed: bool

    def to_mapping(self) -> dict[str, object]:
        return {
            "schema": OPENAI_COMPATIBLE_RECEIPT_SCHEMA,
            "request_manifest_sha256": self.request_manifest_sha256,
            "endpoint": self.endpoint,
            "request_body_sha256": self.request_body_sha256,
            "request_body_bytes": self.request_body_bytes,
            "tool_count": self.tool_count,
            "sent": self.sent,
            "http_status": self.http_status,
            "latency_ms": self.latency_ms,
            "provider_request_id": self.provider_request_id,
            "provider_model": self.provider_model,
            "selected_alias": self.selected_alias,
            "selected_tool": self.selected_tool,
            "response_sha256": self.response_sha256,
            "model_visible_exposure_observed": self.model_visible_exposure_observed,
            "authority_effect": "NONE",
        }


def send_openai_compatible_request(
    prepared: OpenAICompatibleRequest,
    *,
    endpoint: str,
    api_key: str | None,
    timeout_seconds: float = 30.0,
    opener: Callable[..., object] = urllib_request.urlopen,
) -> OpenAICompatibleHttpReceipt:
    """Send one exact JSON request and attest only directly observed transport facts.

    Credentials are used only in the Authorization header and are never included in
    request hashes or receipts.
    """

    if not isinstance(endpoint, str) or not endpoint.strip():
        raise ValueError("endpoint must be non-empty")
    body = prepared.canonical_body_bytes()
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    req = urllib_request.Request(
        endpoint,
        data=body,
        headers=headers,
        method="POST",
    )
    started = time.perf_counter()
    try:
        response = opener(req, timeout=timeout_seconds)
        raw = response.read()
        status = getattr(response, "status", None)
    except Exception:
        raise
    elapsed_ms = int((time.perf_counter() - started) * 1000)

    parsed: dict[str, object] = {}
    try:
        candidate = json.loads(raw.decode("utf-8"))
        if isinstance(candidate, dict):
            parsed = candidate
    except (UnicodeDecodeError, json.JSONDecodeError):
        pass

    provider_request_id = parsed.get("id")
    provider_model = parsed.get("model")
    if not isinstance(provider_request_id, str):
        provider_request_id = None
    if not isinstance(provider_model, str):
        provider_model = None

    selected_alias: str | None = None
    try:
        choices = parsed["choices"]
        message = choices[0]["message"]
        tool_calls = message["tool_calls"]
        candidate_alias = tool_calls[0]["function"]["name"]
        if isinstance(candidate_alias, str):
            selected_alias = candidate_alias
    except (KeyError, IndexError, TypeError):
        selected_alias = None

    alias_map = prepared.alias_map()
    selected_tool = alias_map.get(selected_alias) if selected_alias else None

    # Direct model-visible exposure is admitted only when the provider identifies
    # the request/model AND the response contains a tool-call alias from the exact
    # request catalog. The request hash proves what was sent; the tool call proves
    # the model acted on one member of that catalog.
    observed = (
        isinstance(status, int)
        and 200 <= status < 300
        and provider_request_id is not None
        and provider_model is not None
        and selected_tool is not None
    )

    return OpenAICompatibleHttpReceipt(
        request_manifest_sha256=model_request_manifest_sha256(prepared.manifest),
        endpoint=endpoint,
        request_body_sha256=_sha256_bytes(body),
        request_body_bytes=len(body),
        tool_count=len(prepared.catalog.descriptors),
        sent=True,
        http_status=status if isinstance(status, int) else None,
        latency_ms=elapsed_ms,
        provider_request_id=provider_request_id,
        provider_model=provider_model,
        selected_alias=selected_alias,
        selected_tool=selected_tool,
        response_sha256=_sha256_bytes(raw),
        model_visible_exposure_observed=observed,
    )
