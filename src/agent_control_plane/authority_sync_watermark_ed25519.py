"""Optional Ed25519 origin-signature profile for ACP synchronization watermarks."""

from __future__ import annotations

import base64
from dataclasses import dataclass
import json
from typing import Mapping

from .authority import AuthorityValidationError
from .authority_sync_watermark import (
    AuthoritySyncWatermark,
    decode_authority_sync_watermark,
)
from .authority_sync_watermark_keys import (
    WatermarkAuthenticationKeyRegistry,
    WatermarkKeyStatus,
)


ED25519_WATERMARK_SCHEMA_VERSION = (
    "agent-control-plane.ed25519-authority-sync-watermark.v0-candidate"
)
ED25519_WATERMARK_ALGORITHM = "ed25519"


def _required(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise AuthorityValidationError(f"{field_name} must not be blank")
    return value.strip()


def _load_ed25519():
    try:
        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives.asymmetric.ed25519 import (
            Ed25519PrivateKey,
            Ed25519PublicKey,
        )
    except ImportError as exc:
        raise AuthorityValidationError(
            "Ed25519 watermark support requires the 'crypto' extra"
        ) from exc
    return InvalidSignature, Ed25519PrivateKey, Ed25519PublicKey


@dataclass(frozen=True)
class Ed25519AuthenticatedAuthoritySyncWatermark:
    watermark: AuthoritySyncWatermark
    key_id: str
    algorithm: str
    signature_b64: str
    schema_version: str = ED25519_WATERMARK_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.watermark, AuthoritySyncWatermark):
            raise AuthorityValidationError(
                "watermark must be AuthoritySyncWatermark"
            )
        object.__setattr__(self, "key_id", _required(self.key_id, "key_id"))
        if self.algorithm != ED25519_WATERMARK_ALGORITHM:
            raise AuthorityValidationError(
                f"unsupported algorithm: {self.algorithm}"
            )
        if not isinstance(self.signature_b64, str) or not self.signature_b64:
            raise AuthorityValidationError("signature_b64 must not be blank")
        try:
            signature = base64.b64decode(
                self.signature_b64.encode("ascii"),
                validate=True,
            )
        except Exception as exc:
            raise AuthorityValidationError(
                "signature_b64 must be valid base64"
            ) from exc
        if len(signature) != 64:
            raise AuthorityValidationError(
                "Ed25519 signature must be 64 bytes"
            )
        if self.schema_version != ED25519_WATERMARK_SCHEMA_VERSION:
            raise AuthorityValidationError(
                f"unsupported schema_version: {self.schema_version}"
            )

    def to_dict(self) -> dict[str, object]:
        return {
            "watermark": self.watermark.to_dict(),
            "key_id": self.key_id,
            "algorithm": self.algorithm,
            "signature_b64": self.signature_b64,
            "schema_version": self.schema_version,
        }


