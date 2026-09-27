"""Durable append-only journal for the non-executing remote mutation control path."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
import sqlite3
from typing import Optional

from .remote_mutation_path_safety import MutationPathSafetyRecord
from .remote_mutation_rollback_custody import RollbackCustodyAdmissionRecord
from .remote_mutation_transaction import MutationPlan

MUTATION_JOURNAL_SCHEMA_VERSION = "agent-control-plane.remote-mutation-journal.v0-candidate"


class MutationJournalError(ValueError):
    pass


def _required(value: str, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise MutationJournalError(f"{field} must not be blank")
    return value.strip()


def _sha256(value: str, field: str) -> str:
    value = _required(value, field)
    if len(value) != 64 or any(ch not in "0123456789abcdef" for ch in value):
        raise MutationJournalError(f"{field} must be lowercase sha256")
    return value


def _utc(value: str, field: str) -> str:
    raw = _required(value, field)
    candidate = raw[:-1] + "+00:00" if raw.endswith("Z") else raw
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError as exc:
        raise MutationJournalError(f"{field} must be valid ISO-8601") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise MutationJournalError(f"{field} must be timezone-aware UTC")
    if parsed.utcoffset() != timedelta(0):
        raise MutationJournalError(f"{field} must use UTC")
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


class MutationJournalState(str, Enum):
    PREPARED = "prepared"
    EXECUTION_INTENT_RECORDED = "execution_intent_recorded"
    EXTERNAL_EFFECT_REPORTED = "external_effect_reported"
    POSTCONDITION_VERIFIED = "postcondition_verified"
    ROLLBACK_INTENT_RECORDED = "rollback_intent_recorded"
    ROLLBACK_VERIFIED = "rollback_verified"
    FAILED = "failed"


_TERMINAL = {
    MutationJournalState.POSTCONDITION_VERIFIED,
    MutationJournalState.ROLLBACK_VERIFIED,
}

_ALLOWED = {
    MutationJournalState.PREPARED: {
        MutationJournalState.EXECUTION_INTENT_RECORDED,
        MutationJournalState.FAILED,
    },
    MutationJournalState.EXECUTION_INTENT_RECORDED: {
        MutationJournalState.EXTERNAL_EFFECT_REPORTED,
        MutationJournalState.ROLLBACK_INTENT_RECORDED,
        MutationJournalState.FAILED,
    },
    MutationJournalState.EXTERNAL_EFFECT_REPORTED: {
        MutationJournalState.POSTCONDITION_VERIFIED,
        MutationJournalState.ROLLBACK_INTENT_RECORDED,
        MutationJournalState.FAILED,
    },
    MutationJournalState.ROLLBACK_INTENT_RECORDED: {
        MutationJournalState.ROLLBACK_VERIFIED,
        MutationJournalState.FAILED,
    },
    MutationJournalState.FAILED: {
        MutationJournalState.ROLLBACK_INTENT_RECORDED,
    },
}


class MutationRecoveryDisposition(str, Enum):
    SAFE_PRE_EXECUTION = "safe_pre_execution"
    HOLD_AMBIGUOUS_EFFECT = "hold_ambiguous_effect"
    HOLD_POSTCONDITION_REQUIRED = "hold_postcondition_required"
    CLEAN_POSTCONDITION_VERIFIED = "clean_postcondition_verified"
    HOLD_ROLLBACK_AMBIGUOUS = "hold_rollback_ambiguous"
    CLEAN_ROLLED_BACK = "clean_rolled_back"
    FAILED_PRE_EXECUTION = "failed_pre_execution"
    HOLD_FAILED_AFTER_EXECUTION_INTENT = "hold_failed_after_execution_intent"


@dataclass(frozen=True)
class MutationJournalEvent:
    transaction_id: str
    event_index: int
    state: MutationJournalState
    occurred_at: str
    evidence_sha256: str | None = None
    error: str | None = None


@dataclass(frozen=True)
class MutationJournalRecord:
    transaction_id: str
    request_id: str
    resource_id: str
    operation_id: str
    plan_sha256: str
    rollback_descriptor_sha256: str
    custody_ref: str
    created_at: str
    events: tuple[MutationJournalEvent, ...]
    schema_version: str = MUTATION_JOURNAL_SCHEMA_VERSION

    @property
    def current_state(self) -> MutationJournalState:
        return self.events[-1].state


@dataclass(frozen=True)
class MutationRecoveryAssessment:
    transaction_id: str
    current_state: MutationJournalState
    disposition: MutationRecoveryDisposition
    repository_mutation_may_exist: bool
    new_execution_authorization_required: bool = True


class RemoteMutationJournal:
    """SQLite-backed append-only control/evidence journal; never mutates repositories."""

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
                CREATE TABLE IF NOT EXISTS remote_mutation_transaction (
                    transaction_id TEXT PRIMARY KEY,
                    request_id TEXT NOT NULL,
                    resource_id TEXT NOT NULL,
                    operation_id TEXT NOT NULL,
                    plan_sha256 TEXT NOT NULL,
                    rollback_descriptor_sha256 TEXT NOT NULL,
                    custody_ref TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    schema_version TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS remote_mutation_event (
                    transaction_id TEXT NOT NULL,
                    event_index INTEGER NOT NULL,
                    state TEXT NOT NULL,
                    occurred_at TEXT NOT NULL,
                    evidence_sha256 TEXT,
                    error TEXT,
                    PRIMARY KEY (transaction_id, event_index),
                    FOREIGN KEY (transaction_id)
                        REFERENCES remote_mutation_transaction(transaction_id)
                )
                """
            )

    def begin(
        self,
        *,
        transaction_id: str,
        plan: MutationPlan,
        path_safety: MutationPathSafetyRecord,
        rollback_custody: RollbackCustodyAdmissionRecord,
        created_at: str,
    ) -> MutationJournalRecord:
        txid = _required(transaction_id, "transaction_id")
        if not isinstance(plan, MutationPlan):
            raise TypeError("plan must be MutationPlan")
        if not isinstance(path_safety, MutationPathSafetyRecord):
            raise TypeError("path_safety must be MutationPathSafetyRecord")
        if not isinstance(rollback_custody, RollbackCustodyAdmissionRecord):
            raise TypeError("rollback_custody must be RollbackCustodyAdmissionRecord")
        if path_safety.admitted is not True:
            raise MutationJournalError("path safety must be admitted")
        if rollback_custody.admitted is not True or rollback_custody.readback_verified is not True:
            raise MutationJournalError("rollback custody must be admitted and readback-verified")
        if path_safety.execution_enabled is not False or path_safety.mutation_executed is not False:
            raise MutationJournalError("path safety unexpectedly enables execution")
        if rollback_custody.execution_enabled is not False or rollback_custody.mutation_executed is not False:
            raise MutationJournalError("rollback custody unexpectedly enables execution")
        if (
            path_safety.request_id != plan.request_id
            or path_safety.resource_id != plan.resource_id
            or path_safety.operation_id != plan.operation_id
            or path_safety.plan_sha256 != plan.plan_sha256
            or rollback_custody.request_id != plan.request_id
            or rollback_custody.resource_id != plan.resource_id
            or rollback_custody.operation_id != plan.operation_id
            or rollback_custody.plan_sha256 != plan.plan_sha256
            or rollback_custody.descriptor_sha256 != plan.rollback_sha256
        ):
            raise MutationJournalError("upstream mutation identities do not match exact plan")
        created = _utc(created_at, "created_at")

        expected = (
            plan.request_id, plan.resource_id, plan.operation_id, plan.plan_sha256,
            rollback_custody.descriptor_sha256, rollback_custody.custody_ref, created,
        )
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM remote_mutation_transaction WHERE transaction_id = ?",
                (txid,),
            ).fetchone()
            if row is not None:
                actual = (
                    row["request_id"], row["resource_id"], row["operation_id"],
                    row["plan_sha256"], row["rollback_descriptor_sha256"],
                    row["custody_ref"], row["created_at"],
                )
                if actual != expected:
                    raise MutationJournalError("mutation journal transaction_id conflict")
                record = self.get(txid)
                assert record is not None
                return record
            connection.execute(
                """INSERT INTO remote_mutation_transaction (
                    transaction_id, request_id, resource_id, operation_id, plan_sha256,
                    rollback_descriptor_sha256, custody_ref, created_at, schema_version
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (txid, *expected, MUTATION_JOURNAL_SCHEMA_VERSION),
            )
            connection.execute(
                """INSERT INTO remote_mutation_event (
                    transaction_id, event_index, state, occurred_at, evidence_sha256, error
                ) VALUES (?, 0, ?, ?, NULL, NULL)""",
                (txid, MutationJournalState.PREPARED.value, created),
            )
        record = self.get(txid)
        assert record is not None
        return record

    def append(
        self,
        transaction_id: str,
        *,
        state: MutationJournalState,
        occurred_at: str,
        evidence_sha256: Optional[str] = None,
        error: Optional[str] = None,
    ) -> MutationJournalRecord:
        txid = _required(transaction_id, "transaction_id")
        if not isinstance(state, MutationJournalState):
            raise MutationJournalError("state must be MutationJournalState")
        when = _utc(occurred_at, "occurred_at")
        if evidence_sha256 is not None:
            evidence_sha256 = _sha256(evidence_sha256, "evidence_sha256")
        if error is not None:
            error = _required(error, "error")
        if state in {MutationJournalState.EXTERNAL_EFFECT_REPORTED, MutationJournalState.POSTCONDITION_VERIFIED, MutationJournalState.ROLLBACK_VERIFIED} and evidence_sha256 is None:
            raise MutationJournalError("state requires evidence_sha256")
        if state is MutationJournalState.FAILED and error is None:
            raise MutationJournalError("failed state requires error")

        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            tx = connection.execute(
                "SELECT 1 FROM remote_mutation_transaction WHERE transaction_id = ?",
                (txid,),
            ).fetchone()
            if tx is None:
                raise MutationJournalError("mutation journal transaction not found")
            row = connection.execute(
                """SELECT * FROM remote_mutation_event WHERE transaction_id = ?
                   ORDER BY event_index DESC LIMIT 1""",
                (txid,),
            ).fetchone()
            assert row is not None
            current = MutationJournalState(row["state"])
            if current in _TERMINAL:
                raise MutationJournalError("mutation journal transaction is terminal")
            if state not in _ALLOWED.get(current, set()):
                raise MutationJournalError(
                    f"invalid mutation journal transition: {current.value} -> {state.value}"
                )
            if (
                current is MutationJournalState.FAILED
                and state is MutationJournalState.ROLLBACK_INTENT_RECORDED
            ):
                prior_rows = connection.execute(
                    """SELECT state FROM remote_mutation_event
                       WHERE transaction_id = ?
                       ORDER BY event_index ASC""",
                    (txid,),
                ).fetchall()
                prior_states = {
                    MutationJournalState(prior["state"])
                    for prior in prior_rows
                }
                if MutationJournalState.EXECUTION_INTENT_RECORDED not in prior_states:
                    raise MutationJournalError(
                        "rollback after FAILED requires prior execution intent"
                    )
            next_index = int(row["event_index"]) + 1
            connection.execute(
                """INSERT INTO remote_mutation_event (
                    transaction_id, event_index, state, occurred_at, evidence_sha256, error
                ) VALUES (?, ?, ?, ?, ?, ?)""",
                (txid, next_index, state.value, when, evidence_sha256, error),
            )
        record = self.get(txid)
        assert record is not None
        return record

    def get(self, transaction_id: str) -> MutationJournalRecord | None:
        txid = _required(transaction_id, "transaction_id")
        with self._connect() as connection:
            tx = connection.execute(
                "SELECT * FROM remote_mutation_transaction WHERE transaction_id = ?",
                (txid,),
            ).fetchone()
            if tx is None:
                return None
            rows = connection.execute(
                """SELECT * FROM remote_mutation_event WHERE transaction_id = ?
                   ORDER BY event_index ASC""",
                (txid,),
            ).fetchall()
        events = tuple(
            MutationJournalEvent(
                transaction_id=txid, event_index=int(row["event_index"]),
                state=MutationJournalState(row["state"]), occurred_at=row["occurred_at"],
                evidence_sha256=row["evidence_sha256"], error=row["error"],
            )
            for row in rows
        )
        return MutationJournalRecord(
            transaction_id=txid, request_id=tx["request_id"], resource_id=tx["resource_id"],
            operation_id=tx["operation_id"], plan_sha256=tx["plan_sha256"],
            rollback_descriptor_sha256=tx["rollback_descriptor_sha256"],
            custody_ref=tx["custody_ref"], created_at=tx["created_at"], events=events,
            schema_version=tx["schema_version"],
        )

    def assess_recovery(self, transaction_id: str) -> MutationRecoveryAssessment:
        record = self.get(transaction_id)
        if record is None:
            raise MutationJournalError("mutation journal transaction not found")
        states = tuple(event.state for event in record.events)
        current = record.current_state
        saw_intent = MutationJournalState.EXECUTION_INTENT_RECORDED in states
        mapping = {
            MutationJournalState.PREPARED: (MutationRecoveryDisposition.SAFE_PRE_EXECUTION, False),
            MutationJournalState.EXECUTION_INTENT_RECORDED: (MutationRecoveryDisposition.HOLD_AMBIGUOUS_EFFECT, True),
            MutationJournalState.EXTERNAL_EFFECT_REPORTED: (MutationRecoveryDisposition.HOLD_POSTCONDITION_REQUIRED, True),
            MutationJournalState.POSTCONDITION_VERIFIED: (MutationRecoveryDisposition.CLEAN_POSTCONDITION_VERIFIED, True),
            MutationJournalState.ROLLBACK_INTENT_RECORDED: (MutationRecoveryDisposition.HOLD_ROLLBACK_AMBIGUOUS, True),
            MutationJournalState.ROLLBACK_VERIFIED: (MutationRecoveryDisposition.CLEAN_ROLLED_BACK, False),
        }
        if current is MutationJournalState.FAILED:
            disposition = (
                MutationRecoveryDisposition.HOLD_FAILED_AFTER_EXECUTION_INTENT
                if saw_intent
                else MutationRecoveryDisposition.FAILED_PRE_EXECUTION
            )
            may_exist = saw_intent
        else:
            disposition, may_exist = mapping[current]
        return MutationRecoveryAssessment(
            transaction_id=record.transaction_id, current_state=current,
            disposition=disposition, repository_mutation_may_exist=may_exist,
        )