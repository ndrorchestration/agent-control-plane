"""Durable journal for a separately governed rollback transaction.

The original mutation journal remains immutable. This journal records only the
new rollback transaction and never performs or authorizes a rollback.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
import sqlite3

from .remote_mutation_rollback_plan import RepositoryRollbackPlan

ROLLBACK_JOURNAL_SCHEMA_VERSION = (
    "agent-control-plane.remote-mutation-rollback-journal.v0-candidate"
)


class RollbackJournalError(ValueError):
    pass


def _required(value: str, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RollbackJournalError(f"{field} must not be blank")
    return value.strip()


def _sha256(value: str, field: str) -> str:
    value = _required(value, field)
    if len(value) != 64 or any(ch not in "0123456789abcdef" for ch in value):
        raise RollbackJournalError(f"{field} must be lowercase sha256")
    return value


def _utc(value: str, field: str) -> str:
    raw = _required(value, field)
    candidate = raw[:-1] + "+00:00" if raw.endswith("Z") else raw
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError as exc:
        raise RollbackJournalError(f"{field} must be valid ISO-8601") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise RollbackJournalError(f"{field} must be timezone-aware UTC")
    if parsed.utcoffset() != timedelta(0):
        raise RollbackJournalError(f"{field} must use UTC")
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


class RollbackJournalState(str, Enum):
    PREPARED = "prepared"
    ROLLBACK_INTENT_RECORDED = "rollback_intent_recorded"
    ROLLBACK_EFFECT_REPORTED = "rollback_effect_reported"
    ROLLBACK_VERIFIED = "rollback_verified"
    FAILED = "failed"


_ALLOWED = {
    RollbackJournalState.PREPARED: {
        RollbackJournalState.ROLLBACK_INTENT_RECORDED,
        RollbackJournalState.FAILED,
    },
    RollbackJournalState.ROLLBACK_INTENT_RECORDED: {
        RollbackJournalState.ROLLBACK_EFFECT_REPORTED,
        RollbackJournalState.ROLLBACK_VERIFIED,
        RollbackJournalState.FAILED,
    },
    RollbackJournalState.ROLLBACK_EFFECT_REPORTED: {
        RollbackJournalState.ROLLBACK_VERIFIED,
        RollbackJournalState.FAILED,
    },
}
_TERMINAL = {
    RollbackJournalState.ROLLBACK_VERIFIED,
    RollbackJournalState.FAILED,
}


class RollbackRecoveryDisposition(str, Enum):
    SAFE_PRE_ROLLBACK = "safe_pre_rollback"
    HOLD_AMBIGUOUS_ROLLBACK = "hold_ambiguous_rollback"
    HOLD_ROLLBACK_POSTCONDITION_REQUIRED = "hold_rollback_postcondition_required"
    CLEAN_ROLLED_BACK = "clean_rolled_back"
    FAILED_PRE_ROLLBACK = "failed_pre_rollback"
    HOLD_FAILED_AFTER_ROLLBACK_INTENT = "hold_failed_after_rollback_intent"


@dataclass(frozen=True)
class RollbackJournalEvent:
    rollback_transaction_id: str
    event_index: int
    state: RollbackJournalState
    occurred_at: str
    evidence_sha256: str | None = None
    error: str | None = None


@dataclass(frozen=True)
class RollbackJournalRecord:
    rollback_transaction_id: str
    rollback_request_id: str
    rollback_authority_id: str
    rollback_plan_sha256: str
    original_transaction_id: str
    original_plan_sha256: str
    rollback_descriptor_sha256: str
    rollback_custody_ref: str
    created_at: str
    events: tuple[RollbackJournalEvent, ...]
    schema_version: str = ROLLBACK_JOURNAL_SCHEMA_VERSION

    @property
    def current_state(self) -> RollbackJournalState:
        return self.events[-1].state


@dataclass(frozen=True)
class RollbackRecoveryAssessment:
    rollback_transaction_id: str
    current_state: RollbackJournalState
    disposition: RollbackRecoveryDisposition
    rollback_effect_may_exist: bool
    new_rollback_authorization_required: bool = True
    execution_enabled: bool = False
    rollback_executed: bool = False

    def __post_init__(self) -> None:
        if self.execution_enabled is not False or self.rollback_executed is not False:
            raise RollbackJournalError(
                "rollback recovery assessment cannot enable or claim rollback execution"
            )


class RemoteMutationRollbackJournal:
    """SQLite-backed rollback control/evidence journal; never mutates repositories."""

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
                CREATE TABLE IF NOT EXISTS remote_mutation_rollback_transaction (
                    rollback_transaction_id TEXT PRIMARY KEY,
                    rollback_request_id TEXT NOT NULL,
                    rollback_authority_id TEXT NOT NULL,
                    rollback_plan_sha256 TEXT NOT NULL,
                    original_transaction_id TEXT NOT NULL,
                    original_plan_sha256 TEXT NOT NULL,
                    rollback_descriptor_sha256 TEXT NOT NULL,
                    rollback_custody_ref TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    schema_version TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS remote_mutation_rollback_event (
                    rollback_transaction_id TEXT NOT NULL,
                    event_index INTEGER NOT NULL,
                    state TEXT NOT NULL,
                    occurred_at TEXT NOT NULL,
                    evidence_sha256 TEXT,
                    error TEXT,
                    PRIMARY KEY (rollback_transaction_id, event_index),
                    FOREIGN KEY (rollback_transaction_id)
                        REFERENCES remote_mutation_rollback_transaction(
                            rollback_transaction_id
                        )
                )
                """
            )

    def begin(
        self,
        *,
        plan: RepositoryRollbackPlan,
        created_at: str,
    ) -> RollbackJournalRecord:
        if not isinstance(plan, RepositoryRollbackPlan):
            raise TypeError("plan must be RepositoryRollbackPlan")
        if plan.execution_enabled is not False or plan.rollback_executed is not False:
            raise RollbackJournalError("rollback plan unexpectedly enables execution")
        created = _utc(created_at, "created_at")
        expected = (
            plan.rollback_request_id,
            plan.rollback_authority_id,
            plan.rollback_plan_sha256,
            plan.original_transaction_id,
            plan.original_plan_sha256,
            plan.rollback_descriptor_sha256,
            plan.rollback_custody_ref,
            created,
        )

        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT * FROM remote_mutation_rollback_transaction
                WHERE rollback_transaction_id = ?
                """,
                (plan.rollback_transaction_id,),
            ).fetchone()
            if row is not None:
                actual = (
                    row["rollback_request_id"],
                    row["rollback_authority_id"],
                    row["rollback_plan_sha256"],
                    row["original_transaction_id"],
                    row["original_plan_sha256"],
                    row["rollback_descriptor_sha256"],
                    row["rollback_custody_ref"],
                    row["created_at"],
                )
                if actual != expected:
                    raise RollbackJournalError(
                        "rollback_transaction_id conflict"
                    )
                record = self.get(plan.rollback_transaction_id)
                assert record is not None
                return record

            connection.execute(
                """
                INSERT INTO remote_mutation_rollback_transaction (
                    rollback_transaction_id, rollback_request_id,
                    rollback_authority_id, rollback_plan_sha256,
                    original_transaction_id, original_plan_sha256,
                    rollback_descriptor_sha256, rollback_custody_ref,
                    created_at, schema_version
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    plan.rollback_transaction_id,
                    *expected,
                    ROLLBACK_JOURNAL_SCHEMA_VERSION,
                ),
            )
            connection.execute(
                """
                INSERT INTO remote_mutation_rollback_event (
                    rollback_transaction_id, event_index, state,
                    occurred_at, evidence_sha256, error
                ) VALUES (?, 0, ?, ?, NULL, NULL)
                """,
                (
                    plan.rollback_transaction_id,
                    RollbackJournalState.PREPARED.value,
                    created,
                ),
            )
        record = self.get(plan.rollback_transaction_id)
        assert record is not None
        return record

    def append(
        self,
        rollback_transaction_id: str,
        *,
        state: RollbackJournalState,
        occurred_at: str,
        evidence_sha256: str | None = None,
        error: str | None = None,
    ) -> RollbackJournalRecord:
        txid = _required(rollback_transaction_id, "rollback_transaction_id")
        if not isinstance(state, RollbackJournalState):
            raise RollbackJournalError("state must be RollbackJournalState")
        when = _utc(occurred_at, "occurred_at")
        if evidence_sha256 is not None:
            evidence_sha256 = _sha256(evidence_sha256, "evidence_sha256")
        if error is not None:
            error = _required(error, "error")
        if state in {
            RollbackJournalState.ROLLBACK_EFFECT_REPORTED,
            RollbackJournalState.ROLLBACK_VERIFIED,
        } and evidence_sha256 is None:
            raise RollbackJournalError("rollback state requires evidence_sha256")
        if state is RollbackJournalState.FAILED and error is None:
            raise RollbackJournalError("failed rollback state requires error")

        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT * FROM remote_mutation_rollback_event
                WHERE rollback_transaction_id = ?
                ORDER BY event_index DESC LIMIT 1
                """,
                (txid,),
            ).fetchone()
            if row is None:
                raise RollbackJournalError("rollback transaction not found")
            current = RollbackJournalState(row["state"])
            if current in _TERMINAL:
                raise RollbackJournalError("rollback transaction is terminal")
            if state not in _ALLOWED.get(current, set()):
                raise RollbackJournalError(
                    f"invalid rollback transition: {current.value} -> {state.value}"
                )
            next_index = int(row["event_index"]) + 1
            connection.execute(
                """
                INSERT INTO remote_mutation_rollback_event (
                    rollback_transaction_id, event_index, state,
                    occurred_at, evidence_sha256, error
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (txid, next_index, state.value, when, evidence_sha256, error),
            )
        record = self.get(txid)
        assert record is not None
        return record

    def get(self, rollback_transaction_id: str) -> RollbackJournalRecord | None:
        txid = _required(rollback_transaction_id, "rollback_transaction_id")
        with self._connect() as connection:
            tx = connection.execute(
                """
                SELECT * FROM remote_mutation_rollback_transaction
                WHERE rollback_transaction_id = ?
                """,
                (txid,),
            ).fetchone()
            if tx is None:
                return None
            rows = connection.execute(
                """
                SELECT * FROM remote_mutation_rollback_event
                WHERE rollback_transaction_id = ?
                ORDER BY event_index ASC
                """,
                (txid,),
            ).fetchall()

        events = tuple(
            RollbackJournalEvent(
                rollback_transaction_id=txid,
                event_index=int(row["event_index"]),
                state=RollbackJournalState(row["state"]),
                occurred_at=row["occurred_at"],
                evidence_sha256=row["evidence_sha256"],
                error=row["error"],
            )
            for row in rows
        )
        return RollbackJournalRecord(
            rollback_transaction_id=txid,
            rollback_request_id=tx["rollback_request_id"],
            rollback_authority_id=tx["rollback_authority_id"],
            rollback_plan_sha256=tx["rollback_plan_sha256"],
            original_transaction_id=tx["original_transaction_id"],
            original_plan_sha256=tx["original_plan_sha256"],
            rollback_descriptor_sha256=tx["rollback_descriptor_sha256"],
            rollback_custody_ref=tx["rollback_custody_ref"],
            created_at=tx["created_at"],
            events=events,
            schema_version=tx["schema_version"],
        )

    def assess_recovery(
        self,
        rollback_transaction_id: str,
    ) -> RollbackRecoveryAssessment:
        record = self.get(rollback_transaction_id)
        if record is None:
            raise RollbackJournalError("rollback transaction not found")
        states = tuple(event.state for event in record.events)
        current = record.current_state
        saw_intent = RollbackJournalState.ROLLBACK_INTENT_RECORDED in states

        if current is RollbackJournalState.PREPARED:
            disposition = RollbackRecoveryDisposition.SAFE_PRE_ROLLBACK
            may_exist = False
        elif current is RollbackJournalState.ROLLBACK_INTENT_RECORDED:
            disposition = RollbackRecoveryDisposition.HOLD_AMBIGUOUS_ROLLBACK
            may_exist = True
        elif current is RollbackJournalState.ROLLBACK_EFFECT_REPORTED:
            disposition = (
                RollbackRecoveryDisposition.HOLD_ROLLBACK_POSTCONDITION_REQUIRED
            )
            may_exist = True
        elif current is RollbackJournalState.ROLLBACK_VERIFIED:
            disposition = RollbackRecoveryDisposition.CLEAN_ROLLED_BACK
            may_exist = True
        else:
            disposition = (
                RollbackRecoveryDisposition.HOLD_FAILED_AFTER_ROLLBACK_INTENT
                if saw_intent
                else RollbackRecoveryDisposition.FAILED_PRE_ROLLBACK
            )
            may_exist = saw_intent

        return RollbackRecoveryAssessment(
            rollback_transaction_id=record.rollback_transaction_id,
            current_state=current,
            disposition=disposition,
            rollback_effect_may_exist=may_exist,
        )
