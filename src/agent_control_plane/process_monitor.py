"""Durable process-failure state and one-shot monitoring for ACP supervision."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import sqlite3
from typing import Optional

from .authority import AuthorityValidationError
from .process_runtime import ManagedProcessController, ProcessObservation
from .process_supervision import (
    ProcessFailureState,
    ProcessSupervisionDecision,
    ProcessSupervisionPolicy,
)


PROCESS_FAILURE_STORE_SCHEMA_VERSION = (
    "agent-control-plane.process-failure-store.v0-candidate"
)


def _required(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise AuthorityValidationError(f"{field_name} must not be blank")
    return value.strip()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class PersistedProcessFailure:
    process_id: str
    failure_count: int
    last_failure_at: str
    last_restart_at: Optional[str]
    schema_version: str = PROCESS_FAILURE_STORE_SCHEMA_VERSION


class DurableProcessFailureStore:
    """SQLite-backed durable crash/restart counters for one or more process IDs."""

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
                CREATE TABLE IF NOT EXISTS process_failure_state (
                    process_id TEXT PRIMARY KEY,
                    failure_count INTEGER NOT NULL,
                    last_failure_at TEXT NOT NULL,
                    last_restart_at TEXT,
                    schema_version TEXT NOT NULL
                )
                """
            )

    def get(self, process_id: str) -> Optional[PersistedProcessFailure]:
        identifier = _required(process_id, "process_id")
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM process_failure_state WHERE process_id = ?",
                (identifier,),
            ).fetchone()
        if row is None:
            return None
        return PersistedProcessFailure(
            process_id=row["process_id"],
            failure_count=row["failure_count"],
            last_failure_at=row["last_failure_at"],
            last_restart_at=row["last_restart_at"],
            schema_version=row["schema_version"],
        )

    def record_failure(
        self,
        *,
        process_id: str,
        failed_at: Optional[str] = None,
    ) -> PersistedProcessFailure:
        identifier = _required(process_id, "process_id")
        when = failed_at or _utc_now()
        prior = self.get(identifier)
        count = 1 if prior is None else prior.failure_count + 1
        restart_at = None if prior is None else prior.last_restart_at
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO process_failure_state (
                    process_id,
                    failure_count,
                    last_failure_at,
                    last_restart_at,
                    schema_version
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(process_id) DO UPDATE SET
                    failure_count = excluded.failure_count,
                    last_failure_at = excluded.last_failure_at,
                    last_restart_at = excluded.last_restart_at,
                    schema_version = excluded.schema_version
                """,
                (
                    identifier,
                    count,
                    when,
                    restart_at,
                    PROCESS_FAILURE_STORE_SCHEMA_VERSION,
                ),
            )
        return self.get(identifier)  # type: ignore[return-value]

    def record_restart(
        self,
        *,
        process_id: str,
        restarted_at: Optional[str] = None,
    ) -> PersistedProcessFailure:
        identifier = _required(process_id, "process_id")
        prior = self.get(identifier)
        if prior is None:
            raise AuthorityValidationError(
                "cannot record restart without prior failure state"
            )
        when = restarted_at or _utc_now()
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE process_failure_state
                SET last_restart_at = ?
                WHERE process_id = ?
                """,
                (when, identifier),
            )
        return self.get(identifier)  # type: ignore[return-value]

    def clear(self, process_id: str) -> None:
        identifier = _required(process_id, "process_id")
        with self._connect() as connection:
            connection.execute(
                "DELETE FROM process_failure_state WHERE process_id = ?",
                (identifier,),
            )


@dataclass(frozen=True)
class ProcessMonitorTickResult:
    observation_before: ProcessObservation
    decision: Optional[ProcessSupervisionDecision]
    observation_after: ProcessObservation
    failure_state: Optional[PersistedProcessFailure]


class ProcessMonitorTick:
    """One explicit crash-detection/supervision decision tick."""

    def __init__(
        self,
        *,
        controller: ManagedProcessController,
        policy: ProcessSupervisionPolicy,
        failure_store: DurableProcessFailureStore,
    ) -> None:
        if not isinstance(controller, ManagedProcessController):
            raise AuthorityValidationError(
                "controller must be ManagedProcessController"
            )
        if not isinstance(policy, ProcessSupervisionPolicy):
            raise AuthorityValidationError(
                "policy must be ProcessSupervisionPolicy"
            )
        if not isinstance(failure_store, DurableProcessFailureStore):
            raise AuthorityValidationError(
                "failure_store must be DurableProcessFailureStore"
            )
        self.controller = controller
        self.policy = policy
        self.failure_store = failure_store

    def run(
        self,
        *,
        now: str,
        timeout_seconds: float = 5.0,
    ) -> ProcessMonitorTickResult:
        before = self.controller.observe()
        if before.running:
            return ProcessMonitorTickResult(
                observation_before=before,
                decision=None,
                observation_after=before,
                failure_state=self.failure_store.get(before.process_id),
            )

        # A process that has never been started has no return code and should
        # not be interpreted as a crash by a monitor tick.
        if before.pid is None and before.returncode is None:
            return ProcessMonitorTickResult(
                observation_before=before,
                decision=None,
                observation_after=before,
                failure_state=self.failure_store.get(before.process_id),
            )

        persisted = self.failure_store.record_failure(
            process_id=before.process_id,
            failed_at=now,
        )
        state = ProcessFailureState(
            process_id=persisted.process_id,
            failure_count=persisted.failure_count,
            last_failure_at=persisted.last_failure_at,
            last_restart_at=persisted.last_restart_at,
        )
        decision = self.policy.decide(state, now=now)

        if decision is ProcessSupervisionDecision.RESTART:
            after = self.controller.restart(
                timeout_seconds=timeout_seconds
            )
            persisted = self.failure_store.record_restart(
                process_id=before.process_id,
                restarted_at=now,
            )
        elif decision is ProcessSupervisionDecision.HOLD:
            after = self.controller.observe()
        else:
            after = self.controller.terminate(
                timeout_seconds=timeout_seconds
            )

        return ProcessMonitorTickResult(
            observation_before=before,
            decision=decision,
            observation_after=after,
            failure_state=persisted,
        )
