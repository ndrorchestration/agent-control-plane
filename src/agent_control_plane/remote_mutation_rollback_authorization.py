"""Durable single-use authorization for an exact repository rollback plan.

This module authorizes one named rollback executor identity against one exact
rollback plan only. It does not perform rollback or retrieve custody material.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import sqlite3

from .remote_mutation_rollback_journal import (
    RollbackJournalRecord,
    RollbackJournalState,
)
from .remote_mutation_rollback_plan import RepositoryRollbackPlan
from .remote_mutation_rollback_revalidation import (
    RepositoryRollbackRevalidationRecord,
)

ROLLBACK_AUTHORIZATION_SCHEMA_VERSION = (
    "agent-control-plane.remote-mutation-rollback-authorization.v0-candidate"
)


class RollbackAuthorizationError(ValueError):
    pass


def _required(value: str, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RollbackAuthorizationError(f"{field} must not be blank")
    return value.strip()


def _sha256(value: str, field: str) -> str:
    value = _required(value, field)
    if len(value) != 64 or any(ch not in "0123456789abcdef" for ch in value):
        raise RollbackAuthorizationError(f"{field} must be lowercase sha256")
    return value


def _parse_utc(value: str, field: str) -> datetime:
    raw = _required(value, field)
    candidate = raw[:-1] + "+00:00" if raw.endswith("Z") else raw
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError as exc:
        raise RollbackAuthorizationError(f"{field} must be valid ISO-8601") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise RollbackAuthorizationError(f"{field} must be timezone-aware UTC")
    if parsed.utcoffset() != timedelta(0):
        raise RollbackAuthorizationError(f"{field} must use UTC")
    return parsed.astimezone(timezone.utc)


def _utc(value: str, field: str) -> str:
    return _parse_utc(value, field).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class RepositoryRollbackAuthorization:
    authorization_id: str
    rollback_executor_id: str
    rollback_transaction_id: str
    rollback_request_id: str
    rollback_authority_id: str
    rollback_plan_sha256: str
    original_transaction_id: str
    original_plan_sha256: str
    rollback_descriptor_sha256: str
    rollback_custody_ref: str
    issued_at: str
    expires_at: str
    consumed_at: str | None = None
    rollback_executed: bool = False
    schema_version: str = ROLLBACK_AUTHORIZATION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        for field in (
            "authorization_id",
            "rollback_executor_id",
            "rollback_transaction_id",
            "rollback_request_id",
            "rollback_authority_id",
            "original_transaction_id",
            "rollback_custody_ref",
        ):
            object.__setattr__(self, field, _required(getattr(self, field), field))
        for field in (
            "rollback_plan_sha256",
            "original_plan_sha256",
            "rollback_descriptor_sha256",
        ):
            object.__setattr__(self, field, _sha256(getattr(self, field), field))
        issued = _parse_utc(self.issued_at, "issued_at")
        expires = _parse_utc(self.expires_at, "expires_at")
        if expires <= issued:
            raise RollbackAuthorizationError("expires_at must be after issued_at")
        object.__setattr__(self, "issued_at", issued.isoformat().replace("+00:00", "Z"))
        object.__setattr__(self, "expires_at", expires.isoformat().replace("+00:00", "Z"))
        if self.consumed_at is not None:
            consumed = _parse_utc(self.consumed_at, "consumed_at")
            if consumed < issued or consumed > expires:
                raise RollbackAuthorizationError(
                    "consumed_at must fall within authorization window"
                )
            object.__setattr__(
                self, "consumed_at", consumed.isoformat().replace("+00:00", "Z")
            )
        if self.rollback_executed is not False:
            raise RollbackAuthorizationError(
                "authorization record cannot claim rollback execution"
            )

    @property
    def consumed(self) -> bool:
        return self.consumed_at is not None

    def canonical_bytes(self) -> bytes:
        payload = {
            "authorization_id": self.authorization_id,
            "expires_at": self.expires_at,
            "issued_at": self.issued_at,
            "original_plan_sha256": self.original_plan_sha256,
            "original_transaction_id": self.original_transaction_id,
            "rollback_authority_id": self.rollback_authority_id,
            "rollback_custody_ref": self.rollback_custody_ref,
            "rollback_descriptor_sha256": self.rollback_descriptor_sha256,
            "rollback_executor_id": self.rollback_executor_id,
            "rollback_plan_sha256": self.rollback_plan_sha256,
            "rollback_request_id": self.rollback_request_id,
            "rollback_transaction_id": self.rollback_transaction_id,
        }
        return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")

    @property
    def authorization_sha256(self) -> str:
        return hashlib.sha256(self.canonical_bytes()).hexdigest()


class RepositoryRollbackAuthorizationStore:
    """SQLite-backed exact, expiring, single-use rollback authorization store."""

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
                CREATE TABLE IF NOT EXISTS repository_rollback_authorization (
                    authorization_id TEXT PRIMARY KEY,
                    rollback_executor_id TEXT NOT NULL,
                    rollback_transaction_id TEXT NOT NULL,
                    rollback_request_id TEXT NOT NULL,
                    rollback_authority_id TEXT NOT NULL,
                    rollback_plan_sha256 TEXT NOT NULL,
                    original_transaction_id TEXT NOT NULL,
                    original_plan_sha256 TEXT NOT NULL,
                    rollback_descriptor_sha256 TEXT NOT NULL,
                    rollback_custody_ref TEXT NOT NULL,
                    issued_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    consumed_at TEXT,
                    schema_version TEXT NOT NULL
                )
                """
            )

    def issue(
        self,
        *,
        authorization_id: str,
        rollback_executor_id: str,
        plan: RepositoryRollbackPlan,
        revalidation: RepositoryRollbackRevalidationRecord,
        journal: RollbackJournalRecord,
        issued_at: str,
        expires_at: str,
    ) -> RepositoryRollbackAuthorization:
        if not isinstance(plan, RepositoryRollbackPlan):
            raise TypeError("plan must be RepositoryRollbackPlan")
        if not isinstance(revalidation, RepositoryRollbackRevalidationRecord):
            raise TypeError("revalidation must be RepositoryRollbackRevalidationRecord")
        if not isinstance(journal, RollbackJournalRecord):
            raise TypeError("journal must be RollbackJournalRecord")
        if plan.execution_enabled is not False or plan.rollback_executed is not False:
            raise RollbackAuthorizationError("rollback plan unexpectedly enables execution")
        if revalidation.admitted is not True:
            raise RollbackAuthorizationError("rollback revalidation must be admitted")
        if revalidation.execution_enabled is not False or revalidation.rollback_executed is not False:
            raise RollbackAuthorizationError(
                "rollback revalidation unexpectedly enables execution"
            )
        if journal.current_state is not RollbackJournalState.PREPARED:
            raise RollbackAuthorizationError(
                "rollback journal must be PREPARED before authorization"
            )

        exact = (
            revalidation.rollback_transaction_id == plan.rollback_transaction_id
            and revalidation.rollback_plan_sha256 == plan.rollback_plan_sha256
            and revalidation.resource_id == plan.resource_id
            and revalidation.requested_path == plan.requested_path
            and journal.rollback_transaction_id == plan.rollback_transaction_id
            and journal.rollback_request_id == plan.rollback_request_id
            and journal.rollback_authority_id == plan.rollback_authority_id
            and journal.rollback_plan_sha256 == plan.rollback_plan_sha256
            and journal.original_transaction_id == plan.original_transaction_id
            and journal.original_plan_sha256 == plan.original_plan_sha256
            and journal.rollback_descriptor_sha256 == plan.rollback_descriptor_sha256
            and journal.rollback_custody_ref == plan.rollback_custody_ref
        )
        if not exact:
            raise RollbackAuthorizationError(
                "rollback plan, revalidation, and journal identities diverge"
            )

        candidate = RepositoryRollbackAuthorization(
            authorization_id=_required(authorization_id, "authorization_id"),
            rollback_executor_id=_required(
                rollback_executor_id, "rollback_executor_id"
            ),
            rollback_transaction_id=plan.rollback_transaction_id,
            rollback_request_id=plan.rollback_request_id,
            rollback_authority_id=plan.rollback_authority_id,
            rollback_plan_sha256=plan.rollback_plan_sha256,
            original_transaction_id=plan.original_transaction_id,
            original_plan_sha256=plan.original_plan_sha256,
            rollback_descriptor_sha256=plan.rollback_descriptor_sha256,
            rollback_custody_ref=plan.rollback_custody_ref,
            issued_at=_utc(issued_at, "issued_at"),
            expires_at=_utc(expires_at, "expires_at"),
        )

        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                """
                SELECT * FROM repository_rollback_authorization
                WHERE authorization_id = ?
                """,
                (candidate.authorization_id,),
            ).fetchone()
            if existing is not None:
                current = self._from_row(existing)
                if current != candidate:
                    raise RollbackAuthorizationError("authorization_id conflict")
                return current
            connection.execute(
                """
                INSERT INTO repository_rollback_authorization (
                    authorization_id, rollback_executor_id,
                    rollback_transaction_id, rollback_request_id,
                    rollback_authority_id, rollback_plan_sha256,
                    original_transaction_id, original_plan_sha256,
                    rollback_descriptor_sha256, rollback_custody_ref,
                    issued_at, expires_at, consumed_at, schema_version
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?)
                """,
                (
                    candidate.authorization_id,
                    candidate.rollback_executor_id,
                    candidate.rollback_transaction_id,
                    candidate.rollback_request_id,
                    candidate.rollback_authority_id,
                    candidate.rollback_plan_sha256,
                    candidate.original_transaction_id,
                    candidate.original_plan_sha256,
                    candidate.rollback_descriptor_sha256,
                    candidate.rollback_custody_ref,
                    candidate.issued_at,
                    candidate.expires_at,
                    candidate.schema_version,
                ),
            )
        return candidate

    def consume(
        self,
        authorization_id: str,
        *,
        rollback_executor_id: str,
        rollback_transaction_id: str,
        rollback_plan_sha256: str,
        now: str,
    ) -> RepositoryRollbackAuthorization:
        auth_id = _required(authorization_id, "authorization_id")
        when = _parse_utc(now, "now")
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT * FROM repository_rollback_authorization
                WHERE authorization_id = ?
                """,
                (auth_id,),
            ).fetchone()
            if row is None:
                raise RollbackAuthorizationError("rollback authorization not found")
            current = self._from_row(row)
            if current.consumed:
                raise RollbackAuthorizationError("rollback authorization already consumed")
            if (
                current.rollback_executor_id != _required(
                    rollback_executor_id, "rollback_executor_id"
                )
                or current.rollback_transaction_id != _required(
                    rollback_transaction_id, "rollback_transaction_id"
                )
                or current.rollback_plan_sha256
                != _sha256(rollback_plan_sha256, "rollback_plan_sha256")
            ):
                raise RollbackAuthorizationError(
                    "rollback authorization binding mismatch"
                )
            issued = _parse_utc(current.issued_at, "issued_at")
            expires = _parse_utc(current.expires_at, "expires_at")
            if when < issued:
                raise RollbackAuthorizationError(
                    "rollback authorization is not active yet"
                )
            if when > expires:
                raise RollbackAuthorizationError("rollback authorization expired")
            consumed_at = when.isoformat().replace("+00:00", "Z")
            connection.execute(
                """
                UPDATE repository_rollback_authorization
                SET consumed_at = ?
                WHERE authorization_id = ? AND consumed_at IS NULL
                """,
                (consumed_at, auth_id),
            )
            if connection.total_changes != 1:
                raise RollbackAuthorizationError(
                    "rollback authorization consumption race"
                )
        loaded = self.get(auth_id)
        assert loaded is not None
        return loaded

    def get(self, authorization_id: str) -> RepositoryRollbackAuthorization | None:
        auth_id = _required(authorization_id, "authorization_id")
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM repository_rollback_authorization
                WHERE authorization_id = ?
                """,
                (auth_id,),
            ).fetchone()
        return None if row is None else self._from_row(row)

    @staticmethod
    def _from_row(row: sqlite3.Row) -> RepositoryRollbackAuthorization:
        return RepositoryRollbackAuthorization(
            authorization_id=row["authorization_id"],
            rollback_executor_id=row["rollback_executor_id"],
            rollback_transaction_id=row["rollback_transaction_id"],
            rollback_request_id=row["rollback_request_id"],
            rollback_authority_id=row["rollback_authority_id"],
            rollback_plan_sha256=row["rollback_plan_sha256"],
            original_transaction_id=row["original_transaction_id"],
            original_plan_sha256=row["original_plan_sha256"],
            rollback_descriptor_sha256=row["rollback_descriptor_sha256"],
            rollback_custody_ref=row["rollback_custody_ref"],
            issued_at=row["issued_at"],
            expires_at=row["expires_at"],
            consumed_at=row["consumed_at"],
            schema_version=row["schema_version"],
        )
