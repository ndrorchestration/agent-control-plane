"""Durable fenced ownership leases for ACP supervisor resources."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
from pathlib import Path
import sqlite3

from .authority import AuthorityValidationError


SUPERVISOR_OWNERSHIP_LEASE_SCHEMA_VERSION = (
    "agent-control-plane.supervisor-ownership-lease.v0-candidate"
)


def _required(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise AuthorityValidationError(f"{field_name} must not be blank")
    return value.strip()


def _utc(value: str, field_name: str) -> datetime:
    raw = _required(value, field_name)
    candidate = raw[:-1] + "+00:00" if raw.endswith("Z") else raw
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError as exc:
        raise AuthorityValidationError(
            f"{field_name} must be valid ISO-8601"
        ) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise AuthorityValidationError(
            f"{field_name} must be timezone-aware UTC"
        )
    if parsed.utcoffset() != timedelta(0):
        raise AuthorityValidationError(f"{field_name} must use UTC")
    return parsed.astimezone(timezone.utc)


def _canonical(value: str, field_name: str) -> str:
    return _utc(value, field_name).isoformat().replace("+00:00", "Z")


def _expiry(now: str, ttl_seconds: float) -> str:
    if (
        isinstance(ttl_seconds, bool)
        or not isinstance(ttl_seconds, (int, float))
        or ttl_seconds <= 0
    ):
        raise AuthorityValidationError("ttl_seconds must be > 0")
    expires = _utc(now, "now") + timedelta(seconds=float(ttl_seconds))
    return expires.isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class SupervisorOwnershipLease:
    resource_id: str
    owner_id: str
    ownership_token: str
    fencing_token: int
    acquired_at: str
    renewed_at: str
    expires_at: str
    released_at: str | None = None
    schema_version: str = SUPERVISOR_OWNERSHIP_LEASE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "resource_id", _required(self.resource_id, "resource_id")
        )
        object.__setattr__(
            self, "owner_id", _required(self.owner_id, "owner_id")
        )
        object.__setattr__(
            self,
            "ownership_token",
            _required(self.ownership_token, "ownership_token"),
        )
        if (
            isinstance(self.fencing_token, bool)
            or not isinstance(self.fencing_token, int)
            or self.fencing_token < 1
        ):
            raise AuthorityValidationError(
                "fencing_token must be an integer >= 1"
            )
        object.__setattr__(
            self, "acquired_at", _canonical(self.acquired_at, "acquired_at")
        )
        object.__setattr__(
            self, "renewed_at", _canonical(self.renewed_at, "renewed_at")
        )
        object.__setattr__(
            self, "expires_at", _canonical(self.expires_at, "expires_at")
        )
        if self.released_at is not None:
            object.__setattr__(
                self,
                "released_at",
                _canonical(self.released_at, "released_at"),
            )
        if self.schema_version != SUPERVISOR_OWNERSHIP_LEASE_SCHEMA_VERSION:
            raise AuthorityValidationError(
                f"unsupported schema_version: {self.schema_version}"
            )

    @property
    def active(self) -> bool:
        return self.released_at is None


class SupervisorOwnershipLeaseStore:
    """SQLite-backed ownership lease store with monotonic fencing tokens."""

    def __init__(self, database_path: str | Path) -> None:
        self.database_path = str(database_path)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS supervisor_ownership_lease (
                    resource_id TEXT PRIMARY KEY,
                    owner_id TEXT NOT NULL,
                    ownership_token TEXT NOT NULL,
                    fencing_token INTEGER NOT NULL,
                    acquired_at TEXT NOT NULL,
                    renewed_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    released_at TEXT,
                    schema_version TEXT NOT NULL
                )
                """
            )

    def _row(self, row: sqlite3.Row) -> SupervisorOwnershipLease:
        return SupervisorOwnershipLease(
            resource_id=row["resource_id"],
            owner_id=row["owner_id"],
            ownership_token=row["ownership_token"],
            fencing_token=row["fencing_token"],
            acquired_at=row["acquired_at"],
            renewed_at=row["renewed_at"],
            expires_at=row["expires_at"],
            released_at=row["released_at"],
            schema_version=row["schema_version"],
        )

    def get(self, resource_id: str) -> SupervisorOwnershipLease | None:
        identifier = _required(resource_id, "resource_id")
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM supervisor_ownership_lease
                WHERE resource_id = ?
                """,
                (identifier,),
            ).fetchone()
        return None if row is None else self._row(row)

    def acquire(
        self,
        *,
        resource_id: str,
        owner_id: str,
        ownership_token: str,
        now: str,
        ttl_seconds: float,
    ) -> SupervisorOwnershipLease:
        resource = _required(resource_id, "resource_id")
        owner = _required(owner_id, "owner_id")
        token = _required(ownership_token, "ownership_token")
        canonical_now = _canonical(now, "now")
        expires_at = _expiry(canonical_now, ttl_seconds)

        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT * FROM supervisor_ownership_lease
                WHERE resource_id = ?
                """,
                (resource,),
            ).fetchone()

            if row is None:
                fence = 1
                acquired_at = canonical_now
            else:
                prior = self._row(row)
                now_dt = _utc(canonical_now, "now")
                expired = now_dt >= _utc(prior.expires_at, "expires_at")
                available = prior.released_at is not None or expired

                if not available:
                    if (
                        prior.owner_id == owner
                        and prior.ownership_token == token
                    ):
                        return prior
                    raise AuthorityValidationError(
                        "supervisor ownership lease already held"
                    )

                fence = prior.fencing_token + 1
                acquired_at = canonical_now

            connection.execute(
                """
                INSERT INTO supervisor_ownership_lease (
                    resource_id,
                    owner_id,
                    ownership_token,
                    fencing_token,
                    acquired_at,
                    renewed_at,
                    expires_at,
                    released_at,
                    schema_version
                ) VALUES (?, ?, ?, ?, ?, ?, ?, NULL, ?)
                ON CONFLICT(resource_id) DO UPDATE SET
                    owner_id = excluded.owner_id,
                    ownership_token = excluded.ownership_token,
                    fencing_token = excluded.fencing_token,
                    acquired_at = excluded.acquired_at,
                    renewed_at = excluded.renewed_at,
                    expires_at = excluded.expires_at,
                    released_at = NULL,
                    schema_version = excluded.schema_version
                """,
                (
                    resource,
                    owner,
                    token,
                    fence,
                    acquired_at,
                    canonical_now,
                    expires_at,
                    SUPERVISOR_OWNERSHIP_LEASE_SCHEMA_VERSION,
                ),
            )
        result = self.get(resource)
        assert result is not None
        return result

    def _assert_row_matches(
        self,
        current: SupervisorOwnershipLease,
        lease: SupervisorOwnershipLease,
    ) -> None:
        if (
            current.owner_id != lease.owner_id
            or current.ownership_token != lease.ownership_token
            or current.fencing_token != lease.fencing_token
        ):
            raise AuthorityValidationError(
                "stale supervisor ownership lease"
            )

    def assert_current(
        self,
        lease: SupervisorOwnershipLease,
        *,
        now: str,
    ) -> SupervisorOwnershipLease:
        if not isinstance(lease, SupervisorOwnershipLease):
            raise AuthorityValidationError(
                "lease must be SupervisorOwnershipLease"
            )
        current = self.get(lease.resource_id)
        if current is None:
            raise AuthorityValidationError(
                "supervisor ownership lease missing"
            )
        self._assert_row_matches(current, lease)
        if current.released_at is not None:
            raise AuthorityValidationError(
                "supervisor ownership lease released"
            )
        if _utc(now, "now") >= _utc(current.expires_at, "expires_at"):
            raise AuthorityValidationError(
                "supervisor ownership lease expired"
            )
        return current

    def renew(
        self,
        lease: SupervisorOwnershipLease,
        *,
        now: str,
        ttl_seconds: float,
    ) -> SupervisorOwnershipLease:
        canonical_now = _canonical(now, "now")
        expires_at = _expiry(canonical_now, ttl_seconds)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT * FROM supervisor_ownership_lease
                WHERE resource_id = ?
                """,
                (lease.resource_id,),
            ).fetchone()
            if row is None:
                raise AuthorityValidationError(
                    "supervisor ownership lease missing"
                )
            current = self._row(row)
            self._assert_row_matches(current, lease)
            if current.released_at is not None:
                raise AuthorityValidationError(
                    "supervisor ownership lease released"
                )
            if _utc(canonical_now, "now") >= _utc(
                current.expires_at, "expires_at"
            ):
                raise AuthorityValidationError(
                    "supervisor ownership lease expired"
                )
            connection.execute(
                """
                UPDATE supervisor_ownership_lease
                SET renewed_at = ?, expires_at = ?
                WHERE resource_id = ?
                """,
                (canonical_now, expires_at, lease.resource_id),
            )
        result = self.get(lease.resource_id)
        assert result is not None
        return result

    def release(
        self,
        lease: SupervisorOwnershipLease,
        *,
        released_at: str,
    ) -> SupervisorOwnershipLease:
        canonical = _canonical(released_at, "released_at")
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT * FROM supervisor_ownership_lease
                WHERE resource_id = ?
                """,
                (lease.resource_id,),
            ).fetchone()
            if row is None:
                raise AuthorityValidationError(
                    "supervisor ownership lease missing"
                )
            current = self._row(row)
            self._assert_row_matches(current, lease)
            if current.released_at is not None:
                return current
            connection.execute(
                """
                UPDATE supervisor_ownership_lease
                SET released_at = ?
                WHERE resource_id = ?
                """,
                (canonical, lease.resource_id),
            )
        result = self.get(lease.resource_id)
        assert result is not None
        return result

    def manifest(self) -> dict[str, object]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM supervisor_ownership_lease
                ORDER BY resource_id
                """
            ).fetchall()
        leases = [self._row(row) for row in rows]
        return {
            "schema": SUPERVISOR_OWNERSHIP_LEASE_SCHEMA_VERSION,
            "lease_count": len(leases),
            "leases": [
                {
                    "resource_id": lease.resource_id,
                    "owner_id": lease.owner_id,
                    "ownership_token_sha256": hashlib.sha256(
                        lease.ownership_token.encode("utf-8")
                    ).hexdigest(),
                    "fencing_token": lease.fencing_token,
                    "acquired_at": lease.acquired_at,
                    "renewed_at": lease.renewed_at,
                    "expires_at": lease.expires_at,
                    "released_at": lease.released_at,
                }
                for lease in leases
            ],
        }
