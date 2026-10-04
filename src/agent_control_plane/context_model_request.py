"""Provider-neutral model request manifests for CEP exposure attestation.

This module proves what tool payload ACP constructed for a model transport. It
does not prove the provider/model received or used that payload unless a transport
receipt is separately attached.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json

from .context_catalog_snapshot import ToolCatalogSnapshot, tool_catalog_snapshot_sha256
from .context_tool_exposure import canonical_tool_catalog_bytes


MODEL_REQUEST_MANIFEST_SCHEMA = "agent-control-plane.model-request-manifest.v0-candidate"
MODEL_REQUEST_RECEIPT_SCHEMA = "agent-control-plane.model-request-receipt.v0-candidate"


def _non_empty(value: str, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value


@dataclass(frozen=True)
class ModelRequestManifest:
    """Canonical manifest of the exact tool payload prepared for model transport."""

    request_id: str
    provider_family: str
    model: str
    task_contract_sha256: str
    catalog: ToolCatalogSnapshot
    prompt_sha256: str

    def __post_init__(self) -> None:
        _non_empty(self.request_id, "request_id")
        _non_empty(self.provider_family, "provider_family")
        _non_empty(self.model, "model")
        _non_empty(self.task_contract_sha256, "task_contract_sha256")
        _non_empty(self.prompt_sha256, "prompt_sha256")
        if not isinstance(self.catalog, ToolCatalogSnapshot):
            raise TypeError("catalog must be ToolCatalogSnapshot")

    def to_mapping(self) -> dict[str, object]:
        tool_bytes = canonical_tool_catalog_bytes(self.catalog.descriptors)
        return {
            "schema": MODEL_REQUEST_MANIFEST_SCHEMA,
            "request_id": self.request_id,
            "provider_family": self.provider_family,
            "model": self.model,
            "task_contract_sha256": self.task_contract_sha256,
            "prompt_sha256": self.prompt_sha256,
            "catalog_sha256": tool_catalog_snapshot_sha256(self.catalog),
            "tool_count": len(self.catalog.descriptors),
            "tool_payload_sha256": hashlib.sha256(tool_bytes).hexdigest(),
            "tool_payload_bytes": len(tool_bytes),
        }


def canonical_model_request_manifest_bytes(manifest: ModelRequestManifest) -> bytes:
    return json.dumps(
        manifest.to_mapping(),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def model_request_manifest_sha256(manifest: ModelRequestManifest) -> str:
    return hashlib.sha256(canonical_model_request_manifest_bytes(manifest)).hexdigest()


@dataclass(frozen=True)
class ModelTransportReceipt:
    """Transport-side acknowledgement for one prepared request manifest."""

    request_manifest_sha256: str
    transport: str
    sent: bool
    provider_request_id: str | None = None
    response_sha256: str | None = None

    def __post_init__(self) -> None:
        _non_empty(self.request_manifest_sha256, "request_manifest_sha256")
        _non_empty(self.transport, "transport")
        if self.provider_request_id is not None:
            _non_empty(self.provider_request_id, "provider_request_id")
        if self.response_sha256 is not None:
            _non_empty(self.response_sha256, "response_sha256")
        if not self.sent and (
            self.provider_request_id is not None or self.response_sha256 is not None
        ):
            raise ValueError("unsent receipt cannot carry provider response identity")

    def to_mapping(self) -> dict[str, object]:
        return {
            "schema": MODEL_REQUEST_RECEIPT_SCHEMA,
            "request_manifest_sha256": self.request_manifest_sha256,
            "transport": self.transport,
            "sent": self.sent,
            "provider_request_id": self.provider_request_id,
            "response_sha256": self.response_sha256,
            "authority_effect": "NONE",
        }
