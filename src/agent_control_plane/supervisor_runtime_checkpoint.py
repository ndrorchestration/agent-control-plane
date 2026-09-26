"""Durable generation-fenced runtime checkpoints for ACP supervisor services."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
import sqlite3
from typing import Optional

from .authority import AuthorityValidationError
from .supervisor_service import (
    SupervisorServiceSnapshot,
    SupervisorServiceState,
    SupervisorStopReason,
)


SUPERVISOR_RUNTIME_CHECKPOINT_SCHEMA_VERSION = (
    "agent-control-plane.supervisor-runtime-checkpoint.v0-candidate"
)


def _required(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise AuthorityValidationError(f"{field_name} must not be blank")
    return value.strip()


def _canonical_utc(value: str, field_name: str) -> str:
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
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


class SupervisorPreviousRunDisposition(str, Enum):
    FRESH = "fresh"
    CLEAN_STOP = "clean_stop"
    UNCLEAN_EXIT = "unclean_exit"
    TERMINAL_GIVE_UP = "terminal_give_up"
    PRIOR_FAILURE = "prior_failure"


@dataclass(frozen=True)
class SupervisorRuntimeCheckpoint:
    service_id: str
    generation: int
    owner_id: str
    fencing_token: int
    state: SupervisorServiceState
    stop_reason: Optional[SupervisorStopReason]
    updated_at: str
    schema_version: str = SUPERVISOR_RUNTIME_CHECKPOINT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "service_id", _required(self.service_id, "service_id")
        )
        object.__setattr__(
            self, "owner_id", _required(self.owner_id, "owner_id")
        )
        if (
            isinstance(self.generation, bool)
            or not isinstance(self.generation, int)
            or self.generation < 1
        ):
            raise AuthorityValidationError(
                "generation must be an integer >= 1"
            )
        if (
            isinstance(self.fencing_token, bool)
            or not isinstance(self.fencing_token, int)
            or self.fencing_token < 1
        ):
            raise AuthorityValidationError(
                "fencing_token must be an integer >= 1"
            )
        if not isinstance(self.state, SupervisorServiceState):
            raise AuthorityValidationError(
                "state must be SupervisorServiceState"
            )
        if (
            self.stop_reason is not None
            and not isinstance(self.stop_reason, SupervisorStopReason)
        ):
            raise AuthorityValidationError(
                "stop_reason must be SupervisorStopReason or None"
            )
        object.__setattr__(
            self,
            "updated_at",
            _canonical_utc(self.updated_at, "updated_at"),
        )
        if (
            self.schema_version
            != SUPERVISOR_RUNTIME_CHECKPOINT_SCHEMA_VERSION
        ):
            raise AuthorityValidationError(
                f"unsupported schema_version: {self.schema_version}"
            )


@dataclass(frozen=True)
class SupervisorRecoveryAssessment:
    disposition: SupervisorPreviousRunDisposition
    previous: Optional[SupervisorRuntimeCheckpoint]
    stale_owner: bool


@dataclass(frozen=True)
class SupervisorRunStart:
    checkpoint: SupervisorRuntimeCheckpoint
    recovery: SupervisorRecoveryAssessment


_ALLOWED_TRANSITIONS = {
    SupervisorServiceState.STARTING: {
        SupervisorServiceState.STARTING,
        SupervisorServiceState.RUNNING,
        SupervisorServiceState.STOP_REQUESTED,
        SupervisorServiceState.FAILED,
    },
    SupervisorServiceState.RUNNING: {
        SupervisorServiceState.RUNNING,
        SupervisorServiceState.STOP_REQUESTED,
        SupervisorServiceState.FAILED,
    },
    SupervisorServiceState.STOP_REQUESTED: {
        SupervisorServiceState.STOP_REQUESTED,
        SupervisorServiceState.STOPPING,
        SupervisorServiceState.FAILED,
    },
    SupervisorServiceState.STOPPING: {
        SupervisorServiceState.STOPPING,
        SupervisorServiceState.STOPPED,
        SupervisorServiceState.FAILED,
    },
    SupervisorServiceState.STOPPED: {
        SupervisorServiceState.STOPPED,
    },
    SupervisorServiceState.FAILED: {
        SupervisorServiceState.FAILED,
    },
}


class DurableSupervisorRuntimeCheckpointStore:
    """Persist one generation-fenced runtime checkpoint per service ID."""

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
                CREATE TABLE IF NOT EXISTS supervisor_runtime_checkpoint (
                    service_id TEXT PRIMARY KEY,
                    generation INTEGER NOT NULL,
                    owner_id TEXT NOT NULL,
                    fencing_token INTEGER NOT NULL,
                    state TEXT NOT NULL,
                    stop_reason TEXT,
                    updated_at TEXT NOT NULL,
                    schema_version TEXT NOT NULL
                )
                """
            )

    def _row(self, row: sqlite3.Row) -> SupervisorRuntimeCheckpoint:
        stop_reason = (
            None
            if row["stop_reason"] is None
            else SupervisorStopReason(row["stop_reason"])
        )
        return SupervisorRuntimeCheckpoint(
            service_id=row["service_id"],
            generation=row["generation"],
            owner_id=row["owner_id"],
            fencing_token=row["fencing_token"],
            state=SupervisorServiceState(row["state"]),
            stop_reason=stop_reason,
            updated_at=row["updated_at"],
            schema_version=row["schema_version"],
        )

    def get(
        self,
        service_id: str,
    ) -> Optional[SupervisorRuntimeCheckpoint]:
        identifier = _required(service_id, "service_id")
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM supervisor_runtime_checkpoint
                WHERE service_id = ?
                """,
                (identifier,),
            ).fetchone()
        return None if row is None else self._row(row)

    def _assess(
        self,
        previous: Optional[SupervisorRuntimeCheckpoint],
        *,
        owner_id: str,
        fencing_token: int,
    ) -> SupervisorRecoveryAssessment:
        if previous is None:
            return SupervisorRecoveryAssessment(
                disposition=SupervisorPreviousRunDisposition.FRESH,
                previous=None,
                stale_owner=False,
            )

        stale_owner = (
            previous.owner_id != owner_id
            or previous.fencing_token != fencing_token
        )

        if previous.state is SupervisorServiceState.STOPPED:
            disposition = SupervisorPreviousRunDisposition.CLEAN_STOP
        elif (
            previous.state is SupervisorServiceState.FAILED
            and previous.stop_reason is SupervisorStopReason.WORKER_GIVE_UP
        ):
            disposition = (
                SupervisorPreviousRunDisposition.TERMINAL_GIVE_UP
            )
        elif previous.state is SupervisorServiceState.FAILED:
            disposition = SupervisorPreviousRunDisposition.PRIOR_FAILURE
        else:
            disposition = SupervisorPreviousRunDisposition.UNCLEAN_EXIT

        return SupervisorRecoveryAssessment(
            disposition=disposition,
            previous=previous,
            stale_owner=stale_owner,
        )

    def begin_run(
        self,
        *,
        service_id: str,
        owner_id: str,
        fencing_token: int,
        started_at: str,
    ) -> SupervisorRunStart:
        service = _required(service_id, "service_id")
        owner = _required(owner_id, "owner_id")
        if (
            isinstance(fencing_token, bool)
            or not isinstance(fencing_token, int)
            or fencing_token < 1
        ):
            raise AuthorityValidationError(
                "fencing_token must be an integer >= 1"
            )
        timestamp = _canonical_utc(started_at, "started_at")

        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT * FROM supervisor_runtime_checkpoint
                WHERE service_id = ?
                """,
                (service,),
            ).fetchone()
            previous = None if row is None else self._row(row)
            generation = (
                1 if previous is None else previous.generation + 1
            )
            recovery = self._assess(
                previous,
                owner_id=owner,
                fencing_token=fencing_token,
            )
            connection.execute(
                """
                INSERT INTO supervisor_runtime_checkpoint (
                    service_id,
                    generation,
                    owner_id,
                    fencing_token,
                    state,
                    stop_reason,
                    updated_at,
                    schema_version
                ) VALUES (?, ?, ?, ?, ?, NULL, ?, ?)
                ON CONFLICT(service_id) DO UPDATE SET
                    generation = excluded.generation,
                    owner_id = excluded.owner_id,
                    fencing_token = excluded.fencing_token,
                    state = excluded.state,
                    stop_reason = NULL,
                    updated_at = excluded.updated_at,
                    schema_version = excluded.schema_version
                """,
                (
                    service,
                    generation,
                    owner,
                    fencing_token,
                    SupervisorServiceState.STARTING.value,
                    timestamp,
                    SUPERVISOR_RUNTIME_CHECKPOINT_SCHEMA_VERSION,
                ),
            )

        checkpoint = self.get(service)
        assert checkpoint is not None
        return SupervisorRunStart(
            checkpoint=checkpoint,
            recovery=recovery,
        )

    def write_snapshot(
        self,
        checkpoint: SupervisorRuntimeCheckpoint,
        snapshot: SupervisorServiceSnapshot,
        *,
        updated_at: str,
    ) -> SupervisorRuntimeCheckpoint:
        if not isinstance(checkpoint, SupervisorRuntimeCheckpoint):
            raise AuthorityValidationError(
                "checkpoint must be SupervisorRuntimeCheckpoint"
            )
        if not isinstance(snapshot, SupervisorServiceSnapshot):
            raise AuthorityValidationError(
                "snapshot must be SupervisorServiceSnapshot"
            )
        if snapshot.service_id != checkpoint.service_id:
            raise AuthorityValidationError(
                "snapshot service_id mismatch"
            )
        if snapshot.state is SupervisorServiceState.CREATED:
            raise AuthorityValidationError(
                "CREATED state is not persisted after begin_run"
            )
        timestamp = _canonical_utc(updated_at, "updated_at")

        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT * FROM supervisor_runtime_checkpoint
                WHERE service_id = ?
                """,
                (checkpoint.service_id,),
            ).fetchone()
            if row is None:
                raise AuthorityValidationError(
                    "supervisor runtime checkpoint missing"
                )
            current = self._row(row)
            if (
                current.generation != checkpoint.generation
                or current.owner_id != checkpoint.owner_id
                or current.fencing_token != checkpoint.fencing_token
            ):
                raise AuthorityValidationError(
                    "stale supervisor runtime checkpoint"
                )
            allowed = _ALLOWED_TRANSITIONS.get(current.state, set())
            if snapshot.state not in allowed:
                raise AuthorityValidationError(
                    "invalid persisted supervisor state transition"
                )

            connection.execute(
                """
                UPDATE supervisor_runtime_checkpoint
                SET state = ?, stop_reason = ?, updated_at = ?
                WHERE service_id = ?
                """,
                (
                    snapshot.state.value,
                    (
                        None
                        if snapshot.stop_reason is None
                        else snapshot.stop_reason.value
                    ),
                    timestamp,
                    checkpoint.service_id,
                ),
            )

        result = self.get(checkpoint.service_id)
        assert result is not None
        return result

    def manifest(self) -> dict[str, object]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM supervisor_runtime_checkpoint
                ORDER BY service_id
                """
            ).fetchall()
        checkpoints = [self._row(row) for row in rows]
        return {
            "schema": SUPERVISOR_RUNTIME_CHECKPOINT_SCHEMA_VERSION,
            "checkpoint_count": len(checkpoints),
            "checkpoints": [
                {
                    "service_id": cp.service_id,
                    "generation": cp.generation,
                    "owner_id": cp.owner_id,
                    "fencing_token": cp.fencing_token,
                    "state": cp.state.value,
                    "stop_reason": (
                        None
                        if cp.stop_reason is None
                        else cp.stop_reason.value
                    ),
                    "updated_at": cp.updated_at,
                }
                for cp in checkpoints
            ],
        }
