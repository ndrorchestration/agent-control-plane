"""Durable crash/interruption journal for candidate repository mutations.

The journal records intent and verified observations only. It never performs a
mutation or rollback and never grants mutation execution authority.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
import sqlite3

from .remote_mutation_path_safety import MutationPathSafetyRecord
from .remote_mutation_postcondition import MutationPostconditionRecord
from .remote_mutation_rollback_custody import RollbackCustodyAdmissionRecord
from .remote_mutation_transaction import MutationPlan

MUTATION_RECOVERY_JOURNAL_SCHEMA_VERSION = (
    "agent-control-plane.remote-mutation-recovery-journal.v0-candidate"
)


class MutationRecoveryJournalError(ValueError):
    pass


def _required(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise MutationRecoveryJournalError(f"{field_name} must not be blank")
    return value.strip()


def _sha256(value: str, field_name: str) -> str:
    value = _required(value, field_name)
    if len(value) != 64 or any(ch not in "0123456789abcdef" for ch in value):
        raise MutationRecoveryJournalError(f"{field_name} must be lowercase sha256")
    return value


class MutationJournalState(str, Enum):
    PREPARED = "prepared"
    EFFECT_INTENT_RECORDED = "effect_intent_recorded"
    POSTCONDITION_VERIFIED = "postcondition_verified"
    CLOSED_PRE_EFFECT = "closed_pre_effect"
    CLOSED_VERIFIED = "closed_verified"


class MutationRecoveryDisposition(str, Enum):
    SAFE_PRE_EFFECT = "safe_pre_effect"
    HOLD_UNKNOWN_EFFECT = "hold_unknown_effect"
    VERIFIED_EFFECT = "verified_effect"
    CLEAN_PRE_EFFECT = "clean_pre_effect"
    CLEAN_VERIFIED = "clean_verified"


_TERMINAL_STATES = {
    MutationJournalState.CLOSED_PRE_EFFECT,
    MutationJournalState.CLOSED_VERIFIED,
}

_ALLOWED_TRANSITIONS = {
    MutationJournalState.PREPARED: {
        MutationJournalState.EFFECT_INTENT_RECORDED,
        MutationJournalState.CLOSED_PRE_EFFECT,
    },
    MutationJournalState.EFFECT_INTENT_RECORDED: {
        MutationJournalState.POSTCONDITION_VERIFIED,
    },
    MutationJournalState.POSTCONDITION_VERIFIED: {
        MutationJournalState.CLOSED_VERIFIED,
    },
}


@dataclass(frozen=True)
class MutationJournalEvent:
    journal_id: str
    event_index: int
    state: MutationJournalState
    evidence_ref: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "journal_id", _required(self.journal_id, "journal_id"))
        if (
            isinstance(self.event_index, bool)
            or not isinstance(self.event_index, int)
            or self.event_index < 0
        ):
            raise MutationRecoveryJournalError(
                "event_index must be a non-negative integer"
            )
        if not isinstance(self.state, MutationJournalState):
            raise MutationRecoveryJournalError("state must be MutationJournalState")
        if self.evidence_ref is not None:
            object.__setattr__(
                self,
                "evidence_ref",
                _required(self.evidence_ref, "evidence_ref"),
            )


@dataclass(frozen=True)
class MutationRecoveryJournalRecord:
    journal_id: str
    request_id: str
    resource_id: str
    operation_id: str
    plan_sha256: str
    requested_path: str
    rollback_descriptor_sha256: str
    rollback_custody_ref: str
    events: tuple[MutationJournalEvent, ...]
    schema_version: str = MUTATION_RECOVERY_JOURNAL_SCHEMA_VERSION

    def __post_init__(self) -> None:
        for field in (
            "journal_id",
            "request_id",
            "resource_id",
            "operation_id",
            "requested_path",
            "rollback_custody_ref",
        ):
            object.__setattr__(self, field, _required(getattr(self, field), field))
        _sha256(self.plan_sha256, "plan_sha256")
        _sha256(
            self.rollback_descriptor_sha256,
            "rollback_descriptor_sha256",
        )
        if self.schema_version != MUTATION_RECOVERY_JOURNAL_SCHEMA_VERSION:
            raise MutationRecoveryJournalError(
                f"unsupported schema_version: {self.schema_version}"
            )
        if not self.events:
            raise MutationRecoveryJournalError("journal has no events")
        previous: MutationJournalState | None = None
        for expected_index, event in enumerate(self.events):
            if event.journal_id != self.journal_id:
                raise MutationRecoveryJournalError("journal event identity mismatch")
            if event.event_index != expected_index:
                raise MutationRecoveryJournalError(
                    "journal event index sequence is not contiguous"
                )
            if expected_index == 0:
                if event.state is not MutationJournalState.PREPARED:
                    raise MutationRecoveryJournalError(
                        "journal must begin in prepared state"
                    )
            elif event.state not in _ALLOWED_TRANSITIONS.get(previous, set()):
                raise MutationRecoveryJournalError(
                    "journal contains invalid persisted transition"
                )
            previous = event.state

    @property
    def current_state(self) -> MutationJournalState:
        return self.events[-1].state


@dataclass(frozen=True)
class MutationRecoveryAssessment:
    journal_id: str
    current_state: MutationJournalState
    disposition: MutationRecoveryDisposition
    effect_may_exist: bool
    recovery_hold: bool
    execution_enabled: bool = False
    mutation_executed: bool = False

    def __post_init__(self) -> None:
        if self.execution_enabled is not False or self.mutation_executed is not False:
            raise MutationRecoveryJournalError(
                "recovery assessment cannot enable or claim mutation execution"
            )


class MutationRecoveryJournal:
    """SQLite-backed append-only mutation recovery journal."""

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
                CREATE TABLE IF NOT EXISTS mutation_recovery_transaction (
                    journal_id TEXT PRIMARY KEY,
                    request_id TEXT NOT NULL,
                    resource_id TEXT NOT NULL,
                    operation_id TEXT NOT NULL,
                    plan_sha256 TEXT NOT NULL,
                    requested_path TEXT NOT NULL,
                    rollback_descriptor_sha256 TEXT NOT NULL,
                    rollback_custody_ref TEXT NOT NULL,
                    schema_version TEXT NOT NULL
                )
                """)
            connection.execute("""
                CREATE TABLE IF NOT EXISTS mutation_recovery_event (
                    journal_id TEXT NOT NULL,
                    event_index INTEGER NOT NULL,
                    state TEXT NOT NULL,
                    evidence_ref TEXT,
                    PRIMARY KEY (journal_id, event_index),
                    FOREIGN KEY (journal_id)
                        REFERENCES mutation_recovery_transaction(journal_id)
                )
                """)

    def _event_from_row(self, row: sqlite3.Row) -> MutationJournalEvent:
        return MutationJournalEvent(
            journal_id=row["journal_id"],
            event_index=row["event_index"],
            state=MutationJournalState(row["state"]),
            evidence_ref=row["evidence_ref"],
        )

    def get(self, journal_id: str) -> MutationRecoveryJournalRecord | None:
        identifier = _required(journal_id, "journal_id")
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM mutation_recovery_transaction
                WHERE journal_id = ?
                """,
                (identifier,),
            ).fetchone()
            if row is None:
                return None
            event_rows = connection.execute(
                """
                SELECT * FROM mutation_recovery_event
                WHERE journal_id = ?
                ORDER BY event_index
                """,
                (identifier,),
            ).fetchall()

        events = tuple(self._event_from_row(item) for item in event_rows)
        if not events:
            raise MutationRecoveryJournalError("journal transaction has no events")
        return MutationRecoveryJournalRecord(
            journal_id=row["journal_id"],
            request_id=row["request_id"],
            resource_id=row["resource_id"],
            operation_id=row["operation_id"],
            plan_sha256=row["plan_sha256"],
            requested_path=row["requested_path"],
            rollback_descriptor_sha256=row["rollback_descriptor_sha256"],
            rollback_custody_ref=row["rollback_custody_ref"],
            events=events,
            schema_version=row["schema_version"],
        )

    def begin(
        self,
        *,
        journal_id: str,
        plan: MutationPlan,
        path_safety: MutationPathSafetyRecord,
        rollback_custody: RollbackCustodyAdmissionRecord,
    ) -> MutationRecoveryJournalRecord:
        identifier = _required(journal_id, "journal_id")
        if not isinstance(plan, MutationPlan):
            raise TypeError("plan must be MutationPlan")
        if not isinstance(path_safety, MutationPathSafetyRecord):
            raise TypeError("path_safety must be MutationPathSafetyRecord")
        if not isinstance(rollback_custody, RollbackCustodyAdmissionRecord):
            raise TypeError("rollback_custody must be RollbackCustodyAdmissionRecord")

        if (
            path_safety.execution_enabled is not False
            or path_safety.mutation_executed is not False
            or rollback_custody.execution_enabled is not False
            or rollback_custody.mutation_executed is not False
        ):
            raise MutationRecoveryJournalError(
                "upstream mutation gate unexpectedly enables execution"
            )
        if (
            path_safety.admitted is not True
            or path_safety.request_id != plan.request_id
            or path_safety.resource_id != plan.resource_id
            or path_safety.operation_id != plan.operation_id
            or path_safety.plan_sha256 != plan.plan_sha256
            or path_safety.requested_path != plan.parameters["path"]
        ):
            raise MutationRecoveryJournalError("path safety is not congruent with plan")
        if (
            rollback_custody.admitted is not True
            or rollback_custody.readback_verified is not True
            or rollback_custody.request_id != plan.request_id
            or rollback_custody.resource_id != plan.resource_id
            or rollback_custody.operation_id != plan.operation_id
            or rollback_custody.plan_sha256 != plan.plan_sha256
            or rollback_custody.descriptor_sha256 != plan.rollback_sha256
        ):
            raise MutationRecoveryJournalError(
                "rollback custody is not congruent with plan"
            )

        expected = (
            plan.request_id,
            plan.resource_id,
            plan.operation_id,
            plan.plan_sha256,
            plan.parameters["path"],
            rollback_custody.descriptor_sha256,
            rollback_custody.custody_ref,
        )
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                """
                SELECT * FROM mutation_recovery_transaction
                WHERE journal_id = ?
                """,
                (identifier,),
            ).fetchone()
            if existing is not None:
                actual = (
                    existing["request_id"],
                    existing["resource_id"],
                    existing["operation_id"],
                    existing["plan_sha256"],
                    existing["requested_path"],
                    existing["rollback_descriptor_sha256"],
                    existing["rollback_custody_ref"],
                )
                if actual != expected:
                    raise MutationRecoveryJournalError(
                        "journal_id already bound to different mutation identity"
                    )
            else:
                connection.execute(
                    """
                    INSERT INTO mutation_recovery_transaction (
                        journal_id, request_id, resource_id, operation_id,
                        plan_sha256, requested_path,
                        rollback_descriptor_sha256, rollback_custody_ref,
                        schema_version
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        identifier,
                        *expected,
                        MUTATION_RECOVERY_JOURNAL_SCHEMA_VERSION,
                    ),
                )
                connection.execute(
                    """
                    INSERT INTO mutation_recovery_event (
                        journal_id, event_index, state, evidence_ref
                    ) VALUES (?, 0, ?, NULL)
                    """,
                    (identifier, MutationJournalState.PREPARED.value),
                )

        record = self.get(identifier)
        assert record is not None
        return record

    def append(
        self,
        journal_id: str,
        state: MutationJournalState,
        *,
        postcondition: MutationPostconditionRecord | None = None,
    ) -> MutationRecoveryJournalRecord:
        identifier = _required(journal_id, "journal_id")
        if not isinstance(state, MutationJournalState):
            raise TypeError("state must be MutationJournalState")
        record = self.get(identifier)
        if record is None:
            raise MutationRecoveryJournalError("unknown journal_id")
        current = record.current_state
        if current in _TERMINAL_STATES:
            raise MutationRecoveryJournalError("journal is already terminal")
        if state not in _ALLOWED_TRANSITIONS.get(current, set()):
            raise MutationRecoveryJournalError(
                f"invalid journal transition: {current.value} -> {state.value}"
            )

        evidence_ref: str | None = None
        if state is MutationJournalState.POSTCONDITION_VERIFIED:
            if not isinstance(postcondition, MutationPostconditionRecord):
                raise MutationRecoveryJournalError(
                    "verified postcondition event requires postcondition record"
                )
            if (
                postcondition.postcondition_verified is not True
                or postcondition.execution_enabled is not False
                or postcondition.mutation_executed is not False
                or postcondition.request_id != record.request_id
                or postcondition.resource_id != record.resource_id
                or postcondition.operation_id != record.operation_id
                or postcondition.plan_sha256 != record.plan_sha256
                or postcondition.requested_path != record.requested_path
                or postcondition.rollback_descriptor_sha256
                != record.rollback_descriptor_sha256
                or postcondition.rollback_custody_ref != record.rollback_custody_ref
            ):
                raise MutationRecoveryJournalError(
                    "postcondition is not congruent with journal identity"
                )
            evidence_ref = (
                f"postcondition:{postcondition.plan_sha256}:"
                f"{postcondition.observed_content_sha256 or 'absent'}"
            )
        elif postcondition is not None:
            raise MutationRecoveryJournalError(
                "postcondition is valid only for postcondition_verified transition"
            )

        next_index = record.events[-1].event_index + 1
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            fresh = connection.execute(
                """
                SELECT state, event_index
                FROM mutation_recovery_event
                WHERE journal_id = ?
                ORDER BY event_index DESC
                LIMIT 1
                """,
                (identifier,),
            ).fetchone()
            if fresh is None:
                raise MutationRecoveryJournalError("journal has no current event")
            if (
                fresh["state"] != current.value
                or fresh["event_index"] != record.events[-1].event_index
            ):
                raise MutationRecoveryJournalError(
                    "journal changed concurrently; retry from fresh state"
                )
            connection.execute(
                """
                INSERT INTO mutation_recovery_event (
                    journal_id, event_index, state, evidence_ref
                ) VALUES (?, ?, ?, ?)
                """,
                (identifier, next_index, state.value, evidence_ref),
            )

        updated = self.get(identifier)
        assert updated is not None
        return updated

    def assess(self, journal_id: str) -> MutationRecoveryAssessment:
        record = self.get(journal_id)
        if record is None:
            raise MutationRecoveryJournalError("unknown journal_id")
        state = record.current_state
        if state is MutationJournalState.PREPARED:
            disposition = MutationRecoveryDisposition.SAFE_PRE_EFFECT
            effect_may_exist = False
            recovery_hold = False
        elif state is MutationJournalState.EFFECT_INTENT_RECORDED:
            disposition = MutationRecoveryDisposition.HOLD_UNKNOWN_EFFECT
            effect_may_exist = True
            recovery_hold = True
        elif state is MutationJournalState.POSTCONDITION_VERIFIED:
            disposition = MutationRecoveryDisposition.VERIFIED_EFFECT
            effect_may_exist = True
            recovery_hold = False
        elif state is MutationJournalState.CLOSED_PRE_EFFECT:
            disposition = MutationRecoveryDisposition.CLEAN_PRE_EFFECT
            effect_may_exist = False
            recovery_hold = False
        else:
            disposition = MutationRecoveryDisposition.CLEAN_VERIFIED
            effect_may_exist = True
            recovery_hold = False

        return MutationRecoveryAssessment(
            journal_id=record.journal_id,
            current_state=state,
            disposition=disposition,
            effect_may_exist=effect_may_exist,
            recovery_hold=recovery_hold,
        )
