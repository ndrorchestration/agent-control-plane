"""Persisted deterministic cadence for caller-driven ACP process monitoring."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sqlite3
from typing import Optional

from .authority import AuthorityValidationError
from .process_monitor import ProcessMonitorTick, ProcessMonitorTickResult


PROCESS_MONITOR_CADENCE_SCHEMA_VERSION = (
    "agent-control-plane.process-monitor-cadence.v0-candidate"
)


def _utc(value: str, field_name: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise AuthorityValidationError(f"{field_name} must not be blank")
    candidate = value[:-1] + "+00:00" if value.endswith("Z") else value
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


@dataclass(frozen=True)
class ProcessMonitorCadenceState:
    process_id: str
    last_tick_at: Optional[str]
    schema_version: str = PROCESS_MONITOR_CADENCE_SCHEMA_VERSION


class DurableProcessMonitorCadenceStore:
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
                CREATE TABLE IF NOT EXISTS process_monitor_cadence (
                    process_id TEXT PRIMARY KEY,
                    last_tick_at TEXT,
                    schema_version TEXT NOT NULL
                )
                """
            )

    def get(self, process_id: str) -> ProcessMonitorCadenceState:
        if not isinstance(process_id, str) or not process_id.strip():
            raise AuthorityValidationError("process_id must not be blank")
        identifier = process_id.strip()
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM process_monitor_cadence WHERE process_id = ?",
                (identifier,),
            ).fetchone()
        if row is None:
            return ProcessMonitorCadenceState(
                process_id=identifier,
                last_tick_at=None,
            )
        return ProcessMonitorCadenceState(
            process_id=row["process_id"],
            last_tick_at=row["last_tick_at"],
            schema_version=row["schema_version"],
        )

    def record_tick(
        self,
        *,
        process_id: str,
        ticked_at: str,
    ) -> ProcessMonitorCadenceState:
        identifier = process_id.strip()
        canonical = _canonical(ticked_at, "ticked_at")
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO process_monitor_cadence (
                    process_id,
                    last_tick_at,
                    schema_version
                ) VALUES (?, ?, ?)
                ON CONFLICT(process_id) DO UPDATE SET
                    last_tick_at = excluded.last_tick_at,
                    schema_version = excluded.schema_version
                """,
                (
                    identifier,
                    canonical,
                    PROCESS_MONITOR_CADENCE_SCHEMA_VERSION,
                ),
            )
        return self.get(identifier)


@dataclass(frozen=True)
class ProcessMonitorCadencePolicy:
    min_interval_seconds: float = 5.0

    def __post_init__(self) -> None:
        if (
            isinstance(self.min_interval_seconds, bool)
            or not isinstance(self.min_interval_seconds, (int, float))
            or self.min_interval_seconds <= 0
        ):
            raise AuthorityValidationError(
                "min_interval_seconds must be > 0"
            )

    def due(
        self,
        state: ProcessMonitorCadenceState,
        *,
        now: str,
    ) -> bool:
        current = _utc(now, "now")
        if state.last_tick_at is None:
            return True
        last = _utc(state.last_tick_at, "last_tick_at")
        return (current - last).total_seconds() >= self.min_interval_seconds

    def next_due_at(
        self,
        state: ProcessMonitorCadenceState,
    ) -> Optional[str]:
        if state.last_tick_at is None:
            return None
        due = _utc(state.last_tick_at, "last_tick_at") + timedelta(
            seconds=self.min_interval_seconds
        )
        return due.isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class ScheduledProcessMonitorResult:
    ran: bool
    next_due_at: Optional[str]
    tick_result: Optional[ProcessMonitorTickResult]


class ScheduledProcessMonitor:
    """Run the accepted monitor tick only when persisted cadence says due."""

    def __init__(
        self,
        *,
        monitor_tick: ProcessMonitorTick,
        cadence_store: DurableProcessMonitorCadenceStore,
        cadence_policy: ProcessMonitorCadencePolicy,
    ) -> None:
        if not isinstance(monitor_tick, ProcessMonitorTick):
            raise AuthorityValidationError(
                "monitor_tick must be ProcessMonitorTick"
            )
        if not isinstance(
            cadence_store,
            DurableProcessMonitorCadenceStore,
        ):
            raise AuthorityValidationError(
                "cadence_store must be DurableProcessMonitorCadenceStore"
            )
        if not isinstance(cadence_policy, ProcessMonitorCadencePolicy):
            raise AuthorityValidationError(
                "cadence_policy must be ProcessMonitorCadencePolicy"
            )
        self.monitor_tick = monitor_tick
        self.cadence_store = cadence_store
        self.cadence_policy = cadence_policy

    def run_if_due(
        self,
        *,
        now: str,
        timeout_seconds: float = 5.0,
    ) -> ScheduledProcessMonitorResult:
        process_id = self.monitor_tick.controller.spec.process_id
        state = self.cadence_store.get(process_id)
        if not self.cadence_policy.due(state, now=now):
            return ScheduledProcessMonitorResult(
                ran=False,
                next_due_at=self.cadence_policy.next_due_at(state),
                tick_result=None,
            )

        tick_result = self.monitor_tick.run(
            now=now,
            timeout_seconds=timeout_seconds,
        )
        new_state = self.cadence_store.record_tick(
            process_id=process_id,
            ticked_at=now,
        )
        return ScheduledProcessMonitorResult(
            ran=True,
            next_due_at=self.cadence_policy.next_due_at(new_state),
            tick_result=tick_result,
        )
