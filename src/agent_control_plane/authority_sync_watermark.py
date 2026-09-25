"""Transport-neutral synchronization watermark records for ACP authority recovery."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
import json
from typing import Dict, Mapping, Optional, Set, Tuple

from .authority import AuthorityValidationError


AUTHORITY_SYNC_WATERMARK_SCHEMA_VERSION = "agent-control-plane.authority-sync-watermark.v0-candidate"


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


class WatermarkDisposition(str, Enum):
    APPLIED = "applied"
    DUPLICATE = "duplicate"


@dataclass(frozen=True)
class AuthoritySyncWatermark:
    watermark_id: str
    issuer_id: str
    target_sender_id: str
    min_sequence: int
    issued_at: str
    schema_version: str = AUTHORITY_SYNC_WATERMARK_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "watermark_id", _required(self.watermark_id, "watermark_id"))
        object.__setattr__(self, "issuer_id", _required(self.issuer_id, "issuer_id"))
        object.__setattr__(self, "target_sender_id", _required(self.target_sender_id, "target_sender_id"))
        if isinstance(self.min_sequence, bool) or not isinstance(self.min_sequence, int) or self.min_sequence < 0:
            raise AuthorityValidationError("min_sequence must be an integer >= 0")
        object.__setattr__(self, "issued_at", _canonical_utc(self.issued_at, "issued_at"))
        if self.schema_version != AUTHORITY_SYNC_WATERMARK_SCHEMA_VERSION:
            raise AuthorityValidationError(f"unsupported schema_version: {self.schema_version}")

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class AuthoritySyncWatermarkAcknowledgement:
    watermark_id: str
    issuer_id: str
    receiver_id: str
    target_sender_id: str
    min_sequence: int
    disposition: WatermarkDisposition
    schema_version: str = AUTHORITY_SYNC_WATERMARK_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "watermark_id", _required(self.watermark_id, "watermark_id"))
        object.__setattr__(self, "issuer_id", _required(self.issuer_id, "issuer_id"))
        object.__setattr__(self, "receiver_id", _required(self.receiver_id, "receiver_id"))
        object.__setattr__(self, "target_sender_id", _required(self.target_sender_id, "target_sender_id"))
        if isinstance(self.min_sequence, bool) or not isinstance(self.min_sequence, int) or self.min_sequence < 0:
            raise AuthorityValidationError("min_sequence must be an integer >= 0")
        if not isinstance(self.disposition, WatermarkDisposition):
            raise AuthorityValidationError("disposition must be WatermarkDisposition")
        if self.schema_version != AUTHORITY_SYNC_WATERMARK_SCHEMA_VERSION:
            raise AuthorityValidationError(f"unsupported schema_version: {self.schema_version}")

    def to_dict(self) -> dict[str, object]:
        data = asdict(self)
        data["disposition"] = self.disposition.value
        return data


def _decode_json_object(payload: bytes | str, context: str) -> Mapping[str, object]:
    if isinstance(payload, bytes):
        try:
            text = payload.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise AuthorityValidationError(f"{context} must be valid UTF-8") from exc
    elif isinstance(payload, str):
        text = payload
    else:
        raise AuthorityValidationError(f"{context} must be bytes or str")
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise AuthorityValidationError(f"{context} must be valid JSON") from exc
    if not isinstance(data, Mapping):
        raise AuthorityValidationError(f"{context} must decode to an object")
    return data


def encode_authority_sync_watermark(watermark: AuthoritySyncWatermark) -> bytes:
    if not isinstance(watermark, AuthoritySyncWatermark):
        raise AuthorityValidationError("watermark must be AuthoritySyncWatermark")
    return json.dumps(
        watermark.to_dict(),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def decode_authority_sync_watermark(payload: bytes | str) -> AuthoritySyncWatermark:
    data = _decode_json_object(payload, "watermark payload")
    expected = {
        "watermark_id",
        "issuer_id",
        "target_sender_id",
        "min_sequence",
        "issued_at",
        "schema_version",
    }
    if set(data) != expected:
        raise AuthorityValidationError("watermark payload keys mismatch")
    return AuthoritySyncWatermark(**dict(data))


def encode_authority_sync_watermark_acknowledgement(
    acknowledgement: AuthoritySyncWatermarkAcknowledgement,
) -> bytes:
    if not isinstance(acknowledgement, AuthoritySyncWatermarkAcknowledgement):
        raise AuthorityValidationError(
            "acknowledgement must be AuthoritySyncWatermarkAcknowledgement"
        )
    return json.dumps(
        acknowledgement.to_dict(),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def decode_authority_sync_watermark_acknowledgement(
    payload: bytes | str,
) -> AuthoritySyncWatermarkAcknowledgement:
    data = _decode_json_object(payload, "watermark acknowledgement payload")
    expected = {
        "watermark_id",
        "issuer_id",
        "receiver_id",
        "target_sender_id",
        "min_sequence",
        "disposition",
        "schema_version",
    }
    if set(data) != expected:
        raise AuthorityValidationError("watermark acknowledgement keys mismatch")
    try:
        disposition = WatermarkDisposition(data["disposition"])
    except ValueError as exc:
        raise AuthorityValidationError("invalid watermark disposition") from exc
    values = dict(data)
    values["disposition"] = disposition
    return AuthoritySyncWatermarkAcknowledgement(**values)


class AuthoritySyncWatermarkRegistry:
    """Monotonic trusted watermark registry.

    Trust is explicitly configured as target sender -> allowed watermark issuers.
    Watermarks can raise a local required sequence floor but never lower it.
    """

    def __init__(self, trusted_issuers: Mapping[str, Set[str] | tuple[str, ...] | list[str]]) -> None:
        if not isinstance(trusted_issuers, Mapping):
            raise AuthorityValidationError("trusted_issuers must be a mapping")
        normalized: Dict[str, frozenset[str]] = {}
        for target_sender_id, issuers in trusted_issuers.items():
            target = _required(target_sender_id, "target_sender_id")
            if not isinstance(issuers, (set, tuple, list)) or not issuers:
                raise AuthorityValidationError("trusted issuer sets must not be empty")
            normalized[target] = frozenset(_required(i, "issuer_id") for i in issuers)
        self._trusted_issuers = normalized
        self._watermarks: Dict[Tuple[str, str], AuthoritySyncWatermark] = {}
        self._ids: Dict[str, AuthoritySyncWatermark] = {}

    def apply(self, watermark: AuthoritySyncWatermark) -> WatermarkDisposition:
        if not isinstance(watermark, AuthoritySyncWatermark):
            raise AuthorityValidationError("watermark must be AuthoritySyncWatermark")
        trusted = self._trusted_issuers.get(watermark.target_sender_id)
        if trusted is None or watermark.issuer_id not in trusted:
            raise AuthorityValidationError("untrusted authority sync watermark issuer")

        prior_id = self._ids.get(watermark.watermark_id)
        if prior_id is not None:
            if prior_id != watermark:
                raise AuthorityValidationError("watermark_id conflict")
            return WatermarkDisposition.DUPLICATE

        key = (watermark.target_sender_id, watermark.issuer_id)
        prior = self._watermarks.get(key)
        if prior is not None:
            if watermark.min_sequence < prior.min_sequence:
                raise AuthorityValidationError("authority sync watermark regression")
            if watermark.min_sequence == prior.min_sequence and watermark != prior:
                raise AuthorityValidationError("conflicting authority sync watermark at same sequence")
        self._watermarks[key] = watermark
        self._ids[watermark.watermark_id] = watermark
        return WatermarkDisposition.APPLIED

    def required_sequence(self, target_sender_id: str) -> Optional[int]:
        target = _required(target_sender_id, "target_sender_id")
        relevant = [
            item.min_sequence
            for (sender, _issuer), item in self._watermarks.items()
            if sender == target
        ]
        return max(relevant) if relevant else None

    def manifest(self) -> dict[str, object]:
        rows = [
            self._watermarks[key].to_dict()
            for key in sorted(self._watermarks)
        ]
        return {
            "schema": AUTHORITY_SYNC_WATERMARK_SCHEMA_VERSION,
            "watermark_count": len(rows),
            "watermarks": rows,
        }
