"""Single-relay envelope for origin-authenticated ACP watermarks."""

from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
from typing import Mapping

from .authority import AuthorityValidationError
from .authority_sync_watermark import (
    AuthoritySyncWatermarkRegistry,
    WatermarkDisposition,
)
from .authority_sync_watermark_auth import (
    HmacAuthoritySyncWatermarkVerifier,
    decode_authenticated_authority_sync_watermark,
)


AUTHORITY_SYNC_WATERMARK_RELAY_SCHEMA_VERSION = (
    "agent-control-plane.authority-sync-watermark-relay.v0-candidate"
)


def _required(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise AuthorityValidationError(f"{field_name} must not be blank")
    return value.strip()


def _canonical_utc(value: str, field_name: str) -> str:
    _required(value, field_name)
    candidate = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError as exc:
        raise AuthorityValidationError(f"{field_name} must be valid ISO-8601") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise AuthorityValidationError(f"{field_name} must be timezone-aware UTC")
    if parsed.utcoffset() != timedelta(0):
        raise AuthorityValidationError(f"{field_name} must use UTC")
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class RelayedAuthenticatedWatermark:
    relay_id: str
    relayed_at: str
    origin_envelope_b64: str
    schema_version: str = AUTHORITY_SYNC_WATERMARK_RELAY_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "relay_id", _required(self.relay_id, "relay_id"))
        object.__setattr__(
            self,
            "relayed_at",
            _canonical_utc(self.relayed_at, "relayed_at"),
        )
        if not isinstance(self.origin_envelope_b64, str) or not self.origin_envelope_b64:
            raise AuthorityValidationError(
                "origin_envelope_b64 must not be blank"
            )
        try:
            base64.b64decode(
                self.origin_envelope_b64.encode("ascii"),
                validate=True,
            )
        except Exception as exc:
            raise AuthorityValidationError(
                "origin_envelope_b64 must be valid base64"
            ) from exc
        if self.schema_version != AUTHORITY_SYNC_WATERMARK_RELAY_SCHEMA_VERSION:
            raise AuthorityValidationError(
                f"unsupported schema_version: {self.schema_version}"
            )

    def origin_payload(self) -> bytes:
        return base64.b64decode(
            self.origin_envelope_b64.encode("ascii"),
            validate=True,
        )

    def to_dict(self) -> dict[str, str]:
        return {
            "relay_id": self.relay_id,
            "relayed_at": self.relayed_at,
            "origin_envelope_b64": self.origin_envelope_b64,
            "schema_version": self.schema_version,
        }


def wrap_authenticated_watermark_for_relay(
    origin_payload: bytes,
    *,
    relay_id: str,
    relayed_at: str,
) -> RelayedAuthenticatedWatermark:
    if not isinstance(origin_payload, bytes) or not origin_payload:
        raise AuthorityValidationError(
            "origin_payload must be non-empty bytes"
        )
    return RelayedAuthenticatedWatermark(
        relay_id=relay_id,
        relayed_at=relayed_at,
        origin_envelope_b64=base64.b64encode(origin_payload).decode("ascii"),
    )


def encode_relayed_authenticated_watermark(
    envelope: RelayedAuthenticatedWatermark,
) -> bytes:
    if not isinstance(envelope, RelayedAuthenticatedWatermark):
        raise AuthorityValidationError(
            "envelope must be RelayedAuthenticatedWatermark"
        )
    return json.dumps(
        envelope.to_dict(),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def decode_relayed_authenticated_watermark(
    payload: bytes | str,
) -> RelayedAuthenticatedWatermark:
    if isinstance(payload, bytes):
        try:
            text = payload.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise AuthorityValidationError(
                "relay payload must be valid UTF-8"
            ) from exc
    elif isinstance(payload, str):
        text = payload
    else:
        raise AuthorityValidationError("relay payload must be bytes or str")
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise AuthorityValidationError(
            "relay payload must be valid JSON"
        ) from exc
    if not isinstance(data, Mapping):
        raise AuthorityValidationError(
            "relay payload must decode to an object"
        )
    expected = {
        "relay_id",
        "relayed_at",
        "origin_envelope_b64",
        "schema_version",
    }
    if set(data) != expected:
        raise AuthorityValidationError("relay payload keys mismatch")
    return RelayedAuthenticatedWatermark(**dict(data))


class RelayedWatermarkAdmission:
    """Final receiver for one relay hop.

    The caller supplies the relay identity observed/authenticated by the
    transport. ACP then requires it to match the declared relay_id, verifies the
    embedded origin-authenticated watermark, and only then applies the original
    watermark to the trusted monotonic registry.
    """

    def __init__(
        self,
        *,
        verifier: HmacAuthoritySyncWatermarkVerifier,
        registry: AuthoritySyncWatermarkRegistry,
    ) -> None:
        if not isinstance(verifier, HmacAuthoritySyncWatermarkVerifier):
            raise AuthorityValidationError(
                "verifier must be HmacAuthoritySyncWatermarkVerifier"
            )
        if not isinstance(registry, AuthoritySyncWatermarkRegistry):
            raise AuthorityValidationError(
                "registry must be AuthoritySyncWatermarkRegistry"
            )
        self.verifier = verifier
        self.registry = registry

    def admit(
        self,
        envelope: RelayedAuthenticatedWatermark,
        *,
        authenticated_relay_id: str,
    ) -> WatermarkDisposition:
        if not isinstance(envelope, RelayedAuthenticatedWatermark):
            raise AuthorityValidationError(
                "envelope must be RelayedAuthenticatedWatermark"
            )
        observed = _required(
            authenticated_relay_id,
            "authenticated_relay_id",
        )
        if observed != envelope.relay_id:
            raise AuthorityValidationError(
                "authenticated relay identity mismatch"
            )

        authenticated_origin = decode_authenticated_authority_sync_watermark(
            envelope.origin_payload()
        )
        watermark = self.verifier.verify(authenticated_origin)
        return self.registry.apply(watermark)
