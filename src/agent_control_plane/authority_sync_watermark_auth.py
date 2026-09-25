"""Bounded HMAC authentication profile for ACP synchronization watermarks."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import hmac
import json
from typing import Mapping

from .authority import AuthorityValidationError
from .authority_sync_watermark import (
    AuthoritySyncWatermark,
    decode_authority_sync_watermark,
    encode_authority_sync_watermark,
)


AUTHENTICATED_WATERMARK_SCHEMA_VERSION = (
    "agent-control-plane.authenticated-authority-sync-watermark.v0-candidate"
)
AUTHENTICATED_WATERMARK_ALGORITHM = "hmac-sha256"


def _required(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise AuthorityValidationError(f"{field_name} must not be blank")
    return value.strip()


def _validate_key(key: bytes) -> bytes:
    if not isinstance(key, bytes) or len(key) < 32:
        raise AuthorityValidationError(
            "HMAC watermark keys must be bytes with length >= 32"
        )
    return key


@dataclass(frozen=True)
class AuthenticatedAuthoritySyncWatermark:
    watermark: AuthoritySyncWatermark
    key_id: str
    algorithm: str
    signature_hex: str
    schema_version: str = AUTHENTICATED_WATERMARK_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.watermark, AuthoritySyncWatermark):
            raise AuthorityValidationError(
                "watermark must be AuthoritySyncWatermark"
            )
        object.__setattr__(self, "key_id", _required(self.key_id, "key_id"))
        if self.algorithm != AUTHENTICATED_WATERMARK_ALGORITHM:
            raise AuthorityValidationError(
                f"unsupported algorithm: {self.algorithm}"
            )
        if (
            not isinstance(self.signature_hex, str)
            or len(self.signature_hex) != 64
        ):
            raise AuthorityValidationError(
                "signature_hex must be a 64-character SHA-256 hex digest"
            )
        try:
            bytes.fromhex(self.signature_hex)
        except ValueError as exc:
            raise AuthorityValidationError(
                "signature_hex must be hexadecimal"
            ) from exc
        if self.schema_version != AUTHENTICATED_WATERMARK_SCHEMA_VERSION:
            raise AuthorityValidationError(
                f"unsupported schema_version: {self.schema_version}"
            )

    def to_dict(self) -> dict[str, object]:
        return {
            "watermark": self.watermark.to_dict(),
            "key_id": self.key_id,
            "algorithm": self.algorithm,
            "signature_hex": self.signature_hex,
            "schema_version": self.schema_version,
        }


def _signature_input(watermark: AuthoritySyncWatermark, key_id: str) -> bytes:
    envelope = {
        "watermark": watermark.to_dict(),
        "key_id": _required(key_id, "key_id"),
        "algorithm": AUTHENTICATED_WATERMARK_ALGORITHM,
        "schema_version": AUTHENTICATED_WATERMARK_SCHEMA_VERSION,
    }
    return json.dumps(
        envelope,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def authenticate_authority_sync_watermark(
    watermark: AuthoritySyncWatermark,
    *,
    key_id: str,
    key: bytes,
) -> AuthenticatedAuthoritySyncWatermark:
    if not isinstance(watermark, AuthoritySyncWatermark):
        raise AuthorityValidationError(
            "watermark must be AuthoritySyncWatermark"
        )
    secret = _validate_key(key)
    signature = hmac.new(
        secret,
        _signature_input(watermark, key_id),
        hashlib.sha256,
    ).hexdigest()
    return AuthenticatedAuthoritySyncWatermark(
        watermark=watermark,
        key_id=key_id,
        algorithm=AUTHENTICATED_WATERMARK_ALGORITHM,
        signature_hex=signature,
    )


def encode_authenticated_authority_sync_watermark(
    envelope: AuthenticatedAuthoritySyncWatermark,
) -> bytes:
    if not isinstance(envelope, AuthenticatedAuthoritySyncWatermark):
        raise AuthorityValidationError(
            "envelope must be AuthenticatedAuthoritySyncWatermark"
        )
    return json.dumps(
        envelope.to_dict(),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def decode_authenticated_authority_sync_watermark(
    payload: bytes | str,
) -> AuthenticatedAuthoritySyncWatermark:
    if isinstance(payload, bytes):
        try:
            text = payload.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise AuthorityValidationError(
                "authenticated watermark payload must be valid UTF-8"
            ) from exc
    elif isinstance(payload, str):
        text = payload
    else:
        raise AuthorityValidationError(
            "authenticated watermark payload must be bytes or str"
        )

    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise AuthorityValidationError(
            "authenticated watermark payload must be valid JSON"
        ) from exc
    if not isinstance(data, Mapping):
        raise AuthorityValidationError(
            "authenticated watermark payload must decode to an object"
        )

    expected = {
        "watermark",
        "key_id",
        "algorithm",
        "signature_hex",
        "schema_version",
    }
    if set(data) != expected:
        raise AuthorityValidationError(
            "authenticated watermark payload keys mismatch"
        )
    watermark_data = data["watermark"]
    if not isinstance(watermark_data, Mapping):
        raise AuthorityValidationError("watermark must be an object")

    watermark = decode_authority_sync_watermark(
        json.dumps(
            dict(watermark_data),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
    )
    return AuthenticatedAuthoritySyncWatermark(
        watermark=watermark,
        key_id=data["key_id"],
        algorithm=data["algorithm"],
        signature_hex=data["signature_hex"],
        schema_version=data["schema_version"],
    )


class HmacAuthoritySyncWatermarkVerifier:
    """Verify origin-authenticated watermarks against explicitly provisioned keys."""

    def __init__(
        self,
        keys: Mapping[tuple[str, str], bytes],
    ) -> None:
        if not isinstance(keys, Mapping):
            raise AuthorityValidationError("keys must be a mapping")
        normalized: dict[tuple[str, str], bytes] = {}
        for raw_key, secret in keys.items():
            if (
                not isinstance(raw_key, tuple)
                or len(raw_key) != 2
            ):
                raise AuthorityValidationError(
                    "key mapping keys must be (issuer_id, key_id) tuples"
                )
            issuer_id = _required(raw_key[0], "issuer_id")
            key_id = _required(raw_key[1], "key_id")
            normalized[(issuer_id, key_id)] = _validate_key(secret)
        self._keys = normalized

    def verify(
        self,
        envelope: AuthenticatedAuthoritySyncWatermark,
    ) -> AuthoritySyncWatermark:
        if not isinstance(envelope, AuthenticatedAuthoritySyncWatermark):
            raise AuthorityValidationError(
                "envelope must be AuthenticatedAuthoritySyncWatermark"
            )
        lookup = (envelope.watermark.issuer_id, envelope.key_id)
        secret = self._keys.get(lookup)
        if secret is None:
            raise AuthorityValidationError(
                "unknown watermark authentication key"
            )
        expected = hmac.new(
            secret,
            _signature_input(envelope.watermark, envelope.key_id),
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(expected, envelope.signature_hex):
            raise AuthorityValidationError(
                "watermark authentication failed"
            )
        return envelope.watermark
