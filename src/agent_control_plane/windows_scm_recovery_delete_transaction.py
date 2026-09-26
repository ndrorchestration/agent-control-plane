"""Authorized crash-safe deletion transaction for Windows SCM install recovery."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
import sqlite3
from typing import Protocol, runtime_checkable

from .authority import AuthorityValidationError
from .windows_scm_install_journal import WindowsScmInstallationJournal
from .windows_scm_recovery_authorization import (
    WindowsScmRecoveryAction,
    WindowsScmRecoveryAuthorizationStore,
    WindowsScmRecoveryTarget,
    build_windows_scm_recovery_target,
)
from .windows_scm_recovery_inspector import WindowsScmInstallRecoveryInspector
from .windows_scm_registration_plan import WindowsScmServiceRegistrationPlan


WINDOWS_SCM_RECOVERY_JOURNAL_SCHEMA_VERSION = (
    "agent-control-plane.windows-scm-recovery-journal.v0-candidate"
)


class WindowsScmRecoveryJournalState(str, Enum):
    PREPARED = "prepared"
    AUTHORIZATION_CONSUMED = "authorization_consumed"
    DELETE_INTENT_RECORDED = "delete_intent_recorded"
    DELETED = "deleted"
    DELETE_FAILED = "delete_failed"


_RECOVERY_TERMINAL = {
    WindowsScmRecoveryJournalState.DELETED,
    WindowsScmRecoveryJournalState.DELETE_FAILED,
}

_RECOVERY_TRANSITIONS = {
    WindowsScmRecoveryJournalState.PREPARED: {
        WindowsScmRecoveryJournalState.AUTHORIZATION_CONSUMED,
    },
    WindowsScmRecoveryJournalState.AUTHORIZATION_CONSUMED: {
        WindowsScmRecoveryJournalState.DELETE_INTENT_RECORDED,
    },
    WindowsScmRecoveryJournalState.DELETE_INTENT_RECORDED: {
        WindowsScmRecoveryJournalState.DELETED,
        WindowsScmRecoveryJournalState.DELETE_FAILED,
    },
}


@dataclass(frozen=True)
class WindowsScmRecoveryJournalEvent:
    recovery_transaction_id: str
    event_index: int
    state: WindowsScmRecoveryJournalState
    occurred_at: str
    error: str | None = None


@dataclass(frozen=True)
class WindowsScmRecoveryJournalRecord:
    recovery_transaction_id: str
    install_transaction_id: str
    authorization_id: str
    service_name: str
    live_config_sha256: str
    action: str
    events: tuple[WindowsScmRecoveryJournalEvent, ...]
    schema_version: str = WINDOWS_SCM_RECOVERY_JOURNAL_SCHEMA_VERSION

    @property
    def current_state(self) -> WindowsScmRecoveryJournalState:
        return self.events[-1].state


class WindowsScmRecoveryJournal:
    """SQLite-backed immutable recovery transaction history."""

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
                CREATE TABLE IF NOT EXISTS windows_scm_recovery_transaction (
                    recovery_transaction_id TEXT PRIMARY KEY,
                    install_transaction_id TEXT NOT NULL,
                    authorization_id TEXT NOT NULL,
                    service_name TEXT NOT NULL,
                    live_config_sha256 TEXT NOT NULL,
                    action TEXT NOT NULL,
                    schema_version TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS windows_scm_recovery_event (
                    recovery_transaction_id TEXT NOT NULL,
                    event_index INTEGER NOT NULL,
                    state TEXT NOT NULL,
                    occurred_at TEXT NOT NULL,
                    error TEXT,
                    PRIMARY KEY (recovery_transaction_id, event_index)
                )
                """
            )

    def begin(
        self,
        *,
        recovery_transaction_id: str,
        authorization_id: str,
        target: WindowsScmRecoveryTarget,
        occurred_at: str,
    ) -> WindowsScmRecoveryJournalRecord:
        if not isinstance(recovery_transaction_id, str) or not recovery_transaction_id.strip():
            raise AuthorityValidationError(
                "recovery_transaction_id must not be blank"
            )
        if not isinstance(authorization_id, str) or not authorization_id.strip():
            raise AuthorityValidationError(
                "authorization_id must not be blank"
            )
        if not isinstance(target, WindowsScmRecoveryTarget):
            raise AuthorityValidationError(
                "target must be WindowsScmRecoveryTarget"
            )
        identifier = recovery_transaction_id.strip()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                """
                SELECT * FROM windows_scm_recovery_transaction
                WHERE recovery_transaction_id = ?
                """,
                (identifier,),
            ).fetchone()
            if existing is not None:
                record = self.get(identifier)
                assert record is not None
                expected = (
                    target.transaction_id,
                    authorization_id.strip(),
                    target.service_name,
                    target.live_config_sha256,
                    target.action.value,
                )
                actual = (
                    record.install_transaction_id,
                    record.authorization_id,
                    record.service_name,
                    record.live_config_sha256,
                    record.action,
                )
                if actual != expected:
                    raise AuthorityValidationError(
                        "recovery journal transaction_id conflict"
                    )
                return record

            connection.execute(
                """
                INSERT INTO windows_scm_recovery_transaction (
                    recovery_transaction_id, install_transaction_id,
                    authorization_id, service_name, live_config_sha256,
                    action, schema_version
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    identifier,
                    target.transaction_id,
                    authorization_id.strip(),
                    target.service_name,
                    target.live_config_sha256,
                    target.action.value,
                    WINDOWS_SCM_RECOVERY_JOURNAL_SCHEMA_VERSION,
                ),
            )
            connection.execute(
                """
                INSERT INTO windows_scm_recovery_event (
                    recovery_transaction_id, event_index, state,
                    occurred_at, error
                ) VALUES (?, 0, ?, ?, NULL)
                """,
                (
                    identifier,
                    WindowsScmRecoveryJournalState.PREPARED.value,
                    occurred_at,
                ),
            )
        result = self.get(identifier)
        assert result is not None
        return result

    def append(
        self,
        recovery_transaction_id: str,
        *,
        state: WindowsScmRecoveryJournalState,
        occurred_at: str,
        error: str | None = None,
    ) -> WindowsScmRecoveryJournalRecord:
        if not isinstance(state, WindowsScmRecoveryJournalState):
            raise AuthorityValidationError(
                "state must be WindowsScmRecoveryJournalState"
            )
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT * FROM windows_scm_recovery_event
                WHERE recovery_transaction_id = ?
                ORDER BY event_index DESC LIMIT 1
                """,
                (recovery_transaction_id,),
            ).fetchone()
            if row is None:
                raise AuthorityValidationError(
                    "recovery journal transaction not found"
                )
            current = WindowsScmRecoveryJournalState(row["state"])
            if current in _RECOVERY_TERMINAL:
                raise AuthorityValidationError(
                    "recovery journal transaction is terminal"
                )
            if state not in _RECOVERY_TRANSITIONS.get(current, set()):
                raise AuthorityValidationError(
                    f"invalid recovery journal transition: "
                    f"{current.value} -> {state.value}"
                )
            index = int(row["event_index"]) + 1
            connection.execute(
                """
                INSERT INTO windows_scm_recovery_event (
                    recovery_transaction_id, event_index, state,
                    occurred_at, error
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    recovery_transaction_id,
                    index,
                    state.value,
                    occurred_at,
                    error,
                ),
            )
        result = self.get(recovery_transaction_id)
        assert result is not None
        return result

    def get(
        self,
        recovery_transaction_id: str,
    ) -> WindowsScmRecoveryJournalRecord | None:
        with self._connect() as connection:
            tx = connection.execute(
                """
                SELECT * FROM windows_scm_recovery_transaction
                WHERE recovery_transaction_id = ?
                """,
                (recovery_transaction_id,),
            ).fetchone()
            if tx is None:
                return None
            rows = connection.execute(
                """
                SELECT * FROM windows_scm_recovery_event
                WHERE recovery_transaction_id = ?
                ORDER BY event_index
                """,
                (recovery_transaction_id,),
            ).fetchall()
        events = tuple(
            WindowsScmRecoveryJournalEvent(
                recovery_transaction_id=row["recovery_transaction_id"],
                event_index=row["event_index"],
                state=WindowsScmRecoveryJournalState(row["state"]),
                occurred_at=row["occurred_at"],
                error=row["error"],
            )
            for row in rows
        )
        return WindowsScmRecoveryJournalRecord(
            recovery_transaction_id=tx["recovery_transaction_id"],
            install_transaction_id=tx["install_transaction_id"],
            authorization_id=tx["authorization_id"],
            service_name=tx["service_name"],
            live_config_sha256=tx["live_config_sha256"],
            action=tx["action"],
            events=events,
            schema_version=tx["schema_version"],
        )


@runtime_checkable
class WindowsScmRecoveryDeleteBackend(Protocol):
    def open_scm(self): ...
    def open_service_for_delete(self, scm_handle, service_name: str): ...
    def delete_service(self, service_handle) -> None: ...
    def close_handle(self, handle) -> None: ...


@dataclass(frozen=True)
class WindowsScmRecoveryDeleteResult:
    recovery_transaction_id: str
    authorization_id: str
    install_transaction_id: str
    service_name: str
    deleted: bool


class WindowsScmRecoveryDeleteTransactionError(RuntimeError):
    pass


class WindowsScmRecoveryDeleteTransaction:
    """Re-inspect, authorize, journal, and delete one exact recovered service."""

    def __init__(
        self,
        *,
        install_journal: WindowsScmInstallationJournal,
        recovery_journal: WindowsScmRecoveryJournal,
        authorization_store: WindowsScmRecoveryAuthorizationStore,
        inspector: WindowsScmInstallRecoveryInspector,
        backend: WindowsScmRecoveryDeleteBackend,
    ) -> None:
        if not isinstance(install_journal, WindowsScmInstallationJournal):
            raise AuthorityValidationError(
                "install_journal must be WindowsScmInstallationJournal"
            )
        if not isinstance(recovery_journal, WindowsScmRecoveryJournal):
            raise AuthorityValidationError(
                "recovery_journal must be WindowsScmRecoveryJournal"
            )
        if not isinstance(
            authorization_store,
            WindowsScmRecoveryAuthorizationStore,
        ):
            raise AuthorityValidationError(
                "authorization_store must be WindowsScmRecoveryAuthorizationStore"
            )
        if not isinstance(inspector, WindowsScmInstallRecoveryInspector):
            raise AuthorityValidationError(
                "inspector must be WindowsScmInstallRecoveryInspector"
            )
        if not isinstance(backend, WindowsScmRecoveryDeleteBackend):
            raise AuthorityValidationError(
                "backend must implement WindowsScmRecoveryDeleteBackend"
            )
        self.install_journal = install_journal
        self.recovery_journal = recovery_journal
        self.authorization_store = authorization_store
        self.inspector = inspector
        self.backend = backend

    def delete(
        self,
        *,
        recovery_transaction_id: str,
        authorization_id: str,
        install_transaction_id: str,
        plan: WindowsScmServiceRegistrationPlan,
        now: str,
    ) -> WindowsScmRecoveryDeleteResult:
        record = self.install_journal.get(install_transaction_id)
        if record is None:
            raise AuthorityValidationError(
                "installation journal transaction not found"
            )
        assessment = self.install_journal.assess_recovery(
            install_transaction_id
        )
        inspection = self.inspector.inspect(
            assessment=assessment,
            plan=plan,
        )
        target = build_windows_scm_recovery_target(
            journal_record=record,
            assessment=assessment,
            inspection=inspection,
            action=WindowsScmRecoveryAction.DELETE_EXACT_SERVICE,
        )

        self.recovery_journal.begin(
            recovery_transaction_id=recovery_transaction_id,
            authorization_id=authorization_id,
            target=target,
            occurred_at=now,
        )

        self.authorization_store.consume(
            authorization_id,
            target=target,
            now=now,
        )
        self.recovery_journal.append(
            recovery_transaction_id,
            state=WindowsScmRecoveryJournalState.AUTHORIZATION_CONSUMED,
            occurred_at=now,
        )
        self.recovery_journal.append(
            recovery_transaction_id,
            state=WindowsScmRecoveryJournalState.DELETE_INTENT_RECORDED,
            occurred_at=now,
        )

        scm_handle = None
        service_handle = None
        try:
            scm_handle = self.backend.open_scm()
            service_handle = self.backend.open_service_for_delete(
                scm_handle,
                target.service_name,
            )
            self.backend.delete_service(service_handle)
            self.recovery_journal.append(
                recovery_transaction_id,
                state=WindowsScmRecoveryJournalState.DELETED,
                occurred_at=now,
            )
            return WindowsScmRecoveryDeleteResult(
                recovery_transaction_id=recovery_transaction_id,
                authorization_id=authorization_id,
                install_transaction_id=install_transaction_id,
                service_name=target.service_name,
                deleted=True,
            )
        except Exception as exc:
            self.recovery_journal.append(
                recovery_transaction_id,
                state=WindowsScmRecoveryJournalState.DELETE_FAILED,
                occurred_at=now,
                error=f"{type(exc).__name__}: {exc}",
            )
            raise WindowsScmRecoveryDeleteTransactionError(
                f"{type(exc).__name__}: {exc}"
            ) from exc
        finally:
            if service_handle is not None:
                self.backend.close_handle(service_handle)
            if scm_handle is not None:
                self.backend.close_handle(scm_handle)
