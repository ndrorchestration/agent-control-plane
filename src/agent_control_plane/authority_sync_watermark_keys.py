"""Fail-closed lifecycle policy for ACP HMAC watermark authentication keys."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Dict, Mapping, Optional

from .authority import AuthorityValidationError
from .authority_sync_watermark import AuthoritySyncWatermark
from .authority_sync_watermark_auth import (
    AuthenticatedAuthoritySyncWatermark,
    HmacAuthoritySyncWatermarkVerifier,
)


AUTHORITY_SYNC_WATERMARK_KEY_SCHEMA_VERSION = (
    "agent-control-plane.authority-sync-watermark-key.v0-candidate"
)


def _required(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise AuthorityValidationError(f"{field_name} must not be blank")
    return value.strip()


def _utc(value: str, field_name: str) -> datetime:
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
    return parsed.astimezone(timezone.utc)


def _canonical_utc(value: str, field_name: str) -> str:
    return _utc(value, field_name).isoformat().replace("+00:00", "Z")


class WatermarkKeyStatus(str, Enum):
    ACTIVE = "active"
    REVOKED = "revoked"


@dataclass(frozen=True)
class WatermarkAuthenticationKeyRecord:
    issuer_id: str
    key_id: str
    valid_from: str
    valid_until: Optional[str] = None
    status: WatermarkKeyStatus = WatermarkKeyStatus.ACTIVE
    revoked_at: Optional[str] = None
    schema_version: str = AUTHORITY_SYNC_WATERMARK_KEY_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "issuer_id", _required(self.issuer_id, "issuer_id"))
        object.__setattr__(self, "key_id", _required(self.key_id, "key_id"))
        object.__setattr__(
            self,
            "valid_from",
            _canonical_utc(self.valid_from, "valid_from"),
        )
        if self.valid_until is not None:
            canonical_until = _canonical_utc(self.valid_until, "valid_until")
            if _utc(canonical_until, "valid_until") <= _utc(self.valid_from, "valid_from"):
                raise AuthorityValidationError("valid_until must be after valid_from")
            object.__setattr__(self, "valid_until", canonical_until)
        if not isinstance(self.status, WatermarkKeyStatus):
            raise AuthorityValidationError("status must be WatermarkKeyStatus")
        if self.revoked_at is not None:
            object.__setattr__(
                self,
                "revoked_at",
                _canonical_utc(self.revoked_at, "revoked_at"),
            )
        if self.status is WatermarkKeyStatus.REVOKED and self.revoked_at is None:
            raise AuthorityValidationError("revoked keys require revoked_at")
        if self.status is WatermarkKeyStatus.ACTIVE and self.revoked_at is not None:
            raise AuthorityValidationError("active keys must not have revoked_at")
        if self.schema_version != AUTHORITY_SYNC_WATERMARK_KEY_SCHEMA_VERSION:
            raise AuthorityValidationError(
                f"unsupported schema_version: {self.schema_version}"
            )

    def to_dict(self) -> dict[str, object]:
        data = asdict(self)
        data["status"] = self.status.value
        return data


class WatermarkAuthenticationKeyRegistry:
    """Non-secret lifecycle metadata for watermark authentication keys."""

    def __init__(self) -> None:
        self._records: Dict[tuple[str, str], WatermarkAuthenticationKeyRecord] = {}

    def register(self, record: WatermarkAuthenticationKeyRecord) -> None:
        if not isinstance(record, WatermarkAuthenticationKeyRecord):
            raise AuthorityValidationError(
                "record must be WatermarkAuthenticationKeyRecord"
            )
        key = (record.issuer_id, record.key_id)
        prior = self._records.get(key)
        if prior is not None:
            if prior == record:
                return
            raise AuthorityValidationError("watermark key record conflict")
        self._records[key] = record

    def revoke(
        self,
        *,
        issuer_id: str,
        key_id: str,
        revoked_at: str,
    ) -> WatermarkAuthenticationKeyRecord:
        key = (_required(issuer_id, "issuer_id"), _required(key_id, "key_id"))
        prior = self._records.get(key)
        if prior is None:
            raise AuthorityValidationError("unknown watermark authentication key")
        if prior.status is WatermarkKeyStatus.REVOKED:
            candidate = _canonical_utc(revoked_at, "revoked_at")
            if candidate != prior.revoked_at:
                raise AuthorityValidationError("watermark key revocation conflict")
            return prior
        record = WatermarkAuthenticationKeyRecord(
            issuer_id=prior.issuer_id,
            key_id=prior.key_id,
            valid_from=prior.valid_from,
            valid_until=prior.valid_until,
            status=WatermarkKeyStatus.REVOKED,
            revoked_at=revoked_at,
        )
        self._records[key] = record
        return record

    def get(
        self,
        issuer_id: str,
        key_id: str,
    ) -> Optional[WatermarkAuthenticationKeyRecord]:
        return self._records.get(
            (_required(issuer_id, "issuer_id"), _required(key_id, "key_id"))
        )

    def manifest(self) -> dict[str, object]:
        rows = [
            self._records[key].to_dict()
            for key in sorted(self._records)
        ]
        return {
            "schema": AUTHORITY_SYNC_WATERMARK_KEY_SCHEMA_VERSION,
            "key_count": len(rows),
            "keys": rows,
        }


class LifecycleAwareHmacWatermarkVerifier:
    """Apply lifecycle policy before delegating cryptographic verification."""

    def __init__(
        self,
        *,
        verifier: HmacAuthoritySyncWatermarkVerifier,
        key_registry: WatermarkAuthenticationKeyRegistry,
    ) -> None:
        if not isinstance(verifier, HmacAuthoritySyncWatermarkVerifier):
            raise AuthorityValidationError(
                "verifier must be HmacAuthoritySyncWatermarkVerifier"
            )
        if not isinstance(key_registry, WatermarkAuthenticationKeyRegistry):
            raise AuthorityValidationError(
                "key_registry must be WatermarkAuthenticationKeyRegistry"
            )
        self.verifier = verifier
        self.key_registry = key_registry

    def verify(
        self,
        envelope: AuthenticatedAuthoritySyncWatermark,
    ) -> AuthoritySyncWatermark:
        if not isinstance(envelope, AuthenticatedAuthoritySyncWatermark):
            raise AuthorityValidationError(
                "envelope must be AuthenticatedAuthoritySyncWatermark"
            )
        record = self.key_registry.get(
            envelope.watermark.issuer_id,
            envelope.key_id,
        )
        if record is None:
            raise AuthorityValidationError(
                "watermark authentication key lifecycle unknown"
            )
        if record.status is WatermarkKeyStatus.REVOKED:
            raise AuthorityValidationError(
                "watermark authentication key revoked"
            )

        issued_at = _utc(envelope.watermark.issued_at, "issued_at")
        if issued_at < _utc(record.valid_from, "valid_from"):
            raise AuthorityValidationError(
                "watermark authentication key not yet valid"
            )
        if record.valid_until is not None and issued_at >= _utc(
            record.valid_until,
            "valid_until",
        ):
            raise AuthorityValidationError(
                "watermark authentication key expired"
            )
        return self.verifier.verify(envelope)
