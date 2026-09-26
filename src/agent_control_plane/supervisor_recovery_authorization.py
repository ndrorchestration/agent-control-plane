"""Exact one-time recovery authorization for held ACP supervisor generations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Optional

from .authority import AuthorityValidationError
from .supervisor_runtime_checkpoint import (
    SupervisorPreviousRunDisposition,
    SupervisorRecoveryAssessment,
    SupervisorRuntimeCheckpoint,
)


SUPERVISOR_RECOVERY_AUTHORIZATION_SCHEMA_VERSION = (
    "agent-control-plane.supervisor-recovery-authorization.v0-candidate"
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


def supervisor_checkpoint_sha256(
    checkpoint: SupervisorRuntimeCheckpoint,
) -> str:
    if not isinstance(checkpoint, SupervisorRuntimeCheckpoint):
        raise AuthorityValidationError(
            "checkpoint must be SupervisorRuntimeCheckpoint"
        )
    payload = {
        "service_id": checkpoint.service_id,
        "generation": checkpoint.generation,
        "owner_id": checkpoint.owner_id,
        "fencing_token": checkpoint.fencing_token,
        "state": checkpoint.state.value,
        "stop_reason": (
            None
            if checkpoint.stop_reason is None
            else checkpoint.stop_reason.value
        ),
        "updated_at": checkpoint.updated_at,
        "schema_version": checkpoint.schema_version,
    }
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class SupervisorRecoveryAuthorization:
    authorization_id: str
    service_id: str
    previous_generation: int
    previous_owner_id: str
    previous_fencing_token: int
    previous_checkpoint_sha256: str
    previous_disposition: SupervisorPreviousRunDisposition
    authorized_by: str
    issued_at: str
    expires_at: str
    consumed_at: Optional[str] = None
    schema_version: str = SUPERVISOR_RECOVERY_AUTHORIZATION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        for value, field_name in (
            (self.authorization_id, "authorization_id"),
            (self.service_id, "service_id"),
            (self.previous_owner_id, "previous_owner_id"),
            (self.authorized_by, "authorized_by"),
        ):
            object.__setattr__(
                self,
                field_name,
                _required(value, field_name),
            )
        for value, field_name in (
            (self.previous_generation, "previous_generation"),
            (self.previous_fencing_token, "previous_fencing_token"),
        ):
            if (
                isinstance(value, bool)
                or not isinstance(value, int)
                or value < 1
            ):
                raise AuthorityValidationError(
                    f"{field_name} must be an integer >= 1"
                )
        if (
            not isinstance(self.previous_checkpoint_sha256, str)
            or len(self.previous_checkpoint_sha256) != 64
        ):
            raise AuthorityValidationError(
                "previous_checkpoint_sha256 must be a SHA-256 hex digest"
            )
        try:
            bytes.fromhex(self.previous_checkpoint_sha256)
        except ValueError as exc:
            raise AuthorityValidationError(
                "previous_checkpoint_sha256 must be hexadecimal"
            ) from exc
        if not isinstance(
            self.previous_disposition,
            SupervisorPreviousRunDisposition,
        ):
            raise AuthorityValidationError(
                "previous_disposition must be SupervisorPreviousRunDisposition"
            )
        object.__setattr__(
            self,
            "issued_at",
            _canonical(self.issued_at, "issued_at"),
        )
        object.__setattr__(
            self,
            "expires_at",
            _canonical(self.expires_at, "expires_at"),
        )
        if _utc(self.expires_at, "expires_at") <= _utc(
            self.issued_at,
            "issued_at",
        ):
            raise AuthorityValidationError(
                "expires_at must be after issued_at"
            )
        if self.consumed_at is not None:
            object.__setattr__(
                self,
                "consumed_at",
                _canonical(self.consumed_at, "consumed_at"),
            )
        if (
            self.schema_version
            != SUPERVISOR_RECOVERY_AUTHORIZATION_SCHEMA_VERSION
        ):
            raise AuthorityValidationError(
                f"unsupported schema_version: {self.schema_version}"
            )


class SupervisorRecoveryAuthorizationStore:
    """SQLite-backed exact, expiring, single-use recovery authorization."""

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
                CREATE TABLE IF NOT EXISTS supervisor_recovery_authorization (
                    authorization_id TEXT PRIMARY KEY,
                    service_id TEXT NOT NULL,
                    previous_generation INTEGER NOT NULL,
                    previous_owner_id TEXT NOT NULL,
                    previous_fencing_token INTEGER NOT NULL,
                    previous_checkpoint_sha256 TEXT NOT NULL,
                    previous_disposition TEXT NOT NULL,
                    authorized_by TEXT NOT NULL,
                    issued_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    consumed_at TEXT,
                    schema_version TEXT NOT NULL
                )
                """
            )

    def _row(self, row: sqlite3.Row) -> SupervisorRecoveryAuthorization:
        return SupervisorRecoveryAuthorization(
            authorization_id=row["authorization_id"],
            service_id=row["service_id"],
            previous_generation=row["previous_generation"],
            previous_owner_id=row["previous_owner_id"],
            previous_fencing_token=row["previous_fencing_token"],
            previous_checkpoint_sha256=row[
                "previous_checkpoint_sha256"
            ],
            previous_disposition=SupervisorPreviousRunDisposition(
                row["previous_disposition"]
            ),
            authorized_by=row["authorized_by"],
            issued_at=row["issued_at"],
            expires_at=row["expires_at"],
            consumed_at=row["consumed_at"],
            schema_version=row["schema_version"],
        )

    def get(
        self,
        authorization_id: str,
    ) -> Optional[SupervisorRecoveryAuthorization]:
        identifier = _required(
            authorization_id,
            "authorization_id",
        )
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM supervisor_recovery_authorization
                WHERE authorization_id = ?
                """,
                (identifier,),
            ).fetchone()
        return None if row is None else self._row(row)

    def issue(
        self,
        *,
        authorization_id: str,
        assessment: SupervisorRecoveryAssessment,
        authorized_by: str,
        issued_at: str,
        expires_at: str,
    ) -> SupervisorRecoveryAuthorization:
        identifier = _required(
            authorization_id,
            "authorization_id",
        )
        actor = _required(authorized_by, "authorized_by")
        if not isinstance(assessment, SupervisorRecoveryAssessment):
            raise AuthorityValidationError(
                "assessment must be SupervisorRecoveryAssessment"
            )
        previous = assessment.previous
        if previous is None:
            raise AuthorityValidationError(
                "recovery authorization requires a previous checkpoint"
            )
        if assessment.disposition in (
            SupervisorPreviousRunDisposition.FRESH,
            SupervisorPreviousRunDisposition.CLEAN_STOP,
        ):
            raise AuthorityValidationError(
                "recovery authorization is unnecessary for an allowed clean disposition"
            )

        authorization = SupervisorRecoveryAuthorization(
            authorization_id=identifier,
            service_id=previous.service_id,
            previous_generation=previous.generation,
            previous_owner_id=previous.owner_id,
            previous_fencing_token=previous.fencing_token,
            previous_checkpoint_sha256=supervisor_checkpoint_sha256(
                previous
            ),
            previous_disposition=assessment.disposition,
            authorized_by=actor,
            issued_at=issued_at,
            expires_at=expires_at,
        )

        with self._connect() as connection:
            existing = connection.execute(
                """
                SELECT * FROM supervisor_recovery_authorization
                WHERE authorization_id = ?
                """,
                (identifier,),
            ).fetchone()
            if existing is not None:
                prior = self._row(existing)
                if prior == authorization:
                    return prior
                raise AuthorityValidationError(
                    "recovery authorization_id conflict"
                )
            connection.execute(
                """
                INSERT INTO supervisor_recovery_authorization (
                    authorization_id,
                    service_id,
                    previous_generation,
                    previous_owner_id,
                    previous_fencing_token,
                    previous_checkpoint_sha256,
                    previous_disposition,
                    authorized_by,
                    issued_at,
                    expires_at,
                    consumed_at,
                    schema_version
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?)
                """,
                (
                    authorization.authorization_id,
                    authorization.service_id,
                    authorization.previous_generation,
                    authorization.previous_owner_id,
                    authorization.previous_fencing_token,
                    authorization.previous_checkpoint_sha256,
                    authorization.previous_disposition.value,
                    authorization.authorized_by,
                    authorization.issued_at,
                    authorization.expires_at,
                    authorization.schema_version,
                ),
            )
        result = self.get(identifier)
        assert result is not None
        return result

    def consume(
        self,
        authorization_id: str,
        *,
        assessment: SupervisorRecoveryAssessment,
        now: str,
        allow_terminal_give_up: bool = False,
    ) -> SupervisorRecoveryAuthorization:
        identifier = _required(
            authorization_id,
            "authorization_id",
        )
        if not isinstance(assessment, SupervisorRecoveryAssessment):
            raise AuthorityValidationError(
                "assessment must be SupervisorRecoveryAssessment"
            )
        previous = assessment.previous
        if previous is None:
            raise AuthorityValidationError(
                "recovery authorization requires a previous checkpoint"
            )
        if (
            assessment.disposition
            is SupervisorPreviousRunDisposition.TERMINAL_GIVE_UP
            and not allow_terminal_give_up
        ):
            raise AuthorityValidationError(
                "terminal give-up recovery authorization is disabled"
            )
        canonical_now = _canonical(now, "now")

        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT * FROM supervisor_recovery_authorization
                WHERE authorization_id = ?
                """,
                (identifier,),
            ).fetchone()
            if row is None:
                raise AuthorityValidationError(
                    "recovery authorization not found"
                )
            authorization = self._row(row)
            if authorization.consumed_at is not None:
                raise AuthorityValidationError(
                    "recovery authorization already consumed"
                )
            if _utc(canonical_now, "now") >= _utc(
                authorization.expires_at,
                "expires_at",
            ):
                raise AuthorityValidationError(
                    "recovery authorization expired"
                )

            expected = (
                previous.service_id,
                previous.generation,
                previous.owner_id,
                previous.fencing_token,
                supervisor_checkpoint_sha256(previous),
                assessment.disposition,
            )
            actual = (
                authorization.service_id,
                authorization.previous_generation,
                authorization.previous_owner_id,
                authorization.previous_fencing_token,
                authorization.previous_checkpoint_sha256,
                authorization.previous_disposition,
            )
            if actual != expected:
                raise AuthorityValidationError(
                    "recovery authorization does not match prior checkpoint"
                )

            connection.execute(
                """
                UPDATE supervisor_recovery_authorization
                SET consumed_at = ?
                WHERE authorization_id = ?
                """,
                (canonical_now, identifier),
            )

        result = self.get(identifier)
        assert result is not None
        return result

    def manifest(self) -> dict[str, object]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM supervisor_recovery_authorization
                ORDER BY authorization_id
                """
            ).fetchall()
        records = [self._row(row) for row in rows]
        return {
            "schema": SUPERVISOR_RECOVERY_AUTHORIZATION_SCHEMA_VERSION,
            "authorization_count": len(records),
            "authorizations": [
                {
                    "authorization_id": record.authorization_id,
                    "service_id": record.service_id,
                    "previous_generation": record.previous_generation,
                    "previous_owner_id": record.previous_owner_id,
                    "previous_fencing_token": record.previous_fencing_token,
                    "previous_checkpoint_sha256": (
                        record.previous_checkpoint_sha256
                    ),
                    "previous_disposition": (
                        record.previous_disposition.value
                    ),
                    "authorized_by": record.authorized_by,
                    "issued_at": record.issued_at,
                    "expires_at": record.expires_at,
                    "consumed_at": record.consumed_at,
                }
                for record in records
            ],
        }
