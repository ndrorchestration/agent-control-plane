"""Durable single-use authorization for one exact external repository mutation attempt."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import sqlite3

from .remote_mutation_composition import MutationCompositionRecord
from .remote_mutation_journal import MutationJournalRecord, MutationJournalState
from .remote_mutation_path_safety import MutationPathSafetyRecord
from .remote_mutation_rollback_custody import RollbackCustodyAdmissionRecord
from .remote_mutation_transaction import MutationPlan, MutationTransactionReceipt

MUTATION_EXECUTION_AUTHORIZATION_SCHEMA_VERSION = (
    "agent-control-plane.remote-mutation-execution-authorization.v0-candidate"
)


class MutationExecutionAuthorizationError(ValueError):
    pass


def _required(value: str, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise MutationExecutionAuthorizationError(f"{field} must not be blank")
    return value.strip()


def _sha256(value: str, field: str) -> str:
    value = _required(value, field)
    if len(value) != 64 or any(ch not in "0123456789abcdef" for ch in value):
        raise MutationExecutionAuthorizationError(f"{field} must be lowercase sha256")
    return value


def _parse_utc(value: str, field: str) -> datetime:
    raw = _required(value, field)
    candidate = raw[:-1] + "+00:00" if raw.endswith("Z") else raw
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError as exc:
        raise MutationExecutionAuthorizationError(f"{field} must be valid ISO-8601") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise MutationExecutionAuthorizationError(f"{field} must be timezone-aware UTC")
    if parsed.utcoffset() != timedelta(0):
        raise MutationExecutionAuthorizationError(f"{field} must use UTC")
    return parsed.astimezone(timezone.utc)


def _utc(value: str, field: str) -> str:
    return _parse_utc(value, field).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class RemoteMutationExecutionAuthorization:
    authorization_id: str
    executor_id: str
    transaction_id: str
    request_id: str
    authority_id: str
    resource_id: str
    operation_id: str
    plan_sha256: str
    rollback_descriptor_sha256: str
    custody_ref: str
    issued_at: str
    expires_at: str
    consumed_at: str | None = None
    schema_version: str = MUTATION_EXECUTION_AUTHORIZATION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        for field in (
            "authorization_id", "executor_id", "transaction_id", "request_id",
            "authority_id", "resource_id", "operation_id", "custody_ref",
        ):
            object.__setattr__(self, field, _required(getattr(self, field), field))
        for field in ("plan_sha256", "rollback_descriptor_sha256"):
            object.__setattr__(self, field, _sha256(getattr(self, field), field))
        issued = _parse_utc(self.issued_at, "issued_at")
        expires = _parse_utc(self.expires_at, "expires_at")
        if expires <= issued:
            raise MutationExecutionAuthorizationError("expires_at must be after issued_at")
        object.__setattr__(self, "issued_at", issued.isoformat().replace("+00:00", "Z"))
        object.__setattr__(self, "expires_at", expires.isoformat().replace("+00:00", "Z"))
        if self.consumed_at is not None:
            consumed = _parse_utc(self.consumed_at, "consumed_at")
            if consumed < issued or consumed > expires:
                raise MutationExecutionAuthorizationError("consumed_at must fall within authorization window")
            object.__setattr__(self, "consumed_at", consumed.isoformat().replace("+00:00", "Z"))

    @property
    def consumed(self) -> bool:
        return self.consumed_at is not None

    def canonical_bytes(self) -> bytes:
        payload = {
            "authorization_id": self.authorization_id,
            "custody_ref": self.custody_ref,
            "executor_id": self.executor_id,
            "expires_at": self.expires_at,
            "issued_at": self.issued_at,
            "operation_id": self.operation_id,
            "plan_sha256": self.plan_sha256,
            "request_id": self.request_id,
            "resource_id": self.resource_id,
            "rollback_descriptor_sha256": self.rollback_descriptor_sha256,
            "transaction_id": self.transaction_id,
            "authority_id": self.authority_id,
        }
        return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")

    @property
    def authorization_sha256(self) -> str:
        return hashlib.sha256(self.canonical_bytes()).hexdigest()


class RemoteMutationExecutionAuthorizationStore:
    """SQLite-backed exact, expiring, single-use authorization store."""

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
                CREATE TABLE IF NOT EXISTS remote_mutation_execution_authorization (
                    authorization_id TEXT PRIMARY KEY,
                    executor_id TEXT NOT NULL,
                    transaction_id TEXT NOT NULL,
                    request_id TEXT NOT NULL,
                    authority_id TEXT NOT NULL,
                    resource_id TEXT NOT NULL,
                    operation_id TEXT NOT NULL,
                    plan_sha256 TEXT NOT NULL,
                    rollback_descriptor_sha256 TEXT NOT NULL,
                    custody_ref TEXT NOT NULL,
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
        executor_id: str,
        composition: MutationCompositionRecord,
        plan: MutationPlan,
        transaction: MutationTransactionReceipt,
        path_safety: MutationPathSafetyRecord,
        rollback_custody: RollbackCustodyAdmissionRecord,
        journal: MutationJournalRecord,
        issued_at: str,
        expires_at: str,
    ) -> RemoteMutationExecutionAuthorization:
        auth_id = _required(authorization_id, "authorization_id")
        executor = _required(executor_id, "executor_id")
        if not isinstance(composition, MutationCompositionRecord):
            raise TypeError("composition must be MutationCompositionRecord")
        if not isinstance(plan, MutationPlan):
            raise TypeError("plan must be MutationPlan")
        if not isinstance(transaction, MutationTransactionReceipt):
            raise TypeError("transaction must be MutationTransactionReceipt")
        if not isinstance(path_safety, MutationPathSafetyRecord):
            raise TypeError("path_safety must be MutationPathSafetyRecord")
        if not isinstance(rollback_custody, RollbackCustodyAdmissionRecord):
            raise TypeError("rollback_custody must be RollbackCustodyAdmissionRecord")
        if not isinstance(journal, MutationJournalRecord):
            raise TypeError("journal must be MutationJournalRecord")

        if composition.admitted is not True or composition.execution_enabled is not False or composition.mutation_executed is not False:
            raise MutationExecutionAuthorizationError("exact mutation composition must be admitted and non-executing")
        if transaction.preconditions_verified is not True or transaction.rollback_available is not True:
            raise MutationExecutionAuthorizationError("transaction preconditions and rollback must be verified")
        if transaction.execution_enabled is not False or transaction.mutation_executed is not False:
            raise MutationExecutionAuthorizationError("transaction unexpectedly enables execution")
        if path_safety.admitted is not True or path_safety.execution_enabled is not False or path_safety.mutation_executed is not False:
            raise MutationExecutionAuthorizationError("path safety must be admitted and non-executing")
        if rollback_custody.admitted is not True or rollback_custody.readback_verified is not True:
            raise MutationExecutionAuthorizationError("rollback custody must be admitted and readback-verified")
        if rollback_custody.execution_enabled is not False or rollback_custody.mutation_executed is not False:
            raise MutationExecutionAuthorizationError("rollback custody unexpectedly enables execution")
        if journal.current_state is not MutationJournalState.PREPARED:
            raise MutationExecutionAuthorizationError("journal must be PREPARED before authorization issuance")

        exact = (
            composition.request_id == plan.request_id
            and composition.authority_id == plan.authority_id
            and composition.resource_id == plan.resource_id
            and composition.operation_id == plan.operation_id
            and composition.plan_sha256 == plan.plan_sha256
            and transaction.request_id == plan.request_id
            and transaction.authority_id == plan.authority_id
            and transaction.operation_id == plan.operation_id
            and transaction.plan_sha256 == plan.plan_sha256
            and path_safety.request_id == plan.request_id
            and path_safety.resource_id == plan.resource_id
            and path_safety.operation_id == plan.operation_id
            and path_safety.plan_sha256 == plan.plan_sha256
            and rollback_custody.request_id == plan.request_id
            and rollback_custody.resource_id == plan.resource_id
            and rollback_custody.operation_id == plan.operation_id
            and rollback_custody.plan_sha256 == plan.plan_sha256
            and rollback_custody.descriptor_sha256 == plan.rollback_sha256
            and journal.request_id == plan.request_id
            and journal.resource_id == plan.resource_id
            and journal.operation_id == plan.operation_id
            and journal.plan_sha256 == plan.plan_sha256
            and journal.rollback_descriptor_sha256 == plan.rollback_sha256
            and journal.custody_ref == rollback_custody.custody_ref
        )
        if not exact:
            raise MutationExecutionAuthorizationError("pre-execution records do not match exact mutation plan")

        issued = _utc(issued_at, "issued_at")
        expires = _utc(expires_at, "expires_at")
        candidate = RemoteMutationExecutionAuthorization(
            authorization_id=auth_id, executor_id=executor, transaction_id=journal.transaction_id,
            request_id=plan.request_id, authority_id=plan.authority_id, resource_id=plan.resource_id,
            operation_id=plan.operation_id, plan_sha256=plan.plan_sha256,
            rollback_descriptor_sha256=plan.rollback_sha256, custody_ref=rollback_custody.custody_ref,
            issued_at=issued, expires_at=expires,
        )

        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT * FROM remote_mutation_execution_authorization WHERE authorization_id = ?",
                (auth_id,),
            ).fetchone()
            if existing is not None:
                current = self._from_row(existing)
                if current != candidate:
                    raise MutationExecutionAuthorizationError("authorization_id conflict")
                return current
            connection.execute(
                """INSERT INTO remote_mutation_execution_authorization (
                    authorization_id, executor_id, transaction_id, request_id, authority_id,
                    resource_id, operation_id, plan_sha256, rollback_descriptor_sha256,
                    custody_ref, issued_at, expires_at, consumed_at, schema_version
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?)""",
                (
                    candidate.authorization_id, candidate.executor_id, candidate.transaction_id,
                    candidate.request_id, candidate.authority_id, candidate.resource_id,
                    candidate.operation_id, candidate.plan_sha256,
                    candidate.rollback_descriptor_sha256, candidate.custody_ref,
                    candidate.issued_at, candidate.expires_at, candidate.schema_version,
                ),
            )
        return candidate

    def consume(
        self,
        authorization_id: str,
        *,
        executor_id: str,
        transaction_id: str,
        plan_sha256: str,
        now: str,
    ) -> RemoteMutationExecutionAuthorization:
        auth_id = _required(authorization_id, "authorization_id")
        executor = _required(executor_id, "executor_id")
        txid = _required(transaction_id, "transaction_id")
        plan_hash = _sha256(plan_sha256, "plan_sha256")
        now_dt = _parse_utc(now, "now")
        canonical_now = now_dt.isoformat().replace("+00:00", "Z")
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM remote_mutation_execution_authorization WHERE authorization_id = ?",
                (auth_id,),
            ).fetchone()
            if row is None:
                raise MutationExecutionAuthorizationError("authorization not found")
            current = self._from_row(row)
            if current.executor_id != executor or current.transaction_id != txid or current.plan_sha256 != plan_hash:
                raise MutationExecutionAuthorizationError("authorization binding mismatch")
            if current.consumed:
                raise MutationExecutionAuthorizationError("authorization already consumed")
            issued_dt = _parse_utc(current.issued_at, "issued_at")
            expires_dt = _parse_utc(current.expires_at, "expires_at")
            if now_dt < issued_dt:
                raise MutationExecutionAuthorizationError("authorization is not active yet")
            if now_dt > expires_dt:
                raise MutationExecutionAuthorizationError("authorization expired")
            result = connection.execute(
                """UPDATE remote_mutation_execution_authorization
                   SET consumed_at = ?
                   WHERE authorization_id = ? AND consumed_at IS NULL""",
                (canonical_now, auth_id),
            )
            if result.rowcount != 1:
                raise MutationExecutionAuthorizationError("authorization consume race")
        consumed = self.get(auth_id)
        assert consumed is not None
        return consumed

    def get(self, authorization_id: str) -> RemoteMutationExecutionAuthorization | None:
        auth_id = _required(authorization_id, "authorization_id")
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM remote_mutation_execution_authorization WHERE authorization_id = ?",
                (auth_id,),
            ).fetchone()
        return None if row is None else self._from_row(row)

    @staticmethod
    def _from_row(row: sqlite3.Row) -> RemoteMutationExecutionAuthorization:
        return RemoteMutationExecutionAuthorization(
            authorization_id=row["authorization_id"], executor_id=row["executor_id"],
            transaction_id=row["transaction_id"], request_id=row["request_id"],
            authority_id=row["authority_id"], resource_id=row["resource_id"],
            operation_id=row["operation_id"], plan_sha256=row["plan_sha256"],
            rollback_descriptor_sha256=row["rollback_descriptor_sha256"],
            custody_ref=row["custody_ref"], issued_at=row["issued_at"],
            expires_at=row["expires_at"], consumed_at=row["consumed_at"],
            schema_version=row["schema_version"],
        )