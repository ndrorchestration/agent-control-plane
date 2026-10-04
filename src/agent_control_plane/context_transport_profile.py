"""Provider transport profiles for CEP live A/B experiments."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping


TRANSPORT_PROFILE_SCHEMA = "agent-control-plane.transport-profile.v0-candidate"


def _non_empty(value: str, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value


@dataclass(frozen=True)
class TransportProfile:
    """Non-secret provider configuration for an attested model transport."""

    profile_id: str
    provider_family: str
    endpoint: str
    model: str
    api_key_env: str
    headers: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in (
            "profile_id",
            "provider_family",
            "endpoint",
            "model",
            "api_key_env",
        ):
            _non_empty(getattr(self, name), name)
        if not isinstance(self.headers, Mapping):
            raise TypeError("headers must be a mapping")
        for key, value in self.headers.items():
            _non_empty(key, "header name")
            _non_empty(value, "header value")
            if key.lower() == "authorization":
                raise ValueError("transport profile must not contain authorization secrets")

    def to_mapping(self) -> dict[str, object]:
        return {
            "schema": TRANSPORT_PROFILE_SCHEMA,
            "profile_id": self.profile_id,
            "provider_family": self.provider_family,
            "endpoint": self.endpoint,
            "model": self.model,
            "api_key_env": self.api_key_env,
            "headers": dict(sorted(self.headers.items())),
        }
