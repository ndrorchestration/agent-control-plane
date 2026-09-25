"""Candidate authority-state cache for disconnected/stale authority handling."""

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
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


class AuthorityStateStatus(str, Enum):
    CURRENT = "current"
    MISSING = "missing"
    STALE_EPOCH = "stale_epoch"
    STALE_AGE = "stale_age"
    FUTURE_STATE = "future_state"


@dataclass(frozen=True)
class AuthorityStateSnapshot:
    authority_id: str
    epoch: int
    issued_at: str
    source_id: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "authority_id", _required(self.authority_id, "authority_id"))
        if isinstance(self.epoch, bool) or not isinstance(self.epoch, int) or self.epoch < 0:
            raise AuthorityValidationError("epoch must be an integer >= 0")
        object.__setattr__(self, "issued_at", _canonical_utc(self.issued_at, "issued_at"))
        object.__setattr__(self, "source_id", _required(self.source_id, "source_id"))

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class AuthorityStateRequirement:
    min_epoch: int
    max_age_seconds: int

    def __post_init__(self) -> None:
        if isinstance(self.min_epoch, bool) or not isinstance(self.min_epoch, int) or self.min_epoch < 0:
            raise AuthorityValidationError("min_epoch must be an integer >= 0")
        if isinstance(self.max_age_seconds, bool) or not isinstance(self.max_age_seconds, int) or self.max_age_seconds < 0:
            raise AuthorityValidationError("max_age_seconds must be an integer >= 0")


@dataclass(frozen=True)
class AuthorityStateEvaluation:
    status: AuthorityStateStatus
    authority_id: str
    observed_at: str
    required_min_epoch: int
    max_age_seconds: int
    observed_epoch: int | None = None
    issued_at: str | None = None
    source_id: str | None = None

    @property
    def current(self) -> bool:
        return self.status is AuthorityStateStatus.CURRENT


class InMemoryAuthorityStateCache:
    """Monotonic in-memory authority snapshots for local partition/staleness tests."""

    def __init__(self) -> None:
        self._snapshots: Dict[str, AuthorityStateSnapshot] = {}

    def update(self, snapshot: AuthorityStateSnapshot) -> None:
        if not isinstance(snapshot, AuthorityStateSnapshot):
            raise AuthorityValidationError("snapshot must be AuthorityStateSnapshot")
        existing = self._snapshots.get(snapshot.authority_id)
        if existing is not None:
            if snapshot.epoch < existing.epoch:
                raise AuthorityValidationError("authority state epoch regression")
            if snapshot.epoch == existing.epoch and snapshot != existing:
                raise AuthorityValidationError("conflicting authority state at same epoch")
            if snapshot.epoch == existing.epoch:
                return
        self._snapshots[snapshot.authority_id] = snapshot

    def get(self, authority_id: str) -> AuthorityStateSnapshot | None:
        return self._snapshots.get(_required(authority_id, "authority_id"))

    def evaluate(
        self,
        authority_id: str,
        observed_at: str,
        requirement: AuthorityStateRequirement,
    ) -> AuthorityStateEvaluation:
        authority = _required(authority_id, "authority_id")
        if not isinstance(requirement, AuthorityStateRequirement):
            raise AuthorityValidationError("requirement must be AuthorityStateRequirement")
        observed_canonical = _canonical_utc(observed_at, "observed_at")
        observed_dt = _parse_utc(observed_canonical, "observed_at")
        snapshot = self._snapshots.get(authority)
        if snapshot is None:
            return AuthorityStateEvaluation(
                AuthorityStateStatus.MISSING, authority, observed_canonical,
                requirement.min_epoch, requirement.max_age_seconds,
            )
        issued_dt = _parse_utc(snapshot.issued_at, "issued_at")
        if issued_dt > observed_dt:
            status = AuthorityStateStatus.FUTURE_STATE
        elif snapshot.epoch < requirement.min_epoch:
            status = AuthorityStateStatus.STALE_EPOCH
        elif (observed_dt - issued_dt).total_seconds() > requirement.max_age_seconds:
            status = AuthorityStateStatus.STALE_AGE
        else:
            status = AuthorityStateStatus.CURRENT
        return AuthorityStateEvaluation(
            status=status,
            authority_id=authority,
            observed_at=observed_canonical,
            required_min_epoch=requirement.min_epoch,
            max_age_seconds=requirement.max_age_seconds,
            observed_epoch=snapshot.epoch,
            issued_at=snapshot.issued_at,
            source_id=snapshot.source_id,
        )

    def manifest(self) -> dict[str, object]:
        snapshots = [self._snapshots[key].to_dict() for key in sorted(self._snapshots)]
        return {
            "schema": "agent-control-plane.authority-state.v0-candidate",
            "snapshot_count": len(snapshots),
            "snapshots": snapshots,
        }