def _signature_input(
    watermark: AuthoritySyncWatermark,
    key_id: str,
) -> bytes:
    envelope = {
        "watermark": watermark.to_dict(),
        "key_id": _required(key_id, "key_id"),
        "algorithm": ED25519_WATERMARK_ALGORITHM,
        "schema_version": ED25519_WATERMARK_SCHEMA_VERSION,
    }
    return json.dumps(
        envelope,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def sign_authority_sync_watermark_ed25519(
    watermark: AuthoritySyncWatermark,
    *,
    key_id: str,
    private_key_raw: bytes,
) -> Ed25519AuthenticatedAuthoritySyncWatermark:
    if not isinstance(watermark, AuthoritySyncWatermark):
        raise AuthorityValidationError(
            "watermark must be AuthoritySyncWatermark"
        )
    if not isinstance(private_key_raw, bytes) or len(private_key_raw) != 32:
        raise AuthorityValidationError(
            "Ed25519 private_key_raw must be exactly 32 bytes"
        )
    _, PrivateKey, _ = _load_ed25519()
    try:
        private_key = PrivateKey.from_private_bytes(private_key_raw)
        signature = private_key.sign(_signature_input(watermark, key_id))
    except Exception as exc:
        raise AuthorityValidationError(
            "Ed25519 watermark signing failed"
        ) from exc
    return Ed25519AuthenticatedAuthoritySyncWatermark(
        watermark=watermark,
        key_id=key_id,
        algorithm=ED25519_WATERMARK_ALGORITHM,
        signature_b64=base64.b64encode(signature).decode("ascii"),
    )


def encode_ed25519_authority_sync_watermark(
    envelope: Ed25519AuthenticatedAuthoritySyncWatermark,
) -> bytes:
    if not isinstance(envelope, Ed25519AuthenticatedAuthoritySyncWatermark):
        raise AuthorityValidationError(
            "envelope must be Ed25519AuthenticatedAuthoritySyncWatermark"
        )
    return json.dumps(
        envelope.to_dict(),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def decode_ed25519_authority_sync_watermark(
    payload: bytes | str,
) -> Ed25519AuthenticatedAuthoritySyncWatermark:
    if isinstance(payload, bytes):
        try:
            text = payload.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise AuthorityValidationError(
                "Ed25519 watermark payload must be valid UTF-8"
            ) from exc
    elif isinstance(payload, str):
        text = payload
    else:
        raise AuthorityValidationError(
            "Ed25519 watermark payload must be bytes or str"
        )
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise AuthorityValidationError(
            "Ed25519 watermark payload must be valid JSON"
        ) from exc
    if not isinstance(data, Mapping):
        raise AuthorityValidationError(
            "Ed25519 watermark payload must decode to an object"
        )
    expected = {
        "watermark",
        "key_id",
        "algorithm",
        "signature_b64",
        "schema_version",
    }
    if set(data) != expected:
        raise AuthorityValidationError(
            "Ed25519 watermark payload keys mismatch"
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
    return Ed25519AuthenticatedAuthoritySyncWatermark(
        watermark=watermark,
        key_id=data["key_id"],
        algorithm=data["algorithm"],
        signature_b64=data["signature_b64"],
        schema_version=data["schema_version"],
    )


class Ed25519AuthoritySyncWatermarkVerifier:
    """Verify origin signatures against public keys and lifecycle metadata."""

    def __init__(
        self,
        *,
        public_keys: Mapping[tuple[str, str], bytes],
        key_registry: WatermarkAuthenticationKeyRegistry,
    ) -> None:
        if not isinstance(public_keys, Mapping):
            raise AuthorityValidationError("public_keys must be a mapping")
        if not isinstance(key_registry, WatermarkAuthenticationKeyRegistry):
            raise AuthorityValidationError(
                "key_registry must be WatermarkAuthenticationKeyRegistry"
            )
        normalized: dict[tuple[str, str], bytes] = {}
        for raw_key, public_key_raw in public_keys.items():
            if not isinstance(raw_key, tuple) or len(raw_key) != 2:
                raise AuthorityValidationError(
                    "public key mapping keys must be (issuer_id, key_id) tuples"
                )
            issuer_id = _required(raw_key[0], "issuer_id")
            key_id = _required(raw_key[1], "key_id")
            if (
                not isinstance(public_key_raw, bytes)
                or len(public_key_raw) != 32
            ):
                raise AuthorityValidationError(
                    "Ed25519 public keys must be exactly 32 bytes"
                )
            normalized[(issuer_id, key_id)] = public_key_raw
        self._public_keys = normalized
        self.key_registry = key_registry

    def verify(
        self,
        envelope: Ed25519AuthenticatedAuthoritySyncWatermark,
    ) -> AuthoritySyncWatermark:
        if not isinstance(envelope, Ed25519AuthenticatedAuthoritySyncWatermark):
            raise AuthorityValidationError(
                "envelope must be Ed25519AuthenticatedAuthoritySyncWatermark"
            )
        lookup = (envelope.watermark.issuer_id, envelope.key_id)
        record = self.key_registry.get(*lookup)
        if record is None:
            raise AuthorityValidationError(
                "watermark authentication key lifecycle unknown"
            )
        if record.status is WatermarkKeyStatus.REVOKED:
            raise AuthorityValidationError(
                "watermark authentication key revoked"
            )

        from datetime import datetime

        issued_at = datetime.fromisoformat(
            envelope.watermark.issued_at.replace("Z", "+00:00")
        )
        valid_from = datetime.fromisoformat(
            record.valid_from.replace("Z", "+00:00")
        )
        if issued_at < valid_from:
            raise AuthorityValidationError(
                "watermark authentication key not yet valid"
            )
        if record.valid_until is not None:
            valid_until = datetime.fromisoformat(
                record.valid_until.replace("Z", "+00:00")
            )
            if issued_at >= valid_until:
                raise AuthorityValidationError(
                    "watermark authentication key expired"
                )

        public_key_raw = self._public_keys.get(lookup)
        if public_key_raw is None:
            raise AuthorityValidationError(
                "unknown Ed25519 watermark public key"
            )

        InvalidSignature, _, PublicKey = _load_ed25519()
        try:
            PublicKey.from_public_bytes(public_key_raw).verify(
                base64.b64decode(envelope.signature_b64.encode("ascii")),
                _signature_input(envelope.watermark, envelope.key_id),
            )
        except InvalidSignature as exc:
            raise AuthorityValidationError(
                "Ed25519 watermark signature verification failed"
            ) from exc
        except Exception as exc:
            raise AuthorityValidationError(
                "Ed25519 watermark verification failed"
            ) from exc
        return envelope.watermark
