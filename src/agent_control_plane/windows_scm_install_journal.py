"""Durable append-only journal for Windows SCM installation mutations."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
import sqlite3
from typing import Optional

from .authority import AuthorityValidationError
from .windows_scm_install_authorization import WindowsScmInstallationTarget


WINDOWS_SCM_INSTALL_JOURNAL_SCHEMA_VERSION = (
    "agent-control-plane.windows-scm-install-journal.v0-candidate"
)


class WindowsScmInstallJournalEvent(str, Enum):
    AUTHORIZATION_CONSUMED = "authorization_consumed"
    SCM_OPEN_INTENT = "scm_open_intent"
    SCM_OPENED = "scm_opened"
    CREATE_SERVICE_INTENT = "create_service_intent"
    SERVICE_CREATED = "service_created"
    DELAYED_AUTO_START_INTENT = "delayed_auto_start_intent"
    DELAYED_AUTO_START_CONFIGURED = "delayed_auto_start_configured"
    ROLLBACK_DELETE_INTENT = "rollback_delete_intent"
    ROLLBACK_DELETE_COMPLETE = "rollback_delete_complete"
    ROLLBACK_DELETE_FAILED = "rollback_delete_failed"
    INSTALL_COMMITTED = "install_committed"


class WindowsScmInstallRecoveryState(str, Enum):
    PRE_CREATE = "pre_create"
    CREATE_OUTCOME_AMBIGUOUS = "create_outcome_ambiguous"
    SERVICE_EXISTS_UNCOMMITTED = "service_exists_uncommitted"
    ROLLBACK_OUTCOME_AMBIGUOUS = "rollback_outcome_ambiguous"
    ROLLED_BACK = "rolled_back"
    COMMITTED = "committed"


@dataclass(frozen=True)
class WindowsScmInstallJournalRecord:
    authorization_id: str
    sequence: int
    service_name: str
    manifest_sha256: str
    binary_sha256: str
    registration_plan_sha256: str
    event: WindowsScmInstallJournalEvent
    recorded_at: str
    detail: Optional[str]
    schema_version: str = WINDOWS_SCM_INSTALL_JOURNAL_SCHEMA_VERSION


class DurableWindowsScmInstallJournal:
    """SQLite-backed append-only mutation journal keyed by authorization ID."""

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
                CREATE TABLE IF NOT EXISTS windows_scm_install_journal (
                    authorization_id TEXT NOT NULL,
                    sequence INTEGER NOT NULL,
                    service_name TEXT NOT NULL,
                    manifest_sha256 TEXT NOT NULL,
                    binary_sha256 TEXT NOT NULL,
                    registration_plan_sha256 TEXT NOT NULL,
                    event TEXT NOT NULL,
                    recorded_at TEXT NOT NULL,
                    detail TEXT,
                    schema_version TEXT NOT NULL,
                    PRIMARY KEY (authorization_id, sequence)
                )
                """
            )

    def append(
        self,
        *,
        authorization_id: str,
        target: WindowsScmInstallationTarget,
        event: WindowsScmInstallJournalEvent,
        recorded_at: str,
        detail: Optional[str] = None,
    ) -> WindowsScmInstallJournalRecord:
        if not isinstance(authorization_id, str) or not authorization_id.strip():
            raise AuthorityValidationError("authorization_id must not be blank")
        if not isinstance(target, WindowsScmInstallationTarget):
            raise AuthorityValidationError(
                "target must be WindowsScmInstallationTarget"
            )
        if not isinstance(event, WindowsScmInstallJournalEvent):
            raise AuthorityValidationError(
                "event must be WindowsScmInstallJournalEvent"
            )
        if not isinstance(recorded_at, str) or not recorded_at.strip():
            raise AuthorityValidationError("recorded_at must not be blank")
        if detail is not None and not isinstance(detail, str):
            raise AuthorityValidationError("detail must be str or None")

        identifier = authorization_id.strip()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            prior_target = connection.execute(
                """
                SELECT service_name, manifest_sha256, binary_sha256,
                       registration_plan_sha256
                FROM windows_scm_install_journal
                WHERE authorization_id = ?
                ORDER BY sequence
                LIMIT 1
                """,
                (identifier,),
            ).fetchone()
            expected = (
                target.service_name,
                target.manifest_sha256,
                target.binary_sha256,
                target.registration_plan_sha256,
            )
            if prior_target is not None:
                actual = (
                    prior_target["service_name"],
                    prior_target["manifest_sha256"],
                    prior_target["binary_sha256"],
                    prior_target["registration_plan_sha256"],
                )
                if actual != expected:
                    raise AuthorityValidationError(
                        "install journal target conflict"
                    )

            row = connection.execute(
                """
                SELECT COALESCE(MAX(sequence), 0) AS max_sequence
                FROM windows_scm_install_journal
                WHERE authorization_id = ?
                """,
                (identifier,),
            ).fetchone()
            sequence = int(row["max_sequence"]) + 1
            connection.execute(
                """
                INSERT INTO windows_scm_install_journal (
                    authorization_id, sequence, service_name,
                    manifest_sha256, binary_sha256,
                    registration_plan_sha256, event, recorded_at,
                    detail, schema_version
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    identifier,
                    sequence,
                    target.service_name,
                    target.manifest_sha256,
                    target.binary_sha256,
                    target.registration_plan_sha256,
                    event.value,
                    recorded_at,
                    detail,
                    WINDOWS_SCM_INSTALL_JOURNAL_SCHEMA_VERSION,
                ),
            )
        return self.records(identifier)[-1]

    def records(
        self,
        authorization_id: str,
    ) -> tuple[WindowsScmInstallJournalRecord, ...]:
        if not isinstance(authorization_id, str) or not authorization_id.strip():
            raise AuthorityValidationError("authorization_id must not be blank")
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM windows_scm_install_journal
                WHERE authorization_id = ?
                ORDER BY sequence
                """,
                (authorization_id.strip(),),
            ).fetchall()
        return tuple(
            WindowsScmInstallJournalRecord(
                authorization_id=row["authorization_id"],
                sequence=row["sequence"],
                service_name=row["service_name"],
                manifest_sha256=row["manifest_sha256"],
                binary_sha256=row["binary_sha256"],
                registration_plan_sha256=row["registration_plan_sha256"],
                event=WindowsScmInstallJournalEvent(row["event"]),
                recorded_at=row["recorded_at"],
                detail=row["detail"],
                schema_version=row["schema_version"],
            )
            for row in rows
        )

    def recovery_state(
        self,
        authorization_id: str,
    ) -> WindowsScmInstallRecoveryState:
        events = [record.event for record in self.records(authorization_id)]
        if WindowsScmInstallJournalEvent.INSTALL_COMMITTED in events:
            return WindowsScmInstallRecoveryState.COMMITTED
        if WindowsScmInstallJournalEvent.ROLLBACK_DELETE_COMPLETE in events:
            return WindowsScmInstallRecoveryState.ROLLED_BACK
        if (
            WindowsScmInstallJournalEvent.ROLLBACK_DELETE_INTENT in events
            and WindowsScmInstallJournalEvent.ROLLBACK_DELETE_COMPLETE
            not in events
        ):
            return WindowsScmInstallRecoveryState.ROLLBACK_OUTCOME_AMBIGUOUS
        if WindowsScmInstallJournalEvent.SERVICE_CREATED in events:
            return WindowsScmInstallRecoveryState.SERVICE_EXISTS_UNCOMMITTED
        if (
            WindowsScmInstallJournalEvent.CREATE_SERVICE_INTENT in events
            and WindowsScmInstallJournalEvent.SERVICE_CREATED not in events
        ):
            return WindowsScmInstallRecoveryState.CREATE_OUTCOME_AMBIGUOUS
        return WindowsScmInstallRecoveryState.PRE_CREATE
