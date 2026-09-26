"""Append-only crash-recovery journal for Windows service installation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
import sqlite3
from typing import Optional

from .authority import AuthorityValidationError
from .windows_scm_install_authorization import WindowsScmInstallationTarget


WINDOWS_SCM_INSTALL_JOURNAL_SCHEMA_VERSION = (
    "agent-control-plane.windows-scm-install-journal.v0-candidate"
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


class WindowsScmInstallJournalState(str, Enum):
    PREPARED = "prepared"
    AUTHORIZATION_CONSUMED = "authorization_consumed"
    SCM_OPENED = "scm_opened"
    SERVICE_CREATED = "service_created"
    DELAYED_AUTO_START_CONFIGURED = "delayed_auto_start_configured"
    COMPLETED = "completed"
    FAILED = "failed"
    ROLLED_BACK = "rolled_back"
    ROLLBACK_FAILED = "rollback_failed"


_TERMINAL_STATES = {
    WindowsScmInstallJournalState.COMPLETED,
    WindowsScmInstallJournalState.FAILED,
    WindowsScmInstallJournalState.ROLLED_BACK,
    WindowsScmInstallJournalState.ROLLBACK_FAILED,
}

_ALLOWED_TRANSITIONS = {
    WindowsScmInstallJournalState.PREPARED: {
        WindowsScmInstallJournalState.AUTHORIZATION_CONSUMED,
        WindowsScmInstallJournalState.FAILED,
    },
    WindowsScmInstallJournalState.AUTHORIZATION_CONSUMED: {
        WindowsScmInstallJournalState.SCM_OPENED,
        WindowsScmInstallJournalState.FAILED,
    },
    WindowsScmInstallJournalState.SCM_OPENED: {
        WindowsScmInstallJournalState.SERVICE_CREATED,
        WindowsScmInstallJournalState.FAILED,
    },
    WindowsScmInstallJournalState.SERVICE_CREATED: {
        WindowsScmInstallJournalState.DELAYED_AUTO_START_CONFIGURED,
        WindowsScmInstallJournalState.COMPLETED,
        WindowsScmInstallJournalState.ROLLED_BACK,
        WindowsScmInstallJournalState.ROLLBACK_FAILED,
    },
    WindowsScmInstallJournalState.DELAYED_AUTO_START_CONFIGURED: {
        WindowsScmInstallJournalState.COMPLETED,
    },
}


class WindowsScmInstallRecoveryDisposition(str, Enum):
    SAFE_PRE_MUTATION = "safe_pre_mutation"
    NO_SERVICE_MUTATION_NEEDS_NEW_AUTH = (
        "no_service_mutation_needs_new_auth"
    )
    HOLD_POSSIBLE_INSTALLED_SERVICE = (
        "hold_possible_installed_service"
    )
    CLEAN_INSTALLED = "clean_installed"
    CLEAN_ROLLED_BACK = "clean_rolled_back"
    HOLD_ROLLBACK_FAILED = "hold_rollback_failed"


@dataclass(frozen=True)
class WindowsScmInstallJournalEvent:
    transaction_id: str
    event_index: int
    state: WindowsScmInstallJournalState
    occurred_at: str
    error: Optional[str] = None


@dataclass(frozen=True)
class WindowsScmInstallJournalRecord:
    transaction_id: str
    authorization_id: str
    service_name: str
    manifest_sha256: str
    binary_sha256: str
    registration_plan_sha256: str
    created_at: str
    events: tuple[WindowsScmInstallJournalEvent, ...]
    schema_version: str = WINDOWS_SCM_INSTALL_JOURNAL_SCHEMA_VERSION

    @property
    def current_state(self) -> WindowsScmInstallJournalState:
        return self.events[-1].state


@dataclass(frozen=True)
class WindowsScmInstallRecoveryAssessment:
    transaction_id: str
    current_state: WindowsScmInstallJournalState
    disposition: WindowsScmInstallRecoveryDisposition
    service_mutation_may_exist: bool


class WindowsScmInstallationJournal:
    """SQLite-backed append-only mutation journal."""

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
                CREATE TABLE IF NOT EXISTS windows_scm_install_transaction (
                    transaction_id TEXT PRIMARY KEY,
                    authorization_id TEXT NOT NULL,
                    service_name TEXT NOT NULL,
                    manifest_sha256 TEXT NOT NULL,
                    binary_sha256 TEXT NOT NULL,
                    registration_plan_sha256 TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    schema_version TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS windows_scm_install_event (
                    transaction_id TEXT NOT NULL,
                    event_index INTEGER NOT NULL,
                    state TEXT NOT NULL,
                    occurred_at TEXT NOT NULL,
                    error TEXT,
                    PRIMARY KEY (transaction_id, event_index),
                    FOREIGN KEY (transaction_id)
                        REFERENCES windows_scm_install_transaction(transaction_id)
                )
                """
            )

    def begin(
        self,
        *,
        transaction_id: str,
        authorization_id: str,
        target: WindowsScmInstallationTarget,
        created_at: str,
    ) -> WindowsScmInstallJournalRecord:
        identifier = _required(transaction_id, "transaction_id")
        auth_id = _required(authorization_id, "authorization_id")
        if not isinstance(target, WindowsScmInstallationTarget):
            raise AuthorityValidationError(
                "target must be WindowsScmInstallationTarget"
            )
        canonical_created = _canonical(created_at, "created_at")

        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                """
                SELECT * FROM windows_scm_install_transaction
                WHERE transaction_id = ?
                """,
                (identifier,),
            ).fetchone()
            if existing is not None:
                record = self.get(identifier)
                assert record is not None
                expected = (
                    auth_id,
                    target.service_name,
                    target.manifest_sha256,
                    target.binary_sha256,
                    target.registration_plan_sha256,
                    canonical_created,
                )
                actual = (
                    record.authorization_id,
                    record.service_name,
                    record.manifest_sha256,
                    record.binary_sha256,
                    record.registration_plan_sha256,
                    record.created_at,
                )
                if actual != expected:
                    raise AuthorityValidationError(
                        "installation journal transaction_id conflict"
                    )
                return record

            connection.execute(
                """
                INSERT INTO windows_scm_install_transaction (
                    transaction_id,
                    authorization_id,
                    service_name,
                    manifest_sha256,
                    binary_sha256,
                    registration_plan_sha256,
                    created_at,
                    schema_version
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    identifier,
                    auth_id,
                    target.service_name,
                    target.manifest_sha256,
                    target.binary_sha256,
                    target.registration_plan_sha256,
                    canonical_created,
                    WINDOWS_SCM_INSTALL_JOURNAL_SCHEMA_VERSION,
                ),
            )
            connection.execute(
                """
                INSERT INTO windows_scm_install_event (
                    transaction_id,
                    event_index,
                    state,
                    occurred_at,
                    error
                ) VALUES (?, 0, ?, ?, NULL)
                """,
                (
                    identifier,
                    WindowsScmInstallJournalState.PREPARED.value,
                    canonical_created,
                ),
            )

        result = self.get(identifier)
        assert result is not None
        return result

    def append(
        self,
        transaction_id: str,
        *,
        state: WindowsScmInstallJournalState,
        occurred_at: str,
        error: Optional[str] = None,
    ) -> WindowsScmInstallJournalRecord:
        identifier = _required(transaction_id, "transaction_id")
        if not isinstance(state, WindowsScmInstallJournalState):
            raise AuthorityValidationError(
                "state must be WindowsScmInstallJournalState"
            )
        canonical_time = _canonical(occurred_at, "occurred_at")
        if error is not None:
            error = _required(error, "error")

        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            tx = connection.execute(
                """
                SELECT * FROM windows_scm_install_transaction
                WHERE transaction_id = ?
                """,
                (identifier,),
            ).fetchone()
            if tx is None:
                raise AuthorityValidationError(
                    "installation journal transaction not found"
                )
            row = connection.execute(
                """
                SELECT * FROM windows_scm_install_event
                WHERE transaction_id = ?
                ORDER BY event_index DESC
                LIMIT 1
                """,
                (identifier,),
            ).fetchone()
            assert row is not None
            current = WindowsScmInstallJournalState(row["state"])
            if current in _TERMINAL_STATES:
                raise AuthorityValidationError(
                    "installation journal transaction is terminal"
                )
            allowed = _ALLOWED_TRANSITIONS.get(current, set())
            if state not in allowed:
                raise AuthorityValidationError(
                    f"invalid installation journal transition: "
                    f"{current.value} -> {state.value}"
                )
            next_index = int(row["event_index"]) + 1
            connection.execute(
                """
                INSERT INTO windows_scm_install_event (
                    transaction_id,
                    event_index,
                    state,
                    occurred_at,
                    error
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    identifier,
                    next_index,
                    state.value,
                    canonical_time,
                    error,
                ),
            )

        result = self.get(identifier)
        assert result is not None
        return result

    def get(
        self,
        transaction_id: str,
    ) -> Optional[WindowsScmInstallJournalRecord]:
        identifier = _required(transaction_id, "transaction_id")
        with self._connect() as connection:
            tx = connection.execute(
                """
                SELECT * FROM windows_scm_install_transaction
                WHERE transaction_id = ?
                """,
                (identifier,),
            ).fetchone()
            if tx is None:
                return None
            rows = connection.execute(
                """
                SELECT * FROM windows_scm_install_event
                WHERE transaction_id = ?
                ORDER BY event_index
                """,
                (identifier,),
            ).fetchall()

        events = tuple(
            WindowsScmInstallJournalEvent(
                transaction_id=row["transaction_id"],
                event_index=row["event_index"],
                state=WindowsScmInstallJournalState(row["state"]),
                occurred_at=row["occurred_at"],
                error=row["error"],
            )
            for row in rows
        )
        if not events:
            raise AuthorityValidationError(
                "installation journal transaction has no events"
            )
        return WindowsScmInstallJournalRecord(
            transaction_id=tx["transaction_id"],
            authorization_id=tx["authorization_id"],
            service_name=tx["service_name"],
            manifest_sha256=tx["manifest_sha256"],
            binary_sha256=tx["binary_sha256"],
            registration_plan_sha256=tx[
                "registration_plan_sha256"
            ],
            created_at=tx["created_at"],
            events=events,
            schema_version=tx["schema_version"],
        )

    def assess_recovery(
        self,
        transaction_id: str,
    ) -> WindowsScmInstallRecoveryAssessment:
        record = self.get(transaction_id)
        if record is None:
            raise AuthorityValidationError(
                "installation journal transaction not found"
            )
        state = record.current_state
        states = {event.state for event in record.events}
        service_created = (
            WindowsScmInstallJournalState.SERVICE_CREATED in states
            or WindowsScmInstallJournalState.DELAYED_AUTO_START_CONFIGURED
            in states
        )

        if state is WindowsScmInstallJournalState.PREPARED:
            disposition = (
                WindowsScmInstallRecoveryDisposition.SAFE_PRE_MUTATION
            )
            may_exist = False
        elif state in (
            WindowsScmInstallJournalState.AUTHORIZATION_CONSUMED,
            WindowsScmInstallJournalState.SCM_OPENED,
        ):
            disposition = (
                WindowsScmInstallRecoveryDisposition
                .NO_SERVICE_MUTATION_NEEDS_NEW_AUTH
            )
            may_exist = False
        elif state is WindowsScmInstallJournalState.COMPLETED:
            disposition = (
                WindowsScmInstallRecoveryDisposition.CLEAN_INSTALLED
            )
            may_exist = True
        elif state is WindowsScmInstallJournalState.ROLLED_BACK:
            disposition = (
                WindowsScmInstallRecoveryDisposition.CLEAN_ROLLED_BACK
            )
            may_exist = False
        elif state is WindowsScmInstallJournalState.ROLLBACK_FAILED:
            disposition = (
                WindowsScmInstallRecoveryDisposition.HOLD_ROLLBACK_FAILED
            )
            may_exist = True
        elif state is WindowsScmInstallJournalState.FAILED:
            if service_created:
                disposition = (
                    WindowsScmInstallRecoveryDisposition
                    .HOLD_POSSIBLE_INSTALLED_SERVICE
                )
                may_exist = True
            else:
                disposition = (
                    WindowsScmInstallRecoveryDisposition
                    .NO_SERVICE_MUTATION_NEEDS_NEW_AUTH
                )
                may_exist = False
        else:
            disposition = (
                WindowsScmInstallRecoveryDisposition
                .HOLD_POSSIBLE_INSTALLED_SERVICE
            )
            may_exist = True

        return WindowsScmInstallRecoveryAssessment(
            transaction_id=record.transaction_id,
            current_state=state,
            disposition=disposition,
            service_mutation_may_exist=may_exist,
        )
