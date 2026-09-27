"""Separate, single-use authorization for a future repository rollback action.

This module never executes rollback. It determines whether one exact rollback
attempt may be considered from an ambiguous, nonterminal recovery state.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import sqlite3

from .remote_mutation_journal import MutationJournalRecord, MutationJournalState
from .remote_mutation_rollback_custody import (
    RollbackCustodyAdmissionRecord,
    RollbackMaterialDescriptor,
    RollbackMode,
)
from .remote_mutation_transaction import MutationPlan

ROLLBACK_AUTHORIZATION_SCHEMA_VERSION = (
    "agent-control-plane.remote-mutation-rollback-authorization.v0-candidate"
)
ROLLBACK_OPERATION_ID = "repo.rollback"


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


@dataclass(frozen=True)
class RollbackCurrentStateObservation:
    target_exists: bool
    content_sha256: str | None

    def __post_init__(self) -> None:
        if self.target_exists:
            if self.content_sha256 is None:
                raise RollbackAuthorizationError(
                    "existing target requires content_sha256"
                )
            _sha256(self.content_sha256, "content_sha256")
        elif self.content_sha256 is not None:
            raise RollbackAuthorizationError(
                "absent target must not carry content_sha256"
            )

    def canonical_bytes(self) -> bytes:
        return json.dumps(
            {
                "content_sha256": self.content_sha256,
                "target_exists": self.target_exists,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")

    @property
    def observation_sha256(self) -> str:
        return hashlib.sha256(self.canonical_bytes()).hexdigest()


@dataclass(frozen=True)
class RemoteMutationRollbackAuthorization:
    authorization_id: str
    rollback_authority_id: str
    rollback_executor_id: str
    transaction_id: str
    request_id: str
    resource_id: str
    original_operation_id: str
    rollback_operation_id: str
    plan_sha256: str
    rollback_descriptor_sha256: str
    custody_ref: str
    current_state_sha256: str
    journal_state: MutationJournalState
    issued_at: str
    expires_at: str
    consumed_at: str | None = None
    execution_enabled: bool = False
    rollback_executed: bool = False
    schema_version: str = ROLLBACK_AUTHORIZATION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        for field in (
            "authorization_id",
            "rollback_authority_id",
            "rollback_executor_id",
            "transaction_id",
            "request_id",
            "resource_id",
            "original_operation_id",
            "rollback_operation_id",
            "custody_ref",
        ):
            object.__setattr__(self, field, _required(getattr(self, field), field))
        if self.rollback_operation_id != ROLLBACK_OPERATION_ID:
            raise RollbackAuthorizationError(
                "rollback_operation_id must be repo.rollback"
            )
        for field in (
            "plan_sha256",
            "rollback_descriptor_sha256",
            "current_state_sha256",
        ):
            _sha256(getattr(self, field), field)
        if self.journal_state not in {
            MutationJournalState.EXECUTION_INTENT_RECORDED,
            MutationJournalState.EXTERNAL_EFFECT_REPORTED,
        }:
            raise RollbackAuthorizationError(
                "rollback authorization requires ambiguous nonterminal journal state"
            )
        issued = _parse_utc(self.issued_at, "issued_at")
        expires = _parse_utc(self.expires_at, "expires_at")
        if expires <= issued:
            raise RollbackAuthorizationError("expires_at must be after issued_at")
        object.__setattr__(self, "issued_at", issued.isoformat().replace("+00:00", "Z"))
        object.__setattr__(
            self, "expires_at", expires.isoformat().replace("+00:00", "Z")
        )
        if self.consumed_at is not None:
            consumed = _parse_utc(self.consumed_at, "consumed_at")
            if consumed < issued or consumed > expires:
                raise RollbackAuthorizationError(
                    "consumed_at must fall within authorization window"
                )
            object.__setattr__(
                self,
                "consumed_at",
                consumed.isoformat().replace("+00:00", "Z"),
            )
        if self.execution_enabled is not False or self.rollback_executed is not False:
            raise RollbackAuthorizationError(
                "rollback authorization cannot enable or claim execution"
            )

    @property
    def consumed(self) -> bool:
        return self.consumed_at is not None


def _safe_current_state(
    plan: MutationPlan,
    descriptor: RollbackMaterialDescriptor,
    observation: RollbackCurrentStateObservation,
) -> bool:
    if descriptor.mode is RollbackMode.DELETE_CREATED_FILE:
        return (
            plan.operation_id == "repo.write_text_file"
            and observation.target_exists
            and observation.content_sha256 == plan.parameters["content_sha256"]
        )
    if descriptor.mode is not RollbackMode.RESTORE_FILE_BYTES:
        return False
    if plan.operation_id == "repo.write_text_file":
        return (
            observation.target_exists
            and observation.content_sha256 == plan.parameters["content_sha256"]
        )
    if plan.operation_id == "repo.delete_file":
        return observation.target_exists is False
    return False


class RemoteMutationRollbackAuthorizationStore:
    """Durable, expiring, single-use rollback authorization store."""

    def __init__(self, database_path: str | Path) -> None:
        self.database_path = str(database_path)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute("""
                CREATE TABLE IF NOT EXISTS remote_mutation_rollback_authorization (
                    authorization_id TEXT PRIMARY KEY,
                    rollback_authority_id TEXT NOT NULL,
                    rollback_executor_id TEXT NOT NULL,
                    transaction_id TEXT NOT NULL,
                    request_id TEXT NOT NULL,
                    resource_id TEXT NOT NULL,
                    original_operation_id TEXT NOT NULL,
                    rollback_operation_id TEXT NOT NULL,
                    plan_sha256 TEXT NOT NULL,
                    rollback_descriptor_sha256 TEXT NOT NULL,
                    custody_ref TEXT NOT NULL,
                    current_state_sha256 TEXT NOT NULL,
                    journal_state TEXT NOT NULL,
                    issued_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    consumed_at TEXT,
                    schema_version TEXT NOT NULL
                )
                """)

    def issue(
        self,
        *,
        authorization_id: str,
        rollback_authority_id: str,
        rollback_executor_id: str,
        plan: MutationPlan,
        descriptor: RollbackMaterialDescriptor,
        custody: RollbackCustodyAdmissionRecord,
        journal: MutationJournalRecord,
        current_state: RollbackCurrentStateObservation,
        issued_at: str,
        expires_at: str,
    ) -> RemoteMutationRollbackAuthorization:
        if not isinstance(plan, MutationPlan):
            raise TypeError("plan must be MutationPlan")
        if not isinstance(descriptor, RollbackMaterialDescriptor):
            raise TypeError("descriptor must be RollbackMaterialDescriptor")
        if not isinstance(custody, RollbackCustodyAdmissionRecord):
            raise TypeError("custody must be RollbackCustodyAdmissionRecord")
        if not isinstance(journal, MutationJournalRecord):
            raise TypeError("journal must be MutationJournalRecord")
        if not isinstance(current_state, RollbackCurrentStateObservation):
            raise TypeError("current_state must be RollbackCurrentStateObservation")
        if journal.current_state not in {
            MutationJournalState.EXECUTION_INTENT_RECORDED,
            MutationJournalState.EXTERNAL_EFFECT_REPORTED,
        }:
            raise RollbackAuthorizationError(
                "journal state is not eligible for rollback authorization"
            )
        if custody.admitted is not True or custody.readback_verified is not True:
            raise RollbackAuthorizationError(
                "rollback custody must be admitted and readback-verified"
            )
        exact = (
            descriptor.operation_id == plan.operation_id
            and descriptor.path == plan.parameters["path"]
            and descriptor.descriptor_sha256 == plan.rollback_sha256
            and custody.request_id == plan.request_id
            and custody.resource_id == plan.resource_id
            and custody.operation_id == plan.operation_id
            and custody.plan_sha256 == plan.plan_sha256
            and custody.descriptor_sha256 == plan.rollback_sha256
            and journal.request_id == plan.request_id
            and journal.resource_id == plan.resource_id
            and journal.operation_id == plan.operation_id
            and journal.plan_sha256 == plan.plan_sha256
            and journal.rollback_descriptor_sha256 == plan.rollback_sha256
            and journal.custody_ref == custody.custody_ref
        )
        if not exact:
            raise RollbackAuthorizationError(
                "rollback records do not match exact original mutation"
            )
        if not _safe_current_state(plan, descriptor, current_state):
            raise RollbackAuthorizationError(
                "current repository state is unsafe for rollback"
            )

        candidate = RemoteMutationRollbackAuthorization(
            authorization_id=_required(authorization_id, "authorization_id"),
            rollback_authority_id=_required(
                rollback_authority_id, "rollback_authority_id"
            ),
            rollback_executor_id=_required(
                rollback_executor_id, "rollback_executor_id"
            ),
            transaction_id=journal.transaction_id,
            request_id=plan.request_id,
            resource_id=plan.resource_id,
            original_operation_id=plan.operation_id,
            rollback_operation_id=ROLLBACK_OPERATION_ID,
            plan_sha256=plan.plan_sha256,
            rollback_descriptor_sha256=plan.rollback_sha256,
            custody_ref=custody.custody_ref,
            current_state_sha256=current_state.observation_sha256,
            journal_state=journal.current_state,
            issued_at=issued_at,
            expires_at=expires_at,
        )
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT * FROM remote_mutation_rollback_authorization "
                "WHERE authorization_id = ?",
                (candidate.authorization_id,),
            ).fetchone()
            if existing is not None:
                current = self._from_row(existing)
                if current != candidate:
                    raise RollbackAuthorizationError(
                        "rollback authorization_id conflict"
                    )
                return current
            connection.execute(
                """INSERT INTO remote_mutation_rollback_authorization (
                    authorization_id, rollback_authority_id, rollback_executor_id,
                    transaction_id, request_id, resource_id, original_operation_id,
                    rollback_operation_id, plan_sha256, rollback_descriptor_sha256,
                    custody_ref, current_state_sha256, journal_state, issued_at,
                    expires_at, consumed_at, schema_version
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?)""",
                (
                    candidate.authorization_id,
                    candidate.rollback_authority_id,
                    candidate.rollback_executor_id,
                    candidate.transaction_id,
                    candidate.request_id,
                    candidate.resource_id,
                    candidate.original_operation_id,
                    candidate.rollback_operation_id,
                    candidate.plan_sha256,
                    candidate.rollback_descriptor_sha256,
                    candidate.custody_ref,
                    candidate.current_state_sha256,
                    candidate.journal_state.value,
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
        current_state_sha256: str,
        now: str,
    ) -> RemoteMutationRollbackAuthorization:
        auth_id = _required(authorization_id, "authorization_id")
        executor = _required(rollback_executor_id, "rollback_executor_id")
        state_hash = _sha256(current_state_sha256, "current_state_sha256")
        now_dt = _parse_utc(now, "now")
        canonical_now = now_dt.isoformat().replace("+00:00", "Z")
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM remote_mutation_rollback_authorization "
                "WHERE authorization_id = ?",
                (auth_id,),
            ).fetchone()
            if row is None:
                raise RollbackAuthorizationError("rollback authorization not found")
            current = self._from_row(row)
            if (
                current.rollback_executor_id != executor
                or current.current_state_sha256 != state_hash
            ):
                raise RollbackAuthorizationError(
                    "rollback authorization binding mismatch"
                )
            if current.consumed:
                raise RollbackAuthorizationError(
                    "rollback authorization already consumed"
                )
            issued = _parse_utc(current.issued_at, "issued_at")
            expires = _parse_utc(current.expires_at, "expires_at")
            if now_dt < issued:
                raise RollbackAuthorizationError(
                    "rollback authorization is not active yet"
                )
            if now_dt > expires:
                raise RollbackAuthorizationError("rollback authorization expired")
            result = connection.execute(
                "UPDATE remote_mutation_rollback_authorization "
                "SET consumed_at = ? "
                "WHERE authorization_id = ? AND consumed_at IS NULL",
                (canonical_now, auth_id),
            )
            if result.rowcount != 1:
                raise RollbackAuthorizationError("rollback authorization consume race")
        consumed = self.get(auth_id)
        assert consumed is not None
        return consumed

    def get(self, authorization_id: str) -> RemoteMutationRollbackAuthorization | None:
        auth_id = _required(authorization_id, "authorization_id")
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM remote_mutation_rollback_authorization "
                "WHERE authorization_id = ?",
                (auth_id,),
            ).fetchone()
        return None if row is None else self._from_row(row)

    @staticmethod
    def _from_row(row: sqlite3.Row) -> RemoteMutationRollbackAuthorization:
        return RemoteMutationRollbackAuthorization(
            authorization_id=row["authorization_id"],
            rollback_authority_id=row["rollback_authority_id"],
            rollback_executor_id=row["rollback_executor_id"],
            transaction_id=row["transaction_id"],
            request_id=row["request_id"],
            resource_id=row["resource_id"],
            original_operation_id=row["original_operation_id"],
            rollback_operation_id=row["rollback_operation_id"],
            plan_sha256=row["plan_sha256"],
            rollback_descriptor_sha256=row["rollback_descriptor_sha256"],
            custody_ref=row["custody_ref"],
            current_state_sha256=row["current_state_sha256"],
            journal_state=MutationJournalState(row["journal_state"]),
            issued_at=row["issued_at"],
            expires_at=row["expires_at"],
            consumed_at=row["consumed_at"],
            schema_version=row["schema_version"],
        )
