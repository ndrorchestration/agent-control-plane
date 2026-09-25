"""Explicit public-key and transport-identity bindings for ACP watermark trust."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
import hashlib
from typing import Dict, Mapping, Optional

from .authority import AuthorityValidationError


AUTHORITY_KEY_BINDING_SCHEMA_VERSION = (
    "agent-control-plane.authority-key-binding.v0-candidate"
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


def _validate_sha256(value: str, field_name: str) -> str:
    if not isinstance(value, str) or len(value) != 64:
        raise AuthorityValidationError(
            f"{field_name} must be a 64-character SHA-256 hex digest"
        )
    try:
        bytes.fromhex(value)
    except ValueError as exc:
        raise AuthorityValidationError(
            f"{field_name} must be hexadecimal"
        ) from exc
    return value.lower()


class AuthorityKeyBindingStatus(str, Enum):
    ACTIVE = "active"
    REVOKED = "revoked"


@dataclass(frozen=True)
class AuthorityKeyBinding:
    binding_id: str
    subject_id: str
    key_id: str
    public_key_sha256: str
    valid_from: str
    transport_identity_sha256: Optional[str] = None
    valid_until: Optional[str] = None
    status: AuthorityKeyBindingStatus = AuthorityKeyBindingStatus.ACTIVE
    revoked_at: Optional[str] = None
    schema_version: str = AUTHORITY_KEY_BINDING_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "binding_id", _required(self.binding_id, "binding_id"))
        object.__setattr__(self, "subject_id", _required(self.subject_id, "subject_id"))
        object.__setattr__(self, "key_id", _required(self.key_id, "key_id"))
        object.__setattr__(
            self,
            "public_key_sha256",
            _validate_sha256(self.public_key_sha256, "public_key_sha256"),
        )
        object.__setattr__(
            self,
            "valid_from",
            _canonical_utc(self.valid_from, "valid_from"),
        )
        if self.transport_identity_sha256 is not None:
            object.__setattr__(
                self,
                "transport_identity_sha256",
                _validate_sha256(
                    self.transport_identity_sha256,
                    "transport_identity_sha256",
                ),
            )
        if self.valid_until is not None:
            canonical_until = _canonical_utc(self.valid_until, "valid_until")
            start = datetime.fromisoformat(self.valid_from.replace("Z", "+00:00"))
            end = datetime.fromisoformat(canonical_until.replace("Z", "+00:00"))
            if end <= start:
                raise AuthorityValidationError("valid_until must be after valid_from")
            object.__setattr__(self, "valid_until", canonical_until)
        if not isinstance(self.status, AuthorityKeyBindingStatus):
            raise AuthorityValidationError(
                "status must be AuthorityKeyBindingStatus"
            )
        if self.revoked_at is not None:
            object.__setattr__(
                self,
                "revoked_at",
                _canonical_utc(self.revoked_at, "revoked_at"),
            )
        if self.status is AuthorityKeyBindingStatus.REVOKED and self.revoked_at is None:
            raise AuthorityValidationError("revoked bindings require revoked_at")
        if self.status is AuthorityKeyBindingStatus.ACTIVE and self.revoked_at is not None:
            raise AuthorityValidationError("active bindings must not have revoked_at")
        if self.schema_version != AUTHORITY_KEY_BINDING_SCHEMA_VERSION:
            raise AuthorityValidationError(
                f"unsupported schema_version: {self.schema_version}"
            )

    def to_dict(self) -> dict[str, object]:
        data = asdict(self)
        data["status"] = self.status.value
        return data


class AuthorityKeyBindingRegistry:
    """Caller-provisioned binding registry for logical subject, key, and transport identity."""

    def __init__(self) -> None:
        self._by_id: Dict[str, AuthorityKeyBinding] = {}
        self._by_subject_key: Dict[tuple[str, str], AuthorityKeyBinding] = {}

    def register(self, binding: AuthorityKeyBinding) -> None:
        if not isinstance(binding, AuthorityKeyBinding):
            raise AuthorityValidationError("binding must be AuthorityKeyBinding")
        prior_id = self._by_id.get(binding.binding_id)
        if prior_id is not None:
            if prior_id == binding:
                return
            raise AuthorityValidationError("authority key binding_id conflict")

        key = (binding.subject_id, binding.key_id)
        prior = self._by_subject_key.get(key)
        if prior is not None and prior != binding:
            raise AuthorityValidationError(
                "authority subject/key binding conflict"
            )
        self._by_id[binding.binding_id] = binding
        self._by_subject_key[key] = binding

    def revoke(
        self,
        *,
        subject_id: str,
        key_id: str,
        revoked_at: str,
    ) -> AuthorityKeyBinding:
        key = (_required(subject_id, "subject_id"), _required(key_id, "key_id"))
        prior = self._by_subject_key.get(key)
        if prior is None:
            raise AuthorityValidationError("unknown authority key binding")
        if prior.status is AuthorityKeyBindingStatus.REVOKED:
            canonical = _canonical_utc(revoked_at, "revoked_at")
            if prior.revoked_at != canonical:
                raise AuthorityValidationError(
                    "authority key binding revocation conflict"
                )
            return prior

        revoked = AuthorityKeyBinding(
            binding_id=prior.binding_id,
            subject_id=prior.subject_id,
            key_id=prior.key_id,
            public_key_sha256=prior.public_key_sha256,
            transport_identity_sha256=prior.transport_identity_sha256,
            valid_from=prior.valid_from,
            valid_until=prior.valid_until,
            status=AuthorityKeyBindingStatus.REVOKED,
            revoked_at=revoked_at,
        )
        self._by_id[prior.binding_id] = revoked
        self._by_subject_key[key] = revoked
        return revoked

    def get(
        self,
        subject_id: str,
        key_id: str,
    ) -> Optional[AuthorityKeyBinding]:
        return self._by_subject_key.get(
            (_required(subject_id, "subject_id"), _required(key_id, "key_id"))
        )

    def verify(
        self,
        *,
        subject_id: str,
        key_id: str,
        public_key_raw: bytes,
        observed_at: str,
        transport_identity_raw: Optional[bytes] = None,
    ) -> AuthorityKeyBinding:
        if not isinstance(public_key_raw, bytes) or not public_key_raw:
            raise AuthorityValidationError("public_key_raw must be non-empty bytes")
        binding = self.get(subject_id, key_id)
        if binding is None:
            raise AuthorityValidationError("authority key binding unknown")
        if binding.status is AuthorityKeyBindingStatus.REVOKED:
            raise AuthorityValidationError("authority key binding revoked")

        observed = datetime.fromisoformat(
            _canonical_utc(observed_at, "observed_at").replace("Z", "+00:00")
        )
        start = datetime.fromisoformat(binding.valid_from.replace("Z", "+00:00"))
        if observed < start:
            raise AuthorityValidationError("authority key binding not yet valid")
        if binding.valid_until is not None:
            end = datetime.fromisoformat(binding.valid_until.replace("Z", "+00:00"))
            if observed >= end:
                raise AuthorityValidationError("authority key binding expired")

        public_digest = hashlib.sha256(public_key_raw).hexdigest()
        if public_digest != binding.public_key_sha256:
            raise AuthorityValidationError("authority public key binding mismatch")

        if binding.transport_identity_sha256 is not None:
            if not isinstance(transport_identity_raw, bytes) or not transport_identity_raw:
                raise AuthorityValidationError(
                    "bound transport identity required"
                )
            transport_digest = hashlib.sha256(transport_identity_raw).hexdigest()
            if transport_digest != binding.transport_identity_sha256:
                raise AuthorityValidationError(
                    "authority transport identity binding mismatch"
                )
        return binding

    def manifest(self) -> dict[str, object]:
        rows = [
            self._by_id[key].to_dict()
            for key in sorted(self._by_id)
        ]
        return {
            "schema": AUTHORITY_KEY_BINDING_SCHEMA_VERSION,
            "binding_count": len(rows),
            "bindings": rows,
        }


def binding_from_public_key(
    *,
    binding_id: str,
    subject_id: str,
    key_id: str,
    public_key_raw: bytes,
    valid_from: str,
    transport_identity_raw: Optional[bytes] = None,
    valid_until: Optional[str] = None,
) -> AuthorityKeyBinding:
    if not isinstance(public_key_raw, bytes) or not public_key_raw:
        raise AuthorityValidationError("public_key_raw must be non-empty bytes")
    if transport_identity_raw is not None and (
        not isinstance(transport_identity_raw, bytes) or not transport_identity_raw
    ):
        raise AuthorityValidationError(
            "transport_identity_raw must be non-empty bytes or None"
        )
    return AuthorityKeyBinding(
        binding_id=binding_id,
        subject_id=subject_id,
        key_id=key_id,
        public_key_sha256=hashlib.sha256(public_key_raw).hexdigest(),
        transport_identity_sha256=(
            hashlib.sha256(transport_identity_raw).hexdigest()
            if transport_identity_raw is not None
            else None
        ),
        valid_from=valid_from,
        valid_until=valid_until,
    )



class BoundEd25519WatermarkVerifier:
    """Verify key/transport binding before delegating Ed25519 signature checks."""

    def __init__(
        self,
        *,
        public_keys: Mapping[tuple[str, str], bytes],
        key_registry,
        binding_registry: AuthorityKeyBindingRegistry,
    ) -> None:
        if not isinstance(public_keys, Mapping):
            raise AuthorityValidationError("public_keys must be a mapping")
        if not isinstance(binding_registry, AuthorityKeyBindingRegistry):
            raise AuthorityValidationError(
                "binding_registry must be AuthorityKeyBindingRegistry"
            )
        from .authority_sync_watermark_ed25519 import (
            Ed25519AuthoritySyncWatermarkVerifier,
        )
        self._public_keys: dict[tuple[str, str], bytes] = {}
        for raw_key, public_key_raw in public_keys.items():
            if not isinstance(raw_key, tuple) or len(raw_key) != 2:
                raise AuthorityValidationError(
                    "public key mapping keys must be (issuer_id, key_id) tuples"
                )
            issuer_id = _required(raw_key[0], "issuer_id")
            key_id = _required(raw_key[1], "key_id")
            if not isinstance(public_key_raw, bytes) or len(public_key_raw) != 32:
                raise AuthorityValidationError(
                    "Ed25519 public keys must be exactly 32 bytes"
                )
            self._public_keys[(issuer_id, key_id)] = public_key_raw
        self.binding_registry = binding_registry
        self.verifier = Ed25519AuthoritySyncWatermarkVerifier(
            public_keys=self._public_keys,
            key_registry=key_registry,
        )

    def verify(
        self,
        envelope,
        *,
        observed_at: str,
        transport_identity_raw: Optional[bytes] = None,
    ):
        issuer_id = envelope.watermark.issuer_id
        key_id = envelope.key_id
        public_key_raw = self._public_keys.get((issuer_id, key_id))
        if public_key_raw is None:
            raise AuthorityValidationError(
                "unknown Ed25519 watermark public key"
            )
        self.binding_registry.verify(
            subject_id=issuer_id,
            key_id=key_id,
            public_key_raw=public_key_raw,
            transport_identity_raw=transport_identity_raw,
            observed_at=observed_at,
        )
        return self.verifier.verify(envelope)
