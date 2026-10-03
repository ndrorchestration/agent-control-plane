"""Durable local lineage for bounded disposable-repository mutation execution.

The store is a fail-closed local control for the BOUNDED_LOCAL_TEST profile.
It does not authorize execution and does not establish a distributed/global
resource lineage oracle.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import sqlite3

from .remote_mutation_execution_closure import MutationExecutionClosureRecord

MUTATION_LINEAGE_SCHEMA_VERSION = (
    "agent-control-plane.remote-mutation-lineage.v0-bounded-local-test"
)

STATE_PENDING = "PENDING_EFFECT"
STATE_TERMINAL = "TERMINAL"
STATE_ABORTED_PRE_EXECUTION = "ABORTED_PRE_EXECUTION"
STATE_RECOVERY_HOLD = "RECOVERY_HOLD"


class MutationLineageError(ValueError):
    pass


def _required(value: str, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise MutationLineageError(f"{field} must not be blank")
    return value.strip()


def _sha256(value: str, field: str) -> str:
    value = _required(value, field)
    if len(value) != 64 or any(ch not in "0123456789abcdef" for ch in value):
        raise MutationLineageError(f"{field} must be lowercase sha256")
    return value


def repository_root_identity(repository_root: str | Path) -> str:
    root = Path(repository_root)
    if not root.is_absolute():
        raise MutationLineageError("repository_root must be absolute")
    resolved = root.resolve(strict=True)
    return hashlib.sha256(str(resolved).encode("utf-8")).hexdigest()


def _canonical_sha256(payload: dict[str, object]) -> str:
    raw = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


@dataclass(frozen=True)
class MutationLineageRecord:
    sequence: int
    transaction_id: str
    resource_id: str
    repository_root_sha256: str
    authorization_id: str
    request_id: str
    operation_id: str
    plan_sha256: str
    state: str
    evidence_sha256: str | None
    reason: str | None
    record_sha256: str
    schema_version: str = MUTATION_LINEAGE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.sequence < 1:
            raise MutationLineageError("sequence must be positive")
        for field in (
            "transaction_id",
            "resource_id",
            "authorization_id",
            "request_id",
            "operation_id",
        ):
            object.__setattr__(self, field, _required(getattr(self, field), field))
        object.__setattr__(
            self,
            "repository_root_sha256",
            _sha256(self.repository_root_sha256, "repository_root_sha256"),
        )
        object.__setattr__(self, "plan_sha256", _sha256(self.plan_sha256, "plan_sha256"))
        if self.evidence_sha256 is not None:
            object.__setattr__(
                self,
                "evidence_sha256",
                _sha256(self.evidence_sha256, "evidence_sha256"),
            )
        if self.state not in {
            STATE_PENDING,
            STATE_TERMINAL,
            STATE_ABORTED_PRE_EXECUTION,
            STATE_RECOVERY_HOLD,
        }:
            raise MutationLineageError("unsupported lineage state")
        if self.state == STATE_TERMINAL and self.evidence_sha256 is None:
            raise MutationLineageError("terminal lineage requires evidence_sha256")
        expected = self.compute_record_sha256()
        if self.record_sha256 != expected:
            raise MutationLineageError("mutation lineage record integrity mismatch")

    def digest_payload(self) -> dict[str, object]:
        return {
            "authorization_id": self.authorization_id,
            "evidence_sha256": self.evidence_sha256,
            "operation_id": self.operation_id,
            "plan_sha256": self.plan_sha256,
            "reason": self.reason,
            "repository_root_sha256": self.repository_root_sha256,
            "request_id": self.request_id,
            "resource_id": self.resource_id,
            "schema_version": self.schema_version,
            "sequence": self.sequence,
            "state": self.state,
            "transaction_id": self.transaction_id,
        }

    def compute_record_sha256(self) -> str:
        return _canonical_sha256(self.digest_payload())


class RemoteMutationLineageStore:
    """SQLite-backed append/update lineage for one local bounded executor profile."""

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
                CREATE TABLE IF NOT EXISTS remote_mutation_lineage (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    transaction_id TEXT NOT NULL UNIQUE,
                    resource_id TEXT NOT NULL,
                    repository_root_sha256 TEXT NOT NULL,
                    authorization_id TEXT NOT NULL,
                    request_id TEXT NOT NULL,
                    operation_id TEXT NOT NULL,
                    plan_sha256 TEXT NOT NULL,
                    state TEXT NOT NULL,
                    evidence_sha256 TEXT,
                    reason TEXT,
                    record_sha256 TEXT NOT NULL,
                    schema_version TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_remote_mutation_lineage_resource_root
                ON remote_mutation_lineage(resource_id, repository_root_sha256, sequence)
                """
            )

    @staticmethod
    def _digest_for(
        *,
        sequence: int,
        transaction_id: str,
        resource_id: str,
        repository_root_sha256: str,
        authorization_id: str,
        request_id: str,
        operation_id: str,
        plan_sha256: str,
        state: str,
        evidence_sha256: str | None,
        reason: str | None,
    ) -> str:
        return _canonical_sha256(
            {
                "authorization_id": authorization_id,
                "evidence_sha256": evidence_sha256,
                "operation_id": operation_id,
                "plan_sha256": plan_sha256,
                "reason": reason,
                "repository_root_sha256": repository_root_sha256,
                "request_id": request_id,
                "resource_id": resource_id,
                "schema_version": MUTATION_LINEAGE_SCHEMA_VERSION,
                "sequence": sequence,
                "state": state,
                "transaction_id": transaction_id,
            }
        )

    def begin_attempt(
        self,
        *,
        transaction_id: str,
        resource_id: str,
        repository_root: str | Path,
        authorization_id: str,
        request_id: str,
        operation_id: str,
        plan_sha256: str,
    ) -> MutationLineageRecord:
        txid = _required(transaction_id, "transaction_id")
        resource = _required(resource_id, "resource_id")
        root_sha = repository_root_identity(repository_root)
        auth = _required(authorization_id, "authorization_id")
        request = _required(request_id, "request_id")
        operation = _required(operation_id, "operation_id")
        plan = _sha256(plan_sha256, "plan_sha256")

        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT * FROM remote_mutation_lineage WHERE transaction_id = ?",
                (txid,),
            ).fetchone()
            if existing is not None:
                current = self._from_row(existing)
                if (
                    current.resource_id != resource
                    or current.repository_root_sha256 != root_sha
                    or current.authorization_id != auth
                    or current.request_id != request
                    or current.operation_id != operation
                    or current.plan_sha256 != plan
                ):
                    raise MutationLineageError("transaction_id lineage conflict")
                return current

            cursor = connection.execute(
                """
                INSERT INTO remote_mutation_lineage (
                    transaction_id, resource_id, repository_root_sha256,
                    authorization_id, request_id, operation_id, plan_sha256,
                    state, evidence_sha256, reason, record_sha256, schema_version
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, '', ?)
                """,
                (
                    txid,
                    resource,
                    root_sha,
                    auth,
                    request,
                    operation,
                    plan,
                    STATE_PENDING,
                    MUTATION_LINEAGE_SCHEMA_VERSION,
                ),
            )
            sequence = int(cursor.lastrowid)
            digest = self._digest_for(
                sequence=sequence,
                transaction_id=txid,
                resource_id=resource,
                repository_root_sha256=root_sha,
                authorization_id=auth,
                request_id=request,
                operation_id=operation,
                plan_sha256=plan,
                state=STATE_PENDING,
                evidence_sha256=None,
                reason=None,
            )
            connection.execute(
                "UPDATE remote_mutation_lineage SET record_sha256 = ? WHERE transaction_id = ?",
                (digest, txid),
            )
        record = self.get(txid)
        assert record is not None
        return record

    def _transition(
        self,
        transaction_id: str,
        *,
        state: str,
        evidence_sha256: str | None = None,
        reason: str | None = None,
    ) -> MutationLineageRecord:
        txid = _required(transaction_id, "transaction_id")
        if state not in {
            STATE_TERMINAL,
            STATE_ABORTED_PRE_EXECUTION,
            STATE_RECOVERY_HOLD,
        }:
            raise MutationLineageError("unsupported lineage transition target")
        if evidence_sha256 is not None:
            evidence_sha256 = _sha256(evidence_sha256, "evidence_sha256")
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM remote_mutation_lineage WHERE transaction_id = ?",
                (txid,),
            ).fetchone()
            if row is None:
                raise MutationLineageError("mutation lineage transaction not found")
            current = self._from_row(row)
            if current.state != STATE_PENDING:
                raise MutationLineageError("mutation lineage attempt is not pending")
            if state == STATE_TERMINAL and evidence_sha256 is None:
                raise MutationLineageError("terminal lineage requires evidence_sha256")
            digest = self._digest_for(
                sequence=current.sequence,
                transaction_id=current.transaction_id,
                resource_id=current.resource_id,
                repository_root_sha256=current.repository_root_sha256,
                authorization_id=current.authorization_id,
                request_id=current.request_id,
                operation_id=current.operation_id,
                plan_sha256=current.plan_sha256,
                state=state,
                evidence_sha256=evidence_sha256,
                reason=reason,
            )
            connection.execute(
                """
                UPDATE remote_mutation_lineage
                SET state = ?, evidence_sha256 = ?, reason = ?, record_sha256 = ?
                WHERE transaction_id = ?
                """,
                (state, evidence_sha256, reason, digest, txid),
            )
        record = self.get(txid)
        assert record is not None
        return record

    def mark_terminal(
        self,
        transaction_id: str,
        closure: MutationExecutionClosureRecord,
    ) -> MutationLineageRecord:
        if not isinstance(closure, MutationExecutionClosureRecord):
            raise TypeError("closure must be MutationExecutionClosureRecord")
        if closure.closed is not True:
            raise MutationLineageError("terminal lineage requires closed execution")
        current = self.get(transaction_id)
        if current is None:
            raise MutationLineageError("mutation lineage transaction not found")
        if (
            current.authorization_id != closure.authorization_id
            or current.request_id != closure.request_id
            or current.resource_id != closure.resource_id
            or current.operation_id != closure.operation_id
            or current.plan_sha256 != closure.plan_sha256
        ):
            raise MutationLineageError("closure does not match pending lineage attempt")
        return self._transition(
            transaction_id,
            state=STATE_TERMINAL,
            evidence_sha256=closure.evidence_sha256,
            reason=closure.reason,
        )

    def mark_aborted_pre_execution(
        self,
        transaction_id: str,
        *,
        reason: str,
    ) -> MutationLineageRecord:
        return self._transition(
            transaction_id,
            state=STATE_ABORTED_PRE_EXECUTION,
            reason=_required(reason, "reason"),
        )

    def mark_recovery_hold(
        self,
        transaction_id: str,
        *,
        reason: str,
    ) -> MutationLineageRecord:
        return self._transition(
            transaction_id,
            state=STATE_RECOVERY_HOLD,
            reason=_required(reason, "reason"),
        )

    def latest(
        self,
        *,
        resource_id: str,
        repository_root: str | Path,
    ) -> MutationLineageRecord | None:
        resource = _required(resource_id, "resource_id")
        root_sha = repository_root_identity(repository_root)
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM remote_mutation_lineage
                WHERE resource_id = ? AND repository_root_sha256 = ?
                ORDER BY sequence DESC LIMIT 1
                """,
                (resource, root_sha),
            ).fetchone()
        return None if row is None else self._from_row(row)

    def get(self, transaction_id: str) -> MutationLineageRecord | None:
        txid = _required(transaction_id, "transaction_id")
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM remote_mutation_lineage WHERE transaction_id = ?",
                (txid,),
            ).fetchone()
        return None if row is None else self._from_row(row)

    @staticmethod
    def _from_row(row: sqlite3.Row) -> MutationLineageRecord:
        return MutationLineageRecord(
            sequence=int(row["sequence"]),
            transaction_id=row["transaction_id"],
            resource_id=row["resource_id"],
            repository_root_sha256=row["repository_root_sha256"],
            authorization_id=row["authorization_id"],
            request_id=row["request_id"],
            operation_id=row["operation_id"],
            plan_sha256=row["plan_sha256"],
            state=row["state"],
            evidence_sha256=row["evidence_sha256"],
            reason=row["reason"],
            record_sha256=row["record_sha256"],
            schema_version=row["schema_version"],
        )
