"""In-memory append-only revocation records for candidate ACP authority envelopes."""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Dict

from .authority import AuthorityValidationError


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


def _parse_utc(value: str, field_name: str) -> datetime:
    canonical = _canonical_utc(value, field_name)
    return datetime.fromisoformat(canonical[:-1] + "+00:00")


@dataclass(frozen=True)
class RevocationRecord:
    authority_id: str
    revoked_at: str
    reason_code: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "authority_id", _required(self.authority_id, "authority_id"))
        object.__setattr__(self, "revoked_at", _canonical_utc(self.revoked_at, "revoked_at"))
        object.__setattr__(self, "reason_code", _required(self.reason_code, "reason_code"))

    def to_dict(self) -> dict[str, str]:
        return {
            "authority_id": self.authority_id,
            "revoked_at": self.revoked_at,
            "reason_code": self.reason_code,
        }


class InMemoryRevocationRegistry:
    """Append-only per-authority revocation state for local deterministic checks."""

    def __init__(self) -> None:
        self._records: Dict[str, RevocationRecord] = {}

    def revoke(self, record: RevocationRecord) -> None:
        if not isinstance(record, RevocationRecord):
            raise AuthorityValidationError("record must be RevocationRecord")
        existing = self._records.get(record.authority_id)
        if existing is not None:
            if existing != record:
                raise AuthorityValidationError("authority already revoked with a different record")
            return
        self._records[record.authority_id] = record

    def get(self, authority_id: str) -> RevocationRecord | None:
        return self._records.get(_required(authority_id, "authority_id"))

    def is_revoked_at(self, authority_id: str, utc_timestamp: str) -> bool:
        record = self.get(authority_id)
        if record is None:
            return False
        observed = _parse_utc(utc_timestamp, "utc_timestamp")
        revoked = _parse_utc(record.revoked_at, "revoked_at")
        return observed >= revoked

    def manifest(self) -> dict[str, object]:
        records = [self._records[key].to_dict() for key in sorted(self._records)]
        return {
            "schema": "agent-control-plane.revocation.v0-candidate",
            "record_count": len(records),
            "records": records,
        }
